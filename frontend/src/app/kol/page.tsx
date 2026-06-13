"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconBrain, IconRefresh, IconFlame, IconNews } from "@tabler/icons-react"

interface XueqiuItem {
  code: string; name: string; follow_count: number; price: number
}

interface RSSItem {
  source: string; title: string; link: string; published: string
}

interface KolData {
  brief: string
  xueqiu_items: XueqiuItem[]
  rss_items: RSSItem[]
  generated_at: string
}

export default function KolPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [data, setData] = useState<KolData | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const result = await apiGet<KolData>("/api/kol/briefs/latest")
      if (result && result.brief) setData(result)
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchData()
  }, [fetchData, router])

  const refresh = async () => {
    setRefreshing(true)
    try {
      await apiPost("/api/kol/briefs/generate", {})
      await fetchData()
    } catch { /* */ }
    finally { setRefreshing(false) }
  }

  if (loading) return (
    <>
      <SiteHeader title="大佬观点" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        <Skeleton className="h-[300px]" />
        <Skeleton className="h-[200px]" />
      </div>
    </>
  )

  const xqItems = data?.xueqiu_items || []
  const rssItems = data?.rss_items || []

  return (
    <>
      <SiteHeader title="大佬观点" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">

        {/* Toolbar */}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={refresh} disabled={refreshing}>
            <IconRefresh className={refreshing ? "animate-spin size-3.5 mr-1" : "size-3.5 mr-1"} />
            刷新
          </Button>
          <span className="text-xs text-muted-foreground">
            {data?.generated_at ? `更新于 ${data.generated_at}` : "暂无数据"}
          </span>
        </div>

        {/* AI 摘要 */}
        <Card className="border-l-[3px] border-l-purple-400">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <IconBrain className="size-4 text-purple-400" />
              AI 观点摘要
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data?.brief && data.brief !== "📭 暂无日报" ? (
              <div className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground"
                   dangerouslySetInnerHTML={{ __html: data.brief.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>') }} />
            ) : (
              <p className="text-sm text-muted-foreground">
                点击"刷新"按钮，AI 将根据雪球社区热度和财经新闻生成投资情绪日报。
              </p>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* 雪球热门关注 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <IconFlame className="size-4 text-orange-400" />
                雪球热门关注
              </CardTitle>
              <CardDescription>社区热度最高的股票</CardDescription>
            </CardHeader>
            <CardContent>
              {xqItems.length > 0 ? (
                <div className="space-y-1">
                  {xqItems.slice(0, 10).map((item, i) => (
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
                <p className="text-xs text-muted-foreground">暂无数据</p>
              )}
            </CardContent>
          </Card>

          {/* RSS 新闻 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <IconNews className="size-4 text-blue-400" />
                财经快讯
              </CardTitle>
              <CardDescription>实时财经 RSS 摘要</CardDescription>
            </CardHeader>
            <CardContent>
              {rssItems.length > 0 ? (
                <div className="space-y-1">
                  {rssItems.map((item, i) => (
                    <div key={i} className="text-xs py-1.5 border-b border-border/30 last:border-0">
                      <a href={item.link} target="_blank" className="hover:underline text-foreground block">
                        {item.title}
                      </a>
                      <div className="flex items-center gap-2 mt-0.5 text-muted-foreground">
                        <Badge variant="outline" className="text-[10px]">{item.source}</Badge>
                        <span>{item.published}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  财经 RSS 源读取中（需 feedparser）。点"刷新"重试。
                </p>
              )}
            </CardContent>
          </Card>
        </div>

      </div>
    </>
  )
}
