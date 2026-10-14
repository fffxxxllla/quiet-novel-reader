$ErrorActionPreference = 'Stop'
$readerExe = Join-Path $PSScriptRoot 'dist\静读\静读.exe'
if (-not (Test-Path -LiteralPath $readerExe)) { throw 'Build the application first.' }
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
$startDirectory = Join-Path ([Environment]::GetFolderPath('Programs')) '静读'
New-Item -ItemType Directory -Path $startDirectory -Force | Out-Null
$shortcutShell = New-Object -ComObject WScript.Shell
$entries = @(
    @{ Path = (Join-Path $desktopDirectory '静读.lnk'); Arguments = '--no-top' },
    @{ Path = (Join-Path $startDirectory '静读.lnk'); Arguments = '--no-top' },
    @{ Path = (Join-Path $startDirectory '书架.lnk'); Arguments = '--no-top --bookshelf' }
)
foreach ($entry in $entries) {
    $shortcut = $shortcutShell.CreateShortcut($entry.Path)
    $shortcut.TargetPath = $readerExe
    $shortcut.Arguments = $entry.Arguments
    $shortcut.WorkingDirectory = Split-Path -Parent $readerExe
    $shortcut.IconLocation = $readerExe + ',0'
    $shortcut.Description = '静读小说阅读器'
    $shortcut.Save()
    Write-Output $entry.Path
}
