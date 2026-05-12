package org.smojol.toolkit.analysis.staticvalue;

import org.smojol.common.ast.SerialisableCFGFlowNode;
import org.smojol.common.ast.SerialisableEdge;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class StaticValueDataflowPass {
    private static final String SCHEMA_VERSION = "1.0";
    private static final String ANALYSIS_VERSION = "0.1";

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges) {
        Map<String, DataflowNodeState> nodeStates = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeStates.put(node.getId(), DataflowNodeState.empty());
        }

        return new DataflowAnalysisResult(
                program,
                SCHEMA_VERSION,
                "static_value_dataflow",
                ANALYSIS_VERSION,
                "skeleton",
                config(),
                summary(nodes.size(), edges.size()),
                nodeStates,
                new LinkedHashMap<>(),
                new LinkedHashMap<>(),
                List.of()
        );
    }

    private Map<String, Object> config() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("constant_propagation_enabled", false);
        config.put("path_sensitive_targets_enabled", false);
        config.put("paragraph_summaries_enabled", false);
        config.put("alias_analysis_enabled", false);
        config.put("mode", "skeleton");
        return config;
    }

    private Map<String, Object> summary(int nodeCount, int edgeCount) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("node_count", nodeCount);
        summary.put("edge_count", edgeCount);
        summary.put("entry_constant_count", 0);
        summary.put("exit_constant_count", 0);
        summary.put("kill_count", 0);
        summary.put("diagnostic_count", 0);
        summary.put("alias_set_count", 0);
        summary.put("paragraph_summary_count", 0);
        return summary;
    }
}
