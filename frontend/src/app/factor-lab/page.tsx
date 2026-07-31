"use client"

import { useState, useEffect, useMemo } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { IconChartBar, IconGridDots, IconChartScatter, IconFlask, IconPlayerPlay, IconCheck, IconBrain, IconActivity, IconTrophy, IconChartLine, IconBinaryTree } from "@tabler/icons-react"
import {
  ScatterChart, Scatter, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts"

// ═══════════════════════════════════════════════════════════
//  类型定义
// ═══════════════════════════════════════════════════════════

interface FactorInfo { name: string; needs_volume: boolean }
interface DecayScore {
  score: number | null
  status: string            // stable | decay_warning | rapid_decay | insufficient_data | weak_signal
  color: string             // green | yellow | red | gray
  decay_pct: number | null
  label: string
}
interface FactorMetrics {
  ic_mean: number
  ic_std: number
  ir: number
  win_rate: number
  ic_decay: Record<string, number>
  decay_score?: DecayScore  // 后端在 compute_factor_metrics 里新增
  turnover: number
  ic_series: [string, number][]
  valid_days: number
}
interface ICResult {
  period: { start: string; end: string }
  pool: string
  stock_count: number
  factor_count: number
  factors: Record<string, FactorMetrics>
}
interface CorrResult {
  factors: string[]
  matrix: number[][]
  pool: string
  stock_count: number
}
interface ScatterPoint { code: string; x: number; y: number }
interface ScatterResult {
  factor_a: string
  factor_b: string
  y_label: string
  correlation: number
  pool: string
  date: string | null
  stock_count: number
  points: ScatterPoint[]
}

// GP mining 类型
interface GPCandidate {
  id: number; expr_text: string; ir: number; ic_mean: number
  win_rate: number; valid_days: number; tree_depth: number
  promoted: number; run_id: string; created_at: string
}
interface GPHistory { generation: number; best_ir: number; best_expr: string; kept_count: number; duration_s: number }
interface GPResult {
  run_id: string
  best: Array<{ expr: string; ir: number; ic_mean: number; win_rate: number; valid_days: number; tree_depth: number }>
  history: GPHistory[]
  stats: { evaluated: number; duration_s: number; kept: number }
}

// ML mining 类型
interface MLResult {
  run_id: string
  feature_importance: Array<{ name: string; importance: number }>
  train_metrics: { ic_mean: number; ir: number; win_rate: number; valid_days: number }
  test_metrics: { ic_mean: number; ir: number; win_rate: number; valid_days: number }
  top_decile_return: number
  bottom_decile_return: number
  spread: number
  sample_count: number
  train_days: number
  test_days: number
  n_estimators: number
  max_depth: number
  learning_rate: number
  summary: string
}

// 因子生命周期类型
interface LifecycleFactor {
  factor_name: string
  status: "active" | "warning" | "retired"
  ic_current: number
  ir_current: number
  warning_days: number
  last_check: string | null
  note: string | null
}
interface LifecycleStatus {
  count: number
  summary: { active: number; warning: number; retired: number }
  factors: LifecycleFactor[]
}

// 排行榜类型 (P0-1)
interface LeaderboardRow {
  name: string
  ic_mean: number
  ic_std: number
  ir: number
  win_rate: number
  turnover: number
  decay_score: number | null
  decay_status: string
  decay_color: "green" | "yellow" | "red" | "gray"
  decay_label: string
  decay_pct: number | null
  valid_days: number
}
interface LeaderboardResult {
  period: { start: string; end: string }
  pool: string
  stock_count: number
  total: number
  rows: LeaderboardRow[]
}

// 分位数收益类型 (P0-2)
interface QuantileGroup {
  group: number
  label: string
  daily_ret: number[]
  cumret: number[]
}
interface QuantileSummary {
  q1_cumret: number
  q5_cumret: number
  long_short_cumret: number
  monotonic: boolean
  long_short_sharpe: number
}
interface QuantileResult {
  factor: string
  period: { start: string; end: string }
  pool: string
  n_groups: number
  dates: string[]
  groups: QuantileGroup[]
  long_short: { daily_ret: number[]; cumret: number[] }
  summary: QuantileSummary
  error?: string
}

// 层次聚类类型 (P1-1)
interface ClusterTreeNode {
  name?: string
  cluster_id: number | string
  distance: number
  size?: number
  is_leaf?: boolean
  children?: ClusterTreeNode[]
}
interface ClusterGroup {
  id: number
  factors: string[]
  size: number
  avg_corr: number
  distance: number
}
interface ClusteringResult {
  factors: string[]
  tree: ClusterTreeNode
  groups: ClusterGroup[]
  summary: {
    n_factors: number
    n_clusters: number
    method: string
    threshold: number
  }
  period?: string
  end_date?: string
  pool: string
  stock_count: number
  error?: string
}

// ═══════════════════════════════════════════════════════════
//  工具函数
// ═══════════════════════════════════════════════════════════

const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`
const fmtIR = (v: number) => v.toFixed(3)

function strength(ir: number, ic: number): { label: string; color: string } {
  // 简化评级: IR > 0.5 = 强, > 0.3 = 中, > 0.1 = 弱, 否则垃圾
  if (ir > 0.5 && ic > 0) return { label: "强有效", color: "text-emerald-400 bg-emerald-400/10" }
  if (ir > 0.3 && ic > 0) return { label: "中等", color: "text-blue-400 bg-blue-400/10" }
  if (ir > 0.1 && ic > 0) return { label: "弱", color: "text-yellow-400 bg-yellow-400/10" }
  if (ic < 0) return { label: "反向", color: "text-orange-400 bg-orange-400/10" }
  return { label: "无效", color: "text-muted-foreground bg-muted" }
}

// ═══════════════════════════════════════════════════════════
//  Tab 1: IC 分析
// ═══════════════════════════════════════════════════════════

function ICTab({ factors, pool, setPool, startDate, setStartDate, endDate, setEndDate }: any) {
  const [selectedFactors, setSelectedFactors] = useState<string[]>([])
  const [data, setData] = useState<ICResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  // 默认选 5 个核心因子
  useEffect(() => {
    if (factors.length && selectedFactors.length === 0) {
      setSelectedFactors(["ret_5d", "ret_20d", "ma20", "rsi_14", "macd_signal"])
    }
  }, [factors, selectedFactors.length])

  const run = async () => {
    if (selectedFactors.length === 0) return
    setLoading(true)
    setError("")
    try {
      const params = new URLSearchParams()
      selectedFactors.forEach((f) => params.append("factors", f))
      params.append("pool", pool)
      if (startDate) params.append("start_date", startDate)
      if (endDate) params.append("end_date", endDate)
      const res = await apiPost<ICResult>(`/api/factor-lab/ic?${params.toString()}`)
      setData(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "计算失败")
    } finally {
      setLoading(false)
    }
  }

  const sortedFactors = useMemo(() => {
    if (!data?.factors) return []
    return Object.entries(data.factors).sort((a, b) => b[1].ir - a[1].ir)
  }, [data])

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconFlask className="size-4" />
            IC 分析 — 因子预测能力评估
          </CardTitle>
          <CardDescription className="text-xs">
            IC (Information Coefficient) = 因子值与次日收益的相关系数 | IR = IC 均值 / IC 标准差 (越高越稳定)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">股票池</label>
              <Select value={pool} onValueChange={setPool}>
                <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全 A 股</SelectItem>
                  <SelectItem value="hs300">沪深 300</SelectItem>
                  <SelectItem value="csi500">中证 500</SelectItem>
                  <SelectItem value="csi800">沪深 300+中证 500</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">起始日期</label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 w-36 text-xs" />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">结束日期</label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 w-36 text-xs" />
            </div>
            <Button onClick={run} disabled={loading} size="sm">
              {loading ? "计算中..." : "计算 IC"}
            </Button>
          </div>

          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground">选择因子 (可多选)</label>
            <div className="flex flex-wrap gap-1.5">
              {factors.map((f: FactorInfo) => (
                <button
                  key={f.name}
                  onClick={() => setSelectedFactors((s) =>
                    s.includes(f.name) ? s.filter((x) => x !== f.name) : [...s, f.name]
                  )}
                  className={`px-2 py-1 text-[11px] border transition-colors ${
                    selectedFactors.includes(f.name)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {f.name}
                </button>
              ))}
            </div>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {loading ? (
        <Card><CardContent className="py-4 space-y-2">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-3/4" />
        </CardContent></Card>
      ) : data && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              结果: {data.factor_count} 因子 / {data.stock_count} 只股票 / {data.period?.start} ~ {data.period?.end}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/50 sticky top-0">
                  <tr className="text-left">
                    <th className="p-2 font-medium">因子</th>
                    <th className="p-2 font-medium text-right">IC 均值</th>
                    <th className="p-2 font-medium text-right">IR</th>
                    <th className="p-2 font-medium text-right">胜率</th>
                    <th className="p-2 font-medium text-right">换手</th>
                    <th className="p-2 font-medium text-center">衰减评分</th>
                    <th className="p-2 font-medium text-center" colSpan={4}>衰减 (天)</th>
                    <th className="p-2 font-medium text-right">有效天数</th>
                    <th className="p-2 font-medium">评级</th>
                  </tr>
                  <tr className="text-[10px] text-muted-foreground">
                    <th className="p-1"></th>
                    <th className="p-1"></th>
                    <th className="p-1"></th>
                    <th className="p-1"></th>
                    <th className="p-1"></th>
                    <th className="p-1"></th>
                    <th className="p-1 text-right">1d</th>
                    <th className="p-1 text-right">5d</th>
                    <th className="p-1 text-right">10d</th>
                    <th className="p-1 text-right">20d</th>
                    <th className="p-1"></th>
                    <th className="p-1"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedFactors.map(([name, m]) => {
                    const s = strength(m.ir, m.ic_mean)
                    return (
                      <tr key={name} className="border-t border-border hover:bg-accent/30">
                        <td className="p-2 font-mono font-medium">{name}</td>
                        <td className={`p-2 text-right font-mono tabular-nums ${m.ic_mean >= 0 ? "text-red-400" : "text-emerald-400"}`}>
                          {m.ic_mean >= 0 ? "+" : ""}{fmtPct(m.ic_mean)}
                        </td>
                        <td className={`p-2 text-right font-mono tabular-nums ${m.ir >= 0 ? "text-red-400" : "text-emerald-400"}`}>
                          {m.ir >= 0 ? "+" : ""}{fmtIR(m.ir)}
                        </td>
                        <td className="p-2 text-right font-mono tabular-nums">{fmtPct(m.win_rate)}</td>
                        <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
                          {(m.turnover * 100).toFixed(0)}%
                        </td>
                        <td className="p-2 text-center">
                          {m.decay_score ? (
                            <Badge
                              variant="outline"
                              title={`1日→5日 IC 衰减 ${((m.decay_score.decay_pct ?? 0) * 100).toFixed(0)}%`}
                              className={cn(
                                "text-[10px] font-mono tabular-nums",
                                m.decay_score.color === "green" && "border-emerald-500/50 text-emerald-400",
                                m.decay_score.color === "yellow" && "border-yellow-500/50 text-yellow-400",
                                m.decay_score.color === "red" && "border-red-500/50 text-red-400 bg-red-500/5",
                                m.decay_score.color === "gray" && "border-border text-muted-foreground",
                              )}
                            >
                              {m.decay_score.score != null ? `${m.decay_score.score}` : "--"}
                              <span className="ml-1 text-[9px] opacity-70">{m.decay_score.label}</span>
                            </Badge>
                          ) : (
                            <span className="text-[10px] text-muted-foreground">--</span>
                          )}
                        </td>
                        <td className="p-1 text-right font-mono tabular-nums text-[10px]">
                          {(m.ic_decay?.[1] ?? 0) >= 0 ? "+" : ""}{(m.ic_decay?.[1] ?? 0).toFixed(4)}
                        </td>
                        <td className="p-1 text-right font-mono tabular-nums text-[10px]">
                          {(m.ic_decay?.[5] ?? 0) >= 0 ? "+" : ""}{(m.ic_decay?.[5] ?? 0).toFixed(4)}
                        </td>
                        <td className="p-1 text-right font-mono tabular-nums text-[10px]">
                          {(m.ic_decay?.[10] ?? 0) >= 0 ? "+" : ""}{(m.ic_decay?.[10] ?? 0).toFixed(4)}
                        </td>
                        <td className="p-1 text-right font-mono tabular-nums text-[10px]">
                          {(m.ic_decay?.[20] ?? 0) >= 0 ? "+" : ""}{(m.ic_decay?.[20] ?? 0).toFixed(4)}
                        </td>
                        <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
                          {m.valid_days}
                        </td>
                        <td className="p-2">
                          <Badge className={`text-[10px] ${s.color}`}>{s.label}</Badge>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  Tab 2: 相关性矩阵
// ═══════════════════════════════════════════════════════════

function CorrelationTab({ factors, pool }: any) {
  const [data, setData] = useState<CorrResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedCell, setSelectedCell] = useState<[number, number] | null>(null)

  const run = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      factors.forEach((f: FactorInfo) => params.append("factors", f.name))
      params.append("pool", pool)
      const res = await apiPost<CorrResult>(`/api/factor-lab/correlation?${params.toString()}`)
      setData(res)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { run() }, [pool, factors])  // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !data) {
    return <Card><CardContent className="py-4 space-y-2">
      <Skeleton className="h-32 w-full" />
    </CardContent></Card>
  }

  if (!data) return null

  const colorFor = (v: number) => {
    // -1 红色, +1 蓝色
    const intensity = Math.abs(v)
    if (v > 0) return `rgba(59, 130, 246, ${intensity})`  // blue
    if (v < 0) return `rgba(239, 68, 68, ${intensity})`  // red
    return `rgba(115, 115, 115, 0.3)`
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <IconGridDots className="size-4" />
          因子相关性矩阵 — Pearson ({data.factors.length}×{data.factors.length}, {data.stock_count} 只股票)
        </CardTitle>
        <CardDescription className="text-xs">
          蓝色 = 正相关, 红色 = 负相关, 颜色越深越强 | 点单元格看具体值
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="text-[10px]">
            <thead>
              <tr>
                <th className="p-1"></th>
                {data.factors.map((f) => (
                  <th key={f} className="p-1 font-medium font-mono">{f}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.matrix.map((row, i) => (
                <tr key={i}>
                  <td className="p-1 font-mono font-medium">{data.factors[i]}</td>
                  {row.map((v, j) => (
                    <td
                      key={j}
                      className="p-1 text-center font-mono tabular-nums cursor-pointer hover:ring-1 hover:ring-primary"
                      style={{ backgroundColor: colorFor(v), color: Math.abs(v) > 0.5 ? "white" : "inherit" }}
                      onClick={() => setSelectedCell([i, j])}
                    >
                      {v.toFixed(2)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selectedCell && (
          <div className="mt-3 p-3 bg-muted text-xs">
            <p>
              <span className="font-mono font-medium">{data.factors[selectedCell[0]]}</span>
              {" vs "}
              <span className="font-mono font-medium">{data.factors[selectedCell[1]]}</span>
              {" = "}
              <span className="font-mono tabular-nums text-red-400">
                {data.matrix[selectedCell[0]][selectedCell[1]].toFixed(4)}
              </span>
            </p>
            <p className="mt-1 text-muted-foreground">
              {Math.abs(data.matrix[selectedCell[0]][selectedCell[1]]) > 0.7
                ? "⚠️ 高度相关 — 这两个因子可能重复，可考虑删一个"
                : Math.abs(data.matrix[selectedCell[0]][selectedCell[1]]) > 0.4
                ? "中等相关 — 两个因子有重叠信号"
                : "低相关 — 两个因子互补"}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════
//  Tab 4: GP 因子挖掘
// ═══════════════════════════════════════════════════════════

function MiningTab({ pool }: { pool: string }) {
  const [candidates, setCandidates] = useState<GPCandidate[]>([])
  const [minIr, setMinIr] = useState(0.0)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")
  const [lastRun, setLastRun] = useState<GPResult | null>(null)
  const [popSize, setPopSize] = useState(30)
  const [gens, setGens] = useState(3)

  const refreshCandidates = async () => {
    try {
      const d = await apiGet<{ candidates: GPCandidate[]; count: number }>(
        `/api/factor-lab/mine/candidates?min_ir=${minIr}&limit=50`
      )
      setCandidates(d.candidates || [])
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => { refreshCandidates() }, [minIr])  // eslint-disable-line react-hooks/exhaustive-deps

  const runMine = async () => {
    setRunning(true)
    setError("")
    setLastRun(null)
    try {
      const params = new URLSearchParams()
      params.append("pool", pool)
      params.append("population", String(popSize))
      params.append("generations", String(gens))
      params.append("top_k", "10")
      const res = await apiPost<GPResult>(`/api/factor-lab/mine/run?${params.toString()}`)
      setLastRun(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "挖掘失败")
    } finally {
      setRunning(false)
      refreshCandidates()
    }
  }

  const promote = async (id: number) => {
    try {
      await apiPost(`/api/factor-lab/mine/candidate/${id}/promote`)
      refreshCandidates()
    } catch (e) {
      console.error(e)
    }
  }

  // Lifecycle 状态
  const [lifecycle, setLifecycle] = useState<LifecycleStatus | null>(null)
  const [lifecycleLoading, setLifecycleLoading] = useState(false)

  const refreshLifecycle = async () => {
    try {
      const d = await apiGet<LifecycleStatus>("/api/factor-lab/lifecycle/status")
      setLifecycle(d)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => { refreshLifecycle() }, [])

  const runEvaluate = async () => {
    setLifecycleLoading(true)
    try {
      await apiPost("/api/factor-lab/lifecycle/evaluate")
      await refreshLifecycle()
    } catch (e) {
      console.error(e)
    } finally {
      setLifecycleLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* 因子生命周期卡片 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconActivity className="size-4" />
            因子生命周期 — 自动评估 / 告警 / 退役
          </CardTitle>
          <CardDescription className="text-xs">
            规则: IR ≥ 0.15 = 活跃, IR &lt; 0.05 累计 14 天 = 自动退役
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={runEvaluate} disabled={lifecycleLoading}>
              <IconPlayerPlay className="size-3.5 mr-1" />
              {lifecycleLoading ? "评估中..." : "立即评估全部 15 因子"}
            </Button>
            {lifecycle && (
              <div className="flex gap-2 text-xs">
                <Badge className="bg-emerald-400/10 text-emerald-400">
                  活跃 {lifecycle.summary.active}
                </Badge>
                <Badge className="bg-yellow-400/10 text-yellow-400">
                  警告 {lifecycle.summary.warning}
                </Badge>
                <Badge className="bg-orange-400/10 text-orange-400">
                  退役 {lifecycle.summary.retired}
                </Badge>
              </div>
            )}
          </div>
          {lifecycle && lifecycle.factors.length > 0 && (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
              {lifecycle.factors.map((f) => {
                const colorMap = {
                  active: "border-emerald-400/50 bg-emerald-400/5",
                  warning: "border-yellow-400/50 bg-yellow-400/5",
                  retired: "border-orange-400/50 bg-orange-400/5 line-through",
                }
                const statusLabel = { active: "活跃", warning: "警告", retired: "退役" }
                return (
                  <div key={f.factor_name} className={`p-2 border ${colorMap[f.status]}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono text-xs font-medium">{f.factor_name}</span>
                      <span className={`text-[10px] ${
                        f.status === "active" ? "text-emerald-400" :
                        f.status === "warning" ? "text-yellow-400" : "text-orange-400"
                      }`}>{statusLabel[f.status]}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] font-mono tabular-nums">
                      <span>IR {f.ir_current >= 0 ? "+" : ""}{f.ir_current.toFixed(3)}</span>
                      <span className="text-muted-foreground">IC {f.ic_current >= 0 ? "+" : ""}{f.ic_current.toFixed(4)}</span>
                    </div>
                    {f.warning_days > 0 && (
                      <div className="text-[9px] text-yellow-400 mt-0.5">警告 {f.warning_days}/14 天</div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconFlask className="size-4" />
            GP 遗传编程 — 自动挖掘新因子
          </CardTitle>
          <CardDescription className="text-xs">
            随机生成 + 评估 IC + 选择 + 变异 + 交叉 的进化循环, 自动发现新因子表达式
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">种群大小</label>
              <Input type="number" value={popSize} onChange={(e) => setPopSize(Number(e.target.value))} className="h-8 w-20 text-xs" min={10} max={200} />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">迭代代数</label>
              <Input type="number" value={gens} onChange={(e) => setGens(Number(e.target.value))} className="h-8 w-20 text-xs" min={1} max={20} />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">显示 IR ≥</label>
              <Input type="number" value={minIr} onChange={(e) => setMinIr(Number(e.target.value))} className="h-8 w-20 text-xs" step={0.05} />
            </div>
            <Button onClick={runMine} disabled={running} size="sm">
              <IconPlayerPlay className="size-3.5 mr-1" />
              {running ? "挖掘中..." : "运行 GP"}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            时间预估: 30 pop × 3 代 ≈ 1-2 分钟, 50 pop × 5 代 ≈ 5-10 分钟
          </p>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {lastRun && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <IconCheck className="size-4 text-emerald-400" />
              运行完成 — {lastRun.run_id}
            </CardTitle>
            <p className="text-[10px] text-muted-foreground">
              评估 {lastRun.stats.evaluated} 表达式 / 保留 {lastRun.stats.kept} / 耗时 {lastRun.stats.duration_s}s
            </p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">每代最佳 IR:</p>
              <div className="flex flex-wrap gap-2">
                {lastRun.history.map((h) => (
                  <Badge key={h.generation} variant="outline" className="text-[10px] font-mono">
                    代 {h.generation}: {h.best_ir >= 0 ? "+" : ""}{h.best_ir.toFixed(3)}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">本轮 Top 候选:</p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-2 text-left">表达式</th>
                      <th className="p-2 text-right">IR</th>
                      <th className="p-2 text-right">IC</th>
                      <th className="p-2 text-right">胜率</th>
                      <th className="p-2 text-right">深度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lastRun.best.slice(0, 10).map((c, i) => (
                      <tr key={i} className="border-t border-border">
                        <td className="p-2 font-mono">{c.expr}</td>
                        <td className={`p-2 text-right font-mono tabular-nums ${c.ir >= 0 ? "text-red-400" : "text-emerald-400"}`}>
                          {c.ir >= 0 ? "+" : ""}{c.ir.toFixed(4)}
                        </td>
                        <td className="p-2 text-right font-mono tabular-nums">{c.ic_mean >= 0 ? "+" : ""}{c.ic_mean.toFixed(5)}</td>
                        <td className="p-2 text-right font-mono tabular-nums">{(c.win_rate * 100).toFixed(0)}%</td>
                        <td className="p-2 text-right text-muted-foreground">{c.tree_depth}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            历史候选池 ({candidates.length} 条, IR ≥ {minIr.toFixed(2)})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {candidates.length === 0 ? (
            <p className="text-xs text-muted-foreground py-8 text-center">
              暂无候选, 运行 GP 挖掘
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/50 sticky top-0">
                  <tr>
                    <th className="p-2 text-left">表达式</th>
                    <th className="p-2 text-right">IR</th>
                    <th className="p-2 text-right">IC</th>
                    <th className="p-2 text-right">胜率</th>
                    <th className="p-2 text-right">深度</th>
                    <th className="p-2 text-left">run</th>
                    <th className="p-2 text-center">采纳</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.id} className="border-t border-border hover:bg-accent/30">
                      <td className="p-2 font-mono">{c.expr_text}</td>
                      <td className={`p-2 text-right font-mono tabular-nums ${c.ir >= 0 ? "text-red-400" : "text-emerald-400"}`}>
                        {c.ir >= 0 ? "+" : ""}{c.ir.toFixed(4)}
                      </td>
                      <td className="p-2 text-right font-mono tabular-nums">{c.ic_mean >= 0 ? "+" : ""}{c.ic_mean.toFixed(5)}</td>
                      <td className="p-2 text-right font-mono tabular-nums">{(c.win_rate * 100).toFixed(0)}%</td>
                      <td className="p-2 text-right text-muted-foreground">{c.tree_depth}</td>
                      <td className="p-2 text-[10px] text-muted-foreground font-mono">{c.run_id.slice(-6)}</td>
                      <td className="p-2 text-center">
                        {c.promoted ? (
                          <Badge className="text-[10px] bg-emerald-400/10 text-emerald-400">
                            <IconCheck className="size-2.5 mr-0.5" />已采纳
                          </Badge>
                        ) : (
                          <Button size="sm" variant="ghost" className="h-5 px-1.5 text-[10px]" onClick={() => promote(c.id)}>
                            采纳
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  Tab 5: ML 因子生成 (LightGBM)
// ═══════════════════════════════════════════════════════════

function MlMiningTab({ pool }: { pool: string }) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState<MLResult | null>(null)
  const [nEstimators, setNEstimators] = useState(100)
  const [maxDepth, setMaxDepth] = useState(4)

  const run = async () => {
    setRunning(true)
    setError("")
    try {
      const params = new URLSearchParams()
      params.append("pool", pool)
      params.append("n_estimators", String(nEstimators))
      params.append("max_depth", String(maxDepth))
      const res = await apiPost<MLResult>(`/api/factor-lab/mine/run-ml?${params.toString()}`)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "ML 挖掘失败")
    } finally {
      setRunning(false)
    }
  }

  const maxImp = result?.feature_importance?.[0]?.importance || 1

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconBrain className="size-4" />
            LightGBM ML 因子生成
          </CardTitle>
          <CardDescription className="text-xs">
            用 15 个价格/技术因子训练 LightGBM 回归器预测次日收益, 输出非线性"组合因子" + 特征重要性
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">树数量 (n_estimators)</label>
              <Input type="number" value={nEstimators} onChange={(e) => setNEstimators(Number(e.target.value))} className="h-8 w-24 text-xs" min={20} max={500} step={20} />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">单树最大深度</label>
              <Input type="number" value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value))} className="h-8 w-24 text-xs" min={2} max={10} />
            </div>
            <Button onClick={run} disabled={running} size="sm">
              <IconPlayerPlay className="size-3.5 mr-1" />
              {running ? "训练中..." : "运行 LightGBM"}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            时间预估: 100 树 ≈ 5-15 秒, 200 树 ≈ 20-40 秒 | 默认 70/30 时序分训练/测试集
          </p>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {result && !result.error && (
        <>
          {/* 指标总览 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <IconCheck className="size-4 text-emerald-400" />
                {result.run_id} — 多空对冲 spread {result.spread >= 0 ? "+" : ""}{(result.spread * 100).toFixed(3)}%/日
              </CardTitle>
              <p className="text-[10px] text-muted-foreground">
                样本 {result.sample_count} ({result.train_days} 训练日 / {result.test_days} 测试日) | {result.n_estimators} 树 × depth {result.max_depth} × lr {result.learning_rate}
              </p>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <MetricBox label="训练集 IR" value={result.train_metrics.ir.toFixed(3)} />
                <MetricBox label="测试集 IR" value={result.test_metrics.ir.toFixed(3)} highlight />
                <MetricBox label="测试集胜率" value={`${(result.test_metrics.win_rate * 100).toFixed(0)}%`} />
                <MetricBox label="Top 10% 收益" value={`${(result.top_decile_return * 100).toFixed(2)}%`} positive={result.top_decile_return >= 0} />
              </div>
              <div className="mt-3 grid grid-cols-2 lg:grid-cols-4 gap-3">
                <MetricBox label="训练 IC" value={result.train_metrics.ic_mean.toFixed(4)} />
                <MetricBox label="测试 IC" value={result.test_metrics.ic_mean.toFixed(4)} />
                <MetricBox label="Bottom 10% 收益" value={`${(result.bottom_decile_return * 100).toFixed(2)}%`} positive={result.bottom_decile_return >= 0} />
                <MetricBox label="训练/测试 IC 比" value={result.test_metrics.ic_mean > 0 && result.train_metrics.ic_mean > 0 ? (result.test_metrics.ic_mean / result.train_metrics.ic_mean).toFixed(2) : "—"} hint="越接近 1 越未过拟合" />
              </div>
            </CardContent>
          </Card>

          {/* 特征重要性 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">特征重要性 (Top 15)</CardTitle>
              <CardDescription className="text-xs">
                LightGBM 决策时该特征被使用的次数, 越高越关键
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-2 text-left">特征</th>
                      <th className="p-2 text-left">重要性</th>
                      <th className="p-2 text-left">相对强度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.feature_importance.map((f) => (
                      <tr key={f.name} className="border-t border-border hover:bg-accent/30">
                        <td className="p-2 font-mono">{f.name}</td>
                        <td className="p-2 font-mono tabular-nums">{f.importance}</td>
                        <td className="p-2 w-1/2">
                          <div className="h-2 bg-muted rounded-none overflow-hidden">
                            <div
                              className="h-full bg-primary"
                              style={{ width: `${(f.importance / maxImp) * 100}%` }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* 解读 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">解读</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <p>
                <span className="font-medium">测试集 IR = {result.test_metrics.ir.toFixed(3)}</span>:
                {result.test_metrics.ir > 0.5 ? " 强有效 — 模型能稳定预测次日收益" :
                 result.test_metrics.ir > 0.3 ? " 中等 — 有一定预测能力" :
                 " 弱 — 模型表现一般, 可能过拟合或市场环境特殊"}
              </p>
              <p>
                <span className="font-medium">多空 spread = {(result.spread * 100).toFixed(3)}%/日</span>:
                按模型预测排序, top 10% 平均每天比 bottom 10% 多赚 {result.spread >= 0 ? "+" : ""}{(result.spread * 100).toFixed(3)}%
              </p>
              <p className="text-muted-foreground">
                模型已保存到 <code className="text-[10px] bg-muted px-1">{result.run_id}.pkl</code>,
                可在 Python 中加载用于实盘预测
              </p>
            </CardContent>
          </Card>
        </>
      )}

      {result?.error && (
        <Card><CardContent className="py-4 text-xs text-destructive">{result.error}</CardContent></Card>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  Tab 7 (新): 全因子排行榜 — 一张可排序表 + 🟢🟡🔴 状态徽章
// ═══════════════════════════════════════════════════════════

function LeaderboardTab({
  pool, setPool, startDate, setStartDate, endDate, setEndDate,
}: {
  pool: string; setPool: (v: string) => void
  startDate: string; setStartDate: (v: string) => void
  endDate: string; setEndDate: (v: string) => void
}) {
  const [data, setData] = useState<LeaderboardResult | null>(null)
  const [loading, setLoading] = useState(false)
  // 列排序状态: 默认按 |ir| desc
  const [sortKey, setSortKey] = useState<"ir" | "ic_mean" | "win_rate" | "turnover" | "decay_score">("ir")
  const [sortDesc, setSortDesc] = useState(true)

  const run = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        pool, start_date: startDate, end_date: endDate,
      })
      const res = await apiGet<LeaderboardResult>(`/api/factor-lab/leaderboard?${params}`)
      setData(res)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const sorted = useMemo(() => {
    if (!data) return []
    const rows = [...data.rows]
    rows.sort((a, b) => {
      const va = sortKey === "ir" ? Math.abs(a.ir) : (a as any)[sortKey]
      const vb = sortKey === "ir" ? Math.abs(b.ir) : (b as any)[sortKey]
      const v = (va ?? -Infinity) - (vb ?? -Infinity)
      return sortDesc ? -v : v
    })
    return rows
  }, [data, sortKey, sortDesc])

  const headerCell = (key: typeof sortKey, label: string, hint?: string) => (
    <th
      className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground"
      onClick={() => {
        if (sortKey === key) setSortDesc(!sortDesc)
        else { setSortKey(key); setSortDesc(true) }
      }}
    >
      {label} {sortKey === key && (sortDesc ? "↓" : "↑")}
      {hint && <span className="block text-[8px] text-muted-foreground/60">{hint}</span>}
    </th>
  )

  const decayBadge = (row: LeaderboardRow) => {
    const colorMap = {
      green: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
      yellow: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
      red: "bg-red-500/15 text-red-400 border-red-500/30",
      gray: "bg-muted text-muted-foreground border-border",
    } as const
    const cls = colorMap[row.decay_color] ?? colorMap.gray
    return (
      <span className={`px-1.5 py-0.5 text-[9px] border ${cls}`}>
        {row.decay_label || row.decay_status}
      </span>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconTrophy className="size-4" />
            全因子排行榜 — IC / IR / Turnover / Decay
          </CardTitle>
          <CardDescription className="text-xs">
            一张表看全部因子强度,按列点击排序
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">股票池</label>
              <Select value={pool} onValueChange={setPool}>
                <SelectTrigger className="h-8 w-24 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="hs300">HS300</SelectItem>
                  <SelectItem value="csi500">CSI500</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">起始</label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 w-32 text-xs" />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">结束</label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 w-32 text-xs" />
            </div>
            <Button onClick={run} disabled={loading} size="sm">
              {loading ? "计算中..." : "刷新排行榜"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <Card><CardContent className="py-8">
          <Skeleton className="h-64 w-full" />
        </CardContent></Card>
      ) : data && data.total > 0 ? (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left p-2 text-[10px] text-muted-foreground">#</th>
                    <th className="text-left p-2 text-[10px] text-muted-foreground">因子</th>
                    {headerCell("ir", "IR", "信息比率")}
                    {headerCell("ic_mean", "IC Mean", "截面相关均值")}
                    {headerCell("win_rate", "胜率", "IC>0 占比")}
                    {headerCell("turnover", "换手", "IC 自相关倒数")}
                    {headerCell("decay_score", "Decay", "衰减评分 0-1")}
                    <th className="text-[10px] text-muted-foreground">状态</th>
                    <th className="text-[10px] text-muted-foreground">有效天数</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((row, i) => (
                    <tr key={row.name} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 text-muted-foreground">{i + 1}</td>
                      <td className="p-2 font-medium">{row.name}</td>
                      <td className={`p-2 ${Math.abs(row.ir) > 0.5 ? "text-emerald-400" : Math.abs(row.ir) > 0.3 ? "text-yellow-400" : "text-muted-foreground"}`}>
                        {row.ir.toFixed(3)}
                      </td>
                      <td className="p-2">{row.ic_mean.toFixed(4)}</td>
                      <td className="p-2">{(row.win_rate * 100).toFixed(1)}%</td>
                      <td className="p-2">{(row.turnover * 100).toFixed(0)}%</td>
                      <td className="p-2">{row.decay_score !== null ? row.decay_score.toFixed(2) : "—"}</td>
                      <td className="p-2">{decayBadge(row)}</td>
                      <td className="p-2 text-muted-foreground">{row.valid_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="p-2 text-[10px] text-muted-foreground border-t border-border">
              共 {data.total} 个因子 · {data.stock_count} 只股票 · {data.period.start} ~ {data.period.end}
            </div>
          </CardContent>
        </Card>
      ) : data?.total === 0 ? (
        <Card><CardContent className="py-8 text-xs text-muted-foreground text-center">
          无有效因子(全部数据不足 30 天) — 拉长日期窗口重试
        </CardContent></Card>
      ) : null}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  Tab 8 (新): 分位数收益 — alphalens 风格 5 等分累计收益图
// ═══════════════════════════════════════════════════════════

function QuantileReturnsTab({
  factors, pool, setPool, startDate, setStartDate, endDate, setEndDate,
}: {
  factors: FactorInfo[]
  pool: string; setPool: (v: string) => void
  startDate: string; setStartDate: (v: string) => void
  endDate: string; setEndDate: (v: string) => void
}) {
  const [factor, setFactor] = useState("ret_5d")
  const [nGroups, setNGroups] = useState(5)
  const [data, setData] = useState<QuantileResult | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        factor, pool,
        start_date: startDate, end_date: endDate,
        n_groups: String(nGroups),
      })
      const res = await apiPost<QuantileResult>(`/api/factor-lab/quantile-returns?${params}`)
      setData(res)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  // 把 5 组 cumret + 多空对冲压成 wide format 给 Recharts
  const chartData = useMemo(() => {
    if (!data || data.error || !data.dates || !data.groups || !data.long_short) return []
    return data.dates.map((d, i) => {
      const row: Record<string, number | string> = { date: d }
      for (const g of data.groups!) {
        row[`Q${g.group}`] = g.cumret[i]
      }
      row["L/S"] = data.long_short.cumret[i]
      return row
    })
  }, [data])

  // 5 组颜色:Q1 红(最差) → Q5 绿(最好),中间过渡
  const lineColors = ["#ef4444", "#f97316", "#eab308", "#84cc16", "#22c55e", "#3b82f6"]

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconChartLine className="size-4" />
            分位数收益 — alphalens 风格 5 等分累计曲线
          </CardTitle>
          <CardDescription className="text-xs">
            按因子值分组(Q1 最差 ~ Q5 最好),每日等权,次日卖出;L/S = Q5 - Q1 多空对冲
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">因子</label>
              <Select value={factor} onValueChange={setFactor}>
                <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {factors.map((f) => (
                    <SelectItem key={f.name} value={f.name}>{f.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">分组数</label>
              <Select value={String(nGroups)} onValueChange={(v) => setNGroups(parseInt(v))}>
                <SelectTrigger className="h-8 w-16 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[2, 3, 5, 10].map((n) => (
                    <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">股票池</label>
              <Select value={pool} onValueChange={setPool}>
                <SelectTrigger className="h-8 w-24 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="hs300">HS300</SelectItem>
                  <SelectItem value="csi500">CSI500</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">起始</label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 w-32 text-xs" />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">结束</label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 w-32 text-xs" />
            </div>
            <Button onClick={run} disabled={loading} size="sm">
              {loading ? "计算中..." : "跑分位数"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <Card><CardContent className="py-8">
          <Skeleton className="h-80 w-full" />
        </CardContent></Card>
      ) : data?.error ? (
        <Card><CardContent className="py-8 text-xs text-destructive text-center">
          {data.error}
        </CardContent></Card>
      ) : data && !data.error && data.summary ? (
        <>
          {/* 摘要卡片 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <MetricBox label="Q1 (最差组) 累计" value={`${(data.summary.q1_cumret * 100).toFixed(2)}%`} positive={data.summary.q1_cumret > 0} />
            <MetricBox label="Q5 (最好组) 累计" value={`${(data.summary.q5_cumret * 100).toFixed(2)}%`} positive={data.summary.q5_cumret > 0} />
            <MetricBox label="L/S 多空对冲" value={`${(data.summary.long_short_cumret * 100).toFixed(2)}%`} positive={data.summary.long_short_cumret > 0} highlight />
            <MetricBox label="L/S Sharpe (年化)" value={data.summary.long_short_sharpe.toFixed(2)} positive={data.summary.long_short_sharpe > 0} />
          </div>

          {/* 主图 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">累计收益曲线 {data.summary.monotonic ? "🟢 单调上升" : "🟡 非单调"}</CardTitle>
              <CardDescription className="text-xs">
                {data.summary.monotonic
                  ? "5 组期末收益严格递增 → 因子区分度优秀,可作为 alpha 信号"
                  : "5 组收益非严格递增 → 因子区分度有限,需配合其他信号"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={360}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                  <Tooltip
                    contentStyle={{ background: "#1a1a1a", border: "1px solid #333", fontSize: 11 }}
                    formatter={(v: any) => `${(Number(v) * 100).toFixed(2)}%`}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {data.groups.map((g, i) => (
                    <Line
                      key={g.group}
                      type="monotone"
                      dataKey={`Q${g.group}`}
                      name={g.label}
                      stroke={lineColors[i]}
                      strokeWidth={1.5}
                      dot={false}
                    />
                  ))}
                  <Line
                    type="monotone"
                    dataKey="L/S"
                    name="L/S 多空对冲"
                    stroke={lineColors[5]}
                    strokeWidth={2}
                    strokeDasharray="4 2"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  Tab 5 (新): 层次聚类树 — 自渲染 SVG 树状图 + 簇卡片
// ═══════════════════════════════════════════════════════════

function ClusteringTab({
  factors, pool, setPool, startDate, setStartDate, endDate, setEndDate,
}: {
  factors: FactorInfo[]
  pool: string; setPool: (v: string) => void
  startDate: string; setStartDate: (v: string) => void
  endDate: string; setEndDate: (v: string) => void
}) {
  const [selectedFactors, setSelectedFactors] = useState<string[]>(
    ["ret_5d", "ret_10d", "ret_20d", "rsi_14", "macd_signal", "volatility_20", "std20", "std5"]
  )
  const [threshold, setThreshold] = useState(0.3)
  const [data, setData] = useState<ClusteringResult | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        factors: selectedFactors.join(","),
        pool, start_date: startDate, end_date: endDate,
        distance_threshold: String(threshold),
      })
      const res = await apiPost<ClusteringResult>(`/api/factor-lab/clustering?${params}`)
      setData(res)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const toggleFactor = (name: string) => {
    setSelectedFactors((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconBinaryTree className="size-4" />
            层次聚类 — 把相似因子自动归组
          </CardTitle>
          <CardDescription className="text-xs">
            基于因子相关性 + scipy average linkage,距离阈值越小聚类越严格
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">股票池</label>
              <Select value={pool} onValueChange={setPool}>
                <SelectTrigger className="h-8 w-24 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="hs300">HS300</SelectItem>
                  <SelectItem value="csi500">CSI500</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">起始</label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 w-32 text-xs" />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">结束</label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 w-32 text-xs" />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">距离阈值</label>
              <Select value={String(threshold)} onValueChange={(v) => setThreshold(parseFloat(v))}>
                <SelectTrigger className="h-8 w-24 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="0.2">0.2 严格</SelectItem>
                  <SelectItem value="0.3">0.3 默认</SelectItem>
                  <SelectItem value="0.5">0.5 宽松</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button onClick={run} disabled={loading || selectedFactors.length < 2} size="sm">
              {loading ? "聚类中..." : "跑聚类"}
            </Button>
          </div>

          {/* 因子多选 */}
          <div className="border border-border p-2 max-h-32 overflow-y-auto">
            <div className="text-[10px] text-muted-foreground mb-1">
              选因子({selectedFactors.length}/{factors.length}):
            </div>
            <div className="flex flex-wrap gap-1">
              {factors.map((f) => (
                <button
                  key={f.name}
                  onClick={() => toggleFactor(f.name)}
                  className={`px-1.5 py-0.5 text-[10px] border ${
                    selectedFactors.includes(f.name)
                      ? "bg-primary/15 border-primary text-foreground"
                      : "border-border text-muted-foreground hover:border-primary/50"
                  }`}
                >
                  {f.name}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <Card><CardContent className="py-8"><Skeleton className="h-64 w-full" /></CardContent></Card>
      ) : data?.error ? (
        <Card><CardContent className="py-8 text-xs text-destructive text-center">{data.error}</CardContent></Card>
      ) : data && data.tree && data.tree.children ? (
        <>
          {/* 摘要 */}
          <div className="grid grid-cols-3 gap-2">
            <MetricBox label="有效因子" value={String(data.summary.n_factors)} />
            <MetricBox label="聚类簇数" value={String(data.summary.n_clusters)} />
            <MetricBox label="阈值 (distance)" value={String(data.summary.threshold)} hint="越小越严格" />
          </div>

          {/* 簇卡片 + Dendrogram 并排 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* 簇列表 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">聚类簇列表</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 max-h-[500px] overflow-y-auto">
                {data.groups.map((g) => (
                  <div key={g.id} className="border border-border p-2 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">簇 #{g.id}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {g.size} 因子 · |corr|={g.avg_corr.toFixed(2)}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {g.factors.map((f) => (
                        <span key={f} className="px-1 py-0.5 text-[9px] bg-muted border border-border">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            {/* Dendrogram SVG */}
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">聚类树 (Dendrogram)</CardTitle>
                <CardDescription className="text-xs">
                  越早合并 = 相关性越强;叶节点 = 因子,横线高度 = 距离
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Dendrogram tree={data.tree} factors={data.factors} />
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}


// 自渲染 Dendrogram SVG — 走树结构 + 计算每个节点的 x/y
function Dendrogram({ tree, factors }: { tree: ClusterTreeNode; factors: string[] }) {
  // 1. 给每个叶节点分配 x 坐标(0..n-1)
  const leafOrder: string[] = []
  function collectLeaves(node: ClusterTreeNode) {
    if (node.is_leaf && node.name) {
      leafOrder.push(node.name)
    } else if (node.children) {
      node.children.forEach(collectLeaves)
    }
  }
  collectLeaves(tree)

  const nLeaves = Math.max(leafOrder.length, 1)
  const leafIndex = new Map(leafOrder.map((n, i) => [n, i]))

  // 2. 后序遍历计算每个节点的 x/y
  // x: 叶子 = leafIndex, 内部 = 子节点 x 平均
  // y: 叶子 = 0, 内部 = max(子节点 y) + 子节点的距离差
  type Pos = { x: number; y: number; node: ClusterTreeNode }
  const positions = new Map<string | number, Pos>()
  function assignPos(node: ClusterTreeNode): { x: number; y: number } {
    if (node.is_leaf && node.name) {
      const x = leafIndex.get(node.name) ?? 0
      const y = 0
      positions.set(node.cluster_id, { x, y, node })
      return { x, y }
    }
    if (!node.children) return { x: 0, y: 0 }

    const childPositions = node.children.map((c) => {
      const p = assignPos(c)
      return { ...p, node: c }
    })
    const x = childPositions.reduce((s, c) => s + c.x, 0) / childPositions.length
    const maxChildY = Math.max(...childPositions.map((c) => c.y))
    const y = maxChildY + (node.distance || 0.05) * 5  // 缩放距离为视觉间距
    positions.set(node.cluster_id, { x, y, node })
    return { x, y }
  }
  assignPos(tree)

  // 3. 画 SVG
  const padding = 16
  const labelWidth = 100
  const width = 600
  const height = Math.max(120, nLeaves * 28)
  const xScale = (width - labelWidth - padding) / Math.max(nLeaves - 1, 1)
  const yScale = (height - padding * 2) / Math.max(tree.distance * 6, 1)

  const toX = (x: number) => padding + x * xScale
  const toY = (y: number) => height - padding - y * yScale

  // 4. 收集所有 edges (父子连线) + leaf labels
  const edges: { x1: number; y1: number; x2: number; y2: number; key: string }[] = []
  function drawEdges(node: ClusterTreeNode) {
    if (!node.children || node.children.length === 0) return
    const parentPos = positions.get(node.cluster_id)!
    for (const child of node.children) {
      const cp = positions.get(child.cluster_id)!
      // L 形连线: 父 -> 父的 y -> 子的 y -> 子
      const px = toX(parentPos.x)
      const py = toY(parentPos.y)
      const cx = toX(cp.x)
      const cy = toY(cp.y)
      // 父节点横线
      edges.push({ x1: cx, y1: py, x2: px, y2: py, key: `h-${String(node.cluster_id)}-${String(child.cluster_id)}` })
      // 子节点竖线
      edges.push({ x1: cx, y1: py, x2: cx, y2: cy, key: `v-${String(node.cluster_id)}-${String(child.cluster_id)}` })
      drawEdges(child)
    }
  }
  drawEdges(tree)

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} className="text-foreground">
        {/* edges */}
        {edges.map((e) => (
          <line
            key={e.key}
            x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
            stroke="currentColor"
            strokeWidth={1}
            opacity={0.4}
          />
        ))}
        {/* 叶节点 labels */}
        {leafOrder.map((name, i) => {
          const x = toX(i)
          const y = toY(0)
          return (
            <g key={name}>
              <circle cx={x} cy={y} r={3} fill="currentColor" />
              <text
                x={x + 6}
                y={y + 3}
                fontSize={10}
                fill="currentColor"
                fontFamily="monospace"
              >
                {name}
              </text>
            </g>
          )
        })}
        {/* 根节点标尺 */}
        <line
          x1={padding}
          y1={height - padding}
          x2={padding + xScale * (nLeaves - 1)}
          y2={height - padding}
          stroke="currentColor"
          strokeWidth={0.5}
          opacity={0.2}
        />
        <text x={padding} y={height - 4} fontSize={9} fill="currentColor" opacity={0.5}>
          distance →
        </text>
      </svg>
    </div>
  )
}


function MetricBox({ label, value, highlight = false, positive, hint }: { label: string; value: string; highlight?: boolean; positive?: boolean; hint?: string }) {
  const valueColor = positive === undefined ? "" : positive ? "text-red-400" : "text-emerald-400"
  return (
    <div className={`p-3 border ${highlight ? "border-primary bg-primary/5" : "border-border"}`}>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={`text-lg font-mono tabular-nums ${highlight ? "text-primary" : valueColor}`}>{value}</p>
      {hint && <p className="text-[9px] text-muted-foreground mt-0.5">{hint}</p>}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  Tab 3: 散点图
// ═══════════════════════════════════════════════════════════

function ScatterTab({ factors, pool }: any) {
  const [factorA, setFactorA] = useState("ret_5d")
  const [factorB, setFactorB] = useState("rsi_14")
  const [data, setData] = useState<ScatterResult | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.append("factor_a", factorA)
      params.append("factor_b", factorB)
      params.append("pool", pool)
      const res = await apiPost<ScatterResult>(`/api/factor-lab/scatter?${params.toString()}`)
      setData(res)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconChartScatter className="size-4" />
            散点图探索 — 两因子关系
          </CardTitle>
          <CardDescription className="text-xs">
            X 轴 = 因子 A 当日值 | Y 轴 = 未来 5 日累计收益 (次日 t+5)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">因子 A (X 轴)</label>
              <Select value={factorA} onValueChange={setFactorA}>
                <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {factors.map((f: FactorInfo) => (
                    <SelectItem key={f.name} value={f.name}>{f.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">因子 B (Y 轴因子 — 实际是 5 日 forward return)</label>
              <Select value={factorB} onValueChange={setFactorB}>
                <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {factors.map((f: FactorInfo) => (
                    <SelectItem key={f.name} value={f.name}>{f.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={run} disabled={loading} size="sm">
              {loading ? "计算中..." : "画散点"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <Card><CardContent className="py-8">
          <Skeleton className="h-64 w-full" />
        </CardContent></Card>
      ) : data && data.points.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center justify-between">
              <span>
                <span className="font-mono">{data.factor_a}</span> vs <span className="font-mono">{data.y_label}</span>
              </span>
              <Badge variant="outline" className="text-[10px]">
                相关系数: <span className={`ml-1 font-mono tabular-nums ${data.correlation > 0 ? "text-red-400" : "text-emerald-400"}`}>
                  {data.correlation >= 0 ? "+" : ""}{data.correlation.toFixed(4)}
                </span>
              </Badge>
            </CardTitle>
            <p className="text-[10px] text-muted-foreground mt-1">
              {data.stock_count} 只股票 / 基准日 {data.date} / 抽样 {data.points.length} 点
            </p>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={400}>
              <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(115,115,115,0.2)" />
                <XAxis
                  type="number"
                  dataKey="x"
                  name={data.factor_a}
                  tickFormatter={(v) => (v * 100).toFixed(1) + "%"}
                  stroke="#adadad"
                  fontSize={10}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  tickFormatter={(v) => (v * 100).toFixed(1) + "%"}
                  stroke="#adadad"
                  fontSize={10}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: "#2a2a2a", border: "1px solid #3a3a3a", fontSize: 11 }}
                  labelStyle={{ color: "#adadad" }}
                  formatter={(v: any) => `${(Number(v) * 100).toFixed(2)}%`}
                />
                <Scatter data={data.points} fill="#3b82f6" />
              </ScatterChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      ) : data && data.points.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-xs text-muted-foreground">
          数据不足, 请调整股票池或日期范围
        </CardContent></Card>
      ) : null}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  主页面
// ═══════════════════════════════════════════════════════════

export default function FactorLabPage() {
  const [factors, setFactors] = useState<FactorInfo[]>([])
  const [pool, setPool] = useState("csi800")
  const [startDate, setStartDate] = useState("2025-10-01")
  const [endDate, setEndDate] = useState("2026-07-13")

  useEffect(() => {
    apiGet<{ factors: FactorInfo[] }>("/api/factor-lab/factors")
      .then((d) => setFactors(d.factors || []))
      .catch((e) => console.error(e))
  }, [])

  return (
    <>
      <SiteHeader title="因子实验室" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        <Tabs defaultValue="ic" className="space-y-4">
          <TabsList className="grid w-full max-w-4xl grid-cols-8">
            <TabsTrigger value="ic" className="text-xs"><IconChartBar className="size-3.5 mr-1" />IC</TabsTrigger>
            <TabsTrigger value="leaderboard" className="text-xs"><IconTrophy className="size-3.5 mr-1" />排行</TabsTrigger>
            <TabsTrigger value="quantile" className="text-xs"><IconChartLine className="size-3.5 mr-1" />分位数</TabsTrigger>
            <TabsTrigger value="clustering" className="text-xs"><IconBinaryTree className="size-3.5 mr-1" />聚类</TabsTrigger>
            <TabsTrigger value="correlation" className="text-xs"><IconGridDots className="size-3.5 mr-1" />相关性</TabsTrigger>
            <TabsTrigger value="scatter" className="text-xs"><IconChartScatter className="size-3.5 mr-1" />散点</TabsTrigger>
            <TabsTrigger value="mining" className="text-xs"><IconFlask className="size-3.5 mr-1" />GP</TabsTrigger>
            <TabsTrigger value="ml" className="text-xs"><IconBrain className="size-3.5 mr-1" />ML</TabsTrigger>
          </TabsList>
          <TabsContent value="ic">
            <ICTab
              factors={factors}
              pool={pool} setPool={setPool}
              startDate={startDate} setStartDate={setStartDate}
              endDate={endDate} setEndDate={setEndDate}
            />
          </TabsContent>
          <TabsContent value="leaderboard">
            <LeaderboardTab
              pool={pool} setPool={setPool}
              startDate={startDate} setStartDate={setStartDate}
              endDate={endDate} setEndDate={setEndDate}
            />
          </TabsContent>
          <TabsContent value="quantile">
            <QuantileReturnsTab
              factors={factors}
              pool={pool} setPool={setPool}
              startDate={startDate} setStartDate={setStartDate}
              endDate={endDate} setEndDate={setEndDate}
            />
          </TabsContent>
          <TabsContent value="correlation">
            <CorrelationTab factors={factors} pool={pool} />
          </TabsContent>
          <TabsContent value="clustering">
            <ClusteringTab
              factors={factors}
              pool={pool} setPool={setPool}
              startDate={startDate} setStartDate={setStartDate}
              endDate={endDate} setEndDate={setEndDate}
            />
          </TabsContent>
          <TabsContent value="scatter">
            <ScatterTab factors={factors} pool={pool} />
          </TabsContent>
          <TabsContent value="mining">
            <MiningTab pool={pool} />
          </TabsContent>
          <TabsContent value="ml">
            <MlMiningTab pool={pool} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  )
}