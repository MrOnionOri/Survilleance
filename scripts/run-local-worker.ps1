$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$WorkerDir = Join-Path $Root "worker"
$VenvDir = Join-Path $WorkerDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "No existe el venv del worker. Creandolo ahora..."
    & (Join-Path $PSScriptRoot "setup-local-worker.ps1")
}

$env:BACKEND_URL = "http://localhost:8000"
$env:WORKER_EMAIL = "admin@streamwatch.example.com"
$env:WORKER_PASSWORD = "admin123"
$env:STREAMWATCH_DATA_DIR = $Root
$env:WORKER_SOURCE_SCOPE = "local"
if (-not $env:WORKER_DEBUG) { $env:WORKER_DEBUG = "0" }
if ($env:WORKER_DEBUG -ne "0") { Write-Host "WORKER_DEBUG activo: $env:WORKER_DEBUG" }

Set-Location $WorkerDir
& $PythonExe -m app.main
