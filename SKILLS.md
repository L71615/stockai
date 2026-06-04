# StockAI 项目技能参考

## 项目专属技能（本仓库）

| 技能 | 命令 | 什么时候用 |
|------|------|-----------|
| **run-stockai** | `/run-stockai` | 刚 clone 项目、换了新机器、不确定服务能不能跑。一键装依赖→启动→验证 9 个核心 API→停止 |
| **qa-stockai** | `/qa-stockai` | 改完代码准备 push。全站检查 8 个页面 + Canvas 图表 + 常见故障模式（"加载中…"卡住 / 图不显示 / Tooltip 漂移） |
| **debug-stockai** | `/debug-stockai` | 出问题了但不知道原因。5 步排查：①服务器有没有加载新代码 ②前端渲染问题 ③数据源问题 ④数据库问题 ⑤AI 配置问题 |

### 典型使用流程

```
改代码 → /qa-stockai → 通过了 → /ship 推送
                       → 没过 → /debug-stockai → 修 → /qa-stockai
新机器 → /run-stockai → 9 个 API 全过 → 可以开始开发
"为什么 XX 没显示" → /debug-stockai → Step 1 → Step 2 → 定位
```

---

## 通用技能（gstack 体系）

### 开发流程

| 技能 | 什么时候用 |
|------|-----------|
| `/office-hours` | 有新想法、产品脑暴、不确定做什么 |
| `/plan-ceo-review` | 决定产品方向、排优先级 |
| `/plan-eng-review` | 决定技术方案、架构设计 |
| `/plan-design-review` | 决定 UI/UX 方案 |
| `/design-consult` | 需要设计建议 |
| `/autoplan` | 大功能开工前，全流程规划（产品→工程→设计） |

### 代码质量

| 技能 | 什么时候用 |
|------|-----------|
| `/review` | PR 提交前做代码审查 |
| `/code-review` | 审查当前改动，找 bug 和可优化点 |
| `/simplify` | 重构冗余代码，提升可读性（不找 bug） |
| `/investigate` | 追查 bug 根因 |
| `/verify` | 验证一个改动是否真的生效（启动 App 观察行为） |

### 发布部署

| 技能 | 什么时候用 |
|------|-----------|
| `/ship` | 提交代码、写 commit message、推送到 GitHub |
| `/land-and-deploy` | 需要部署上线（含 canary、回滚方案） |
| `/setup-deploy` | 首次部署配置 |

### 测试

| 技能 | 什么时候用 |
|------|-----------|
| `/qa` | 全功能 QA 测试（人工 + 自动化） |
| `/qa-only` | 仅跑 QA 检查，不做代码分析 |
| `/benchmark` | 性能基准测试 |

### 文档

| 技能 | 什么时候用 |
|------|-----------|
| `/document-release` | 写 Release Notes |
| `/document-generate` | 生成项目文档 |
| `/spec` | 写功能规格说明书 |

---

## 本项目设计系统

设计决策在 `DESIGN.md`，任何视觉相关的改动都应该先读它。

- `backend/services/` — 数据源适配器（腾讯/Baostock/新浪/天天基金）
- `frontend/quant.html` — 量化分析页（K线+成交量+因子+AI对抗）
- `frontend/settings.html` — 多供应商 AI 配置（MiniMax/DeepSeek/小米/Claude/OpenAI）
- `tests/` — pytest 测试（45 pass / 2 skip）
