# Design System — StockAI

## Product Context
- **What this is:** A-share investment review and AI coaching platform. Users record trades from brokerages, track holdings, and get AI-driven analysis (behavior patterns, risk warnings, profit/loss attribution).
- **Who it's for:** Interviewers and recruiters evaluating the product (primary); the developer for daily use (secondary).
- **Space/industry:** Fintech — Chinese stock market tools (peers: 同花顺, 东方财富, 雪球, 富途牛牛).
- **Project type:** Web dashboard — FastAPI backend + vanilla JS frontend, dark theme, data-dense views.

## North Star
**"Clarity in a noisy market."** Chinese stock tools are walls of red/green numbers with no hierarchy. StockAI's visual system delivers calm, clear, intentional data display. Every number on screen earns its place.

## Aesthetic Direction
- **Direction:** Industrial-Utilitarian + Editorial
- **Decoration level:** Minimal — typography and spacing do all the work. No glassmorphism, no glow effects, no decorative elements. The data IS the decoration.
- **Mood:** Trustworthy, calm, precise. Like a well-designed financial report, not a trading floor. The AI feels like a thoughtful analyst, not a chatbot.
- **Key differentiators from category:**
  1. Calm density — fewer data points per screen, more context per position
  2. Editorial AI panels — AI insights rendered like magazine pull quotes with left-border accent, distinct from raw data zones

## Typography
- **Body/UI:** System font stack — `-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif`. Pragmatic choice for Chinese text (web fonts for Chinese are 5-15MB and render poorly).
- **Data/Tables:** JetBrains Mono — `"JetBrains Mono", "SF Mono", "Cascadia Code", monospace`. Tabular-nums for aligned columns, professional character, recognizable to engineers.
- **Code:** JetBrains Mono (same as data).
- **Loading:** Google Fonts for JetBrains Mono (Latin subset only, ~40KB).
- **Scale (modular, base 14px):**
  - `--text-xs`: 11px (labels, captions, tertiary info)
  - `--text-sm`: 13px (secondary text, table cells, tags)
  - `--text-base`: 14px (body, navigation, form inputs)
  - `--text-lg`: 16px (section headings, AI insight headlines)
  - `--text-xl`: 20px (KPI values, page titles)
  - `--text-2xl`: 28px (hero numbers, major section breaks)
  - `--text-3xl`: 36px (dashboard hero, report titles)

## Color
- **Approach:** Restrained — 1 accent + neutrals. Color is rare and meaningful. The only vibrant colors are red/green for P&L.
- **Primary accent:** `#7c8ae0` — softer indigo than the previous `#5c6bc0`. Used for primary buttons, active nav, links, focus rings.
- **AI insight accent:** `#c4b5fd` — warm purple, distinguishes AI-generated content from raw data. Used only for AI panel borders and labels.
- **Neutrals (warm-gray, blue undertone — calmer than pure gray):**
  - `#0a0c14` — deepest background (near-black with blue undertone)
  - `#141722` — surface / sidebar background
  - `#1a1e2b` — card background
  - `#242836` — card hover / elevated surface
  - `#2a2f3d` — elevated surface (dialogs, dropdowns)
  - `#2d3342` — subtle borders
  - `#3a4050` — strong borders / input borders
- **Text:**
  - `#e8eaed` — primary text (warm white, not harsh pure white)
  - `#9ca3af` — secondary / muted text
  - `#6b7280` — tertiary / placeholder text
- **Semantic (Chinese market convention — red = rise, green = fall):**
  - `#ef5350` — up / positive / profit (always paired with "+" sign for colorblind accessibility)
  - `#26a69a` — down / negative / loss (always paired with "-" sign)
  - `#f59e0b` — warning / caution
  - `#3b82f6` — info / neutral

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable — more whitespace than typical fintech. This IS the clarity differentiator.
- **Scale:** `--space-2xs: 2px`, `--space-xs: 4px`, `--space-sm: 8px`, `--space-md: 16px`, `--space-lg: 24px`, `--space-xl: 32px`, `--space-2xl: 48px`, `--space-3xl: 64px`
- **Max content width:** 1200px (dashboard), 720px (AI report reading view)

## Layout
- **Approach:** Grid-disciplined — strict columns for data tables and KPIs; editorial asymmetry for AI insight panels to create visual distinction between "data" and "analysis" zones.
- **Sidebar:** 200px fixed left sidebar, collapses on mobile (<768px) to bottom tab bar.
- **Content area:** Flexible grid, card-based KPI row at top (4 columns desktop, 2 mobile), table below, AI panels as editorial inserts.
- **Border radius:** `--radius-sm: 4px` (buttons, inputs, tags), `--radius-md: 8px` (cards), `--radius-lg: 12px` (modals, large panels), `--radius-full: 9999px` (pills, badges)

## Motion
- **Approach:** Minimal-functional — only transitions that aid comprehension. No decorative animation, no page transitions, no scroll-driven effects.
- **Easing:** enter = `ease-out` (cubic-bezier(0.16, 1, 0.3, 1)), exit = `ease-in` (cubic-bezier(0.4, 0, 1, 1))
- **Duration:**
  - micro (50-100ms): hover state changes
  - short (150-250ms): number value changes, tag appearances
  - medium (250-400ms): panel expand/collapse, skeleton shimmer
- **Skeleton loading:** Pulse animation, 1.5s cycle, gradient shimmer over card-color base. No spinner — skeleton is the loading pattern everywhere.

## Shadows
- `--shadow-card: 0 1px 3px rgba(0,0,0,0.3)` — subtle card elevation
- `--shadow-elevated: 0 4px 12px rgba(0,0,0,0.4)` — dialogs, dropdowns
- No glow effects. No colored shadows. Shadows are grayscale only.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-30 | Initial design system created | Created by /design-consultation based on office-hours product context and competitive fintech landscape research |
| 2026-05-30 | North Star: "Clarity in a noisy market" | Chinese stock platforms are visually chaotic; StockAI's differentiation is visual calm and intentional data display |
| 2026-05-30 | System font stack for Chinese body text | Web fonts for Chinese are 5-15MB and render poorly; system fonts are the pragmatic choice |
| 2026-05-30 | JetBrains Mono for numbers | Tabular-nums essential for aligned data columns; monospace adds precision character without decorative weight |
| 2026-05-30 | AI insight accent (#c4b5fd) distinct from primary (#7c8ae0) | Visual distinction between "raw data" and "AI analysis" zones — the editorial risk |
| 2026-05-30 | Calm density as deliberate risk | Showing fewer data points with more context serves clarity; competitors show 50 stocks, StockAI shows 10 with reasoning |
| 2026-05-30 | No glassmorphism, no glow, no decorative elements | Anti-slop stance; the "stealth finance" neon-on-dark trend is the new purple gradient |
| 2026-05-30 | Red/green P&L with +/- symbols | Chinese market convention (red=rise) is non-negotiable; +/- signs ensure colorblind accessibility (from plan-design-review D14) |
