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
import { IconBrain, IconRadar2, IconPlayerPlay, IconPlus, IconSparkles, IconX } from "@tabler/icons-react"
import { BacktestResults } from "@/components/backtest-results"
import { MultiAgentAnalysis } from "@/components/multi-agent-analysis"

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

interface MemoryEntry {
  date: string; code: string; direction: string
  pending: boolean; raw: string | null
  pnl_pct: string | null; exit_date: string | null
  decision: string; reflection: string
}
interface MemoryStats {
  total_entries: number; resolved_count: number; pending_count: number
  total_gain: number; total_loss: number; avg_gain: number; avg_loss: number; net_pnl: number
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

// Strategy backtest types
interface StrategyParam {
  name: string; label: string; type: string
  default: number | [number, number]
  range: [number, number] | [[number, number], [number, number]]
  step: number; description: string
}
interface StrategyInfo {
  id: string; name: string; description: string
  source: string; source_url: string; tags: string[]
  params: StrategyParam[]; market_state: string[]
  recommended_position: string; conditions_count: number; builtin?: boolean
}

interface StrategyBacktestMetrics {
  total_return: number; annual_return: number; sharpe: number
  max_drawdown: number; win_rate: number; profit_factor: number
  num_trades: number; win_count: number; loss_count: number
  calmar: number; final_value: number; initial_cash: number
  total_pnl: number; avg_win: number; avg_loss: number
}
interface StrategyBacktestTrade {
  id: number; date: string; code: string; name: string
  direction: string; price: number; shares: number
  pnl: number | null; pnl_pct: number | null; reason: string
}
interface StrategyBacktestEquity {
  date: string; value: number; cash: number
  positions_value: number; benchmark_value: number | null
  positions_count: number
}
interface StrategyBacktestMonthly {
  month: string; strategy_return: number; benchmark_return: number | null
}
interface StrategyBacktestResult {
  error?: string
  config?: Record<string, unknown>
  metrics?: StrategyBacktestMetrics
  equity_curve?: StrategyBacktestEquity[]
  trades?: StrategyBacktestTrade[]
  monthly_returns?: StrategyBacktestMonthly[]
  final_value?: number
}

function QuantPageInner() {
  const router = useRouter()
  const params = useSearchParams()

  const [code, setCode] = useState(params.get("code") || "")
  const [days, setDays] = useState("60")
  const [insight, setInsight] = useState<StockInsight | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTabState] = useState(params.get("tab") || "insight")

  // 状态同步到 URL 参数 — 切页面再回来不会丢失
  const setTab = (v: string) => {
    setTabState(v)
    const p = new URLSearchParams(window.location.search)
    if (code) p.set("code", code); else p.delete("code")
    p.set("tab", v)
    router.replace(`/quant?${p.toString()}`, { scroll: false })
  }

  const updateCode = (v: string) => {
    setCode(v)
    const p = new URLSearchParams(window.location.search)
    if (v) p.set("code", v); else p.delete("code")
    p.set("tab", tab)
    router.replace(`/quant?${p.toString()}`, { scroll: false })
  }

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

  // Trading Memory tab
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null)
  const [memoryEntries, setMemoryEntries] = useState<MemoryEntry[]>([])
  const [memoryLoading, setMemoryLoading] = useState(false)

  // Factor panel
  const [factorData, setFactorData] = useState<FactorPanelData | null>(null)
  const [factorLoading, setFactorLoading] = useState(false)

  // Strategy backtest
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(["turtle_s1"])
  const [btStockCodes, setBtStockCodes] = useState("")
  const [btStartDate, setBtStartDate] = useState("2025-06-01")
  const [btEndDate, setBtEndDate] = useState("2026-06-01")
  const [btHoldDays, setBtHoldDays] = useState("5")
  const [btRebalanceFreq, setBtRebalanceFreq] = useState("daily")
  const [btMaxPos, setBtMaxPos] = useState("10")
  const [btPosSize, setBtPosSize] = useState("0.1")
  const [btBenchmark, setBtBenchmark] = useState("000300")
  const [btRunning, setBtRunning] = useState(false)
  const [btStrategyResult, setBtStrategyResult] = useState<StrategyBacktestResult | null>(null)
  const [btParamOverrides, setBtParamOverrides] = useState<Record<string, Record<string, number | [number, number]>>>({})
  const [btOptimizing, setBtOptimizing] = useState(false)
  const [btOptimizeResult, setBtOptimizeResult] = useState<Record<string, unknown> | null>(null)
  const [btComparing, setBtComparing] = useState(false)
  const [btCompareResult, setBtCompareResult] = useState<Record<string, unknown> | null>(null)

  // Monthly report
  const [reportMonth, setReportMonth] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
  })
  const [reportData, setReportData] = useState<Record<string, unknown> | null>(null)
  const [reportCompare, setReportCompare] = useState<Record<string, unknown> | null>(null)
  const [reportLoading, setReportLoading] = useState(false)

  const fetchMonthlyReport = async (gen = false) => {
    setReportLoading(true)
    try {
      if (gen) {
        const data = await apiPost<Record<string, unknown>>("/api/quant/monthly-report", { year_month: reportMonth })
        setReportData(data)
      } else {
        const data = await apiGet<Record<string, unknown>>(`/api/quant/monthly-report?month=${reportMonth}`)
        setReportData(data)
      }
    } catch {
      // 不存在时静默
    } finally {
      setReportLoading(false)
    }
  }

  // Load strategies on mount
  useEffect(() => {
    apiGet<StrategyInfo[]>("/api/quant/strategies").then((d) => {
      if (Array.isArray(d)) setStrategies(d)
    }).catch(() => {})
  }, [])

  const toggleStrategy = (sid: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(sid) ? prev.filter((s) => s !== sid) : [...prev, sid]
    )
  }

  const addStockFromQuick = (codes: string[]) => {
    const current = btStockCodes.split(/[,，\s]+/).filter(Boolean)
    const merged = [...new Set([...current, ...codes])]
    setBtStockCodes(merged.join(", "))
  }

  const runStrategyBacktest = async () => {
    if (selectedStrategies.length === 0) return
    setBtRunning(true)
    setBtStrategyResult(null)
    try {
      const stockCodes = btStockCodes
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
      const data = await apiPost<StrategyBacktestResult>("/api/quant/strategy-backtest", {
        strategy_ids: selectedStrategies,
        stock_codes: stockCodes,
        start_date: btStartDate,
        end_date: btEndDate,
        initial_cash: 100000,
        hold_days: Number(btHoldDays) || 5,
        rebalance_freq: btRebalanceFreq,
        max_positions: Number(btMaxPos) || 10,
        position_size_pct: Number(btPosSize) || 0.1,
        benchmark: btBenchmark,
        param_overrides: Object.keys(btParamOverrides).length > 0 ? btParamOverrides : null,
      })
      setBtStrategyResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "回测失败")
    } finally {
      setBtRunning(false)
    }
  }

  const runOptimize = async () => {
    if (selectedStrategies.length === 0) return
    const sid = selectedStrategies[0] // 一次优化一个策略
    setBtOptimizing(true)
    setBtOptimizeResult(null)
    try {
      const stockCodes = btStockCodes
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
      const data = await apiPost<Record<string, unknown>>("/api/quant/strategy-optimize", {
        strategy_id: sid,
        stock_codes: stockCodes,
        start_date: btStartDate,
        end_date: btEndDate,
        initial_cash: 100000,
        hold_days: Number(btHoldDays) || 5,
        rebalance_freq: btRebalanceFreq,
        max_positions: Number(btMaxPos) || 10,
        position_size_pct: Number(btPosSize) || 0.1,
        top_n: 20,
      })
      setBtOptimizeResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "参数优化失败")
    } finally {
      setBtOptimizing(false)
    }
  }

  const runStrategyCompare = async () => {
    if (selectedStrategies.length < 2) return
    setBtComparing(true)
    setBtCompareResult(null)
    try {
      const stockCodes = btStockCodes.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
      const data = await apiPost<Record<string, unknown>>("/api/quant/strategy-compare", {
        strategy_ids: selectedStrategies,
        stock_codes: stockCodes,
        start_date: btStartDate,
        end_date: btEndDate,
        initial_cash: 100000,
        hold_days: Number(btHoldDays) || 5,
        rebalance_freq: btRebalanceFreq,
        max_positions: Number(btMaxPos) || 10,
        position_size_pct: Number(btPosSize) || 0.1,
      })
      setBtCompareResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "对比失败")
    } finally { setBtComparing(false) }
  }

  const applyOptimizedParams = (params: Record<string, number | [number, number]>) => {
    const sid = selectedStrategies[0]
    // Convert array params from tuple-as-array format
    const normalized: Record<string, number | [number, number]> = {}
    for (const [k, v] of Object.entries(params)) {
      normalized[k] = v
    }
    setBtParamOverrides((prev) => ({ ...prev, [sid]: normalized }))
  }

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

  // URL 参数变化时自动恢复状态 + 保存到 sessionStorage（切页回来不丢失）
  useEffect(() => {
    const urlStr = params.toString()
    if (urlStr && typeof window !== "undefined") {
      sessionStorage.setItem("sidebar_quant_url", `/quant?${urlStr}`)
    }
    const urlCode = params.get("code")
    const urlTab = params.get("tab")
    if (urlTab) setTabState(urlTab)
    if (urlCode && urlCode !== code) {
      setCode(urlCode)
      setTimeout(() => {
        if (urlCode.trim()) {
          setLoading(true); setError(null)
          const t = params.get("tab") || "insight"
          if (t === "insight") {
            apiGet<StockInsight>(`/api/quant/stock-insight/${urlCode.trim()}?days=${days}`)
              .then((data) => setInsight(data as StockInsight))
              .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
              .finally(() => setLoading(false))
          }
        }
      }, 0)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()])

  const fetchInsight = async () => {
    if (!code.trim()) return
    setLoading(true); setError(null)
    try {
      const data = await apiGet<StockInsight>(`/api/quant/stock-insight/${code.trim()}?days=${days}`)
      setInsight(data)
    } catch (err) { setError(err instanceof Error ? err.message : "加载失败") }
    finally { setLoading(false) }
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

  // ── Trading Memory ──
  const fetchMemory = useCallback(async () => {
    setMemoryLoading(true)
    try {
      const [stats, entries] = await Promise.all([
        apiGet<MemoryStats>("/api/stocks/memory/stats"),
        apiGet<MemoryEntry[]>("/api/stocks/memory/entries?limit=50"),
      ])
      setMemoryStats(stats)
      setMemoryEntries(Array.isArray(entries) ? entries : [])
    } catch { /* */ }
    finally { setMemoryLoading(false) }
  }, [])

  // 统一查询入口：根据当前 tab 分发到对应操作
  const handleQuery = async () => {
    if (!code.trim()) return
    updateCode(code.trim())  // 同步 URL
    switch (tab) {
      case "insight": await fetchInsight(); break
      case "factors": await fetchFactors(); break
      case "backtest": await runStrategyBacktest(); break
      case "mc": await runMC(); break
      case "review": await fetchMemory(); break
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
                          onClick={() => { updateCode(h.code); setSelectorOpen(false) }}
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
                          onClick={() => { updateCode(w.code); setSelectorOpen(false) }}
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
                        onClick={() => { updateCode(t.code); setSelectorOpen(false) }}
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

        <Tabs value={tab} onValueChange={(v) => { setTab(v) }}>
          <TabsList className="overflow-x-auto flex-nowrap">
            <TabsTrigger value="insight" className="text-xs">个股透视</TabsTrigger>
            <TabsTrigger value="backtest" className="text-xs">策略回测</TabsTrigger>
            <TabsTrigger value="mc" className="text-xs">蒙特卡洛</TabsTrigger>
            <TabsTrigger value="agents" className="text-xs">AI 分析</TabsTrigger>
            <TabsTrigger value="factors" className="text-xs">因子分析</TabsTrigger>
            <TabsTrigger value="review" className="text-xs">交易记忆</TabsTrigger>
            <TabsTrigger value="monthly" className="text-xs">月报</TabsTrigger>
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
                            if (typeof val === "object" && val !== null && !Array.isArray(val)) {
                              return Object.entries(val as Record<string, unknown>).map(([label, arr]) => {
                                const v = Array.isArray(arr) ? arr.filter((x) => x != null).slice(-1)[0] : arr
                                const display = typeof v === "number" ? v.toFixed(v < 1 ? 4 : 2) : (v != null ? String(v) : "--")
                                return (
                                  <div key={`${key}-${label}`} className="border border-border rounded-none p-1.5">
                                    <p className="text-[10px] text-muted-foreground">{label}</p>
                                    <p className="text-xs font-mono font-medium">{display}</p>
                                  </div>
                                )
                              })
                            }
                            // 标量值（如 RSI）
                            const v = Array.isArray(val) ? val.filter((x) => x != null).slice(-1)[0] : val
                            const display = typeof v === "number" ? v.toFixed(v < 1 ? 4 : 2) : (v != null ? String(v) : "--")
                            return (
                              <div key={key} className="border border-border rounded-none p-1.5">
                                <p className="text-[10px] text-muted-foreground">{key}</p>
                                <p className="text-xs font-mono font-medium">{display}</p>
                              </div>
                            )
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
          {/* Tab 3: Strategy Backtest */}
          <TabsContent value="backtest" className="space-y-4">
            {/* 策略选择 */}
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-xs">选择策略</CardTitle></CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {strategies.length === 0 ? (
                    <span className="text-xs text-muted-foreground">加载策略列表...</span>
                  ) : (
                    strategies.map((s) => {
                      const active = selectedStrategies.includes(s.id)
                      return (
                        <button
                          key={s.id}
                          onClick={() => toggleStrategy(s.id)}
                          className={cn(
                            "inline-flex items-center gap-1 px-2 py-1 text-[11px] border transition-colors",
                            active
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground"
                          )}
                        >
                          {s.name || s.id}
                          {active && <IconX className="size-3" />}
                          {!active && <IconPlus className="size-3" />}
                        </button>
                      )
                    })
                  )}
                </div>

                {/* 已选策略详情 */}
                {selectedStrategies.map((sid) => {
                  const s = strategies.find((st) => st.id === sid)
                  if (!s) return null
                  return (
                    <div key={sid} className="mt-3 pt-3 border-t border-border space-y-2">
                      {/* 来源和标签 */}
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-medium">{s.name}</span>
                        {s.source && (
                          <Badge variant="secondary" className="text-[9px] px-1.5 py-0 h-4" title={s.source}>
                            {s.source.length > 25 ? s.source.slice(0, 25) + "…" : s.source}
                          </Badge>
                        )}
                        {s.recommended_position && (
                          <span className="text-[9px] text-muted-foreground">
                            仓位: {s.recommended_position}
                          </span>
                        )}
                      </div>
                      {s.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {s.tags.map((t) => (
                            <Badge key={t} variant="outline" className="text-[9px] px-1 py-0 h-4">{t}</Badge>
                          ))}
                          {s.market_state.map((m) => (
                            <Badge key={m} variant="outline" className={cn(
                              "text-[9px] px-1 py-0 h-4",
                              m === "bull" ? "text-red-400 border-red-500/20" :
                              m === "bear" ? "text-emerald-400 border-emerald-500/20" :
                              "text-muted-foreground"
                            )}>
                              {m === "bull" ? "牛市" : m === "bear" ? "熊市" : m === "range" ? "震荡" : m}
                            </Badge>
                          ))}
                        </div>
                      )}

                      {/* 可调参数 */}
                      {s.params.length > 0 && (
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                          {s.params.map((p) => {
                            const overrideVal = btParamOverrides[sid]?.[p.name]
                            const currentVal = overrideVal !== undefined ? overrideVal : p.default
                            return (
                              <div key={p.name} className="space-y-0.5" title={p.description}>
                                <Label className="text-[9px] text-muted-foreground flex items-center gap-1">
                                  {p.label}
                                  {overrideVal !== undefined && (
                                    <span className="text-primary">*</span>
                                  )}
                                </Label>
                                {p.type === "range" ? (
                                  <div className="flex items-center gap-1">
                                    <Input
                                      className="h-6 w-14 text-[10px] font-mono"
                                      value={Array.isArray(currentVal) ? currentVal[0] : ""}
                                      onChange={(e) => {
                                        const newVal: [number, number] = [
                                          Number(e.target.value),
                                          Array.isArray(currentVal) ? currentVal[1] : 5,
                                        ]
                                        setBtParamOverrides((prev) => ({
                                          ...prev, [sid]: { ...prev[sid], [p.name]: newVal }
                                        }))
                                      }}
                                      type="number"
                                    />
                                    <span className="text-[9px] text-muted-foreground">-</span>
                                    <Input
                                      className="h-6 w-14 text-[10px] font-mono"
                                      value={Array.isArray(currentVal) ? currentVal[1] : ""}
                                      onChange={(e) => {
                                        const newVal: [number, number] = [
                                          Array.isArray(currentVal) ? currentVal[0] : 0,
                                          Number(e.target.value),
                                        ]
                                        setBtParamOverrides((prev) => ({
                                          ...prev, [sid]: { ...prev[sid], [p.name]: newVal }
                                        }))
                                      }}
                                      type="number"
                                    />
                                  </div>
                                ) : (
                                  <Input
                                    className="h-6 text-[10px] font-mono"
                                    value={typeof currentVal === "number" ? currentVal : ""}
                                    onChange={(e) => {
                                      setBtParamOverrides((prev) => ({
                                        ...prev, [sid]: { ...prev[sid], [p.name]: Number(e.target.value) }
                                      }))
                                    }}
                                    type="number"
                                    step={p.step}
                                  />
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}

                      {/* 重置参数 */}
                      {btParamOverrides[sid] && Object.keys(btParamOverrides[sid]).length > 0 && (
                        <button
                          className="text-[9px] text-muted-foreground hover:text-foreground transition-colors"
                          onClick={() => {
                            setBtParamOverrides((prev) => {
                              const next = { ...prev }
                              delete next[sid]
                              return next
                            })
                          }}
                        >
                          重置为默认参数
                        </button>
                      )}
                    </div>
                  )
                })}
              </CardContent>
            </Card>

            {/* 股票池 */}
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-xs">股票池</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-1 flex-wrap">
                  <Button variant="outline" size="sm" className="h-6 text-[10px]" onClick={() => addStockFromQuick(quickData.holdings.map((h) => h.code))}>
                    持仓股 ({quickData.holdings.length})
                  </Button>
                  <Button variant="outline" size="sm" className="h-6 text-[10px]" onClick={() => addStockFromQuick(quickData.watchlist.map((w) => w.code))}>
                    自选股 ({quickData.watchlist.length})
                  </Button>
                </div>
                <Input
                  value={btStockCodes}
                  onChange={(e) => setBtStockCodes(e.target.value)}
                  placeholder="000001, 600519, ... (留空使用默认沪深300池)"
                  className="h-8 text-xs font-mono"
                />
              </CardContent>
            </Card>

            {/* 参数设置 */}
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-xs">参数设置</CardTitle></CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  <div className="space-y-1">
                    <Label className="text-[10px]">起始日期</Label>
                    <Input value={btStartDate} onChange={(e) => setBtStartDate(e.target.value)} className="h-7 text-xs font-mono" placeholder="2024-01-01" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">结束日期</Label>
                    <Input value={btEndDate} onChange={(e) => setBtEndDate(e.target.value)} className="h-7 text-xs font-mono" placeholder="2025-01-01" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">持仓天数</Label>
                    <Input value={btHoldDays} onChange={(e) => setBtHoldDays(e.target.value)} className="h-7 w-20 text-xs" type="number" min="1" max="60" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">调仓频率</Label>
                    <Select value={btRebalanceFreq} onValueChange={setBtRebalanceFreq}>
                      <SelectTrigger className="h-7 text-xs w-auto min-w-[80px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="daily">每日</SelectItem>
                        <SelectItem value="weekly">每周</SelectItem>
                        <SelectItem value="monthly">每月</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">最大持仓</Label>
                    <Input value={btMaxPos} onChange={(e) => setBtMaxPos(e.target.value)} className="h-7 w-20 text-xs" type="number" min="1" max="50" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">单票仓位%</Label>
                    <Input value={btPosSize} onChange={(e) => setBtPosSize(e.target.value)} className="h-7 w-20 text-xs" placeholder="0.1" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">基准指数</Label>
                    <Select value={btBenchmark} onValueChange={setBtBenchmark}>
                      <SelectTrigger className="h-7 text-xs w-auto min-w-[100px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="000300">沪深300</SelectItem>
                        <SelectItem value="000905">中证500</SelectItem>
                        <SelectItem value="399006">创业板指</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-3">
                  <Button
                    size="sm"
                    onClick={runStrategyBacktest}
                    disabled={btRunning || selectedStrategies.length === 0}
                  >
                    <IconPlayerPlay className="size-3.5" />
                    {btRunning ? "回测中..." : "开始回测"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={runOptimize}
                    disabled={btOptimizing || selectedStrategies.length !== 1}
                    title={selectedStrategies.length !== 1 ? "参数优化需选择恰好1个策略" : "网格搜索最优参数"}
                  >
                    <IconSparkles className="size-3.5" />
                    {btOptimizing ? "优化中..." : "参数优化"}
                  </Button>
                  {selectedStrategies.length !== 1 && (
                    <span className="text-[10px] text-muted-foreground">选1个策略可优化</span>
                  )}
                  {selectedStrategies.length >= 2 && (
                    <Button
                      size="sm" variant="outline"
                      onClick={runStrategyCompare}
                      disabled={btComparing}
                    >
                      <IconPlayerPlay className="size-3.5" />
                      {btComparing ? "对比中..." : "对比策略"}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* 策略对比结果 */}
            {btCompareResult && !("error" in btCompareResult) && (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-xs">策略对比</CardTitle></CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr className="border-b border-border text-muted-foreground">
                          <td className="py-1 pr-2">策略</td>
                          <td className="py-1 pr-2 text-right">交易数</td>
                          <td className="py-1 pr-2 text-right">胜率</td>
                          <td className="py-1 pr-2 text-right">夏普</td>
                          <td className="py-1 pr-2 text-right">最大回撤</td>
                          <td className="py-1 text-right">总收益</td>
                        </tr>
                      </thead>
                      <tbody>
                        {(btCompareResult.ranking as Array<Record<string, string | number>>)?.map((r, i) => (
                          <tr key={i} className={cn("border-b border-border/50", i === 0 && "bg-primary/5")}>
                            <td className="py-1 pr-2 font-medium">
                              {i === 0 && "🥇"}{i === 1 && "🥈"}{i === 2 && "🥉"}
                              {" "}{r.strategy_name as string}
                            </td>
                            <td className="py-1 pr-2 font-mono text-right">{Number(r.num_trades)}</td>
                            <td className="py-1 pr-2 font-mono text-right">{(Number(r.win_rate) * 100).toFixed(0)}%</td>
                            <td className="py-1 pr-2 font-mono text-right">{Number(r.sharpe).toFixed(2)}</td>
                            <td className={cn("py-1 pr-2 font-mono text-right", Number(r.max_drawdown) > -0.1 ? "text-emerald-400" : "text-red-400")}>
                              {(Number(r.max_drawdown) * 100).toFixed(1)}%
                            </td>
                            <td className={cn("py-1 font-mono text-right", Number(r.total_return) >= 0 ? "text-red-400" : "text-emerald-400")}>
                              {Number(r.total_return) >= 0 ? "+" : ""}{(Number(r.total_return) * 100).toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* 参数优化结果 */}
            {btOptimizeResult && !("error" in btOptimizeResult) && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs">
                    参数优化结果 — {btOptimizeResult.strategy_name as string}
                    <span className="text-[10px] text-muted-foreground ml-2">
                      ({btOptimizeResult.evaluated as number}/{btOptimizeResult.total_combinations as number} 组合)
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                    <table className="w-full text-[10px]">
                      <thead className="sticky top-0 bg-card">
                        <tr className="border-b border-border">
                          <td className="py-1 pr-2 font-medium text-muted-foreground">排名</td>
                          {((btOptimizeResult.params_definition as StrategyParam[]) || []).map((p) => (
                            <td key={p.name} className="py-1 pr-2 font-medium text-muted-foreground" title={p.description}>
                              {p.label}
                            </td>
                          ))}
                          <td className="py-1 pr-2 font-medium text-muted-foreground text-right">最大回撤</td>
                          <td className="py-1 pr-2 font-medium text-muted-foreground text-right">夏普</td>
                          <td className="py-1 pr-2 font-medium text-muted-foreground text-right">胜率</td>
                          <td className="py-1 font-medium text-muted-foreground text-center">操作</td>
                        </tr>
                      </thead>
                      <tbody>
                        {(btOptimizeResult.top_results as Array<{
                          rank: number
                          params: Record<string, number | [number, number]>
                          metrics: { max_drawdown: number; sharpe: number; win_rate: number }
                        }>)?.map((r) => (
                          <tr key={r.rank} className={cn(
                            "border-b border-border/50",
                            r.rank === 1 && "bg-primary/5"
                          )}>
                            <td className="py-1 pr-2 font-mono">
                              {r.rank === 1 && "🥇"}
                              {r.rank === 2 && "🥈"}
                              {r.rank === 3 && "🥉"}
                              {r.rank > 3 && `#${r.rank}`}
                            </td>
                            {(btOptimizeResult.params_definition as StrategyParam[]).map((p) => (
                              <td key={p.name} className="py-1 pr-2 font-mono">
                                {(() => {
                                  const val = r.params[p.name]
                                  if (p.type === "range" && Array.isArray(val)) {
                                    return `${val[0]}~${val[1]}`
                                  }
                                  return String(val)
                                })()}
                              </td>
                            ))}
                            <td className={cn(
                              "py-1 pr-2 font-mono text-right tabular-nums",
                              r.metrics.max_drawdown > -0.1 ? "text-emerald-400" : "text-red-400"
                            )}>
                              {(r.metrics.max_drawdown * 100).toFixed(1)}%
                            </td>
                            <td className="py-1 pr-2 font-mono text-right tabular-nums">
                              {r.metrics.sharpe.toFixed(2)}
                            </td>
                            <td className="py-1 pr-2 font-mono text-right tabular-nums">
                              {(r.metrics.win_rate * 100).toFixed(0)}%
                            </td>
                            <td className="py-1 text-center">
                              <button
                                className="text-[10px] text-primary hover:underline"
                                onClick={() => applyOptimizedParams(r.params)}
                              >
                                应用
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* 默认 vs 最优对比 */}
                  {(btOptimizeResult.default_metrics as object | null) != null && (
                    <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground">
                      <span>
                        默认回撤: {Number(((btOptimizeResult.default_metrics as Record<string, number>).max_drawdown ?? 0) * 100).toFixed(1)}%
                      </span>
                      <span className="text-primary">→</span>
                      <span className="text-emerald-400">
                        最优回撤: {Number(((btOptimizeResult.top_results as Array<{ metrics: Record<string, number> }>)[0]?.metrics?.max_drawdown ?? 0) * 100).toFixed(1)}%
                      </span>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {btOptimizeResult && "error" in btOptimizeResult && (
              <Card className="border-red-500/30 bg-red-500/5">
                <CardContent className="py-3">
                  <p className="text-xs text-red-400">{btOptimizeResult.error as string}</p>
                </CardContent>
              </Card>
            )}

            {/* 回测结果 */}
            {btStrategyResult?.error && (
              <Card className="border-red-500/30 bg-red-500/5">
                <CardContent className="py-3">
                  <p className="text-xs text-red-400">{btStrategyResult.error}</p>
                </CardContent>
              </Card>
            )}

            {btStrategyResult?.metrics && btStrategyResult?.equity_curve && btStrategyResult?.trades && (
              <BacktestResults
                metrics={btStrategyResult.metrics}
                equity_curve={btStrategyResult.equity_curve}
                trades={btStrategyResult.trades as Array<{
                  id: number; date: string; code: string; name: string
                  direction: "buy" | "sell"; price: number; shares: number
                  pnl: number | null; pnl_pct: number | null; reason: string
                }>}
                monthly_returns={btStrategyResult.monthly_returns ?? []}
              />
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

          {/* Tab 5: AI 多 Agent 分析 */}
          <TabsContent value="agents" className="space-y-4">
            <MultiAgentAnalysis />
          </TabsContent>

          {/* Tab 6: Factor Panel */}
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

          {/* Tab 6: 交易记忆 */}
          <TabsContent value="review" className="space-y-4">
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={fetchMemory} disabled={memoryLoading}>
                <IconBrain className="size-3.5" />
                {memoryLoading ? "加载中..." : "刷新记忆"}
              </Button>
            </div>

            {memoryStats && (
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                <Card><CardContent className="py-2 text-center">
                  <p className="text-[10px] text-muted-foreground">总记录</p>
                  <p className="text-sm font-mono font-semibold">{memoryStats.total_entries}</p>
                </CardContent></Card>
                <Card><CardContent className="py-2 text-center">
                  <p className="text-[10px] text-muted-foreground">已反思</p>
                  <p className="text-sm font-mono font-semibold text-purple-400">{memoryStats.resolved_count}</p>
                </CardContent></Card>
                <Card><CardContent className="py-2 text-center">
                  <p className="text-[10px] text-muted-foreground">待处理</p>
                  <p className="text-sm font-mono font-semibold text-yellow-400">{memoryStats.pending_count}</p>
                </CardContent></Card>
                <Card><CardContent className="py-2 text-center">
                  <p className="text-[10px] text-muted-foreground">净盈亏</p>
                  <p className={cn("text-sm font-mono font-semibold", memoryStats.net_pnl >= 0 ? "text-red-400" : "text-emerald-400")}>
                    {memoryStats.net_pnl >= 0 ? "+" : ""}¥{memoryStats.net_pnl.toFixed(0)}
                  </p>
                </CardContent></Card>
              </div>
            )}

            {memoryEntries.length === 0 && !memoryLoading && (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground text-sm">
                  <IconBrain className="size-8 mx-auto mb-2 opacity-40" />
                  暂无交易记忆。完成一笔交易后，系统会自动记录并反思。
                </CardContent>
              </Card>
            )}

            {memoryEntries.length > 0 && (
              <div className="space-y-2">
                {memoryEntries.map((e, i) => (
                  <Card key={i} className={e.pending ? "border-l-[3px] border-l-yellow-400" : "border-l-[3px] border-l-purple-400"}>
                    <CardContent className="py-2">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-muted-foreground font-mono">{e.date}</span>
                          <span className="font-mono text-xs">{e.code}</span>
                          <Badge variant="outline" className={cn("text-[10px]", e.direction === "买入" ? "text-red-400" : "text-emerald-400")}>
                            {e.direction}
                          </Badge>
                          {e.raw != null && (
                            <span className={cn("text-[10px] font-mono", parseFloat(e.raw) >= 0 ? "text-red-400" : "text-emerald-400")}>
                              {parseFloat(e.raw) >= 0 ? "+" : ""}¥{parseFloat(e.raw).toFixed(0)}
                            </span>
                          )}
                          {e.pending && <Badge className="text-[10px] bg-yellow-500/10 text-yellow-400">待反思</Badge>}
                        </div>
                      </div>
                      {e.reflection && (
                        <p className="text-xs text-muted-foreground italic mt-1">&ldquo;{e.reflection.slice(0, 200)}{e.reflection.length > 200 ? "..." : ""}&rdquo;</p>
                      )}
                      {e.pending && e.decision && (
                        <p className="text-xs text-muted-foreground mt-1 truncate">{e.decision.slice(0, 150)}</p>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>

          {/* Tab 8: Monthly Report */}
          <TabsContent value="monthly" className="space-y-4">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-xs">月度投资报告</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center gap-2">
                  <Input
                    value={reportMonth}
                    onChange={(e) => setReportMonth(e.target.value)}
                    className="h-7 w-28 text-xs font-mono"
                    placeholder="2026-07"
                    type="month"
                  />
                  <Button size="sm" variant="outline" onClick={() => fetchMonthlyReport(false)} disabled={reportLoading}>
                    {reportLoading ? "..." : "查询"}
                  </Button>
                  <Button size="sm" onClick={() => fetchMonthlyReport(true)} disabled={reportLoading}>
                    <IconBrain className="size-3.5" />
                    {reportLoading ? "生成中..." : "生成月报"}
                  </Button>
                  <Button
                    size="sm" variant="outline"
                    onClick={async () => {
                      setReportLoading(true)
                      try {
                        const data = await apiGet<Record<string, unknown>>(`/api/quant/monthly-compare?month=${reportMonth}`)
                        setReportCompare(data)
                      } catch { setReportCompare(null) }
                      finally { setReportLoading(false) }
                    }}
                    disabled={reportLoading}
                  >
                    上月对比
                  </Button>
                </div>

                {/* 月报对比 */}
                {reportCompare && !("error" in reportCompare) && (
                  <Card className="border-l-[3px] border-l-blue-400">
                    <CardContent className="py-2 space-y-1.5">
                      <p className="text-[10px] font-medium text-blue-400">
                        {reportCompare.current_month as string} vs {reportCompare.previous_month as string}
                        <Badge variant="outline" className={cn(
                          "ml-1.5 text-[9px] px-1 py-0 h-4",
                          reportCompare.trend === "improving" ? "text-green-400" :
                          reportCompare.trend === "declining" ? "text-red-400" : "text-muted-foreground"
                        )}>
                          {reportCompare.trend === "improving" ? "📈 进步" :
                           reportCompare.trend === "declining" ? "📉 退步" : "➡ 持平"}
                        </Badge>
                      </p>
                      <p className="text-xs text-muted-foreground">{reportCompare.diagnosis as string}</p>
                      {(reportCompare.delta as object | null) != null && (
                        <div className="flex gap-3 text-[10px] text-muted-foreground">
                          <span>胜率: {(reportCompare.delta as Record<string,number>).win_rate >= 0 ? "+" : ""}{(reportCompare.delta as Record<string,number>).win_rate.toFixed(1)}%</span>
                          <span>净盈亏: {(reportCompare.delta as Record<string,number>).total_pnl >= 0 ? "+" : ""}¥{(reportCompare.delta as Record<string,number>).total_pnl.toFixed(0)}</span>
                          <span>交易: {(reportCompare.delta as Record<string,number>).num_trades >= 0 ? "+" : ""}{(reportCompare.delta as Record<string,number>).num_trades}</span>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}

                {reportData && (reportData.summary as object | null) != null && (
                  <>
                    {/* 一句话概要 */}
                    {reportData.one_liner && (
                      <Card className="border-l-[3px] border-l-purple-400">
                        <CardContent className="py-2">
                          <p className="text-xs italic text-muted-foreground">
                            &ldquo;{reportData.one_liner as string}&rdquo;
                          </p>
                          {reportData.ai_score != null && (
                            <Badge variant="outline" className="mt-1 text-[10px]">
                              综合评分: {reportData.ai_score as number}/10
                            </Badge>
                          )}
                        </CardContent>
                      </Card>
                    )}

                    {/* 总成绩 */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {(() => {
                        const summary = reportData.summary as Record<string, number>
                        return (
                          <>
                            <Card><CardContent className="py-2 text-center">
                              <p className="text-[10px] text-muted-foreground">总交易</p>
                              <p className="text-sm font-mono font-semibold">{summary.total_trades ?? 0}</p>
                            </CardContent></Card>
                            <Card><CardContent className="py-2 text-center">
                              <p className="text-[10px] text-muted-foreground">胜率</p>
                              <p className="text-sm font-mono font-semibold">{(summary.win_rate ?? 0)}%</p>
                            </CardContent></Card>
                            <Card><CardContent className="py-2 text-center">
                              <p className="text-[10px] text-muted-foreground">净盈亏</p>
                              <p className={cn("text-sm font-mono font-semibold", (summary.total_pnl ?? 0) >= 0 ? "text-red-400" : "text-emerald-400")}>
                                {(summary.total_pnl ?? 0) >= 0 ? "+" : ""}¥{(summary.total_pnl ?? 0).toFixed(0)}
                              </p>
                            </CardContent></Card>
                            <Card><CardContent className="py-2 text-center">
                              <p className="text-[10px] text-muted-foreground">均持有时长</p>
                              <p className="text-sm font-mono font-semibold">{summary.avg_hold_days ?? 0}天</p>
                            </CardContent></Card>
                          </>
                        )
                      })()}
                    </div>

                    {/* 赚最多 / 亏最多 */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <Card>
                        <CardContent className="py-2">
                          <p className="text-[10px] font-medium text-red-400 mb-1">赚最多</p>
                          {((reportData.top_gainers as Array<Record<string, unknown>>) || []).length === 0 ? (
                            <p className="text-[10px] text-muted-foreground">无</p>
                          ) : (
                            (reportData.top_gainers as Array<Record<string, unknown>>).map((t, i) => (
                              <div key={i} className="flex items-center justify-between text-xs">
                                <span className="font-mono">{t.code as string} {t.name as string}</span>
                                <span className="text-red-400 font-mono">+¥{(t.pnl as number)?.toFixed(0)}</span>
                              </div>
                            ))
                          )}
                        </CardContent>
                      </Card>
                      <Card>
                        <CardContent className="py-2">
                          <p className="text-[10px] font-medium text-emerald-400 mb-1">亏最多</p>
                          {((reportData.top_losers as Array<Record<string, unknown>>) || []).length === 0 ? (
                            <p className="text-[10px] text-muted-foreground">无</p>
                          ) : (
                            (reportData.top_losers as Array<Record<string, unknown>>).map((t, i) => (
                              <div key={i} className="flex items-center justify-between text-xs">
                                <span className="font-mono">{t.code as string} {t.name as string}</span>
                                <span className="text-emerald-400 font-mono">¥{(t.pnl as number)?.toFixed(0)}</span>
                              </div>
                            ))
                          )}
                        </CardContent>
                      </Card>
                    </div>

                    {/* 策略排名 */}
                    {(reportData.strategy_ranking as Array<Record<string, unknown>>)?.length > 0 && (
                      <Card>
                        <CardContent className="py-2">
                          <p className="text-[10px] font-medium mb-1">策略表现</p>
                          <table className="w-full text-[10px]">
                            <thead>
                              <tr className="border-b border-border text-muted-foreground">
                                <td className="py-1">策略</td>
                                <td className="py-1 text-right">笔数</td>
                                <td className="py-1 text-right">胜率</td>
                                <td className="py-1 text-right">盈亏</td>
                              </tr>
                            </thead>
                            <tbody>
                              {(reportData.strategy_ranking as Array<Record<string, unknown>>).map((s, i) => (
                                <tr key={i} className="border-b border-border/50">
                                  <td className="py-1 font-mono">{s.strategy_id as string}</td>
                                  <td className="py-1 font-mono text-right">{s.trades as number}</td>
                                  <td className="py-1 font-mono text-right">{s.win_rate as number}%</td>
                                  <td className={cn("py-1 font-mono text-right", (s.total_pnl as number) >= 0 ? "text-red-400" : "text-emerald-400")}>
                                    {(s.total_pnl as number) >= 0 ? "+" : ""}¥{(s.total_pnl as number)?.toFixed(0)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </CardContent>
                      </Card>
                    )}

                    {/* AI 建议 */}
                    {reportData.ai_advice && (
                      <Card className="border-l-[3px] border-l-blue-400">
                        <CardContent className="py-2">
                          <p className="text-[10px] font-medium text-blue-400 mb-1">AI 建议</p>
                          <p className="text-xs text-muted-foreground">{reportData.ai_advice as string}</p>
                          {(reportData.ai_good as string[])?.length > 0 && (
                            <div className="mt-1 space-y-0.5">
                              <p className="text-[9px] text-green-400">做得好:</p>
                              {(reportData.ai_good as string[]).map((g, i) => (
                                <p key={i} className="text-[9px] text-muted-foreground">✓ {g}</p>
                              ))}
                            </div>
                          )}
                          {(reportData.ai_bad as string[])?.length > 0 && (
                            <div className="mt-1 space-y-0.5">
                              <p className="text-[9px] text-red-400">需改进:</p>
                              {(reportData.ai_bad as string[]).map((b, i) => (
                                <p key={i} className="text-[9px] text-muted-foreground">✗ {b}</p>
                              ))}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    )}
                  </>
                )}

                {reportData && (reportData.summary as object | null) == null && (
                  <p className="text-xs text-muted-foreground">
                    {(reportData as Record<string, unknown>).message as string || "本月暂无交易数据，无法生成月报"}
                  </p>
                )}
              </CardContent>
            </Card>
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
