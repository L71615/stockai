/**
 * 错误统计 — 24h 内 ERROR/WARN 数量
 */

import { useEffect, useState } from "react"
import { getLogStats, onLogsUpdated } from "../lib/api"

interface LogStats {
  total: number
  info: number
  warn: number
  error: number
  lastHour: { error: number; warn: number }
}

export function ErrorStats() {
  const [stats, setStats] = useState<LogStats | null>(null)

  const refresh = async () => {
    const s = await getLogStats()
    setStats(s)
  }

  useEffect(() => {
    refresh()
    const off = onLogsUpdated(() => refresh())
    return off
  }, [])

  if (!stats) {
    return (
      <div className="bg-bg-secondary border border-border p-4 rounded-none text-xs text-fg-muted">
        加载中...
      </div>
    )
  }

  return (
    <div className="bg-bg-secondary border border-border rounded-none">
      <div className="px-4 py-3 border-b border-border">
        <h2 className="text-sm font-medium">⚠ 错误统计</h2>
      </div>
      <div className="p-4">
        <div className="grid grid-cols-4 gap-2 text-center">
          <Card label="总日志" value={stats.total} color="text-fg" />
          <Card label="INFO" value={stats.info} color="text-success" />
          <Card label="WARN" value={stats.warn} color="text-warning" />
          <Card label="ERROR" value={stats.error} color="text-danger" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <div className="border border-border-subtle px-3 py-2 rounded-none">
            <div className="text-fg-muted">1h 内 ERROR</div>
            <div className="text-lg font-mono tabular-nums text-danger">
              {stats.lastHour.error}
            </div>
          </div>
          <div className="border border-border-subtle px-3 py-2 rounded-none">
            <div className="text-fg-muted">1h 内 WARN</div>
            <div className="text-lg font-mono tabular-nums text-warning">
              {stats.lastHour.warn}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Card({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="border border-border-subtle px-3 py-2 rounded-none">
      <div className="text-[10px] text-fg-muted uppercase tracking-wide">{label}</div>
      <div className={`text-lg font-mono tabular-nums ${color}`}>{value}</div>
    </div>
  )
}