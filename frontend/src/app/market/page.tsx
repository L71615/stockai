"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, isAuthenticated } from "@/lib/auth"
import { IconTrendingUp, IconTrendingDown, IconRefresh } from "@tabler/icons-react"

interface IndexItem {
  code: string
  name: string
  region: string
  price: number | null
  change: number | null
  change_pct: number | null
}

const REGION_LABELS: Record<string, string> = {
  "中国": "🇨🇳 中国",
  "美国": "🇺🇸 美国",
  "欧洲": "🇪🇺 欧洲",
  "亚太": "🌏 亚太",
  "其他": "🌐 其他",
}

export default function MarketPage() {
  const router = useRouter()
  const [indices, setIndices] = useState<IndexItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<string>("")

  const fetchIndices = useCallback(async () => {
    try {
      const data = await apiGet<IndexItem[]>("/api/stocks/indices/global")
      const items = Array.isArray(data) ? data : (data as { items?: IndexItem[] }).items || []
      setIndices(items)
      setError(null)
      setLastUpdate(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login")
      return
    }
    fetchIndices()
    const timer = setInterval(fetchIndices, 30000)
    return () => clearInterval(timer)
  }, [fetchIndices, router])

  // Group by region
  const grouped = indices.reduce<Record<string, IndexItem[]>>((acc, idx) => {
    const r = idx.region || "其他"
    if (!acc[r]) acc[r] = []
    acc[r].push(idx)
    return acc
  }, {})

  const regionOrder = ["中国", "美国", "欧洲", "亚太", "其他"]

  return (
    <>
      <SiteHeader title="大盘指数" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6">
          {/* Status bar */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              {lastUpdate && (
                <p className="text-xs text-muted-foreground">
                  <span className="inline-block size-1.5 rounded-full bg-emerald-500 mr-1.5" />
                  更新于 {lastUpdate}
                </p>
              )}
              {loading && !lastUpdate && (
                <p className="text-xs text-muted-foreground">加载中...</p>
              )}
            </div>
            <button
              onClick={fetchIndices}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <IconRefresh className="size-3" />
              刷新
            </button>
          </div>

          {/* Error state */}
          {error && (
            <Card className="border-red-500/20 bg-red-500/5 mb-4">
              <CardContent className="py-6 text-center">
                <p className="text-sm text-red-500">加载失败: {error}</p>
                <button
                  onClick={fetchIndices}
                  className="mt-2 text-xs text-primary hover:underline"
                >
                  点击重试
                </button>
              </CardContent>
            </Card>
          )}

          {/* Loading skeleton */}
          {loading && indices.length === 0 && (
            <div className="space-y-6">
              {[1, 2, 3].map((g) => (
                <div key={g}>
                  <Skeleton className="h-5 w-20 mb-3" />
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {[1, 2, 3, 4].map((c) => (
                      <Skeleton key={c} className="h-[100px]" />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && indices.length === 0 && (
            <Card>
              <CardContent className="py-12 text-center">
                <p className="text-muted-foreground">暂无指数数据</p>
              </CardContent>
            </Card>
          )}

          {/* Index cards grid */}
          {indices.length > 0 && (
            <div className="space-y-6">
              {regionOrder.map((region) => {
                const items = grouped[region]
                if (!items || items.length === 0) return null
                return (
                  <div key={region}>
                    <h3 className="text-sm font-semibold mb-3 text-foreground">
                      {REGION_LABELS[region] || region}
                    </h3>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                      {items.map((idx) => (
                        <IndexCard key={idx.code} item={idx} />
                      ))}
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
  const isUp = change !== null && change > 0
  const isDown = change !== null && change < 0
  const isFlat = change === 0

  const priceStr = price != null
    ? Number(price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—"

  const sign = isUp ? "+" : ""
  const chgStr = change != null ? `${sign}${change.toFixed(2)}` : "—"
  const pctStr = changePct != null ? `${sign}${changePct.toFixed(2)}%` : "—"

  const colorClass = isUp ? "text-red-500" : isDown ? "text-emerald-500" : "text-muted-foreground"

  return (
    <Card
      className={cn(
        "@container/card transition-colors hover:bg-accent/30",
        isUp && "border-red-500/10",
        isDown && "border-emerald-500/10"
      )}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{item.name}</p>
            <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{item.code}</p>
          </div>
          <Badge
            variant="outline"
            className={cn(
              "shrink-0 ml-2",
              isUp && "text-red-500 border-red-500/20 bg-red-500/5",
              isDown && "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"
            )}
          >
            {isUp ? <IconTrendingUp className="size-3" /> : isDown ? <IconTrendingDown className="size-3" /> : null}
            {pctStr}
          </Badge>
        </div>
        <p className={cn("text-xl font-semibold font-mono mt-3 tabular-nums", colorClass)}>
          {priceStr}
        </p>
        <p className={cn("text-xs mt-1 font-mono tabular-nums", colorClass)}>
          {chgStr}
        </p>
      </CardContent>
    </Card>
  )
}
