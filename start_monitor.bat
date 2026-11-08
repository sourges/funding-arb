@echo off
title FUNDING - ETH monitor (paper)
cd /d "%~dp0"
timeout /t 30 /nobreak
call venv\Scripts\activate.bat
python main_monitor.py
pause
