import sys
import os
import logging

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import PORT, CORS_ORIGINS
import database  # noqa: F401  # 导入即触发建表与数据迁移

from routes.auth import router as auth_router
from routes.ai import router as ai_router
from routes.admin import router as admin_router
from routes.rag import router as rag_router
from routes.projects import router as projects_router
from services.code_analyzer import analyze_code
from services.nlp_comment_generator import build_comments
from services import project_service

logger = logging.getLogger(__name__)


class AnalyzeReq(BaseModel):
    code: str
    language: str = "javascript"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 清理上次异常退出残留的项目上传工作目录（例如容器被强杀）。
    # 清理失败不影响服务启动。
    try:
        project_service.cleanup_stale_upload_dirs()
    except Exception:
        logger.exception("清理陈旧项目上传目录失败")
    yield


app = FastAPI(
    title="CodeMind API",
    description="AI 代码理解与文档生成助手：代码结构分析、RAG 检索增强、流式生成与结构化输出校验",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(admin_router)
app.include_router(rag_router)
app.include_router(projects_router)


@app.get("/api/health")
async def health():
    return {"status": "服务运行正常", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/analyze-code")
async def analyze(body: AnalyzeReq):
    if not body.code or not body.code.strip():
        return JSONResponse(content={"success": False, "error": "代码内容不能为空"}, status_code=400)
    try:
        structure = analyze_code(body.code, body.language)
        return {
            "success": True,
            "structure": structure,
            "language": body.language,
            "totalLines": len(body.code.split("\n")),
        }
    except Exception as exc:
        return JSONResponse(content={"success": False, "error": f"分析代码时发生错误: {exc}"}, status_code=500)


@app.post("/api/generate-comments")
async def generate_rule_based(body: AnalyzeReq):
    if not body.code or not body.code.strip():
        return JSONResponse(content={"success": False, "error": "代码内容不能为空"}, status_code=400)
    try:
        structure = analyze_code(body.code, body.language)
        return {
            "success": True,
            "structure": structure,
            "comments": build_comments(structure, body.language),
            "language": body.language,
        }
    except Exception as exc:
        return JSONResponse(content={"success": False, "error": f"生成注释时发生错误: {exc}"}, status_code=500)


# --- 单端口部署：由 FastAPI 一并托管前端构建产物（CloudStudio 等仅暴露单端口的环境） ---
from pathlib import Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"


def mount_frontend(application: FastAPI) -> None:
    """存在前端构建产物时挂载静态资源并提供 SPA 回退。

    API 路由已在 mount 之前注册，因此 /api/* 会优先命中业务路由，不会被回退吞掉。
    """
    if not FRONTEND_DIST.is_dir():
        return

    # 逐个目录判断，产物不完整时降级为纯 API 服务而不是直接崩溃
    for route, folder in (("/js", "js"), ("/css", "css")):
        directory = FRONTEND_DIST / folder
        if directory.is_dir():
            application.mount(route, StaticFiles(directory=directory), name=f"frontend-{folder}")

    # 同时支持 HEAD：平台的健康检查用 HEAD / 探活，只注册 GET 会返回 405
    @application.api_route("/", methods=["GET", "HEAD"])
    async def frontend_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @application.get("/{full_path:path}")
    async def frontend_spa(full_path: str):
        # 未命中的 API 路径应返回 404，而不是回退到 index.html
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(content={"detail": "Not Found"}, status_code=404)
        target = (FRONTEND_DIST / full_path).resolve()
        if target.is_file() and FRONTEND_DIST in target.parents:
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")


mount_frontend(app)

# 统一异常响应结构，避免 FastAPI 的 detail 包装破坏前端 {success, error} 契约
from http_errors import install_error_handlers  # noqa: E402

install_error_handlers(app)


if __name__ == "__main__":
    import uvicorn

    reload_enabled = os.getenv("RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=reload_enabled)
