@echo off
chcp 65001 >nul
title 图书套装主图生成工具

echo 正在启动服务...
start "图书套装主图工具" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --port 8000"

timeout /t 3 >nul

echo 正在打开浏览器...
start http://127.0.0.1:8000

echo.
echo 关闭「图书套装主图工具」黑色窗口即可停止服务。
pause
