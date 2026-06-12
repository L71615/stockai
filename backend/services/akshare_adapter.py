"""数据适配层 — 腾讯财经 API + 内存缓存

东方财富 push2 API 已全面封锁非浏览器 TLS 指纹（2026-05-26 起），
本地和 VM 均无法访问。改用腾讯财经 API（qt.gtimg.cn / web.ifzq.gtimg.cn）。
"""

import json
import re
import time
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ==================== 缓存 ====================

_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
_QUOTE_TTL = 3.0

_KLINE_CACHE: dict[str, tuple[float, dict]] = {}
_KLINE_TTL = 300.0

_INDEX_CACHE: dict[str, tuple[float, dict]] = {}
_INDEX_TTL = 3.0

_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_TTL = 300.0

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _http_get(url: str, timeout: int = 10, encoding: str = "gbk") -> str:
    """发起 HTTP GET 请求，返回解码后的文本"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors="replace")


def _symbol(code: str) -> str:
    """个股代码转腾讯格式 sh600519 / sz000001"""
    c = code.strip()
    # 沪市：60xxxx(主板), 68xxxx(科创板), 51xxxx(ETF), 56xxxx(ETF), 58xxxx(ETF)
    if c.startswith(("51", "56", "58", "60", "68")):
        return f"sh{c}"
    return f"sz{c}"


# ==================== 个股行情 ====================

def _parse_tencent_quote(raw: str) -> Optional[dict]:
    """解析腾讯行情返回（个股或指数）"""
    m = re.search(r'="(.+)"', raw)
    if not m:
        return None
    parts = m.group(1).split("~")
    if len(parts) < 6:
        return None

    try:
        # 指数格式：0市场 1名称 2代码 3当前价 4涨跌额 5涨跌幅 ...
        # 个股格式：0市场 1名称 2代码 3当前价 4昨收 5今开 ... 31涨跌额 32涨跌幅 33最高 34最低 ...
        if len(parts) < 30:
            # 指数格式（精简字段）
            return {
                "name": parts[1],
                "code": parts[2],
                "price": _f(parts[3]),
                "change": _f(parts[4]),
                "change_pct": _f(parts[5]),
                "source": "tencent",
            }
        else:
            # 个股格式（完整字段）
            return {
                "name": parts[1],
                "code": parts[2],
                "price": _f(parts[3]),
                "yesterday_close": _f(parts[4]),
                "open": _f(parts[5]),
                "volume": _f(parts[6]),
                "change": _f(parts[31]),
                "change_pct": _f(parts[32]),
                "high": _f(parts[33]),
                "low": _f(parts[34]),
                "amount": _f(parts[37]),
                "turnover": _f(parts[38]),
                "source": "tencent",
            }
    except (ValueError, IndexError):
        return None


def get_quote(code: str) -> Optional[dict]:
    """获取单只股票实时行情"""
    now = time.time()
    if code in _QUOTE_CACHE:
        ts, data = _QUOTE_CACHE[code]
        if now - ts < _QUOTE_TTL:
            return data

    try:
        raw = _http_get(f"https://qt.gtimg.cn/q={_symbol(code)}")
        result = _parse_tencent_quote(raw)
        if result:
            _QUOTE_CACHE[code] = (now, result)
            return result
    except Exception as e:
        logger.warning(f"get_quote({code}): {e}")
    return None


def get_stock_name(code: str) -> str:
    """获取股票名称"""
    q = get_quote(code)
    return q["name"] if q else ""


# 腾讯 API 全球指数符号映射: 短代码 → (腾讯符号, 名称, 地区)
_TENCENT_GLOBAL_MAP: dict[str, tuple[str, str, str]] = {
    # A股
    "000001": ("s_sh000001", "上证指数", "中国"),
    "399001": ("s_sz399001", "深证成指", "中国"),
    "399006": ("s_sz399006", "创业板指", "中国"),
    # 港股
    "HSI":    ("s_hkHSI",  "恒生指数", "中国香港"),
    # 美股
    "IXIC":   ("s_usIXIC", "纳斯达克", "美国"),
    "INX":    ("s_usINX",  "标普500",  "美国"),
    "DJI":    ("s_usDJI",  "道琼斯",   "美国"),
}


def get_global_indices() -> list[dict]:
    """获取全球主要指数行情（腾讯 API 批量请求）

    腾讯 API 支持约 7 个全球指数（A股3 + 港股1 + 美股3）。
    其余指数（日经/韩国/欧洲/印度/巴西/新加坡/台湾）暂无免费数据源，
    stocks.py 的 get_global_indices 会为缺失指数生成 price=null 的占位卡片。
    """
    if not _TENCENT_GLOBAL_MAP:
        return []

    now = time.time()
    results: list[dict] = []
    uncached_symbols: list[str] = []
    uncached_codes: list[str] = []

    # 检查缓存
    for short_code, (tencent_sym, name, region) in _TENCENT_GLOBAL_MAP.items():
        if short_code in _INDEX_CACHE:
            ts, data = _INDEX_CACHE[short_code]
            if now - ts < _INDEX_TTL:
                results.append(_make_index_result(short_code, name, region, data))
                continue
        uncached_symbols.append(tencent_sym)
        uncached_codes.append(short_code)

    if not uncached_symbols:
        return results

    # 批量请求腾讯 API（换行分隔多个返回值）
    try:
        syms = ",".join(uncached_symbols)
        raw = _http_get(f"https://qt.gtimg.cn/q={syms}", encoding="gbk")
        lines = raw.strip().split("\n")

        # 解析每一行，建立 规范化代码 → 行情 的临时映射
        # 注意：美国指数返回的 code 带前导 "."（如 ".IXIC"），需要 strip
        sym_to_quote: dict[str, dict] = {}
        for line in lines:
            q = _parse_tencent_quote(line)
            if q:
                raw_code = q.get("code", "")
                normalized = raw_code.lstrip(".")  # .IXIC → IXIC, HSI → HSI
                sym_to_quote[normalized] = q

        # 匹配回 uncached 列表
        for i, short_code in enumerate(uncached_codes):
            q = sym_to_quote.get(short_code)
            if q:
                _INDEX_CACHE[short_code] = (now, q)
                name, region = _TENCENT_GLOBAL_MAP[short_code][1], _TENCENT_GLOBAL_MAP[short_code][2]
                results.append(_make_index_result(short_code, name, region, q))
    except Exception as e:
        logger.warning(f"get_global_indices batch: {e}")

    return results


def _make_index_result(code: str, name: str, region: str, quote: dict) -> dict:
    """组装标准化的指数结果"""
    return {
        "code": code,
        "name": quote.get("name") or name,
        "region": region,
        "price": quote.get("price"),
        "change": quote.get("change"),
        "change_pct": quote.get("change_pct"),
    }


# ==================== K 线 ====================

def get_kline(code: str, days: int = 120) -> dict:
    """获取日 K 线数据（腾讯前复权 JSON API）"""
    cache_key = f"{code}:{days}"
    now = time.time()
    if cache_key in _KLINE_CACHE:
        ts, data = _KLINE_CACHE[cache_key]
        if now - ts < _KLINE_TTL:
            return data

    try:
        sym = _symbol(code)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{days},qfq"
        raw = _http_get(url, encoding="utf-8")
        data = json.loads(raw)

        if data.get("code") != 0:
            return {"error": "无K线数据", "code": code}

        klines = data.get("data", {}).get(sym, {}).get("qfqday", [])
        if not klines:
            klines = data.get("data", {}).get(sym, {}).get("day", []) or []

        if not klines:
            return {"error": "无K线数据", "code": code}

        dates = [k[0] for k in klines[-days:]]
        opens = [float(k[1]) for k in klines[-days:]]
        closes = [float(k[2]) for k in klines[-days:]]
        highs = [float(k[3]) for k in klines[-days:]]
        lows = [float(k[4]) for k in klines[-days:]]

        result = {
            "code": code,
            "dates": dates,
            "opens": opens,
            "closes": closes,
            "highs": highs,
            "lows": lows,
        }
        _KLINE_CACHE[cache_key] = (now, result)
        return result
    except Exception as e:
        logger.warning(f"get_kline({code}): {e}")
        return {"error": f"获取K线失败: {e}", "code": code}


# ==================== 搜索 ====================

def search_stock(keyword: str) -> list[dict]:
    """搜索股票代码/名称（腾讯智能选股 API）"""
    kw = keyword.strip()
    cache_key = kw.upper()
    now = time.time()
    if cache_key in _SEARCH_CACHE:
        ts, data = _SEARCH_CACHE[cache_key]
        if now - ts < _SEARCH_TTL:
            return data

    results = []
    try:
        import urllib.parse
        encoded = urllib.parse.quote(kw)
        url = f"https://smartbox.gtimg.cn/s3/?q={encoded}&t=all&c=2"
        raw = _http_get(url, encoding="utf-8")
        # 格式: v_hint="sh~600519~贵州茅台~gzmt~GP-A"
        m = re.search(r'v_hint="(.+)"', raw)
        if m:
            items = m.group(1).split("^")
            for item in items:
                parts = item.split("~")
                if len(parts) >= 3:
                    code = parts[1].strip()
                    name = parts[2].strip()
                    # 处理 unicode 转义
                    name = name.encode().decode('unicode_escape') if '\\u' in name else name
                    mkt = _market_label(code)
                    at = _detect_type(code)
                    if code:
                        results.append({
                            "code": code, "name": name,
                            "market": mkt, "asset_type": at,
                        })
    except Exception as e:
        logger.warning(f"search_stock({keyword}): {e}")

    results = results[:8]
    _SEARCH_CACHE[cache_key] = (now, results)
    return results


# ==================== 行业信息 ====================

_INDUSTRY_CACHE: dict[str, tuple[float, dict]] = {}
_INDUSTRY_TTL = 3600.0


def get_stock_info(code: str) -> Optional[dict]:
    """获取股票基本信息（名称，行业信息腾讯 API 不提供，返回空）"""
    now = time.time()
    if code in _INDUSTRY_CACHE:
        ts, data = _INDUSTRY_CACHE[code]
        if now - ts < _INDUSTRY_TTL:
            return data

    q = get_quote(code)
    if q:
        result = {
            "code": code, "name": q.get("name", ""),
            "industry": "", "region": "", "concepts": "",
        }
        _INDUSTRY_CACHE[code] = (now, result)
        return result
    return None


# ==================== 辅助 ====================

def _f(val) -> Optional[float]:
    """安全转 float，空字符串返回 None"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _detect_type(code: str) -> str:
    from services.utils import detect_asset_type
    return detect_asset_type(code)


def _market_label(code: str) -> str:
    if code.startswith(("60", "68")):
        return "SH"
    if code.startswith(("00", "30", "39")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"
