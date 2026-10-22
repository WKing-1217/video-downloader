$ErrorActionPreference = 'Stop'
$appRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $appRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Create .venv and install requirements.txt plus pyinstaller first.' }
Push-Location (Split-Path $appRoot -Parent)
try {
    & $python -m PyInstaller (Join-Path $PSScriptRoot 'VideoDownloader.spec') --distpath (Join-Path $appRoot 'dist\v2') --workpath (Join-Path $appRoot 'build\windows-v2') --noconfirm
    if ($LASTEXITCODE) { throw 'Qt standalone build failed.' }
    $compiler = 'D:\Program\Inno Setup 6\ISCC.exe'
    if (!(Test-Path -LiteralPath $compiler)) { $compiler = (Get-Command ISCC.exe -ErrorAction Stop).Source }
    $releaseVersion = (Get-Content -LiteralPath (Join-Path $appRoot 'version.json') -Raw | ConvertFrom-Json).version
    $releaseDirectory = Join-Path (Split-Path $appRoot -Parent) ("release\v" + $releaseVersion)
    & $compiler ("/DAppVersion=" + $releaseVersion) ("/DReleaseDir=" + $releaseDirectory) (Join-Path $PSScriptRoot 'installer.iss')
    if ($LASTEXITCODE) { throw 'Windows installer build failed.' }
} finally { Pop-Location }
