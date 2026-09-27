# Build the debug APK (needs Android Studio's JDK 17+ and Android SDK; or just download it from GitHub Actions).
$android = Join-Path $PSScriptRoot "..\android"
Set-Location $android
if (-not $env:JAVA_HOME -and (Test-Path "C:\Program Files\Android\Android Studio\jbr")) {
    $env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
}
.\gradlew.bat assembleDebug testDebugUnitTest
if ($LASTEXITCODE -eq 0) { Write-Host "APK: $android\app\build\outputs\apk\debug\app-debug.apk" -ForegroundColor Green }
