package org.smojol.toolkit.analysis.error;

import lombok.Getter;

@Getter
public class BaseModelValidationException extends RuntimeException {
    private final String diagnosticCode;
    private final String analysisStage;

    public BaseModelValidationException(String diagnosticCode, String message) {
        this(diagnosticCode, message, null);
    }

    public BaseModelValidationException(String diagnosticCode, String message, Throwable cause) {
        super(message, cause);
        this.diagnosticCode = diagnosticCode;
        this.analysisStage = "BUILD_BASE_ANALYSIS";
    }
}
