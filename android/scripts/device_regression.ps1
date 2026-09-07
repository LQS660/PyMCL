param(
    [string]$Serial = "AHSPUT2107006254",
    [string]$Apk = "",
    [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$android = Split-Path -Parent $here
$root = Split-Path -Parent $android
if (-not $OutDir) { $OutDir = Join-Path $android "regression-out" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$sdkAdb = "C:\Users\Administrator\Android\Sdk\platform-tools\adb.exe"
$wbAdb = "C:\Users\Administrator\WorkBuddy\2026-08-16-11-41-31\platform-tools\adb.exe"
$adb = if (Test-Path $sdkAdb) { $sdkAdb } elseif (Test-Path $wbAdb) { $wbAdb } else { "adb" }

function Invoke-Adb([string[]]$Args) {
    & $adb -s $Serial @Args
}

function Save-Shot([string]$Path) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $adb
    $psi.Arguments = "-s $Serial exec-out screencap -p"
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $p = [Diagnostics.Process]::Start($psi)
    $ms = New-Object IO.MemoryStream
    $p.StandardOutput.BaseStream.CopyTo($ms)
    $p.WaitForExit()
    [IO.File]::WriteAllBytes($Path, $ms.ToArray())
}

function Tap-Node([string]$Text) {
    Invoke-Adb @("shell", "uiautomator", "dump", "/sdcard/window_dump.xml") | Out-Null
    Invoke-Adb @("pull", "/sdcard/window_dump.xml", (Join-Path $OutDir "window_dump.xml")) | Out-Null
    $xml = Get-Content (Join-Path $OutDir "window_dump.xml") -Raw -Encoding UTF8
    if ($xml -notmatch [regex]::Escape("text=`"$Text`"")) { return $false }
    if ($xml -notmatch ('text="' + [regex]::Escape($Text) + '"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')) {
        if ($xml -notmatch ('bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="' + [regex]::Escape($Text) + '"')) {
            return $false
        }
    }
    $x1 = [int]$Matches[1]; $y1 = [int]$Matches[2]; $x2 = [int]$Matches[3]; $y2 = [int]$Matches[4]
    $x = [int](($x1 + $x2) / 2); $y = [int](($y1 + $y2) / 2)
    Invoke-Adb @("shell", "input", "tap", "$x", "$y") | Out-Null
    return $true
}

Write-Host "ADB=$adb"
$list = Invoke-Adb @("devices", "-l") | Out-String
Write-Host $list
if ($list -notmatch $Serial) { throw "device $Serial not in adb devices" }
if ($list -notmatch "device product:") { throw "device not in device state" }

if (-not $Apk) {
    $Apk = Join-Path $android "app\build\outputs\apk\debug\app-debug.apk"
}
if (-not (Test-Path $Apk)) { throw "missing apk $Apk" }

Invoke-Adb @("install", "-r", "-t", $Apk)
Invoke-Adb @("shell", "am", "force-stop", "com.pymcl.mobile.debug")
Invoke-Adb @("shell", "am", "start", "-n", "com.pymcl.mobile.debug/com.pymcl.mobile.MainActivity")
Start-Sleep 5
Save-Shot (Join-Path $OutDir "01-launch.png")
Tap-Node "下载" | Out-Null
Start-Sleep 2
Save-Shot (Join-Path $OutDir "02-download.png")
Tap-Node "实例" | Out-Null
Start-Sleep 2
Save-Shot (Join-Path $OutDir "03-instances.png")
Tap-Node "联机" | Out-Null
Start-Sleep 2
Save-Shot (Join-Path $OutDir "04-multiplayer.png")
Tap-Node "AI" | Out-Null
Start-Sleep 2
Save-Shot (Join-Path $OutDir "05-ai.png")
Tap-Node "设置" | Out-Null
Start-Sleep 2
Save-Shot (Join-Path $OutDir "06-settings.png")
Write-Host "shots -> $OutDir"
Get-ChildItem $OutDir -Filter *.png | Format-Table Name,Length
