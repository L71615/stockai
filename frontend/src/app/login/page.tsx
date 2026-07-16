"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { setAuth } from "@/lib/auth"

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      })

      // 先按 text 读取，再尝试 JSON.parse — 避免非 JSON 响应（502/网络错误）被 SyntaxError 误导
      const raw = await res.text()
      let data: { token?: string; username?: string; error?: string; detail?: string | Array<{ msg?: string }> } = {}
      try {
        data = raw ? JSON.parse(raw) : {}
      } catch {
        throw new Error(
          `服务器返回了非 JSON 内容（HTTP ${res.status}）— ${raw.slice(0, 80) || "空响应"}`
        )
      }

      if (!res.ok) {
        const detailMsg = Array.isArray(data.detail)
          ? data.detail.map((d) => d.msg).join("; ")
          : data.detail
        throw new Error(data.error || detailMsg || `登录失败（HTTP ${res.status}）`)
      }

      if (!data.token || !data.username) {
        throw new Error("登录响应缺少 token 或 username 字段")
      }

      setAuth(data.token, data.username)
      router.push("/")
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-none bg-primary text-sm font-bold text-primary-foreground">
            SA
          </div>
          <CardTitle>登录 StockAI</CardTitle>
          <CardDescription>使用管理员账号登录</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && (
              <p className="text-xs text-red-500">{error}</p>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "登录中..." : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
