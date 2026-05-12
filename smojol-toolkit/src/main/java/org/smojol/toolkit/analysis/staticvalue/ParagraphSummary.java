package org.smojol.toolkit.analysis.staticvalue;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

public record ParagraphSummary(
        String paragraph,
        @SerializedName("paragraph_node_id") String paragraphNodeId,
        @SerializedName("node_ids") List<String> nodeIds,
        @SerializedName("variables_read_direct") List<String> variablesReadDirect,
        @SerializedName("variables_modified_direct") List<String> variablesModifiedDirect,
        @SerializedName("variables_read_transitive") List<String> variablesReadTransitive,
        @SerializedName("variables_modified_transitive") List<String> variablesModifiedTransitive,
        @SerializedName("calls_paragraphs") List<String> callsParagraphs,
        @SerializedName("called_programs") List<String> calledPrograms,
        @SerializedName("external_side_effects") List<String> externalSideEffects,
        @SerializedName("unsupported_constructs") List<Map<String, Object>> unsupportedConstructs,
        @SerializedName("cycle_detected") boolean cycleDetected,
        @SerializedName("transitive_summary_status") String transitiveSummaryStatus,
        @SerializedName("summary_source") String summarySource) {
}
