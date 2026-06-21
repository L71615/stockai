export type ProtectedPageAuthState = "checking" | "authenticated" | "unauthenticated"

export function getProtectedPageAuthState({
  hasHydrated,
  isAuthenticated,
}: {
  hasHydrated: boolean
  isAuthenticated: boolean
}): ProtectedPageAuthState {
  if (!hasHydrated) {
    return "checking"
  }

  return isAuthenticated ? "authenticated" : "unauthenticated"
}
