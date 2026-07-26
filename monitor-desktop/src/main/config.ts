/**
 * stockai 路径/端口配置 — 仅做绝对路径读取,不动 stockai 任何代码
 */

import path from "node:path"
import os from "node:os"

// 默认假设 stockai 项目在 D:\stocks\
// 监视器位于 D:\stocks\monitor-desktop\
// 自动从 monitor-desktop 推断 stockai 根目录
function detectStockaiRoot(): string {
  // 监视器位于 monitor-desktop/src/main/config.ts
  // ../../../ 即 D:\stocks\
  const inferred = path.resolve(__dirname, "..", "..", "..")
  return inferred
}

export const config = {
  stockaiRoot: detectStockaiRoot(),
  databasePath: path.resolve(detectStockaiRoot(), "database", "stockai.db"),
  schemaPath: path.resolve(detectStockaiRoot(), "database", "schema.sql"),
  backendLogDir: path.resolve(detectStockaiRoot(), "backend", "logs"),
  apiBaseUrl: "http://localhost:3000",
  apiHealthUrl: "http://localhost:3000/api/health",
  apiPipelineStatusUrl: "http://localhost:3000/api/pipeline/status",
  ports: {
    backend: 3000,
    frontend: 3001,
  },
  refreshIntervalMs: 5000,
  hostname: os.hostname(),
}
