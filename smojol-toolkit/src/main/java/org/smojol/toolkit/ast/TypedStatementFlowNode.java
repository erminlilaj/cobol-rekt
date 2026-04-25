package org.smojol.toolkit.ast;

import com.mojo.algorithms.domain.FlowNodeType;
import org.antlr.v4.runtime.tree.ParseTree;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.ast.FlowNodeService;
import org.smojol.common.vm.stack.StackFrames;

import java.util.LinkedHashMap;
import java.util.Map;

public class TypedStatementFlowNode extends GenericStatementFlowNode {
    private final FlowNodeType flowNodeType;

    public TypedStatementFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService,
                                  StackFrames stackFrames, FlowNodeType flowNodeType) {
        super(parseTree, scope, nodeService, stackFrames);
        this.flowNodeType = flowNodeType;
    }

    @Override
    public FlowNodeType type() {
        return flowNodeType;
    }

    @Override
    public Map<String, Object> metadata() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("statement_kind", flowNodeType.name());
        metadata.put("unsupported_semantics", true);
        metadata.put("semantics_status", "typed_only_linear_control_flow");
        return metadata;
    }
}
