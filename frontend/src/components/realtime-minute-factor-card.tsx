"use client"

/**
 * 盘中分钟级 55 因子卡片 — v4.2 M2
 *
 * 默认展示 4 组核心因子: 价格 / 动量 / 波动 / 成交量
 * 数据源标记: 'historical_daily_fallback' (M2) / 'futu_1m' (v5.0-rc)
 */

import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useRealtimeMinuteFactor, MINUTE_FACTOR_GROUPS } from "@/hooks/use-realtime-minute-factor"
import { cn } from "@/lib/utils"
import { IconCircleDot } from "@tabler/icons-react"

interface Props {
  code: string | null | undefined
  className?: string
}

/** 百分比因子 (后端返 0-1 比率) — 显示时 ×100 + % */
const PERCENT_FACTORS = new Set([
  // 价格偏离度
  "ma5", "ma10", "ma20", "ma60", "price_position",
  // 收益率
  "ret_5d", "ret_20d", "ret_60d",
  // BOLL 偏离度
  "boll_position",
  // 量价比率
  "vol_ratio", "turnover_rate",
  // K 线形态偏离
  "klen", "kup", "klow", "kmid",
  // 量价相关/变化
  "price_volume_corr", "vroc", "vol_change", "hist_vol_5d", "hist_vol_20d",
  "volatility_ratio", "amplitude_20d", "downside_vol",
  // 个股情绪
  "strength", "momentum_score", "acceleration",
])

export function RealtimeMinuteFactorCard({ code, className }: Props) {
  const { factors, isLoading, lastUpdate, barCount, dataSource } = useRealtimeMinuteFactor(
    code,
    { refreshMs: 30000 }
  )

  if (!code) {
    return null
  }

  if (isLoading && Object.keys(factors).length === 0) {
    return <Skeleton className="h-48 w-full" />
  }

  const fmt = (v: number | null | undefined, decimals = 2): string => {
    if (v === null || v === undefined) return "--"
    return v.toFixed(decimals)
  }

  const isFallback = dataSource === "historical_daily_fallback"

  return (
    <Card className={className}>
      <CardContent className="py-3">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs text-muted-foreground">
            分钟因子 · {code} · <span className="text-[10px]">{Object.keys(factors).length}</span> 个
          </p>
          <p className="text-[10px] text-muted-foreground flex items-center gap-1">
            <IconCircleDot
              className={cn(
                "size-3",
                isFallback ? "text-yellow-500" : "text-emerald-500"
              )}
            />
            {isFallback ? "日级 fallback" : dataSource || "未知源"}
            {barCount > 0 && ` · ${barCount} bar`}
          </p>
        </div>

        <FactorGroup
          title="价格"
          names={MINUTE_FACTOR_GROUPS.价格}
          factors={factors}
          fmt={fmt}
        />
        <FactorGroup
          title="动量"
          names={MINUTE_FACTOR_GROUPS.动量}
          factors={factors}
          fmt={fmt}
          decimalsMap={{ macd_signal: 3, hist_vol_5d: 3, hist_vol_20d: 3 }}
        />
        <FactorGroup
          title="波动"
          names={MINUTE_FACTOR_GROUPS.波动.slice(0, 6)}
          factors={factors}
          fmt={fmt}
          decimalsMap={{ atr_14: 3, amplitude_20d: 3, volatility_ratio: 3 }}
        />
        <FactorGroup
          title="成交量"
          names={MINUTE_FACTOR_GROUPS.成交量}
          factors={factors}
          fmt={fmt}
        />
      </CardContent>
    </Card>
  )
}

function FactorGroup({
  title,
  names,
  factors,
  fmt,
  decimalsMap = {},
}: {
  title: string
  names: string[]
  factors: Record<string, number | null | undefined>
  fmt: (v: number | null | undefined, decimals?: number) => string
  decimalsMap?: Record<string, number>
}) {
  return (
    <div className="mb-2 last:mb-0">
      <p className="text-[10px] text-muted-foreground mb-1">{title}</p>
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2 text-xs">
        {names.map((name) => {
          const v = factors[name]
          const decimals = decimalsMap[name] ?? 2
          const display = PERCENT_FACTORS.has(name)
            ? (v === null || v === undefined ? "--" : `${(v * 100).toFixed(decimals)}%`)
            : fmt(v, decimals)
          return (
            <div key={name} className="border border-border rounded-none p-1.5">
              <p className="text-[10px] text-muted-foreground">{name}</p>
              <p className="font-mono tabular-nums">{display}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}