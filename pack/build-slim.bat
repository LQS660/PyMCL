@echo off
REM PCL-style slim package: C bridge + www UI, NO WinUI/WASDK inside.
REM Requires system Edge. Target: dist\PyMCL.exe under 5MB.
setlocal
cd /d "%~dp0.."
set "PY=C:\Python312\python.exe"
if not exist "%PY%" set "PY=python"
call native\build.bat
if errorlevel 1 exit /b 1
pushd eziapp
if not exist dist\index.html call npm run build:web
popd
"%PY%" -u _pack_slim.py
endlocal
