import os
import subprocess
import sys
import shutil
import re
from pathlib import Path
import graph_to_text
import copybook_resolver
from copybook_resolver import Colors
from sandbox_manager import SandboxEnvironment






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
        print(f"Usage: python analyze.py <filename.cbl> [--llm] [--graphviz] [--lenient] [--ignore-copybooks] [--no-sandbox]")
        print(f"       (Ensure the file exists in {src_dir})")
        sys.exit(1)

    target_path = Path(sys.argv[1]).resolve().absolute()
    if not target_path.exists():
        Colors.print_msg(f"Error: File not found at {target_path}", Colors.RED)
        sys.exit(1)

    target_file = target_path.name
    src_dir = target_path.parent
    copybooks_dir = src_dir # Assume copybooks are in the same dir for now

    use_llm = "--llm" in sys.argv
    use_graphviz = "--graphviz" in sys.argv
    use_lenient = "--lenient" in sys.argv
    lenient_flag = "--lenient" if use_lenient else ""
    ignore_copybooks = "--ignore-copybooks" in sys.argv
    use_sandbox = "--no-sandbox" not in sys.argv


    # Ensure Report Directory Exists
    os.makedirs(report_dir, exist_ok=True)

    Colors.print_msg("---------------------------------------------------", Colors.BLUE)
    Colors.print_msg(f"Analyzing: {target_file}", Colors.GREEN)
    Colors.print_msg(f"Source Dir: {src_dir}", Colors.GREEN)
    if use_llm:
        Colors.print_msg("LLM Analysis: ENABLED (see run_llm_documentation.py for config)", Colors.YELLOW)
    if use_lenient:
        Colors.print_msg("Lenient Mode: ENABLED (will continue despite parsing errors)", Colors.YELLOW)
    if ignore_copybooks:
        Colors.print_msg("Ignore Copybooks: ENABLED (All copybooks will be DUMMY)", Colors.MAGENTA)
    if use_sandbox:
        Colors.print_msg("Sandbox Mode: ENABLED (isolated environment with auto-stubbing)", Colors.YELLOW)
    Colors.print_msg("---------------------------------------------------", Colors.BLUE)

    # Set up sandbox environment if enabled
    sandbox = None
    effective_src_dir = src_dir
    effective_copybooks_dir = copybooks_dir
    effective_target_file = target_file
    
    if use_sandbox:
        Colors.print_msg("[0/7] Setting up Sandbox Environment...", Colors.BLUE)
        # Create sandbox with auto-stub enabled (unless ignore_copybooks is set)
        sandbox = SandboxEnvironment(
            source_file=target_path,
            copybook_dirs=[copybooks_dir],
            auto_stub=not ignore_copybooks,
            verbose=True
        )
        sandbox.__enter__()
        
        # Use sandbox paths for analysis
        effective_src_dir = sandbox.sandbox_source_dir
        effective_copybooks_dir = sandbox.sandbox_copybooks
        effective_target_file = sandbox.sandbox_source.name
        
        if sandbox.stubs_created:
            Colors.print_msg(f"  Auto-created {len(sandbox.stubs_created)} stub copybooks", Colors.YELLOW)
    else:
        # Legacy mode: resolve copybooks in-place
        Colors.print_msg("[0/7] Resolving Copybook Dependencies...", Colors.BLUE)
        copybook_resolver.resolve_copybooks_recursively(target_path, copybooks_dir, src_dir, ignore_mode=ignore_copybooks)


    # 1. Core Structures
    Colors.print_msg("[1/7] Generating Core Structures (AST, CFG)...", Colors.GREEN)
    cmd_core = (
        f'java -jar "{smojol_cli}" run "{effective_target_file}" '
        f'--commands="WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES" '
        f'--srcDir "{effective_src_dir}" '
        f'--copyBooksDir "{effective_copybooks_dir}" '
        f'--dialectJarPath "{dialect_jar}" '
        f'--dialect COBOL '
        f'--reportDir "{report_dir}" '
        f'--generation=PROGRAM '
        f'{lenient_flag}'
    )
    run_command(cmd_core)

    # 2. Advanced Analysis
    Colors.print_msg("[2/7] Generating Advanced Analysis (Transpiler, Unified, GraphML)...", Colors.GREEN)
    cmd_adv = (
        f'java -jar "{smojol_cli}" run "{effective_target_file}" '
        f'--commands="BUILD_TRANSPILER_FLOWGRAPH ATTACH_COMMENTS BUILD_PROGRAM_DEPENDENCIES EXPORT_UNIFIED_TO_JSON FLOW_TO_GRAPHML" '
        f'--srcDir "{effective_src_dir}" '
        f'--copyBooksDir "{effective_copybooks_dir}" '
        f'--dialectJarPath "{dialect_jar}" '
        f'--dialect COBOL '
        f'--reportDir "{report_dir}" '
        f'--generation=PROGRAM '
        f'{lenient_flag}'
    )
    # Allow this to fail without stopping
    run_command(cmd_adv, check=False)

    # 3. Mermaid Flowchart
    Colors.print_msg("[3/7] Attempting Mermaid Flowchart Generation (Section-based)...", Colors.GREEN)
    cmd_mermaid = (
        f'java -jar "{smojol_cli}" run "{effective_target_file}" '
        f'--commands="EXPORT_MERMAID" '
        f'--srcDir "{effective_src_dir}" '
        f'--copyBooksDir "{effective_copybooks_dir}" '
        f'--dialectJarPath "{dialect_jar}" '
        f'--dialect COBOL '
        f'--reportDir "{report_dir}" '
        f'--generation=SECTION '
        f'{lenient_flag}'
    )
    run_command(cmd_mermaid)

    if use_graphviz:
        Colors.print_msg("[3.5/7] Generating Graphviz Flowchart (DOT/SVG)...", Colors.GREEN)
        cmd_graphviz = (
            f'java -jar "{smojol_cli}" run "{effective_target_file}" '
            f'--commands="EXPORT_GRAPHVIZ" '
            f'--srcDir "{effective_src_dir}" '
            f'--copyBooksDir "{effective_copybooks_dir}" '
            f'--dialectJarPath "{dialect_jar}" '
            f'--dialect COBOL '
            f'--reportDir "{report_dir}" '
            f'--generation=PROGRAM '
            f'{lenient_flag}'
        )
        run_command(cmd_graphviz)

        # 3.5.1 Generate LLM Input
        report_subdir_gv = Path(report_dir) / f"{target_file}.report" / "graphviz"
        llm_input_dir = Path(report_dir) / f"{target_file}.report" / "llm_input"
        
        if report_subdir_gv.exists():
            Colors.print_msg("[3.6/7] Generating LLM Input Text...", Colors.GREEN)
            os.makedirs(llm_input_dir, exist_ok=True)
            for dot_file in report_subdir_gv.glob("*.dot"):
                out_txt = llm_input_dir / f"{dot_file.stem}.txt"
                Colors.print_msg(f"  Converting {dot_file.name} -> {out_txt.name}", Colors.GREEN)
                nodes, edges = graph_to_text.parse_dot(str(dot_file))

                if nodes:
                    graph_to_text.generate_llm_text(nodes, edges, str(out_txt))





    report_subdir = Path(report_dir) / f"{target_file}.report"
    
    # 4. Custom CFG to Mermaid
    Colors.print_msg("[4/7] Converting CFG to Mermaid (Custom Program-wide Flowchart)...", Colors.GREEN)
    cfg_json = report_subdir / "cfg" / f"cfg-{target_file}.json"
    mermaid_out = report_subdir / "mermaid" / "program_flow.md"
    os.makedirs(mermaid_out.parent, exist_ok=True)

    if cfg_json.exists():
        run_command(f'"{sys.executable}" json_to_mermaid.py "{cfg_json}" "{mermaid_out}"')
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
        run_command(f'"{sys.executable}" -m src.analysis.variable_static_values "{ast_json}" --output="{values_out}"', env=env)
    else:
        Colors.print_msg(f"Warning: AST JSON not found at {ast_json}", Colors.YELLOW)

    # 6. Data Dependency Graph
    Colors.print_msg("[6/7] Generating Data Dependency Graph...", Colors.GREEN)
    unified_json = report_subdir / "unified_model" / f"{target_file}-unified.json"
    dep_mermaid = report_subdir / "mermaid" / "data_dependencies.md"
    
    if unified_json.exists():
        run_command(f'"{sys.executable}" convert_dependencies.py "{unified_json}" "{dep_mermaid}"')
    else:
        Colors.print_msg(f"Warning: Unified JSON not found at {unified_json}", Colors.YELLOW)

    # 7. HTML Viewer
    Colors.print_msg("[7/7] Generating HTML Visualizer...", Colors.GREEN)
    cmd_viewer = (
        f'"{sys.executable}" generate_viewer.py '
        f'--mermaid-dir "{report_subdir / "mermaid"}" '
        f'--output "{report_subdir / "visualize_graphs.html"}" '
        f'--title "{target_file}" '
        f'--source "{target_path}"'
    )
    if use_graphviz:
        cmd_viewer += ' --graphviz'

    run_command(cmd_viewer)


    # 8. LLM Documentation (Optional)
    if use_llm:
        Colors.print_msg("[8/8] Running LLM Documentation Generation...", Colors.GREEN)
        
        # LLM input directory from graphviz conversion
        llm_input_dir = report_subdir / "llm_input"
        
        if llm_input_dir.exists():
            # Call run_llm_documentation.py - it owns all model/port/endpoint config
            run_command(f'"{sys.executable}" run_llm_documentation.py "{llm_input_dir}" --verbose')
        else:
            Colors.print_msg(f"Warning: LLM input directory not found at {llm_input_dir}", Colors.YELLOW)
            Colors.print_msg("Tip: Use --graphviz flag to generate LLM input files.", Colors.YELLOW)

    Colors.print_msg("[Optional] Converting AST and Data Structures to Graphs...", Colors.GREEN)
    run_command(f'"{sys.executable}" convert_json_graphs.py "{report_subdir}"')

    # Regenerate Viewer to include new graphs
    Colors.print_msg("[Refresing] Generating HTML Visualizer...", Colors.GREEN)
    run_command(cmd_viewer)

    # Cleanup sandbox if used
    if sandbox is not None:
        Colors.print_msg("[Cleanup] Removing sandbox environment...", Colors.BLUE)
        sandbox.__exit__(None, None, None)

    Colors.print_msg("===================================================", Colors.BLUE)
    Colors.print_msg("Analysis complete. View results at:", Colors.GREEN)
    Colors.print_msg(f"  {report_subdir / 'visualize_graphs.html'}")
    Colors.print_msg("===================================================", Colors.BLUE)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
