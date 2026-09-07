@echo off
rem PyMCL launcher - double-click to open the GUI
rem Keep this file ASCII-only: cmd.exe on Chinese Windows reads bat files as GBK.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.9+ first: https://www.python.org/downloads/
    pause
    exit /b 1
)
python main.py %*
if errorlevel 1 pause
