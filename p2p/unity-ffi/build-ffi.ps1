param([switch]$r)   # -r: Android release 빌드 / 없음: Windows 에디터 debug 빌드

$unityFfi = Split-Path $MyInvocation.MyCommand.Path
$p2p      = Split-Path $unityFfi
$root     = Split-Path $p2p                # cadverse/
$plugins  = Join-Path $root "client\Assets\Plugins"

# ── Android release ───────────────────────────────────────────────────────────
if ($r) {
    # [shell] NDK 탐색
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
        if ($path -and (Test-Path "$path\toolchains")) { $ndkPath = $path; break }
    }
    if (-not $ndkPath) { Write-Error "Android NDK를 찾을 수 없음."; exit 1 }
    Write-Host "NDK: $ndkPath"

    # [shell] 크로스 컴파일 환경 변수 설정
    $llvmBin = "$ndkPath\toolchains\llvm\prebuilt\windows-x86_64\bin"
    $linker  = Get-ChildItem "$llvmBin\aarch64-linux-android*-clang.cmd" |
                   Sort-Object Name | Select-Object -First 1
    if (-not $linker) { Write-Error "aarch64 clang 링커를 찾을 수 없음: $llvmBin"; exit 1 }

    $env:CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER = $linker.FullName
    $env:CC_aarch64_linux_android                  = $linker.FullName
    $env:AR_aarch64_linux_android                  = "$llvmBin\llvm-ar.exe"
    $env:PATH                                      = "$llvmBin;" + $env:PATH
    Write-Host "링커: $($linker.FullName)"

    # [shell] 빌드
    cargo build --target aarch64-linux-android -p unity-ffi --manifest-path (Join-Path $p2p "Cargo.toml") --release
    if ($LASTEXITCODE -ne 0) { Write-Error "Android 빌드 실패"; exit $LASTEXITCODE }

    $soSrc     = Join-Path $p2p "target\aarch64-linux-android\release\libunity_ffi.so"
    $androidDir = Join-Path $plugins "Android"
    if (-not (Test-Path $soSrc)) { Write-Error "산출물 없음: $soSrc"; exit 1 }
    if (-not (Test-Path $androidDir)) { New-Item -ItemType Directory -Path $androidDir | Out-Null }
    Copy-Item $soSrc $androidDir -Force
    Write-Host "복사 완료: $soSrc -> $androidDir"
    exit 0
}

# ── Windows 에디터 debug ───────────────────────────────────────────────────────
cargo build -p unity-ffi --manifest-path (Join-Path $p2p "Cargo.toml")
if ($LASTEXITCODE -ne 0) { Write-Error "Windows 빌드 실패"; exit $LASTEXITCODE }

$dllSrc = Join-Path $p2p "target\debug\unity_ffi.dll"
if (-not (Test-Path $dllSrc)) { Write-Error "산출물 없음: $dllSrc"; exit 1 }
if (-not (Test-Path $plugins)) { New-Item -ItemType Directory -Path $plugins | Out-Null }
Copy-Item $dllSrc $plugins -Force
Write-Host "복사 완료: $dllSrc -> $plugins"
