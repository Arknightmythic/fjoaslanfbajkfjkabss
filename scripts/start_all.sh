#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "File .env belum ditemukan. Menyalin dari .env.example..."
        cp .env.example .env
    else
        echo "Error: File .env atau .env.example tidak ditemukan!"
        exit 1
    fi
fi

echo "Membangun dan menyalakan seluruh stack Synchrono Chatbot via Docker Compose..."
docker compose --profile analytics --profile app up -d --build

echo "Menunggu service siap menerima koneksi..."
max_retries=30
retry_count=0
ready=false

while [ "$ready" = false ] && [ $retry_count -lt $max_retries ]; do
    if curl -s -f http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 2
    retry_count=$((retry_count + 1))
done

if [ "$ready" = true ]; then
    echo "=========================================================="
    echo "[SUCCESS] Synchrono Chatbot Full Stack Siap Digunakan!"
    echo "Testing UI: http://localhost:8000/"
    echo "API Docs:   http://localhost:8000/docs"
    echo "PostgreSQL: localhost:5433 (Database: synchrono_chatbot)"
    echo "=========================================================="
else
    echo "Error: Timeout menunggu kesiapan service. Silakan cek 'docker compose logs -f'." >&2
    exit 1
fi
