import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

const PUBLIC_PATHS = ["/login"]

/**
 * Next.js Middleware — 统一认证守卫
 *
 * - 检查 stockai_token cookie
 * - 无 token -> 重定向到 /login
 * - 已登录访问 /login -> 重定向到 /
 * - 静态资源 / API 请求不做认证检查
 *
 * 效果: 14 个页面不再需要 useEffect + isAuthenticated() 检查
 */
export function middleware(request: NextRequest) {
  const token = request.cookies.get("stockai_token")?.value
  const { pathname } = request.nextUrl

  // API / static / Next.js 内部路径放行
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next()
  }

  // 公开路径: /login
  if (PUBLIC_PATHS.includes(pathname)) {
    // 已登录则跳回首页
    if (token) {
      return NextResponse.redirect(new URL("/", request.url))
    }
    return NextResponse.next()
  }

  // 需要认证的路径 — 无 token -> /login
  if (!token) {
    const loginUrl = new URL("/login", request.url)
    // 登录后跳回原页面
    loginUrl.searchParams.set("redirect", pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  // 匹配所有路径，排除静态资源和 Next.js 内部文件
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
