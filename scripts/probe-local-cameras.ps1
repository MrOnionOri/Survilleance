$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$WorkerDir = Join-Path $Root "worker"
$PythonExe = Join-Path $WorkerDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "No existe el venv del worker. Creandolo ahora..."
    & (Join-Path $PSScriptRoot "setup-local-worker.ps1")
}

Set-Location $WorkerDir
& $PythonExe -m app.probe_cameras
