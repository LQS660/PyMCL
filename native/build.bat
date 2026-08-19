@echo off
setlocal
set "PATH=C:\msys64\mingw64\bin;%PATH%"
set "ROOT=%~dp0"
if not exist "%ROOT%build" mkdir "%ROOT%build"
gcc -O2 -std=c11 -Wall -Wno-unused-parameter -Wno-unused-function -Wno-format-truncation -DUNICODE -D_UNICODE -DWIN32_LEAN_AND_MEAN -I"%ROOT%include" -I"%ROOT%vendor" -o "%ROOT%build\pymcl-bridge.exe" "%ROOT%src\util.c" "%ROOT%src\http.c" "%ROOT%src\config.c" "%ROOT%src\instances.c" "%ROOT%src\catalog.c" "%ROOT%src\manifest.c" "%ROOT%src\java.c" "%ROOT%src\auth.c" "%ROOT%src\launcher.c" "%ROOT%src\installer.c" "%ROOT%src\mods.c" "%ROOT%src\modpack.c" "%ROOT%src\backend.c" "%ROOT%src\server.c" "%ROOT%src\main.c" "%ROOT%src\zip.c" "%ROOT%vendor\cJSON.c" -lcurl -lz -lbcrypt -lcrypt32 -lws2_32 -lwinhttp -lpthread -lole32 -lshell32
if errorlevel 1 exit /b 1
copy /Y "C:\msys64\mingw64\etc\ssl\certs\ca-bundle.crt" "%ROOT%build\curl-ca-bundle.crt" >nul
for %%D in (libcurl-4.dll zlib1.dll libwinpthread-1.dll libssl-3-x64.dll libcrypto-3-x64.dll libzstd.dll libbrotlidec.dll libbrotlicommon.dll libnghttp2-14.dll libidn2-0.dll libpsl-5.dll libssh2-1.dll libiconv-2.dll libintl-8.dll libgcc_s_seh-1.dll) do (
  if exist "C:\msys64\mingw64\bin\%%D" copy /Y "C:\msys64\mingw64\bin\%%D" "%ROOT%build\%%D" >nul
)
echo Built %ROOT%build\pymcl-bridge.exe
endlocal
