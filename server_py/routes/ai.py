import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from auth import get_current_user
from config import AI_DAILY_QUOTA, DEEPSEEK_INPUT_COST, DEEPSEEK_MODEL, DEEPSEEK_OUTPUT_COST
from database import get_conn
from models import FeedbackReq, GenerateReq
from rate_limit import SlidingWindowLimiter
from services import cache_service
from services import rag_service
from services.ai_comment_service import generate_comments
from services.code_analyzer import analyze_code
from services.evaluation_service import assess_generation, get_evaluation_metrics, record_evaluation
from services.feedback_service import get_feedback_metrics, save_feedback
from services.generation_history_service import list_generations, save_generation
from services.usage_service import get_usage_metrics, record_usage

router = APIRouter(prefix="/api/ai", tags=["ai"])

logger = logging.getLogger(__name__)

MAX_CODE_LENGTH = 20000
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX = 10
_generation_limiter = SlidingWindowLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_SECONDS)

_task_aliases = {
    "comment": "生成函数级代码注释",
    "explain": "解释代码整体逻辑、主要函数职责和关键数据流",
    "refactor": "识别可维护性问题并给出具体、可执行的重构建议",
}

_allowed_tasks = {
    "生成函数级代码注释",
    "解释代码整体逻辑、主要函数职责和关键数据流",
    "识别可维护性问题并给出具体、可执行的重构建议",
} | set(_task_aliases.values())


def _normalize_task(task: str) -> str:
    if not task:
        return "生成函数级代码注释"
    t = task.strip()
    if not t:
        return "生成函数级代码注释"
    if t in _task_aliases:
        return _task_aliases[t]
    aliases_reverse = {
        "生成注释": "生成函数级代码注释",
        "代码解释": "解释代码整体逻辑、主要函数职责和关键数据流",
        "重构建议": "识别可维护性问题并给出具体、可执行的重构建议",
    }
    if t in aliases_reverse:
        return aliases_reverse[t]
    return t


# 额度按北京时间（UTC+8）自然日重置，避免 UTC 0 点（北京 08:00）与“明天再试”的提示口径不一致
CN_TZ = timezone(timedelta(hours=8))


def _get_daily_quota(user_id: int) -> dict:
    now_cn = datetime.now(CN_TZ)
    start_cn = now_cn.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_cn.astimezone(timezone.utc)
    conn = get_conn()
    used = conn.execute(
        "SELECT COUNT(*) AS c FROM usage_records WHERE user_id=? AND created_at>=?",
        (user_id, start_utc.isoformat()),
    ).fetchone()["c"]
    conn.close()
    return {
        "limit": AI_DAILY_QUOTA,
        "used": used,
        "remaining": max(0, AI_DAILY_QUOTA - used),
        "resetAt": start_cn.timestamp() + 86400,
    }


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round((input_tokens * DEEPSEEK_INPUT_COST + output_tokens * DEEPSEEK_OUTPUT_COST) / 1_000_000, 6)


async def _run_generation(input_data: dict, user_id: int, on_token=None):
    code = input_data["code"]
    language = input_data["language"]
    style = input_data["style"]
    task = input_data["task"]
    structure = analyze_code(code, language)
    structure["totalLines"] = len(code.split("\n"))

    function_names = " ".join(f.get("name", "") for f in structure.get("functions", [])[:20])
    rag_query = "\n".join([language, task, function_names, code[:1500]])
    context_text, retrieved = rag_service.build_context(user_id, rag_query, top_k=4)

    kb_version = cache_service._kb_version(user_id)
    signature = cache_service.build_signature(code, language, style, task, kb_version)
    cached = cache_service.lookup(user_id, signature, kb_version)

    generation_id = str(uuid.uuid4())
    if cached:
        result = json.loads(json.dumps(cached["result"], ensure_ascii=False))
        cache_hit = True
    else:
        result = await generate_comments(code, language, style, task, structure, context=context_text, on_token=on_token)
        cache_service.store(user_id, signature, result)
        cache_hit = False

    evaluation = assess_generation(
        generation_id, structure, result["comments"], result["debug"]["durationMs"], user_id
    )
    result["debug"]["evaluation"] = evaluation
    result["debug"]["rag"] = {
        "enabled": True,
        "retrievedCount": len(retrieved),
        "contextChars": len(context_text),
        "retrieved": retrieved,
    }
    result["debug"]["cache"] = {"hit": cache_hit, "score": cached["score"] if cached else None}

    if cache_hit:
        input_tokens = 0
        output_tokens = 0
        cost = 0.0
        result["debug"]["usage"] = {
            "estimatedInputTokens": 0,
            "estimatedOutputTokens": 0,
            "estimated": False,
            "source": "cache",
            "estimatedCostUsd": 0.0,
        }
    else:
        input_tokens = result["debug"]["usage"]["estimatedInputTokens"]
        output_tokens = result["debug"]["usage"]["estimatedOutputTokens"]
        cost = _estimate_cost(input_tokens, output_tokens)
        result["debug"]["usage"]["estimatedCostUsd"] = cost

    now = datetime.now(timezone.utc).isoformat()
    token_source = "cache" if cache_hit else result["debug"]["usage"].get("source", "unknown")
    record_usage(generation_id, user_id, DEEPSEEK_MODEL, input_tokens, output_tokens, cost, now, token_source)
    evaluation["createdAt"] = now
    record_evaluation(evaluation)
    save_generation(
        generation_id, user_id, language, task, style, code,
        result["summary"], result["comments"], result["risks"], result["suggestions"],
        result["debug"], now,
    )

    return {"success": True, "generationId": generation_id, "language": language, "structure": structure, **result}


def _validate(body: GenerateReq):
    if not body.code or not body.code.strip():
        return None, JSONResponse(content={"success": False, "error": {"code": "INVALID_CODE", "message": "代码内容不能为空"}}, status_code=400)
    if len(body.code) > MAX_CODE_LENGTH:
        return None, JSONResponse(content={"success": False, "error": {"code": "CODE_TOO_LARGE", "message": f"代码长度不能超过 {MAX_CODE_LENGTH} 个字符"}}, status_code=413)
    task = _normalize_task(body.task)
    if task not in _allowed_tasks:
        return None, JSONResponse(content={"success": False, "error": {"code": "INVALID_TASK", "message": "AI 任务类型无效"}}, status_code=400)
    return task, None


@router.post("/generate-comments")
async def generate(body: GenerateReq, request: Request, user=Depends(get_current_user)):
    task, error = _validate(body)
    if error:
        return error

    quota = _get_daily_quota(user["id"])
    if quota["remaining"] <= 0:
        return JSONResponse(content={"success": False, "error": {"code": "DAILY_QUOTA_EXCEEDED", "message": "今日 AI 使用额度已用完，请明天再试"}}, status_code=429)

    ip = request.client.host if request.client else "unknown"
    if not _generation_limiter.allow(ip):
        return JSONResponse(content={"success": False, "error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请一分钟后再试"}}, status_code=429)

    try:
        result = await _run_generation(
            {"code": body.code, "language": body.language, "style": body.style, "task": task},
            user["id"],
        )
        resp = JSONResponse(content=result, status_code=200)
        resp.headers["X-AI-Quota-Limit"] = str(quota["limit"])
        resp.headers["X-AI-Quota-Remaining"] = str(quota["remaining"] - 1)
        return resp
    except RuntimeError as e:
        if "DEEPSEEK_API_KEY" in str(e):
            return JSONResponse(content={"success": False, "error": {"code": "AI_NOT_CONFIGURED", "message": str(e)}}, status_code=503)
        return JSONResponse(content={"success": False, "error": {"code": "AI_GENERATION_FAILED", "message": "AI 服务暂时不可用，请稍后重试"}}, status_code=502)
    except Exception:
        return JSONResponse(content={"success": False, "error": {"code": "AI_GENERATION_FAILED", "message": "AI 服务暂时不可用，请稍后重试"}}, status_code=502)


@router.post("/generate-comments/stream")
async def generate_stream(body: GenerateReq, request: Request, user=Depends(get_current_user)):
    task, error = _validate(body)
    if error:
        return error

    quota = _get_daily_quota(user["id"])
    if quota["remaining"] <= 0:
        return JSONResponse(content={"success": False, "error": {"code": "DAILY_QUOTA_EXCEEDED", "message": "今日 AI 使用额度已用完，请明天再试"}}, status_code=429)

    ip = request.client.host if request.client else "unknown"
    if not _generation_limiter.allow(ip):
        return JSONResponse(content={"success": False, "error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请一分钟后再试"}}, status_code=429)

    input_data = {"code": body.code, "language": body.language, "style": body.style, "task": task}

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def on_token(token: str):
            queue.put_nowait(("token", {"token": token}))

        async def run():
            try:
                result = await _run_generation(input_data, user["id"], on_token=on_token)
                await queue.put(("complete", result))
            except RuntimeError as exc:
                if "DEEPSEEK_API_KEY" in str(exc):
                    await queue.put(("error", {"code": "AI_NOT_CONFIGURED", "message": str(exc)}))
                else:
                    logger.exception("AI 流式生成失败（RuntimeError）")
                    await queue.put(("error", {"code": "AI_GENERATION_FAILED", "message": "AI 服务暂时不可用，请稍后重试"}))
            except Exception:
                logger.exception("AI 流式生成失败（未预期异常）")
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


@router.get("/config")
async def config():
    from config import DEEPSEEK_API_KEY
    return {
        "configured": bool(DEEPSEEK_API_KEY),
        "model": DEEPSEEK_MODEL,
        "provider": "DeepSeek",
        "framework": "LangChain-Python",
    }


@router.get("/quota")
async def quota(user=Depends(get_current_user)):
    return {"success": True, "quota": _get_daily_quota(user["id"])}


@router.get("/usage")
async def usage(user=Depends(get_current_user)):
    # estimated 口径由 usage_records.token_source 实际聚合得出，不再硬编码
    return {"success": True, "metrics": get_usage_metrics(user["id"])}


@router.get("/evaluation")
async def evaluation(user=Depends(get_current_user)):
    return {"success": True, "metrics": get_evaluation_metrics(user["id"])}


@router.get("/history")
async def history(
    page: int = 1,
    pageSize: int = 10,
    language: Optional[str] = None,
    task: Optional[str] = None,
    user=Depends(get_current_user),
):
    page = max(1, page)
    pageSize = min(50, max(1, pageSize))
    result = list_generations(page=page, page_size=pageSize, language=language, task=task, user_id=user["id"])
    return {"success": True, **result}


@router.post("/feedback")
async def feedback(body: FeedbackReq, user=Depends(get_current_user)):
    if not body.generationId or not body.generationId.strip():
        return JSONResponse(content={"success": False, "error": "缺少生成结果标识"}, status_code=400)
    if body.rating not in ("helpful", "needs_improvement"):
        return JSONResponse(content={"success": False, "error": "反馈类型无效"}, status_code=400)
    if len(body.comment) > 1000:
        return JSONResponse(content={"success": False, "error": "反馈说明长度无效"}, status_code=400)

    save_feedback(body.generationId, user["id"], body.rating, body.comment.strip(), datetime.now(timezone.utc).isoformat())
    return {"success": True, "metrics": get_feedback_metrics(user["id"])}


@router.get("/feedback/metrics")
async def feedback_metrics(user=Depends(get_current_user)):
    return {"success": True, "metrics": get_feedback_metrics(user["id"])}


@router.get("/cache/stats")
async def cache_stats(user=Depends(get_current_user)):
    return {"success": True, "stats": cache_service.stats(user["id"])}


@router.delete("/cache")
async def clear_cache(user=Depends(get_current_user)):
    removed = cache_service.clear(user["id"])
    return {"success": True, "removed": removed}
