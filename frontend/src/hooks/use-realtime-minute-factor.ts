"use client"

/**
 * 盘中分钟级 55 因子 hook — v4.2 M2
 *
 * SWR 30s 拉一次 /api/realtime/factor/{code}/minute
 * - names 参数: 可指定要看的因子子集, 留空 = 全部 55
 * - 与 useRealtimeFactor(v5.0-alpha M2 的 30 因子) 平行, 不冲突
 */

import useSWR from "swr"
import { apiGet } from "@/lib/auth"

export interface MinuteFactorResponse {
  code: string
  factors: Record<string, number | null>
  ts: number
  bar_count: number
  cached_count: number
  fresh_count: number
  data_source: string            // 'historical_daily_fallback' (M2 阶段) / 'futu_1m' (v5.0-rc)
}

export function useRealtimeMinuteFactor(
  code: string | null | undefined,
  options?: {
    names?: string[]             // 指定要看的因子子集
    refreshMs?: number           // 默认 30s
    enabled?: boolean
  }
): {
  factors: Record<string, number | null>
  isLoading: boolean
  lastUpdate: number
  cachedCount: number
  freshCount: number
  barCount: number
  dataSource: string
  error: Error | undefined
  refresh: () => void
} {
  const refreshMs = options?.refreshMs ?? 30000
  const enabled = options?.enabled !== false && !!code
  const namesParam = options?.names?.length ? `?names=${options.names.join(",")}` : ""

  const swrKey = enabled && code ? `/api/realtime/factor/${code}/minute${namesParam}` : null

  const { data, isLoading, error, mutate } = useSWR<MinuteFactorResponse>(
    swrKey,
    (url) => apiGet<MinuteFactorResponse>(url),
    {
      refreshInterval: refreshMs,
      revalidateOnFocus: false,
      keepPreviousData: true,
    }
  )

  return {
    factors: data?.factors ?? {},
    isLoading,
    lastUpdate: data?.ts ?? 0,
    cachedCount: data?.cached_count ?? 0,
    freshCount: data?.fresh_count ?? 0,
    barCount: data?.bar_count ?? 0,
    dataSource: data?.data_source ?? "",
    error,
    refresh: () => mutate(),
  }
}

// 55 因子分组(给前端 UI 用)
export const MINUTE_FACTOR_GROUPS: Record<string, string[]> = {
  价格: ["ma5", "ma10", "ma20", "ma60", "price_position", "high_low_ratio", "typical_price"],
  动量: ["ret_5d", "ret_20d", "ret_60d", "rsi_14", "macd_signal", "ma_disposition"],
  波动: ["hist_vol_5d", "hist_vol_20d", "atr_14", "amplitude_20d", "boll_upper", "boll_lower", "boll_position", "volatility_ratio", "bb_width"],
  成交量: ["vol_ma5", "vol_ma10", "vol_ma20", "vol_std", "vol_ratio"],
  量价: ["turnover_rate", "obv_divergence", "avg_amount", "vwap", "corr", "corr20"],
  K线形态: ["klen", "kup", "klow", "ksft", "kmid"],
  情绪: ["strength", "momentum_score", "acceleration"],
  资金: ["north_flow", "inst_change"],
}