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


def get_batch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量获取实时行情 — 一次 HTTP 请求查多只股票"""
    now = time.time()
    result_map: dict[str, dict] = {}
    uncached: list[str] = []

    for code in codes:
        if code in _QUOTE_CACHE:
            ts, data = _QUOTE_CACHE[code]
            if now - ts < _QUOTE_TTL:
                result_map[code] = data
                continue
        uncached.append(code)

    if not uncached:
        return result_map

    # 分批（腾讯 API 限制约 50 个/次）
    BATCH = 50
    for i in range(0, len(uncached), BATCH):
        chunk = uncached[i:i + BATCH]
        symbols = ",".join(_symbol(c) for c in chunk)
        try:
            raw = _http_get(f"https://qt.gtimg.cn/q={symbols}")
            # 返回多行，每行格式: v_symbol="...~...~..."
            for line in raw.strip().split("\n"):
                if '="' not in line:
                    continue
                # 提取 symbol: v_s_sh600519="..."
                match = re.search(r'v_(\w+)="([^"]*)"', line)
                if match:
                    sym = match.group(1)
                    # 重建完整行格式让 _parse_tencent_quote 解析
                    full_line = f'v_{sym}="{match.group(2)}"'
                    # 反向查找 code
                    for c in chunk:
                        if _symbol(c) == sym:
                            result = _parse_tencent_quote(full_line)
                            if result:
                                result["code"] = c  # 确保 code 正确
                                _QUOTE_CACHE[c] = (now, result)
                                result_map[c] = result
                            break
        except Exception as e:
            logger.warning(f"get_batch_quotes chunk {i}: {e}")
            # 回退到单个查询
            for c in chunk:
                q = get_quote(c)
                if q:
                    result_map[c] = q

    return result_map


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
        volumes = [float(k[5]) for k in klines[-days:]]

        result = {
            "code": code,
            "dates": dates,
            "opens": opens,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
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


# ==================== 基本面数据（akshare HTTP，无锁可并发） ====================

_FIN_HTTP_CACHE: dict[str, tuple[float, dict]] = {}
_FIN_HTTP_TTL = 7200.0  # 2 小时


def get_stock_factors_http(code: str) -> dict | None:
    """通过 akshare HTTP 获取基本面数据（EPS/ROE/BVPS/prev_eps）

    无全局锁，多线程可真正并发。失败返回 None，调用方应回退到 Baostock。
    """
    cache_key = f"fin_http:{code}"
    now = time.time()
    if cache_key in _FIN_HTTP_CACHE:
        ts, data = _FIN_HTTP_CACHE[cache_key]
        if now - ts < _FIN_HTTP_TTL:
            return data

    try:
        import akshare as ak
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if df is None or df.empty:
            return None

        # 列名映射（同花顺 → 标准字段）
        col_map = {
            "报告期": "date",
            "基本每股收益": "eps",
            "每股净资产": "bvps",
            "净资产收益率": "roe_pct",
            "归母净利润": "net_profit",
            "营业总收入": "revenue",
        }

        # 找到实际列名
        actual_cols: dict[str, int] = {}
        for i, c in enumerate(df.columns):
            for key in col_map:
                if key in str(c):
                    actual_cols[key] = i
                    break

        if "基本每股收益" not in actual_cols:
            return None

        def _val(row, key) -> float | None:
            """从行中安全提取数值（处理 '646.27亿' 这种格式）"""
            if key not in actual_cols:
                return None
            idx = actual_cols[key]
            raw = str(row[idx]) if idx < len(row) else ""
            if not raw or raw == "nan":
                return None
            # 处理带单位的值
            raw = raw.replace("亿", "e8").replace("万", "e4").replace("%", "").replace(",", "")
            try:
                return float(raw)
            except ValueError:
                return None

        rows = df.values
        if len(rows) < 1:
            return None

        # 最新一期
        latest = rows[-1]
        eps = _val(latest, "基本每股收益")
        roe_pct = _val(latest, "净资产收益率")
        bvps = _val(latest, "每股净资产")
        report_date = str(latest[actual_cols.get("报告期", 0)]) if "报告期" in actual_cols else ""

        if eps is None:
            return None

        # 季报数据年化（akshare 返回的是本期值，非 TTM）
        quarter = 4  # 默认 Q4（年报，不需要年化）
        if report_date and len(report_date) >= 10:
            month = int(report_date[5:7]) if report_date[4] == "-" else 0
            if month == 3:
                quarter = 1
            elif month == 6:
                quarter = 2
            elif month == 9:
                quarter = 3
        if quarter != 4:
            annual_factor = {1: 4.0, 2: 2.0, 3: 4.0 / 3.0}[quarter]
            eps = round(eps * annual_factor, 6)
            if roe_pct is not None:
                roe_pct = round(roe_pct * annual_factor, 2)

        result: dict = {
            "code": code,
            "eps": eps,
            "roe": roe_pct,
            "bvps": bvps,
            "source": "akshare",
        }

        # prev_eps：从更早期数据中取
        if len(rows) >= 2:
            prev_eps = None
            for i in range(len(rows) - 2, -1, -1):
                pe = _val(rows[i], "基本每股收益")
                if pe is not None and pe != eps:
                    prev_eps = pe
                    break
            if prev_eps:
                result["prev_eps"] = prev_eps

        _FIN_HTTP_CACHE[cache_key] = (now, result)
        return result

    except Exception:
        logger.warning("akshare_adapter: get_stock_factors_http failed for %s", code, exc_info=True)
        return None


# ==================== 北向资金 / 融资融券 / 机构持仓 ====================

_NORTH_FLOW_CACHE: dict[str, tuple[float, dict]] = {}
_NORTH_FLOW_TTL = 3600.0  # 1 小时

_INST_HOLD_CACHE: dict[str, tuple[float, dict]] = {}
_INST_HOLD_TTL = 7200.0  # 2 小时


def get_north_flow(code: str) -> dict | None:
    """获取个股北向资金净流入数据

    通过 akshare stock_hsgt_individual_em (沪深港通个股成交统计) 获取。
    Returns: {"net_flow": float (亿元), "buy_amount": float, "sell_amount": float} or None
    """
    cache_key = f"north:{code}"
    now = time.time()
    if cache_key in _NORTH_FLOW_CACHE:
        ts, data = _NORTH_FLOW_CACHE[cache_key]
        if now - ts < _NORTH_FLOW_TTL:
            return data

    try:
        import akshare as ak
        # akshare 1.18+ 沪深港通个股持股统计 (替代已删除的 stock_hsgt_individual_north_net_flow_in_em)
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df is None or df.empty:
            return None

        # 取最近一条记录：当日买卖资金 = 北向净买卖额（元）
        latest = df.iloc[-1]
        net_flow_yuan = float(latest.iloc[-3] if len(latest) >= 8 else 0)  # 当日买卖资金列

        result = {
            "net_flow": round(net_flow_yuan / 1e8, 4),  # 元 → 亿元
        }

        # 当日持股数量变化 (股)
        qty_change = float(latest.iloc[-4] if len(latest) >= 7 else 0)
        result["change_qty"] = int(qty_change)

        _NORTH_FLOW_CACHE[cache_key] = (now, result)
        return result

    except Exception as e:
        logger.warning(f"get_north_flow({code}): {e}")
        return None


def get_inst_holding(code: str) -> dict | None:
    """获取个股机构持仓变动数据

    Returns: {"hold_pct": float (持仓占比%), "change_pct": float (变动%)} or None
    """
    cache_key = f"inst:{code}"
    now = time.time()
    if cache_key in _INST_HOLD_CACHE:
        ts, data = _INST_HOLD_CACHE[cache_key]
        if now - ts < _INST_HOLD_TTL:
            return data

    try:
        import akshare as ak
        import datetime
        # akshare 1.18+ 机构持仓明细 (替代已删除的 stock_institute_hold_em)
        year = datetime.date.today().year
        df = None
        for q in (1, 4, 3, 2):  # 从当年Q1往前试
            for y in (year, year - 1):
                qtr = f"{y}{q}"
                try:
                    df = ak.stock_institute_hold_detail(stock=code, quarter=qtr)
                    if df is not None and not df.empty:
                        break
                except Exception:
                    continue
            if df is not None and not df.empty:
                break

        if df is None or df.empty:
            return None

        # 汇总所有机构的持股比例
        total_hold_pct = 0.0
        for _, row in df.iterrows():
            try:
                # 持股比例列（第7列，0-indexed = index 6）
                hold_pct = float(row.iloc[6]) if len(row) > 6 else 0
                total_hold_pct += hold_pct
            except (ValueError, TypeError):
                continue

        result = {"hold_pct": round(total_hold_pct, 4)}

        # 尝试取上一季度数据计算变动
        try:
            prev_q = q - 1 if q > 1 else 4
            prev_year = year if q > 1 else year - 1
            prev_qtr = f"{prev_year}{prev_q}"
            df_prev = ak.stock_institute_hold_detail(stock=code, quarter=prev_qtr)
            if df_prev is not None and not df_prev.empty:
                prev_total = 0.0
                for _, row in df_prev.iterrows():
                    try:
                        prev_total += float(row.iloc[6]) if len(row) > 6 else 0
                    except (ValueError, TypeError):
                        continue
                if prev_total > 0:
                    result["change_pct"] = round((total_hold_pct - prev_total) / prev_total, 6)
                elif total_hold_pct > 0:
                    result["change_pct"] = 1.0  # 从0到有持仓=100%增长
        except Exception:
            pass

        _INST_HOLD_CACHE[cache_key] = (now, result if result else None)
        return result if result else None

    except Exception as e:
        logger.warning(f"get_inst_holding({code}): {e}")
        return None


# ==================== 港股行情 ====================

_HK_KLINE_CACHE: dict[str, tuple[float, dict]] = {}
_HK_KLINE_TTL = 300.0  # 5 分钟


def get_hk_kline(code: str, days: int = 120) -> dict:
    """获取港股历史日 K 线（akshare 东方财富港股接口）"""
    cache_key = f"hk_kline:{code}:{days}"
    now = time.time()
    if cache_key in _HK_KLINE_CACHE:
        ts, data = _HK_KLINE_CACHE[cache_key]
        if now - ts < _HK_KLINE_TTL:
            return data

    try:
        import akshare as ak
        df = ak.stock_hk_hist(symbol=code, period="daily", start_date="", end_date="", adjust="qfq")
        if df is None or df.empty:
            return {"error": "无港股K线数据", "code": code}

        df = df.tail(days)
        dates = [str(d)[:10] for d in df["日期"].tolist()]
        opens = [float(o) for o in df["开盘"].tolist()]
        closes = [float(c) for c in df["收盘"].tolist()]
        highs = [float(h) for h in df["最高"].tolist()]
        lows = [float(l) for l in df["最低"].tolist()]

        result = {
            "code": code,
            "dates": dates,
            "opens": opens,
            "closes": closes,
            "highs": highs,
            "lows": lows,
        }
        _HK_KLINE_CACHE[cache_key] = (now, result)
        return result

    except Exception as e:
        logger.warning(f"get_hk_kline({code}): {e}")
        return {"error": f"获取港股K线失败: {e}", "code": code}


_HK_FACTORS_CACHE: dict[str, tuple[float, dict]] = {}
_HK_FACTORS_TTL = 7200.0  # 2 小时


def get_hk_factors(code: str) -> dict | None:
    """获取港股基本面数据（PE/ROE/EPS/市值等）"""
    cache_key = f"hk_factors:{code}"
    now = time.time()
    if cache_key in _HK_FACTORS_CACHE:
        ts, data = _HK_FACTORS_CACHE[cache_key]
        if now - ts < _HK_FACTORS_TTL:
            return data

    try:
        import akshare as ak
        df = ak.stock_hk_financial_indicator_em(symbol=code)
        if df is None or df.empty:
            return None

        latest = df.iloc[-1]
        result = {"code": code, "source": "akshare_hk"}

        col_map = {
            "基本每股收益": "eps",
            "每股净资产": "bvps",
            "净资产收益率": "roe",
            "市盈率": "pe",
            "市净率": "pb",
            "总市值": "market_cap",
        }

        for cn_name, en_name in col_map.items():
            for col in df.columns:
                if cn_name in str(col):
                    val = latest.get(col)
                    if val is not None and str(val) != "nan":
                        try:
                            result[en_name] = float(val)
                        except (ValueError, TypeError):
                            pass  # 字段类型转换失败，跳过该字段继续处理
                    break

        if "eps" not in result:
            return None

        _HK_FACTORS_CACHE[cache_key] = (now, result)
        return result

    except Exception as e:
        logger.warning(f"get_hk_factors({code}): {e}")
        return None


# ==================== 美股行情 ====================

_US_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
_US_QUOTE_TTL = 5.0
_US_KLINE_CACHE: dict[str, tuple[float, dict]] = {}
_US_KLINE_TTL = 300.0


def get_us_quote(code: str) -> dict | None:
    """获取美股实时行情（akshare 东方财富美股接口）"""
    cache_key = f"us_quote:{code}"
    now = time.time()
    if cache_key in _US_QUOTE_CACHE:
        ts, data = _US_QUOTE_CACHE[cache_key]
        if now - ts < _US_QUOTE_TTL:
            return data

    try:
        import akshare as ak
        df = ak.stock_us_spot_em()
        if df is None or df.empty:
            return None

        row = df[df["代码"].str.upper() == code.upper()]
        if row.empty:
            return None

        r = row.iloc[0]
        result = {
            "code": str(r.get("代码", code)),
            "name": str(r.get("名称", "")),
            "price": _f(r.get("最新价")),
            "change": _f(r.get("涨跌额")),
            "change_pct": _f(r.get("涨跌幅")),
            "high": _f(r.get("最高价")),
            "low": _f(r.get("最低价")),
            "source": "akshare_us",
        }
        _US_QUOTE_CACHE[cache_key] = (now, result)
        return result

    except Exception as e:
        logger.warning(f"get_us_quote({code}): {e}")
        return None


def get_us_kline(code: str, days: int = 120) -> dict:
    """获取美股历史日 K 线（akshare 东方财富美股接口）"""
    cache_key = f"us_kline:{code}:{days}"
    now = time.time()
    if cache_key in _US_KLINE_CACHE:
        ts, data = _US_KLINE_CACHE[cache_key]
        if now - ts < _US_KLINE_TTL:
            return data

    try:
        import akshare as ak
        df = ak.stock_us_hist(symbol=code, period="daily", start_date="", end_date="", adjust="qfq")
        if df is None or df.empty:
            return {"error": "无美股K线数据", "code": code}

        df = df.tail(days)
        dates = [str(d)[:10] for d in df["日期"].tolist()]
        opens = [float(o) for o in df["开盘"].tolist()]
        closes = [float(c) for c in df["收盘"].tolist()]
        highs = [float(h) for h in df["最高"].tolist()]
        lows = [float(l) for l in df["最低"].tolist()]

        result = {
            "code": code,
            "dates": dates,
            "opens": opens,
            "closes": closes,
            "highs": highs,
            "lows": lows,
        }
        _US_KLINE_CACHE[cache_key] = (now, result)
        return result

    except Exception as e:
        logger.warning(f"get_us_kline({code}): {e}")
        return {"error": f"获取美股K线失败: {e}", "code": code}
