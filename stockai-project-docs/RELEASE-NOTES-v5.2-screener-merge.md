# StockAI v5.2 — 选股中心(单页面 + Tab)

**发布日: 2026-08-07**
**代号: v5.2-screener-merge**

> 🎯 **解决"侧边栏噪音"** — AI 选股 + 条件选股 合并为单页面 / 选股中心,减 1 个侧边栏入口

---

## 🎯 一句话

把分散在两个页面的选股功能(AI 选股 + 条件选股)合并到单页面 `/screener`,通过 Tab 切换。侧边栏减 1 个入口,两个心智模型保留。

---

## ✨ 改动清单

| 能力 | 之前 | v5.2 |
|---|---|---|
| 入口 | 2 个侧边栏项(AI 选股 + 条件选股) | 1 个"选股中心" |
| 页面 | `/screener` + `/screener/condition` | 单页 `/screener` + Tab 切换 |
| Tab 状态 | N/A | URL `?tab=` + localStorage 跨刷新记忆 |
| 深链兼容 | N/A | `/screener/condition` 自动重定向 |

---

## 🎨 新 UI 结构

```
📊 /screener  (选股中心)
├── Tab 1: 🧠 AI 选股      ← 原 /screener
└── Tab 2: ⚙️ 条件选股    ← 原 /screener/condition
```

**侧边栏**: 移除"条件选股",只剩"选股中心"。

---

## 🏗️ 架构

### 组件拆分
| 文件 | 职责 |
|------|------|
| `frontend/src/app/screener/page.tsx` | Tab 容器(URL 同步 + localStorage) |
| `frontend/src/components/ai-screener.tsx` | AI 选股逻辑(从 page.tsx 提取) |
| `frontend/src/components/condition-screener.tsx` | 条件选股逻辑(从 condition/page.tsx 提取) |
| `frontend/src/app/screener/condition/page.tsx` | 1 行 redirect 到 `/screener?tab=condition` |

### Tab 状态管理
- **URL 同步**: `?tab=ai|condition` 写 URL(用 `router.replace`,不触发导航)
- **localStorage**: `screener:activeTab` 跨刷新记忆
- **默认**: `ai`
- **优先级**: URL > localStorage > 默认

### 深链兼容
- 老 `/screener/condition` → `redirect('/screener?tab=condition')` (Next.js server redirect)

---

## 📁 文件清单

### 新增 (2)
- `frontend/src/components/ai-screener.tsx`
- `frontend/src/components/condition-screener.tsx`

### 改动 (3)
- `frontend/src/app/screener/page.tsx` — 重写为 Tab 容器(从 607 行降到 92 行)
- `frontend/src/app/screener/condition/page.tsx` — 简化为 1 行 redirect
- `frontend/src/components/app-sidebar.tsx` — 移除 "条件选股" 入口

---

## 🚀 启用步骤

无需配置,前端自动热重载:
```bash
# 已重启 next dev 即可
# 浏览器: http://localhost:3001/screener
# 老链接 http://localhost:3001/screener/condition 自动跳转
```

---

## 🚧 已知限制

- **localStorage vs URL**: URL 优先,但 SSR 初始渲染时拿不到 URL → 初次渲染用默认 `ai`,然后 `useEffect` 切换。可能有一帧闪烁。
- **Tab state 不持久到 server**: 纯客户端状态,刷新会重新从 URL/localStorage 读。
- **没有 keyboard shortcut 切 Tab**: 用户需鼠标点。如有需要可加 `Cmd+1/2`。

---

## 📌 下一步

- **v5.2 完成** — 选股中心合并上线
- **下一步**: 试跑 1 周收集 UX 反馈 + 优化 AI 录入体验
- **可选**: Tab 状态持久化到 server (deferred)

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**