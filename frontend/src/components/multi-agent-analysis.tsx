"use client"

import * as React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiPost } from "@/lib/auth"
import {
  IconBrain,
  IconChartBar,
  IconReportMoney,
  IconArrowUp,
  IconArrowDown,
  IconGavel,
  IconShield,
  IconTarget,
  IconPlayerPlay,
} from "@tabler/icons-react"

interface AnalysisResult {
  error?: string
  code: string
  name: string
  price: number
  technical_report: string
  fundamentals_report: string
  bull_case: string
  bear_case: string
  verdict: string
  confidence: number
  key_reasons: string[]
  risk_warning: string
  suggested_hold_days: number | null
  stop_loss_pct: number | null
}

const PHASES = [
  { key: "tech", label: "技术面 + 基本面分析", icon: IconChartBar },
  { key: "debate", label: "多空辩论", icon: IconGavel },
  { key: "judge", label: "生成最终判断", icon: IconBrain },
]

export function MultiAgentAnalysis() {
  const [code, setCode] = React.useState("")
  const [loading, setLoading] = React.useState(false)
  const [phase, setPhase] = React.useState(0)
  const [result, setResult] = React.useState<AnalysisResult | null>(null)
  const [error, setError] = React.useState("")
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({})

  const toggle = (key: string) => setExpanded((p) => ({ ...p, [key]: !p[key] }))

  const analyze = async () => {
    if (!code.trim()) return
    setLoading(true); setError(""); setResult(null)
    setPhase(0)
    const timer1 = setTimeout(() => setPhase(1), 3000)
    const timer2 = setTimeout(() => setPhase(2), 10000)
    try {
      const data = await apiPost<AnalysisResult>("/api/quant/multi-agent-analysis", { code: code.trim() })
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "分析失败")
    } finally {
      clearTimeout(timer1); clearTimeout(timer2)
      setLoading(false); setPhase(0)
    }
  }

  const verdictColor =
    result?.verdict === "买入" ? "text-red-400 bg-red-500/10" :
    result?.verdict === "卖出" ? "text-emerald-400 bg-emerald-500/10" :
    "text-yellow-400 bg-yellow-500/10"

  const confidenceColor =
    (result?.confidence ?? 0) >= 0.7 ? "text-purple-400" :
    (result?.confidence ?? 0) >= 0.4 ? "text-yellow-400" : "text-muted-foreground"

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-xs">AI 深度分析</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-end gap-2">
            <div className="space-y-1 flex-1">
              <Label className="text-[10px]">股票代码</Label>
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && analyze()}
                placeholder="600519"
                className="h-8 w-32 font-mono"
              />
            </div>
            <Button size="sm" onClick={analyze} disabled={loading || !code.trim()}>
              <IconPlayerPlay className="size-3.5" />
              {loading ? "分析中..." : "开始分析"}
            </Button>
          </div>
          {loading && (
            <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              <Skeleton className="h-4 w-4 rounded-full" />
              <span>{PHASES[phase]?.label ?? "分析中..."}</span>
            </div>
          )}
          {error && <p className="text-xs text-destructive mt-2">{error}</p>}
        </CardContent>
      </Card>

      {result && (
        <>
          {/* Verdict */}
          <Card className="border-l-[3px] border-l-purple-400">
            <CardContent className="py-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <IconGavel className="size-4 text-purple-400" />
                  <span className="font-mono text-sm">{result.code}</span>
                  <span className="text-xs text-muted-foreground">{result.name}</span>
                  <span className="text-xs font-mono">¥{result.price}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge className={cn("text-xs", verdictColor)}>{result.verdict}</Badge>
                  <Badge variant="outline" className={cn("text-[10px]", confidenceColor)}>
                    置信度 {(result.confidence * 100).toFixed(0)}%
                  </Badge>
                </div>
              </div>
              {result.key_reasons.length > 0 && (
                <div className="space-y-0.5 mb-2">
                  {result.key_reasons.map((r, i) => (
                    <p key={i} className="text-xs text-muted-foreground">• {r}</p>
                  ))}
                </div>
              )}
              <div className="flex gap-4 text-[10px] text-muted-foreground">
                {result.suggested_hold_days && <span>建议持仓 {result.suggested_hold_days} 天</span>}
                {result.stop_loss_pct && <span>止损 -{result.stop_loss_pct}%</span>}
                {result.risk_warning && (
                  <span className="flex items-center gap-1"><IconShield className="size-3" />{result.risk_warning}</span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Bull vs Bear */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            <Card className="border-l-[3px] border-l-red-400">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconArrowUp className="size-3 text-red-400" />多头论点
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground whitespace-pre-line">
                  {expanded.bull ? result.bull_case : result.bull_case.slice(0, 200)}
                  {result.bull_case.length > 200 && (
                    <button className="text-purple-400 ml-1" onClick={() => toggle("bull")}>
                      {expanded.bull ? "收起" : "展开"}
                    </button>
                  )}
                </p>
              </CardContent>
            </Card>
            <Card className="border-l-[3px] border-l-emerald-400">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconArrowDown className="size-3 text-emerald-400" />空头论点
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground whitespace-pre-line">
                  {expanded.bear ? result.bear_case : result.bear_case.slice(0, 200)}
                  {result.bear_case.length > 200 && (
                    <button className="text-purple-400 ml-1" onClick={() => toggle("bear")}>
                      {expanded.bear ? "收起" : "展开"}
                    </button>
                  )}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Reports */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconChartBar className="size-3" />技术面报告
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground whitespace-pre-line">
                  {expanded.tech ? result.technical_report : result.technical_report.slice(0, 200)}
                  {result.technical_report.length > 200 && (
                    <button className="text-purple-400 ml-1" onClick={() => toggle("tech")}>
                      {expanded.tech ? "收起" : "展开"}
                    </button>
                  )}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconReportMoney className="size-3" />基本面报告
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground whitespace-pre-line">
                  {expanded.fund ? result.fundamentals_report : result.fundamentals_report.slice(0, 200)}
                  {result.fundamentals_report.length > 200 && (
                    <button className="text-purple-400 ml-1" onClick={() => toggle("fund")}>
                      {expanded.fund ? "收起" : "展开"}
                    </button>
                  )}
                </p>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
