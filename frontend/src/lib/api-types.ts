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
  stock_count: number
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
