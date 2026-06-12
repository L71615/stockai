"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { apiGet, apiPost, isAuthenticated } from "@/lib/auth"
import { IconPlus, IconPencil, IconTrash, IconBrain } from "@tabler/icons-react"

interface Agent {
  id: number; name: string; description?: string; system_prompt?: string
  tools?: string; is_active?: boolean
}

interface MemoryEntry { timestamp: string; content: string }

const TOOLS_MAP: Record<string, string> = {
  quote: "行情查询", news: "新闻搜索", holdings: "持仓分析", dca: "定投计算", indicator: "技术指标",
}

export default function SkillsPage() {
  const router = useRouter()
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [memoryAgent, setMemoryAgent] = useState<Agent | null>(null)
  const [memory, setMemory] = useState<MemoryEntry[]>([])
  const [memoryInput, setMemoryInput] = useState("")

  // Form
  const [aName, setAName] = useState(""); const [aDesc, setADesc] = useState("")
  const [aPrompt, setAPrompt] = useState(""); const [aTools, setATools] = useState<string[]>([])

  const fetchAgents = useCallback(async () => {
    try {
      const data = await apiGet<Agent[]>("/api/agents/agents")
      setAgents(Array.isArray(data) ? data : [])
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchAgents()
  }, [fetchAgents, router])

  const resetForm = () => {
    setAName(""); setADesc(""); setAPrompt(""); setATools([]); setEditId(null); setShowForm(false)
  }

  const startEdit = (a: Agent) => {
    setEditId(a.id); setAName(a.name); setADesc(a.description || "")
    setAPrompt(a.system_prompt || ""); setATools(a.tools ? a.tools.split(",").map((t) => t.trim()) : [])
    setShowForm(true)
  }

  const submit = async () => {
    const body = { name: aName, description: aDesc, system_prompt: aPrompt, tools: aTools.join(",") }
    if (editId) {
      await apiPost(`/api/agents/agents/${editId}`, body, "PUT")
    } else {
      await apiPost("/api/agents/agents", body)
    }
    resetForm(); fetchAgents()
  }

  const deleteAgent = async (id: number) => {
    if (!confirm("确认删除？")) return
    await apiPost(`/api/agents/agents/${id}`, {}, "DELETE")
    fetchAgents()
  }

  const loadMemory = async (agent: Agent) => {
    setMemoryAgent(agent)
    try {
      const data = await apiGet<{ content?: string }>(`/api/agents/${agent.id}/memory`)
      // Parse markdown — entries are separated by "## " headings
      const text = data.content || ""
      const entries: MemoryEntry[] = []
      const parts = text.split(/(?=^## )/m)
      for (const part of parts) {
        const lines = part.trim().split("\n")
        const ts = lines[0]?.replace(/^## /, "").trim() || ""
        const content = lines.slice(1).join("\n").trim()
        if (content) entries.push({ timestamp: ts, content })
      }
      setMemory(entries)
    } catch { setMemory([]) }
  }

  const addMemory = async () => {
    if (!memoryAgent || !memoryInput.trim()) return
    const now = new Date().toISOString()
    await apiPost(`/api/agents/${memoryAgent.id}/memory`, { entry: `## ${now}\n${memoryInput.trim()}` })
    setMemoryInput("")
    loadMemory(memoryAgent)
  }

  const toggleTool = (t: string) => {
    setATools((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t])
  }

  const toolOptions = Object.entries(TOOLS_MAP)

  return (
    <>
      <SiteHeader title="Agent 工坊" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => { resetForm(); setShowForm(!showForm) }}>
            <IconPlus className="size-3.5 mr-1" />{showForm ? "收起" : "创建 Agent"}
          </Button>
        </div>

        {/* Create/Edit form */}
        {showForm && (
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">名称</Label>
                  <Input value={aName} onChange={(e) => setAName(e.target.value)} className="h-8" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">描述</Label>
                  <Input value={aDesc} onChange={(e) => setADesc(e.target.value)} className="h-8" />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">系统提示词</Label>
                <Textarea value={aPrompt} onChange={(e) => setAPrompt(e.target.value)} className="min-h-20 text-xs" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">可用工具</Label>
                <div className="flex gap-2 flex-wrap">
                  {toolOptions.map(([key, label]) => (
                    <label key={key} className="flex items-center gap-1 text-xs cursor-pointer">
                      <input type="checkbox" checked={aTools.includes(key)} onChange={() => toggleTool(key)} className="size-3" />
                      {label}
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={submit}>{editId ? "更新" : "创建"}</Button>
                <Button size="sm" variant="ghost" onClick={resetForm}>取消</Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Memory panel */}
        {memoryAgent && (
          <Card className="border-l-[3px] border-l-purple-400">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2">
                  <IconBrain className="size-4 text-purple-400" />
                  {memoryAgent.name} 记忆
                </CardTitle>
                <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setMemoryAgent(null)}>关闭</Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex gap-2">
                <Input value={memoryInput} onChange={(e) => setMemoryInput(e.target.value)} className="h-7 text-xs flex-1" placeholder="添加记忆条目..." />
                <Button size="sm" className="h-7 text-xs" onClick={addMemory}>添加</Button>
              </div>
              <Separator />
              <div className="max-h-60 overflow-auto space-y-2">
                {memory.length === 0 && <p className="text-xs text-muted-foreground text-center py-4">暂无记忆</p>}
                {memory.map((m, i) => (
                  <div key={i} className="border border-border rounded-none p-2">
                    <p className="text-[10px] text-muted-foreground mb-1">{m.timestamp}</p>
                    <p className="text-xs whitespace-pre-wrap">{m.content}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Agent cards */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[1, 2].map((i) => <Skeleton key={i} className="h-32" />)}
          </div>
        ) : agents.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-4xl mb-2 opacity-40">🛠</p>
              <p className="text-sm text-muted-foreground">还没有自定义 Agent</p>
              <p className="text-xs text-muted-foreground mt-1">创建你的第一个 AI Agent，赋予它专属技能和记忆</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {agents.map((a) => (
              <Card key={a.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-sm">{a.name}</CardTitle>
                      {a.description && <CardDescription className="text-xs mt-0.5">{a.description}</CardDescription>}
                    </div>
                    <Badge variant="outline" className={cn("text-[10px]", a.is_active ? "" : "opacity-50")}>
                      {a.is_active !== false ? "启用" : "停用"}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1 mb-2">
                    {a.tools ? a.tools.split(",").map((t) => (
                      <Badge key={t} variant="secondary" className="text-[10px]">
                        {TOOLS_MAP[t.trim()] || t.trim()}
                      </Badge>
                    )) : <span className="text-[10px] text-muted-foreground">无工具</span>}
                  </div>
                  <div className="flex items-center gap-1 mt-2">
                    <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => startEdit(a)}>
                      <IconPencil className="size-3 mr-0.5" />编辑
                    </Button>
                    <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => loadMemory(a)}>
                      <IconBrain className="size-3 mr-0.5" />记忆
                    </Button>
                    <Button variant="ghost" size="sm" className="h-6 text-[10px] text-red-500" onClick={() => deleteAgent(a.id)}>
                      <IconTrash className="size-3 mr-0.5" />删除
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
