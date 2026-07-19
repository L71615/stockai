@echo off
REM StockAI Backend 停止
chcp 65001 >nul

echo === Stopping StockAI Backend ===
echo.

netstat -ano 2>nul | findstr ":3000.*LISTEN" >nul
if %errorlevel%==1 (
    echo [INFO] Port 3000 not in use, backend not running
    pause
    exit /b 0
)

REM 找占 3000 端口的 PID
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTEN"') do (
    set "PID=%%a"
)

echo Killing PID %PID% (port 3000)...
taskkill /F /PID %PID%
if %errorlevel%==0 (
    echo [OK] Backend stopped
) else (
    echo [ERROR] Failed to stop backend
)

echo.
pause