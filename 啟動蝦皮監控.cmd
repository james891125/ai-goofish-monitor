@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if errorlevel 1 goto directory_failed
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" goto missing_powershell
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0start.ps1" -DoubleClick
set "LaunchResult=%ERRORLEVEL%"
if "%LaunchResult%"=="0" goto finished
echo.
echo 啟動未完成，請先看上方的錯誤訊息；本視窗會保留。
echo 若訊息指出 PowerShell 原則封鎖，請依下方說明處理。
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$m=Get-ExecutionPolicy -Scope MachinePolicy; $u=Get-ExecutionPolicy -Scope UserPolicy; if ($m -ne 'Undefined' -or $u -ne 'Undefined') { exit 20 }; if ((Get-ExecutionPolicy) -eq 'RemoteSigned') { exit 10 }; exit 20"
if errorlevel 20 goto policy_admin
if errorlevel 10 goto policy_remote
goto policy_admin
:policy_remote
echo 目前為 RemoteSigned。僅限確認下載來源與內容可信後：
echo 在檔案總管右鍵 start.ps1 → 內容 → 勾選「解除封鎖」→ 套用。
echo 若沒有此選項或仍被封鎖，請交由管理員檢查；本工具不會變更原則。
goto finished
:policy_admin
echo AllSigned、Restricted 或組織原則需由管理員提供核准／簽署的腳本。
echo 請勿降低執行原則、關閉 SmartScreen 或改用其他途徑繞過封鎖。
goto finished
:directory_failed
set "LaunchResult=1"
echo 無法開啟專案資料夾，請完整解壓縮 ZIP 到本機資料夾後重試。
goto finished
:missing_powershell
set "LaunchResult=1"
echo 找不到 Windows PowerShell，請請管理員確認 Windows 安裝。
:finished
echo.
echo 工作已結束。若主程式仍在原視窗執行，請保留原視窗。
pause
exit /b %LaunchResult%
