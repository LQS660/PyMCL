@echo off
rem Build uihost\build\pymcl-ui.exe (WebView2 window host, no browser).
rem Keep this file ASCII-only: cmd.exe on Chinese Windows reads bat files as GBK.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PATH=C:\msys64\mingw64\bin;%PATH%"
set "OUT=build"
if not exist "%OUT%" mkdir "%OUT%"

rem ---- Locate the WebView2 SDK (NuGet package layout) ----
set "SDK="
for %%R in ("%USERPROFILE%\.nuget\packages\microsoft.web.webview2" "D:\pymcl-pack\nuget\microsoft.web.webview2") do (
  if exist %%R (
    for /f "delims=" %%V in ('dir /b /ad /o-n %%R 2^>nul') do (
      if not defined SDK if exist "%%~R\%%V\build\native\include\WebView2.h" set "SDK=%%~R\%%V\build\native"
    )
  )
)
if not defined SDK (
  echo [ERROR] WebView2 SDK not found.
  echo         Expected: %%USERPROFILE%%\.nuget\packages\microsoft.web.webview2\^<version^>\build\native
  echo         Get it with: nuget install Microsoft.Web.WebView2
  exit /b 1
)
echo [1/3] SDK: %SDK%

rem -static: link libstdc++/libgcc/winpthread in. Without it the host needs
rem three MinGW DLLs that only exist under C:\msys64, so it dies with
rem 0xC0000135 on any machine that does not have MSYS2 installed.
echo [2/3] compiling pymcl-ui.exe
g++ -O2 -s -std=c++17 -municode -mwindows -DUNICODE -D_UNICODE -static ^
  -I"%SDK%\include" ^
  -o "%OUT%\pymcl-ui.exe" uihost.cpp ^
  -lole32 -loleaut32 -luuid -luser32 -lgdi32 -lshell32 -lshlwapi
if errorlevel 1 (
  echo [ERROR] compile failed
  exit /b 1
)

echo [3/3] copying WebView2Loader.dll
copy /y "%SDK%\x64\WebView2Loader.dll" "%OUT%\WebView2Loader.dll" >nul
if errorlevel 1 (
  echo [ERROR] cannot copy WebView2Loader.dll
  exit /b 1
)

echo.
echo Done: %~dp0%OUT%\pymcl-ui.exe
echo Try:  %OUT%\pymcl-ui.exe --url http://127.0.0.1:5178/
endlocal
