"use client"

import { useEffect, useState, useCallback, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import { apiGet, apiPost } from "@/lib/auth"
import type { KlineResponse } from "@/lib/api-types"
import { Area, AreaChart, CartesianGrid, XAxis, BarChart, Bar, Cell } from "recharts"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { KlineChart } from "@/components/KlineChart"
import { IconBrain, IconRadar2 } from "@tabler/icons-react"

interface AISignal { indicator: string; value: string; reason: string }
interface AIVerdict { verdict: string; signals: AISignal[] }
interface RiskAlert { level: "warn" | "info"; message: string }
interface AIExplainData {
  error?: string
  stock?: { code: string; name: string }
  technical?: AIVerdict
  fundamental?: AIVerdict
  risk_alerts?: RiskAlert[]
}

interface AlertItem {
  id: number; stock_code: string; alert_type: string
  target_value: number; created_at: string
}

interface ReviewDimension {
  title: string; score: string; summary: string; detail: string
}
interface ReviewSuggestion {
  text: string; reasoning: string
}
interface ReviewData {
  id?: number; created_at?: string; total_pnl?: number
  transactions_count?: number; avg_score?: number
  ai_headline?: string; dimensions?: ReviewDimension[]
  suggestions?: ReviewSuggestion[]
}

interface FactorCategory {
  key: string; name: string
  score_avg: number | null; factor_count: number; done_count: number
  factors: { name: string; display: string; value: unknown; score: number | null; status: string; direction: string }[]
}

interface FactorPanelData {
  code: string; price: number; date: string
  overall_score: number | null
  categories: FactorCategory[]
  hit_count: number; registry_summary?: { done: number; total_registered: number }
}

interface TurtleData {
  error?: string
  atr_20: number | null; sys1_entry: number | null; sys2_entry: number | null
  sys1_exit: number | null; sys2_exit: number | null
  distance_sys1_pct: number | null; distance_sys2_pct: number | null
  sys1_triggered: boolean; sys2_triggered: boolean
  sys1_exit_triggered: boolean; sys2_exit_triggered: boolean
  channel_position: number | null; turtle_score: number; details: string[]
}

interface StockInsight {
  code: string; name: string; price?: number; change_pct?: number
  indicators?: {
    MA?: Record<string, number>
    MACD?: { DIF: number; DEA: number; MACD?: number }
    KDJ?: { K: number; D: number; J: number }
    RSI?: number
  }
  signal?: string
  factors?: Record<string, unknown>
  kline?: KlineResponse
  turtle?: TurtleData
}

interface RiskKPI {
  sharpe?: number; max_drawdown?: number; volatility?: number; beta?: number
}

interface CorrelationItem { code1: string; code2: string; value: number }

interface BacktestResult {
  total_invested?: number; final_value?: number; total_return?: number
  lump_sum_return?: number; conclusion?: string
}

interface CompareStrategyItem {
  total_invested?: number; final_value?: number
  return?: number; trades?: number
}

interface CompareResult {
  name: string; total_invested: number; final_value: number
  return: number  // backend field is literally "return"
  trades: number
}

interface MCResult {
  current_price: number; mean_final: number; prob_loss: number; prob_loss_15pct: number
  distribution?: { price: number; count: number }[]
}

function QuantPageInner() {
  const router = useRouter()
  const params = useSearchParams()

  const [code, setCode] = useState(params.get("code") || "")
  const [days, setDays] = useState("60")
  const [insight, setInsight] = useState<StockInsight | null>(null)
  const [risk, setRisk] = useState<RiskKPI | null>(null)
  const [correlations, setCorrelations] = useState<CorrelationItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState("insight")

  // Backtest form
  const [btAmount, setBtAmount] = useState("1000")
  const [btFreq, setBtFreq] = useState("weekly")
  const [btResult, setBtResult] = useState<BacktestResult | null>(null)

  // Compare
  const [compareResult, setCompareResult] = useState<CompareResult[]>([])

  // Monte Carlo
  const [mcDays, setMcDays] = useState("60")
  const [mcSims, setMcSims] = useState("100")
  const [mcResult, setMcResult] = useState<MCResult | null>(null)

  // AI explain
  const [aiExplain, setAiExplain] = useState<AIExplainData | null>(null)
  const [aiLoading, setAiLoading] = useState(false)

  // Quick selector
  const [quickData, setQuickData] = useState<{ holdings: { code: string; name: string }[]; watchlist: { code: string; name: string }[] }>({ holdings: [], watchlist: [] })
  const [selectorOpen, setSelectorOpen] = useState(false)

  // Alerts
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [alertsLoading, setAlertsLoading] = useState(false)

  // AI Review tab
  const [reviewData, setReviewData] = useState<ReviewData | null>(null)
  const [reviewHistory, setReviewHistory] = useState<ReviewData[]>([])
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewGenerating, setReviewGenerating] = useState(false)
  const [reviewGenError, setReviewGenError] = useState("")
  const [expandedDims, setExpandedDims] = useState<Set<number>>(new Set())
  const [showReasoning, setShowReasoning] = useState<Set<number>>(new Set())

  // Factor panel
  const [factorData, setFactorData] = useState<FactorPanelData | null>(null)
  const [factorLoading, setFactorLoading] = useState(false)

  // Factor AI explain
  interface FactorExplainResult {
    error?: string; code?: string; overall_score?: number | null
    strengths?: { dimension: string; score: number; insight: string }[]
    weaknesses?: { dimension: string; score: number; insight: string }[]
    overall?: string; suggestion?: string
  }
  const [factorExplain, setFactorExplain] = useState<FactorExplainResult | null>(null)
  const [factorExplainLoading, setFactorExplainLoading] = useState(false)

  // Load alerts + quick selector data on mount
  useEffect(() => {
    fetchAlerts()
    apiGet<{ stock_code: string; stock_name: string }[]>("/api/stocks/holdings").then((d) => {
      if (Array.isArray(d)) setQuickData((prev) => ({ ...prev, holdings: d.map((h) => ({ code: h.stock_code, name: h.stock_name })) }))
    }).catch(() => {})
    apiGet<{ stock_code: string; stock_name: string }[]>("/api/stocks/watchlist").then((d) => {
      if (Array.isArray(d)) setQuickData((prev) => ({ ...prev, watchlist: d.map((w) => ({ code: w.stock_code, name: w.stock_name })) }))
    }).catch(() => {})
  }, [])

  // 从 screener 跳转过来时自动查询
  useEffect(() => {
    const urlCode = params.get("code")
    if (urlCode && urlCode !== code) {
      setCode(urlCode)
      // 异步 fetchInsight 需要等 state 更新后才能读到新 code
      setTimeout(() => {
        if (urlCode.trim()) {
          setLoading(true); setError(null)
          apiGet<StockInsight>(`/api/quant/stock-insight/${urlCode.trim()}?days=${days}`)
            .then((data) => setInsight(data as StockInsight))
            .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
            .finally(() => setLoading(false))
        }
      }, 0)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  const fetchInsight = async () => {
    if (!code.trim()) return
    setLoading(true); setError(null)
    try {
      const data = await apiGet<StockInsight>(`/api/quant/stock-insight/${code.trim()}?days=${days}`)
      setInsight(data)
    } catch (err) { setError(err instanceof Error ? err.message : "加载失败") }
    finally { setLoading(false) }
  }

  const fetchRisk = async () => {
    try {
      const [r, corrs] = await Promise.all([
        apiGet<RiskKPI>("/api/quant/portfolio-risk"),
        apiGet<CorrelationItem[]>("/api/stocks/diversification?format=correlation").catch(() => []),
      ])
      setRisk(r)
      setCorrelations(Array.isArray(corrs) ? corrs : [])
    } catch { /* */ }
  }

  const runBacktest = async () => {
    if (!code.trim()) return
    setLoading(true)
    try {
      const data = await apiPost<BacktestResult>("/api/quant/backtest", {
        code: code.trim(), amount: Number(btAmount), freq: btFreq,
        start_date: "2024-01-01", end_date: "2025-01-01",
      })
      setBtResult(data)
    } catch (err) { setError(err instanceof Error ? err.message : "回测失败") }
    finally { setLoading(false) }
  }

  const runCompare = async () => {
    if (!code.trim()) return
    setLoading(true)
    try {
      const data = await apiPost<{ strategies: Record<string, CompareStrategyItem> }>("/api/quant/compare", { code: code.trim(), amount: Number(btAmount) || 1000, start_date: "2024-01-01", end_date: "2025-01-01" })
      if (data?.strategies) {
        const arr: CompareResult[] = []
        for (const [name, s] of Object.entries(data.strategies)) {
          arr.push({ name, total_invested: s.total_invested || 0, final_value: s.final_value || 0, return: s.return || 0, trades: s.trades || 0 })
        }
        setCompareResult(arr)
      }
    } catch { /* */ }
    finally { setLoading(false) }
  }

  const fetchAIExplain = async () => {
    if (!code.trim()) return
    setAiLoading(true); setAiExplain(null); setError(null)
    try {
      const data = await apiPost<AIExplainData>(`/api/quant/stock/${code.trim()}/explain`, {})
      setAiExplain(data)
    } catch (err) { setError(err instanceof Error ? err.message : "AI 解读失败") }
    finally { setAiLoading(false) }
  }

  const fetchAlerts = async () => {
    setAlertsLoading(true)
    try {
      const data = await apiGet<AlertItem[]>("/api/stocks/alerts")
      setAlerts(Array.isArray(data) ? data : [])
    } catch { /* alerts are optional */ }
    finally { setAlertsLoading(false) }
  }

  const deleteAlert = async (id: number) => {
    try {
      await apiPost(`/api/stocks/alerts/${id}`, undefined, "DELETE")
      setAlerts((prev) => prev.filter((a) => a.id !== id))
    } catch { /* alerts are optional */ }
  }

  const fetchFactors = async () => {
    if (!code.trim()) return
    setFactorLoading(true); setFactorData(null); setFactorExplain(null)
    try {
      const data = await apiGet<FactorPanelData>(`/api/quant/factor-panel/${code.trim()}?days=${days}`)
      setFactorData(data)
      setTab("factors")
    } catch (err) { setError(err instanceof Error ? err.message : "因子加载失败") }
    finally { setFactorLoading(false) }
  }

  const fetchFactorExplain = async () => {
    if (!factorData) return
    setFactorExplainLoading(true); setFactorExplain(null)
    try {
      const data = await apiPost<FactorExplainResult>("/api/quant/factor-explain", {
        code: factorData.code,
        overall_score: factorData.overall_score,
        categories: factorData.categories.map((c) => ({
          name: c.name, score_avg: c.score_avg,
          done_count: c.done_count, factor_count: c.factor_count,
        })),
      })
      setFactorExplain(data)
    } catch (err) { setError(err instanceof Error ? err.message : "AI 因子解读失败") }
    finally { setFactorExplainLoading(false) }
  }

  const runMC = async () => {
    if (!code.trim()) return
    setLoading(true)
    try {
      const data = await apiPost<MCResult>("/api/quant/monte-carlo", {
        code: code.trim(), days: Number(mcDays), sims: Number(mcSims),
      })
      setMcResult(data)
    } catch { /* */ }
    finally { setLoading(false) }
  }

  // ── AI Review ──
  const fetchLatestReview = useCallback(async () => {
    try {
      const [revData, histData] = await Promise.all([
        apiGet<ReviewData[]>("/api/stocks/reviews?limit=1").then((d) => (Array.isArray(d) ? d[0] : null)),
        apiGet<ReviewData[]>("/api/stocks/reviews?limit=10"),
      ])
      setReviewData(revData || null)
      setReviewHistory(Array.isArray(histData) ? histData : [])
    } catch { /* */ }
  }, [])

  const generateReview = async () => {
    setReviewGenerating(true); setReviewGenError("")
    try {
      const data = await apiPost<ReviewData>("/api/stocks/review/structured", { report_type: "daily" })
      setReviewData(data)
    } catch (err) {
      setReviewGenError(err instanceof Error ? err.message : "生成失败，请确认已配置 AI Key")
    } finally { setReviewGenerating(false) }
    try {
      const revs = await apiGet<ReviewData[]>("/api/stocks/reviews?limit=10")
      if (Array.isArray(revs)) setReviewHistory(revs)
    } catch { /* */ }
  }

  const loadReview = async (id: number) => {
    setReviewLoading(true)
    try {
      const data = await apiGet<ReviewData>(`/api/stocks/reviews/${id}`)
      setReviewData(data)
    } catch { /* */ } finally { setReviewLoading(false) }
  }

  // 统一查询入口：根据当前 tab 分发到对应操作
  const handleQuery = async () => {
    if (!code.trim()) return
    switch (tab) {
      case "insight": await fetchInsight(); break
      case "factors": await fetchFactors(); break
      case "backtest": await runBacktest(); break
      case "mc": await runMC(); break
      case "risk": await fetchRisk(); break
      case "review": await fetchLatestReview(); break
    }
  }

  return (
    <>
      <SiteHeader title="量化分析" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* Stock input + Quick Selector */}
        <div className="flex flex-wrap items-end gap-2">
          <div className="relative space-y-1">
            <Label className="text-xs">股票代码</Label>
            <div className="flex gap-0">
              <Input value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleQuery()} placeholder="000001" className="h-8 w-28 font-mono rounded-none" />
              <button
                onClick={() => setSelectorOpen(!selectorOpen)}
                className="h-8 px-2 border border-l-0 border-input bg-background text-muted-foreground hover:text-foreground text-xs"
                title="快速选择"
              >
                ▼
              </button>
            </div>
            {selectorOpen && (
              <div className="absolute top-full left-0 mt-1 w-64 border border-border bg-background shadow-lg z-50 rounded-none">
                <div className="p-1">
                  {/* Holdings group */}
                  {quickData.holdings.length > 0 && (
                    <div className="mb-1">
                      <p className="text-[10px] text-muted-foreground px-2 py-0.5">我的持仓</p>
                      {quickData.holdings.map((h) => (
                        <button
                          key={h.code}
                          className="w-full text-left px-3 py-1 text-xs hover:bg-muted flex justify-between"
                          onClick={() => { setCode(h.code); setSelectorOpen(false) }}
                        >
                          <span className="font-mono">{h.code}</span>
                          <span className="text-muted-foreground truncate ml-2">{h.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {/* Watchlist group */}
                  {quickData.watchlist.length > 0 && (
                    <div className="mb-1">
                      <p className="text-[10px] text-muted-foreground px-2 py-0.5">我的自选</p>
                      {quickData.watchlist.slice(0, 10).map((w) => (
                        <button
                          key={w.code}
                          className="w-full text-left px-3 py-1 text-xs hover:bg-muted flex justify-between"
                          onClick={() => { setCode(w.code); setSelectorOpen(false) }}
                        >
                          <span className="font-mono">{w.code}</span>
                          <span className="text-muted-foreground truncate ml-2">{w.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {/* Turtle Top10 group */}
                  <div>
                    <p className="text-[10px] text-muted-foreground px-2 py-0.5">
                      今日海龟 Top10
                      <span className="text-orange-400 ml-1">{new Date().toISOString().slice(5, 10)}</span>
                    </p>
                    {[
                      { code: "002171", name: "楚江新材" },
                      { code: "600063", name: "皖维高新" },
                      { code: "000630", name: "铜陵有色" },
                      { code: "000725", name: "京东方A" },
                      { code: "002057", name: "中钢天源" },
                      { code: "600703", name: "三安光电" },
                      { code: "002734", name: "利民股份" },
                      { code: "300146", name: "汤臣倍健" },
                      { code: "300401", name: "花园生物" },
                      { code: "600246", name: "万通发展" },
                    ].map((t) => (
                      <button
                        key={t.code}
                        className="w-full text-left px-3 py-1 text-xs hover:bg-muted flex justify-between"
                        onClick={() => { setCode(t.code); setSelectorOpen(false) }}
                      >
                        <span className="font-mono">{t.code}</span>
                        <span className="text-muted-foreground truncate ml-2">{t.name}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="border-t border-border p-1">
                  <button
                    className="w-full text-center text-[10px] text-muted-foreground hover:text-foreground py-0.5"
                    onClick={() => setSelectorOpen(false)}
                  >
                    关闭
                  </button>
                </div>
              </div>
            )}
          </div>
          <div className="space-y-1">
            <Label className="text-xs">周期</Label>
            <Select value={days} onValueChange={setDays}>
              <SelectTrigger className="h-8 text-xs w-auto min-w-[90px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-48">
                <SelectItem value="30">30天</SelectItem>
                <SelectItem value="60">60天</SelectItem>
                <SelectItem value="120">120天</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button size="sm" onClick={handleQuery} disabled={loading || !code.trim()}>
            查询
          </Button>
        </div>

        {error && <p className="text-xs text-red-500">{error}</p>}

        <Tabs value={tab} onValueChange={(v) => { setTab(v); if (v === "risk") fetchRisk() }}>
          <TabsList className="overflow-x-auto flex-nowrap">
            <TabsTrigger value="insight" className="text-xs">个股透视</TabsTrigger>
            <TabsTrigger value="risk" className="text-xs">组合风险</TabsTrigger>
            <TabsTrigger value="backtest" className="text-xs">策略回测</TabsTrigger>
            <TabsTrigger value="mc" className="text-xs">蒙特卡洛</TabsTrigger>
            <TabsTrigger value="factors" className="text-xs">因子分析</TabsTrigger>
            <TabsTrigger value="review" className="text-xs">AI复盘</TabsTrigger>
          </TabsList>

          {/* Tab 1: Stock Insight */}
          <TabsContent value="insight" className="space-y-4">
            {loading ? (
              <div className="space-y-3"><Skeleton className="h-[250px] sm:h-[300px] w-full" /><Skeleton className="h-20 w-full" /></div>
            ) : insight ? (
              <>
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono font-semibold">{insight.code}</span>
                  <span>{insight.name}</span>
                </div>

                {/* K-line chart — lightweight-charts 蜡烛图 */}
                {insight.kline?.dates?.length ? (
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm">K线图表</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <KlineChart
                        rawData={insight.kline as KlineResponse}
                        height={400}
                        turtleOverlay={insight.turtle ? {
                          sys1_entry: insight.turtle.sys1_entry,
                          sys2_entry: insight.turtle.sys2_entry,
                          sys1_exit: insight.turtle.sys1_exit,
                          sys2_exit: insight.turtle.sys2_exit,
                          sys1_triggered: insight.turtle.sys1_triggered,
                          sys2_triggered: insight.turtle.sys2_triggered,
                        } : undefined}
                      />
                    </CardContent>
                  </Card>
                ) : null}

                {/* Turtle Trading Card */}
                {insight.turtle && !insight.turtle.error && (
                  <Card className="border-l-[3px] border-l-orange-400">
                    <CardContent className="py-3">
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs text-orange-400 font-medium">海龟交易法</p>
                        <Badge className={`text-[10px] ${
                          insight.turtle.turtle_score >= 70 ? "bg-red-500/20 text-red-400" :
                          insight.turtle.turtle_score >= 50 ? "bg-orange-500/20 text-orange-400" :
                          "bg-muted text-muted-foreground"
                        }`}>
                          评分 {insight.turtle.turtle_score}/100
                        </Badge>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                        <div className="space-y-0.5">
                          <span className="text-muted-foreground">S1入场(20日高)</span>
                          <p className={`font-mono font-medium ${insight.turtle.sys1_triggered ? "text-red-400" : ""}`}>
                            {insight.turtle.sys1_entry?.toFixed(2) ?? "--"}
                            {insight.turtle.sys1_triggered && " 🔥"}
                          </p>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-muted-foreground">S2入场(55日高)</span>
                          <p className={`font-mono font-medium ${insight.turtle.sys2_triggered ? "text-red-400" : ""}`}>
                            {insight.turtle.sys2_entry?.toFixed(2) ?? "--"}
                            {insight.turtle.sys2_triggered && " 🔥"}
                          </p>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-muted-foreground">S1出场(10日低)</span>
                          <p className={`font-mono font-medium ${insight.turtle.sys1_exit_triggered ? "text-emerald-400" : ""}`}>
                            {insight.turtle.sys1_exit?.toFixed(2) ?? "--"}
                          </p>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-muted-foreground">S2出场(20日低)</span>
                          <p className={`font-mono font-medium ${insight.turtle.sys2_exit_triggered ? "text-emerald-400" : ""}`}>
                            {insight.turtle.sys2_exit?.toFixed(2) ?? "--"}
                          </p>
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2 mt-2 text-[11px]">
                        <div>
                          <span className="text-muted-foreground">ATR(N): </span>
                          <span className="font-mono">{insight.turtle.atr_20?.toFixed(3) ?? "--"}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">止损2N: </span>
                          <span className="font-mono">{insight.turtle.atr_20 ? (insight.turtle.atr_20 * 2).toFixed(3) : "--"}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">仓位/万元: </span>
                          <span className="font-mono">{insight.turtle.atr_20 ? Math.floor(100 / insight.turtle.atr_20) : "--"}股</span>
                        </div>
                      </div>
                      {insight.turtle.details.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {insight.turtle.details.map((d, i) => (
                            <Badge key={i} variant="outline" className="text-[10px]">{d}</Badge>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}

                {/* AI 解读 — inline in insight tab */}
                {!aiExplain && !aiLoading && (
                  <div className="flex items-center gap-2">
                    <Button size="sm" variant="outline" onClick={fetchAIExplain} disabled={aiLoading}>
                      <IconBrain className="size-3.5 mr-1" />AI 解读
                    </Button>
                    <span className="text-[10px] text-muted-foreground">
                      需要配置 AI Key 后使用
                    </span>
                  </div>
                )}

                {/* AI Explain Result */}
                {aiLoading ? (
                  <Card>
                    <CardContent className="py-8 text-center space-y-2">
                      <IconBrain className="size-6 mx-auto text-muted-foreground animate-pulse" />
                      <p className="text-sm text-muted-foreground">AI 正在分析中...</p>
                    </CardContent>
                  </Card>
                ) : aiExplain ? (
                  aiExplain.error ? (
                    <Card className="border-l-[3px] border-l-red-400">
                      <CardContent className="py-3">
                        <p className="text-xs text-red-400">{aiExplain.error}</p>
                      </CardContent>
                    </Card>
                  ) : (
                    <Card className="border-l-[3px] border-l-purple-400">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <IconBrain className="size-4 text-purple-400" />
                          AI 量化解读
                          <span className="text-[10px] text-muted-foreground font-normal">
                            {aiExplain.stock?.name} ({aiExplain.stock?.code})
                          </span>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {/* Technical */}
                        {aiExplain.technical && (
                          <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                              <Badge variant="outline" className="text-[10px] border-purple-400/30 text-purple-400">技术面</Badge>
                              <span className="text-sm font-medium">{aiExplain.technical.verdict}</span>
                            </div>
                            {aiExplain.technical.signals.map((s, i) => (
                              <div key={i} className="flex gap-2 text-xs pl-2 border-l-2 border-purple-400/20">
                                <span className="text-muted-foreground shrink-0">{s.indicator}:</span>
                                <span className="font-mono shrink-0">{s.value}</span>
                                <span className="text-muted-foreground">— {s.reason}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Fundamental */}
                        {aiExplain.fundamental && (
                          <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                              <Badge variant="outline" className="text-[10px] border-blue-400/30 text-blue-400">基本面</Badge>
                              <span className="text-sm font-medium">{aiExplain.fundamental.verdict}</span>
                            </div>
                            {aiExplain.fundamental.signals.map((s, i) => (
                              <div key={i} className="flex gap-2 text-xs pl-2 border-l-2 border-blue-400/20">
                                <span className="text-muted-foreground shrink-0">{s.indicator}:</span>
                                <span className="font-mono shrink-0">{s.value}</span>
                                <span className="text-muted-foreground">— {s.reason}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Risk Alerts */}
                        {aiExplain.risk_alerts && aiExplain.risk_alerts.length > 0 && (
                          <div className="space-y-1">
                            {aiExplain.risk_alerts.map((r, i) => (
                              <div key={i} className={`text-xs flex items-start gap-1.5 ${
                                r.level === "warn" ? "text-orange-400" : "text-muted-foreground"
                              }`}>
                                <span className="shrink-0 mt-0.5">
                                  {r.level === "warn" ? "⚠" : "ℹ"}
                                </span>
                                <span>{r.message}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  )
                ) : null}

                {/* Indicators summary */}
                {insight.indicators && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">技术指标摘要</CardTitle></CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center">
                        {Object.entries(insight.indicators)
                          .filter(([key]) => key !== "signal")
                          .map(([key, val]) => {
                            const latest = typeof val === "object" && val !== null
                              ? Object.entries(val as Record<string, unknown>).slice(0, 1).map(([k, v]) => ({ k, v }))
                              : [{ k: key, v: val }]
                            return latest.map(({ k, v }) => (
                              <div key={`${key}-${k}`} className="border border-border rounded-none p-1.5">
                                <p className="text-[10px] text-muted-foreground">{k}</p>
                                <p className="text-xs font-mono font-medium">
                                  {typeof v === "number" ? v.toFixed(v < 1 ? 4 : 2) : String(v)}
                                </p>
                              </div>
                            ))
                          })}
                      </div>
                    </CardContent>
                  </Card>
                )}
                {/* AI signal summary */}
                {insight.signal && (
                  <Card className="border-l-[3px] border-l-purple-400">
                    <CardContent className="py-3">
                      <p className="text-xs text-purple-400 font-medium mb-1">综合信号</p>
                      <p className="text-sm text-muted-foreground">{insight.signal}</p>
                    </CardContent>
                  </Card>
                )}

                {/* Fundamental factors */}
                {insight.factors && Object.keys(insight.factors).length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">基本面</CardTitle></CardHeader>
                    <CardContent>
                      <div className="flex flex-wrap gap-3">
                        {Object.entries(insight.factors).map(([key, val]) => val != null && (
                          <div key={key} className="text-xs">
                            <span className="text-muted-foreground">{key}:</span>{" "}
                            <span className="font-mono">{String(val)}</span>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <Card>
                <CardContent className="py-12 text-center">
                  <p className="text-sm text-muted-foreground">输入股票代码查看技术指标和K线图</p>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Tab 2: Risk */}
          <TabsContent value="risk" className="space-y-4">
            {risk ? (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  <KpiCard label="Sharpe 比率" value={risk.sharpe?.toFixed(2) || "--"} />
                  <KpiCard label="最大回撤" value={risk.max_drawdown != null ? `${(risk.max_drawdown * 100).toFixed(1)}%` : "--"}
                    className="text-emerald-500" />
                  <KpiCard label="年化波动率" value={risk.volatility != null ? `${(risk.volatility * 100).toFixed(1)}%` : "--"} />
                  <KpiCard label="Beta (沪深300)" value={risk.beta?.toFixed(2) || "--"} />
                </div>
                {correlations.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">持仓相关性</CardTitle></CardHeader>
                    <CardContent>
                      <div className="flex flex-wrap gap-1">
                        {correlations.map((c, i) => (
                          <Badge key={i} variant="outline" className={cn("text-xs",
                            c.value > 0.7 ? "text-red-500 border-red-500/20" :
                            c.value < -0.3 ? "text-emerald-500 border-emerald-500/20" : ""
                          )}>
                            {c.code1}↔{c.code2}: {c.value.toFixed(2)}
                          </Badge>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <Card>
                <CardContent className="py-12 text-center">
                  <p className="text-sm text-muted-foreground">点击"组合风险"按钮加载</p>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Tab 3: Backtest */}
          <TabsContent value="backtest" className="space-y-4">
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-end gap-2 flex-wrap">
                  <div className="space-y-1">
                    <Label className="text-xs">每次定投</Label>
                    <Input value={btAmount} onChange={(e) => setBtAmount(e.target.value)} className="h-8 w-24" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">频率</Label>
                    <Select value={btFreq} onValueChange={setBtFreq}>
                      <SelectTrigger className="h-8 text-xs w-auto min-w-[80px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="max-h-48">
                        <SelectItem value="weekly">每周</SelectItem>
                        <SelectItem value="monthly">每月</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <Button size="sm" onClick={runBacktest} disabled={loading}>定投回测</Button>
                  <Button size="sm" variant="outline" onClick={runCompare} disabled={loading}>策略对比</Button>
                </div>
              </CardContent>
            </Card>

            {btResult && (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">定投回测结果</CardTitle></CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-center">
                    <div><p className="text-xs text-muted-foreground">总投资</p><p className="text-lg font-mono font-semibold">¥ {btResult.total_invested?.toLocaleString()}</p></div>
                    <div><p className="text-xs text-muted-foreground">终值</p><p className="text-lg font-mono font-semibold">¥ {btResult.final_value?.toLocaleString()}</p></div>
                    <div><p className="text-xs text-muted-foreground">定投收益</p><p className={cn("text-lg font-mono font-semibold", (btResult.total_return || 0) >= 0 ? "text-red-500" : "text-emerald-500")}>{btResult.total_return != null ? `${(btResult.total_return * 100).toFixed(1)}%` : "--"}</p></div>
                    <div><p className="text-xs text-muted-foreground">一次性收益</p><p className={cn("text-lg font-mono font-semibold", (btResult.lump_sum_return || 0) >= 0 ? "text-red-500" : "text-emerald-500")}>{btResult.lump_sum_return != null ? `${(btResult.lump_sum_return * 100).toFixed(1)}%` : "--"}</p></div>
                  </div>
                  {btResult.conclusion && <p className="text-xs text-muted-foreground mt-3">{btResult.conclusion}</p>}
                </CardContent>
              </Card>
            )}

            {compareResult.length > 0 && (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">策略对比</CardTitle></CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                    {compareResult.map((s, i) => {
                      const labels: Record<string, string> = { dca: "定期定额", value_avg: "价值平均", fixed_shares: "固定股数", dip_buy: "下跌加仓" }
                      return (
                        <div key={i} className="border border-border rounded-none p-2 text-center">
                          <Badge variant="outline" className="text-[10px] mb-1">{labels[s.name] || s.name}</Badge>
                          <p className={cn("text-sm font-mono font-semibold", s.return >= 0 ? "text-red-500" : "text-emerald-500")}>
                            {s.return >= 0 ? "+" : ""}{(s.return * 100).toFixed(1)}%
                          </p>
                          <p className="text-[10px] text-muted-foreground">
                            投入 ¥{s.total_invested?.toLocaleString()} · {s.trades}笔
                          </p>
                        </div>
                      )
                    })}
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Tab 4: Monte Carlo */}
          <TabsContent value="mc" className="space-y-4">
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-end gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">模拟天数</Label>
                    <Input value={mcDays} onChange={(e) => setMcDays(e.target.value)} className="h-8 w-20" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">模拟次数</Label>
                    <Input value={mcSims} onChange={(e) => setMcSims(e.target.value)} className="h-8 w-20" />
                  </div>
                  <Button size="sm" onClick={runMC} disabled={loading}>运行模拟</Button>
                </div>
              </CardContent>
            </Card>

            {mcResult && (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">蒙特卡洛模拟</CardTitle></CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-center">
                    <div><p className="text-xs text-muted-foreground">当前价格</p><p className="text-lg font-mono font-semibold">¥ {mcResult.current_price?.toFixed(2)}</p></div>
                    <div><p className="text-xs text-muted-foreground">预期终值</p><p className="text-lg font-mono font-semibold">¥ {mcResult.mean_final?.toFixed(2)}</p></div>
                    <div><p className="text-xs text-muted-foreground">亏损概率</p><p className="text-lg font-mono font-semibold text-emerald-500">{mcResult.prob_loss != null ? `${(mcResult.prob_loss * 100).toFixed(1)}%` : "--"}</p></div>
                    <div><p className="text-xs text-muted-foreground">&gt;15%亏损概率</p><p className="text-lg font-mono font-semibold text-emerald-500">{mcResult.prob_loss_15pct != null ? `${(mcResult.prob_loss_15pct * 100).toFixed(1)}%` : "--"}</p></div>
                  </div>

                  {/* Distribution chart */}
                  {mcResult.distribution && mcResult.distribution.length > 0 && (
                    <div className="mt-4">
                      <ChartContainer config={{ count: { label: "频次", color: "var(--primary)" } }} className="h-[200px] w-full">
                        <BarChart data={mcResult.distribution}>
                          <CartesianGrid vertical={false} />
                          <XAxis dataKey="price" tickLine={false} axisLine={false} tickMargin={4} tickFormatter={(v) => `¥${Number(v).toFixed(0)}`} />
                          <ChartTooltip content={<ChartTooltipContent />} />
                          <Bar dataKey="count" fill="var(--color-count)" radius={0}>
                            {mcResult.distribution.map((item, i) => (
                              <Cell key={i} fill={item.price >= mcResult.current_price ? "#ef5350" : "#26a69a"} fillOpacity={0.7} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ChartContainer>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Tab 5: Factor Panel */}
          <TabsContent value="factors" className="space-y-4">
            {factorLoading ? (
              <div className="space-y-3"><Skeleton className="h-[300px] w-full" /><Skeleton className="h-20 w-full" /></div>
            ) : factorData ? (
              <>
                {/* Overall Score */}
                <Card className="border-l-[3px] border-l-purple-400">
                  <CardContent className="py-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-muted-foreground">综合因子评分</p>
                        <p className="text-3xl font-bold font-mono mt-1">
                          {factorData.overall_score ?? "--"}
                          <span className="text-xs text-muted-foreground font-normal ml-1">/100</span>
                        </p>
                      </div>
                      <div className="text-right text-xs text-muted-foreground">
                        <p>{factorData.code} {factorData.date?.slice(0,10)}</p>
                        <p>已激活 {factorData.hit_count}/{factorData.registry_summary?.done ?? "?"} 因子</p>
                      </div>
                    </div>
                    {/* Score bar */}
                    <div className="mt-2 w-full h-2 bg-muted rounded-none overflow-hidden">
                      <div
                        className="h-full transition-all"
                        style={{
                          width: `${factorData.overall_score ?? 0}%`,
                          background: (factorData.overall_score ?? 0) >= 60 ? "#26a69a" : (factorData.overall_score ?? 0) >= 40 ? "#ffa726" : "#ef5350"
                        }}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Radar-like bar chart for categories */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">因子维度雷达</CardTitle></CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {factorData.categories.map((cat) => {
                        const score = cat.score_avg
                        const color = !score ? "var(--muted-foreground)" : score >= 60 ? "#26a69a" : score >= 40 ? "#ffa726" : "#ef5350"
                        return (
                          <div key={cat.key} className="space-y-1">
                            <div className="flex justify-between text-xs">
                              <span className="font-medium">{cat.name}</span>
                              <span className="font-mono text-muted-foreground">
                                {score ?? "--"} / 100 ({cat.done_count}/{cat.factor_count})
                              </span>
                            </div>
                            <div className="w-full h-3 bg-muted rounded-none overflow-hidden">
                              <div className="h-full transition-all rounded-none" style={{ width: `${score ?? 0}%`, background: color }} />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </CardContent>
                </Card>

                {/* Factor details per category */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {factorData.categories.map((cat) => (
                    <Card key={cat.key}>
                      <CardHeader className="pb-1">
                        <CardTitle className="text-xs flex items-center justify-between">
                          <span>{cat.name}</span>
                          <Badge variant="outline" className="text-[10px]">
                            {cat.done_count}/{cat.factor_count}
                          </Badge>
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        {cat.factors.length === 0 ? (
                          <p className="text-xs text-muted-foreground">暂无数据</p>
                        ) : (
                          <div className="space-y-1.5">
                            {cat.factors.map((f) => {
                              const isDone = f.status === "done"
                              const score = f.score
                              const color = !isDone ? "var(--muted)" :
                                (score ?? 0) >= 60 ? "#26a69a" :
                                (score ?? 0) >= 40 ? "#ffa726" : "#ef5350"
                              return (
                                <div key={f.name} className="flex items-center gap-2">
                                  <div className="flex-1 min-w-0">
                                    <div className="flex justify-between text-[11px]">
                                      <span className={cn("truncate", !isDone && "text-muted-foreground")}>
                                        {f.display}
                                        {f.direction === "正向" ? "↑" : f.direction === "负向" ? "↓" : ""}
                                      </span>
                                      <span className="font-mono ml-1 shrink-0">
                                        {isDone && score != null ? score : (isDone ? "--" : "待开发")}
                                      </span>
                                    </div>
                                    {isDone && score != null && (
                                      <div className="w-full h-1.5 bg-muted rounded-none overflow-hidden mt-0.5">
                                        <div className="h-full rounded-none" style={{ width: `${score}%`, backgroundColor: color }} />
                                      </div>
                                    )}
                                  </div>
                                  {isDone && f.value != null && f.value !== 0 && (
                                    <span className="text-[10px] font-mono text-muted-foreground w-14 text-right shrink-0 truncate">
                                      {typeof f.value === "number" ? f.value.toFixed(f.value < 0.01 ? 6 : 3) : String(f.value).slice(0, 8)}
                                    </span>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {/* AI 因子解读 */}
                {!factorExplain && !factorExplainLoading && (
                  <div className="flex items-center gap-2">
                    <Button size="sm" variant="outline" onClick={fetchFactorExplain} disabled={factorExplainLoading}>
                      <IconBrain className="size-3.5 mr-1" />AI 因子解读
                    </Button>
                    <span className="text-[10px] text-muted-foreground">基于因子评分生成总结报告</span>
                  </div>
                )}

                {factorExplainLoading && (
                  <Card>
                    <CardContent className="py-6 text-center space-y-2">
                      <IconBrain className="size-5 mx-auto text-muted-foreground animate-pulse" />
                      <p className="text-sm text-muted-foreground">AI 正在分析因子数据...</p>
                    </CardContent>
                  </Card>
                )}

                {factorExplain && (
                  factorExplain.error ? (
                    <Card className="border-l-[3px] border-l-red-400">
                      <CardContent className="py-3">
                        <p className="text-xs text-red-400">{factorExplain.error}</p>
                      </CardContent>
                    </Card>
                  ) : (
                    <Card className="border-l-[3px] border-l-purple-400">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <IconBrain className="size-4 text-purple-400" />
                          AI 因子解读
                          <span className="text-[10px] text-muted-foreground font-normal">
                            {factorExplain.code} · 综合 {factorExplain.overall_score}/100
                          </span>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {/* Strengths */}
                        {factorExplain.strengths && factorExplain.strengths.length > 0 && (
                          <div className="space-y-1.5">
                            <Badge variant="outline" className="text-[10px] border-emerald-400/30 text-emerald-400">优势维度</Badge>
                            {factorExplain.strengths.map((s, i) => (
                              <div key={i} className="flex gap-2 text-xs pl-2 border-l-2 border-emerald-400/20">
                                <span className="text-muted-foreground shrink-0 w-16">{s.dimension}</span>
                                <span className="font-mono shrink-0 text-emerald-400">{s.score}/100</span>
                                <span className="text-muted-foreground">{s.insight}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Weaknesses */}
                        {factorExplain.weaknesses && factorExplain.weaknesses.length > 0 && (
                          <div className="space-y-1.5">
                            <Badge variant="outline" className="text-[10px] border-orange-400/30 text-orange-400">风险维度</Badge>
                            {factorExplain.weaknesses.map((w, i) => (
                              <div key={i} className="flex gap-2 text-xs pl-2 border-l-2 border-orange-400/20">
                                <span className="text-muted-foreground shrink-0 w-16">{w.dimension}</span>
                                <span className="font-mono shrink-0 text-orange-400">{w.score}/100</span>
                                <span className="text-muted-foreground">{w.insight}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Overall */}
                        {factorExplain.overall && (
                          <p className="text-xs text-muted-foreground border-t border-border pt-2">{factorExplain.overall}</p>
                        )}

                        {/* Suggestion */}
                        {factorExplain.suggestion && (
                          <p className="text-xs font-medium text-purple-400">{factorExplain.suggestion}</p>
                        )}
                      </CardContent>
                    </Card>
                  )
                )}
              </>
            ) : (
              <Card>
                <CardContent className="py-12 text-center space-y-2">
                  <IconRadar2 className="size-8 mx-auto text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">输入代码后点击上方「查询」按钮</p>
                  <p className="text-xs text-muted-foreground">展示 10 大类 57 因子的完整评分</p>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Tab 6: AI 复盘 */}
          <TabsContent value="review" className="space-y-4">
            {/* Action bar */}
            <div className="flex items-center gap-2 flex-wrap">
              <Button size="sm" onClick={generateReview} disabled={reviewGenerating}>
                <IconBrain className="size-3.5 mr-1" />
                {reviewGenerating ? "AI 分析中..." : "生成复盘报告"}
              </Button>
              {reviewGenError && <p className="text-xs text-destructive">{reviewGenError}</p>}
              {reviewHistory.length > 0 && (
                <Select onValueChange={(v) => { const id = Number(v); if (id) loadReview(id) }}>
                  <SelectTrigger className="h-8 text-xs w-auto min-w-[160px]">
                    <SelectValue placeholder="历史报告" />
                  </SelectTrigger>
                  <SelectContent className="max-h-48">
                    {reviewHistory.map((h) => (
                      <SelectItem key={h.id} value={String(h.id)}>
                        {h.created_at?.slice(0, 10)} · {h.transactions_count || 0}笔
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            {/* Loading */}
            {(reviewLoading || reviewGenerating) && (
              <div className="space-y-3">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-32 w-full" />
              </div>
            )}

            {/* Empty */}
            {!reviewLoading && !reviewGenerating && !reviewData && (
              <Card>
                <CardContent className="py-12 text-center space-y-2">
                  <p className="text-4xl opacity-40">🧠</p>
                  <p className="text-sm text-muted-foreground">暂无复盘报告</p>
                  <p className="text-xs text-muted-foreground">点击「生成复盘报告」，AI 将分析你的交易行为</p>
                </CardContent>
              </Card>
            )}

            {/* Review content */}
            {!reviewLoading && reviewData && (
              <>
                {/* Hero stats */}
                <div className="grid grid-cols-3 gap-3">
                  <KpiCard label="总盈亏" value={reviewData.total_pnl != null ? `¥ ${reviewData.total_pnl.toLocaleString()}` : "--"} />
                  <KpiCard label="交易次数" value={reviewData.transactions_count?.toString() || "--"} />
                  <KpiCard label="综合评分" value={reviewData.avg_score != null ? `${reviewData.avg_score} 分` : "--"} />
                </div>

                {/* AI headline */}
                {reviewData.ai_headline && (
                  <Card className="border-l-[3px] border-l-purple-400">
                    <CardContent className="py-3">
                      <p className="text-sm italic text-muted-foreground">&ldquo;{reviewData.ai_headline}&rdquo;</p>
                    </CardContent>
                  </Card>
                )}

                {/* Dimensions */}
                {reviewData.dimensions && reviewData.dimensions.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-medium">分析维度</h3>
                    {reviewData.dimensions.map((dim, i) => (
                      <Card key={i} className="border-l-[3px] border-l-purple-400/60">
                        <CardHeader className="pb-2 cursor-pointer select-none" onClick={() => {
                          const next = new Set(expandedDims)
                          next.has(i) ? next.delete(i) : next.add(i)
                          setExpandedDims(next)
                        }}>
                          <div className="flex items-center justify-between">
                            <CardTitle className="text-sm">{dim.title}</CardTitle>
                            <Badge variant="secondary" className="text-xs">{dim.score}</Badge>
                          </div>
                          <CardDescription className="text-xs">{dim.summary}</CardDescription>
                        </CardHeader>
                        {expandedDims.has(i) && (
                          <CardContent className="pt-0">
                            <p className="text-xs text-muted-foreground whitespace-pre-wrap">{dim.detail}</p>
                          </CardContent>
                        )}
                      </Card>
                    ))}
                  </div>
                )}

                {/* Suggestions */}
                {reviewData.suggestions && reviewData.suggestions.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-medium">改进建议</h3>
                    {reviewData.suggestions.map((s, i) => (
                      <Card key={i} className="bg-purple-400/5 border border-purple-400/20">
                        <CardContent className="py-3 space-y-2">
                          <p className="text-sm">{s.text}</p>
                          {showReasoning.has(i) && <p className="text-xs text-muted-foreground border-t border-purple-400/10 pt-2">{s.reasoning}</p>}
                          <Button variant="link" size="sm" className="h-auto p-0 text-xs text-purple-400" onClick={() => {
                            const next = new Set(showReasoning)
                            next.has(i) ? next.delete(i) : next.add(i)
                            setShowReasoning(next)
                          }}>
                            {showReasoning.has(i) ? "收起推理" : "查看推理"}
                          </Button>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </>
            )}
          </TabsContent>
        </Tabs>

        {/* My Alerts Panel */}
        {!alertsLoading && alerts.length > 0 && (
          <Card className="border-l-[3px] border-l-orange-400">
            <CardHeader className="pb-1">
              <CardTitle className="text-sm flex items-center gap-2">
                <span className="text-orange-400">我的提醒</span>
                <Badge variant="outline" className="text-[10px]">{alerts.length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {alerts.map((a) => {
                  const typeLabel = a.alert_type === "turtle_s1_entry" ? "海龟S1入场" :
                    a.alert_type === "turtle_s2_entry" ? "海龟S2入场" :
                    a.alert_type
                  const isTriggered = insight && insight.code === a.stock_code &&
                    insight.price != null && insight.price >= a.target_value
                  return (
                    <div key={a.id} className={`border rounded-none p-2 flex items-center justify-between ${
                      isTriggered ? "border-red-400/50 bg-red-500/5" : "border-border"
                    }`}>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-mono font-medium">{a.stock_code}</span>
                          <Badge variant="outline" className={`text-[10px] ${
                            isTriggered ? "text-red-400 border-red-400/30" : ""
                          }`}>
                            {typeLabel}
                          </Badge>
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          目标价: <span className="font-mono">{a.target_value.toFixed(2)}</span>
                          {isTriggered && (
                            <span className="text-red-400 ml-1">触发!</span>
                          )}
                        </p>
                      </div>
                      <button
                        onClick={() => deleteAlert(a.id)}
                        className="text-[10px] text-muted-foreground hover:text-red-400 shrink-0 ml-2"
                      >
                        删除
                      </button>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  )
}

function KpiCard({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <Card>
      <CardContent className="py-3 text-center">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("text-lg font-semibold font-mono mt-0.5", className)}>{value}</p>
      </CardContent>
    </Card>
  )
}

export default function QuantPage() {
  return (
    <Suspense fallback={
      <div className="flex flex-1 flex-col">
        <SiteHeader title="量化分析" />
        <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6">
          <Skeleton className="h-[300px] w-full" />
        </div>
      </div>
    }>
      <QuantPageInner />
    </Suspense>
  )
}
