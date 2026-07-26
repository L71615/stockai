import test from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { createHoldingRowActionHandlers } = require("../src/lib/holding-row-actions.ts") as {
  createHoldingRowActionHandlers: typeof import("../src/lib/holding-row-actions").createHoldingRowActionHandlers
}

test("holding row action handlers call the matching callbacks", () => {
  const calls: string[] = []
  const row = { code: "600519", name: "贵州茅台" }

  const handlers = createHoldingRowActionHandlers(row, {
    onEdit: (item: typeof row) => calls.push(`edit:${item.code}`),
    onView: (item: typeof row) => calls.push(`view:${item.code}`),
    onAddToWatchlist: (item: typeof row) => calls.push(`watch:${item.code}`),
    onDelete: (item: typeof row) => calls.push(`delete:${item.code}`),
  })

  handlers.edit()
  handlers.view()
  handlers.addToWatchlist()
  handlers.delete()

  assert.deepEqual(calls, [
    "edit:600519",
    "view:600519",
    "watch:600519",
    "delete:600519",
  ])
})
