#!/bin/bash
set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Starting Cobol-REKT via Docker...${NC}"

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed. Please install Docker Desktop or Engine.${NC}"
    exit 1
fi

# Create necessary directories if they don't exist
mkdir -p projects reports neo4j_data db

# Check if projects dir is empty and warn (optional)
if [ -z "$(ls -A projects)" ]; then
    echo -e "${GREEN}Note: 'projects' directory is empty. Place your COBOL files there to analyze them.${NC}"
fi

# Initialize git submodules
if [ -f ".gitmodules" ]; then
    echo -e "${GREEN}Initializing git submodules...${NC}"
    git submodule update --init --recursive
fi

echo -e "${GREEN}Building and starting services...${NC}"
echo -e "Use Ctrl+C to stop the logs (containers will keep running)."
echo -e "To stop containers, run: docker-compose down"

docker-compose up --build
