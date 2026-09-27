# Start the Nixin brain (voice + dashboard). Extra args are passed through, e.g. -- --no-voice
$brain = Join-Path $PSScriptRoot "..\brain"
Set-Location $brain
& .\.venv\Scripts\nixin.exe run @args
