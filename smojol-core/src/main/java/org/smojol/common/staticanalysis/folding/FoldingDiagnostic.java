package org.smojol.common.staticanalysis.folding;

import java.util.LinkedHashMap;
import java.util.Map;

public record FoldingDiagnostic(FoldingDiagnosticCode code, String message, String construct) {
    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("code", code.name());
        json.put("severity", code.severity());
        json.put("category", code.category());
        json.put("message", message);
        if (construct != null && !construct.isBlank()) {
            json.put("construct", construct);
        }
        return json;
    }
}
