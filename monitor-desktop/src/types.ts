/**
 * 共享类型定义 — 渲染端和主进程共用
 * (类型不参与运行时,仅 TS 编译用)
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

export interface ColumnInfo {
  cid: number
  name: string
  type: string
  notnull: boolean
  pk: boolean
}

export interface ForeignKeyInfo {
  from: string
  table: string
  to: string
}

export interface IndexInfo {
  name: string
  unique: boolean
}

export interface TableInfo {
  name: string
  type: "table" | "view" | "index"
  rowCount: number | null
  sizeMB: number | null
  columns: ColumnInfo[]
  foreignKeys: ForeignKeyInfo[]
  indexes: IndexInfo[]
  sampleRows: Record<string, unknown>[]
}

export interface DbSummary {
  databasePath: string
  databaseSizeMB: number
  schemaVersion: string | null
  journalMode?: string
  lastUpdated: string
  tableCount: number
  totalRows: number
  tables: { name: string; type: string; rowCount: number | null; sizeMB: number | null }[]
}

export interface PipelineStatus {
  timestamp: string
  reachable: boolean
  status: "idle" | "running" | "success" | "failed" | "unknown"
  step?: string
  progress?: number
  startedAt?: string
  finishedAt?: string
  briefId?: string
  errorMessage?: string
  raw?: unknown
}

export interface ProcessInfo {
  name: string
  pid: number | null
  status: "running" | "stopped" | "unknown"
  cpuPercent: number
  memoryMB: number
  uptimeSeconds: number
  port: number
  portListening: boolean
  startedAt: string | null
}

export interface ProcessSnapshot {
  timestamp: string
  overall: {
    cpuPercent: number
    memoryUsedPercent: number
    memoryUsedMB: number
    memoryTotalMB: number
  }
  processes: {
    backend: ProcessInfo
    frontend: ProcessInfo
  }
  portChecks: {
    backend: boolean
    frontend: boolean
  }
}

export interface MonitorConfig {
  refreshIntervalMs: number
  stockaiRoot: string
}