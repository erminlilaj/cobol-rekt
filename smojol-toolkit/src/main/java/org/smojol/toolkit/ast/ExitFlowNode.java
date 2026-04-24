package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import org.antlr.v4.runtime.tree.ParseTree;
import org.smojol.common.ast.FlowNode;
import com.mojo.algorithms.domain.SemanticCategory;
import org.smojol.common.ast.FlowNodeService;
import com.mojo.algorithms.domain.FlowNodeType;
import org.smojol.common.ast.SyntaxIdentity;
import org.smojol.common.vm.interpreter.CobolInterpreter;
import org.smojol.common.vm.interpreter.CobolVmSignal;
import org.smojol.common.vm.interpreter.FlowControl;
import org.smojol.common.vm.stack.StackFrames;

import java.util.List;
import java.util.Map;

import org.eclipse.lsp.cobol.core.CobolParser;

public class ExitFlowNode extends CobolFlowNode {
    public ExitFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        return interpreter.scope(this).executeExit(this, nodeService);
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.EXIT;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.TERMINAL);
    }

    @Override
    public Map<String, Object> metadata() {
        return Map.of("exit_kind", exitKind());
    }

    private String exitKind() {
        ParseTree target = new SyntaxIdentity<ParseTree>(executionContext).get();
        if (target instanceof CobolParser.GobackStatementContext) return "GOBACK";
        if (!(target instanceof CobolParser.ExitStatementContext)) return "EXIT";

        String upperText = target.getText().toUpperCase();
        if (upperText.contains("EXITPARAGRAPH")) return "EXIT_PARAGRAPH";
        if (upperText.contains("EXITSECTION")) return "EXIT_SECTION";
        if (upperText.contains("EXITPERFORM")) return "EXIT_PERFORM";
        if (upperText.contains("EXITPROGRAM")) return "EXIT_PROGRAM";
        return "EXIT";
    }
}
