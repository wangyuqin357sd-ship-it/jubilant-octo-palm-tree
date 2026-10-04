@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 语忆 · 手机预览

echo.
echo   ==============================================================
echo     语忆 · 手机预览  正在启动（安卓手机请用 https 打开）
echo   ==============================================================
echo.

where python >nul 2>nul
if not %errorlevel%==0 (
  echo   没有找到 python，无法启动。
  echo   请先装 Python 3；证书生成还需要：pip install cryptography
  echo.
  pause
  goto :eof
)

echo   手机和电脑要连同一个 WiFi / 热点。
echo   下面会打印手机该打开的 https 地址和 4 步操作。
echo.

python "%~dp0_tools\serve-mobile.py"

echo.
echo   服务已停止。按任意键关闭窗口。
pause >nul