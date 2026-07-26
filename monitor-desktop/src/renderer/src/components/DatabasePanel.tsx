/**
 * 数据库结构探针 — 表清单 + 字段 + 外键
 */

import { useEffect, useState, useMemo } from "react"
import type { DbSummary, TableInfo } from "../../../types"
import { getDbSummary, getTableDetail, refreshDb } from "../lib/api"

function formatNumber(n: number | null): string {
  if (n == null) return "—"
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatSize(mb: number | null): string {
  if (mb == null) return "—"
  if (mb >= 1) return `${mb.toFixed(2)} MB`
  if (mb >= 0.001) return `${(mb * 1024).toFixed(0)} KB`
  return "<1 KB"
}

export function DatabasePanel() {
  const [summary, setSummary] = useState<DbSummary | null>(null)
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<TableInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<"rowCount" | "sizeMB" | "name">("rowCount")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const loadSummary = async () => {
    try {
      setError(null)
      const s = await getDbSummary()
      setSummary(s)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  useEffect(() => {
    loadSummary()
  }, [])

  // 30s 自动刷新
  useEffect(() => {
    const t = setInterval(loadSummary, 30_000)
    return () => clearInterval(t)
  }, [])

  const filteredTables = useMemo(() => {
    if (!summary) return []
    const list = summary.tables.filter((t) =>
      search ? t.name.toLowerCase().includes(search.toLowerCase()) : true
    )
    list.sort((a, b) => {
      const av = a[sortKey] ?? -1
      const bv = b[sortKey] ?? -1
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv))
      return sortDir === "desc" ? -cmp : cmp
    })
    return list
  }, [summary, search, sortKey, sortDir])

  const handleSelect = async (name: string) => {
    setSelected(name)
    setLoading(true)
    setError(null)
    try {
      const d = await getTableDetail(name)
      setDetail(d)
    } catch (err) {
      setError((err as Error).message)
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }

  const handleRefresh = async () => {
    setError(null)
    try {
      const s = await refreshDb()
      setSummary(s)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const toggleSort = (key: "rowCount" | "sizeMB" | "name") => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  return (
    <div className="bg-bg-secondary border border-border rounded-none flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium">🗄 数据库结构</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              className="h-7 px-2 text-xs border border-border text-fg-muted hover:text-fg hover:border-primary transition-colors"
            >
              🔄 刷新
            </button>
          </div>
        </div>

        {summary && (
          <div className="flex items-center gap-4 text-xs text-fg-muted">
            <span>
              路径 <span className="font-mono text-fg">{summary.databasePath.split("\\").slice(-2).join("\\")}</span>
            </span>
            <span>·</span>
            <span>
              <span className="text-primary font-mono tabular-nums">{summary.tableCount}</span> 张表
            </span>
            <span>
              <span className="text-primary font-mono tabular-nums">{formatNumber(summary.totalRows)}</span> 行
            </span>
            <span>
              <span className="text-primary font-mono tabular-nums">{summary.databaseSizeMB.toFixed(1)}</span> MB
            </span>
            {summary.schemaVersion && summary.schemaVersion !== "0" && (
              <span>· schema v{summary.schemaVersion}</span>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="px-4 py-2 bg-danger/10 border-b border-danger/30 text-xs text-danger">
          ⚠ {error}
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {/* 左: 表列表 */}
        <div className="w-1/2 border-r border-border-subtle flex flex-col">
          <div className="px-3 py-2 border-b border-border-subtle">
            <input
              type="text"
              placeholder="🔍 搜索表名..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full h-7 px-2 text-xs bg-bg-tertiary border border-border-subtle text-fg placeholder:text-fg-subtle focus:outline-none focus:border-primary font-mono"
            />
          </div>

          <div className="flex-1 overflow-auto">
            <table className="w-full text-xs">
              <thead className="bg-bg-tertiary sticky top-0 z-10">
                <tr>
                  <th
                    className="text-left p-2 font-medium cursor-pointer hover:text-primary"
                    onClick={() => toggleSort("name")}
                  >
                    表名 {sortKey === "name" && (sortDir === "desc" ? "↓" : "↑")}
                  </th>
                  <th className="text-left p-2 font-medium w-16">类型</th>
                  <th
                    className="text-right p-2 font-medium cursor-pointer hover:text-primary w-24"
                    onClick={() => toggleSort("rowCount")}
                  >
                    行数 {sortKey === "rowCount" && (sortDir === "desc" ? "↓" : "↑")}
                  </th>
                  <th
                    className="text-right p-2 font-medium cursor-pointer hover:text-primary w-24"
                    onClick={() => toggleSort("sizeMB")}
                  >
                    大小 {sortKey === "sizeMB" && (sortDir === "desc" ? "↓" : "↑")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredTables.map((t) => (
                  <tr
                    key={t.name}
                    onClick={() => handleSelect(t.name)}
                    className={`border-t border-border-subtle cursor-pointer transition-colors ${
                      selected === t.name
                        ? "bg-primary/15 text-primary"
                        : "hover:bg-bg-tertiary"
                    }`}
                  >
                    <td className="p-2 font-mono">{t.name}</td>
                    <td className="p-2">
                      <span
                        className={`text-[10px] px-1.5 py-0.5 border ${
                          t.type === "view"
                            ? "border-primary/40 text-primary"
                            : "border-border-subtle text-fg-muted"
                        }`}
                      >
                        {t.type}
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums">
                      {formatNumber(t.rowCount)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-fg-muted">
                      {formatSize(t.sizeMB)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 右: 表详情 */}
        <div className="w-1/2 flex flex-col">
          {!selected ? (
            <div className="flex-1 flex items-center justify-center text-fg-subtle text-xs">
              ← 选择左侧表查看字段 + 外键
            </div>
          ) : loading ? (
            <div className="flex-1 flex items-center justify-center text-fg-muted text-xs">
              加载中...
            </div>
          ) : detail ? (
            <TableDetailView detail={detail} />
          ) : (
            <div className="flex-1 flex items-center justify-center text-danger text-xs">
              {error || "加载失败"}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TableDetailView({ detail }: { detail: TableInfo }) {
  return (
    <div className="flex-1 overflow-auto p-4 space-y-4">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium font-mono">{detail.name}</h3>
          <span className="text-xs text-fg-muted">
            <span className="font-mono tabular-nums text-fg">{formatNumber(detail.rowCount)}</span> 行
          </span>
        </div>
      </div>

      {/* 字段 */}
      <div>
        <h4 className="text-xs font-medium text-fg-muted mb-2">
          📋 字段 ({detail.columns.length})
        </h4>
        <div className="border border-border-subtle rounded-none overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-bg-tertiary">
              <tr>
                <th className="text-left p-1.5 font-medium w-12">#</th>
                <th className="text-left p-1.5 font-medium">名称</th>
                <th className="text-left p-1.5 font-medium">类型</th>
                <th className="text-center p-1.5 font-medium w-16">约束</th>
              </tr>
            </thead>
            <tbody>
              {detail.columns.map((c) => (
                <tr key={c.cid} className="border-t border-border-subtle">
                  <td className="p-1.5 text-fg-subtle font-mono">{c.cid}</td>
                  <td className="p-1.5 font-mono">
                    {c.name}
                    {c.pk && <span className="ml-1 text-primary">🔑</span>}
                  </td>
                  <td className="p-1.5 text-fg-muted font-mono">{c.type || "—"}</td>
                  <td className="p-1.5 text-center text-fg-muted">
                    {c.notnull ? "NOT NULL" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 外键 */}
      {detail.foreignKeys.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-fg-muted mb-2">
            🔗 外键 ({detail.foreignKeys.length})
          </h4>
          <div className="space-y-1">
            {detail.foreignKeys.map((fk, i) => (
              <div
                key={i}
                className="text-xs font-mono text-fg px-2 py-1.5 bg-bg-tertiary border border-border-subtle"
              >
                <span className="text-primary">{detail.name}.{fk.from}</span>
                <span className="text-fg-subtle mx-2">→</span>
                <span className="text-success">{fk.table}.{fk.to}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 索引 */}
      {detail.indexes.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-fg-muted mb-2">
            📑 索引 ({detail.indexes.length})
          </h4>
          <div className="space-y-1">
            {detail.indexes.map((idx, i) => (
              <div
                key={i}
                className="text-xs font-mono text-fg-muted px-2 py-1 bg-bg-tertiary border border-border-subtle"
              >
                {idx.unique && <span className="text-warning mr-1.5">UQ</span>}
                {idx.name}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 抽样 */}
      {detail.sampleRows.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-fg-muted mb-2">
            🔍 抽样 5 行
          </h4>
          <div className="border border-border-subtle overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-bg-tertiary">
                <tr>
                  {Object.keys(detail.sampleRows[0]).map((k) => (
                    <th key={k} className="text-left p-1.5 font-medium whitespace-nowrap">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detail.sampleRows.map((row, i) => (
                  <tr key={i} className="border-t border-border-subtle">
                    {Object.values(row).map((v, j) => (
                      <td
                        key={j}
                        className="p-1.5 font-mono whitespace-nowrap max-w-[200px] truncate"
                        title={String(v ?? "")}
                      >
                        {v == null ? <span className="text-fg-subtle">NULL</span> : String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}