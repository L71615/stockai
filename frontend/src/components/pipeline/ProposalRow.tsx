"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  IconCheck, IconX, IconClock, IconAlertCircle, IconRefresh,
} from "@tabler/icons-react"
import type { ApprovalProposal } from "@/lib/api-types"
import { GateBadgeGroup } from "./GateBadgeGroup"
import {
  submitDecision, reopenProposal,
  leaseRemainingSeconds, formatLeaseRemaining,
} from "@/hooks/use-pipeline"

// ════════════════════════════════════════════════════════════
//  ProposalRow — 单条审批提案行 (桌面 table-row + 移动 card)
// ════════════════════════════════════════════════════════════

interface ProposalRowProps {
  proposal: ApprovalProposal
  onDecided?: () => void  // 决策后回调, 让父组件刷新 SWR
}

export function ProposalRow({ proposal, onDecided }: ProposalRowProps) {
  const [submitting, setSubmitting] = useState<"" | "approve" | "reject" | "later" | "reopen">("")
  const [error, setError] = useState<string | null>(null)

  const leaseSeconds = leaseRemainingSeconds(proposal.lease_expires_at)
  const leaseExpired = proposal.status === "pending" && leaseSeconds <= 0
  const isTerminal = proposal.status !== "pending" && proposal.status !== "expired"

  async function doAction(action: "approve" | "reject" | "later") {
    setSubmitting(action)
    setError(null)
    try {
      await submitDecision(proposal.proposal_id, action, {
        expected_version: proposal.version,
        lease_id: proposal.lease_id,
        reason: `user ${action}`,
      })
      onDecided?.()
    } catch (e: any) {
      setError(e?.message || `${action} 失败`)
    } finally {
      setSubmitting("")
    }
  }

  async function doReopen() {
    setSubmitting("reopen")
    setError(null)
    try {
      await reopenProposal(proposal.proposal_id)
      onDecided?.()
    } catch (e: any) {
      setError(e?.message || "reopen 失败")
    } finally {
      setSubmitting("")
    }
  }

  return (
    <div
      className={cn(
        "border border-border p-3 space-y-2",
        "transition-colors hover:bg-accent/30",
      )}
    >
      {/* 头: ID + expr + 状态 badges */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">#{proposal.proposal_id}</span>
        <code className="font-mono text-xs truncate max-w-[300px]">
          {proposal.action} :: exp={proposal.experiment_id.slice(-12)}
        </code>
        <GateBadgeGroup proposal={proposal} />
      </div>

      {/* 中: evidence 摘要 + 决策理由 */}
      <div className="text-xs space-y-1">
        <div className="text-muted-foreground">
          evidence: <span className="font-mono">{proposal.evidence_version || "—"}</span>
          {" "}· candidate v<span className="font-mono">{proposal.candidate_version}</span>
          {" "}· exp v<span className="font-mono">{proposal.experiment_version}</span>
        </div>
        {proposal.decision_reason && (
          <div className="text-muted-foreground italic">
            {proposal.decision_reason}
          </div>
        )}
        {error && (
          <div className="text-red-400 flex items-center gap-1">
            <IconAlertCircle className="h-3 w-3" />
            {error}
          </div>
        )}
      </div>

      {/* 尾: lease 倒计时 + 三个按钮 */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border">
        <div className="flex items-center gap-2 text-xs">
          {proposal.status === "pending" && !leaseExpired && (
            <Badge variant="outline" className="font-mono">
              ⏱ {formatLeaseRemaining(leaseSeconds)}
            </Badge>
          )}
          {leaseExpired && proposal.status === "pending" && (
            <Badge variant="outline" className="bg-red-900/40 text-red-300 border-red-700 font-mono">
              ⏱ 已过期
            </Badge>
          )}
          {proposal.status === "approved" && (
            <Badge variant="outline" className="bg-emerald-900/40 text-emerald-300 border-emerald-700">
              by {proposal.decided_by?.slice(0, 16)}
            </Badge>
          )}
          {proposal.status === "rejected" && (
            <Badge variant="outline" className="bg-zinc-800 text-zinc-400">
              rejected
            </Badge>
          )}
          {proposal.status === "withdrawn" && (
            <Badge variant="outline" className="bg-zinc-800 text-zinc-400">
              withdrawn
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* 已决定 + 未过期: 不显示按钮 */}
          {isTerminal && !leaseExpired ? null : (
            <>
              {/* 过期 + 还能 reopen: 只显示 reopen */}
              {leaseExpired ? (
                <Button
                  size="sm" variant="outline"
                  onClick={doReopen}
                  disabled={!!submitting}
                  className="min-h-[44px] min-w-[44px]"
                >
                  <IconRefresh className="h-4 w-4 mr-1" />
                  {submitting === "reopen" ? "重开中..." : "重开发 lease"}
                </Button>
              ) : (
                <>
                  <Button
                    size="sm"
                    onClick={() => doAction("approve")}
                    disabled={!!submitting}
                    className="min-h-[44px]"
                  >
                    <IconCheck className="h-4 w-4 mr-1" />
                    {submitting === "approve" ? "..." : "接受"}
                  </Button>
                  <Button
                    size="sm" variant="outline"
                    onClick={() => doAction("reject")}
                    disabled={!!submitting}
                    className="min-h-[44px]"
                  >
                    <IconX className="h-4 w-4 mr-1" />
                    {submitting === "reject" ? "..." : "拒绝"}
                  </Button>
                  <Button
                    size="sm" variant="ghost"
                    onClick={() => doAction("later")}
                    disabled={!!submitting}
                    className="min-h-[44px]"
                  >
                    <IconClock className="h-4 w-4 mr-1" />
                    {submitting === "later" ? "..." : "稍后"}
                  </Button>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
//  Skeleton (loading state)
// ════════════════════════════════════════════════════════════

export function ProposalRowSkeleton() {
  return (
    <div className="border border-border p-3 space-y-2">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-3 w-1/2" />
      <Skeleton className="h-8 w-1/4" />
    </div>
  )
}