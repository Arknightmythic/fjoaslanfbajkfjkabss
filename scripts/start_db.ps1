# PowerShell script untuk menyalakan database PostgreSQL chatbot via Docker Compose
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Menyalakan PostgreSQL Chatbot container (Port 5433)..." -ForegroundColor Cyan
docker compose up -d postgres-chatbot

Write-Host "Menunggu PostgreSQL siap menerima koneksi..." -ForegroundColor Yellow
$maxRetries = 20
$retryCount = 0
$ready = $false

while (-not $ready -and $retryCount -lt $maxRetries) {
    try {
        $result = docker compose exec -T postgres-chatbot pg_isready -U synchrono -d synchrono_chatbot 2>$null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
    $retryCount++
}

if ($ready) {
    Write-Host "PostgreSQL Chatbot aktif dan siap di localhost:5433 (Database: synchrono_chatbot, User: synchrono)" -ForegroundColor Green
} else {
    Write-Host "Peringatan: Timeout menunggu kesiapan PostgreSQL. Silakan cek docker compose logs." -ForegroundColor DarkYellow
}
