#!/bin/bash

# Configuration: Paths INSIDE the container
SRC_DIR="/app/projects/Cobol-Projects/OpenCobol/dastagg/cbl"
CPY_DIR="/app/projects/Cobol-Projects/OpenCobol/cpy"
REPORT_DIR="/app/reports"

# Check if a parameter was provided
if [ -z "$1" ]; then
  echo "Usage: ./analyze.sh <filename.cbl> OR ./analyze.sh all"
  exit 1
fi

TARGET=$1

# Function to run analysis on a specific file
run_analysis() {
  local filename=$1
  echo "---------------------------------------------------"
  echo "Analyzing: $filename"
  echo "---------------------------------------------------"
  
  docker compose exec app java -jar /app/cli.jar run \
    --srcDir "$SRC_DIR" \
    --copyBooksDir "$CPY_DIR" \
    --reportDir "$REPORT_DIR" \
    --commands DRAW_FLOWCHART \
    "$filename"
}

if [ "$TARGET" == "all" ]; then
  echo "Batch processing ALL files in $SRC_DIR..."
  # Loop through all .cbl files in the directory inside the container
  # We use 'docker compose exec' to list files inside the container first
  FILES=$(docker compose exec app ls "$SRC_DIR" | grep .cbl)
  
  for f in $FILES; do
    run_analysis "$f"
  done
else
  # Process single file provided by user
  run_analysis "$TARGET"
fi

echo "==================================================="
echo "Analysis complete. Check the 'reports' folder."
echo "==================================================="