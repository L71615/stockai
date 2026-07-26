/**
 * Pipeline 状态面板 — 调用 stockai /api/pipeline/status
 */

import { useEffect, useState } from "react"
import type { PipelineStatus } from "../../../types"
import { getPipelineStatus } from "../lib/api"

const STEPS = [
  { key: "gp_mining", label: "GP 挖掘", icon: "🌱" },
  { key: "ml_training", label: "ML 训练", icon: "🤖" },
  { key: "factor_decay", label: "因子衰减", icon: "📉" },
  { key: "data_health", label: "数据健康", icon: "💚" },
  { key: "brief_notify", label: "简报推送", icon: "📨" },
]

const STATUS_STYLES: Record<string, { color: string; text: string }> = {
  idle: { color: "text-fg-muted", text: "空闲" },
  running: { color: "text-primary", text: "运行中" },
  success: { color: "text-success", text: "完成" },
  failed: { color: "text-danger", text: "失败" },
  unknown: { color: "text-fg-subtle", text: "未知" },
}

function formatRelative(iso?: string): string {
  if (!iso) return "—"
  try {
    const d = new Date(iso)
    const diff = Math.floor((Date.now() - d.getTime()) / 1000)
    if (diff < 60) return `${diff}秒前`
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    return `${Math.floor(diff / 86400)}天前`
  } catch {
    return iso
  }
}

export function PipelinePanel() {
  const [status, setStatus] = useState<PipelineStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    try {
      const s = await getPipelineStatus()
      setStatus(s)
      setError(null)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [])

  if (!status) {
    return (
      <div className="bg-bg-secondary border border-border p-4 rounded-none text-xs text-fg-muted">
        加载中...
      </div>
    )
  }

  const style = STATUS_STYLES[status.status] || STATUS_STYLES.unknown

  return (
    <div className="bg-bg-secondary border border-border rounded-none">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-medium">📨 Pipeline 状态</h2>
          <span className={`text-xs font-medium ${style.color}`}>
            <span className="mr-1">●</span>
            {style.text}
          </span>
        </div>
        {!status.reachable && (
          <span className="text-xs text-warning">stockai 未响应</span>
        )}
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-danger border-b border-danger/30">
          ⚠ {error}
        </div>
      )}

      <div className="p-4 space-y-3">
        {/* 5 步进度 */}
        <div className="flex items-center gap-1 flex-wrap">
          {STEPS.map((s, i) => {
            const isCurrent = status.step === s.key
            const isDone = status.status === "success"
            const isFailed = status.status === "failed"
            return (
              <div
                key={s.key}
                className={`flex items-center gap-1 px-2 py-1 text-xs border transition-colors ${
                  isCurrent
                    ? "border-primary bg-primary/15 text-primary"
                    : isDone
                      ? "border-success/40 text-success"
                      : isFailed
                        ? "border-danger/40 text-danger"
                        : "border-border-subtle text-fg-subtle"
                }`}
              >
                <span>{s.icon}</span>
                <span>{s.label}</span>
                {isDone && <span>✓</span>}
                {isCurrent && <span>●</span>}
                {i < STEPS.length - 1 && <span className="text-fg-subtle ml-1">→</span>}
              </div>
            )
          })}
        </div>

        {/* 元信息 */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <Row label="当前步骤" value={status.step || "—"} />
          <Row label="进度" value={status.progress != null ? `${status.progress}%` : "—"} />
          <Row label="开始时间" value={formatRelative(status.startedAt)} />
          <Row label="结束时间" value={formatRelative(status.finishedAt)} />
          {status.briefId && <Row label="简报 ID" value={status.briefId} mono />}
          {status.errorMessage && (
            <Row label="错误" value={status.errorMessage} />
          )}
        </div>
      </div>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-fg-muted">{label}</span>
      <span className={`${mono ? "font-mono" : ""} text-fg tabular-nums truncate ml-2`} title={value}>
        {value}
      </span>
    </div>
  )
}