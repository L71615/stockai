"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconPlus, IconPencil, IconTrash, IconBrain } from "@tabler/icons-react"

interface Transaction {
  id: number; stock_code: string; stock_name: string; asset_type: string
  direction: string; price: number; quantity: number; amount: number; fee: number
  traded_at: string; note?: string
}

export default function TransactionsPage() {
  const router = useRouter()
  const [txns, setTxns] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [reviewText, setReviewText] = useState("")

  // Form fields
  const [code, setCode] = useState(""); const [name, setName] = useState(""); const [aType, setAType] = useState("stock")
  const [direction, setDirection] = useState("buy"); const [price, setPrice] = useState(""); const [qty, setQty] = useState("")
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10)); const [note, setNote] = useState("")
  const [fee, setFee] = useState(""); const [autoFee, setAutoFee] = useState(true)

  const fetchTxns = useCallback(async () => {
    try {
      const data = await apiGet<Transaction[]>("/api/stocks/transactions")
      setTxns(Array.isArray(data) ? data : [])
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchTxns()
  }, [fetchTxns, router])

  const totalBuy = txns.filter((t) => t.direction === "buy").reduce((s, t) => s + (t.amount || t.price * t.quantity), 0)
  const totalSell = txns.filter((t) => t.direction === "sell").reduce((s, t) => s + (t.amount || t.price * t.quantity), 0)
  const totalFee = txns.reduce((s, t) => s + (t.fee || 0), 0)
  const buyCount = txns.filter((t) => t.direction === "buy").length
  const sellCount = txns.filter((t) => t.direction === "sell").length

  const resetForm = () => { setCode(""); setName(""); setPrice(""); setQty(""); setNote(""); setFee(""); setAutoFee(true); setEditId(null); setShowForm(false) }

  const submit = async () => {
    const body: Record<string, unknown> = { stock_code: code, stock_name: name, asset_type: aType, direction, price: Number(price), quantity: Number(qty), traded_at: date, note }
    if (!autoFee && fee) body.fee = Number(fee)
    if (editId) {
      await apiPost(`/api/stocks/transactions/${editId}`, body, "PUT")
    } else {
      await apiPost("/api/stocks/transactions", body)
    }
    resetForm(); fetchTxns()
  }

  const startEdit = (t: Transaction) => {
    setEditId(t.id); setCode(t.stock_code); setName(t.stock_name); setAType(t.asset_type || "stock")
    setDirection(t.direction); setPrice(String(t.price)); setQty(String(t.quantity))
    setDate(t.traded_at?.slice(0, 10) || ""); setNote(t.note || "")
    setFee(t.fee ? String(t.fee) : ""); setAutoFee(!t.fee); setShowForm(true)
  }

  const deleteTxn = async (id: number) => {
    if (!confirm("确认删除？")) return
    try {
      await apiPost(`/api/stocks/transactions/${id}`, {}, "DELETE")
      fetchTxns()
    } catch (err) {
      alert("删除失败：" + (err instanceof Error ? err.message : "未知错误"))
    }
  }

  const aiReview = async () => {
    setReviewText("AI 分析中...")
    try {
      const data = await apiPost<{ report?: string }>("/api/stocks/review", { report_type: "daily" })
      setReviewText(data.report || JSON.stringify(data))
    } catch (err) { setReviewText(err instanceof Error ? err.message : "失败") }
  }

  return (
    <>
      <SiteHeader title="交易记录" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* KPI row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <StatCard label="总交易" value={`${txns.length}`} sub={`${buyCount} 买 · ${sellCount} 卖`} />
          <StatCard label="总买入" value={`¥ ${totalBuy.toLocaleString()}`} className="text-red-500" />
          <StatCard label="总卖出" value={`¥ ${totalSell.toLocaleString()}`} className="text-emerald-500" />
          <StatCard label="净额" value={`¥ ${(totalSell - totalBuy).toLocaleString()}`} className={totalSell - totalBuy >= 0 ? "text-red-500" : "text-emerald-500"} />
          <StatCard label="总佣金" value={`¥ ${totalFee.toLocaleString()}`} sub={`${txns.filter(t => t.fee > 0).length} 笔含佣金`} className="text-orange-400" />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => { resetForm(); setShowForm(!showForm) }}>
            <IconPlus className="size-3.5 mr-1" />{showForm ? "收起" : "添加交易"}
          </Button>
          <Button size="sm" variant="outline" onClick={aiReview}>
            <IconBrain className="size-3.5 mr-1" />AI 复盘
          </Button>
        </div>

        {/* Add/Edit form */}
        {showForm && (
          <Card>
            <CardContent className="pt-4">
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 items-end">
                <div className="space-y-1">
                  <Label className="text-xs">代码</Label>
                  <Input value={code} onChange={(e) => setCode(e.target.value)} className="h-8 font-mono" placeholder="000001" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">名称</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">类型</Label>
                  <select value={aType} onChange={(e) => setAType(e.target.value)} className="h-8 w-full rounded-none border border-input bg-background text-foreground px-2 text-xs">
                    <option value="stock">股票</option><option value="etf">ETF</option><option value="fund">基金</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">方向</Label>
                  <select value={direction} onChange={(e) => setDirection(e.target.value)} className="h-8 w-full rounded-none border border-input bg-background text-foreground px-2 text-xs">
                    <option value="buy">买入</option><option value="sell">卖出</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">价格</Label>
                  <Input value={price} onChange={(e) => setPrice(e.target.value)} className="h-8 font-mono" type="number" step="0.01" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">数量</Label>
                  <Input value={qty} onChange={(e) => setQty(e.target.value)} className="h-8 font-mono" type="number" />
                </div>
                <div className="flex gap-1 items-end">
                  <Button size="sm" onClick={submit}>{editId ? "更新" : "添加"}</Button>
                  <Button size="sm" variant="ghost" onClick={resetForm}>取消</Button>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 mt-2 items-end">
                <div className="space-y-1">
                  <Label className="text-xs">日期</Label>
                  <Input value={date} onChange={(e) => setDate(e.target.value)} className="h-8 w-36" type="date" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">佣金</Label>
                  <div className="flex items-center gap-1">
                    <Input
                      value={autoFee ? "自动计算" : fee}
                      onChange={(e) => setFee(e.target.value)}
                      className="h-8 w-28 font-mono"
                      type={autoFee ? "text" : "number"}
                      step="0.01"
                      disabled={autoFee}
                      placeholder="0.00"
                    />
                    <button
                      type="button"
                      onClick={() => setAutoFee(!autoFee)}
                      className={`text-[10px] px-1.5 py-0.5 rounded-none border whitespace-nowrap transition-colors ${
                        autoFee ? "bg-primary text-primary-foreground border-primary" : "bg-muted text-muted-foreground border-input"
                      }`}
                    >
                      {autoFee ? "自动" : "手动"}
                    </button>
                  </div>
                </div>
                <div className="space-y-1 flex-1 min-w-[120px]">
                  <Label className="text-xs">备注</Label>
                  <Input value={note} onChange={(e) => setNote(e.target.value)} className="h-8" placeholder="可选" />
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* AI Review */}
        {reviewText && (
          <Card className="border-l-[3px] border-l-purple-400">
            <CardContent className="py-3">
              <p className="text-xs font-medium text-purple-400 mb-1">AI 复盘分析</p>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">{reviewText}</p>
            </CardContent>
          </Card>
        )}

        {/* Table */}
        <Card>
          <CardContent className="p-0">
            {loading ? (
              <div className="p-4 space-y-2"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
            ) : txns.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">暂无交易记录，点击"添加交易"</p>
            ) : (
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full text-xs">
                  <thead className="bg-muted sticky top-0">
                    <tr>
                      <th className="text-left p-2 font-medium">日期</th>
                      <th className="text-left p-2 font-medium">股票</th>
                      <th className="text-center p-2 font-medium">方向</th>
                      <th className="text-right p-2 font-medium">价格</th>
                      <th className="text-right p-2 font-medium">数量</th>
                      <th className="text-right p-2 font-medium">金额</th>
                      <th className="text-right p-2 font-medium">佣金</th>
                      <th className="text-left p-2 font-medium">备注</th>
                      <th className="text-right p-2 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txns.map((t) => (
                      <tr key={t.id} className="border-t border-border hover:bg-accent/30 transition-colors">
                        <td className="p-2 text-muted-foreground">{t.traded_at?.slice(0, 10)}</td>
                        <td className="p-2">
                          <span className="font-mono text-muted-foreground">{t.stock_code}</span>
                          <span className="ml-1.5">{t.stock_name}</span>
                        </td>
                        <td className="p-2 text-center">
                          <Badge className={cn("text-[10px]", t.direction === "buy" ? "bg-red-500/10 text-red-500 border-red-500/20" : "bg-emerald-500/10 text-emerald-500 border-emerald-500/20")} variant="outline">
                            {t.direction === "buy" ? "买入" : "卖出"}
                          </Badge>
                        </td>
                        <td className="p-2 text-right font-mono">¥ {t.price?.toFixed(2)}</td>
                        <td className="p-2 text-right font-mono">{t.quantity}</td>
                        <td className="p-2 text-right font-mono">¥ {(t.amount || t.price * t.quantity).toLocaleString()}</td>
                        <td className="p-2 text-right font-mono text-muted-foreground">{t.fee > 0 ? `¥ ${t.fee.toFixed(2)}` : "—"}</td>
                        <td className="p-2 text-muted-foreground max-w-32 truncate">{t.note || ""}</td>
                        <td className="p-2 text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button variant="ghost" size="icon" className="size-6" onClick={() => startEdit(t)}>
                              <IconPencil className="size-3" />
                            </Button>
                            <Button variant="ghost" size="icon" className="size-6" onClick={() => deleteTxn(t.id)}>
                              <IconTrash className="size-3" />
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
      </div>
    </>
  )
}

function StatCard({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return (
    <Card>
      <CardContent className="py-3 text-center">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("text-lg font-semibold font-mono mt-0.5", className)}>{value}</p>
        {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
      </CardContent>
    </Card>
  )
}
