"""X (Twitter) 爬虫适配器 — Playwright 方案

用真实浏览器拦截 X 的 GraphQL 数据包，比直接调 API 更稳定。
模拟真人浏览行为：慢速滚动 + 随机停顿。
"""

import json
import time
import random

from database import query_all, execute


def _extract_tweets_from_response(response_body: str, username: str) -> list[dict]:
    """从 X GraphQL UserTweets 响应中提取推文"""
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError:
        return []

    posts = []
    try:
        result = data.get("data", {}).get("user", {}).get("result", {})

        # 尝试多种路径找到 instructions
        entries = []
        for path_try in [
            lambda r: r.get("timeline_v2", {}).get("timeline", {}).get("instructions", []),
            lambda r: r.get("timeline", {}).get("timeline", {}).get("instructions", []),
            lambda r: r.get("timeline", {}).get("instructions", []),
        ]:
            try:
                entries = path_try(result)
                if entries:
                    break
            except Exception:
                continue
    except Exception:
        return posts

    for instruction in entries:
        # Skip non-content instructions
        if instruction.get("type") == "TimelineClearCache":
            continue

        # entries 可能是复数 (TimelineAddEntries) 或单数 entry
        entry_list = instruction.get("entries", [])
        if not entry_list:
            single = instruction.get("entry")
            if single:
                entry_list = [single]

        for entry in entry_list:
            if len(posts) >= 50:  # 硬限制，保护
                break

            content = entry.get("content", {})
            item = content.get("itemContent", {})
            tweet = item.get("tweet_results", {}).get("result", {})
            if not tweet or tweet.get("__typename") == "TweetWithVisibilityResults":
                tweet = tweet.get("tweet", {})

            legacy = tweet.get("legacy", {})
            if not legacy:
                continue

            post_id = tweet.get("rest_id") or legacy.get("id_str", "")
            full_text = legacy.get("full_text", "") or legacy.get("text", "")

            posts.append({
                "username": username,
                "post_id": str(post_id),
                "content": full_text,
                "posted_at": legacy.get("created_at", ""),
                "likes": legacy.get("favorite_count", 0) or 0,
                "retweets": legacy.get("retweet_count", 0) or 0,
                "replies": legacy.get("reply_count", 0) or 0,
            })

    return posts



import os as _os

def _get_cookies() -> list[dict]:
    """从文件加载 X.com cookies（JSON 格式）"""
    cookie_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'data', 'x_cookies.json')
    if not _os.path.exists(cookie_file):
        return []
    try:
        with open(cookie_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _get_proxy() -> str | None:
    import os
    proxy = os.getenv("KOL_PROXY", "").strip()
    if proxy:
        return proxy
    try:
        from database import query_one
        row = query_one("SELECT value FROM settings WHERE key = 'kol_proxy'")
        if row and row.get("value"):
            return row["value"].strip()
    except Exception:
        pass
    return None


def crawl_account(username: str, max_posts: int = 20) -> tuple[list[dict], str]:
    """用 Playwright 打开 X 用户主页，拦截数据包，提取推文

    返回: (posts, error_msg)
    """
    from playwright.sync_api import sync_playwright

    screen_name = username.lstrip("@")
    target_url = f"https://x.com/{screen_name}"
    captured_responses: list[str] = []

    try:
        with sync_playwright() as p:
            # 启动无头浏览器
            browser = p.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            # 加载已保存的 X.com cookies
            saved_cookies = _get_cookies()
            if saved_cookies:
                context.add_cookies(saved_cookies)

            page = context.new_page()

            launch_args = {"headless": True}
            proxy = _get_proxy()
            if proxy:
                launch_args["proxy"] = {"server": proxy}
            browser = p.chromium.launch(**launch_args)
            def intercept_response(response):
                url = response.url
                if response.status == 200 and ("graphql" in url or "UserTweets" in url or "TweetDetail" in url or "HomeTimeline" in url):
                    try:
                        body = response.text()
                        if body and len(body) > 100:
                            captured_responses.append(body)
                    except Exception:
                        pass

            page.on("response", intercept_response)

            # 打开目标页面
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass  # X 后台请求永不停止，超时正常


            page.wait_for_timeout(3000)  # 等待 GraphQL 数据包加载

            # 模拟真人滚动，触发加载更多
            for i in range(4):
                time.sleep(random.uniform(1.5, 2.5))
                page.evaluate("window.scrollBy(0, 800)")
                time.sleep(random.uniform(0.5, 1.5))

                # 检查是否已够
                seen_ids = set()
                for resp_body in captured_responses:
                    for post in _extract_tweets_from_response(resp_body, screen_name):
                        seen_ids.add(post["post_id"])
                if len(seen_ids) >= max_posts:
                    break

            browser.close()

            # 合并所有拦截到的推文，去重
            seen_ids = set()
            all_posts = []
            for resp_body in captured_responses:
                for post in _extract_tweets_from_response(resp_body, screen_name):
                    if post["post_id"] not in seen_ids:
                        seen_ids.add(post["post_id"])
                        all_posts.append(post)

            if all_posts:
                return all_posts[:max_posts], ""
            else:
                return [], "PLAYWRIGHT: 未拦截到数据包"

    except Exception as e:
        error_str = str(e)
        if "net::ERR" in error_str or "Timeout" in error_str or "Tunnel" in error_str:
            return [], "网络不通。如果你在中国大陆，请配置代理后重试"
        return [], f"Playwright 错误: {error_str[:200]}"


def crawl_all(user_id: int = 1, max_posts_per_account: int = 20) -> dict:
    """爬取所有活跃账号并保存帖子"""
    accounts = query_all(
        "SELECT * FROM kol_accounts WHERE user_id = ? AND active = 1",
        (user_id,),
    )

    if not accounts:
        return {"total_posts": 0, "accounts_crawled": 0, "accounts_failed": 0, "errors": []}

    total_posts = 0
    accounts_crawled = 0
    accounts_failed = 0
    errors = []

    for account in accounts:
        username = account["username"]
        posts, error = crawl_account(username, max_posts_per_account)

        if posts:
            saved = 0
            for post in posts:
                try:
                    result = execute(
                        """INSERT OR IGNORE INTO kol_posts
                           (username, post_id, content, posted_at, likes, retweets, replies)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            post["username"], post["post_id"], post["content"][:5000],
                            post["posted_at"], post["likes"], post["retweets"],
                            post["replies"],
                        ),
                    )
                    if result["changes"] > 0:
                        saved += 1
                except Exception:
                    pass

            execute("UPDATE kol_accounts SET last_error = '' WHERE id = ?", (account["id"],))
            total_posts += saved
            accounts_crawled += 1
        else:
            _mark_error(account, error)
            accounts_failed += 1
            errors.append(f"{username}: {error}")

    return {
        "total_posts": total_posts,
        "accounts_crawled": accounts_crawled,
        "accounts_failed": accounts_failed,
        "errors": errors,
    }


def _mark_error(account: dict, msg: str):
    execute("UPDATE kol_accounts SET last_error = ? WHERE id = ?", (msg[:200], account["id"]))
