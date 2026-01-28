import os
import subprocess
import glob
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Configuration
TEST_ROOT = "che-che4z-lsp-for-cobol-integration/tests/test_files"
MAX_WORKERS = 4  # Adjust based on CPU
TIMEOUT_SECONDS = 60

class Counters:
    passed = 0
    failed = 0
    generated = 0
    total = 0

def run_analysis(filepath):
    """Runs analyze.py on a single file and returns result."""
    start_time = time.time()
    try:
        # Run with --lenient and --ignore-copybooks to focus on parsing stability
        # We assume for batch testing we don't have all system copybooks set up
        cmd = [
            sys.executable, "analyze.py", 
            str(filepath), 
            "--lenient", 
            "--ignore-copybooks" 
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
        
        # Check if HTML was actually generated (strict success)
        report_dir = Path("out/report") / f"{filepath.name}.report" / "visualize_graphs.html"
        generated = report_dir.exists()
        
        return {
            "file": filepath.name,
            "success": success,
            "generated": generated,
            "duration": duration,
            "error": result.stderr if not success else ""
        }
        
    except subprocess.TimeoutExpired:
        return {
            "file": filepath.name,
            "success": False,
            "generated": False,
            "duration": TIMEOUT_SECONDS,
            "error": "TIMEOUT"
        }
    except Exception as e:
        return {
            "file": filepath.name,
            "success": False,
            "generated": False,
            "duration": 0,
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
    
    # Filter out files that are clearly copybooks (if any naming convention exists) or just small snippets if needed
    # For now, take all.
    
    total_files = len(files)
    print(f"Found {total_files} files. Starting batch analysis with {MAX_WORKERS} workers...")
    print("-" * 60)
    print(f"{'Filename':<30} | {'Status':<10} | {'Time':<6} | {'Generated'}")
    print("-" * 60)

    results = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {executor.submit(run_analysis, f): f for f in files}
        
        for future in as_completed(future_to_file):
            res = future.result()
            results.append(res)
            
            status_color = "\033[92mPASS\033[0m" if res['success'] else "\033[91mFAIL\033[0m"
            gen_mark = "✅" if res['generated'] else "❌"
            
            print(f"{res['file']:<30} | {status_color:<19} | {res['duration']:>5.2f}s | {gen_mark}")
            
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
    print(f"HTML Generated:  {generated}")
    print("\nSee batch_error_*.log files for failure details.")

if __name__ == "__main__":
    main()
