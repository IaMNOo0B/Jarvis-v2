@echo off
cd /d "%~dp0"
python -m jarvis.chat --data-dir "%~dp0data"
pause
