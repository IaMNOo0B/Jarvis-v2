@echo off
REM JARVIS v2 setup — double-click to run. No terminal needed.
REM 1. Checks Python exists. 2. Runs preflight. 3. First-run wizard if
REM needed. 4. Starts the chat.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo JARVIS needs Python 3.11 or newer to run.
    echo.
    echo Please install it from the Python website, ticking the box that
    echo adds Python to PATH, then double-click this file again.
    echo.
    pause
    exit /b 1
)

python -m jarvis.setup --wizard
if errorlevel 1 (
    echo.
    echo Setup did not finish. Fix the items above, then double-click
    echo this file again — it picks up where it left off.
    echo.
    pause
    exit /b 1
)

python -m jarvis.chat
pause
