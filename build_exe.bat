@echo off
rem Rebuild dist\PyMCL.exe (windowed, no console).
rem Keep this file ASCII-only: cmd.exe on Chinese Windows reads bat files as GBK.
cd /d "%~dp0"

set "PYEXE=python"
if exist "C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe" (
  set "PYEXE=C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe"
) else (
  py -3.13 -c "import sys" >nul 2>nul
  if not errorlevel 1 set PYEXE=py -3.13
  py -3.12 -c "import sys" >nul 2>nul
  if not errorlevel 1 set PYEXE=py -3.12
)

"%PYEXE%" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    exit /b 1
)

echo [1/3] Building with: %PYEXE%
"%PYEXE%" --version

echo [2/3] Installing PyInstaller if needed...
"%PYEXE%" -m pip install "pyinstaller==6.10.0" "requests"
if errorlevel 1 (
    echo [ERROR] pip install failed.
    exit /b 1
)

echo [3/3] Building windowed exe: dist\PyMCL.exe
"%PYEXE%" -m PyInstaller --noconfirm --clean PyMCL.spec
if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)

echo.
echo Done: dist\PyMCL.exe
exit /b 0
