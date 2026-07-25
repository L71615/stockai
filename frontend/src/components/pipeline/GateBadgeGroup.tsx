"use client"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { ApprovalProposal, LifecycleStatus, ProposalStatus } from "@/lib/api-types"

// ════════════════════════════════════════════════════════════
//  状态颜色映射 (token-aligned, DESIGN.md oklch dark)
// ════════════════════════════════════════════════════════════

const STATUS_COLOR: Record<string, string> = {
  // lifecycle
  candidate: "bg-muted text-muted-foreground",
  validated: "bg-emerald-900/40 text-emerald-300 border-emerald-700",
  blocked:   "bg-red-900/40 text-red-300 border-red-700",
  stale:     "bg-amber-900/40 text-amber-300 border-amber-700",
  paper:     "bg-blue-900/40 text-blue-300 border-blue-700",
  champion:  "bg-violet-900/40 text-violet-300 border-violet-700",
  retired:   "bg-zinc-800 text-zinc-400",
  rejected:  "bg-zinc-800 text-zinc-400",
  // proposal status
  pending:    "bg-blue-900/40 text-blue-300 border-blue-700",
  approved:   "bg-emerald-900/40 text-emerald-300 border-emerald-700",
  expired:    "bg-amber-900/40 text-amber-300 border-amber-700",
  withdrawn:  "bg-zinc-800 text-zinc-400",
}

export function LifecycleBadge({ status }: { status: LifecycleStatus }) {
  return (
    <Badge variant="outline" className={cn("text-[10px] uppercase", STATUS_COLOR[status])}>
      {status}
    </Badge>
  )
}

export function ProposalStatusBadge({ status }: { status: ProposalStatus }) {
  return (
    <Badge variant="outline" className={cn("text-[10px] uppercase", STATUS_COLOR[status])}>
      {status}
    </Badge>
  )
}

export function GateBadgeGroup({ proposal }: { proposal: ApprovalProposal }) {
  return (
    <div className="flex flex-wrap gap-1">
      <ProposalStatusBadge status={proposal.status} />
      {proposal.target_lifecycle && (
        <Badge variant="outline" className="text-[10px]">
          → {proposal.target_lifecycle}
        </Badge>
      )}
      {proposal.target_portfolio && (
        <Badge variant="outline" className="text-[10px]">
          role: {proposal.target_portfolio}
        </Badge>
      )}
      <Badge variant="outline" className="text-[10px] font-mono">
        v{proposal.version}
      </Badge>
      <Badge variant="outline" className="text-[10px] font-mono">
        {proposal.policy_version}
      </Badge>
    </div>
  )
}