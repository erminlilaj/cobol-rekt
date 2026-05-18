package org.smojol.toolkit.analysis.staticvalue;

import com.mojo.algorithms.domain.FlowNodeType;
import org.smojol.common.ast.SerialisableCFGFlowNode;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public class PathSensitiveTargetResolver {
    private static final String DATAFLOW_ENTRY_CONSTANTS = "static_analysis.dataflow.entry_constants";
    private static final String DATAFLOW_ARTIFACT = "static_analysis/dataflow.json";
    private static final Set<String> SUPPORTED_CICS_ARGUMENTS =
            Set.of("PROGRAM", "FILE", "DATASET", "QUEUE", "QNAME", "MAP", "MAPSET", "TRANSID");

    public void annotateTargets(List<SerialisableCFGFlowNode> nodes, DataflowAnalysisResult dataflow) {
        for (SerialisableCFGFlowNode node : nodes) {
            annotateCallTarget(node, dataflow);
            annotateCicsTarget(node, dataflow);
            annotateCicsArguments(node, dataflow);
        }
    }

    private void annotateCallTarget(SerialisableCFGFlowNode node, DataflowAnalysisResult dataflow) {
        if (node.getType() != FlowNodeType.CALL) return;
        Map<String, Object> metadata = node.getMetadata();
        if (!Boolean.TRUE.equals(metadata.get("dynamic_call"))) return;
        String identifier = callTargetIdentifier(metadata);
        if (identifier == null || identifier.isBlank()) return;
        Map<String, Object> value = entryValue(node, dataflow, canonicalVariable(identifier));
        if (isAlphanumericConstant(value)) {
            annotateCallResolved(metadata, node.getId(), identifier, value);
        } else {
            annotateCallUnresolved(metadata, identifier);
        }
    }

    private void annotateCicsArguments(SerialisableCFGFlowNode node, DataflowAnalysisResult dataflow) {
        if (node.getType() != FlowNodeType.DIALECT) return;
        Map<String, Object> metadata = node.getMetadata();
        Object command = metadata.get("cics_command");
        if (!(command instanceof String)) return;
        Object cicsArguments = metadata.get("cics_arguments");
        if (!(cicsArguments instanceof List<?> argumentList)) return;

        List<Map<String, Object>> pathSensitiveArguments = new ArrayList<>();
        for (Object argument : argumentList) {
            if (!(argument instanceof Map<?, ?> rawArgument)) continue;
            Map<String, Object> cicsArgument = stringKeyMap(rawArgument);
            Object rawName = cicsArgument.get("name");
            Object rawValue = cicsArgument.get("value");
            Object rawSource = cicsArgument.get("value_source");
            if (!(rawName instanceof String name) || !(rawValue instanceof String identifier)
                    || !"identifier".equals(rawSource)) {
                continue;
            }
            String canonicalName = name.toUpperCase(Locale.ROOT);
            if (!SUPPORTED_CICS_ARGUMENTS.contains(canonicalName)) continue;

            Map<String, Object> value = entryValue(node, dataflow, canonicalVariable(identifier));
            pathSensitiveArguments.add(isAlphanumericConstant(value)
                    ? resolvedCicsArgument(node.getId(), canonicalName, identifier, value)
                    : unresolvedCicsArgument(canonicalName, identifier));
        }
        if (!pathSensitiveArguments.isEmpty()) {
            metadata.put("path_sensitive_cics_arguments", pathSensitiveArguments);
        }
    }

    private void annotateCicsTarget(SerialisableCFGFlowNode node, DataflowAnalysisResult dataflow) {
        if (node.getType() != FlowNodeType.DIALECT) return;
        Map<String, Object> metadata = node.getMetadata();
        Object command = metadata.get("cics_command");
        if (!(command instanceof String)) return;
        String identifier = cicsTargetIdentifier(metadata);
        if (identifier == null || identifier.isBlank()) return;
        String targetKind = cicsTargetKind(metadata);
        Map<String, Object> value = entryValue(node, dataflow, canonicalVariable(identifier));
        if (isAlphanumericConstant(value)) {
            annotateCicsResolved(metadata, node.getId(), identifier, targetKind, value);
        } else {
            annotateCicsUnresolved(metadata, identifier, targetKind);
        }
    }

    private String callTargetIdentifier(Map<String, Object> metadata) {
        Object explicitIdentifier = metadata.get("call_target_identifier");
        if (explicitIdentifier instanceof String identifier && !identifier.isBlank()) return identifier;
        Object callTarget = metadata.get("call_target");
        return callTarget instanceof String target ? target : null;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> entryValue(SerialisableCFGFlowNode node, DataflowAnalysisResult dataflow,
                                           String variable) {
        DataflowNodeState nodeState = dataflow.nodeStates().get(node.getId());
        if (nodeState == null) return null;
        Object value = nodeState.entryConstants().get(variable);
        return value instanceof Map<?, ?> rawValue ? (Map<String, Object>) rawValue : null;
    }

    private boolean isAlphanumericConstant(Map<String, Object> value) {
        return value != null
                && "CONSTANT".equals(value.get("state"))
                && "ALPHANUMERIC".equals(value.get("kind"))
                && value.get("normalized_value") instanceof String normalized
                && !normalized.isBlank();
    }

    private String cicsTargetIdentifier(Map<String, Object> metadata) {
        Object explicitIdentifier = metadata.get("cics_target_identifier");
        if (explicitIdentifier instanceof String identifier && !identifier.isBlank()) return identifier;
        Object targetSource = metadata.get("cics_target_source");
        Object target = metadata.get("cics_target");
        if ("identifier".equals(targetSource) && target instanceof String identifier) return identifier;
        return null;
    }

    private String cicsTargetKind(Map<String, Object> metadata) {
        Object targetKind = metadata.get("cics_target_kind");
        return targetKind instanceof String kind && !kind.isBlank() ? kind : "UNKNOWN";
    }

    private void annotateCallResolved(Map<String, Object> metadata, String nodeId, String identifier,
                                      Map<String, Object> value) {
        metadata.put("path_sensitive_call_resolution_status", "resolved");
        metadata.put("path_sensitive_call_target", value.get("normalized_value"));
        metadata.put("path_sensitive_call_target_identifier", canonicalVariable(identifier));
        metadata.put("path_sensitive_call_target_source", DATAFLOW_ENTRY_CONSTANTS);
        metadata.put("path_sensitive_call_confidence", "high");
        metadata.put("path_sensitive_call_evidence", evidence(nodeId, identifier, value, null));
    }

    private void annotateCicsResolved(Map<String, Object> metadata, String nodeId, String identifier,
                                      String targetKind, Map<String, Object> value) {
        metadata.put("path_sensitive_cics_resolution_status", "resolved");
        metadata.put("path_sensitive_cics_target", value.get("normalized_value"));
        metadata.put("path_sensitive_cics_target_identifier", canonicalVariable(identifier));
        metadata.put("path_sensitive_cics_target_kind", targetKind);
        metadata.put("path_sensitive_cics_target_source", DATAFLOW_ENTRY_CONSTANTS);
        metadata.put("path_sensitive_cics_confidence", "high");
        metadata.put("path_sensitive_cics_evidence", evidence(nodeId, identifier, value, targetKind));
    }

    private Map<String, Object> evidence(String nodeId, String identifier, Map<String, Object> value,
                                         String targetKind) {
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("node_id", nodeId);
        evidence.put("entry_variable", canonicalVariable(identifier));
        evidence.put("value_state", value.get("state"));
        evidence.put("value_kind", value.get("kind"));
        if (targetKind != null) evidence.put("target_kind", targetKind);
        evidence.put("dataflow_artifact", DATAFLOW_ARTIFACT);
        return evidence;
    }

    private Map<String, Object> resolvedCicsArgument(String nodeId, String name, String identifier,
                                                     Map<String, Object> value) {
        Map<String, Object> argument = new LinkedHashMap<>();
        argument.put("name", name);
        argument.put("identifier", canonicalVariable(identifier));
        argument.put("resolution_status", "resolved");
        argument.put("resolved_value", value.get("normalized_value"));
        argument.put("value_kind", value.get("kind"));
        argument.put("source", DATAFLOW_ENTRY_CONSTANTS);
        argument.put("confidence", "high");
        argument.put("evidence", cicsArgumentEvidence(nodeId, name, identifier, value));
        return argument;
    }

    private Map<String, Object> unresolvedCicsArgument(String name, String identifier) {
        String canonicalIdentifier = canonicalVariable(identifier);
        Map<String, Object> argument = new LinkedHashMap<>();
        argument.put("name", name);
        argument.put("identifier", canonicalIdentifier);
        argument.put("resolution_status", "unresolved");
        argument.put("source", DATAFLOW_ENTRY_CONSTANTS);
        argument.put("confidence", "none");
        argument.put("resolution_note",
                "No proven alphanumeric constant for " + canonicalIdentifier + " at CICS node entry.");
        return argument;
    }

    private Map<String, Object> cicsArgumentEvidence(String nodeId, String name, String identifier,
                                                    Map<String, Object> value) {
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("node_id", nodeId);
        evidence.put("argument_name", name);
        evidence.put("entry_variable", canonicalVariable(identifier));
        evidence.put("value_state", value.get("state"));
        evidence.put("value_kind", value.get("kind"));
        evidence.put("dataflow_artifact", DATAFLOW_ARTIFACT);
        return evidence;
    }

    private void annotateCallUnresolved(Map<String, Object> metadata, String identifier) {
        String canonicalIdentifier = canonicalVariable(identifier);
        metadata.put("path_sensitive_call_resolution_status", "unresolved");
        metadata.put("path_sensitive_call_target_identifier", canonicalIdentifier);
        metadata.put("path_sensitive_call_target_source", DATAFLOW_ENTRY_CONSTANTS);
        metadata.put("path_sensitive_call_confidence", "none");
        metadata.put("path_sensitive_call_resolution_note",
                "No proven alphanumeric constant for " + canonicalIdentifier + " at CALL node entry.");
    }

    private void annotateCicsUnresolved(Map<String, Object> metadata, String identifier, String targetKind) {
        String canonicalIdentifier = canonicalVariable(identifier);
        metadata.put("path_sensitive_cics_resolution_status", "unresolved");
        metadata.put("path_sensitive_cics_target_identifier", canonicalIdentifier);
        metadata.put("path_sensitive_cics_target_kind", targetKind);
        metadata.put("path_sensitive_cics_target_source", DATAFLOW_ENTRY_CONSTANTS);
        metadata.put("path_sensitive_cics_confidence", "none");
        metadata.put("path_sensitive_cics_resolution_note",
                "No proven alphanumeric constant for " + canonicalIdentifier + " at CICS node entry.");
    }

    private static String canonicalVariable(String variable) {
        if (variable == null) return "";
        String canonical = variable.trim().toUpperCase(Locale.ROOT);
        int subscriptStart = canonical.indexOf('(');
        return subscriptStart < 0 ? canonical : canonical.substring(0, subscriptStart);
    }

    private Map<String, Object> stringKeyMap(Map<?, ?> rawMap) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : rawMap.entrySet()) {
            result.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        return result;
    }
}
