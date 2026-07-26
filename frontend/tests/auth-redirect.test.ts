import test from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { shouldHandleUnauthorized } = require("../src/lib/auth-redirect.ts") as {
  shouldHandleUnauthorized: typeof import("../src/lib/auth-redirect").shouldHandleUnauthorized
}

test("401 handler should redirect only on unauthorized responses", () => {
  assert.equal(shouldHandleUnauthorized(401), true)
  assert.equal(shouldHandleUnauthorized(200), false)
  assert.equal(shouldHandleUnauthorized(500), false)
})
