"""StockAI — FastAPI 主入口"""

import os
import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import PORT, ENV, VERSION
from routers import auth, stocks, skills, ai, agents, memory, dca, settings as settings_router, quant, holdings, transactions, screener, kol

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

# API 路由
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["Stocks"])
app.include_router(holdings.router, prefix="/api/stocks", tags=["Holdings"])
app.include_router(transactions.router, prefix="/api/stocks", tags=["Transactions"])
app.include_router(skills.router, prefix="/api/skills", tags=["Skills"])
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(memory.router, prefix="/api", tags=["Memory"])
app.include_router(dca.router, prefix="/api/stocks", tags=["DCA"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(settings_router.router, tags=["Settings"])
app.include_router(quant.router)
app.include_router(screener.router)
app.include_router(kol.router)

# 健康检查
@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.get("/api/version")
def api_version():
    return {"version": VERSION, "name": "StockAI", "factors": 29}

@app.on_event("startup")
def startup():
    from database import init_db, ensure_admin_user
    init_db()
    ensure_admin_user()
    from services.scheduler import start_dca_reminder_thread, start_kol_daily_thread
    start_dca_reminder_thread()
    start_kol_daily_thread()


# ── 认证中间件：保护所有 /api/ 路由（登录接口除外）──
import jwt as pyjwt
from config import JWT_SECRET

# 不需要认证的接口
PUBLIC_APIS = {"/api/auth/login", "/api/auth/register", "/api/health", "/api/version", "/api/docs", "/api/openapi.json"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # 非 API 路由不拦截（前端静态文件）
    if not path.startswith("/api/"):
        return await call_next(request)

    # 公开接口放行
    if path in PUBLIC_APIS or path.startswith("/api/docs") or path.startswith("/api/openapi"):
        return await call_next(request)

    # 验证 JWT
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return JSONResponse({"error": "未登录，请先登录"}, status_code=401)

    try:
        pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        return JSONResponse({"error": "登录已过期，请重新登录"}, status_code=401)
    except pyjwt.InvalidTokenError:
        return JSONResponse({"error": "登录无效，请重新登录"}, status_code=401)

    return await call_next(request)


if __name__ == "__main__":
    import uvicorn
    print(f"StockAI server starting at http://localhost:{PORT}")
    print(f"Docs at http://localhost:{PORT}/api/docs")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=(ENV == "development"))

