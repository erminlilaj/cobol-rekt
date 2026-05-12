package org.smojol.common.staticanalysis.folding;

import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.staticanalysis.value.ConstantStaticValue;
import org.smojol.common.staticanalysis.value.StaticValue;

import java.math.BigDecimal;
import java.util.List;

public class StaticValueLiteralExtractor {
    public LiteralExtractionResult extractNumeric(CobolParser.LiteralContext literal) {
        return extractNumericLiteral(literal.getText(), literal.numericLiteral() != null,
                literal.figurativeConstant() != null);
    }

    LiteralExtractionResult extractNumericLiteral(String text, boolean hasNumericLiteral,
                                                  boolean hasFigurativeConstant) {
        if (hasFigurativeConstant || "ZERO".equalsIgnoreCase(text)
                || "ZEROS".equalsIgnoreCase(text) || "ZEROES".equalsIgnoreCase(text)) {
            return unsupported(FoldingDiagnosticCode.FOLD_UNSUPPORTED_FIGURATIVE_CONSTANT,
                    "Figurative constant " + text + " is not folded in Phase 1.", text);
        }
        if (!hasNumericLiteral) {
            return unsupported(FoldingDiagnosticCode.FOLD_UNSUPPORTED_NON_NUMERIC_LITERAL,
                    "Phase 1 folds only numeric literals.", text);
        }
        if (text.contains(",")) {
            return unsupported(FoldingDiagnosticCode.FOLD_UNSUPPORTED_DECIMAL_COMMA_MODE_UNKNOWN,
                    "Decimal comma literal " + text + " requires DECIMAL-POINT IS COMMA support before folding.",
                    text);
        }
        try {
            BigDecimal value = new BigDecimal(text);
            return new LiteralExtractionResult(ConstantStaticValue.numeric(value, text), List.of());
        } catch (NumberFormatException e) {
            return unsupported(FoldingDiagnosticCode.FOLD_INVALID_NUMERIC_LITERAL,
                    "Invalid numeric literal " + text + " cannot be folded.", text);
        }
    }

    private LiteralExtractionResult unsupported(FoldingDiagnosticCode code, String message, String construct) {
        return new LiteralExtractionResult(null, List.of(new FoldingDiagnostic(code, message, construct)));
    }

    public record LiteralExtractionResult(StaticValue value, List<FoldingDiagnostic> diagnostics) {
        public boolean folded() {
            return value != null && diagnostics.isEmpty();
        }
    }
}
