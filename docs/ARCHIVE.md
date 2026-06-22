# 文档归档说明

## 项目文档演进

```
2026-05-20  MVP 阶段
  │         docs/PROJECT_PLAN.md           ← 早期技术栈规划
  │         docs/TODOS.md (T1-T10)         ← 早期待办清单
  │
2026-05-30  AI 投资教练计划
  │         docs/superpowers/plans/
  │           ai-investment-coach.md       ← 复盘引擎实现计划
  │
2026-06-12  Next.js 重构
  │         前后端分离, 12 页面完成
  │
2026-06-14  第三方审计
  │         docs/ROADMAP.md ← 此后作为唯一未来计划
  │
2026-06-21  文档整合
  │         旧文档内容 → 吸收到 CHANGELOG.md
  │         融合计划   → 合并到 ROADMAP.md
  │         本文件     ← 归档说明
  ▼         CHANGELOG.md + ROADMAP.md = 唯一真相源
```

## 当前活跃文档

| 文件 | 位置 | 作用 |
|------|------|------|
| `CHANGELOG.md` | 项目根目录 | 从 MVP 到现在的完整发展历程（按时间倒序） |
| `docs/ROADMAP.md` | docs/ | 已完成 + 待完成 + 融合计划（唯一未来计划） |
| `docs/ARCHIVE.md` | docs/ | 本文件——归档说明 |
| `docs/README.md` | docs/ | 文档索引 |

## 已归档的文件

以下文件的内容已被吸收到 CHANGELOG.md 或 ROADMAP.md 中，原始文件已删除：

| 文件 | 吸收到 | 主要内容 |
|------|--------|----------|
| `docs/TODOS.md` | CHANGELOG (2026-05-30 条目) | 早期 T1-T10 待办，大部分已完成 |
| `docs/PROJECT_PLAN.md` | CHANGELOG (2026-05-20 条目) | 早期技术栈规划 (Vanilla JS → FastAPI) |
| `docs/superpowers/plans/...md` | CHANGELOG (2026-05-30 条目) | AI 投资教练复盘引擎实现计划 |

## 阅读指引

- **想了解项目怎么发展到今天** → 看 `CHANGELOG.md`（按时间线从上到下）
- **想知道接下来做什么** → 看 `docs/ROADMAP.md`（已完成 + 待完成 + 融合计划）
- **想找某个旧文档内容** → 在 `CHANGELOG.md` 中搜索对应日期
