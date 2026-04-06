param([switch]$r)

# [shell] Search for Android NDK
# Unity NDK paths are checked first, then standard Android SDK paths.
# Unity installs its own NDK under the editor's PlaybackEngines directory.
$candidates = @()

$unityRoot = "C:\Program Files\Unity\Hub\Editor"
if (Test-Path $unityRoot) {
    Get-ChildItem $unityRoot | ForEach-Object {
        $candidates += "$($_.FullName)\Editor\Data\PlaybackEngines\AndroidPlayer\NDK"
    }
}

$candidates += @(
    $env:ANDROID_NDK_HOME,
    $env:ANDROID_NDK_ROOT,
    "$env:ANDROID_HOME\ndk-bundle",
    "$env:LOCALAPPDATA\Android\Sdk\ndk-bundle"
)

$ndkPath = $null
foreach ($path in $candidates) {
    if ($path -and (Test-Path "$path\toolchains")) {
        $ndkPath = $path
        break
    }
}

if (-not $ndkPath) {
    Write-Error "Android NDK not found. Install Android NDK via Unity or Android Studio."
    exit 1
}

Write-Host "NDK found: $ndkPath"

# [shell] Find aarch64 clang linker in NDK
# The binary name includes the API level (e.g. aarch64-linux-android21-clang.cmd).
# We pick the first available one.
$llvmBin = "$ndkPath\toolchains\llvm\prebuilt\windows-x86_64\bin"
$linker = Get-ChildItem "$llvmBin\aarch64-linux-android*-clang.cmd" |
    Sort-Object Name | Select-Object -First 1

if (-not $linker) {
    Write-Error "aarch64 clang linker not found in $llvmBin"
    exit 1
}

# [shell] Set linker and CC for this session only
# CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER must be set before cargo starts.
# CC_aarch64-linux-android is required by cc-rs for C dependency compilation.
# PATH is temporarily extended so cc-rs can locate the NDK clang.
$env:CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER = $linker.FullName
$env:CC_aarch64_linux_android = $linker.FullName
$env:AR_aarch64_linux_android = "$llvmBin\llvm-ar.exe"
$env:PATH = "$llvmBin;" + $env:PATH
Write-Host "Linker: $($linker.FullName)"

# [shell] Build unity-ffi for Android
cargo build --target aarch64-linux-android -p unity-ffi --manifest-path ../Cargo.toml $(if ($r) { "--release" })
