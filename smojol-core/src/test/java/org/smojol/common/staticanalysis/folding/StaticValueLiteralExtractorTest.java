package org.smojol.common.staticanalysis.folding;

import org.junit.jupiter.api.Test;
import org.smojol.common.staticanalysis.value.ConstantStaticValue;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StaticValueLiteralExtractorTest {
    private final StaticValueLiteralExtractor extractor = new StaticValueLiteralExtractor();

    @Test
    void extractsDotDecimalNumericLiteralExactly() {
        StaticValueLiteralExtractor.LiteralExtractionResult result =
                extractor.extractNumericLiteral("12.30", true, false);

        assertTrue(result.folded());
        ConstantStaticValue value = (ConstantStaticValue) result.value();
        assertEquals("12.30", value.rawLexeme());
        assertEquals("12.30", value.normalizedValue());
        assertEquals("12.30", value.numeric().decimal());
        assertEquals(2, value.numeric().scale());
        assertEquals(4, value.numeric().precision());
        assertEquals("POSITIVE", value.numeric().sign());
    }

    @Test
    void rejectsDecimalCommaUntilSpecialNamesIsSupported() {
        StaticValueLiteralExtractor.LiteralExtractionResult result =
                extractor.extractNumericLiteral("1,20", true, false);

        assertDiagnostic(result, FoldingDiagnosticCode.FOLD_UNSUPPORTED_DECIMAL_COMMA_MODE_UNKNOWN,
                "Decimal comma literal 1,20 requires DECIMAL-POINT IS COMMA support before folding.",
                "1,20");
    }

    @Test
    void rejectsFigurativeZeroAsOutOfScopeForPhaseOne() {
        StaticValueLiteralExtractor.LiteralExtractionResult result =
                extractor.extractNumericLiteral("ZERO", true, false);

        assertDiagnostic(result, FoldingDiagnosticCode.FOLD_UNSUPPORTED_FIGURATIVE_CONSTANT,
                "Figurative constant ZERO is not folded in Phase 1.", "ZERO");
    }

    @Test
    void rejectsNonNumericLiteral() {
        StaticValueLiteralExtractor.LiteralExtractionResult result =
                extractor.extractNumericLiteral("'ABC'", false, false);

        assertDiagnostic(result, FoldingDiagnosticCode.FOLD_UNSUPPORTED_NON_NUMERIC_LITERAL,
                "Phase 1 folds only numeric literals.", "'ABC'");
    }

    @Test
    void rejectsInvalidNumericTextEvenIfMarkedNumericByCaller() {
        StaticValueLiteralExtractor.LiteralExtractionResult result =
                extractor.extractNumericLiteral("12A", true, false);

        assertDiagnostic(result, FoldingDiagnosticCode.FOLD_INVALID_NUMERIC_LITERAL,
                "Invalid numeric literal 12A cannot be folded.", "12A");
    }

    private void assertDiagnostic(StaticValueLiteralExtractor.LiteralExtractionResult result,
                                  FoldingDiagnosticCode code, String message, String construct) {
        assertFalse(result.folded());
        assertEquals(1, result.diagnostics().size());
        FoldingDiagnostic diagnostic = result.diagnostics().get(0);
        assertEquals(code, diagnostic.code());
        assertEquals(code.severity(), diagnostic.code().severity());
        assertEquals(code.category(), diagnostic.code().category());
        assertEquals(message, diagnostic.message());
        assertEquals(construct, diagnostic.construct());
    }
}
