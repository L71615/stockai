"use client"

import * as React from "react"
import { Pie, PieChart, Label, Cell, Tooltip } from "recharts"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

interface SectorItem {
  name: string
  count: number
  market_value: number
  pct: number
}

interface SectorPieChartProps {
  data: SectorItem[]
  totalValue: number
}

// 暗色主题友好的行业配色
const COLORS = [
  "#6366f1", // indigo
  "#22d3ee", // cyan
  "#f59e0b", // amber
  "#a78bfa", // violet
  "#34d399", // emerald
  "#f472b6", // pink
  "#60a5fa", // blue
  "#fb923c", // orange
  "#4ade80", // green
  "#e879f9", // fuchsia
  "#38bdf8", // sky
  "#fbbf24", // yellow
]

const chartConfig = {
  pct: { label: "占比" },
} satisfies ChartConfig

export function SectorPieChart({ data, totalValue }: SectorPieChartProps) {
  const total = React.useMemo(() => {
    return data.reduce((acc, cur) => acc + cur.market_value, 0)
  }, [data])

  if (!data || data.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>行业分布</CardTitle>
        <CardDescription>持仓行业市值占比</CardDescription>
      </CardHeader>
      <CardContent className="flex-1 pb-0">
        <ChartContainer
          config={chartConfig}
          className="mx-auto aspect-square max-h-[300px]"
        >
          <PieChart>
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  hideLabel
                  formatter={(value, name, item) => {
                    const entry = item?.payload as SectorItem | undefined
                    if (!entry) return <></>
                    return (
                      <div className="flex min-w-[140px] items-center gap-2 text-xs">
                        <span
                          className="inline-block size-2.5 shrink-0 rounded-[2px]"
                          style={{ backgroundColor: item?.color }}
                        />
                        <span className="flex flex-1 items-center gap-1 text-muted-foreground">
                          {entry.name}
                        </span>
                        <span className="font-mono tabular-nums font-medium">
                          {entry.pct}%
                        </span>
                        <span className="text-muted-foreground font-mono tabular-nums">
                          ¥ {Math.round(entry.market_value).toLocaleString()}
                        </span>
                      </div>
                    )
                  }}
                />
              }
            />
            <Pie
              data={data}
              dataKey="market_value"
              nameKey="name"
              innerRadius={65}
              outerRadius={100}
              strokeWidth={2}
              stroke="var(--background)"
            >
              {data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={COLORS[index % COLORS.length]}
                  className="transition-opacity hover:opacity-80"
                />
              ))}
              <Label
                content={({ viewBox }) => {
                  if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                    return (
                      <text
                        x={viewBox.cx}
                        y={viewBox.cy}
                        textAnchor="middle"
                        dominantBaseline="middle"
                      >
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy || 0) - 8}
                          className="fill-foreground text-lg font-semibold font-mono"
                        >
                          {data.length} 个行业
                        </tspan>
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy || 0) + 16}
                          className="fill-muted-foreground text-xs"
                        >
                          ¥ {Math.round(totalValue).toLocaleString()}
                        </tspan>
                      </text>
                    )
                  }
                }}
              />
            </Pie>
          </PieChart>
        </ChartContainer>

        {/* 图例列表 */}
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 justify-center">
          {data.map((entry, index) => (
            <div
              key={entry.name}
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <span
                className="inline-block size-2.5 shrink-0 rounded-[2px]"
                style={{ backgroundColor: COLORS[index % COLORS.length] }}
              />
              <span>{entry.name}</span>
              <span className="font-mono tabular-nums text-foreground">
                {entry.pct}%
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
