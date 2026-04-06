param([switch]$r)

# [shell] Search for Android NDK
# Unity NDK paths are checked first, then standard Android SDK paths.
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

# Android SDK NDK 버전 디렉토리 탐색 (e.g. AppData\Local\Android\Sdk\ndk\27.x.x)
$sdkNdkDir = "$env:LOCALAPPDATA\Android\Sdk\ndk"
if (Test-Path $sdkNdkDir) {
    Get-ChildItem $sdkNdkDir | Sort-Object Name -Descending | ForEach-Object {
        $candidates += $_.FullName
    }
}

$ndkPath = $null
foreach ($path in $candidates) {
    if ($path -and (Test-Path "$path\toolchains")) {
        $ndkPath = $path
        break
    }
}

if (-not $ndkPath) {
    Write-Error "Android NDK not found. Install Android NDK via Unity or Android Studio, or set ANDROID_NDK_HOME."
    exit 1
}

Write-Host "NDK found: $ndkPath"

# [shell] Find aarch64 clang linker in NDK
$llvmBin = "$ndkPath\toolchains\llvm\prebuilt\windows-x86_64\bin"
$linker = Get-ChildItem "$llvmBin\aarch64-linux-android*-clang.cmd" |
    Sort-Object Name | Select-Object -First 1

if (-not $linker) {
    Write-Error "aarch64 clang linker not found in $llvmBin"
    exit 1
}

# [shell] Set Android SDK path (ANDROID_HOME)
# cargo-apk uses ANDROID_HOME to find build-tools (aapt2, zipalign, apksigner).
$sdkCandidates = @(
    $env:ANDROID_HOME,
    $env:ANDROID_SDK_ROOT,
    "$env:LOCALAPPDATA\Android\Sdk"
)
$sdkPath = $null
foreach ($path in $sdkCandidates) {
    if ($path -and (Test-Path "$path\build-tools")) {
        $sdkPath = $path
        break
    }
}
if (-not $sdkPath) {
    Write-Error "Android SDK not found. Install Android Studio or set ANDROID_HOME."
    exit 1
}
Write-Host "SDK found: $sdkPath"

# [shell] Set NDK env vars before cargo starts
# ANDROID_NDK_HOME is required by cargo-apk for APK packaging.
# CARGO_TARGET_* / CC_* / AR_* are required for cross-compilation and cc-rs.
$env:ANDROID_HOME = $sdkPath
$env:ANDROID_NDK_HOME = $ndkPath
$env:CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER = $linker.FullName
$env:CC_aarch64_linux_android = $linker.FullName
$env:AR_aarch64_linux_android = "$llvmBin\llvm-ar.exe"
$env:PATH = "$llvmBin;" + $env:PATH
Write-Host "Linker: $($linker.FullName)"

# [shell] Ensure Rust Android target is installed
# rustup must run before cargo-apk because cargo-apk needs the target stdlib.
rustup target add aarch64-linux-android

# [shell] Ensure cargo-apk is installed
# cargo-apk must exist before we invoke it; shell installs it if missing.
if (-not (Get-Command cargo-apk -ErrorAction SilentlyContinue)) {
    Write-Host "Installing cargo-apk..."
    cargo install cargo-apk
}

# [shell] Build APK
cargo apk build -p android-sample --manifest-path ../Cargo.toml $(if ($r) { "--release" })

if ($LASTEXITCODE -eq 0) {
    $apkDir = if ($r) { "../target/release/apk" } else { "../target/debug/apk" }
    Write-Host ""
    Write-Host "APK: $apkDir\android-sample.apk"
    Write-Host "Install: adb install $apkDir\android-sample.apk"
}
