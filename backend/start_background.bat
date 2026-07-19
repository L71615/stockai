@echo off
REM StockAI Backend 后台启动 — 关闭终端不杀
REM 用法: start_background.bat  (从 cmd 或文件管理器双击)
chcp 65001 >nul

echo === StockAI Backend (Background) ===
echo.

cd /d D:\stocks\backend

REM 检查 3000 端口是否已占用
netstat -ano 2>nul | findstr ":3000.*LISTEN" >nul
if %errorlevel%==0 (
    echo [WARN] Port 3000 already in use, backend may already be running
    echo       URL: http://localhost:3000
    pause
    exit /b 0
)

echo Starting backend in background (logs: backend.log)...
echo URL: http://localhost:3000
echo.
echo To stop: taskkill /F /PID <PID>
echo         or run stop_background.bat
echo.

REM 关键: /B 不开新窗口 + 立即返回, 不阻塞当前 shell
REM 日志输出到 backend.log, 不需要新 cmd 窗口
start /B "StockAI Backend" cmd /c "python -m uvicorn main:app --host 0.0.0.0 --port 3000 --env-file .env > D:\stocks\backend\backend.log 2>&1"

REM 等 5 秒让 uvicorn 启动
timeout /t 5 /nobreak >nul

REM 验证启动成功
netstat -ano 2>nul | findstr ":3000.*LISTEN" >nul
if %errorlevel%==0 (
    echo [OK] Backend started, port 3000 LISTENING
    echo      Logs: tail -f D:\stocks\backend\backend.log
) else (
    echo [ERROR] Backend not started, check backend.log
    echo Last 20 lines of log:
    powershell -Command "Get-Content D:\stocks\backend\backend.log -Tail 20"
)

echo.
pause