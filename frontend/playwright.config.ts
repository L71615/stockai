import { defineConfig, devices } from "@playwright/test"

/**
 * Playwright E2E 配置
 *
 * 跑法:
 *   # 1. 启动后端 (port 3000) + 前端 (port 3001)
 *      start.bat 选项 3
 *   # 2. 在 frontend/ 目录运行:
 *      npx playwright test
 *   # 3. (可选) UI 模式:
 *      npx playwright test --ui
 *   # 4. (可选) 只跑一个文件:
 *      npx playwright test e2e/login.spec.ts
 *
 * 注意: CI 默认不跑 E2E（需要前后端服务）。本地手动跑。
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3001",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: process.env.CI ? {
    command: "npm run start",
    url: "http://localhost:3001",
    reuseExistingServer: true,
    timeout: 120_000,
  } : undefined,
})
