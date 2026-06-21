"use client"

import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"
import type { WatchlistItem } from "@/lib/api-types"

/**
 * 自选股列表。
 */
export function useWatchlist() {
  return useSWR<WatchlistItem[]>("/api/stocks/watchlist", swrFetcher, {
    dedupingInterval: 5000,
  })
}
