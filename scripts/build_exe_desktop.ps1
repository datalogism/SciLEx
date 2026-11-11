<#
.SYNOPSIS
    Build SciLEx.exe (the desktop app, one self-contained file) and copy it
    to the Windows Desktop.

.DESCRIPTION
    Runs PyInstaller on packaging/scilex-gui.spec in single-file mode
    (SCILEX_ONEFILE=1), checks the result with the app's --self-test, then
    copies SciLEx.exe to the Desktop (or -Destination).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_exe_desktop.ps1
.EXAMPLE
    scripts\build_exe_desktop.ps1 -Destination D:\Apps -SkipSelfTest
#>
[CmdletBinding()]
param(
    # Folder that receives SciLEx.exe (default: the current user's Desktop).
    [string]$Destination = [Environment]::GetFolderPath('Desktop'),
    # Skip the post-build --self-test.
    [switch]$SkipSelfTest
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found on PATH: install it from https://docs.astral.sh/uv/"
}

$distDir = Join-Path $repo 'build\onefile-dist'
$workDir = Join-Path $repo 'build\onefile-work'
$exe = Join-Path $distDir 'SciLEx.exe'
if (Test-Path $exe) { Remove-Item $exe -Force }

Write-Host "==> Building SciLEx.exe (single file) with PyInstaller..." -ForegroundColor Cyan
$env:SCILEX_ONEFILE = '1'
# .venv may be a Linux (WSL) environment: keep the Windows one apart.
if (-not $env:UV_PROJECT_ENVIRONMENT) { $env:UV_PROJECT_ENVIRONMENT = '.venv-win' }
try {
    & uv run --extra gui --extra build pyinstaller packaging/scilex-gui.spec `
        --noconfirm --clean --distpath $distDir --workpath $workDir
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit code $LASTEXITCODE)" }
} finally {
    Remove-Item Env:SCILEX_ONEFILE -ErrorAction SilentlyContinue
}
if (-not (Test-Path $exe)) { throw "Build finished but $exe is missing" }

if (-not $SkipSelfTest) {
    Write-Host "==> Running the self-test..." -ForegroundColor Cyan
    # The exe is windowed (no console): pipe its output so it is shown here.
    $proc = Start-Process -FilePath $exe -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow `
        -RedirectStandardOutput (Join-Path $workDir 'self-test.out') `
        -RedirectStandardError (Join-Path $workDir 'self-test.err')
    Get-Content (Join-Path $workDir 'self-test.out'), (Join-Path $workDir 'self-test.err') -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) { throw "Self-test failed (exit code $($proc.ExitCode))" }
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$target = Join-Path $Destination 'SciLEx.exe'
Copy-Item $exe $target -Force
$sizeMb = [math]::Round((Get-Item $target).Length / 1MB, 1)
Write-Host "==> Done: $target ($sizeMb MB)" -ForegroundColor Green
