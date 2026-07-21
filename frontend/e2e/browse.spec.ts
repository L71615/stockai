import { test, expect } from "@playwright/test"

/**
 * /browse 页面 E2E（v3.9 关键页）
 *
 * 前置：需要登录（admin@stockai.com / 实际密码）
 * 此测试假设已经有有效 token 存在 localStorage
 */
test.describe("股票浏览页（v3.9）", () => {
  test.beforeEach(async ({ page, context }) => {
    // 注入 localStorage token（跳过登录页）
    await context.addInitScript(() => {
      // 实际 token 应该是真实有效的；测试时由 setup 步骤生成
      // 这里仅做 placeholder，CI 应在 beforeAll 真实登录
      localStorage.setItem("stockai_token", "PLACEHOLDER")
    })
    await page.goto("/browse")
  })

  test("页面能加载（即使无数据也不应 crash）", async ({ page }) => {
    // 不报 500 / 渲染错误
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {})
    // 标题或侧边栏应存在
    const bodyText = await page.locator("body").innerText()
    expect(bodyText.length).toBeGreaterThan(100)
  })
})
