#!/bin/bash
# Script untuk menyalakan database PostgreSQL chatbot via Docker Compose
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Menyalakan PostgreSQL Chatbot container (Port 5433)..."
docker compose up -d postgres-chatbot

echo "Menunggu PostgreSQL siap menerima koneksi..."
until docker compose exec -T postgres-chatbot pg_isready -U synchrono -d synchrono_chatbot > /dev/null 2>&1; do
    sleep 1
done

echo "PostgreSQL Chatbot aktif dan siap di localhost:5433 (Database: synchrono_chatbot, User: synchrono)"
