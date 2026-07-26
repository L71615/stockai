/**
 * 实时日志面板 — 显示监视器自己 ping stockai 的"虚拟 access log"
 */

import { useEffect, useRef, useState } from "react"
import type { LogEntry, LogLevel } from "../../../types"
import { clearLogs, getLogs, onLogsUpdated } from "../lib/api"

const LEVEL_STYLES: Record<LogLevel, { dot: string; text: string; bg: string }> = {
  INFO: { dot: "text-success", text: "text-fg", bg: "" },
  WARN: { dot: "text-warning", text: "text-warning", bg: "bg-warning/5" },
  ERROR: { dot: "text-danger", text: "text-danger", bg: "bg-danger/5" },
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
  } catch {
    return iso.slice(11, 19)
  }
}

function levelFilterMatches(level: LogLevel, filter: Set<LogLevel>) {
  return filter.has(level)
}

export function LogPanel() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState<Set<LogLevel>>(new Set(["INFO", "WARN", "ERROR"]))
  const [searchText, setSearchText] = useState("")
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const refresh = async () => {
    const l = await getLogs(200)
    setLogs(l)
  }

  useEffect(() => {
    refresh()
    const off = onLogsUpdated(() => refresh())
    return off
  }, [])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const filtered = logs
    .filter((l) => levelFilterMatches(l.level, filter))
    .filter((l) =>
      searchText
        ? l.message.toLowerCase().includes(searchText.toLowerCase()) ||
          l.source.toLowerCase().includes(searchText.toLowerCase())
        : true
    )

  const toggleFilter = (lv: LogLevel) => {
    setFilter((prev) => {
      const next = new Set(prev)
      if (next.has(lv)) next.delete(lv)
      else next.add(lv)
      return next
    })
  }

  const handleClear = async () => {
    await clearLogs()
    refresh()
  }

  return (
    <div className="bg-bg-secondary border border-border rounded-none flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-medium">📋 实时访问日志</h2>
          <span className="text-xs text-fg-muted">{filtered.length} / {logs.length} 条</span>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="🔍 关键字过滤..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="h-7 px-2 text-xs bg-bg-tertiary border border-border-subtle text-fg placeholder:text-fg-subtle focus:outline-none focus:border-primary font-mono"
            style={{ width: 180 }}
          />
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`h-7 px-2 text-xs border transition-colors ${
              autoScroll
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-fg-muted hover:text-fg"
            }`}
          >
            {autoScroll ? "📍 自动滚动" : "⏸ 暂停滚动"}
          </button>
          <button
            onClick={handleClear}
            className="h-7 px-2 text-xs border border-border text-fg-muted hover:text-danger hover:border-danger transition-colors"
          >
            🗑 清空
          </button>
        </div>
      </div>

      {/* 级别过滤 */}
      <div className="px-4 py-2 border-b border-border-subtle flex items-center gap-2 text-xs">
        {(["INFO", "WARN", "ERROR"] as LogLevel[]).map((lv) => {
          const active = filter.has(lv)
          return (
            <button
              key={lv}
              onClick={() => toggleFilter(lv)}
              className={`px-2 py-0.5 border transition-colors ${LEVEL_STYLES[lv].text} ${
                active
                  ? "border-current bg-current/10"
                  : "border-border-subtle text-fg-subtle"
              }`}
            >
              {lv}
            </button>
          )
        })}
        <span className="ml-2 text-fg-subtle">· 来源: 监视器心跳 ping</span>
      </div>

      {/* 日志列表 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto font-mono text-xs leading-relaxed"
      >
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-fg-subtle">暂无日志</div>
        ) : (
          filtered.map((l) => {
            const style = LEVEL_STYLES[l.level]
            return (
              <div
                key={l.id}
                className={`flex items-start gap-3 px-4 py-1 hover:bg-bg-tertiary transition-colors ${style.bg}`}
              >
                <span className="text-fg-subtle shrink-0 tabular-nums">
                  {formatTime(l.timestamp)}
                </span>
                <span className={`shrink-0 w-12 ${style.dot}`}>●</span>
                <span className={`shrink-0 w-12 ${style.text}`}>{l.level}</span>
                <span className="shrink-0 text-fg-muted">{l.source}</span>
                <span className={`flex-1 ${style.text} break-all`}>{l.message}</span>
                {l.durationMs !== undefined && (
                  <span className="shrink-0 text-fg-subtle tabular-nums">
                    {l.durationMs}ms
                  </span>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}