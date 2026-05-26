param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$DistName = "ADB_RTSP_Player"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$ToolsRoot = Join-Path $Root "tools"
$AdbSourceDir = Join-Path $ToolsRoot "adb"
$FfmpegSourceDir = Join-Path $ToolsRoot "ffmpeg"
$AdbExe = Join-Path $AdbSourceDir "adb.exe"
$FfplayExe = Join-Path $FfmpegSourceDir "ffplay.exe"
$SpecPath = Join-Path $Root "packaging\windows\ADB_RTSP_Player.spec"
$DistDir = Join-Path $Root "dist\$DistName"
$DistToolsDir = Join-Path $DistDir "tools"
$ZipPath = Join-Path $Root "dist\${DistName}_Windows.zip"

if (!(Test-Path -LiteralPath $AdbExe)) {
    throw "Missing bundled adb at $AdbExe"
}

if (!(Test-Path -LiteralPath $FfplayExe)) {
    throw "Missing bundled ffplay at $FfplayExe"
}

$PushedLocation = $false
$SmokeRoot = $null

try {
    Push-Location -LiteralPath $Root
    $PushedLocation = $true

    & $Python -m unittest discover -v
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed"
    }

    & $Python -m compileall -q app.py rtsp_tool
    if ($LASTEXITCODE -ne 0) {
        throw "Python compile check failed"
    }

    & $Python -m PyInstaller --version
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run '$Python -m pip install -r requirements-build.txt' before running this script."
    }

    & $Python -m PyInstaller --clean --noconfirm $SpecPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed"
    }

    if (!(Test-Path -LiteralPath $DistDir)) {
        throw "PyInstaller did not create $DistDir"
    }

    Remove-Item -LiteralPath $DistToolsDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $DistToolsDir | Out-Null
    Copy-Item -LiteralPath $AdbSourceDir -Destination (Join-Path $DistToolsDir "adb") -Recurse
    Copy-Item -LiteralPath $FfmpegSourceDir -Destination (Join-Path $DistToolsDir "ffmpeg") -Recurse

    $PackagedAdbExe = Join-Path $DistToolsDir "adb\adb.exe"
    $PackagedAdbApiDll = Join-Path $DistToolsDir "adb\AdbWinApi.dll"
    $PackagedAdbUsbDll = Join-Path $DistToolsDir "adb\AdbWinUsbApi.dll"
    $PackagedFfplayExe = Join-Path $DistToolsDir "ffmpeg\ffplay.exe"

    if (!(Test-Path -LiteralPath $PackagedAdbExe)) {
        throw "Packaged adb.exe is missing"
    }
    if (!(Test-Path -LiteralPath $PackagedAdbApiDll)) {
        throw "Packaged AdbWinApi.dll is missing"
    }
    if (!(Test-Path -LiteralPath $PackagedAdbUsbDll)) {
        throw "Packaged AdbWinUsbApi.dll is missing"
    }
    if (!(Test-Path -LiteralPath $PackagedFfplayExe)) {
        throw "Packaged ffplay.exe is missing"
    }

    & $PackagedAdbExe version
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged adb.exe failed to run"
    }

    & $PackagedFfplayExe -version
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged ffplay.exe failed to run"
    }

    Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
    Compress-Archive -LiteralPath $DistDir -DestinationPath $ZipPath

    if (!(Test-Path -LiteralPath $ZipPath)) {
        throw "Zip package was not created"
    }

    $SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ADB_RTSP_Player_smoke_{0}" -f [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $SmokeRoot -Force

    if (!(Test-Path -LiteralPath (Join-Path $SmokeRoot "ADB_RTSP_Player\ADB_RTSP_Player.exe"))) {
        throw "Smoke test failed: packaged ADB_RTSP_Player.exe is missing"
    }

    $SmokeAdbExe = Join-Path $SmokeRoot "ADB_RTSP_Player\tools\adb\adb.exe"
    $SmokeAdbApiDll = Join-Path $SmokeRoot "ADB_RTSP_Player\tools\adb\AdbWinApi.dll"
    $SmokeAdbUsbDll = Join-Path $SmokeRoot "ADB_RTSP_Player\tools\adb\AdbWinUsbApi.dll"
    $SmokeFfplayExe = Join-Path $SmokeRoot "ADB_RTSP_Player\tools\ffmpeg\ffplay.exe"

    if (!(Test-Path -LiteralPath $SmokeAdbExe)) {
        throw "Smoke test failed: packaged adb.exe is missing"
    }
    if (!(Test-Path -LiteralPath $SmokeAdbApiDll)) {
        throw "Smoke test failed: packaged AdbWinApi.dll is missing"
    }
    if (!(Test-Path -LiteralPath $SmokeAdbUsbDll)) {
        throw "Smoke test failed: packaged AdbWinUsbApi.dll is missing"
    }
    if (!(Test-Path -LiteralPath $SmokeFfplayExe)) {
        throw "Smoke test failed: packaged ffplay.exe is missing"
    }

    & $SmokeAdbExe version
    if ($LASTEXITCODE -ne 0) {
        throw "Smoke test failed: packaged adb.exe failed to run"
    }

    & $SmokeFfplayExe -version
    if ($LASTEXITCODE -ne 0) {
        throw "Smoke test failed: packaged ffplay.exe failed to run"
    }

    Write-Host "Created $ZipPath"
}
finally {
    if ($SmokeRoot -and (Test-Path -LiteralPath $SmokeRoot)) {
        Remove-Item -LiteralPath $SmokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($PushedLocation) {
        Pop-Location
    }
}
