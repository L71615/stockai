"use client"

import useSWR from "swr"
import { apiGet } from "@/lib/auth"

export interface ShadowEquityPoint {
  date: string
  nav: number
  drawdown: number
  turnover: number
  costs: number
}

export interface ShadowEquityResponse {
  portfolio_id: number
  bucket: string
  points: ShadowEquityPoint[]
  count: number
  accumulating: boolean
  v4_metadata: { phase: string; days: number; bucket: string }
}

/**
 * v4.1 1B.2: 拉取 shadow portfolio 净值曲线.
 *
 * @param portfolioId  - shadow portfolio id; null 时不发送请求
 * @param bucket       - '1d' (默认) / '4h' / '1h'
 * @param days         - 回看天数, 默认 30
 */
export function useShadowEquity(
  portfolioId: number | null,
  bucket: "1d" | "4h" | "1h" = "1d",
  days: number = 30,
) {
  const key =
    portfolioId === null
      ? null
      : `/api/pipeline/shadow/equity-curve?portfolio_id=${portfolioId}&bucket=${bucket}&days=${days}`

  const { data, error, isLoading, mutate } = useSWR<ShadowEquityResponse>(
    key,
    (url) => apiGet<ShadowEquityResponse>(url),
    { refreshInterval: 60_000 },                 // 60s 自动刷新
  )

  return {
    data,
    points: data?.points ?? [],
    accumulating: data?.accumulating ?? true,
    isLoading,
    error,
    refresh: mutate,
  }
}