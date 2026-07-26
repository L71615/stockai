/**
 * IPC 客户端 — 封装主进程 API
 */

import type {
  ProcessSnapshot,
  MonitorConfig,
  LogEntry,
  DbSummary,
  TableInfo,
  PipelineStatus,
} from "../../../types"

export async function getSnapshot(): Promise<ProcessSnapshot | null> {
  if (!window.monitor) return null
  return await window.monitor.getSnapshot()
}

export async function getConfig(): Promise<MonitorConfig | null> {
  if (!window.monitor) return null
  return await window.monitor.getConfig()
}

export async function getLogs(limit = 200): Promise<LogEntry[]> {
  if (!window.monitor) return []
  return await window.monitor.getLogs(limit)
}

export async function getLogStats() {
  if (!window.monitor)
    return { total: 0, info: 0, warn: 0, error: 0, lastHour: { error: 0, warn: 0 } }
  return await window.monitor.getLogStats()
}

export async function clearLogs() {
  if (!window.monitor) return
  return await window.monitor.clearLogs()
}

export async function getDbSummary(): Promise<DbSummary | null> {
  if (!window.monitor) return null
  return await window.monitor.getDbSummary()
}

export async function getTableDetail(name: string): Promise<TableInfo | null> {
  if (!window.monitor) return null
  return await window.monitor.getTableDetail(name)
}

export async function refreshDb(): Promise<DbSummary | null> {
  if (!window.monitor) return null
  return await window.monitor.refreshDb()
}

export async function getPipelineStatus(): Promise<PipelineStatus | null> {
  if (!window.monitor) return null
  return await window.monitor.getPipelineStatus()
}

export function onLogsUpdated(cb: () => void) {
  if (!window.monitor) return () => {}
  return window.monitor.onLogsUpdated(cb)
}