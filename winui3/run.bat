@echo off
setlocal
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PYMCL_HOME=%ROOT%"
if exist "C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe" (
  set "PYMCL_PYTHON=C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe"
)
set "DOTNET=C:\Users\Administrator\dotnet\dotnet.exe"
if not exist "%DOTNET%" set "DOTNET=dotnet"
set "EXE=%~dp0PyMCL.WinUI\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64\PyMCL.WinUI.exe"
if not exist "%EXE%" set "EXE=%~dp0PyMCL.WinUI\bin\Release\net8.0-windows10.0.19041.0\win-x64\PyMCL.WinUI.exe"
if not exist "%EXE%" (
  echo Building WinUI 3...
  "%DOTNET%" build "%~dp0PyMCL.WinUI\PyMCL.WinUI.csproj" -c Release -p:Platform=x64
  set "EXE=%~dp0PyMCL.WinUI\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64\PyMCL.WinUI.exe"
)
if not exist "%EXE%" (
  echo Build failed or exe missing.
  exit /b 1
)
start "" "%EXE%"
endlocal
