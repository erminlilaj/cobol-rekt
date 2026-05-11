package org.smojol.common.staticanalysis.folding;

public enum FoldingDiagnosticCode {
    FOLD_UNSUPPORTED_VARIABLE_REFERENCE("info", "unsupported"),
    FOLD_UNSUPPORTED_FUNCTION("info", "unsupported"),
    FOLD_UNSUPPORTED_SUBSCRIPT("info", "unsupported"),
    FOLD_UNSUPPORTED_REFERENCE_MODIFICATION("info", "unsupported"),
    FOLD_UNSUPPORTED_DECIMAL_COMMA_MODE_UNKNOWN("info", "unsupported"),
    FOLD_UNSUPPORTED_FIGURATIVE_CONSTANT("info", "unsupported"),
    FOLD_UNSUPPORTED_SPECIAL_REGISTER("info", "unsupported"),
    FOLD_UNSUPPORTED_NON_NUMERIC_LITERAL("info", "unsupported"),
    FOLD_UNSUPPORTED_EXPONENTIATION("info", "unsupported"),
    FOLD_UNSUPPORTED_DIALECT_NODE("info", "unsupported"),
    FOLD_UNSAFE_DIVIDE_BY_ZERO("warning", "unsafe"),
    FOLD_UNSAFE_NON_TERMINATING_DIVISION("warning", "unsafe"),
    FOLD_UNSAFE_SIZE_ERROR_SEMANTICS("warning", "unsafe"),
    FOLD_INVALID_NUMERIC_LITERAL("warning", "unsupported");

    private final String severity;
    private final String category;

    FoldingDiagnosticCode(String severity, String category) {
        this.severity = severity;
        this.category = category;
    }

    public String severity() {
        return severity;
    }

    public String category() {
        return category;
    }
}
