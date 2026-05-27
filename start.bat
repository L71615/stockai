@echo off
title StockAI Control Panel
cd /d D:\stocks\backend

:menu
cls
echo ==========================================
echo         StockAI Control Panel
echo ==========================================
echo   [1] Start Backend
echo   [2] Restart Backend
echo   [3] Stop Backend
echo   [4] Install Python Dependencies
echo   [5] Open in Browser
echo   [Q] Quit
echo ==========================================
echo   Backend:  http://localhost:3000
echo   API Doc:  http://localhost:3000/api/docs
echo ==========================================
echo.

set /p "opt=Enter option: "

if /i "%opt%"=="1" goto start
if /i "%opt%"=="2" goto restart
if /i "%opt%"=="3" goto stop
if /i "%opt%"=="4" goto install
if /i "%opt%"=="5" goto open
if /i "%opt%"=="q" goto quit
echo Invalid option
timeout /t 1 >nul
goto menu

:start
cls
echo Checking backend status...
netstat -ano 2>nul | findstr ":3000.*LISTEN" >nul
if %errorlevel%==0 (
    echo Backend already running: http://localhost:3000
) else (
    echo Starting backend...
    start "StockAI Backend" /MIN cmd /c "cd /d D:\stocks\backend && python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload"
    echo Waiting 3 seconds...
    timeout /t 3 >nul
    echo Started: http://localhost:3000
)
echo.
echo Press any key to return...
pause >nul
goto menu

:restart
cls
echo Stopping backend...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3000.*LISTEN"') do taskkill /F /PID %%a 2>nul
timeout /t 1 >nul
echo Starting backend...
start "StockAI Backend" /MIN cmd /c "cd /d D:\stocks\backend && python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload"
echo Waiting 3 seconds...
timeout /t 3 >nul
echo Restarted: http://localhost:3000
echo.
echo Press any key to return...
pause >nul
goto menu

:stop
cls
echo Stopping backend...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3000.*LISTEN"') do taskkill /F /PID %%a 2>nul
echo Backend stopped.
echo.
echo Press any key to return...
pause >nul
goto menu

:install
cls
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Done.
echo.
echo Press any key to return...
pause >nul
goto menu

:open
cls
echo Opening browser...
start http://localhost:3000
echo.
echo Press any key to return...
pause >nul
goto menu

:quit
echo Goodbye!
exit /b 0
