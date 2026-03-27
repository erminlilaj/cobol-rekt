import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
TEST_ROOT = "che-che4z-lsp-for-cobol-integration/tests/test_files"

# ---------------------------------------------------------------------------
# Dry-run copybook scan (mirrors _pre_stub_from_source in analyze.py)
# ---------------------------------------------------------------------------

def _scan_copy_names(filepath):
    """Return the list of COPY-referenced copybook names in a COBOL source file."""
    try:
        source_text = filepath.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return []
    names = []
    for line in source_text.splitlines():
        if len(line) < 8:
            continue
        if line[6] in ('*', '/'):
            continue
        area = line[7:72]
        m = re.match(
            r'\s*COPY\s+([A-Z0-9@#$][A-Z0-9@#$_-]*)(?:\s+(?:IN|OF)\s+\S+)?',
            area, re.IGNORECASE
        )
        if m:
            names.append(m.group(1).upper())
    return list(set(names))

# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

def _copybook_ratio(filepath, copybooks_from_result, report_base_dir):
    """Return (found, total_needed) for copybooks actually referenced by filepath.

    'total_needed' = number of distinct COPY statements in the source.
    'found' = how many of those were resolved (not stubs) per the manifest.
    Returns (None, None) if source can't be scanned or manifest is unavailable.
    """
    needed = set(_scan_copy_names(filepath))
    if not needed:
        return None, None

    # Build name→is_stub lookup from the manifest returned by run_analysis
    stub_lookup = {}
    if copybooks_from_result and isinstance(copybooks_from_result[0], dict):
        for c in copybooks_from_result:
            stub_lookup[c["name"].upper()] = c.get("is_stub", True)

    if not stub_lookup:
        # Manifest not available (e.g. timeout before sandbox completes)
        return None, len(needed)

    found = sum(1 for n in needed if not stub_lookup.get(n, True))
    return found, len(needed)


def _read_analysis_coverage(filepath, report_base_dir):
    """Read pipeline_report.json and parse_diagnostics.json for coverage stats.

    Returns (step_pct, parse_pct) where each may be None if not available.
    """
    report_base = report_base_dir / f"{filepath.name}.report"
    step_pct = parse_pct = None

    pr = report_base / "pipeline_report.json"
    if pr.exists():
        try:
            data = json.loads(pr.read_text(encoding='utf-8'))
            steps = data.get("steps", [])
            total = len(steps)
            passed = sum(1 for s in steps if s.get("status") == "success")
            if total:
                step_pct = int(passed * 100 / total)
        except Exception:
            pass

    pd = report_base / "parse_diagnostics.json"
    if pd.exists():
        try:
            data = json.loads(pd.read_text(encoding='utf-8'))
            parse_pct = data.get("coverage_percentage")
        except Exception:
            pass

    return step_pct, parse_pct

# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------

def run_analysis(filepath, timeout_seconds, extra_flags, report_base_dir):
    """Runs analyze.py on a single file and returns result."""
    start_time = time.time()
    proc = None
    try:
        cmd = [
            sys.executable, "analyze.py",
            str(filepath),
            "--lenient",
            "--no-graphviz",
            "--skip-transpiler",
            "--no-mermaid",
        ] + extra_flags

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            # Send SIGTERM first so analyze.py can write pipeline_report.json,
            # then SIGKILL after 5 s to guarantee termination.
            try:
                proc.send_signal(signal.SIGTERM)
                time.sleep(5)
                proc.kill()
            except Exception:
                pass
            proc.wait()
            # Try to read the copybook manifest even on timeout — it's written by
            # setup_sandbox early in the pipeline, so it's usually already on disk.
            manifest_path = report_base_dir / f"{filepath.name}.report" / "copybook_manifest.json"
            copybooks = []
            if manifest_path.exists():
                try:
                    manifest_data = json.loads(manifest_path.read_text(encoding='utf-8'))
                    cbs = manifest_data.get("copybooks", {})
                    if isinstance(cbs, dict):
                        copybooks = [{"name": k, **v} for k, v in cbs.items()]
                    else:
                        copybooks = cbs
                except Exception:
                    pass
            return {
                "file": filepath.name,
                "success": False,
                "generated": False,
                "duration": timeout_seconds,
                "copybooks": copybooks,
                "error": "TIMEOUT",
            }

        duration = time.time() - start_time
        success = (proc.returncode == 0)

        # Check if knowledge base was actually generated (strict success)
        report_dir = report_base_dir / f"{filepath.name}.report" / "knowledge_base"
        generated = report_dir.exists()

        # Read the copybook manifest
        manifest_path = report_base_dir / f"{filepath.name}.report" / "copybook_manifest.json"
        copybooks = []
        if manifest_path.exists():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding='utf-8'))
                cbs = manifest_data.get("copybooks", {})
                if isinstance(cbs, dict):
                    copybooks = [{"name": k, **v} for k, v in cbs.items()]
                else:
                    copybooks = cbs
            except Exception:
                pass

        return {
            "file": filepath.name,
            "success": success,
            "generated": generated,
            "duration": duration,
            "copybooks": copybooks,
            "error": stderr if not success else "",
        }

    except Exception as e:
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        return {
            "file": filepath.name,
            "success": False,
            "generated": False,
            "duration": 0,
            "copybooks": [],
            "error": str(e),
        }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Batch COBOL analysis runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_runner.py smojol-test-code/
  python batch_runner.py my_cobol_dir/ --workers 2 --timeout 400
  python batch_runner.py my_cobol_dir/ --dry-run
""",
    )
    parser.add_argument("target_dir", nargs="?", default=TEST_ROOT,
                        help="Directory to scan for COBOL files (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=2,
                        help="Parallel JVM workers (default: 2; reduce if memory-constrained)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Per-file timeout in seconds (default: 600)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print files and COPY-stub counts without running analysis")
    parser.add_argument("--java-heap", default="2g",
                        help="JVM heap size passed to analyze.py (default: 2g; use 4g for 5k+ line programs)")
    args = parser.parse_args()

    target_dir = Path(args.target_dir)
    if not target_dir.exists():
        print(f"Directory not found: {target_dir}")
        sys.exit(1)

    report_base_dir = Path("out/report")

    print(f"Scanning for COBOL files in {target_dir}...")
    seen = set()
    files = []
    for p in (list(target_dir.rglob("*.cbl"))
              + list(target_dir.rglob("*.CBL"))
              + list(target_dir.rglob("*.cob"))):
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            files.append(p)
    total_files = len(files)
    print(f"Found {total_files} files.")

    # ---- Dry-run mode -------------------------------------------------------
    if args.dry_run:
        print(f"\n{'Filename':<45} {'Size KB':>8}  {'COPY refs':>10}")
        print("-" * 68)
        for f in sorted(files):
            size_kb = f.stat().st_size / 1024
            names = _scan_copy_names(f)
            print(f"  {f.name:<43} {size_kb:>7.1f}KB  {len(names):>6} ({', '.join(names[:4])}"
                  + (f"... +{len(names)-4} more" if len(names) > 4 else "") + ")")
        return

    # ---- Helpers ----------------------------------------------------------------
    def _print_result(res, filepath, label, total):
        status_color = "\033[92mPASS\033[0m" if res["success"] else "\033[91mFAIL\033[0m"
        gen_mark = "✅" if res["generated"] else "❌"

        step_pct, parse_pct = _read_analysis_coverage(filepath, report_base_dir)
        cov_parts = []
        if step_pct is not None:
            cov_parts.append(f"steps:{step_pct}%")
        if parse_pct is not None:
            cov_parts.append(f"parse:{parse_pct:.1f}%")
        cov_str = " | " + " ".join(cov_parts) if cov_parts else ""

        cpy_found, cpy_total = _copybook_ratio(filepath, res["copybooks"], report_base_dir)
        if cpy_total is not None:
            cpy_str = f" | CPY:{cpy_found if cpy_found is not None else '?'}/{cpy_total}"
        else:
            cpy_str = ""

        print(f"{label:<10} {res['file']:<34} | {status_color:<19} | {res['duration']:>5.2f}s | {gen_mark}{cov_str}{cpy_str}")

        if not res["success"]:
            with open(f"batch_error_{res['file']}.log", "w") as fh:
                fh.write(res["error"])

    # ---- Pass 1: parallel run -----------------------------------------------
    retry_timeout = max(args.timeout * 2, 1200)
    print(f"Workers: {args.workers} | Timeout: {args.timeout}s | Heap: {args.java_heap} | --skip-transpiler: ON")
    print(f"Auto-retry: timed-out files will be retried serially (timeout={retry_timeout}s, heap=4g)")
    print("-" * 75)
    print(f"{'[#]':<10} {'Filename':<34} | {'Status':<10} | {'Time':>6} | {'KB':>3} | {'Coverage'}")
    print("-" * 75)

    results = []
    processed_count = 0
    file_lookup = {f.name: f for f in files}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        extra = [f"--java-heap={args.java_heap}"]
        future_to_file = {
            executor.submit(run_analysis, f, args.timeout, extra, report_base_dir): f
            for f in files
        }

        for future in as_completed(future_to_file):
            processed_count += 1
            res = future.result()
            results.append(res)
            filepath = future_to_file[future]
            _print_result(res, filepath, f"[{processed_count}/{total_files}]", total_files)

    # ---- Pass 2: serial retry for timeouts ----------------------------------
    timed_out = [r for r in results if r["error"] == "TIMEOUT"]
    if timed_out:
        print("-" * 75)
        print(f"Pass 2 — retrying {len(timed_out)} timed-out file(s) serially "
              f"(timeout={retry_timeout}s, heap=4g) ...")
        print("-" * 75)
        retry_extra = ["--java-heap=4g"]
        for i, r in enumerate(timed_out, 1):
            filepath = file_lookup[r["file"]]
            retry_res = run_analysis(filepath, retry_timeout, retry_extra, report_base_dir)
            # Replace original result
            results = [x for x in results if x["file"] != retry_res["file"]]
            results.append(retry_res)
            _print_result(retry_res, filepath, f"[R{i}/{len(timed_out)}]", len(timed_out))

    print("-" * 75)
    passed = sum(1 for r in results if r["success"])
    generated = sum(1 for r in results if r["generated"])
    failed = total_files - passed

    print(f"Batch Complete.")
    print(f"Total: {total_files} | Passed: {passed} | Failed: {failed} | KB Generated: {generated}")
    print("\nSee batch_error_*.log files for failure details.")

    print("\nWriting Consolidated Summary Report to batch_summary_report.json...")

    report_data = {
        "summary": {
            "total_files": total_files,
            "passed": passed,
            "failed": failed,
            "generated": generated,
            "workers": args.workers,
            "timeout_seconds": args.timeout,
        },
        "details": [],
    }

    for r in results:
        cbs = r["copybooks"]
        if cbs and isinstance(cbs[0], dict):
            # Only include copybooks actually referenced by this program
            fp = file_lookup.get(r["file"])
            needed = set(_scan_copy_names(fp)) if fp else set()
            if needed:
                found_cpy = [c["name"] for c in cbs if c["name"].upper() in needed and not c.get("is_stub")]
                missing_cpy = [c["name"] for c in cbs if c["name"].upper() in needed and c.get("is_stub")]
            else:
                found_cpy = [c["name"] for c in cbs if not c.get("is_stub")]
                missing_cpy = [c["name"] for c in cbs if c.get("is_stub")]
        else:
            found_cpy = []
            missing_cpy = []
            needed = set()

        report_data["details"].append({
            "file": r["file"],
            "status": "PASS" if r["success"] else "FAIL",
            "duration_seconds": round(r["duration"], 2),
            "kb_generated": r["generated"],
            "copybooks_needed": len(needed) if needed else None,
            "copybooks_found": found_cpy,
            "copybooks_missing": missing_cpy,
            "error_snippet": r["error"][:500] if r["error"] else None,
        })

    with open("batch_summary_report.json", "w") as f:
        json.dump(report_data, f, indent=2)

    print("Done. Check batch_summary_report.json for details per program.")


if __name__ == "__main__":
    main()
