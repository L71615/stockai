"""数据源 Provider 抽象层

目标: 把"screener 拉股票基本信息" / "脚本拉 K 线" 调用抽成可插拔接口，
      上层用 Chain 声明 fallback 顺序，加新源只需写一个新 provider 接进来。

子模块:
    base     - Protocol + 数据类
    chain    - Chain 实现 (按优先级尝试，失败切下一个)
    tushare  - Tushare MCP (stock_basic 全市场 / 历史 K 线)
    akshare  - Akshare (实时行情批量 / 全市场代码+名 / 历史 K 线)
    baostock - Baostock (历史 K 线 / 行业代码 industry_type)

调用示例:
    from services.providers import preheat_via_chain, backfill_via_chain
    preheat_via_chain(codes)        # 跑一次 screener 预热 (Tushare → Akshare)
    backfill_via_chain()             # 全市场补全 (Tushare → Akshare + Baostock industry)
"""
from .base import StockInfo, KLine, StockInfoProvider, KLineProvider
from .chain import StockInfoChain, KLineChain

# Provider 实现
from .tushare import TushareStockInfoProvider, TushareKLineProvider
from .akshare import AkshareStockInfoProvider, AkshareKLineProvider
from .baostock import BaostockIndustryProvider, BaostockKLineProvider


def build_stock_info_chain() -> StockInfoChain:
    """默认 Chain: Tushare (主) → Akshare (name 兜底) → Baostock (仅 industry 补充)"""
    return StockInfoChain([
        TushareStockInfoProvider(),
        AkshareStockInfoProvider(),
        BaostockIndustryProvider(),  # 仅在缺 industry 时叠加
    ])


def build_kline_chain() -> KLineChain:
    """默认 Chain: Tushare (主, 1次调用拉单只) → Baostock (兜底) → Akshare (兜底)"""
    return KLineChain([
        TushareKLineProvider(),     # 1 次 MCP 调用拉 1 只 ~250 交易日 (~0.4s/只)
        BaostockKLineProvider(),    # 1.5s/只, 稳定兜底
        AkshareKLineProvider(),     # ~0.4s/只, 最后兜底
    ])


# ─── 兼容旧调用方的辅助函数 ───────────────────────────────────────

def preheat_via_chain(codes: list[str] | None = None) -> dict:
    """批量预热 stock_info 表，把 codes 范围内的股票基本信息写入 DB。

    适用场景: screener 扫描 500 只股前一次性预热，避免单只循环查询。
    返回: {"written": int, "total": int, "source": str, "error": str | None}
    """
    from database import execute_many

    chain = build_stock_info_chain()
    items, stats = chain.fetch_all()
    source_name = stats.get("source", "none")

    if not items:
        return {
            "written": 0, "total": 0,
            "source": source_name,
            "error": "all providers empty/failed",
        }

    # 限定 codes（如果有）
    code_set = set(codes) if codes else None

    # 1) 行业叠加：若 items 中的 industry 为空，从 Baostock industry_map 补
    need_industry = [
        (it.code) for it in items
        if not it.industry and (code_set is None or it.code in code_set)
    ]
    if need_industry:
        try:
            bs_map = BaostockIndustryProvider().fetch_all()
            ind_by_code = {it.code: it.industry for it in bs_map if it.industry}
            for it in items:
                if not it.industry and it.code in ind_by_code:
                    it.industry = ind_by_code[it.code]
        except Exception:
            pass

    # 2) 过滤 + 组装 INSERT 批
    statements: list[tuple[str, tuple]] = []
    skipped = 0
    for it in items:
        if code_set and it.code not in code_set:
            continue
        if not it.name:
            skipped += 1
            continue
        # 脏数据兜底：industry == name 时 industry 视为空（已知 Baostock bug）
        industry = it.industry
        if industry and industry == it.name:
            industry = ""
        statements.append((
            "INSERT OR REPLACE INTO stock_info (stock_code, name, industry, list_date) VALUES (?, ?, ?, ?)",
            (it.code, it.name, industry, it.list_date),
        ))

    if not statements:
        return {"written": 0, "total": len(items), "source": source_name,
                "skipped": skipped, "error": None}

    try:
        execute_many(statements)
        return {"written": len(statements), "total": len(items),
                "source": source_name, "skipped": skipped, "error": None}
    except Exception as e:
        return {"written": 0, "total": len(items),
                "source": source_name, "skipped": skipped, "error": str(e)}


def backfill_via_chain() -> dict:
    """一次性全市场补全 stock_info 表（全量数据源组合 Tushare→Akshare+Baostock industry）。

    与 preheat_via_chain 区别: preheat 限定 codes，backfill 不限（全市场）。
    返回: {"written": int, "total": int, "source": str, "industry_filled": int, "error": str | None}
    """
    result = preheat_via_chain(codes=None)
    # 计算 industry_filled 供上层诊断
    if result.get("error"):
        return {**result, "industry_filled": 0}

    from database import query_one
    filled = query_one("SELECT COUNT(*) AS n FROM stock_info WHERE industry != ''")
    return {**result, "industry_filled": filled["n"] if filled else 0}
