/**
 * 预加载脚本 — 暴露 IPC API 给渲染进程
 */

import { contextBridge, ipcRenderer } from "electron"
import type { LogEntry } from "../main/monitor/logger"
import type { DbSummary, TableInfo } from "../main/monitor/database"
import type { PipelineStatus } from "../main/monitor/pipeline"

export interface MonitorConfig {
  refreshIntervalMs: number
  stockaiRoot: string
}

const api = {
  // 进程
  getSnapshot: () => ipcRenderer.invoke("monitor:get-snapshot"),
  getConfig: () => ipcRenderer.invoke("monitor:get-config"),

  // 日志
  getLogs: (limit?: number) => ipcRenderer.invoke("monitor:get-logs", limit) as Promise<LogEntry[]>,
  getLogStats: () => ipcRenderer.invoke("monitor:get-log-stats"),
  clearLogs: () => ipcRenderer.invoke("monitor:clear-logs"),

  // 数据库
  getDbSummary: () => ipcRenderer.invoke("monitor:get-db-summary") as Promise<DbSummary>,
  getTableDetail: (name: string) =>
    ipcRenderer.invoke("monitor:get-table-detail", name) as Promise<TableInfo>,
  refreshDb: () => ipcRenderer.invoke("monitor:refresh-db") as Promise<DbSummary>,

  // Pipeline
  getPipelineStatus: () =>
    ipcRenderer.invoke("monitor:get-pipeline-status") as Promise<PipelineStatus>,

  // 事件订阅
  onLogsUpdated: (cb: () => void) => {
    const handler = () => cb()
    ipcRenderer.on("monitor:logs-updated", handler)
    return () => ipcRenderer.removeListener("monitor:logs-updated", handler)
  },
}

contextBridge.exposeInMainWorld("monitor", api)

declare global {
  interface Window {
    monitor: typeof api
  }
}

// 重新导出类型供渲染进程用
export type { LogEntry, DbSummary, TableInfo, PipelineStatus }