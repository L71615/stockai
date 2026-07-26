/**
 * 数据库探针 — 通过 child_process 调 Python sqlite3(流式,不爆内存)
 *
 * 为什么不用 sql.js / better-sqlite3:
 *  - better-sqlite3 native 编译失败(Win 工具链缺失)
 *  - sql.js 需要把整个 db 加载到内存(stockai.db 245MB 太大)
 *  - Python sqlite3 标准库 + WAL 流式读取,最稳妥
 *
 * 只读 — 从不写 stockai.db
 */

import { spawn } from "node:child_process"
import { config } from "../config"

export interface ColumnInfo {
  cid: number
  name: string
  type: string
  notnull: boolean
  pk: boolean
}

export interface ForeignKeyInfo {
  from: string
  table: string
  to: string
}

export interface IndexInfo {
  name: string
  unique: boolean
}

export interface TableInfo {
  name: string
  type: "table" | "view" | "index"
  rowCount: number | null
  sizeMB: number | null
  columns: ColumnInfo[]
  foreignKeys: ForeignKeyInfo[]
  indexes: IndexInfo[]
  sampleRows: Record<string, unknown>[]
}

export interface DbSummary {
  databasePath: string
  databaseSizeMB: number
  schemaVersion: string | null
  lastUpdated: string
  tableCount: number
  totalRows: number
  tables: { name: string; type: string; rowCount: number | null; sizeMB: number | null }[]
}

// Python 脚本 — 接受 JSON 命令,返回 JSON 结果
const PYTHON_SCRIPT = `
import sqlite3
import json
import sys

def run(cmd):
    db_path = r"${config.databasePath.replace(/\\/g, "\\\\")}"
    conn = sqlite3.connect(db_path, uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    op = cmd.get("op")

    try:
        if op == "summary":
            cur.execute("PRAGMA journal_mode")
            journal = cur.fetchone()[0]
            cur.execute("PRAGMA user_version")
            schema_ver = cur.fetchone()[0]
            cur.execute("PRAGMA page_size")
            page_size = cur.fetchone()[0]
            cur.execute("PRAGMA page_count")
            page_count = cur.fetchone()[0]
            size_bytes = page_size * page_count

            # 表 + 视图列表
            cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name")
            objects = cur.fetchall()

            tables = []
            total_rows = 0
            for obj in objects:
                name = obj["name"]
                otype = obj["type"]
                row_count = None
                size_mb = None
                if otype == "table":
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM \\"{name}\\"")
                        row_count = cur.fetchone()[0]
                        total_rows += row_count
                    except Exception:
                        row_count = None
                    try:
                        # 估算表大小
                        cur.execute(f"SELECT SUM(pgsize) FROM dbstat WHERE name=?", (name,))
                        sz = cur.fetchone()[0]
                        size_mb = round((sz or 0) / 1024 / 1024, 3)
                    except Exception:
                        size_mb = None
                tables.append({
                    "name": name,
                    "type": otype,
                    "rowCount": row_count,
                    "sizeMB": size_mb,
                })

            return {
                "databasePath": db_path,
                "databaseSizeMB": round(size_bytes / 1024 / 1024, 2),
                "journalMode": journal,
                "schemaVersion": str(schema_ver),
                "tableCount": len(tables),
                "totalRows": total_rows,
                "tables": tables,
            }

        elif op == "table_detail":
            name = cmd["name"]
            cur.execute("SELECT name FROM sqlite_master WHERE name=? AND type='table'", (name,))
            if not cur.fetchone():
                return {"error": f"表 {name} 不存在"}

            # 列
            cur.execute(f"PRAGMA table_info(\\"{name}\\")")
            cols = cur.fetchall()
            columns = [
                {
                    "cid": c["cid"],
                    "name": c["name"],
                    "type": c["type"],
                    "notnull": bool(c["notnull"]),
                    "pk": bool(c["pk"]),
                }
                for c in cols
            ]

            # 外键
            cur.execute(f"PRAGMA foreign_key_list(\\"{name}\\")")
            fks_raw = cur.fetchall()
            foreign_keys = [
                {"from": f["from"], "table": f["table"], "to": f["to"]}
                for f in fks_raw
            ]

            # 索引
            cur.execute(f"PRAGMA index_list(\\"{name}\\")")
            idx_raw = cur.fetchall()
            indexes = [
                {"name": i["name"], "unique": bool(i["unique"])}
                for i in idx_raw
            ]

            # 行数
            cur.execute(f"SELECT COUNT(*) AS n FROM \\"{name}\\"")
            row_count = cur.fetchone()[0]

            # 抽样 5 行
            sample = []
            try:
                cur.execute(f"SELECT * FROM \\"{name}\\" LIMIT 5")
                rows = cur.fetchall()
                sample = [dict(r) for r in rows]
            except Exception:
                sample = []

            return {
                "name": name,
                "type": "table",
                "rowCount": row_count,
                "columns": columns,
                "foreignKeys": foreign_keys,
                "indexes": indexes,
                "sampleRows": sample,
            }

        else:
            return {"error": f"未知 op: {op}"}
    finally:
        conn.close()

if __name__ == "__main__":
    cmd = json.loads(sys.stdin.read())
    result = run(cmd)
    print(json.dumps(result, ensure_ascii=False, default=str))
`

// 异步调用 Python 子进程
function callPython<T>(cmd: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    const py = spawn("python", ["-c", PYTHON_SCRIPT], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    })

    let stdout = ""
    let stderr = ""

    py.stdout.on("data", (d) => (stdout += d.toString()))
    py.stderr.on("data", (d) => (stderr += d.toString()))

    py.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`Python 退出码 ${code}: ${stderr}`))
        return
      }
      try {
        const result = JSON.parse(stdout) as T
        resolve(result)
      } catch (err) {
        reject(new Error(`JSON 解析失败: ${(err as Error).message}\n输出: ${stdout}`))
      }
    })

    py.on("error", (err) => reject(err))
    py.stdin.write(JSON.stringify(cmd))
    py.stdin.end()
  })
}

// 缓存:避免每 5s 都跑 Python
let cachedSummary: DbSummary | null = null
let cachedAt = 0
const CACHE_TTL_MS = 30_000 // 30s 刷新一次足够

export async function getDbSummary(): Promise<DbSummary> {
  const now = Date.now()
  if (cachedSummary && now - cachedAt < CACHE_TTL_MS) {
    return { ...cachedSummary, lastUpdated: new Date(cachedAt).toISOString() }
  }
  const raw = await callPython<{
    databasePath: string
    databaseSizeMB: number
    schemaVersion: string | null
    tableCount: number
    totalRows: number
    tables: { name: string; type: string; rowCount: number | null; sizeMB: number | null }[]
    journalMode?: string
  }>({ op: "summary" })

  const summary: DbSummary = {
    ...raw,
    lastUpdated: new Date().toISOString(),
  }
  cachedSummary = summary
  cachedAt = now
  return summary
}

export async function getTableDetail(name: string): Promise<TableInfo> {
  const raw = await callPython<{
    name: string
    type: "table"
    rowCount: number
    columns: ColumnInfo[]
    foreignKeys: ForeignKeyInfo[]
    indexes: IndexInfo[]
    sampleRows: Record<string, unknown>[]
    error?: string
  }>({ op: "table_detail", name })

  if (raw.error) throw new Error(raw.error)

  return {
    ...raw,
    sizeMB: null, // detail 里不算大小
  }
}

export async function refreshDb(): Promise<DbSummary> {
  cachedSummary = null
  cachedAt = 0
  return getDbSummary()
}