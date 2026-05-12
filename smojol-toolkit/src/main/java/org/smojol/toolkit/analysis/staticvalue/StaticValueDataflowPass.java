package org.smojol.toolkit.analysis.staticvalue;

import com.mojo.algorithms.domain.FlowNodeType;
import org.smojol.common.ast.SerialisableCFGFlowNode;
import org.smojol.common.ast.SerialisableEdge;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeSet;
import java.util.Set;

public class StaticValueDataflowPass {
    private static final String SCHEMA_VERSION = "1.0";
    private static final String ANALYSIS_VERSION = "0.2";
    private static final String SUMMARY_SOURCE = "java_static_value_dataflow";

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges) {
        Map<String, DataflowNodeState> nodeStates = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeStates.put(node.getId(), DataflowNodeState.empty());
        }
        Map<String, ParagraphSummary> paragraphSummaries = paragraphSummaries(nodes);

        return new DataflowAnalysisResult(
                program,
                SCHEMA_VERSION,
                "static_value_dataflow",
                ANALYSIS_VERSION,
                "paragraph_summary_skeleton",
                config(),
                summary(nodes.size(), edges.size(), paragraphSummaries.size()),
                nodeStates,
                new LinkedHashMap<>(),
                paragraphSummaries,
                List.of()
        );
    }

    private Map<String, Object> config() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("constant_propagation_enabled", false);
        config.put("path_sensitive_targets_enabled", false);
        config.put("paragraph_summaries_enabled", true);
        config.put("alias_analysis_enabled", false);
        config.put("mode", "paragraph_summary_skeleton");
        return config;
    }

    private Map<String, Object> summary(int nodeCount, int edgeCount, int paragraphSummaryCount) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("node_count", nodeCount);
        summary.put("edge_count", edgeCount);
        summary.put("entry_constant_count", 0);
        summary.put("exit_constant_count", 0);
        summary.put("kill_count", 0);
        summary.put("diagnostic_count", 0);
        summary.put("alias_set_count", 0);
        summary.put("paragraph_summary_count", paragraphSummaryCount);
        return summary;
    }

    private Map<String, ParagraphSummary> paragraphSummaries(List<SerialisableCFGFlowNode> nodes) {
        Map<String, ParagraphSummary> result = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode paragraph : nodes) {
            if (paragraph.getType() != FlowNodeType.PARAGRAPH) continue;
            List<SerialisableCFGFlowNode> containedNodes = containedNodes(paragraph, nodes);
            Set<String> callsParagraphs = new TreeSet<>();
            Set<String> calledPrograms = new TreeSet<>();
            Set<String> externalSideEffects = new TreeSet<>();
            for (SerialisableCFGFlowNode node : containedNodes) {
                collectParagraphCalls(node, callsParagraphs);
                collectCalledPrograms(node, calledPrograms);
                collectExternalSideEffects(node, externalSideEffects);
            }
            boolean transitiveComplete = callsParagraphs.isEmpty();
            List<String> variablesReadDirect = sortedStrings(paragraph.getVariablesRead());
            List<String> variablesModifiedDirect = sortedStrings(paragraph.getVariablesModified());
            result.put(paragraph.getName(), new ParagraphSummary(
                    paragraph.getName(),
                    paragraph.getId(),
                    containedNodes.stream().map(SerialisableCFGFlowNode::getId).toList(),
                    variablesReadDirect,
                    variablesModifiedDirect,
                    transitiveComplete ? variablesReadDirect : List.of(),
                    transitiveComplete ? variablesModifiedDirect : List.of(),
                    callsParagraphs.stream().toList(),
                    calledPrograms.stream().toList(),
                    externalSideEffects.stream().toList(),
                    unsupportedConstructs(callsParagraphs, transitiveComplete),
                    false,
                    transitiveComplete ? "complete_no_paragraph_calls" : "not_computed_perform_targets_present",
                    SUMMARY_SOURCE
            ));
        }
        return result;
    }

    private List<SerialisableCFGFlowNode> containedNodes(SerialisableCFGFlowNode paragraph,
                                                        List<SerialisableCFGFlowNode> nodes) {
        Integer start = paragraph.getSourceLine();
        Integer end = paragraph.getSourceEndLine();
        if (start == null || end == null) return List.of();
        return nodes.stream()
                .filter(node -> !Objects.equals(node.getId(), paragraph.getId()))
                .filter(node -> node.getSourceLine() != null && node.getSourceEndLine() != null)
                .filter(node -> node.getSourceLine() >= start && node.getSourceEndLine() <= end)
                .filter(node -> node.getType() != FlowNodeType.PROCEDURE_DIVISION_BODY)
                .filter(node -> node.getType() != FlowNodeType.PARAGRAPHS)
                .filter(node -> node.getType() != FlowNodeType.PARAGRAPH)
                .toList();
    }

    private List<String> sortedStrings(List<String> values) {
        if (values == null) return List.of();
        Set<String> sorted = new TreeSet<>();
        values.stream().filter(Objects::nonNull).forEach(sorted::add);
        return sorted.stream().toList();
    }

    private void collectParagraphCalls(SerialisableCFGFlowNode node, Set<String> callsParagraphs) {
        Object resolvedStart = node.getMetadata().get("resolved_start");
        if (resolvedStart instanceof String target && !target.isBlank()) callsParagraphs.add(target);
        Object targets = node.getMetadata().get("perform_targets");
        if (!(targets instanceof List<?> targetList)) return;
        for (Object target : targetList) {
            if (target instanceof String targetName && !targetName.isBlank()) callsParagraphs.add(targetName);
        }
    }

    private void collectCalledPrograms(SerialisableCFGFlowNode node, Set<String> calledPrograms) {
        Object resolvedCallTarget = node.getMetadata().get("resolved_call_target");
        if (resolvedCallTarget instanceof String target && !target.isBlank()) {
            calledPrograms.add(target);
            return;
        }
        Object callTarget = node.getMetadata().get("call_target");
        if (callTarget instanceof String target && !target.isBlank()) calledPrograms.add(target);
    }

    private void collectExternalSideEffects(SerialisableCFGFlowNode node, Set<String> externalSideEffects) {
        FlowNodeType type = node.getType();
        if (node.getMetadata().containsKey("call_target")) externalSideEffects.add("CALL");
        if (node.getMetadata().containsKey("cics_command")) externalSideEffects.add("EXEC_CICS");
        if (List.of("ACCEPT", "READ", "WRITE", "OPEN", "CLOSE", "DELETE", "REWRITE", "START")
                .contains(type.name())) {
            externalSideEffects.add(type.name());
        }
    }

    private List<Map<String, Object>> unsupportedConstructs(Set<String> callsParagraphs, boolean transitiveComplete) {
        if (transitiveComplete) return List.of();
        Map<String, Object> unsupported = new LinkedHashMap<>();
        unsupported.put("code", "PARAGRAPH_TRANSITIVE_SUMMARY_NOT_COMPUTED");
        unsupported.put("severity", "info");
        unsupported.put("category", "deferred");
        unsupported.put("message", "PERFORM target summaries are recorded but not expanded transitively in Phase 2.2.");
        unsupported.put("calls_paragraphs", callsParagraphs.stream().toList());
        return List.of(unsupported);
    }
}
