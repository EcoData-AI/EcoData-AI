<#
.SYNOPSIS
    Run GAIA without the desktop shell.

.DESCRIPTION
    Starts the backend, which also serves the built interface, then opens it in
    your default browser. Ctrl-C stops everything.
#>

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    Write-Host 'GAIA is not installed yet. Run .\scripts\install.ps1 first.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $Root 'frontend\dist'))) {
    Write-Host 'The interface has not been built. Run .\scripts\install.ps1 first.' -ForegroundColor Red
    exit 1
}

$port = if ($env:GAIA_PORT) { $env:GAIA_PORT } else { '8756' }
$url = "http://127.0.0.1:$port"

$backend = Start-Process -FilePath $Python -ArgumentList '-m', 'gaia', '--port', $port -PassThru -NoNewWindow

try {
    Write-Host -NoNewline 'Starting GAIA'
    $ready = $false
    foreach ($_ in 1..60) {
        try {
            Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {
            Write-Host -NoNewline '.'
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) {
        Write-Host "`nThe backend did not start. Check the log in your GAIA data directory." -ForegroundColor Red
        exit 1
    }

    Write-Host " ready`n`n  $url`n"
    Start-Process $url
    Wait-Process -Id $backend.Id
} finally {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
