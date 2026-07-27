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
  IconCoin,
  IconBuildingMonument,
  IconArrowUp,
  IconArrowDown,
  IconArrowBigDownLines,
  IconGavel,
  IconShield,
  IconTarget,
  IconPlayerPlay,
} from "@tabler/icons-react"

/** v4.0 (A1): 8 角色结果。5 角色字段保留,新增 3 角色字段。 */
interface AnalysisResult {
  error?: string
  code: string
  name: string
  price: number
  // Round 1 — 4 分析面
  technical_report: string
  fundamentals_report: string
  capital_flow_report: string    // v4.0 新增
  policy_report: string          // v4.0 新增
  // Round 2 — 3 辩论
  bull_case: string
  bear_case: string
  short_researcher_case: string  // v4.0 新增
  // Round 3 — 裁判
  verdict: string
  confidence: number
  key_reasons: string[]
  risk_warning: string
  suggested_hold_days: number | null
  stop_loss_pct: number | null
  // v4.0 A3 — CoT 推理链
  reasoning_chain?: {
    step1_signals?: string[]
    step2_evaluation?: string
    step3_risks?: string
    step4_decision?: string
    step5_confidence?: string
  }
  // 元数据
  agent_count?: number
  enabled_roles?: string[]
  enable_cot?: boolean
}

const PHASES = [
  { key: "r1", label: "8 角色并行分析(技术+基本面+资金面+政策)", icon: IconChartBar },
  { key: "r2", label: "3 角色辩论(多+空+做空)", icon: IconGavel },
  { key: "r3", label: "生成最终判断", icon: IconBrain },
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

              {/* v4.0 A3 — CoT 推理链(可折叠) */}
              {result.reasoning_chain && Object.keys(result.reasoning_chain).length > 0 && (
                <details className="mt-2 text-[10px]">
                  <summary className="cursor-pointer text-purple-400 hover:underline">
                    推理链 (CoT 5 步) {result.enable_cot === false ? "(已关闭)" : ""}
                  </summary>
                  <div className="mt-2 space-y-1.5 pl-3 border-l-2 border-purple-500/30">
                    {result.reasoning_chain.step1_signals && result.reasoning_chain.step1_signals.length > 0 && (
                      <div>
                        <span className="text-muted-foreground">Step 1 — 关键信号:</span>
                        <ul className="list-disc list-inside pl-2">
                          {result.reasoning_chain.step1_signals.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {result.reasoning_chain.step2_evaluation && (
                      <div><span className="text-muted-foreground">Step 2 — 多空评估:</span> {result.reasoning_chain.step2_evaluation}</div>
                    )}
                    {result.reasoning_chain.step3_risks && (
                      <div><span className="text-muted-foreground">Step 3 — 风险:</span> {result.reasoning_chain.step3_risks}</div>
                    )}
                    {result.reasoning_chain.step4_decision && (
                      <div><span className="text-muted-foreground">Step 4 — 决策:</span> {result.reasoning_chain.step4_decision}</div>
                    )}
                    {result.reasoning_chain.step5_confidence && (
                      <div><span className="text-muted-foreground">Step 5 — 信心:</span> {result.reasoning_chain.step5_confidence}</div>
                    )}
                  </div>
                </details>
              )}
            </CardContent>
          </Card>

          {/* v4.0 (A1): 8 角色报告 — 2x4 网格布局 */}
          {/* Round 1 — 4 分析面:技术 + 基本面 + 资金面 + 政策 */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
            <ReportCard
              title="技术面"
              icon={<IconChartBar className="size-3" />}
              content={result.technical_report}
              field="tech"
              expanded={expanded.tech}
              onToggle={toggle}
            />
            <ReportCard
              title="基本面"
              icon={<IconReportMoney className="size-3" />}
              content={result.fundamentals_report}
              field="fund"
              expanded={expanded.fund}
              onToggle={toggle}
            />
            <ReportCard
              title="资金面"
              icon={<IconCoin className="size-3" />}
              content={result.capital_flow_report}
              field="capital"
              expanded={expanded.capital}
              onToggle={toggle}
            />
            <ReportCard
              title="政策解读"
              icon={<IconBuildingMonument className="size-3" />}
              content={result.policy_report}
              field="policy"
              expanded={expanded.policy}
              onToggle={toggle}
            />
          </div>

          {/* Round 2 — 3 辩论角色:多 + 空 + 做空 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <Card className="border-l-[3px] border-l-red-400">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconArrowUp className="size-3 text-red-400" />多头论点
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ReportBody
                  content={result.bull_case}
                  field="bull"
                  expanded={expanded.bull}
                  onToggle={toggle}
                />
              </CardContent>
            </Card>
            <Card className="border-l-[3px] border-l-emerald-400">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconArrowDown className="size-3 text-emerald-400" />空头论点
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ReportBody
                  content={result.bear_case}
                  field="bear"
                  expanded={expanded.bear}
                  onToggle={toggle}
                />
              </CardContent>
            </Card>
            <Card className="border-l-[3px] border-l-amber-400">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs flex items-center gap-1">
                  <IconArrowBigDownLines className="size-3 text-amber-400" />做空论点
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ReportBody
                  content={result.short_researcher_case}
                  field="short"
                  expanded={expanded.short}
                  onToggle={toggle}
                />
              </CardContent>
            </Card>
          </div>

          {/* Agent 元数据 */}
          {result.agent_count && (
            <p className="text-[10px] text-muted-foreground text-center">
              本次分析调用 {result.agent_count} 个 Agent 角色
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** 报告卡(标题 + 折叠正文) */
function ReportCard({
  title,
  icon,
  content,
  field,
  expanded,
  onToggle,
}: {
  title: string
  icon: React.ReactNode
  content: string
  field: string
  expanded: boolean
  onToggle: (key: string) => void
}) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-xs flex items-center gap-1">
          {icon}{title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ReportBody
          content={content}
          field={field}
          expanded={expanded}
          onToggle={onToggle}
        />
      </CardContent>
    </Card>
  )
}

/** 报告正文(超过 200 字折叠) */
function ReportBody({
  content,
  field,
  expanded,
  onToggle,
}: {
  content: string
  field: string
  expanded: boolean
  onToggle: (key: string) => void
}) {
  if (!content) {
    return <p className="text-[10px] text-muted-foreground italic">未启用该角色</p>
  }
  const sliced = content.slice(0, 200)
  const truncated = content.length > 200
  return (
    <p className="text-xs text-muted-foreground whitespace-pre-line">
      {expanded ? content : sliced}
      {truncated && (
        <button
          className="text-purple-400 ml-1"
          onClick={() => onToggle(field)}
        >
          {expanded ? "收起" : "展开"}
        </button>
      )}
    </p>
  )
}
