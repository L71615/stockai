"use client"

import * as React from "react"
import { Area, ComposedChart, CartesianGrid, Scatter, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

interface EquityPoint {
  date: string
  value: number
  benchmark_value?: number | null
}

interface TradeMarker {
  id: number
  date: string
  direction: "buy" | "sell"
  price: number
  pnl: number | null
}

interface ChartEquityCurveProps {
  data: EquityPoint[]
  trades?: TradeMarker[]
  className?: string
}

const chartConfig = {
  value: {
    label: "策略净值",
    color: "#6366f1",
  },
  benchmark_value: {
    label: "基准",
    color: "#6b7280",
  },
} satisfies ChartConfig

function buildTradePoints(data: EquityPoint[], trades: TradeMarker[]) {
  if (!trades || trades.length === 0) return { buys: [], sells: [] }

  const dateToValue = new Map(data.map((d) => [d.date, d.value]))
  const buys: Array<{ x: string; y: number; trade: TradeMarker }> = []
  const sells: Array<{ x: string; y: number; trade: TradeMarker }> = []

  for (const t of trades) {
    // Find the equity value on the trade date (or nearest)
    let eqVal = dateToValue.get(t.date)
    if (eqVal === undefined) {
      // Find nearest date
      const dates = data.map((d) => d.date)
      const idx = dates.findIndex((d) => d >= t.date)
      eqVal = idx >= 0 ? data[idx].value : data[data.length - 1]?.value ?? 0
    }
    const pt = { x: t.date?.slice(5) ?? t.date, y: eqVal, trade: t }
    if (t.direction === "buy") {
      buys.push(pt)
    } else {
      sells.push(pt)
    }
  }
  return { buys, sells }
}

export function ChartEquityCurve({ data, trades, className }: ChartEquityCurveProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-xs text-muted-foreground">
        暂无净值数据
      </div>
    )
  }

  const formatted = data.map((d) => ({
    ...d,
    date: d.date?.slice(5) ?? d.date,
  }))

  const hasBenchmark = formatted.some((d) => d.benchmark_value != null)

  const tradePts = trades ? buildTradePoints(data, trades) : { buys: [], sells: [] }

  return (
    <ChartContainer config={chartConfig} className={className}>
      <ComposedChart data={formatted} margin={{ top: 8, right: 4, left: 4, bottom: 4 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" strokeOpacity={0.1} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={4}
          tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
          interval="preserveStartEnd"
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={4}
          tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
          tickFormatter={(v: number) =>
            v >= 1000 ? `${(v / 10000).toFixed(1)}万` : v.toFixed(0)
          }
          domain={["auto", "auto"]}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(label, payload) => {
                // Check if this is a trade marker tooltip
                const tradePayload = payload?.find((p) => p.dataKey === "buyMarker" || p.dataKey === "sellMarker")
                if (tradePayload?.payload?.trade) {
                  const t = tradePayload.payload.trade as TradeMarker
                  return `${t.date} ${t.direction === "buy" ? "买入" : "卖出"} ¥${t.price.toFixed(2)}`
                }
                return label as string
              }}
            />
          }
        />
        <defs>
          <linearGradient id="fillStrategy" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-value)" stopOpacity={0.15} />
            <stop offset="100%" stopColor="var(--color-value)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {hasBenchmark && (
          <Area
            dataKey="benchmark_value"
            type="monotone"
            fill="none"
            stroke="var(--color-benchmark_value)"
            strokeWidth={1}
            strokeDasharray="4 3"
            dot={false}
            activeDot={false}
          />
        )}
        <Area
          dataKey="value"
          type="monotone"
          fill="url(#fillStrategy)"
          stroke="var(--color-value)"
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, strokeWidth: 0 }}
        />

        {/* Buy markers: green upward triangles */}
        {tradePts.buys.length > 0 && (
          <Scatter
            data={tradePts.buys}
            dataKey="y"
            name="buyMarker"
            fill="#22c55e"
            stroke="#22c55e"
            shape={(props) => {
              const { cx, cy } = props as { cx: number; cy: number }
              if (cx == null || cy == null) return null
              return (
                <g>
                  <circle cx={cx} cy={cy} r={4} fill="#22c55e" fillOpacity={0.8} stroke="#fff" strokeWidth={1} />
                </g>
              )
            }}
            legendType="none"
          />
        )}

        {/* Sell markers: red downward triangles */}
        {tradePts.sells.length > 0 && (
          <Scatter
            data={tradePts.sells}
            dataKey="y"
            name="sellMarker"
            fill="#ef4444"
            stroke="#ef4444"
            shape={(props) => {
              const { cx, cy } = props as { cx: number; cy: number }
              if (cx == null || cy == null) return null
              return (
                <g>
                  <circle cx={cx} cy={cy} r={4} fill="#ef4444" fillOpacity={0.8} stroke="#fff" strokeWidth={1} />
                </g>
              )
            }}
            legendType="none"
          />
        )}
      </ComposedChart>
    </ChartContainer>
  )
}
