$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
$distRoot = Join-Path $backendRoot "dist"
$output = Join-Path $distRoot "quick-sciplot-backend"
$targetDir = Join-Path $backendRoot "..\frontend\src-tauri\backend-dist"

if (-not (Test-Path -LiteralPath $python)) {
    throw "backend/.venv not found. Create it and install requirements-build.txt first."
}

foreach ($lockFile in @("requirements.lock.txt", "requirements-sandbox.lock.txt")) {
    $lockPath = Join-Path $backendRoot $lockFile
    if (-not (Test-Path -LiteralPath $lockPath)) {
        throw "Missing dependency lock file: $lockPath"
    }
}

# One-dir build: a one-file executable unpacks ~150 MB on every launch, which
# made the desktop app take 30+ seconds to start on busy machines.
# The sandbox Dockerfile and its lock file are bundled so the first-run wizard
# can build the Docker image without the source repository.
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --name quick-sciplot-backend `
    --distpath $distRoot `
    --workpath (Join-Path $backendRoot "build") `
    --specpath $backendRoot `
    --paths $backendRoot `
    --add-data "$(Join-Path $backendRoot 'Dockerfile.sandbox');." `
    --add-data "$(Join-Path $backendRoot 'requirements-sandbox.lock.txt');." `
    --collect-submodules app `
    --collect-all matplotlib `
    --collect-all pandas `
    --collect-all scipy `
    --collect-all seaborn `
    --collect-all statsmodels `
    --collect-all plotly `
    --collect-all openpyxl `
    (Join-Path $backendRoot "run_server.py")

if (-not (Test-Path -LiteralPath (Join-Path $output "quick-sciplot-backend.exe"))) {
    throw "PyInstaller did not produce $output"
}

if (Test-Path -LiteralPath $targetDir) {
    Remove-Item -LiteralPath $targetDir -Recurse -Force
}
Copy-Item -LiteralPath $output -Destination $targetDir -Recurse
Write-Output "Created $targetDir"

if ($env:GENERATE_SBOM -eq "1") {
    $sbomScript = Join-Path $backendRoot "generate_sbom.py"
    $sbomOutput = Join-Path $distRoot "quick-sciplot-backend.sbom.json"
    & $python $sbomScript --output $sbomOutput
    if ($LASTEXITCODE -ne 0) {
        throw "SBOM generation failed"
    }
    Write-Output "Created $sbomOutput"
}
