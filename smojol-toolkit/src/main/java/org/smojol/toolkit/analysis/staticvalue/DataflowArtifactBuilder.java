package org.smojol.toolkit.analysis.staticvalue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.TreeSet;

public class DataflowArtifactBuilder {
    private static final String SOURCE_ARTIFACT = "static_analysis/dataflow.json";

    public Map<String, Object> compactSummary(DataflowAnalysisResult result) {
        Map<String, Object> compact = new LinkedHashMap<>();
        compact.put("schema_version", result.schemaVersion());
        compact.put("analysis_version", result.analysisVersion());
        compact.put("source_artifact", SOURCE_ARTIFACT);
        compact.put("summary", result.summary());
        compact.put("node_states", compactNodeStates(result.nodeStates()));
        compact.put("rag_compacted", true);
        return compact;
    }

    public Map<String, Object> ruleCompactedSidecar(DataflowAnalysisResult result) {
        KillRuleIndex killRuleIndex = killRuleIndex(result.nodeStates());
        Map<String, Object> sidecar = new LinkedHashMap<>();
        sidecar.put("program", result.program());
        sidecar.put("schema_version", result.schemaVersion());
        sidecar.put("analysis", result.analysis());
        sidecar.put("analysis_version", result.analysisVersion());
        sidecar.put("status", result.status());
        sidecar.put("config", result.config());
        sidecar.put("storage_model", "kill_rule_compacted");
        sidecar.put("materialized_kill_count", result.summary().get("kill_count"));
        sidecar.put("kill_rule_count", killRuleIndex.rules().size());
        sidecar.put("summary", result.summary());
        sidecar.put("node_states", compactedRawNodeStates(result.nodeStates(), killRuleIndex.refsByNode()));
        sidecar.put("kill_rules", killRuleIndex.rules());
        sidecar.put("alias_sets", result.aliasSets());
        sidecar.put("paragraph_summaries", result.paragraphSummaries());
        sidecar.put("diagnostics", result.diagnostics());
        return sidecar;
    }

    private Map<String, Object> compactNodeStates(Map<String, DataflowNodeState> nodeStates) {
        Map<String, Object> compact = new LinkedHashMap<>();
        for (String nodeId : nodeStates.keySet()) {
            DataflowNodeState state = nodeStates.get(nodeId);
            Map<String, Object> entryConstants = compactConstants(state.entryConstants());
            Map<String, Object> exitConstants = compactConstants(state.exitConstants());
            List<Map<String, Object>> diagnostics = state.diagnostics();
            if (entryConstants.isEmpty() && exitConstants.isEmpty()
                    && (diagnostics == null || diagnostics.isEmpty())) {
                continue;
            }
            Map<String, Object> compactState = new LinkedHashMap<>();
            compactState.put("entry_constants", entryConstants);
            compactState.put("exit_constants", exitConstants);
            compactState.put("diagnostics", diagnostics == null ? List.of() : diagnostics);
            compact.put(nodeId, compactState);
        }
        return compact;
    }

    private Map<String, Object> compactedRawNodeStates(Map<String, DataflowNodeState> nodeStates,
                                                       Map<String, List<String>> refsByNode) {
        Map<String, Object> compact = new LinkedHashMap<>();
        for (String nodeId : nodeStates.keySet()) {
            DataflowNodeState state = nodeStates.get(nodeId);
            Map<String, Object> compactState = new LinkedHashMap<>();
            compactState.put("entry_constants", state.entryConstants());
            compactState.put("exit_constants", state.exitConstants());
            compactState.put("kill_rule_refs", refsByNode.getOrDefault(nodeId, List.of()));
            compactState.put("diagnostics", state.diagnostics());
            compact.put(nodeId, compactState);
        }
        return compact;
    }

    private Map<String, Object> compactConstants(Map<String, Object> values) {
        Map<String, Object> compact = new LinkedHashMap<>();
        if (values == null) return compact;
        for (String variable : new TreeSet<>(values.keySet())) {
            Map<String, Object> value = mapValue(values.get(variable));
            Map<String, Object> constant = compactConstant(variable, value);
            if (!constant.isEmpty()) compact.put(variable, constant);
        }
        return compact;
    }

    private Map<String, Object> compactConstant(String variable, Map<String, Object> value) {
        Map<String, Object> compact = new LinkedHashMap<>();
        if (!"CONSTANT".equals(stringValue(value.get("state")))) return compact;
        String kind = stringValue(value.get("kind")).toUpperCase(Locale.ROOT);
        if (!"NUMERIC".equals(kind) && !"ALPHANUMERIC".equals(kind)) return compact;
        String normalized = stringValue(value.get("normalized_value"));
        if (normalized.isBlank()) normalized = stringValue(value.get("display_value"));
        normalized = normalized.trim();
        if (normalized.isBlank()) return compact;
        compact.put("variable", variable);
        compact.put("kind", kind);
        compact.put("normalized_value", normalized);
        compact.put("display_value", stringValue(value.getOrDefault("display_value", normalized)));
        Map<String, Object> numeric = mapValue(value.get("numeric"));
        if (!numeric.isEmpty()) {
            Map<String, Object> compactNumeric = new LinkedHashMap<>();
            for (String key : List.of("decimal", "scale", "precision", "sign")) {
                if (numeric.get(key) != null) compactNumeric.put(key, numeric.get(key));
            }
            if (!compactNumeric.isEmpty()) compact.put("numeric", compactNumeric);
        }
        return compact;
    }

    private KillRuleIndex killRuleIndex(Map<String, DataflowNodeState> nodeStates) {
        Map<String, KillRuleAccumulator> bySignature = new TreeMap<>();
        Map<String, List<String>> refsByNode = new LinkedHashMap<>();
        for (String nodeId : nodeStates.keySet()) {
            List<String> refs = new ArrayList<>();
            for (Map<String, Object> kill : nodeStates.get(nodeId).kills()) {
                String signature = killSignature(kill);
                KillRuleAccumulator accumulator = bySignature.computeIfAbsent(signature,
                        ignored -> new KillRuleAccumulator(rulePayload(kill)));
                Object variable = kill.get("variable");
                if (!usesAliasSetReference(kill) && variable instanceof String variableName && !variableName.isBlank()) {
                    accumulator.killedVariables().add(variableName);
                }
                refs.add(signature);
            }
            refsByNode.put(nodeId, refs);
        }

        Map<String, Object> rules = new LinkedHashMap<>();
        Map<String, String> idsBySignature = new TreeMap<>();
        int index = 1;
        for (String signature : bySignature.keySet()) {
            String id = "K" + String.format("%06d", index++);
            idsBySignature.put(signature, id);
            Map<String, Object> rule = new LinkedHashMap<>(bySignature.get(signature).payload());
            if (!bySignature.get(signature).killedVariables().isEmpty()) {
                rule.put("killed_variables", bySignature.get(signature).killedVariables().stream().toList());
            }
            rules.put(id, rule);
        }

        Map<String, List<String>> resolvedRefs = new LinkedHashMap<>();
        for (Map.Entry<String, List<String>> entry : refsByNode.entrySet()) {
            resolvedRefs.put(entry.getKey(), entry.getValue().stream()
                    .map(idsBySignature::get)
                    .filter(Objects::nonNull)
                    .distinct()
                    .toList());
        }
        return new KillRuleIndex(rules, resolvedRefs);
    }

    private String killSignature(Map<String, Object> kill) {
        return rulePayload(kill).toString();
    }

    private Map<String, Object> rulePayload(Map<String, Object> kill) {
        Map<String, Object> payload = new TreeMap<>();
        for (Map.Entry<String, Object> entry : kill.entrySet()) {
            if ("variable".equals(entry.getKey())) continue;
            payload.put(entry.getKey(), entry.getValue());
        }
        if (usesAliasSetReference(kill)) {
            payload.put("killed_alias_set_id", kill.get("alias_set_id"));
        }
        return payload;
    }

    private boolean usesAliasSetReference(Map<String, Object> kill) {
        return "ALIAS_CONSERVATIVE_KILL".equals(kill.get("code"))
                && kill.get("alias_set_id") instanceof String aliasSetId
                && !aliasSetId.isBlank();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> mapValue(Object raw) {
        if (!(raw instanceof Map<?, ?> rawMap)) return Map.of();
        Map<String, Object> value = new LinkedHashMap<>();
        rawMap.forEach((key, element) -> value.put(String.valueOf(key), element));
        return value;
    }

    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private record KillRuleAccumulator(Map<String, Object> payload, TreeSet<String> killedVariables) {
        private KillRuleAccumulator(Map<String, Object> payload) {
            this(payload, new TreeSet<>());
        }
    }

    private record KillRuleIndex(Map<String, Object> rules, Map<String, List<String>> refsByNode) {
    }
}
