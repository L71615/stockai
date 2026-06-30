"use client"

import { useState, useEffect } from "react"
import { apiGet } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { useIsMobile } from "@/hooks/use-mobile"
import type { KlineResponse } from "@/lib/api-types"
import { KlineChart } from "./KlineChart"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import { z } from "zod"

export const stockDetailSchema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  shares: z.string(),
  price: z.string(),
  cost: z.string(),
  pnl: z.string(),
  pnlPct: z.string(),
})

export type StockDetailItem = z.infer<typeof stockDetailSchema>

export function StockDetailDrawer({ item }: { item: StockDetailItem }) {
  const isMobile = useIsMobile()
  const [period, setPeriod] = useState("1m")
  const [chartData, setChartData] = useState<KlineResponse | null>(null)
  const [chartLoading, setChartLoading] = useState(false)

  useEffect(() => {
    if (!item.code) return
    setChartLoading(true)
    apiGet<KlineResponse>("/api/stocks/kline/" + item.code + "?period=" + period)
      .then((raw) => setChartData(raw))
      .catch(() => {})
      .finally(() => setChartLoading(false))
  }, [item.code, period])

  const pers = [
    { k: "5d", l: "5日" },
    { k: "1m", l: "1月" },
    { k: "3m", l: "3月" },
    { k: "6m", l: "6月" },
  ]

  return (
    <Drawer direction={isMobile ? "bottom" : "right"}>
      <DrawerTrigger asChild>
        <Button variant="link" className="w-fit px-0 text-left text-foreground font-medium">{item.name}</Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle className="font-mono">{item.code} {item.name}</DrawerTitle>
          <DrawerDescription className="sr-only">股票详情与K线图表</DrawerDescription>
        </DrawerHeader>
        <div className="flex flex-col gap-2 overflow-y-auto px-4 text-sm">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-muted-foreground">现价</span> <span className="font-mono ml-1">{item.price}</span></div>
            <div><span className="text-muted-foreground">成本</span> <span className="font-mono ml-1">{item.cost}</span></div>
            <div><span className="text-muted-foreground">持仓</span> <span className="font-mono ml-1">{item.shares}</span></div>
            <div><span className={cn("font-mono", String(item.pnl).startsWith("+") ? "text-red-500" : String(item.pnl).startsWith("-") ? "text-emerald-500" : "")}>{item.pnl} ({item.pnlPct})</span></div>
          </div>
          <Separator />
          <div className="flex gap-1">
            {pers.map((p) => (
              <button key={p.k} onClick={() => setPeriod(p.k)} className={cn("px-3 py-1 text-xs border-b-2", period === p.k ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>{p.l}</button>
            ))}
          </div>
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <span><span className="inline-block w-3 h-0.5 bg-amber-500 align-middle mr-0.5" />MA5</span>
            <span><span className="inline-block w-3 h-0.5 bg-purple-500 align-middle mr-0.5" />MA10</span>
            <span><span className="inline-block w-3 h-0.5 bg-cyan-500 align-middle mr-0.5" />MA20</span>
          </div>
          {chartLoading ? (
            <div className="space-y-2"><Skeleton className="h-[260px] w-full" /><Skeleton className="h-[70px] w-full" /></div>
          ) : !chartData?.dates?.length ? (
            <p className="text-xs text-muted-foreground text-center py-12">暂无数据</p>
          ) : (
            <>
              <KlineChart rawData={chartData} height={260} showIndicatorSelector={false} />
              <KlineChart rawData={chartData} height={70} showIndicatorSelector={false} />
            </>
          )}
        </div>
        <DrawerFooter>
        <DrawerClose asChild>
          <Button variant="outline" size="sm">关闭</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  )
}
