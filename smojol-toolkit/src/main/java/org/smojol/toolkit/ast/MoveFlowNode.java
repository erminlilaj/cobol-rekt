package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;
import org.antlr.v4.runtime.tree.ParseTree;
import org.antlr.v4.runtime.ParserRuleContext;
import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.ast.*;
import org.smojol.common.pseudocode.SmojolSymbolTable;
import org.smojol.common.vm.expression.CobolExpression;
import org.smojol.common.vm.expression.CobolExpressionBuilder;
import org.smojol.common.vm.interpreter.CobolInterpreter;
import org.smojol.common.vm.interpreter.CobolVmSignal;
import org.smojol.common.vm.interpreter.FlowControl;
import org.smojol.common.vm.stack.StackFrames;
import org.smojol.common.vm.structure.CobolDataStructure;
import com.mojo.algorithms.types.AbstractCobolType;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Getter
public class MoveFlowNode extends CobolFlowNode {
    private CobolParser.MoveToSendingAreaContext fromSingle;
    private List<CobolParser.GeneralIdentifierContext> tos;
    private List<CobolExpression> fromExpressions = ImmutableList.of();
    private List<CobolExpression> toExpressions = ImmutableList.of();

    public MoveFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    // TODO: Support CORRESPONDING, fromSingle only looks at MoveTo
    @Override
    public void buildInternalFlow() {
        CobolParser.MoveStatementContext moveStatement = new SyntaxIdentity<CobolParser.MoveStatementContext>(executionContext).get();
        fromSingle = Optional.of(moveStatement)
                .map(CobolParser.MoveStatementContext::moveToStatement)
                .map(CobolParser.MoveToStatementContext::moveToSendingArea).orElse(null);
        tos = moveStatement.moveToStatement() != null
                ? moveStatement.moveToStatement().generalIdentifier()
                : moveStatement.moveCorrespondingToStatement().generalIdentifier();
        super.buildInternalFlow();
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.MOVE;
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        CobolVmSignal signal = interpreter.scope(this).executeMove(this, nodeService);
        return flowControl.apply(() -> continueOrAbort(signal, interpreter, nodeService), signal);
    }

    @Override
    public boolean isMergeable() {
        return true;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.DATA_FLOW);
    }

    @Override
    public void resolve(SmojolSymbolTable symbolTable, CobolDataStructure dataStructures) {
        CobolParser.MoveStatementContext moveStatement = new SyntaxIdentity<CobolParser.MoveStatementContext>(executionContext).get();
        CobolExpressionBuilder builder = new CobolExpressionBuilder();
        toExpressions = toExpressions(moveStatement, builder);
        if (moveStatement.moveToStatement() != null) {
            CobolParser.MoveToSendingAreaContext sendingArea = moveStatement.moveToStatement().moveToSendingArea();
            AbstractCobolType expectedType = toExpressions.getFirst().expressionType(dataStructures);
            // TODO: Maybe distribute this across multiple expressions, one corresponding to each destination, but with a separate type
            fromExpressions = ImmutableList.of(sendingArea.literal() != null ? builder.literal(sendingArea.literal(), expectedType) : builder.identifier(sendingArea.generalIdentifier()));
        } else {
            CobolParser.MoveCorrespondingToSendingAreaContext sendingArea = moveStatement.moveCorrespondingToStatement().moveCorrespondingToSendingArea();
            fromExpressions = ImmutableList.of(builder.identifier(sendingArea.generalIdentifier()));
        }
    }

    @Override
    public List<String> variablesRead() {
        return VariableUsageCollector.variableNamesIn(fromExpressions);
    }

    @Override
    public List<String> variablesModified() {
        return VariableUsageCollector.variableNamesIn(toExpressions);
    }

    @Override
    public Map<String, Object> metadata() {
        if (fromSingle == null || fromSingle.literal() == null || tos == null || tos.isEmpty()) {
            return Map.of();
        }

        String value = fromSingle.literal().getText();
        List<Map<String, Object>> assignments = new ArrayList<>();
        for (CobolParser.GeneralIdentifierContext target : tos) {
            Map<String, Object> assignment = new LinkedHashMap<>();
            assignment.put("target_variable", target.getText().toUpperCase());
            assignment.put("source_value", value);
            assignment.put("source_kind", "literal");
            assignment.put("statement_type", "MOVE");
            assignment.put("statement_text", originalText());
            assignment.put("provenance_source", "java_move_literal");
            String paragraph = enclosingName(FlowNodeType.PARAGRAPH);
            if (paragraph != null) assignment.put("paragraph", paragraph);
            String section = enclosingName(FlowNodeType.SECTION);
            if (section != null) assignment.put("section", section);
            Integer line = sourceLine();
            if (line != null) assignment.put("source_line", line);
            assignments.add(assignment);
        }
        return Map.of("assignment_facts", assignments);
    }

    private String enclosingName(FlowNodeType type) {
        FlowNode current = scope;
        while (current != null) {
            if (current.type() == type) return current.name();
            if (!(current instanceof CobolFlowNode cobolFlowNode)) return null;
            current = cobolFlowNode.scope;
        }
        return null;
    }

    private Integer sourceLine() {
        if (!(executionContext instanceof ParserRuleContext parserRuleContext)) return null;
        return parserRuleContext.getStart() == null ? null : parserRuleContext.getStart().getLine();
    }

    private static List<CobolExpression> toExpressions(CobolParser.MoveStatementContext moveStatement, CobolExpressionBuilder builder) {
        if (moveStatement.moveToStatement() != null)
            return moveStatement.moveToStatement().generalIdentifier().stream().map(builder::identifier).toList();
        else
            return moveStatement.moveCorrespondingToStatement().generalIdentifier().stream().map(builder::identifier).toList();
    }
}
