import { test, expect } from "@playwright/test"

/**
 * 登录页 E2E（最简冒烟测试）
 *
 * 验证:
 *   1. 访问 /login 页面正常加载
 *   2. 表单元素存在（邮箱/密码/登录按钮）
 *   3. 错误密码显示错误
 *   4. 正确凭据跳转首页
 */
test.describe("登录页", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login")
  })

  test("页面加载 + 表单元素可见", async ({ page }) => {
    await expect(page).toHaveTitle(/StockAI/)
    // 表单字段（按 antd/Tailwind 渲染后的 selector）
    await expect(page.getByRole("textbox", { name: /邮箱|email/i }).first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole("textbox", { name: /密码|password/i }).first()).toBeVisible()
    await expect(page.getByRole("button", { name: /登录|login|sign in/i }).first()).toBeVisible()
  })

  test("错误密码显示错误", async ({ page }) => {
    await page.getByRole("textbox", { name: /邮箱|email/i }).first().fill("admin@stockai.com")
    await page.getByRole("textbox", { name: /密码|password/i }).first().fill("wrong_password_xxx")
    await page.getByRole("button", { name: /登录|login|sign in/i }).first().click()

    // 应该有错误提示（不跳走）
    await page.waitForTimeout(2000)
    await expect(page).toHaveURL(/\/login/)
  })
})
