"use client"

import { useEffect, useRef } from "react"
import {
  createChart,
  AreaSeries,
  type IChartApi,
  type ISeriesApi,
  type AreaData,
  type Time,
} from "lightweight-charts"

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useShadowEquity, type ShadowEquityPoint } from "@/hooks/use-shadow-equity"

import { IconTrendingUp, IconTrendingDown } from "@tabler/icons-react"
import { cn } from "@/lib/utils"

/**
 * v4.1 1B.2: Shadow 净值曲线 (1d / 4h / 1h bucket)
 *
 * - 冷启动 (<5 天数据): 显示骨架屏 + "积累中 N/30" 提示
 * - 正常情况: lightweight-charts AreaSeries + 累计收益 + 最大回撤
 */
export function ShadowEquityChart({
  portfolioId,
  days = 30,
}: {
  portfolioId: number | null
  days?: number
}) {
  const { points, accumulating, isLoading, error } = useShadowEquity(portfolioId, "1d", days)

  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    if (points.length === 0) return

    // 创建图表 (只在第一次 / 容器变化时)
    if (!chartRef.current) {
      chartRef.current = createChart(containerRef.current, {
        layout: { background: { color: "transparent" }, textColor: "#9ca3af" },
        grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
        timeScale: { borderColor: "#3f3f46" },
        rightPriceScale: { borderColor: "#3f3f46" },
        width: containerRef.current.clientWidth,
        height: 240,
      })
      seriesRef.current = chartRef.current.addSeries(AreaSeries, {
        lineColor: "#22c55e",
        topColor: "rgba(34, 197, 94, 0.4)",
        bottomColor: "rgba(34, 197, 94, 0.02)",
        lineWidth: 2,
      })
    }

    // 填充数据 (lightweight-charts 需要 ascending 时间)
    const data: AreaData[] = points
      .map((p: ShadowEquityPoint) => ({
        time: p.date as Time,
        value: p.nav,
      }))
      .sort((a, b) => (a.time < b.time ? -1 : 1))

    seriesRef.current?.setData(data)
    chartRef.current?.timeScale().fitContent()

    // 容器大小变化时自动 resize
    const onResize = () => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.resize(containerRef.current.clientWidth, 240)
      }
    }
    window.addEventListener("resize", onResize)

    return () => {
      window.removeEventListener("resize", onResize)
    }
  }, [points])

  // 卸载时清理 chart
  useEffect(() => {
    return () => {
      chartRef.current?.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">影子组合净值曲线</CardTitle>
          <CardDescription>v3.11 shadow portfolio · 1d bucket</CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[240px] w-full" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">影子组合净值曲线</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">数据源失败 — 稍后刷新</div>
        </CardContent>
      </Card>
    )
  }

  if (accumulating) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">影子组合净值曲线</CardTitle>
          <CardDescription>冷启动 — 数据积累中</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-[240px] text-center space-y-2">
            <div className="text-3xl font-mono tabular-nums text-muted-foreground">
              {points.length} / 30
            </div>
            <div className="text-sm text-muted-foreground">
              影子组合刚启动，{30 - points.length} 个交易日后开始绘制
            </div>
            <div className="text-xs text-muted-foreground/60">
              每天 09:30 watcher 结算后自动增长
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  // 正常显示
  const firstNav = points[0]?.nav ?? 1
  const lastNav = points[points.length - 1]?.nav ?? 1
  const totalReturn = (lastNav / firstNav - 1) * 100
  const maxDrawdown = Math.min(...points.map((p) => p.drawdown)) * 100  // drawdown 是负值

  const isPositive = totalReturn >= 0

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-base">影子组合净值曲线</CardTitle>
            <CardDescription>
              v3.11 shadow portfolio · {points.length} 个交易日 · 1d bucket
            </CardDescription>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <div className="flex items-center gap-1">
              {isPositive ? (
                <IconTrendingUp className="size-4 text-green-500" />
              ) : (
                <IconTrendingDown className="size-4 text-red-500" />
              )}
              <span
                className={cn(
                  "font-mono tabular-nums font-semibold",
                  isPositive ? "text-green-500" : "text-red-500",
                )}
              >
                {isPositive ? "+" : ""}
                {totalReturn.toFixed(2)}%
              </span>
            </div>
            <div className="text-muted-foreground">
              回撤 <span className="font-mono tabular-nums text-red-400">{maxDrawdown.toFixed(2)}%</span>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div ref={containerRef} className="w-full h-[240px]" />
      </CardContent>
    </Card>
  )
}