@echo off
rem PyMCL build script using cx_Freeze.
rem This works even when PyInstaller crashes with "KeyError: 'CACHE'"
rem on a Python installation with mixed/broken stdlib files.
rem Keep this file ASCII-only.
cd /d "%~dp0"

set "BUILD_LOG=build_exe_cx.log"
echo ============================================ > "%BUILD_LOG%"
echo [build_exe_cx.bat] started %date% %time% >> "%BUILD_LOG%"

rem ---- Find Python ----
set "PYEXE="
set "PYARGS="

rem 1) workbuddy env
if exist "C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe" (
  set "PYEXE=C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe"
)

rem 2) plain python
if not defined PYEXE (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)

rem 3) py launcher
if not defined PYEXE (
  py -3.13 -c "import sys" >nul 2>nul
  if not errorlevel 1 (set "PYEXE=py" & set "PYARGS=-3.13")
)
if not defined PYEXE (
  py -3.12 -c "import sys" >nul 2>nul
  if not errorlevel 1 (set "PYEXE=py" & set "PYARGS=-3.12")
)
if not defined PYEXE (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 (set "PYEXE=py" & set "PYARGS=-3.11")
)

if not defined PYEXE (
  echo.
  echo [ERROR] Python not found. Install Python 3.11+ from https://www.python.org/downloads/
  echo         Make sure "Add Python to PATH" is checked when installing.
  echo.
  pause
  exit /b 1
)

echo [1/3] Installing cx-Freeze (small, one-time)... >> "%BUILD_LOG%"
"%PYEXE%" %PYARGS% -m pip install "cx-Freeze" >> "%BUILD_LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Failed to install cx-Freeze. See %BUILD_LOG% for details.
  pause
  exit /b 1
)

echo [2/3] Building PyMCL.exe ...
if exist dist_cx rmdir /s /q dist_cx
"%PYEXE%" %PYARGS% cx_setup.py build_exe --build-exe dist_cx >> "%BUILD_LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Build failed. See %BUILD_LOG% for details.
  type "%BUILD_LOG%" 2>nul
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
echo.
start "" explorer dist_cx
pause