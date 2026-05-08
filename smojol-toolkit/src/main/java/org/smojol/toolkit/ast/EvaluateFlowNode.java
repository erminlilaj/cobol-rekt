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
import org.smojol.common.vm.expression.EvaluateBreaker;
import org.smojol.common.vm.expression.ExpandedEvaluation;
import org.smojol.common.vm.interpreter.CobolInterpreter;
import org.smojol.common.vm.interpreter.CobolVmSignal;
import org.smojol.common.vm.interpreter.FlowControl;
import org.smojol.common.vm.stack.StackFrames;
import org.smojol.common.vm.structure.CobolDataStructure;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Getter
public class EvaluateFlowNode extends CobolFlowNode {
    private final List<CobolParser.EvaluateSelectContext> evaluationChannels = new ArrayList<>();
    private List<EvaluateBranchFlowNode> whenPhrases = List.of();
    private List<CobolExpression> evaluationSubjects = new ArrayList<>();
    private ExpandedEvaluation deconstructedRepresentation;

    public EvaluateFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public void buildInternalFlow() {
        CobolParser.EvaluateStatementContext whenStatement = new SyntaxIdentity<CobolParser.EvaluateStatementContext>(executionContext).get();
        evaluationChannels.add(whenStatement.evaluateSelect());
        evaluationChannels.addAll(whenStatement.evaluateAlsoSelect().stream().map(CobolParser.EvaluateAlsoSelectContext::evaluateSelect).toList());
        List<EvaluateBranchFlowNode> branches = new ArrayList<>();
        for (CobolParser.EvaluateWhenPhraseContext whenPhraseContext : whenStatement.evaluateWhenPhrase()) {
            EvaluateBranchFlowNode branchFlowNode = (EvaluateBranchFlowNode) nodeService.register(
                    new EvaluateBranchFlowNode(whenPhraseContext, this, nodeService, staticFrameContext));
            branchFlowNode.buildFlow();
            branches.add(branchFlowNode);
        }
        if (whenStatement.evaluateWhenOther() != null) {
            EvaluateBranchFlowNode whenOtherBranch = (EvaluateBranchFlowNode) nodeService.register(
                    new EvaluateBranchFlowNode(whenStatement.evaluateWhenOther(), this, nodeService, staticFrameContext));
            whenOtherBranch.buildFlow();
            branches.add(whenOtherBranch);
        }
        whenPhrases = branches;
        deconstructedRepresentation = new EvaluateBreaker(staticFrameContext, this, nodeService).decompose(whenStatement);
    }

    @Override
    public void acceptUnvisited(FlowNodeVisitor visitor, int level) {
        super.acceptUnvisited(visitor, level);
        whenPhrases.forEach(branch -> branch.acceptUnvisited(visitor, level));
        whenPhrases.forEach(branch -> visitor.visitParentChildLink(this, branch, new VisitContext(level), nodeService));
    }

    @Override
    public void buildControlFlow() {
        whenPhrases.forEach(FlowNode::buildControlFlow);
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.EVALUATE;
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        CobolVmSignal signal = interpreter.scope(this).execute(this, nodeService);
        return flowControl.apply(() -> continueOrAbort(signal, interpreter, nodeService), signal);
    }

    @Override
    public String name() {
        return "EVALUATE";
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.DECISION);
    }

    @Override
    public List<FlowNode> astChildren() {
        return ImmutableList.copyOf(whenPhrases);
    }

    @Override
    public void resolve(SmojolSymbolTable symbolTable, CobolDataStructure dataStructures) {
        whenPhrases.forEach(branch -> branch.resolve(symbolTable, dataStructures));
    }

    @Override
    public Map<String, Object> metadata() {
        return Map.of(
                "evaluation_subjects", evaluationChannels.stream()
                        .map(channel -> NodeText.originalText(channel, NodeText::PASSTHROUGH))
                        .toList(),
                "branch_count", whenPhrases.size()
        );
    }
}
