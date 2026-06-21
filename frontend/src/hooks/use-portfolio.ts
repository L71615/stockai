"use client"

import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"
import type { DiversificationResponse, PortfolioData, PortfolioHistoryResponse } from "@/lib/api-types"

/**
 * 持仓数据 hook，30s 自动刷新，页面间共享缓存。
 */
export function usePortfolio() {
  return useSWR<PortfolioData>(
    "/api/stocks/holdings/with-pnl",
    swrFetcher,
    { refreshInterval: 30000, dedupingInterval: 5000 }
  )
}

/**
 * 持仓历史走势，不自动轮询。
 */
export function usePortfolioHistory() {
  return useSWR<PortfolioHistoryResponse>("/api/stocks/holdings/history", swrFetcher, {
    dedupingInterval: 60000,
    revalidateOnFocus: false,
  })
}

/**
 * 行业/市场分散度。
 */
export function useDiversification() {
  return useSWR<DiversificationResponse>("/api/stocks/diversification", swrFetcher, {
    dedupingInterval: 60000,
    revalidateOnFocus: false,
  })
}
