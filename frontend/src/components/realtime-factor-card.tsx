"use client"

import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useRealtimeFactor } from "@/hooks/use-realtime-factor"
import { cn } from "@/lib/utils"

interface Props {
  code: string | null | undefined
  className?: string
}

/**
 * 盘中因子卡片 — v5.0-alpha M2
 * 默认展示 trend / tech / momentum 三组核心因子
 */
export function RealtimeFactorCard({ code, className }: Props) {
  const { factors, isLoading, lastUpdate, barCount } = useRealtimeFactor(code, {
    refreshMs: 30000,
    names: [
      "MA5", "MA10", "MA20", "MA60",
      "RSI", "MACD", "BOLL_UPPER", "BOLL_LOWER", "BOLL_POSITION",
      "RET_5D", "RET_20D",
    ],
  })

  if (!code) {
    return null
  }

  if (isLoading && Object.keys(factors).length === 0) {
    return <Skeleton className="h-32 w-full" />
  }

  const fmt = (v: number | null | undefined, decimals = 2): string => {
    if (v === null || v === undefined) return "--"
    return v.toFixed(decimals)
  }

  return (
    <Card className={className}>
      <CardContent className="py-3">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs text-muted-foreground">盘中因子 · {code}</p>
          <p className="text-[10px] text-muted-foreground">
            {barCount > 0 ? `${barCount} bar` : "无数据"}
            {lastUpdate > 0 && ` · ${Math.max(0, Math.floor(Date.now() / 1000 - lastUpdate))}s 前`}
          </p>
        </div>

        <FactorGroup
          title="趋势"
          items={[
            { label: "MA5", value: factors.MA5, color: "text-blue-400" },
            { label: "MA10", value: factors.MA10, color: "text-blue-400" },
            { label: "MA20", value: factors.MA20, color: "text-blue-400" },
            { label: "MA60", value: factors.MA60, color: "text-blue-400" },
          ]}
        />

        <FactorGroup
          title="技术"
          items={[
            { label: "RSI", value: factors.RSI, decimals: 1 },
            { label: "MACD", value: factors.MACD, decimals: 3 },
            { label: "BOLL 上", value: factors.BOLL_UPPER },
            { label: "BOLL 下", value: factors.BOLL_LOWER },
            { label: "BOLL 位", value: factors.BOLL_POSITION, decimals: 3 },
          ]}
        />

        <FactorGroup
          title="动量"
          items={[
            { label: "5日", value: factors.RET_5D, decimals: 3 },
            { label: "20日", value: factors.RET_20D, decimals: 3 },
          ]}
        />
      </CardContent>
    </Card>
  )
}

function FactorGroup({
  title,
  items,
}: {
  title: string
  items: Array<{ label: string; value: number | null | undefined; decimals?: number; color?: string }>
}) {
  return (
    <div className="mb-2 last:mb-0">
      <p className="text-[10px] text-muted-foreground mb-1">{title}</p>
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2 text-xs">
        {items.map((it) => (
          <div key={it.label} className="border border-border rounded-none p-1.5">
            <p className="text-[10px] text-muted-foreground">{it.label}</p>
            <p className={cn("font-mono", it.color)}>
              {it.value === null || it.value === undefined
                ? "--"
                : it.value.toFixed(it.decimals ?? 2)}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}