"use client"

/** v5.2 — 选股中心(单页面 + Tab 容器)
 *
 * 合并了:
 *   - 原 /screener(AI 选股) → Tab 1
 *   - 原 /screener/condition(条件选股) → Tab 2
 *
 * 设计:
 *  - URL search param `?tab=ai|condition` 用于 deep link + 浏览器后退
 *  - localStorage `screener:activeTab` 用于跨刷新记忆
 *  - 默认 tab = ai
 */
import { useState, useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { AIScreener } from "@/components/ai-screener"
import { ConditionScreener } from "@/components/condition-screener"
import { IconBrain, IconFilter } from "@tabler/icons-react"

type ScreenerTab = "ai" | "condition"
const VALID_TABS: ScreenerTab[] = ["ai", "condition"]

export default function ScreenerPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [tab, setTab] = useState<ScreenerTab>("ai")

  // 初始化 tab — URL ?tab= 优先, localStorage 其次, 默认 ai
  useEffect(() => {
    const urlTab = searchParams.get("tab") as ScreenerTab | null
    if (urlTab && VALID_TABS.includes(urlTab)) {
      setTab(urlTab)
    } else if (typeof window !== "undefined") {
      const saved = window.localStorage.getItem("screener:activeTab") as ScreenerTab | null
      if (saved && VALID_TABS.includes(saved)) setTab(saved)
    }
  }, [searchParams])

  // tab 切换 → URL + localStorage 同步
  const handleTabChange = (v: string) => {
    if (!VALID_TABS.includes(v as ScreenerTab)) return
    const next = v as ScreenerTab
    setTab(next)
    if (typeof window !== "undefined") {
      window.localStorage.setItem("screener:activeTab", next)
    }
    // URL 同步(不触发导航, 只换 search param)
    const params = new URLSearchParams(searchParams.toString())
    params.set("tab", next)
    router.replace(`/screener?${params.toString()}`, { scroll: false })
  }

  return (
    <>
      <SiteHeader title="选股中心" />
      <div className="flex flex-1 flex-col overflow-auto">
        <div className="p-4 lg:p-6">
          <Tabs value={tab} onValueChange={handleTabChange} className="w-full">
            <TabsList className="mb-4">
              <TabsTrigger value="ai" className="gap-1.5">
                <IconBrain className="size-3.5" />
                AI 选股
              </TabsTrigger>
              <TabsTrigger value="condition" className="gap-1.5">
                <IconFilter className="size-3.5" />
                条件选股
              </TabsTrigger>
            </TabsList>
            <TabsContent value="ai">
              <AIScreener />
            </TabsContent>
            <TabsContent value="condition">
              <ConditionScreener />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </>
  )
}