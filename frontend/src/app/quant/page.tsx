"use client"

import { useEffect, useState, useCallback, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { Area, AreaChart, CartesianGrid, XAxis, BarChart, Bar, Cell } from "recharts"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { IconChartBar, IconTrendingUp, IconBrain } from "@tabler/icons-react"

interface StockInsight {
  code: string; name: string
  indicators?: Record<string, unknown>
  signal?: string
  factors?: { label: string; value: string }[]
  kline?: { date: string; open: number; high: number; low: number; close: number; volume: number }[]
}

interface RiskKPI {
  sharpe?: number; max_drawdown?: number; volatility?: number; beta?: number
}

interface CorrelationItem { code1: string; code2: string; value: number }

interface BacktestResult {
  total_invested?: number; final_value?: number; total_return?: number
  lump_sum_return?: number; conclusion?: string
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

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
  }, [router])

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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = await apiPost<any>("/api/quant/compare", { code: code.trim(), amount: Number(btAmount) || 1000, start_date: "2024-01-01", end_date: "2025-01-01" })
      if (data?.strategies) {
        const arr: CompareResult[] = []
        for (const [name, s] of Object.entries(data.strategies) as [string, Record<string, unknown>][]) {
          arr.push({ name, total_invested: (s.total_invested as number) || 0, final_value: (s.final_value as number) || 0, return: (s.return as number) || 0, trades: (s.trades as number) || 0 })
        }
        setCompareResult(arr)
      }
    } catch { /* */ }
    finally { setLoading(false) }
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

  const klineData = insight?.kline || []
  const priceChartConfig = { close: { label: "价格", color: "#ef5350" } } satisfies ChartConfig

  return (
    <>
      <SiteHeader title="量化分析" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* Stock input */}
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <Label className="text-xs">股票代码</Label>
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="000001" className="h-8 w-28 font-mono" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">周期</Label>
            <select value={days} onChange={(e) => setDays(e.target.value)} className="h-8 rounded-none border border-input bg-background text-foreground px-2 text-xs">
              <option value="30">30天</option><option value="60">60天</option><option value="120">120天</option>
            </select>
          </div>
          <Button size="sm" onClick={fetchInsight} disabled={loading}>查看</Button>
          <Button size="sm" variant="outline" onClick={() => { fetchRisk(); setTab("risk") }}>
            <IconChartBar className="size-3.5 mr-1" />组合风险
          </Button>
        </div>

        {error && <p className="text-xs text-red-500">{error}</p>}

        <Tabs value={tab} onValueChange={(v) => { setTab(v); if (v === "risk") fetchRisk() }}>
          <TabsList className="overflow-x-auto flex-nowrap">
            <TabsTrigger value="insight" className="text-xs">个股透视</TabsTrigger>
            <TabsTrigger value="risk" className="text-xs">组合风险</TabsTrigger>
            <TabsTrigger value="backtest" className="text-xs">策略回测</TabsTrigger>
            <TabsTrigger value="mc" className="text-xs">蒙特卡洛</TabsTrigger>
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

                {/* K-line chart */}
                {klineData.length > 0 && (
                  <Card>
                    <CardContent className="pt-4">
                      <ChartContainer config={priceChartConfig} className="h-[250px] sm:h-[300px] w-full">
                        <AreaChart data={klineData}>
                          <CartesianGrid vertical={false} strokeDasharray="3 3" />
                          <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} minTickGap={32}
                            tickFormatter={(v) => String(v).slice(5)} />
                          <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
                          <Area dataKey="close" type="monotone" fill="var(--color-close)" fillOpacity={0.1}
                            stroke="var(--color-close)" strokeWidth={1.5} />
                        </AreaChart>
                      </ChartContainer>
                    </CardContent>
                  </Card>
                )}

                {/* Indicators */}
                {insight.indicators && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">技术指标</CardTitle></CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        {Object.entries(insight.indicators)
                          .filter(([key]) => key !== "signal")  // signal shown separately below
                          .map(([key, val]) => (
                          <div key={key} className="border border-border rounded-none p-2">
                            <p className="text-[10px] text-muted-foreground uppercase">{key}</p>
                            {typeof val === "object" && val !== null ? (
                              <div className="space-y-0.5">
                                {Object.entries(val as Record<string, unknown>).map(([k, v]) => (
                                  <p key={k} className="text-xs font-mono">
                                    <span className="text-muted-foreground">{k}</span>{" "}
                                    <span className="font-medium">{typeof v === "number" ? v.toFixed(v < 1 ? 4 : 2) : String(v)}</span>
                                  </p>
                                ))}
                              </div>
                            ) : (
                              <p className="text-sm font-mono font-medium">
                                {typeof val === "number" ? val.toFixed(2) : String(val)}
                              </p>
                            )}
                          </div>
                        ))}
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
                {insight.factors && insight.factors.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">基本面</CardTitle></CardHeader>
                    <CardContent>
                      <div className="flex flex-wrap gap-3">
                        {insight.factors.map((f, i) => (
                          <div key={i} className="text-xs">
                            <span className="text-muted-foreground">{f.label}:</span>{" "}
                            <span className="font-mono">{f.value}</span>
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
                    <select value={btFreq} onChange={(e) => setBtFreq(e.target.value)} className="h-8 rounded-none border border-input bg-background text-foreground px-2 text-xs">
                      <option value="weekly">每周</option><option value="monthly">每月</option>
                    </select>
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
        </Tabs>
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
