"use client"

import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"
import type { ReviewItem } from "@/lib/api-types"

/**
 * 最新复盘分析结果。
 */
export function useLatestReview() {
  return useSWR<ReviewItem[]>("/api/stocks/reviews?limit=1", swrFetcher, {
    dedupingInterval: 60000,
    revalidateOnFocus: false,
  })
}

/**
 * 最近 N 份历史复盘报告。
 */
export function useReviewHistory(limit: number = 10) {
  return useSWR<ReviewItem[]>(
    `/api/stocks/reviews?limit=${limit}`,
    swrFetcher,
    { dedupingInterval: 60000, revalidateOnFocus: false }
  )
}
