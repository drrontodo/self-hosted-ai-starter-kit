@echo off
REM ---------------------------------------------------------------------------
REM Double-click to start the CPD Companion. No terminal work needed.
REM
REM Stops any previous instance still holding port 8340, starts the app in its
REM own minimised window, waits until it actually answers /health, and opens the
REM dashboard. Safe to run when nothing is running, and safe to run twice.
REM
REM Holds no secrets - everything sensitive lives in cpd-companion\.env.
REM ---------------------------------------------------------------------------
title CPD Companion

where pwsh >nul 2>&1
if errorlevel 1 (
    echo PowerShell 7 ^(pwsh^) was not found on PATH.
    echo Install it, or start the app with: powershell -File scripts\start-cpd.ps1
    echo.
    pause
    exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-cpd.ps1" -Detach
if errorlevel 1 (
    echo.
    echo Startup FAILED - see the message above.
    echo.
    pause
    exit /b 1
)

start "" http://localhost:8340/
REM Cosmetic pause so the success message is readable before the window closes.
REM /nobreak plus swallowed stderr keeps this quiet when stdin is redirected.
timeout /t 4 /nobreak >nul 2>&1
exit /b 0
