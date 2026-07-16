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
import { IconChartBar, IconGridDots, IconScatterChart, IconFlask } from "@tabler/icons-react"
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts"

// ═══════════════════════════════════════════════════════════
//  类型定义
// ═══════════════════════════════════════════════════════════

interface FactorInfo { name: string; needs_volume: boolean }
interface FactorMetrics {
  ic_mean: number
  ic_std: number
  ir: number
  win_rate: number
  ic_decay: Record<string, number>
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
            <IconScatterChart className="size-4" />
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
          <TabsList className="grid w-full max-w-xl grid-cols-3">
            <TabsTrigger value="ic" className="text-xs"><IconChartBar className="size-3.5 mr-1" />IC 分析</TabsTrigger>
            <TabsTrigger value="correlation" className="text-xs"><IconGridDots className="size-3.5 mr-1" />相关性矩阵</TabsTrigger>
            <TabsTrigger value="scatter" className="text-xs"><IconScatterChart className="size-3.5 mr-1" />散点图</TabsTrigger>
          </TabsList>
          <TabsContent value="ic">
            <ICTab
              factors={factors}
              pool={pool} setPool={setPool}
              startDate={startDate} setStartDate={setStartDate}
              endDate={endDate} setEndDate={setEndDate}
            />
          </TabsContent>
          <TabsContent value="correlation">
            <CorrelationTab factors={factors} pool={pool} />
          </TabsContent>
          <TabsContent value="scatter">
            <ScatterTab factors={factors} pool={pool} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  )
}