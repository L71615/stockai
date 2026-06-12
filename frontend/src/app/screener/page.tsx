"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconSearch, IconBrain, IconBolt, IconStar, IconTrash, IconChartBar } from "@tabler/icons-react"

interface ScanResult {
  code: string; name: string; industry?: string; score: number; top_factors?: string[]
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
  const [statusText, setStatusText] = useState("")

  const pollScan = useCallback(async () => {
    try {
      const s = await apiGet<{ running: boolean; progress: number; total: number; has_result: boolean }>("/api/screener/status")
      setScanning(s.running)
      setProgress(s.total ? Math.round((s.progress / s.total) * 100) : 0)
      setStatusText(s.running ? `扫描中 ${s.progress}/${s.total}` : "")
      if (s.running) {
        setTimeout(pollScan, 2000)
      } else if (s.has_result) {
        const r = await apiGet<any>("/api/screener/results?limit=30")
        setResults(r?.candidates || [])
      }
    } catch { /* */ }
  }, [])

  const fetchData = useCallback(async () => {
    try {
      const [res, wl] = await Promise.all([
        apiGet<any>("/api/screener/results?limit=30").catch(() => ({ candidates: [] })),
        apiGet<WatchItem[]>("/api/screener/watchlist").catch(() => []),
      ])
      const candidates = Array.isArray(res) ? res : (res?.candidates || [])
      setResults(candidates)
      setWatchlist(Array.isArray(wl) ? wl : [])
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchData()
    pollScan()
  }, [fetchData, pollScan, router])

  const startScan = async () => {
    setScanning(true); setProgress(0)
    await apiPost("/api/screener/run", { stock_count: 30, max_workers: 4, industry_neutral: true })
    pollScan()
  }

  const aiScreen = async () => {
    setAiScreenLoading(true)
    try {
      const picks = await apiPost<AIPick[]>("/api/screener/ai-screen", { provider: "", top_n: 5 })
      setAiPicks(Array.isArray(picks) ? picks : [])
    } catch { /* */ }
    finally { setAiScreenLoading(false) }
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
            <Button size="sm" onClick={startScan} disabled={scanning}>
              <IconSearch className="size-3.5 mr-1" />
              {scanning ? `扫描中 ${progress}%` : "开始扫描"}
            </Button>
            <Button size="sm" variant="outline" onClick={aiScreen} disabled={aiScreenLoading || results.length === 0}>
              <IconBrain className="size-3.5 mr-1" />
              AI 精选
            </Button>
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
                    <p className="p-6 text-center text-sm text-muted-foreground">点击"开始扫描"筛选全市场股票</p>
                  ) : (
                    <div className="overflow-auto max-h-[500px]">
                      <table className="w-full text-xs">
                        <thead className="bg-muted sticky top-0">
                          <tr>
                            <th className="text-left p-2 font-medium">#</th>
                            <th className="text-left p-2 font-medium">代码</th>
                            <th className="text-left p-2 font-medium">名称</th>
                            <th className="text-left p-2 font-medium">行业</th>
                            <th className="text-left p-2 font-medium">评分</th>
                            <th className="text-left p-2 font-medium">关键因子</th>
                            <th className="text-right p-2 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {results.map((r, i) => (
                            <tr key={r.code} className="border-t border-border hover:bg-accent/30 transition-colors">
                              <td className="p-2 text-muted-foreground">{i + 1}</td>
                              <td className="p-2 font-mono">{r.code}</td>
                              <td className="p-2 font-medium">{r.name}</td>
                              <td className="p-2 text-muted-foreground">{r.industry || "--"}</td>
                              <td className="p-2">
                                <div className="flex items-center gap-1.5">
                                  <div className="w-16 h-1.5 bg-muted rounded-none overflow-hidden">
                                    <div className="h-full bg-primary transition-all" style={{ width: `${Math.min(r.score || 0, 100)}%` }} />
                                  </div>
                                  <span className="font-mono text-muted-foreground">{r.score != null ? r.score.toFixed(1) : "--"}</span>
                                </div>
                              </td>
                              <td className="p-2">
                                <div className="flex flex-wrap gap-0.5">
                                  {(r.top_factors || []).slice(0, 3).map((f, j) => (
                                    <Badge key={j} variant="secondary" className="text-[10px]">{typeof f === "string" ? f : (f as { factor?: string }).factor || ""}</Badge>
                                  ))}
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
        </div>
      </div>
    </>
  )
}
