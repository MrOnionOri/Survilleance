$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend-svelte"

Set-Location $FrontendDir

if (-not (Test-Path "node_modules")) {
    Write-Host "Instalando dependencias del frontend..."
    npm install
}

Write-Host "Frontend: http://localhost:5173"
npm run dev
