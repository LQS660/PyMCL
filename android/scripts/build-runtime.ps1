$ErrorActionPreference = 'Stop'
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot'
$env:ANDROID_HOME = 'D:\Android\Sdk'
$env:ANDROID_SDK_ROOT = 'D:\Android\Sdk'
$env:GRADLE_USER_HOME = 'D:\gradle-home'
$src = 'C:\pymcl-android'
$dst = 'D:\pymcl-work\pymcl-android'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
& robocopy $src $dst /MIR /XD .gradle build .idea /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw "robocopy failed $LASTEXITCODE" }
Set-Location $dst
& 'D:\gradle-8.13\bin\gradle.bat' --no-daemon assembleDebug testDebugUnitTest --stacktrace
