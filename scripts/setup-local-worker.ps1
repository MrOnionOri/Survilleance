$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$WorkerDir = Join-Path $Root "worker"
$VenvDir = Join-Path $WorkerDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvDir)) {
    Write-Host "Creando entorno virtual del worker..."
    python -m venv $VenvDir
}

Write-Host "Instalando dependencias del worker..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $WorkerDir "requirements.txt")

Write-Host "Worker local listo."
Write-Host "Para ejecutarlo: .\scripts\run-local-worker.ps1"

