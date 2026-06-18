"use client"

import { useState, useEffect } from "react"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/auth"
import type { KlineResponse } from "@/lib/api-types"
import { KlineChart } from "./KlineChart"

const PERIODS = [
  { key: "5d", label: "5日" },
  { key: "1m", label: "日K" },
  { key: "3m", label: "周K" },
  { key: "6m", label: "月K" },
]

export function StockChartDrawer({
  code,
  name,
  open,
  onClose,
}: {
  code: string
  name: string
  open: boolean
  onClose: () => void
}) {
  const [period, setPeriod] = useState("1m")
  const [data, setData] = useState<KlineResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !code) return
    setLoading(true)
    setError(null)
    apiGet<KlineResponse>(`/api/stocks/kline/${code}?period=${period}`)
      .then((raw) => setData(raw))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false))
  }, [code, period, open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      {/* Panel */}
      <div className="relative w-full max-w-lg bg-card border-l border-border flex flex-col h-full overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div>
            <p className="text-sm font-semibold font-mono">{code} {name}</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-lg leading-none">&times;</button>
        </div>

        {/* Period tabs */}
        <Tabs value={period} onValueChange={setPeriod} className="shrink-0">
          <TabsList className="w-full justify-start rounded-none border-b border-border bg-transparent px-4 h-9">
            {PERIODS.map((p) => (
              <TabsTrigger key={p.key} value={p.key}
                className="rounded-none text-xs data-[state=active]:border-b-2 data-[state=active]:border-primary h-9">
                {p.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {/* Legend */}
        <div className="flex items-center gap-4 px-4 py-1.5 text-[10px] text-muted-foreground shrink-0">
          <span><span className="inline-block w-2.5 h-0.5 bg-amber-500 align-middle mr-1" />MA5</span>
          <span><span className="inline-block w-2.5 h-0.5 bg-purple-500 align-middle mr-1" />MA10</span>
          <span><span className="inline-block w-2.5 h-0.5 bg-cyan-500 align-middle mr-1" />MA20</span>
        </div>

        {/* Chart body */}
        <div className="flex-1 px-2 py-2">
          {loading ? (
            <div className="space-y-3 px-2">
              <Skeleton className="h-[280px] w-full" />
              <Skeleton className="h-[80px] w-full" />
            </div>
          ) : error ? (
            <p className="text-xs text-muted-foreground text-center py-12">{error}</p>
          ) : !data || !data.dates?.length ? (
            <p className="text-xs text-muted-foreground text-center py-12">暂无数据</p>
          ) : (
            <>
              {/* Price + MA chart */}
              <KlineChart rawData={data} height={280} />
              {/* Volume chart */}
              <KlineChart rawData={data} height={80} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
