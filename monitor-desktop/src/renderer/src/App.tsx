import { useEffect, useState } from "react"
import { useMonitor } from "./hooks/useMonitor"
import { ProcessCard } from "./components/ProcessPanel"
import { LogPanel } from "./components/LogPanel"
import { DatabasePanel } from "./components/DatabasePanel"
import { PipelinePanel } from "./components/PipelinePanel"
import { ErrorStats } from "./components/ErrorStats"
import { getConfig } from "./lib/api"

function formatTime(d: Date | null): string {
  if (!d) return "—"
  return d.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

export default function App() {
  const { snapshot, paused, setPaused, error, lastUpdate } = useMonitor(5000)
  const [stockaiRoot, setStockaiRoot] = useState<string>("")

  useEffect(() => {
    getConfig().then((c) => {
      if (c?.stockaiRoot) setStockaiRoot(c.stockaiRoot)
    })
  }, [])

  const allUp = snapshot?.portChecks.backend && snapshot?.portChecks.frontend
  const someDown = !snapshot?.portChecks.backend || !snapshot?.portChecks.frontend

  return (
    <div className="flex flex-col h-screen bg-bg-primary text-fg">
      {/* Top bar */}
      <header className="flex items-center justify-between h-12 px-4 bg-bg-secondary border-b border-border">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-medium">📊 StockAI 后端监视器</h1>
          <span className="text-xs text-fg-muted font-mono">
            {stockaiRoot && `· ${stockaiRoot}`}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-fg-muted">
            ⏱ {formatTime(lastUpdate)}
          </span>
          <span className="text-fg-muted">·</span>
          <span className="text-fg-muted">刷新 5s</span>
          <button
            onClick={() => setPaused(!paused)}
            className={`px-2 py-1 text-xs border transition-colors ${
              paused
                ? "border-warning text-warning"
                : "border-border text-fg-muted hover:text-fg"
            }`}
          >
            {paused ? "▶ 继续" : "⏸ 暂停"}
          </button>
        </div>
      </header>

      {/* Overall status */}
      <div className="px-4 py-2 bg-bg-secondary border-b border-border-subtle">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs">
            {snapshot ? (
              allUp ? (
                <>
                  <span className="text-success">●</span>
                  <span className="text-success">全部正常</span>
                </>
              ) : someDown ? (
                <>
                  <span className="text-danger">●</span>
                  <span className="text-danger">异常</span>
                </>
              ) : (
                <>
                  <span className="text-warning">●</span>
                  <span className="text-warning">部分异常</span>
                </>
              )
            ) : (
              <span className="text-fg-muted">采集中...</span>
            )}
          </div>
          {snapshot && (
            <div className="flex items-center gap-4 text-xs text-fg-muted">
              <span>
                CPU <span className="font-mono tabular-nums text-fg">
                  {snapshot.overall.cpuPercent.toFixed(1)}%
                </span>
              </span>
              <span>
                内存 <span className="font-mono tabular-nums text-fg">
                  {snapshot.overall.memoryUsedMB.toFixed(0)}/
                  {snapshot.overall.memoryTotalMB.toFixed(0)} MB
                </span>
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Main content — 三栏布局 */}
      <main className="flex-1 overflow-auto p-3">
        {error && (
          <div className="bg-bg-secondary border border-danger/50 p-3 rounded-none mb-3">
            <p className="text-sm text-danger">⚠ {error}</p>
          </div>
        )}

        {/* 第 1 行: 进程总览 + Pipeline + 错误统计 */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-3 mb-3">
          <div className="xl:col-span-4">
            <ProcessCard
              title="后端 uvicorn (3000)"
              icon="🟢"
              info={snapshot?.processes.backend ?? null}
              color="primary"
            />
          </div>
          <div className="xl:col-span-4">
            <ProcessCard
              title="前端 next.js (3001)"
              icon="🟢"
              info={snapshot?.processes.frontend ?? null}
              color="primary"
            />
          </div>
          <div className="xl:col-span-4 grid grid-cols-1 gap-3">
            <PipelinePanel />
            <ErrorStats />
          </div>
        </div>

        {/* 第 2 行: 日志 + 数据库 */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3" style={{ minHeight: 480 }}>
          <LogPanel />
          <DatabasePanel />
        </div>
      </main>

      {/* Footer */}
      <footer className="h-8 px-4 bg-bg-secondary border-t border-border flex items-center justify-between text-xs text-fg-muted">
        <span>StockAI 监视器 v0.1.0 · 仅观察,不动 stockai</span>
        <span>{paused ? "已暂停" : "自动刷新中"}</span>
      </footer>
    </div>
  )
}