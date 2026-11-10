@echo off
rem One-click launcher for Windows. Double-click this file.
rem All real work (and all Chinese messages) lives in start.py.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 start.py
    goto done
)
where python >nul 2>nul
if %errorlevel%==0 (
    python start.py
    goto done
)
echo.
echo [ERROR] Python was not found.
echo Please install Python 3.10+ from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, then run this file again.

:done
echo.
pause
endlocal
