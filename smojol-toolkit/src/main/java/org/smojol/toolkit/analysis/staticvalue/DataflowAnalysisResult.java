package org.smojol.toolkit.analysis.staticvalue;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

public record DataflowAnalysisResult(
        String program,
        @SerializedName("schema_version") String schemaVersion,
        String analysis,
        @SerializedName("analysis_version") String analysisVersion,
        String status,
        Map<String, Object> config,
        Map<String, Object> summary,
        @SerializedName("node_states") Map<String, DataflowNodeState> nodeStates,
        @SerializedName("alias_sets") Map<String, Object> aliasSets,
        @SerializedName("paragraph_summaries") Map<String, ParagraphSummary> paragraphSummaries,
        List<Map<String, Object>> diagnostics) {
}
