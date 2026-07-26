import test from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { getHoldingRowActionLabels } = require("../src/lib/holding-row-actions.ts") as {
  getHoldingRowActionLabels: typeof import("../src/lib/holding-row-actions").getHoldingRowActionLabels
}

test("holding row actions expose all expected menu labels", () => {
  assert.deepEqual(getHoldingRowActionLabels(), ["编辑", "查看详情", "加入自选", "删除"])
})
