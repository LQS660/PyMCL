@echo off
rem ============================================================
rem  PyMCL wallpaper crash fixer
rem
rem  Symptom: launcher opens and instantly dies, pymcl-error.log
rem  shows "Windows fatal exception: access violation" inside
rem  app/background.py _on_frame.
rem  Cause: an .mp4/.mkv/... video wallpaper; on some GPU drivers
rem  QtMultimedia crashes while converting the decoded frames.
rem
rem  What this tool does: clears the video wallpaper entries in
rem  config.json (ui_background / ui_background_folder) so the
rem  launcher starts again. It never deletes your media files.
rem
rem  Usage: put this .bat in the SAME folder as PyMCL.exe and
rem  double-click it.
rem
rem  Keep this file ASCII-only: cmd.exe on Chinese Windows reads
rem  bat files as GBK.
rem ============================================================
setlocal
set "PYMCL_FIX_DIR=%~dp0"
where powershell >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Windows PowerShell not found, cannot run the fixer.
    pause
    exit /b 1
)
rem The search pattern below is assembled from two string pieces on
rem purpose: this command line must NOT contain the real boundary
rem marker, or the payload would be cut at the wrong place.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$raw = Get-Content -LiteralPath '%~f0' -Raw; Invoke-Expression ($raw -replace ('(?s)\A.*?#PS_B' + 'EGIN#'), '')"
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
#PS_BEGIN#
$ErrorActionPreference = 'Stop'

$VIDEO_EXTS = @('.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.wmv')

function Is-VideoPath([string]$p) {
    if ([string]::IsNullOrWhiteSpace($p)) { return $false }
    $ext = [System.IO.Path]::GetExtension($p.Trim())
    return $VIDEO_EXTS -contains $ext.ToLower()
}

function Test-DirWritable([string]$d) {
    try {
        $probe = Join-Path $d '.pymcl_wtest'
        [System.IO.File]::WriteAllText($probe, '1')
        Remove-Item -LiteralPath $probe -Force
        return $true
    } catch {
        return $false
    }
}

Write-Host '=============================================='
Write-Host '  PyMCL wallpaper crash fixer'
Write-Host '=============================================='
Write-Host ''

$fixDir = $env:PYMCL_FIX_DIR
if (-not $fixDir) { $fixDir = (Get-Location).Path }

$target = $null
if ($env:PYMCL_HOME) {
    $cand = Join-Path $env:PYMCL_HOME 'config.json'
    if (Test-Path -LiteralPath $cand -PathType Leaf) { $target = $cand }
}
if (-not $target -and (Test-DirWritable $fixDir)) {
    $cand = Join-Path $fixDir 'config.json'
    if (Test-Path -LiteralPath $cand -PathType Leaf) {
        $target = $cand
    } else {
        Write-Host "Config file: $cand"
        Write-Host 'NOT FOUND. The launcher has never saved settings here,'
        Write-Host 'it runs on defaults and cannot hit this crash.'
        Write-Host 'Nothing to fix.'
        exit 0
    }
}
if (-not $target) {
    $cand = Join-Path $env:APPDATA 'PyMCL\config.json'
    if (Test-Path -LiteralPath $cand -PathType Leaf) {
        $target = $cand
    } else {
        Write-Host "No config.json found next to the launcher or in $env:APPDATA\PyMCL ."
        Write-Host 'The launcher runs on defaults and cannot hit this crash.'
        Write-Host 'Nothing to fix.'
        exit 0
    }
}

Write-Host "Config file: $target"
Write-Host ''

$proc = Get-Process -Name 'PyMCL', 'PyMCL-EziApp' -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host '[ERROR] PyMCL is still running. Close it (check Task Manager)'
    Write-Host 'and run this fixer again.'
    exit 1
}

try {
    $raw = [System.IO.File]::ReadAllText($target, [System.Text.Encoding]::UTF8)
    $cfg = $raw | ConvertFrom-Json
} catch {
    Write-Host "[ERROR] config.json is not valid JSON: $($_.Exception.Message)"
    Write-Host 'Nothing was modified.'
    exit 1
}

$changed = @()

$bg = ''
if ($cfg.PSObject.Properties['ui_background']) { $bg = [string]$cfg.ui_background }
if (Is-VideoPath $bg) {
    Write-Host "Found video wallpaper:  ui_background = $bg"
    $cfg.ui_background = ''
    $changed += 'ui_background'
} else {
    Write-Host "ui_background is not a video (no change needed)."
}

$fold = ''
if ($cfg.PSObject.Properties['ui_background_folder']) { $fold = [string]$cfg.ui_background_folder }
if ($fold -and (Test-Path -LiteralPath $fold -PathType Container)) {
    $vids = @(Get-ChildItem -LiteralPath $fold -File -ErrorAction SilentlyContinue |
        Where-Object { Is-VideoPath $_.Extension })
    if ($vids.Count -gt 0) {
        Write-Host "Wallpaper folder holds $($vids.Count) video file(s):  $fold"
        $cfg.ui_background_folder = ''
        $changed += 'ui_background_folder'
    } else {
        Write-Host "Wallpaper folder has no video files (no change needed)."
    }
} else {
    Write-Host "ui_background_folder is empty or missing (no change needed)."
}

if ($changed.Count -eq 0) {
    Write-Host ''
    Write-Host 'No video wallpaper setting found. Config was NOT modified.'
    Write-Host 'If the launcher still crashes, send pymcl-error.log (next to'
    Write-Host 'PyMCL.exe, or in the %APPDATA%\PyMCL folder) to the developer.'
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "$target.bak-wallpaperfix-$stamp"
Copy-Item -LiteralPath $target -Destination $bak

try {
    $json = $cfg | ConvertTo-Json -Depth 24
    [System.IO.File]::WriteAllText($target, $json, (New-Object System.Text.UTF8Encoding($false)))
    [void] ([System.IO.File]::ReadAllText($target) | ConvertFrom-Json)
} catch {
    Copy-Item -LiteralPath $bak -Destination $target -Force
    Write-Host "[ERROR] Failed to write config.json, restored from backup."
    Write-Host "        $($_.Exception.Message)"
    exit 1
}

Write-Host ''
Write-Host "FIXED: cleared $($changed.Count) setting(s): $($changed -join ', ')"
Write-Host "Backup of the old config: $bak"
Write-Host ''
Write-Host 'You can now start PyMCL.exe normally.'
Write-Host 'Your wallpaper media files were NOT deleted.'
exit 0
