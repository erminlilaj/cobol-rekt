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
    void abortsAfterBaseAnalysisFailureWithoutCascadeNoise() throws IOException {
        LoggingConfig.setupLogging();
        LocalFilesystemOperations resourceOperations = new LocalFilesystemOperations();
        UUIDProvider idProvider = new UUIDProvider();
        Map<String, List<AnalysisTaskResult>> results = new CodeTaskRunner(
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
        ).runForPrograms(
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

    private boolean jsonArrayContainsString(JsonArray array, String value) {
        if (array == null) return false;
        for (int i = 0; i < array.size(); i++) {
            if (value.equals(array.get(i).getAsString())) return true;
        }
        return false;
    }

    private List<JsonObject> jsonObjects(JsonArray array) {
        List<JsonObject> objects = new ArrayList<>();
        if (array == null) return objects;
        array.forEach(element -> objects.add(element.getAsJsonObject()));
        return objects;
    }
}
