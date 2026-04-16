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
$env:WORKER_CAMERA_BACKEND = "msmf"
$env:OPENCV_LOG_LEVEL = "FATAL"
$env:CAPTURE_FPS = "10"
$env:STREAM_WS_EVERY_SECONDS = "0.10"

Write-Host "WORKER_CAMERA_BACKEND=$env:WORKER_CAMERA_BACKEND"
Write-Host "OPENCV_LOG_LEVEL=$env:OPENCV_LOG_LEVEL"
Write-Host "CAPTURE_FPS=$env:CAPTURE_FPS"
Write-Host "STREAM_WS_EVERY_SECONDS=$env:STREAM_WS_EVERY_SECONDS"

Set-Location $WorkerDir
& $PythonExe -m app.main
