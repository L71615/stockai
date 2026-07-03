"use client"

import * as React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { ChartEquityCurve } from "@/components/chart-equity-curve"
import {
  IconTrendingUp,
  IconTrendingDown,
  IconTarget,
  IconBolt,
  IconScale,
  IconShield,
} from "@tabler/icons-react"

interface BacktestMetrics {
  total_return: number
  annual_return: number
  sharpe: number
  max_drawdown: number
  win_rate: number
  profit_factor: number
  num_trades: number
  win_count: number
  loss_count: number
  calmar: number
  final_value: number
  initial_cash: number
  total_pnl: number
  avg_win: number
  avg_loss: number
}

interface Trade {
  id: number
  date: string
  code: string
  name: string
  direction: "buy" | "sell"
  price: number
  shares: number
  pnl: number | null
  pnl_pct: number | null
  reason: string
}

interface EquityPoint {
  date: string
  value: number
  benchmark_value?: number | null
}

interface MonthlyReturn {
  month: string
  strategy_return: number
  benchmark_return: number | null
}

interface BacktestResultsProps {
  metrics: BacktestMetrics
  equity_curve: EquityPoint[]
  trades: Trade[]
  monthly_returns: MonthlyReturn[]
}

const fmtMoney = (v: number) =>
  `¥ ${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const fmtPct = (v: number) => {
  const sign = v >= 0 ? "+" : ""
  return `${sign}${(v * 100).toFixed(2)}%`
}

const metricCards = (m: BacktestMetrics) => [
  {
    label: "年化收益",
    value: fmtPct(m.annual_return),
    icon: IconTrendingUp,
    positive: m.annual_return >= 0,
    sub: `总收益 ${fmtPct(m.total_return)}`,
  },
  {
    label: "夏普比率",
    value: m.sharpe.toFixed(2),
    icon: IconTarget,
    positive: m.sharpe >= 1,
    sub: m.sharpe >= 2 ? "优秀" : m.sharpe >= 1 ? "良好" : "偏低",
  },
  {
    label: "最大回撤",
    value: fmtPct(m.max_drawdown),
    icon: IconShield,
    positive: m.max_drawdown > -0.2,
    sub: m.max_drawdown > -0.1 ? "可控" : m.max_drawdown > -0.2 ? "偏高" : "严重",
  },
  {
    label: "胜率",
    value: `${(m.win_rate * 100).toFixed(1)}%`,
    icon: IconBolt,
    positive: m.win_rate >= 0.4,
    sub: `${m.win_count} 胜 / ${m.loss_count} 负`,
  },
  {
    label: "盈亏比",
    value: m.profit_factor.toFixed(2),
    icon: IconScale,
    positive: m.profit_factor >= 1.5,
    sub: m.profit_factor >= 2 ? "优秀" : m.profit_factor >= 1.2 ? "良好" : "偏低",
  },
  {
    label: "卡玛比率",
    value: m.calmar.toFixed(2),
    icon: IconTrendingDown,
    positive: m.calmar >= 1,
    sub: m.calmar >= 2 ? "优秀" : m.calmar >= 1 ? "良好" : "偏低",
  },
]

export function BacktestResults({ metrics, equity_curve, trades, monthly_returns }: BacktestResultsProps) {
  const [showTrades, setShowTrades] = React.useState(false)

  const sellTrades = trades.filter((t) => t.direction === "sell" && t.pnl != null)
  const buyTrades = trades.filter((t) => t.direction === "buy")

  return (
    <div className="space-y-4">
      {/* 指标卡片 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {metricCards(metrics).map((mc) => (
          <Card key={mc.label}>
            <CardContent className="py-3 px-3">
              <p className="text-[10px] text-muted-foreground mb-0.5 flex items-center gap-1">
                <mc.icon className="size-3" />
                {mc.label}
              </p>
              <p
                className={cn(
                  "text-sm font-mono font-semibold tabular-nums",
                  mc.positive ? "text-red-400" : "text-emerald-400"
                )}
              >
                {mc.value}
              </p>
              <p className="text-[10px] text-muted-foreground">{mc.sub}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 汇总行 */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary" className="text-[10px]">
          {metrics.num_trades} 笔交易
        </Badge>
        <span>
          初始 {fmtMoney(metrics.initial_cash)} → 终值 {fmtMoney(metrics.final_value)}
        </span>
        <span className={cn("font-mono", metrics.total_pnl >= 0 ? "text-red-400" : "text-emerald-400")}>
          净盈亏 {metrics.total_pnl >= 0 ? "+" : ""}{fmtMoney(metrics.total_pnl)}
        </span>
        <span className="text-[10px]">
          均盈 {fmtMoney(metrics.avg_win)} / 均亏 {fmtMoney(Math.abs(metrics.avg_loss))}
        </span>
      </div>

      {/* 净值曲线 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-xs">净值曲线</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartEquityCurve data={equity_curve} className="h-[260px]" />
        </CardContent>
      </Card>

      {/* 月度收益热力图 */}
      {monthly_returns.length > 0 && (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs">月度收益</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <td className="py-1 pr-4 font-medium text-muted-foreground">月份</td>
                    <td className="py-1 pr-4 font-medium text-muted-foreground text-right">策略</td>
                    <td className="py-1 pr-4 font-medium text-muted-foreground text-right">基准</td>
                    <td className="py-1 font-medium text-muted-foreground text-right">超额</td>
                  </tr>
                </thead>
                <tbody>
                  {monthly_returns.map((mr) => {
                    const excess =
                      mr.benchmark_return != null
                        ? mr.strategy_return - mr.benchmark_return
                        : null
                    return (
                      <tr key={mr.month} className="border-b border-border/50">
                        <td className="py-1 pr-4 font-mono text-muted-foreground">{mr.month}</td>
                        <td
                          className={cn(
                            "py-1 pr-4 font-mono text-right tabular-nums",
                            mr.strategy_return >= 0 ? "text-red-400" : "text-emerald-400"
                          )}
                        >
                          {mr.strategy_return >= 0 ? "+" : ""}
                          {mr.strategy_return.toFixed(2)}%
                        </td>
                        <td
                          className={cn(
                            "py-1 pr-4 font-mono text-right tabular-nums",
                            (mr.benchmark_return ?? 0) >= 0 ? "text-red-400" : "text-emerald-400"
                          )}
                        >
                          {mr.benchmark_return != null
                            ? `${mr.benchmark_return >= 0 ? "+" : ""}${mr.benchmark_return.toFixed(2)}%`
                            : "--"}
                        </td>
                        <td
                          className={cn(
                            "py-1 font-mono text-right tabular-nums",
                            (excess ?? 0) >= 0 ? "text-red-400" : "text-emerald-400"
                          )}
                        >
                          {excess != null
                            ? `${excess >= 0 ? "+" : ""}${excess.toFixed(2)}%`
                            : "--"}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 交易明细（折叠） */}
      {trades.length > 0 && (
        <Card>
          <CardHeader className="pb-1">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs">
                交易明细 ({buyTrades.length} 买 / {sellTrades.length} 卖)
              </CardTitle>
              <button
                onClick={() => setShowTrades(!showTrades)}
                className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                {showTrades ? "收起" : "展开"}
              </button>
            </div>
          </CardHeader>
          {showTrades && (
            <CardContent>
              <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border">
                      <td className="py-1 pr-2 font-medium text-muted-foreground">日期</td>
                      <td className="py-1 pr-2 font-medium text-muted-foreground">代码</td>
                      <td className="py-1 pr-2 font-medium text-muted-foreground">名称</td>
                      <td className="py-1 pr-2 font-medium text-muted-foreground text-center">方向</td>
                      <td className="py-1 pr-2 font-medium text-muted-foreground text-right">价格</td>
                      <td className="py-1 pr-2 font-medium text-muted-foreground text-right">股数</td>
                      <td className="py-1 pr-2 font-medium text-muted-foreground text-right">金额</td>
                      <td className="py-1 font-medium text-muted-foreground text-right">盈亏</td>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.id} className="border-b border-border/50">
                        <td className="py-1 pr-2 font-mono text-muted-foreground">{t.date}</td>
                        <td className="py-1 pr-2 font-mono">{t.code}</td>
                        <td className="py-1 pr-2">{t.name}</td>
                        <td className="py-1 pr-2 text-center">
                          <Badge
                            variant="outline"
                            className={cn(
                              "text-[10px]",
                              t.direction === "buy"
                                ? "text-red-400 border-red-500/20"
                                : "text-emerald-400 border-emerald-500/20"
                            )}
                          >
                            {t.direction === "buy" ? "买入" : "卖出"}
                          </Badge>
                        </td>
                        <td className="py-1 pr-2 font-mono text-right tabular-nums">
                          ¥{t.price.toFixed(2)}
                        </td>
                        <td className="py-1 pr-2 font-mono text-right tabular-nums">{t.shares}</td>
                        <td className="py-1 pr-2 font-mono text-right tabular-nums text-muted-foreground">
                          ¥{(t.price * t.shares).toLocaleString()}
                        </td>
                        <td
                          className={cn(
                            "py-1 font-mono text-right tabular-nums",
                            (t.pnl ?? 0) >= 0 ? "text-red-400" : "text-emerald-400"
                          )}
                        >
                          {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}¥${t.pnl.toFixed(2)}` : "--"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          )}
        </Card>
      )}
    </div>
  )
}
