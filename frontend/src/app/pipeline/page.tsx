"use client"

import { useCallback, useEffect, useState } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost } from "@/lib/auth"
import { cn } from "@/lib/utils"
import {
  IconPlayerPlay, IconRefresh, IconCircleCheck, IconAlertTriangle,
  IconCircleX, IconClock, IconInbox, IconHistory, IconScale,
  IconTrendingUp,
} from "@tabler/icons-react"

import { useProposals } from "@/hooks/use-pipeline"
import { ProposalRow, ProposalRowSkeleton } from "@/components/pipeline/ProposalRow"
import { ShadowEquityChart } from "@/components/pipeline/ShadowEquityChart"
import { useShadowPortfolios } from "@/hooks/use-shadow-portfolios"

// ════════════════════════════════════════════════════════════
//  T6 /pipeline 页面
//  - 默认 Tab: 收件箱 (4 子 tab: pending / approved / rejected / expired)
//  - 第二个 Tab: Runs (原 auto-pipeline runner)
// ════════════════════════════════════════════════════════════

export default function PipelinePage() {
  return (
    <>
      <SiteHeader title="量化 Pipeline" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6 max-w-7xl mx-auto w-full">
          <Tabs defaultValue="inbox">
            <TabsList>
              <TabsTrigger value="inbox">
                <IconInbox className="size-3.5 mr-1" />
                收件箱
              </TabsTrigger>
              <TabsTrigger value="runs">
                <IconPlayerPlay className="size-3.5 mr-1" />
                运行
              </TabsTrigger>
              <TabsTrigger value="counterfactual">
                <IconScale className="size-3.5 mr-1" />
                反事实
              </TabsTrigger>
              <TabsTrigger value="shadow">
                <IconTrendingUp className="size-3.5 mr-1" />
                影子组合
              </TabsTrigger>
            </TabsList>

            <TabsContent value="inbox" className="mt-4">
              <InboxView />
            </TabsContent>

            <TabsContent value="runs" className="mt-4">
              <RunsView />
            </TabsContent>

            <TabsContent value="counterfactual" className="mt-4">
              <CounterfactualView />
            </TabsContent>

            <TabsContent value="shadow" className="mt-4">
              <ShadowView />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </>
  )
}

// ════════════════════════════════════════════════════════════
//  收件箱 (默认 Tab)
// ════════════════════════════════════════════════════════════

function InboxView() {
  const [subTab, setSubTab] = useState<"pending" | "approved" | "rejected" | "expired">("pending")
  const { data, error, isLoading, mutate } = useProposals(subTab)

  const proposals = data?.proposals ?? []

  return (
    <div className="space-y-3">
      {/* Status banner */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm">审批收件箱</CardTitle>
              <CardDescription className="text-xs">
                三轴状态变更需人工确认 (CAS + TTL lease, v3.11)
              </CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => mutate()}>
              <IconRefresh className="size-3.5 mr-1" />刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={subTab} onValueChange={(v) => setSubTab(v as typeof subTab)}>
            <TabsList>
              <TabsTrigger value="pending">待审批</TabsTrigger>
              <TabsTrigger value="approved">已通过</TabsTrigger>
              <TabsTrigger value="rejected">已拒绝</TabsTrigger>
              <TabsTrigger value="expired">已过期</TabsTrigger>
            </TabsList>
          </Tabs>
        </CardContent>
      </Card>

      {/* 列表 */}
      {error && (
        <Card className="border-red-500/40">
          <CardContent className="p-4 text-xs text-red-400">
            加载失败: {String(error?.message || error)}
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <ProposalRowSkeleton key={i} />)}
        </div>
      ) : proposals.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-xs text-muted-foreground">
            {subTab === "pending" ? "暂无待审批建议" : `${subTab} 列表为空`}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {proposals.map((p) => (
            <ProposalRow key={p.proposal_id} proposal={p} onDecided={() => mutate()} />
          ))}
        </div>
      )}

      {/* 底部提示 */}
      <p className="text-[10px] text-muted-foreground text-center py-2">
        keyboard: ↑↓/j k 切换行 · ⏎ 接受 · Esc 关闭 · ? 显示快捷键
      </p>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  Runs (原 auto-pipeline runner 内容)
// ════════════════════════════════════════════════════════════

interface PipelineStatus {
  run_id?: string
  status: "running" | "done" | "failed" | "partial" | "idle"
  current_step?: number
  total_steps?: number
  steps?: Array<{
    name: string
    status: string
    index?: number
    candidates?: number
    kept?: number
    base_ir?: number
    enhanced_ir?: number
    lift_pct?: number
    warning_count?: number
    warnings?: Array<{ level: string; type: string; factors: string[]; message: string }>
    retired_count?: number
    status_detail?: string
    error?: string
  }>
  started_at?: string
  finished_at?: string
  summary?: Record<string, unknown>
  errors?: Array<{ step: string; error: string; ts: string }>
}

interface HealthData {
  overall_status: "ok" | "stale" | "down" | "rate_limited"
  checks: {
    akshare: { status: string; latency_ms?: number; error?: string }
    futu: { status: string; connected?: boolean; error?: string }
    db_freshness: { latest_date?: string; days_ago?: number; status: string }
  }
  issues: string[]
  checked_at: string
}

interface BriefItem {
  id: string
  created_at: string
}

function RunsView() {
  const [status, setStatus] = useState<PipelineStatus | null>(null)
  const [health, setHealth] = useState<HealthData | null>(null)
  const [briefs, setBriefs] = useState<BriefItem[]>([])
  const [latestBrief, setLatestBrief] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [tick, setTick] = useState(0)

  const fetchAll = useCallback(async () => {
    try {
      const [s, h, b] = await Promise.all([
        apiGet<PipelineStatus>("/api/pipeline/status").catch(() => null),
        apiGet<HealthData>("/api/pipeline/health").catch(() => null),
        apiGet<{ briefs: BriefItem[] }>("/api/pipeline/briefs").catch(() => ({ briefs: [] })),
      ])
      if (s) setStatus(s)
      if (h) setHealth(h)
      if (b?.briefs) setBriefs(b.briefs)
    } catch (e) {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll, tick])

  useEffect(() => {
    if (status?.status !== "running") return
    const t = setInterval(() => setTick((x) => x + 1), 3000)
    return () => clearInterval(t)
  }, [status?.status])

  const triggerRun = async () => {
    setRunning(true)
    try {
      await apiPost("/api/pipeline/run")
      setTick((x) => x + 1)
      setTimeout(() => setTick((x) => x + 1), 2000)
    } catch (e) {
      alert("触发失败: " + (e instanceof Error ? e.message : "未知"))
    } finally {
      setRunning(false)
    }
  }

  const loadBrief = async () => {
    try {
      const b = await apiGet<{ id: string; content_md: string; created_at: string }>("/api/pipeline/brief")
      setLatestBrief(b.content_md)
    } catch {
      setLatestBrief(null)
    }
  }

  useEffect(() => {
    if (briefs.length > 0) loadBrief()
  }, [briefs])

  const steps = status?.steps ?? []
  const stepEmoji = (s: string) => s === "done" ? "✅" : s === "failed" ? "❌" : s === "running" ? "⏳" : "·"
  const [openWarnings, setOpenWarnings] = useState<Record<string, boolean>>({})
  const toggleWarnings = (name: string) => setOpenWarnings((m) => ({ ...m, [name]: !m[name] }))

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm">自动量化 Pipeline</CardTitle>
              <CardDescription className="text-xs">
                每天 18:00 自动跑: GP 挖 → ML 训 → 过拟合验证 → 衰减检查 → 简报推送
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => setTick((x) => x + 1)}>
                <IconRefresh className="size-3.5 mr-1" />刷新
              </Button>
              <Button size="sm" onClick={triggerRun} disabled={running || status?.status === "running"}>
                <IconPlayerPlay className="size-3.5 mr-1" />
                {running || status?.status === "running" ? "跑中..." : "立即跑一次"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-12 w-full" />
          ) : (
            <div className="flex items-center gap-3 text-sm">
              <span className="font-semibold">状态:</span>
              {status?.status === "running" ? (
                <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/40">
                  <IconClock className="size-3 mr-1 animate-pulse" /> 跑中
                </Badge>
              ) : status?.status === "done" ? (
                <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/40">
                  <IconCircleCheck className="size-3 mr-1" />完成
                </Badge>
              ) : status?.status === "partial" ? (
                <Badge className="bg-yellow-500/20 text-yellow-400 border-yellow-500/40">
                  <IconAlertTriangle className="size-3 mr-1" />部分完成
                </Badge>
              ) : (
                <Badge variant="outline">未运行</Badge>
              )}
              {status?.started_at && (
                <span className="text-xs text-muted-foreground">
                  开始: {new Date(status.started_at).toLocaleString("zh-CN")}
                </span>
              )}
              {status?.summary && Object.keys(status.summary).length > 0 && (
                <span className="text-xs text-muted-foreground">
                  耗时: {String(status.summary.elapsed_s ?? "?")}s
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {health && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">数据源健康</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <HealthItem
                  label="akshare"
                  status={health.checks.akshare.status}
                  detail={health.checks.akshare.latency_ms ? `${health.checks.akshare.latency_ms}ms` : (health.checks.akshare.error ?? "")}
                />
                <HealthItem
                  label="Futu OpenD"
                  status={health.checks.futu.status}
                  detail={health.checks.futu.connected ? "已连" : (health.checks.futu.error ?? "")}
                />
                <HealthItem
                  label="DB 最新数据"
                  status={health.checks.db_freshness.status}
                  detail={health.checks.db_freshness.latest_date
                    ? `${health.checks.db_freshness.latest_date} (${health.checks.db_freshness.days_ago} 天前)`
                    : ""}
                />
              </div>
              {health.issues.length > 0 && (
                <ul className="mt-3 space-y-1 text-xs">
                  {health.issues.map((issue, i) => (
                    <li key={i} className="text-yellow-400">⚠️ {issue}</li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}

        {steps.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">5 步进度</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="space-y-2 text-sm">
                {steps.map((step) => (
                  <li key={step.name} className="flex items-center gap-2">
                    <span className="text-base">{stepEmoji(step.status)}</span>
                    <span className="font-mono text-xs">{step.name}</span>
                    <span className={cn(
                      "text-xs",
                      step.status === "done" ? "text-emerald-400" :
                      step.status === "failed" ? "text-red-400" :
                      step.status === "running" ? "text-blue-400" : "text-muted-foreground"
                    )}>
                      {step.status}
                    </span>
                    {step.candidates !== undefined && (
                      <span className="text-xs text-muted-foreground">候选: {step.candidates}</span>
                    )}
                    {step.lift_pct !== undefined && (
                      <span className="text-xs text-muted-foreground">IR 提升: {step.lift_pct}%</span>
                    )}
                    {(step.warning_count ?? step.warnings?.length ?? 0) > 0 && (
                      <button
                        type="button"
                        onClick={() => toggleWarnings(step.name)}
                        className="text-xs text-yellow-400 hover:underline"
                      >
                        告警: {step.warning_count ?? step.warnings?.length ?? 0} 个 {openWarnings[step.name] ? "▾" : "▸"}
                      </button>
                    )}
                    {step.error && (
                      <span className="text-xs text-red-400 truncate" title={step.error}>err: {step.error}</span>
                    )}
                  </li>
                ))}
              </ol>
              {steps.some((s) => openWarnings[s.name] && (s.warnings?.length ?? 0) > 0) && (
                <ul className="mt-3 space-y-1 border-t border-border/40 pt-2">
                  {steps
                    .filter((s) => openWarnings[s.name] && (s.warnings?.length ?? 0) > 0)
                    .flatMap((s) =>
                      (s.warnings ?? []).map((w, i) => (
                        <li key={`${s.name}-${i}`} className="text-xs text-yellow-400/90">
                          <span className="font-mono text-[10px] text-muted-foreground mr-1">[{s.name}]</span>
                          <Badge variant="outline" className="mr-1 text-[10px] py-0">{w.level}</Badge>
                          {w.type && <Badge variant="outline" className="mr-1 text-[10px] py-0">{w.type}</Badge>}
                          {w.message}
                        </li>
                      )),
                    )}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">历史简报 ({briefs.length})</CardTitle>
            <Button size="sm" variant="ghost" onClick={loadBrief}>
              <IconRefresh className="size-3.5" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {briefs.length === 0 ? (
            <p className="text-xs text-muted-foreground py-4 text-center">
              暂无简报, 点上方"立即跑一次"生成第一份
            </p>
          ) : (
            <div className="space-y-2">
              {briefs.map((b) => (
                <button
                  key={b.id}
                  onClick={loadBrief}
                  className="block w-full text-left px-3 py-2 rounded border border-border/40 hover:bg-accent/30 text-xs"
                >
                  <span className="font-mono">{b.id}</span>
                  <span className="text-muted-foreground ml-2">{b.created_at}</span>
                </button>
              ))}
            </div>
          )}
          {latestBrief && (
            <pre className="mt-4 p-3 bg-muted/30 rounded text-xs whitespace-pre-wrap font-mono overflow-auto max-h-96">
              {latestBrief}
            </pre>
          )}
        </CardContent>
      </Card>

      {status?.errors && status.errors.length > 0 && (
        <Card className="border-red-500/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-red-400">错误列表</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="text-xs space-y-1">
              {status.errors.map((e, i) => (
                <li key={i} className="text-red-400">
                  [{e.step}] {e.error}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function HealthItem({ label, status, detail }: { label: string; status: string; detail: string }) {
  const Icon = status === "ok" ? IconCircleCheck : status === "down" || status === "critical" ? IconCircleX : IconAlertTriangle
  const color = status === "ok" ? "text-emerald-400" : status === "down" || status === "critical" ? "text-red-400" : "text-yellow-400"
  return (
    <div className="rounded border border-border/40 p-2 bg-muted/20">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={cn("flex items-center gap-1 mt-1 text-sm font-semibold", color)}>
        <Icon className="size-3.5" />{status}
      </div>
      {detail && <div className="text-[10px] text-muted-foreground mt-0.5">{detail}</div>}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  v4.0 C1 — 反事实报告视图
//  - 对比 approved vs rejected 的实际表现
//  - 列出每条反事实的 hypothesis / evidence / realized / lesson
// ════════════════════════════════════════════════════════════

interface CounterfactualSummary {
  window: { since: string; until: string }
  baseline_code: string
  accepted: {
    count: number
    avg_fwd_return: number
    avg_baseline_diff: number
    good_rate: number
  }
  rejected: {
    count: number
    avg_fwd_return: number
    avg_baseline_diff: number
    good_rate: number
  }
  edge: number
  interpretation: string
  v4_metadata?: { phase: string; days: number; data_source: string }
}

interface Retrospective {
  retro_id: number
  proposal_id: number
  experiment_id: string
  decision: string
  fwd_days: number
  fwd_return: number
  fwd_baseline_diff: number
  hypothesis: string
  evidence_summary: string
  realized_summary: string
  lesson: string
  confidence: number
  created_at: string
}

function CounterfactualView() {
  const [days, setDays] = useState(30)
  const [summary, setSummary] = useState<CounterfactualSummary | null>(null)
  const [retros, setRetros] = useState<Retrospective[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, r] = await Promise.all([
        apiGet<CounterfactualSummary>(`/api/pipeline/counterfactual?days=${days}`),
        apiGet<{ retrospectives: Retrospective[] }>(`/api/pipeline/retrospectives?limit=20`),
      ])
      setSummary(s)
      setRetros(r?.retrospectives ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    load()
  }, [load])

  const edge = summary?.edge ?? 0
  const edgePositive = edge > 0

  return (
    <div className="space-y-4">
      {/* Header + 时间窗口选择 */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm">反事实报告</CardTitle>
              <CardDescription className="text-xs">
                对比"通过"和"拒绝"的实际表现, 衡量 pipeline 的决策质量
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <select
                className="h-8 rounded border border-border/40 bg-background px-2 text-xs"
                value={days}
                onChange={(e) => setDays(parseInt(e.target.value, 10))}
              >
                <option value={7}>最近 7 天</option>
                <option value={30}>最近 30 天</option>
                <option value={60}>最近 60 天</option>
                <option value={90}>最近 90 天</option>
              </select>
              <Button size="sm" variant="outline" onClick={load}>
                <IconRefresh className="size-3.5 mr-1" />刷新
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {error && (
        <Card className="border-red-500/40">
          <CardContent className="p-4 text-xs text-red-400">
            加载失败: {error}
          </CardContent>
        </Card>
      )}

      {loading ? (
        <Skeleton className="h-32 w-full" />
      ) : summary && (
        <>
          {/* 摘要: 通过 vs 拒绝 表现对比 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <CounterfactualCard
              title="已通过"
              decision="approved"
              data={summary.accepted}
              accent="emerald"
            />
            <CounterfactualCard
              title="已拒绝"
              decision="rejected"
              data={summary.rejected}
              accent="red"
            />
            <Card className={cn(
              "border-l-[3px]",
              edgePositive ? "border-l-emerald-400" : "border-l-amber-400"
            )}>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs">决策 Edge</CardTitle>
                <CardDescription className="text-[10px]">通过 - 拒绝 收益差</CardDescription>
              </CardHeader>
              <CardContent>
                <div className={cn(
                  "text-2xl font-mono font-semibold",
                  edgePositive ? "text-emerald-400" : "text-amber-400"
                )}>
                  {edge > 0 ? "+" : ""}{(edge * 100).toFixed(2)}%
                </div>
                <p className="text-[10px] text-muted-foreground mt-1">
                  {summary.interpretation}
                </p>
                <p className="text-[10px] text-muted-foreground mt-2">
                  基准: {summary.baseline_code} · 窗口: {summary.window.since?.slice(0, 10)} ~ {summary.window.until?.slice(0, 10)}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* 详细反事实列表 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">详细反事实 (最近 {retros.length} 条)</CardTitle>
              <CardDescription className="text-xs">
                每条记录显示假设 / 证据 / 实际结果 / 教训
              </CardDescription>
            </CardHeader>
            <CardContent>
              {retros.length === 0 ? (
                <p className="text-xs text-muted-foreground py-4 text-center">
                  暂无反事实数据。等待 proposal 决策被回填实际表现后,这里会自动展示。
                </p>
              ) : (
                <div className="space-y-3">
                  {retros.map((r) => (
                    <RetrospectiveCard key={r.retro_id} r={r} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

function CounterfactualCard({
  title,
  decision,
  data,
  accent,
}: {
  title: string
  decision: string
  data: { count: number; avg_fwd_return: number; avg_baseline_diff: number; good_rate: number }
  accent: "emerald" | "red"
}) {
  const accentColor = accent === "emerald" ? "text-emerald-400" : "text-red-400"
  return (
    <Card className={cn("border-l-[3px]", accent === "emerald" ? "border-l-emerald-400" : "border-l-red-400")}>
      <CardHeader className="pb-1">
        <CardTitle className="text-xs">{title}</CardTitle>
        <CardDescription className="text-[10px]">{decision} · n = {data.count}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className={cn("text-2xl font-mono font-semibold", accentColor)}>
          {(data.avg_fwd_return * 100).toFixed(2)}%
        </div>
        <p className="text-[10px] text-muted-foreground mt-1">
          vs 基准 {(data.avg_baseline_diff * 100).toFixed(2)}% · 胜率 {(data.good_rate * 100).toFixed(0)}%
        </p>
      </CardContent>
    </Card>
  )
}

function RetrospectiveCard({ r }: { r: Retrospective }) {
  const positive = r.fwd_baseline_diff > 0
  return (
    <div className="rounded border border-border/40 p-3 bg-muted/10">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className={cn(
              "text-[10px]",
              r.decision === "approved" ? "text-emerald-400 border-emerald-500/40" :
              r.decision === "rejected" ? "text-red-400 border-red-500/40" :
              "text-muted-foreground"
            )}
          >
            {r.decision}
          </Badge>
          <span className="font-mono text-[10px] text-muted-foreground">{r.experiment_id}</span>
          <span className="text-[10px] text-muted-foreground">· {r.fwd_days}天</span>
        </div>
        <div className={cn(
          "text-sm font-mono font-semibold",
          positive ? "text-emerald-400" : "text-red-400"
        )}>
          {r.fwd_baseline_diff > 0 ? "+" : ""}{(r.fwd_baseline_diff * 100).toFixed(2)}%
        </div>
      </div>
      <div className="space-y-1.5 text-xs">
        <div>
          <span className="text-muted-foreground">假设:</span>{" "}
          <span>{r.hypothesis || "(无)"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">证据:</span>{" "}
          <span>{r.evidence_summary || "(无)"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">实际:</span>{" "}
          <span>{r.realized_summary || "(无)"}</span>
        </div>
        {r.lesson && (
          <div className="pt-1.5 mt-1.5 border-t border-border/30">
            <span className="text-purple-400">教训:</span>{" "}
            <span>{r.lesson}</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  v4.1 1B.2 — 影子组合净值曲线 Tab
// ════════════════════════════════════════════════════════════

function ShadowView() {
  const { data, isLoading } = useShadowPortfolios()
  const portfolios = data?.portfolios ?? []

  // 取第一个活跃 portfolio (v4.1 单 portfolio 起步, 多 portfolio 留给 v4.2)
  const activePortfolio = portfolios.find((p: any) => p.status === "active") ?? portfolios[0]

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">影子组合选择</CardTitle>
          <CardDescription>
            v3.11 影子组合 — 模拟跟随 AI 决策的虚拟持仓组合
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-8 w-full" />
          ) : portfolios.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4">
              暂无影子组合。等 watcher 跑通后会自动建立第一个 portfolio。
            </div>
          ) : (
            <div className="text-sm">
              当前查看:{" "}
              <span className="font-mono tabular-nums">
                #{activePortfolio?.portfolio_id} {activePortfolio?.name ?? ""}
              </span>
              <span className="text-muted-foreground ml-2">
                (共 {portfolios.length} 个 portfolio)
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      <ShadowEquityChart portfolioId={activePortfolio?.portfolio_id ?? null} days={30} />
    </div>
  )
}