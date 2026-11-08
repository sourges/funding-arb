@echo off
title FUNDING - cross-venue logger
cd /d "%~dp0"
timeout /t 30 /nobreak
call venv\Scripts\activate.bat
python main_cross.py
pause
