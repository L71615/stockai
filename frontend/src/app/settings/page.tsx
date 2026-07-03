"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost, clearAuth } from "@/lib/auth"
import { IconLogout, IconMail, IconCheck, IconX } from "@tabler/icons-react"
import { cn } from "@/lib/utils"

interface AIProvider { key: string; label: string; api_key: string; model: string; base_url: string }

const PROVIDERS: AIProvider[] = [
  { key: "minimax", label: "MiniMax（国内）", api_key: "", model: "MiniMax-M2.7", base_url: "https://api.minimax.chat/v1" },
  { key: "deepseek", label: "DeepSeek", api_key: "", model: "deepseek-chat", base_url: "https://api.deepseek.com/v1" },
  { key: "openai", label: "OpenAI", api_key: "", model: "gpt-4o", base_url: "" },
  { key: "claude", label: "Claude / Anthropic", api_key: "", model: "claude-opus-4-7", base_url: "" },
  { key: "custom", label: "自定义 OpenAI 兼容", api_key: "", model: "", base_url: "" },
]

const AI_FUNCTIONS = [
  { key: "screener", label: "AI 选股", desc: "多因子扫描二次筛选" },
  { key: "explain", label: "AI 深度分析", desc: "多 Agent 分析 / 因子解读" },
  { key: "chat", label: "AI 对话", desc: "投资助手 SSE 流式聊天" },
  { key: "watchdog", label: "AI 盯盘简报", desc: "异动推送摘要" },
]

interface Rules {
  require_stop_loss: boolean
  max_position_pct: number
  max_total_position_pct: number
  forbid_chasing_limit_up: boolean
  max_consecutive_losses: number
  min_hold_days: number
  enabled: boolean
}

function TradingRulesSection() {
  const [rules, setRules] = useState<Rules | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState("")

  useEffect(() => {
    apiGet<Rules>("/api/discipline/rules").then(setRules).catch(() => {})
  }, [])

  const save = async () => {
    if (!rules) return
    setSaving(true); setMsg("")
    try {
      await apiPost("/api/discipline/rules", rules, "PUT")
      setMsg("已保存")
    } catch { setMsg("保存失败") }
    finally { setSaving(false) }
  }

  if (!rules) return null

  const toggle = (key: keyof Rules) => {
    if (typeof rules[key] === "boolean") {
      setRules((p) => p ? { ...p, [key]: !p[key] } : null)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">交易规则</CardTitle>
        <CardDescription>买入时强制执行，违规将被拦截</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <Label className="text-xs">规则总开关</Label>
          <Badge
            variant="outline"
            className={cn("cursor-pointer text-xs", rules.enabled ? "text-emerald-400" : "text-muted-foreground")}
            onClick={() => toggle("enabled")}
          >
            {rules.enabled ? "已启用" : "已关闭"}
          </Badge>
        </div>
        {rules.enabled && (
          <>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">买入前强制设止损</span>
                <Badge variant="outline" className="cursor-pointer text-xs" onClick={() => toggle("require_stop_loss")}>
                  {rules.require_stop_loss ? "开启" : "关闭"}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">禁止追涨停板（涨幅 &ge; 9.5%）</span>
                <Badge variant="outline" className="cursor-pointer text-xs" onClick={() => toggle("forbid_chasing_limit_up")}>
                  {rules.forbid_chasing_limit_up ? "开启" : "关闭"}
                </Badge>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-[10px]">单票仓位上限 %</Label>
                <Input
                  type="number" min="5" max="100"
                  value={rules.max_position_pct}
                  onChange={(e) => setRules((p) => p ? { ...p, max_position_pct: Number(e.target.value) || 30 } : null)}
                  className="h-7 text-xs w-20"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">总仓位上限 %</Label>
                <Input
                  type="number" min="10" max="100"
                  value={rules.max_total_position_pct}
                  onChange={(e) => setRules((p) => p ? { ...p, max_total_position_pct: Number(e.target.value) || 80 } : null)}
                  className="h-7 text-xs w-20"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">连亏停手机制</Label>
                <Input
                  type="number" min="1" max="10"
                  value={rules.max_consecutive_losses}
                  onChange={(e) => setRules((p) => p ? { ...p, max_consecutive_losses: Number(e.target.value) || 3 } : null)}
                  className="h-7 text-xs w-20"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">最短持仓天数</Label>
                <Input
                  type="number" min="1" max="30"
                  value={rules.min_hold_days}
                  onChange={(e) => setRules((p) => p ? { ...p, min_hold_days: Number(e.target.value) || 1 } : null)}
                  className="h-7 text-xs w-20"
                />
              </div>
            </div>
          </>
        )}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={save} disabled={saving}>{saving ? "保存中..." : "保存规则"}</Button>
          {msg && <span className={cn("text-[10px]", msg === "已保存" ? "text-emerald-400" : "text-destructive")}>{msg}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

export default function SettingsPage() {
  const router = useRouter()
  const [providers, setProviders] = useState<AIProvider[]>(PROVIDERS)
  const [functionProviders, setFunctionProviders] = useState<Record<string, string>>({})
  const [envKeys, setEnvKeys] = useState<Record<string, boolean>>({})
  const [smtp, setSmtp] = useState({ host: "", port: "465", user: "", password: "", sender: "" })
  const [feeRate, setFeeRate] = useState("0.025")
  const [feeMin, setFeeMin] = useState("5")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState("")
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg: string } | null>>({})

  const fetchConfigs = useCallback(async () => {
    try {
      const [ai, smtpData] = await Promise.all([
        apiGet<{ configs?: Record<string, { api_key?: string; model?: string; base_url?: string }>; function_providers?: Record<string, string>; env_keys?: Record<string, boolean> }>("/api/settings/ai-configs").catch(() => ({ configs: {}, function_providers: {}, env_keys: {} })),
        apiGet<{ host?: string; port?: string; user?: string; sender?: string }>("/api/settings/smtp").catch(() => ({})),
      ])
      if (ai) {
        setFunctionProviders(ai.function_providers || {})
        setEnvKeys(ai.env_keys || {})
        const cfgs: Record<string, { api_key?: string; model?: string; base_url?: string }> = ai.configs || {}
        setProviders((prev) => prev.map((p) => ({
          ...p,
          api_key: cfgs[p.key]?.api_key || "",
          model: cfgs[p.key]?.model || p.model,
          base_url: cfgs[p.key]?.base_url || p.base_url,
        })))
      }
      if (smtpData) setSmtp((prev) => ({ ...prev, ...smtpData, password: "" }))
      try {
        const fee = await apiGet<{ commission_rate?: number; commission_min?: number }>("/api/settings/fee-config")
        if (fee && fee.commission_rate != null) setFeeRate(String(fee.commission_rate * 100))
        if (fee && fee.commission_min != null) setFeeMin(String(fee.commission_min))
      } catch { /* optional */ }
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchConfigs()
  }, [fetchConfigs, router])

  const updateFunctionProvider = (funcKey: string, providerKey: string) => {
    setFunctionProviders((prev) => ({ ...prev, [funcKey]: providerKey }))
  }

  const updateProviderField = (key: string, field: "api_key" | "model" | "base_url", value: string) => {
    setProviders((prev) => prev.map((p) => p.key === key ? { ...p, [field]: value } : p))
  }

  const getConfigSource = (providerKey: string): { label: string; color: string } => {
    const p = providers.find((x) => x.key === providerKey)
    if (p?.api_key) return { label: "已保存", color: "text-emerald-400 border-emerald-400/30" }
    if (envKeys[providerKey]) return { label: ".env", color: "text-blue-400 border-blue-400/30" }
    if (p?.model) return { label: "默认", color: "text-muted-foreground border-muted" }
    return { label: "未配置", color: "text-orange-400 border-orange-400/30" }
  }

  const getFunctionStatus = (funcKey: string): { label: string; color: string; ok: boolean } => {
    const pk = functionProviders[funcKey]
    if (!pk) return { label: "未选择", color: "text-muted-foreground", ok: false }
    const p = providers.find((x) => x.key === pk)
    if (p?.api_key || envKeys[pk]) return { label: "已配置", color: "text-emerald-400", ok: true }
    return { label: "缺 Key", color: "text-orange-400", ok: false }
  }

  const usedProviders = new Set(Object.values(functionProviders).filter(Boolean))

  const testProvider = async (providerKey: string) => {
    setTestResults((prev) => ({ ...prev, [providerKey]: null }))
    const p = providers.find((x) => x.key === providerKey)
    if (!p) return
    try {
      const res = await apiPost<{ ok: boolean; error?: string; response?: string }>("/api/settings/ai-test", {
        provider: providerKey,
        api_key: p.api_key,
        model: p.model,
        base_url: p.base_url,
      })
      setTestResults((prev) => ({
        ...prev,
        [providerKey]: { ok: res.ok, msg: res.ok ? (res.response || "连通") : (res.error || "失败") },
      }))
    } catch (err) {
      setTestResults((prev) => ({ ...prev, [providerKey]: { ok: false, msg: err instanceof Error ? err.message : "测试失败" } }))
    }
  }

  const saveAI = async () => {
    setSaving(true); setMsg("")
    const configs: Record<string, unknown> = {}
    // 供应商密钥配置 — 掩码(****)表示未修改，不发送以避免覆盖真实 Key
    providers.forEach((p) => {
      const defaults = PROVIDERS.find((d) => d.key === p.key)
      const isMasked = p.api_key.includes("****")
      const hasCustomKey = p.api_key && !isMasked
      const hasCustomModel = p.model !== (defaults?.model || "")
      const hasCustomBaseUrl = !!p.base_url && p.base_url !== (defaults?.base_url || "")
      if (hasCustomKey || hasCustomModel || hasCustomBaseUrl) {
        configs[p.key] = {
          api_key: hasCustomKey ? p.api_key : "",
          model: p.model,
          base_url: p.base_url,
        }
      }
    })
    configs.function_providers = functionProviders
    try {
      await apiPost("/api/settings/ai-configs", { configs }, "PUT")
      setMsg("AI 配置已保存")
    } catch (err) { setMsg(err instanceof Error ? err.message : "保存失败") }
    finally { setSaving(false) }
  }

  const saveSMTP = async () => {
    setSaving(true); setMsg("")
    try {
      await apiPost("/api/settings/smtp", smtp, "PUT")
      setMsg("邮件配置已保存")
    } catch (err) { setMsg(err instanceof Error ? err.message : "保存失败") }
    finally { setSaving(false) }
  }

  const testSMTP = async () => {
    setMsg("")
    try {
      await apiPost("/api/settings/smtp/test", {
        host: smtp.host,
        port: Number(smtp.port) || 465,
        user: smtp.user,
        password: smtp.password,
      })
      setMsg("测试邮件发送成功")
    } catch (err) { setMsg(err instanceof Error ? err.message : "测试失败") }
  }

  const logout = () => { clearAuth(); router.push("/login") }

  return (
    <>
      <SiteHeader title="设置" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6 space-y-4 max-w-2xl">
        {/* AI Config */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">AI 模型配置</CardTitle>
            <CardDescription>每个 AI 功能独立选择供应商。下方只展开被引用的供应商密钥配置。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <div className="space-y-2"><Skeleton className="h-48 w-full" /></div>
            ) : (
              <>
                {/* Function → Provider mapping table */}
                <div className="border border-border overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border bg-muted/50">
                        <th className="text-left p-2 font-medium">AI 功能</th>
                        <th className="text-left p-2 font-medium w-40">供应商</th>
                        <th className="text-center p-2 font-medium w-20">状态</th>
                        <th className="text-center p-2 font-medium w-16">测试</th>
                      </tr>
                    </thead>
                    <tbody>
                      {AI_FUNCTIONS.map((f) => {
                        const status = getFunctionStatus(f.key)
                        const pk = functionProviders[f.key]
                        const tr = pk ? testResults[pk] : null
                        return (
                          <tr key={f.key} className="border-b border-border last:border-b-0 hover:bg-muted/30">
                            <td className="p-2">
                              <p className="font-medium">{f.label}</p>
                              <p className="text-[10px] text-muted-foreground">{f.desc}</p>
                            </td>
                            <td className="p-2">
                              <Select
                                value={functionProviders[f.key] || ""}
                                onValueChange={(v) => updateFunctionProvider(f.key, v)}
                              >
                                <SelectTrigger className="h-7 text-xs">
                                  <SelectValue placeholder="选择供应商" />
                                </SelectTrigger>
                                <SelectContent>
                                  {providers.map((p) => (
                                    <SelectItem key={p.key} value={p.key}>{p.label}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </td>
                            <td className="p-2 text-center">
                              <Badge variant="outline" className={cn("text-[10px]", status.color)}>
                                {status.label}
                              </Badge>
                            </td>
                            <td className="p-2 text-center">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 w-7 p-0"
                                title={tr ? (tr.ok ? "连通" : tr.msg) : "测试连通"}
                                disabled={!pk}
                                onClick={() => pk && testProvider(pk)}
                              >
                                {tr ? (
                                  tr.ok ? <IconCheck className="size-3.5 text-emerald-400" /> :
                                    <IconX className="size-3.5 text-red-400" />
                                ) : (
                                  <span className="text-[10px]">🧪</span>
                                )}
                              </Button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* 已引用的供应商配置 — 只展开被选中的 */}
                {usedProviders.size > 0 && (
                  <div className="space-y-3">
                    <p className="text-[10px] text-muted-foreground border-b border-border pb-1">
                      已引用的供应商配置（{usedProviders.size} 个）
                    </p>
                    {Array.from(usedProviders).map((pk) => {
                      const p = providers.find((x) => x.key === pk)
                      if (!p) return null
                      const source = getConfigSource(pk)
                      const tr = testResults[pk]
                      return (
                        <div key={pk} className="border border-border p-3 space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium">{p.label}</span>
                              <Badge variant="outline" className={cn("text-[10px]", source.color)}>
                                {source.label}
                              </Badge>
                            </div>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-6 text-[10px]"
                              onClick={() => testProvider(pk)}
                            >
                              {tr ? (tr.ok ? "✅ 连通" : "❌ 失败") : "测试连通"}
                            </Button>
                          </div>
                          {tr && (
                            <p className={cn("text-[10px]", tr.ok ? "text-emerald-400" : "text-red-400")}>
                              {tr.msg}
                            </p>
                          )}
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <div className="space-y-1">
                              <Label className="text-[10px]">API Key</Label>
                              <Input
                                type="password"
                                value={p.api_key}
                                onChange={(e) => updateProviderField(pk, "api_key", e.target.value)}
                                className="h-7 text-xs"
                                placeholder={p.api_key ? "••••••••" : envKeys[pk] ? "来自 .env" : "填入 Key"}
                              />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-[10px]">Model</Label>
                              <Input
                                value={p.model}
                                onChange={(e) => updateProviderField(pk, "model", e.target.value)}
                                className="h-7 text-xs"
                              />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-[10px]">Base URL</Label>
                              <Input
                                value={p.base_url}
                                onChange={(e) => updateProviderField(pk, "base_url", e.target.value)}
                                className="h-7 text-xs"
                                placeholder="默认"
                              />
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                {usedProviders.size === 0 && (
                  <p className="text-xs text-muted-foreground text-center py-4 border border-dashed border-border">
                    请在上方表格中为各功能选择供应商
                  </p>
                )}
              </>
            )}

            <div className="flex items-center gap-2 pt-2 border-t border-border">
              <Button size="sm" onClick={saveAI} disabled={saving}>保存 AI 配置</Button>
              {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
            </div>
          </CardContent>
        </Card>

        {/* Fee Config */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">交易佣金</CardTitle>
            <CardDescription>
              A 股交易佣金费率（ETF 也适用）。印花税和过户费按国家标准自动计算。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-[10px]">佣金费率 (%)</Label>
                <Input value={feeRate} onChange={(e) => setFeeRate(e.target.value)} className="h-7 text-xs font-mono" placeholder="0.025" />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">最低佣金 (元)</Label>
                <Input value={feeMin} onChange={(e) => setFeeMin(e.target.value)} className="h-7 text-xs font-mono" placeholder="5" />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={async () => {
                setSaving(true); setMsg("")
                try {
                  await apiPost("/api/settings/fee-config", {
                    commission_rate: Number(feeRate) / 100,
                    commission_min: Number(feeMin),
                  }, "PUT")
                  setMsg("佣金配置已保存")
                } catch (err) { setMsg(err instanceof Error ? err.message : "保存失败") }
                finally { setSaving(false) }
              }} disabled={saving}>保存佣金配置</Button>
              <Button size="sm" variant="outline" onClick={async () => {
                setSaving(true); setMsg("")
                try {
                  await apiPost("/api/stocks/recalc-fees", {})
                  setMsg("手续费已全部重算")
                } catch (err) { setMsg(err instanceof Error ? err.message : "重算失败") }
                finally { setSaving(false) }
              }} disabled={saving}>重算全部手续费</Button>
            </div>
          </CardContent>
        </Card>

        {/* SMTP Config */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <IconMail className="size-4" />邮件通知
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? <Skeleton className="h-32 w-full" /> : (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div className="space-y-1">
                    <Label className="text-[10px]">SMTP 服务器</Label>
                    <Input value={smtp.host} onChange={(e) => setSmtp((p) => ({ ...p, host: e.target.value }))} className="h-7 text-xs" placeholder="smtp.example.com" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">端口</Label>
                    <Input value={smtp.port} onChange={(e) => setSmtp((p) => ({ ...p, port: e.target.value }))} className="h-7 text-xs" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">发件人邮箱</Label>
                    <Input value={smtp.sender} onChange={(e) => setSmtp((p) => ({ ...p, sender: e.target.value }))} className="h-7 text-xs" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">授权密码</Label>
                    <Input type="password" value={smtp.password} onChange={(e) => setSmtp((p) => ({ ...p, password: e.target.value }))} className="h-7 text-xs" />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">SMTP 用户名</Label>
                  <Input value={smtp.user} onChange={(e) => setSmtp((p) => ({ ...p, user: e.target.value }))} className="h-7 text-xs" />
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={saveSMTP} disabled={saving}>保存</Button>
                  <Button size="sm" variant="outline" onClick={testSMTP}>测试发送</Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Trading Rules */}
        <TradingRulesSection />

        {/* Logout */}
        <Separator />
        <Button variant="outline" size="sm" className="w-fit" onClick={logout}>
          <IconLogout className="size-3.5 mr-1" />退出登录
        </Button>
      </div>
    </>
  )
}
