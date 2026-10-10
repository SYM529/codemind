"""统一 HTTP 错误响应结构。

项目内的业务错误有两种写法：
- ``JSONResponse({"success": False, "error": {...}})``：顶层结构，前端可直接读取
- ``raise HTTPException(detail={...})``：FastAPI 会自动包一层 ``detail``，
  前端读 ``response.data.error.message`` 时会取不到值，从而退化成通用提示

这里注册一个全局异常处理器，把 ``HTTPException`` 的 ``detail`` 提升回顶层，
让所有错误响应保持 ``{success, error: {code, message}}`` 的统一契约。
"""

from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def install_error_handlers(app):
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request, exc: StarletteHTTPException):
        detail = exc.detail
        # 业务错误：detail 本身已是 {success: False, error: {...}}，直接返回顶层结构
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(content=detail, status_code=exc.status_code)

        # 其他情况（404、405 等）：包装成同样的结构，保证前端解析逻辑单一
        message = detail if isinstance(detail, str) else "请求失败"
        return JSONResponse(
            content={
                "success": False,
                "error": {"code": f"HTTP_{exc.status_code}", "message": message},
            },
            status_code=exc.status_code,
        )
