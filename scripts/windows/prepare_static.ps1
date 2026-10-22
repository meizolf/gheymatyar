#Requires -Version 5.1
<#
.SYNOPSIS
  Build the React frontend and copy dist into the Python package static folder.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Frontend = Join-Path $RepoRoot "frontend"
$StaticDest = Join-Path $RepoRoot "backend\src\gheymatyar\static"

Write-Host "==> Building frontend (npm ci + npm run build)"
Push-Location $Frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

$Dist = Join-Path $Frontend "dist"
$Index = Join-Path $Dist "index.html"
if (-not (Test-Path $Index)) {
    throw "Frontend build missing index.html at $Index"
}

Write-Host "==> Embedding static assets into $StaticDest"
if (Test-Path $StaticDest) {
    Remove-Item -Recurse -Force $StaticDest
}
New-Item -ItemType Directory -Path $StaticDest | Out-Null
Copy-Item -Path (Join-Path $Dist "*") -Destination $StaticDest -Recurse -Force

if (-not (Test-Path (Join-Path $StaticDest "index.html"))) {
    throw "Static copy failed: index.html missing in $StaticDest"
}

Write-Host "Static assets ready."
