"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { ChartAreaInteractive } from "@/components/chart-area-interactive"
import { DataTable } from "@/components/data-table"
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconTrendingUp, IconTrendingDown, IconRefresh, IconBrain } from "@tabler/icons-react"
import { SectorPieChart } from "@/components/sector-pie-chart"

interface HoldingItem {
  id: number; stock_code: string; stock_name: string; asset_type: string
  quantity: number; cost_price: number; current_price: number | null
  market_value: number; pnl: number; pnl_pct: number; today_pnl: number
  change_pct?: number
}

interface SummaryData {
  total_cost: number; total_value: number; total_pnl: number
  total_pnl_pct: number; today_pnl: number
}

interface SectorItem {
  name: string; count: number; market_value: number; pct: number
}

interface DiversificationData {
  by_industry: SectorItem[]
  by_market: SectorItem[]
  risk_level: string
  max_single_pct: number
}

export default function Home() {
  const router = useRouter()
  const [holdings, setHoldings] = useState<HoldingItem[]>([])
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [aiHeadline, setAiHeadline] = useState("")
  const [diversification, setDiversification] = useState<DiversificationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdate, setLastUpdate] = useState("")
  const [history, setHistory] = useState<{ date: string; cost: number; value?: number }[]>([])

  const fetchData = useCallback(async () => {
    try {
      const data = await apiGet<{ holdings: HoldingItem[]; summary: SummaryData }>("/api/stocks/holdings/with-pnl")
      if (data) {
        setHoldings(Array.isArray(data.holdings) ? data.holdings : [])
        setSummary(data.summary || null)
      }
      // Try getting AI insight
      try {
        const revs = await apiGet<{ ai_headline?: string }[]>("/api/stocks/reviews?limit=1")
        if (Array.isArray(revs) && revs.length > 0 && revs[0].ai_headline) {
          setAiHeadline(revs[0].ai_headline)
        }
      } catch { /* optional */ }
      // Fetch diversification data
      try {
        const div = await apiGet<DiversificationData>("/api/stocks/diversification")
        if (div) setDiversification(div)
      } catch { /* optional */ }
      // Fetch portfolio history for chart
      try {
        const hist = await apiGet<{ data: { date: string; cost: number; value?: number }[] }>("/api/stocks/holdings/history")
        if (hist?.data) setHistory(hist.data)
      } catch { /* optional */ }
    } catch { /* */ }
    finally { setLoading(false); setRefreshing(false) }
    setLastUpdate(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchData()
    const timer = setInterval(fetchData, 30000)
    return () => clearInterval(timer)
  }, [fetchData, router])

  const refresh = () => { setRefreshing(true); fetchData() }

  // Helper: decimal places for price display
  const decimals = (assetType: string) => assetType === "fund" ? 4 : 3

  // Convert holdings to DataTable format
  const tableData = holdings.map((h, i) => ({
    id: i + 1,
    code: h.stock_code,
    name: h.stock_name,
    shares: `${h.quantity}${h.asset_type === "fund" ? "份" : "股"}`,
    price: h.current_price != null ? `¥ ${Number(h.current_price).toFixed(decimals(h.asset_type))}` : "—",
    cost: `¥ ${Number(h.cost_price).toFixed(decimals(h.asset_type))}`,
    pnl: h.pnl != null ? `${h.pnl >= 0 ? "+" : ""}¥ ${Number(h.pnl).toFixed(2)}` : "—",
    pnlPct: h.pnl_pct != null ? `${h.pnl_pct >= 0 ? "+" : ""}${Number(h.pnl_pct).toFixed(2)}%` : "—",
  }))

  const upCount = holdings.filter((h) => (h.pnl || 0) > 0).length
  const downCount = holdings.filter((h) => (h.pnl || 0) < 0).length

  return (
    <>
      <SiteHeader title="持仓概览" />
      <div className="flex flex-1 flex-col">
        <div className="@container/main flex flex-1 flex-col gap-2">
          <div className="flex flex-col gap-4 py-4 md:gap-6 md:py-6">
            {/* KPI Cards */}
            {loading ? (
              <div className="grid grid-cols-1 gap-4 px-4 lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
                {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[120px]" />)}
              </div>
            ) : summary ? (
              <div className="grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4 dark:*:data-[slot=card]:bg-card">
                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>总资产</CardDescription>
                    <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
                      ¥ {Number(summary.total_value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </CardTitle>
                    <CardAction>
                      <Badge variant="outline" className={cn(
                        summary.total_pnl >= 0 ? "text-red-500 border-red-500/20 bg-red-500/5" : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"
                      )}>
                        {summary.total_pnl >= 0 ? <IconTrendingUp /> : <IconTrendingDown />}
                        {summary.total_pnl_pct >= 0 ? "+" : ""}{Number(summary.total_pnl_pct).toFixed(2)}%
                      </Badge>
                    </CardAction>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className={cn("line-clamp-1 flex gap-2 font-medium", summary.total_pnl >= 0 ? "text-red-500" : "text-emerald-500")}>
                      总盈亏 ¥ {Number(summary.total_pnl).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                    <div className="text-muted-foreground">成本 ¥ {Number(summary.total_cost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
                  </CardFooter>
                </Card>

                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>今日盈亏</CardDescription>
                    <CardTitle className={cn("text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono",
                      (summary.today_pnl || 0) >= 0 ? "text-red-500" : "text-emerald-500")}>
                      {summary.today_pnl >= 0 ? "+" : ""}¥ {Number(summary.today_pnl || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </CardTitle>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="inline-block size-1.5 rounded-full bg-emerald-500"></span>
                      实时数据 · {lastUpdate || "加载中"}
                    </div>
                  </CardFooter>
                </Card>

                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>持仓数量</CardDescription>
                    <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
                      {holdings.length}<span className="text-base text-muted-foreground font-normal"> 只</span>
                    </CardTitle>
                    <CardAction>
                      <Badge variant="outline" className={upCount >= downCount ? "text-red-500 border-red-500/20 bg-red-500/5" : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"}>
                        {upCount} 涨 {downCount} 跌
                      </Badge>
                    </CardAction>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className="text-muted-foreground">盈亏比 {downCount > 0 ? (upCount / downCount).toFixed(1) : upCount}:{downCount}</div>
                  </CardFooter>
                </Card>

                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>持仓占比</CardDescription>
                    <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
                      {summary.total_cost > 0 ? `${Math.round((summary.total_value / summary.total_cost - 1) * 100)}%` : "--"}
                    </CardTitle>
                    <CardAction>
                      <Badge variant="outline" className={summary.total_pnl >= 0 ? "text-red-500 border-red-500/20 bg-red-500/5" : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"}>
                        {summary.total_pnl >= 0 ? "盈利" : "亏损"}
                      </Badge>
                    </CardAction>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className="text-muted-foreground">
                      持有 {holdings.map((h) => h.asset_type).filter((t, i, a) => a.indexOf(t) === i).join(" / ") || "--"}
                    </div>
                  </CardFooter>
                </Card>
              </div>
            ) : (
              <div className="px-4 lg:px-6">
                <Card>
                  <CardContent className="py-12 text-center">
                    <p className="text-sm text-muted-foreground">暂无持仓数据</p>
                    <p className="text-xs text-muted-foreground mt-1">点击"交易记录"添加第一笔持仓</p>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* AI Insight */}
            {aiHeadline && (
              <div className="px-4 lg:px-6">
                <Card className="border-l-[3px] border-l-purple-400">
                  <CardContent className="py-3">
                    <p className="text-xs text-purple-400 font-medium mb-1 flex items-center gap-1">
                      <IconBrain className="size-3" />AI 洞察
                    </p>
                    <p className="text-sm text-muted-foreground italic">
                      &ldquo;{aiHeadline}&rdquo;
                    </p>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Chart — only show when there are holdings */}
            {holdings.length > 0 && (
              <div className="px-4 lg:px-6">
                <ChartAreaInteractive data={history} />
              </div>
            )}

            {/* Sector Pie Chart — only show when there are holdings with industry data */}
            {diversification && diversification.by_industry.length > 0 && (
              <div className="px-4 lg:px-6">
                <SectorPieChart
                  data={diversification.by_industry}
                  totalValue={summary?.total_value || 0}
                />
              </div>
            )}

            {/* Holdings Table */}
            {holdings.length > 0 ? (
              <DataTable data={tableData} />
            ) : !loading && (
              <div className="px-4 lg:px-6">
                <Card>
                  <CardContent className="py-12 text-center space-y-2">
                    <p className="text-4xl opacity-40">📊</p>
                    <p className="text-sm text-muted-foreground">暂无持仓数据</p>
                    <p className="text-xs text-muted-foreground">
                      请先前往{" "}
                      <button onClick={() => router.push("/transactions")} className="text-primary hover:underline">
                        交易记录
                      </button>
                      {" "}添加持仓
                    </p>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Refresh button */}
            <div className="flex justify-center pb-4">
              <button
                onClick={refresh}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <IconRefresh className={cn("size-3", refreshing && "animate-spin")} />
                {lastUpdate ? `最后更新 ${lastUpdate}` : "点击刷新"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
