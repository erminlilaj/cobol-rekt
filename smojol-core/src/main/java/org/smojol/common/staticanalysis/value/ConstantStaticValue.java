package org.smojol.common.staticanalysis.value;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;

public record ConstantStaticValue(StaticValueKind kind, String rawLexeme, String normalizedValue, String displayValue,
                                  NumericStaticValue numeric, FigurativeStaticValue figurative,
                                  TypeContext typeContext) implements StaticValue {
    public static ConstantStaticValue numeric(BigDecimal value, String rawLexeme) {
        NumericStaticValue numeric = NumericStaticValue.from(value);
        return new ConstantStaticValue(
                StaticValueKind.NUMERIC,
                rawLexeme,
                numeric.decimal(),
                numeric.decimal(),
                numeric,
                null,
                null
        );
    }

    public static ConstantStaticValue alphanumeric(String rawLexeme, String normalizedValue) {
        return new ConstantStaticValue(
                StaticValueKind.ALPHANUMERIC,
                rawLexeme,
                normalizedValue,
                normalizedValue,
                null,
                null,
                null
        );
    }

    @Override
    public StaticValueState state() {
        return StaticValueState.CONSTANT;
    }

    @Override
    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("state", state().name());
        json.put("kind", kind.name());
        json.put("raw_lexeme", rawLexeme);
        json.put("normalized_value", normalizedValue);
        json.put("display_value", displayValue);
        json.put("numeric", numeric == null ? null : numeric.toJsonMap());
        json.put("figurative", figurative == null ? null : figurative.toJsonMap());
        json.put("type_context", typeContext == null ? null : typeContext.toJsonMap());
        return json;
    }
}
