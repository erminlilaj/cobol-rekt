#!/bin/bash

# Configuration: Paths INSIDE the container
SRC_DIR="/app/projects/Cobol-Projects/OpenCobol/dastagg/cbl"
CPY_DIR="/app/projects/Cobol-Projects/OpenCobol/cpy"
REPORT_DIR="/app/reports"

# Check if parameters were provided
if [ -z "$1" ]; then
  echo "Usage: ./analyze.sh <filename.cbl> [--llm] OR ./analyze.sh all [--llm]"
  exit 1
fi

TARGET=$1
USE_LLM="false"
if [ "$2" == "--llm" ]; then
  USE_LLM="true"
fi

# Function to run analysis on a specific file
run_analysis() {
  local filename=$1
  local llm=$2
  echo "---------------------------------------------------"
  echo "Analyzing: $filename"
  echo "---------------------------------------------------"
  
  local commands="DRAW_FLOWCHART"
  local env_vars=""

  if [ "$llm" == "true" ]; then
      commands="WRITE_LLM_SUMMARY DRAW_FLOWCHART"
      env_vars="-e LLM_SOURCE=OLLAMA -e OLLAMA_ENDPOINT=http://host.docker.internal:11434"
  fi

  docker compose exec $env_vars app java -jar /app/cli.jar run \
    --srcDir "$SRC_DIR" \
    --copyBooksDir "$CPY_DIR" \
    --reportDir "$REPORT_DIR" \
    --commands "$commands" \
    "$filename"
}

if [ "$TARGET" == "all" ]; then
  echo "Batch processing ALL files in $SRC_DIR..."
  # Loop through all .cbl files in the directory inside the container
  # We use 'docker compose exec' to list files inside the container first
  FILES=$(docker compose exec app ls "$SRC_DIR" | grep .cbl)
  
  for f in $FILES; do
    run_analysis "$f" "$USE_LLM"
  done
else
  # Process single file provided by user
  run_analysis "$TARGET" "$USE_LLM"
fi

echo "==================================================="
echo "Analysis complete. Check the 'reports' folder."
echo "==================================================="