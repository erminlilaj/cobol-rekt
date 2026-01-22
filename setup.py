import os
import subprocess
import sys
import shutil

# ANSI colors for terminal output
class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    NC = '\033[0m' # No Color

    @staticmethod
    def print_green(msg):
        print(f"{Colors.GREEN}{msg}{Colors.NC}")

    @staticmethod
    def print_red(msg):
        print(f"{Colors.RED}{msg}{Colors.NC}")

def main():
    # Enable ANSI escape sequences on Windows if possible (for colors)
    os.system('')

    Colors.print_green("Starting Cobol-REKT via Docker...")

    # Check for Docker
    try:
        subprocess.run(["docker", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        Colors.print_red("Docker is not installed or not in PATH. Please install Docker Desktop or Engine.")
        sys.exit(1)

    # Create necessary directories
    dirs_to_create = ["projects", "reports", "neo4j_data", "db"]
    for directory in dirs_to_create:
        os.makedirs(directory, exist_ok=True)
    
    # Check if projects dir is empty
    if not os.listdir("projects"):
        Colors.print_green("Note: 'projects' directory is empty. Place your COBOL files there to analyze them.")

    # Initialize git submodules
    if os.path.exists(".gitmodules"):
        Colors.print_green("Initializing git submodules...")
        try:
            subprocess.run(["git", "submodule", "update", "--init", "--recursive"], check=True)
        except subprocess.CalledProcessError:
            Colors.print_red("Failed to initialize git submodules.")
            sys.exit(1)

    Colors.print_green("Building and starting services...")
    print("Use Ctrl+C to stop the logs (containers will keep running).")
    print("To stop containers, run: docker-compose down")

    # Run docker-compose
    try:
        # Try 'docker-compose' first (older style/standalone)
        subprocess.run(["docker-compose", "up", "--build"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            # Fallback to 'docker compose' (newer plugin style)
            subprocess.run(["docker", "compose", "up", "--build"], check=True)
        except subprocess.CalledProcessError:
             Colors.print_red("Failed to run docker-compose.")
             sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
