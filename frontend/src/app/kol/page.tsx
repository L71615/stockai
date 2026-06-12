"use client"

import { SiteHeader } from "@/components/site-header"
import { Card, CardContent } from "@/components/ui/card"

export default function KolPage() {
  return (
    <>
      <SiteHeader title="大佬观点" />
      <div className="flex flex-1 flex-col overflow-auto p-4 lg:p-6">
        <Card>
          <CardContent className="py-16 text-center space-y-3">
            <p className="text-5xl opacity-30">🚧</p>
            <p className="text-sm text-muted-foreground font-medium">功能开发中</p>
            <p className="text-xs text-muted-foreground max-w-md mx-auto">
              追踪 X(Twitter) 财经大 V 观点，AI 自动生成每日投资情绪日报。
              <br />
              此功能需要配置代理访问 X.com，将在后续版本中正式上线。
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
