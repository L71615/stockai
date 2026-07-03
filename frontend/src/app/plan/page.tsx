"use client"

import { useEffect, useState, useCallback } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import { apiGet, apiPost } from "@/lib/auth"
import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"
import {
  IconCalendar,
  IconPlus,
  IconX,
  IconDeviceFloppy,
  IconClipboardList,
  IconTarget,
  IconAlertTriangle,
  IconChartBar,
  IconBrain,
} from "@tabler/icons-react"

interface StrategyInfo {
  id: string; name: string; description: string
}

interface PlanContent {
  targets: { code: string; name: string; reason: string }[]
  strategy: string
  risk_notes: string
  max_position_pct: number
}

interface PlanData {
  id?: number
  plan_date: string
  market_state: string
  content: PlanContent | null
  summary: string
}

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export default function PlanPage() {
  const [planDate, setPlanDate] = useState(todayStr())
  const [marketState, setMarketState] = useState("")
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([])
  const [targets, setTargets] = useState<{ code: string; name: string; reason: string }[]>([])
  const [maxPosPct, setMaxPosPct] = useState(50)
  const [riskNotes, setRiskNotes] = useState("")
  const [summary, setSummary] = useState("")
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState("")
  const [newCode, setNewCode] = useState("")
  const [newName, setNewName] = useState("")
  const [newReason, setNewReason] = useState("")

  const { data: strategies } = useSWR<StrategyInfo[]>("/api/quant/strategies", swrFetcher)
  const { data: holdings } = useSWR<{ stock_code: string; stock_name: string }[]>("/api/stocks/holdings", swrFetcher)

  // 加载已有计划
  const fetchPlan = useCallback(async (date: string) => {
    try {
      const data = await apiGet<PlanData | null>(`/api/discipline/plan?date=${date}`)
      if (data) {
        setMarketState(data.market_state || "")
        setSummary(data.summary || "")
        if (data.content) {
          setTargets(data.content.targets || [])
          setSelectedStrategies(data.content.strategy ? data.content.strategy.split(",").filter(Boolean) : [])
          setRiskNotes(data.content.risk_notes || "")
          setMaxPosPct(data.content.max_position_pct || 50)
        }
      } else {
        resetForm()
      }
    } catch { /* */ }
  }, [])

  useEffect(() => {
    fetchPlan(planDate)
  }, [planDate, fetchPlan])

  const resetForm = () => {
    setMarketState("")
    setSelectedStrategies([])
    setTargets([])
    setMaxPosPct(50)
    setRiskNotes("")
    setSummary("")
  }

  const addTarget = () => {
    const code = newCode.trim()
    if (!code) return
    if (targets.some((t) => t.code === code)) return
    setTargets((prev) => [...prev, { code, name: newName.trim() || code, reason: newReason.trim() }])
    setNewCode(""); setNewName(""); setNewReason("")
  }

  const removeTarget = (idx: number) => {
    setTargets((prev) => prev.filter((_, i) => i !== idx))
  }

  const toggleStrategy = (sid: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(sid) ? prev.filter((s) => s !== sid) : [...prev, sid]
    )
  }

  const addHolding = (code: string, name: string) => {
    if (targets.some((t) => t.code === code)) return
    setTargets((prev) => [...prev, { code, name, reason: "持仓股" }])
  }

  const save = async () => {
    setSaving(true); setMsg("")
    try {
      await apiPost("/api/discipline/plan", {
        date: planDate,
        market_state: marketState,
        strategy: selectedStrategies.join(","),
        targets,
        risk_notes: riskNotes,
        max_position_pct: maxPosPct,
        summary,
      })
      setMsg("已保存")
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "保存失败")
    } finally { setSaving(false) }
  }

  const hasPlan = targets.length > 0 || selectedStrategies.length > 0 || summary

  return (
    <>
      <SiteHeader title="盘前计划" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <IconCalendar className="size-4 text-muted-foreground" />
            <Input
              type="date"
              value={planDate}
              onChange={(e) => setPlanDate(e.target.value)}
              className="h-8 w-36 text-xs font-mono"
            />
          </div>
          <Badge variant="outline" className={cn(
            "text-xs",
            hasPlan ? "text-emerald-400" : "text-muted-foreground"
          )}>
            {hasPlan ? "已有计划" : "未制定计划"}
          </Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Left column */}
          <div className="space-y-4">
            {/* Market state */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <IconChartBar className="size-4" />市场状态
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Select value={marketState} onValueChange={setMarketState}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="选择市场状态..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bull">牛市（做多为主）</SelectItem>
                    <SelectItem value="range">震荡市（高抛低吸）</SelectItem>
                    <SelectItem value="bear">熊市（防御为主）</SelectItem>
                  </SelectContent>
                </Select>
              </CardContent>
            </Card>

            {/* Strategies */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <IconTarget className="size-4" />今日策略
                </CardTitle>
                <CardDescription>选择 1-3 个策略模板</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {(strategies || []).slice(0, 12).map((s) => {
                    const active = selectedStrategies.includes(s.id)
                    return (
                      <button
                        key={s.id}
                        onClick={() => toggleStrategy(s.id)}
                        className={cn(
                          "inline-flex items-center gap-1 px-2 py-1 text-[11px] border transition-colors",
                          active
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border text-muted-foreground hover:text-foreground"
                        )}
                      >
                        {s.name || s.id}
                        {active ? <IconX className="size-3" /> : <IconPlus className="size-3" />}
                      </button>
                    )
                  })}
                </div>
              </CardContent>
            </Card>

            {/* Position limit */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <IconAlertTriangle className="size-4" />仓位控制
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-3">
                  <Input
                    type="range"
                    min="10" max="100" step="10"
                    value={maxPosPct}
                    onChange={(e) => setMaxPosPct(Number(e.target.value))}
                    className="flex-1 h-6"
                  />
                  <span className="text-sm font-mono font-semibold w-12 text-right">{maxPosPct}%</span>
                </div>
                <p className="text-[10px] text-muted-foreground mt-1">
                  今日最大仓位上限（剩余 {100 - maxPosPct}% 现金保留）
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Right column */}
          <div className="space-y-4">
            {/* Targets */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <IconClipboardList className="size-4" />候选标的
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {/* Add new */}
                <div className="flex gap-1">
                  <Input
                    value={newCode}
                    onChange={(e) => setNewCode(e.target.value)}
                    placeholder="代码"
                    className="h-7 w-24 text-xs font-mono"
                    onKeyDown={(e) => e.key === "Enter" && addTarget()}
                  />
                  <Input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="名称"
                    className="h-7 flex-1 text-xs"
                    onKeyDown={(e) => e.key === "Enter" && addTarget()}
                  />
                  <Input
                    value={newReason}
                    onChange={(e) => setNewReason(e.target.value)}
                    placeholder="理由"
                    className="h-7 w-24 text-xs"
                    onKeyDown={(e) => e.key === "Enter" && addTarget()}
                  />
                  <Button size="sm" className="h-7 px-2" onClick={addTarget}>
                    <IconPlus className="size-3" />
                  </Button>
                </div>
                {/* Quick add from holdings */}
                {holdings && holdings.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {holdings.map((h) => (
                      <button
                        key={h.stock_code}
                        onClick={() => addHolding(h.stock_code, h.stock_name)}
                        className="text-[10px] px-1.5 py-0.5 border border-border hover:border-primary text-muted-foreground hover:text-primary transition-colors"
                      >
                        +{h.stock_code} {h.stock_name}
                      </button>
                    ))}
                  </div>
                )}
                {/* Target list */}
                {targets.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-2">尚未添加候选标的</p>
                ) : (
                  <div className="space-y-1">
                    {targets.map((t, i) => (
                      <div key={i} className="flex items-center gap-2 py-1 px-2 border border-border">
                        <span className="font-mono text-xs">{t.code}</span>
                        <span className="text-xs">{t.name}</span>
                        <span className="text-[10px] text-muted-foreground flex-1 truncate">{t.reason}</span>
                        <button onClick={() => removeTarget(i)} className="text-muted-foreground hover:text-destructive">
                          <IconX className="size-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Risk notes */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">风险提示</CardTitle>
              </CardHeader>
              <CardContent>
                <Textarea
                  value={riskNotes}
                  onChange={(e) => setRiskNotes(e.target.value)}
                  placeholder="今日需要注意的风险：大盘走势、行业消息、个股风险..."
                  className="h-20 text-xs resize-none"
                />
              </CardContent>
            </Card>

            {/* Summary */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">总结</CardTitle>
              </CardHeader>
              <CardContent>
                <Textarea
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="今日交易总结（盘后填写）..."
                  className="h-20 text-xs resize-none"
                />
              </CardContent>
            </Card>

            {/* Save */}
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={save} disabled={saving}>
                <IconDeviceFloppy className="size-3.5" />
                {saving ? "保存中..." : "保存计划"}
              </Button>
              {msg && (
                <span className={cn("text-xs", msg === "已保存" ? "text-emerald-400" : "text-destructive")}>
                  {msg}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
