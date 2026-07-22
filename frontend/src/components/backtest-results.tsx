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
  overfit_warning?: string | null
  fees_included?: boolean
}

/** 过拟合检测详细 (v3.10 新增) */
export interface OverfitCheck {
  split_ratio: number
  train_period: [string, string]
  test_period: [string, string]
  train_days: number
  test_days: number
  train_metrics: { sharpe: number; total_return: number; max_drawdown: number }
  test_metrics: { sharpe: number; total_return: number; max_drawdown: number }
  sharpe_decay_pct: number
  verdict: "stable" | "watch" | "overfit" | "weak"
  message: string
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
  overfit?: OverfitCheck
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

export function BacktestResults({ metrics, equity_curve, trades, monthly_returns, overfit }: BacktestResultsProps) {
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
        {metrics.fees_included && (
          <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 text-muted-foreground">
            含手续费
          </Badge>
        )}
      </div>

      {/* 过拟合检测 — 样本外表现 (v3.10 新增) */}
      {overfit && (
        <Card className={cn(
          "border-2",
          overfit.verdict === "overfit" && "border-red-500/50 bg-red-500/5",
          overfit.verdict === "watch" && "border-yellow-500/50 bg-yellow-500/5",
          overfit.verdict === "stable" && "border-emerald-500/50 bg-emerald-500/5",
          overfit.verdict === "weak" && "border-orange-500/50 bg-orange-500/5",
        )}>
          <CardContent className="py-3">
            <div className="flex items-start justify-between mb-2">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-semibold">样本外表现（防过拟合）</span>
                  <Badge variant="outline" className={cn(
                    "text-[10px]",
                    overfit.verdict === "overfit" && "border-red-500/50 text-red-400",
                    overfit.verdict === "watch" && "border-yellow-500/50 text-yellow-400",
                    overfit.verdict === "stable" && "border-emerald-500/50 text-emerald-400",
                    overfit.verdict === "weak" && "border-orange-500/50 text-orange-400",
                  )}>
                    {overfit.verdict === "stable" ? "✓ 稳健" :
                     overfit.verdict === "watch" ? "⚡ 留意" :
                     overfit.verdict === "overfit" ? "⚠️ 过拟合" : "⚡ 整体弱"}
                  </Badge>
                </div>
                <p className="text-[11px] text-muted-foreground">{overfit.message}</p>
              </div>
              <div className="text-[10px] text-muted-foreground text-right">
                <div>切分 {Math.round(overfit.split_ratio * 100)}% / {100 - Math.round(overfit.split_ratio * 100)}%</div>
                <div>训练 {overfit.train_days} 天 / 测试 {overfit.test_days} 天</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] mt-2">
              <div className="rounded border border-border/40 bg-muted/20 p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-muted-foreground">训练 (前 {Math.round(overfit.split_ratio * 100)}%)</span>
                  <span className="text-[10px] text-muted-foreground">{overfit.train_period[0]} ~ {overfit.train_period[1]}</span>
                </div>
                <div className="font-mono">
                  Sharpe <span className={(overfit.train_metrics.sharpe ?? 0) >= 1 ? "text-red-400" : "text-muted-foreground"}>{(overfit.train_metrics.sharpe ?? 0).toFixed(2)}</span>
                </div>
                <div className="font-mono">
                  收益 <span className={((overfit.train_metrics.total_return ?? 0) >= 0) ? "text-red-400" : "text-emerald-400"}>{fmtPct(overfit.train_metrics.total_return ?? 0)}</span>
                </div>
              </div>
              <div className="rounded border border-border/40 bg-muted/20 p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-muted-foreground">测试 (后 {100 - Math.round(overfit.split_ratio * 100)}%)</span>
                  <span className="text-[10px] text-muted-foreground">{overfit.test_period[0]} ~ {overfit.test_period[1]}</span>
                </div>
                <div className="font-mono">
                  Sharpe <span className={(overfit.test_metrics.sharpe ?? 0) >= 1 ? "text-red-400" : "text-muted-foreground"}>{(overfit.test_metrics.sharpe ?? 0).toFixed(2)}</span>
                </div>
                <div className="font-mono">
                  收益 <span className={((overfit.test_metrics.total_return ?? 0) >= 0) ? "text-red-400" : "text-emerald-400"}>{fmtPct(overfit.test_metrics.total_return ?? 0)}</span>
                </div>
              </div>
            </div>
            {overfit.sharpe_decay_pct > 0.3 && (
              <p className="text-[10px] text-muted-foreground mt-2">
                Sharpe 下降 {Math.round(overfit.sharpe_decay_pct * 100)}% — 训练表现明显好于测试
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* 过拟合警告 (兼容旧字段) */}
      {metrics.overfit_warning && !overfit && (
        <Card className="border-yellow-500/30 bg-yellow-500/5">
          <CardContent className="py-2">
            <p className="text-xs text-yellow-400">⚠️ {metrics.overfit_warning}</p>
          </CardContent>
        </Card>
      )}

      {/* 净值曲线 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-xs">净值曲线</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartEquityCurve
            data={equity_curve}
            trades={trades.map((t) => ({
              id: t.id,
              date: t.date,
              direction: t.direction,
              price: t.price,
              pnl: t.pnl,
            }))}
            className="h-[260px]"
          />
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
