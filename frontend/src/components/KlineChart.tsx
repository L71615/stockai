"use client"

import { useEffect, useRef } from "react"
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
} from "lightweight-charts"
import type { KlineResponse } from "@/lib/api-types"

interface KlineBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  ma5: number | null
  ma10: number | null
  ma20: number | null
}

interface KlineChartProps {
  /** Raw API response — converted internally */
  rawData: KlineResponse
  height?: number
}

/** Convert raw API response to chart-ready format */
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

export function KlineChart({ rawData, height = 260 }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<{
    candle: ISeriesApi<"Candlestick">
    volume: ISeriesApi<"Histogram">
    ma5: ISeriesApi<"Line">
    ma10: ISeriesApi<"Line">
    ma20: ISeriesApi<"Line">
  } | null>(null)

  // 1. Initialise chart once
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: "#888",
      },
      grid: {
        vertLines: { color: "#333" },
        horzLines: { color: "#333" },
      },
      crosshair: {
        mode: 1, // CrosshairMode.Normal
      },
      rightPriceScale: {
        borderColor: "#333",
      },
      timeScale: {
        borderColor: "#333",
        timeVisible: true,
        tickMarkFormatter: (time: Time) => {
          // Show MM-DD on the time axis
          if (typeof time === "number") {
            const d = new Date(time * 1000)
            return `${d.getMonth() + 1}-${d.getDate()}`
          }
          // string format "YYYY-MM-DD"
          return String(time).slice(5)
        },
      },
      handleScroll: true,
      handleScale: true,
    })
    chartRef.current = chart

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#ef4444",
      downColor: "#10b981",
      borderVisible: false,
      wickUpColor: "#ef4444",
      wickDownColor: "#10b981",
    })
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
    })
    // MA lines — priceLineVisible false for a cleaner chart
    const ma5 = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false })
    const ma10 = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false })
    const ma20 = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false })

    seriesRef.current = { candle, volume, ma5, ma10, ma20 }

    // ResizeObserver is built into lightweight-charts — no extra code needed
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [height])

  // 2. Push data whenever rawData changes
  useEffect(() => {
    if (!seriesRef.current || !rawData) return

    const bars = toChartBars(rawData)
    if (!bars.length) return

    const candleData: CandlestickData[] = bars.map((d) => ({
      time: d.date as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }))

    const volumeData: HistogramData[] = bars.map((d) => ({
      time: d.date as Time,
      value: d.volume,
      color: d.close >= d.open ? "rgba(239,68,68,0.4)" : "rgba(16,185,129,0.4)",
    }))

    const ma5Data: LineData[] = bars
      .filter((d) => d.ma5 != null)
      .map((d) => ({ time: d.date as Time, value: d.ma5 as number }))

    const ma10Data: LineData[] = bars
      .filter((d) => d.ma10 != null)
      .map((d) => ({ time: d.date as Time, value: d.ma10 as number }))

    const ma20Data: LineData[] = bars
      .filter((d) => d.ma20 != null)
      .map((d) => ({ time: d.date as Time, value: d.ma20 as number }))

    seriesRef.current.candle.setData(candleData)
    seriesRef.current.volume.setData(volumeData)
    seriesRef.current.ma5.setData(ma5Data)
    seriesRef.current.ma10.setData(ma10Data)
    seriesRef.current.ma20.setData(ma20Data)

    chartRef.current?.timeScale().fitContent()
  }, [rawData])

  return <div ref={containerRef} style={{ width: "100%", height }} />
}
