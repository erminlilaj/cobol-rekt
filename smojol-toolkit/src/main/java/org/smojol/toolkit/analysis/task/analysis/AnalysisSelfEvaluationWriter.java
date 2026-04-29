package org.smojol.toolkit.analysis.task.analysis;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

public class AnalysisSelfEvaluationWriter {
    private static final Logger LOGGER = Logger.getLogger(AnalysisSelfEvaluationWriter.class.getName());
    private static final String SELF_EVALUATION_FILENAME = "analysis_self_evaluation.json";

    public static void write(String program, String analysisMode, Path reportDir, Map<String, Path> artifacts) {
        Path outputPath = reportDir.resolve(SELF_EVALUATION_FILENAME).toAbsolutePath().normalize();
        try {
            JsonObject health = readObject(reportDir.resolve("analysis_health.json"));
            JsonObject cfg = readObject(artifacts.get("cfg"));
            JsonObject data = readObject(artifacts.get("data_structures"));

            JsonObject root = new JsonObject();
            root.addProperty("schema_version", "1.0");
            root.addProperty("program", program);
            root.addProperty("analysis_mode", analysisMode);
            boolean baseSucceeded = !health.has("base_analysis_succeeded")
                    || health.get("base_analysis_succeeded").getAsBoolean();
            root.addProperty("base_analysis_succeeded", baseSucceeded);
            root.add("artifact_presence", artifactPresence(artifacts));
            JsonObject primaryFailure = object(health, "primary_failure");
            if (primaryFailure.size() > 0) root.add("primary_failure", primaryFailure);

            Evaluation evaluation = new Evaluation();
            JsonObject cfgMetrics = cfgMetrics(cfg, evaluation);
            JsonObject dataMetrics = dataMetrics(data, health, evaluation);
            root.add("cfg_metrics", cfgMetrics);
            root.add("data_metrics", dataMetrics);
            root.add("dialect_metrics", dialectMetrics(cfg, evaluation));
            root.add("semantic_coverage", semanticCoverage(cfgMetrics, evaluation));

            if (health.has("failed_tasks") && health.get("failed_tasks").isJsonArray()
                    && health.getAsJsonArray("failed_tasks").size() > 0) {
                evaluation.warn("TASK_FAILURE", "high", "One or more Java analysis tasks failed");
            }
            if (primaryFailure.has("diagnostic_code")) {
                evaluation.warn(primaryFailure.get("diagnostic_code").getAsString(), "high",
                        string(primaryFailure, "message"));
            }
            if (!baseSucceeded) evaluation.warn("BASE_ANALYSIS_FAILED", "critical", "Base analysis failed; downstream artifacts may be absent");

            Score score = score(baseSucceeded, cfgMetrics, dataMetrics, evaluation);
            root.add("warnings", evaluation.warnings);
            root.addProperty("confidence_score", score.value());
            root.addProperty("confidence_label", score.label());

            Files.createDirectories(outputPath.getParent());
            Files.writeString(outputPath, new GsonBuilder().setPrettyPrinting().create().toJson(root));
            LOGGER.info("Analysis self-evaluation written to " + outputPath);
        } catch (Exception e) {
            LOGGER.warning("Failed to write analysis self-evaluation: " + e.getMessage());
        }
    }

    private static JsonObject artifactPresence(Map<String, Path> artifacts) {
        JsonObject presence = new JsonObject();
        artifacts.forEach((name, path) -> presence.addProperty(name, path != null && Files.exists(path)));
        return presence;
    }

    private static JsonObject cfgMetrics(JsonObject cfg, Evaluation evaluation) {
        JsonObject metrics = new JsonObject();
        JsonArray nodes = array(cfg, "nodes");
        JsonArray edges = array(cfg, "edges");
        metrics.addProperty("node_count", nodes.size());
        metrics.addProperty("edge_count", edges.size());

        Map<String, Integer> nodeCounts = new LinkedHashMap<>();
        List<String> genericSamples = new ArrayList<>();
        int dynamicHazards = 0;
        int evaluateCount = 0;
        int evaluateBranchCount = 0;
        int cicsHandleCount = 0;
        int cicsHandleBindingCount = 0;
        int unresolvedTransferCount = 0;

        for (JsonElement element : nodes) {
            if (!element.isJsonObject()) continue;
            JsonObject node = element.getAsJsonObject();
            String type = string(node, "type");
            nodeCounts.merge(type, 1, Integer::sum);
            if ("GENERIC_STATEMENT".equals(type) && genericSamples.size() < 10) {
                genericSamples.add(string(node, "originalText"));
            }
            if ("EVALUATE".equals(type)) evaluateCount++;
            if ("EVALUATE_BRANCH".equals(type)) evaluateBranchCount++;
            JsonObject metadata = object(node, "metadata");
            if (metadata.has("dynamic_control_hazard") && metadata.get("dynamic_control_hazard").getAsBoolean()) {
                dynamicHazards++;
            }
            if (metadata.has("dynamic_call") && metadata.get("dynamic_call").getAsBoolean()) unresolvedTransferCount++;
            if (metadata.has("depending_on")) unresolvedTransferCount++;
            if ("DIALECT".equals(type) && string(node, "originalText").toUpperCase().contains("EXEC CICS HANDLE")) cicsHandleCount++;
            if (metadata.has("handler_bindings") && metadata.get("handler_bindings").isJsonArray()) {
                cicsHandleBindingCount += metadata.getAsJsonArray("handler_bindings").size();
            }
        }

        JsonObject edgeCounts = new JsonObject();
        for (JsonElement element : edges) {
            if (!element.isJsonObject()) continue;
            String edgeType = string(element.getAsJsonObject(), "edgeType");
            edgeCounts.addProperty(edgeType, edgeCounts.has(edgeType) ? edgeCounts.get(edgeType).getAsInt() + 1 : 1);
        }

        int genericCount = nodeCounts.getOrDefault("GENERIC_STATEMENT", 0);
        double genericRatio = nodes.isEmpty() ? 0.0 : round(genericCount * 100.0 / nodes.size());
        metrics.add("node_counts_by_type", new GsonBuilder().create().toJsonTree(nodeCounts));
        metrics.add("edge_counts_by_type", edgeCounts);
        metrics.addProperty("generic_statement_count", genericCount);
        metrics.addProperty("generic_statement_ratio", genericRatio);
        metrics.add("top_generic_samples", new GsonBuilder().create().toJsonTree(genericSamples));
        metrics.addProperty("unresolved_transfer_count", unresolvedTransferCount);
        metrics.addProperty("dynamic_control_hazards", dynamicHazards);
        metrics.addProperty("evaluate_count", evaluateCount);
        metrics.addProperty("evaluate_branch_count", evaluateBranchCount);
        metrics.addProperty("cics_handle_count", cicsHandleCount);
        metrics.addProperty("cics_handle_binding_count", cicsHandleBindingCount);

        if (evaluateCount > 0 && evaluateBranchCount == 0) {
            evaluation.warn("CFG_EVALUATE_BRANCH_MISSING", "high", "EVALUATE nodes exist without exported branch nodes");
        }
        if (genericRatio > 25.0) {
            evaluation.warn("GENERIC_STATEMENT_HIGH_RATIO", "medium", "More than 25% of CFG nodes are generic statements");
        }
        if (dynamicHazards > 0) {
            evaluation.warn("DYNAMIC_CONTROL_FLOW", "medium", "Program contains dynamic control-flow hazards");
        }
        if (cicsHandleCount > 0 && cicsHandleBindingCount == 0) {
            evaluation.warn("CICS_HANDLE_UNPARSED", "medium", "CICS HANDLE text exists without parsed handler bindings");
        }
        return metrics;
    }

    private static JsonObject dataMetrics(JsonObject data, JsonObject health, Evaluation evaluation) {
        JsonObject metrics = new JsonObject();
        DataCounts counts = new DataCounts();
        walkData(data, counts);
        metrics.addProperty("variable_count", counts.variableCount);
        metrics.addProperty("redefines_count", counts.redefinesCount);
        metrics.addProperty("level_88_count", counts.level88Count);
        metrics.addProperty("occurs_count", counts.occursCount);
        metrics.addProperty("occurs_depending_on_count", counts.occursDependingOnCount);
        int skipped = health.has("skipped_variable_count") ? health.get("skipped_variable_count").getAsInt() : 0;
        boolean degraded = health.has("data_structures_degraded") && health.get("data_structures_degraded").getAsBoolean();
        metrics.addProperty("skipped_variable_count", skipped);
        metrics.addProperty("data_structures_degraded", degraded);
        if (degraded) evaluation.warn("DATA_STRUCTURES_DEGRADED", "high", "Data structure builder degraded to partial or null output");
        if (skipped > 0) evaluation.warn("DATA_VARIABLES_SKIPPED", "medium", "One or more data declarations were skipped");
        return metrics;
    }

    private static JsonObject dialectMetrics(JsonObject cfg, Evaluation evaluation) {
        JsonArray nodes = array(cfg, "nodes");
        Map<String, Integer> families = new LinkedHashMap<>();
        int sqlBlocks = 0;
        int unparsedSql = 0;
        int cicsBlocks = 0;
        for (JsonElement element : nodes) {
            if (!element.isJsonObject()) continue;
            JsonObject metadata = object(element.getAsJsonObject(), "metadata");
            if (!metadata.has("dialect_family")) continue;
            String family = metadata.get("dialect_family").getAsString();
            families.merge(family, 1, Integer::sum);
            if ("DB2_SQL".equals(family)) {
                sqlBlocks++;
                if ("UNKNOWN".equals(string(metadata, "sql_operation"))) unparsedSql++;
            }
            if ("CICS".equals(family)) cicsBlocks++;
        }
        if (unparsedSql > 0) evaluation.warn("DIALECT_UNPARSED_EXEC_SQL", "medium", "Some EXEC SQL blocks have unknown operation metadata");
        JsonObject metrics = new JsonObject();
        metrics.add("dialect_families", new GsonBuilder().create().toJsonTree(families));
        metrics.addProperty("sql_block_count", sqlBlocks);
        metrics.addProperty("unparsed_sql_block_count", unparsedSql);
        metrics.addProperty("cics_block_count", cicsBlocks);
        return metrics;
    }

    private static JsonObject semanticCoverage(JsonObject cfgMetrics, Evaluation evaluation) {
        JsonObject coverage = new JsonObject();
        int nodes = cfgMetrics.get("node_count").getAsInt();
        int generic = cfgMetrics.get("generic_statement_count").getAsInt();
        int evaluate = cfgMetrics.get("evaluate_count").getAsInt();
        int branches = cfgMetrics.get("evaluate_branch_count").getAsInt();
        int cicsHandle = cfgMetrics.get("cics_handle_count").getAsInt();
        int cicsBindings = cfgMetrics.get("cics_handle_binding_count").getAsInt();
        coverage.addProperty("typed_node_ratio", nodes == 0 ? 0.0 : round((nodes - generic) * 100.0 / nodes));
        coverage.addProperty("evaluate_branch_coverage", evaluate == 0 ? 100.0 : round(branches * 100.0 / evaluate));
        coverage.addProperty("cics_handle_binding_coverage", cicsHandle == 0 ? 100.0 : round(cicsBindings * 100.0 / cicsHandle));
        return coverage;
    }

    private static Score score(boolean baseSucceeded, JsonObject cfgMetrics, JsonObject dataMetrics, Evaluation evaluation) {
        if (!baseSucceeded) return new Score(0, "none");
        double score = 100.0;
        score -= Math.min(35.0, cfgMetrics.get("generic_statement_ratio").getAsDouble());
        score -= cfgMetrics.get("dynamic_control_hazards").getAsInt() * 5.0;
        score -= dataMetrics.get("skipped_variable_count").getAsInt() * 2.0;
        if (dataMetrics.get("data_structures_degraded").getAsBoolean()) score -= 30.0;
        score -= evaluation.warningCount("high") * 12.0;
        score -= evaluation.warningCount("medium") * 5.0;
        int rounded = (int) Math.max(0, Math.round(score));
        String label = rounded >= 85 ? "high" : rounded >= 65 ? "medium" : rounded >= 35 ? "low" : "none";
        return new Score(rounded, label);
    }

    private static void walkData(JsonElement element, DataCounts counts) {
        if (element == null || element.isJsonNull()) return;
        if (element.isJsonObject()) {
            JsonObject object = element.getAsJsonObject();
            if (object.has("name") && !string(object, "levelNumber").isEmpty()) counts.variableCount++;
            String level = string(object, "levelNumber");
            if ("88".equals(level)) counts.level88Count++;
            String raw = string(object, "rawText").toUpperCase();
            if (raw.contains(" REDEFINES ")) counts.redefinesCount++;
            if (raw.contains(" OCCURS ")) counts.occursCount++;
            if (raw.contains(" DEPENDING ON ")) counts.occursDependingOnCount++;
            object.entrySet().forEach(entry -> walkData(entry.getValue(), counts));
        } else if (element.isJsonArray()) {
            for (JsonElement child : element.getAsJsonArray()) walkData(child, counts);
        }
    }

    private static JsonObject readObject(Path path) throws IOException {
        if (path == null || !Files.exists(path)) return new JsonObject();
        JsonElement element = JsonParser.parseString(Files.readString(path));
        return element != null && element.isJsonObject() ? element.getAsJsonObject() : new JsonObject();
    }

    private static JsonArray array(JsonObject object, String key) {
        return object.has(key) && object.get(key).isJsonArray() ? object.getAsJsonArray(key) : new JsonArray();
    }

    private static JsonObject object(JsonObject object, String key) {
        return object.has(key) && object.get(key).isJsonObject() ? object.getAsJsonObject(key) : new JsonObject();
    }

    private static String string(JsonObject object, String key) {
        if (!object.has(key) || object.get(key) == JsonNull.INSTANCE || object.get(key).isJsonNull()) return "";
        return object.get(key).getAsString();
    }

    private static double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private static class Evaluation {
        private final JsonArray warnings = new JsonArray();

        void warn(String code, String severity, String message) {
            JsonObject warning = new JsonObject();
            warning.addProperty("code", code);
            warning.addProperty("severity", severity);
            warning.addProperty("message", message);
            warnings.add(warning);
        }

        long warningCount(String severity) {
            List<JsonObject> objects = new ArrayList<>();
            warnings.forEach(element -> objects.add(element.getAsJsonObject()));
            return objects.stream().filter(w -> severity.equals(string(w, "severity"))).count();
        }
    }

    private static class DataCounts {
        private int variableCount;
        private int redefinesCount;
        private int level88Count;
        private int occursCount;
        private int occursDependingOnCount;
    }

    private record Score(int value, String label) {
    }
}
