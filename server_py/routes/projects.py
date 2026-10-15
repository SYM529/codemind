"""项目级代码理解接口：ZIP 上传、解析进度、文件清单与项目内检索。

约定与现有接口保持一致：
- 所有接口都需要登录（``Depends(get_current_user)``）；
- 响应统一为 ``{success, ...}`` / ``{success: false, error: {code, message}}``
  （错误结构由 ``http_errors`` 统一兜底）；
- 项目对外只用随机 ``project_id``（32 位十六进制），不暴露自增主键。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import get_current_user
from config import (
    PROJECT_MAX_FILES,
    PROJECT_MAX_PER_USER,
    PROJECT_MAX_SINGLE_FILE_BYTES,
    PROJECT_MAX_ZIP_BYTES,
    PROJECT_QA_MAX_CONTEXT_CHARS,
    PROJECT_QA_MAX_TOP_K,
    PROJECT_QA_RATE_LIMIT,
    PROJECT_QA_RATE_WINDOW_SECONDS,
    PROJECT_UPLOAD_RATE_LIMIT,
    PROJECT_UPLOAD_RATE_WINDOW_SECONDS,
)
from rate_limit import SlidingWindowLimiter
from routes.ai import _estimate_cost, _get_daily_quota
from services import ai_qa_service, project_service, rag_service
from services.usage_service import record_usage

router = APIRouter(prefix="/api/projects", tags=["projects"])

logger = logging.getLogger(__name__)

_upload_limiter = SlidingWindowLimiter(PROJECT_UPLOAD_RATE_LIMIT, PROJECT_UPLOAD_RATE_WINDOW_SECONDS)
_qa_limiter = SlidingWindowLimiter(PROJECT_QA_RATE_LIMIT, PROJECT_QA_RATE_WINDOW_SECONDS)

# 常见 ZIP 起始签名：普通包、空包、跨卷包
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_READ_CHUNK_BYTES = 256 * 1024
_MAX_NAME_LENGTH = 128


class ProjectSearchReq(BaseModel):
    query: str
    topK: int = 4


class AskReq(BaseModel):
    question: str
    topK: int = 4


_MAX_QUESTION_LENGTH = 2000
INSUFFICIENT_ANSWER = (
    "根据当前项目代码无法确定：没有检索到与问题相关的代码片段。"
    "建议改用更具体的函数名、类名或英文关键词提问。"
)


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        content={"success": False, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        404,
        detail={"success": False, "error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}},
    )


def _clean_project_name(raw_name: str, archive_name: str) -> str:
    """项目名优先取表单，其次取压缩包文件名；只保留可打印字符并限长。"""
    name = (raw_name or "").strip()
    if not name:
        name = archive_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if name.lower().endswith(".zip"):
            name = name[:-4]
    name = "".join(char for char in name if char.isprintable()).strip()
    return (name or "未命名项目")[:_MAX_NAME_LENGTH]


@router.post("", status_code=201)
async def upload_project(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(""),
    user=Depends(get_current_user),
):
    """上传 ZIP 项目包，立即返回项目 ID，解析在后台进行（前端轮询详情接口看进度）。"""
    client_ip = request.client.host if request.client else "unknown"
    if not _upload_limiter.allow(client_ip):
        return _error("RATE_LIMITED", "上传过于频繁，请稍后再试", 429)

    if project_service.count_user_projects(user["id"]) >= PROJECT_MAX_PER_USER:
        return _error(
            "PROJECT_LIMIT_REACHED",
            f"项目数量已达上限（{PROJECT_MAX_PER_USER} 个），请先删除不再需要的项目",
            409,
        )

    archive_name = (file.filename or "").strip()
    if not archive_name.lower().endswith(".zip"):
        return _error("INVALID_ARCHIVE_TYPE", "只支持上传 .zip 压缩包", 400)

    public_id = project_service.new_public_id()
    upload_dir = project_service.new_upload_dir(public_id)
    zip_path = upload_dir / project_service.ARCHIVE_FILENAME

    total_bytes = 0
    head = b""
    too_large = False
    try:
        # 流式落盘 + 按实际字节计数：不信任 Content-Length，也不把整个文件读进内存
        with open(zip_path, "wb") as sink:
            while True:
                block = await file.read(_READ_CHUNK_BYTES)
                if not block:
                    break
                if not head:
                    head = block[:4]
                total_bytes += len(block)
                if total_bytes > PROJECT_MAX_ZIP_BYTES:
                    too_large = True
                    break
                sink.write(block)
    except OSError:
        logger.exception("上传文件写入失败 public_id=%s", public_id)
        project_service.discard_upload_dir(upload_dir)
        return _error("UPLOAD_FAILED", "上传写入失败，请稍后重试", 500)
    finally:
        await file.close()

    if too_large:
        project_service.discard_upload_dir(upload_dir)
        return _error(
            "ARCHIVE_TOO_LARGE",
            f"压缩包超过大小上限（{PROJECT_MAX_ZIP_BYTES // (1024 * 1024)} MB）",
            413,
        )
    if total_bytes == 0:
        project_service.discard_upload_dir(upload_dir)
        return _error("EMPTY_ARCHIVE", "上传的压缩包为空", 400)
    if not head.startswith(_ZIP_MAGIC):
        project_service.discard_upload_dir(upload_dir)
        return _error("INVALID_ARCHIVE", "文件不是有效的 ZIP 压缩包", 400)

    project = project_service.create_project(
        user["id"], public_id, _clean_project_name(name, archive_name), archive_name
    )
    # 同步函数交给线程池执行：解压/向量化是 CPU 密集任务，不能占用事件循环
    background_tasks.add_task(project_service.index_project, public_id, upload_dir)
    return {"success": True, "project": project}


@router.get("")
async def list_projects(user=Depends(get_current_user)):
    return {
        "success": True,
        "projects": project_service.list_projects(user["id"]),
        # 前端据此在本地先提示大小/数量上限，避免上传到一半才知道超限
        "limits": {
            "maxZipBytes": PROJECT_MAX_ZIP_BYTES,
            "maxFiles": PROJECT_MAX_FILES,
            "maxSingleFileBytes": PROJECT_MAX_SINGLE_FILE_BYTES,
        },
    }


@router.get("/{project_id}")
async def get_project(project_id: str, user=Depends(get_current_user)):
    project = project_service.get_project(user["id"], project_id)
    if not project:
        raise _not_found()
    return {"success": True, "project": project}


@router.get("/{project_id}/files")
async def list_project_files(project_id: str, user=Depends(get_current_user)):
    files = project_service.list_files(user["id"], project_id)
    if files is None:
        raise _not_found()
    return {"success": True, "files": files}


@router.get("/{project_id}/files/{document_id}")
async def get_project_file(project_id: str, document_id: int, user=Depends(get_current_user)):
    file_detail = project_service.get_file(user["id"], project_id, document_id)
    if file_detail is None:
        raise HTTPException(
            404,
            detail={"success": False, "error": {"code": "FILE_NOT_FOUND", "message": "文件不存在"}},
        )
    return {"success": True, "file": file_detail}


@router.delete("/{project_id}")
async def delete_project(project_id: str, user=Depends(get_current_user)):
    if not project_service.delete_project(user["id"], project_id):
        raise _not_found()
    return {"success": True, "message": "项目及其知识库已删除"}


@router.post("/{project_id}/search")
async def search_project(project_id: str, body: ProjectSearchReq, user=Depends(get_current_user)):
    """项目内检索验证：只在本项目的知识库中召回，跨项目互不可见。"""
    if not body.query or not body.query.strip():
        return _error("INVALID_QUERY", "查询内容不能为空", 400)

    project = project_service.get_project(user["id"], project_id)
    if not project:
        raise _not_found()
    if project["status"] not in (project_service.STATUS_READY, project_service.STATUS_PARTIAL):
        return _error("PROJECT_NOT_READY", "项目尚未解析完成，请稍后再试", 409)

    top_k = min(20, max(1, body.topK))
    try:
        results = project_service.search_project(user["id"], project_id, body.query.strip(), top_k)
    except RuntimeError as exc:
        return _error("EMBEDDING_DIM_MISMATCH", str(exc), 409)
    return {"success": True, "projectId": project_id, "results": results}


async def _run_project_qa(project_row, user_id: int, question: str, top_k: int, on_token) -> dict:
    """检索本项目上下文并生成回答；检索不到足够证据时直接返回提示，不调用模型。"""
    context_text, metadata = rag_service.build_context(
        user_id,
        question,
        top_k=top_k,
        min_score=0.05,
        project_id=project_row["id"],
        max_chars=PROJECT_QA_MAX_CONTEXT_CHARS,
        require_overlap=True,
        # 维度不一致是配置问题（换了 Embedding 但没重建索引），要显式报错而不是
        # 退化成"检索不到内容"，否则用户会以为只是检索效果差
        raise_on_error=True,
    )

    if not context_text:
        return {
            "success": True,
            "projectId": project_row["public_id"],
            "answer": INSUFFICIENT_ANSWER,
            "citations": [],
            "insufficientEvidence": True,
            "durationMs": 0,
            "usage": {
                "model": None,
                "estimatedInputTokens": 0,
                "estimatedOutputTokens": 0,
                "source": "cache",
                "estimatedCostUsd": 0.0,
            },
        }

    generation_id = str(uuid.uuid4())
    result = await ai_qa_service.stream_answer(question, context_text, on_token=on_token)
    input_tokens = result["usage"]["estimatedInputTokens"]
    output_tokens = result["usage"]["estimatedOutputTokens"]
    cost = _estimate_cost(input_tokens, output_tokens)
    result["usage"]["estimatedCostUsd"] = cost

    now = datetime.now(timezone.utc).isoformat()
    record_usage(
        generation_id, user_id, result["usage"]["model"],
        input_tokens, output_tokens, cost, now, result["usage"]["source"],
    )

    # 引用完全来自真实检索元数据，不信任模型文本里的路径/行号
    citations = [
        {
            "relPath": item.get("relPath") or item["title"],
            "symbolName": item.get("symbolName"),
            "startLine": item.get("startLine"),
            "endLine": item.get("endLine"),
            "score": item["score"],
            "preview": item["preview"],
        }
        for item in metadata
    ]

    return {
        "success": True,
        "projectId": project_row["public_id"],
        "answer": result["answer"],
        "citations": citations,
        "insufficientEvidence": False,
        "durationMs": result["durationMs"],
        "usage": result["usage"],
    }


@router.post("/{project_id}/ask")
async def ask_project(project_id: str, body: AskReq, request: Request, user=Depends(get_current_user)):
    """项目级问答：只检索该项目知识库，通过 SSE 逐 token 返回带引用的答案。

    事件契约与单文件生成保持一致：``token`` / ``complete`` / ``error``。
    前置校验（鉴权、项目归属、状态、额度、限流）都在进入流之前完成并返回 JSON 错误。
    """
    if not body.question or not body.question.strip():
        return _error("INVALID_QUERY", "问题内容不能为空", 400)
    question = body.question.strip()[:_MAX_QUESTION_LENGTH]

    project_row = project_service.fetch_project_row(user["id"], project_id)
    if not project_row:
        raise _not_found()

    status = project_row["status"]
    if status not in (project_service.STATUS_READY, project_service.STATUS_PARTIAL):
        if status == project_service.STATUS_FAILED:
            return _error("PROJECT_FAILED", project_row["error_message"] or "项目解析失败", 409)
        return _error("PROJECT_NOT_READY", "项目知识库尚未构建完成，请稍后再试", 409)

    quota = _get_daily_quota(user["id"])
    if quota["remaining"] <= 0:
        return _error("DAILY_QUOTA_EXCEEDED", "今日 AI 使用额度已用完，请明天再试", 429)

    client_ip = request.client.host if request.client else "unknown"
    if not _qa_limiter.allow(client_ip):
        return _error("RATE_LIMITED", "提问过于频繁，请稍后再试", 429)

    top_k = min(PROJECT_QA_MAX_TOP_K, max(1, body.topK))

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def on_token(token: str):
            queue.put_nowait(("token", {"token": token}))

        async def run():
            try:
                result = await _run_project_qa(project_row, user["id"], question, top_k, on_token)
                await queue.put(("complete", result))
            except rag_service.EmbeddingDimensionError as exc:
                logger.warning("项目问答维度不一致 public_id=%s: %s", project_id, exc)
                await queue.put(("error", {
                    "code": "EMBEDDING_DIM_MISMATCH",
                    "message": "项目索引与当前 Embedding 模型不一致，请删除该项目后重新上传",
                }))
            except RuntimeError as exc:
                if "DEEPSEEK_API_KEY" in str(exc):
                    await queue.put(("error", {"code": "AI_NOT_CONFIGURED", "message": str(exc)}))
                else:
                    logger.exception("项目问答失败（RuntimeError）")
                    await queue.put(("error", {"code": "AI_GENERATION_FAILED", "message": "AI 服务暂时不可用，请稍后重试"}))
            except Exception:
                logger.exception("项目问答失败（未预期异常）")
                await queue.put(("error", {"code": "AI_GENERATION_FAILED", "message": "AI 服务暂时不可用，请稍后重试"}))

        task_handle = asyncio.create_task(run())
        try:
            while True:
                event, data = await queue.get()
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                if event in ("complete", "error"):
                    break
        finally:
            if not task_handle.done():
                task_handle.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-AI-Quota-Limit": str(quota["limit"]),
        "X-AI-Quota-Remaining": str(quota["remaining"] - 1),
    })
