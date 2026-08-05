@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Danus 桌面版
echo ============================================
echo   Danus 桌面版 - 数学证明搜索（DeepSeek）
echo ============================================
echo.

rem 如果程序已经在运行，就直接打开浏览器，避免端口冲突导致“前端没了”
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo 程序已在运行（端口 8765 已占用），直接打开浏览器...
  start "" http://127.0.0.1:8765
  exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python。请先安装 Python 3.10+（安装时勾选 "Add python.exe to PATH"），
  echo         然后重新双击本文件。
  echo 下载地址: https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 首次运行：正在创建虚拟环境并安装依赖（约 1~3 分钟，请耐心等待）...
  python -m venv .venv
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet fastapi uvicorn pydantic openai psutil "mcp>=1.2,<2" -e .
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
  echo 依赖安装完成。
)

echo 正在启动（浏览器将自动打开 http://127.0.0.1:8765 ）...
echo 关闭本窗口即退出程序。
echo.
".venv\Scripts\python.exe" -m app
pause