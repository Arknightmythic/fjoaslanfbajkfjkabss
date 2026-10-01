#!/bin/bash
# Script untuk mematikan database PostgreSQL chatbot agar hemat resource
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Menghentikan PostgreSQL Chatbot container..."
docker compose stop postgres-chatbot

echo "PostgreSQL Chatbot container telah dimatikan."
