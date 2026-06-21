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
