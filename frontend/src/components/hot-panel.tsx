"use client"

import * as React from "react"
import useSWR from "swr"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet } from "@/lib/auth"
import { IconTrendingUp, IconTrendingDown } from "@tabler/icons-react"

interface SectorFlow {
  name: string
  change_pct: number
}

interface NorthFlow {
  code: string
  name: string
  hold_value_wan: number
}

interface HeatmapData {
  sectors: SectorFlow[]
  north_inflow: NorthFlow[]
  update_time: string
}

function fmtVal(v: number) {
  const abs = Math.abs(v)
  if (abs >= 10000) return `${(abs / 10000).toFixed(1)}亿`
  if (abs >= 1) return `${abs.toFixed(0)}万`
  return `${(abs * 10000).toFixed(0)}`
}

function HotPanelInner() {
  const { data, error, isLoading } = useSWR<HeatmapData>(
    "/api/stocks/market-heatmap",
    (url: string) => apiGet<HeatmapData>(url),
    { refreshInterval: 300000, dedupingInterval: 60000 }
  )

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-2.5">
          <div className="grid grid-cols-2 gap-3">
            {[1, 2].map((i) => (
              <div key={i} className="space-y-1.5">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error || !data) return null

  const { sectors, north_inflow, update_time } = data

  return (
    <Card>
      <CardContent className="py-2.5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* 板块资金流向 */}
          <div>
            <p className="text-[10px] font-medium text-muted-foreground mb-1 flex items-center gap-1">
              <IconTrendingUp className="size-3 text-red-400" />
              板块资金
            </p>
            {sectors.length === 0 ? (
              <p className="text-[10px] text-muted-foreground">暂无数据</p>
            ) : (
              <div className="space-y-0.5">
                {sectors.slice(0, 5).map((s) => (
                  <div key={s.name} className="flex items-center justify-between text-[10px]">
                    <span className="truncate max-w-[90px]">{s.name}</span>
                    <span className={cn(
                      "font-mono tabular-nums",
                      s.change_pct >= 0 ? "text-red-400" : "text-emerald-400"
                    )}>
                      {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 北向资金持股 */}
          <div>
            <p className="text-[10px] font-medium text-muted-foreground mb-1 flex items-center gap-1">
              <IconTrendingDown className="size-3 text-blue-400" />
              北向资金持股 TOP5
            </p>
            {north_inflow.length === 0 ? (
              <p className="text-[10px] text-muted-foreground">暂无数据</p>
            ) : (
              <div className="space-y-0.5">
                {north_inflow.slice(0, 5).map((n) => (
                  <div key={n.code} className="flex items-center justify-between text-[10px]">
                    <span className="font-mono truncate max-w-[100px]">
                      {n.code} {n.name}
                    </span>
                    <span className="font-mono tabular-nums text-blue-400">
                      ¥{fmtVal(n.hold_value_wan)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        {update_time && (
          <p className="text-[9px] text-muted-foreground mt-2 text-right">{update_time}</p>
        )}
      </CardContent>
    </Card>
  )
}

export function HotPanel() {
  return (
    <React.Suspense fallback={null}>
      <HotPanelInner />
    </React.Suspense>
  )
}
