package org.smojol.toolkit.analysis.task.analysis;

import com.mojo.woof.Neo4JDriverBuilder;
import lombok.Getter;
import org.apache.commons.lang3.tuple.Pair;
import org.eclipse.lsp.cobol.common.error.SyntaxError;
import org.smojol.common.dialect.LanguageDialect;
import org.smojol.toolkit.analysis.pipeline.*;
import org.smojol.common.resource.ResourceOperations;
import com.mojo.algorithms.task.AnalysisTaskResult;
import org.smojol.toolkit.analysis.error.ParseDiagnosticRuntimeError;
import org.smojol.toolkit.analysis.graph.neo4j.NodeReferenceStrategy;
import org.smojol.common.dependency.ComponentsBuilder;
import org.smojol.toolkit.analysis.pipeline.config.*;
import org.smojol.common.ast.CobolTreeVisualiser;
import com.mojo.algorithms.id.IdProvider;
import org.smojol.common.navigation.EntityNavigatorBuilder;
import org.smojol.common.vm.strategy.UnresolvedReferenceThrowStrategy;
import org.smojol.common.vm.structure.Format1DataStructureBuildStrategy;
import org.smojol.toolkit.flowchart.FlowchartGenerationStrategy;
import org.smojol.toolkit.flowchart.FlowchartOutputWriter;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import org.smojol.toolkit.task.SmojolTasks;
import org.smojol.toolkit.task.TaskRunnerMode;

import com.google.gson.*;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.logging.Logger;
import java.util.stream.Stream;

public class CodeTaskRunner {
    private static final Logger LOGGER = Logger.getLogger(CodeTaskRunner.class.getName());
    private static final String AST_DIR = "ast";
    private static final String DATA_STRUCTURES_DIR = "data_structures";
    private static final String FLOW_AST_DIR = "flow_ast";
    private static final String IMAGES_DIR = "flowcharts";
    private static final String DOTFILES_DIR = "dotfiles";
    private static final String GRAPHML_DIR = "graphml";
    private static final String CFG_DIR = "cfg";
    private static final String SIMILARITY_DIR = "similarity";
    private static final String UNIFIED_MODEL_DIR = "unified_model";
    private static final String TRANSPILER_MODEL_DIR = "transpiler_model";
    private static final String LLM_SUMMARY_DIR = "llm_summary";
    private static final String MERMAID_DIR = "mermaid";
    private static final String GRAPHVIZ_DIR = "graphviz";

    private final String sourceDir;
    private final List<File> copyBookPaths;
    private final String dialectJarPath;
    private final String reportRootDir;
    private final LanguageDialect dialect;
    private final FlowchartGenerationStrategy flowchartGenerationStrategy;
    private final IdProvider idProvider;
    @Getter
    private final Map<String, List<SyntaxError>> errorMap = new HashMap<>();
    private final Format1DataStructureBuildStrategy format1DataStructureBuilder;
    private final ProgramSearch programSearch;
    private final ResourceOperations resourceOperations;

    public CodeTaskRunner(String sourceDir, String reportRootDir, List<File> copyBookPaths, String dialectJarPath,
            LanguageDialect dialect, FlowchartGenerationStrategy flowchartGenerationStrategy, IdProvider idProvider,
            Format1DataStructureBuildStrategy format1DataStructureBuilder, ProgramSearch programSearch,
            ResourceOperations resourceOperations) {
        this.sourceDir = sourceDir;
        this.copyBookPaths = copyBookPaths;
        this.dialectJarPath = dialectJarPath;
        this.reportRootDir = reportRootDir;
        this.dialect = dialect;
        this.flowchartGenerationStrategy = flowchartGenerationStrategy;
        this.idProvider = idProvider;
        this.format1DataStructureBuilder = format1DataStructureBuilder;
        this.programSearch = programSearch;
        this.resourceOperations = resourceOperations;
        reportParameters();
    }

    private void reportParameters() {
        LOGGER.info("Parameters passed in \n--------------------");
        LOGGER.info("srcDir = " + sourceDir);
        LOGGER.info("reportRootDir = " + reportRootDir);
        LOGGER.info("dialectJarPath = " + dialectJarPath);
        LOGGER.info(
                "copyBookPaths = " + String.join(",", copyBookPaths.stream().map(cp -> cp.toString() + "\n").toList()));
    }

    public Map<String, List<AnalysisTaskResult>> runForPrograms(List<CommandLineAnalysisTask> tasks,
            List<String> programFilenames, TaskRunnerMode runnerMode) throws IOException {
        Map<String, List<AnalysisTaskResult>> results = new HashMap<>();
        for (String programFilename : programFilenames) {
            LOGGER.info(String.format("Running tasks: %s for program '%s' in %s mode...",
                    tasks.stream().map(CommandLineAnalysisTask::name).toList(),
                    programFilename, runnerMode.toString()));
            try {
                Pair<File, String> programPath = programSearch.run(programFilename, sourceDir);
                if (programPath == ProgramSearch.NO_PATH) {
                    LOGGER.severe(String.format("No program found for '%s' anywhere in path %s \n", programFilename,
                            sourceDir));
                    continue;
                }
                boolean lenient = (runnerMode == TaskRunnerMode.LENIENT_MODE);
                List<AnalysisTaskResult> analysisTaskResults = runForProgram(programFilename, programPath.getRight(),
                        reportRootDir, this.dialect, runnerMode.tasks(tasks), lenient);
                results.put(programFilename, analysisTaskResults);
            } catch (ParseDiagnosticRuntimeError e) {
                errorMap.put(programFilename, e.getErrors());
            }
        }

        return runnerMode.run(errorMap, results);
    }

    public Map<String, List<AnalysisTaskResult>> runForPrograms(List<CommandLineAnalysisTask> tasks,
            List<String> programFilenames) throws IOException {
        return runForPrograms(tasks, programFilenames, TaskRunnerMode.PRODUCTION_MODE);
    }

    private List<AnalysisTaskResult> runForProgram(String programFilename, String sourceDir, String reportRootDir,
            LanguageDialect dialect, List<CommandLineAnalysisTask> tasks, boolean lenient) throws IOException {
        String programReportDir = String.format("%s.report", programFilename);
        Path astOutputDir = Paths.get(reportRootDir, programReportDir, AST_DIR).toAbsolutePath().normalize();
        Path dataStructuresOutputDir = Paths.get(reportRootDir, programReportDir, DATA_STRUCTURES_DIR).toAbsolutePath()
                .normalize();
        Path flowASTOutputDir = Paths.get(reportRootDir, programReportDir, FLOW_AST_DIR).toAbsolutePath().normalize();
        Path imageOutputDir = Paths.get(reportRootDir, programReportDir, IMAGES_DIR).toAbsolutePath().normalize();
        Path dotFileOutputDir = Paths.get(reportRootDir, programReportDir, DOTFILES_DIR).toAbsolutePath().normalize();
        Path graphvizOutputDir = Paths.get(reportRootDir, programReportDir, GRAPHVIZ_DIR).toAbsolutePath().normalize();
        Path graphMLExportOutputDir = Paths.get(reportRootDir, programReportDir, GRAPHML_DIR).toAbsolutePath()
                .normalize();

        Path cfgOutputDir = Paths.get(reportRootDir, programReportDir, CFG_DIR).toAbsolutePath().normalize();
        Path similarityOutputDir = Paths.get(reportRootDir, programReportDir, SIMILARITY_DIR).toAbsolutePath()
                .normalize();
        Path unifiedModelOutputDir = Paths.get(reportRootDir, programReportDir, UNIFIED_MODEL_DIR).toAbsolutePath()
                .normalize();
        Path transpilerModelOutputDir = Paths.get(reportRootDir, programReportDir, TRANSPILER_MODEL_DIR)
                .toAbsolutePath().normalize();
        Path llmSummaryOutputDir = Paths.get(reportRootDir, programReportDir, LLM_SUMMARY_DIR).toAbsolutePath()
                .normalize();
        String graphMLExportOutputPath = graphMLExportOutputDir.resolve(String.format("%s.graphml", programFilename))
                .toAbsolutePath().normalize().toString();
        String cfgOutputPath = cfgOutputDir.resolve(String.format("cfg-%s.json", programFilename)).toAbsolutePath()
                .normalize().toString();
        String cobolParseTreeOutputPath = astOutputDir.resolve(String.format("cobol-%s.json", programFilename))
                .toAbsolutePath().normalize().toString();
        String flowASTOutputPath = flowASTOutputDir.resolve(String.format("flow-ast-%s.json", programFilename))
                .toAbsolutePath().normalize().toString();
        String absoluteDialectJarPath = Paths.get(dialectJarPath).toAbsolutePath().normalize().toString();
        SourceConfig sourceConfig = new SourceConfig(programFilename, sourceDir, copyBookPaths, absoluteDialectJarPath);
        OutputArtifactConfig dataStructuresOutputConfig = new OutputArtifactConfig(dataStructuresOutputDir,
                programFilename + "-data.json");
        OutputArtifactConfig similarityOutputConfig = new OutputArtifactConfig(similarityOutputDir,
                programFilename + "-similarity.json");
        OutputArtifactConfig unifiedModelOutputConfig = new OutputArtifactConfig(unifiedModelOutputDir,
                programFilename + "-unified.json");
        OutputArtifactConfig transpilerModelOutputConfig = new OutputArtifactConfig(transpilerModelOutputDir,
                programFilename + "-transpiler-model.json");
        OutputArtifactConfig llmOutputConfig = new OutputArtifactConfig(llmSummaryOutputDir,
                programFilename + "-llm-summary.json");

        FlowchartOutputWriter flowchartOutputWriter = new FlowchartOutputWriter(flowchartGenerationStrategy,
                dotFileOutputDir, imageOutputDir);
        RawASTOutputConfig rawAstOutputConfig = new RawASTOutputConfig(astOutputDir, cobolParseTreeOutputPath,
                new CobolTreeVisualiser());
        OutputArtifactConfig mermaidOutputConfig = new OutputArtifactConfig(
                Paths.get(reportRootDir, programReportDir, MERMAID_DIR).toAbsolutePath().normalize(), "");
        OutputArtifactConfig graphvizOutputConfig = new OutputArtifactConfig(graphvizOutputDir, "");

        FlowASTOutputConfig flowASTOutputConfig = new FlowASTOutputConfig(flowASTOutputDir, flowASTOutputPath);
        GraphMLExportConfig graphMLOutputConfig = new GraphMLExportConfig(graphMLExportOutputDir,
                graphMLExportOutputPath);
        CFGOutputConfig cfgOutputConfig = new CFGOutputConfig(cfgOutputDir, cfgOutputPath);
        ComponentsBuilder ops = new ComponentsBuilder(new CobolTreeVisualiser(resourceOperations),
                new EntityNavigatorBuilder(), new UnresolvedReferenceThrowStrategy(),
                format1DataStructureBuilder, idProvider, resourceOperations);
        ParsePipeline pipeline = new ParsePipeline(sourceConfig, ops, dialect);
        pipeline.setLenient(lenient);
        GraphBuildConfig graphBuildConfig = new GraphBuildConfig(
                NodeReferenceStrategy.EXISTING_CFG_NODE,
                NodeReferenceStrategy.EXISTING_CFG_NODE);

        SmojolTasks pipelineTasks = new SmojolTasks(pipeline,
                sourceConfig, flowchartOutputWriter,
                rawAstOutputConfig, graphMLOutputConfig,
                flowASTOutputConfig, cfgOutputConfig,
                graphBuildConfig, dataStructuresOutputConfig, unifiedModelOutputConfig, similarityOutputConfig,
                mermaidOutputConfig, graphvizOutputConfig, transpilerModelOutputConfig,
                llmOutputConfig, idProvider, resourceOperations, new Neo4JDriverBuilder());

        List<CommandLineAnalysisTask> effectiveTasks = tasks.getFirst() != CommandLineAnalysisTask.BUILD_BASE_ANALYSIS
                ? Stream.concat(Stream.of(CommandLineAnalysisTask.BUILD_BASE_ANALYSIS), tasks.stream()).toList()
                : tasks;

        List<AnalysisTaskResult> taskResults;
        try {
            taskResults = pipelineTasks.run(effectiveTasks);
        } catch (RuntimeException e) {
            if (!lenient) throw e;
            LOGGER.warning("LENIENT MODE: Task execution failed after partial parse: " + e.getMessage());
            taskResults = List.of(AnalysisTaskResult.ERROR(e, "LENIENT_TASK_EXECUTION"));
        }

        if (lenient && !pipeline.getParseErrors().isEmpty()) {
            writeParseDiagnostics(pipeline, programFilename, reportRootDir);
        }
        return taskResults;
    }

    private void writeParseDiagnostics(ParsePipeline pipeline, String programFilename,
            String reportRootDir) {
        String programReportDir = String.format("%s.report", programFilename);
        Path diagnosticsPath = Paths.get(reportRootDir, programReportDir, "parse_diagnostics.json")
                .toAbsolutePath().normalize();
        try {
            JsonObject root = new JsonObject();
            root.addProperty("program", programFilename);
            root.addProperty("mode", "lenient");
            root.addProperty("source_lines", pipeline.getSourceLineCount());
            root.addProperty("total_tree_nodes", pipeline.getTotalTreeNodes());

            Set<Integer> errorLines = new HashSet<>();
            JsonArray errorsArray = new JsonArray();
            for (SyntaxError e : pipeline.getParseErrors()) {
                JsonObject err = new JsonObject();
                if (e.getLocation() != null && e.getLocation().getLocation() != null) {
                    var range = e.getLocation().getLocation().getRange();
                    int line = range.getStart().getLine() + 1;
                    err.addProperty("line", line);
                    err.addProperty("column", range.getStart().getCharacter());
                    err.addProperty("end_line", range.getEnd().getLine() + 1);
                    err.addProperty("end_column", range.getEnd().getCharacter());
                    for (int l = range.getStart().getLine(); l <= range.getEnd().getLine(); l++) {
                        errorLines.add(l);
                    }
                }
                err.addProperty("severity",
                    e.getSeverity() != null ? e.getSeverity().name() : "UNKNOWN");
                err.addProperty("source",
                    e.getErrorSource() != null ? e.getErrorSource().getText() : "UNKNOWN");
                err.addProperty("suggestion",
                    e.getSuggestion() != null ? e.getSuggestion() : "No suggestion");
                String copybookId = (e.getLocation() != null) ? e.getLocation().getCopybookId() : null;
                if (copybookId != null) {
                    err.addProperty("copybook", copybookId);
                } else {
                    err.add("copybook", JsonNull.INSTANCE);
                }
                errorsArray.add(err);
            }
            root.add("errors", errorsArray);

            int sourceLines = pipeline.getSourceLineCount();
            int affectedLines = errorLines.size();
            double coverage = sourceLines > 0
                ? ((sourceLines - affectedLines) * 100.0 / sourceLines) : 0.0;
            root.addProperty("coverage_percentage", Math.round(coverage * 100.0) / 100.0);
            root.addProperty("affected_lines", affectedLines);

            JsonObject summary = new JsonObject();
            summary.addProperty("total_errors", pipeline.getParseErrors().size());
            Map<String, Integer> bySeverity = new HashMap<>();
            Map<String, Integer> bySource = new HashMap<>();
            for (SyntaxError e : pipeline.getParseErrors()) {
                String sev = e.getSeverity() != null ? e.getSeverity().name() : "UNKNOWN";
                bySeverity.merge(sev, 1, Integer::sum);
                String src = e.getErrorSource() != null ? e.getErrorSource().getText() : "UNKNOWN";
                bySource.merge(src, 1, Integer::sum);
            }
            summary.add("by_severity", new Gson().toJsonTree(bySeverity));
            summary.add("by_source", new Gson().toJsonTree(bySource));
            root.add("error_summary", summary);

            Files.createDirectories(diagnosticsPath.getParent());
            Files.writeString(diagnosticsPath,
                new GsonBuilder().setPrettyPrinting().create().toJson(root));
            LOGGER.info("Parse diagnostics written to " + diagnosticsPath);
        } catch (Exception ex) {
            LOGGER.warning("Failed to write parse diagnostics: " + ex.getMessage());
        }
    }
}
