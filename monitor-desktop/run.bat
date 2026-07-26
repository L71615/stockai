@echo off
title StockAI 后端监视器
cd /d "%~dp0"

echo ==========================================
echo    StockAI 后端监视器 启动脚本
echo ==========================================
echo.

REM 检查 node_modules
if not exist "node_modules" (
    echo 首次运行,正在安装依赖...
    set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
    call npm install
    if errorlevel 1 (
        echo 依赖安装失败!
        pause
        exit /b 1
    )
)

REM 启动 vite dev server(会自动打开 Electron 窗口)
echo 启动监视器...
echo 关闭窗口即可退出
echo.
call npm run dev

pause
