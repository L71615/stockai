"use client"

import { SWRConfig } from "swr"
import { apiGet } from "./auth"

/**
 * SWR 全局 fetcher — 包装 apiGet，返回数据或抛错
 * swr 期望 fetcher 返回 data 或 throw error（status 不在 2xx 范围时）
 */
export async function swrFetcher<T>(url: string): Promise<T> {
  const data = await apiGet<T>(url)
  return data as T
}

/**
 * 全局 SWR 配置
 *
 * - dedupingInterval: 2s 内同 key 请求自动去重
 * - focusThrottleInterval: 10s 窗口聚焦不触发全量重验
 * - revalidateOnFocus: 开启（标签页切回自动刷新）
 * - errorRetryCount: 3 次（网络波动自动重试）
 * - refreshInterval: 0（默认不轮询，需要轮询的页面自行设置）
 */
export const SWR_GLOBAL_CONFIG = {
  fetcher: swrFetcher,
  dedupingInterval: 5000,          // 5s 去重（原来 2s 太短）
  focusThrottleInterval: 30000,    // 30s 内切回不再全量刷新（原来 10s）
  revalidateOnFocus: false,        // 关闭切回刷新（最大头：多 tab 切换时所有 hook 同时发请求）
  revalidateOnReconnect: false,    // 网络恢复不触发全量刷新
  errorRetryCount: 3,
  errorRetryInterval: 5000,
  refreshInterval: 0,
}

/**
 * SWR Provider — 在 layout 中包裹 children
 */
export function SWRProvider({ children }: { children: React.ReactNode }) {
  return <SWRConfig value={SWR_GLOBAL_CONFIG}>{children}</SWRConfig>
}
