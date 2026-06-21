export type AppLayoutAuthState =
  | "login"
  | "checking"
  | "authenticated"
  | "unauthenticated"

export function getAppLayoutAuthState({
  pathname,
  hasHydrated,
  isAuthenticated,
}: {
  pathname: string
  hasHydrated: boolean
  isAuthenticated: boolean
}): AppLayoutAuthState {
  if (pathname === "/login") {
    return "login"
  }

  if (!hasHydrated) {
    return "checking"
  }

  return isAuthenticated ? "authenticated" : "unauthenticated"
}
