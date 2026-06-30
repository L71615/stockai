"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import useSWR from "swr"
import { swrFetcher } from "@/lib/swr-config"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar"
import {
  IconLayoutDashboard,
  IconStar,
  IconChartBar,
  IconChartScatter,
  IconSearch,
  IconFilter,
  IconFileInvoice,
  IconNotebook,
  IconRobot,
  IconSettings,
  IconChevronDown,
} from "@tabler/icons-react"

const navGroups = [
  {
    id: "invest",
    label: "投资",
    icon: IconChartBar,
    defaultOpen: true,
    items: [
      { id: "holdings", label: "持仓概览", icon: IconLayoutDashboard, url: "/" },
      { id: "watchlist", label: "自选股", icon: IconStar, url: "/watchlist" },
      { id: "market", label: "大盘指数", icon: IconChartBar, url: "/market" },
    ],
  },
  {
    id: "analysis",
    label: "分析",
    icon: IconChartScatter,
    defaultOpen: true,
    items: [
      { id: "quant", label: "量化分析", icon: IconChartScatter, url: "/quant" },
      { id: "condition", label: "条件选股", icon: IconFilter, url: "/screener/condition" },
      { id: "screener", label: "AI 选股", icon: IconSearch, url: "/screener" },
    ],
  },
  {
    id: "tools",
    label: "工具",
    icon: IconRobot,
    defaultOpen: true,
    items: [
      { id: "transactions", label: "交易记录", icon: IconFileInvoice, url: "/transactions" },
      { id: "journal", label: "交易日志", icon: IconNotebook, url: "/journal" },
      { id: "ai-chat", label: "AI 对话", icon: IconRobot, url: "/ai-assistant" },
      { id: "settings", label: "设置", icon: IconSettings, url: "/settings" },
    ],
  },
]

export function AppSidebar() {
  const pathname = usePathname()
  const [openGroups, setOpenGroups] = React.useState<Record<string, boolean>>({
    invest: true,
    analysis: true,
    tools: true,
  })

  const { data: versionData } = useSWR<{ version: string }>("/api/version", swrFetcher)
  const version = versionData?.version ?? "?.?"

  const toggleGroup = (id: string) => {
    setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 pt-3 pb-1">
          <div className="flex size-6 items-center justify-center rounded-none bg-primary text-[10px] font-bold text-primary-foreground">
            SA
          </div>
          <div className="flex flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold tracking-tight">StockAI</span>
            <span className="text-[10px] text-muted-foreground">投资复盘 · AI 教练</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {navGroups.map((group, gi) => (
          <React.Fragment key={group.id}>
            {gi > 0 && <SidebarSeparator />}
            <SidebarGroup>
              <Collapsible
                open={openGroups[group.id]}
                onOpenChange={() => toggleGroup(group.id)}
                className="group/collapsible"
              >
                <SidebarGroupLabel asChild>
                  <CollapsibleTrigger className="cursor-pointer hover:text-sidebar-foreground w-full flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <group.icon className="size-3.5" />
                      <span>{group.label}</span>
                    </span>
                    <IconChevronDown className="size-3 transition-transform duration-200 group-data-[state=closed]/collapsible:-rotate-90" />
                  </CollapsibleTrigger>
                </SidebarGroupLabel>
                <CollapsibleContent>
                  <SidebarGroupContent>
                    <SidebarMenu>
                      {group.items.map((item) => (
                        <SidebarMenuItem key={item.id}>
                          <SidebarMenuButton
                            asChild
                            isActive={pathname === item.url}
                            tooltip={item.label}
                          >
                            <Link href={item.url}>
                              <item.icon className="size-4" />
                              <span>{item.label}</span>
                            </Link>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      ))}
                    </SidebarMenu>
                  </SidebarGroupContent>
                </CollapsibleContent>
              </Collapsible>
            </SidebarGroup>
          </React.Fragment>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <div className="px-3 py-2 space-y-1">
          <p className="text-[10px] text-muted-foreground font-mono group-data-[collapsible=icon]:hidden">
            StockAI v{version}
          </p>
          <p className="text-[10px] text-muted-foreground group-data-[collapsible=icon]:hidden">
            <kbd className="rounded-none border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">Ctrl+B</kbd>{" "}
            收起侧边栏
          </p>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
