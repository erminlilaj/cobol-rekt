package org.smojol.toolkit.analysis.task.analysis;

import com.mojo.woof.Neo4JDriverBuilder;
import com.mojo.algorithms.task.AnalysisTaskResultError;
import com.mojo.algorithms.task.AnalysisTaskResultOK;
import lombok.Getter;
import org.apache.commons.lang3.tuple.Pair;
import org.eclipse.lsp.cobol.common.error.SyntaxError;
import org.smojol.common.dialect.LanguageDialect;
import org.smojol.toolkit.analysis.pipeline.*;
import org.smojol.common.resource.ResourceOperations;
import com.mojo.algorithms.task.AnalysisTaskResult;
import org.smojol.toolkit.analysis.error.BaseModelValidationException;
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
    private static final String ANALYSIS_HEALTH_FILENAME = "analysis_health.json";

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
        writeAnalysisHealth(pipeline, effectiveTasks, taskResults, programFilename, reportRootDir, lenient);
        AnalysisSelfEvaluationWriter.write(programFilename, lenient ? "lenient" : "strict",
                Paths.get(reportRootDir, programReportDir).toAbsolutePath().normalize(),
                Map.of(
                        "raw_ast", Path.of(cobolParseTreeOutputPath),
                        "flow_ast", Path.of(flowASTOutputPath),
                        "cfg", Path.of(cfgOutputPath),
                        "data_structures", dataStructuresOutputConfig.outputDir()
                                .resolve(dataStructuresOutputConfig.filename()),
                        "unified_model", unifiedModelOutputConfig.outputDir()
                                .resolve(unifiedModelOutputConfig.filename()),
                        "analysis_health", Paths.get(reportRootDir, programReportDir, ANALYSIS_HEALTH_FILENAME)
                ));
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
            int nullLocationErrors = 0;
            JsonArray errorsArray = new JsonArray();
            for (SyntaxError e : pipeline.getParseErrors()) {
                JsonObject err = new JsonObject();
                boolean hasLocation = false;
                if (e.getLocation() != null && e.getLocation().getLocation() != null) {
                    var range = e.getLocation().getLocation().getRange();
                    if (range != null && range.getStart() != null) {
                        hasLocation = true;
                        int line = range.getStart().getLine() + 1;
                        err.addProperty("line", line);
                        err.addProperty("column", range.getStart().getCharacter());
                        if (range.getEnd() != null) {
                            err.addProperty("end_line", range.getEnd().getLine() + 1);
                            err.addProperty("end_column", range.getEnd().getCharacter());
                            for (int l = range.getStart().getLine(); l <= range.getEnd().getLine(); l++) {
                                errorLines.add(l);
                            }
                        } else {
                            errorLines.add(range.getStart().getLine());
                        }
                    }
                }
                if (!hasLocation) {
                    nullLocationErrors++;
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
            // Heuristic: assume 3 affected lines per error with no location info
            int estimatedAffectedFromNullLocations = nullLocationErrors * 3;
            int affectedLines = errorLines.size() + estimatedAffectedFromNullLocations;
            double coverage = sourceLines > 0
                ? ((sourceLines - affectedLines) * 100.0 / sourceLines) : 0.0;
            root.addProperty("coverage_percentage", Math.round(coverage * 100.0) / 100.0);
            root.addProperty("affected_lines", affectedLines);
            root.addProperty("null_location_errors", nullLocationErrors);

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

            // Skipped variables from data structure building
            JsonArray skippedVars = new JsonArray();
            for (org.smojol.common.structure.SkippedVariable sv : pipeline.getSkippedDataStructures()) {
                JsonObject entry = new JsonObject();
                entry.addProperty("variable", sv.name());
                entry.addProperty("error", sv.error());
                entry.addProperty("section", sv.section());
                skippedVars.add(entry);
            }
            root.add("skipped_variables", skippedVars);
            root.addProperty("data_structures_degraded", pipeline.isDataStructureDegraded());

            Files.createDirectories(diagnosticsPath.getParent());
            Files.writeString(diagnosticsPath,
                new GsonBuilder().setPrettyPrinting().create().toJson(root));
            LOGGER.info("Parse diagnostics written to " + diagnosticsPath);
        } catch (Exception ex) {
            LOGGER.warning("Failed to write parse diagnostics: " + ex.getMessage());
        }
    }

    private void writeAnalysisHealth(ParsePipeline pipeline, List<CommandLineAnalysisTask> requestedTasks,
            List<AnalysisTaskResult> taskResults, String programFilename, String reportRootDir, boolean lenient) {
        String programReportDir = String.format("%s.report", programFilename);
        Path healthPath = Paths.get(reportRootDir, programReportDir, ANALYSIS_HEALTH_FILENAME)
                .toAbsolutePath().normalize();
        try {
            JsonObject root = new JsonObject();
            root.addProperty("program", programFilename);
            root.addProperty("mode", lenient ? "lenient" : "strict");
            root.addProperty("base_analysis_succeeded", baseAnalysisSucceeded(taskResults));
            root.addProperty("parse_error_count", parseErrorCount(pipeline, taskResults));

            Double coverage = coveragePercentage(pipeline, taskResults);
            if (coverage != null) root.addProperty("coverage_percentage", coverage);
            else root.add("coverage_percentage", JsonNull.INSTANCE);

            root.addProperty("source_lines", pipeline.getSourceLineCount());
            root.addProperty("total_tree_nodes", pipeline.getTotalTreeNodes());
            root.addProperty("skipped_variable_count", pipeline.getSkippedDataStructures().size());
            root.addProperty("data_structures_degraded", pipeline.isDataStructureDegraded());
            root.add("requested_tasks", new Gson().toJsonTree(requestedTasks.stream()
                    .map(CommandLineAnalysisTask::name).toList()));
            root.add("completed_tasks", new Gson().toJsonTree(taskResults.stream()
                    .filter(AnalysisTaskResult::isSuccess)
                    .map(r -> ((AnalysisTaskResultOK) r).getTask())
                    .toList()));
            root.add("failed_tasks", new Gson().toJsonTree(taskResults.stream()
                    .filter(r -> !r.isSuccess())
                    .map(r -> ((AnalysisTaskResultError) r).getTask())
                    .toList()));
            root.add("primary_failure", primaryFailure(taskResults));

            Files.createDirectories(healthPath.getParent());
            Files.writeString(healthPath, new GsonBuilder().setPrettyPrinting().create().toJson(root));
            LOGGER.info("Analysis health written to " + healthPath);
        } catch (Exception ex) {
            LOGGER.warning("Failed to write analysis health: " + ex.getMessage());
        }
    }

    private boolean baseAnalysisSucceeded(List<AnalysisTaskResult> taskResults) {
        if (taskResults.isEmpty()) return false;
        AnalysisTaskResult firstResult = taskResults.getFirst();
        return firstResult.isSuccess()
                && firstResult instanceof AnalysisTaskResultOK ok
                && CommandLineAnalysisTask.BUILD_BASE_ANALYSIS.name().equals(ok.getTask());
    }

    private int parseErrorCount(ParsePipeline pipeline, List<AnalysisTaskResult> taskResults) {
        if (!pipeline.getParseErrors().isEmpty()) return pipeline.getParseErrors().size();
        return taskResults.stream()
                .filter(r -> !r.isSuccess())
                .map(r -> ((AnalysisTaskResultError) r).getException())
                .filter(ParseDiagnosticRuntimeError.class::isInstance)
                .map(ParseDiagnosticRuntimeError.class::cast)
                .findFirst()
                .map(e -> e.getErrors().size())
                .orElse(0);
    }

    private Double coveragePercentage(ParsePipeline pipeline, List<AnalysisTaskResult> taskResults) {
        if (pipeline.getSourceLineCount() <= 0) return null;
        List<SyntaxError> errors = !pipeline.getParseErrors().isEmpty()
                ? pipeline.getParseErrors()
                : taskResults.stream()
                        .filter(r -> !r.isSuccess())
                        .map(r -> ((AnalysisTaskResultError) r).getException())
                        .filter(ParseDiagnosticRuntimeError.class::isInstance)
                        .map(ParseDiagnosticRuntimeError.class::cast)
                        .findFirst()
                        .map(ParseDiagnosticRuntimeError::getErrors)
                        .orElse(List.of());
        if (errors.isEmpty()) return 100.0;
        Set<Integer> errorLines = new HashSet<>();
        int nullLocationErrors = 0;
        for (SyntaxError error : errors) {
            if (error.getLocation() != null && error.getLocation().getLocation() != null
                    && error.getLocation().getLocation().getRange() != null
                    && error.getLocation().getLocation().getRange().getStart() != null) {
                var range = error.getLocation().getLocation().getRange();
                if (range.getEnd() != null) {
                    for (int l = range.getStart().getLine(); l <= range.getEnd().getLine(); l++) {
                        errorLines.add(l);
                    }
                } else {
                    errorLines.add(range.getStart().getLine());
                }
            } else {
                nullLocationErrors++;
            }
        }

        int affectedLines = errorLines.size() + (nullLocationErrors * 3);
        double coverage = (pipeline.getSourceLineCount() - affectedLines) * 100.0 / pipeline.getSourceLineCount();
        return Math.round(coverage * 100.0) / 100.0;
    }

    private JsonElement primaryFailure(List<AnalysisTaskResult> taskResults) {
        Optional<AnalysisTaskResultError> maybeError = taskResults.stream()
                .filter(r -> !r.isSuccess())
                .map(r -> (AnalysisTaskResultError) r)
                .findFirst();
        if (maybeError.isEmpty()) return JsonNull.INSTANCE;

        AnalysisTaskResultError error = maybeError.get();
        JsonObject root = new JsonObject();
        root.addProperty("task", error.getTask());
        root.addProperty("exception_class", error.getException().getClass().getName());
        root.addProperty("message", error.getException().getMessage());
        if (error.getException() instanceof BaseModelValidationException baseModelValidationException) {
            root.addProperty("diagnostic_code", baseModelValidationException.getDiagnosticCode());
            root.addProperty("analysis_stage", baseModelValidationException.getAnalysisStage());
        }
        if (error.getException() instanceof ParseDiagnosticRuntimeError parseDiagnosticRuntimeError) {
            root.addProperty("parse_error_count", parseDiagnosticRuntimeError.getErrors().size());
        }
        return root;
    }
}
