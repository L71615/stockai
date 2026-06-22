"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { apiGet, apiPost } from "@/lib/auth"
import {
  IconSwords, IconTrophy, IconTrendingUp, IconTrendingDown,
  IconRefresh, IconChevronDown, IconChevronUp, IconHistory,
} from "@tabler/icons-react"

// ── 6 个 AI 投资人格 ──
const PERSONAS: Record<string, { name: string; desc: string; color: string }> = {
  "价值猎手": { name: "价值猎手", desc: "低 PE/PB + 高股息", color: "text-blue-400" },
  "成长捕手": { name: "成长捕手", desc: "高 EPS 增速 + ROE", color: "text-emerald-400" },
  "逆向抄底": { name: "逆向抄底", desc: "寻找超跌反弹机会", color: "text-amber-400" },
  "动量追涨": { name: "动量追涨", desc: "追逐强势趋势股", color: "text-red-400" },
  "质量精选": { name: "质量精选", desc: "高 ROE + 低负债", color: "text-purple-400" },
  "红利低波": { name: "红利低波", desc: "高股息 + 低波动", color: "text-cyan-400" },
  "价值": { name: "价值猎手", desc: "", color: "text-blue-400" },
  "成长": { name: "成长捕手", desc: "", color: "text-emerald-400" },
  "低波": { name: "红利低波", desc: "", color: "text-cyan-400" },
}

interface PickItem {
  stock_code: string; stock_name: string; buy_price: number
  quantity: number; invested: number; reason?: string; style?: string
}

interface PlayerStatus {
  provider: string; persona: string; persona_id?: string
  picks: PickItem[]; total_value: number; total_return: number
  total_return_pct: number; is_winner: boolean
}

interface RoundStatus {
  round_id: number; period_days: number; initial_capital: number
  started_at?: string; status: string
  players: PlayerStatus[]
}

interface DuelStartResponse {
  round_id: number
}

interface HistoryRound {
  id: number; status: string; period_days: number
  initial_capital: number; created_at?: string
}

export default function DuelPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [activeRound, setActiveRound] = useState<RoundStatus | null>(null)
  const [history, setHistory] = useState<HistoryRound[]>([])
  const [starting, setStarting] = useState(false)
  const [rebalancing, setRebalancing] = useState(false)
  const [expandedPlayer, setExpandedPlayer] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  // Provider selection: 至少 2 个不同 AI 对打
  const AVAILABLE_PROVIDERS = [
    { key: "deepseek", label: "DeepSeek" },
    { key: "minimax", label: "MiniMax" },
    { key: "openai", label: "OpenAI" },
    { key: "claude", label: "Claude" },
    { key: "xiaomi", label: "小米" },
    { key: "custom", label: "自定义" },
  ]
  const [duelProviders, setDuelProviders] = useState<string[]>(["deepseek", "minimax"]) // 至少 2 个

  const fetchStatus = useCallback(async () => {
    try {
      // 查最新 active 回合
      const rounds = await apiGet<HistoryRound[]>("/api/quant/ai-duel/history")
      setHistory(Array.isArray(rounds) ? rounds : [])
      const active = rounds.find((r: HistoryRound) => r.status === "active")
      if (active) {
        const status = await apiGet<RoundStatus>(`/api/quant/ai-duel/status/${active.id}`)
        setActiveRound(status)
      } else {
        setActiveRound(null)
      }
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus, router])

  const startDuel = async () => {
    // 验证至少 2 个不同供应商
    const uniqueProviders = [...new Set(duelProviders)].filter(Boolean)
    if (uniqueProviders.length < 2) {
      alert("请至少选择 2 个不同的 AI 供应商进行对战")
      return
    }
    setStarting(true)
    try {
      await apiPost<DuelStartResponse>("/api/quant/ai-duel/start", {
        providers: uniqueProviders,
        period_days: 7,
        capital: 100000,
      })
      await fetchStatus()
      // 滚动到对战区域
      setTimeout(() => window.scrollTo({ top: 200, behavior: "smooth" }), 300)
    } catch (e: unknown) {
      alert((e as Error).message || "开局失败")
    }
    finally { setStarting(false) }
  }

  const doRebalance = async () => {
    if (!activeRound) return
    setRebalancing(true)
    try {
      await apiPost(`/api/quant/ai-duel/rebalance/${activeRound.round_id}`, {})
      await fetchStatus()
    } catch (e: unknown) {
      alert((e as Error).message || "调仓失败")
    }
    finally { setRebalancing(false) }
  }

  const formatMoney = (v: number | undefined | null) =>
    v != null ? `¥ ${v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : "¥ —"
  const formatPct = (v: number | undefined | null) =>
    v != null ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—"

  return (
    <>
      <SiteHeader title="AI 策略对抗" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6 space-y-4">

          {/* ── Toolbar ── */}
          <div className="flex items-center gap-3 flex-wrap">
            <Button size="sm" onClick={startDuel} disabled={starting || !!activeRound}>
              <IconSwords className="size-4 mr-1" />
              {starting ? "开局中..." : activeRound ? "对战进行中" : "开局对战"}
            </Button>
            {activeRound && (
              <>
                <Button size="sm" variant="outline" onClick={doRebalance} disabled={rebalancing}>
                  <IconRefresh className={cn("size-3.5 mr-1", rebalancing && "animate-spin")} />
                  调仓
                </Button>
                <Button size="sm" variant="outline" onClick={fetchStatus}>
                  <IconRefresh className="size-3.5 mr-1" />
                  刷新
                </Button>
              </>
            )}
            {activeRound && (
              <span className="text-xs text-muted-foreground">
                回合 #{activeRound.round_id} · {activeRound.period_days}天 · 每人 ¥{(activeRound.initial_capital / 10000).toFixed(0)}万
              </span>
            )}
          </div>

          {/* ── Loading ── */}
          {loading && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-[200px]" />)}
            </div>
          )}

          {/* ── Active Duel ── */}
          {!loading && activeRound && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-muted-foreground">实时排名</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {[...activeRound.players]
                  .sort((a, b) => b.total_return_pct - a.total_return_pct)
                  .map((player, rank) => {
                    const persona = PERSONAS[player.persona] || { name: player.persona, desc: "", color: "text-muted-foreground" }
                    const isExpanded = expandedPlayer === `${player.provider}-${player.persona}`
                    const isUp = player.total_return_pct >= 0

                    return (
                      <Card
                        key={`${player.provider}-${player.persona}`}
                        className={cn(
                          "relative transition-shadow hover:shadow-md",
                          rank === 0 && "ring-1 ring-amber-400/50"
                        )}
                      >
                        <CardHeader className="pb-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              {rank === 0 && <IconTrophy className="size-4 text-amber-400" />}
                              {rank === 1 && <IconTrophy className="size-4 text-slate-400" />}
                              {rank === 2 && <IconTrophy className="size-4 text-orange-400" />}
                              <span className="text-xs text-muted-foreground">#{rank + 1}</span>
                            </div>
                            <Badge variant="outline" className="text-[10px]">
                              {player.provider}
                            </Badge>
                          </div>
                          <CardTitle className={cn("text-base font-semibold", persona.color)}>
                            {persona.name}
                          </CardTitle>
                          <CardDescription className="text-xs">{persona.desc}</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-2">
                          {/* 收益率 */}
                          <div className="flex items-baseline justify-between">
                            <span className="text-xl sm:text-2xl font-mono font-bold tabular-nums">
                              {formatMoney(player.total_value)}
                            </span>
                            <span className={cn(
                              "text-lg font-mono font-semibold tabular-nums",
                              isUp ? "text-red-500" : "text-emerald-500"
                            )}>
                              {formatPct(player.total_return_pct)}
                            </span>
                          </div>

                          {/* 持仓摘要 */}
                          <div className="text-xs text-muted-foreground">
                            {player.picks.length} 只持仓 · 初始 {formatMoney(activeRound.initial_capital)}
                          </div>

                          {/* 展开持仓明细 */}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="w-full text-xs h-7"
                            onClick={() => setExpandedPlayer(isExpanded ? null : `${player.provider}-${player.persona}`)}
                          >
                            {isExpanded ? <IconChevronUp className="size-3 mr-1" /> : <IconChevronDown className="size-3 mr-1" />}
                            {isExpanded ? "收起" : "持仓明细"}
                          </Button>

                          {isExpanded && (
                            <div className="space-y-1.5 pt-1">
                              {player.picks.map((pick, pi) => {
                                const pickPnl = (pick.buy_price || 0) * (pick.quantity || 0)
                                return (
                                  <div key={pi} className="flex items-center justify-between text-xs border-t border-border/50 pt-1.5">
                                    <div>
                                      <span className="font-mono">{pick.stock_code}</span>
                                      <span className="text-muted-foreground ml-1">{pick.stock_name}</span>
                                    </div>
                                    <div className="text-right font-mono tabular-nums">
                                      <div>¥{pick.buy_price?.toFixed(2)} × {pick.quantity}</div>
                                      <div className="text-muted-foreground">{formatMoney(pick.invested || pickPnl)}</div>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    )
                  })}
              </div>
            </div>
          )}

          {/* ── No Active Duel ── */}
          {!loading && !activeRound && (
            <Card>
              <CardContent className="py-8 text-center space-y-4">
                <IconSwords className="size-12 mx-auto text-muted-foreground/30" />
                <div>
                  <p className="text-sm text-muted-foreground">暂无进行中的 AI 对战</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    6 个 AI 投资人格 × 多个供应商，独立选股对战
                  </p>
                </div>

                {/* Provider 选择 */}
                <div className="max-w-md mx-auto space-y-3 text-left">
                  <p className="text-xs font-medium text-muted-foreground">选择对战供应商（至少 2 个不同 AI）</p>
                  <div className="grid grid-cols-2 gap-2">
                    {duelProviders.map((provider, i) => (
                      <div key={i} className="flex items-center gap-1.5">
                        <Select value={provider} onValueChange={(v) => {
                            const next = [...duelProviders]
                            next[i] = v
                            setDuelProviders(next)
                          }}>
                          <SelectTrigger className="h-8 text-xs flex-1">
                            <SelectValue placeholder="-- 不选 --" />
                          </SelectTrigger>
                          <SelectContent className="max-h-48">
                            {AVAILABLE_PROVIDERS.map((ap) => (
                              <SelectItem key={ap.key} value={ap.key}>{ap.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        {duelProviders.length > 2 && (
                          <button
                            onClick={() => setDuelProviders(duelProviders.filter((_, j) => j !== i))}
                            className="text-xs text-muted-foreground hover:text-red-400 shrink-0"
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  {duelProviders.length < 6 && (
                    <button
                      onClick={() => setDuelProviders([...duelProviders, ""])}
                      className="text-[10px] text-primary hover:underline"
                    >
                      + 添加更多供应商
                    </button>
                  )}
                  <p className="text-[10px] text-muted-foreground">
                    6 个投资人格将均分给所选供应商（{" "}
                    {duelProviders.filter(Boolean).length >= 2
                      ? `每个供应商管理 ${Math.floor(6 / duelProviders.filter(Boolean).length)} 个人格`
                      : "至少需要 2 个"}
                    ）
                  </p>
                </div>

                <Button onClick={startDuel} disabled={starting}>
                  <IconSwords className="size-4 mr-1" />
                  {starting ? "开局中..." : "立即开局"}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* ── 对战说明 ── */}
          {!loading && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">对战规则</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 text-xs text-muted-foreground">
                  {Object.entries(PERSONAS).filter(([k]) => !["价值", "成长", "低波"].includes(k)).map(([key, p]) => (
                    <div key={key} className="flex items-center gap-1.5">
                      <span className={cn("font-medium", p.color)}>{p.name}</span>
                      <span>{p.desc}</span>
                    </div>
                  ))}
                </div>
                <Separator className="my-3" />
                <div className="text-xs text-muted-foreground space-y-1">
                  <p>· 每个 AI 获得 ¥10 万虚拟初始资金，独立选股（最多 6 只）</p>
                  <p>· 按实时股价成交，7 天后结算排名</p>
                  <p>· 自动止盈 (+30%) / 止损 (-15%)</p>
                  <p>· 交易窗口内可一键调仓（11:00-11:30 / 14:30-15:00）</p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ── 历史对战 ── */}
          {history.length > 1 && (
            <Card>
              <CardHeader
                className="pb-2 cursor-pointer"
                onClick={() => setHistoryOpen(!historyOpen)}
              >
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <IconHistory className="size-4" />
                    历史对战 ({history.length - (activeRound ? 1 : 0)} 场)
                  </CardTitle>
                  {historyOpen ? <IconChevronUp className="size-4" /> : <IconChevronDown className="size-4" />}
                </div>
              </CardHeader>
              {historyOpen && (
                <CardContent>
                  <div className="space-y-1">
                    {history.filter(r => r.id !== activeRound?.round_id).map((r) => (
                      <div key={r.id} className="flex items-center justify-between text-xs py-1.5 border-b border-border/30 last:border-0">
                        <span>回合 #{r.id}</span>
                        <span className="text-muted-foreground">{r.period_days} 天</span>
                        <Badge variant="secondary" className={cn(
                          "text-[10px]",
                          r.status === "completed" ? "text-blue-400" : "text-muted-foreground"
                        )}>
                          {r.status === "active" ? "进行中" : r.status === "completed" ? "已结束" : r.status}
                        </Badge>
                        <span className="text-muted-foreground font-mono">
                          ¥{(r.initial_capital / 10000).toFixed(0)}万
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              )}
            </Card>
          )}

        </div>
      </div>
    </>
  )
}
