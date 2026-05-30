# TODOS

## 待办事项

### T1: 搭建 pytest 测试框架
- **What:** 创建 requirements-dev.txt (pytest, pytest-asyncio, httpx)、pytest.ini 配置、tests/ 目录结构
- **Why:** 当前项目 0% 测试覆盖。复盘引擎引入核心业务逻辑 (aggregate/parse/fallback)，没有测试无法保证正确性
- **Pros:** 为后续所有功能提供测试基础设施；面试官看到测试是加分项
- **Cons:** 需要学习 pytest-asyncio 的 async test 写法
- **Context:** FastAPI + SQLite 项目。测试策略：纯函数用 pytest，API 端点用 httpx + pytest-asyncio
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-eng-review

### T5: SVG 图标替换全站 Emoji
- **What:** 用 Heroicons SVG 替换侧边栏导航图标、空状态图标、页面标题 emoji
- **Why:** emoji 在面试 demo 中降低产品专业感；专业图标是"这是认真做的产品"的信号
- **Pros:** 面试加分、视觉一致性提升、SVG 体积可忽略
- **Cons:** 需要替换 ~20 处 emoji 引用（renderSidebar、showLoading/showEmpty/showError、initPage）
- **Context:** 使用 Heroicons MIT 协议，内联 SVG 避免额外网络请求
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T6: PWA 离线降级 UI
- **What:** 添加 navigator.onLine 检测 + 离线横幅 UI（顶部提示"当前离线，显示缓存数据"）
- **Why:** service worker 已注册但所有 api() 调用在离线时静默失败，用户无感知
- **Pros:** PWA 完整性提升
- **Cons:** 面试 demo 场景离线概率低
- **Context:** common.js 中加全局 online/offline 事件监听 + CSS 横幅组件
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T7: CSS 重试按钮 + 数据新鲜度指示器
- **What:** 1) common.css 新增 .btn-retry 样式（刷新图标 + 文字）；2) market.html 加"最后更新于 XX:XX:XX"时间戳
- **Why:** 内联错误横幅需要统一的重试按钮样式；面试官可能注意到市场数据无新鲜度指示
- **Pros:** 极低成本（几行 CSS + 一个 span）
- **Cons:** 几乎没有
- **Context:** .btn-retry 与现有 .btn-outline 区分（前者有刷新图标和 error 配色）
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T2: Playwright E2E 测试
- **What:** 用 Playwright 覆盖核心用户流程：持仓仪表盘加载、AI 对话交互、大盘指数展示、复盘报告生成、键盘快捷键
- **Why:** 前端是纯 vanilla JS，没有框架保护，UX 回归风险高。面试官 demo 时任何一个白屏都会扣分
- **Pros:** 捕获跨浏览器兼容性问题；CI 可自动运行
- **Cons:** 需要安装 Node.js 依赖和浏览器驱动 (~200MB)；测试速度较慢
- **Context:** 等待 pytest 基础设施 (T1) 就绪后实施。测试文件放在 tests/e2e/
- **Depends on:** T1
- **Added:** 2026-05-30 by /plan-eng-review

### T5: SVG 图标替换全站 Emoji
- **What:** 用 Heroicons SVG 替换侧边栏导航图标、空状态图标、页面标题 emoji
- **Why:** emoji 在面试 demo 中降低产品专业感；专业图标是"这是认真做的产品"的信号
- **Pros:** 面试加分、视觉一致性提升、SVG 体积可忽略
- **Cons:** 需要替换 ~20 处 emoji 引用（renderSidebar、showLoading/showEmpty/showError、initPage）
- **Context:** 使用 Heroicons MIT 协议，内联 SVG 避免额外网络请求
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T6: PWA 离线降级 UI
- **What:** 添加 navigator.onLine 检测 + 离线横幅 UI（顶部提示"当前离线，显示缓存数据"）
- **Why:** service worker 已注册但所有 api() 调用在离线时静默失败，用户无感知
- **Pros:** PWA 完整性提升
- **Cons:** 面试 demo 场景离线概率低
- **Context:** common.js 中加全局 online/offline 事件监听 + CSS 横幅组件
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T7: CSS 重试按钮 + 数据新鲜度指示器
- **What:** 1) common.css 新增 .btn-retry 样式（刷新图标 + 文字）；2) market.html 加"最后更新于 XX:XX:XX"时间戳
- **Why:** 内联错误横幅需要统一的重试按钮样式；面试官可能注意到市场数据无新鲜度指示
- **Pros:** 极低成本（几行 CSS + 一个 span）
- **Cons:** 几乎没有
- **Context:** .btn-retry 与现有 .btn-outline 区分（前者有刷新图标和 error 配色）
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T3: Docker 化部署
- **What:** 编写 Dockerfile + docker-compose.yml，实现一键启动 (frontend + backend + SQLite)
- **Why:** 降低面试官本地运行门槛；代码质量信号
- **Pros:** 标准化运行环境，消除"在我机器上能跑"问题
- **Cons:** Windows 上 Docker Desktop 资源消耗大
- **Context:** 已有 start.bat。Dockerfile 基于 python:3.12-slim，静态文件用 FastAPI StaticFiles 挂载
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-eng-review

### T5: SVG 图标替换全站 Emoji
- **What:** 用 Heroicons SVG 替换侧边栏导航图标、空状态图标、页面标题 emoji
- **Why:** emoji 在面试 demo 中降低产品专业感；专业图标是"这是认真做的产品"的信号
- **Pros:** 面试加分、视觉一致性提升、SVG 体积可忽略
- **Cons:** 需要替换 ~20 处 emoji 引用（renderSidebar、showLoading/showEmpty/showError、initPage）
- **Context:** 使用 Heroicons MIT 协议，内联 SVG 避免额外网络请求
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T6: PWA 离线降级 UI
- **What:** 添加 navigator.onLine 检测 + 离线横幅 UI（顶部提示"当前离线，显示缓存数据"）
- **Why:** service worker 已注册但所有 api() 调用在离线时静默失败，用户无感知
- **Pros:** PWA 完整性提升
- **Cons:** 面试 demo 场景离线概率低
- **Context:** common.js 中加全局 online/offline 事件监听 + CSS 横幅组件
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T7: CSS 重试按钮 + 数据新鲜度指示器
- **What:** 1) common.css 新增 .btn-retry 样式（刷新图标 + 文字）；2) market.html 加"最后更新于 XX:XX:XX"时间戳
- **Why:** 内联错误横幅需要统一的重试按钮样式；面试官可能注意到市场数据无新鲜度指示
- **Pros:** 极低成本（几行 CSS + 一个 span）
- **Cons:** 几乎没有
- **Context:** .btn-retry 与现有 .btn-outline 区分（前者有刷新图标和 error 配色）
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T4: GitHub Actions CI/CD
- **What:** 配置 .github/workflows/ci.yml: 安装依赖 → 运行 pytest → lint (ruff)
- **Why:** 自动化测试运行，PR 时自动验证；面试官看到 CI 配置是专业信号
- **Pros:** 免费 (公开仓库)，配置简单 (~30 行 YAML)
- **Cons:** 需要 GitHub Secrets 配置 API key（可跳过 AI 测试）
- **Context:** 放在 T1 完成后。矩阵测试 python 3.11/3.12
- **Depends on:** T1
- **Added:** 2026-05-30 by /plan-eng-review

### T5: SVG 图标替换全站 Emoji
- **What:** 用 Heroicons SVG 替换侧边栏导航图标、空状态图标、页面标题 emoji
- **Why:** emoji 在面试 demo 中降低产品专业感；专业图标是"这是认真做的产品"的信号
- **Pros:** 面试加分、视觉一致性提升、SVG 体积可忽略
- **Cons:** 需要替换 ~20 处 emoji 引用（renderSidebar、showLoading/showEmpty/showError、initPage）
- **Context:** 使用 Heroicons MIT 协议，内联 SVG 避免额外网络请求
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T6: PWA 离线降级 UI
- **What:** 添加 navigator.onLine 检测 + 离线横幅 UI（顶部提示"当前离线，显示缓存数据"）
- **Why:** service worker 已注册但所有 api() 调用在离线时静默失败，用户无感知
- **Pros:** PWA 完整性提升
- **Cons:** 面试 demo 场景离线概率低
- **Context:** common.js 中加全局 online/offline 事件监听 + CSS 横幅组件
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review

### T7: CSS 重试按钮 + 数据新鲜度指示器
- **What:** 1) common.css 新增 .btn-retry 样式（刷新图标 + 文字）；2) market.html 加"最后更新于 XX:XX:XX"时间戳
- **Why:** 内联错误横幅需要统一的重试按钮样式；面试官可能注意到市场数据无新鲜度指示
- **Pros:** 极低成本（几行 CSS + 一个 span）
- **Cons:** 几乎没有
- **Context:** .btn-retry 与现有 .btn-outline 区分（前者有刷新图标和 error 配色）
- **Depends on:** —
- **Added:** 2026-05-30 by /plan-design-review
