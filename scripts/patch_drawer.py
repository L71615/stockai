import re

with open('D:/stocks/frontend/src/components/data-table.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Insert useState, useEffect, apiGet imports
content = content.replace(
    'import * as React from "react"',
    'import * as React from "react"\nimport { useState, useEffect } from "react"\nimport { apiGet } from "@/lib/auth"'
)

# Find StockDetailDrawer function
start_marker = 'function StockDetailDrawer({ item }: { item: z.infer<typeof schema> }) {'
start_idx = content.find(start_marker)
if start_idx == -1:
    print("ERROR: function not found!")
    exit(1)

# Find closing brace of function
pos = start_idx + len(start_marker)
brace_count = 1
while brace_count > 0 and pos < len(content):
    if content[pos] == '{':
        brace_count += 1
    elif content[pos] == '}':
        brace_count -= 1
    pos += 1
end_idx = pos

# Read the new function from a separate file
with open('D:/stocks/frontend/src/components/stock-chart-drawer.tsx', 'r', encoding='utf-8') as f:
    drawer_content = f.read()

# Instead of using the separate component, write inline JSX
# Create a simpler inline version
new_fn = '''function StockDetailDrawer({ item }: { item: z.infer<typeof schema> }) {
  const isMobile = useIsMobile()
  const [period, setPeriod] = useState("1m")
  const [chartData, setChartData] = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)

  useEffect(() => {
    if (!item.code) return
    setChartLoading(true)
    apiGet<Record<string, any>>("/api/stocks/kline/" + item.code + "?period=" + period)
      .then((raw: any) => {
        if (raw && raw.dates) {
          setChartData(raw.dates.map((dt: string, i: number) => ({
            date: dt.slice(5),
            open: raw.opens?.[i] ?? raw.closes[i],
            high: raw.highs?.[i] ?? raw.closes[i],
            low: raw.lows?.[i] ?? raw.closes[i],
            close: raw.closes[i],
            volume: raw.volumes?.[i] ?? 0,
            ma5: raw.ma5?.[i],
            ma10: raw.ma10?.[i],
            ma20: raw.ma20?.[i],
          })))
        }
      })
      .catch(() => {})
      .finally(() => setChartLoading(false))
  }, [item.code, period])

  const yMin = chartData.length ? Math.min(...chartData.map((d: any) => d.low)) : 0
  const yMax = chartData.length ? Math.max(...chartData.map((d: any) => d.high)) : 100
  const yPad = (yMax - yMin) * 0.08 || 1
  const cw = chartData.length <= 10 ? 8 : chartData.length <= 30 ? 4 : 2
  const pers = [{k:"5d",l:"5日"},{k:"1m",l:"日K"},{k:"3m",l:"周K"},{k:"6m",l:"月K"}]
  const fv = (v: number) => v >= 1e8 ? (v/1e8).toFixed(1)+"亿" : v >= 1e4 ? (v/1e4).toFixed(1)+"万" : String(v)

  String.prototype.startsWith = String.prototype.startsWith || function(s: string) { return this.indexOf(s) === 0 }

  return (
    <Drawer direction={isMobile ? "bottom" : "right"}>
      <DrawerTrigger asChild>
        <Button variant="link" className="w-fit px-0 text-left text-foreground font-medium">{item.name}</Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader className="gap-1 pb-2">
          <DrawerTitle className="font-mono text-sm">{item.code} {item.name}</DrawerTitle>
        </DrawerHeader>
        <div className="flex flex-col gap-2 overflow-y-auto px-4 text-sm">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-muted-foreground">现价</span> <span className="font-mono ml-1">{item.price}</span></div>
            <div><span className="text-muted-foreground">成本</span> <span className="font-mono ml-1">{item.cost}</span></div>
            <div><span className="text-muted-foreground">持仓</span> <span className="font-mono ml-1">{item.shares}</span></div>
            <div><span className={cn("font-mono", String(item.pnl).startsWith("+") ? "text-red-500" : String(item.pnl).startsWith("-") ? "text-emerald-500" : "")}>{item.pnl} ({item.pnlPct})</span></div>
          </div>
          <Separator />
          <div className="flex gap-1">
            {pers.map((p: any) => (
              <button key={p.k} onClick={() => setPeriod(p.k)} className={cn("px-3 py-1 text-xs border-b-2", period === p.k ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>{p.l}</button>
            ))}
          </div>
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <span><span className="inline-block w-3 h-0.5 bg-amber-500 align-middle mr-0.5" />MA5</span>
            <span><span className="inline-block w-3 h-0.5 bg-purple-500 align-middle mr-0.5" />MA10</span>
            <span><span className="inline-block w-3 h-0.5 bg-cyan-500 align-middle mr-0.5" />MA20</span>
          </div>
          {chartLoading ? (
            <div className="space-y-2"><Skeleton className="h-[260px] w-full" /><Skeleton className="h-[70px] w-full" /></div>
          ) : chartData.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-12">加载中...</p>
          ) : (
            <>
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <ComposedChart data={chartData} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#888" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                    <YAxis domain={[yMin - yPad, yMax + yPad]} tick={{ fontSize: 10, fill: "#888" }} tickLine={false} axisLine={false} width={50} tickFormatter={(v: number) => v.toFixed(2)} />
                    <Tooltip content={({ active, payload }: any) => {
                      if (!active || !payload?.length) return null
                      const d = payload[0]?.payload
                      if (!d) return null
                      return (
                        <div className="rounded-none border border-border bg-card px-2.5 py-1.5 text-[11px] shadow">
                          <p className="font-mono text-muted-foreground mb-1">{d.date}</p>
                          <div className="grid grid-cols-2 gap-x-2 font-mono">
                            <span className="text-muted-foreground">开</span><span>{d.open.toFixed(2)}</span>
                            <span className="text-muted-foreground">高</span><span className="text-red-400">{d.high.toFixed(2)}</span>
                            <span className="text-muted-foreground">低</span><span className="text-emerald-400">{d.low.toFixed(2)}</span>
                            <span className="text-muted-foreground">收</span><span className={d.close >= d.open ? "text-red-400" : "text-emerald-400"}>{d.close.toFixed(2)}</span>
                            <span className="text-muted-foreground">量</span><span>{fv(d.volume)}</span>
                          </div>
                        </div>
                      )
                    }} />
                    <Bar dataKey="low" isAnimationActive={false}
                      shape={(props: any) => {
                        const { x, width, payload: p } = props
                        if (!p) return null
                        const up = p.close >= p.open
                        const col = up ? "#ef4444" : "#10b981"
                        const top = up ? p.close : p.open
                        const h = Math.abs(p.close - p.open) || 0.01
                        const w = Math.min(cw, (width as number) || 6)
                        const cx = (x as number) + (width as number) / 2
                        return <g><line x1={cx} x2={cx} y1={p.low} y2={p.high} stroke={col} strokeWidth={1}/><rect x={cx-w/2} y={top} width={w} height={h} fill={col}/></g>
                      }} />
                    <Line type="monotone" dataKey="ma5" stroke="#f59e0b" dot={false} strokeWidth={1} connectNulls />
                    <Line type="monotone" dataKey="ma10" stroke="#8b5cf6" dot={false} strokeWidth={1} connectNulls />
                    <Line type="monotone" dataKey="ma20" stroke="#06b6d4" dot={false} strokeWidth={1} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div style={{ width: "100%", height: 70 }}>
                <ResponsiveContainer>
                  <ComposedChart data={chartData} margin={{ top: 0, right: 5, bottom: 0, left: 0 }}>
                    <XAxis dataKey="date" tick={false} axisLine={false} />
                    <YAxis tick={false} axisLine={false} width={0} />
                    <Bar dataKey="volume" isAnimationActive={false}
                      shape={(props: any) => {
                        const { x, width, payload: p } = props
                        if (!p) return null
                        const w = Math.min(8, (width as number) || 8)
                        const cx = (x as number) + (width as number) / 2
                        return <rect x={cx-w/2} y={0} width={w} height={p.volume} fill={p.close>=p.open?"rgba(239,68,68,0.5)":"rgba(16,185,129,0.5)"}/>
                      }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </div>
        <DrawerFooter>
          <DrawerClose asChild>
            <Button variant="outline" size="sm">关闭</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  )
}'''

content = content[:start_idx] + new_fn + content[end_idx:]

# Remove old sparkData/_sparkConfig
content = content.replace(
    'const _sparkConfig = {\n  price: { label: "价格", color: "#ef5350" },\n} satisfies ChartConfig\n\n',
    ''
)

with open('D:/stocks/frontend/src/components/data-table.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print(f'Patched successfully. Replaced {start_idx}-{end_idx}')
print(f'Original function was {end_idx - start_idx} chars, new is {len(new_fn)} chars')
