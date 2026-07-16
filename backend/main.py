"""StockAI — FastAPI 主入口"""

import logging
import os
import sys
import traceback
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import PORT, ENV, VERSION
from routers import auth, stocks, ai, dca, discipline, prediction, settings as settings_router, quant, holdings, transactions, screener, factor_lab

app = FastAPI(title="StockAI", version=VERSION, docs_url="/api/docs")

# CORS — 仅允许明确的白名单域名
_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
if not _CORS_ORIGINS:
    raise ValueError("CORS_ORIGINS environment variable must be set (comma-separated list of allowed origins)")
ALLOWED_ORIGINS = [o.strip() for o in _CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局限流（slowapi）──
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

_rate_limit_default = int(os.getenv("RATE_LIMIT_DEFAULT", "60"))  # 默认 60 req/min
_limiter = Limiter(key_func=get_remote_address, default_limits=[f"{_rate_limit_default}/minute"])
app.state.limiter = _limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        {"error": f"请求过于频繁，请稍后再试（{_rate_limit_default} 次/分钟）"},
        status_code=429,
    )


logger = logging.getLogger("stockai")

from services.ai_exceptions import AIServiceError

@app.exception_handler(AIServiceError)
async def ai_service_error_handler(request: Request, exc: AIServiceError):
    """AI 服务异常 — 统一返回 503，前端可据此提示用户"""
    logger.warning(f"AI服务异常 [{request.method} {request.url.path}]: {exc} (provider={exc.provider_name}, function={exc.function_key})")
    return JSONResponse(
        {"error": str(exc), "provider": exc.provider_name, "function": exc.function_key},
        status_code=503,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器 — 捕获所有未处理的异常，记录完整 traceback，返回 JSON 错误"""
    tb = traceback.format_exc()
    logger.error(f"未处理异常 [{request.method} {request.url.path}]: {exc}\n{tb}")
    return JSONResponse(
        {"error": f"服务器内部错误：{exc}"},
        status_code=500,
    )

# API 路由
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["Stocks"])
app.include_router(holdings.router, prefix="/api/stocks", tags=["Holdings"])
app.include_router(transactions.router, prefix="/api/stocks", tags=["Transactions"])
app.include_router(dca.router, prefix="/api/stocks", tags=["DCA"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(settings_router.router, tags=["Settings"])
app.include_router(quant.router)
app.include_router(screener.router)
app.include_router(discipline.router)
app.include_router(prediction.router)
app.include_router(factor_lab.router)

# 健康检查
@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.get("/api/version")
def api_version():
    from services.factor_service import REGISTRY_SUMMARY
    return {
        "version": VERSION,
        "name": "StockAI",
        "factors": {
            "done": REGISTRY_SUMMARY["done"],
            "pending": REGISTRY_SUMMARY["pending"],
            "planned_alpha158": REGISTRY_SUMMARY["planned_alpha158"],
            "total": REGISTRY_SUMMARY["grand_total"],
            "categories": REGISTRY_SUMMARY["categories"],
        }
    }

@app.on_event("startup")
def startup():
    from database import init_db, ensure_admin_user
    init_db()
    ensure_admin_user()
    from services.scheduler import (
        start_dca_reminder_thread,
        start_stop_loss_thread,
        start_futu_intraday_sync_thread,
        start_futu_nightly_sync_thread,
        start_memory_resolution_thread,
        start_futu_nightly_fundamentals_thread,
    )
    start_dca_reminder_thread()
    start_stop_loss_thread()
    start_futu_intraday_sync_thread()
    start_futu_nightly_sync_thread()
    start_memory_resolution_thread()
    start_futu_nightly_fundamentals_thread()


# ── 认证中间件：保护所有 /api/ 路由（登录接口除外）──
import jwt as pyjwt
from config import JWT_SECRET
from dependencies import _current_user_id

# 不需要认证的接口
PUBLIC_APIS = {"/api/auth/login", "/api/auth/register", "/api/health", "/api/version", "/api/docs", "/api/openapi.json"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # 非 API 路由不拦截（前端静态文件）
    if not path.startswith("/api/"):
        return await call_next(request)

    # 公开接口放行（user_id 保持默认值 1）
    if path in PUBLIC_APIS or path.startswith("/api/docs") or path.startswith("/api/openapi"):
        return await call_next(request)

    # 验证 JWT 并提取 user_id
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return JSONResponse({"error": "未登录，请先登录"}, status_code=401)

    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
        _current_user_id.set(user_id)
    except pyjwt.ExpiredSignatureError:
        return JSONResponse({"error": "登录已过期，请重新登录"}, status_code=401)
    except pyjwt.InvalidTokenError:
        return JSONResponse({"error": "登录无效，请重新登录"}, status_code=401)

    return await call_next(request)


# ── 安全响应头中间件（最外层，确保所有响应都带安全头）──
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)

    # HSTS — 强制 HTTPS（仅生产环境生效，max-age=1年）
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # 禁止 MIME 类型嗅探
    response.headers["X-Content-Type-Options"] = "nosniff"

    # 禁止被 iframe 嵌入（防点击劫持）
    response.headers["X-Frame-Options"] = "DENY"

    # 反射型 XSS 过滤（旧浏览器兼容）
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Referrer 策略 — 同源发完整 URL，跨域只发 origin
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # 权限策略 — 禁用摄像头/麦克风/定位等非必要 API
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), "
        "usb=(), bluetooth=(), payment=()"
    )

    # CSP — 内容安全策略
    # API 返回主要是 JSON，但 /api/docs 返回 Swagger UI HTML
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    return response


if __name__ == "__main__":
    import uvicorn
    print(f"StockAI server starting at http://localhost:{PORT}")
    print(f"Docs at http://localhost:{PORT}/api/docs")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=(ENV == "development"))

