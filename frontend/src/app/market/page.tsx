"use client"

import { useState } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { useGlobalIndices } from "@/hooks/use-market"
import { IconTrendingUp, IconTrendingDown, IconRefresh } from "@tabler/icons-react"

interface IndexItem {
  code: string; name: string; region: string
  price: number | null; change: number | null; change_pct: number | null
}

const REGION_LABELS: Record<string, string> = {
  "中国": "🇨🇳 中国", "美国": "🇺🇸 美国", "欧洲": "🇪🇺 欧洲",
  "亚太": "🌏 亚太", "其他": "🌐 其他",
}

export default function MarketPage() {
  const { data, isLoading, error, mutate } = useGlobalIndices()
  const [lastRefreshAt, setLastRefreshAt] = useState("")

  const indices: IndexItem[] = Array.isArray(data) ? data : (data as { items?: IndexItem[] } | undefined)?.items || []
  const displayUpdateTime = lastRefreshAt || (!isLoading && data ? "刚刚" : "")

  const refresh = () => {
    setLastRefreshAt(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
    mutate()
  }

  const grouped = indices.reduce<Record<string, IndexItem[]>>((acc, idx) => {
    const r = idx.region || "其他"; if (!acc[r]) acc[r] = []; acc[r].push(idx); return acc
  }, {})

  const regionOrder = ["中国", "美国", "欧洲", "亚太", "其他"]

  return (
    <>
      <SiteHeader title="大盘指数" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              {displayUpdateTime && (
                <p className="text-xs text-muted-foreground">
                  <span className="inline-block size-1.5 rounded-full bg-emerald-500 mr-1.5" />
                  更新于 {displayUpdateTime}
                </p>
              )}
              {isLoading && !displayUpdateTime && <p className="text-xs text-muted-foreground">加载中...</p>}
            </div>
            <button onClick={refresh} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
              <IconRefresh className="size-3" /> 刷新
            </button>
          </div>

          {error && (
            <Card className="border-red-500/20 bg-red-500/5 mb-4">
              <CardContent className="py-6 text-center">
                <p className="text-sm text-red-500">加载失败: {String(error)}</p>
                <button onClick={refresh} className="mt-2 text-xs text-primary hover:underline">点击重试</button>
              </CardContent>
            </Card>
          )}

          {isLoading && indices.length === 0 && (
            <div className="space-y-6">
              {[1, 2, 3].map((g) => (
                <div key={g}>
                  <Skeleton className="h-5 w-20 mb-3" />
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {[1, 2, 3, 4].map((c) => <Skeleton key={c} className="h-[100px]" />)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isLoading && !error && indices.length === 0 && (
            <Card><CardContent className="py-12 text-center"><p className="text-muted-foreground">暂无指数数据</p></CardContent></Card>
          )}

          {indices.length > 0 && (
            <div className="space-y-6">
              {regionOrder.map((region) => {
                const items = grouped[region]
                if (!items?.length) return null
                return (
                  <div key={region}>
                    <h3 className="text-sm font-semibold mb-3">{REGION_LABELS[region] || region}</h3>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                      {items.map((idx) => <IndexCard key={idx.code} item={idx} />)}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function IndexCard({ item }: { item: IndexItem }) {
  const price = item.price
  const change = item.change
  const changePct = item.change_pct
  const up = (change || 0) >= 0

  return (
    <Card className="hover:bg-muted/30 transition-colors">
      <CardContent className="p-3">
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{item.name}</p>
            <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{item.code}</p>
          </div>
          <Badge variant="outline" className={cn(
            "shrink-0",
            up ? "text-red-500 border-red-500/20 bg-red-500/5" : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"
          )}>
            {up ? <IconTrendingUp className="size-3 mr-0.5" /> : <IconTrendingDown className="size-3 mr-0.5" />}
            {changePct != null ? `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%` : "--"}
          </Badge>
        </div>
        <div className="space-y-1">
          <p className="text-xl font-semibold font-mono tabular-nums">
            {price != null ? price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "--"}
          </p>
          <p className={cn("text-xs font-mono tabular-nums", up ? "text-red-500" : "text-emerald-500")}>
            {change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}` : "--"}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
