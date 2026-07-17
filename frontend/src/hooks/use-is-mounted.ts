"use client"

/**
 * useIsMounted — 跟踪组件是否仍挂载, 防止 setState on unmounted component
 *
 * 解决问题: Next.js 16 + React 19 严格模式 + 路由切换快
 *   错误: "Object is disposed" / "Can't perform a React state update on an unmounted component"
 *
 * 用法:
 *   const isMounted = useIsMounted()
 *   useEffect(() => {
 *     fetchSomething().then((data) => {
 *       if (isMounted.current) setState(data)
 *     })
 *   }, [])
 */
import { useEffect, useRef } from "react"

export function useIsMounted() {
  const isMounted = useRef(false)

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  return isMounted
}