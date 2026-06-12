"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconPlus, IconTrash, IconRefresh, IconRobot, IconUser } from "@tabler/icons-react"

interface KOLAccount {
  id: number
  username: string
  display_name?: string
  category?: string
  is_active: boolean
}

interface BriefData {
  brief_date?: string
  summary?: string
  account_count?: number
  post_count?: number
  sentiment?: { bullish: number; bearish: number; neutral: number }
  topics?: { topic: string; sentiment: string }[]
  bull_case?: string
  bear_case?: string
  stocks_mentioned?: { code: string; name: string }[]
  notable_quotes?: { text: string; author: string; why_notable: string }[]
  full_text?: string
}

const CATEGORIES = ["宏观", "行业", "个股", "加密货币", "量化"]

export default function KolPage() {
  const router = useRouter()
  const [accounts, setAccounts] = useState<KOLAccount[]>([])
  const [brief, setBrief] = useState<BriefData | null>(null)
  const [loading, setLoading] = useState(true)
  const [briefLoading, setBriefLoading] = useState(true)
  const [crawling, setCrawling] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [newUser, setNewUser] = useState("")
  const [newName, setNewName] = useState("")
  const [newCat, setNewCat] = useState("宏观")

  const fetchData = useCallback(async () => {
    try {
      const [accs, briefData] = await Promise.all([
        apiGet<KOLAccount[]>("/api/kol/accounts"),
        apiGet<BriefData>("/api/kol/briefs/latest").catch(() => null),
      ])
      setAccounts(Array.isArray(accs) ? accs : [])
      setBrief(briefData)
    } catch { /* auth handled by apiGet */ }
    finally { setLoading(false); setBriefLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchData()
  }, [fetchData, router])

  const addAccount = async () => {
    if (!newUser.trim()) return
    await apiPost("/api/kol/accounts", { username: newUser.trim(), display_name: newName.trim(), category: newCat })
    setNewUser(""); setNewName(""); setShowAdd(false)
    fetchData()
  }

  const deleteAccount = async (id: number) => {
    await apiPost(`/api/kol/accounts/${id}`, {}, "DELETE")
    fetchData()
  }

  const crawl = async () => {
    setCrawling(true)
    await apiPost("/api/kol/crawl", {})
    setCrawling(false)
    fetchData()
  }

  const genBrief = async () => {
    setBriefLoading(true)
    await apiPost("/api/kol/briefs/generate", {})
    setTimeout(fetchData, 3000)
  }

  return (
    <>
      <SiteHeader title="大佬观点" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* Action bar */}
        <div className="flex items-center gap-2 flex-wrap">
          <Button size="sm" onClick={crawl} disabled={crawling}>
            <IconRefresh className={cn("size-3.5 mr-1", crawling && "animate-spin")} />
            {crawling ? "抓取中..." : "刷新帖子"}
          </Button>
          <Button size="sm" variant="outline" onClick={genBrief} disabled={briefLoading}>
            <IconRobot className="size-3.5 mr-1" />
            生成日报
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowAdd(!showAdd)}>
            <IconPlus className="size-3.5 mr-1" />
            添加账号
          </Button>
        </div>

        {/* Accounts bar */}
        {loading ? (
          <Skeleton className="h-8 w-full" />
        ) : (
          <div className="flex flex-wrap gap-1.5 items-center">
            {accounts.map((a) => (
              <Badge key={a.id} variant="outline" className={cn("gap-1 pr-1", !a.is_active && "line-through opacity-60")}>
                <IconUser className="size-3" />@{a.username}
                {a.display_name && <span className="text-muted-foreground">({a.display_name})</span>}
                <button onClick={() => deleteAccount(a.id)} className="ml-0.5 hover:text-red-500">
                  <IconTrash className="size-3" />
                </button>
              </Badge>
            ))}
            {accounts.length === 0 && <span className="text-xs text-muted-foreground">暂无追踪账号，点击"添加账号"</span>}
          </div>
        )}

        {/* Add account form */}
        {showAdd && (
          <Card>
            <CardContent className="pt-4">
              <div className="flex gap-2 items-end flex-wrap">
                <div className="space-y-1">
                  <Label className="text-xs">X 用户名</Label>
                  <Input value={newUser} onChange={(e) => setNewUser(e.target.value)} placeholder="username (不含@)" className="h-8 w-36" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">显示名</Label>
                  <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="可选" className="h-8 w-28" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">分类</Label>
                  <select value={newCat} onChange={(e) => setNewCat(e.target.value)} className="h-8 rounded-none border border-input bg-background text-foreground px-2 text-xs">
                    {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <Button size="sm" onClick={addAccount}>添加</Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Daily Brief */}
        {briefLoading ? (
          <Card>
            <CardContent className="py-8 space-y-3">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-3/4" />
            </CardContent>
          </Card>
        ) : brief?.summary ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <IconRobot className="size-4 text-purple-400" />
                <span>今日观点日报</span>
              </CardTitle>
              <CardDescription>
                {brief.brief_date} · {brief.account_count || 0} 位大佬 · {brief.post_count || 0} 条帖子
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* One-liner */}
              <p className="text-sm font-medium">{brief.summary}</p>

              {/* Sentiment bar */}
              {brief.sentiment && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-red-500">🐂 {brief.sentiment.bullish}%</span>
                  <div className="flex-1 h-2 bg-muted rounded-none overflow-hidden flex">
                    <div className="h-full bg-red-500/60" style={{ width: `${brief.sentiment.bullish}%` }} />
                    <div className="h-full bg-muted-foreground/30" style={{ width: `${brief.sentiment.neutral}%` }} />
                    <div className="h-full bg-emerald-500/60" style={{ width: `${brief.sentiment.bearish}%` }} />
                  </div>
                  <span className="text-emerald-500">🐻 {brief.sentiment.bearish}%</span>
                </div>
              )}

              {/* Topics */}
              {brief.topics && brief.topics.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {brief.topics.map((t, i) => (
                    <Badge key={i} variant="secondary" className={cn(
                      "text-[10px]",
                      t.sentiment === "bullish" && "text-red-500",
                      t.sentiment === "bearish" && "text-emerald-500"
                    )}>{t.topic}</Badge>
                  ))}
                </div>
              )}

              {/* Bull/Bear cases */}
              {(brief.bull_case || brief.bear_case) && (
                <div className="grid grid-cols-2 gap-3">
                  {brief.bull_case && (
                    <div className="p-3 bg-red-500/5 border border-red-500/10 rounded-none">
                      <p className="text-xs font-medium text-red-500 mb-1">🐂 看涨观点</p>
                      <p className="text-xs text-muted-foreground">{brief.bull_case}</p>
                    </div>
                  )}
                  {brief.bear_case && (
                    <div className="p-3 bg-emerald-500/5 border border-emerald-500/10 rounded-none">
                      <p className="text-xs font-medium text-emerald-500 mb-1">🐻 看跌观点</p>
                      <p className="text-xs text-muted-foreground">{brief.bear_case}</p>
                    </div>
                  )}
                </div>
              )}

              {/* Mentioned stocks */}
              {brief.stocks_mentioned && brief.stocks_mentioned.length > 0 && (
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground">提及股票:</span>
                  {brief.stocks_mentioned.map((s, i) => (
                    <Badge key={i} variant="outline" className="font-mono cursor-pointer hover:bg-accent"
                      onClick={() => router.push(`/quant?code=${s.code}`)}>
                      {s.code} {s.name}
                    </Badge>
                  ))}
                </div>
              )}

              {/* Notable quotes */}
              {brief.notable_quotes && brief.notable_quotes.length > 0 && (
                <div className="space-y-2">
                  <Separator />
                  {brief.notable_quotes.map((q, i) => (
                    <div key={i} className="pl-3 border-l-2 border-purple-400/40">
                      <p className="text-sm italic">"{q.text}"</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        — @{q.author} · {q.why_notable}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-4xl mb-2 opacity-40">🤖</p>
              <p className="text-sm text-muted-foreground">暂无日报</p>
              <p className="text-xs text-muted-foreground mt-1">点击"生成日报"让 AI 分析追踪账号的观点</p>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  )
}
