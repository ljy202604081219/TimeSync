@echo off
setlocal
cd /d "%~dp0"
rem UTF-8 everywhere: Python files, pip logs and uvicorn output are UTF-8,
rem while a default Chinese Windows console still uses cp936/GBK.
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python 3.12+ is required. Install it from https://www.python.org/downloads/ , then run again.
    pause
    exit /b 1
  )
  py -3 -X utf8 run.py %*
) else (
  python -X utf8 run.py %*
)
rem Keep the window open only when something went wrong, so a double-click shows
rem the error and non-interactive runs (CI, start.cmd --check) never block.
if errorlevel 1 pause
