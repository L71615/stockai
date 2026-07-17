"use client"

/**
 * usePersistedState — useState 的 sessionStorage 持久化版本
 *
 * 解决问题: Next.js 路由切换会卸载组件 → state 丢失
 * 解决: state 变化时同步到 sessionStorage, 重新挂载时从 sessionStorage 恢复
 *
 * 持久化范围:
 *   ✅ 同一 tab 跨 F5 刷新
 *   ✅ 同一 tab 跨路由切换
 *   ❌ 关闭 tab 再开 (sessionStorage 生命周期 = tab 生命周期)
 *
 * 用法:
 *   const [tab, setTab] = usePersistedState("quant:tab", "insight")
 */
import { useState, useEffect, useRef } from "react"

export function usePersistedState<T>(
  key: string,
  defaultValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  // 初始值: 优先 sessionStorage, fallback defaultValue
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") return defaultValue
    try {
      const stored = sessionStorage.getItem(key)
      if (stored === null) return defaultValue
      return JSON.parse(stored) as T
    } catch {
      return defaultValue
    }
  })

  // 防抖写: 避免每次 setState 都立即写 storage (滚动等高频操作)
  const timerRef = useRef<NodeJS.Timeout | null>(null)
  useEffect(() => {
    if (typeof window === "undefined") return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      try {
        sessionStorage.setItem(key, JSON.stringify(value))
      } catch (e) {
        // quota 满 / 序列化失败, 静默
        console.warn(`usePersistedState: save failed for ${key}`, e)
      }
    }, 100)  // 100ms debounce
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [key, value])

  return [value, setValue]
}

/**
 * 主动清空某个 key (例如: 用户点了"重置筛选")
 */
export function clearPersistedState(key: string) {
  if (typeof window === "undefined") return
  try {
    sessionStorage.removeItem(key)
  } catch {
    // ignore
  }
}

/**
 * 列出所有 usePersistedState 用的 key (用于调试)
 */
export function listPersistedKeys(prefix: string): string[] {
  if (typeof window === "undefined") return []
  const keys: string[] = []
  for (let i = 0; i < sessionStorage.length; i++) {
    const k = sessionStorage.key(i)
    if (k && k.startsWith(prefix)) keys.push(k)
  }
  return keys
}