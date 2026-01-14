#!/usr/bin/env pwsh
# ========================================
# Set PyO3 Environment Variable
# ========================================

Write-Host "Setting up PyO3 environment variable..." -ForegroundColor Cyan
Write-Host ""

# Get Python path from conda environment
$pythonPath = "C:\Users\nananina\anaconda3\envs\cadverse_dev\python.exe"

# Check if Python exists
if (Test-Path $pythonPath) {
    Write-Host "✓ Found Python at: $pythonPath" -ForegroundColor Green

    # Set user environment variable (permanent)
    [System.Environment]::SetEnvironmentVariable('PYO3_PYTHON', $pythonPath, 'User')

    # Also set for current session
    $env:PYO3_PYTHON = $pythonPath

    Write-Host "✓ PYO3_PYTHON environment variable set successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Variable will be available in new terminal sessions." -ForegroundColor Yellow
    Write-Host "For current session, it's already set." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Verification:" -ForegroundColor Cyan
    Write-Host "  PYO3_PYTHON = $env:PYO3_PYTHON"
    Write-Host ""
} else {
    Write-Host "✗ Python not found at: $pythonPath" -ForegroundColor Red
    Write-Host "Please run setup_pychrono_env.ps1 first" -ForegroundColor Yellow
    exit 1
}

Write-Host "Done! You can now build Rust projects with PyO3." -ForegroundColor Green
