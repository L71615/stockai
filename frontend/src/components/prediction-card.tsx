"use client"

import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { IconTrendingUp, IconChevronDown, IconChevronRight } from "@tabler/icons-react"

interface TopMatch {
  date: string; stock_code: string
  fwd_ret_1d: number | null; fwd_ret_3d: number | null
  similarity: number
}

interface PredictionResult {
  stock_code: string; stock_name?: string
  probability_1d: number | null; probability_3d: number | null
  similar_count: number
  win_count_1d: number; win_count_3d: number
  avg_similarity: number
  top_matches: TopMatch[]
  error?: string; status?: string
}

function probLabel(p: number | null): { text: string; color: string } {
  if (p == null) return { text: "--", color: "text-muted-foreground" }
  if (p >= 0.65) return { text: `${(p * 100).toFixed(0)}%`, color: "text-emerald-400" }
  if (p >= 0.5) return { text: `${(p * 100).toFixed(0)}%`, color: "text-yellow-400" }
  return { text: `${(p * 100).toFixed(0)}%`, color: "text-red-400" }
}

export function PredictionCard({ data, isLoading }: { data: PredictionResult | null; isLoading?: boolean }) {
  const [expanded, setExpanded] = useState(false)

  if (isLoading) {
    return (
      <Card className="border-l-[3px] border-l-blue-400">
        <CardContent className="py-3">
          <p className="text-xs text-muted-foreground">正在分析历史规律...</p>
        </CardContent>
      </Card>
    )
  }

  if (!data || data.status === "not_ready") {
    return null
  }

  if (data.error) {
    return (
      <Card className="border-l-[3px] border-l-orange-400">
        <CardContent className="py-3">
          <p className="text-xs text-orange-400">{data.error}</p>
        </CardContent>
      </Card>
    )
  }

  const p1 = probLabel(data.probability_1d)
  const p3 = probLabel(data.probability_3d)

  return (
    <Card className="border-l-[3px] border-l-blue-400">
      <CardContent className="py-3">
        <div className="flex items-center justify-between">
          <p className="flex items-center gap-1 text-xs font-medium text-blue-400">
            <IconTrendingUp className="size-3" />
            趋势预测 · {data.stock_code}
          </p>
          <Button variant="ghost" size="sm" className="h-5 text-[10px]"
            onClick={() => setExpanded(!expanded)}>
            {expanded ? "收起" : "详情"}
            {expanded ? <IconChevronDown className="size-3" /> : <IconChevronRight className="size-3" />}
          </Button>
        </div>

        <div className="flex gap-4 mt-1.5">
          <div className="text-center">
            <p className="text-[10px] text-muted-foreground">明日上涨</p>
            <p className={`text-lg font-bold ${p1.color}`}>{p1.text}</p>
          </div>
          <div className="text-center">
            <p className="text-[10px] text-muted-foreground">3日上涨</p>
            <p className={`text-lg font-bold ${p3.color}`}>{p3.text}</p>
          </div>
          <div className="text-center">
            <p className="text-[10px] text-muted-foreground">历史参考</p>
            <p className="text-xs text-muted-foreground">
              类似 <span className="font-mono text-foreground">{data.similar_count}</span> 次
              {data.win_count_1d != null && (
                <span className="ml-1">· 涨 <span className="text-emerald-400">{data.win_count_1d}</span> 次</span>
              )}
            </p>
          </div>
        </div>

        {expanded && data.top_matches?.length > 0 && (
          <div className="mt-2 pt-2 border-t border-border space-y-1">
            <p className="text-[10px] text-muted-foreground mb-1">最相似的历史时刻:</p>
            {data.top_matches.slice(0, 5).map((m, i) => (
              <div key={i} className="flex items-center justify-between text-[10px]">
                <span className="font-mono text-muted-foreground">{m.date}</span>
                <span className="font-mono">{m.stock_code}</span>
                <Badge variant="outline" className="text-[9px] px-1">
                  相似 {(m.similarity * 100).toFixed(0)}%
                </Badge>
                <span className={m.fwd_ret_1d != null && m.fwd_ret_1d > 0 ? "text-emerald-400" : "text-red-400"}>
                  {m.fwd_ret_1d != null ? `${(m.fwd_ret_1d * 100).toFixed(1)}%` : "--"}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
