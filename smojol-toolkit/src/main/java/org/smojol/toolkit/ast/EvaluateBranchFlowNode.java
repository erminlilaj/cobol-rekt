package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;
import org.antlr.v4.runtime.tree.ParseTree;
import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.ast.*;
import org.smojol.common.pseudocode.SmojolSymbolTable;
import org.smojol.common.vm.expression.CobolExpression;
import org.smojol.common.vm.expression.CobolExpressionBuilder;
import org.smojol.common.vm.expression.OrExpression;
import org.smojol.common.vm.expression.PrimitiveCobolExpression;
import org.smojol.common.vm.expression.RelationalOperation;
import org.smojol.common.vm.expression.RelationExpression;
import org.smojol.common.vm.expression.SimpleConditionExpression;
import org.smojol.common.vm.interpreter.CobolInterpreter;
import org.smojol.common.vm.interpreter.CobolVmSignal;
import org.smojol.common.vm.interpreter.FlowControl;
import org.smojol.common.vm.stack.StackFrames;
import org.smojol.common.vm.structure.CobolDataStructure;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

@Getter
public class EvaluateBranchFlowNode extends CompositeCobolFlowNode {
    private CobolExpression conditionExpression;

    public EvaluateBranchFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public void buildInternalFlow() {
        super.buildInternalFlow();
    }

    @Override
    public void acceptUnvisited(FlowNodeVisitor visitor, int level) {
        super.acceptUnvisited(visitor, level);
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.EVALUATE_BRANCH;
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        CobolVmSignal signal = acceptInterpreterForCompositeExecution(interpreter, flowControl);
        return flowControl.apply(() -> continueOrAbort(signal, interpreter, nodeService), signal);
    }

    @Override
    public String name() {
        return isWhenOther()
                ? "WHEN OTHER"
                : "WHEN\n" + conditionText();
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.DECISION_BRANCH);
    }

    @Override
    public List<FlowNode> astChildren() {
        return super.astChildren();
    }

    @Override
    public void resolve(SmojolSymbolTable symbolTable, CobolDataStructure dataStructures) {
        if (!isWhenOther()) {
            CobolExpressionBuilder builder = new CobolExpressionBuilder();
            List<CobolExpression> conditions = whenPhraseContext().evaluateWhen().stream()
                    .map(when -> {
                        if (when.evaluateCondition() == null) {
                            return new PrimitiveCobolExpression(com.mojo.algorithms.domain.TypedRecord.TRUE);
                        }
                        if (when.evaluateCondition().condition() != null) {
                            return builder.condition(when.evaluateCondition().condition(), nodeService.getDataStructures());
                        }
                        if (when.evaluateCondition().booleanLiteral() != null) {
                            return new PrimitiveCobolExpression(com.mojo.algorithms.domain.TypedRecord
                                    .typedBoolean(Boolean.parseBoolean(when.evaluateCondition().booleanLiteral().getText())));
                        }
                        if (when.evaluateCondition().evaluateValue() != null
                                && when.evaluateCondition().evaluateValue().arithmeticExpression() != null) {
                            return new SimpleConditionExpression(
                                    new PrimitiveCobolExpression(com.mojo.algorithms.domain.TypedRecord.TRUE),
                                    new RelationExpression(RelationalOperation.EQUAL,
                                            builder.arithmetic(when.evaluateCondition().evaluateValue().arithmeticExpression())));
                        }
                        return new PrimitiveCobolExpression(com.mojo.algorithms.domain.TypedRecord.TRUE);
                    })
                    .toList();
            conditionExpression = collapseOr(conditions);
        }
        super.resolve(symbolTable, dataStructures);
    }

    @Override
    public List<? extends ParseTree> getChildren() {
        if (executionContext instanceof CobolParser.EvaluateWhenPhraseContext whenPhraseContext) {
            return whenPhraseContext.conditionalStatementCall();
        }
        if (executionContext instanceof CobolParser.EvaluateWhenOtherContext whenOtherContext) {
            return whenOtherContext.conditionalStatementCall();
        }
        return List.of();
    }

    @Override
    public Map<String, Object> metadata() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("branch_kind", isWhenOther() ? "WHEN_OTHER" : "WHEN");
        metadata.put("condition_text", conditionText());
        metadata.put("conditions", conditionTexts());
        if (conditionExpression != null) {
            metadata.put("condition_expression", conditionExpression.description());
        }
        return metadata;
    }

    private boolean isWhenOther() {
        return executionContext instanceof CobolParser.EvaluateWhenOtherContext;
    }

    private CobolParser.EvaluateWhenPhraseContext whenPhraseContext() {
        return (CobolParser.EvaluateWhenPhraseContext) executionContext;
    }

    private String conditionText() {
        return isWhenOther()
                ? "OTHER"
                : String.join(" OR ", conditionTexts());
    }

    private List<String> conditionTexts() {
        if (isWhenOther()) return ImmutableList.of("OTHER");
        return whenPhraseContext().evaluateWhen().stream()
                .map(when -> NodeText.originalText(when, NodeText::PASSTHROUGH))
                .toList();
    }

    private CobolExpression collapseOr(List<CobolExpression> conditions) {
        if (conditions.isEmpty()) return null;
        CobolExpression current = conditions.getFirst();
        for (int i = 1; i < conditions.size(); i++) {
            current = new OrExpression(current, conditions.get(i));
        }
        return current;
    }
}
