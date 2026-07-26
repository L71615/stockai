/**
 * 日志缓冲 — 内存 ring buffer(纯实时,不落库)
 *
 * 数据源策略:
 * 由于 start.bat 没把 stockai stdout 重定向到文件,真正的 uvicorn access log 抓不到。
 * 这里采用"虚拟 access log":监视器每 5s ping 一次 stockai /api/health,
 * 把每次请求记成一行日志,展示在 LogPanel 里。
 *
 * 用户后续若同意改 start.bat(加 > logs/access.log 2>&1),可切换为 tail 真实日志。
 */

export type LogLevel = "INFO" | "WARN" | "ERROR"

export interface LogEntry {
  id: number
  timestamp: string
  level: LogLevel
  source: string
  message: string
  status?: number
  durationMs?: number
}

const MAX_ENTRIES = 1000
const buffer: LogEntry[] = []
let nextId = 1

let cleanupInterval: NodeJS.Timeout | null = null
const cleanupListeners = new Set<() => void>()

export function logEvent(entry: Omit<LogEntry, "id" | "timestamp">): LogEntry {
  const e: LogEntry = {
    ...entry,
    id: nextId++,
    timestamp: new Date().toISOString(),
  }
  buffer.push(e)
  // ring buffer
  if (buffer.length > MAX_ENTRIES) {
    buffer.splice(0, buffer.length - MAX_ENTRIES)
  }
  // 通知订阅者(IPC push)
  cleanupListeners.forEach((cb) => cb())
  return e
}

// 给 fetch 工具用的包装
export async function loggedFetch(
  url: string,
  label: string
): Promise<{ ok: boolean; status: number; durationMs: number; data?: unknown; error?: string }> {
  const start = Date.now()
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(3000) })
    const durationMs = Date.now() - start
    const status = res.status
    const level: LogLevel = status >= 500 ? "ERROR" : status >= 400 ? "WARN" : "INFO"

    let data: unknown
    try {
      data = await res.json()
    } catch {
      /* ignore */
    }

    logEvent({
      level,
      source: label,
      message: `${methodFromUrl(url)} ${pathFromUrl(url)} → ${status}`,
      status,
      durationMs,
    })

    return { ok: res.ok, status, durationMs, data }
  } catch (err) {
    const durationMs = Date.now() - start
    logEvent({
      level: "ERROR",
      source: label,
      message: `${methodFromUrl(url)} ${pathFromUrl(url)} → FAILED: ${(err as Error).message}`,
      status: 0,
      durationMs,
    })
    return {
      ok: false,
      status: 0,
      durationMs,
      error: (err as Error).message,
    }
  }
}

function methodFromUrl(url: string): string {
  // 默认 GET,我们的实现只做 GET
  return "GET"
}

function pathFromUrl(url: string): string {
  try {
    const u = new URL(url)
    return u.pathname + u.search
  } catch {
    return url
  }
}

// 公共 API
export function getLogs(limit = 200): LogEntry[] {
  // 返回最新 limit 条
  return buffer.slice(-limit)
}

export function getLogStats(): {
  total: number
  info: number
  warn: number
  error: number
  lastHour: { error: number; warn: number }
} {
  const now = Date.now()
  const oneHourAgo = now - 60 * 60 * 1000

  let info = 0
  let warn = 0
  let error = 0
  let lastHourErr = 0
  let lastHourWarn = 0

  for (const e of buffer) {
    if (e.level === "INFO") info++
    else if (e.level === "WARN") warn++
    else if (e.level === "ERROR") error++

    const t = new Date(e.timestamp).getTime()
    if (t >= oneHourAgo) {
      if (e.level === "ERROR") lastHourErr++
      if (e.level === "WARN") lastHourWarn++
    }
  }

  return {
    total: buffer.length,
    info,
    warn,
    error,
    lastHour: { error: lastHourErr, warn: lastHourWarn },
  }
}

export function subscribeLogs(cb: () => void): () => void {
  cleanupListeners.add(cb)
  return () => cleanupListeners.delete(cb)
}

export function clearLogs() {
  buffer.length = 0
  cleanupListeners.forEach((cb) => cb())
}

// 心跳 — 每 5s ping 一次 stockai /api/health,产生 access log
let healthTimer: NodeJS.Timeout | null = null

export function startHealthProbe(url: string, intervalMs: number) {
  if (healthTimer) return
  // 立即一次
  loggedFetch(url, "stockai /api/health")
  healthTimer = setInterval(() => {
    loggedFetch(url, "stockai /api/health")
  }, intervalMs)
}

export function stopHealthProbe() {
  if (healthTimer) {
    clearInterval(healthTimer)
    healthTimer = null
  }
}