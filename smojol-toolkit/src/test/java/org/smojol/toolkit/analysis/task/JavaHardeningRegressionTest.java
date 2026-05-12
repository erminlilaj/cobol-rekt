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
        assertTrue(hasCicsArgument(nodes, "PROGRAM", "WS-PROGRAM", "identifier"));
        assertTrue(hasCicsArgument(nodes, "COMMAREA", "WS-MSG", "identifier"));
        assertTrue(hasCicsArgument(nodes, "LENGTH", "20", "literal"));
        assertTrue(hasCicsArgument(nodes, "RESP", "WS-RESP", "identifier"));
        assertTrue(hasResolvedCicsTarget(nodes, "WS-PROGRAM", "DYNCICS",
                "inferred_literal_assignment", "medium"));
        assertTrue(hasCicsOperation(nodes, "LINK", "PROGRAM", "DYNCICS"));
        assertTrue(hasCicsOperation(nodes, "SEND", "MAP", "PAYMAP"));
    }

    @Test
    void exportsCallGotoPerformAndTypedStatementMetadata() throws IOException {
        new TestTaskRunner("metadata-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("metadata-features.cbl.report/cfg/cfg-metadata-features.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");
        JsonArray edges = cfg.getAsJsonArray("edges");

        assertTrue(hasMetadataValue(nodes, "call_target", "SUBPROG"));
        assertTrue(hasMetadataValue(nodes, "program_reference_type", "STATIC"));
        assertTrue(hasResolvedCall(nodes, "SUBPROG", "SUBPROG", "literal", "high"));
        assertTrue(hasMetadataValue(nodes, "call_target", "CALL-NAME"));
        assertTrue(hasMetadataValue(nodes, "program_reference_type", "DYNAMIC"));
        assertTrue(hasResolvedCall(nodes, "CALL-NAME", "DYNPROG", "inferred_literal_assignment", "medium"));
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
        assertTrue(hasNodeSourceLocation(nodes));
        assertTrue(hasEdgeSourceContract(edges));

        JsonObject selfEvaluation = readJson("metadata-features.cbl.report/analysis_self_evaluation.json");
        assertTrue(selfEvaluation.getAsJsonObject("cfg_metrics").get("node_count").getAsInt() > 0);
    }

    @Test
    void exportsParagraphVariableUsageFromResolvedFlowNodes() throws IOException {
        new TestTaskRunner("variable-usage-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("variable-usage-features.cbl.report/cfg/cfg-variable-usage-features.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");
        JsonArray edges = cfg.getAsJsonArray("edges");
        JsonObject paragraph = findNode(nodes, "type", "PARAGRAPH");
        JsonObject move = findNodeByOriginalText(nodes, "MOVE IN-1 TO OUT-1 OUT-2");

        assertNotNull(paragraph);
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "IN-1"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "IN-2"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "COUNTER"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "FLAG"));
        assertTrue(jsonArrayContainsString(paragraph.getAsJsonArray("variablesRead"), "INIT-SOURCE"));
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
        assertTrue(hasInitializeFact(nodes, "OUT-1", "NUMERIC", "0", "MAIN-PARA"));
        assertTrue(hasInitializeReplacementSource(nodes, "OUT-1", "ALPHANUMERIC", "INIT-SOURCE"));
        assertTrue(hasConditionedEdge(edges, "FLAG = 'Y'"));
    }

    // -----------------------------------------------------------------------
    // Stage 1 (proposal 0006) — D1 + D2 contract-locking tests.
    // These tests assert the *current* literal-fact gate and dynamic call
    // resolution behaviour. They must pass against unmodified main/. If a
    // future change alters the behaviour, the test must be edited explicitly,
    // forcing the change to be a deliberate, reviewed decision.
    // -----------------------------------------------------------------------

    @Test
    void exportsNoAssignmentFactsForLiteralArithmeticCompute() throws IOException {
        new TestTaskRunner("optimization-stage1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("optimization-stage1.cbl.report/cfg/cfg-optimization-stage1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        JsonObject computeNode = findNodeByOriginalText(nodes, "COMPUTE WS-COMP-X = 1 + 2");
        assertNotNull(computeNode);
        assertFalse(computeNode.has("metadata") && computeNode.getAsJsonObject("metadata").has("assignment_facts"),
                "COMPUTE with non-bare-literal RHS (1 + 2) must not emit assignment_facts; "
                        + "the current gate is value.matches(\"\\\\d+(\\\\.\\\\d+)?\") which only accepts a single bare numeric literal");
    }

    @Test
    void exportsFoldedValueFactForClosedNumericCompute() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonObject computeNode = findNodeByOriginalTextAndType(cfg.getAsJsonArray("nodes"),
                "COMPUTE WS-A = 1 + 2", "COMPUTE");
        assertNotNull(computeNode);
        assertTrue(computeNode.get("originalText").getAsString().contains("COMPUTE WS-A = 1 + 2"));
        assertFalse(computeNode.getAsJsonObject("metadata").has("assignment_facts"));

        JsonObject fact = firstFoldedValueFact(computeNode);
        assertEquals("1.0", fact.get("schema_version").getAsString());
        assertEquals("folded_expression", fact.get("fact_type").getAsString());
        assertEquals("folded", fact.get("status").getAsString());
        assertEquals("COMPUTE", fact.get("statement_type").getAsString());
        assertEquals("WS-A", fact.get("target_variable").getAsString());
        assertEquals("1+2", fact.get("original_expression").getAsString());
        assertEquals("3", fact.get("folded_expression").getAsString());
        assertEquals("high", fact.get("confidence").getAsString());
        assertEquals("java_static_value_folded_expression", fact.get("provenance_source").getAsString());
        assertEquals("MAIN-PARA", fact.get("paragraph").getAsString());

        JsonObject value = fact.getAsJsonObject("value");
        assertEquals("CONSTANT", value.get("state").getAsString());
        assertEquals("NUMERIC", value.get("kind").getAsString());
        assertEquals("3", value.get("raw_lexeme").getAsString());
        assertEquals("3", value.get("normalized_value").getAsString());
        assertEquals("3", value.get("display_value").getAsString());

        JsonObject numeric = value.getAsJsonObject("numeric");
        assertEquals("3", numeric.get("decimal").getAsString());
        assertEquals(0, numeric.get("scale").getAsInt());
        assertEquals(1, numeric.get("precision").getAsInt());
        assertEquals("POSITIVE", numeric.get("sign").getAsString());
    }

    @Test
    void reportsVariableReferenceAsUnsupportedForPhaseOneFolding() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonObject computeNode = findNodeByOriginalTextAndType(cfg.getAsJsonArray("nodes"),
                "COMPUTE WS-B = WS-A + 1", "COMPUTE");
        assertNotNull(computeNode);
        JsonObject metadata = computeNode.getAsJsonObject("metadata");
        assertFalse(metadata.has("assignment_facts"));
        assertFalse(metadata.has("folded_value_facts"));

        JsonObject diagnostic = firstFoldingDiagnostic(computeNode);
        assertEquals("FOLD_UNSUPPORTED_VARIABLE_REFERENCE", diagnostic.get("code").getAsString());
        assertEquals("info", diagnostic.get("severity").getAsString());
        assertEquals("unsupported", diagnostic.get("category").getAsString());
        assertEquals("WS-A", diagnostic.get("construct").getAsString());
        assertEquals("Expression contains variable WS-A; Phase 1 folds only closed literal expressions.",
                diagnostic.get("message").getAsString());
    }

    @Test
    void reportsDivideByZeroAsUnsafeForPhaseOneFolding() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonObject computeNode = findNodeByOriginalTextAndType(cfg.getAsJsonArray("nodes"),
                "COMPUTE WS-C = 1 / 0", "COMPUTE");
        assertNotNull(computeNode);
        JsonObject metadata = computeNode.getAsJsonObject("metadata");
        assertFalse(metadata.has("assignment_facts"));
        assertFalse(metadata.has("folded_value_facts"));

        JsonObject diagnostic = firstFoldingDiagnostic(computeNode);
        assertEquals("FOLD_UNSAFE_DIVIDE_BY_ZERO", diagnostic.get("code").getAsString());
        assertEquals("warning", diagnostic.get("severity").getAsString());
        assertEquals("unsafe", diagnostic.get("category").getAsString());
        assertEquals("/0", diagnostic.get("construct").getAsString());
        assertEquals("Division by zero cannot be folded safely.", diagnostic.get("message").getAsString());
    }

    @Test
    void foldsParenthesesUnaryDecimalAndExactDivisionWithoutBinaryRounding() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        assertFoldedNumeric(nodes, "COMPUTE WS-E = (1 + 2) * -3", "WS-E", "(1+2)*-3",
                "-9", "-9", 0, 1, "NEGATIVE");
        assertFoldedNumeric(nodes, "COMPUTE WS-F = 1.20 + 2.30", "WS-F", "1.20+2.30",
                "3.50", "3.50", 2, 3, "POSITIVE");
        assertFoldedNumeric(nodes, "COMPUTE WS-G = 1 / 4", "WS-G", "1/4",
                "0.25", "0.25", 2, 2, "POSITIVE");
        assertFoldedNumeric(nodes, "COMPUTE WS-K = 10 - 3", "WS-K", "10-3",
                "7", "7", 0, 1, "POSITIVE");
        assertFoldedNumeric(nodes, "COMPUTE WS-L = +4", "WS-L", "+4",
                "4", "4", 0, 1, "POSITIVE");
    }

    @Test
    void reportsNonTerminatingDivisionFigurativeConstantAndExponentiationPrecisely() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        assertFoldingDiagnostic(nodes, "COMPUTE WS-H = 1 / 3", "FOLD_UNSAFE_NON_TERMINATING_DIVISION",
                "warning", "unsafe", "/3", "Non-terminating decimal division cannot be folded exactly.");
        assertFoldingDiagnostic(nodes, "COMPUTE WS-I = ZERO + 1", "FOLD_UNSUPPORTED_FIGURATIVE_CONSTANT",
                "info", "unsupported", "ZERO", "Figurative constant ZERO is not folded in Phase 1.");
        assertFoldingDiagnostic(nodes, "COMPUTE WS-J = 2 ** 3", "FOLD_UNSUPPORTED_EXPONENTIATION",
                "info", "unsupported", "2**3", "Exponentiation is not folded in Phase 1.");
    }

    @Test
    void preservesStatementTextAndCfgShapeForPhaseOneFixture() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");
        JsonArray edges = cfg.getAsJsonArray("edges");

        assertEquals(18, nodes.size());
        assertEquals(17, edges.size());
        assertEquals(List.of(
                "COMPUTE WS-A = 1 + 2",
                "COMPUTE WS-B = WS-A + 1",
                "COMPUTE WS-C = 1 / 0",
                "MOVE 7 TO WS-D",
                "COMPUTE WS-E = (1 + 2) * -3",
                "COMPUTE WS-F = 1.20 + 2.30",
                "COMPUTE WS-G = 1 / 4",
                "COMPUTE WS-H = 1 / 3",
                "COMPUTE WS-I = ZERO + 1",
                "COMPUTE WS-J = 2 ** 3",
                "COMPUTE WS-K = 10 - 3",
                "COMPUTE WS-L = +4"
        ), executableStatementTexts(nodes));

        long nonComputeFoldingMetadataCount = jsonObjects(nodes).stream()
                .filter(node -> !"COMPUTE".equals(node.get("type").getAsString()))
                .filter(node -> node.has("metadata"))
                .map(node -> node.getAsJsonObject("metadata"))
                .filter(metadata -> metadata.has("folded_value_facts") || metadata.has("folding_diagnostics"))
                .count();
        assertEquals(0, nonComputeFoldingMetadataCount);
    }

    @Test
    void writeCfgEmitsStaticValueDataflowSkeletonSidecar() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject dataflow = readJson("constant-folding-phase1.cbl.report/static_analysis/dataflow.json");
        assertEquals("constant-folding-phase1.cbl", dataflow.get("program").getAsString());
        assertEquals("1.0", dataflow.get("schema_version").getAsString());
        assertEquals("static_value_dataflow", dataflow.get("analysis").getAsString());
        assertEquals("0.2", dataflow.get("analysis_version").getAsString());
        assertEquals("paragraph_summary_skeleton", dataflow.get("status").getAsString());

        JsonObject config = dataflow.getAsJsonObject("config");
        assertFalse(config.get("constant_propagation_enabled").getAsBoolean());
        assertFalse(config.get("path_sensitive_targets_enabled").getAsBoolean());
        assertTrue(config.get("paragraph_summaries_enabled").getAsBoolean());
        assertFalse(config.get("alias_analysis_enabled").getAsBoolean());
        assertEquals("paragraph_summary_skeleton", config.get("mode").getAsString());

        JsonObject summary = dataflow.getAsJsonObject("summary");
        assertEquals(18, summary.get("node_count").getAsInt());
        assertEquals(17, summary.get("edge_count").getAsInt());
        assertEquals(0, summary.get("entry_constant_count").getAsInt());
        assertEquals(0, summary.get("exit_constant_count").getAsInt());
        assertEquals(0, summary.get("kill_count").getAsInt());
        assertEquals(0, summary.get("diagnostic_count").getAsInt());
        assertEquals(0, summary.get("alias_set_count").getAsInt());
        assertEquals(1, summary.get("paragraph_summary_count").getAsInt());

        assertEquals(0, dataflow.getAsJsonArray("diagnostics").size());
        assertEquals(0, dataflow.getAsJsonObject("alias_sets").size());
        assertEquals(1, dataflow.getAsJsonObject("paragraph_summaries").size());
        assertEquals(18, dataflow.getAsJsonObject("node_states").size());
    }

    @Test
    void dataflowSkeletonEmitsDeterministicParagraphSummary() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonObject dataflow = readJson("constant-folding-phase1.cbl.report/static_analysis/dataflow.json");
        JsonObject paragraphNode = findNodeByOriginalTextAndType(cfg.getAsJsonArray("nodes"),
                "MAIN-PARA.\n           COMPUTE WS-A = 1 + 2\n           COMPUTE WS-B = WS-A + 1\n           COMPUTE WS-C = 1 / 0\n           MOVE 7 TO WS-D\n           COMPUTE WS-E = (1 + 2) * -3\n           COMPUTE WS-F = 1.20 + 2.30\n           COMPUTE WS-G = 1 / 4\n           COMPUTE WS-H = 1 / 3\n           COMPUTE WS-I = ZERO + 1\n           COMPUTE WS-J = 2 ** 3\n           COMPUTE WS-K = 10 - 3\n           COMPUTE WS-L = +4\n           GOBACK.",
                "PARAGRAPH");

        JsonObject summary = dataflow.getAsJsonObject("paragraph_summaries").getAsJsonObject("MAIN-PARA");
        assertEquals("MAIN-PARA", summary.get("paragraph").getAsString());
        assertEquals(paragraphNode.get("id").getAsString(), summary.get("paragraph_node_id").getAsString());
        assertEquals(containedParagraphNodeIds(cfg.getAsJsonArray("nodes"), paragraphNode),
                jsonArrayStrings(summary.getAsJsonArray("node_ids")));
        assertEquals(List.of("WS-A"), jsonArrayStrings(summary.getAsJsonArray("variables_read_direct")));
        assertEquals(List.of("WS-A", "WS-B", "WS-C", "WS-D", "WS-E", "WS-F",
                        "WS-G", "WS-H", "WS-I", "WS-J", "WS-K", "WS-L"),
                jsonArrayStrings(summary.getAsJsonArray("variables_modified_direct")));
        assertEquals(jsonArrayStrings(summary.getAsJsonArray("variables_read_direct")),
                jsonArrayStrings(summary.getAsJsonArray("variables_read_transitive")));
        assertEquals(jsonArrayStrings(summary.getAsJsonArray("variables_modified_direct")),
                jsonArrayStrings(summary.getAsJsonArray("variables_modified_transitive")));
        assertEquals(0, summary.getAsJsonArray("calls_paragraphs").size());
        assertEquals(0, summary.getAsJsonArray("called_programs").size());
        assertEquals(0, summary.getAsJsonArray("external_side_effects").size());
        assertEquals(0, summary.getAsJsonArray("unsupported_constructs").size());
        assertFalse(summary.get("cycle_detected").getAsBoolean());
        assertEquals("complete_no_paragraph_calls", summary.get("transitive_summary_status").getAsString());
        assertEquals("java_static_value_dataflow", summary.get("summary_source").getAsString());
    }

    @Test
    void paragraphSummaryRecordsCallsSideEffectsAndDeferredTransitiveExpansion() throws IOException {
        new TestTaskRunner("metadata-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject dataflow = readJson("metadata-features.cbl.report/static_analysis/dataflow.json");
        JsonObject paragraphSummaries = dataflow.getAsJsonObject("paragraph_summaries");
        assertEquals(4, paragraphSummaries.size());

        JsonObject main = paragraphSummaries.getAsJsonObject("MAIN-PARA");
        assertEquals(List.of("LOOP-PARA"), jsonArrayStrings(main.getAsJsonArray("calls_paragraphs")));
        assertEquals(List.of("DYNPROG", "SUBPROG"), jsonArrayStrings(main.getAsJsonArray("called_programs")));
        assertEquals(List.of("ACCEPT", "CALL", "CLOSE", "OPEN", "READ", "WRITE"),
                jsonArrayStrings(main.getAsJsonArray("external_side_effects")));
        assertEquals("not_computed_perform_targets_present", main.get("transitive_summary_status").getAsString());
        assertEquals(0, main.getAsJsonArray("variables_read_transitive").size());
        assertEquals(0, main.getAsJsonArray("variables_modified_transitive").size());

        JsonObject unsupported = main.getAsJsonArray("unsupported_constructs").get(0).getAsJsonObject();
        assertEquals("PARAGRAPH_TRANSITIVE_SUMMARY_NOT_COMPUTED", unsupported.get("code").getAsString());
        assertEquals("info", unsupported.get("severity").getAsString());
        assertEquals("deferred", unsupported.get("category").getAsString());
        assertEquals(List.of("LOOP-PARA"), jsonArrayStrings(unsupported.getAsJsonArray("calls_paragraphs")));

        JsonObject loop = paragraphSummaries.getAsJsonObject("LOOP-PARA");
        assertEquals("complete_no_paragraph_calls", loop.get("transitive_summary_status").getAsString());
        assertEquals(0, loop.getAsJsonArray("unsupported_constructs").size());
    }

    @Test
    void dataflowSkeletonReferencesCfgNodeIdsWithoutPropagatedFacts() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonObject dataflow = readJson("constant-folding-phase1.cbl.report/static_analysis/dataflow.json");
        List<String> cfgNodeIds = jsonObjects(cfg.getAsJsonArray("nodes")).stream()
                .map(node -> node.get("id").getAsString())
                .toList();
        List<String> dataflowNodeIds = dataflow.getAsJsonObject("node_states").entrySet().stream()
                .map(Map.Entry::getKey)
                .toList();
        assertEquals(cfgNodeIds, dataflowNodeIds);

        String computeNodeId = findNodeByOriginalTextAndType(cfg.getAsJsonArray("nodes"),
                "COMPUTE WS-A = 1 + 2", "COMPUTE").get("id").getAsString();
        JsonObject computeState = dataflow.getAsJsonObject("node_states").getAsJsonObject(computeNodeId);
        assertEquals(0, computeState.getAsJsonObject("entry_constants").size());
        assertEquals(0, computeState.getAsJsonObject("exit_constants").size());
        assertEquals(0, computeState.getAsJsonArray("kills").size());
        assertEquals(0, computeState.getAsJsonArray("diagnostics").size());
    }

    @Test
    void leavesMoveAssignmentFactsUnchangedAndDoesNotEmitFoldingMetadata() throws IOException {
        new TestTaskRunner("constant-folding-phase1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("constant-folding-phase1.cbl.report/cfg/cfg-constant-folding-phase1.cbl.json");
        JsonObject moveNode = findNodeByOriginalTextAndType(cfg.getAsJsonArray("nodes"), "MOVE 7 TO WS-D", "MOVE");
        assertNotNull(moveNode);
        JsonObject metadata = moveNode.getAsJsonObject("metadata");
        assertTrue(metadata.has("assignment_facts"));
        assertFalse(metadata.has("folded_value_facts"));
        assertFalse(metadata.has("folding_diagnostics"));

        JsonObject assignment = jsonObjects(metadata.getAsJsonArray("assignment_facts")).get(0);
        assertEquals("WS-D", assignment.get("target_variable").getAsString());
        assertEquals("7", assignment.get("source_value").getAsString());
        assertEquals("literal", assignment.get("source_kind").getAsString());
        assertEquals("MOVE", assignment.get("statement_type").getAsString());
        assertEquals("java_move_literal", assignment.get("provenance_source").getAsString());
        assertEquals("MAIN-PARA", assignment.get("paragraph").getAsString());
    }

    @Test
    void exportsAssignmentFactsForFigurativeConstantsAsLiterals() throws IOException {
        new TestTaskRunner("optimization-stage1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("optimization-stage1.cbl.report/cfg/cfg-optimization-stage1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        // Locks current behaviour: figurative constants SPACES/ZEROS are treated as
        // literals by the MoveFlowNode gate and emit assignment_facts. If this is later
        // changed (e.g., to flag them as figurative_constant rather than literal), this
        // test must change explicitly so the decision is deliberate and reviewable.
        assertTrue(hasAssignmentFact(nodes, "WS-FIG-A", "SPACES",
                "D1-MOVE-FIGURATIVE-PARA", "java_move_literal"));
        assertTrue(hasAssignmentFact(nodes, "WS-FIG-B", "ZEROS",
                "D1-MOVE-FIGURATIVE-PARA", "java_move_literal"));
    }

    @Test
    void exportsNoAssignmentFactsForSetEightyEightCondition() throws IOException {
        new TestTaskRunner("metadata-features.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("metadata-features.cbl.report/cfg/cfg-metadata-features.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        JsonObject setNode = findNodeByOriginalText(nodes, "SET SWITCH-ON TO TRUE");
        assertNotNull(setNode);
        assertFalse(setNode.has("metadata") && setNode.getAsJsonObject("metadata").has("assignment_facts"),
                "SET to an 88-level condition name must not emit assignment_facts; "
                        + "the SetFlowNode gate requires sendingField().literal() != null");
    }

    @Test
    void exportsChainedCallResolutionEachUsingItsPrecedingMoveLiteralWithMediumConfidence() throws IOException {
        new TestTaskRunner("optimization-stage1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("optimization-stage1.cbl.report/cfg/cfg-optimization-stage1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        // D2-CHAINED-CALL-PARA: MOVE 'PROG-A', CALL, MOVE 'PROG-B', CALL.
        // Both CALLs are CALL WS-CALL-CH. Within a single paragraph, walk order
        // matches source order, so the latest-literal map carries 'PROG-A' to the
        // first CALL and 'PROG-B' to the second.
        assertTrue(hasResolvedCall(nodes, "WS-CALL-CH", "PROG-A",
                "inferred_literal_assignment", "medium"));
        assertTrue(hasResolvedCall(nodes, "WS-CALL-CH", "PROG-B",
                "inferred_literal_assignment", "medium"));
    }

    @Test
    void exportsCallTargetSourceUnresolvedWhenWalkOrderHasNoPriorLiteralForTarget() throws IOException {
        new TestTaskRunner("optimization-stage1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("optimization-stage1.cbl.report/cfg/cfg-optimization-stage1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        // D2-CALL-AFTER-SQL-PARA: even though MOVE 'PROG-C' precedes the CALL in
        // *source* order, the SerialisableCFGGraphCollector walks nodes in CFG
        // emission order (not source order), and the CALL is annotated before the
        // MOVE has populated latestLiteralAssignments. Result: unresolved_identifier
        // with confidence low. This locks the "not path-sensitive" guarantee.
        assertTrue(hasResolvedCall(nodes, "WS-CALL-SQ", "WS-CALL-SQ",
                "unresolved_identifier", "low"));

        // D2-CALL-IN-IF-PARA: CALL inside an IF with no MOVE for WS-CALL-IF anywhere
        // in the program. The resolved field echoes the identifier itself.
        assertTrue(hasResolvedCall(nodes, "WS-CALL-IF", "WS-CALL-IF",
                "unresolved_identifier", "low"));
    }

    @Test
    void exportsChainedXctlResolutionEachUsingItsPrecedingMoveLiteralWithMediumConfidence() throws IOException {
        new TestTaskRunner("optimization-stage1.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_CFG);

        JsonObject cfg = readJson("optimization-stage1.cbl.report/cfg/cfg-optimization-stage1.cbl.json");
        JsonArray nodes = cfg.getAsJsonArray("nodes");

        // D2-XCTL-CHAINED-PARA: MOVE 'TARGET-X', XCTL, MOVE 'TARGET-Y', XCTL.
        // Same chained semantics as the CALL case but via CICS XCTL.
        assertTrue(hasResolvedCicsTarget(nodes, "WS-CALL-XC", "TARGET-X",
                "inferred_literal_assignment", "medium"));
        assertTrue(hasResolvedCicsTarget(nodes, "WS-CALL-XC", "TARGET-Y",
                "inferred_literal_assignment", "medium"));
        assertTrue(hasCicsOperation(nodes, "XCTL", "PROGRAM", "TARGET-X"));
        assertTrue(hasCicsOperation(nodes, "XCTL", "PROGRAM", "TARGET-Y"));
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

    private boolean hasResolvedCicsTarget(JsonArray nodes, String targetIdentifier, String resolvedTarget,
                                          String targetSource, String confidence) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .anyMatch(metadata -> metadata.has("cics_target_identifier")
                        && targetIdentifier.equals(metadata.get("cics_target_identifier").getAsString())
                        && metadata.has("resolved_cics_target")
                        && resolvedTarget.equals(metadata.get("resolved_cics_target").getAsString())
                        && metadata.has("cics_target_source")
                        && targetSource.equals(metadata.get("cics_target_source").getAsString())
                        && metadata.has("cics_dynamic_resolution_confidence")
                        && confidence.equals(metadata.get("cics_dynamic_resolution_confidence").getAsString()));
    }

    private boolean hasCicsOperation(JsonArray nodes, String command, String targetKind, String target) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .filter(metadata -> metadata.has("cics_operation"))
                .map(metadata -> metadata.get("cics_operation").getAsJsonObject())
                .anyMatch(operation -> command.equals(operation.get("command").getAsString())
                        && targetKind.equals(operation.get("target_kind").getAsString())
                        && target.equals(operation.get("target").getAsString()));
    }

    private boolean hasResolvedCall(JsonArray nodes, String callTarget, String resolvedTarget,
                                    String targetSource, String confidence) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .anyMatch(metadata -> metadata.has("call_target")
                        && callTarget.equals(metadata.get("call_target").getAsString())
                        && metadata.has("resolved_call_target")
                        && resolvedTarget.equals(metadata.get("resolved_call_target").getAsString())
                        && metadata.has("call_target_source")
                        && targetSource.equals(metadata.get("call_target_source").getAsString())
                        && metadata.has("dynamic_call_resolution_confidence")
                        && confidence.equals(metadata.get("dynamic_call_resolution_confidence").getAsString()));
    }

    private boolean hasNodeSourceLocation(JsonArray nodes) {
        return jsonObjects(nodes).stream()
                .anyMatch(node -> node.has("sourceLine")
                        && node.has("sourceColumn")
                        && node.has("sourceEndLine")
                        && node.has("sourceEndColumn")
                        && node.has("lineOrigin")
                        && "parser_source".equals(node.get("lineOrigin").getAsString())
                        && node.has("sourceLocationSource")
                        && "java_parser_token".equals(node.get("sourceLocationSource").getAsString()));
    }

    private boolean hasEdgeSourceContract(JsonArray edges) {
        return jsonObjects(edges).stream()
                .anyMatch(edge -> edge.has("fromLabel")
                        && edge.has("toLabel")
                        && edge.has("evidence")
                        && edge.has("sourceLine")
                        && edge.has("sourceColumn")
                        && edge.has("lineOrigin")
                        && "parser_source".equals(edge.get("lineOrigin").getAsString()));
    }

    private boolean hasConditionedEdge(JsonArray edges, String condition) {
        return jsonObjects(edges).stream()
                .anyMatch(edge -> edge.has("condition")
                        && condition.equals(edge.get("condition").getAsString())
                        && edge.has("fromLabel")
                        && edge.has("toLabel"));
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

    private boolean hasInitializeFact(JsonArray nodes, String targetVariable, String category,
                                      String sourceValue, String paragraph) {
        return initializeFacts(nodes).stream()
                .filter(fact -> targetVariable.equals(fact.get("target_variable").getAsString())
                        && paragraph.equals(fact.get("paragraph").getAsString()))
                .filter(fact -> fact.has("replacements"))
                .flatMap(fact -> jsonObjects(fact.getAsJsonArray("replacements")).stream())
                .anyMatch(replacement -> category.equals(replacement.get("category").getAsString())
                        && sourceValue.equals(replacement.get("source_value").getAsString())
                        && "literal".equals(replacement.get("source_kind").getAsString()));
    }

    private boolean hasInitializeReplacementSource(JsonArray nodes, String targetVariable, String category,
                                                   String sourceVariable) {
        return initializeFacts(nodes).stream()
                .filter(fact -> targetVariable.equals(fact.get("target_variable").getAsString()))
                .filter(fact -> fact.has("replacements"))
                .flatMap(fact -> jsonObjects(fact.getAsJsonArray("replacements")).stream())
                .anyMatch(replacement -> category.equals(replacement.get("category").getAsString())
                        && sourceVariable.equals(replacement.get("source_variable").getAsString())
                        && "identifier".equals(replacement.get("source_kind").getAsString()));
    }

    private List<JsonObject> initializeFacts(JsonArray nodes) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("metadata"))
                .map(node -> node.get("metadata").getAsJsonObject())
                .filter(metadata -> metadata.has("initialize_facts"))
                .flatMap(metadata -> jsonObjects(metadata.getAsJsonArray("initialize_facts")).stream())
                .toList();
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

    private JsonObject findNodeByOriginalTextAndType(JsonArray nodes, String text, String type) {
        return jsonObjects(nodes).stream()
                .filter(node -> node.has("type") && type.equals(node.get("type").getAsString()))
                .filter(node -> node.has("originalText") && node.get("originalText").getAsString().contains(text))
                .findFirst()
                .orElse(null);
    }

    private List<String> containedParagraphNodeIds(JsonArray nodes, JsonObject paragraphNode) {
        int startLine = paragraphNode.get("sourceLine").getAsInt();
        int endLine = paragraphNode.get("sourceEndLine").getAsInt();
        String paragraphNodeId = paragraphNode.get("id").getAsString();
        return jsonObjects(nodes).stream()
                .filter(node -> !paragraphNodeId.equals(node.get("id").getAsString()))
                .filter(node -> node.has("sourceLine") && node.has("sourceEndLine"))
                .filter(node -> node.get("sourceLine").getAsInt() >= startLine)
                .filter(node -> node.get("sourceEndLine").getAsInt() <= endLine)
                .filter(node -> !List.of("PROCEDURE_DIVISION_BODY", "PARAGRAPHS", "PARAGRAPH")
                        .contains(node.get("type").getAsString()))
                .map(node -> node.get("id").getAsString())
                .toList();
    }

    private List<String> jsonArrayStrings(JsonArray array) {
        List<String> values = new ArrayList<>();
        array.forEach(element -> values.add(element.getAsString()));
        return values;
    }

    private JsonObject firstFoldedValueFact(JsonObject node) {
        JsonObject metadata = node.getAsJsonObject("metadata");
        assertNotNull(metadata);
        assertTrue(metadata.has("folded_value_facts"));
        assertEquals(1, metadata.getAsJsonArray("folded_value_facts").size());
        return metadata.getAsJsonArray("folded_value_facts").get(0).getAsJsonObject();
    }

    private JsonObject firstFoldingDiagnostic(JsonObject node) {
        JsonObject metadata = node.getAsJsonObject("metadata");
        assertNotNull(metadata);
        assertTrue(metadata.has("folding_diagnostics"));
        assertEquals(1, metadata.getAsJsonArray("folding_diagnostics").size());
        return metadata.getAsJsonArray("folding_diagnostics").get(0).getAsJsonObject();
    }

    private List<String> executableStatementTexts(JsonArray nodes) {
        return jsonObjects(nodes).stream()
                .filter(node -> List.of("COMPUTE", "MOVE", "GOBACK").contains(node.get("type").getAsString()))
                .map(node -> node.get("originalText").getAsString())
                .toList();
    }

    private void assertFoldedNumeric(JsonArray nodes, String originalText, String targetVariable,
                                     String originalExpression, String foldedExpression, String decimal,
                                     int scale, int precision, String sign) {
        JsonObject computeNode = findNodeByOriginalTextAndType(nodes, originalText, "COMPUTE");
        assertNotNull(computeNode);
        JsonObject metadata = computeNode.getAsJsonObject("metadata");
        assertFalse(metadata.has("assignment_facts"));

        JsonObject fact = firstFoldedValueFact(computeNode);
        assertEquals(targetVariable, fact.get("target_variable").getAsString());
        assertEquals(originalExpression, fact.get("original_expression").getAsString());
        assertEquals(foldedExpression, fact.get("folded_expression").getAsString());

        JsonObject value = fact.getAsJsonObject("value");
        assertEquals("CONSTANT", value.get("state").getAsString());
        assertEquals("NUMERIC", value.get("kind").getAsString());
        assertEquals(decimal, value.get("normalized_value").getAsString());
        assertEquals(decimal, value.get("display_value").getAsString());

        JsonObject numeric = value.getAsJsonObject("numeric");
        assertEquals(decimal, numeric.get("decimal").getAsString());
        assertEquals(scale, numeric.get("scale").getAsInt());
        assertEquals(precision, numeric.get("precision").getAsInt());
        assertEquals(sign, numeric.get("sign").getAsString());
    }

    private void assertFoldingDiagnostic(JsonArray nodes, String originalText, String code, String severity,
                                         String category, String construct, String message) {
        JsonObject computeNode = findNodeByOriginalTextAndType(nodes, originalText, "COMPUTE");
        assertNotNull(computeNode);
        JsonObject metadata = computeNode.getAsJsonObject("metadata");
        assertFalse(metadata.has("assignment_facts"));
        assertFalse(metadata.has("folded_value_facts"));

        JsonObject diagnostic = firstFoldingDiagnostic(computeNode);
        assertEquals(code, diagnostic.get("code").getAsString());
        assertEquals(severity, diagnostic.get("severity").getAsString());
        assertEquals(category, diagnostic.get("category").getAsString());
        assertEquals(construct, diagnostic.get("construct").getAsString());
        assertEquals(message, diagnostic.get("message").getAsString());
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
