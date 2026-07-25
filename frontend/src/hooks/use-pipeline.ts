"use client"

import useSWR from "swr"
import { apiGet, apiPost } from "@/lib/auth"
import { swrFetcher } from "@/lib/swr-config"
import type {
  ApprovalListResponse,
  ApprovalProposal,
  ApprovalAttemptsResponse,
  CreateProposalRequest,
  DecisionRequest,
  ExperimentListResponse,
  ShadowPortfolioListResponse,
  ShadowSnapshotsResponse,
} from "@/lib/api-types"

/**
 * Pipeline 收件箱 — 3 个 fetcher + mutation helpers.
 *
 * 30s 自动刷新, 5s 去重, 与其它 hook 保持一致.
 * mutation 后用 mutate() 主动失效相关 SWR 缓存.
 */

// ════════════════════════════════════════════════════════════
//  Proposals (审批收件箱)
// ════════════════════════════════════════════════════════════

export function useProposals(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ""
  return useSWR<ApprovalListResponse>(
    `/api/pipeline/proposals${qs}`,
    swrFetcher,
    { refreshInterval: 30000, dedupingInterval: 5000 },
  )
}

export function useProposalDetail(proposalId: number | null) {
  return useSWR<ApprovalProposal>(
    proposalId ? `/api/pipeline/proposals/${proposalId}` : null,
    swrFetcher,
  )
}

export function useProposalAttempts(proposalId: number | null) {
  return useSWR<ApprovalAttemptsResponse>(
    proposalId ? `/api/pipeline/proposals/${proposalId}/attempts` : null,
    swrFetcher,
  )
}

// ════════════════════════════════════════════════════════════
//  Experiments (实验查询)
// ════════════════════════════════════════════════════════════

export function useExperiments(filters?: {
  lifecycle_status?: string
  portfolio_role?: string
  proposal_status?: string
}) {
  const qs = filters
    ? "?" + Object.entries(filters)
        .filter(([, v]) => !!v)
        .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
        .join("&")
    : ""
  return useSWR<ExperimentListResponse>(
    `/api/pipeline/experiments${qs}`,
    swrFetcher,
    { dedupingInterval: 10000 },
  )
}

// ════════════════════════════════════════════════════════════
//  Shadow portfolios (影子组合查询)
// ════════════════════════════════════════════════════════════

export function useShadowPortfolios() {
  return useSWR<ShadowPortfolioListResponse>(
    "/api/pipeline/shadow",
    swrFetcher,
    { refreshInterval: 30000 },
  )
}

export function useShadowSnapshots(portfolioId: number | null) {
  return useSWR<ShadowSnapshotsResponse>(
    portfolioId ? `/api/pipeline/shadow/${portfolioId}/snapshots` : null,
    swrFetcher,
  )
}

// ════════════════════════════════════════════════════════════
//  Mutations (操作 API)
// ════════════════════════════════════════════════════════════

export async function createProposal(body: CreateProposalRequest): Promise<ApprovalProposal> {
  return apiPost<ApprovalProposal>("/api/pipeline/proposals", body)
}

export type DecisionAction = "approve" | "reject" | "later" | "withdraw"

export async function submitDecision(
  proposalId: number,
  action: DecisionAction,
  body: DecisionRequest,
): Promise<ApprovalProposal> {
  return apiPost<ApprovalProposal>(
    `/api/pipeline/proposals/${proposalId}/${action}`,
    body,
  )
}

export async function reopenProposal(proposalId: number, ttlSeconds = 86400) {
  return apiPost<ApprovalProposal>(
    `/api/pipeline/proposals/${proposalId}/reopen`,
    { lease_ttl_seconds: ttlSeconds },
  )
}

// ════════════════════════════════════════════════════════════
//  工具: 计算 lease 剩余时间 (秒)
// ════════════════════════════════════════════════════

export function leaseRemainingSeconds(leaseExpiresAt: string | null): number {
  if (!leaseExpiresAt) return 0
  const expires = new Date(leaseExpiresAt.replace(" ", "T")).getTime()
  const now = Date.now()
  return Math.max(0, Math.floor((expires - now) / 1000))
}

export function formatLeaseRemaining(seconds: number): string {
  if (seconds <= 0) return "已过期"
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}