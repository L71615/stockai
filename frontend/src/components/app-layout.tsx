"use client"

import { usePathname, useRouter } from "next/navigation"
import { useEffect, useMemo, useSyncExternalStore } from "react"
import useSWR from "swr"
import { TooltipProvider } from "@/components/ui/tooltip"
import { SidebarProvider, SidebarTrigger, SidebarInset } from "@/components/ui/sidebar"
import { AppSidebar } from "@/components/app-sidebar"
import { SWRProvider, swrFetcher } from "@/lib/swr-config"
import { isAuthenticated } from "@/lib/auth"
import { getProtectedPageAuthState } from "@/lib/protected-page-auth"

const subscribe = () => () => {}

function VersionBadge() {
  const { data } = useSWR<{ version: string }>("/api/version", swrFetcher)
  return <span className="text-sm text-muted-foreground font-mono">v{data?.version ?? "?.?"}</span>
}

export function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const hasHydrated = useSyncExternalStore(subscribe, () => true, () => false)

  const authState = useMemo(() => {
    if (pathname === "/login") {
      return "login" as const
    }

    return getProtectedPageAuthState({
      hasHydrated,
      isAuthenticated: hasHydrated ? isAuthenticated() : false,
    })
  }, [pathname, hasHydrated])

  // 首屏先走统一占位，避免服务端和客户端因 localStorage 认证状态不同而 hydration 失败。
  useEffect(() => {
    if (authState === "unauthenticated") {
      router.replace("/login")
    }
  }, [authState, router])

  if (authState === "login") {
    return <>{children}</>
  }

  if (authState === "checking" || authState === "unauthenticated") {
    return null
  }

  return (
    <SWRProvider>
      <TooltipProvider>
        <SidebarProvider defaultOpen={true}>
          <AppSidebar />
          <SidebarInset>
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
              <SidebarTrigger />
              <VersionBadge />
            </header>
            <div className="flex flex-1 flex-col">{children}</div>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </SWRProvider>
  )
}
