package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import org.antlr.v4.runtime.tree.ParseTree;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.ast.FlowNodeService;
import org.smojol.common.vm.stack.StackFrames;

import java.util.List;
import java.util.Map;

public class AlterFlowNode extends CobolFlowNode {
    public AlterFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.ALTER;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.CONTROL_FLOW);
    }

    @Override
    public Map<String, Object> metadata() {
        return Map.of(
                "dynamic_control_hazard", true,
                "warning", "ALTER changes control flow dynamically and is not statically resolved"
        );
    }
}
