@echo off
setlocal EnableExtensions
set "PATH=C:\msys64\mingw64\bin;%PATH%"
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "DOTNET=C:\Users\Administrator\dotnet\dotnet.exe"
if not exist "%DOTNET%" set "DOTNET=dotnet"
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PACKTMP=D:\pymcl-pack"
if not exist "%PACKTMP%" set "PACKTMP=%ROOT%\pack"
set "STAGE=%PACKTMP%\stage"
set "DIST=%ROOT%\dist"
set "PUB=%PACKTMP%\publish"
set "TEMP=%PACKTMP%\tmp"
set "TMP=%PACKTMP%\tmp"
if not exist "%PACKTMP%\tmp" mkdir "%PACKTMP%\tmp"

echo [1/5] native bridge
call "%ROOT%\native\build.bat"
if errorlevel 1 exit /b 1

echo [2/5] WinUI folder publish (no single-file)
if exist "%PUB%" rmdir /s /q "%PUB%"
"%DOTNET%" publish "%ROOT%\winui3\PyMCL.WinUI\PyMCL.WinUI.csproj" -c Release -r win-x64 --self-contained false -p:Platform=x64 -p:PublishSingleFile=false -p:WindowsAppSDKSelfContained=true -p:WindowsPackageType=None -o "%PUB%"
if errorlevel 1 exit /b 1

echo [3/5] stage payload
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%\ui" "%STAGE%\native\build" "%STAGE%\native\data"
xcopy /e /y /q "%PUB%\*" "%STAGE%\ui\" >nul
copy /y "%ROOT%\native\build\pymcl-bridge.exe" "%STAGE%\native\build\" >nul
copy /y "%ROOT%\native\data\catalog.json" "%STAGE%\native\data\" >nul
if exist "%ROOT%\native\build\curl-ca-bundle.crt" copy /y "%ROOT%\native\build\curl-ca-bundle.crt" "%STAGE%\native\build\" >nul
for %%D in (libcurl-4.dll zlib1.dll libwinpthread-1.dll libssl-3-x64.dll libcrypto-3-x64.dll libzstd.dll libbrotlidec.dll libbrotlicommon.dll libnghttp2-14.dll libidn2-0.dll libpsl-5.dll libssh2-1.dll libiconv-2.dll libintl-8.dll libgcc_s_seh-1.dll) do (
  if exist "%ROOT%\native\build\%%D" copy /y "%ROOT%\native\build\%%D" "%STAGE%\native\build\" >nul
)

echo [4/5] 7z + stub
if not exist "%DIST%" mkdir "%DIST%"
"%PY%" "%ROOT%\pack\pack.py" --root "%ROOT%" --stage "%STAGE%" --dist "%DIST%"
if errorlevel 1 exit /b 1
echo Built %DIST%\PyMCL.exe
endlocal
