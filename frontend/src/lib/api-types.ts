export interface PortfolioHistoryPoint {
  date: string
  cost: number
  value?: number
}

export interface PortfolioHistoryResponse {
  data: PortfolioHistoryPoint[]
}

export interface PortfolioHolding {
  id: number
  stock_code: string
  stock_name: string
  asset_type: string
  portfolio_id: number | null
  quantity: number
  cost_price: number
  current_price: number | null
  market_value?: number | null
  pnl: number | null
  pnl_pct: number | null
  industry?: string
  sector?: string
}

export interface PortfolioSummary {
  total_cost: number
  total_value: number
  total_pnl: number
  total_pnl_pct: number
  today_pnl: number
  profit_count: number
  loss_count: number
}

export interface PortfolioData {
  holdings: PortfolioHolding[]
  summary: PortfolioSummary
}

export interface DiversificationSlice {
  name: string
  value: number
  count: number
  market_value: number
  pct: number
  color?: string
}

export interface DiversificationResponse {
  by_industry: DiversificationSlice[]
  by_asset?: DiversificationSlice[]
}

export interface ReviewDimension {
  title: string
  score: string
  summary: string
  detail: string
}

export interface ReviewSuggestion {
  text: string
  reasoning: string
}

export interface ReviewItem {
  id?: number
  created_at?: string
  total_pnl?: number
  trade_count?: number
  avg_score?: number
  ai_headline?: string
  dimensions?: ReviewDimension[]
  suggestions?: ReviewSuggestion[]
}

export interface WatchlistItem {
  id: number
  stock_code: string
  stock_name: string
  market: string
  asset_type: string
  price?: number
  name?: string
  change?: number
  change_pct?: number
  volume?: number
  high?: number
  low?: number
}

export interface KlineResponse {
  dates?: string[]
  opens?: number[]
  highs?: number[]
  lows?: number[]
  closes?: number[]
  volumes?: number[]
  ma5?: Array<number | null>
  ma10?: Array<number | null>
  ma20?: Array<number | null>
}

export interface ScreenerStatusResponse {
  running: boolean
  progress: number
  total: number
  has_result: boolean
}

// ── /browse 页面（v3.9 全市场浏览）──

export type SectorKey =
  | "main_sh"
  | "main_sz"
  | "gem"
  | "star"
  | "bse"
  | "nq"
  | "etf"
  | "index"
  | "other"

export type IntegrityStatus = "fresh" | "stale" | "missing"

export interface BrowseStock {
  code: string
  name: string
  industry: string
  sector: SectorKey
  sector_label: string
  latest_date: string | null
  latest_close: number | null
  prev_close: number | null
  change_pct: number | null
  volume: number | null
  kline_count: number
  days_ago: number | null
  integrity: IntegrityStatus
}

export interface BrowseSector {
  sector: SectorKey
  label: string
  total: number
  fresh_count: number
  stale_count: number
  missing_count: number
  fresh_pct: number
  stocks: BrowseStock[]
}

export interface BrowseStocksResponse {
  total: number
  sectors: BrowseSector[]
  sector_labels: Record<string, string>
  as_of: string
}

export interface LagBucket {
  bucket: string
  count: number
}

export interface FreshnessSector {
  sector: SectorKey
  label: string
  stock_count: number
  latest_date: string | null
  days_ago: number | null
  status: IntegrityStatus
  lag_distribution: Record<string, number>
}

export interface FreshnessResponse {
  as_of: string
  total_stocks: number
  fresh_stocks: number
  fresh_pct: number
  sectors: FreshnessSector[]
}

export interface SectorPerformanceItem {
  industry: string
  /** @deprecated 用 n_total / n_with_data */
  stock_count: number
  /** 行业总股票数（来自 stock_info） */
  n_total: number
  /** 有完整 (今日+昨日) K 线的股票数（参与均值计算的） */
  n_with_data: number
  /** 数据完整率：n_with_data / n_total (%) */
  data_pct: number
  avg_change_pct: number
}

export interface SectorPerformanceResponse {
  as_of: string
  days: number
  industries: SectorPerformanceItem[]
}

export interface SparklineResponse {
  code: string
  days: number
  dates: string[]
  closes: number[]
  min: number
  max: number
  change_pct: number
}

export interface SyncTaskResponse {
  task_id: string
  scope: string
  sector: string
  target_count: number
  message: string
}

export interface SyncStatusResponse {
  task_id: string
  status: "running" | "done"
  total: number
  completed: number
  failed: number
  percent: number
  started_at: string
  finished_at: string | null
}

// ════════════════════════════════════════════════════════════
//  v3.11 (T6): /pipeline 审批收件箱类型
// ════════════════════════════════════════════════════════════

export type LifecycleStatus =
  | "candidate" | "validated" | "blocked" | "stale" | "rejected"
  | "paper" | "champion" | "retired"

export type PortfolioRole =
  | "none" | "baseline" | "paper" | "champion" | "challenger"

export type ProposalStatus =
  | "pending" | "approved" | "rejected" | "expired" | "withdrawn"

export interface Experiment {
  experiment_id: string
  owner_user_id: number
  expr_text: string
  candidate_id: number | null
  policy_version: string
  snapshot_hash: string
  lifecycle_status: LifecycleStatus
  portfolio_role: PortfolioRole
  proposal_status: ProposalStatus
  version: number
  snapshot_json: string
  note: string
  created_at: string
  updated_at: string
}

export interface ExperimentListResponse {
  experiments: Experiment[]
  count: number
}

export interface ExperimentEvent {
  event_id: number
  experiment_id: string
  run_id: number | null
  actor: string
  event_type: string
  from_state: string | null
  to_state: string | null
  from_version: number | null
  to_version: number | null
  reason: string
  evidence_version: string
  created_at: string
}

export interface ExperimentEventsResponse {
  events: ExperimentEvent[]
}

export interface ApprovalProposal {
  proposal_id: number
  experiment_id: string
  candidate_id: number | null
  owner_user_id: number
  evidence_version: string
  candidate_version: number
  experiment_version: number
  action: string
  target_lifecycle: string | null
  target_portfolio: string | null
  target_proposal: string | null
  policy_version: string
  policy_hash: string
  snapshot_hash: string
  lease_id: string
  lease_expires_at: string | null
  status: ProposalStatus
  decided_at: string | null
  decided_by: string | null
  decision_reason: string
  version: number
  created_at: string
  updated_at: string
}

export interface ApprovalListResponse {
  proposals: ApprovalProposal[]
  count: number
}

export interface ApprovalAttempt {
  attempt_id: number
  proposal_id: number
  lease_id: string
  action: string
  actor: string
  result: string            // "ok" | "conflict"
  error_json: string
  expected_version: number
  current_version: number
  created_at: string
}

export interface ApprovalAttemptsResponse {
  attempts: ApprovalAttempt[]
  proposal_id: number
}

export interface CreateProposalRequest {
  experiment_id: string
  action?: string
  target_lifecycle?: string
  target_portfolio?: string
  target_proposal?: string
  candidate_id?: number
  evidence_version?: string
  policy_version?: string
  policy_hash?: string
  snapshot_hash?: string
  lease_ttl_seconds?: number
}

export interface DecisionRequest {
  expected_version: number
  lease_id: string
  reason?: string
}

export interface ShadowPortfolio {
  portfolio_id: number
  owner_user_id: number
  experiment_id: string | null
  candidate_id: number | null
  name: string
  policy_version: string
  initial_cash: number
  target_weights: Record<string, number>
  scope: string
  status: string
  created_at: string
  updated_at: string
}

export interface ShadowPortfolioListResponse {
  portfolios: ShadowPortfolio[]
  count: number
}

export interface ShadowSnapshot {
  snapshot_id: number
  portfolio_id: number
  observation_date: string
  nav: number
  cash: number
  holdings: Record<string, number>
  target_weights: Record<string, number>
  actual_weights: Record<string, number>
  turnover: number
  costs: number
  drawdown: number
  baseline_diff: Record<string, number>
  status: string           // "settled" | "stale" | "blocked"
  reason: string
  input_version: string
  created_at: string
}

export interface ShadowSnapshotsResponse {
  snapshots: ShadowSnapshot[]
  count: number
}

// ════════════════════════════════════════════════════════════
// v4.1 1B.4 — Holdings vs Shadow Portfolio Comparison Card
// ════════════════════════════════════════════════════════════

export type WindowKey = "7d" | "30d" | "90d" | "180d"
export type DiffSide = "both" | "actual_only" | "shadow_only" | "aligned_zero"

export interface HoldingVsShadowSide {
  quantity: number | null
  cost_price: number | null
  last_price: number | null
  market_value: number | null
  pnl: number | null
  pnl_pct: number | null
  today_pnl: number | null
  weight_pct: number | null
}

export interface HoldingVsShadowDiff {
  stock_code: string
  stock_name: string
  actual: HoldingVsShadowSide
  shadow: HoldingVsShadowSide
  delta_qty: number | null
  delta_market_value: number | null
  diff_side: DiffSide
}

export interface PortfolioComparisonSummary {
  market_value: number
  cost_basis: number
  pnl: number
  pnl_pct: number
  today_pnl: number
}

export interface ShadowComparisonSummary {
  nav: number
  cash: number
  market_value: number
  delta_nav: number
  delta_nav_pct: number
}

export interface PortfolioComparisonDiffSummary {
  value_gap: number
  value_gap_pct: number
  position_overlap_count: number
  actual_only_count: number
  shadow_only_count: number
}

export interface PortfolioComparisonResponse {
  window_days: number
  shadow_portfolio_id: number | null
  shadow_portfolio_name: string | null
  snapshot_date: string | null
  accumulating: boolean
  snapshot_count: number
  snapshot_target: number
  actual: PortfolioComparisonSummary
  shadow: ShadowComparisonSummary
  diff_summary: PortfolioComparisonDiffSummary
  rows: HoldingVsShadowDiff[]
  message?: string
}

// ── v5.1: AI 录入交易 ──

export interface AIParsedTransaction {
  code: string
  stock_name?: string
  direction: "buy" | "sell"
  quantity: number
  price: number
  date: string
  note?: string
}

export interface AIParseError {
  line: number
  raw: string
  reason: string
}

export interface AIParseSummary {
  input_lines: number
  parsed_ok: number
  parse_failed: number
  validation_failed: number
}

export interface AIParseResponse {
  template: string
  transactions: AIParsedTransaction[]
  errors: AIParseError[]
  summary: AIParseSummary
}

export interface BulkTransactionItem {
  stock_code: string
  direction: "buy" | "sell"
  quantity: number
  price: number
  traded_at: string
  note?: string
}

export interface BulkTransactionInserted extends BulkTransactionItem {
  id: number
  stock_name: string
  amount: number
  fee: number
}

export interface BulkTransactionResponse {
  message: string
  inserted: BulkTransactionInserted[]
  holding_updates: Record<string, { stock_code: string; quantity: number; cost_price: number }>
}
