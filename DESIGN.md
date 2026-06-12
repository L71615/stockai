# Design System — StockAI

## Product Context
- **What this is:** A-share investment review and AI coaching platform. Users record trades from brokerages, track holdings, and get AI-driven analysis (behavior patterns, risk warnings, profit/loss attribution).
- **Who it's for:** Interviewers and recruiters evaluating the product (primary); the developer for daily use (secondary).
- **Space/industry:** Fintech — Chinese stock market tools (peers: 同花顺, 东方财富, 雪球, 富途牛牛).
- **Project type:** Web dashboard — FastAPI backend (port 3000) + Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4 (port 3001).

## North Star
**"Clarity in a noisy market."** Chinese stock tools are walls of red/green numbers with no hierarchy. StockAI's visual system delivers calm, clear, intentional data display. Every number on screen earns its place.

## Aesthetic Direction
- **Direction:** Industrial-Utilitarian + Editorial
- **Decoration level:** Minimal — typography and spacing do all the work. No glassmorphism, no glow effects, no decorative elements. The data IS the decoration.
- **Mood:** Trustworthy, calm, precise. Like a well-designed financial report, not a trading floor. The AI feels like a thoughtful analyst, not a chatbot.
- **Key differentiators from category:**
  1. Calm density — fewer data points per screen, more context per position
  2. Editorial AI panels — AI insights rendered like magazine pull quotes with left-border accent (`border-l-[3px] border-l-purple-400`), distinct from raw data zones

## Tech Stack
- **Framework:** Next.js 16 (App Router, Turbopack)
- **UI:** shadcn/ui (Radix primitives) + Tailwind CSS 4
- **Icons:** @tabler/icons-react
- **Charts:** recharts
- **Theme:** oklch-based CSS variables via shadcn preset (neutral monochrome). Sharp corners (`--radius: 0`).
- **Dark mode:** Default (`<html class="dark">`), no light mode toggle.
- **Fonts:** System font stack for UI; JetBrains Mono for data/tables (configured in `globals.css` via `@theme inline`).

## Typography
- **Body/UI:** System font stack — `-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif`. Configured as `--font-sans` in `globals.css`.
- **Data/Tables:** JetBrains Mono — `"JetBrains Mono", "SF Mono", "Cascadia Code", monospace`. Configured as `--font-mono` in `globals.css`.
- **Scale (Tailwind defaults, base 14px):**
  - `text-xs` (12px): labels, captions, tertiary info
  - `text-sm` (14px): secondary text, table cells, tags
  - `text-base` (16px): body, navigation, form inputs
  - `text-lg` (18px): section headings
  - `text-xl` (20px): KPI values, page titles
  - `text-2xl` (24px): hero numbers
  - `font-mono` applied to all numeric data columns via `tabular-nums`

## Color
- **Theme system:** shadcn oklch preset (neutral monochrome). CSS variables in `globals.css` under `:root` and `.dark`.
- **Primary accent:** oklch-based neutral primary — used for buttons, active nav, focus rings.
- **AI insight accent:** `border-l-purple-400` / `text-purple-400` — distinguishes AI-generated content from raw data. Used only for AI panel left borders and labels.
- **Semantic (Chinese market convention — red = rise, green = fall):**
  - `text-red-500` / `bg-red-500/5` / `border-red-500/20` — up / positive / profit (always paired with "+" sign)
  - `text-emerald-500` / `bg-emerald-500/5` / `border-emerald-500/20` — down / negative / loss (always paired with "-" sign)
  - `text-yellow-500` — warning / caution
  - `text-purple-400` — AI insight (not a data state)

## Layout
- **Sidebar:** shadcn `<Sidebar>` component, 16rem width, `collapsible="icon"`, `variant="sidebar"`. Collapses with Ctrl+B.
- **Sidebar navigation:** 3 collapsible groups (投资 / 分析 / 工具) with Lucide-style tabler icons. Active route highlighted via `usePathname()`.
- **Header:** `<SiteHeader>` with `<SidebarTrigger>` + breadcrumb separator + page title.
- **Content area:** `<SidebarInset>` wrapper. Card-based KPI row at top (4 columns desktop, 2 tablet, 1 mobile via `@xl/main` and `@5xl/main` container queries).
- **Max content width:** Unconstrained for dashboard; 720px for AI reading views (via `max-w-2xl`).
- **Border radius:** `--radius: 0` globally — sharp corners everywhere (buttons, cards, inputs, badges).

## Component Patterns
- **KPI Cards:** `<Card>` with `bg-gradient-to-t from-primary/5 to-card`, `<CardTitle>` in `font-mono text-2xl`, `<Badge>` with colored trend icon.
- **Data Tables:** shadcn `<Table>` with sticky `<TableHeader className="bg-muted">`, `font-mono tabular-nums` for numeric columns, red/green P&L coloring, draggable rows via `@dnd-kit`.
- **AI Panels:** `<Card className="border-l-[3px] border-l-purple-400">` with italic AI quote text.
- **Charts:** recharts `<AreaChart>` with `<ChartContainer>` wrapper, red area fill for total asset growth.
- **Loading:** `Skeleton` shimmer (pulse animation). No spinner — skeleton is the loading pattern everywhere.
- **Error:** Inline error card with `border-red-500/20 bg-red-500/5` + retry button.
- **Empty:** Centered card with emoji icon + description text + CTA link.

## Motion
- **Approach:** Minimal-functional. No decorative animation, no page transitions.
- **Micro:** Tailwind `transition-colors` on hover states.
- **Skeleton:** Pulse animation via shadcn Skeleton component.
- **Sidebar:** Collapse/expand with CSS transitions via shadcn Sidebar.
- **Map:** SVG `<animate>` for city pulse dots on global-news page.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-05-30 | Initial design system created | Based on office-hours product context and competitive fintech landscape research |
| 2025-05-30 | System font stack for Chinese body text | Web fonts for Chinese are 5-15MB and render poorly |
| 2025-05-30 | JetBrains Mono for numbers | Tabular-nums for aligned data columns; precision character |
| 2025-05-30 | AI insight purple distinct from primary | Visual distinction between "raw data" and "AI analysis" zones |
| 2025-06-12 | Migrated to Next.js + shadcn/ui + Tailwind 4 | Replaced vanilla HTML/JS frontend; kept oklch neutral theme from shadcn preset |
| 2025-06-12 | Sharp corners (`--radius: 0`) | Clean, industrial-utilitarian aesthetic per user preference |
| 2025-06-12 | Red/green P&L with +/- symbols | Chinese market convention; +/- signs ensure colorblind accessibility |
| 2025-06-12 | shadcn Sidebar with collapsible groups | 3-group navigation (投资/分析/工具) for 12-page information architecture |
| 2025-06-12 | dashboard-01 template as layout baseline | SectionCards → Chart → DataTable dashboard structure, customized for stock data |
