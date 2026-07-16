"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { PortfolioRiskCards } from "@/components/portfolio-risk-cards"
import { ChartAreaInteractive } from "@/components/chart-area-interactive"
import { DataTable } from "@/components/data-table"
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { usePortfolio, usePortfolioHistory, useDiversification } from "@/hooks/use-portfolio"
import { useLatestReview } from "@/hooks/use-review"
import { apiGet, apiPost } from "@/lib/auth"
import useSWR from "swr"
import type { PortfolioData, PortfolioHolding } from "@/lib/api-types"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { IconTrendingUp, IconTrendingDown, IconRefresh, IconBrain, IconChartBar } from "@tabler/icons-react"
import { SectorPieChart } from "@/components/sector-pie-chart"

type HomeHolding = PortfolioHolding

export default function Home() {
  const router = useRouter()

  const { data: portfolio, error: portfolioError, isLoading, isValidating, mutate } = usePortfolio()
  const { data: reviewData } = useLatestReview()
  const { data: diversification } = useDiversification()
  const { data: historyData } = usePortfolioHistory()

  const holdings: HomeHolding[] = Array.isArray(portfolio?.holdings)
    ? (portfolio.holdings as unknown as HomeHolding[])
    : []
  const summary = portfolio?.summary ?? null
  const { data: disciplineData } = useSWR("/api/discipline/dashboard", (url: string) => apiGet(url), { refreshInterval: 60000 })
  const { data: protectionData } = useSWR("/api/discipline/loss-streak", (url: string) => apiGet(url), { refreshInterval: 120000 })
  const { data: riskData } = useSWR("/api/quant/portfolio-risk", (url: string) => apiGet(url), { refreshInterval: 300000 })
  const aiHeadline = Array.isArray(reviewData) && reviewData[0]?.ai_headline ? reviewData[0].ai_headline : ""
  const history = historyData?.data ?? []
  const portfolioErrorMessage = portfolioError instanceof Error
    ? portfolioError.message
    : portfolioError
      ? "持仓接口请求失败"
      : ""

  const refreshing = isValidating
  const [lastRefreshAt, setLastRefreshAt] = useState("")
  const [deleting, setDeleting] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ holdingId: number; code: string; name: string } | null>(null)
  const displayUpdateTime = lastRefreshAt || (!isLoading && portfolio ? "刚刚" : "")

  const refresh = () => {
    setLastRefreshAt(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
    mutate()
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await apiPost(`/api/stocks/holdings/${deleteTarget.holdingId}`, undefined, "DELETE")
      mutate(
        (current: PortfolioData | undefined) => {
          if (!current) return current
          return {
            ...current,
            holdings: current.holdings.filter((h) => h.id !== deleteTarget.holdingId),
            summary: {
              ...current.summary,
              total_cost: 0,
            },
          }
        },
        { revalidate: true }
      )
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "删除失败"
      alert(msg)
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }

  const decimals = (assetType: string) => assetType === "fund" ? 4 : 3

  const tableData = holdings.map((h) => ({
    id: h.id,
    code: h.stock_code,
    name: h.stock_name,
    shares: `${h.quantity}${h.asset_type === "fund" ? "份" : "股"}`,
    price: h.current_price != null ? `¥ ${Number(h.current_price).toFixed(decimals(h.asset_type))}` : "—",
    cost: `¥ ${Number(h.cost_price).toFixed(decimals(h.asset_type))}`,
    pnl: h.pnl != null ? `${h.pnl >= 0 ? "+" : ""}¥ ${Number(h.pnl).toFixed(2)}` : "—",
    pnlPct: h.pnl_pct != null ? `${h.pnl_pct >= 0 ? "+" : ""}${Number(h.pnl_pct).toFixed(2)}%` : "—",
    holdingId: h.id,
  }))

  const upCount = holdings.filter((h) => (h.pnl || 0) > 0).length
  const downCount = holdings.filter((h) => (h.pnl || 0) < 0).length
  const holdingTypes = holdings.map((h) => h.asset_type).filter((t, i, a) => a.indexOf(t) === i).join(" / ") || "--"

  return (
    <>
      <SiteHeader title="持仓概览" />
      <div className="flex flex-1 flex-col">
        <div className="@container/main flex flex-1 flex-col gap-2">
          <div className="flex flex-col gap-4 py-4 md:gap-6 md:py-6">
            {isLoading ? (
              <div className="grid grid-cols-1 gap-4 px-4 lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
                {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[120px]" />)}
              </div>
            ) : portfolioErrorMessage ? (
              <div className="px-4 lg:px-6">
                <Card className="border-amber-500/40 bg-amber-500/5">
                  <CardContent className="space-y-2 py-6">
                    <p className="text-sm font-medium text-amber-500">持仓数据加载失败</p>
                    <p className="text-sm text-muted-foreground">
                      前端运行在 <span className="font-mono">3001</span>，持仓数据通过后端 <span className="font-mono">3000</span> 的
                      <span className="font-mono">/api/stocks/holdings/with-pnl</span> 获取。
                    </p>
                    <p className="text-xs text-muted-foreground">
                      当前请求失败：{portfolioErrorMessage}。如果你是本地启动，请先确认后端已经在 <span className="font-mono">3000</span> 端口运行，
                      或者直接使用项目根目录的 <span className="font-mono">start.bat</span> 同时启动前后端。
                    </p>
                  </CardContent>
                </Card>
              </div>
            ) : summary ? (
              <div className="grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4 dark:*:data-[slot=card]:bg-card">
                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>总资产</CardDescription>
                    <CardTitle className="font-mono text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
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
                    <CardTitle className={cn(
                      "font-mono text-2xl font-semibold tabular-nums @[250px]/card:text-3xl",
                      (summary.today_pnl || 0) >= 0 ? "text-red-500" : "text-emerald-500"
                    )}>
                      {summary.today_pnl >= 0 ? "+" : ""}¥ {Number(summary.today_pnl || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </CardTitle>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="inline-block size-1.5 rounded-full bg-emerald-500"></span>
                      实时数据 · {displayUpdateTime || "加载中"}
                    </div>
                  </CardFooter>
                </Card>

                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>持仓数量</CardDescription>
                    <CardTitle className="font-mono text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                      {holdings.length}<span className="text-base font-normal text-muted-foreground"> 只</span>
                    </CardTitle>
                    <CardAction>
                      <Badge variant="outline" className={upCount >= downCount ? "text-red-500 border-red-500/20 bg-red-500/5" : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"}>
                        {upCount} 盈 / {downCount} 亏
                      </Badge>
                    </CardAction>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className="text-muted-foreground">盈亏比 {downCount > 0 ? (upCount / downCount).toFixed(1) : upCount}:{downCount}</div>
                  </CardFooter>
                </Card>

                <Card className="@container/card">
                  <CardHeader>
                    <CardDescription>总收益率</CardDescription>
                    <CardTitle className="font-mono text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                      {summary.total_pnl_pct != null ? `${summary.total_pnl_pct >= 0 ? "+" : ""}${summary.total_pnl_pct}%` : "--"}
                    </CardTitle>
                    <CardAction>
                      <Badge variant="outline" className={summary.total_pnl >= 0 ? "text-red-500 border-red-500/20 bg-red-500/5" : "text-emerald-500 border-emerald-500/20 bg-emerald-500/5"}>
                        {summary.total_pnl >= 0 ? "盈利" : "亏损"}
                      </Badge>
                    </CardAction>
                  </CardHeader>
                  <CardFooter className="flex-col items-start gap-1.5 text-sm">
                    <div className="text-muted-foreground">持有 {holdingTypes}</div>
                  </CardFooter>
                </Card>
              </div>
            ) : (
              <div className="px-4 lg:px-6">
                <Card>
                  <CardContent className="py-12 text-center">
                    <p className="text-sm text-muted-foreground">暂无持仓数据</p>
                    <p className="mt-1 text-xs text-muted-foreground">点击“交易记录”添加第一笔持仓</p>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* 组合风险指标 */}
            <PortfolioRiskCards data={riskData as { sharpe?: number | null; max_drawdown?: number | null; volatility?: number | null; beta?: number | null } | null | undefined} />

            {aiHeadline && (
              <div className="px-4 lg:px-6">
                <Card className="border-l-[3px] border-l-purple-400">
                  <CardContent className="py-3">
                    <p className="mb-1 flex items-center gap-1 text-xs font-medium text-purple-400">
                      <IconBrain className="size-3" />AI 洞察
                    </p>
                    <p className="text-sm italic text-muted-foreground">
                      &ldquo;{aiHeadline}&rdquo;
                    </p>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Protection Warning */}
            {protectionData && (protectionData as Record<string, unknown>).streak > 0 && (
              <div className="px-4 lg:px-6">
                <Card className={cn(
                  "border-l-[3px]",
                  (protectionData as Record<string, unknown>).warning_level === "danger"
                    ? "border-l-red-500 bg-red-500/5"
                    : "border-l-yellow-400 bg-yellow-500/5"
                )}>
                  <CardContent className="py-3">
                    <p className={cn(
                      "mb-1 text-xs font-medium",
                      (protectionData as Record<string, unknown>).warning_level === "danger"
                        ? "text-red-400"
                        : "text-yellow-400"
                    )}>
                      {(protectionData as Record<string, unknown>).warning_level === "danger" ? "🛑 保护模式" : "⚠️ 连亏警告"}
                      {" "}（连亏 {(protectionData as Record<string, unknown>).streak as number} 笔）
                    </p>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {(protectionData as Record<string, unknown>).advice as string}
                    </p>
                    {((protectionData as Record<string, unknown>).recent_losses as Array<Record<string, unknown>>)?.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-2">
                        {((protectionData as Record<string, unknown>).recent_losses as Array<Record<string, unknown>>).map((l, i) => (
                          <span key={i} className="text-[10px] text-muted-foreground font-mono">
                            {l.code as string} {l.name as string} ¥{l.pnl as number}
                            {l.pnl_pct != null && ` (${(l.pnl_pct as number) >= 0 ? "+" : ""}${(l.pnl_pct as number).toFixed(1)}%)`}
                          </span>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Stop-Loss Monitoring Card */}
            {disciplineData && disciplineData.holdings_with_stop_loss?.length > 0 && (
              <div className="px-4 lg:px-6">
                <Card className="border-l-[3px] border-l-red-400">
                  <CardContent className="py-3">
                    <p className="mb-2 flex items-center gap-1 text-xs font-medium text-red-400">
                      🛡 止损监控 ({disciplineData.active_stop_loss_count} 只)
                    </p>
                    <div className="space-y-1.5">
                      {disciplineData.holdings_with_stop_loss.map((h: Record<string, unknown>) => (
                        <div key={String(h.holding_id)} className="flex items-center justify-between text-xs">
                          <span className="font-mono">{h.stock_code as string}</span>
                          <span className="text-muted-foreground">
                            止损 ¥{h.stop_loss_price as number}
                          </span>
                          <span className={h.danger ? "text-red-400 font-medium" : "text-muted-foreground"}>
                            {h.stop_loss_distance_pct != null ? `${h.stop_loss_distance_pct}%` : "--"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}

            {holdings.length > 0 && (
              <div className="px-4 lg:px-6">
                <ChartAreaInteractive data={history} />
              </div>
            )}

            {diversification && diversification.by_industry?.length > 0 && (
              <div className="px-4 lg:px-6">
                <SectorPieChart
                  data={diversification.by_industry}
                  totalValue={summary?.total_value || 0}
                />
              </div>
            )}

            {holdings.length > 0 ? (
              <DataTable
                data={tableData}
                actions={{
                  onEdit: (item) => alert(`编辑 ${item.code} ${item.name} 暂未实现`),
                  onView: (item) => alert(`请点击名称查看 ${item.code} ${item.name} 详情`),
                  onAddToWatchlist: (item) => alert(`${item.code} ${item.name} 已在持仓中，可去自选股页管理`),
                  onDelete: (item) => setDeleteTarget({ holdingId: item.id, code: item.code, name: item.name }),
                }}
              />
            ) : !isLoading && !portfolioErrorMessage && (
              <div className="px-4 lg:px-6">
                <Card>
                  <CardContent className="space-y-2 py-12 text-center">
                    <IconChartBar className="mx-auto size-8 opacity-40" />
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

            <div className="flex justify-center pb-4">
              <button
                onClick={refresh}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <IconRefresh className={cn("size-3", refreshing && "animate-spin")} />
                {displayUpdateTime ? `最后更新 ${displayUpdateTime}` : "点击刷新"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除持仓</AlertDialogTitle>
            <AlertDialogDescription>
              将删除 <span className="font-mono font-semibold text-foreground">{deleteTarget?.code}</span> {deleteTarget?.name} 的持仓记录。
              <br />
              此操作不会删除已有的交易记录。删除后可在交易记录中重新添加。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleting} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              {deleting ? "删除中…" : "确认删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
