/**
 * 5s 轮询 hook
 */

import { useEffect } from "react"
import { getSnapshot } from "../lib/api"
import { useState } from "react"
import type { ProcessSnapshot } from "../../../main/monitor/process"

export function useMonitor(intervalMs = 5000) {
  const [snapshot, setSnapshot] = useState<ProcessSnapshot | null>(null)
  const [paused, setPaused] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchOnce() {
      try {
        const s = await getSnapshot()
        if (!cancelled) {
          setSnapshot(s)
          setLastUpdate(new Date())
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "采集失败")
        }
      }
    }

    fetchOnce()

    if (paused) return

    const timer = setInterval(fetchOnce, intervalMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [intervalMs, paused])

  return { snapshot, paused, setPaused, error, lastUpdate }
}
