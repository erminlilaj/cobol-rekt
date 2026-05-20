package org.smojol.common.staticanalysis.folding;

import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.staticanalysis.value.ConstantStaticValue;
import org.smojol.common.staticanalysis.value.StaticValue;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public class StaticExpressionFolder {
    private final StaticValueLiteralExtractor literalExtractor = new StaticValueLiteralExtractor();

    public FoldingResult fold(CobolParser.ArithmeticExpressionContext expression) {
        Evaluation evaluation = evaluateArithmetic(expression);
        if (!evaluation.diagnostics().isEmpty()) {
            return new FoldingResult(null, expression.getText(), evaluation.diagnostics());
        }
        ConstantStaticValue foldedValue = ConstantStaticValue.numeric(evaluation.value(), evaluation.value().toPlainString());
        return new FoldingResult(foldedValue, foldedValue.displayValue(), List.of());
    }

    public ExpressionSerialization serializeDataflowExpression(CobolParser.ArithmeticExpressionContext expression) {
        return serializeArithmetic(expression);
    }

    private ExpressionSerialization serializeArithmetic(CobolParser.ArithmeticExpressionContext expression) {
        ExpressionSerialization current = serializeMultDivs(expression.multDivs());
        if (!current.serialized()) return current;
        for (CobolParser.PlusMinusContext plusMinus : expression.plusMinus()) {
            ExpressionSerialization next = serializeMultDivs(plusMinus.multDivs());
            if (!next.serialized()) return next;
            current = ExpressionSerialization.expression(binaryNode(
                    plusMinus.MINUSCHAR() != null ? "SUBTRACT" : "ADD",
                    current.expression(), next.expression(), plusMinus.getText()));
        }
        return current;
    }

    private ExpressionSerialization serializeMultDivs(CobolParser.MultDivsContext multDivs) {
        ExpressionSerialization current = serializePowers(multDivs.powers());
        if (!current.serialized()) return current;
        for (CobolParser.MultDivContext multDiv : multDivs.multDiv()) {
            ExpressionSerialization next = serializePowers(multDiv.powers());
            if (!next.serialized()) return next;
            current = ExpressionSerialization.expression(binaryNode(
                    multDiv.ASTERISKCHAR() != null ? "MULTIPLY" : "DIVIDE",
                    current.expression(), next.expression(), multDiv.getText()));
        }
        return current;
    }

    private ExpressionSerialization serializePowers(CobolParser.PowersContext powers) {
        if (!powers.power().isEmpty()) return ExpressionSerialization.unsupported();
        ExpressionSerialization base = serializeBasis(powers.basis());
        if (!base.serialized()) return base;
        if (powers.MINUSCHAR() != null) {
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("kind", "unary");
            node.put("operator", "NEGATE");
            node.put("operand", base.expression());
            node.put("source_text", powers.getText());
            return ExpressionSerialization.expression(node);
        }
        return base;
    }

    private ExpressionSerialization serializeBasis(CobolParser.BasisContext basis) {
        if (basis.arithmeticExpression() != null) return serializeArithmetic(basis.arithmeticExpression());
        if (basis.literal() != null) {
            StaticValueLiteralExtractor.LiteralExtractionResult literal =
                    literalExtractor.extractNumeric(basis.literal());
            if (!literal.folded()) return ExpressionSerialization.unsupported();
            ConstantStaticValue constant = (ConstantStaticValue) literal.value();
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("kind", "numeric_literal");
            node.put("raw_lexeme", basis.literal().getText());
            node.put("normalized_value", constant.normalizedValue());
            node.put("source_text", basis.getText());
            return ExpressionSerialization.expression(node);
        }
        if (basis.generalIdentifier() != null) return serializeGeneralIdentifier(basis.generalIdentifier());
        return ExpressionSerialization.unsupported();
    }

    private ExpressionSerialization serializeGeneralIdentifier(CobolParser.GeneralIdentifierContext generalIdentifier) {
        if (generalIdentifier.functionCall() != null || generalIdentifier.specialRegister() != null) {
            return ExpressionSerialization.unsupported();
        }
        CobolParser.QualifiedDataNameContext qualifiedDataName = generalIdentifier.qualifiedDataName();
        if (qualifiedDataName == null || qualifiedDataName.tableCall() != null
                || qualifiedDataName.referenceModifier() != null) {
            return ExpressionSerialization.unsupported();
        }
        Map<String, Object> node = new LinkedHashMap<>();
        node.put("kind", "variable");
        node.put("name", generalIdentifier.getText().toUpperCase(Locale.ROOT));
        node.put("source_text", generalIdentifier.getText());
        return ExpressionSerialization.expression(node);
    }

    private Map<String, Object> binaryNode(String operator, Map<String, Object> left,
                                           Map<String, Object> right, String sourceText) {
        Map<String, Object> node = new LinkedHashMap<>();
        node.put("kind", "binary");
        node.put("operator", operator);
        node.put("left", left);
        node.put("right", right);
        node.put("source_text", sourceText);
        return node;
    }

    private Evaluation evaluateArithmetic(CobolParser.ArithmeticExpressionContext expression) {
        Evaluation current = evaluateMultDivs(expression.multDivs());
        if (!current.folded()) return current;
        for (CobolParser.PlusMinusContext plusMinus : expression.plusMinus()) {
            Evaluation next = evaluateMultDivs(plusMinus.multDivs());
            if (!next.folded()) return next;
            current = plusMinus.MINUSCHAR() != null
                    ? current.withValue(current.value().subtract(next.value()))
                    : current.withValue(current.value().add(next.value()));
        }
        return current;
    }

    private Evaluation evaluateMultDivs(CobolParser.MultDivsContext multDivs) {
        Evaluation current = evaluatePowers(multDivs.powers());
        if (!current.folded()) return current;
        for (CobolParser.MultDivContext multDiv : multDivs.multDiv()) {
            Evaluation next = evaluatePowers(multDiv.powers());
            if (!next.folded()) return next;
            if (multDiv.ASTERISKCHAR() != null) {
                current = current.withValue(current.value().multiply(next.value()));
            } else if (next.value().compareTo(BigDecimal.ZERO) == 0) {
                return Evaluation.diagnostic(new FoldingDiagnostic(
                        FoldingDiagnosticCode.FOLD_UNSAFE_DIVIDE_BY_ZERO,
                        "Division by zero cannot be folded safely.",
                        multDiv.getText()
                ));
            } else {
                try {
                    current = current.withValue(current.value().divide(next.value()));
                } catch (ArithmeticException e) {
                    return Evaluation.diagnostic(new FoldingDiagnostic(
                            FoldingDiagnosticCode.FOLD_UNSAFE_NON_TERMINATING_DIVISION,
                            "Non-terminating decimal division cannot be folded exactly.",
                            multDiv.getText()
                    ));
                }
            }
        }
        return current;
    }

    private Evaluation evaluatePowers(CobolParser.PowersContext powers) {
        if (!powers.power().isEmpty()) {
            return Evaluation.diagnostic(new FoldingDiagnostic(
                    FoldingDiagnosticCode.FOLD_UNSUPPORTED_EXPONENTIATION,
                    "Exponentiation is not folded in Phase 1.",
                    powers.getText()
            ));
        }
        Evaluation base = evaluateBasis(powers.basis());
        if (!base.folded()) return base;
        if (powers.MINUSCHAR() != null) {
            return base.withValue(base.value().negate());
        }
        return base;
    }

    private Evaluation evaluateBasis(CobolParser.BasisContext basis) {
        if (basis.arithmeticExpression() != null) {
            return evaluateArithmetic(basis.arithmeticExpression());
        }
        if (basis.literal() != null) {
            StaticValueLiteralExtractor.LiteralExtractionResult literal =
                    literalExtractor.extractNumeric(basis.literal());
            if (!literal.folded()) return new Evaluation(null, literal.diagnostics());
            ConstantStaticValue constant = (ConstantStaticValue) literal.value();
            return new Evaluation(new BigDecimal(constant.normalizedValue()), List.of());
        }
        if (basis.generalIdentifier() != null) {
            return diagnosticForGeneralIdentifier(basis.generalIdentifier());
        }
        return Evaluation.diagnostic(new FoldingDiagnostic(
                FoldingDiagnosticCode.FOLD_UNSUPPORTED_DIALECT_NODE,
                "Dialect-specific expression node is not folded in Phase 1.",
                basis.getText()
        ));
    }

    private Evaluation diagnosticForGeneralIdentifier(CobolParser.GeneralIdentifierContext generalIdentifier) {
        if (generalIdentifier.functionCall() != null) {
            return Evaluation.diagnostic(new FoldingDiagnostic(
                    FoldingDiagnosticCode.FOLD_UNSUPPORTED_FUNCTION,
                    "Expression contains a function call; Phase 1 folds only closed literal expressions.",
                    generalIdentifier.getText()
            ));
        }
        if (generalIdentifier.specialRegister() != null) {
            return Evaluation.diagnostic(new FoldingDiagnostic(
                    FoldingDiagnosticCode.FOLD_UNSUPPORTED_SPECIAL_REGISTER,
                    "Expression contains a special register; Phase 1 folds only closed literal expressions.",
                    generalIdentifier.getText()
            ));
        }
        CobolParser.QualifiedDataNameContext qualifiedDataName = generalIdentifier.qualifiedDataName();
        if (qualifiedDataName != null && qualifiedDataName.tableCall() != null) {
            return Evaluation.diagnostic(new FoldingDiagnostic(
                    FoldingDiagnosticCode.FOLD_UNSUPPORTED_SUBSCRIPT,
                    "Expression contains a subscript or index; Phase 1 folds only closed literal expressions.",
                    generalIdentifier.getText()
            ));
        }
        if (qualifiedDataName != null && qualifiedDataName.referenceModifier() != null) {
            return Evaluation.diagnostic(new FoldingDiagnostic(
                    FoldingDiagnosticCode.FOLD_UNSUPPORTED_REFERENCE_MODIFICATION,
                    "Expression contains reference modification; Phase 1 folds only closed literal expressions.",
                    generalIdentifier.getText()
            ));
        }
        return Evaluation.diagnostic(new FoldingDiagnostic(
                FoldingDiagnosticCode.FOLD_UNSUPPORTED_VARIABLE_REFERENCE,
                "Expression contains variable " + generalIdentifier.getText()
                        + "; Phase 1 folds only closed literal expressions.",
                generalIdentifier.getText()
        ));
    }

    private record Evaluation(BigDecimal value, List<FoldingDiagnostic> diagnostics) {
        static Evaluation diagnostic(FoldingDiagnostic diagnostic) {
            return new Evaluation(null, List.of(diagnostic));
        }

        boolean folded() {
            return value != null && diagnostics.isEmpty();
        }

        Evaluation withValue(BigDecimal nextValue) {
            return new Evaluation(nextValue, diagnostics);
        }
    }

    public record FoldingResult(StaticValue value, String foldedExpression, List<FoldingDiagnostic> diagnostics) {
        public boolean folded() {
            return value != null && diagnostics.isEmpty();
        }

        public List<Map<String, Object>> diagnosticJson() {
            List<Map<String, Object>> json = new ArrayList<>();
            diagnostics.forEach(diagnostic -> json.add(diagnostic.toJsonMap()));
            return json;
        }
    }

    public record ExpressionSerialization(Map<String, Object> expression) {
        static ExpressionSerialization expression(Map<String, Object> expression) {
            return new ExpressionSerialization(expression);
        }

        static ExpressionSerialization unsupported() {
            return new ExpressionSerialization(null);
        }

        public boolean serialized() {
            return expression != null;
        }
    }
}
