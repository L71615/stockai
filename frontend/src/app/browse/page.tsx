"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { apiGet, apiPost } from "@/lib/auth"
import { cn } from "@/lib/utils"
import {
  IconSearch, IconRefresh, IconCircleCheck, IconAlertTriangle, IconCircleX,
  IconChevronDown, IconChevronUp, IconStar, IconPlayerPlay, IconBuildingBank,
} from "@tabler/icons-react"
import type {
  BrowseStock, BrowseSector, BrowseStocksResponse,
  FreshnessResponse, SectorPerformanceResponse, SparklineResponse,
  SyncTaskResponse, SyncStatusResponse,
} from "@/lib/api-types"

// ── 完整性 badge 颜色映射 ──
const INTEGRITY_BADGE = {
  fresh: { label: "新鲜", color: "border-emerald-500/50 bg-emerald-500/10 text-emerald-400", icon: IconCircleCheck },
  stale: { label: "滞后", color: "border-yellow-500/50 bg-yellow-500/10 text-yellow-400", icon: IconAlertTriangle },
  missing: { label: "缺失", color: "border-red-500/50 bg-red-500/10 text-red-400", icon: IconCircleX },
} as const

export default function BrowsePage() {
  const router = useRouter()

  // ── 状态 ──
  const [search, setSearch] = useState("")
  const [sector, setSector] = useState<string>("")
  const [integrity, setIntegrity] = useState<string>("")
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState<SyncStatusResponse | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── 数据获取 ──
  const stocksSwr = useBrowseStocks({ sector, integrity, search })
  const freshnessSwr = useFreshness()
  const sectorPerfSwr = useSectorPerformance()
  const sparklineCache = useSparklineCache()

  // ── 一键补齐 ──
  const startSync = useCallback(async (scope: string, sec: string = "") => {
    setSyncing(true)
    setSyncProgress(null)
    try {
      const params = new URLSearchParams({ scope })
      if (sec) params.set("sector", sec)
      const task = await apiPost<SyncTaskResponse>(`/api/data-ops/sync-stocks?${params}`)
      setToast(`补齐任务已启动：${task.target_count} 只股票`)
      // 轮询状态
      const poll = async () => {
        try {
          const status = await apiGet<SyncStatusResponse>(`/api/data-ops/sync-status/${task.task_id}`)
          setSyncProgress(status)
          if (status.status === "running") {
            pollRef.current = setTimeout(poll, 2000)
          } else {
            setSyncing(false)
            setToast(`补齐完成：✓ ${status.completed}  ✗ ${status.failed}`)
            stocksSwr.refresh()
            freshnessSwr.refresh()
          }
        } catch {
          setSyncing(false)
        }
      }
      poll()
    } catch (e) {
      setSyncing(false)
      setToast(`启动失败: ${e instanceof Error ? e.message : "未知错误"}`)
    }
  }, [stocksSwr, freshnessSwr])

  // ── 批量勾选 ──
  const toggleSelect = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }
  const toggleSelectSector = (stocks: BrowseStock[]) => {
    setSelected((prev) => {
      const next = new Set(prev)
      const codes = stocks.map((s) => s.code)
      const allSelected = codes.every((c) => next.has(c))
      codes.forEach((c) => allSelected ? next.delete(c) : next.add(c))
      return next
    })
  }

  // ── 批量操作 ──
  const batchAddWatch = async () => {
    if (selected.size === 0) return
    setToast(`加入 ${selected.size} 只到自选...`)
    let ok = 0, fail = 0
    for (const code of Array.from(selected)) {
      try {
        // 查找股票名（从 stocksSwr.data 缓存）
        const stock = findStockInData(stocksSwr.data, code)
        await apiPost("/api/holdings/watchlist", {
          stock_code: code,
          stock_name: stock?.name || code,
        })
        ok++
      } catch {
        fail++
      }
    }
    setToast(`加自选完成：✓ ${ok}${fail > 0 ? ` ✗ ${fail}` : ""}`)
  }

  const findStockInData = (data: BrowseStocksResponse | null, code: string): BrowseStock | undefined => {
    if (!data) return undefined
    for (const sec of data.sectors) {
      const found = sec.stocks.find((s) => s.code === code)
      if (found) return found
    }
    return undefined
  }

  const jumpToQuant = (code: string) => router.push(`/quant?code=${code}`)

  return (
    <>
      <SiteHeader title="股票浏览" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6 space-y-4">

          {/* ── 顶部：新鲜度仪表盘 + 操作按钮 ── */}
          <FreshnessBar data={freshnessSwr.data} onRefresh={freshnessSwr.refresh} syncing={syncing} syncProgress={syncProgress} onSync={startSync} />

          {/* ── 工具栏：搜索 + 过滤 ── */}
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="relative flex-1 min-w-[200px]">
                  <IconSearch className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                  <Input
                    placeholder="搜索代码或名称（如 600519 或 茅台）"
                    className="pl-8 h-8 text-xs"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <Select value={sector || "all"} onValueChange={(v) => setSector(v === "all" ? "" : v)}>
                  <SelectTrigger className="h-8 text-xs w-auto min-w-[120px]">
                    <SelectValue placeholder="全部板块" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部板块</SelectItem>
                    <SelectItem value="main_sh">沪深主板</SelectItem>
                    <SelectItem value="main_sz">深证主板</SelectItem>
                    <SelectItem value="gem">创业板</SelectItem>
                    <SelectItem value="star">科创板</SelectItem>
                    <SelectItem value="bse">北交所</SelectItem>
                    <SelectItem value="etf">ETF/基金</SelectItem>
                    <SelectItem value="index">指数</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={integrity || "all"} onValueChange={(v) => setIntegrity(v === "all" ? "" : v)}>
                  <SelectTrigger className="h-8 text-xs w-auto min-w-[110px]">
                    <SelectValue placeholder="全部状态" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部状态</SelectItem>
                    <SelectItem value="fresh">新鲜</SelectItem>
                    <SelectItem value="stale">滞后</SelectItem>
                    <SelectItem value="missing">缺失</SelectItem>
                  </SelectContent>
                </Select>
                <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => stocksSwr.refresh()}>
                  <IconRefresh className="size-3.5 mr-1" />刷新
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* ── 行业涨幅榜 ── */}
          {sectorPerfSwr.data && sectorPerfSwr.data.industries.length > 0 && (
            <SectorPerformanceBar data={sectorPerfSwr.data.industries} />
          )}

          {/* ── 批量操作栏 ── */}
          {selected.size > 0 && (
            <Card className="border-primary/50 bg-primary/5">
              <CardContent className="py-3 flex items-center gap-2">
                <span className="text-xs">已选 <strong>{selected.size}</strong> 只</span>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={batchAddWatch}>
                  <IconStar className="size-3 mr-1" />加自选
                </Button>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => alert("跳转到 AI 选股（TODO）")}>
                  <IconPlayerPlay className="size-3 mr-1" />加入扫描
                </Button>
                <Button size="sm" variant="ghost" className="h-7 text-xs ml-auto" onClick={() => setSelected(new Set())}>
                  清除选择
                </Button>
              </CardContent>
            </Card>
          )}

          {/* ── 板块分组列表 ── */}
          {stocksSwr.loading && !stocksSwr.data ? (
            <Skeleton className="h-64 w-full" />
          ) : stocksSwr.data?.sectors.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-sm text-muted-foreground">
                无匹配股票（试试调整搜索/板块/状态过滤）
              </CardContent>
            </Card>
          ) : (
            stocksSwr.data?.sectors.map((sec) => (
              <SectorCard
                key={sec.sector}
                sector={sec}
                collapsed={!!collapsed[sec.sector]}
                onToggleCollapse={() => setCollapsed((prev) => ({ ...prev, [sec.sector]: !prev[sec.sector] }))}
                sparklineCache={sparklineCache}
                selected={selected}
                onToggleSelect={toggleSelect}
                onToggleSelectAll={() => toggleSelectSector(sec.stocks)}
                onJump={jumpToQuant}
                onSyncSector={() => startSync("sector", sec.sector)}
              />
            ))
          )}

          {toast && (
            <div className="fixed bottom-4 right-4 z-50 bg-card border border-border rounded-md px-4 py-2 shadow-lg text-sm" onClick={() => setToast(null)}>
              {toast}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ════════════════════════════════════════════════════════════
//  Sub-components
// ════════════════════════════════════════════════════════════

function FreshnessBar({ data, onRefresh, syncing, syncProgress, onSync }: {
  data: FreshnessResponse | null
  onRefresh: () => void
  syncing: boolean
  syncProgress: SyncStatusResponse | null
  onSync: (scope: string) => void
}) {
  if (!data) {
    return <Skeleton className="h-20 w-full" />
  }
  return (
    <Card>
      <CardContent className="py-3 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-xs">
          <IconBuildingBank className="size-4 text-muted-foreground" />
          <span className="text-muted-foreground">数据新鲜度</span>
          <Badge variant="outline" className="text-[10px]">
            {data.total_stocks} 只股票
          </Badge>
        </div>
        <div className="flex items-center gap-2 flex-1">
          {data.sectors.map((s) => {
            const color = s.status === "fresh" ? "text-emerald-400" : s.status === "stale" ? "text-yellow-400" : "text-red-400"
            return (
              <TooltipProvider key={s.sector}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className={cn("flex items-center gap-1 px-2 py-0.5 rounded border border-border text-[10px] cursor-help", color)}>
                      <span>{s.label}</span>
                      <span className="font-mono text-muted-foreground">{s.days_ago ?? "?"}d</span>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="text-xs">
                    <div>{s.label}: {s.stock_count} 只 · 最新 {s.latest_date ?? "无"}</div>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )
          })}
        </div>
        {syncing && syncProgress ? (
          <div className="flex items-center gap-2 text-xs">
            <IconRefresh className="size-3 animate-spin" />
            <span>补齐中 {syncProgress.completed}/{syncProgress.total} ({syncProgress.percent}%)</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onSync("stale")}>
              <IconRefresh className="size-3 mr-1" />一键补齐滞后
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onRefresh}>
              <IconRefresh className="size-3" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SectorPerformanceBar({ data }: { data: SectorPerformanceResponse["industries"] }) {
  // 计算最大涨幅用于柱状比例
  const maxAbs = data.reduce((m, ind) => Math.max(m, Math.abs(ind.avg_change_pct ?? 0)), 0) || 1

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">行业涨幅榜 TOP 10</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className="p-2 text-left font-medium">行业</th>
                <th className="p-2 text-right font-medium w-16">股票数</th>
                <th className="p-2 text-right font-medium w-20">平均涨幅</th>
                <th className="p-2 text-center font-medium">柱状</th>
              </tr>
            </thead>
            <tbody>
              {data.slice(0, 10).map((ind) => {
                const pct = ind.avg_change_pct ?? 0
                const up = pct >= 0
                const barWidth = Math.min(Math.abs(pct) / maxAbs * 100, 100)
                return (
                  <tr key={ind.industry} className="border-t border-border/50 hover:bg-accent/30">
                    <td className="p-2 truncate max-w-[200px]" title={ind.industry}>
                      {ind.industry}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
                      {ind.stock_count}
                    </td>
                    <td className={cn(
                      "p-2 text-right font-mono tabular-nums font-semibold",
                      up ? "text-red-400" : "text-emerald-400"
                    )}>
                      {up ? "+" : ""}{pct.toFixed(2)}%
                    </td>
                    <td className="p-2">
                      <div className="h-2 bg-muted/30 rounded-full overflow-hidden">
                        <div
                          className={cn("h-full transition-all", up ? "bg-red-500/60" : "bg-emerald-500/60")}
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function SectorCard({ sector, collapsed, onToggleCollapse, sparklineCache, selected, onToggleSelect, onToggleSelectAll, onJump, onSyncSector }: {
  sector: BrowseSector
  collapsed: boolean
  onToggleCollapse: () => void
  sparklineCache: ReturnType<typeof useSparklineCache>
  selected: Set<string>
  onToggleSelect: (code: string) => void
  onToggleSelectAll: () => void
  onJump: (code: string) => void
  onSyncSector: () => void
}) {
  const allSelected = sector.stocks.length > 0 && sector.stocks.every((s) => selected.has(s.code))

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <button onClick={onToggleCollapse} className="flex items-center gap-2 hover:text-primary transition-colors">
            {collapsed ? <IconChevronDown className="size-4" /> : <IconChevronUp className="size-4" />}
            <CardTitle className="text-sm">{sector.label}</CardTitle>
            <Badge variant="outline" className="text-[10px]">{sector.total} 只</Badge>
            {sector.fresh_count > 0 && (
              <Badge variant="outline" className="text-[10px] border-emerald-500/50 text-emerald-400">
                ✓ {sector.fresh_pct}%
              </Badge>
            )}
            {sector.stale_count > 0 && (
              <Badge variant="outline" className="text-[10px] border-yellow-500/50 text-yellow-400">
                ⚠ {sector.stale_count} 滞后
              </Badge>
            )}
            {sector.missing_count > 0 && (
              <Badge variant="outline" className="text-[10px] border-red-500/50 text-red-400">
                ❌ {sector.missing_count} 缺失
              </Badge>
            )}
          </button>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onToggleSelectAll}>
              {allSelected ? "取消全选" : "全选"}
            </Button>
            {(sector.stale_count + sector.missing_count) > 0 && (
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onSyncSector}>
                <IconRefresh className="size-3 mr-1" />补齐此板块
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      {!collapsed && (
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-muted/50 sticky top-0">
                <tr>
                  <th className="p-2 w-8"></th>
                  <th className="p-2 text-left font-medium">代码</th>
                  <th className="p-2 text-left font-medium">名称</th>
                  <th className="p-2 text-left font-medium">行业</th>
                  <th className="p-2 text-right font-medium">最新价</th>
                  <th className="p-2 text-right font-medium">涨跌幅</th>
                  <th className="p-2 text-right font-medium">成交量</th>
                  <th className="p-2 text-center font-medium">完整性</th>
                  <th className="p-2 text-center font-medium w-32">60 日走势</th>
                  <th className="p-2 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {sector.stocks.map((s) => (
                  <BrowseRow
                    key={s.code}
                    stock={s}
                    isSelected={selected.has(s.code)}
                    onToggleSelect={() => onToggleSelect(s.code)}
                    sparklineCache={sparklineCache}
                    onJump={() => onJump(s.code)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

function BrowseRow({ stock, isSelected, onToggleSelect, sparklineCache, onJump }: {
  stock: BrowseStock
  isSelected: boolean
  onToggleSelect: () => void
  sparklineCache: ReturnType<typeof useSparklineCache> & { fetchOne: (code: string) => Promise<SparklineResponse | null> }
  onJump: () => void
}) {
  const badge = INTEGRITY_BADGE[stock.integrity]
  const BadgeIcon = badge.icon
  const change = stock.change_pct ?? 0
  const up = change >= 0

  // 懒加载 sparkline（每次进可视区才请求）
  useEffect(() => {
    if (!sparklineCache.get(stock.code)) {
      sparklineCache.fetchOne(stock.code).catch(() => {})
    }
  }, [stock.code, sparklineCache])

  return (
    <tr className={cn("border-t border-border/50 hover:bg-accent/30 transition-colors", isSelected && "bg-primary/10")}>
      <td className="p-2">
        <input type="checkbox" checked={isSelected} onChange={onToggleSelect} className="cursor-pointer" />
      </td>
      <td className="p-2 font-mono font-medium cursor-pointer hover:text-primary" onClick={onJump}>
        {stock.code}
      </td>
      <td className="p-2 truncate max-w-[100px]" title={stock.name}>{stock.name || "—"}</td>
      <td className="p-2 text-muted-foreground truncate max-w-[120px]" title={stock.industry}>{stock.industry || "—"}</td>
      <td className="p-2 text-right font-mono tabular-nums">
        {stock.latest_close != null ? stock.latest_close.toFixed(2) : "—"}
      </td>
      <td className={cn("p-2 text-right font-mono tabular-nums font-semibold", up ? "text-red-400" : "text-emerald-400")}>
        {up ? "+" : ""}{change.toFixed(2)}%
      </td>
      <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
        {stock.volume != null ? formatVolume(stock.volume) : "—"}
      </td>
      <td className="p-2 text-center">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className={cn("text-[10px] gap-1", badge.color)}>
                <BadgeIcon className="size-2.5" />
                {badge.label}
                {stock.days_ago != null && stock.days_ago > 0 && (
                  <span className="opacity-70">{stock.days_ago}d</span>
                )}
              </Badge>
            </TooltipTrigger>
            <TooltipContent className="text-xs">
              <div>最新数据: {stock.latest_date ?? "无"}</div>
              <div>K线数: {stock.kline_count}</div>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </td>
      <td className="p-2">
        <Sparkline code={stock.code} cache={sparklineCache as ReturnType<typeof useSparklineCache>} />
      </td>
      <td className="p-2 text-right">
        <Button size="sm" variant="ghost" className="h-6 text-[10px]" onClick={onJump}>
          <IconPlayerPlay className="size-3 mr-1" />分析
        </Button>
      </td>
    </tr>
  )
}

function Sparkline({ code, cache }: { code: string; cache: ReturnType<typeof useSparklineCache> & { fetchOne?: (code: string) => Promise<SparklineResponse | null> } }) {
  const data = cache.get(code)
  if (!data || data.closes.length < 2) {
    return <div className="h-8 w-32 bg-muted/30 rounded" />
  }
  const closes = data.closes
  const min = data.min
  const max = data.max
  const range = max - min || 1
  const W = 120, H = 32
  const step = W / (closes.length - 1)
  const points = closes.map((c: number, i: number) => `${(i * step).toFixed(1)},${(H - ((c - min) / range) * H).toFixed(1)}`).join(" ")
  const up = closes[closes.length - 1] >= closes[0]
  const color = up ? "#ef4444" : "#10b981"
  return (
    <svg width={W} height={H} className="block mx-auto">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  )
}

function formatVolume(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`
  return String(Math.round(v))
}

// ════════════════════════════════════════════════════════════
//  Data hooks (no SWR — keep it simple)
// ════════════════════════════════════════════════════════════

function useBrowseStocks(params: { sector: string; integrity: string; search: string }) {
  const [data, setData] = useState<BrowseStocksResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const refresh = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    const debounce = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const sp = new URLSearchParams()
        if (params.sector) sp.set("sector", params.sector)
        if (params.integrity) sp.set("integrity", params.integrity)
        if (params.search) sp.set("search", params.search)
        sp.set("limit", "5000")
        const r = await apiGet<BrowseStocksResponse>(`/api/data-ops/stocks?${sp}`)
        setData(r)
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载失败")
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => clearTimeout(debounce)
  }, [params.sector, params.integrity, params.search, tick])

  return { data, loading, error, refresh }
}

function useFreshness() {
  const [data, setData] = useState<FreshnessResponse | null>(null)
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    apiGet<FreshnessResponse>("/api/data-ops/freshness")
      .then(setData)
      .catch(() => {})
  }, [tick])

  return { data, refresh }
}

function useSectorPerformance() {
  const [data, setData] = useState<SectorPerformanceResponse | null>(null)
  useEffect(() => {
    apiGet<SectorPerformanceResponse>("/api/data-ops/sector-performance?top_n=10")
      .then(setData)
      .catch(() => {})
  }, [])
  return { data }
}

function useSparklineCache(): {
  get: (code: string) => SparklineResponse | undefined
  fetchOne: (code: string) => Promise<SparklineResponse | null>
} {
  const cache = useRef<Map<string, SparklineResponse>>(new Map())
  const [, setTick] = useState(0)

  const get = useCallback((code: string) => cache.current.get(code), [])

  useEffect(() => {
    // 占位: 实际在 BrowseRow 内按需懒加载
  }, [])

  return {
    get,
    fetchOne: useCallback(async (code: string) => {
      if (cache.current.has(code)) return cache.current.get(code) ?? null
      try {
        const r = await apiGet<SparklineResponse>(`/api/data-ops/sparkline/${code}?days=60`)
        cache.current.set(code, r)
        setTick((t) => t + 1)
        return r
      } catch {
        return null
      }
    }, []),
  }
}