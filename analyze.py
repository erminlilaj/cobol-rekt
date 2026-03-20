#!/usr/bin/env python3
"""
COBOL Analysis Orchestrator

Main entry point for analyzing COBOL source files. This script orchestrates:
1. Sandbox setup (isolation, auto-stubbing)
2. Dialect detection (IDMS vs standard COBOL)
3. smojol-cli invocations (AST, CFG, flowcharts)
4. Post-processing (Mermaid, Graphviz, LLM input)
5. HTML visualization generation

Usage:
    python analyze.py <file.cbl> [options]

Options:
    --no-graphviz             Skip Graphviz DOT/SVG and LLM input generation
    --lenient                 Continue despite parsing errors
    --ignore-copybooks        Stub all copybooks
    --no-sandbox              Skip sandbox (modify files in-place)
    --no-comment-enrichment   Skip Italian comment translation via Ollama (step 7b)
"""

import os
import subprocess
import sys
import shutil
import re
from pathlib import Path

# Local imports
import graph_to_text
import copybook_resolver
import knowledge_base_builder
import comment_extractor
import comment_enricher
from analysis import SandboxEnvironment, Colors

# ============================================================================
# Configuration
# ============================================================================

class Config:
    """Centralized configuration for the analysis pipeline."""
    
    def __init__(self):
        self.base_dir = Path.cwd()
        self.smojol_cli = self.base_dir / "smojol-cli" / "target" / "smojol-cli.jar"
        self.idms_dialect_jar = (
            self.base_dir / "che-che4z-lsp-for-cobol-integration" / 
            "server" / "dialect-idms" / "target" / "dialect-idms.jar"
        )
        self.report_dir = Path("out/report")
        self.python_dir = self.base_dir / "smojol_python"

# ============================================================================
# Utility Functions
# ============================================================================

def run_command(command, cwd=None, env=None, check=True):
    """Execute a shell command with error handling."""
    try:
        subprocess.run(command, cwd=cwd, env=env, check=check, shell=True)
    except subprocess.CalledProcessError as e:
        Colors.print_msg(f"Error running command: {e}", Colors.RED)
        if check:
            sys.exit(1)

def run_command_captured(command, cwd=None, env=None):
    """Execute a shell command and return the CompletedProcess with captured output.

    Unlike run_command(), this does NOT call sys.exit() on failure.
    The caller is responsible for checking the return code.
    """
    return subprocess.run(command, cwd=cwd, env=env, shell=True,
                          capture_output=True, text=True)

def _count_parse_errors(output: str) -> int:
    """Count parse errors from Java CLI output."""
    count = 0
    for line in output.splitlines():
        if re.search(r'SyntaxError|parsing error|ParseDiagnostic', line, re.IGNORECASE):
            count += 1
    return max(count, 1)  # At least 1 if we got here

def detect_dialect(source_file: Path) -> tuple:
    """
    Detect COBOL dialect by scanning source for IDMS keywords.
    Returns (dialect_name, requires_idms_jar)
    """
    try:
        content = source_file.read_text(errors='replace')[:50000]
    except Exception:
        return ('COBOL', False)
    
    idms_patterns = [
        r'\bBIND\s+RUN-UNIT\b',
        r'\bIDMS-\w+',
        r'\bOBTAIN\s+(CALC|FIRST|NEXT|OWNER|PRIOR)\b',
        r'\bREADY\s+USAGE-MODE\b',
    ]
    
    for pattern in idms_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return ('IDMS', True)
    
    return ('COBOL', False)

def pre_validate_and_stub(smojol_cli, target_file, src_dir, copybooks_dir, 
                          dialect_jar, lenient_flag, max_retries=3):
    """
    Pre-validation loop: parse, detect broken copybooks, stub them, retry.
    """
    all_stubbed = []
    stub_content = """\
      * STUB COPYBOOK - Auto-generated due to parsing errors
"""
    
    for attempt in range(1, max_retries + 1):
        cmd = (
            f'java -jar "{smojol_cli}" run "{target_file}" '
            f'--commands="WRITE_RAW_AST" '
            f'--srcDir "{src_dir}" --copyBooksDir "{copybooks_dir}" '
            f'--dialectJarPath "{dialect_jar}" --dialect COBOL '
            f'--reportDir "out/prevalidate_temp" --generation=PROGRAM {lenient_flag}'
        )
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        combined = result.stderr + result.stdout
        
        # Extract problematic copybook names
        problematic = set()
        for pattern in [r'copybookId["\s:=]+([A-Za-z0-9_-]+)',
                        r'Error.*copybook.*["\']([A-Za-z0-9_-]+)["\']']:
            for match in re.finditer(pattern, combined, re.IGNORECASE):
                name = match.group(1)
                if name and name.lower() not in ('null', 'none', 'cobol'):
                    problematic.add(name)
        
        if not problematic:
            break
        
        # Stub problematic copybooks
        stubbed_round = []
        for name in problematic:
            if name in all_stubbed:
                continue
            path = Path(copybooks_dir) / f"{name}.cpy"
            if path.exists():
                try:
                    path.write_text(stub_content, encoding='utf-8')
                    stubbed_round.append(name)
                    all_stubbed.append(name)
                except Exception:
                    pass
        
        if not stubbed_round:
            break
        Colors.print_msg(f"    Attempt {attempt}: stubbed {len(stubbed_round)} copybooks", Colors.YELLOW)
    
    # Cleanup
    temp_dir = Path("out/prevalidate_temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return all_stubbed

# ============================================================================
# Analysis Pipeline Steps
# ============================================================================

class AnalysisPipeline:
    """Orchestrates the COBOL analysis pipeline."""
    
    def __init__(self, config: Config, target_path: Path, options: dict):
        self.config = config
        self.target_path = target_path
        self.options = options
        
        self.verbose = options.get('verbose', False)
        # Effective paths (may be overridden by sandbox)
        self.src_dir = target_path.parent
        self.copybooks_dir = target_path.parent
        self.target_file = target_path.name
        self.report_subdir = config.report_dir / f"{self.target_file}.report"
        
        # Detect dialect
        self.dialect, self.needs_idms = detect_dialect(target_path)
        self.dialect_jar = config.idms_dialect_jar
        
        # Sandbox reference
        self.sandbox = None
    
    def setup_sandbox(self):
        """Set up isolated sandbox environment."""
        if not self.options.get('use_sandbox', True):
            Colors.print_msg("[0/7] Resolving Copybook Dependencies...", Colors.BLUE)
            copybook_resolver.resolve_copybooks_recursively(
                self.target_path, self.copybooks_dir, self.src_dir,
                ignore_mode=self.options.get('ignore_copybooks', False)
            )
            return
        
        Colors.print_msg("[0/7] Setting up Sandbox Environment...", Colors.BLUE)
        self.sandbox = SandboxEnvironment(
            source_file=self.target_path,
            copybook_dirs=[self.copybooks_dir],
            auto_stub=not self.options.get('ignore_copybooks', False),
            verbose=True
        )
        self.sandbox.__enter__()
        
        # Update paths to sandbox
        self.src_dir = self.sandbox.sandbox_source_dir
        self.copybooks_dir = self.sandbox.sandbox_copybooks
        self.target_file = self.sandbox.sandbox_source.name
        
        if self.sandbox.stubs_created:
            Colors.print_msg(f"  Auto-created {len(self.sandbox.stubs_created)} stubs", Colors.YELLOW)
        self._write_copybook_manifest()

    def _write_copybook_manifest(self):
        """Write copybook resolution report to report directory."""
        import json as _json
        cpb_dir = self.copybooks_dir
        if not Path(cpb_dir).is_dir():
            return
        stubbed = [s.upper() for s in getattr(self.sandbox, 'stubs_created', [])]
        manifest = {"program": self.target_file, "copybooks": {}, "summary": {}}

        for cpf in sorted(Path(cpb_dir).glob("*")):
            if not cpf.is_file():
                continue
            name = cpf.stem.upper()
            is_stub = name in stubbed
            try:
                lines = len(cpf.read_text(errors='replace').splitlines())
            except Exception:
                lines = 0
            manifest["copybooks"][name] = {
                "file": cpf.name,
                "is_stub": is_stub,
                "lines": lines,
                "status": "stubbed" if is_stub else "resolved",
            }

        total = len(manifest["copybooks"])
        stub_count = sum(1 for c in manifest["copybooks"].values() if c["is_stub"])
        manifest["summary"] = {
            "total_copybooks": total,
            "resolved": total - stub_count,
            "stubbed": stub_count,
            "resolved_percentage": round((total - stub_count) * 100.0 / total, 1) if total > 0 else 100.0,
        }

        out_path = self.report_subdir / "copybook_manifest.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_json.dumps(manifest, indent=2))
        if stub_count > 0:
            Colors.print_msg(
                f"  Copybooks: {manifest['summary']['resolved_percentage']}% resolved "
                f"({total - stub_count}/{total}), {stub_count} stubbed",
                Colors.YELLOW
            )

    def pre_validate(self):
        """Pre-validation: detect and stub broken copybooks."""
        if not self.options.get('use_sandbox', True):
            return
        
        Colors.print_msg("[0.5/7] Pre-validating syntax...", Colors.BLUE)
        lenient = "--lenient" if self.options.get('lenient') else ""
        problematic = pre_validate_and_stub(
            self.config.smojol_cli, self.target_file, self.src_dir,
            self.copybooks_dir, self.dialect_jar, lenient
        )
        if problematic:
            Colors.print_msg(f"  Stubbed {len(problematic)} problematic copybooks", Colors.YELLOW)
    
    def _build_smojol_cmd(self, commands: str, generation: str = "PROGRAM") -> str:
        """Build smojol-cli command string."""
        lenient = "--lenient" if self.options.get('lenient') else ""
        return (
            f'java -jar "{self.config.smojol_cli}" run "{self.target_file}" '
            f'--commands="{commands}" '
            f'--srcDir "{self.src_dir}" --copyBooksDir "{self.copybooks_dir}" '
            f'--dialectJarPath "{self.dialect_jar}" --dialect COBOL '
            f'--reportDir "{self.config.report_dir}" --generation={generation} {lenient}'
        )
    
    def step1_core_structures(self):
        """Generate AST, CFG, data structures.

        Smart behavior:
        1. Try strict parse first
        2. If strict fails and --lenient was not passed, auto-retry with --lenient
        3. If lenient succeeds, continue pipeline (Java wrote parse_diagnostics.json)
        4. If lenient also fails, write parse_failure_report.json from stderr
           and abort pipeline with structured error output
        5. Always log diagnostics before continuing or aborting
        """
        Colors.print_msg("[1/7] Generating Core Structures (AST, CFG)...", Colors.GREEN)

        cmd = self._build_smojol_cmd(
            "WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES"
        )

        result = run_command_captured(cmd)

        if result.returncode == 0:
            self._log_parse_diagnostics()
            return

        # Parse failed
        stderr = result.stderr or ""
        stdout = result.stdout or ""

        if self.options.get('lenient'):
            # Already running with --lenient — check if parse_diagnostics.json
            # was written. If so, the parse succeeded but a downstream task
            # crashed on the partial tree. We can still continue.
            if self._check_lenient_partial_success(stderr, "lenient"):
                return
            sys.exit(1)

        # Auto-retry with --lenient
        err_count = _count_parse_errors(stderr + stdout)
        Colors.print_msg(
            f"  Strict parse failed ({err_count} parse error(s)). "
            f"Auto-retrying with --lenient...",
            Colors.YELLOW
        )
        Colors.print_msg(
            "  Lenient mode uses ANTLR error recovery — only errored tokens "
            "are skipped, rest is fully analyzed.",
            Colors.YELLOW
        )

        # Enable lenient for this and all subsequent smojol commands
        self.options['lenient'] = True
        cmd_lenient = self._build_smojol_cmd(
            "WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES"
        )
        result2 = run_command_captured(cmd_lenient)

        if result2.returncode == 0:
            Colors.print_msg(
                "  Lenient parse succeeded. Continuing with partial analysis.",
                Colors.GREEN
            )
            self._log_parse_diagnostics()
            return

        # Even lenient returned non-zero — check if diagnostics were written
        stderr2 = result2.stderr or ""
        if self._check_lenient_partial_success(stderr2, "lenient-auto-retry"):
            return
        sys.exit(1)

    def _log_parse_diagnostics(self):
        """Read parse_diagnostics.json if it exists and log a summary."""
        import json as _json
        diag_path = self.report_subdir / "parse_diagnostics.json"
        if not diag_path.is_file():
            return
        try:
            diag = _json.loads(diag_path.read_text())
        except Exception:
            return
        coverage = diag.get("coverage_percentage", 0)
        errors = diag.get("error_summary", {}).get("total_errors", 0)
        affected = diag.get("affected_lines", 0)
        source_lines = diag.get("source_lines", 0)
        Colors.print_msg(
            f"[LENIENT] Parse coverage: {coverage}% "
            f"({errors} error(s) affecting {affected}/{source_lines} lines)",
            Colors.YELLOW
        )
        for err in diag.get("errors", []):
            line = err.get("line", "?")
            suggestion = err.get("suggestion", "Unknown error")
            source = err.get("source", "?")
            cpb = err.get("copybook")
            loc = f"line {line}" + (f" (copybook {cpb})" if cpb else "")
            Colors.print_msg(f"  [{source}] {loc}: {suggestion}", Colors.YELLOW)

    def _check_lenient_partial_success(self, stderr: str, mode: str) -> bool:
        """Check if lenient mode produced diagnostics despite non-zero exit code.

        The Java CLI may exit with code 1 even when lenient parsing succeeds,
        because a downstream task (e.g. WRITE_CFG) crashed on the partial tree.
        If parse_diagnostics.json exists, the parse DID succeed and we can
        continue with whatever output files were produced.

        Returns True if we can continue, False if it's a real failure.
        """
        diag_path = self.report_subdir / "parse_diagnostics.json"
        if diag_path.is_file():
            # Parse succeeded, downstream task failed — partial success
            Colors.print_msg(
                "  Lenient parse succeeded (some downstream tasks may have failed). "
                "Continuing with available output.",
                Colors.YELLOW
            )
            self._log_parse_diagnostics()
            return True

        # No diagnostics — real failure
        Colors.print_msg(
            "[FATAL] Parse failed even with --lenient mode.",
            Colors.RED
        )
        self._print_stderr_summary(stderr)
        self._write_parse_failure_report(stderr, mode)
        Colors.print_msg(
            f"  Failure report written to: "
            f"{self.report_subdir / 'parse_failure_report.json'}",
            Colors.YELLOW
        )
        return False

    def _parse_stderr_errors(self, stderr: str) -> list[dict]:
        """Parse Java CLI stderr to extract actual parse error info.

        Only captures lines that contain SyntaxError records, parse error
        messages, or exception stack traces — NOT regular [INFO] log lines.
        """
        errors = []
        for line in stderr.splitlines():
            # Skip normal log lines (they all start with timestamp + [INFO]/[WARNING] etc.)
            # We only want actual error content: SyntaxError records, exceptions, etc.
            is_error_line = bool(re.search(
                r'SyntaxError|ParseDiagnostic|Exception|'
                r'parsing error|LENIENT MODE|severity=ERROR',
                line, re.IGNORECASE
            ))
            if not is_error_line:
                continue

            err = {}
            line_match = re.search(r'(?:line\s*=\s*)(\d+)', line)
            if line_match:
                err["line"] = int(line_match.group(1))
            sev_match = re.search(r'severity[=\s]+(\w+)', line, re.IGNORECASE)
            if sev_match:
                err["severity"] = sev_match.group(1).upper()
            suggestion_match = re.search(r'suggestion[=\s]+(.*?)(?:,\s*severity|$)', line)
            if suggestion_match:
                err["suggestion"] = suggestion_match.group(1).strip()
            cpb_match = re.search(r'copybookId[=\s]+([A-Za-z0-9_-]+)', line, re.IGNORECASE)
            if cpb_match:
                name = cpb_match.group(1)
                if name.lower() not in ('null', 'none'):
                    err["copybook"] = name
            err["message"] = line.strip()
            errors.append(err)
        return errors

    def _write_parse_failure_report(self, stderr: str, mode: str):
        """Write parse_failure_report.json from Python-side stderr parsing.

        This is the fallback when Java CLI crashes and doesn't write
        parse_diagnostics.json itself.
        """
        import json as _json
        errors = self._parse_stderr_errors(stderr)
        report = {
            "program": self.target_file,
            "mode": mode,
            "status": "failed",
            "reason": "Java CLI exited with non-zero return code",
            "errors_extracted_from_stderr": errors,
            "error_count": len(errors),
            "raw_stderr_tail": "\n".join(stderr.splitlines()[-20:]) if stderr else "",
        }
        out_path = self.report_subdir / "parse_failure_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_json.dumps(report, indent=2))
        return report

    def _print_stderr_summary(self, stderr: str):
        """Print a structured summary of Java CLI stderr to the console."""
        errors = self._parse_stderr_errors(stderr)
        if errors:
            Colors.print_msg(f"  {len(errors)} error(s) detected:", Colors.RED)
            for err in errors[:10]:
                line = err.get("line", "?")
                msg = err.get("suggestion", err.get("message", "Unknown error"))
                cpb = err.get("copybook")
                loc = f"line {line}" + (f" (copybook {cpb})" if cpb else "")
                Colors.print_msg(f"    {loc}: {msg}", Colors.RED)
            if len(errors) > 10:
                Colors.print_msg(f"    ... and {len(errors) - 10} more", Colors.RED)
        else:
            tail = stderr.strip().splitlines()[-5:]
            for line in tail:
                Colors.print_msg(f"    {line}", Colors.RED)

    def step2_advanced_analysis(self):
        """Generate transpiler flowgraph, unified model, GraphML."""
        Colors.print_msg("[2/7] Generating Advanced Analysis...", Colors.GREEN)
        run_command(self._build_smojol_cmd(
            "BUILD_TRANSPILER_FLOWGRAPH ATTACH_COMMENTS BUILD_PROGRAM_DEPENDENCIES "
            "EXPORT_UNIFIED_TO_JSON FLOW_TO_GRAPHML"
        ), check=False)
    
    def step3_mermaid(self):
        """Generate Mermaid flowcharts."""
        Colors.print_msg("[3/7] Generating Mermaid Flowchart...", Colors.GREEN)
        run_command(self._build_smojol_cmd("EXPORT_MERMAID", generation="SECTION"))
    
    def step3b_graphviz(self):
        """Generate Graphviz diagrams and LLM input text."""
        if not self.options.get('graphviz'):
            return
        
        Colors.print_msg("[3.5/7] Generating Graphviz Flowchart...", Colors.GREEN)
        run_command(self._build_smojol_cmd("EXPORT_GRAPHVIZ"))
        
        # Convert DOT to LLM input
        gv_dir = self.report_subdir / "graphviz"
        llm_dir = self.report_subdir / "llm_input"
        
        if gv_dir.exists():
            Colors.print_msg("[3.6/7] Generating LLM Input Text...", Colors.GREEN)
            llm_dir.mkdir(exist_ok=True)
            for dot_file in gv_dir.glob("*.dot"):
                out_txt = llm_dir / f"{dot_file.stem}.txt"
                nodes, edges = graph_to_text.parse_dot(str(dot_file))
                if nodes:
                    graph_to_text.generate_llm_text(nodes, edges, str(out_txt))
    
    def step4_cfg_to_mermaid(self):
        """Convert CFG JSON to Mermaid."""
        Colors.print_msg("[4/7] Converting CFG to Mermaid...", Colors.GREEN)
        cfg_json = self.report_subdir / "cfg" / f"cfg-{self.target_file}.json"
        mermaid_out = self.report_subdir / "mermaid" / "program_flow.md"
        mermaid_out.parent.mkdir(exist_ok=True)
        
        if cfg_json.exists():
            run_command(f'"{sys.executable}" json_to_mermaid.py "{cfg_json}" "{mermaid_out}"')
        else:
            Colors.print_msg(f"  Warning: CFG JSON not found", Colors.YELLOW)
    
    def step5_variable_analysis(self):
        """Run variable static values analysis."""
        Colors.print_msg("[5/7] Running Variable Analysis...", Colors.GREEN)
        ast_json = self.report_subdir / "ast" / f"cobol-{self.target_file}.json"
        values_out = self.report_subdir / "variable_values.json"
        
        if ast_json.exists():
            env = os.environ.copy()
            env["PYTHONPATH"] = f"{env.get('PYTHONPATH', '')}{os.pathsep}{self.config.python_dir}"
            run_command(
                f'"{sys.executable}" -m src.analysis.variable_static_values "{ast_json}" '
                f'--output="{values_out}"', env=env
            )
        else:
            Colors.print_msg("  Warning: AST JSON not found", Colors.YELLOW)
    
    def step6_data_dependencies(self):
        """Generate data dependency graph."""
        Colors.print_msg("[6/7] Generating Data Dependency Graph...", Colors.GREEN)
        unified_json = self.report_subdir / "unified_model" / f"{self.target_file}-unified.json"
        dep_mermaid = self.report_subdir / "mermaid" / "data_dependencies.md"
        
        if unified_json.exists():
            run_command(f'"{sys.executable}" convert_dependencies.py "{unified_json}" "{dep_mermaid}"')
        else:
            Colors.print_msg("  Warning: Unified JSON not found", Colors.YELLOW)
    
    def step7_knowledge_base(self):
        """Build LLM-optimized knowledge base."""
        Colors.print_msg("[7/7] Building Knowledge Base...", Colors.GREEN)
        
        # Extract comments from original source file
        try:
            comments_output = self.report_subdir / "comments.json"
            comment_extractor.extract_comments_to_json(
                self.target_path, comments_output, verbose=False
            )
            if self.verbose:
                Colors.print_msg("  Extracted source comments", Colors.GREEN)
        except Exception as e:
            Colors.print_msg(f"  Warning: Comment extraction failed: {e}", Colors.YELLOW)
        
        try:
            kb_path = knowledge_base_builder.build_knowledge_base(
                self.report_subdir, self.target_file, verbose=True
            )
            Colors.print_msg(f"  Output: {kb_path}", Colors.GREEN)
        except Exception as e:
            Colors.print_msg(f"  Warning: Knowledge base generation failed: {e}", Colors.YELLOW)
    
    
    def step7b_comment_enrichment(self):
        """Translate and categorize Italian COBOL comments via Ollama (optional)."""
        if not self.options.get('comment_enrichment', True):
            Colors.print_msg("[7b] Comment enrichment skipped (--no-comment-enrichment)", Colors.BLUE)
            return

        comments_json = self.report_subdir / "comments.json"
        if not comments_json.exists():
            Colors.print_msg("[7b] Comment enrichment skipped: comments.json not found", Colors.YELLOW)
            return

        if not comment_enricher.check_ollama(port=11434):
            Colors.print_msg("[7b] Comment enrichment skipped: Ollama not reachable at localhost:11434", Colors.YELLOW)
            return

        Colors.print_msg("[7b] Enriching comments (translate + categorize)...", Colors.GREEN)
        try:
            out = comment_enricher.enrich_comments(
                comments_json,
                model=comment_enricher.DEFAULT_MODEL,
                port=comment_enricher.DEFAULT_PORT,
                verbose=self.verbose,
            )
            Colors.print_msg(f"  Output: {out}", Colors.GREEN)
        except Exception as e:
            Colors.print_msg(f"  Warning: Comment enrichment failed: {e}", Colors.YELLOW)

    def cleanup(self):
        """Cleanup sandbox and finalize."""
        # Convert additional JSON graphs
        run_command(f'"{sys.executable}" convert_json_graphs.py "{self.report_subdir}"')
        
        # Cleanup sandbox
        if self.sandbox:
            Colors.print_msg("[Cleanup] Removing sandbox...", Colors.BLUE)
            self.sandbox.__exit__(None, None, None)
        
        Colors.print_msg("=" * 60, Colors.BLUE)
        Colors.print_msg("Analysis complete. Results at:", Colors.GREEN)
        Colors.print_msg(f"  {self.report_subdir}")
        Colors.print_msg("=" * 60, Colors.BLUE)
    
    def run(self):
        """Execute the full analysis pipeline."""
        self.setup_sandbox()
        self.pre_validate()
        self.step1_core_structures()
        self.step2_advanced_analysis()
        self.step3_mermaid()
        self.step3b_graphviz()
        self.step4_cfg_to_mermaid()
        self.step5_variable_analysis()
        self.step6_data_dependencies()
        self.step7_knowledge_base()
        self.step7b_comment_enrichment()
        self.cleanup()

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    os.system('')  # Enable ANSI on Windows
    
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    target_path = Path(sys.argv[1]).resolve()
    if not target_path.exists():
        Colors.print_msg(f"Error: File not found: {target_path}", Colors.RED)
        sys.exit(1)
    
    # Parse options (graphviz enabled by default)
    options = {
        'graphviz': "--no-graphviz" not in sys.argv,
        'lenient': "--lenient" in sys.argv,
        'ignore_copybooks': "--ignore-copybooks" in sys.argv,
        'use_sandbox': "--no-sandbox" not in sys.argv,
        'comment_enrichment': "--no-comment-enrichment" not in sys.argv,
    }
    
    config = Config()
    config.report_dir.mkdir(parents=True, exist_ok=True)
    
    # Print banner
    Colors.print_msg("-" * 60, Colors.BLUE)
    Colors.print_msg(f"COBOL Analysis: {target_path.name}", Colors.GREEN)
    dialect, needs_idms = detect_dialect(target_path)
    Colors.print_msg(f"Dialect: {dialect}" + (" (IDMS)" if needs_idms else ""), Colors.BLUE)
    if options['graphviz']:
        Colors.print_msg("Graphviz: ENABLED", Colors.YELLOW)
    if options['use_sandbox']:
        Colors.print_msg("Sandbox: ENABLED", Colors.YELLOW)
    Colors.print_msg("-" * 60, Colors.BLUE)
    
    # Run pipeline
    pipeline = AnalysisPipeline(config, target_path, options)
    pipeline.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
