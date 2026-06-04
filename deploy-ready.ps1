param([string]$v = "")

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null
Set-Location $PSScriptRoot

# 버전 자동 추출 (Cargo.toml)
if (-not $v) {
    $line = Select-String -Path "server\Cargo.toml" -Pattern '^version\s*=' | Select-Object -First 1
    $v = ($line.Line -replace '.*"([^"]+)".*', '$1').Trim()
}
Write-Host "배포 버전: $v"

# 임시 스테이징 폴더 (모든 요소가 준비되면 deploy로 교체)
$stage = Join-Path $env:TEMP "cadverse_deploy_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

try {
    # ── 서버 ──────────────────────────────────────────────────────────────────
    Write-Host "`n[1/3] 서버 릴리즈 빌드..."
    Push-Location "server"
    try {
        & ".\build-server.ps1" -r
        if ($LASTEXITCODE -ne 0) { throw "서버 빌드 실패" }
    } finally {
        Pop-Location
    }

    $serverExe    = "server\target\release\server.exe"
    $serverBundle = "server\target\release\python_env.tar.gz"
    if (-not (Test-Path $serverExe))    { throw "빌드 산출물 없음: $serverExe" }
    if (-not (Test-Path $serverBundle)) { throw "빌드 산출물 없음: $serverBundle" }

    # ── 클라이언트 APK ────────────────────────────────────────────────────────
    Write-Host "`n[2/3] 클라이언트 APK 수집..."
    $apk = Get-ChildItem "client\*.apk" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $apk) { throw "client\ 에 APK 파일이 없습니다. Unity에서 먼저 빌드하세요." }

    Copy-Item $apk.FullName -Destination "$stage\CADverse-$v-client.apk" -Force
    Write-Host "클라이언트 완료  (원본: $($apk.Name))"

    # ── 서버+플러그인 ZIP ─────────────────────────────────────────────────────
    Write-Host "`n[3/3] 서버+플러그인 패키징..."
    $zipTmp = Join-Path $env:TEMP "cadverse_zip_tmp"
    if (Test-Path $zipTmp) { Remove-Item $zipTmp -Recurse -Force }
    New-Item -ItemType Directory -Force -Path "$zipTmp\server" | Out-Null
    New-Item -ItemType Directory -Force -Path "$zipTmp\plugin" | Out-Null

    Copy-Item $serverExe    -Destination "$zipTmp\server\CADverse.exe" -Force
    Copy-Item $serverBundle -Destination "$zipTmp\server\python_env.tar.gz" -Force

    $pluginFiles = @("CADverse.manifest","CADverse.py","extract.py","extract_mesh.py","extract_meta.py","palette.html","server.py")
    foreach ($f in $pluginFiles) {
        Copy-Item "cad_plugin\$f" -Destination "$zipTmp\plugin\$f" -Force
    }

    # Compress-Archive는 python_env.tar.gz 같은 큰 파일에서 극단적으로 느려 hang처럼 보임.
    # tar.gz는 이미 압축 상태라 추가 압축 효과도 거의 없으므로 .NET ZipFile을 store mode로 사용.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipOut = "$stage\CADverse-$v-server.zip"
    if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $zipTmp,
        $zipOut,
        [System.IO.Compression.CompressionLevel]::NoCompression,
        $false   # includeBaseDirectory=false → zip 루트에 server/, plugin/ 직접
    )
    Remove-Item $zipTmp -Recurse -Force
    Write-Host "패키징 완료"

    # ── README ────────────────────────────────────────────────────────────────
    Copy-Item "README.md" -Destination $stage -Force

    # ── 모두 성공 → deploy 교체 ───────────────────────────────────────────────
    Write-Host "`n모든 요소 준비 완료. deploy 폴더 교체 중..."
    if (Test-Path "deploy") { Remove-Item "deploy" -Recurse -Force }
    Move-Item $stage "deploy"

    Write-Host "`n배포 패키지 준비 완료:"
    Get-ChildItem "deploy" | ForEach-Object {
        Write-Host "  $($_.Name)  ($([math]::Round($_.Length/1MB,1)) MB)"
    }
}
catch {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    Write-Error "배포 준비 실패 (deploy 폴더 유지): $_"
    exit 1
}
