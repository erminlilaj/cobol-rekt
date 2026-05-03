package org.smojol.toolkit.analysis.task;

import com.google.common.collect.ImmutableList;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mojo.algorithms.id.UUIDProvider;
import com.mojo.algorithms.task.AnalysisTaskResult;
import com.mojo.algorithms.task.AnalysisTaskResultError;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import com.mojo.algorithms.visualisation.FlowchartOutputFormat;
import org.junit.jupiter.api.Test;
import org.smojol.common.dialect.LanguageDialect;
import org.smojol.common.logging.LoggingConfig;
import org.smojol.common.resource.LocalFilesystemOperations;
import org.smojol.toolkit.analysis.pipeline.ProgramSearch;
import org.smojol.toolkit.analysis.task.analysis.CodeTaskRunner;
import org.smojol.toolkit.interpreter.FullProgram;
import org.smojol.toolkit.interpreter.structure.OccursIgnoringFormat1DataStructureBuilder;
import org.smojol.toolkit.task.TaskRunnerMode;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class JavaHardeningRegressionTest {
    private static final Gson GSON = new Gson();

    @Test
    void writesStableAnalysisHealthArtifact() throws IOException {
        new TestTaskRunner("hardening-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject health = readJson("hardening-features.cbl.report/analysis_health.json");
        assertEquals("strict", health.get("mode").getAsString());
        assertTrue(health.get("base_analysis_succeeded").getAsBoolean());
        assertTrue(jsonArrayContainsString(health.getAsJsonArray("requested_tasks"), "BUILD_BASE_ANALYSIS"));
        assertTrue(jsonArrayContainsString(health.getAsJsonArray("requested_tasks"), "WRITE_CFG"));

        JsonObject selfEvaluation = readJson("hardening-features.cbl.report/analysis_self_evaluation.json");
        assertEquals("1.0", selfEvaluation.get("schema_version").getAsString());
        assertTrue(selfEvaluation.get("base_analysis_succeeded").getAsBoolean());
        assertTrue(selfEvaluation.has("cfg_metrics"));
        assertTrue(selfEvaluation.has("semantic_coverage"));
    }

    @Test
    void exportsEvaluateBranchExitKindAndSpecialStatementTypes() throws IOException {
        new TestTaskRunner("hardening-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("hardening-features.cbl.report/cfg/cfg-hardening-features.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        assertTrue(hasNodeType(nodes, "EVALUATE_BRANCH"));
        assertTrue(hasNodeType(nodes, "STRING"));
        assertTrue(hasNodeType(nodes, "UNSTRING"));
        assertTrue(hasNodeType(nodes, "ALTER"));
        assertTrue(hasExitKind(nodes, "EXIT_PARAGRAPH"));
        assertTrue(hasExitKind(nodes, "GOBACK"));
        assertTrue(hasAlterHazard(nodes));
    }

    @Test
    void exportsCicsHandleBindingsAsMetadata() throws IOException {
        new TestTaskRunner("cics-handle.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("cics-handle.cbl.report/cfg/cfg-cics-handle.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");
        assertTrue(hasHandlerBinding(nodes, "CONDITION", "ERROR"));
        assertTrue(hasHandlerBinding(nodes, "CONDITION", "MAPFAIL"));
        assertTrue(hasHandlerBinding(nodes, "AID", "CLEAR"));
        assertTrue(hasHandlerBinding(nodes, "ABEND", "LABEL"));
        assertTrue(hasMetadataValue(nodes, "cics_command", "LINK"));
        assertTrue(hasMetadataValue(nodes, "cics_target_program", "PAYPGM"));
        assertTrue(hasMetadataValue(nodes, "cics_map", "PAYMAP"));
        assertTrue(hasMetadataValue(nodes, "cics_mapset", "PAYMAPS"));
        assertTrue(hasMetadataValue(nodes, "cics_transid", "PAYT"));
        assertTrue(hasCicsArgument(nodes, "PROGRAM", "PAYPGM", "literal"));
        assertTrue(hasCicsArgument(nodes, "MAP", "PAYMAP", "literal"));
        assertTrue(hasCicsArgument(nodes, "MAPSET", "PAYMAPS", "literal"));
        assertTrue(hasCicsArgument(nodes, "TRANSID", "PAYT", "literal"));
    }

    @Test
    void exportsCallGotoPerformAndTypedStatementMetadata() throws IOException {
        new TestTaskRunner("metadata-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("metadata-features.cbl.report/cfg/cfg-metadata-features.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        assertTrue(hasMetadataValue(nodes, "call_target", "SUBPROG"));
        assertTrue(hasMetadataValue(nodes, "program_reference_type", "STATIC"));
        assertTrue(hasMetadataValue(nodes, "call_target", "CALL-NAME"));
        assertTrue(hasMetadataValue(nodes, "program_reference_type", "DYNAMIC"));
        assertTrue(hasMetadataValue(nodes, "depending_on", "SWITCH-FLAG"));
        assertTrue(hasMetadataValue(nodes, "perform_start", "LOOP-PARA"));
        assertTrue(hasNodeType(nodes, "SET"));
        assertTrue(hasNodeType(nodes, "INITIALIZE"));
        assertTrue(hasNodeType(nodes, "ACCEPT"));
        assertTrue(hasNodeType(nodes, "INSPECT"));
        assertTrue(hasNodeType(nodes, "OPEN"));
        assertTrue(hasNodeType(nodes, "READ"));
        assertTrue(hasNodeType(nodes, "WRITE"));
        assertTrue(hasNodeType(nodes, "CLOSE"));
        assertTrue(hasNodeType(nodes, "CONTINUE"));
        assertTrue(hasNodeType(nodes, "CANCEL"));

        JsonObject selfEvaluation = readJson("metadata-features.cbl.report/analysis_self_evaluation.json");
        assertTrue(selfEvaluation.getAsJsonObject("cfg_metrics").get("node_count").getAsInt() > 0);
    }

    @Test
    void exportsParagraphVariableUsageFromResolvedFlowNodes() throws IOException {
        new TestTaskRunner("variable-usage-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("variable-usage-features.cbl.report/cfg/cfg-variable-usage-features.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");
        JsonObject paragraph = findNode(nodes, "type", "PARAGRAPH");
        JsonObject move = findNodeByOriginalText(nodes, "MOVE IN-1 TO OUT-1 OUT-2");

        assertNotNull(paragraph);
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "IN-1"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "IN-2"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "COUNTER"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "FLAG"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesModified"), "OUT-1"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesModified"), "OUT-2"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesModified"), "RESULT"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesModified"), "TOTAL"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesModified"), "FLAG"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesModified"), "COUNTER"));
        assertEquals("java_flow_node_expressions", paragraph.get("variableUsageSource").getAsString());
        assertTrue(paragraph.get("reachable").getAsBoolean());
        assertEquals("java_cfg_graph_traversal", paragraph.get("reachabilitySource").getAsString());
        assertFalse(paragraph.get("deadCodeCandidate").getAsBoolean());

        assertNotNull(move);
        assertTrue(jsonArrayContainsString(move.getAsJsonArray("variablesRead"), "IN-1"));
        assertTrue(jsonArrayContainsString(move.getAsJsonArray("variablesModified"), "OUT-1"));
        assertTrue(jsonArrayContainsString(move.getAsJsonArray("variablesModified"), "OUT-2"));
        assertTrue(hasAssignmentFact(nodes, "FLAG", "'Y'", "MAIN-PARA", "java_move_literal"));
        assertTrue(hasAssignmentFact(nodes, "OUT-2", "7", "MAIN-PARA", "java_compute_numeric_literal"));
        assertTrue(hasAssignmentFact(nodes, "COUNTER", "3", "MAIN-PARA", "java_set_literal"));
    }

    @Test
    void abortsAfterBaseAnalysisFailureWithoutCascadeNoise() throws IOException {
        Map<String, List<AnalysisTaskResult>> results = runTasks(
                TaskRunnerMode.PRODUCTION_MODE,
                ImmutableList.of(CommandLineAnalysisTask.WRITE_CFG, CommandLineAnalysisTask.WRITE_FLOW_AST),
                ImmutableList.of("missing-copybook.cbl"));

        List<AnalysisTaskResult> taskResults = results.get("missing-copybook.cbl");
        assertEquals(1, taskResults.size());
        assertTrue(taskResults.get(0) instanceof AnalysisTaskResultError);

        JsonObject health = readJson("missing-copybook.cbl.report/analysis_health.json");
        assertFalse(health.get("base_analysis_succeeded").getAsBoolean());
        assertEquals(1, health.getAsJsonArray("failed_tasks").size());
        assertEquals("BUILD_BASE_ANALYSIS", health.get("primary_failure").getAsJsonObject().get("task").getAsString());

        JsonObject selfEvaluation = readJson("missing-copybook.cbl.report/analysis_self_evaluation.json");
        assertFalse(selfEvaluation.get("base_analysis_succeeded").getAsBoolean());
        assertEquals("none", selfEvaluation.get("confidence_label").getAsString());
    }

    @Test
    void transpilerHandlesParagraphsWithoutSections() throws IOException {
        AnalysisTaskResult taskResult = new TestTaskRunner("no-section-transpiler.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.BUILD_TRANSPILER_FLOWGRAPH);

        assertTrue(taskResult.isSuccess(), taskResult::toString);
    }

    @Test
    void reportsStructuredDiagnosticForMissingProcedureBody() throws IOException {
        Map<String, List<AnalysisTaskResult>> results = runTasks(
                TaskRunnerMode.PRODUCTION_MODE,
                ImmutableList.of(CommandLineAnalysisTask.WRITE_CFG, CommandLineAnalysisTask.WRITE_FLOW_AST),
                ImmutableList.of("missing-procedure-body.cbl"));
        List<AnalysisTaskResult> taskResults = results.get("missing-procedure-body.cbl");

        assertEquals(1, taskResults.size());
        assertTrue(taskResults.get(0) instanceof AnalysisTaskResultError);

        JsonObject health = readJson("missing-procedure-body.cbl.report/analysis_health.json");
        JsonObject primaryFailure = health.get("primary_failure").getAsJsonObject();
        assertFalse(health.get("base_analysis_succeeded").getAsBoolean());
        assertEquals("BUILD_BASE_ANALYSIS", primaryFailure.get("task").getAsString());
        assertEquals("MISSING_PROCEDURE_DIVISION_BODY", primaryFailure.get("diagnostic_code").getAsString());

        JsonObject selfEvaluation = readJson("missing-procedure-body.cbl.report/analysis_self_evaluation.json");
        assertEquals("MISSING_PROCEDURE_DIVISION_BODY",
                selfEvaluation.get("primary_failure").getAsJsonObject().get("diagnostic_code").getAsString());
        assertTrue(hasWarningCode(selfEvaluation.getAsJsonArray("warnings"), "MISSING_PROCEDURE_DIVISION_BODY"));
    }

    @Test
    void writesHealthForMissingIdentificationDivisionInLenientMode() throws IOException {
        runTasks(
                TaskRunnerMode.LENIENT_MODE,
                ImmutableList.of(CommandLineAnalysisTask.WRITE_CFG),
                ImmutableList.of("missing-identification-division.cbl"));

        JsonObject health = readJson("missing-identification-division.cbl.report/analysis_health.json");
        assertEquals("lenient", health.get("mode").getAsString());
        assertFalse(health.get("base_analysis_succeeded").getAsBoolean());
        JsonObject primaryFailure = health.get("primary_failure").getAsJsonObject();
        assertEquals("BUILD_BASE_ANALYSIS", primaryFailure.get("task").getAsString());
        assertEquals("MISSING_IDENTIFICATION_DIVISION", primaryFailure.get("diagnostic_code").getAsString());

        JsonObject selfEvaluation = readJson("missing-identification-division.cbl.report/analysis_self_evaluation.json");
        assertEquals("MISSING_IDENTIFICATION_DIVISION",
                selfEvaluation.get("primary_failure").getAsJsonObject().get("diagnostic_code").getAsString());
        assertTrue(hasWarningCode(selfEvaluation.getAsJsonArray("warnings"), "MISSING_IDENTIFICATION_DIVISION"));
    }

    private JsonObject readJson(String relativePath) throws IOException {
        Path path = Path.of(TestTaskRunner.dir("test-code/out"), relativePath);
        return GSON.fromJson(Files.readString(path), JsonObject.class);
    }

    private boolean hasNodeType(JsonArray nodes, String type) {
        return jsonObjects(nodes).stream()
                .anyMatch(node -> type.equals(node.get("type").getAsString()));
    }

    private boolean hasExitKind(JsonArray nodes, String exitKind) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .anyMatch(metadata -> metadata.has("exit_kind")
                        && exitKind.equals(metadata.get("exit_kind").getAsString()));
    }

    private boolean hasAlterHazard(JsonArray nodes) {
        return jsonObjects(nodes).stream()
                .filter(node -> "ALTER".equals(node.get("type").getAsString()) && node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .anyMatch(metadata -> metadata.has("dynamic_control_hazard")
                        && metadata.get("dynamic_control_hazard").getAsBoolean());
    }

    private boolean hasHandlerBinding(JsonArray nodes, String kind, String handledKey) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .filter(metadata -> metadata.has("handler_bindings"))
                .flatMap(metadata -> jsonObjects(metadata.getAsJsonArray("handler_bindings")).stream())
                .anyMatch(binding -> kind.equals(binding.get("handler_kind").getAsString())
                        && handledKey.equals(binding.get("handled_key").getAsString()));
    }

    private boolean hasMetadataValue(JsonArray nodes, String key, String value) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .anyMatch(metadata -> metadata.has(key) && value.equals(metadata.get(key).getAsString()));
    }

    private boolean hasCicsArgument(JsonArray nodes, String name, String value, String valueSource) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .filter(metadata -> metadata.has("cics_arguments"))
                .flatMap(metadata -> jsonObjects(metadata.getAsJsonArray("cics_arguments")).stream())
                .anyMatch(argument -> name.equals(argument.get("name").getAsString())
                        && value.equals(argument.get("value").getAsString())
                        && valueSource.equals(argument.get("value_source").getAsString()));
    }

    private boolean hasAssignmentFact(JsonArray nodes, String targetVariable, String sourceValue,
                                      String paragraph, String provenanceSource) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .filter(metadata -> metadata.has("assignment_facts"))
                .flatMap(metadata -> jsonObjects(metadata.getAsJsonArray("assignment_facts")).stream())
                .anyMatch(assignment -> targetVariable.equals(assignment.get("target_variable").getAsString())
                        && sourceValue.equals(assignment.get("source_value").getAsString())
                        && paragraph.equals(assignment.get("paragraph").getAsString())
                        && provenanceSource.equals(assignment.get("provenance_source").getAsString()));
    }

    private JsonObject findNode(JsonArray nodes, String key, String value) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has(key) && value.equals(node.get(key).getAsString()))
                .findFirst()
                .orElse(null);
    }

    private JsonObject findNodeByOriginalText(JsonArray nodes, String text) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("originalText") && node.get("originalText").getAsString().contains(text))
                .findFirst()
                .orElse(null);
    }

    private boolean jsonArrayContainsString(JsonArray array, String value) {
        if (array == null) return false;
        for (int i = 0; i < array.size(); i++) {
            if (value.equals(array.get(i).getAsString())) return true;
        }
        return false;
    }

    private boolean hasWarningCode(JsonArray warnings, String code) {
        return jsonObjects(warnings).stream()
                .anyMatch(warning -> code.equals(warning.get("code").getAsString()));
    }

    private List<JsonObject> jsonObjects(JsonArray array) {
        List<JsonObject> objects = new ArrayList<>();
        if (array == null) return objects;
        array.forEach(element -> objects.add(element.getAsJsonObject()));
        return objects;
    }

    private Map<String, List<AnalysisTaskResult>> runTasks(TaskRunnerMode mode,
            List<CommandLineAnalysisTask> tasks, List<String> programs) throws IOException {
        LoggingConfig.setupLogging();
        LocalFilesystemOperations resourceOperations = new LocalFilesystemOperations();
        UUIDProvider idProvider = new UUIDProvider();
        return new CodeTaskRunner(
                TestTaskRunner.dir("test-code/flow-ast"),
                TestTaskRunner.dir("test-code/out"),
                ImmutableList.of(new File(TestTaskRunner.dir("test-code/flow-ast"))),
                TestTaskRunner.dir("che-che4z-lsp-for-cobol-integration/server/dialect-idms/target/dialect-idms.jar"),
                LanguageDialect.COBOL,
                new FullProgram(FlowchartOutputFormat.MERMAID, idProvider),
                idProvider,
                new OccursIgnoringFormat1DataStructureBuilder(),
                new ProgramSearch(resourceOperations),
                resourceOperations
        ).runForPrograms(tasks, programs, mode);
    }
}
