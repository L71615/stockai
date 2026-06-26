"use client"

import { useEffect, useMemo, useRef, useState, useCallback } from "react"
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  type IPriceLine,
} from "lightweight-charts"
import type { KlineResponse } from "@/lib/api-types"

// ═══════════════════════════════════════════════════════════════
//  Types
// ═══════════════════════════════════════════════════════════════

interface KlineBar {
  date: string; open: number; high: number; low: number
  close: number; volume: number
  ma5: number | null; ma10: number | null; ma20: number | null
}

/** 可选叠加指标 — 全部前端计算 */
export type IndicatorPane =
  | "volume"     // 成交量柱
  | "bollinger"  // 布林带 (叠加在价格面板)
  | "macd"       // MACD 柱 + DIF/DEA
  | "rsi"        // RSI 线 + 70/30 参考线
  | "kdj"        // KDJ 三线

/** 指标讲解条 */
export interface IndicatorExplanation {
  key: IndicatorPane
  label: string
  color: string
  value: string
  interpretation: string
  signal: "bullish" | "bearish" | "neutral"
}

export interface TurtleOverlay {
  sys1_entry: number | null
  sys2_entry: number | null
  sys1_exit: number | null
  sys2_exit: number | null
  sys1_triggered: boolean
  sys2_triggered: boolean
}

export interface KlineChartProps {
  rawData: KlineResponse
  height?: number
  /** 要显示的指标面板 (受控模式；不传则内部管理，默认从localStorage读取) */
  indicators?: IndicatorPane[]
  /** 指标变更回调 (受控模式) */
  onIndicatorsChange?: (val: IndicatorPane[]) => void
  /** 是否显示内嵌指标选择器 (默认 true) */
  showIndicatorSelector?: boolean
  /** 海龟通道线叠加 */
  turtleOverlay?: TurtleOverlay
}

// ═══════════════════════════════════════════════════════════════
//  Data conversion
// ═══════════════════════════════════════════════════════════════

function toChartBars(raw: KlineResponse): KlineBar[] {
  const { dates, opens, highs, lows, closes, volumes, ma5, ma10, ma20 } = raw
  if (!dates) return []
  return dates.map((dt: string, i: number) => ({
    date: dt,
    open: opens?.[i] ?? closes?.[i] ?? 0,
    high: highs?.[i] ?? closes?.[i] ?? 0,
    low: lows?.[i] ?? closes?.[i] ?? 0,
    close: closes?.[i] ?? 0,
    volume: volumes?.[i] ?? 0,
    ma5: ma5?.[i] ?? null,
    ma10: ma10?.[i] ?? null,
    ma20: ma20?.[i] ?? null,
  }))
}

// ═══════════════════════════════════════════════════════════════
//  Indicator calculators (O(N) sliding window)
// ═══════════════════════════════════════════════════════════════

function calcSMA(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period - 1) {
      if (i >= period) sum -= values[i - period]
      result[i] = sum / period
    }
  }
  return result
}

function calcEMA(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(values.length).fill(null)
  const k = 2 / (period + 1)
  for (let i = 0; i < values.length; i++) {
    if (i === 0) { result[i] = values[i]; continue }
    const prev = result[i - 1] ?? values[i]
    result[i] = values[i] * k + prev * (1 - k)
  }
  return result
}

interface BollingerResult {
  mid: (number | null)[]; upper: (number | null)[]; lower: (number | null)[]
}

function calcBollinger(closes: number[], period: number = 20, mult: number = 2): BollingerResult {
  const mid = calcSMA(closes, period)
  const upper: (number | null)[] = new Array(closes.length).fill(null)
  const lower: (number | null)[] = new Array(closes.length).fill(null)
  for (let i = period - 1; i < closes.length; i++) {
    let sumSq = 0
    for (let j = i - period + 1; j <= i; j++) {
      sumSq += (closes[j] - (mid[i] ?? 0)) ** 2
    }
    const std = Math.sqrt(sumSq / period)
    upper[i] = (mid[i] ?? 0) + mult * std
    lower[i] = (mid[i] ?? 0) - mult * std
  }
  return { mid, upper, lower }
}

interface MACDResult {
  dif: (number | null)[]; dea: (number | null)[]; histogram: (number | null)[]
}

function calcMACD(closes: number[], fast: number = 12, slow: number = 26, signal: number = 9): MACDResult {
  const emaFast = calcEMA(closes, fast)
  const emaSlow = calcEMA(closes, slow)
  const dif: (number | null)[] = closes.map((_, i) => {
    if (emaFast[i] == null || emaSlow[i] == null) return null
    return emaFast[i]! - emaSlow[i]!
  })
  const dea = calcEMA(dif.filter((v): v is number => v != null), signal)
  // pad dea to match
  const deaPadded: (number | null)[] = new Array(closes.length).fill(null)
  let di = 0
  for (let i = 0; i < closes.length; i++) {
    if (dif[i] != null) deaPadded[i] = dea[di++] ?? null
  }
  const histogram = closes.map((_, i) => {
    if (dif[i] == null || deaPadded[i] == null) return null
    return (dif[i]! - deaPadded[i]!) * 2
  })
  return { dif, dea: deaPadded, histogram }
}

function calcRSI(closes: number[], period: number = 14): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length < period + 1) return result
  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1]
    if (delta > 0) avgGain += delta
    else avgLoss += -delta
  }
  avgGain /= period; avgLoss /= period
  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1]
    const gain = delta > 0 ? delta : 0
    const loss = delta < 0 ? -delta : 0
    avgGain = (avgGain * (period - 1) + gain) / period
    avgLoss = (avgLoss * (period - 1) + loss) / period
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return result
}

function calcKDJ(
  highs: number[], lows: number[], closes: number[],
  period: number = 9
): { k: (number | null)[]; d: (number | null)[]; j: (number | null)[] } {
  const n = closes.length
  const k: (number | null)[] = new Array(n).fill(null)
  const d: (number | null)[] = new Array(n).fill(null)
  const j: (number | null)[] = new Array(n).fill(null)
  let prevK = 50, prevD = 50
  for (let i = period - 1; i < n; i++) {
    let highest = highs[i], lowest = lows[i]
    for (let t = i - period + 1; t <= i; t++) {
      if (highs[t] > highest) highest = highs[t]
      if (lows[t] < lowest) lowest = lows[t]
    }
    const rsv = lowest === highest ? 50 : ((closes[i] - lowest) / (highest - lowest)) * 100
    prevK = prevK * 2 / 3 + rsv / 3
    prevD = prevD * 2 / 3 + prevK / 3
    k[i] = prevK; d[i] = prevD; j[i] = 3 * prevK - 2 * prevD
  }
  return { k, d, j }
}

// ═══════════════════════════════════════════════════════════════
//  Indicator explanation builder
// ═══════════════════════════════════════════════════════════════

function buildExplanations(bars: KlineBar[], indicators: IndicatorPane[]): IndicatorExplanation[] {
  if (!bars.length || !indicators.length) return []

  const n = bars.length - 1  // latest bar index
  const closes = bars.map(b => b.close)
  const highs = bars.map(b => b.high)
  const lows = bars.map(b => b.low)
  const volumes = bars.map(b => b.volume)

  const results: IndicatorExplanation[] = []

  for (const ind of indicators) {
    switch (ind) {
      case "volume": {
        const volMA5 = calcSMA(volumes, 5)
        const vol = volumes[n]
        const ma5 = volMA5[n]
        const ratio = ma5 && ma5 > 0 ? vol / ma5 : 1
        const volStr = vol >= 1e8 ? `${(vol / 1e8).toFixed(2)}亿`
          : vol >= 1e4 ? `${(vol / 1e4).toFixed(0)}万` : `${vol}`
        results.push({
          key: "volume", label: "VOL", color: "#6b7280",
          value: volStr,
          interpretation: ratio > 1.5 ? "📈 放量" : ratio < 0.5 ? "📉 缩量" : "正常",
          signal: ratio > 1.5 ? "bullish" : ratio < 0.5 ? "bearish" : "neutral",
        })
        break
      }
      case "bollinger": {
        const bb = calcBollinger(closes)
        const price = closes[n]
        const upper = bb.upper[n]
        const mid = bb.mid[n]
        const lower = bb.lower[n]
        let pos = "中轨附近"
        let signal: IndicatorExplanation["signal"] = "neutral"
        if (upper != null && price > upper) { pos = "突破上轨 ↑"; signal = "bullish" }
        else if (lower != null && price < lower) { pos = "跌破下轨 ↓"; signal = "bearish" }
        else if (upper != null && lower != null) {
          const bandwidth = ((upper - lower) / (mid ?? price)) * 100
          if (bandwidth < 5) pos = "收窄待变"
        }
        results.push({
          key: "bollinger", label: "BOLL", color: "#06b6d4",
          value: mid != null ? `${mid.toFixed(2)}` : "-",
          interpretation: pos,
          signal,
        })
        break
      }
      case "macd": {
        const macd = calcMACD(closes)
        const dif = macd.dif[n]
        const dea = macd.dea[n]
        const hist = macd.histogram[n]
        let interp = ""
        let signal: IndicatorExplanation["signal"] = "neutral"
        if (dif != null && dea != null) {
          if (dif > dea) { interp = "多头排列 ↑"; signal = "bullish" }
          else { interp = "空头排列 ↓"; signal = "bearish" }

          // Check for golden/death cross (compare with previous)
          const difPrev = n > 0 ? macd.dif[n-1] : null
          const deaPrev = n > 0 ? macd.dea[n-1] : null
          if (difPrev != null && deaPrev != null) {
            if (difPrev <= deaPrev && dif > dea) interp = "🔴 金叉 ↑"
            else if (difPrev >= deaPrev && dif < dea) interp = "🟢 死叉 ↓"
          }
        }
        const difStr = dif != null ? dif.toFixed(3) : "-"
        const deaStr = dea != null ? dea.toFixed(3) : "-"
        const histStr = hist != null ? (hist > 0 ? `+${hist.toFixed(3)}` : hist.toFixed(3)) : ""
        results.push({
          key: "macd", label: "MACD", color: "#f59e0b",
          value: `DIF ${difStr} DEA ${deaStr}${histStr ? ` | ${histStr}` : ""}`,
          interpretation: interp,
          signal,
        })
        break
      }
      case "rsi": {
        const rsi = calcRSI(closes, 14)
        const v = rsi[n]
        let interp = ""
        let signal: IndicatorExplanation["signal"] = "neutral"
        if (v != null) {
          if (v > 80) { interp = "严重超买 ⚠️"; signal = "bearish" }
          else if (v > 70) { interp = "超买区"; signal = "bearish" }
          else if (v < 20) { interp = "严重超卖 💡"; signal = "bullish" }
          else if (v < 30) { interp = "超卖区"; signal = "bullish" }
          else if (v > 50) { interp = "偏强"; signal = "bullish" }
          else { interp = "偏弱"; signal = "bearish" }
        }
        results.push({
          key: "rsi", label: "RSI", color: "#06b6d4",
          value: v != null ? v.toFixed(1) : "-",
          interpretation: interp,
          signal,
        })
        break
      }
      case "kdj": {
        const kdj = calcKDJ(highs, lows, closes, 9)
        const k = kdj.k[n]
        const d = kdj.d[n]
        const j = kdj.j[n]
        let interp = ""
        let signal: IndicatorExplanation["signal"] = "neutral"
        if (k != null && d != null && j != null) {
          if (k > 80 && d > 80) { interp = "高位钝化 ⚠️"; signal = "bearish" }
          else if (k < 20 && d < 20) { interp = "低位区 💡"; signal = "bullish" }
          else if (j > 100) { interp = "J值超百 ⚠️"; signal = "bearish" }
          else if (j < 0) { interp = "J值负值 💡"; signal = "bullish" }

          // Golden/death cross
          const kPrev = n > 0 ? kdj.k[n-1] : null
          const dPrev = n > 0 ? kdj.d[n-1] : null
          if (kPrev != null && dPrev != null) {
            if (kPrev <= dPrev && k > d) interp = "🔴 金叉 ↑"
            else if (kPrev >= dPrev && k < d) interp = "🟢 死叉 ↓"
          }
        }
        const kStr = k != null ? k.toFixed(1) : "-"
        const dStr = d != null ? d.toFixed(1) : "-"
        const jStr = j != null ? j.toFixed(1) : "-"
        results.push({
          key: "kdj", label: "KDJ", color: "#8b5cf6",
          value: `K ${kStr} D ${dStr} J ${jStr}`,
          interpretation: interp,
          signal,
        })
        break
      }
    }
  }
  return results
}

// ═══════════════════════════════════════════════════════════════
//  Pane height ratios (from stock-analyst-ui)
// ═══════════════════════════════════════════════════════════════

const PANE_RATIOS: Record<string, number> = {
  price: 2.0,
  volume: 0.5,
  macd: 0.7,
  rsi: 0.5,
  kdj: 0.5,
}

function getPaneHeights(indicators: IndicatorPane[], totalHeight: number): Record<string, number> {
  // Always have price pane
  const keys = ["price", ...indicators.map((i) => i === "bollinger" ? "price" : i).filter((k, idx, arr) => arr.indexOf(k) === idx)]
  const totalWeight = keys.reduce((s, k) => s + (PANE_RATIOS[k] ?? 0.5), 0)
  const unit = totalHeight / totalWeight
  const result: Record<string, number> = {}
  for (const k of keys) {
    result[k] = Math.round(unit * (PANE_RATIOS[k] ?? 0.5))
  }
  return result
}

// ═══════════════════════════════════════════════════════════════
//  Main component
// ═══════════════════════════════════════════════════════════════

const DEFAULT_INDICATORS: IndicatorPane[] = ["volume", "macd"]
const INDICATOR_STORAGE_KEY = "klinechart-indicators-v1"
const ALL_INDICATORS: { key: IndicatorPane; label: string }[] = [
  { key: "volume", label: "VOL" },
  { key: "bollinger", label: "BOLL" },
  { key: "macd", label: "MACD" },
  { key: "rsi", label: "RSI" },
  { key: "kdj", label: "KDJ" },
]

function loadStoredIndicators(): IndicatorPane[] | null {
  try {
    const raw = localStorage.getItem(INDICATOR_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.every((v: any) => typeof v === "string")) return parsed as IndicatorPane[]
    }
  } catch { /* corrupted */ }
  return null
}

function saveStoredIndicators(val: IndicatorPane[]) {
  try { localStorage.setItem(INDICATOR_STORAGE_KEY, JSON.stringify(val)) } catch { /* quota */ }
}

export function KlineChart({ rawData, height = 500, indicators: controlledIndicators, onIndicatorsChange, showIndicatorSelector = true, turtleOverlay }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [popoverOpen, setPopoverOpen] = useState(false)

  // Internal indicator state (uncontrolled mode) with localStorage
  const [internalIndicators, setInternalIndicators] = useState<IndicatorPane[]>(() => {
    if (controlledIndicators) return controlledIndicators
    return loadStoredIndicators() ?? [...DEFAULT_INDICATORS]
  })

  const indicators = controlledIndicators ?? internalIndicators

  const toggleIndicator = useCallback((key: IndicatorPane) => {
    if (controlledIndicators && onIndicatorsChange) {
      const next = controlledIndicators.includes(key)
        ? controlledIndicators.filter((k) => k !== key)
        : [...controlledIndicators, key]
      onIndicatorsChange(next)
      return
    }
    setInternalIndicators((prev) => {
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
      saveStoredIndicators(next)
      return next
    })
  }, [controlledIndicators, onIndicatorsChange])

  // ── Mobile: responsive detection + single-indicator cycling ──
  const [isMobile, setIsMobile] = useState(false)
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener("resize", check)
    return () => window.removeEventListener("resize", check)
  }, [])

  const MOBILE_CYCLE: IndicatorPane[] = ["volume", "macd", "rsi", "kdj"]
  const [mobileCycleIdx, setMobileCycleIdx] = useState(0)

  // mobile: cycle one indicator at a time; desktop: all selected
  const effectiveIndicators = isMobile
    ? (mobileCycleIdx === 0 ? [] : [MOBILE_CYCLE[mobileCycleIdx - 1]])
    : indicators

  const cycleMobile = useCallback(() => {
    setMobileCycleIdx((prev) => (prev + 1) % (MOBILE_CYCLE.length + 1))
  }, [MOBILE_CYCLE.length])

  // Indicator explanations (memoized from rawData + effectiveIndicators)
  const explanations = useMemo(() => {
    if (!rawData) return []
    const bars = toChartBars(rawData)
    return buildExplanations(bars, effectiveIndicators)
  }, [rawData, effectiveIndicators])

  const chartRef = useRef<IChartApi | null>(null)
  const allSeries = useRef<ISeriesApi<any>[]>([])
  const turtleLines = useRef<IPriceLine[]>([])
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const showVolume = effectiveIndicators.includes("volume")
  const showBollinger = effectiveIndicators.includes("bollinger")
  const showMACD = effectiveIndicators.includes("macd")
  const showRSI = effectiveIndicators.includes("rsi")
  const showKDJ = effectiveIndicators.includes("kdj")

  const paneHeights = getPaneHeights(effectiveIndicators, height)

  // 1. Create chart + series
  useEffect(() => {
    if (!containerRef.current) return

    // Abort any previous render in flight
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const container = containerRef.current

    const chart = createChart(container, {
      height,
      layout: { background: { color: "transparent" }, textColor: "#888" },
      grid: { vertLines: { color: "#222" }, horzLines: { color: "#222" } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#333" },
      timeScale: { borderColor: "#333", timeVisible: true,
        tickMarkFormatter: (t: Time) => {
          if (typeof t === "number") { const d = new Date(t * 1000); return `${d.getMonth()+1}-${d.getDate()}` }
          return String(t).slice(5)
        },
      },
      handleScroll: false, handleScale: false,
    })
    chartRef.current = chart
    const series: ISeriesApi<any>[] = []

    // ── Price pane ──
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#ef4444", downColor: "#10b981", borderVisible: false,
      wickUpColor: "#ef4444", wickDownColor: "#10b981",
      priceScaleId: "price",
    })
    candleSeries.current = candle
    series.push(candle)

    // MA lines
    const ma5 = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false, priceScaleId: "price" })
    const ma10 = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, priceScaleId: "price" })
    const ma20 = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 1, priceLineVisible: false, priceScaleId: "price" })
    series.push(ma5, ma10, ma20)

    // Bollinger (on price pane)
    if (showBollinger) {
      const bbMid = chart.addSeries(LineSeries, { color: "rgba(6,182,212,0.6)", lineWidth: 1, priceLineVisible: false, priceScaleId: "price" })
      const bbUp  = chart.addSeries(LineSeries, { color: "rgba(6,182,212,0.3)", lineWidth: 1, priceLineVisible: false, priceScaleId: "price" })
      const bbLow = chart.addSeries(LineSeries, { color: "rgba(6,182,212,0.3)", lineWidth: 1, priceLineVisible: false, priceScaleId: "price" })
      series.push(bbMid, bbUp, bbLow)
    }

    // ── Volume pane ──
    if (showVolume) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume" })
      series.push(vol)
    }

    // ── MACD pane ──
    if (showMACD) {
      const macdHist = chart.addSeries(HistogramSeries, { priceScaleId: "macd" })
      const macdDif = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false, priceScaleId: "macd" })
      const macdDea = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, priceScaleId: "macd" })
      series.push(macdHist, macdDif, macdDea)
    }

    // ── RSI pane ──
    if (showRSI) {
      const rsiLine = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 2, priceScaleId: "rsi" })
      // 70/30 reference lines
      const rsi70 = chart.addSeries(LineSeries, { color: "rgba(239,68,68,0.4)", lineWidth: 1, priceLineVisible: false, priceScaleId: "rsi", lastValueVisible: false })
      const rsi30 = chart.addSeries(LineSeries, { color: "rgba(16,185,129,0.4)", lineWidth: 1, priceLineVisible: false, priceScaleId: "rsi", lastValueVisible: false })
      series.push(rsiLine, rsi70, rsi30)
      chart.priceScale("rsi").applyOptions({
        scaleMargins: { top: 0.05, bottom: 0.05 },
      })
    }

    // ── KDJ pane ──
    if (showKDJ) {
      const kdjK = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false, priceScaleId: "kdj" })
      const kdjD = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, priceScaleId: "kdj" })
      const kdjJ = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 1, priceLineVisible: false, priceScaleId: "kdj" })
      series.push(kdjK, kdjD, kdjJ)
      chart.priceScale("kdj").applyOptions({
        scaleMargins: { top: 0.05, bottom: 0.05 },
      })
    }

    allSeries.current = series

    // Cleanup turtle lines on unmount
    turtleLines.current.forEach((pl) => { try { candleSeries.current?.removePriceLine(pl) } catch { /* */ } })
    turtleLines.current = []

    return () => {
      controller.abort()
      chart.remove()
      chartRef.current = null
    }
  }, [height, showVolume, showBollinger, showMACD, showRSI, showKDJ])

  // 1.5 Turtle price lines — managed separately
  useEffect(() => {
    const candle = candleSeries.current
    if (!candle) return

    // Remove old lines
    turtleLines.current.forEach((pl) => { try { candle.removePriceLine(pl) } catch { /* */ } })
    turtleLines.current = []

    if (!turtleOverlay) return

    const lines: { price: number; color: string; title: string; style: number }[] = []

    if (turtleOverlay.sys1_entry != null) {
      lines.push({ price: turtleOverlay.sys1_entry, color: "#ef5350", title: "S1入", style: LineStyle.Dashed })
    }
    if (turtleOverlay.sys2_entry != null) {
      lines.push({ price: turtleOverlay.sys2_entry, color: "#ff9800", title: "S2入", style: LineStyle.Dashed })
    }
    if (turtleOverlay.sys1_exit != null) {
      lines.push({ price: turtleOverlay.sys1_exit, color: "#26a69a", title: "S1出", style: LineStyle.Dotted })
    }
    if (turtleOverlay.sys2_exit != null) {
      lines.push({ price: turtleOverlay.sys2_exit, color: "#4caf50", title: "S2出", style: LineStyle.Dotted })
    }

    for (const l of lines) {
      try {
        const pl = candle.createPriceLine({
          price: l.price,
          color: l.color,
          lineWidth: 1,
          lineStyle: l.style,
          axisLabelVisible: true,
          title: l.title,
        })
        turtleLines.current.push(pl)
      } catch { /* */ }
    }

    return () => {
      turtleLines.current.forEach((pl) => { try { candle.removePriceLine(pl) } catch { /* */ } })
      turtleLines.current = []
    }
  }, [turtleOverlay])

  // 2. Push data
  useEffect(() => {
    if (allSeries.current.length === 0 || !rawData) return
    // Bail if a newer render has been scheduled
    if (abortRef.current?.signal.aborted) return
    const bars = toChartBars(rawData)
    if (!bars.length) return
    const closes = bars.map(b => b.close)
    const highs = bars.map(b => b.high)
    const lows = bars.map(b => b.low)
    const dates = bars.map(b => b.date as Time)

    let si = 0 // series index

    // Price: candle
    const candleData: CandlestickData[] = bars.map(d => ({
      time: d.date as Time, open: d.open, high: d.high, low: d.low, close: d.close,
    }))
    allSeries.current[si++].setData(candleData)

    // Price: MA5,10,20
    const toLine = (vals: (number | null)[]) => vals
      .map((v, i) => v != null ? { time: dates[i], value: v } : null)
      .filter((v): v is {time: Time, value: number} => v != null)
    for (const key of ["ma5", "ma10", "ma20"] as const) {
      const vals: (number | null)[] = bars.map(b => b[key])
      allSeries.current[si++].setData(toLine(vals))
    }

    // Bollinger
    if (showBollinger) {
      const bb = calcBollinger(closes, 20, 2)
      allSeries.current[si++].setData(toLine(bb.mid))
      allSeries.current[si++].setData(toLine(bb.upper))
      allSeries.current[si++].setData(toLine(bb.lower))
    }

    // Volume
    if (showVolume) {
      const volData: HistogramData[] = bars.map(d => ({
        time: d.date as Time, value: d.volume,
        color: d.close >= d.open ? "rgba(239,68,68,0.4)" : "rgba(16,185,129,0.4)",
      }))
      allSeries.current[si++].setData(volData)
    }

    // MACD
    if (showMACD) {
      const macd = calcMACD(closes)
      const histData: HistogramData[] = []
      for (let i = 0; i < bars.length; i++) {
        if (macd.histogram[i] != null) {
          const v = macd.histogram[i]!
          histData.push({ time: dates[i], value: v, color: v >= 0 ? "rgba(239,68,68,0.6)" : "rgba(16,185,129,0.6)" })
        }
      }
      allSeries.current[si++].setData(histData)
      allSeries.current[si++].setData(toLine(macd.dif))
      allSeries.current[si++].setData(toLine(macd.dea))
    }

    // RSI
    if (showRSI) {
      const rsi = calcRSI(closes, 14)
      allSeries.current[si++].setData(toLine(rsi))
      // 70/30 reference lines
      const flat70 = rsi.map((_, i) => (rsi[i] != null ? { time: dates[i], value: 70 } : null)).filter((v): v is {time: Time, value: number} => v != null)
      const flat30 = rsi.map((_, i) => (rsi[i] != null ? { time: dates[i], value: 30 } : null)).filter((v): v is {time: Time, value: number} => v != null)
      allSeries.current[si++].setData(flat70)
      allSeries.current[si++].setData(flat30)
    }

    // KDJ
    if (showKDJ) {
      const kdj = calcKDJ(highs, lows, closes, 9)
      allSeries.current[si++].setData(toLine(kdj.k))
      allSeries.current[si++].setData(toLine(kdj.d))
      allSeries.current[si++].setData(toLine(kdj.j))
    }

    // Skip if chart was recreated mid-push (AbortController)
    if (!abortRef.current?.signal.aborted) {
      chartRef.current?.timeScale().fitContent()
    }
  }, [rawData, showVolume, showBollinger, showMACD, showRSI, showKDJ])

  // 3. ResizeObserver
  useEffect(() => {
    if (!containerRef.current || !chartRef.current) return
    const observer = new ResizeObserver(() => {
      if (containerRef.current && containerRef.current.clientWidth > 0) {
        chartRef.current?.resize(containerRef.current.clientWidth, height)
      }
    })
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [height])

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <div ref={containerRef} style={{ width: "100%", height }} />

      {/* Indicator explanation bar */}
      {explanations.length > 0 && (
        <div className="mt-1.5 px-2 py-1.5 rounded border border-border/40 bg-muted/20 text-[11px] leading-relaxed">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {explanations.map((exp) => (
              <span key={exp.key} className="inline-flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: exp.color }}
                />
                <span className="font-semibold text-foreground/80">{exp.label}</span>
                <span className="text-muted-foreground font-mono">{exp.value}</span>
                <span className={
                  exp.signal === "bullish" ? "text-red-400" :
                  exp.signal === "bearish" ? "text-green-400" :
                  "text-muted-foreground"
                }>
                  {exp.interpretation}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Desktop: indicator selector popover */}
      {showIndicatorSelector && !isMobile && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); setPopoverOpen((v) => !v) }}
            className="absolute top-2 right-2 z-10 text-[10px] px-2 py-1 rounded border
              bg-card/90 backdrop-blur border-border text-muted-foreground
              hover:text-foreground hover:border-primary/50 transition-colors"
          >
            ⚙ 指标
          </button>

          {popoverOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setPopoverOpen(false)} />
              <div className="absolute top-9 right-2 z-30 bg-card border border-border rounded-md
                shadow-lg p-2 min-w-[120px]">
                <p className="text-[10px] text-muted-foreground mb-1.5 px-1">切换指标</p>
                {ALL_INDICATORS.map((ind) => {
                  const active = indicators.includes(ind.key)
                  return (
                    <button
                      key={ind.key}
                      onClick={(e) => { e.stopPropagation(); toggleIndicator(ind.key) }}
                      className={`flex items-center justify-between w-full text-[11px] px-2 py-1.5
                        rounded transition-colors text-left
                        ${active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
                    >
                      <span>{ind.label}</span>
                      <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center
                        ${active ? "bg-primary border-primary text-primary-foreground" : "border-border"}`}>
                        {active ? "✓" : ""}
                      </span>
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </>
      )}

      {/* Mobile: floating cycle button */}
      {isMobile && showIndicatorSelector && (
        <button
          onClick={(e) => { e.stopPropagation(); cycleMobile() }}
          className="absolute bottom-3 right-3 z-10 text-xs px-3 py-1.5 rounded-full
            bg-primary text-primary-foreground shadow-lg
            active:scale-95 transition-transform"
        >
          {mobileCycleIdx === 0
            ? "📊"
            : MOBILE_CYCLE[mobileCycleIdx - 1].toUpperCase()}
        </button>
      )}
    </div>
  )
}
