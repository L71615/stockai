"""StockAI — 配置文件"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# 服务器
PORT = int(os.getenv("PORT", 3000))
ENV = os.getenv("ENV", "development")

# SQLite 数据库
DB_PATH = os.getenv("DB_PATH", str(PROJECT_DIR / "database" / "stockai.db"))

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_EXPIRES = 7 * 24 * 3600  # 7 天

# AI
AI_PROVIDER = os.getenv("AI_PROVIDER", "minimax")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-7")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
XIAOMI_API_KEY = os.getenv("XIAOMI_API_KEY", "")
XIAOMI_MODEL = os.getenv("XIAOMI_MODEL", "mixtral-8x7b")
XIAOMI_BASE_URL = os.getenv("XIAOMI_BASE_URL", "")

# 爬虫
CRAWLER_UA = "StockAI-Bot/1.0"
CRAWLER_TIMEOUT = int(os.getenv("CRAWLER_TIMEOUT", 15))
EASTMONEY_TOKEN = os.getenv("EASTMONEY_TOKEN", "D43BF722C8E33BDC906FB84A85A3263A")

# SMTP 邮件
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# 前端目录
FRONTEND_DIR = PROJECT_DIR / "frontend"
