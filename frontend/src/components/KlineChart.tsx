"use client"

import { useEffect, useRef } from "react"
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
  /** 要显示的指标面板 (默认: volume) */
  indicators?: IndicatorPane[]
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

const DEFAULT_INDICATORS: IndicatorPane[] = ["volume"]

export function KlineChart({ rawData, height = 500, indicators = DEFAULT_INDICATORS, turtleOverlay }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const allSeries = useRef<ISeriesApi<any>[]>([])
  const turtleLines = useRef<IPriceLine[]>([])
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null)

  const showVolume = indicators.includes("volume")
  const showBollinger = indicators.includes("bollinger")
  const showMACD = indicators.includes("macd")
  const showRSI = indicators.includes("rsi")
  const showKDJ = indicators.includes("kdj")

  const paneHeights = getPaneHeights(indicators, height)

  // 1. Create chart + series
  useEffect(() => {
    if (!containerRef.current) return
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
    }

    // ── KDJ pane ──
    if (showKDJ) {
      const kdjK = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false, priceScaleId: "kdj" })
      const kdjD = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, priceScaleId: "kdj" })
      const kdjJ = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 1, priceLineVisible: false, priceScaleId: "kdj" })
      series.push(kdjK, kdjD, kdjJ)
    }

    allSeries.current = series

    // Cleanup turtle lines on unmount
    turtleLines.current.forEach((pl) => { try { candleSeries.current?.removePriceLine(pl) } catch { /* */ } })
    turtleLines.current = []

    return () => { chart.remove(); chartRef.current = null }
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
      .filter((v): v is number => v != null)
      .map((v, i) => ({ time: dates[i], value: v }))
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

    chartRef.current?.timeScale().fitContent()
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

  return <div ref={containerRef} style={{ width: "100%", height }} />
}
