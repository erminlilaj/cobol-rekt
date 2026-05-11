package org.smojol.common.staticanalysis.folding;

import org.smojol.common.staticanalysis.value.StaticValue;

import java.util.LinkedHashMap;
import java.util.Map;

public record FoldedValueFact(String statementType, String targetVariable, String originalExpression,
                              String foldedExpression, StaticValue value, String statementText,
                              String paragraph, String section, Integer sourceLine) {
    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("schema_version", "1.0");
        json.put("fact_type", "folded_expression");
        json.put("status", FoldingStatus.FOLDED.name().toLowerCase());
        json.put("statement_type", statementType);
        json.put("target_variable", targetVariable);
        json.put("original_expression", originalExpression);
        json.put("folded_expression", foldedExpression);
        json.put("value", value.toJsonMap());
        json.put("confidence", "high");
        json.put("provenance_source", "java_static_value_folded_expression");
        if (statementText != null) json.put("statement_text", statementText);
        if (paragraph != null) json.put("paragraph", paragraph);
        if (section != null) json.put("section", section);
        if (sourceLine != null) json.put("source_line", sourceLine);
        return json;
    }
}
