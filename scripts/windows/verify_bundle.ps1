#Requires -Version 5.1
<#
.SYNOPSIS
  Static checks for the PyInstaller onedir tree before Inno packaging.

.DESCRIPTION
  Verifies SPA assets, PE architecture (AMD64), required native libraries
  (pdfium / Python / VC++ runtimes), and PE import completeness against the
  bundled tree — without relying on separately installed Visual Studio
  redistributables on the build machine.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDir
)

$ErrorActionPreference = "Stop"
$Bundle = Resolve-Path $BundleDir
$Exe = Join-Path $Bundle "GheymatYar.exe"
if (-not (Test-Path $Exe)) {
    throw "Missing executable: $Exe"
}

$internal = Join-Path $Bundle "_internal"
$searchRoots = @([string]$Bundle)
if (Test-Path $internal) { $searchRoots += [string](Resolve-Path $internal) }

function Find-Under {
    param([string[]]$Roots, [string]$Relative)
    foreach ($root in $Roots) {
        $candidate = Join-Path $root $Relative
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Get-PeMachine {
    param([string]$Path)
    $fs = [System.IO.File]::OpenRead($Path)
    try {
        $br = New-Object System.IO.BinaryReader $fs
        if ($br.ReadUInt16() -ne 0x5A4D) { return $null } # MZ
        $fs.Seek(0x3C, 'Begin') | Out-Null
        $peOffset = $br.ReadUInt32()
        $fs.Seek($peOffset, 'Begin') | Out-Null
        if ($br.ReadUInt32() -ne 0x4550) { return $null } # PE\0\0
        return $br.ReadUInt16()
    }
    finally {
        $fs.Dispose()
    }
}

function Get-PeImportDllNames {
    param([string]$Path)
    # Minimal PE import directory walk (PE32+). Returns lower-case DLL names.
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 0x40) { return @() }
    if ([BitConverter]::ToUInt16($bytes, 0) -ne 0x5A4D) { return @() }
    $pe = [BitConverter]::ToInt32($bytes, 0x3C)
    if ($pe -lt 0 -or ($pe + 24) -ge $bytes.Length) { return @() }
    if ([BitConverter]::ToUInt32($bytes, $pe) -ne 0x4550) { return @() }
    $machine = [BitConverter]::ToUInt16($bytes, $pe + 4)
    $optMagic = [BitConverter]::ToUInt16($bytes, $pe + 24)
    $isPe32Plus = $optMagic -eq 0x20B
    $isPe32 = $optMagic -eq 0x10B
    if (-not ($isPe32 -or $isPe32Plus)) { return @() }

    $numSections = [BitConverter]::ToUInt16($bytes, $pe + 6)
    $sizeOpt = [BitConverter]::ToUInt16($bytes, $pe + 20)
    $ddOffset = $pe + 24 + $(if ($isPe32Plus) { 112 } else { 96 })
    if (($ddOffset + 8) -ge $bytes.Length) { return @() }
    $importRva = [BitConverter]::ToUInt32($bytes, $ddOffset + 8) # DataDirectory[1]
    if ($importRva -eq 0) { return @() }

    $sectionStart = $pe + 24 + $sizeOpt
    function RvaToOffset([uint32]$rva) {
        for ($i = 0; $i -lt $numSections; $i++) {
            $s = $sectionStart + ($i * 40)
            if (($s + 40) -gt $bytes.Length) { return -1 }
            $virtSize = [BitConverter]::ToUInt32($bytes, $s + 8)
            $virtAddr = [BitConverter]::ToUInt32($bytes, $s + 12)
            $rawSize = [BitConverter]::ToUInt32($bytes, $s + 16)
            $rawPtr = [BitConverter]::ToUInt32($bytes, $s + 20)
            $span = [Math]::Max($virtSize, $rawSize)
            if ($rva -ge $virtAddr -and $rva -lt ($virtAddr + $span)) {
                return [int]($rawPtr + ($rva - $virtAddr))
            }
        }
        return -1
    }

    $names = New-Object System.Collections.Generic.List[string]
    $descOff = RvaToOffset $importRva
    if ($descOff -lt 0) { return @() }
    while (($descOff + 20) -le $bytes.Length) {
        $nameRva = [BitConverter]::ToUInt32($bytes, $descOff + 12)
        $oft = [BitConverter]::ToUInt32($bytes, $descOff)
        $ft = [BitConverter]::ToUInt32($bytes, $descOff + 16)
        if ($nameRva -eq 0 -and $oft -eq 0 -and $ft -eq 0) { break }
        $nameOff = RvaToOffset $nameRva
        if ($nameOff -ge 0) {
            $end = $nameOff
            while ($end -lt $bytes.Length -and $bytes[$end] -ne 0) { $end++ }
            $dll = [System.Text.Encoding]::ASCII.GetString($bytes, $nameOff, $end - $nameOff).ToLowerInvariant()
            if ($dll) { $names.Add($dll) }
        }
        $descOff += 20
    }
    return $names
}

function Find-BundleFile {
    param([string]$FileName)
    foreach ($root in $searchRoots) {
        $hit = Get-ChildItem -Path $root -Recurse -Filter $FileName -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

# --- SPA ---
$index = Find-Under -Roots $searchRoots -Relative "gheymatyar\static\index.html"
if (-not $index) {
    throw "Bundled SPA index.html not found under gheymatyar/static"
}
Write-Host "OK static: $index"
$assets = Join-Path (Split-Path $index -Parent) "assets"
if (-not (Test-Path $assets)) {
    throw "Bundled SPA assets/ directory missing next to index.html"
}
# Offline guard: production CSS/JS must not reference Google Fonts CDN.
$staticRoot = Split-Path $index -Parent
$staticFiles = Get-ChildItem -Path $staticRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -match '\.(html|css|js|svg|txt|json)$' }
$cdnHits = @($staticFiles | Select-String -Pattern "fonts\.googleapis|fonts\.gstatic|cdn\.jsdelivr|unpkg\.com" -ErrorAction SilentlyContinue |
    Select-Object -First 5)
if ($cdnHits.Count -gt 0) {
    throw "Bundled static assets reference external CDN URLs: $($cdnHits.Path -join ', ')"
}
Write-Host "OK offline static (no Google Fonts / CDN refs)"

# --- Architecture: AMD64 only ---
$IMAGE_FILE_MACHINE_AMD64 = 0x8664
$exeMachine = Get-PeMachine -Path $Exe
if ($exeMachine -ne $IMAGE_FILE_MACHINE_AMD64) {
    throw "GheymatYar.exe is not AMD64 (machine=0x$('{0:X}' -f $exeMachine))"
}
Write-Host "OK arch: GheymatYar.exe is AMD64"

$archSamples = @(
    "python312.dll",
    "python3*.dll",
    "pdfium.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll"
)
foreach ($pattern in $archSamples) {
    foreach ($root in $searchRoots) {
        Get-ChildItem -Path $root -Recurse -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
            $m = Get-PeMachine -Path $_.FullName
            if ($null -ne $m -and $m -ne $IMAGE_FILE_MACHINE_AMD64 -and $m -ne 0x0) {
                # Some resource-only DLLs may be neutral; skip 0
                if ($m -eq 0x14C) { # IMAGE_FILE_MACHINE_I386
                    throw "32-bit PE found in x64 bundle: $($_.FullName)"
                }
            }
            if ($m -eq $IMAGE_FILE_MACHINE_AMD64) {
                Write-Host "OK arch: $($_.Name)"
            }
        }
    }
}

# --- Required shipped files (must not rely on VS redist outside the bundle) ---
$requiredFiles = @(
    @{ Name = "python3*.dll"; Label = "Python runtime DLL" },
    @{ Name = "pdfium.dll"; Label = "PDFium (pdfplumber/pypdfium2)"; Alternate = @("libpdfium.dll") },
    @{ Name = "vcruntime140.dll"; Label = "VC++ Runtime (vcruntime140)" },
    # HTTPS for the optional supplier-website price fetch (Pars Plast).
    @{ Name = "_ssl.pyd"; Label = "Python SSL module (website fetch)" },
    @{ Name = "libssl-*.dll"; Label = "OpenSSL libssl (website fetch)" },
    @{ Name = "libcrypto-*.dll"; Label = "OpenSSL libcrypto (website fetch)" }
)

foreach ($req in $requiredFiles) {
    $hit = $null
    foreach ($root in $searchRoots) {
        $hit = Get-ChildItem -Path $root -Recurse -Filter $req.Name -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { break }
    }
    if (-not $hit -and $req.Alternate) {
        foreach ($alt in $req.Alternate) {
            $hitPath = Find-BundleFile -FileName $alt
            if ($hitPath) { $hit = Get-Item $hitPath; break }
        }
    }
    if (-not $hit) {
        throw "Missing required bundled dependency: $($req.Label) ($($req.Name))"
    }
    Write-Host "OK dep: $($hit.FullName)"
}

# --- Import resolution for EVERY shipped native binary ---
# OS system DLLs may resolve from Win10 System32. VC++ redistributable DLLs
# (vcruntime*/msvcp*/concrt*) are NOT treated as system — they must be in the
# onedir tree whenever any PE imports them.
$systemDllAllow = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
@(
    "kernel32.dll", "user32.dll", "gdi32.dll", "gdiplus.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "comdlg32.dll", "comctl32.dll", "shlwapi.dll",
    "ws2_32.dll", "wsock32.dll", "iphlpapi.dll", "ntdll.dll", "rpcrt4.dll",
    "secur32.dll", "crypt32.dll", "bcrypt.dll", "ncrypt.dll", "winmm.dll",
    "imm32.dll", "version.dll", "setupapi.dll", "cfgmgr32.dll", "dwmapi.dll",
    "uxtheme.dll", "dnsapi.dll", "mswsock.dll", "winhttp.dll", "wininet.dll",
    "normaliz.dll", "wldap32.dll", "powrprof.dll", "profapi.dll",
    "kernelbase.dll", "ucrtbase.dll", "msvcrt.dll", "sechost.dll", "shcore.dll",
    "userenv.dll", "netapi32.dll", "authz.dll", "cabinet.dll", "dbghelp.dll",
    "imagehlp.dll", "psapi.dll", "wintrust.dll",
    # CNG primitive provider (ProcessPrng etc.) — shipped with Windows, imported by
    # cryptography / pydantic-core wheels; PyInstaller correctly leaves it out.
    "bcryptprimitives.dll",
    # Windows Property System — System32 DLL imported by CPython _wmi.pyd;
    # PyInstaller excludes it as a Windows-dir dependency (not redistributable).
    "propsys.dll"
) | ForEach-Object { [void]$systemDllAllow.Add($_) }

function Test-IsOsSystemDll([string]$name) {
    if ($systemDllAllow.Contains($name)) { return $true }
    if ($name -like "api-ms-win-*.dll") { return $true }
    if ($name -like "ext-ms-*.dll") { return $true }
    return $false
}

function Test-IsVcRedistDll([string]$name) {
    return ($name -like "vcruntime*.dll") -or ($name -like "msvcp*.dll") -or ($name -like "concrt*.dll") -or ($name -like "vccorlib*.dll")
}

$bundleFileIndex = @{}
$allNative = New-Object System.Collections.Generic.List[string]
foreach ($root in $searchRoots) {
    Get-ChildItem -Path $root -Recurse -Include "*.dll","*.pyd","*.exe" -ErrorAction SilentlyContinue | ForEach-Object {
        $bundleFileIndex[$_.Name.ToLowerInvariant()] = $_.FullName
        $allNative.Add($_.FullName)
    }
}

$missingImports = New-Object System.Collections.Generic.List[string]
$requiredVc = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
[void]$requiredVc.Add("vcruntime140.dll")

foreach ($pePath in $allNative) {
    $imports = @(Get-PeImportDllNames -Path $pePath)
    foreach ($dll in $imports) {
        if (Test-IsVcRedistDll $dll) {
            [void]$requiredVc.Add($dll)
            if (-not $bundleFileIndex.ContainsKey($dll)) {
                $missingImports.Add("$([IO.Path]::GetFileName($pePath)) -> $dll (VC++ redist must be bundled)")
            }
            continue
        }
        if (Test-IsOsSystemDll $dll) { continue }
        if (-not $bundleFileIndex.ContainsKey($dll)) {
            $missingImports.Add("$([IO.Path]::GetFileName($pePath)) -> $dll")
        }
    }
}

foreach ($dll in $requiredVc) {
    if (-not $bundleFileIndex.ContainsKey($dll)) {
        $missingImports.Add("required VC++ runtime missing from bundle: $dll")
    } else {
        Write-Host "OK VC++ bundled: $($bundleFileIndex[$dll])"
    }
}

if ($missingImports.Count -gt 0) {
    throw "Unresolved native imports / missing VC++ DLLs:`n - $($missingImports -join "`n - ")"
}
Write-Host "OK import closure for $($allNative.Count) native binaries against bundled tree"

# --- UPX guard ---
$peSamples = Get-ChildItem -Path $searchRoots -Recurse -Include "*.dll","*.pyd","*.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 40
foreach ($file in $peSamples) {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $len = [Math]::Min(4096, $bytes.Length)
    $ascii = [System.Text.Encoding]::ASCII.GetString($bytes, 0, $len)
    if ($ascii -match "UPX!") {
        throw "UPX signature found in $($file.FullName); rebuild with upx=False"
    }
}

Write-Host "Bundle verification passed: $Bundle"
