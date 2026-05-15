package org.smojol.common.staticanalysis.value;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class StaticValueTest {
    @Test
    void numericValuePreservesExactDecimalPayload() {
        ConstantStaticValue value = ConstantStaticValue.numeric(new BigDecimal("3.50"), "3.50");

        assertEquals(StaticValueState.CONSTANT, value.state());
        assertEquals(StaticValueKind.NUMERIC, value.kind());
        assertEquals("3.50", value.rawLexeme());
        assertEquals("3.50", value.normalizedValue());
        assertEquals("3.50", value.displayValue());
        assertEquals("3.50", value.numeric().decimal());
        assertEquals(2, value.numeric().scale());
        assertEquals(3, value.numeric().precision());
        assertEquals("POSITIVE", value.numeric().sign());
    }

    @Test
    void numericValueKeepsNegativeSignAndScale() {
        ConstantStaticValue value = ConstantStaticValue.numeric(new BigDecimal("-9.0"), "-9.0");

        assertEquals("-9.0", value.numeric().decimal());
        assertEquals(1, value.numeric().scale());
        assertEquals(2, value.numeric().precision());
        assertEquals("NEGATIVE", value.numeric().sign());
    }

    @Test
    void numericValueJsonUsesSnakeCaseFields() {
        Map<String, Object> json = ConstantStaticValue.numeric(new BigDecimal("0.25"), "0.25").toJsonMap();

        assertEquals("CONSTANT", json.get("state"));
        assertEquals("NUMERIC", json.get("kind"));
        assertEquals("0.25", json.get("raw_lexeme"));
        assertEquals("0.25", json.get("normalized_value"));
        assertEquals("0.25", json.get("display_value"));

        @SuppressWarnings("unchecked")
        Map<String, Object> numeric = (Map<String, Object>) json.get("numeric");
        assertEquals("0.25", numeric.get("decimal"));
        assertEquals(2, numeric.get("scale"));
        assertEquals(2, numeric.get("precision"));
        assertEquals("POSITIVE", numeric.get("sign"));
    }

    @Test
    void alphanumericValueJsonUsesSnakeCaseFieldsAndNoNumericPayload() {
        Map<String, Object> json = ConstantStaticValue.alphanumeric("\"PROG-A\"", "PROG-A").toJsonMap();

        assertEquals("CONSTANT", json.get("state"));
        assertEquals("ALPHANUMERIC", json.get("kind"));
        assertEquals("\"PROG-A\"", json.get("raw_lexeme"));
        assertEquals("PROG-A", json.get("normalized_value"));
        assertEquals("PROG-A", json.get("display_value"));
        assertEquals(null, json.get("numeric"));
        assertEquals(null, json.get("figurative"));
        assertEquals(null, json.get("type_context"));
    }
}
