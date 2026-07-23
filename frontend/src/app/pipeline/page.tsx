"use client"

import { useCallback, useEffect, useState } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { apiGet, apiPost } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { IconPlayerPlay, IconRefresh, IconCircleCheck, IconAlertTriangle, IconCircleX, IconClock } from "@tabler/icons-react"

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
    warnings?: number
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

export default function PipelinePage() {
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

  // 当 status=running, 自动刷新
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
      // 立刻开始轮询
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

  return (
    <>
      <SiteHeader title="量化 Pipeline" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6 space-y-4 max-w-5xl mx-auto">
          {/* ── 顶部: 触发按钮 + 状态 ── */}
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

          {/* ── 数据源健康 ── */}
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

          {/* ── 5 步进度 ── */}
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
                      {(step.warning_count ?? (Array.isArray(step.warnings) ? step.warnings.length : 0)) > 0 && (
                        <span
                          className="text-xs text-yellow-400"
                          title={Array.isArray(step.warnings) && step.warnings[0]?.message}
                        >
                          告警: {step.warning_count ?? step.warnings.length} 个
                        </span>
                      )}
                      {step.error && (
                        <span className="text-xs text-red-400 truncate" title={step.error}>err: {step.error}</span>
                      )}
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          )}

          {/* ── 简报列表 + 内容 ── */}
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

          {/* ── 错误列表 ── */}
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
      </div>
    </>
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
