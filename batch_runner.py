import os
import subprocess
import glob
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Configuration
TEST_ROOT = "che-che4z-lsp-for-cobol-integration/tests/test_files"
MAX_WORKERS = 4  # Adjust based on CPU
TIMEOUT_SECONDS = 300 # Increased to 5 mins mostly for nist85

class Counters:
    passed = 0
    failed = 0
    generated = 0
    total = 0

def run_analysis(filepath):
    """Runs analyze.py on a single file and returns result."""
    start_time = time.time()
    try:
        # Note: Removing --ignore-copybooks so copybook resolution happens
        cmd = [
            sys.executable, "analyze.py",
            str(filepath),
            "--lenient",
            "--no-graphviz",
        ]
        
        # Capture output to avoid console spam
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=TIMEOUT_SECONDS
        )
        
        duration = time.time() - start_time
        success = (result.returncode == 0)
        
        # Check if knowledge base was actually generated (strict success)
        report_dir = Path("out/report") / f"{filepath.name}.report" / "knowledge_base"
        generated = report_dir.exists()
        
        # Read the copybook manifest
        manifest_path = Path("out/report") / f"{filepath.name}.report" / "copybook_manifest.json"
        copybooks = []
        if manifest_path.exists():
            try:
                with open(manifest_path, "r") as f:
                    manifest_data = json.load(f)
                    copybooks = manifest_data.get("copybooks", [])
            except json.JSONDecodeError:
                pass
        
        return {
            "file": filepath.name,
            "success": success,
            "generated": generated,
            "duration": duration,
            "copybooks": copybooks,
            "error": result.stderr if not success else ""
        }
        
    except subprocess.TimeoutExpired:
        return {
            "file": filepath.name,
            "success": False,
            "generated": False,
            "duration": TIMEOUT_SECONDS,
            "copybooks": [],
            "error": "TIMEOUT"
        }
    except Exception as e:
        return {
            "file": filepath.name,
            "success": False,
            "generated": False,
            "duration": 0,
            "copybooks": [],
            "error": str(e)
        }

def main():
    if len(sys.argv) > 1:
        target_dir = Path(sys.argv[1])
    else:
        target_dir = Path(TEST_ROOT)

    if not target_dir.exists():
        print(f"Directory not found: {target_dir}")
        sys.exit(1)

    print(f"Scanning for COBOL files in {target_dir}...")
    # Find all .cbl, .cob, .CBL files recursively
    files = list(target_dir.rglob("*.cbl")) + list(target_dir.rglob("*.CBL")) + list(target_dir.rglob("*.cob"))
    
    total_files = len(files)
    print(f"Found {total_files} files. Starting batch analysis with {MAX_WORKERS} workers...")
    print("-" * 60)
    print(f"{'[#]':<10} {'Filename':<30} | {'Status':<10} | {'Time':<6} | {'Generated'}")
    print("-" * 65)

    results = []
    
    processed_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {executor.submit(run_analysis, f): f for f in files}
        
        for future in as_completed(future_to_file):
            processed_count += 1
            res = future.result()
            results.append(res)
            
            status_color = "\033[92mPASS\033[0m" if res['success'] else "\033[91mFAIL\033[0m"
            gen_mark = "✅" if res['generated'] else "❌"
            
            prog = f"[{processed_count}/{total_files}]"
            print(f"{prog:<10} {res['file']:<30} | {status_color:<19} | {res['duration']:>5.2f}s | {gen_mark}")
            
            if not res['success']:
                # Save error log
                with open(f"batch_error_{res['file']}.log", "w") as f:
                    f.write(res['error'])
    
    print("-" * 60)
    passed = sum(1 for r in results if r['success'])
    generated = sum(1 for r in results if r['generated'])
    failed = total_files - passed
    
    print(f"Batch Complete.")
    print(f"Total: {total_files}")
    print(f"Passed (Exit 0): {passed}")
    print(f"Failed (Exit 1): {failed}")
    print(f"Knowledge Base Generated: {generated}")
    print("\nSee batch_error_*.log files for failure details.")
    
    print("\nWriting Consolidated Summary Report to batch_summary_report.json...")
    
    report_data = {
        "summary": {
            "total_files": total_files,
            "passed": passed,
            "failed": failed,
            "generated": generated
        },
        "details": []
    }
    
    for r in results:
        found_cpy = [c['name'] for c in r['copybooks'] if c.get('status') == 'resolved']
        missing_cpy = [c['name'] for c in r['copybooks'] if c.get('status') == 'stubbed']
        
        report_data["details"].append({
            "file": r["file"],
            "status": "PASS" if r["success"] else "FAIL",
            "duration_seconds": round(r["duration"], 2),
            "kb_generated": r["generated"],
            "copybooks_found": found_cpy,
            "copybooks_missing": missing_cpy,
            "error_snippet": r["error"][:500] if r["error"] else None
        })
        
    with open("batch_summary_report.json", "w") as f:
        json.dump(report_data, f, indent=2)
        
    print("Done. Check batch_summary_report.json for details per program.")

if __name__ == "__main__":
    main()
