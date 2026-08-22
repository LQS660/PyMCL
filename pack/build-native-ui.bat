@echo off
REM Native WinUI + C bridge (no Edge). Needs .NET 8 Desktop + Windows App Runtime.
setlocal
cd /d "%~dp0.."
set "PY=C:\Python312\python.exe"
if not exist "%PY%" set "PY=python"
call native\build.bat
if errorlevel 1 exit /b 1
"%PY%" -u _pack_native_ui.py
endlocal
