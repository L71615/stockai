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
export const COMMON_FACTOR_GROUPS = {
  trend:   ["MA5", "MA10", "MA20", "MA60"],
  momentum: ["RET_5D", "RET_20D", "RET_60D"],
  tech:    ["RSI", "MACD", "BOLL_UPPER", "BOLL_LOWER", "BOLL_POSITION"],
  volume:  ["VOL_MA5", "VOL_MA10", "VOL_RATIO"],
  volatility: ["VOLATILITY", "AMPLITUDE", "BOLL_POSITION"],
}