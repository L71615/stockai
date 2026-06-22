"use client"

import { useState, useCallback, useEffect } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost } from "@/lib/auth"
import { IconBrain, IconRefresh, IconFlame, IconNews } from "@tabler/icons-react"
import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"

interface XueqiuItem {
  code: string; name: string; follow_count: number; price: number
}

interface RSSItem {
  source: string; title: string; link: string; published: string
}

// ═══════════════════════════════════════════════════════════
// 雪球热门 — 独立 SWR 模块
// ═══════════════════════════════════════════════════════════
function XueqiuSection() {
  const { data, isLoading, isValidating, mutate } = useSWR<{ items: XueqiuItem[] }>(
    "/api/kol/xueqiu", swrFetcher, { dedupingInterval: 60000, revalidateOnFocus: false }
  )
  const items = data?.items || []

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm flex items-center gap-2">
              <IconFlame className="size-4 text-orange-400" />
              雪球热门关注
            </CardTitle>
            <CardDescription>社区热度最高的股票（akshare → 雪球）</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={() => mutate()} disabled={isValidating}>
            <IconRefresh className={isValidating ? "animate-spin size-3" : "size-3"} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2"><Skeleton className="h-6 w-full" /><Skeleton className="h-6 w-full" /><Skeleton className="h-6 w-full" /></div>
        ) : items.length > 0 ? (
          <div className="space-y-1">
            {items.slice(0, 10).map((item, i) => (
              <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-border/30 last:border-0">
                <div>
                  <span className="font-mono">{item.code}</span>
                  <span className="ml-2">{item.name}</span>
                </div>
                <div className="flex items-center gap-3 text-muted-foreground">
                  <span>¥{item.price?.toFixed(2)}</span>
                  <Badge variant="secondary" className="text-[10px]">
                    {item.follow_count?.toLocaleString()} 关注
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">暂无数据（需 akshare 库可用）</p>
        )}
      </CardContent>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════
// 财经快讯 — 独立 SWR 模块
// ═══════════════════════════════════════════════════════════
function RSSSection() {
  const { data, isLoading, isValidating, mutate } = useSWR<{ items: RSSItem[] }>(
    "/api/kol/rss", swrFetcher, { dedupingInterval: 60000, revalidateOnFocus: false }
  )
  const items = data?.items || []

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm flex items-center gap-2">
              <IconNews className="size-4 text-blue-400" />
              财经快讯
            </CardTitle>
            <CardDescription>华尔街见闻 + 东方财富 RSS</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={() => mutate()} disabled={isValidating}>
            <IconRefresh className={isValidating ? "animate-spin size-3" : "size-3"} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2"><Skeleton className="h-6 w-full" /><Skeleton className="h-6 w-full" /><Skeleton className="h-6 w-full" /></div>
        ) : items.length > 0 ? (
          <div className="space-y-1">
            {items.map((item, i) => (
              <div key={i} className="text-xs py-1.5 border-b border-border/30 last:border-0">
                {item.link ? (
                  <a href={item.link} target="_blank" className="hover:underline text-foreground block">{item.title}</a>
                ) : (
                  <span className="text-muted-foreground">{item.title}</span>
                )}
                <div className="flex items-center gap-2 mt-0.5 text-muted-foreground">
                  {item.source !== "error" && <Badge variant="outline" className="text-[10px]">{item.source}</Badge>}
                  {item.published && <span>{item.published}</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            暂无数据。RSS 源可能不可达，或需安装 feedparser：pip install feedparser
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════
// 主页面 — AI 摘要单独刷新
// ═══════════════════════════════════════════════════════════
export default function KolPage() {
  const router = useRouter()
  const [brief, setBrief] = useState("")
  const [generatedAt, setGeneratedAt] = useState("")
  const [briefLoading, setBriefLoading] = useState(true)
  const [briefRefreshing, setBriefRefreshing] = useState(false)

  const fetchBrief = useCallback(async () => {
    try {
      const result = await apiGet<{ brief: string; generated_at: string }>("/api/kol/briefs/latest")
      if (result?.brief) {
        setBrief(result.brief)
        setGeneratedAt(result.generated_at || "")
      }
    } catch { /* */ }
    finally { setBriefLoading(false) }
  }, [])

  // 首次加载
  useEffect(() => {
    fetchBrief()
  }, [fetchBrief, router])

  const refreshBrief = async () => {
    setBriefRefreshing(true)
    try {
      await apiPost("/api/kol/briefs/generate", {})
      await fetchBrief()
    } catch { /* */ }
    finally { setBriefRefreshing(false) }
  }

  return (
    <>
      <SiteHeader title="大佬观点" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">

        {/* AI 摘要 */}
        <Card className="border-l-[3px] border-l-purple-400">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <IconBrain className="size-4 text-purple-400" />
                AI 观点摘要
              </CardTitle>
              <Button size="sm" variant="outline" onClick={refreshBrief} disabled={briefRefreshing}>
                <IconRefresh className={briefRefreshing ? "animate-spin size-3.5 mr-1" : "size-3.5 mr-1"} />
                {briefRefreshing ? "生成中..." : "生成日报"}
              </Button>
            </div>
            {generatedAt && <CardDescription>更新于 {generatedAt}</CardDescription>}
          </CardHeader>
          <CardContent>
            {briefLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : brief && brief !== "📭 暂无日报" ? (
              <div className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground"
                   dangerouslySetInnerHTML={{ __html: brief.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>') }} />
            ) : (
              <p className="text-sm text-muted-foreground">
                点击"生成日报"，AI 将根据雪球社区热度和财经新闻生成投资情绪摘要。
              </p>
            )}
          </CardContent>
        </Card>

        {/* 雪球 + RSS 独立模块 — 各自加载，互不阻塞 */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <XueqiuSection />
          <RSSSection />
        </div>
      </div>
    </>
  )
}
