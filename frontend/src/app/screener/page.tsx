"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { apiGet, apiPost } from "@/lib/auth"
import { IconSearch, IconBrain, IconBolt, IconStar, IconTrash, IconChartBar, IconUsers, IconCheck, IconX, IconCoin, IconShield, IconFlame, IconWorld } from "@tabler/icons-react"

interface ScreenerResultsResponse {
  candidates: ScanResult[]
}

interface ScanResult {
  code: string; name: string; industry?: string; score: number; top_factors?: string[]
  price?: number; change_pct?: number
  score_neutral?: number  // 行业中性化分数 (industry_neutralize 后), 后端排序键
  factor_warnings?: { factor: string; status: string; label: string; warning_days?: number; ir_current?: number | null }[]
  has_critical_warnings?: boolean
}

interface BacktestResult {
  code: string; name: string; strategy: string; return_pct?: number
  sharpe?: number; win_rate?: number; max_drawdown?: number; trade_count?: number
}

interface AIPick {
  rank: number; code: string; name: string; score: number; reasoning: string
}

interface WatchItem {
  code: string; name: string; reason?: string; score?: number
  backtest_strategy?: string; backtest_sharpe?: number
}

interface MultiAgentResult {
  // 后端 /api/screener/multi-agent-screen 实际返回:
  // { results: AgentResultItem[], summary: AgentSummary, top_picks: [] }
  results: AgentResultItem[]
  summary: {
    total: number
    buy_count: number
    hold_count: number
    sell_count: number
    avg_confidence: number
  }
  top_picks: unknown[]  // 后端目前返回空数组, 保留占位
}

interface AgentResultItem {
  rank: number
  code: string
  name: string
  verdict: "买入" | "持有" | "卖出"
  confidence: number
  score: number
  key_reasons: string[]
  risk_warning: string
  technical_report: string
}

export default function ScreenerPage() {
  const router = useRouter()
  const [scanning, setScanning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState<ScanResult[]>([])
  const [backtests, setBacktests] = useState<BacktestResult[]>([])
  const [aiPicks, setAiPicks] = useState<AIPick[]>([])
  const [watchlist, setWatchlist] = useState<WatchItem[]>([])
  const [loading, setLoading] = useState(true)
  const [aiScreenLoading, setAiScreenLoading] = useState(false)
  const [multiAgentLoading, setMultiAgentLoading] = useState(false)
  const [multiAgentResult, setMultiAgentResult] = useState<MultiAgentResult | null>(null)
  const [multiAgentError, setMultiAgentError] = useState<string | null>(null)
  const [statusText, setStatusText] = useState("")
  const [stockPool, setStockPool] = useState(500)
  const [includeGem, setIncludeGem] = useState(false)   // 是否包含创业板

  const POOL_OPTIONS = [
    { value: 30, label: "快速测试 (30只)" },
    { value: 500, label: "标准扫描 (沪深300+中证500)" },
    { value: 0, label: "全市场扫描 (全部A股)" },
  ]

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pollScan = useCallback(async () => {
    try {
      const s = await apiGet<{ running: boolean; progress: number; total: number; has_result: boolean }>("/api/screener/status")
      setScanning(s.running)
      setProgress(s.total ? Math.round((s.progress / s.total) * 100) : 0)
      setStatusText(s.running ? `扫描中 ${s.progress}/${s.total}` : "")
      if (s.running) {
        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => { void pollScan() }, 2000)
      } else if (s.has_result) {
        const r = await apiGet<ScreenerResultsResponse>("/api/screener/results?limit=30")
        setResults(r?.candidates || [])
      }
    } catch { /* */ }
  }, [])

  const fetchData = useCallback(async () => {
    try {
      const [res, wl] = await Promise.all([
        apiGet<ScreenerResultsResponse>("/api/screener/results?limit=30").catch(() => ({ candidates: [] })),
        apiGet<WatchItem[]>("/api/screener/watchlist").catch(() => []),
      ])
      const candidates = Array.isArray(res) ? res : (res?.candidates || [])
      setResults(candidates)
      setWatchlist(Array.isArray(wl) ? wl : [])
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchData()
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [fetchData])

  const startScan = async () => {
    setScanning(true); setProgress(0)
    setStatusText("")
    const boards = ["main_sh", "main_sz"]
    if (includeGem) boards.push("gem")
    await apiPost("/api/screener/run", { stock_count: stockPool, max_workers: 4, industry_neutral: true, allowed_boards: boards })
    pollScan()
  }

  const aiScreen = async () => {
    setAiScreenLoading(true)
    try {
      // 后端返回 { picks: AIPick[], summary: string, total_candidates: number }
      const result = await apiPost<{ picks?: AIPick[]; summary?: string }>(
        "/api/screener/ai-screen", { provider: "", top_n: 5 }
      )
      setAiPicks(Array.isArray(result?.picks) ? result.picks : [])
    } catch { /* */ }
    finally { setAiScreenLoading(false) }
  }

  const multiAgentScreen = async () => {
    setMultiAgentLoading(true)
    setMultiAgentError(null)
    setMultiAgentResult(null)
    try {
      // 后端返回 { results, summary, top_picks } - 5 角色多空辩论结构
      const result = await apiPost<MultiAgentResult>("/api/screener/multi-agent-screen", { provider: "" })
      if (result && Array.isArray(result.results)) {
        setMultiAgentResult(result)
      } else if (result && "error" in result) {
        setMultiAgentError((result as { error?: string }).error || "Agent 分析返回异常")
      } else {
        setMultiAgentError("Agent 分析返回结构异常")
      }
    } catch (e: unknown) {
      setMultiAgentError((e as Error).message || "Agent 分析请求失败，请检查网络后重试")
    }
    finally { setMultiAgentLoading(false) }
  }

  const runBacktest = async (code: string) => {
    const bt = await apiPost<BacktestResult[]>("/api/screener/backtest/batch", {
      codes: [code], strategies: ["ma_cross", "macd", "rsi"]
    })
    if (Array.isArray(bt)) {
      setBacktests((prev) => [...prev.filter((b) => b.code !== code), ...bt])
    }
  }

  const addWatch = async (item: ScanResult) => {
    await apiPost("/api/screener/watchlist/add", {
      code: item.code, name: item.name, reason: "", score: item.score
    })
    fetchData()
  }

  const removeWatch = async (code: string) => {
    await apiPost(`/api/screener/watchlist/${code}`, {}, "DELETE")
    fetchData()
  }

  const pipeline = async () => {
    setScanning(true)
    await apiPost("/api/screener/pipeline", { provider: "", top_n: 5 })
    fetchData()
    aiScreen()
    setScanning(false)
  }

  return (
    <>
      <SiteHeader title="AI 选股" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6 space-y-4">
          {/* Toolbar */}
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={String(stockPool)} onValueChange={(v) => setStockPool(Number(v))} disabled={scanning}>
              <SelectTrigger className="h-8 text-xs w-auto min-w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-48">
                {POOL_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={String(opt.value)}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <button
              onClick={() => setIncludeGem(!includeGem)}
              disabled={scanning}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 text-[11px] border transition-colors",
                includeGem ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
              )}
            >
              创业板{includeGem ? " ✓" : ""}
            </button>
            <Button size="sm" onClick={startScan} disabled={scanning}>
              <IconSearch className="size-3.5 mr-1" />
              {scanning ? `扫描中 ${progress}%` : "开始扫描"}
            </Button>
            <Button size="sm" variant="outline" onClick={aiScreen} disabled={aiScreenLoading || results.length === 0}>
              <IconBrain className="size-3.5 mr-1" />
              AI 精选
            </Button>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="sm" variant="outline" onClick={multiAgentScreen} disabled={multiAgentLoading || results.length === 0}>
                    <IconUsers className="size-3.5 mr-1" />
                    {multiAgentLoading ? "验证中..." : "5 Agent 验证"}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-xs max-w-[280px]">
                  5 位 AI 分析师从价值/技术/风险/情绪/宏观维度独立评估候选股，投票聚合后给出共识推荐
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <Button size="sm" variant="outline" onClick={pipeline} disabled={scanning}>
              <IconBolt className="size-3.5 mr-1" />
              一键流程
            </Button>
            {scanning && <Progress value={progress} className="w-32 h-2" />}
            {statusText && <span className="text-xs text-muted-foreground">{statusText}</span>}
          </div>

          <div className="flex flex-col xl:flex-row gap-4">
            {/* Left: Results table */}
            <div className="flex-1 space-y-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">多因子候选池</CardTitle>
                  <CardDescription>{results.length} 只股票</CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  {loading ? (
                    <div className="p-4 space-y-2"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
                  ) : results.length === 0 ? (
                    <p className="p-6 text-center text-sm text-muted-foreground">选择股票池范围，点击"开始扫描"启动多因子筛选</p>
                  ) : (
                    <div className="overflow-x-auto max-h-[500px]">
                      <table className="w-full text-xs min-w-[600px]">
                        <thead className="bg-muted sticky top-0 z-10">
                          <tr>
                            <th className="text-left p-2 font-medium sticky left-0 bg-muted z-20">#</th>
                            <th className="text-left p-2 font-medium sticky left-[28px] bg-muted z-20">代码</th>
                            <th className="text-left p-2 font-medium">名称</th>
                            <th className="text-right p-2 font-medium">股价</th>
                            <th className="text-left p-2 font-medium">评分</th>
                            <th className="text-left p-2 font-medium">关键因子</th>
                            <th className="text-right p-2 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {results.map((r, i) => (
                            <tr key={r.code} className="border-t border-border hover:bg-accent/30 transition-colors">
                              <td className="p-2 text-muted-foreground sticky left-0 bg-background">{i + 1}</td>
                              <td className="p-2 font-mono sticky left-[28px] bg-background">{r.code}</td>
                              <td className="p-2 font-medium">{r.name || r.code}</td>
                              <td className="p-2 text-right">
                                {r.price != null ? (
                                  <div className="flex flex-col items-end leading-tight">
                                    <span className="font-mono tabular-nums">{r.price.toFixed(2)}</span>
                                    {r.change_pct != null && (
                                      <span className={cn(
                                        "text-[10px] font-mono tabular-nums",
                                        r.change_pct > 0 ? "text-red-500" : r.change_pct < 0 ? "text-emerald-500" : "text-muted-foreground"
                                      )}>
                                        {r.change_pct > 0 ? "+" : ""}{r.change_pct.toFixed(2)}%
                                      </span>
                                    )}
                                  </div>
                                ) : (
                                  <span className="text-muted-foreground">--</span>
                                )}
                              </td>
                              <td className="p-2">
                                <div className="flex items-center gap-1.5">
                                  <div className="w-16 h-1.5 bg-muted rounded-none overflow-hidden">
                                    {/* 后端排序键是 score_neutral (行业中性化); 如果存在则用, 否则 fallback 到 score */}
                                    <div className="h-full bg-primary transition-all" style={{ width: `${Math.min((r.score_neutral ?? r.score) || 0, 100) * 10}%` }} />
                                  </div>
                                  <span
                                    className="font-mono text-muted-foreground"
                                    title={r.score_neutral != null ? `原始 score=${r.score?.toFixed(2)} | 行业中性化=${r.score_neutral.toFixed(2)}` : undefined}
                                  >
                                    {r.score_neutral != null ? r.score_neutral.toFixed(2) : (r.score != null ? r.score.toFixed(1) : "--")}
                                  </span>
                                </div>
                              </td>
                              <td className="p-2">
                                <div className="flex flex-wrap gap-0.5 items-center">
                                  {(r.top_factors || []).slice(0, 3).map((f, j) => {
                                    const factorName = typeof f === "string" ? f : (f as { factor?: string }).factor || ""
                                    const warn = (r.factor_warnings || []).find((w) => w.factor === factorName)
                                    return (
                                      <Badge
                                        key={j}
                                        variant="secondary"
                                        title={warn ? `${warn.label} · 累计 ${warn.warning_days ?? 0} 天 · IR ${warn.ir_current?.toFixed(3) ?? "?"}` : undefined}
                                        className={cn(
                                          "text-[10px]",
                                          warn?.status === "retired" && "bg-red-500/15 text-red-400 border-red-500/40",
                                          warn?.status === "warning" && "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
                                        )}
                                      >
                                        {factorName}{warn ? " ⚠" : ""}
                                      </Badge>
                                    )
                                  })}
                                </div>
                              </td>
                              <td className="p-2 text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => runBacktest(r.code)}>
                                    <IconChartBar className="size-3" />
                                  </Button>
                                  <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => addWatch(r)}>
                                    <IconStar className="size-3" />
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Backtest results */}
              {backtests.length > 0 && (
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">策略回测</CardTitle></CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
                      {backtests.map((bt, i) => (
                        <div key={i} className="border border-border rounded-none p-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-mono font-medium">{bt.code}</span>
                            <Badge variant="outline" className="text-[10px]">{bt.strategy}</Badge>
                          </div>
                          <div className="grid grid-cols-2 gap-1 mt-1.5 text-[11px]">
                            <span className="text-muted-foreground">收益</span>
                            <span className={cn("font-mono text-right", (bt.return_pct || 0) >= 0 ? "text-red-500" : "text-emerald-500")}>
                              {bt.return_pct != null ? `${bt.return_pct >= 0 ? "+" : ""}${bt.return_pct.toFixed(1)}%` : "--"}
                            </span>
                            <span className="text-muted-foreground">Sharpe</span>
                            <span className="font-mono text-right">{bt.sharpe?.toFixed(2) || "--"}</span>
                            <span className="text-muted-foreground">胜率</span>
                            <span className="font-mono text-right">{bt.win_rate != null ? `${(bt.win_rate * 100).toFixed(0)}%` : "--"}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Right: AI Picks + Watchlist */}
            <div className="w-full xl:w-80 shrink-0 space-y-4">
              {/* AI Picks */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-1.5">
                    <IconBrain className="size-3.5 text-purple-400" />
                    AI 精选
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {aiPicks.length === 0 ? (
                    <p className="text-xs text-muted-foreground">点击"AI 精选"让 AI 从候选池中挑选</p>
                  ) : (
                    <div className="space-y-2">
                      {aiPicks.map((pick, i) => (
                        <div key={i} className="border border-border rounded-none p-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-mono font-medium">{pick.code} {pick.name}</span>
                            <Badge variant="outline" className="text-[10px] text-purple-400">#{pick.rank}</Badge>
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2">{pick.reasoning}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Watchlist */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-1.5">
                    <IconStar className="size-3.5 text-yellow-500" />
                    盯盘列表
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {watchlist.length === 0 ? (
                    <p className="text-xs text-muted-foreground">点击结果列表中的 ⭐ 加入盯盘</p>
                  ) : (
                    <div className="space-y-1">
                      {watchlist.map((w) => (
                        <div key={w.code} className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
                          <div>
                            <span className="text-xs font-mono font-medium">{w.code}</span>
                            <span className="text-xs ml-1.5">{w.name}</span>
                          </div>
                          <Button variant="ghost" size="icon" className="size-5" onClick={() => removeWatch(w.code)}>
                            <IconTrash className="size-3 text-muted-foreground hover:text-red-500" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Multi-Agent Cross-Validation — Loading */}
          {multiAgentLoading && (
            <Card className="mt-4">
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-72 mt-1" />
              </CardHeader>
              <CardContent className="space-y-4">
                <Skeleton className="h-5 w-60" />
                <Skeleton className="h-[200px] w-full" />
                <Separator />
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="border border-border rounded-none p-3 space-y-2">
                      <Skeleton className="h-3 w-24" />
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-3 w-3/4" />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Multi-Agent Cross-Validation — Error */}
          {multiAgentError && !multiAgentLoading && (
            <Card className="mt-4 border-red-500/30">
              <CardContent className="py-4">
                <div className="flex items-start gap-3">
                  <IconX className="size-5 text-red-400 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-red-400">Agent 分析失败</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{multiAgentError}</p>
                  </div>
                  <Button size="sm" variant="outline" onClick={multiAgentScreen}>
                    重试
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Multi-Agent Cross-Validation Results */}
          {multiAgentResult && !multiAgentLoading && (
            <Card className="mt-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5 flex-wrap">
                  <IconUsers className="size-4 text-purple-400" />
                  5 Agent 交叉验证
                </CardTitle>
                <CardDescription>
                  5 角色多空辩论 · 共 {multiAgentResult.summary.total} 只 · 平均置信 {(multiAgentResult.summary.avg_confidence * 100).toFixed(0)}%
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Verdict Distribution */}
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-emerald-400">买入 {multiAgentResult.summary.buy_count}</span>
                  <span className="text-yellow-400">持有 {multiAgentResult.summary.hold_count}</span>
                  <span className="text-red-400">卖出 {multiAgentResult.summary.sell_count}</span>
                </div>

                {/* Per-Stock Results */}
                <div className="overflow-auto max-h-[500px]">
                  <table className="w-full text-xs">
                    <thead className="bg-muted sticky top-0">
                      <tr>
                        <th className="text-left p-2 font-medium">#</th>
                        <th className="text-left p-2 font-medium">股票</th>
                        <th className="text-center p-2 font-medium">结论</th>
                        <th className="text-center p-2 font-medium">置信</th>
                        <th className="text-center p-2 font-medium">评分</th>
                        <th className="text-left p-2 font-medium">关键理由</th>
                        <th className="text-center p-2 font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {multiAgentResult.results.map((a) => (
                        <tr key={a.code} className="border-t border-border hover:bg-accent/30 transition-colors">
                          <td className="p-2 text-muted-foreground font-mono">{a.rank}</td>
                          <td className="p-2">
                            <span className="font-mono">{a.code}</span>
                            <span className="ml-1 font-medium text-[11px]">{a.name}</span>
                          </td>
                          <td className="p-2 text-center">
                            <Badge variant="outline" className={cn(
                              "text-[10px]",
                              a.verdict === "买入" && "border-emerald-500/50 text-emerald-400",
                              a.verdict === "持有" && "border-yellow-500/50 text-yellow-400",
                              a.verdict === "卖出" && "border-red-500/50 text-red-400",
                            )}>
                              {a.verdict === "买入" && <IconCheck className="size-3 mr-0.5" />}
                              {a.verdict === "卖出" && <IconX className="size-3 mr-0.5" />}
                              {a.verdict}
                            </Badge>
                          </td>
                          <td className="p-2 text-center font-mono text-muted-foreground">
                            {(a.confidence * 100).toFixed(0)}%
                          </td>
                          <td className="p-2 text-center font-mono">
                            {a.score > 0 ? a.score.toFixed(2) : "--"}
                          </td>
                          <td className="p-2">
                            <div className="space-y-0.5 max-w-[320px]">
                              {a.key_reasons.slice(0, 2).map((r, j) => (
                                <div key={j} className="text-[10px] leading-tight text-muted-foreground line-clamp-2">
                                  {r.length > 60 ? r.slice(0, 60) + "..." : r}
                                </div>
                              ))}
                              {a.risk_warning && (
                                <div className="text-[10px] leading-tight text-yellow-400 line-clamp-1 mt-1">
                                  ⚠ {a.risk_warning.length > 60 ? a.risk_warning.slice(0, 60) + "..." : a.risk_warning}
                                </div>
                              )}
                            </div>
                          </td>
                          <td className="p-2 text-center">
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-6 text-[10px] px-2 py-0.5"
                              onClick={() => router.push(`/quant?code=${a.code}&from=screener`)}
                            >
                              分析
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
