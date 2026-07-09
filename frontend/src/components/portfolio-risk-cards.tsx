"use client"

import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface RiskData {
  sharpe?: number | null
  max_drawdown?: number | null
  volatility?: number | null
  beta?: number | null
}

export function PortfolioRiskCards({ data }: { data: RiskData | null | undefined }) {
  if (!data || data.sharpe == null) return null

  return (
    <div className="px-4 lg:px-6">
      <div className="grid grid-cols-2 gap-2 @xl/main:grid-cols-4">
        <Card>
          <CardContent className="py-2 text-center">
            <p className="text-[10px] text-muted-foreground">Sharpe 比率</p>
            <p className={cn("text-sm font-mono font-semibold tabular-nums",
              (data.sharpe ?? 0) >= 1 ? "text-green-400" : "text-muted-foreground"
            )}>{(data.sharpe ?? 0).toFixed(2)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-2 text-center">
            <p className="text-[10px] text-muted-foreground">最大回撤</p>
            <p className={cn("text-sm font-mono font-semibold tabular-nums",
              (data.max_drawdown ?? 0) > -0.15 ? "text-green-400" : "text-red-400"
            )}>{data.max_drawdown != null ? `${(data.max_drawdown * 100).toFixed(1)}%` : "--"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-2 text-center">
            <p className="text-[10px] text-muted-foreground">年化波动率</p>
            <p className="text-sm font-mono font-semibold tabular-nums text-muted-foreground">
              {data.volatility != null ? `${(data.volatility * 100).toFixed(1)}%` : "--"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-2 text-center">
            <p className="text-[10px] text-muted-foreground">Beta (沪深300)</p>
            <p className="text-sm font-mono font-semibold tabular-nums text-muted-foreground">
              {(data.beta ?? 0).toFixed(2)}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
