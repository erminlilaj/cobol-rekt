package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import org.smojol.common.ast.*;
import org.smojol.common.idms.DialectContainerNode;
import org.smojol.common.vm.stack.StackFrames;

import java.util.List;
import java.util.Map;

public class CicsBlockFlowNode extends CobolFlowNode {

    public CicsBlockFlowNode(DialectContainerNode containerNode, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(containerNode, scope, nodeService, stackFrames);
    }

    @Override
    public String label() {
        return originalText();
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.DIALECT_CONTAINER;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.TRANSACTION);
    }

    @Override
    public Map<String, Object> metadata() {
        List<Map<String, Object>> handlerBindings = CicsHandleBindingParser.parse(originalText());
        if (handlerBindings.isEmpty()) return Map.of();
        return Map.of("handler_bindings", handlerBindings);
    }
}
