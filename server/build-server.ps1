param([switch]$r)

# [shell] Locate conda via CONDA_BASE
# CONDA_BASE is set once by setup-server.ps1 as a user environment variable
# PATH is not permanently modified - only this session uses conda paths
if (-not $env:CONDA_BASE) {
    Write-Error "CONDA_BASE is not set. Run setup-server.ps1 first."
    exit 1
}

$env:PYTHONPATH = ""
$env:PYTHONHOME = ""
$env:PATH = "$env:CONDA_BASE;$env:CONDA_BASE\Scripts;$env:CONDA_BASE\condabin;" + $env:PATH
. "$env:CONDA_BASE\shell\condabin\conda-hook.ps1"

# [shell] Activate conda env
# Only shell can set PATH for child processes
conda activate cadverse

# [shell] Invoke cargo
# env update and conda-pack are handled inside build.rs
cargo build --manifest-path Cargo.toml $(if ($r) { "--release" })
