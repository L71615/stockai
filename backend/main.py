"""StockAI — FastAPI 主入口"""

import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import PORT, ENV, FRONTEND_DIR
from routers import auth, stocks, skills, ai, agents, memory, dca, settings as settings_router

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
app.include_router(skills.router, prefix="/api/skills", tags=["Skills"])
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(memory.router, prefix="/api", tags=["Memory"])
app.include_router(dca.router, prefix="/api/stocks", tags=["DCA"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(settings_router.router, tags=["Settings"])

# 健康检查
@app.get("/api/health")
def health():
    return {"status": "ok"}

# 前端静态文件 (必须在 API 路由之后挂载)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

@app.on_event("startup")
def startup():
    from database import init_db
    init_db()
    from services.scheduler import start_dca_reminder_thread
    start_dca_reminder_thread()


if __name__ == "__main__":
    import uvicorn
    print(f"StockAI server starting at http://localhost:{PORT}")
    print(f"Docs at http://localhost:{PORT}/api/docs")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=(ENV == "development"))
