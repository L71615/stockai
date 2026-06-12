"""KOL 业务逻辑 — AI 日报生成

聚合帖子 → 构建 prompt → AI 调用 → JSON 解析 → 存储
使用 asyncio.run() 桥接同步入口与异步 AI 调用。
"""

import asyncio
import json
from datetime import datetime, date

from database import query_all, query_one, execute
from services.utils import parse_ai_json


def aggregate_posts(username_filter: str | None = None) -> list[dict]:
    """拉取最新日期的帖子，按账号分组、按互动量排序

    优先今天，今天没有则回退到最近有帖子的日期。
    """
    if username_filter:
        latest = query_one(
            "SELECT date(fetched_at) as d FROM kol_posts WHERE username = ? ORDER BY fetched_at DESC LIMIT 1",
            (username_filter,),
        )
    else:
        latest = query_one(
            "SELECT date(fetched_at) as d FROM kol_posts ORDER BY fetched_at DESC LIMIT 1"
        )

    if not latest or not latest["d"]:
        return []

    fetch_date = latest["d"]

    if username_filter:
        posts = query_all(
            """SELECT * FROM kol_posts
               WHERE username = ? AND date(fetched_at) = ?
               ORDER BY (likes + retweets * 2 + replies * 0.5) DESC""",
            (username_filter, fetch_date),
        )
    else:
        posts = query_all(
            """SELECT * FROM kol_posts
               WHERE date(fetched_at) = ?
               ORDER BY (likes + retweets * 2 + replies * 0.5) DESC""",
            (fetch_date,),
        )

    if not posts:
        return []

    # 按账号分组
    grouped: dict[str, list[dict]] = {}
    for p in posts:
        grouped.setdefault(p["username"], []).append(p)

    return [
        {"username": uname, "posts": plist, "count": len(plist)}
        for uname, plist in grouped.items()
    ]


def build_daily_brief_prompt(grouped_posts: list[dict]) -> str:
    """构建 AI 日报 prompt，嵌入结构化输出 JSON schema"""
    accounts_text_parts = []
    for g in grouped_posts:
        posts_text = "\n".join(
            f"  [{i+1}] {p['content'][:300]}\n"
            f"       ♥{p['likes']} 🔄{p['retweets']} 💬{p['replies']}"
            for i, p in enumerate(g["posts"][:10])
        )
        accounts_text_parts.append(
            f"### @{g['username']}（{g['count']} 条帖子）\n{posts_text}"
        )

    accounts_text = "\n\n".join(accounts_text_parts) if accounts_text_parts else "暂无帖子"

    prompt = f"""你是一位专业的 A 股/港股/美股投资分析师。以下是你追踪的投资大佬今日在 X (Twitter) 上发布的帖子汇总。请基于这些帖子生成一份结构化的每日投资观点简报。

## 今日帖子

{accounts_text}

## 输出要求

请严格按以下 JSON 结构输出（不要包含 markdown 代码块标记，直接输出 JSON 对象）：

{{
  "brief_date": "今天日期 YYYY-MM-DD",
  "one_liner": "一句话概要，总结今日核心观点（不超过 60 字）",
  "sentiment_overview": {{
    "bullish_ratio": 0.0-1.0 的小数，看多占比,
    "bearish_ratio": 0.0-1.0 的小数，看空占比,
    "neutral_ratio": 0.0-1.0 的小数，中性占比
  }},
  "key_topics": [
    {{
      "topic": "话题名称（如 半导体、新能源、AI 等）",
      "sentiment": "bullish / bearish / neutral",
      "mention_count": 整数，被提及的次数,
      "key_opinion": "核心观点一句话概括"
    }}
  ],
  "mentioned_stocks": [
    {{
      "code": "股票代码（6位A股/5位港股/美股ticker），如无法确定则为空字符串",
      "name": "股票名称",
      "mentions": 整数，被提及次数,
      "avg_sentiment": "bullish / bearish / neutral"
    }}
  ],
  "bull_case_summary": "多方主要论点（一段话，100 字以内）",
  "bear_case_summary": "空方主要论点（一段话，100 字以内）",
  "notable_quotes": [
    {{
      "username": "发帖人用户名",
      "quote": "引用的核心观点（不超过 100 字）",
      "why_notable": "为什么这条值得关注（一句话）"
    }}
  ],
  "raw_summary": "完整的 AI 总结文本（降级展示用，200-400 字）"
}}

请确保：
1. 输出是有效的 JSON（不要 markdown 代码块包裹）
2. key_topics 至少 1 条，最多 8 条
3. mentioned_stocks 只列出真正被提到的股票，不要编造
4. 情感判断要客观，不要因为帖子情绪强烈就全标 bullish/bearish
5. 如果帖子太少无法结构化分析，raw_summary 字段说明情况，其他字段放空值"""
    return prompt


def generate_brief(
    user_id: int = 1,
    provider: str = "",
    api_key: str = "",
    model: str = "",
) -> dict:
    """生成每日 AI 日报的同步入口（供 scheduler / API 调用）

    使用 asyncio.run() 包装异步 AI 调用。

    返回: 日报 dict，如果无帖子则返回 {"skipped": True}
    """
    # Step 1: 聚合帖子
    grouped = aggregate_posts()
    if not grouped:
        return {"skipped": True, "reason": "今日无帖子"}

    # Step 2: 获取活跃账号数
    accounts = query_all(
        "SELECT COUNT(*) as cnt FROM kol_accounts WHERE user_id = ? AND active = 1",
        (user_id,),
    )
    accounts_count = accounts[0]["cnt"] if accounts else 0

    # Step 3: 构建 prompt
    prompt = build_daily_brief_prompt(grouped)

    # Step 4: 同步桥接异步 AI 调用
    raw = _call_ai_sync(prompt, provider, api_key, model)

    # Step 5: 解析 AI 响应
    if not raw:
        # AI 完全失败——生成纯统计摘要
        parsed = {
            "brief_date": date.today().isoformat(),
            "one_liner": f"今日追踪 {accounts_count} 位大佬，共 {sum(g['count'] for g in grouped)} 条帖子。AI 分析暂不可用。",
            "sentiment_overview": {"bullish_ratio": 0, "bearish_ratio": 0, "neutral_ratio": 1.0},
            "key_topics": [],
            "mentioned_stocks": [],
            "bull_case_summary": "",
            "bear_case_summary": "",
            "notable_quotes": [],
            "raw_summary": "AI 调用失败，无法生成分析。请稍后重试。",
        }
    else:
        parsed = parse_ai_json(raw)
        if parsed.get("parse_error"):
            # JSON 解析失败——用 raw_summary 降级
            parsed = {
                "brief_date": date.today().isoformat(),
                "one_liner": f"今日追踪 {accounts_count} 位大佬，共 {sum(g['count'] for g in grouped)} 条帖子。",
                "sentiment_overview": {"bullish_ratio": 0, "bearish_ratio": 0, "neutral_ratio": 1.0},
                "key_topics": [],
                "mentioned_stocks": [],
                "bull_case_summary": "",
                "bear_case_summary": "",
                "notable_quotes": [],
                "raw_summary": raw,
            }

    # Step 6: 存储到 kol_daily_briefs
    ai_summary = parsed.get("raw_summary", raw or "")
    key_topics = json.dumps(parsed.get("key_topics", []), ensure_ascii=False)
    sentiment = json.dumps(parsed.get("sentiment_overview", {}), ensure_ascii=False)
    stocks = json.dumps(parsed.get("mentioned_stocks", []), ensure_ascii=False)

    total_posts = sum(g["count"] for g in grouped)

    execute(
        """INSERT OR REPLACE INTO kol_daily_briefs
           (user_id, brief_date, posts_count, accounts_count, ai_summary, key_topics, sentiment_overview, mentioned_stocks)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            parsed.get("brief_date", date.today().isoformat()),
            total_posts,
            accounts_count,
            ai_summary,
            key_topics,
            sentiment,
            stocks,
        ),
    )

    return {
        **parsed,
        "posts_count": total_posts,
        "accounts_count": accounts_count,
        "raw": raw,
    }


def _call_ai_sync(prompt: str, provider: str = "", api_key: str = "", model: str = "") -> str:
    """同步调用 AI——使用 asyncio.run() 桥接异步 ai_chat()"""
    from services.ai_service import ai_chat

    async def _do_call():
        try:
            return await asyncio.wait_for(
                ai_chat(
                    prompt,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    system_prompt="你是专业的投资分析师。请严格按 JSON 格式输出分析报告。",
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            # 重试一次
            try:
                return await asyncio.wait_for(
                    ai_chat(
                        prompt,
                        provider=provider,
                        api_key=api_key,
                        model=model,
                        system_prompt="你是专业的投资分析师。请严格按 JSON 格式输出分析报告。",
                    ),
                    timeout=60.0,
                )
            except Exception:
                return ""
        except Exception:
            return ""

    try:
        return asyncio.run(_do_call())
    except Exception:
        return ""


def get_latest_brief(user_id: int = 1) -> dict | None:
    """获取最新日报"""
    row = query_one(
        """SELECT * FROM kol_daily_briefs
           WHERE user_id = ?
           ORDER BY brief_date DESC LIMIT 1""",
        (user_id,),
    )
    if not row:
        return None

    result = dict(row)
    # 反序列化 JSON 字段
    for field in ["key_topics", "sentiment_overview", "mentioned_stocks"]:
        try:
            result[field] = json.loads(result.get(field, "[]"))
        except (json.JSONDecodeError, TypeError):
            result[field] = [] if field != "sentiment_overview" else {}

    return result


def get_brief_by_date(brief_date: str, user_id: int = 1) -> dict | None:
    """获取指定日期的日报"""
    row = query_one(
        "SELECT * FROM kol_daily_briefs WHERE user_id = ? AND brief_date = ?",
        (user_id, brief_date),
    )
    if not row:
        return None

    result = dict(row)
    for field in ["key_topics", "sentiment_overview", "mentioned_stocks"]:
        try:
            result[field] = json.loads(result.get(field, "[]"))
        except (json.JSONDecodeError, TypeError):
            result[field] = [] if field != "sentiment_overview" else {}

    return result
