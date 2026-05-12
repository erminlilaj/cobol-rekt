package org.smojol.toolkit.analysis.staticvalue;

import com.google.gson.annotations.SerializedName;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public record DataflowNodeState(
        @SerializedName("entry_constants") Map<String, Object> entryConstants,
        @SerializedName("exit_constants") Map<String, Object> exitConstants,
        List<Map<String, Object>> kills,
        List<Map<String, Object>> diagnostics) {
    public static DataflowNodeState empty() {
        return new DataflowNodeState(new LinkedHashMap<>(), new LinkedHashMap<>(), List.of(), List.of());
    }
}
