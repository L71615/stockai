"use client"

/**
 * 实时行情 hook — v5.0-alpha M1
 *
 * 用 SWR 5s 高频轮询取 /api/realtime/watchlist
 * - 自动 join codes 成 comma-separated string 作为 cache key
 * - 返回 Map<code, Quote> 方便 O(1) 查询
 * - 返回 lastUpdate (server ts) 用于显示"X 秒前更新"
 *
 * v5.0-beta 升级路径:
 *   - 切 WebSocket 推送(避免 5s 延迟)
 *   - 加乐观更新(本地插 quote,后续校准)
 */

import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import { apiGet } from "@/lib/auth"

export interface Quote {
  code: string
  name: string
  price: number | null
  yesterday_close: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  amount: number | null
  change: number | null
  change_pct: number | null
  timestamp: number
  source: string
}

interface WatchlistResponse {
  quotes: Quote[]
  ts: number
  is_trading: boolean
  is_trading_day: boolean
}

export interface UseRealtimeQuoteResult {
  quotes: Map<string, Quote>
  isLoading: boolean
  lastUpdate: number
  isTradingHours: boolean
  isTradingDay: boolean
  refresh: () => void
}

export function useRealtimeQuote(
  codes: string[],
  options?: { refreshMs?: number; enabled?: boolean }
): UseRealtimeQuoteResult {
  const refreshMs = options?.refreshMs ?? 5000
  const enabled = options?.enabled !== false

  // SWR key: codes 排序去重后 join — 避免顺序差异触发不同 cache
  const sortedCodes = useMemo(() => {
    const set = new Set(codes.filter(Boolean))
    return Array.from(set).sort()
  }, [codes.join(",")])
  const codesKey = sortedCodes.join(",")

  const swrKey = enabled && codesKey ? `/api/realtime/watchlist?codes=${codesKey}` : null

  const { data, isLoading, mutate } = useSWR<WatchlistResponse>(
    swrKey,
    (url) => apiGet<WatchlistResponse>(url),
    {
      refreshInterval: refreshMs,
      revalidateOnFocus: false,
      keepPreviousData: true,
    }
  )

  const quotes = useMemo<Map<string, Quote>>(() => {
    const m = new Map<string, Quote>()
    if (data?.quotes) {
      for (const q of data.quotes) m.set(q.code, q)
    }
    return m
  }, [data])

  // 暴露 lastUpdate 用于 UI 显示(每次 SWR 重新拉都更新)
  const [lastUpdate, setLastUpdate] = useState(0)
  useEffect(() => {
    if (data?.ts) setLastUpdate(data.ts)
  }, [data?.ts])

  return {
    quotes,
    isLoading,
    lastUpdate,
    isTradingHours: data?.is_trading ?? false,
    isTradingDay: data?.is_trading_day ?? false,
    refresh: () => mutate(),
  }
}