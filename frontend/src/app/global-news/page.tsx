"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, isAuthenticated } from "@/lib/auth"
import { IconExternalLink, IconRefresh, IconMapPin } from "@tabler/icons-react"

// --- Data ---

interface NewsItem {
  title: string
  url?: string
  date?: string
  source?: string
}

interface CityInfo {
  id: string
  name: string
  country: string
  lat: number
  lng: number
}

const CITIES: CityInfo[] = [
  { id: "us", name: "纽约", country: "美国", lat: 40.7, lng: -74.0 },
  { id: "uk", name: "伦敦", country: "英国", lat: 51.5, lng: -0.1 },
  { id: "cn", name: "上海", country: "中国", lat: 31.2, lng: 121.5 },
  { id: "jp", name: "东京", country: "日本", lat: 35.7, lng: 139.8 },
  { id: "hk", name: "香港", country: "中国香港", lat: 22.3, lng: 114.2 },
  { id: "sg", name: "新加坡", country: "新加坡", lat: 1.3, lng: 103.8 },
  { id: "de", name: "法兰克福", country: "德国", lat: 50.1, lng: 8.7 },
  { id: "ae", name: "迪拜", country: "阿联酋", lat: 25.3, lng: 55.3 },
  { id: "in", name: "孟买", country: "印度", lat: 19.1, lng: 72.9 },
  { id: "au", name: "悉尼", country: "澳大利亚", lat: -33.9, lng: 151.2 },
  { id: "br", name: "圣保罗", country: "巴西", lat: -23.5, lng: -46.6 },
  { id: "ca", name: "多伦多", country: "加拿大", lat: 43.7, lng: -79.4 },
  { id: "kr", name: "首尔", country: "韩国", lat: 37.6, lng: 127.0 },
  { id: "ru", name: "莫斯科", country: "俄罗斯", lat: 55.8, lng: 37.6 },
  { id: "sa", name: "利雅得", country: "沙特", lat: 24.7, lng: 46.7 },
  { id: "za", name: "约翰内斯堡", country: "南非", lat: -26.2, lng: 28.0 },
]

const CONNECTIONS: [string, string][] = [
  ["us", "uk"], ["us", "cn"], ["uk", "de"], ["uk", "hk"],
  ["cn", "jp"], ["cn", "hk"], ["cn", "sg"], ["hk", "sg"],
  ["jp", "kr"], ["ae", "in"], ["ae", "sg"], ["us", "br"],
  ["us", "ca"], ["uk", "ae"], ["in", "sg"], ["au", "sg"],
]

function project(lat: number, lng: number) {
  return {
    x: (lng + 180) * (198 / 360),
    y: (90 - lat) * (100 / 180),
  }
}

function curvePath(s: { x: number; y: number }, e: { x: number; y: number }) {
  const mx = (s.x + e.x) / 2
  const my = Math.min(s.y, e.y) - 4
  return `M${s.x} ${s.y} Q${mx} ${my} ${e.x} ${e.y}`
}

const QUICK_REGIONS = [
  { id: "us", flag: "🇺🇸", name: "美国" },
  { id: "cn", flag: "🇨🇳", name: "中国" },
  { id: "hk", flag: "🇭🇰", name: "香港" },
  { id: "jp", flag: "🇯🇵", name: "日本" },
  { id: "uk", flag: "🇬🇧", name: "英国" },
  { id: "de", flag: "🇩🇪", name: "德国" },
  { id: "in", flag: "🇮🇳", name: "印度" },
  { id: "br", flag: "🇧🇷", name: "巴西" },
  { id: "sa", flag: "🇸🇦", name: "沙特" },
  { id: "ae", flag: "🇦🇪", name: "中东" },
  { id: "au", flag: "🇦🇺", name: "澳洲" },
  { id: "ru", flag: "🇷🇺", name: "俄罗斯" },
]

// --- Page ---

export default function GlobalNewsPage() {
  const router = useRouter()
  const [selected, setSelected] = useState<string>("cn")
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const selectedCity = CITIES.find((c) => c.id === selected)

  const fetchNews = useCallback(async (regionId: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<{ news: NewsItem[] }>(`/api/stocks/news/global/${regionId}`)
      setNews(data.news || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
      setNews([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login")
      return
    }
    fetchNews(selected)
  }, [selected, fetchNews, router])

  return (
    <>
      <SiteHeader title="全球资讯" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6 space-y-4">
          {/* Quick region chips */}
          <div className="flex flex-wrap gap-1.5">
            {QUICK_REGIONS.map((r) => (
              <Badge
                key={r.id}
                variant={selected === r.id ? "default" : "outline"}
                className={cn(
                  "cursor-pointer select-none transition-colors",
                  selected === r.id
                    ? "bg-primary text-primary-foreground hover:bg-primary/80"
                    : "hover:bg-accent hover:text-accent-foreground"
                )}
                onClick={() => setSelected(r.id)}
              >
                {r.flag} {r.name}
              </Badge>
            ))}
          </div>

          <div className="flex flex-col lg:flex-row gap-4">
            {/* World Map */}
            <Card className="flex-1 overflow-hidden">
              <CardContent className="p-0 h-[350px] lg:h-[480px]">
                <svg
                  viewBox="0 0 198 100"
                  preserveAspectRatio="xMidYMid meet"
                  className="w-full h-full block"
                >
                  {/* Background */}
                  <rect width="198" height="100" fill="#0f172a" />

                  {/* Defs — edge fade mask */}
                  <defs>
                    <linearGradient id="fadeGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="black" stopOpacity="0" />
                      <stop offset="8%" stopColor="white" />
                      <stop offset="92%" stopColor="white" />
                      <stop offset="100%" stopColor="black" stopOpacity="0" />
                    </linearGradient>
                    <mask id="edgeFade">
                      <rect width="198" height="100" fill="url(#fadeGrad)" />
                    </mask>
                  </defs>

                  {/* Grid lines */}
                  {[-80, -40, 0, 40, 80].map((lat) => (
                    <line
                      key={`lat-${lat}`}
                      x1="0" y1={(90 - lat) * (100 / 180)} x2="198" y2={(90 - lat) * (100 / 180)}
                      stroke="#1e293b" strokeWidth="0.15"
                    />
                  ))}
                  {[-160, -120, -80, -40, 0, 40, 80, 120, 160].map((lng) => (
                    <line
                      key={`lng-${lng}`}
                      x1={(lng + 180) * (198 / 360)} y1="0" x2={(lng + 180) * (198 / 360)} y2="100"
                      stroke="#1e293b" strokeWidth="0.15"
                    />
                  ))}

                  {/* Connection lines */}
                  {CONNECTIONS.map(([aId, bId], i) => {
                    const ca = CITIES.find((c) => c.id === aId)
                    const cb = CITIES.find((c) => c.id === bId)
                    if (!ca || !cb) return null
                    const pa = project(ca.lat, ca.lng)
                    const pb = project(cb.lat, cb.lng)
                    return (
                      <path
                        key={`conn-${i}`}
                        d={curvePath(pa, pb)}
                        fill="none"
                        stroke="#3b82f6"
                        strokeWidth="0.3"
                        strokeDasharray="1 2"
                        opacity="0.35"
                      />
                    )
                  })}

                  {/* World dots map — base layer */}
                  <image
                    href="/world-dots.svg"
                    width="198"
                    height="100"
                    mask="url(#edgeFade)"
                    opacity="0.85"
                    pointerEvents="none"
                  />

                  {/* City dots */}
                  {CITIES.map((city) => {
                    const pos = project(city.lat, city.lng)
                    const isActive = selected === city.id
                    return (
                      <g key={city.id} className="cursor-pointer" onClick={() => setSelected(city.id)}>
                        {/* Pulse ring (active only) */}
                        {isActive && (
                          <circle
                            cx={pos.x} cy={pos.y} r="0.6"
                            fill="#f59e0b" opacity="0.5"
                          >
                            <animate attributeName="r" from="0.6" to="2.2" dur="1.5s" repeatCount="indefinite" />
                            <animate attributeName="opacity" from="0.5" to="0" dur="1.5s" repeatCount="indefinite" />
                          </circle>
                        )}
                        {/* Dot */}
                        <circle
                          cx={pos.x} cy={pos.y} r="0.55"
                          fill={isActive ? "#f59e0b" : "#3b82f6"}
                          className="transition-colors hover:fill-[#60a5fa]"
                        />
                        {/* Label */}
                        <text
                          x={pos.x + 0.9} y={pos.y + 0.4}
                          fill={isActive ? "#fbbf24" : "#94a3b8"}
                          fontSize="2.2"
                          fontFamily="system-ui, sans-serif"
                          pointerEvents="none"
                        >
                          {city.name}
                        </text>
                      </g>
                    )
                  })}
                </svg>
              </CardContent>
            </Card>

            {/* News Panel */}
            <Card className="w-full lg:w-[370px] shrink-0 flex flex-col max-h-[600px]">
              <CardContent className="p-0 flex flex-col h-full">
                {/* Panel header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
                  <div className="flex items-center gap-2">
                    <IconMapPin className="size-4 text-muted-foreground" />
                    <span className="text-sm font-medium">
                      {selectedCity ? `${selectedCity.name}, ${selectedCity.country}` : "选择城市"}
                    </span>
                  </div>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => fetchNews(selected)}>
                    <IconRefresh className="size-3.5" />
                  </Button>
                </div>

                {/* News list */}
                <div className="flex-1 overflow-auto">
                  {loading && (
                    <div className="p-4 space-y-3">
                      {[1, 2, 3, 4, 5].map((i) => (
                        <div key={i} className="space-y-1.5">
                          <Skeleton className="h-4 w-full" />
                          <Skeleton className="h-3 w-24" />
                        </div>
                      ))}
                    </div>
                  )}

                  {!loading && error && (
                    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                      <p className="text-sm text-red-500 mb-2">{error}</p>
                      <Button variant="outline" size="sm" onClick={() => fetchNews(selected)}>
                        重试
                      </Button>
                    </div>
                  )}

                  {!loading && !error && news.length === 0 && (
                    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                      <p className="text-4xl mb-2 opacity-40">📭</p>
                      <p className="text-sm text-muted-foreground">暂无相关财经新闻</p>
                    </div>
                  )}

                  {!loading && !error && news.length > 0 && (
                    <div>
                      {news.map((item, i) => (
                        <div
                          key={i}
                          className={cn(
                            "px-4 py-3 border-b border-border last:border-b-0 transition-colors hover:bg-accent/30 cursor-pointer"
                          )}
                          onClick={() => {
                            if (item.url) window.open(item.url, "_blank")
                          }}
                        >
                          <p className="text-sm leading-relaxed mb-1 line-clamp-2">{item.title}</p>
                          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                            {item.source && <span>{item.source}</span>}
                            {item.date && <span>{item.date}</span>}
                            {item.url && <IconExternalLink className="size-3" />}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </>
  )
}
