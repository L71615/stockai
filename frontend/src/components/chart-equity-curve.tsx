"use client"

import * as React from "react"
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts"

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

interface ChartEquityCurveProps {
  data: EquityPoint[]
  className?: string
}

const chartConfig = {
  value: {
    label: "策略净值",
    color: "#6366f1",  // indigo
  },
  benchmark_value: {
    label: "基准",
    color: "#6b7280",  // gray-500
  },
} satisfies ChartConfig

export function ChartEquityCurve({ data, className }: ChartEquityCurveProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-xs text-muted-foreground">
        暂无净值数据
      </div>
    )
  }

  const formatted = data.map((d) => ({
    ...d,
    date: d.date?.slice(5) ?? d.date,  // MM-DD 格式
  }))

  const hasBenchmark = formatted.some((d) => d.benchmark_value != null)

  return (
    <ChartContainer config={chartConfig} className={className}>
      <AreaChart data={formatted} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
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
        <ChartTooltip content={<ChartTooltipContent />} />
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
      </AreaChart>
    </ChartContainer>
  )
}
