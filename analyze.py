import os
import subprocess
import sys
import shutil
from pathlib import Path

# ANSI colors for terminal output
class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'
    YELLOW = '\033[1;33m'
    NC = '\033[0m'

    @staticmethod
    def print_msg(msg, color=NC):
        print(f"{color}{msg}{Colors.NC}")

def run_command(command, cwd=None, env=None, check=True):
    try:
        subprocess.run(command, cwd=cwd, env=env, check=check, shell=True)
    except subprocess.CalledProcessError as e:
        Colors.print_msg(f"Error running command: {e}", Colors.RED)
        if check:
            sys.exit(1)

def main():
    # Enable ANSI support on Windows
    os.system('')

    # Configuration
    current_dir = Path.cwd()
    smojol_cli = current_dir / "smojol-cli" / "target" / "smojol-cli.jar"
    dialect_jar = current_dir / "che-che4z-lsp-for-cobol-integration" / "server" / "dialect-idms" / "target" / "dialect-idms.jar"
    src_dir = "smojol-test-code"
    copybooks_dir = "smojol-test-code"
    report_dir = "out/report"
    python_dir = "smojol_python"

    # Argument Parsing
    if len(sys.argv) < 2:
        print(f"Usage: python analyze.py <filename.cbl> [--llm]")
        print(f"       (Ensure the file exists in {src_dir})")
        sys.exit(1)

    target_file = sys.argv[1]
    use_llm = "--llm" in sys.argv

    # Ensure Report Directory Exists
    os.makedirs(report_dir, exist_ok=True)

    Colors.print_msg("---------------------------------------------------", Colors.BLUE)
    Colors.print_msg(f"Analyzing: {target_file}", Colors.GREEN)
    if use_llm:
        Colors.print_msg("LLM Analysis: ENABLED (Model: granite-code:20b)", Colors.YELLOW)
    Colors.print_msg("---------------------------------------------------", Colors.BLUE)

    # 1. Core Structures
    Colors.print_msg("[1/7] Generating Core Structures (AST, CFG)...", Colors.GREEN)
    cmd_core = (
        f'java -jar "{smojol_cli}" run "{target_file}" '
        f'--commands="WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES" '
        f'--srcDir "{src_dir}" '
        f'--copyBooksDir "{copybooks_dir}" '
        f'--dialectJarPath "{dialect_jar}" '
        f'--dialect COBOL '
        f'--reportDir "{report_dir}" '
        f'--generation=PROGRAM'
    )
    run_command(cmd_core)

    # 2. Advanced Analysis
    Colors.print_msg("[2/7] Generating Advanced Analysis (Transpiler, Unified, GraphML)...", Colors.GREEN)
    cmd_adv = (
        f'java -jar "{smojol_cli}" run "{target_file}" '
        f'--commands="BUILD_TRANSPILER_FLOWGRAPH ATTACH_COMMENTS BUILD_PROGRAM_DEPENDENCIES EXPORT_UNIFIED_TO_JSON FLOW_TO_GRAPHML" '
        f'--srcDir "{src_dir}" '
        f'--copyBooksDir "{copybooks_dir}" '
        f'--dialectJarPath "{dialect_jar}" '
        f'--dialect COBOL '
        f'--reportDir "{report_dir}" '
        f'--generation=PROGRAM'
    )
    # Allow this to fail without stopping
    run_command(cmd_adv, check=False)

    # 3. Mermaid Flowchart
    Colors.print_msg("[3/7] Attempting Mermaid Flowchart Generation (Section-based)...", Colors.GREEN)
    cmd_mermaid = (
        f'java -jar "{smojol_cli}" run "{target_file}" '
        f'--commands="EXPORT_MERMAID" '
        f'--srcDir "{src_dir}" '
        f'--copyBooksDir "{copybooks_dir}" '
        f'--dialectJarPath "{dialect_jar}" '
        f'--dialect COBOL '
        f'--reportDir "{report_dir}" '
        f'--generation=SECTION'
    )
    run_command(cmd_mermaid)

    report_subdir = Path(report_dir) / f"{target_file}.report"
    
    # 4. Custom CFG to Mermaid
    Colors.print_msg("[4/7] Converting CFG to Mermaid (Custom Program-wide Flowchart)...", Colors.GREEN)
    cfg_json = report_subdir / "cfg" / f"cfg-{target_file}.json"
    mermaid_out = report_subdir / "mermaid" / "program_flow.md"
    os.makedirs(mermaid_out.parent, exist_ok=True)

    if cfg_json.exists():
        run_command(f'python json_to_mermaid.py "{cfg_json}" "{mermaid_out}"')
    else:
        Colors.print_msg(f"Warning: CFG JSON not found at {cfg_json}", Colors.YELLOW)

    # 5. Variable Static Values Analysis
    Colors.print_msg("[5/7] Running Variable Static Values Analysis...", Colors.GREEN)
    ast_json = report_subdir / "ast" / f"cobol-{target_file}.json"
    values_out = report_subdir / "variable_values.json"

    if ast_json.exists():
        env = os.environ.copy()
        # Add python module path to PYTHONPATH
        env["PYTHONPATH"] = f"{env.get('PYTHONPATH', '')}{os.pathsep}{current_dir / python_dir}"
        run_command(f'python -m src.analysis.variable_static_values "{ast_json}" --output="{values_out}"', env=env)
    else:
        Colors.print_msg(f"Warning: AST JSON not found at {ast_json}", Colors.YELLOW)

    # 6. Data Dependency Graph
    Colors.print_msg("[6/7] Generating Data Dependency Graph...", Colors.GREEN)
    unified_json = report_subdir / "unified_model" / f"{target_file}-unified.json"
    dep_mermaid = report_subdir / "mermaid" / "data_dependencies.md"
    
    if unified_json.exists():
        run_command(f'python convert_dependencies.py "{unified_json}" "{dep_mermaid}"')
    else:
        Colors.print_msg(f"Warning: Unified JSON not found at {unified_json}", Colors.YELLOW)

    # 7. HTML Viewer
    Colors.print_msg("[7/7] Generating HTML Visualizer...", Colors.GREEN)
    cmd_viewer = (
        f'python generate_viewer.py '
        f'--mermaid-dir "{report_subdir / "mermaid"}" '
        f'--output "{report_subdir / "visualize_graphs.html"}" '
        f'--title "{target_file}"'
    )
    run_command(cmd_viewer)

    # 8. LLM Analysis
    if use_llm:
        Colors.print_msg("[8/8] Running LLM-based Summarization...", Colors.GREEN)
        # Set environment variables for LLM
        env = os.environ.copy()
        env["LLM_SOURCE"] = "OLLAMA"
        env["OLLAMA_ENDPOINT"] = "http://localhost:11434/api/generate"
        env["OLLAMA_MODEL"] = "granite-code:20b"
        
        cmd_llm = (
            f'java -jar "{smojol_cli}" run "{target_file}" '
            f'--commands="WRITE_LLM_SUMMARY" '
            f'--srcDir "{src_dir}" '
            f'--copyBooksDir "{copybooks_dir}" '
            f'--dialectJarPath "{dialect_jar}" '
            f'--dialect COBOL '
            f'--reportDir "{report_dir}" '
            f'--generation=PROGRAM'
        )
        run_command(cmd_llm, env=env)

        Colors.print_msg("[Optional] Generating LLM Graph...", Colors.GREEN)
        llm_json = report_subdir / "llm_summary" / f"{target_file}-llm-summary.json"
        llm_mermaid = report_subdir / "mermaid" / "llm_summary_graph.md"
        
        if llm_json.exists():
            run_command(f'python llm_json_to_mermaid.py "{llm_json}" "{llm_mermaid}"')

    Colors.print_msg("[Optional] Converting AST and Data Structures to Graphs...", Colors.GREEN)
    run_command(f'python convert_json_graphs.py "{report_subdir}"')

    # Regenerate Viewer to include new graphs
    Colors.print_msg("[Refresing] Generating HTML Visualizer...", Colors.GREEN)
    run_command(cmd_viewer)

    Colors.print_msg("===================================================", Colors.BLUE)
    Colors.print_msg("Analysis complete. View results at:", Colors.GREEN)
    Colors.print_msg(f"  {report_subdir / 'visualize_graphs.html'}")
    Colors.print_msg("===================================================", Colors.BLUE)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
