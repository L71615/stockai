# StockAI — 项目根目录入口

> 欢迎来到 StockAI 项目。本文件是根目录入口,**所有 MD 文档已整理到下面两个文件夹**。

---

## 📁 文档结构(2 个文件夹 + 1 个根目录入口)

```
D:\stocks\
├── CLAUDE.md                       ← Claude Code 入会必读(留在根目录)
├── INDEX.md                        ← 本文件(根目录入口)
│
├── stockai-project-docs/           ← 📘 StockAI 项目 MD
│   ├── README.md                   ← 项目主入口
│   ├── README.en.md                ← English
│   ├── CHANGELOG.md                ← 完整变更日志
│   ├── DESIGN.md                   ← 设计系统(权威)
│   ├── TODOS.md                    ← 待办
│   ├── AGENTS.md                   ← Agent 工作流
│   ├── ROADMAP.md                  ← 路线图
│   ├── RUNBOOK.md                  ← 运行手册
│   ├── ARCHIVE.md                  ← 归档说明
│   └── designs/ + superpowers/     ← 设计稿 + 旧 spec
│
└── monitor-desktop-docs/           ← 🖥️ 后端监视器 MD
    ├── PLAN.md                     ← 监视器计划(技术栈/UI/10 决策)
    └── DAILY-LOG.md                ← 监视器每日改动日志
```

---

## 🎯 项目说明

### StockAI 主项目

- **类型**: A 股量化研究 + 回测 + 预测
- **后端**: Python FastAPI (端口 3000)
- **前端**: Next.js 16 (端口 3001)
- **数据库**: SQLite (WAL 模式)
- **当前版本**: v3.10 (2026-07-23)
- **核心能力**: 55 因子 / 13 策略 / AI 选股 / 自动量化 Pipeline
- **项目入口**: `stockai-project-docs/README.md`
- **设计系统**: `stockai-project-docs/DESIGN.md`
- **变更日志**: `stockai-project-docs/CHANGELOG.md`

### 后端监视器(独立子项目)

- **类型**: Electron 桌面 app,**纯观察,deep freeze**
- **位置**: `D:\stocks\monitor-desktop/`(代码) + `monitor-desktop-docs/`(文档)
- **目的**: 实时观察 stockai 后端进程、日志、数据库结构
- **特点**: 独立 gitignore,**对 stockai 0 改动**
- **计划**: `monitor-desktop-docs/PLAN.md`
- **每日改动**: `monitor-desktop-docs/DAILY-LOG.md`

---

## 🚀 快速索引

| 我想看... | 打开这个文件 |
|----------|--------------|
| 项目是什么 | `stockai-project-docs/README.md` |
| 怎么启动 | `stockai-project-docs/README.md` (快速启动段) |
| 设计规范 | `stockai-project-docs/DESIGN.md` |
| 完整变更历史 | `stockai-project-docs/CHANGELOG.md` |
| 项目路线图 | `stockai-project-docs/ROADMAP.md` |
| 运行手册 | `stockai-project-docs/RUNBOOK.md` |
| 待办事项 | `stockai-project-docs/TODOS.md` |
| 监视器计划 | `monitor-desktop-docs/PLAN.md` |
| 监视器改动 | `monitor-desktop-docs/DAILY-LOG.md` |
| 文档归档说明 | `stockai-project-docs/ARCHIVE.md` |
| Agent 工作流 | `stockai-project-docs/AGENTS.md` |

---

## 📂 目录约定

| 目录 | 用途 |
|------|------|
| `backend/` | StockAI 后端 FastAPI |
| `frontend/` | StockAI 前端 Next.js |
| `tests/` | StockAI 测试 |
| `docs/` | StockAI 文档(部分,已分离) |
| `database/` | StockAI SQLite 数据库文件 |
| `scripts/` | StockAI 辅助脚本 |
| `reports/` | StockAI 运行报告(quant brief) |
| `stockai-project-docs/` | **Project MD 一类**(项目文档) |
| `monitor-desktop-docs/` | **Monitor MD 一类**(监视器文档) |
| `monitor-desktop/` | **监视器代码**(后续建,gitignore) |

---

## 📝 文档重组日期

**2026-07-26**: MD 文件分类整理,从根目录移入 `stockai-project-docs/` + `monitor-desktop-docs/`。
