"""KOL 大佬观点追踪 — API 路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute

router = APIRouter(prefix="/api/kol", tags=["KOL"])


# ── 账号管理 ──

@router.get("/accounts")
def list_accounts():
    """获取所有追踪的大佬账号"""
    return query_all(
        "SELECT * FROM kol_accounts WHERE user_id = 1 ORDER BY active DESC, created_at DESC"
    )


class AccountBody(BaseModel):
    username: str
    display_name: str = ""
    category: str = ""
    market: str = ""
    notes: str = ""


@router.post("/accounts")
def add_account(body: AccountBody):
    """添加一个大佬账号"""
    username = body.username.strip().lstrip("@")
    if not username:
        raise HTTPException(400, "用户名不能为空")

    existing = query_one(
        "SELECT id FROM kol_accounts WHERE user_id = 1 AND username = ?",
        (username,),
    )
    if existing:
        raise HTTPException(409, f"@{username} 已存在")

    result = execute(
        """INSERT INTO kol_accounts (user_id, username, display_name, category, market, notes)
           VALUES (1, ?, ?, ?, ?, ?)""",
        (username, body.display_name, body.category, body.market, body.notes),
    )
    return {"id": result["lastrowid"], "username": username, "message": f"@{username} 已添加"}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    """删除一个大佬账号"""
    row = query_one("SELECT id, username FROM kol_accounts WHERE id = ? AND user_id = 1", (account_id,))
    if not row:
        raise HTTPException(404, "账号不存在")
    execute("DELETE FROM kol_accounts WHERE id = ?", (account_id,))
    return {"message": f"@{row['username']} 已删除"}


@router.put("/accounts/{account_id}")
def toggle_account(account_id: int, active: bool = True):
    """启用/禁用追踪"""
    row = query_one("SELECT id, username FROM kol_accounts WHERE id = ? AND user_id = 1", (account_id,))
    if not row:
        raise HTTPException(404, "账号不存在")
    execute("UPDATE kol_accounts SET active = ? WHERE id = ?", (1 if active else 0, account_id))
    status = "启用" if active else "暂停"
    return {"message": f"@{row['username']} 已{status}"}


# ── 爬取 ──

@router.post("/crawl")
def trigger_crawl():
    """手动触发爬取所有活跃账号"""
    from services.kol_crawler import crawl_all
    result = crawl_all(user_id=1)
    return result


# ── 日报 ──

@router.get("/briefs/latest")
def get_latest_brief():
    """获取最新日报"""
    from services.kol_service import get_latest_brief
    brief = get_latest_brief(user_id=1)
    if not brief:
        return {"empty": True, "message": "还没有日报，请先添加追踪账号并触发爬取"}
    return brief


@router.get("/briefs")
def get_brief_by_date(brief_date: str):
    """获取指定日期日报 (YYYY-MM-DD)"""
    from services.kol_service import get_brief_by_date
    brief = get_brief_by_date(brief_date, user_id=1)
    if not brief:
        raise HTTPException(404, f"未找到 {brief_date} 的日报")
    return brief


@router.post("/briefs/generate")
def generate_brief_manual():
    """手动触发日报生成（同步等待 AI 返回）"""
    from services.kol_service import generate_brief
    result = generate_brief(user_id=1)
    if result.get("skipped"):
        return {"empty": True, "message": result.get("reason", "无帖子可分析")}
    return result


# ── 帖子查询 ──

@router.get("/posts")
def get_posts(username: str = "", limit: int = 50):
    """获取今日帖子（可选按账号筛选）"""
    from datetime import date
    today = date.today().isoformat()
    if username:
        posts = query_all(
            """SELECT * FROM kol_posts
               WHERE username = ? AND date(fetched_at) = ?
               ORDER BY (likes + retweets * 2) DESC LIMIT ?""",
            (username, today, limit),
        )
    else:
        posts = query_all(
            """SELECT * FROM kol_posts
               WHERE date(fetched_at) = ?
               ORDER BY (likes + retweets * 2) DESC LIMIT ?""",
            (today, limit),
        )
    return posts


# ── 代理配置 ──

@router.get("/proxy")
def get_proxy_config():
    """获取爬虫代理配置"""
    row = query_one("SELECT value FROM settings WHERE key = 'kol_proxy'")
    proxy = row["value"] if row else ""
    return {"proxy": proxy, "configured": bool(proxy)}


class ProxyBody(BaseModel):
    proxy: str


@router.put("/proxy")
def set_proxy_config(body: ProxyBody):
    """设置爬虫代理（如 socks5://127.0.0.1:1080）"""
    proxy = body.proxy.strip()
    if proxy:
        execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('kol_proxy', ?)",
            (proxy,),
        )
    else:
        execute("DELETE FROM settings WHERE key = 'kol_proxy'")
    return {"proxy": proxy, "message": "代理已保存" if proxy else "代理已清除"}
