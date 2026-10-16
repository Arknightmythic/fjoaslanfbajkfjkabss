# PowerShell script untuk menyalakan seluruh stack Synchrono Chatbot (DB + API) via Docker Compose
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Pastikan file .env ada
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "File .env belum ditemukan. Menyalin dari .env.example..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
    } else {
        Write-Error "File .env atau .env.example tidak ditemukan!"
    }
}

Write-Host "Membangun dan menyalakan seluruh stack Synchrono Chatbot via Docker Compose..." -ForegroundColor Cyan
docker compose --profile analytics --profile app up -d --build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Menunggu service siap menerima koneksi..." -ForegroundColor Yellow
$maxRetries = 30
$retryCount = 0
$ready = $false

while (-not $ready -and $retryCount -lt $maxRetries) {
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response -and $response.status -eq "healthy") {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
    $retryCount++
}

if ($ready) {
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "[SUCCESS] Synchrono Chatbot Full Stack Siap Digunakan!" -ForegroundColor Green
    Write-Host "Testing UI: http://localhost:8000/" -ForegroundColor Cyan
    Write-Host "API Docs:   http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "PostgreSQL: localhost:5433 (Database: synchrono_chatbot)" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Green
} else {
    Write-Host "Error: Timeout menunggu kesiapan service. Silakan periksa status dengan 'docker compose logs -f'." -ForegroundColor DarkYellow
    exit 1
}
