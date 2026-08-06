"use client"

/** v5.1 — AI 录入交易 (批量)
 *
 * 工作流:
 *   1. 用户粘贴交易文本(支持 CSV 模板 + 自然语言混排)
 *   2. 点 "AI 识别" → POST /api/ai/parse-transactions → 预览
 *   3. 检查预览(可点击行编辑/删除)
 *   4. 点 "确认入库" → POST /api/transactions/bulk → 刷新持仓
 */

import { useState, useCallback, useMemo } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { IconChevronDown, IconBrain, IconCheck, IconAlertCircle, IconRefresh, IconTrash } from "@tabler/icons-react"
import { apiPost } from "@/lib/auth"
import { cn } from "@/lib/utils"

// ── Types ──

interface ParsedTransaction {
  code: string
  stock_name?: string
  direction: "buy" | "sell"
  quantity: number
  price: number
  date: string
  note?: string
}

interface ParseError {
  line: number
  raw: string
  reason: string
}

interface ParseResponse {
  template: string
  transactions: ParsedTransaction[]
  errors: ParseError[]
  summary: {
    input_lines: number
    parsed_ok: number
    parse_failed: number
    validation_failed: number
  }
}

interface BulkItem {
  stock_code: string
  direction: "buy" | "sell"
  quantity: number
  price: number
  traded_at: string
  note?: string
}

interface BulkResponse {
  message: string
  inserted: Array<BulkItem & { id: number; stock_name: string; amount: number; fee: number }>
  holding_updates: Record<string, { stock_code: string; quantity: number; cost_price: number }>
}

// ── Component ──

export interface AITransactionImporterProps {
  onSuccess?: () => void
}

export function AITransactionImporter({ onSuccess }: AITransactionImporterProps) {
  const [text, setText] = useState("")
  const [templateOpen, setTemplateOpen] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<ParseResponse | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitOk, setSubmitOk] = useState<string | null>(null)

  // ── AI 识别 ──
  const handleParse = useCallback(async () => {
    if (!text.trim()) return
    setParsing(true)
    setSubmitError(null)
    setSubmitOk(null)
    try {
      const resp = await apiPost<ParseResponse>("/api/ai/parse-transactions", { text })
      setResult(resp)
    } catch (e) {
      const msg = e instanceof Error ? e.message : "AI 识别失败"
      setSubmitError(msg)
    } finally {
      setParsing(false)
    }
  }, [text])

  // ── 删除单行预览 ──
  const removeTransaction = useCallback((idx: number) => {
    setResult((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        transactions: prev.transactions.filter((_, i) => i !== idx),
        summary: { ...prev.summary, parsed_ok: prev.transactions.length - 1 },
      }
    })
  }, [])

  // ── 清空 ──
  const handleClear = useCallback(() => {
    setText("")
    setResult(null)
    setSubmitError(null)
    setSubmitOk(null)
  }, [])

  // ── 批量入库 ──
  const handleConfirm = useCallback(async () => {
    if (!result || result.transactions.length === 0) return
    setSubmitting(true)
    setSubmitError(null)
    setSubmitOk(null)
    try {
      const bulkItems: BulkItem[] = result.transactions.map((t) => ({
        stock_code: t.code,
        direction: t.direction,
        quantity: t.quantity,
        price: t.price,
        traded_at: t.date,
      }))
      const resp = await apiPost<BulkResponse>("/api/transactions/bulk", {
        transactions: bulkItems,
      })
      setSubmitOk(resp.message)
      setResult(null)
      setText("")
      onSuccess?.()
    } catch (e) {
      const msg = e instanceof Error ? e.message : "批量入库失败"
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }, [result, onSuccess])

  const canConfirm = result && result.transactions.length > 0 && !submitting

  return (
    <div className="px-4 lg:px-6">
      <Card className="border-l-[3px] border-l-purple-400">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <IconBrain className="size-4 text-purple-400" />
              <CardTitle className="text-base">AI 录入交易</CardTitle>
              <Badge variant="outline" className="text-[10px]">v5.1</Badge>
            </div>
            {result && (
              <span className="text-xs text-muted-foreground">
                {result.summary.parsed_ok} 笔可入库
                {result.errors.length > 0 && ` / ${result.errors.length} 笔错误`}
              </span>
            )}
          </div>
          <CardDescription>
            粘贴交易文本 → AI 自动识别 → 预览 → 批量入库 (支持 CSV 模板 + 自然语言混排)
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* ── 模板示例(可折叠) ── */}
          <Collapsible open={templateOpen} onOpenChange={setTemplateOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
                <IconChevronDown
                  className={cn("size-3 transition-transform", templateOpen && "rotate-180")}
                />
                模板参考
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <pre className="rounded border border-dashed border-border/60 bg-muted/30 px-3 py-2 text-[11px] font-mono leading-relaxed">
{`代码,方向,数量,价格,日期
600519,买入,100,1680.00,2026-08-06
000725,卖出,500,4.20,2026-08-06`}
              </pre>
              <p className="mt-1 text-[10px] text-muted-foreground">
                支持: 买入/buy/Buy · 卖出/sell/Sold · &quot;今天&quot; / &quot;昨天&quot; · &quot;1手&quot;=100股 · 空行/注释自动跳过
              </p>
            </CollapsibleContent>
          </Collapsible>

          {/* ── 文本框 ── */}
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="在此粘贴你的交易记录 (每行一笔, 支持 CSV 模板或自然语言)..."
            className={cn(
              "min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2",
              "font-mono text-xs leading-relaxed",
              "placeholder:text-muted-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400/40"
            )}
            disabled={parsing || submitting}
          />

          {/* ── 工具栏 ── */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={handleParse}
              disabled={!text.trim() || parsing || submitting}
              className="gap-1"
            >
              <IconBrain className="size-3" />
              {parsing ? "识别中…" : "AI 识别"}
            </Button>

            {result && (
              <Button
                size="sm"
                onClick={handleConfirm}
                disabled={!canConfirm}
                className="gap-1"
              >
                <IconCheck className="size-3" />
                {submitting
                  ? "入库中…"
                  : `确认入库 (${result.transactions.length} 笔)`}
              </Button>
            )}

            <Button
              size="sm"
              variant="ghost"
              onClick={handleClear}
              disabled={parsing || submitting || (!text && !result)}
              className="ml-auto gap-1"
            >
              <IconRefresh className="size-3" />
              清空
            </Button>
          </div>

          {/* ── 反馈消息 ── */}
          {submitError && (
            <div className="flex items-start gap-2 rounded border border-red-500/40 bg-red-500/5 px-3 py-2 text-xs text-red-400">
              <IconAlertCircle className="size-3.5 shrink-0 mt-0.5" />
              <span>{submitError}</span>
            </div>
          )}
          {submitOk && (
            <div className="flex items-start gap-2 rounded border border-emerald-500/40 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-400">
              <IconCheck className="size-3.5 shrink-0 mt-0.5" />
              <span>{submitOk} · 持仓已刷新</span>
            </div>
          )}

          {/* ── 解析结果 ── */}
          {parsing ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-3/4" />
            </div>
          ) : result ? (
            <ParseResultView
              result={result}
              onRemove={removeTransaction}
            />
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

// ── 结果视图 ──

interface ParseResultViewProps {
  result: ParseResponse
  onRemove: (idx: number) => void
}

function ParseResultView({ result, onRemove }: ParseResultViewProps) {
  const hasErrors = result.errors.length > 0
  const hasTxs = result.transactions.length > 0

  if (!hasTxs && !hasErrors) {
    return (
      <p className="text-xs text-muted-foreground">无识别结果</p>
    )
  }

  return (
    <div className="space-y-3">
      {/* ── 交易列表 ── */}
      {hasTxs && (
        <div className="rounded border border-border/60 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium text-muted-foreground">#</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground">代码</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground">名称</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground">方向</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground text-right">数量</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground text-right">价格</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground">日期</th>
                <th className="px-2 py-1.5 font-medium text-muted-foreground w-8"></th>
              </tr>
            </thead>
            <tbody>
              {result.transactions.map((tx, i) => (
                <tr key={i} className="border-t border-border/40 hover:bg-muted/20">
                  <td className="px-2 py-1.5 font-mono text-muted-foreground">{i + 1}</td>
                  <td className="px-2 py-1.5 font-mono">{tx.code}</td>
                  <td className="px-2 py-1.5">{tx.stock_name || "—"}</td>
                  <td className="px-2 py-1.5">
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px]",
                        tx.direction === "buy"
                          ? "text-red-500 border-red-500/30"
                          : "text-emerald-500 border-emerald-500/30"
                      )}
                    >
                      {tx.direction === "buy" ? "买入" : "卖出"}
                    </Badge>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">{tx.quantity}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                    ¥ {tx.price.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-muted-foreground">{tx.date}</td>
                  <td className="px-2 py-1.5">
                    <button
                      onClick={() => onRemove(i)}
                      className="text-muted-foreground hover:text-red-400 transition-colors"
                      title="移除此行"
                    >
                      <IconTrash className="size-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── 错误列表 ── */}
      {hasErrors && (
        <div className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 space-y-1">
          <p className="text-xs font-medium text-amber-500 flex items-center gap-1">
            <IconAlertCircle className="size-3" />
            {result.errors.length} 行无法识别/校验失败
          </p>
          {result.errors.map((err, i) => (
            <p key={i} className="text-[11px] text-muted-foreground font-mono">
              {err.line > 0 ? `L${err.line}:` : ""} {err.raw && <code>{err.raw}</code>}
              {" — "}
              {err.reason}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}