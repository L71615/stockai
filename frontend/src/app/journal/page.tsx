"use client"

import { useEffect, useState, useCallback } from "react"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost } from "@/lib/auth"
import { IconNotebook } from "@tabler/icons-react"

interface JournalEntry {
  id: number; stock_code: string; stock_name: string
  direction: string; entry_price: number; exit_price: number
  quantity: number; pnl: number; pnl_pct: number
  stop_loss_hit: number; discipline_score: number | null
  emotional_state: string; lessons_learned: string
  entry_date: string; exit_date: string
}

const EMOTIONS: Record<string, string> = {
  calm: "冷静", anxious: "焦虑", greedy: "贪婪", fearful: "恐惧",
  confident: "自信", regret: "后悔",
}

export default function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [editId, setEditId] = useState<number | null>(null)
  const [score, setScore] = useState("")
  const [emotion, setEmotion] = useState("")
  const [lesson, setLesson] = useState("")

  const fetchEntries = useCallback(async () => {
    try {
      const data = await apiGet<JournalEntry[]>("/api/discipline/journal")
      setEntries(Array.isArray(data) ? data : [])
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchEntries() }, [fetchEntries])

  const saveEdit = async (id: number) => {
    await apiPost(`/api/discipline/journal/${id}`, {
      discipline_score: score ? Number(score) : undefined,
      emotional_state: emotion || undefined,
      lessons_learned: lesson || undefined,
    }, "PUT")
    setEditId(null); fetchEntries()
  }

  const totalPnl = entries.reduce((s, e) => s + (e.pnl || 0), 0)
  const winCount = entries.filter(e => (e.pnl || 0) > 0).length
  const lossCount = entries.filter(e => (e.pnl || 0) < 0).length

  if (loading) return (
    <>
      <SiteHeader title="交易日志" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        <Skeleton className="h-[400px]" />
      </div>
    </>
  )

  return (
    <>
      <SiteHeader title="交易日志" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4">
        {/* Summary */}
        <div className="grid grid-cols-4 gap-3">
          <Card><CardContent className="py-3 text-center">
            <p className="text-xs text-muted-foreground">总笔数</p>
            <p className="text-lg font-bold">{entries.length}</p>
          </CardContent></Card>
          <Card><CardContent className="py-3 text-center">
            <p className="text-xs text-muted-foreground">盈利</p>
            <p className="text-lg font-bold text-emerald-400">{winCount}</p>
          </CardContent></Card>
          <Card><CardContent className="py-3 text-center">
            <p className="text-xs text-muted-foreground">亏损</p>
            <p className="text-lg font-bold text-red-400">{lossCount}</p>
          </CardContent></Card>
          <Card><CardContent className="py-3 text-center">
            <p className="text-xs text-muted-foreground">累计盈亏</p>
            <p className={`text-lg font-bold ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              ¥{totalPnl.toFixed(2)}
            </p>
          </CardContent></Card>
        </div>

        {/* Entries */}
        {entries.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground text-sm">
              <IconNotebook className="size-8 mx-auto mb-2 opacity-40" />
              还没有交易日志。卖出交易时会自动生成日志。
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {entries.map((e) => (
              <Card key={e.id} className={e.stop_loss_hit ? "border-l-[3px] border-l-red-400" : ""}>
                <CardContent className="py-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-sm">{e.stock_code}</span>
                      <span className="text-xs text-muted-foreground">{e.stock_name}</span>
                      <Badge variant="outline" className={e.pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {e.pnl >= 0 ? "+" : ""}¥{(e.pnl || 0).toFixed(2)}
                      </Badge>
                      {e.pnl_pct != null && (
                        <span className={`text-xs ${e.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {e.pnl_pct >= 0 ? "+" : ""}{e.pnl_pct}%
                        </span>
                      )}
                      {e.stop_loss_hit ? <Badge className="text-[10px] bg-red-500/10 text-red-400">止损</Badge> : null}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{e.exit_date}</span>
                      {e.discipline_score != null && <Badge variant="secondary">{e.discipline_score}/10</Badge>}
                      {e.emotional_state && <span>{EMOTIONS[e.emotional_state] || e.emotional_state}</span>}
                    </div>
                  </div>

                  {/* Expandable edit */}
                  {editId === e.id ? (
                    <div className="mt-3 pt-3 border-t border-border space-y-2">
                      <div className="flex gap-2">
                        <Select value={score} onValueChange={setScore}>
                          <SelectTrigger className="h-7 text-xs w-24">
                            <SelectValue placeholder="评分" />
                          </SelectTrigger>
                          <SelectContent>
                            {[1,2,3,4,5,6,7,8,9,10].map(n => (
                              <SelectItem key={n} value={String(n)} className="text-xs">{n} 分</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Select value={emotion} onValueChange={setEmotion}>
                          <SelectTrigger className="h-7 text-xs w-24">
                            <SelectValue placeholder="情绪" />
                          </SelectTrigger>
                          <SelectContent>
                            {Object.entries(EMOTIONS).map(([k, v]) => (
                              <SelectItem key={k} value={k} className="text-xs">{v}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Input
                          value={lesson}
                          onChange={(ev) => setLesson(ev.target.value)}
                          className="h-7 text-xs flex-1"
                          placeholder="学到了什么..."
                        />
                        <Button size="sm" className="h-7 text-xs" onClick={() => saveEdit(e.id)}>保存</Button>
                        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setEditId(null)}>取消</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 mt-1">
                      {e.lessons_learned && (
                        <p className="text-xs text-muted-foreground italic flex-1">&ldquo;{e.lessons_learned}&rdquo;</p>
                      )}
                      <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => {
                        setEditId(e.id); setScore(e.discipline_score ? String(e.discipline_score) : "")
                        setEmotion(e.emotional_state || ""); setLesson(e.lessons_learned || "")
                      }}>评分/复盘</Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
