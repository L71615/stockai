import test from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { getProtectedPageAuthState } = require("../src/lib/protected-page-auth.ts") as {
  getProtectedPageAuthState: typeof import("../src/lib/protected-page-auth").getProtectedPageAuthState
}

test("protected page stays in checking state before hydration", () => {
  assert.equal(
    getProtectedPageAuthState({
      hasHydrated: false,
      isAuthenticated: true,
    }),
    "checking"
  )
})

test("protected page redirects only after hydration when unauthenticated", () => {
  assert.equal(
    getProtectedPageAuthState({
      hasHydrated: true,
      isAuthenticated: false,
    }),
    "unauthenticated"
  )
})

test("protected page can render after hydration when authenticated", () => {
  assert.equal(
    getProtectedPageAuthState({
      hasHydrated: true,
      isAuthenticated: true,
    }),
    "authenticated"
  )
})
