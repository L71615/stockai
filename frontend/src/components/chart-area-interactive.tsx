"use client"

import * as React from "react"
import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"

import { useIsMobile } from "@/hooks/use-mobile"
import {
  Card,
  CardAction,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group"

interface DataPoint {
  date: string
  cost: number
  value?: number
}

interface ChartAreaInteractiveProps {
  data: DataPoint[]
}

const chartConfig = {
  value: {
    label: "总市值",
    color: "#ef5350",
  },
  cost: {
    label: "成本",
    color: "#6b7280",
  },
} satisfies ChartConfig

export function ChartAreaInteractive({ data }: ChartAreaInteractiveProps) {
  const isMobile = useIsMobile()
  const [timeRange, setTimeRange] = React.useState("90d")

  React.useEffect(() => {
    if (isMobile) {
      setTimeRange("30d")
    }
  }, [isMobile])

  // Convert to chart data: use value if available, otherwise cost
  const chartData = data.map((d) => ({
    ...d,
    value: d.value ?? d.cost,
  }))

  // Use actual latest date as reference
  const referenceDate = chartData.length > 0
    ? new Date(chartData[chartData.length - 1].date)
    : new Date()

  const filteredData = chartData.filter((item) => {
    const date = new Date(item.date)
    let daysToSubtract = 90
    if (timeRange === "30d") {
      daysToSubtract = 30
    } else if (timeRange === "7d") {
      daysToSubtract = 7
    }
    const startDate = new Date(referenceDate)
    startDate.setDate(startDate.getDate() - daysToSubtract)
    return date >= startDate
  })

  if (chartData.length === 0) return null

  return (
    <Card className="@container/card">
      <CardHeader>
        <CardTitle>总资产走势</CardTitle>
        <CardDescription>
          <span className="hidden @[540px]/card:block">
            持仓成本投入与市值变化
          </span>
          <span className="@[540px]/card:hidden">持仓市值</span>
        </CardDescription>
        <CardAction>
          <ToggleGroup
            type="single"
            value={timeRange}
            onValueChange={setTimeRange}
            variant="outline"
            className="hidden *:data-[slot=toggle-group-item]:px-4! @[767px]/card:flex"
          >
            <ToggleGroupItem value="90d">近 3 月</ToggleGroupItem>
            <ToggleGroupItem value="30d">近 30 天</ToggleGroupItem>
            <ToggleGroupItem value="7d">近 7 天</ToggleGroupItem>
          </ToggleGroup>
          <Select value={timeRange} onValueChange={setTimeRange}>
            <SelectTrigger
              className="flex w-40 **:data-[slot=select-value]:block **:data-[slot=select-value]:truncate @[767px]/card:hidden"
              size="sm"
              aria-label="选择时间范围"
            >
              <SelectValue placeholder="近 3 月" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="90d">近 3 月</SelectItem>
              <SelectItem value="30d">近 30 天</SelectItem>
              <SelectItem value="7d">近 7 天</SelectItem>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        <ChartContainer
          config={chartConfig}
          className="aspect-auto h-[250px] w-full"
        >
          <AreaChart data={filteredData}>
            <defs>
              <linearGradient id="fillValue" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="5%"
                  stopColor="var(--color-value)"
                  stopOpacity={0.3}
                />
                <stop
                  offset="95%"
                  stopColor="var(--color-value)"
                  stopOpacity={0.02}
                />
              </linearGradient>
              <linearGradient id="fillCost" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="5%"
                  stopColor="var(--color-cost)"
                  stopOpacity={0.15}
                />
                <stop
                  offset="95%"
                  stopColor="var(--color-cost)"
                  stopOpacity={0.0}
                />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={32}
              tickFormatter={(value) => {
                const date = new Date(value)
                return `${date.getMonth() + 1}/${date.getDate()}`
              }}
            />
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  labelFormatter={(value) => {
                    return new Date(value).toLocaleDateString("zh-CN", {
                      month: "long",
                      day: "numeric",
                    })
                  }}
                  indicator="dot"
                />
              }
            />
            <Area
              dataKey="cost"
              type="monotone"
              fill="url(#fillCost)"
              stroke="var(--color-cost)"
              strokeWidth={1.5}
              strokeDasharray="4 2"
            />
            <Area
              dataKey="value"
              type="monotone"
              fill="url(#fillValue)"
              stroke="var(--color-value)"
              strokeWidth={2}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
