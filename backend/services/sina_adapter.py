"""数据适配层 — 新浪财经全球指数（补充腾讯未覆盖的指数）

新浪支持日经/富时/DAX/巴西等腾讯缺失的全球指数。
实时行情接口无需 API Key，返回 GBK 编码的 JS 变量。
"""

import re
import time
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ==================== 缓存 ====================

_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 5.0

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _http_get(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://finance.sina.com.cn/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", errors="replace")


# ==================== 新浪全球指数映射 ====================

# short_code → (新浪符号, 名称, 地区)
_SINA_GLOBAL_MAP: dict[str, tuple[str, str, str]] = {
    "N225":   ("int_nikkei",  "日经225",       "日本"),
    "FTSE":   ("int_ftse",    "英国富时100",   "英国"),
    "GDAXI":  ("int_dax30",   "德国DAX30",     "德国"),
    "BVSP":   ("int_bovespa", "巴西BOVESPA",   "巴西"),
    # 以下新浪也支持，但腾讯已覆盖，作为备用
    # "DJI": ("int_dji", "道琼斯", "美国"),
    # "INX": ("int_sp500", "标普500", "美国"),
    # "IXIC": ("int_nasdaq", "纳斯达克", "美国"),
}


def get_global_indices() -> list[dict]:
    """获取新浪支持的全球指数行情（批量请求）"""
    if not _SINA_GLOBAL_MAP:
        return []

    now = time.time()
    results: list[dict] = []
    uncached_codes: list[str] = []
    uncached_symbols: list[str] = []

    for short_code, (sina_sym, name, region) in _SINA_GLOBAL_MAP.items():
        cache_key = f"sina:{short_code}"
        if cache_key in _QUOTE_CACHE:
            ts, data = _QUOTE_CACHE[cache_key]
            if now - ts < _CACHE_TTL:
                results.append(_make_result(short_code, name, region, data))
                continue
        uncached_symbols.append(sina_sym)
        uncached_codes.append(short_code)

    if not uncached_symbols:
        return results

    try:
        syms = ",".join(uncached_symbols)
        raw = _http_get(f"https://hq.sinajs.cn/list={syms}")

        # 解析每行: var hq_str_int_nikkei="日经指数,44946.64,-408.35,-0.90";
        for i, line in enumerate(raw.strip().split("\n")):
            q = _parse_sina_quote(line)
            if q:
                short_code = uncached_codes[i] if i < len(uncached_codes) else ""
                if short_code:
                    cache_key = f"sina:{short_code}"
                    _QUOTE_CACHE[cache_key] = (now, q)
                    name, region = _SINA_GLOBAL_MAP[short_code][1], _SINA_GLOBAL_MAP[short_code][2]
                    results.append(_make_result(short_code, name, region, q))
    except Exception as e:
        logger.warning(f"get_global_indices(sina): {e}")

    return results


def _parse_sina_quote(line: str) -> Optional[dict]:
    """解析新浪行情行: var hq_str_XXX="名称,价格,涨跌额,涨跌幅";"""
    m = re.search(r'="(.+)"', line)
    if not m:
        return None
    parts = m.group(1).split(",")
    if len(parts) < 4 or not parts[1]:
        return None
    try:
        return {
            "name": parts[0],
            "price": float(parts[1]),
            "change": float(parts[2]) if parts[2] else None,
            "change_pct": float(parts[3]) if parts[3] else None,
        }
    except (ValueError, IndexError):
        return None


def _make_result(code: str, name: str, region: str, quote: dict) -> dict:
    return {
        "code": code,
        "name": quote.get("name") or name,
        "region": region,
        "price": quote.get("price"),
        "change": quote.get("change"),
        "change_pct": quote.get("change_pct"),
    }


# ==================== 港股行情 ====================

def get_hk_quote(code: str) -> Optional[dict]:
    """获取港股实时行情（新浪财经 rt_hk 接口）

    格式: var hq_str_rt_hk00700="英文名,中文名,最新价,今开,最高,最低,昨收,涨跌额,涨跌幅,..."
    """
    c = code.strip()
    cache_key = f"sina:hk:{c}"
    now = time.time()
    if cache_key in _QUOTE_CACHE:
        ts, data = _QUOTE_CACHE[cache_key]
        if now - ts < _CACHE_TTL:
            return data

    try:
        raw = _http_get(f"https://hq.sinajs.cn/list=rt_hk{c}")
        m = re.search(r'="(.+)"', raw)
        if not m:
            return None
        parts = m.group(1).split(",")
        if len(parts) < 9:
            return None

        result = {
            "code": code,
            "name": parts[1] if len(parts) > 1 else parts[0],
            "price": _f(parts[2]) if len(parts) > 2 else None,
            "open": _f(parts[3]) if len(parts) > 3 else None,
            "high": _f(parts[4]) if len(parts) > 4 else None,
            "low": _f(parts[5]) if len(parts) > 5 else None,
            "yesterday_close": _f(parts[6]) if len(parts) > 6 else None,
            "change": _f(parts[7]) if len(parts) > 7 else None,
            "change_pct": _f(parts[8]) if len(parts) > 8 else None,
            "source": "sina",
        }
        _QUOTE_CACHE[cache_key] = (now, result)
        return result
    except Exception as e:
        logger.warning(f"get_hk_quote({code}): {e}")
    return None


def _f(val) -> Optional[float]:
    """安全转 float"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
