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

# Finding a usable Python is the one step where being clever backfires.
#
# Two rules, both learned the hard way:
#
# 1. NEVER put a double quote inside the -c argument. Windows PowerShell does
#    not escape embedded double quotes when it builds a native command line,
#    so the quotes are consumed as delimiters and Python receives a corrupted
#    snippet — a SyntaxError it reports on stderr, which a 2>$null hides. The
#    result is an interpreter that works perfectly being reported as missing.
#
# 2. Let Python decide whether Python is new enough, and answer through its
#    exit code. Parsing a version string in PowerShell means string splitting,
#    integer casts and comparison operators, every one of which is a chance to
#    get a future version wrong. `sys.version_info >= (3, 10)` cannot be.
#
# There is deliberately no upper bound: a newer Python is supported unless a
# dependency says otherwise, and the dependencies are checked by the test
# suite rather than guessed at here.
$python = $null
$pythonVersion = $null
$rejected = @()

foreach ($candidate in @('python', 'python3', 'py')) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }

    $reported = & $candidate -c "import sys; print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null

    if ($LASTEXITCODE -eq 0 -and $reported) {
        $python = $candidate
        $pythonVersion = $reported
        break
    }
    # Record near-misses so the failure message can be specific instead of
    # telling someone with a working Python to go and install Python.
    if ($reported) { $rejected += "$candidate reports $reported" }
}

if (-not $python) {
    $detail = if ($rejected.Count) {
        'Found, but too old: ' + ($rejected -join '; ') + '.'
    } else {
        'No working Python was found on PATH.'
    }
    Fail @"
Python 3.10 or newer is required. $detail
Install it from https://www.python.org/downloads/windows/ and tick
'Add python.exe to PATH' in the installer. Avoid the Microsoft Store build.
"@
}
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
