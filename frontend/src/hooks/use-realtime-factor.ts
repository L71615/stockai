"use client"

/**
 * 盘中因子 hook — v5.0-alpha M2
 *
 * SWR 30s 拉一次 /api/realtime/factor/{code}
 * - names 参数: 可指定要看的因子子集, 留空 = 全部
 */

import useSWR from "swr"
import { apiGet } from "@/lib/auth"

export interface FactorResponse {
  code: string
  factors: Record<string, number | null>
  ts: number
  cached_count: number
  fresh_count: number
  bar_count: number
}

export function useRealtimeFactor(
  code: string | null | undefined,
  options?: {
    names?: string[]                 // 指定要看的因子子集
    refreshMs?: number               // 默认 30s
    enabled?: boolean
  }
): {
  factors: Record<string, number | null>
  isLoading: boolean
  lastUpdate: number
  cachedCount: number
  freshCount: number
  barCount: number
  error: Error | undefined
  refresh: () => void
} {
  const refreshMs = options?.refreshMs ?? 30000
  const enabled = options?.enabled !== false && !!code
  const namesParam = options?.names?.length ? `?names=${options.names.join(",")}` : ""

  const swrKey = enabled && code ? `/api/realtime/factor/${code}${namesParam}` : null

  const { data, isLoading, error, mutate } = useSWR<FactorResponse>(
    swrKey,
    (url) => apiGet<FactorResponse>(url),
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
    error,
    refresh: () => mutate(),
  }
}

// 常用因子分组(给前端 UI 用)
// key 用小写 — 与 factor_lab.FACTOR_REGISTRY 返回的 key 一致(v4.2 M2 修)
export const COMMON_FACTOR_GROUPS = {
  trend:   ["ma5", "ma10", "ma20", "ma60"],
  momentum: ["ret_5d", "ret_20d", "ret_60d"],
  tech:    ["rsi_14", "macd_signal", "boll_upper", "boll_lower", "boll_position"],
  volume:  ["vol_ma5", "vol_ma10", "vol_ratio"],
  volatility: ["volatility", "amplitude", "boll_position"],
}