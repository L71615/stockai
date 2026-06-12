"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconPlus, IconTrash, IconChartBar, IconFolderPlus } from "@tabler/icons-react"

interface WatchItem {
  id: number; stock_code: string; stock_name: string; market: string; asset_type: string
  price?: number; name?: string; change?: number; change_pct?: number
  volume?: number; high?: number; low?: number
}

export default function WatchlistPage() {
  const router = useRouter()
  const [items, setItems] = useState<WatchItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [code, setCode] = useState(""); const [name, setName] = useState("")
  const [market, setMarket] = useState("SH"); const [aType, setAType] = useState("auto")
  const [lookingUp, setLookingUp] = useState(false)
  const [lookupError, setLookupError] = useState("")
  const [addError, setAddError] = useState("")
  const lookupTimer = useRef<ReturnType<typeof setTimeout>>(null)

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null)

  // Add-to-holdings form (replaces prompt())
  const [addHoldingItem, setAddHoldingItem] = useState<WatchItem | null>(null)
  const [addQty, setAddQty] = useState("")
  const [addCost, setAddCost] = useState("")
  const [addHoldingError, setAddHoldingError] = useState("")

  const fetchWatchlist = useCallback(async () => {
    try {
      const data = await apiGet<WatchItem[]>("/api/stocks/watchlist")
      const list = Array.isArray(data) ? data : []
      if (list.length > 0) {
        try {
          const codes = list.map((i) => i.stock_code)
          const markets = list.map((i) => i.market || "SH")
          const types = list.map((i) => i.asset_type || "stock")
          const quotes = await apiPost<(WatchItem & { code?: string; error?: string })[]>("/api/stocks/quotes", { codes, markets, asset_types: types })
          if (Array.isArray(quotes)) {
            const valid = quotes.filter((q) => !q.error)
            const qmap = new Map(valid.map((q) => [(q as { code?: string }).code || q.stock_code, q]))
            list.forEach((item) => {
              const q = qmap.get(item.stock_code)
              if (q) {
                if (q.price != null) item.price = q.price
                if (q.change != null) item.change = q.change
                if (q.change_pct != null) item.change_pct = q.change_pct
                if (q.volume != null) item.volume = q.volume
                if (q.high != null) item.high = q.high
                if (q.low != null) item.low = q.low
              }
            })
          }
        } catch { /* quotes optional */ }
      }
      setItems(list)
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchWatchlist()
    const timer = setInterval(fetchWatchlist, 30000)
    return () => clearInterval(timer)
  }, [fetchWatchlist, router])

  const lookup = async (c: string) => {
    if (!c.trim()) { setLookupError(""); return }
    setLookingUp(true)
    setLookupError("")
    try {
      const data = await apiGet<{ name: string; type: string }>(`/api/stocks/lookup/${c.trim()}`)
      setName(data.name || "")
      const t = data.type || "stock"
      setAType(t === "etf" ? "etf" : t === "fund" ? "fund" : "stock")
      // Autodetect market
      if (c.startsWith("5") || c.startsWith("6")) setMarket("SH")
      else if (c.startsWith("0") || c.startsWith("3")) setMarket("SZ")
      else if (c.startsWith("4") || c.startsWith("8")) setMarket("BJ")
    } catch (err) {
      setName("")
      setLookupError(err instanceof Error ? err.message : "未找到该代码")
    }
    finally { setLookingUp(false) }
  }

  const onCodeChange = (v: string) => {
    setCode(v)
    setLookupError("")
    if (lookupTimer.current) clearTimeout(lookupTimer.current)
    lookupTimer.current = setTimeout(() => lookup(v), 500)
  }

  const add = async () => {
    setAddError("")
    if (!code.trim()) { setAddError("请输入股票代码"); return }
    if (!name.trim()) { setAddError("请输入股票名称或等待自动查询"); return }
    try {
      await apiPost("/api/stocks/watchlist", {
        stock_code: code.trim(), stock_name: name.trim(), market, asset_type: aType === "auto" ? "stock" : aType
      })
      setCode(""); setName(""); setShowAdd(false); setAddError("")
      fetchWatchlist()
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "添加失败")
    }
  }

  const confirmDelete = (item: WatchItem) => {
    setDeleteTarget({ id: item.id, name: `${item.stock_code} ${item.stock_name || item.name}` })
  }

  const executeDelete = async () => {
    if (!deleteTarget) return
    await apiPost(`/api/stocks/watchlist/${deleteTarget.id}`, {}, "DELETE")
    setDeleteTarget(null)
    fetchWatchlist()
  }

  const openAddHolding = (item: WatchItem) => {
    setAddHoldingItem(item)
    setAddQty("")
    setAddCost("")
    setAddHoldingError("")
  }

  const submitAddHolding = async () => {
    if (!addHoldingItem) return
    setAddHoldingError("")
    const qty = Number(addQty)
    const cost = Number(addCost)
    if (!qty || qty <= 0) { setAddHoldingError("请输入有效数量"); return }
    if (!cost || cost <= 0) { setAddHoldingError("请输入有效成本价"); return }
    try {
      await apiPost("/api/stocks/holdings", {
        stock_code: addHoldingItem.stock_code, stock_name: addHoldingItem.stock_name,
        market: addHoldingItem.market, asset_type: addHoldingItem.asset_type,
        quantity: qty, cost_price: cost,
      })
      setAddHoldingItem(null)
      router.push("/")
    } catch (err) {
      setAddHoldingError(err instanceof Error ? err.message : "添加失败")
    }
  }

  const decimals = (item: WatchItem) => {
    if (item.asset_type === "fund") return 4
    if (item.asset_type === "etf") return 3
    return 2
  }

  return (
    <>
      <SiteHeader title="自选股" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => { setShowAdd(!showAdd); setAddError("") }}>
            <IconPlus className="size-3.5 mr-1" />{showAdd ? "收起" : "添加自选"}
          </Button>
        </div>

        {showAdd && (
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-end gap-2 flex-wrap">
                <div className="space-y-1">
                  <Label className="text-xs">代码</Label>
                  <Input value={code} onChange={(e) => onCodeChange(e.target.value)} className="h-8 w-28 font-mono" placeholder="000001" />
                  {lookupError && <p className="text-[10px] text-red-500">{lookupError}</p>}
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">名称 {lookingUp && "查询中..."}</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 w-28" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">市场</Label>
                  <select value={market} onChange={(e) => setMarket(e.target.value)} className="h-8 rounded-none border border-input bg-background text-foreground px-2 text-xs">
                    <option value="SH">上海</option><option value="SZ">深圳</option><option value="BJ">北京</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">类型</Label>
                  <select value={aType} onChange={(e) => setAType(e.target.value)} className="h-8 rounded-none border border-input bg-background text-foreground px-2 text-xs">
                    <option value="auto">自动</option><option value="stock">股票</option><option value="etf">ETF</option><option value="fund">基金</option>
                  </select>
                </div>
                <Button size="sm" onClick={add} disabled={lookingUp}>添加</Button>
              </div>
              {addError && <p className="text-xs text-red-500 mt-2">{addError}</p>}
            </CardContent>
          </Card>
        )}

        {/* Add to Holdings form */}
        {addHoldingItem && (
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm font-medium mb-2">
                加入持仓：{addHoldingItem.stock_code} {addHoldingItem.stock_name}
              </p>
              <div className="flex items-end gap-2 flex-wrap">
                <div className="space-y-1">
                  <Label className="text-xs">数量{addHoldingItem.asset_type === "fund" ? "(份)" : "(股)"}</Label>
                  <Input value={addQty} onChange={(e) => setAddQty(e.target.value)} className="h-8 w-28 font-mono" type="number" step="1" autoFocus />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">成本价</Label>
                  <Input value={addCost} onChange={(e) => setAddCost(e.target.value)} className="h-8 w-28 font-mono" type="number" step="0.001" />
                </div>
                <Button size="sm" onClick={submitAddHolding}>确认添加</Button>
                <Button size="sm" variant="ghost" onClick={() => { setAddHoldingItem(null); setAddHoldingError("") }}>取消</Button>
              </div>
              {addHoldingError && <p className="text-xs text-red-500 mt-2">{addHoldingError}</p>}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="p-0">
            {loading ? (
              <div className="p-4 space-y-2"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
            ) : items.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">暂无自选股，点击"添加自选"</p>
            ) : (
              <div className="overflow-auto max-h-[600px]">
                <table className="w-full text-xs">
                  <thead className="bg-muted sticky top-0">
                    <tr>
                      <th className="text-left p-2 font-medium">股票</th>
                      <th className="text-right p-2 font-medium">现价</th>
                      <th className="text-right p-2 font-medium">涨跌幅</th>
                      <th className="text-right p-2 font-medium">涨跌额</th>
                      <th className="text-right p-2 font-medium">成交量</th>
                      <th className="text-right p-2 font-medium">最高</th>
                      <th className="text-right p-2 font-medium">最低</th>
                      <th className="text-right p-2 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const isUp = (item.change_pct || 0) > 0
                      const isDown = (item.change_pct || 0) < 0
                      const colorClass = isUp ? "text-red-500" : isDown ? "text-emerald-500" : ""
                      return (
                        <tr key={item.id} className="border-t border-border hover:bg-accent/30 transition-colors">
                          <td className="p-2">
                            <span className="font-mono text-muted-foreground">{item.stock_code}</span>
                            <span className="ml-1.5">{item.stock_name || item.name}</span>
                            {item.asset_type && item.asset_type !== "stock" && item.asset_type !== "auto" && (
                              <Badge variant="outline" className="ml-1 text-[10px]">{item.asset_type.toUpperCase()}</Badge>
                            )}
                            <Badge variant="secondary" className="ml-1 text-[10px]">{item.market}</Badge>
                          </td>
                          <td className={cn("p-2 text-right font-mono tabular-nums", colorClass)}>
                            {item.price != null ? Number(item.price).toFixed(decimals(item)) : "--"}
                          </td>
                          <td className={cn("p-2 text-right font-mono tabular-nums", colorClass)}>
                            {item.change_pct != null ? `${item.change_pct >= 0 ? "+" : ""}${Number(item.change_pct).toFixed(2)}%` : "--"}
                          </td>
                          <td className={cn("p-2 text-right font-mono tabular-nums", colorClass)}>
                            {item.change != null ? `${item.change >= 0 ? "+" : ""}${Number(item.change).toFixed(decimals(item))}` : "--"}
                          </td>
                          <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
                            {item.volume != null ? `${(Number(item.volume) / 10000).toFixed(0)}万` : "--"}
                          </td>
                          <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
                            {item.high != null ? Number(item.high).toFixed(decimals(item)) : "--"}
                          </td>
                          <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">
                            {item.low != null ? Number(item.low).toFixed(decimals(item)) : "--"}
                          </td>
                          <td className="p-2 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button variant="ghost" size="icon" className="size-6" onClick={() => openAddHolding(item)} title="加入持仓">
                                <IconFolderPlus className="size-3" />
                              </Button>
                              <Button variant="ghost" size="icon" className="size-6" onClick={() => router.push(`/quant?code=${item.stock_code}`)} title="分析">
                                <IconChartBar className="size-3" />
                              </Button>
                              <Button variant="ghost" size="icon" className="size-6" onClick={() => confirmDelete(item)}>
                                <IconTrash className="size-3" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Delete confirmation dialog */}
        <AlertDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认移除</AlertDialogTitle>
              <AlertDialogDescription>
                确定要从自选股中移除 <span className="font-mono font-medium text-foreground">{deleteTarget?.name}</span> 吗？
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction onClick={executeDelete} className="bg-red-500 hover:bg-red-600">移除</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </>
  )
}
