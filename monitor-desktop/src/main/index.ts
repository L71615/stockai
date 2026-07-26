/**
 * StockAI 后端监视器 — Electron 主进程入口
 */

import { app, BrowserWindow, ipcMain, shell } from "electron"
import path from "node:path"
import { config } from "./config"
import { startMonitor, getCurrentSnapshot } from "./monitor/process"
import {
  getLogs,
  getLogStats,
  subscribeLogs,
  startHealthProbe,
  clearLogs,
} from "./monitor/logger"
import { getDbSummary, getTableDetail, refreshDb } from "./monitor/database"
import { getPipelineStatus, startPipelineProbe } from "./monitor/pipeline"

const isDev = process.env.NODE_ENV === "development"

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
  process.exit(0)
}

let mainWindow: BrowserWindow | null = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 720,
    title: "StockAI 后端监视器",
    backgroundColor: "#1a1d24",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  if (isDev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, "../../dist/index.html"))
  }

  mainWindow.once("ready-to-show", () => {
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: "deny" }
  })

  mainWindow.on("closed", () => {
    mainWindow = null
  })
}

app.whenReady().then(() => {
  createWindow()

  // 启动监控线程(每 5s 采集一次)
  startMonitor({ intervalMs: config.refreshIntervalMs })

  // 启动 stockai /api/health 心跳 → 形成 access log
  startHealthProbe(config.apiHealthUrl, config.refreshIntervalMs)

  // 启动 pipeline 状态轮询(每 10s)
  startPipelineProbe(config.apiPipelineStatusUrl, 10000)

  // 注册 IPC 通道
  ipcMain.handle("monitor:get-snapshot", () => getCurrentSnapshot())
  ipcMain.handle("monitor:get-config", () => ({
    refreshIntervalMs: config.refreshIntervalMs,
    stockaiRoot: config.stockaiRoot,
  }))

  ipcMain.handle("monitor:get-logs", (_e, limit?: number) => getLogs(limit))
  ipcMain.handle("monitor:get-log-stats", () => getLogStats())
  ipcMain.handle("monitor:clear-logs", () => clearLogs())

  ipcMain.handle("monitor:get-db-summary", () => getDbSummary())
  ipcMain.handle("monitor:get-table-detail", (_e, name: string) => getTableDetail(name))
  ipcMain.handle("monitor:refresh-db", () => refreshDb())

  ipcMain.handle("monitor:get-pipeline-status", () => getPipelineStatus())

  // 日志变化时推送事件给渲染进程
  subscribeLogs(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("monitor:logs-updated")
    }
  })

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit()
})

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
})