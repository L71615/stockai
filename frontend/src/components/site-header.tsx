"use client"

/**
 * 页面标题栏 — 只展示页面标题，不再放 SidebarTrigger
 * SidebarTrigger 由 app-layout.tsx 的全局 Top header 提供（DESIGN.md §Navigation）
 */
export function SiteHeader({ title = "持仓概览" }: { title?: string }) {
  return (
    <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-4 lg:px-6">
      <h1 className="text-base font-medium">{title}</h1>
    </header>
  )
}