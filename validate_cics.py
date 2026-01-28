import os
import subprocess
import glob
import sys
import time
from pathlib import Path

# Config
SMOJOL_JAR = "/home/eri/workspace/sapienza/Master-Thesis/cobol-rekt/smojol-cli/target/smojol-cli.jar"
SRC_DIR = "/home/eri/workspace/sapienza/Master-Thesis/cobol-rekt/cics-genapp/base/src/cobol"
COPYBOOK_DIR = "../copybook"
REPORT_ROOT = "/home/eri/workspace/sapienza/Master-Thesis/cobol-rekt/out/report_batch"

def run_validation(cbl_file):
    filename = os.path.basename(cbl_file)
    print(f"Processing {filename}...")
    
    report_dir = os.path.join(REPORT_ROOT, filename)
    
    cmd = [
        "java", "-jar", SMOJOL_JAR, "run", filename,
        "--commands=WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES",
        "--srcDir", ".",
        "--copyBooksDir", COPYBOOK_DIR,
        "--dialect", "COBOL",
        "--reportDir", report_dir,
        "--generation=PROGRAM"
    ]
    
    start = time.time()
    try:
        # Run in the cobol directory so relative paths work
        result = subprocess.run(
            cmd,
            cwd=SRC_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )
        duration = time.time() - start
        
        if result.returncode == 0:
            print(f"✅ {filename} [PASS] ({duration:.2f}s)")
            return True, filename, duration, ""
        else:
            print(f"❌ {filename} [FAIL] ({duration:.2f}s)")
            # Return stderr for logging
            return False, filename, duration, result.stderr
            
    except subprocess.TimeoutExpired:
        print(f"⏰ {filename} [TIMEOUT]")
        return False, filename, 60, "Timed out"
    except Exception as e:
        print(f"💥 {filename} [ERROR] {e}")
        return False, filename, 0, str(e)

def main():
    if not os.path.exists(SRC_DIR):
        print(f"Directory not found: {SRC_DIR}")
        sys.exit(1)
        
    cbl_files = sorted(glob.glob(os.path.join(SRC_DIR, "*.cbl")))
    print(f"Found {len(cbl_files)} COBOL files in {SRC_DIR}")
    
    passed = 0
    failed = 0
    results = []
    
    os.makedirs(REPORT_ROOT, exist_ok=True)
    
    for cbl in cbl_files:
        success, name, duration, error = run_validation(cbl)
        if success:
            passed += 1
        else:
            failed += 1
            # Write error log
            with open(os.path.join(REPORT_ROOT, f"{name}.error.log"), "w") as f:
                f.write(error)
                
    print("-" * 60)
    print(f"Batch Processing Complete")
    print(f"Total: {len(cbl_files)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Logs in: {REPORT_ROOT}")

if __name__ == "__main__":
    main()
