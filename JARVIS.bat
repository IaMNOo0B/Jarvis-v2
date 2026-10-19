@echo off
REM JARVIS v2 — double-click me. That's it.
cd /d "%~dp0"

REM --- F-05: never die silently. Check python first. ---
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [JARVIS] Python not found. Install Python 3.11+ from python.org,
    echo  then double-click me again. Tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

REM --- F-07: single instance. A second double-click just nudges you. ---
set "JARVIS_LOCK=%TEMP%\jarvis-v2.lock"
if exist "%JARVIS_LOCK%" (
    echo.
    echo  [JARVIS] Already running — look for the JARVIS window.
    echo  If it's stuck, delete %JARVIS_LOCK% and try again.
    echo.
    pause
    exit /b 0
)
echo %date% %time% > "%JARVIS_LOCK%"

python -m jarvis.chat_gui
set "RC=%errorlevel%"
del "%JARVIS_LOCK%" 2>nul

if not "%RC%"=="0" (
    echo.
    echo  [JARVIS] Something went wrong ^(code %RC%^). Take a photo of this
    echo  window and send it to Ovi — he'll know what to do.
    echo.
    pause
)
