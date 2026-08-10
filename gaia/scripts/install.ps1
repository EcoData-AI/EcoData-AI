<#
.SYNOPSIS
    GAIA installer for Windows.

.DESCRIPTION
    Creates a virtualenv for the backend and builds the frontend. Nothing is
    installed system-wide and no user data is written by this script.

.PARAMETER Build
    Also build a double-clickable desktop installer (requires Rust).

.EXAMPLE
    .\scripts\install.ps1
    .\scripts\install.ps1 -Build
#>

[CmdletBinding()]
param([switch]$Build)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Say  { param($m) Write-Host "`n$m" -ForegroundColor White }
function Ok   { param($m) Write-Host "  [ok] $m" -ForegroundColor Green }
function Fail { param($m) Write-Host "  [!!] $m" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- checks

Say 'Checking prerequisites'

$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $command) { continue }
    try {
        $version = & $candidate -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        $parts = $version.Split('.')
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) { $python = $candidate; break }
    } catch { }
}
if (-not $python) { Fail 'Python 3.10+ is required. Install it from python.org, then re-run.' }
# Quote carefully: the PowerShell string is double-quoted so the Python source
# inside it can use single quotes. Backslash is not a PowerShell escape, so a
# backslash-escaped quote here would reach Python verbatim and be a SyntaxError.
$pythonVersion = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Ok "Python $pythonVersion ($python)"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail 'Node.js 18+ is required (https://nodejs.org).'
}
Ok "Node $(node -v)"

if ($Build -and -not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Fail 'Rust is required to build the desktop app (https://rustup.rs).'
}

# --------------------------------------------------------------- backend

Say 'Installing the backend'
$BackendDir = Join-Path $Root 'backend'
# Absolute path: PowerShell's call operator does not resolve a bare relative
# path the way a shell would.
$VenvPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
Push-Location $BackendDir
try {
    if (-not (Test-Path $VenvPython)) { & $python -m venv .venv }
    if (-not (Test-Path $VenvPython)) {
        Fail "Creating the virtualenv failed. Check that '$python -m venv' works."
    }
    Ok 'virtualenv at backend\.venv'
    & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { Fail 'Could not upgrade pip.' }
    & $VenvPython -m pip install --quiet -e .
    if ($LASTEXITCODE -ne 0) { Fail 'Installing the backend dependencies failed.' }
    Ok 'backend dependencies installed'
    if ((Test-Path '.env.example') -and -not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Ok 'created backend\.env from the example'
    }
} finally { Pop-Location }

# -------------------------------------------------------------- frontend

Say 'Building the interface'
Push-Location (Join-Path $Root 'frontend')
try {
    npm install --no-audit --no-fund --silent
    npm run build --silent
    Ok 'frontend built to frontend\dist'
} finally { Pop-Location }

# --------------------------------------------------------------- desktop

if ($Build) {
    Say 'Building the desktop application (this takes several minutes the first time)'
    Push-Location $Root
    try {
        npm install --no-audit --no-fund --silent
        npx tauri build
        Ok 'installer written to src-tauri\target\release\bundle\'
    } finally { Pop-Location }
}

Say 'GAIA is installed'
Write-Host @'
  Start it with:
      .\scripts\run.ps1

  Or build a double-clickable desktop app:
      .\scripts\install.ps1 -Build

  Your data will live outside this folder, under %LOCALAPPDATA%\GAIA.
  GAIA shows the exact path in Settings -> Data.
'@
