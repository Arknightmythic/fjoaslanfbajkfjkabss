#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Menghentikan seluruh container Synchrono Chatbot..."
docker compose down

echo "Seluruh container berhasil dihentikan."
