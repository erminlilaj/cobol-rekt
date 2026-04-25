package org.smojol.common.vm.expression;

import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.vm.structure.CobolDataStructure;

public class ConditionVisitor extends AntlrCobolExpressionVisitor {
    private final CobolDataStructure dataRoot;

    public ConditionVisitor(CobolDataStructure dataRoot) {
        this.dataRoot = dataRoot;
    }

    @Override
    public CobolExpression visitCondition(CobolParser.ConditionContext ctx) {
        if (ctx.simpleCondition() != null) {
            SimpleConditionVisitor simpleConditionVisitor = new SimpleConditionVisitor(null, null, dataRoot);
            ctx.simpleCondition().accept(simpleConditionVisitor);
            expression = simpleConditionVisitor.getExpression();
        } else if (ctx.nestedCondition() != null) {
            NestedConditionVisitor nestedConditionVisitor = new NestedConditionVisitor(dataRoot);
            ctx.nestedCondition().accept(nestedConditionVisitor);
            expression = nestedConditionVisitor.getExpression();
        }

        // TODO: Handle dialect nodes, currently will fail if dialect node is present
        if (ctx.additionalCondition().isEmpty()) return expression;
        CobolExpression modifiedExpression = expression;
        SimpleConditionExpression simpleExpression = expression instanceof SimpleConditionExpression e ? e : null;
        ComparisonOperator mostRecentOperator = simpleExpression != null && simpleExpression.getComparison() != null
                ? simpleExpression.getComparison().getRelationalOperation() : null;
        CobolExpression mostRecentLhs = simpleExpression != null ? simpleExpression.getLhs() : null;
        for (CobolParser.AdditionalConditionContext c : ctx.additionalCondition()) {
            AdditionalConditionVisitor additionalConditionVisitor = new AdditionalConditionVisitor(mostRecentLhs, mostRecentOperator, dataRoot);
            c.accept(additionalConditionVisitor);
            CobolExpression additionalExpression = additionalConditionVisitor.getExpression();
            if (additionalExpression.getClass() == SimpleConditionExpression.class) {
                mostRecentOperator = additionalConditionVisitor.getRelationalOperation();
                mostRecentLhs = additionalConditionVisitor.getLhs();
            }
            LogicOperation operator = additionalConditionVisitor.operator();
            modifiedExpression = graft(operator, modifiedExpression, additionalExpression);
        }
        expression = new NestedConditionExpression(modifiedExpression);
        if (ctx.NOT() != null) expression = new NotExpression(expression);
        return expression;
    }
}
