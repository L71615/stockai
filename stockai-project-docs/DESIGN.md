# DESIGN.md — StockAI Design System

StockAI 投研平台的设计约定。所有 UI 决策参考此文件。

## Colors

使用 shadcn/ui 暗色主题（`.dark`），基于 oklch 色彩空间。

### Theme Tokens
- background: near-black #1a1a1a
- foreground: near-white #fafafa
- card: dark gray #2a2a2a
- muted: #3a3a3a, muted-foreground: #adadad
- border: subtle white at 10% opacity
- destructive: red accent

### Consensus Badge Colors (共识标签)
| Label | Color |
|-------|-------|
| 全票通过 | emerald/green |
| 多数通过 | blue |
| 分歧较大 | yellow/orange |
| 少数推荐 | muted-gray |
| 风险否决 | destructive red + IconX |

## Typography

- Sans: PingFang SC, Microsoft YaHei, system fonts
- Mono: JetBrains Mono, SF Mono — for numbers/scores/prices
- Body: 12-14px. Headings: 14px medium. Badges: 10px.
- Always `tabular-nums` for numeric columns

## Border Radius

`--radius: 0` — sharp corners. No rounded cards. Data-dense APP UI.

## Spacing

- Card padding: 12px (p-3)
- Section gap: 16px (space-y-4)
- Table cells: 8px (p-2)

## Components

- **Card**: independent info blocks, `rounded-none`, `border-border`
- **Badge**: tags/status/labels, 10px, secondary or outline variant
- **Table**: ranking data, sticky header, monospace numbers
- **Button**: size=sm default, Tabler Icons at size-3.5 (14px)
- **Skeleton**: loading states, same layout structure as content

## Icons

Tabler Icons (`@tabler/icons-react`) only. No emoji as functional identifiers.

Agent role icon map: value=IconCoin, technical=IconChartBar, risk=IconShield, sentiment=IconFlame, macro=IconWorld

## Interaction States

All data-driven components must handle 4 states:
- Loading: Skeleton matching content layout
- Empty: inline message + primary action
- Error: inline Alert + error message + retry button
- Success: full data display

## Responsive

- Desktop: grid-cols-2 xl:grid-cols-3
- Mobile: grid-cols-1 stacked, tables overflow-x-auto
- Touch targets: >= 44px

## Navigation

Sidebar + Header (`app-layout.tsx`):
- Left sidebar: primary nav
- Top header: h-12, SidebarTrigger + version

## Anti-Patterns

- No emoji as functional icons
- No centered large text blocks
- No purple gradient backgrounds
- No decorative Card wrappers
- No large border-radius
