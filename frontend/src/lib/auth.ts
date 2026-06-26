"use client"

import { shouldHandleUnauthorized } from "./auth-redirect"

const TOKEN_KEY = "stockai_token"
const USER_KEY = "stockai_user"

let unauthorizedRedirectPending = false

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(TOKEN_KEY)
}

export function getUsername(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(USER_KEY)
}

export function setAuth(token: string, username: string) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, username)
  // 同步 cookie 供 middleware 使用
  document.cookie = `stockai_token=${token}; path=/; max-age=${2 * 3600}; SameSite=Lax`
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  // 清除 middleware cookie
  document.cookie = "stockai_token=; path=/; max-age=0"
}

export function isAuthenticated(): boolean {
  return !!getToken()
}

function redirectToLoginOnce() {
  if (typeof window === "undefined" || unauthorizedRedirectPending) {
    return
  }

  unauthorizedRedirectPending = true
  window.location.replace("/login")
}

interface ApiOptions extends RequestInit {
  signal?: AbortSignal
}

async function apiRequest<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const token = getToken()
  const { signal, ...rest } = options
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const res = await fetch(path, { ...rest, signal, headers })
  if (shouldHandleUnauthorized(res.status)) {
    clearAuth()
    redirectToLoginOnce()
    throw new Error("登录已过期")
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { error?: string }).error || `HTTP ${res.status}`)
  }
  return res.json()
}

export function apiGet<T = unknown>(path: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, { signal })
}

export function apiPost<T = unknown>(path: string, body?: unknown, method = "POST", signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, {
    method,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
}
