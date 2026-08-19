@echo off
rem PyMCL build script using cx_Freeze.
rem This works even when PyInstaller crashes with "KeyError: 'CACHE'"
rem on a Python installation with mixed/broken stdlib files.
rem Keep this file ASCII-only.
cd /d "%~dp0"

python -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo [1/3] Installing cx-Freeze (small, one-time)...
python -m pip install "cx-Freeze"
if errorlevel 1 (
    echo [ERROR] Failed to install cx-Freeze. Try manually: pip install cx-Freeze
    pause
    exit /b 1
)

echo [2/3] Building PyMCL.exe ...
if exist dist_cx rmdir /s /q dist_cx
python cx_setup.py build_exe --build-exe dist_cx
if errorlevel 1 (
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo [3/3] Done!
echo.
echo ============================================================
echo   dist_cx\PyMCL.exe  - double-click to open the launcher
echo.
echo   IMPORTANT: this is a folder build. Copy the WHOLE
echo   "dist_cx" folder together (do not move PyMCL.exe alone).
echo   Game data is stored inside that folder, next to the exe.
echo ============================================================
start "" explorer dist_cx
pause
