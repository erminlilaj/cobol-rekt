package org.smojol.common.ast;

import org.antlr.v4.runtime.tree.ParseTree;
import org.smojol.common.pseudocode.SmojolSymbolTable;
import org.smojol.common.vm.interpreter.CobolInterpreter;
import org.smojol.common.vm.interpreter.CobolVmSignal;
import org.smojol.common.vm.interpreter.FlowControl;
import org.smojol.common.vm.structure.CobolDataStructure;

import java.util.List;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import com.mojo.algorithms.domain.CodeSentinelType;

public class DecoratedFlowNode implements FlowNode {
    private final FlowNode inner;
    private final String decoration;

    public DecoratedFlowNode(FlowNode inner, String decoration) {
        this.inner = inner;
        this.decoration = decoration;
    }

    @Override
    public String label() {
        return inner.label() + "\n" + decoration;
    }

    @Override
    public String name() {
        return inner.name();
    }

    @Override
    public String originalText() {
        return inner.originalText();
    }

    @Override
    public String id() {
        return inner.id();
    }

    @Override
    public void buildFlow() {
        inner.buildFlow();
    }

    @Override
    public void buildOutgoingFlow() {
        inner.buildOutgoingFlow();
    }

    @Override
    public void buildInternalFlow() {
        inner.buildInternalFlow();
    }

    @Override
    public void buildControlFlow() {
        inner.buildControlFlow();
    }

    @Override
    public void goesTo(FlowNode successor) {
        inner.goesTo(successor);
    }

    @Override
    public void addIncomingNode(FlowNode flowNode) {
        inner.addIncomingNode(flowNode);
    }

    @Override
    public List<FlowNode> getOutgoingNodes() {
        return inner.getOutgoingNodes();
    }

    @Override
    public List<FlowNode> getIncomingNodes() {
        return inner.getIncomingNodes();
    }

    @Override
    public FlowNode next(FlowNodeCondition nodeCondition, FlowNode startingNode, boolean isComplete) {
        return inner.next(nodeCondition, startingNode, isComplete);
    }

    @Override
    public void linkParentToChild(FlowNodeVisitor visitor, int level) {
        inner.linkParentToChild(visitor, level);
    }

    @Override
    public void accept(FlowNodeVisitor visitor, int level) {
        inner.accept(visitor, level);
    }

    @Override
    public void accept(FlowNodeVisitor visitor, FlowNodeCondition stopCondition, int level) {
        inner.accept(visitor, stopCondition, level);
    }

    @Override
    public void acceptUnvisited(FlowNodeVisitor visitor, int level) {
        inner.acceptUnvisited(visitor, level);
    }

    @Override
    public void resolve(SmojolSymbolTable symbolTable, CobolDataStructure dataStructures) {
        inner.resolve(symbolTable, dataStructures);
    }

    @Override
    public List<? extends ParseTree> getChildren() {
        return inner.getChildren();
    }

    @Override
    public FlowNode findUpwards(FlowNodeCondition nodeCondition, FlowNode startingNode) {
        return inner.findUpwards(nodeCondition, startingNode);
    }

    @Override
    public FlowNode tail() {
        return inner.tail();
    }

    @Override
    public List<FlowNode> astChildren() {
        return inner.astChildren();
    }

    @Override
    public boolean accessesDatabase() {
        return inner.accessesDatabase();
    }

    @Override
    public boolean isMergeable() {
        return inner.isMergeable();
    }

    @Override
    public boolean contains(FlowNode node) {
        return inner.contains(node);
    }

    @Override
    public ParseTree getExecutionContext() {
        return inner.getExecutionContext();
    }

    @Override
    public FlowNode passthrough() {
        return inner.passthrough();
    }

    @Override
    public boolean isPassthrough() {
        return inner.isPassthrough();
    }

    @Override
    public CobolVmSignal acceptInterpreter(CobolInterpreter interpreter, FlowControl flowControl) {
        return inner.acceptInterpreter(interpreter, flowControl);
    }

    @Override
    public void addComment(CommentBlock cb) {
        inner.addComment(cb);
    }

    @Override
    public List<CommentBlock> getCommentBlocks() {
        return inner.getCommentBlocks();
    }

    @Override
    public void addChild(FlowNode child) {
        inner.addChild(child);
    }

    @Override
    public List<SemanticCategory> categories() {
        return inner.categories();
    }

    @Override
    public CodeSentinelType codeSentinelType() {
        return inner.codeSentinelType();
    }

    @Override
    public FlowNodeType type() {
        return inner.type();
    }

    @Override
    public void buildTwin() {
        inner.buildTwin();
    }
}
