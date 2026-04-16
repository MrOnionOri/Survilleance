$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$VenvDir = Join-Path $BackendDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creando venv del backend..."
    Set-Location $BackendDir
    python -m venv .venv
}

Set-Location $BackendDir
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r requirements.txt

$HasEnvFile = Test-Path ".env"

if (-not $env:DATABASE_URL -and -not $HasEnvFile) {
    $env:DATABASE_URL = "mysql+pymysql://streamwatch:streamwatch@localhost:3306/streamwatch?charset=utf8mb4"
}

if (-not $env:JWT_SECRET -and -not $HasEnvFile) {
    $env:JWT_SECRET = "dev-local-change-me"
}

if (-not $env:ADMIN_EMAIL -and -not $HasEnvFile) {
    $env:ADMIN_EMAIL = "admin@streamwatch.example.com"
}

if (-not $env:ADMIN_PASSWORD -and -not $HasEnvFile) {
    $env:ADMIN_PASSWORD = "admin123"
}

if (-not $env:STREAMWATCH_DATA_DIR -and -not $HasEnvFile) {
    $env:STREAMWATCH_DATA_DIR = $Root
}

Write-Host "Backend: http://localhost:8000"
if ($env:DATABASE_URL) {
    Write-Host "DB: $env:DATABASE_URL"
} else {
    Write-Host "DB: usando backend\.env"
}
& $PythonExe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
