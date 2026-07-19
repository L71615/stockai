' StockAI Backend 隐藏启动 (真正脱离父进程)
' 双击或在 cmd 里: wscript start_hidden.vbs

Set WshShell = CreateObject("WScript.Shell")

' start /B 不开新窗口, 后台跑
' 0 = 隐藏窗口, False = 不等待
WshShell.Run "cmd /c cd /d D:\stocks\backend && python -m uvicorn main:app --host 0.0.0.0 --port 3000 --env-file .env > D:\stocks\backend\backend.log 2>&1", 0, False

WScript.Quit 0