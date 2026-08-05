"use client"

/**
 * 实时行情 hook — v5.0-beta M5 (WebSocket 推送)
 *
 * 协议: ws://host/api/realtime/ws
 *   - 服务端推 {type: "trading_status", ...}  (连接建立)
 *   - 服务端推 {type: "snapshot", quotes: [...]}  (subscribe 触发)
 *   - 服务端推 {type: "quote", ...}  (每次 service 更新)
 *   - 客户端发 {type: "subscribe", codes: [...]}  (订代码)
 *   - 客户端发 {type: "unsubscribe", codes: [...]}  (退订)
 *   - 客户端发 "ping" → 服务端返 {type: "pong"}
 *
 * 已知限制(v5.0-beta M5 最小版):
 *   - 简单重连(3s 后重试一次,无指数退避)
 *   - 无 SWR fallback 缓存层
 *   - 断线后 quotes 保持最后状态(不自动重置)
 */

import { useEffect, useMemo, useRef, useState } from "react"

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

export interface UseRealtimeQuoteResult {
  quotes: Map<string, Quote>
  isLoading: boolean
  lastUpdate: number
  isTradingHours: boolean
  isTradingDay: boolean
  isConnected: boolean
  refresh: () => void
}

export function useRealtimeQuote(
  codes: string[],
  options?: { enabled?: boolean }
): UseRealtimeQuoteResult {
  const enabled = options?.enabled !== false

  // 稳定 codes 列表(排序去重)— 避免顺序差异触发不同 WS subscribe
  const sortedCodes = useMemo(() => {
    const set = new Set(codes.filter(Boolean))
    return Array.from(set).sort()
  }, [codes.join(",")])

  const [quotes, setQuotes] = useState<Map<string, Quote>>(new Map())
  const [lastUpdate, setLastUpdate] = useState(0)
  const [isTradingHours, setIsTradingHours] = useState(false)
  const [isTradingDay, setIsTradingDay] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(enabled && sortedCodes.length > 0)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled || sortedCodes.length === 0) {
      setIsLoading(false)
      return
    }

    // 构造 ws URL(从当前 location 推 host)
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const wsUrl = `${protocol}//${window.location.host}/api/realtime/ws`

    let mounted = true
    let currentWs: WebSocket | null = null
    let subscribedNow: string[] = []

    const connect = () => {
      if (!mounted) return
      const ws = new WebSocket(wsUrl)
      currentWs = ws
      wsRef.current = ws

      ws.onopen = () => {
        if (!mounted) return
        setIsConnected(true)
        // 订阅当前 codes
        subscribedNow = [...sortedCodes]
        ws.send(JSON.stringify({ type: "subscribe", codes: subscribedNow }))
      }

      ws.onmessage = (event) => {
        if (!mounted) return
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === "trading_status") {
            setIsTradingHours(!!msg.is_trading_hours)
            setIsTradingDay(!!msg.is_trading_day)
            setLastUpdate(msg.ts ?? Date.now() / 1000)
          } else if (msg.type === "snapshot") {
            setQuotes((prev) => {
              const next = new Map(prev)
              for (const q of msg.quotes as Quote[]) next.set(q.code, q)
              return next
            })
            setLastUpdate(msg.ts ?? Date.now() / 1000)
            setIsLoading(false)
          } else if (msg.type === "quote") {
            setQuotes((prev) => {
              const next = new Map(prev)
              next.set(msg.code, msg as Quote)
              return next
            })
            setLastUpdate(msg.timestamp ?? Date.now() / 1000)
          }
        } catch (e) {
          // 忽略 JSON 解析错误
        }
      }

      ws.onerror = () => {
        // 浏览器触发 onclose,统一在 onclose 处理
      }

      ws.onclose = () => {
        if (!mounted) return
        setIsConnected(false)
        // 简单重连(3s 后)— 不无限重试,避免失控
        reconnectTimerRef.current = setTimeout(() => {
          if (mounted) connect()
        }, 3000)
      }
    }

    connect()

    return () => {
      mounted = false
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (currentWs) {
        // 退订后关闭
        try {
          if (currentWs.readyState === WebSocket.OPEN) {
            currentWs.send(JSON.stringify({ type: "unsubscribe", codes: subscribedNow }))
          }
          currentWs.close()
        } catch {
          // ignore
        }
      }
      wsRef.current = null
    }
  }, [enabled, sortedCodes.join(",")])

  return {
    quotes,
    isLoading,
    lastUpdate,
    isTradingHours,
    isTradingDay,
    isConnected,
    refresh: () => {
      // 简单 refresh: 重新连接
      if (wsRef.current) wsRef.current.close()
    },
  }
}
