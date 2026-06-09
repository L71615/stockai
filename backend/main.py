"""StockAI — FastAPI 主入口"""

import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles as _StaticFiles

from config import PORT, ENV, FRONTEND_DIR


class StaticFiles(_StaticFiles):
    """StaticFiles with no-cache headers for development."""
    async def __call__(self, scope, receive, send):
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"cache-control"] = b"no-cache, no-store, must-revalidate"
                message["headers"] = list(headers.items())
            await send(message)
        await super().__call__(scope, receive, send_wrapper)
from routers import auth, stocks, skills, ai, agents, memory, dca, settings as settings_router, quant, holdings, transactions, screener

app = FastAPI(title="StockAI", version="0.2.0", docs_url="/api/docs")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

# 健康检查
@app.get("/api/health")
def health():
    return {"status": "ok"}

# 前端静态文件 (必须在 API 路由之后挂载)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

@app.on_event("startup")
def startup():
    from database import init_db, ensure_admin_user
    init_db()
    ensure_admin_user()
    from services.scheduler import start_dca_reminder_thread
    start_dca_reminder_thread()


# ── 认证中间件：保护所有 /api/ 路由（登录接口除外）──
from fastapi import Request
from fastapi.responses import JSONResponse
import jwt as pyjwt
from config import JWT_SECRET

# 不需要认证的接口
PUBLIC_APIS = {"/api/auth/login", "/api/auth/register", "/api/health", "/api/docs", "/api/openapi.json"}

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
