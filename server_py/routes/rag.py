from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import get_current_user
from services import rag_service

router = APIRouter(prefix="/api/rag", tags=["rag"])


class DocumentReq(BaseModel):
    title: str
    content: str
    language: str = "text"
    source: str = "manual"


class SearchReq(BaseModel):
    query: str
    topK: int = 4


SAMPLE_DOCUMENTS = [
    {
        "title": "团队代码注释规范",
        "language": "text",
        "source": "builtin",
        "content": (
            "注释规范：\n"
            "1. 所有导出函数必须使用 JSDoc 风格注释，包含功能描述、@param 和 @returns。\n"
            "2. 注释应说明“为什么”而不是重复“做什么”，避免与代码字面重复。\n"
            "3. 异步函数需说明失败时的行为与抛出的错误类型。\n"
            "4. 金额、时间、权限等敏感参数必须在注释中标注单位与取值范围。\n"
            "5. 废弃函数需标注 @deprecated 并给出替代方案。"
        ),
    },
    {
        "title": "错误处理与日志约定",
        "language": "javascript",
        "source": "builtin",
        "content": (
            "错误处理约定：\n"
            "- 对外接口统一返回 { success, error: { code, message } } 结构。\n"
            "- 错误码使用大写下划线风格，如 INVALID_CODE、RATE_LIMITED。\n"
            "- 禁止吞掉异常，捕获后必须记录日志或向上抛出。\n"
            "- 网络请求需设置超时，并对 5xx 做重试与降级。\n"
            "- 用户可见错误信息不得泄露内部堆栈或密钥。"
        ),
    },
    {
        "title": "REST API 设计规范",
        "language": "text",
        "source": "builtin",
        "content": (
            "REST 设计规范：\n"
            "- 资源使用名词复数，如 /api/rag/documents。\n"
            "- 使用 HTTP 状态码表达结果：200 成功、201 创建、400 参数错误、401 未认证、403 无权限、429 限流。\n"
            "- 分页参数使用 page 与 pageSize，返回 total 字段。\n"
            "- 所有写操作需鉴权，用户数据按 user_id 隔离。\n"
            "- 流式接口使用 text/event-stream，事件类型包含 token、complete、error。"
        ),
    },
]


@router.post("/documents")
async def add_document(body: DocumentReq, user=Depends(get_current_user)):
    if not body.title or not body.title.strip():
        return JSONResponse(content={"success": False, "error": "标题不能为空"}, status_code=400)
    if not body.content or not body.content.strip():
        return JSONResponse(content={"success": False, "error": "文档内容不能为空"}, status_code=400)
    if len(body.content) > 200000:
        return JSONResponse(content={"success": False, "error": "文档内容不能超过 200000 个字符"}, status_code=413)

    try:
        doc = rag_service.add_document(user["id"], body.title.strip(), body.content, body.language, body.source)
    except ValueError as exc:
        return JSONResponse(content={"success": False, "error": {"code": "EMBEDDING_DIM_MISMATCH", "message": str(exc)}}, status_code=409)
    return {"success": True, "document": doc}


@router.get("/documents")
async def list_documents(user=Depends(get_current_user)):
    return {"success": True, "documents": rag_service.list_documents(user["id"])}


@router.get("/documents/{document_id}")
async def get_document(document_id: int, user=Depends(get_current_user)):
    doc = rag_service.get_document(user["id"], document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return {"success": True, "document": doc}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int, user=Depends(get_current_user)):
    if not rag_service.delete_document(user["id"], document_id):
        raise HTTPException(404, "文档不存在")
    return {"success": True, "message": "文档已删除"}


@router.post("/search")
async def search(body: SearchReq, user=Depends(get_current_user)):
    if not body.query or not body.query.strip():
        return JSONResponse(content={"success": False, "error": "查询内容不能为空"}, status_code=400)
    top_k = min(20, max(1, body.topK))
    try:
        results = rag_service.search(user["id"], body.query, top_k)
    except RuntimeError as exc:
        return JSONResponse(content={"success": False, "error": {"code": "EMBEDDING_DIM_MISMATCH", "message": str(exc)}}, status_code=409)
    return {"success": True, "results": results}


@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    return {"success": True, "stats": rag_service.get_stats(user["id"])}


@router.post("/seed")
async def seed(user=Depends(get_current_user)):
    added = []
    for sample in SAMPLE_DOCUMENTS:
        added.append(rag_service.add_document(
            user["id"], sample["title"], sample["content"], sample["language"], sample["source"]
        ))
    return {"success": True, "added": added}
