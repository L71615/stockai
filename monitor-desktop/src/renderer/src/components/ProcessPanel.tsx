import type { ProcessInfo } from "../../../main/monitor/process"

interface ProcessCardProps {
  title: string
  icon: string
  info: ProcessInfo | null
  color: "primary" | "warning" | "danger"
}

function formatUptime(seconds: number): string {
  if (seconds <= 0) return "—"
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function ProgressBar({ value, max = 100, color }: { value: number; max?: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100)
  return (
    <div className="h-1.5 bg-bg-tertiary rounded-none overflow-hidden">
      <div
        className={`h-full transition-all duration-300 ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function ProcessCard({ title, icon, info, color }: ProcessCardProps) {
  const running = info?.status === "running"
  const portOk = info?.portListening

  const statusColor = !running
    ? "text-danger"
    : !portOk
      ? "text-warning"
      : "text-success"

  const statusText = !running
    ? "未运行"
    : !portOk
      ? "进程在但端口未监听"
      : "运行中"

  const barColor =
    color === "primary"
      ? "bg-primary"
      : color === "warning"
        ? "bg-warning"
        : "bg-danger"

  return (
    <div className="bg-bg-secondary border border-border p-4 rounded-none">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">{icon}</span>
          <h3 className="text-sm font-medium">{title}</h3>
        </div>
        <div className={`text-xs font-medium ${statusColor}`}>
          <span className="mr-1">●</span>
          {statusText}
        </div>
      </div>

      {info && (
        <div className="space-y-2.5">
          <Row label="PID" value={info.pid ? String(info.pid) : "—"} mono />
          <Row label="端口" value={`${info.port} ${portOk ? "✅" : "❌"}`} mono />
          <Row
            label="CPU"
            value={running ? `${info.cpuPercent.toFixed(1)}%` : "—"}
            mono
          >
            <ProgressBar value={info.cpuPercent} color={barColor} />
          </Row>
          <Row
            label="内存"
            value={running ? `${info.memoryMB.toFixed(1)} MB` : "—"}
            mono
          >
            <ProgressBar value={info.memoryMB} max={2048} color={barColor} />
          </Row>
          <Row
            label="启动"
            value={running ? formatUptime(info.uptimeSeconds) : "—"}
            mono
          />
        </div>
      )}
    </div>
  )
}

function Row({
  label,
  value,
  mono,
  children,
}: {
  label: string
  value: string
  mono?: boolean
  children?: React.ReactNode
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-fg-muted">{label}</span>
        <span className={`${mono ? "font-mono" : ""} text-fg tabular-nums`}>{value}</span>
      </div>
      {children && <div className="mt-1">{children}</div>}
    </div>
  )
}
