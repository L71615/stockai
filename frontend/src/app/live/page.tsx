"use client"

/**
 * /live 盘中量化分析仪表板 — v5.0-alpha M4 + v4.2 M2
 *
 * 6 个 section:
 *   1. 顶部 持仓实时 PnL 总览
 *   2. 实时行情 watchlist 表 (5s 刷新)
 *   3. 盘中信号触发列表 (接受/拒绝手动确认)
 *   4. 实时持仓表 (含未实现盈亏)
 *   5. 选中股票的日级因子卡片 (v5.0-alpha M2 30 因子)
 *   6. 选中股票的分钟级因子卡片 (v4.2 M2 55 因子 — historical_kline fallback)
 *
 * 设计遵循 stockai-project-docs/DESIGN.md:
 *   - 暗色主题 + rounded-none
 *   - Tabler Icons (size-3 / size-3.5)
 *   - 数字列 tabular-nums
 *   - 涨红跌绿 (中国 A 股惯例: 红涨绿跌)
 */

import { useEffect, useState } from "react"
import useSWR from "swr"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { RealtimeFactorCard } from "@/components/realtime-factor-card"
import { RealtimeMinuteFactorCard } from "@/components/realtime-minute-factor-card"
import { useRealtimeQuote, type Quote } from "@/hooks/use-realtime-quote"
import { apiPost } from "@/lib/auth"
import { swrFetcher } from "@/lib/swr-config"
import { useWatchlist } from "@/hooks/use-watchlist"
import { usePortfolio } from "@/hooks/use-portfolio"
import { cn } from "@/lib/utils"
import {
  IconCheck, IconX, IconRefresh, IconBolt,
  IconAlertTriangle, IconClock, IconCircleDot,
} from "@tabler/icons-react"
import type { PortfolioHolding } from "@/lib/api-types"

// ── 信号数据结构 ──

interface Signal {
  id: number
  strategy_id: string
  stock_code: string
  direction: string
  score: number
  triggered_at: number
  accepted: boolean
  order_id: number | null
}

interface SignalResponse {
  signals: Signal[]
  count: number
}

// ── 主页面 ──

export default function LivePage() {
  // 1. 实时行情 (watchlist + 持仓合并去重)
  const { data: watchlist = [] } = useWatchlist()
  const { data: portfolioData } = usePortfolio()
  const holdings: PortfolioHolding[] = portfolioData?.holdings ?? []
  const allCodes = Array.from(new Set([
    ...watchlist.map((w) => w.stock_code),
    ...holdings.map((h) => h.stock_code),
  ]))
  const { quotes, isTradingHours } = useRealtimeQuote(allCodes)

  // 2. 信号历史 (5s 刷新)
  const { data: signalData, mutate: refreshSignals } = useSWR<SignalResponse>(
    "/api/realtime/signal/recent?limit=20",
    swrFetcher,
    { refreshInterval: 5000, revalidateOnFocus: false },
  )

  // 3. 选中股票(用于展示因子卡片) — 默认取 watchlist 第一只
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  useEffect(() => {
    if (!selectedCode && watchlist.length > 0) {
      setSelectedCode(watchlist[0].stock_code)
    }
  }, [watchlist, selectedCode])

  // 4. 信号接受/拒绝
  const [hiddenSignals, setHiddenSignals] = useState<Set<number>>(new Set())
  const [busyId, setBusyId] = useState<number | null>(null)

  const acceptSignal = async (id: number) => {
    setBusyId(id)
    try {
      await apiPost(`/api/realtime/signal/${id}/accept`)
      refreshSignals()
    } catch (e) {
      console.error("accept signal failed:", e)
    } finally {
      setBusyId(null)
    }
  }
  const rejectSignal = (id: number) => {
    setHiddenSignals((prev) => new Set([...prev, id]))
  }

  // 5. 持仓实时盈亏
  const positionsWithPnl = holdings.map((h) => {
    const q: Quote | undefined = quotes.get(h.stock_code)
    const marketPrice = q?.price ?? h.current_price ?? h.cost_price
    const pnl = (marketPrice - h.cost_price) * h.quantity
    const pnl_pct = h.cost_price > 0 ? ((marketPrice - h.cost_price) / h.cost_price) * 100 : 0
    return { ...h, market_price: marketPrice, pnl, pnl_pct }
  })
  const totalPnl = positionsWithPnl.reduce((sum, p) => sum + (p.pnl ?? 0), 0)
  const totalCost = positionsWithPnl.reduce((sum, p) => sum + p.cost_price * p.quantity, 0)
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0

  // 6. 信号列表过滤 + 排序(最新在前)
  const visibleSignals = (signalData?.signals ?? [])
    .filter((s) => !hiddenSignals.has(s.id))
    .slice(0, 10)
  const pendingCount = visibleSignals.filter((s) => !s.accepted).length

  return (
    <>
      <SiteHeader title="盘中量化分析" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* ───── 1. 顶部 PnL 总览 ───── */}
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <IconBolt className="size-3.5" />
                  <span>持仓实时盈亏</span>
                  {isTradingHours ? (
                    <Badge variant="outline" className="text-[10px] text-red-400 border-red-500/30">
                      <IconCircleDot className="size-2.5 mr-0.5 animate-pulse" /> 盘中
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px] text-muted-foreground">
                      <IconClock className="size-2.5 mr-0.5" /> 盘后
                    </Badge>
                  )}
                </div>
                <div className="flex items-baseline gap-2 mt-1">
                  <p
                    className={cn(
                      "text-3xl font-bold font-mono tabular-nums",
                      totalPnl >= 0 ? "text-red-400" : "text-emerald-400",
                    )}
                  >
                    {totalPnl >= 0 ? "+" : ""}¥{totalPnl.toFixed(0)}
                  </p>
                  <span
                    className={cn(
                      "text-sm font-mono tabular-nums",
                      totalPnlPct >= 0 ? "text-red-400" : "text-emerald-400",
                    )}
                  >
                    {totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground mt-1">
                  {positionsWithPnl.length} 只持仓 · 成本 ¥{totalCost.toFixed(0)}
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={() => refreshSignals()}>
                <IconRefresh className="size-3.5 mr-1" /> 刷新
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* ───── 2. 实时行情 watchlist ───── */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center justify-between">
              <span>实时行情 · {watchlist.length} 只</span>
              <span className="text-[10px] text-muted-foreground font-normal">
                5s 刷新
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {watchlist.length === 0 ? (
              <EmptyHint text="暂无自选股 — 在 watchlist 页面添加股票" />
            ) : (
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border">
                    <td className="py-1">代码</td>
                    <td className="py-1">名称</td>
                    <td className="py-1 text-right">现价</td>
                    <td className="py-1 text-right">涨跌幅</td>
                  </tr>
                </thead>
                <tbody>
                  {watchlist.map((w) => {
                    const q = quotes.get(w.stock_code)
                    const isSelected = selectedCode === w.stock_code
                    return (
                      <tr
                        key={w.stock_code}
                        onClick={() => setSelectedCode(w.stock_code)}
                        className={cn(
                          "border-b border-border/50 cursor-pointer hover:bg-muted/30",
                          isSelected && "bg-muted/50",
                        )}
                      >
                        <td className="py-1.5 font-mono">{w.stock_code}</td>
                        <td className="py-1.5">{w.stock_name}</td>
                        <td className="py-1.5 font-mono text-right tabular-nums">
                          {q?.price != null ? `¥${q.price.toFixed(2)}` : "--"}
                        </td>
                        <td
                          className={cn(
                            "py-1.5 font-mono text-right tabular-nums",
                            q?.change_pct != null && q.change_pct >= 0
                              ? "text-red-400"
                              : "text-emerald-400",
                          )}
                        >
                          {q?.change_pct != null
                            ? `${q.change_pct >= 0 ? "+" : ""}${q.change_pct.toFixed(2)}%`
                            : "--"}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {/* ───── 3. 盘中信号触发(手动确认) ───── */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <IconAlertTriangle className="size-3.5" />
              盘中信号触发
              {pendingCount > 0 && (
                <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-500/30">
                  {pendingCount} 待确认
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {visibleSignals.length === 0 ? (
              <EmptyHint text="暂无信号触发 — 盘中时段会持续监控 (5s/轮)" />
            ) : (
              visibleSignals.map((s) => (
                <SignalRow
                  key={s.id}
                  signal={s}
                  busy={busyId === s.id}
                  onAccept={() => acceptSignal(s.id)}
                  onReject={() => rejectSignal(s.id)}
                />
              ))
            )}
          </CardContent>
        </Card>

        {/* ───── 4. 实时持仓表 ───── */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">实时持仓 ({positionsWithPnl.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {positionsWithPnl.length === 0 ? (
              <EmptyHint text="暂无持仓" />
            ) : (
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border">
                    <td className="py-1">代码</td>
                    <td className="py-1">名称</td>
                    <td className="py-1 text-right">数量</td>
                    <td className="py-1 text-right">成本</td>
                    <td className="py-1 text-right">现价</td>
                    <td className="py-1 text-right">盈亏</td>
                  </tr>
                </thead>
                <tbody>
                  {positionsWithPnl.map((p) => (
                    <tr key={p.stock_code} className="border-b border-border/50">
                      <td className="py-1.5 font-mono">{p.stock_code}</td>
                      <td className="py-1.5">{p.stock_name}</td>
                      <td className="py-1.5 font-mono text-right tabular-nums">{p.quantity}</td>
                      <td className="py-1.5 font-mono text-right tabular-nums">
                        {p.cost_price.toFixed(2)}
                      </td>
                      <td className="py-1.5 font-mono text-right tabular-nums">
                        {p.market_price.toFixed(2)}
                      </td>
                      <td
                        className={cn(
                          "py-1.5 font-mono text-right tabular-nums",
                          (p.pnl ?? 0) >= 0 ? "text-red-400" : "text-emerald-400",
                        )}
                      >
                        {(p.pnl ?? 0) >= 0 ? "+" : ""}¥{(p.pnl ?? 0).toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {/* ───── 5. 选中股票的盘中因子 (日级 30 因子, v5.0-alpha M2) ───── */}
        {selectedCode && (
          <RealtimeFactorCard code={selectedCode} />
        )}

        {/* ───── 6. 选中股票的分钟级因子 (v4.2 M2, 55 因子 historical_kline fallback) ───── */}
        {selectedCode && (
          <RealtimeMinuteFactorCard code={selectedCode} />
        )}
      </div>
    </>
  )
}

// ── 子组件 ──

function SignalRow({
  signal,
  busy,
  onAccept,
  onReject,
}: {
  signal: Signal
  busy: boolean
  onAccept: () => void
  onReject: () => void
}) {
  const time = new Date(signal.triggered_at * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  })
  return (
    <div
      className={cn(
        "flex items-center gap-2 p-2 border rounded-none transition-colors",
        signal.accepted
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-border bg-card",
      )}
    >
      <Badge variant="outline" className="text-[10px] shrink-0">
        {signal.strategy_id}
      </Badge>
      <span className="font-mono text-xs shrink-0">{signal.stock_code}</span>
      <span
        className={cn(
          "text-xs font-medium shrink-0",
          signal.direction === "buy" ? "text-red-400" : "text-emerald-400",
        )}
      >
        {signal.direction === "buy" ? "买入" : "卖出"}
      </span>
      <span className="text-[10px] text-muted-foreground shrink-0 tabular-nums">{time}</span>
      <span className="text-[10px] text-muted-foreground shrink-0">
        score={signal.score.toFixed(2)}
      </span>
      <span className="ml-auto flex gap-1 shrink-0">
        {signal.accepted ? (
          <Badge className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30">
            <IconCheck className="size-2.5 mr-0.5" /> 已接受
          </Badge>
        ) : (
          <>
            <Button
              size="sm"
              variant="outline"
              className="h-6 text-[10px]"
              onClick={onAccept}
              disabled={busy}
            >
              <IconCheck className="size-3 mr-0.5" />
              {busy ? "下单中..." : "接受"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-[10px]"
              onClick={onReject}
              disabled={busy}
            >
              <IconX className="size-3 mr-0.5" />
              拒绝
            </Button>
          </>
        )}
      </span>
    </div>
  )
}

function EmptyHint({ text }: { text: string }) {
  return (
    <p className="text-xs text-muted-foreground text-center py-4 font-mono">
      {text}
    </p>
  )
}