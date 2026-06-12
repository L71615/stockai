"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconBrain, IconChevronDown, IconChevronRight, IconHistory } from "@tabler/icons-react"

interface Dimension {
  title: string
  score: string // "high" | "mid" | "low"
  summary: string
  detail: string
}

interface Suggestion {
  text: string
  reasoning: string
}

interface ReviewData {
  id?: number
  created_at?: string
  total_pnl?: number
  trade_count?: number
  avg_score?: number
  ai_headline?: string
  dimensions?: Dimension[]
  suggestions?: Suggestion[]
}

const SCORE_COLORS: Record<string, string> = {
  high: "text-red-500 border-red-500/20 bg-red-500/5",
  mid: "text-yellow-500 border-yellow-500/20 bg-yellow-500/5",
  low: "text-emerald-500 border-emerald-500/20 bg-emerald-500/5",
}

const SCORE_LABELS: Record<string, string> = { high: "优秀", mid: "一般", low: "需改进" }

export default function ReviewPage() {
  const router = useRouter()
  const [review, setReview] = useState<ReviewData | null>(null)
  const [history, setHistory] = useState<ReviewData[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [expandedDims, setExpandedDims] = useState<Set<number>>(new Set())
  const [showReasoning, setShowReasoning] = useState<Set<number>>(new Set())

  const fetchLatest = useCallback(async () => {
    try {
      const [revData, histData] = await Promise.all([
        apiGet<ReviewData[]>("/api/stocks/reviews?limit=1").then((d) => (Array.isArray(d) ? d[0] : null)),
        apiGet<ReviewData[]>("/api/stocks/reviews?limit=10"),
      ])
      setReview(revData || null)
      setHistory(Array.isArray(histData) ? histData : [])
    } catch { /* auth handled */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchLatest()
  }, [fetchLatest, router])

  const [genError, setGenError] = useState("")

  const generate = async () => {
    setGenerating(true); setGenError("")
    try {
      const data = await apiPost<ReviewData>("/api/stocks/review/structured", { report_type: "daily" })
      setReview(data)
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "生成失败，请确认已配置 AI Key")
    }
    finally { setGenerating(false) }
    // Refresh latest in background (no loading flash)
    try {
      const revs = await apiGet<ReviewData[]>("api/stocks/reviews?limit=10")
      if (Array.isArray(revs)) setHistory(revs)
    } catch { /* optional */ }
  }

  const loadReview = async (id: number) => {
    setLoading(true)
    try {
      const data = await apiGet<ReviewData>(`/api/stocks/reviews/${id}`)
      setReview(data)
    } catch { /* */ }
    finally { setLoading(false) }
  }

  const toggleDim = (i: number) => {
    const next = new Set(expandedDims)
    next.has(i) ? next.delete(i) : next.add(i)
    setExpandedDims(next)
  }

  const toggleReasoning = (i: number) => {
    const next = new Set(showReasoning)
    next.has(i) ? next.delete(i) : next.add(i)
    setShowReasoning(next)
  }

  return (
    <>
      <SiteHeader title="AI 复盘" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* Action bar */}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={generate} disabled={generating}>
            <IconBrain className="size-3.5 mr-1" />
            {generating ? "AI 分析中..." : "生成复盘报告"}
          </Button>
          {genError && <p className="text-xs text-red-500">{genError}</p>}
          {history.length > 0 && (
            <select
              className="h-8 rounded-none border border-input bg-background text-foreground px-2 text-xs"
              onChange={(e) => { const id = Number(e.target.value); if (id) loadReview(id) }}
              defaultValue=""
            >
              <option value="" disabled>历史报告</option>
              {history.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.created_at?.slice(0, 10)} · {h.trade_count || 0} 笔交易
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Loading */}
        {loading && (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}

        {/* Empty */}
        {!loading && !review && (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-4xl mb-2 opacity-40">🧠</p>
              <p className="text-sm text-muted-foreground">暂无复盘报告</p>
              <p className="text-xs text-muted-foreground mt-1">点击"生成复盘报告"，AI 将分析你的交易行为</p>
            </CardContent>
          </Card>
        )}

        {/* Review content */}
        {!loading && review && (
          <>
            {/* Hero stats */}
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="总盈亏" value={review.total_pnl ? `¥ ${review.total_pnl.toLocaleString()}` : "--"}
                className={review.total_pnl && review.total_pnl > 0 ? "text-red-500" : review.total_pnl && review.total_pnl < 0 ? "text-emerald-500" : ""} />
              <StatCard label="交易次数" value={review.trade_count?.toString() || "--"} />
              <StatCard label="综合评分" value={review.avg_score ? `${review.avg_score} 分` : "--"} />
            </div>

            {/* AI headline */}
            {review.ai_headline && (
              <Card className="border-l-[3px] border-l-purple-400">
                <CardContent className="py-3">
                  <p className="text-sm italic text-muted-foreground">
                    &ldquo;{review.ai_headline}&rdquo;
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Dimension panels */}
            {review.dimensions && review.dimensions.length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-sm">交易维度分析</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {review.dimensions.map((dim, i) => (
                    <div key={i} className="border border-border rounded-none">
                      <button
                        className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-accent/30 transition-colors"
                        onClick={() => toggleDim(i)}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{dim.title}</span>
                          <Badge variant="outline" className={cn("text-[10px]", SCORE_COLORS[dim.score] || "")}>
                            {SCORE_LABELS[dim.score] || dim.score}
                          </Badge>
                        </div>
                        {expandedDims.has(i) ? <IconChevronDown className="size-4" /> : <IconChevronRight className="size-4" />}
                      </button>
                      {expandedDims.has(i) && (
                        <div className="px-3 pb-3 space-y-1.5">
                          <p className="text-sm">{dim.summary}</p>
                          <p className="text-xs text-muted-foreground">{dim.detail}</p>
                        </div>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Suggestions */}
            {review.suggestions && review.suggestions.length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-sm">改进建议</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {review.suggestions.map((sug, i) => (
                    <div key={i} className="border border-border rounded-none p-3">
                      <p className="text-sm">{sug.text}</p>
                      <button
                        className="text-xs text-purple-400 hover:text-purple-300 mt-1.5"
                        onClick={() => toggleReasoning(i)}
                      >
                        {showReasoning.has(i) ? "收起理由" : "查看理由"}
                      </button>
                      {showReasoning.has(i) && (
                        <p className="text-xs text-muted-foreground mt-1 pl-2 border-l-2 border-purple-400/40">
                          {sug.reasoning}
                        </p>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </>
  )
}

function StatCard({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <Card>
      <CardContent className="py-3 text-center">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("text-lg font-semibold font-mono mt-0.5", className)}>{value}</p>
      </CardContent>
    </Card>
  )
}
