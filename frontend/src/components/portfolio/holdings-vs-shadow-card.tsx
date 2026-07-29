"use client"

/**
 * v4.1 1B.4: 持仓 vs 影子组合差异卡
 *
 * 永远显示策略名 (无 active 时显示"未选择"占位)
 * 7/30/90/180 天窗口可切换
 * 冷启动 UX: 积累中 (N/30) 黄色 badge / 数据完整 N 个快照 绿色 badge
 */
import { useMemo, useState } from "react"
import {
  IconTrendingUp,
  IconTrendingDown,
  IconMinus,
  IconArrowRight,
  IconChevronDown,
  IconChevronUp,
} from "@tabler/icons-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { usePortfolioComparison } from "@/hooks/use-portfolio-comparison"
import { cn } from "@/lib/utils"
import type {
  HoldingVsShadowDiff,
  PortfolioComparisonResponse,
  WindowKey,
} from "@/lib/api-types"

const WINDOW_OPTIONS: WindowKey[] = ["7d", "30d", "90d", "180d"]

interface HoldingsVsShadowCardProps {
  window?: WindowKey
  maxRows?: number
  className?: string
}

export function HoldingsVsShadowCard({
  window: initialWindow = "30d",
  maxRows = 10,
  className,
}: HoldingsVsShadowCardProps) {
  const [window, setWindow] = useState<WindowKey>(initialWindow)
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading, error } = usePortfolioComparison(window)

  return (
    <div className={cn("px-4 lg:px-6", className)}>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">持仓 vs 影子组合</CardTitle>
              <CardDescription>
                策略:{" "}
                <span className="font-medium text-foreground">
                  {data?.shadow_portfolio_name ?? "未选择"}
                </span>
                {data?.snapshot_date && (
                  <span className="ml-2 text-muted-foreground/60">
                    · 最近 snapshot {data.snapshot_date}
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <WindowSelector value={window} onChange={setWindow} />
              <StatusBadge data={data} />
            </div>
          </div>
        </CardHeader>

        <CardContent>
          {isLoading ? (
            <SkeletonGrid />
          ) : error ? (
            <ErrorState />
          ) : data ? (
            <ComparisonBody
              data={data}
              maxRows={maxRows}
              expanded={expanded}
              onToggleExpand={() => setExpanded((v) => !v)}
            />
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

// ─────────────────────── Sub Components ───────────────────────

function WindowSelector({
  value,
  onChange,
}: {
  value: WindowKey
  onChange: (w: WindowKey) => void
}) {
  return (
    <div className="flex items-center gap-1 rounded-md border border-border bg-background p-0.5">
      {WINDOW_OPTIONS.map((w) => (
        <button
          key={w}
          type="button"
          onClick={() => onChange(w)}
          className={cn(
            "rounded px-2 py-0.5 text-xs font-mono tabular-nums transition-colors",
            value === w
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {w}
        </button>
      ))}
    </div>
  )
}

function StatusBadge({ data }: { data: PortfolioComparisonResponse | undefined }) {
  if (!data) return null
  if (data.shadow_portfolio_id == null) {
    return (
      <span className="rounded bg-zinc-700 px-2 py-0.5 text-[10px] text-zinc-300">
        无影子组合
      </span>
    )
  }
  if (data.accumulating) {
    return (
      <span className="rounded bg-yellow-900/40 px-2 py-0.5 text-[10px] text-yellow-400">
        积累中 ({data.snapshot_count}/{data.snapshot_target})
      </span>
    )
  }
  return (
    <span className="rounded bg-green-900/40 px-2 py-0.5 text-[10px] text-green-400">
      数据完整 · {data.snapshot_count} 个快照
    </span>
  )
}

function SkeletonGrid() {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
      <Skeleton className="h-40 w-full" />
    </div>
  )
}

function ErrorState() {
  return (
    <div className="py-6 text-center text-sm text-muted-foreground">
      数据源失败 — 稍后刷新
    </div>
  )
}

function ComparisonBody({
  data,
  maxRows,
  expanded,
  onToggleExpand,
}: {
  data: PortfolioComparisonResponse
  maxRows: number
  expanded: boolean
  onToggleExpand: () => void
}) {
  const sortedRows = useMemo(() => {
    return [...data.rows].sort((a, b) => {
      const a_dmv = Math.abs(a.delta_market_value ?? 0)
      const b_dmv = Math.abs(b.delta_market_value ?? 0)
      return b_dmv - a_dmv
    })
  }, [data.rows])

  const visibleRows = expanded ? sortedRows : sortedRows.slice(0, maxRows)
  const hasMore = sortedRows.length > maxRows

  return (
    <div className="space-y-4">
      {/* 汇总 2 列 */}
      <SummaryGrid data={data} />

      {/* 表格 */}
      {sortedRows.length === 0 ? (
        <EmptyDiff />
      ) : (
        <>
          <DiffTable rows={visibleRows} />
          {hasMore && (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={onToggleExpand}
                className="flex items-center gap-1 rounded px-3 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {expanded ? (
                  <>
                    <IconChevronUp className="size-3" />
                    收起 ({sortedRows.length - maxRows} 行隐藏)
                  </>
                ) : (
                  <>
                    <IconChevronDown className="size-3" />
                    展开全部 ({sortedRows.length} 行)
                  </>
                )}
              </button>
            </div>
          )}
        </>
      )}

      {/* Footer */}
      <CardFooterRow data={data} />
    </div>
  )
}

function SummaryGrid({ data }: { data: PortfolioComparisonResponse }) {
  const a = data.actual
  const s = data.shadow
  const ds = data.diff_summary
  const aPnlColor = (a.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
  const shadowGainColor = (s.delta_nav_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"
  const gapPositive = (ds.value_gap ?? 0) >= 0

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
      {/* 我的持仓 */}
      <SummaryColumn
        title="我的持仓"
        rows={[
          { label: "市值", value: formatCurrency(a.market_value), className: "text-foreground" },
          {
            label: "盈亏",
            value: formatCurrency(a.pnl),
            className: aPnlColor,
          },
          {
            label: "收益率",
            value: formatPct(a.pnl_pct),
            className: aPnlColor,
          },
          { label: "今日", value: formatCurrency(a.today_pnl), className: aPnlColor },
        ]}
      />

      {/* 中间 delta */}
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-accent/20 p-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {gapPositive ? (
            <IconTrendingUp className="size-4 text-blue-400" />
          ) : (
            <IconTrendingDown className="size-4 text-purple-400" />
          )}
          <span>持仓 − 影子</span>
        </div>
        <div className={cn(
          "mt-1 font-mono text-lg font-semibold tabular-nums",
          gapPositive ? "text-blue-400" : "text-purple-400",
        )}>
          {gapPositive ? "+" : ""}
          {formatCurrency(ds.value_gap)}
        </div>
        <div className="text-[10px] text-muted-foreground/70 tabular-nums">
          {formatPct(ds.value_gap_pct)} · {ds.position_overlap_count} 重叠 /{" "}
          {ds.actual_only_count} 独有 / {ds.shadow_only_count} 影子独有
        </div>
      </div>

      {/* 影子 NAV */}
      <SummaryColumn
        title={`影子 NAV${data.shadow_portfolio_name ? ` · ${data.shadow_portfolio_name}` : ""}`}
        rows={[
          { label: "NAV", value: formatCurrency(s.nav), className: "text-foreground" },
          {
            label: "持仓市值",
            value: formatCurrency(s.market_value),
            className: "text-muted-foreground",
          },
          { label: "现金", value: formatCurrency(s.cash), className: "text-muted-foreground" },
          {
            label: `ΔNAV (${data.window_days}d)`,
            value: `${formatPct(s.delta_nav_pct)}`,
            className: shadowGainColor,
          },
        ]}
      />
    </div>
  )
}

function SummaryColumn({
  title,
  rows,
}: {
  title: string
  rows: { label: string; value: string; className?: string }[]
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between">
            <span className="text-xs text-muted-foreground">{r.label}</span>
            <span
              className={cn(
                "font-mono text-sm font-semibold tabular-nums",
                r.className ?? "text-foreground",
              )}
            >
              {r.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyDiff() {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-10 text-center">
      <IconMinus className="size-6 text-muted-foreground/50" />
      <p className="mt-2 text-sm text-muted-foreground">
        当前没有可比对的持仓 — 跑一次 pipeline 生成影子组合后再来看
      </p>
    </div>
  )
}

function DiffTable({ rows }: { rows: HoldingVsShadowDiff[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left">代码</th>
            <th className="px-2 py-1.5 text-left">名称</th>
            <th className="px-2 py-1.5 text-right">实际 qty</th>
            <th className="px-2 py-1.5 text-right">实际 mv</th>
            <th className="px-2 py-1.5 text-right">实际 pnl%</th>
            <th className="px-2 py-1.5 text-right">影子 shares</th>
            <th className="px-2 py-1.5 text-right">影子 weight</th>
            <th className="px-2 py-1.5 text-right">Δqty</th>
            <th className="px-2 py-1.5 text-right">Δmv</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <DiffRow key={row.stock_code} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DiffRow({ row }: { row: HoldingVsShadowDiff }) {
  const bgClass = {
    both: "",
    actual_only: "bg-blue-950/20",
    shadow_only: "bg-purple-950/20",
    aligned_zero: "bg-zinc-900/30",
  }[row.diff_side]

  const pnlPctClass = (row.actual.pnl_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"

  return (
    <tr className={cn("border-b border-border/40 hover:bg-accent/30", bgClass)}>
      <td className="px-2 py-1.5 font-mono tabular-nums">{row.stock_code}</td>
      <td className="px-2 py-1.5 max-w-[120px] truncate" title={row.stock_name}>
        {row.stock_name}
      </td>
      <td className="px-2 py-1.5 text-right font-mono tabular-nums">
        {row.actual.quantity ?? <span className="text-muted-foreground/40">—</span>}
      </td>
      <td className="px-2 py-1.5 text-right font-mono tabular-nums">
        {row.actual.market_value != null ? formatCurrency(row.actual.market_value) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>
      <td className={cn("px-2 py-1.5 text-right font-mono tabular-nums", pnlPctClass)}>
        {row.actual.pnl_pct != null ? formatPct(row.actual.pnl_pct) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>
      <td className="px-2 py-1.5 text-right font-mono tabular-nums">
        {row.shadow.quantity ?? <span className="text-muted-foreground/40">—</span>}
      </td>
      <td className="px-2 py-1.5 text-right font-mono tabular-nums">
        {row.shadow.weight_pct != null ? `${row.shadow.weight_pct.toFixed(2)}%` : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>
      <td className="px-2 py-1.5 text-right font-mono tabular-nums">
        {row.delta_qty != null ? (
          <DeltaIndicator value={row.delta_qty} />
        ) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>
      <td className="px-2 py-1.5 text-right font-mono tabular-nums">
        {row.delta_market_value != null ? (
          <DeltaIndicator value={row.delta_market_value} currency />
        ) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>
    </tr>
  )
}

function DeltaIndicator({ value, currency }: { value: number; currency?: boolean }) {
  if (value === 0) {
    return <span className="text-muted-foreground/60">0</span>
  }
  const isPos = value > 0
  const formatted = currency ? formatCurrency(value) : value.toString()
  return (
    <span className={isPos ? "text-blue-400" : "text-purple-400"}>
      {isPos ? "+" : ""}
      {formatted}
    </span>
  )
}

function CardFooterRow({ data }: { data: PortfolioComparisonResponse }) {
  return (
    <div className="flex items-center justify-between border-t border-border/40 pt-2 text-[10px] text-muted-foreground">
      <div>
        {data.shadow_portfolio_id == null
          ? "无 active 影子组合"
          : data.accumulating
            ? `积累中 (${data.snapshot_count}/${data.snapshot_target})`
            : `数据完整 · ${data.snapshot_count} 个快照`}
      </div>
      <div className="flex items-center gap-1">
        管理影子组合
        <IconArrowRight className="size-3" />
      </div>
    </div>
  )
}

// ─────────────────────── Formatters ───────────────────────

function formatCurrency(v: number | null | undefined): string {
  if (v == null) return "—"
  const abs = Math.abs(v)
  const sign = v < 0 ? "-" : ""
  if (abs >= 1_0000_0000) return `${sign}¥${(abs / 1_0000_0000).toFixed(2)}亿`
  if (abs >= 1_0000) return `${sign}¥${(abs / 1_0000).toFixed(2)}万`
  return `${sign}¥${abs.toFixed(2)}`
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return "—"
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
}