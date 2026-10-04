$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
$output = Join-Path $backendRoot "dist\quick-sciplot-backend.exe"
$targetDir = Join-Path $backendRoot "..\frontend\src-tauri\binaries"
$target = "x86_64-pc-windows-msvc"
$targetBinary = Join-Path $targetDir "quick-sciplot-backend-$target.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "backend/.venv not found. Create it and install requirements-build.txt first."
}

foreach ($lockFile in @("requirements.lock.txt", "requirements-sandbox.lock.txt")) {
    $lockPath = Join-Path $backendRoot $lockFile
    if (-not (Test-Path -LiteralPath $lockPath)) {
        throw "Missing dependency lock file: $lockPath"
    }
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name quick-sciplot-backend `
    --distpath (Join-Path $backendRoot "dist") `
    --workpath (Join-Path $backendRoot "build") `
    --specpath $backendRoot `
    --paths $backendRoot `
    --collect-submodules app `
    --collect-all matplotlib `
    --collect-all pandas `
    --collect-all scipy `
    --collect-all seaborn `
    --collect-all statsmodels `
    --collect-all plotly `
    --collect-all openpyxl `
    (Join-Path $backendRoot "run_server.py")

if (-not (Test-Path -LiteralPath $output)) {
    throw "PyInstaller did not produce $output"
}

if (-not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir | Out-Null
}
Copy-Item -LiteralPath $output -Destination $targetBinary -Force
Write-Output "Created $targetBinary"

if ($env:GENERATE_SBOM -eq "1") {
    $sbomScript = Join-Path $backendRoot "generate_sbom.py"
    $sbomOutput = Join-Path $backendRoot "dist\quick-sciplot-backend.sbom.json"
    & $python $sbomScript --output $sbomOutput
    if ($LASTEXITCODE -ne 0) {
        throw "SBOM generation failed"
    }
    Write-Output "Created $sbomOutput"
}
