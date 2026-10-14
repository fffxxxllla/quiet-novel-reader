$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$readerPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $readerPython)) { throw 'Project Python environment is missing.' }
Push-Location -LiteralPath $projectRoot
try {
    & $readerPython build_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon build failed.' }
    & $readerPython -m PyInstaller --noconfirm --distpath (Join-Path $projectRoot 'dist') --workpath (Join-Path $projectRoot '.build') QuietNovelReader.spec
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
    Write-Output (Join-Path $projectRoot 'dist\静读\静读.exe')
} finally {
    Pop-Location
}
