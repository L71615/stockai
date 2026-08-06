/** v5.2 — /screener/condition 已合并到 /screener?tab=condition
 * 此页面保留为深链兼容 — 301 重定向到新位置
 */
import { redirect } from "next/navigation"

export default function ConditionRedirect() {
  redirect("/screener?tab=condition")
}