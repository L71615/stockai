"use client"

import useSWR from "swr"
import { apiGet } from "@/lib/auth"
import type { PortfolioComparisonResponse, WindowKey } from "@/lib/api-types"

/**
 * v4.1 1B.4: 持仓 vs 影子组合差异 — SWR hook.
 *
 * @param window - 7d / 30d / 90d / 180d (默认 30d)
 * @returns { data, isLoading, error, refresh }
 */
export function usePortfolioComparison(window: WindowKey = "30d") {
  const key = `/api/stocks/holdings/shadow-comparison?window=${window}`

  const { data, error, isLoading, mutate } = useSWR<PortfolioComparisonResponse>(
    key,
    (url) => apiGet<PortfolioComparisonResponse>(url),
    {
      refreshInterval: 60_000,
      revalidateOnFocus: false,
      dedupingInterval: 30_000,
    },
  )

  return {
    data,
    isLoading,
    error,
    refresh: mutate,
  }
}