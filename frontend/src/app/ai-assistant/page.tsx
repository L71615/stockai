"use client"

import { useEffect, useState, useRef, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, getUsername, isAuthenticated } from "@/lib/auth"
import { IconSend, IconRobot, IconUser } from "@tabler/icons-react"

interface Agent { id: number; name: string; description?: string; tools?: string }
interface Message { role: string; content: string; id?: number }

const QUICK_COMMANDS = [
  { label: "分析持仓", msg: "请分析我当前的持仓情况" },
  { label: "交易复盘", msg: "请帮我复盘最近的交易记录" },
  { label: "定投建议", msg: "请给我一些定投策略建议" },
  { label: "市场概览", msg: "当前市场整体情况如何？" },
  { label: "持仓新闻", msg: "我持仓的股票最近有什么重要新闻？" },
]

export default function AiAssistantPage() {
  const router = useRouter()
  const [agents, setAgents] = useState<Agent[]>([])
  const [agentId, setAgentId] = useState("")
  const [tools, setTools] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [convId, setConvId] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)
  const username = getUsername()

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    apiGet<Agent[]>("/api/agents/agents").then((d) => {
      if (Array.isArray(d) && d.length > 0) {
        setAgents(d)
        setAgentId(String(d[0].id))
        setTools(d[0].tools || "")
      }
    }).catch(() => {})
  }, [router])

  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }) }, [messages])

  const send = async (msg?: string) => {
    const text = msg || input.trim()
    if (!text || loading) return
    setInput("")
    setMessages((prev) => [...prev, { role: "user", content: text }])
    setLoading(true)

    try {
      const data = await apiPost<{ reply: string; conversationId: string }>("/api/ai/chat", {
        message: text, agentId: agentId ? Number(agentId) : null, conversationId: convId,
      })
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }])
      if (data.conversationId) setConvId(data.conversationId)
    } catch (err) {
      setMessages((prev) => [...prev, { role: "error", content: err instanceof Error ? err.message : "发送失败" }])
    } finally { setLoading(false) }
  }

  return (
    <>
      <SiteHeader title="AI 对话" />
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex flex-1 flex-col max-w-3xl mx-auto w-full p-4 lg:p-6">
          {/* Toolbar */}
          <div className="flex items-center gap-2 mb-3 shrink-0">
            <select
              value={agentId}
              onChange={(e) => {
                setAgentId(e.target.value)
                const a = agents.find((a) => String(a.id) === e.target.value)
                setTools(a?.tools || "")
              }}
              className="h-8 rounded-none border border-input bg-transparent px-2 text-xs"
            >
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              {agents.length === 0 && <option value="">默认助手</option>}
            </select>
            {tools && (
              <div className="flex gap-1 flex-wrap">
                {tools.split(",").map((t) => (
                  <Badge key={t} variant="secondary" className="text-[10px]">{t.trim()}</Badge>
                ))}
              </div>
            )}
          </div>

          {/* Chat area */}
          <div ref={scrollRef} className="flex-1 overflow-auto space-y-3 mb-3">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <IconRobot className="size-12 text-muted-foreground/30 mb-3" />
                <p className="text-sm text-muted-foreground">我是你的 StockAI 投资教练</p>
                <p className="text-xs text-muted-foreground mt-1">选择一个快捷指令开始对话</p>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={cn("flex gap-2", m.role === "user" ? "justify-end" : "justify-start")}>
                {m.role !== "user" && (
                  <div className="shrink-0 size-6 rounded-none bg-purple-400/20 flex items-center justify-center">
                    <IconRobot className="size-3.5 text-purple-400" />
                  </div>
                )}
                <div className={cn(
                  "max-w-[80%] rounded-none px-3 py-2 text-sm",
                  m.role === "user" ? "bg-primary text-primary-foreground" :
                  m.role === "error" ? "bg-red-500/10 text-red-500" :
                  "bg-muted"
                )}>
                  <p className="whitespace-pre-wrap">{m.content}</p>
                </div>
                {m.role === "user" && (
                  <div className="shrink-0 size-6 rounded-none bg-primary/20 flex items-center justify-center">
                    <IconUser className="size-3.5" />
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-2">
                <div className="shrink-0 size-6 rounded-none bg-purple-400/20 flex items-center justify-center">
                  <IconRobot className="size-3.5 text-purple-400 animate-pulse" />
                </div>
                <div className="bg-muted rounded-none px-3 py-2 space-y-1.5">
                  <Skeleton className="h-3 w-48" />
                  <Skeleton className="h-3 w-32" />
                </div>
              </div>
            )}
          </div>

          {/* Quick commands */}
          <div className="flex gap-1 flex-wrap mb-2 shrink-0">
            {QUICK_COMMANDS.map((cmd) => (
              <Badge key={cmd.label} variant="outline"
                className="cursor-pointer hover:bg-accent transition-colors text-xs"
                onClick={() => send(cmd.msg)}>
                {cmd.label}
              </Badge>
            ))}
          </div>

          {/* Input */}
          <div className="flex gap-2 shrink-0">
            <Input
              value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="输入消息..."
              className="flex-1 h-9"
            />
            <Button size="sm" onClick={() => send()} disabled={loading}>
              <IconSend className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
