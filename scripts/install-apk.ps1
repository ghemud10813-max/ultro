# Install the debug APK on a USB-connected phone (USB debugging on).
$apk = Join-Path $PSScriptRoot "..\android\app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { Write-Error "Build it first: scripts\build-apk.ps1"; exit 1 }
adb install -r $apk
