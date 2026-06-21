"use client"

import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"

interface IndexData {
  code: string; name: string; region: string
  price: number | null; change: number | null; change_pct: number | null
}

/**
 * 全球指数行情（30s 自动刷新）
 */
export function useGlobalIndices() {
  return useSWR<IndexData[]>("/api/stocks/indices/global", swrFetcher, {
    refreshInterval: 30000,
    dedupingInterval: 5000,
  })
}
