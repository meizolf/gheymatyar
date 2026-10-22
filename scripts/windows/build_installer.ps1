#Requires -Version 5.1
<#
.SYNOPSIS
  Build the offline Windows onedir app and GheymatYarSetup.exe installer.

.DESCRIPTION
  Must run on Windows x64 with Python 3.12, Node.js, and Inno Setup 6 (ISCC).
  Produces:
    dist\GheymatYar\GheymatYar.exe
    dist\installer\GheymatYarSetup.exe
#>
param(
    [string]$Python = "python",
    [string]$Iscc = "",
    [switch]$SkipFrontend,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

function Find-Iscc {
    param([string]$Hint)
    if ($Hint -and (Test-Path $Hint)) { return (Resolve-Path $Hint).Path }
    $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    throw "Inno Setup ISCC.exe not found. Install Inno Setup 6 or pass -Iscc."
}

Write-Host "==> Python: $Python"
& $Python --version
if ($LASTEXITCODE -ne 0) { throw "Python is not available" }

$pyVer = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pyVer -ne "3.12") {
    throw "Packaging requires Python 3.12 x64 (found $pyVer). Install 3.12.10+ and retry."
}

if (-not $SkipFrontend) {
    & (Join-Path $PSScriptRoot "prepare_static.ps1")
}

$Venv = Join-Path $RepoRoot "backend\.venv-win-packaging"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating packaging venv at $Venv"
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}

Write-Host "==> Installing pinned backend + packaging dependencies"
& $VenvPython -m pip install -U "pip==25.2" "setuptools==84.2.1" "wheel==0.45.1"
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed" }
& $VenvPython -m pip install -r (Join-Path $RepoRoot "backend\requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "requirements-windows install failed" }
& $VenvPython -m pip install -e (Join-Path $RepoRoot "backend")
if ($LASTEXITCODE -ne 0) { throw "editable install failed" }

if (-not $SkipTests) {
    Write-Host "==> Running backend pytest"
    & $VenvPython -m pytest (Join-Path $RepoRoot "backend\tests") -q
    if ($LASTEXITCODE -ne 0) { throw "backend tests failed" }
}

Write-Host "==> Cleaning previous PyInstaller output"
foreach ($dir in @("build", "dist\GheymatYar")) {
    $full = Join-Path $RepoRoot $dir
    if (Test-Path $full) { Remove-Item -Recurse -Force $full }
}

Write-Host "==> PyInstaller onedir (UPX disabled)"
& $VenvPython -m PyInstaller --noconfirm --clean (Join-Path $RepoRoot "installer\gheymatyar.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Exe = Join-Path $RepoRoot "dist\GheymatYar\GheymatYar.exe"
if (-not (Test-Path $Exe)) {
    throw "PyInstaller did not produce $Exe"
}

Write-Host "==> Verifying packaged tree"
& (Join-Path $PSScriptRoot "verify_bundle.ps1") -BundleDir (Join-Path $RepoRoot "dist\GheymatYar")
if (-not $SkipTests) {
    & (Join-Path $PSScriptRoot "smoke_packaged.ps1") `
        -BundleDir (Join-Path $RepoRoot "dist\GheymatYar") `
        -Python $VenvPython
}

$IsccPath = Find-Iscc -Hint $Iscc
Write-Host "==> Compiling installer with $IsccPath"
$InstallerOut = Join-Path $RepoRoot "dist\installer"
if (Test-Path $InstallerOut) {
    Get-ChildItem $InstallerOut -Filter "GheymatYarSetup*.exe" -ErrorAction SilentlyContinue |
        Remove-Item -Force
}
& $IsccPath (Join-Path $RepoRoot "installer\gheymatyar.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$Setup = Join-Path $InstallerOut "GheymatYarSetup.exe"
if (-not (Test-Path $Setup)) {
    throw "Installer missing at $Setup"
}

$item = Get-Item $Setup
$sha = (Get-FileHash -Algorithm SHA256 $Setup).Hash.ToLowerInvariant()
@"
file=$($item.Name)
bytes=$($item.Length)
sha256=$sha
"@ | Set-Content -Encoding ascii (Join-Path $InstallerOut "GheymatYarSetup.exe.sha256.txt")
"GheymatYarSetup.exe  $sha" | Set-Content -Encoding ascii (Join-Path $InstallerOut "SHA256SUMS")

Write-Host ""
Write-Host "Build complete."
Write-Host "  App:       $Exe"
Write-Host "  Installer: $Setup"
Write-Host "  Size:      $([math]::Round($item.Length / 1MB, 2)) MB ($($item.Length) bytes)"
Write-Host "  SHA256:    $sha"
Write-Host ""
Write-Host "NOTE: Older Windows 10 offline install + Pioneers reimport remain"
Write-Host "manual verification steps — see docs/windows_packaging.md."
