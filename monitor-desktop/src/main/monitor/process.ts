/**
 * 进程监控模块
 *
 * 监控 stockai 的两个核心进程:
 * 1. backend uvicorn (端口 3000)
 * 2. frontend next (端口 3001)
 *
 * 纯只读 — 用 systeminformation 抓进程列表,扫描端口监听
 */

import si from "systeminformation"
import { config } from "../config"

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

// 进程识别规则 — Windows 用命令行模糊匹配
// 1. backend: 命令行包含 "uvicorn" 且端口 3000
// 2. frontend: 命令行包含 "next" 或 "node" 且端口 3001
async function findProcessByPort(
  port: number,
  procName?: string
): Promise<{ pid: number; cmd: string } | null> {
  try {
    const connections = await si.networkConnections()
    const conn = connections.find((c) => c.localPort === String(port))
    if (!conn) return null

    const processes = await si.processes()
    const proc = processes.list.find((p) => p.pid === conn.pid)
    if (!proc) return null

    const cmd = (proc.command || proc.params || "").toString()
    if (procName && !cmd.toLowerCase().includes(procName.toLowerCase())) {
      return null
    }
    return { pid: proc.pid, cmd }
  } catch {
    return null
  }
}

async function getProcessInfo(
  port: number,
  procName: string,
  displayName: string
): Promise<ProcessInfo> {
  const found = await findProcessByPort(port, procName)

  if (!found) {
    return {
      name: displayName,
      pid: null,
      status: "stopped",
      cpuPercent: 0,
      memoryMB: 0,
      uptimeSeconds: 0,
      port,
      portListening: false,
      startedAt: null,
    }
  }

  try {
    const proc = await si.processes()
    const live = proc.list.find((p) => p.pid === found.pid)
    if (!live) {
      return {
        name: displayName,
        pid: found.pid,
        status: "unknown",
        cpuPercent: 0,
        memoryMB: 0,
        uptimeSeconds: 0,
        port,
        portListening: true,
        startedAt: null,
      }
    }

    const startedAt = live.started ? new Date(live.started).toISOString() : null
    const uptimeSeconds = live.started
      ? Math.floor((Date.now() - new Date(live.started).getTime()) / 1000)
      : 0

    return {
      name: displayName,
      pid: live.pid,
      status: "running",
      cpuPercent: Math.round((live.cpu || 0) * 10) / 10,
      memoryMB: Math.round(((live.mem || 0) / 1024 / 1024) * 10) / 10,
      uptimeSeconds,
      port,
      portListening: true,
      startedAt,
    }
  } catch {
    return {
      name: displayName,
      pid: found.pid,
      status: "unknown",
      cpuPercent: 0,
      memoryMB: 0,
      uptimeSeconds: 0,
      port,
      portListening: true,
      startedAt: null,
    }
  }
}

async function getSnapshot(): Promise<ProcessSnapshot> {
  const [load, mem, backend, frontend] = await Promise.all([
    si.currentLoad(),
    si.mem(),
    getProcessInfo(3000, "uvicorn", "Backend (uvicorn)"),
    getProcessInfo(3001, "next", "Frontend (next-server)"),
  ])

  return {
    timestamp: new Date().toISOString(),
    overall: {
      cpuPercent: Math.round((load.currentLoad || 0) * 10) / 10,
      memoryUsedPercent: Math.round(((mem.used / mem.total) * 100) * 10) / 10,
      memoryUsedMB: Math.round((mem.used / 1024 / 1024) * 10) / 10,
      memoryTotalMB: Math.round((mem.total / 1024 / 1024) * 10) / 10,
    },
    processes: {
      backend,
      frontend,
    },
    portChecks: {
      backend: backend.portListening,
      frontend: frontend.portListening,
    },
  }
}

// 后台定时采集
let currentSnapshot: ProcessSnapshot | null = null
let monitorInterval: NodeJS.Timeout | null = null

export function startMonitor({ intervalMs }: { intervalMs: number }) {
  if (monitorInterval) return

  // 立即采集一次
  getSnapshot()
    .then((s) => {
      currentSnapshot = s
    })
    .catch((err) => {
      console.error("[monitor] 首次采集失败:", err)
    })

  monitorInterval = setInterval(async () => {
    try {
      currentSnapshot = await getSnapshot()
    } catch (err) {
      console.error("[monitor] 采集失败:", err)
    }
  }, intervalMs)
}

export function getCurrentSnapshot(): ProcessSnapshot | null {
  return currentSnapshot
}

export function stopMonitor() {
  if (monitorInterval) {
    clearInterval(monitorInterval)
    monitorInterval = null
  }
}
