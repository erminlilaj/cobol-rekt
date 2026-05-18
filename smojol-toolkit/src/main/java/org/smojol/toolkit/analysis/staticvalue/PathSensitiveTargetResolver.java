package org.smojol.toolkit.analysis.staticvalue;

import com.mojo.algorithms.domain.FlowNodeType;
import org.smojol.common.ast.SerialisableCFGFlowNode;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public class PathSensitiveTargetResolver {
    private static final String DATAFLOW_ENTRY_CONSTANTS = "static_analysis.dataflow.entry_constants";
    private static final String DATAFLOW_ARTIFACT = "static_analysis/dataflow.json";

    public void annotateTargets(List<SerialisableCFGFlowNode> nodes, DataflowAnalysisResult dataflow) {
        for (SerialisableCFGFlowNode node : nodes) {
            if (node.getType() != FlowNodeType.CALL) continue;
            Map<String, Object> metadata = node.getMetadata();
            if (!Boolean.TRUE.equals(metadata.get("dynamic_call"))) continue;
            String identifier = callTargetIdentifier(metadata);
            if (identifier == null || identifier.isBlank()) continue;
            Map<String, Object> value = entryValue(node, dataflow, canonicalVariable(identifier));
            if (isAlphanumericConstant(value)) {
                annotateResolved(metadata, node.getId(), identifier, value);
            } else {
                annotateUnresolved(metadata, identifier);
            }
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

    private void annotateResolved(Map<String, Object> metadata, String nodeId, String identifier,
                                  Map<String, Object> value) {
        metadata.put("path_sensitive_call_resolution_status", "resolved");
        metadata.put("path_sensitive_call_target", value.get("normalized_value"));
        metadata.put("path_sensitive_call_target_identifier", canonicalVariable(identifier));
        metadata.put("path_sensitive_call_target_source", DATAFLOW_ENTRY_CONSTANTS);
        metadata.put("path_sensitive_call_confidence", "high");
        metadata.put("path_sensitive_call_evidence", evidence(nodeId, identifier, value));
    }

    private Map<String, Object> evidence(String nodeId, String identifier, Map<String, Object> value) {
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("node_id", nodeId);
        evidence.put("entry_variable", canonicalVariable(identifier));
        evidence.put("value_state", value.get("state"));
        evidence.put("value_kind", value.get("kind"));
        evidence.put("dataflow_artifact", DATAFLOW_ARTIFACT);
        return evidence;
    }

    private void annotateUnresolved(Map<String, Object> metadata, String identifier) {
        String canonicalIdentifier = canonicalVariable(identifier);
        metadata.put("path_sensitive_call_resolution_status", "unresolved");
        metadata.put("path_sensitive_call_target_identifier", canonicalIdentifier);
        metadata.put("path_sensitive_call_target_source", DATAFLOW_ENTRY_CONSTANTS);
        metadata.put("path_sensitive_call_confidence", "none");
        metadata.put("path_sensitive_call_resolution_note",
                "No proven alphanumeric constant for " + canonicalIdentifier + " at CALL node entry.");
    }

    private static String canonicalVariable(String variable) {
        if (variable == null) return "";
        String canonical = variable.trim().toUpperCase(Locale.ROOT);
        int subscriptStart = canonical.indexOf('(');
        return subscriptStart < 0 ? canonical : canonical.substring(0, subscriptStart);
    }
}
