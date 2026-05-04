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

public class InitializeFlowNode extends CobolFlowNode {
    private CobolParser.InitializeStatementContext initializeStatement;

    public InitializeFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public void buildInternalFlow() {
        initializeStatement = new SyntaxIdentity<CobolParser.InitializeStatementContext>(executionContext).get();
        super.buildInternalFlow();
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.INITIALIZE;
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
        if (initializeStatement == null || initializeStatement.initializeReplacingPhrase() == null) {
            return List.of();
        }
        return initializeStatement.initializeReplacingPhrase().initializeReplacingBy().stream()
                .filter(replacingBy -> replacingBy.generalIdentifier() != null)
                .map(replacingBy -> replacingBy.generalIdentifier().getText().toUpperCase())
                .toList();
    }

    @Override
    public List<String> variablesModified() {
        if (initializeStatement == null) {
            return List.of();
        }
        return initializeStatement.generalIdentifier().stream()
                .map(target -> target.getText().toUpperCase())
                .toList();
    }

    @Override
    public Map<String, Object> metadata() {
        if (initializeStatement == null) {
            return Map.of();
        }

        List<Map<String, Object>> initializeFacts = new ArrayList<>();
        for (CobolParser.GeneralIdentifierContext target : initializeStatement.generalIdentifier()) {
            Map<String, Object> fact = baseFact(target.getText().toUpperCase());
            List<Map<String, Object>> replacements = replacementFacts();
            if (!replacements.isEmpty()) fact.put("replacements", replacements);
            initializeFacts.add(fact);
        }
        return Map.of("initialize_facts", initializeFacts);
    }

    private List<Map<String, Object>> replacementFacts() {
        if (initializeStatement.initializeReplacingPhrase() == null) {
            return List.of();
        }
        List<Map<String, Object>> replacements = new ArrayList<>();
        for (CobolParser.InitializeReplacingByContext replacingBy
                : initializeStatement.initializeReplacingPhrase().initializeReplacingBy()) {
            Map<String, Object> replacement = new LinkedHashMap<>();
            replacement.put("category", replacingBy.categoryName().getText().toUpperCase());
            if (replacingBy.literal() != null) {
                replacement.put("source_value", replacingBy.literal().getText());
                replacement.put("source_kind", "literal");
                replacement.put("provenance_source", "java_initialize_replacing_literal");
            } else if (replacingBy.generalIdentifier() != null) {
                replacement.put("source_variable", replacingBy.generalIdentifier().getText().toUpperCase());
                replacement.put("source_kind", "identifier");
                replacement.put("provenance_source", "java_initialize_replacing_identifier");
            }
            replacements.add(replacement);
        }
        return replacements;
    }

    private Map<String, Object> baseFact(String targetVariable) {
        Map<String, Object> fact = new LinkedHashMap<>();
        fact.put("target_variable", targetVariable);
        fact.put("statement_type", "INITIALIZE");
        fact.put("statement_text", originalText());
        fact.put("provenance_source", "java_initialize_statement");
        String paragraph = enclosingName(FlowNodeType.PARAGRAPH);
        if (paragraph != null) fact.put("paragraph", paragraph);
        String section = enclosingName(FlowNodeType.SECTION);
        if (section != null) fact.put("section", section);
        Integer line = sourceLine();
        if (line != null) fact.put("source_line", line);
        return fact;
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
