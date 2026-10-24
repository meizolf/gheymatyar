#Requires -Version 5.1
<#
.SYNOPSIS
  Headless smoke test against the packaged GheymatYar.exe.

.DESCRIPTION
  Starts the windowed EXE with a sanitized PATH (no VS/dev redistributable
  directories), verifies identity via /api/health, runs Excel+PDF workflows for
  both .xlsx and HTML-based .xls fixtures, asserts export cell/formula
  integrity across all sheets, explicitly saves a mapping, restarts the EXE,
  and confirms the mapping survived. Uses the local control token for
  /api/shutdown. Force-kill is only used for emergency cleanup and fails the
  ViaApi shutdown path.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDir,
    [int]$Port = 18765,
    [int]$ReadyTimeoutSec = 90,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Bundle = Resolve-Path $BundleDir
$Exe = Join-Path $Bundle "GheymatYar.exe"
if (-not (Test-Path $Exe)) { throw "Missing $Exe" }

# Resolve Python to an absolute path BEFORE any PATH sanitization so compare
# scripts remain runnable after Start-Process inherits a trimmed PATH.
$PythonExe = $null
if (Test-Path -LiteralPath $Python) {
    $PythonExe = (Resolve-Path -LiteralPath $Python).Path
} else {
    $cmd = Get-Command $Python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $PythonExe = $cmd.Source
    }
}
if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found for '$Python'. Pass -Python with an absolute path."
}
Write-Host "Using Python: $PythonExe"

$ExcelXlsx = Join-Path $RepoRoot "fixtures\pioneers\pioneers_azin_subset.xlsx"
$ExcelXls = Join-Path $RepoRoot "fixtures\pioneers\pioneers_azin_subset.xls"
$Pdf = Join-Path $RepoRoot "fixtures\suppliers\458_124550609784457.pdf"
$DinaPdf = Join-Path $RepoRoot "fixtures\suppliers\dina_polymer_1405_07_04.pdf"
$CompareScript = Join-Path $RepoRoot "scripts\windows\compare_export.py"
foreach ($p in @($ExcelXlsx, $ExcelXls, $Pdf, $DinaPdf, $CompareScript)) {
    if (-not (Test-Path $p)) { throw "Missing required file: $p" }
}

$DataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("gheymatyar-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $DataDir | Out-Null
$Base = "http://127.0.0.1:$Port"
$script:Proc = $null
$script:ControlToken = $null
$script:OriginalPath = $env:PATH

function Get-SanitizedPath {
    $internal = Join-Path $Bundle "_internal"
    $parts = @(
        [string]$Bundle,
        $(if (Test-Path $internal) { [string](Resolve-Path $internal) } else { $null }),
        "$env:SystemRoot\System32",
        "$env:SystemRoot",
        "$env:SystemRoot\System32\Wbem"
    ) | Where-Object { $_ }
    return ($parts -join ";")
}

function Start-GheymatYar {
    $env:GHEYMATYAR_DATA_DIR = $DataDir
    $env:GHEYMATYAR_PORT = "$Port"
    # Child inherits the environment at CreateProcess time; restore PATH
    # immediately so this shell can still invoke $PythonExe afterward.
    $savedPath = $env:PATH
    try {
        $env:PATH = Get-SanitizedPath
        Write-Host "==> Starting packaged EXE (data=$DataDir port=$Port sanitized PATH)"
        $script:Proc = Start-Process -FilePath $Exe -WorkingDirectory $Bundle -PassThru -WindowStyle Hidden
    }
    finally {
        $env:PATH = $savedPath
    }
}

function Stop-GheymatYar {
    param(
        [switch]$ViaApi,
        [switch]$ForceCleanup
    )
    if ($ViaApi) {
        if (-not $script:Proc) {
            throw "ViaApi shutdown requested but no process handle exists"
        }
        if ($script:Proc.HasExited) {
            Write-Host "Process already exited (code=$($script:Proc.ExitCode))"
            $script:Proc = $null
            $script:ControlToken = $null
            return
        }
        if (-not $script:ControlToken) {
            throw "Cannot API-shutdown without control token"
        }
        try {
            Invoke-Json -Method POST -Url "$Base/api/shutdown" -Headers @{
                "X-GheymatYar-Token" = $script:ControlToken
            } | Out-Null
        } catch {
            throw "shutdown API failed: $_"
        }
        if (-not $script:Proc.WaitForExit(20000)) {
            throw "Process did not exit within 20s after /api/shutdown (refusing silent force-kill)"
        }
        Write-Host "OK clean shutdown via API (exit=$($script:Proc.ExitCode))"
        $script:Proc = $null
        $script:ControlToken = $null
        return
    }

    if ($script:Proc -and -not $script:Proc.HasExited) {
        if (-not $ForceCleanup) {
            throw "Process still running; refusing silent force-kill (use -ViaApi or -ForceCleanup)"
        }
        Write-Host "WARN force-killing leftover process for cleanup only"
        Stop-Process -Id $script:Proc.Id -Force -ErrorAction SilentlyContinue
        $script:Proc.WaitForExit(5000) | Out-Null
    }
    $script:Proc = $null
    $script:ControlToken = $null
}

function Wait-GheymatYarReady {
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($script:Proc.HasExited) {
            $log = Join-Path $DataDir "gheymatyar.log"
            $tail = if (Test-Path $log) { Get-Content $log -Tail 50 -ErrorAction SilentlyContinue } else { @() }
            throw "GheymatYar.exe exited early (code=$($script:Proc.ExitCode)). Log:`n$($tail -join "`n")"
        }
        try {
            $resp = Invoke-WebRequest -Uri "$Base/api/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                $health = $resp.Content | ConvertFrom-Json
                if ($health.app -ne "gheymatyar" -or $health.status -ne "ok") {
                    throw "Port $Port answered but is not GheymatYar: $($resp.Content)"
                }
                if (-not $health.control_token) {
                    throw "health response missing control_token"
                }
                $script:ControlToken = [string]$health.control_token
                return $health
            }
        } catch {
            if ($_.Exception.Message -match "not GheymatYar|control_token") { throw }
            Start-Sleep -Milliseconds 400
        }
    }
    throw "Timed out waiting for GheymatYar health on $Base/api/health"
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )
    $params = @{
        Method = $Method
        Uri = $Url
        UseBasicParsing = $true
        Headers = $Headers
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json; charset=utf-8"
        $params.Body = ($Body | ConvertTo-Json -Compress -Depth 8)
    }
    $status = 0
    $text = ""
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        $params.SkipHttpErrorCheck = $true
        $resp = Invoke-WebRequest @params
        $status = [int]$resp.StatusCode
        $text = [string]$resp.Content
    } else {
        try {
            $resp = Invoke-WebRequest @params
            $status = [int]$resp.StatusCode
            $text = [string]$resp.Content
        } catch {
            $response = $_.Exception.Response
            if ($null -eq $response) { throw }
            $status = [int]$response.StatusCode
            $stream = $response.GetResponseStream()
            if ($null -ne $stream) {
                $reader = New-Object System.IO.StreamReader($stream)
                $text = $reader.ReadToEnd()
                $reader.Dispose()
            }
        }
    }
    $parsed = $null
    if ($text) {
        try { $parsed = $text | ConvertFrom-Json } catch { $parsed = $null }
    }
    return [pscustomobject]@{ StatusCode = $status; Body = $parsed; Text = $text }
}

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )
    $result = Invoke-Api -Method $Method -Url $Url -Body $Body -Headers $Headers
    if ($result.StatusCode -lt 200 -or $result.StatusCode -ge 300) {
        throw "$Method $Url failed HTTP $($result.StatusCode): $($result.Text)"
    }
    return $result.Body
}

function Invoke-Multipart {
    param(
        [string]$Url,
        [hashtable]$FormFields,
        [string]$FileField,
        [string]$FilePath,
        [string]$ContentType
    )
    Add-Type -AssemblyName System.Net.Http
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        $multipart = [System.Net.Http.MultipartFormDataContent]::new()
        foreach ($key in $FormFields.Keys) {
            $multipart.Add([System.Net.Http.StringContent]::new([string]$FormFields[$key]), $key)
        }
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse($ContentType)
        $multipart.Add($fileContent, $FileField, [System.IO.Path]::GetFileName($FilePath))
        $response = $client.PostAsync($Url, $multipart).GetAwaiter().GetResult()
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Upload failed $($response.StatusCode): $text"
        }
        return $text | ConvertFrom-Json
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Invoke-Workflow {
    param(
        [string]$ExcelPath,
        [string]$Label,
        [switch]$SaveMapping,
        [switch]$HtmlXls,
        [string]$SupplierKey = "azin_pipe",
        [string]$PdfPath = $Pdf,
        [switch]$ExpectBlocked
    )

    $sourceSha = Get-FileSha256 $ExcelPath
    Write-Host "==> Workflow $Label (sha=$($sourceSha.Substring(0,12))…)"

    $session = Invoke-Json -Method POST -Url "$Base/api/sessions"
    $sid = $session.session_id
    if (-not $sid) { throw "session_id missing" }

    $contentType = if ($HtmlXls) {
        "application/vnd.ms-excel"
    } else {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }

    $null = Invoke-Multipart -Url "$Base/api/sessions/$sid/pioneers-excel" `
        -FormFields @{} `
        -FileField "file" `
        -FilePath $ExcelPath `
        -ContentType $contentType
    Write-Host "OK excel upload ($Label)"

    $null = Invoke-Multipart -Url "$Base/api/sessions/$sid/supplier-pdf" `
        -FormFields @{ supplier_key = $SupplierKey } `
        -FileField "file" `
        -FilePath $PdfPath `
        -ContentType "application/pdf"
    Write-Host "OK pdf upload"

    $match = Invoke-Json -Method POST -Url "$Base/api/sessions/$sid/match" `
        -Body @{ suspicious_percent_threshold = "30" }
    if (-not $match.candidates) { throw "match returned no candidates" }
    Write-Host "OK match ($($match.candidates.Count) candidates)"

    $candidates = $match.candidates
    $keep = $null
    $savedMappingKey = $null

    if ($SaveMapping) {
        $needy = $candidates | Where-Object {
            $_.status -in @("UNMATCHED", "AMBIGUOUS") -and $_.suggestions -and $_.suggestions.Count -gt 0
        } | Select-Object -First 1
        if (-not $needy) {
            $matched = $candidates | Where-Object { $_.status -eq "MATCHED" } | Select-Object -First 1
            if (-not $matched) { throw "No candidate available to save a mapping" }
            $keep = $matched
            Write-Host "WARN no unmatched candidate; will rely on existing auto mapping path"
        } else {
            $keep = Invoke-Json -Method POST `
                -Url "$Base/api/sessions/$sid/candidates/$($needy.candidate_id)/confirm-mapping" `
                -Body @{ pioneers_row_number = $needy.suggestions[0].row_number; save = $true }
            $savedMappingKey = [string]$needy.supplier_name
            if (-not $savedMappingKey) { $savedMappingKey = [string]$keep.supplier_name }
            Write-Host "OK saved mapping for '$savedMappingKey'"
        }
    }

    if (-not $keep) {
        $keep = $candidates | Where-Object { $_.status -eq "MATCHED" } | Select-Object -First 1
        if (-not $keep) {
            $needy = $candidates | Where-Object {
                $_.status -in @("UNMATCHED", "AMBIGUOUS") -and $_.suggestions -and $_.suggestions.Count -gt 0
            } | Select-Object -First 1
            if (-not $needy) { throw "No confirmable candidate found" }
            $keep = Invoke-Json -Method POST `
                -Url "$Base/api/sessions/$sid/candidates/$($needy.candidate_id)/confirm-mapping" `
                -Body @{ pioneers_row_number = $needy.suggestions[0].row_number; save = $true }
            if ($SaveMapping) {
                $savedMappingKey = [string]$needy.supplier_name
            }
        }
    }

    $approved = Invoke-Api -Method POST `
        -Url "$Base/api/sessions/$sid/candidates/$($keep.candidate_id)/review" `
        -Body @{ decision = "APPROVE" }
    if ($ExpectBlocked) {
        if ($approved.StatusCode -lt 400) {
            throw "blocked $Label review was accepted (HTTP $($approved.StatusCode))"
        }
        $blockedExport = Invoke-Api -Method POST -Url "$Base/api/sessions/$sid/export"
        if ($blockedExport.StatusCode -ne 400) {
            throw "blocked $Label export expected HTTP 400, got $($blockedExport.StatusCode): $($blockedExport.Text)"
        }
        $blockedDownload = Invoke-Api -Method GET -Url "$Base/api/sessions/$sid/download"
        if ($blockedDownload.StatusCode -ne 404) {
            throw "blocked $Label download expected HTTP 404, got $($blockedDownload.StatusCode)"
        }
        $afterSha = Get-FileSha256 $ExcelPath
        if ($afterSha -ne $sourceSha) {
            throw "Source fixture was mutated during $Label workflow"
        }
        Write-Host "OK blocked export ($Label) review=$($approved.StatusCode) export=400"
        return @{
            SavedMappingKey = $savedMappingKey
            Keep = $keep
            OutPath = $null
        }
    }
    if ($approved.StatusCode -ne 200) {
        throw "$Label APPROVE failed HTTP $($approved.StatusCode): $($approved.Text)"
    }
    if ($approved.Body.pricing_blockers -and @($approved.Body.pricing_blockers).Count -gt 0) {
        throw "$Label approved a row that still has pricing blockers"
    }

    foreach ($c in $candidates) {
        if ($c.candidate_id -eq $keep.candidate_id) { continue }
        try {
            Invoke-Json -Method POST `
                -Url "$Base/api/sessions/$sid/candidates/$($c.candidate_id)/review" `
                -Body @{ decision = "EXCLUDE" } | Out-Null
        } catch {
            # Some statuses cannot be excluded; ignore.
        }
    }

    $export = Invoke-Json -Method POST -Url "$Base/api/sessions/$sid/export"
    if (-not $export.updated_count -or $export.updated_count -lt 1) {
        throw "export updated_count expected >= 1"
    }
    Write-Host "OK export ($($export.updated_count) rows)"

    $outXlsx = Join-Path $DataDir ("smoke-out-" + $Label + ".xlsx")
    Invoke-WebRequest -Uri "$Base/api/sessions/$sid/download" -OutFile $outXlsx -UseBasicParsing -TimeoutSec 120
    if ((Get-Item $outXlsx).Length -lt 1000) {
        throw "download too small for $Label"
    }
    Write-Host "OK download $outXlsx"

    $afterSha = Get-FileSha256 $ExcelPath
    if ($afterSha -ne $sourceSha) {
        throw "Source fixture was mutated during $Label workflow"
    }
    Write-Host "OK source immutable ($Label)"

    $compareArgs = @(
        $CompareScript,
        "--source", $ExcelPath,
        "--exported", $outXlsx,
        "--source-sha256", $sourceSha
    )
    if ($HtmlXls) { $compareArgs += "--html-xls" }
    & $PythonExe @compareArgs
    if ($LASTEXITCODE -ne 0) { throw "compare_export failed for $Label" }

    return @{
        SavedMappingKey = $savedMappingKey
        Keep = $keep
        OutPath = $outXlsx
    }
}

function Invoke-ConfirmedMetreExport {
    param([string]$ExcelPath)

    $null = Invoke-Json -Method PUT -Url "$Base/api/settings" -Body @{
        settings = @{
            suspicious_percent_threshold = "30"
        }
    }
    Write-Host "OK warning-threshold setting"

    $sourceSha = Get-FileSha256 $ExcelPath
    $session = Invoke-Json -Method POST -Url "$Base/api/sessions"
    $sid = $session.session_id
    $null = Invoke-Multipart -Url "$Base/api/sessions/$sid/pioneers-excel" `
        -FormFields @{} `
        -FileField "file" `
        -FilePath $ExcelPath `
        -ContentType "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    $null = Invoke-Multipart -Url "$Base/api/sessions/$sid/supplier-pdf" `
        -FormFields @{ supplier_key = "dina_polymer" } `
        -FileField "file" `
        -FilePath $DinaPdf `
        -ContentType "application/pdf"
    $match = Invoke-Json -Method POST -Url "$Base/api/sessions/$sid/match" -Body @{}
    $pipe = $match.candidates | Where-Object {
        ($_.price_basis -eq "meter") -and (($null -eq $_.pricing_blockers) -or (@($_.pricing_blockers).Count -eq 0))
    } | Select-Object -First 1
    if (-not $pipe) { throw "no explicit per-metre Dina row without a hard blocker" }

    $query = -join @([char]0x0644, [char]0x0648, [char]0x0644, [char]0x0647)
    $escaped = [uri]::EscapeDataString($query)
    $search = Invoke-Json -Method GET -Url "$Base/api/sessions/$sid/pioneers-products/search?q=$escaped"
    if (-not $search.results -or @($search.results).Count -lt 1) {
        throw "Pioneers search returned no row for the Dina metre export"
    }
    $rowNumber = [int]$search.results[0].row_number
    $confirmed = Invoke-Json -Method POST `
        -Url "$Base/api/sessions/$sid/candidates/$($pipe.candidate_id)/confirm-mapping" `
        -Body @{ pioneers_row_number = $rowNumber; save = $true }
    if ($confirmed.pricing_blockers -and @($confirmed.pricing_blockers).Count -gt 0) {
        throw "confirmed Dina metre row is still blocked: $($confirmed.pricing_blockers -join ' | ')"
    }
    if (-not $confirmed.exportable) {
        $approved = Invoke-Api -Method POST `
            -Url "$Base/api/sessions/$sid/candidates/$($pipe.candidate_id)/review" `
            -Body @{ decision = "APPROVE" }
        if ($approved.StatusCode -ne 200 -or -not $approved.Body.exportable) {
            throw "compatible Dina metre APPROVE failed HTTP $($approved.StatusCode): $($approved.Text)"
        }
        $confirmed = $approved.Body
    }

    foreach ($c in $match.candidates) {
        if ($c.candidate_id -eq $pipe.candidate_id) { continue }
        try {
            Invoke-Json -Method POST `
                -Url "$Base/api/sessions/$sid/candidates/$($c.candidate_id)/review" `
                -Body @{ decision = "EXCLUDE" } | Out-Null
        } catch {
            # Unmatched rows that cannot be excluded do not become exportable.
        }
    }

    $export = Invoke-Api -Method POST -Url "$Base/api/sessions/$sid/export"
    if ($export.StatusCode -ne 200 -or $export.Body.updated_count -lt 1) {
        throw "Dina metre export failed HTTP $($export.StatusCode): $($export.Text)"
    }
    $outXlsx = Join-Path $DataDir "smoke-out-dina-metre.xlsx"
    Invoke-WebRequest -Uri "$Base/api/sessions/$sid/download" -OutFile $outXlsx -UseBasicParsing -TimeoutSec 120
    $expected = [string]$confirmed.new_price
    & $PythonExe -c @"
from decimal import Decimal
from openpyxl import load_workbook
header = ''.join(chr(cp) for cp in (0x0646,0x0631,0x062E,0x0020,0x0641,0x0631,0x0648,0x0634,0x0020,0x0627,0x0635,0x0644,0x06CC))
wb = load_workbook(r'$outXlsx')
ws = wb.active
headers = {cell.value: cell.column for cell in ws[1]}
value = ws.cell($rowNumber, headers[header]).value
wb.close()
if Decimal(str(value)) != Decimal('$expected'):
    raise SystemExit('sale cell %s != %s' % (value, '$expected'))
"@
    if ($LASTEXITCODE -ne 0) { throw "Dina metre sale cell was not the supplier price" }

    $compareArgs = @(
        $CompareScript,
        "--source", $ExcelPath,
        "--exported", $outXlsx,
        "--source-sha256", $sourceSha
    )
    & $PythonExe @compareArgs
    if ($LASTEXITCODE -ne 0) { throw "compare_export failed for dina-metre" }
    if ((Get-FileSha256 $ExcelPath) -ne $sourceSha) {
        throw "Source fixture was mutated during the Dina metre export"
    }
    $saved = Invoke-Json -Method GET -Url "$Base/api/suppliers/dina_polymer/mappings"
    if (-not $saved.mappings -or @($saved.mappings).Count -lt 1) {
        throw "Dina mapping was not saved"
    }
    Write-Host "OK Dina metre export row=$rowNumber price=$expected"
}

$smokeFailed = $false
try {
    Start-GheymatYar
    $health = Wait-GheymatYarReady
    Write-Host "OK health app=$($health.app) version=$($health.version)"

    $spa = Invoke-WebRequest -Uri "$Base/" -UseBasicParsing -TimeoutSec 10
    if ($spa.StatusCode -ne 200) { throw "SPA index HTTP $($spa.StatusCode)" }
    if ($spa.Content -match "fonts\.googleapis|cdn\.jsdelivr") {
        throw "SPA HTML/JS references external CDN assets"
    }
    Write-Host "OK spa index (no CDN refs in first document)"

    try {
        Invoke-WebRequest -Method POST -Uri "$Base/api/shutdown" -UseBasicParsing -TimeoutSec 5 | Out-Null
        throw "shutdown without token should fail"
    } catch {
        if ($_.Exception.Message -match "shutdown without token should fail") { throw }
        $msg = "$_"
        if ($msg -notmatch "403|control token|Forbidden") {
            throw "expected 403 for tokenless shutdown, got: $msg"
        }
    }
    Write-Host "OK shutdown rejects missing control token"

    # Foreign Host must be rejected for ordinary API reads/writes.
    try {
        Invoke-WebRequest -Uri "$Base/api/settings" -Headers @{ Host = "evil.example" } -UseBasicParsing -TimeoutSec 5 | Out-Null
        throw "foreign Host GET should fail"
    } catch {
        if ($_.Exception.Message -match "foreign Host GET should fail") { throw }
        $msg = "$_"
        if ($msg -notmatch "403|Host|Forbidden") {
            throw "expected 403 for foreign Host GET, got: $msg"
        }
    }
    Write-Host "OK foreign Host rejected on GET /api/settings"

    $null = Invoke-Workflow -ExcelPath $ExcelXlsx -Label "xlsx" -SaveMapping -ExpectBlocked
    $null = Invoke-Workflow -ExcelPath $ExcelXls -Label "xls" -HtmlXls -ExpectBlocked
    Invoke-ConfirmedMetreExport -ExcelPath $ExcelXlsx

    $mappingsBefore = Invoke-Json -Method GET -Url "$Base/api/suppliers/azin_pipe/mappings"
    if (-not $mappingsBefore.mappings -or $mappingsBefore.mappings.Count -lt 1) {
        throw "expected at least one saved mapping before restart"
    }
    $mappingProbe = $mappingsBefore.mappings[0]
    $probeId = [int]$mappingProbe.id
    $probeSupplier = [string]$mappingProbe.supplier_name_raw
    $probePioneers = [string]$mappingProbe.pioneers_name_raw
    Write-Host "OK mapping before restart id=$probeId supplier='$probeSupplier'"

    $dbPath = Join-Path $DataDir "gheymatyar.db"
    if (-not (Test-Path $dbPath)) { throw "SQLite DB missing at $dbPath" }

    Stop-GheymatYar -ViaApi

    Start-GheymatYar
    $null = Wait-GheymatYarReady
    $mappingsAfter = Invoke-Json -Method GET -Url "$Base/api/suppliers/azin_pipe/mappings"
    $found = $mappingsAfter.mappings | Where-Object {
        [int]$_.id -eq $probeId -and
        [string]$_.supplier_name_raw -eq $probeSupplier -and
        [string]$_.pioneers_name_raw -eq $probePioneers
    } | Select-Object -First 1
    if (-not $found) {
        throw "Mapping id=$probeId did not survive executable restart"
    }
    Write-Host "OK mapping persisted across restart id=$probeId"

    $dup = Invoke-Json -Method GET -Url "$Base/api/health"
    if ($dup.app -ne "gheymatyar") { throw "duplicate probe did not see gheymatyar" }
    Write-Host "OK instance identity stable for duplicate-launch reopen path"

    Stop-GheymatYar -ViaApi
}
catch {
    $smokeFailed = $true
    throw
}
finally {
    try {
        Stop-GheymatYar -ForceCleanup
    } catch {
        Write-Host "WARN cleanup: $_"
    }
    $env:PATH = $script:OriginalPath
    Remove-Item Env:GHEYMATYAR_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:GHEYMATYAR_PORT -ErrorAction SilentlyContinue
}

if ($smokeFailed) {
    throw "Packaged smoke test failed"
}

Write-Host "Packaged smoke test passed (blocked Azin export + Dina metre export + mapping restart)."
