package org.smojol.common.vm.expression;

import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.vm.exception.UnsupportedClassConditionException;

import java.util.logging.Logger;

public class ClassConditionBuilder {
    private static final Logger LOGGER = Logger.getLogger(ClassConditionBuilder.class.getName());

    public CobolExpression build(CobolParser.FixedComparisonContext fixedComparisonContext, CobolExpression expression) {
        ClassConditionExpression classConditionExpression = condition(fixedComparisonContext, expression);
        return fixedComparisonContext.NOT() != null ? new NotExpression(classConditionExpression) : classConditionExpression;
    }

    public ClassConditionExpression condition(CobolParser.FixedComparisonContext fixedComparisonContext, CobolExpression expression) {
        if (fixedComparisonContext.NUMERIC() != null) return IsNumericCondition.isNumeric(expression);
        else if (fixedComparisonContext.ALPHABETIC() != null) return IsAlphabeticCondition.isAlphabetic(expression);
        else if (fixedComparisonContext.ALPHABETIC_LOWER() != null) return IsAlphabeticCondition.isLowercase(expression);
        else if (fixedComparisonContext.ALPHABETIC_UPPER() != null) return IsAlphabeticCondition.isUppercase(expression);
        else if (fixedComparisonContext.POSITIVE() != null) return IsNumericCondition.isPositive(expression);
        else if (fixedComparisonContext.NEGATIVE() != null) return IsNumericCondition.isNegative(expression);
        else if (fixedComparisonContext.ZERO() != null) return IsNumericCondition.isZero(expression);
        else if (fixedComparisonContext.DBCS() != null || fixedComparisonContext.KANJI() != null) {
            return IsAlphabeticCondition.isAlphabetic(expression);
        } else if (fixedComparisonContext.className() != null) {
            LOGGER.warning("User-defined class condition '" + fixedComparisonContext.className().getText()
                + "' approximated as IS ALPHABETIC");
            return IsAlphabeticCondition.isAlphabetic(expression);
        } else throw new UnsupportedClassConditionException(fixedComparisonContext.getText());
    }
}
