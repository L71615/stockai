"use client"

import { useEffect, useState, useCallback } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, apiPost } from "@/lib/auth"
import { IconFilter, IconPlus, IconTrash, IconSearch, IconStar, IconDownload } from "@tabler/icons-react"

// ── Types ──

interface ConditionField {
  key: string; label: string; type: string; category: string
  operators: string[]; unit?: string; compare_field?: string
}

interface Condition {
  id: string
  field: string
  operator: string
  value: number | [number, number] | string
  compareField?: string
}

interface StrategyTemplate {
  id: string; name: string; description: string
  market_state: string[]; recommended_position: string
  condition_count: number
}

interface StrategyDetail {
  id: string; name: string; description: string
  market_state: string[]; recommended_position: string
  conditions: { logic: string; conditions: { field: string; operator: string; value?: unknown; compare_field?: string }[] }
  sort_by: string; sort_order: string
}

interface MarketState {
  state: string; label: string; position: string
  ma60_distance_pct?: number; vol_ratio?: number
  recommended_strategies?: string[]; price?: number; ma60?: number
}

interface ScanResult {
  code: string; name: string; industry?: string
  price: number; change_pct: number
  pe?: number; pb?: number; roe?: number
  rsi_14?: number; vol_ratio?: number; avg_amount?: number
  boll_position?: number; ret_5d?: number; ret_20d?: number; atr_pct?: number
}

interface SavedScreen {
  id: number; name: string; description: string
  sort_by: string; sort_order: string
  created_at: string; updated_at: string
}

// ── Helpers ──

let _condId = 0
function newCondId() { return `c${++_condId}` }

function fmtNum(n: unknown, decimals = 2): string {
  if (n == null) return "--"
  const v = Number(n)
  if (isNaN(v)) return "--"
  return v.toFixed(decimals)
}

function fmtAmount(n: unknown): string {
  if (n == null) return "--"
  const v = Number(n)
  if (isNaN(v)) return "--"
  if (v >= 1e8) return (v / 1e8).toFixed(1) + "亿"
  if (v >= 1e4) return (v / 1e4).toFixed(1) + "万"
  return v.toFixed(0)
}

function getOpLabel(op: string): string {
  const map: Record<string, string> = {
    ">": ">", "<": "<", ">=": "≥", "<=": "≤", "==": "=", "!=": "≠",
    "between": "在...之间", "cross_above": "上穿", "cross_below": "下穿",
    "in_list": "包含", "not_in_list": "排除",
  }
  return map[op] || op
}

const CONDITION_EMOJI: Record<string, string> = {
  turtle_s1: "🐢", turtle_s2: "🐢", ma_bullish: "📈", momentum: "🚀",
  boll_mean: "📊", rsi_oversold: "📉", high_div: "🛡️", oversold_bounce: "💥", deep_value: "🏗️",
}

const CATEGORY_LABELS: Record<string, string> = {
  layer1_stocklist: "L1 股票列表",
  layer2_quote: "L2 实时行情",
  layer3_fundamental: "L3 基本面",
  layer4_kline: "L4 K线指标",
}

const LAYER_BADGE: Record<string, { label: string; color: string }> = {
  layer1_stocklist: { label: "L1", color: "bg-slate-500" },
  layer2_quote: { label: "L2", color: "bg-blue-500" },
  layer3_fundamental: { label: "L3", color: "bg-emerald-500" },
  layer4_kline: { label: "L4", color: "bg-purple-500" },
}

export default function ConditionPage() {
  const [fields, setFields] = useState<ConditionField[]>([])
  const [strategies, setStrategies] = useState<StrategyTemplate[]>([])
  const [activeStrategyId, setActiveStrategyId] = useState("")
  const [conditions, setConditions] = useState<Condition[]>([])
  const [logic, setLogic] = useState<"AND" | "OR">("AND")
  const [newField, setNewField] = useState("")
  const [sortBy, setSortBy] = useState("")
  const [sortOrder, setSortOrder] = useState("desc")
  const [marketState, setMarketState] = useState<MarketState | null>(null)

  // Scan
  const [scanning, setScanning] = useState(false)
  const [results, setResults] = useState<ScanResult[]>([])
  const [scanSummary, setScanSummary] = useState("")

  // Save
  const [savedScreens, setSavedScreens] = useState<SavedScreen[]>([])
  const [saveName, setSaveName] = useState("")
  const [showSave, setShowSave] = useState(false)

  // ── Init ──
  useEffect(() => {
    Promise.all([
      apiGet<{ fields: ConditionField[] }>("/api/screener/conditions/schema"),
      apiGet<{ strategies: StrategyTemplate[] }>("/api/screener/strategies"),
      apiGet<MarketState>("/api/screener/market-state"),
      apiGet<SavedScreen[]>("/api/screener/screens"),
    ]).then(([schema, strats, mkt, screens]) => {
      if (schema?.fields) setFields(schema.fields)
      if (strats?.strategies) setStrategies(strats.strategies)
      if (mkt && mkt.state) setMarketState(mkt)
      if (Array.isArray(screens)) setSavedScreens(screens)
    }).catch(() => {})
  }, [])

  // ── Strategy loading (toggle: click again to deselect) ──
  const loadStrategy = useCallback(async (id: string) => {
    if (activeStrategyId === id) {
      // Deselect: clear conditions
      setActiveStrategyId("")
      setConditions([])
      setSortBy("")
      setSortOrder("desc")
      return
    }
    setActiveStrategyId(id)
    try {
      const data = await apiGet<{ found: boolean; strategy?: StrategyDetail }>(`/api/screener/strategies/${id}`)
      if (data?.found && data.strategy) {
        const s = data.strategy
        const condList = Array.isArray(s.conditions) ? s.conditions : (s.conditions as { logic: string; conditions: { field: string; operator: string; value?: unknown; compare_field?: string }[] }).conditions || []
        setConditions(condList.map((c) => ({
          id: newCondId(),
          field: c.field,
          operator: c.operator,
          value: c.value as (number | [number, number] | string) || "",
          compareField: c.compare_field,
        })))
        setSortBy(s.sort_by || "")
        setSortOrder(s.sort_order || "desc")
      }
    } catch { /* */ }
  }, [activeStrategyId])

  // ── Condition CRUD ──
  const addCondition = () => {
    if (!newField) return
    const f = fields.find((f) => f.key === newField)
    if (!f) return
    const newCond: Condition = {
      id: newCondId(),
      field: f.key,
      operator: f.operators[0],
      value: f.type === "range" ? [0, 100] : f.type === "select" ? "" : 0,
      compareField: f.compare_field,
    }
    setConditions((prev) => [...prev, newCond])
    setNewField("")
  }

  const removeCondition = (id: string) => {
    setConditions((prev) => prev.filter((c) => c.id !== id))
  }

  const updateCondition = (id: string, key: string, val: unknown) => {
    setConditions((prev) => prev.map((c) => c.id === id ? { ...c, [key]: val } : c))
  }

  // ── Scan ──
  const runScan = async () => {
    setScanning(true)
    try {
      const tree = { logic, conditions: conditions.map((c) => {
        const cond: Record<string, unknown> = { field: c.field, operator: c.operator, value: c.value }
        if (c.compareField) cond.compare_field = c.compareField
        return cond
      })}
      const data = await apiPost<{ matched_count: number; total_scanned: number; results: ScanResult[] }>(
        "/api/screener/conditions/scan",
        { conditions: tree, sort_by: sortBy, sort_order: sortOrder, max_results: 100 }
      )
      setResults(data.results || [])
      setScanSummary(`筛选出 ${data.matched_count} 只 (共扫描 ${data.total_scanned} 只)`)
    } catch (err) {
      setScanSummary(`扫描失败: ${err instanceof Error ? err.message : "未知错误"}`)
    } finally { setScanning(false) }
  }

  // ── Save screen ──
  const saveScreen = async () => {
    if (!saveName.trim()) return
    const tree = { logic, conditions: conditions.map((c) => {
      const cond: Record<string, unknown> = { field: c.field, operator: c.operator, value: c.value }
      if (c.compareField) cond.compare_field = c.compareField
      return cond
    })}
    await apiPost("/api/screener/screens", {
      name: saveName, conditions: tree, sort_by: sortBy, sort_order: sortOrder,
    })
    setSaveName(""); setShowSave(false)
    // Refresh list
    const screens = await apiGet<SavedScreen[]>("/api/screener/screens")
    if (Array.isArray(screens)) setSavedScreens(screens)
  }

  const loadSaved = async (id: number) => {
    // screens endpoint returns list, we need to get full conditions
    // For simplicity: we only save/load the name here, full load would need a detail endpoint
    try {
      const rows = await apiGet<{ conditions_json?: string; sort_by?: string; sort_order?: string }[]>(`/api/screener/screens`)
      // Not ideal — conditions_json is in the table but not exposed by list endpoint.
      // For now, the main use case is creating new screens from strategy templates.
    } catch { /* */ }
    setShowSave(false)
  }

  const deleteSaved = async (id: number) => {
    await fetch(`/api/screener/screens/${id}`, { method: "DELETE" })
    setSavedScreens((prev) => prev.filter((s) => s.id !== id))
  }

  // ── Field lookup ──
  const fieldMap = new Map(fields.map((f) => [f.key, f]))
  const fieldGroups = new Map<string, ConditionField[]>()
  for (const f of fields) {
    const g = fieldGroups.get(f.category) || []
    g.push(f)
    fieldGroups.set(f.category, g)
  }

  // ── Export ──
  const exportCSV = () => {
    if (!results.length) return
    const headers = ["代码", "名称", "行业", "股价", "涨跌幅", "PE", "PB", "ROE", "RSI", "量比", "成交额", "5日涨幅"]
    const rows = results.map((r) => [
      r.code, r.name, r.industry || "", r.price, r.change_pct, r.pe ?? "", r.pb ?? "", r.roe ?? "",
      r.rsi_14 ?? "", r.vol_ratio ?? "", fmtAmount(r.avg_amount), r.ret_5d ?? "",
    ])
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n")
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url; a.download = `condition_scan_${new Date().toISOString().slice(0, 10)}.csv`
    a.click(); URL.revokeObjectURL(url)
  }

  return (
    <>
      <SiteHeader title="条件选股" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">

        {/* Market State Banner */}
        {marketState && (
          <Card className={cn(
            "border-l-[4px]",
            marketState.state === "bull" && "border-l-green-400",
            marketState.state === "range" && "border-l-yellow-400",
            marketState.state === "bear" && "border-l-red-400",
          )}>
            <CardContent className="py-3 flex items-center gap-4 flex-wrap">
              <span className="text-lg font-semibold">{marketState.label}</span>
              <span className="text-xs text-muted-foreground">
                上证 {marketState.price?.toFixed(0)} | MA60 {marketState.ma60?.toFixed(0)} ({marketState.ma60_distance_pct?.toFixed(1)}%)
              </span>
              <span className="text-xs text-muted-foreground">量比 {marketState.vol_ratio}</span>
              <span className="text-xs font-medium bg-accent px-2 py-0.5 rounded-none">
                建议仓位: {marketState.position}
              </span>
              {marketState.recommended_strategies?.map((sid) => {
                const s = strategies.find((s) => s.id === sid)
                return s ? (
                  <Badge key={sid} variant="outline" className="cursor-pointer text-xs hover:bg-accent"
                    onClick={() => loadStrategy(sid)}>
                    推荐: {s.name}
                  </Badge>
                ) : null
              })}
            </CardContent>
          </Card>
        )}

        {/* Strategy Templates */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <IconFilter className="size-4" />
              策略模板
              {activeStrategyId && (
                <Badge variant="secondary" className="text-xs ml-2">
                  {CONDITION_EMOJI[activeStrategyId]} {strategies.find((s) => s.id === activeStrategyId)?.name}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex gap-2 flex-wrap">
            {strategies.map((s) => (
              <Button
                key={s.id}
                variant={activeStrategyId === s.id ? "default" : "outline"}
                size="sm"
                className="text-xs h-7"
                onClick={() => loadStrategy(s.id)}
              >
                {CONDITION_EMOJI[s.id] || "📋"} {s.name}
              </Button>
            ))}
          </CardContent>
        </Card>

        {/* Condition Builder */}
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">筛选条件</CardTitle>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">逻辑:</span>
                <Select value={logic} onValueChange={(v) => setLogic(v as "AND" | "OR")}>
                  <SelectTrigger className="h-7 text-xs w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="AND">AND</SelectItem>
                    <SelectItem value="OR">OR</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Existing conditions */}
            {conditions.map((cond) => {
              const fieldDef = fieldMap.get(cond.field)
              if (!fieldDef) return null
              return (
                <div key={cond.id} className="flex items-center gap-2 text-xs">
                  {fieldDef.category && LAYER_BADGE[fieldDef.category] && (
                    <span className={cn(
                      "inline-flex items-center justify-center w-5 h-4 rounded-none text-[9px] font-medium text-white shrink-0",
                      LAYER_BADGE[fieldDef.category].color
                    )}>
                      {LAYER_BADGE[fieldDef.category].label}
                    </span>
                  )}
                  <Badge variant="secondary" className="shrink-0">{fieldDef.label}</Badge>

                  {/* Operator */}
                  <Select value={cond.operator} onValueChange={(v) => updateCondition(cond.id, "operator", v)}>
                    <SelectTrigger className="h-7 w-24 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {fieldDef.operators.map((op) => (
                        <SelectItem key={op} value={op}>{getOpLabel(op)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Value — 根据操作符决定单值/范围 */}
                  {cond.operator === "between" ? (
                    <div className="flex items-center gap-1">
                      <Input
                        className="h-7 w-20 text-xs"
                        value={Array.isArray(cond.value) ? cond.value[0] : (typeof cond.value === "number" ? cond.value : "")}
                        onChange={(e) => {
                          const lo = Number(e.target.value)
                          const hi = Array.isArray(cond.value) ? cond.value[1] : 100
                          updateCondition(cond.id, "value", [lo, hi])
                        }}
                        placeholder="Min"
                      />
                      <span>~</span>
                      <Input
                        className="h-7 w-20 text-xs"
                        value={Array.isArray(cond.value) ? cond.value[1] : ""}
                        onChange={(e) => {
                          const lo = Array.isArray(cond.value) ? cond.value[0] : 0
                          const hi = Number(e.target.value)
                          updateCondition(cond.id, "value", [lo, hi])
                        }}
                        placeholder="Max"
                      />
                    </div>
                  ) : cond.operator === "in_list" || cond.operator === "not_in_list" ? (
                    <Input
                      className="h-7 w-32 text-xs"
                      value={typeof cond.value === "string" ? cond.value : (Array.isArray(cond.value) ? cond.value.join(",") : "")}
                      onChange={(e) => updateCondition(cond.id, "value", e.target.value)}
                      placeholder="银行,白酒"
                    />
                  ) : (
                    <Input
                      className="h-7 w-24 text-xs"
                      value={!Array.isArray(cond.value) && (typeof cond.value === "string" || typeof cond.value === "number") ? String(cond.value) : ""}
                      onChange={(e) => updateCondition(cond.id, "value", Number(e.target.value) || e.target.value)}
                      placeholder="值"
                    />
                  )}

                  {fieldDef.unit && <span className="text-muted-foreground shrink-0">{fieldDef.unit}</span>}

                  <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={() => removeCondition(cond.id)}>
                    <IconTrash className="size-3 text-muted-foreground" />
                  </Button>
                </div>
              )
            })}

            {conditions.length === 0 && (
              <p className="text-xs text-muted-foreground py-4 text-center">
                选择一个策略模板，或从下方添加条件开始
              </p>
            )}

            {/* Add condition */}
            <div className="flex items-center gap-2 pt-2 border-t border-border">
              <Select value={newField} onValueChange={setNewField}>
                <SelectTrigger className="h-7 text-xs w-40">
                  <SelectValue placeholder="+ 添加条件" />
                </SelectTrigger>
                <SelectContent className="max-h-64">
                  {Array.from(fieldGroups.entries()).map(([cat, flds]) => (
                    <div key={cat}>
                      <div className="px-2 py-1 text-[10px] font-medium text-muted-foreground uppercase">
                        {CATEGORY_LABELS[cat] || cat}
                      </div>
                      {flds.map((f) => (
                        <SelectItem key={f.key} value={f.key}>{f.label}</SelectItem>
                      ))}
                    </div>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={addCondition} disabled={!newField}>
                <IconPlus className="size-3 mr-1" />添加
              </Button>
            </div>

            {/* Sort */}
            <div className="flex items-center gap-2 pt-1">
              <span className="text-xs text-muted-foreground">排序:</span>
              <Select value={sortBy} onValueChange={setSortBy}>
                <SelectTrigger className="h-7 text-xs w-32">
                  <SelectValue placeholder="选择字段" />
                </SelectTrigger>
                <SelectContent>
                  {fields.filter((f) => f.type !== "select").map((f) => (
                    <SelectItem key={f.key} value={f.key}>{f.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={sortOrder} onValueChange={setSortOrder}>
                <SelectTrigger className="h-7 text-xs w-16">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="desc">降序</SelectItem>
                  <SelectItem value="asc">升序</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Actions */}
        <div className="flex items-center gap-2 flex-wrap">
          <Button size="sm" onClick={runScan} disabled={scanning || conditions.length === 0}>
            <IconSearch className="size-3.5 mr-1" />
            {scanning ? "扫描中..." : "开始扫描"}
          </Button>
          <Button variant="outline" size="sm" className="text-xs" onClick={() => {
            setConditions([]); setActiveStrategyId(""); setResults([]); setScanSummary("")
          }}>
            重置
          </Button>
          <Button variant="outline" size="sm" className="text-xs" onClick={() => setShowSave(!showSave)}>
            保存策略
          </Button>
          {results.length > 0 && (
            <Button variant="outline" size="sm" className="text-xs" onClick={exportCSV}>
              <IconDownload className="size-3.5 mr-1" />导出 CSV
            </Button>
          )}
        </div>

        {/* Save dialog */}
        {showSave && (
          <Card className="border-dashed">
            <CardContent className="py-3 flex items-center gap-2">
              <Input className="h-7 text-xs w-40" placeholder="策略名称" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
              <Button size="sm" className="h-7 text-xs" onClick={saveScreen}>保存</Button>
              {/* Saved list */}
              {savedScreens.length > 0 && (
                <Select onValueChange={(v) => { if (v) setSaveName(v) }}>
                  <SelectTrigger className="h-7 text-xs w-32">
                    <SelectValue placeholder="加载已保存" />
                  </SelectTrigger>
                  <SelectContent>
                    {savedScreens.map((s) => (
                      <SelectItem key={s.id} value={s.name}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </CardContent>
          </Card>
        )}

        {/* Scan summary */}
        {scanSummary && <p className="text-xs text-muted-foreground">{scanSummary}</p>}

        {/* Results */}
        {scanning && (
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        )}

        {results.length > 0 && (
          <Card>
            <CardContent className="p-0">
              <div className="overflow-auto max-h-[600px]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card border-b">
                    <tr>
                      <th className="text-left px-3 py-2">#</th>
                      <th className="text-left px-3 py-2">代码</th>
                      <th className="text-left px-3 py-2">名称</th>
                      <th className="text-right px-3 py-2">股价</th>
                      <th className="text-right px-3 py-2">涨跌</th>
                      <th className="text-right px-3 py-2">PE</th>
                      <th className="text-right px-3 py-2">RSI</th>
                      <th className="text-right px-3 py-2">量比</th>
                      <th className="text-right px-3 py-2">成交额</th>
                      <th className="text-center px-3 py-2">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r, i) => (
                      <tr key={r.code} className="border-b border-border/50 hover:bg-muted/50">
                        <td className="px-3 py-1.5 text-muted-foreground">{i + 1}</td>
                        <td className="px-3 py-1.5 font-mono">{r.code}</td>
                        <td className="px-3 py-1.5">{r.name}</td>
                        <td className="px-3 py-1.5 text-right">{fmtNum(r.price)}</td>
                        <td className={cn("px-3 py-1.5 text-right", r.change_pct >= 0 ? "text-green-500" : "text-red-500")}>
                          {r.change_pct > 0 ? "+" : ""}{fmtNum(r.change_pct)}%
                        </td>
                        <td className="px-3 py-1.5 text-right">{fmtNum(r.pe, 1)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtNum(r.rsi_14, 0)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtNum(r.vol_ratio, 2)}</td>
                        <td className="px-3 py-1.5 text-right">{fmtAmount(r.avg_amount)}</td>
                        <td className="px-3 py-1.5 text-center">
                          <Button variant="ghost" size="icon" className="size-6"
                            onClick={() => {
                              apiPost("/api/screener/watchlist/add", {
                                code: r.code, name: r.name, reason: "条件选股",
                              }).catch(() => {})
                            }}
                            title="加入盯盘">
                            <IconStar className="size-3" />
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
    </>
  )
}
