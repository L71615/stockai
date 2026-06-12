"use client"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { IconTrendingUp, IconTrendingDown } from "@tabler/icons-react"

export function SectionCards() {
  return (
    <div className="grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4 dark:*:data-[slot=card]:bg-card">
      {/* 总资产 */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>总资产</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
            ¥ 1,250,000
          </CardTitle>
          <CardAction>
            <Badge variant="outline" className="text-red-500 border-red-500/20 bg-red-500/5">
              <IconTrendingUp />
              +12.5%
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium text-red-500">
            本月上涨 <IconTrendingUp className="size-4" />
          </div>
          <div className="text-muted-foreground">近 6 个月资产走势</div>
        </CardFooter>
      </Card>

      {/* 今日盈亏 */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>今日盈亏</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
            -¥ 3,420
          </CardTitle>
          <CardAction>
            <Badge variant="outline" className="text-emerald-500 border-emerald-500/20 bg-emerald-500/5">
              <IconTrendingDown />
              -0.27%
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium text-emerald-500">
            今日下跌 <IconTrendingDown className="size-4" />
          </div>
          <div className="text-muted-foreground">上证 -0.15% · 深证 -0.32%</div>
        </CardFooter>
      </Card>

      {/* 持仓数量 */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>持仓数量</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
            8<span className="text-base text-muted-foreground font-normal"> 只</span>
          </CardTitle>
          <CardAction>
            <Badge variant="outline" className="text-red-500 border-red-500/20 bg-red-500/5">
              <IconTrendingUp />
              5 涨 3 跌
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            整体持仓偏强
          </div>
          <div className="text-muted-foreground">仓位占比 78%</div>
        </CardFooter>
      </Card>

      {/* 胜率 */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>交易胜率</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl font-mono">
            62.5%
          </CardTitle>
          <CardAction>
            <Badge variant="outline" className="text-red-500 border-red-500/20 bg-red-500/5">
              <IconTrendingUp />
              +2.1%
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            近 20 笔交易
          </div>
          <div className="text-muted-foreground">盈亏比 2.4:1</div>
        </CardFooter>
      </Card>
    </div>
  )
}
