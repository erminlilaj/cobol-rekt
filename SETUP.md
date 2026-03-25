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

---

## Analysis Commands Reference

All Python commands below use `python` on Windows. Replace with `python3` on Linux/macOS if needed.

---

### 1. COBOL Analysis Pipeline (`analyze.py`)

Runs the full reverse-engineering pipeline: parsing, CFG construction, data structures, Mermaid diagrams, Graphviz export, variable analysis, dependency extraction, comments, and knowledge base.

```
python analyze.py <cobol_file> [options]
```

**Options:**

| Option | Description |
|--------|-------------|
| *(none)* | Standard analysis with sandbox, Graphviz, comment enrichment |
| `--no-graphviz` | Skip Graphviz export and LLM input text generation (faster) |
| `--lenient` | Continue despite parse errors |
| `--ignore-copybooks` | Stub all copybooks immediately without resolving |
| `--no-sandbox` | Operate on source files in-place (no temp directory) |
| `--no-comment-enrichment` | Skip Ollama-based comment translation |

**Examples (Windows):**

```powershell
python analyze.py path\to\TEST.CBL
python analyze.py path\to\TEST.CBL --no-graphviz
python analyze.py path\to\TEST.CBL --lenient --ignore-copybooks
```

**Expected output:** `out\report\TEST.CBL.report\`

```
TEST.CBL.report\
  ast\cobol-TEST.CBL.json              # Raw ANTLR parse tree
  flow_ast\flow-ast-TEST.CBL.json      # Semantic Flow AST (47 node types)
  cfg\cfg-TEST.CBL.json                # Control Flow Graph (nodes + edges)
  data_structures\TEST.CBL-data.json   # Variable declarations and hierarchy
  unified_model\TEST.CBL-unified.json  # Merged AST + CFG + data structures
  graphviz\*.dot                       # Graphviz DOT files (unless --no-graphviz)
  llm_input\*.txt                      # Plain-text graph representations for LLM
  mermaid\
    SECTION-*.md                       # Per-section Mermaid flowcharts
    program_flow.md                    # Full program CFG as Mermaid
    data_dependencies.md               # Data flow diagram
  comments.json                        # Extracted COBOL column-7 comments
  variable_values.json                 # Static literal assignments per variable
  knowledge_base\
    00_Executive_Summary.md            # Metrics: nodes, edges, complexity
    01_Logic_Narrative.md              # Paragraph-by-paragraph walkthrough
    02_Data_Dictionary.md              # Variable tables with PIC clauses
    03_Dependencies.yaml               # SQL tables, CALL targets, CICS commands
```

**What can go wrong:**

- **Parse failure (Step 1):** Missing or broken copybooks. Use `--ignore-copybooks` or place copybooks in the same directory as the source.
- **Step 2 non-fatal failure:** `BUILD_TRANSPILER_FLOWGRAPH` fails on unresolvable GOTOs. `unified_model\` will be missing but other outputs still generated.
- **No Graphviz output:** If `--no-graphviz` is set, `graphviz\` and `llm_input\` will be empty.
- **Comment enrichment failure:** If Ollama is not running, enrichment is skipped with a warning. Use `--no-comment-enrichment` to suppress.

---

### 2. JCL Parsing (`jcl_parser.py`)

Parses an IBM JCL file and extracts structured job, step, and dataset information.

```
python jcl_parser.py <jcl_file> [--output-dir DIR] [--verbose]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `jcl_file` | *(required)* | Path to the JCL file to parse |
| `--output-dir` | `out\report` | Root output directory |
| `--verbose` | | Print progress messages |

**Examples:**

```powershell
python jcl_parser.py path\to\TEST.jcl --verbose
python jcl_parser.py path\to\TEST.jcl --output-dir my_reports
```

**Expected output:** `out\report\TEST.jcl.report\`

```
TEST.jcl.report\
  jcl_summary.json       # Job metadata: name, step count, programs invoked,
                          # datasets read/written, conditional flow, unresolved symbols
  jcl_steps.json          # Array of step objects: step name, program/PROC, condition,
                          # PARM, DD statements with DSN, DISP, access classification
  jcl_datasets.json       # Dataset index: which steps read/write each dataset
```

**What to expect:**

- `programs_invoked` lists only user programs (system utilities like IDCAMS, IEFBR14 are filtered out)
- DSN can be a string, or a dict (`{"dsn": "...", "temporary": true}` for `&&TEMP`, `{"dsn": "...", "member": "..."}` for PDS members)
- Temporary datasets (`&&NAME`) are excluded from `jcl_datasets.json`
- Instream PROCs (PROC/PEND) are expanded into individual steps; cataloged PROCs remain as-is
- Symbol resolution: `&SYMBOL` references in DSN/PGM/PARM are resolved from SET statements and PROC overrides
- Unresolved symbols are listed in `unresolved_symbols`

---

### 3. JCL-COBOL Relationship Report (`jcl_cobol_report.py`)

Generates a detailed report showing how a JCL job relates to the COBOL programs it invokes. Cross-references JCL steps with COBOL program internals (complexity, SQL, CALLS, CICS).

```
python jcl_cobol_report.py <jcl_input> [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `jcl_input` | *(required)* | Path to JCL report directory OR raw `.jcl` file |
| `--report-dir` | `out\report` | Report dir to search for COBOL reports (repeatable) |
| `--cobol-dir` | | Directory with COBOL sources (`.cbl`/`.cob`). Auto-analyzes missing programs. Repeatable. |
| `--copybooks-dir` | | Directory with copybook files (`.cpy`). Used when auto-analyzing. If not set, `--cobol-dir` is used. |
| `--output-dir` | `out\report` | Root output directory for reports |
| `--verbose`, `-v` | | Print progress |

**Examples:**

```powershell
# From a pre-existing JCL report directory
python jcl_cobol_report.py out\report\TEST.jcl.report -v

# From a raw JCL file (auto-parses first)
python jcl_cobol_report.py path\to\TEST.jcl -v

# With COBOL sources in the same directory (auto-analyzes missing programs)
python jcl_cobol_report.py path\to\TEST.jcl --cobol-dir path\to\sources -v

# COBOL sources + copybooks in separate directories
python jcl_cobol_report.py path\to\TEST.jcl ^
  --cobol-dir path\to\cobol_sources ^
  --copybooks-dir path\to\copybooks -v

# Multiple source directories
python jcl_cobol_report.py path\to\TEST.jcl ^
  --cobol-dir dir1 --cobol-dir dir2 -v
```

**Expected output** (added to `out\report\TEST.jcl.report\`):

```
TEST.jcl.report\
  jcl_cobol_relationship.json     # Machine-readable relationship model
  jcl_cobol_relationship.md       # Human-readable Markdown report
  mermaid\
    jcl_cobol_flow.md             # Mermaid diagram (steps + datasets + CALL edges)
  chunks\
    TEST__jcl_cobol_overview.json           # Job-level relationship summary
    TEST__step_relationship__*.json         # Per-step COBOL cross-reference
    chunks_manifest.json                    # Updated manifest
```

**Markdown report sections:**

1. **Job Overview** -- name, steps, programs, conditional flow, region, class
2. **Execution Flow Diagram** -- reference to Mermaid file
3. **Step-by-Step Breakdown** -- per step: program status, complexity, DD tables, SQL/CALL/CICS, call chain
4. **Analysis Health Check** -- coverage score (e.g., "2/3 programs analyzed (67%)"), per-program artifact status, quality flags, actionable recommendations
5. **Dataset Flow Table** -- external inputs, inter-step flows, final outputs, temporaries
6. **Transitive Call Chains** -- full chains for all invoked programs
7. **Data Contract Summary** -- per-step consumes/produces table
8. **Analysis Log** -- full `[INFO]`/`[FOUND]`/`[MISSING]`/`[WARN]` log

**Console logging (with `-v`):**

```
[INFO]    Loading JCL artifacts from TEST.jcl.report...
[INFO]    Job TEST: 5 steps, 2 user programs (excluding 3 system utilities)
[FOUND]   PROGA -> out\report\PROGA.CBL.report\ (knowledge_base: OK, cfg: OK)
[MISSING] PROGB -> no report directory found
[WARN]    PROGC -> out\report\PROGC.CBL.report (missing: 03_Dependencies.yaml)
[INFO]    Dataset flow: 3 external inputs, 2 inter-step flows, 1 final outputs
```

**Quality flags detected:**

- `no SQL statements found` -- no database access
- `no CALL targets found (leaf program)` -- does not call other programs
- `no CICS commands` -- not a CICS program
- `empty CFG (0 nodes)` -- parse may have failed
- `high complexity (>50)` -- flag for review
- `03_Dependencies.yaml missing` -- Step 2 of analyze.py likely failed

**What can go wrong:**

- **0% coverage:** All invoked programs missing from `out\report\`. Use `--cobol-dir` to auto-analyze them.
- **Partial coverage:** Some programs analyzed, some missing. Report shows both and recommends which to analyze.
- **Auto-analysis failures:** When using `--cobol-dir`, `analyze.py` may fail on some programs. Warnings are printed; the relationship report still generates with available data.

---

### 4. Knowledge Base Generation (`knowledge_base_builder.py`)

Generates 4 deterministic knowledge base documents from COBOL analysis JSON outputs. Called automatically by `analyze.py` (Step 7), but can be run standalone.

```
python knowledge_base_builder.py <report_dir> --program <program_name>
```

**Example:**

```powershell
python knowledge_base_builder.py out\report\TEST.CBL.report --program TEST.CBL
```

**Expected output:** `out\report\TEST.CBL.report\knowledge_base\`

| File | Content |
|------|---------|
| `00_Executive_Summary.md` | Metrics table (CFG nodes, edges, variables, McCabe complexity), node type distribution |
| `01_Logic_Narrative.md` | Paragraph-by-paragraph walkthrough with comments as blockquotes |
| `02_Data_Dictionary.md` | Variable tables per section (WORKING-STORAGE, LINKAGE) with PIC clauses |
| `03_Dependencies.yaml` | SQL tables (read/updated), CALL targets, CICS commands |

---

### 5. Chunk Pipeline for RAG (`chunk_pipeline.py`)

Splits report artifacts into fine-grained retrieval units for RAG. Works with both COBOL and JCL reports.

```
python chunk_pipeline.py <report_dir> [--verbose]
```

**Examples:**

```powershell
python chunk_pipeline.py out\report\TEST.CBL.report --verbose
python chunk_pipeline.py out\report\TEST.jcl.report --verbose
```

**Expected output:** `out\report\TEST.CBL.report\chunks\` (or `TEST.jcl.report\chunks\`)

**COBOL chunk types:**

| File Pattern | Type | Count |
|-------------|------|-------|
| `*__program_summary.json` | `program_summary` | 1 per program |
| `*__dependencies.json` | `dependencies` | 1 per program |
| `*__paragraph__*.json` | `paragraph_logic` | 1 per paragraph |
| `*__variable_group__*.json` | `variable_group` | 1 per level-01 record |

**JCL chunk types:**

| File Pattern | Type | Count |
|-------------|------|-------|
| `*__job_flow.json` | `job_flow` | 1 per job |
| `*__step_detail__*.json` | `step_detail` | 1 per step |

Each chunk is a JSON file with `{"text": "...", "metadata": {...}}`. Chunks under 20 tokens are merged; chunks over 512 tokens are split with overlap.

---

### 6. Cross-Program Call Graph (`build_call_graph.py`)

Aggregates COBOL CALL and JCL EXECUTES relationships across all reports into a unified graph.

```
python build_call_graph.py [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--report-dir` | `out\report` | Report directory to scan (repeatable) |
| `--output` | `out\cross_program_calls.json` | Output file path |
| `--verbose`, `-v` | | Print progress |
| `--no-update-chunks` | | Skip updating program_summary chunks |

**Examples:**

```powershell
python build_call_graph.py -v
python build_call_graph.py --report-dir dir1 --report-dir dir2 -v
```

**Expected output:** `out\cross_program_calls.json`

Contains: programs (with calls, called_by, entry_type), edges (CALLS/EXECUTES), JCL job metadata, external targets, and summary counts.

Entry types: `jcl_only` (only from JCL), `call_only` (only from COBOL), `both`, `none`.

---

### 7. Batch Analysis (`batch_runner.py`)

Runs `analyze.py` in parallel across all COBOL files in a directory.

```
python batch_runner.py [directory]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `directory` | `smojol-test-code` | Directory to scan for `.cbl`/`.CBL`/`.cob` files (recursive) |

**Example:**

```powershell
python batch_runner.py path\to\cobol_sources\
```

Runs up to 4 programs in parallel. Each creates its own `.report\` directory. Failures logged to `batch_error_*.log`.

---

### 8. HTML Viewer (`generate_viewer.py`)

Generates a self-contained interactive HTML viewer from Mermaid diagrams. Not called automatically by `analyze.py`.

```
python generate_viewer.py [options]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--mermaid-dir` | Directory containing Mermaid `.md` files |
| `--output` | Output HTML file path |
| `--title` | Report title |
| `--source` | Path to COBOL source file for split-pane view |
| `--code` | Enable split-pane code view with interactive highlighting |
| `--graphviz` | Use Graphviz SVG outputs instead of Mermaid |

**Example:**

```powershell
python generate_viewer.py ^
  --mermaid-dir out\report\TEST.CBL.report\mermaid ^
  --output out\report\TEST.CBL.report\visualize_graphs.html ^
  --title TEST.CBL --source path\to\TEST.CBL --code
```

Open the output HTML in any browser. No server required.

---

### 9. LLM Documentation (`run_llm_documentation.py`)

Sends graph-to-text output to Ollama for documentation generation. Requires Ollama running locally.

```
python run_llm_documentation.py <input_dir> [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `input_dir` | *(required)* | Directory containing `.txt` files from `llm_input\` |
| `--output-dir` | auto-inferred | Directory to save generated markdown |
| `--model` | `granite-code:8b` | Ollama model to use |
| `--port` | `11434` | Ollama API port |
| `--prompt-file` | | Path to a custom system prompt file |
| `--full-prompt` | | Use full 6-section prompt instead of trimmed 3-section default |
| `--verbose` | | Enable verbose logging |

**Example:**

```powershell
# Requires: ollama serve (running) + ollama pull granite-code:8b
python run_llm_documentation.py out\report\TEST.CBL.report\llm_input --verbose
```

Output is non-deterministic. Treat as a draft for human review.

---

### 10. Comment Enrichment (`comment_enricher.py`)

Translates and categorizes Italian COBOL comments via Ollama. Called automatically by `analyze.py` unless `--no-comment-enrichment` is set.

```
python comment_enricher.py <comments_json> [options]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `comments_json` | *(required)* | Path to `comments.json` |
| `--model` | `granite-code:8b` | Ollama model |
| `--port` | `11434` | Ollama port |
| `--auto-model` | | Auto-select smallest available Ollama model |
| `--verbose` | | Verbose logging |

**Example:**

```powershell
python comment_enricher.py out\report\TEST.CBL.report\comments.json --verbose
```

Creates `comments_enriched.json` alongside the input file with English translations and categories.

---

## Recommended Workflows

### Single COBOL program

```powershell
REM 1. Analyze
python analyze.py path\to\TEST.CBL

REM 2. Generate chunks for RAG
python chunk_pipeline.py out\report\TEST.CBL.report --verbose

REM 3. Generate HTML viewer
python generate_viewer.py ^
  --mermaid-dir out\report\TEST.CBL.report\mermaid ^
  --output out\report\TEST.CBL.report\visualize_graphs.html ^
  --title TEST.CBL --source path\to\TEST.CBL --code

REM 4. (Optional) LLM documentation
python run_llm_documentation.py out\report\TEST.CBL.report\llm_input --verbose
```

### JCL + COBOL (same directory)

```powershell
REM 1. Parse JCL and auto-analyze referenced COBOL programs
python jcl_cobol_report.py path\to\TEST.jcl ^
  --cobol-dir path\to\sources ^
  --copybooks-dir path\to\copybooks -v

REM 2. Generate chunks for all reports
python chunk_pipeline.py out\report\TEST.CBL.report --verbose
python chunk_pipeline.py out\report\TEST.jcl.report --verbose

REM 3. Build cross-program call graph
python build_call_graph.py -v
```

### Full batch analysis

```powershell
REM 1. Analyze all COBOL files
python batch_runner.py path\to\cobol_sources\

REM 2. Parse all JCL files
for %%f in (path\to\jcl_sources\*.jcl) do (
  python jcl_parser.py "%%f" --verbose
)

REM 3. Generate chunks for all reports
for /D %%d in (out\report\*.report) do (
  python chunk_pipeline.py "%%d" --verbose
)

REM 4. Build cross-program call graph
python build_call_graph.py -v

REM 5. Generate JCL-COBOL relationship reports
for /D %%d in (out\report\*.jcl.report) do (
  python jcl_cobol_report.py "%%d" -v
)
```
