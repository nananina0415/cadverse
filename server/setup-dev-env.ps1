# [setup] Find existing conda installation
$candidates = @(
    "$env:USERPROFILE\anaconda3",
    "$env:USERPROFILE\miniconda3",
    "$env:LOCALAPPDATA\anaconda3",
    "$env:LOCALAPPDATA\miniconda3",
    "C:\ProgramData\anaconda3",
    "C:\ProgramData\miniconda3"
)

$condaBase = $null
foreach ($base in $candidates) {
    if (Test-Path "$base\Scripts\conda.exe") {
        $condaBase = $base
        break
    }
}

# [setup] Install Miniconda if not found
if (-not $condaBase) {
    $installPath = "$env:USERPROFILE\miniconda3"
    $installer = "$env:TEMP\miniconda_installer.exe"
    Write-Host "conda not found. Installing Miniconda to $installPath..."
    Invoke-WebRequest -Uri "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe" -OutFile $installer
    Start-Process -Wait -FilePath $installer -ArgumentList "/S /D=$installPath"
    Remove-Item $installer
    $condaBase = $installPath
}

# [setup] Register CONDA_BASE as persistent user environment variable
# PATH is not modified to avoid conflicts with other Python installations
[Environment]::SetEnvironmentVariable("CONDA_BASE", $condaBase, "User")
$env:CONDA_BASE = $condaBase
Write-Host "CONDA_BASE registered: $condaBase"

# [setup] Add conda to session PATH temporarily for env creation below
$env:PYTHONPATH = ""
$env:PYTHONHOME = ""
$env:PATH = "$condaBase;$condaBase\Scripts;$condaBase\condabin;" + $env:PATH
. "$condaBase\shell\condabin\conda-hook.ps1"

# [setup] Install libmamba solver in base if not already installed
# conda classic solver OOMs on large channels (e.g. conda-forge); libmamba is the fix
$libmambaInstalled = conda list -n base | Select-String "conda-libmamba-solver"
if (-not $libmambaInstalled) {
    Write-Host "Installing conda-libmamba-solver..."
    conda install -n base conda-libmamba-solver -y
    if ($LASTEXITCODE -ne 0) {
        Write-Error "conda-libmamba-solver install failed."
        exit 1
    }
}

# [setup] Create cadverse environment if not exists
# build-server.ps1 assumes the environment already exists (conda activate before cargo)
$envExists = conda env list | Select-String "cadverse"
if (-not $envExists) {
    Write-Host "Creating cadverse environment..."
    conda env create -f server/pychrono/environment.yml --solver=libmamba
    if ($LASTEXITCODE -ne 0) {
        Write-Error "conda env create failed."
        exit 1
    }
} else {
    Write-Host "cadverse environment already exists."
}

Write-Host "Setup complete. Run build-server.ps1 to build."
