@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 语忆 · 手机 USB 直连（插上就能用）

rem 与「小语」的同名脚本保持一致的思路，但**不动别的项目的端口映射**：
rem 只管理本项目的 8790(http) / 8444(https)，不执行 adb reverse --remove-all。

set ADB=
for %%p in ("D:\a'a'a\pcsuite\adb\adb.exe" "D:\a'a'a\pcsuite\adb_41\adb.exe" "D:\Androws\Application\5.10.7500.6534\adb.exe" "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe") do (
  if exist %%p if "%ADB%"=="" set ADB=%%~p
)
if "%ADB%"=="" ( where adb >nul 2>nul && set ADB=adb )
if "%ADB%"=="" (
  echo   没找到 adb.exe。请用数据线连上手机，并打开「开发者选项 -^> USB 调试」。
  echo   或改用无线：双击「手机预览.bat」，用打印出来的 https 地址。
  pause
  exit /b
)

echo.
echo   ================================================================
echo     语忆 · 手机 USB 直连
echo   ================================================================
echo.
echo   先双击「手机预览.bat」把服务起起来，再运行本脚本。
echo   保持这个窗口开着：
echo     · 手机插上  -^> 自动建立端口映射并打开页面
echo     · 拔掉再插上 -^> 自动重建
echo     · 手机弹「允许 USB 调试」-^> 点允许
echo.
echo   手机地址：http://127.0.0.1:8790/
echo     （127.0.0.1 被浏览器视为可信来源，所以走 http 也有振动/通知，
echo       而且没有自签名证书那个「不安全」提示）
echo.

set LAST=
:loop
set CUR=
for /f "tokens=1,2" %%a in ('""%ADB%" devices" 2^>nul') do (
  if "%%b"=="device" set CUR=%%a
  if "%%b"=="unauthorized" set CUR=unauthorized
)
if "%CUR%"=="" (
  if not "%LAST%"=="" echo   [%time:~0,8%] 手机已断开，等待重新插入…
  set LAST=
) else if "%CUR%"=="unauthorized" (
  if not "%LAST%"=="unauth" echo   [%time:~0,8%] 手机还没授权：请在手机上点「允许 USB 调试」
  set LAST=unauth
) else (
  if not "%LAST%"=="ok" (
    echo   [%time:~0,8%] 检测到手机 %CUR%，建立端口映射…
    "%ADB%" reverse tcp:8790 tcp:8790 >nul 2>&1
    "%ADB%" reverse tcp:8444 tcp:8444 >nul 2>&1
    "%ADB%" shell am start -a android.intent.action.VIEW -d "http://127.0.0.1:8790/" >nul 2>&1
    echo   [%time:~0,8%] 已就绪：手机上语忆预览已打开
    echo              ^(打开后先点一下页面，振动才会生效；再去待办面板点「试一次振动」验证马达^)
    set LAST=ok
  )
)
timeout /t 2 /nobreak >nul
goto loop