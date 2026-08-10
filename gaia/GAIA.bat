@echo off
REM ===================================================================
REM  GAIA launcher for Windows.
REM
REM  Double-click this file to start GAIA. It launches the backend and
REM  opens the interface in your default browser.
REM
REM  Run scripts\install.ps1 once before the first launch.
REM
REM  This is the no-build path. For a real installed application with a
REM  Start-menu entry, build the desktop app instead:
REM      powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Build
REM ===================================================================

cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
    echo.
    echo   GAIA is not installed yet.
    echo.
    echo   Open PowerShell in this folder and run:
    echo       powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    echo.
    pause
    exit /b 1
)

REM -ExecutionPolicy Bypass applies to this process only. It does not change
REM any machine or user setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1"

if errorlevel 1 (
    echo.
    echo   GAIA exited with an error. The log is in your GAIA data folder:
    echo       %%LOCALAPPDATA%%\GAIA\logs\gaia.log
    echo.
    pause
)
