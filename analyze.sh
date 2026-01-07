#!/bin/bash

# Configuration: Local Paths
SMOJOL_CLI="smojol-cli/target/smojol-cli.jar"
DIALECT_JAR="che-che4z-lsp-for-cobol-integration/server/dialect-idms/target/dialect-idms.jar"
SRC_DIR="smojol-test-code"
COPYBOOKS_DIR="smojol-test-code"
REPORT_DIR="out/report"
PYTHON_DIR="smojol_python"

# Check if parameters were provided
if [ -z "$1" ]; then
  echo "Usage: ./analyze.sh <filename.cbl> [--llm]"
  echo "       (Ensure the file exists in $SRC_DIR)"
  exit 1
fi

TARGET=$1
USE_LLM="false"
if [ "$2" == "--llm" ]; then
  USE_LLM="true"
fi

# Ensure Report Directory Exists
mkdir -p "$REPORT_DIR"

echo "---------------------------------------------------"
echo "Analyzing: $TARGET"
if [ "$USE_LLM" == "true" ]; then
    echo "LLM Analysis: ENABLED (Model: granite-code:20b)"
fi
echo "---------------------------------------------------"

# 1. Core Structures (AST, CFG, Data)
echo "[1/7] Generating Core Structures (AST, CFG)..."
java -jar "$SMOJOL_CLI" run "$TARGET" \
    --commands="WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES" \
    --srcDir "$SRC_DIR" \
    --copyBooksDir "$COPYBOOKS_DIR" \
    --dialectJarPath "$DIALECT_JAR" \
    --dialect COBOL \
    --reportDir "$REPORT_DIR" \
    --generation=PROGRAM

# 2. Advanced Analysis (Transpiler, Unified, GraphML, Dependencies)
echo "[2/7] Generating Advanced Analysis (Transpiler, Unified, GraphML)..."
# We allow this to fail without stopping the script completely, so the user gets at least the basic graphs
java -jar "$SMOJOL_CLI" run "$TARGET" \
    --commands="BUILD_TRANSPILER_FLOWGRAPH ATTACH_COMMENTS BUILD_PROGRAM_DEPENDENCIES EXPORT_UNIFIED_TO_JSON FLOW_TO_GRAPHML" \
    --srcDir "$SRC_DIR" \
    --copyBooksDir "$COPYBOOKS_DIR" \
    --dialectJarPath "$DIALECT_JAR" \
    --dialect COBOL \
    --reportDir "$REPORT_DIR" \
    --generation=PROGRAM || echo "Warning: Advanced analysis failed. Some graphs may be missing."

# 3. Mermaid Flowchart Generation (Section-based)
echo "[3/7] attempting Mermaid Flowchart Generation (Section-based)..."
java -jar "$SMOJOL_CLI" run "$TARGET" \
    --commands="EXPORT_MERMAID" \
    --srcDir "$SRC_DIR" \
    --copyBooksDir "$COPYBOOKS_DIR" \
    --dialectJarPath "$DIALECT_JAR" \
    --dialect COBOL \
    --reportDir "$REPORT_DIR" \
    --generation=SECTION

REPORT_SUBDIR="$REPORT_DIR/$TARGET.report"

# 4. Custom CFG to Mermaid Conversion (Program-wide fallback)
echo "[4/7] Converting CFG to Mermaid (Custom Program-wide Flowchart)..."
CFG_JSON="$REPORT_SUBDIR/cfg/cfg-$TARGET.json"
MERMAID_OUT="$REPORT_SUBDIR/mermaid/program_flow.md"
mkdir -p "$(dirname "$MERMAID_OUT")"

if [ -f "$CFG_JSON" ]; then
    python3 json_to_mermaid.py "$CFG_JSON" "$MERMAID_OUT"
else
    echo "Warning: CFG JSON not found at $CFG_JSON"
fi

# 5. Variable Static Values Analysis
echo "[5/7] Running Variable Static Values Analysis..."
AST_JSON="$REPORT_SUBDIR/ast/cobol-$TARGET.json"
VALUES_OUT="$REPORT_SUBDIR/variable_values.json"

if [ -f "$AST_JSON" ]; then
    # Create a temporary wrapper to run the module or set PYTHONPATH
    export PYTHONPATH=$PYTHONPATH:$(pwd)/$PYTHON_DIR
    python3 -m src.analysis.variable_static_values "$AST_JSON" --output="$VALUES_OUT"
else
     echo "Warning: AST JSON not found at $AST_JSON"
fi

# 6. HTML Viewer Generation
echo "[6/7] Generating HTML Visualizer..."
python3 generate_viewer.py \
    --mermaid-dir "$REPORT_SUBDIR/mermaid" \
    --output "$REPORT_SUBDIR/visualize_graphs.html" \
    --title "$TARGET"

# 7. LLM Analysis (Optional)
if [ "$USE_LLM" == "true" ]; then
    echo "[7/7] Running LLM-based Summarization..."
    export LLM_SOURCE=OLLAMA
    export OLLAMA_ENDPOINT=http://localhost:11434/api/generate
    export OLLAMA_MODEL="granite-code:20b"
    
    java -jar "$SMOJOL_CLI" run "$TARGET" \
        --commands="WRITE_LLM_SUMMARY" \
        --srcDir "$SRC_DIR" \
        --copyBooksDir "$COPYBOOKS_DIR" \
        --dialectJarPath "$DIALECT_JAR" \
        --dialect COBOL \
        --reportDir "$REPORT_DIR" \
        --generation=PROGRAM

    echo "[Optional] Generating LLM Graph..."
    LLM_JSON="$REPORT_SUBDIR/llm_summary/$TARGET-llm-summary.json"
    LLM_MERMAID="$REPORT_SUBDIR/mermaid/llm_summary_graph.md"
    if [ -f "$LLM_JSON" ]; then
        python3 llm_json_to_mermaid.py "$LLM_JSON" "$LLM_MERMAID"
    fi
fi

echo "[Optional] Converting AST and Data Structures to Graphs..."
python3 convert_json_graphs.py "$REPORT_SUBDIR"

# 6. HTML Viewer Generation
echo "[6/7] Generating HTML Visualizer..."
python3 generate_viewer.py \
    --mermaid-dir "$REPORT_SUBDIR/mermaid" \
    --output "$REPORT_SUBDIR/visualize_graphs.html" \
    --title "$TARGET"

echo "==================================================="
echo "Analysis complete. View results at:"
echo "  $REPORT_SUBDIR/visualize_graphs.html"
echo "==================================================="