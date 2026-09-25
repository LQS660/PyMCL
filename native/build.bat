@echo off
setlocal
set "PATH=C:\msys64\mingw64\bin;%PATH%"
set "ROOT=%~dp0"
if not exist "%ROOT%build" mkdir "%ROOT%build"
gcc -O2 -std=c11 -Wall -Wno-unused-parameter -Wno-unused-function -Wno-format-truncation -DUNICODE -D_UNICODE -DWIN32_LEAN_AND_MEAN -I"%ROOT%include" -I"%ROOT%vendor" -o "%ROOT%build\pymcl-bridge.exe" "%ROOT%src\util.c" "%ROOT%src\http.c" "%ROOT%src\config.c" "%ROOT%src\instances.c" "%ROOT%src\catalog.c" "%ROOT%src\manifest.c" "%ROOT%src\java.c" "%ROOT%src\auth.c" "%ROOT%src\launcher.c" "%ROOT%src\installer.c" "%ROOT%src\mods.c" "%ROOT%src\modpack.c" "%ROOT%src\rpc_extra.c" "%ROOT%src\layout.c" "%ROOT%src\backend.c" "%ROOT%src\server.c" "%ROOT%src\main.c" "%ROOT%src\zip.c" "%ROOT%vendor\cJSON.c" -static -lz -lbcrypt -lcrypt32 -lws2_32 -lwinhttp -lpthread -lole32 -lshell32
if errorlevel 1 exit /b 1
rem ---- 依赖说明（2026-09-24 改）----
rem src/ 里对 libcurl 的调用是 0 处，HTTP/TLS 全走 WinHTTP（系统 schannel +
rem 系统证书库），所以：
rem   1. 去掉 -lcurl；libssl / libcrypto / nghttp2 / nghttp3 / ngtcp2 /
rem      libzstd / brotli / libidn2 / libpsl / libssh2 / libiconv /
rem      libintl / libunistring 这一整套（此前 14.13 MiB）全是不需要的。
rem   2. 加 -static，把 libwinpthread / zlib 也静态链进去，旁路 DLL 归零。
rem   3. 不再需要 curl-ca-bundle.crt，WinHTTP 用 Windows 证书库。
rem 实测：objdump -p 导入表只剩 KERNEL32 / SHELL32 / WINHTTP / WS2_32 /
rem bcrypt / msvcrt；隔离目录内单 exe 起进程跑完整 RPC，17/17 本地 +
rem 3/3 联网通过。改前是 711,036 B + 两个 DLL 194,442 B，改后单文件 817,039 B。
echo Built %ROOT%build\pymcl-bridge.exe (static, no side-by-side DLLs)
endlocal
