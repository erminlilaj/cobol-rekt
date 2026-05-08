#!/bin/bash
set -e # Exit immediately if a command fails

echo "========================================="
echo "STEP 1: Compiling Java Sources Locally..."
echo "========================================="
# Run the local build script
./scripts/build-all.sh

echo "========================================="
echo "STEP 2: Resetting Docker Environment..."
echo "========================================="
# Remove old containers to prevent conflicts
docker compose down --remove-orphans

echo "========================================="
echo "STEP 3: Building and Starting Containers..."
echo "========================================="
# Build the image (copying the fresh JARs) and start in background
docker compose up -d --build

echo "========================================="
echo "DONE! System is running."
echo "Web Dashboard: http://localhost:7070"
echo "Neo4j Browser: http://localhost:7474"
echo "========================================="