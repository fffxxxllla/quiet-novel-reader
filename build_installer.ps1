param([string]$CompilerPath)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$readerPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not $CompilerPath) {
    $candidates = @(
        (Join-Path $projectRoot '.build\installer-tools\compiler\ISCC.exe'),
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    $CompilerPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $CompilerPath -or -not (Test-Path -LiteralPath $CompilerPath)) {
    throw 'Install Inno Setup 6.3 or newer, or pass -CompilerPath with the full ISCC.exe path.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $readerPython prepare_installer.py
    if ($LASTEXITCODE -ne 0) { throw 'Installer payload staging failed.' }
    $payloadExe = Join-Path $projectRoot '.build\installer-payload\静读.exe'
    $checkReport = Join-Path $projectRoot '.build\installer-payload-check.json'
    $checkProcess = Start-Process -FilePath $payloadExe -ArgumentList @('--self-check', ('"' + $checkReport + '"')) -WindowStyle Hidden -PassThru
    if (-not $checkProcess.WaitForExit(45000)) { $checkProcess.Kill(); throw 'Installer payload check timed out.' }
    if ($checkProcess.ExitCode -ne 0) { throw 'Installer payload check failed.' }
    $report = Get-Content -LiteralPath $checkReport -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $report.ok) { throw 'Installer payload check did not pass.' }
    & $CompilerPath /Q installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Get-ChildItem -LiteralPath (Join-Path $projectRoot 'releases') -Filter '*.exe' | Select-Object FullName,Length
} finally {
    Pop-Location
}
