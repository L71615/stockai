"""大佬观点服务 — 雪球热帖 + 财经 RSS → AI 每日情绪摘要

数据源:
  - 雪球热门关注（akshare stock_hot_tweet_xq）
  - 财经 RSS 源（feedparser）
  - AI 摘要（ai_service）
"""

import json
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_RSS_FEEDS = [
    ("华尔街见闻", "https://wallstreetcn.com/rss"),
    ("东方财富", "https://finance.eastmoney.com/rss"),
]

_KOL_CACHE: Optional[dict] = None
_KOL_TS = 0.0
_KOL_TTL = 1800.0


def fetch_rss_feeds(feeds=None) -> list[dict]:
    """抓取 RSS 标题"""
    if feeds is None:
        feeds = DEFAULT_RSS_FEEDS
    results = []
    try:
        import feedparser
    except ImportError:
        return [{"source": "error", "title": "feedparser 库未安装，请运行: pip install feedparser", "link": "", "published": ""}]

    for source, url in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                logger.warning(f"RSS {source} 解析异常: {feed.bozo_exception}")
                continue
            if not feed.entries:
                logger.warning(f"RSS {source} 无条目（可能源不可达）")
                continue
            for entry in feed.entries[:5]:
                results.append({
                    "source": source,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            logger.warning(f"RSS {source} 抓取失败: {e}")
    return results


def fetch_xueqiu_hot(limit: int = 15) -> list[dict]:
    """获取雪球热门关注"""
    results = []
    try:
        import akshare as ak
        df = ak.stock_hot_tweet_xq()
        if df is not None and not df.empty:
            for _, row in df.head(limit).iterrows():
                code = str(row.get("股票代码", "")).replace("SH", "").replace("SZ", "")
                name = str(row.get("股票简称", ""))
                follow = int(row.get("关注", 0) or 0)
                price = float(row.get("最新价", 0) or 0)
                results.append({
                    "code": code, "name": name,
                    "follow_count": follow, "price": price,
                })
    except Exception as e:
        logger.warning(f"雪球抓取失败: {e}")
    return results


async def _ai_summary(xueqiu_items: list, rss_items: list, provider: str = "") -> str:
    """AI 生成每日摘要"""
    if not xueqiu_items and not rss_items:
        return "📭 暂无数据"

    xq_text = ""
    for item in xueqiu_items[:10]:
        xq_text += f"- {item['name']}({item['code']}) 关注:{item['follow_count']:,}\n"

    rss_text = ""
    for item in rss_items[:10]:
        rss_text += f"- [{item['source']}] {item['title']}\n"

    prompt = f"""你是资深A股投资分析师。以下是今日市场热门数据，请生成一份简短的「大佬观点日报」：

【雪球热门关注 Top 10】
{xq_text}

【财经新闻 RSS】
{rss_text}

要求：
1. 1-2 句今日市场情绪总览
2. 社区最关注的 3-5 个方向和股票
3. 关键主题提炼
4. 语气像有经验的投资同行
5. 300 字以内，Markdown 格式，关键股票加粗"""

    try:
        from services.ai_service import ai_chat, get_default_provider
        p = provider or get_default_provider()
        result = await ai_chat(prompt, function="kol", provider=p,
            system_prompt="你是资深A股投资分析师，观点客观、语言精炼。")
        return result.strip()
    except Exception as e:
        top_names = [item['name'] for item in xueqiu_items[:5]]
        return f"## 今日市场关注\n\n社区热度 Top 5：{'、'.join(top_names)}。\n\n（AI 摘要生成中，请稍后刷新）"


async def generate_kol_report(provider: str = "") -> dict:
    """生成大佬观点日报"""
    global _KOL_CACHE, _KOL_TS
    now = time.time()
    if _KOL_CACHE and (now - _KOL_TS) < _KOL_TTL:
        return _KOL_CACHE

    xueqiu_items = fetch_xueqiu_hot(15)
    rss_items = fetch_rss_feeds()
    brief = await _ai_summary(xueqiu_items, rss_items, provider)

    _KOL_CACHE = {
        "brief": brief,
        "xueqiu_items": xueqiu_items,
        "rss_items": rss_items,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _KOL_TS = now
    return _KOL_CACHE


# ── 兼容旧路由的函数 ──

def generate_brief(user_id: int = 1) -> dict:
    """手动触发日报生成（同步包装）"""
    import asyncio
    try:
        return asyncio.run(generate_kol_report())
    except RuntimeError:
        # 已在事件循环中
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as ex:
            return ex.submit(asyncio.run, generate_kol_report()).result(timeout=30)


def get_latest_brief(user_id: int = 1) -> dict | None:
    """获取最新缓存日报"""
    global _KOL_CACHE, _KOL_TS
    now = time.time()
    if _KOL_CACHE and (now - _KOL_TS) < _KOL_TTL:
        return _KOL_CACHE
    # 尝试同步生成
    try:
        return generate_brief(user_id)
    except Exception:
        return {"brief": "📭 暂无日报", "xueqiu_items": [], "rss_items": [], "generated_at": ""}


def get_brief_by_date(brief_date: str, user_id: int = 1) -> dict | None:
    """获取指定日期日报（当前仅返回最新）"""
    return get_latest_brief(user_id)
