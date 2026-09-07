@echo off
setlocal
cd /d "%~dp0.."
C:\Python312\python.exe _pack_pcl_ui.py
exit /b %ERRORLEVEL%
