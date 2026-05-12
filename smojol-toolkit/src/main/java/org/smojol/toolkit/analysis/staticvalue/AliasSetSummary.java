package org.smojol.toolkit.analysis.staticvalue;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

public record AliasSetSummary(
        @SerializedName("alias_set_id") String aliasSetId,
        @SerializedName("alias_kind") String aliasKind,
        @SerializedName("base_variable") String baseVariable,
        List<String> members,
        @SerializedName("kill_scope") String killScope,
        String confidence,
        Map<String, Object> layout,
        List<Map<String, Object>> evidence,
        @SerializedName("summary_source") String summarySource) {
}
