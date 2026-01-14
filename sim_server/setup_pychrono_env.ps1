#!/usr/bin/env pwsh
# ========================================
# PyChrono Development Environment Setup
# Method A: Anaconda Installation
# PowerShell Version
# ========================================

Write-Host ""
Write-Host "========================================"
Write-Host "CADverse PyChrono Environment Setup"
Write-Host "========================================"
Write-Host ""

# Check if conda is installed
$condaExists = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaExists) {
    Write-Host "[ERROR] Conda is not found in PATH!" -ForegroundColor Red
    Write-Host "Please install Anaconda or Miniconda first:"
    Write-Host "https://www.anaconda.com/download"
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[1/5] Checking conda installation..." -ForegroundColor Cyan
conda --version
Write-Host ""

# Set environment name
$envName = "cadverse_dev"

Write-Host "[2/5] Creating conda environment '$envName' with Python 3.10..." -ForegroundColor Cyan
conda create -n $envName python=3.10 -y
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to create conda environment" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

Write-Host "[3/5] Activating environment..." -ForegroundColor Cyan
conda activate $envName
Write-Host ""

Write-Host "[4/5] Installing PyChrono 8.0.0..." -ForegroundColor Cyan
Write-Host "This may take several minutes..." -ForegroundColor Yellow
conda install projectchrono::pychrono=8.0.0 -c conda-forge -y
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install PyChrono" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

Write-Host "[5/5] Verifying installation..." -ForegroundColor Cyan
python -c "import pychrono.core as chrono; print('PyChrono imported successfully'); print('ChSystemNSC:', chrono.ChSystemNSC)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] PyChrono import failed" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Green
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Environment name: $envName"
Write-Host ""
Write-Host "To activate this environment, run:" -ForegroundColor Yellow
Write-Host "    conda activate $envName"
Write-Host ""
Write-Host "To set up PyO3 to use this environment:" -ForegroundColor Yellow
Write-Host "    `$env:PYO3_PYTHON = `"$env:CONDA_PREFIX\python.exe`""
Write-Host ""

# Get conda environment path
$condaInfo = conda info --envs | Select-String -Pattern $envName
if ($condaInfo) {
    Write-Host "Python path for PyO3:" -ForegroundColor Cyan
    $pythonPath = (Get-Command python).Source
    Write-Host "    $pythonPath" -ForegroundColor White
}

Read-Host "Press Enter to exit"
