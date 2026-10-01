# PowerShell script untuk mematikan database PostgreSQL chatbot agar hemat resource
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Menghentikan PostgreSQL Chatbot container..." -ForegroundColor Yellow
docker compose stop postgres-chatbot
Write-Host "PostgreSQL Chatbot container telah dimatikan." -ForegroundColor Green
