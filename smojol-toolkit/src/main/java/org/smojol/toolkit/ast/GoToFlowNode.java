package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;
import org.antlr.v4.runtime.RuleContext;
import org.antlr.v4.runtime.tree.ParseTree;
import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.ast.*;
import org.smojol.common.vm.expression.CobolExpression;
import org.smojol.common.vm.expression.CobolExpressionBuilder;
import org.smojol.common.vm.interpreter.CobolInterpreter;
import org.smojol.common.vm.interpreter.CobolVmSignal;
import org.smojol.common.vm.interpreter.FlowControl;
import org.smojol.common.vm.stack.StackFrames;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.logging.Logger;


@Getter
public class GoToFlowNode extends CobolFlowNode implements InternalControlFlowNode {
    private static final Logger logger = Logger.getLogger(GoToFlowNode.class.getName());

    private List<FlowNode> destinationNodes;
    private CobolExpression dependingFactor;

    public GoToFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public void buildOutgoingFlow() {
        super.buildOutgoingFlow();
    }

    @Override
    public String label() {
        return originalText();
    }

    @Override
    public void buildControlFlow() {
        CobolParser.GoToStatementContext goToStatement = new SyntaxIdentity<CobolParser.GoToStatementContext>(getExecutionContext()).get();
        List<CobolParser.ProcedureNameContext> procedureNames = goToStatement.procedureName();
        logger.finer("Found a GO TO, routing to " + String.join(",", procedureNames.stream().map(RuleContext::getText).toList()));
        destinationNodes = procedureNames.stream().map(p -> nodeService.sectionOrParaWithName(p.paragraphName().getText())).toList();
        if (dependsUponFactor()) dependingFactor = new CobolExpressionBuilder().identifier(goToStatement.generalIdentifier());
    }

    public boolean dependsUponFactor() {
        CobolParser.GoToStatementContext goToStatement = new SyntaxIdentity<CobolParser.GoToStatementContext>(getExecutionContext()).get();
        return goToStatement.DEPENDING() != null;
    }

    @Override
    public void acceptUnvisited(FlowNodeVisitor visitor, int level) {
        super.acceptUnvisited(visitor, level);
        destinationNodes.forEach(destinationNode -> visitor.visitControlTransfer(this, destinationNode, new VisitContext(level)));
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        return interpreter.scope(this).executeGoto(this, destinationNodes, nodeService);
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.GOTO;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.CONTROL_FLOW);
    }

    @Override
    public Map<String, Object> metadata() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        CobolParser.GoToStatementContext goToStatement = new SyntaxIdentity<CobolParser.GoToStatementContext>(getExecutionContext()).get();
        metadata.put("goto_targets", goToStatement.procedureName().stream()
                .map(RuleContext::getText).toList());
        if (dependsUponFactor()) {
            metadata.put("depending_on", goToStatement.generalIdentifier().getText());
            metadata.put("dynamic_control_hazard", true);
            metadata.put("warning", "GO TO DEPENDING ON chooses a target dynamically at runtime");
        }
        return metadata;
    }

    @Override
    public List<FlowNode> callTargets() {
        return destinationNodes;
    }
}
