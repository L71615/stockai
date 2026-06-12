"use client"

import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { SiteHeader } from "@/components/site-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost, isAuthenticated, clearAuth } from "@/lib/auth"
import { IconLogout, IconMail } from "@tabler/icons-react"

interface AIProvider { key: string; label: string; api_key: string; model: string; base_url: string }

const PROVIDERS: AIProvider[] = [
  { key: "minimax", label: "MiniMax", api_key: "", model: "MiniMax-M2.7", base_url: "https://api.minimax.chat/v1" },
  { key: "deepseek", label: "DeepSeek", api_key: "", model: "deepseek-chat", base_url: "https://api.deepseek.com/v1" },
  { key: "openai", label: "OpenAI", api_key: "", model: "gpt-4o", base_url: "" },
  { key: "claude", label: "Claude / Anthropic", api_key: "", model: "claude-opus-4-7", base_url: "" },
  { key: "xiaomi", label: "小米", api_key: "", model: "", base_url: "" },
  { key: "custom", label: "自定义 OpenAI 兼容", api_key: "", model: "", base_url: "" },
]

export default function SettingsPage() {
  const router = useRouter()
  const [providers, setProviders] = useState<AIProvider[]>(PROVIDERS)
  const [smtp, setSmtp] = useState({ host: "", port: "465", user: "", password: "", sender: "" })
  const [feeRate, setFeeRate] = useState("0.025")
  const [feeMin, setFeeMin] = useState("5")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState("")

  const fetchConfigs = useCallback(async () => {
    try {
      const [ai, smtpData] = await Promise.all([
        apiGet<Record<string, { api_key?: string; model?: string; base_url?: string }>>("/api/settings/ai-configs").catch(() => ({})),
        apiGet<{ host?: string; port?: string; user?: string; sender?: string }>("/api/settings/smtp").catch(() => ({})),
      ])
      if (ai && typeof ai === "object") {
        setProviders((prev) => prev.map((p) => ({
          ...p,
          api_key: ai[p.key]?.api_key || "",
          model: ai[p.key]?.model || p.model,
          base_url: ai[p.key]?.base_url || p.base_url,
        })))
      }
      if (smtpData) setSmtp((prev) => ({ ...prev, ...smtpData, password: "" }))
      // Fee config
      try {
        const fee = await apiGet<{ commission_rate?: number; commission_min?: number }>("/api/settings/fee-config")
        if (fee && fee.commission_rate != null) setFeeRate(String(fee.commission_rate * 100))
        if (fee && fee.commission_min != null) setFeeMin(String(fee.commission_min))
      } catch { /* optional */ }
    } catch { /* */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return }
    fetchConfigs()
  }, [fetchConfigs, router])

  const saveAI = async () => {
    setSaving(true); setMsg("")
    const configs: Record<string, { api_key: string; model: string; base_url: string }> = {}
    providers.forEach((p) => { configs[p.key] = { api_key: p.api_key, model: p.model, base_url: p.base_url } })
    try {
      await apiPost("/api/settings/ai-configs", configs, "PUT")
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
      await apiPost("/api/settings/smtp/test", {})
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
            <CardDescription>配置各 AI 供应商的 API Key 和模型</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <div className="space-y-2"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /></div>
            ) : (
              providers.map((p) => (
                <div key={p.key} className="border border-border rounded-none p-3 space-y-2">
                  <p className="text-xs font-medium">{p.label}</p>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    <div className="space-y-1">
                      <Label className="text-[10px]">API Key</Label>
                      <Input
                        type="password"
                        value={p.api_key}
                        onChange={(e) => setProviders((prev) => prev.map((x) => x.key === p.key ? { ...x, api_key: e.target.value } : x))}
                        className="h-7 text-xs"
                        placeholder={p.api_key ? "••••••••" : "填入 Key"}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px]">Model</Label>
                      <Input value={p.model} onChange={(e) => setProviders((prev) => prev.map((x) => x.key === p.key ? { ...x, model: e.target.value } : x))} className="h-7 text-xs" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px]">Base URL</Label>
                      <Input value={p.base_url} onChange={(e) => setProviders((prev) => prev.map((x) => x.key === p.key ? { ...x, base_url: e.target.value } : x))} className="h-7 text-xs" placeholder="默认" />
                    </div>
                  </div>
                </div>
              ))
            )}
            <div className="flex items-center gap-2">
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

        {/* Logout */}
        <Separator />
        <Button variant="outline" size="sm" className="w-fit" onClick={logout}>
          <IconLogout className="size-3.5 mr-1" />退出登录
        </Button>
      </div>
    </>
  )
}
