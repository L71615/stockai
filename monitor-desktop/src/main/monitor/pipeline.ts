/**
 * Pipeline 状态 — 通过 stockai /api/pipeline/status 获取
 *
 * 每 10s 拉一次
 */

import { loggedFetch } from "./logger"

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

let currentStatus: PipelineStatus = {
  timestamp: new Date().toISOString(),
  reachable: false,
  status: "unknown",
}

let probeTimer: NodeJS.Timeout | null = null

export async function getPipelineStatus(): Promise<PipelineStatus> {
  return currentStatus
}

export function startPipelineProbe(url: string, intervalMs: number) {
  if (probeTimer) return

  const probe = async () => {
    const result = await loggedFetch(url, "stockai /api/pipeline/status")
    if (result.ok && result.data) {
      const data = result.data as Record<string, unknown>
      currentStatus = {
        timestamp: new Date().toISOString(),
        reachable: true,
        status: (data.status as PipelineStatus["status"]) || "unknown",
        step: data.step as string | undefined,
        progress: data.progress as number | undefined,
        startedAt: data.started_at as string | undefined,
        finishedAt: data.finished_at as string | undefined,
        briefId: data.brief_id as string | undefined,
        errorMessage: data.error_message as string | undefined,
        raw: data,
      }
    } else {
      currentStatus = {
        timestamp: new Date().toISOString(),
        reachable: false,
        status: "unknown",
        errorMessage: result.error || `HTTP ${result.status}`,
      }
    }
  }

  probe()
  probeTimer = setInterval(probe, intervalMs)
}

export function stopPipelineProbe() {
  if (probeTimer) {
    clearInterval(probeTimer)
    probeTimer = null
  }
}