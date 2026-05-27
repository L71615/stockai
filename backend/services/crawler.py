"""StockAI — 网页爬取服务（BeautifulSoup 版）"""

import httpx
from bs4 import BeautifulSoup
from config import CRAWLER_UA, CRAWLER_TIMEOUT


async def fetch_page(url: str) -> str:
    """抓取网页 HTML"""
    async with httpx.AsyncClient(
        headers={"User-Agent": CRAWLER_UA}, timeout=CRAWLER_TIMEOUT, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def extract_text(html: str, limit: int = 8000) -> str:
    """从 HTML 提取正文文本"""
    soup = BeautifulSoup(html, "html.parser")

    # 移除干扰元素
    for tag in soup.find_all(["script", "style", "nav", "footer", "iframe"]):
        tag.decompose()

    # 移除常见广告/评论区
    for cls in ["ad", "comment", "sidebar", "recommend"]:
        for tag in soup.find_all(class_=lambda c: c and cls in c.lower() if c else False):
            tag.decompose()

    text = soup.body.get_text(separator="\n", strip=True) if soup.body else ""
    # 合并空行
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)[:limit]


async def fetch_stock_news(code: str) -> str:
    """爬取东方财富个股新闻"""
    url = f"https://so.eastmoney.com/news/s?keyword={code}"
    html = await fetch_page(url)
    return extract_text(html)


async def fetch_dragon_tiger() -> str:
    """爬取龙虎榜数据"""
    url = "https://data.eastmoney.com/stock/tradedetail.html"
    html = await fetch_page(url)
    return extract_text(html)
