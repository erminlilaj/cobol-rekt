# Setup Guide for Cobol-REKT

This guide provides instructions to set up, build, and run the cobol-rekt project on Windows.

## 🐳 Option 1: Docker Setup (Recommended)

This is the easiest way to run the project as it handles dependencies automatically.

### Prerequisites
- **Docker Desktop** installed and running.

### Steps
1. Open a terminal (PowerShell or Command Prompt) in the project root.
2. Run the Python setup script:
   ```bash
   python setup.py
   ```
   *(This script initializes the project and runs `docker-compose up --build`)*

3. To stop the application:
   - Press `Ctrl+C` to stop watching logs.
   - Run `docker-compose down` to stop the containers.

---

## 💻 Option 2: Manual Local Setup (Windows)

If you prefer to run tools locally without Docker, follow these steps.

### 1. Prerequisites
Ensure you have the following tools installed and added to your system PATH.

*   **Java Development Kit (JDK)**
    *   **Version:** JDK 21 or higher (JDK 22 is recommended; users have reported issues with JDK 23).
    *   **Verify:** Run `java -version` in your terminal.
*   **Maven**
    *   **Version:** 3.6 or higher.
    *   **Verify:** Run `mvn -version`.
*   **Graphviz (for Flowcharts)**
    *   **Required:** For generating flowcharts using `dot`.
    *   **Installation:** Download the installer from the Graphviz website.
    *   **Configuration:** Ensure the `bin` directory of your Graphviz installation is in your system PATH.
    *   **Verify:** Run `dot -V`.
*   **Python**
    *   **Required:** For additional analysis and LLM-based tasks.
    *   **Verify:** Run `python --version` or `python3 --version`.
*   **Neo4j (Optional but Recommended)**
    *   **Required:** For graph database capabilities (`FLOW_TO_NEO4J`).
    *   **Plugins:** Install APOC and GDS (Graph Data Science) plugins.
    *   **Desktop:** Neo4j Desktop works well for local development.

### 2. Initial Setup
#### Submodules
If you have already cloned the repository, ensure all submodules are fetched and updated. This project relies on `che-che4z-lsp-for-cobol` and `mojo-common`.

Open PowerShell or Command Prompt in the project root:

```bash
git submodule update --init --recursive
```

### 3. Building the Project
The project is built using Maven.

#### Standard Build
Run the following command in the project root:

```bash
mvn clean verify
```

#### Skip Build Checks (Faster)
If you encounter checkstyle errors or want to skip tests to speed up the build:

```bash
mvn clean verify "-Dcheckstyle.skip=true" "-Dmaven.test.skip=true"
```
Upon success, this will generate the executable JARs in the target directories of the respective modules (e.g., `smojol-cli/target/smojol-cli.jar`).

### 4. Setting up Python Environment
If you plan to use the Python-based analysis tools:

1.  Navigate to the python directory:
    ```bash
    cd smojol_python
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### 5. Running the CLI
You can now run the tool using the compiled JAR.

#### Basic Validation Command:
```bash
java -jar smojol-cli/target/smojol-cli.jar validate -s smojol-test-code/ test-exp.cbl
```

#### Full Analysis Run (Example):
To generate flowcharts, CFG, and ASTs for a test program:

```bash
java -jar smojol-cli/target/smojol-cli.jar run test-exp.cbl ^
  --commands="BUILD_BASE_ANALYSIS DRAW_FLOWCHART WRITE_CFG" ^
  --srcDir "smojol-test-code" ^
  --copyBooksDir "smojol-test-code" ^
  --dialectJarPath "che-che4z-lsp-for-cobol-integration/server/dialect-idms/target/dialect-idms.jar" ^
  --reportDir "out/report" ^
  --generation=PROGRAM
```
> **TIP:** Use `^` in cmd or backtick `` ` `` in PowerShell for multi-line commands.

### 6. Demo App (Optional)
To run the web-based demo app, you need valid node and npm installations, plus sqlite3.

#### Frontend:
```bash
cd smojol-app/cobol-lekt
npm install
npm run serve
```

#### Backend (API):
In a new terminal window, run the API server. You must set environment variables for the database.

**PowerShell:**
```powershell
$env:PORT="7070"
$env:DATABASE_URL="jdbc:sqlite:path/to/your/db/file"
java -jar smojol-api/target/smojol-api.jar
```

### Troubleshooting
*   **Git submodules:** If the build fails due to missing classes, try re-running `git submodule update --init --recursive --force`.
*   **Java Version:** Ensure `JAVA_HOME` points to your JDK 21+ installation.
*   **Graphviz:** If flowchart generation fails, ensure `dot` is accessible from the command line.
