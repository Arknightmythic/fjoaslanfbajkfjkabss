# PowerShell script untuk mematikan seluruh stack Synchrono Chatbot
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Menghentikan seluruh container Synchrono Chatbot..." -ForegroundColor Yellow
docker compose down

Write-Host "Seluruh container berhasil dihentikan." -ForegroundColor Green
