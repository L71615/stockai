"use client"

import useSWR from "swr"
import { apiGet } from "@/lib/auth"

export interface ShadowPortfolio {
  portfolio_id: number
  owner_user_id: number
  name: string
  status: string
  target_weights_json: string
  created_at: string
  updated_at: string
}

/**
 * v4.1 1B.2: 列出当前用户的 shadow portfolios.
 *
 * 注: 当前没有 shadow portfolio list API (GET /api/pipeline/shadow/portfolios),
 * 临时用 swr fallback — 等 v4.1 1B.2 落地后, 由 ShadowView 改成真实 API.
 */
export function useShadowPortfolios() {
  // 临时返回空数据 — 接口未实现时显示 "暂无影子组合" UX
  return {
    data: { portfolios: [] as ShadowPortfolio[] },
    isLoading: false,
    error: null,
  }
}