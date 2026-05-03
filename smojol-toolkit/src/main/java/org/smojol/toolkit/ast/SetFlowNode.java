package org.smojol.toolkit.ast;

import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.tree.ParseTree;
import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.ast.FlowNodeService;
import org.smojol.common.ast.SyntaxIdentity;
import org.smojol.common.vm.stack.StackFrames;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class SetFlowNode extends CobolFlowNode {
    private CobolParser.SetToStatementContext setToStatement;

    public SetFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public void buildInternalFlow() {
        CobolParser.SetStatementContext setStatement = new SyntaxIdentity<CobolParser.SetStatementContext>(executionContext).get();
        setToStatement = setStatement.setToStatement();
        super.buildInternalFlow();
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.SET;
    }

    @Override
    public boolean isMergeable() {
        return true;
    }

    @Override
    public List<SemanticCategory> categories() {
        return List.of(SemanticCategory.DATA_FLOW);
    }

    @Override
    public List<String> variablesRead() {
        if (setToStatement == null || setToStatement.sendingField().generalIdentifier() == null) {
            return List.of();
        }
        return List.of(setToStatement.sendingField().generalIdentifier().getText().toUpperCase());
    }

    @Override
    public List<String> variablesModified() {
        if (setToStatement == null) {
            return List.of();
        }
        return setToStatement.receivingField().stream()
                .map(target -> target.generalIdentifier().getText().toUpperCase())
                .toList();
    }

    @Override
    public Map<String, Object> metadata() {
        if (setToStatement == null || setToStatement.sendingField().literal() == null) {
            return Map.of();
        }

        String value = setToStatement.sendingField().literal().getText();
        List<Map<String, Object>> assignments = new ArrayList<>();
        for (CobolParser.ReceivingFieldContext target : setToStatement.receivingField()) {
            Map<String, Object> assignment = new LinkedHashMap<>();
            assignment.put("target_variable", target.generalIdentifier().getText().toUpperCase());
            assignment.put("source_value", value);
            assignment.put("source_kind", "literal");
            assignment.put("statement_type", "SET");
            assignment.put("statement_text", originalText());
            assignment.put("provenance_source", "java_set_literal");
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
