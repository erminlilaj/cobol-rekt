package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.tree.ParseTree;
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

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Getter
public class ComputeFlowNode extends CobolFlowNode {
    @Getter private List<CobolParser.ComputeStoreContext> destinations;
    @Getter private CobolParser.ArithmeticExpressionContext rhs;
    private CobolExpression rhsExpression;
    private List<CobolExpression> destinationExpressions = ImmutableList.of();

    public ComputeFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public void buildInternalFlow() {
        CobolParser.ComputeStatementContext computeStatement = new SyntaxIdentity<CobolParser.ComputeStatementContext>(executionContext).get();
        destinations = computeStatement.computeStore();
        rhs = computeStatement.arithmeticExpression();
        super.buildInternalFlow();
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.COMPUTE;
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        CobolVmSignal signal = interpreter.scope(this).executeCompute(this, nodeService);
        return flowControl.apply(() -> continueOrAbort(signal, interpreter, nodeService), signal);
    }

    @Override
    public boolean isMergeable() {
        return true;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.COMPUTATIONAL, SemanticCategory.DATA_FLOW);
    }

    @Override
    public void resolve(SmojolSymbolTable symbolTable, CobolDataStructure dataStructures) {
        CobolExpressionBuilder builder = new CobolExpressionBuilder();
        rhsExpression = builder.arithmetic(rhs);
        destinationExpressions = destinations.stream().map(dest -> builder.identifier(dest.generalIdentifier())).toList();
    }

    @Override
    public List<String> variablesRead() {
        return VariableUsageCollector.variableNamesIn(rhsExpression);
    }

    @Override
    public List<String> variablesModified() {
        return VariableUsageCollector.variableNamesIn(destinationExpressions);
    }

    @Override
    public Map<String, Object> metadata() {
        if (rhs == null || destinations == null || destinations.isEmpty()) {
            return Map.of();
        }
        String value = rhs.getText();
        if (!value.matches("\\d+(\\.\\d+)?")) {
            return Map.of();
        }

        List<Map<String, Object>> assignments = new ArrayList<>();
        for (CobolParser.ComputeStoreContext destination : destinations) {
            Map<String, Object> assignment = new LinkedHashMap<>();
            assignment.put("target_variable", destination.generalIdentifier().getText().toUpperCase());
            assignment.put("source_value", value);
            assignment.put("source_kind", "numeric_literal");
            assignment.put("statement_type", "COMPUTE");
            assignment.put("statement_text", originalText());
            assignment.put("provenance_source", "java_compute_numeric_literal");
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
}
