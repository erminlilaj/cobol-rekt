package org.smojol.common.ast;

import com.mojo.algorithms.transpiler.FlowNodeLike;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;

import java.util.List;
import java.util.Map;

@Getter
public class SerialisableCFGFlowNode {
    private final String id;
    private final String label;
    private final String name;
    private final String originalText;
    private final FlowNodeType type;
    private final List<SemanticCategory> categories;
    private final Map<String, Object> metadata;
    private final String nodeType = "CODE_VERTEX";

    protected SerialisableCFGFlowNode(String id, String label, String name, String originalText, FlowNodeType type,
                                      List<SemanticCategory> categories, Map<String, Object> metadata) {
        this.id = id;
        this.label = label;
        this.name = name;
        this.originalText = originalText;
        this.type = type;
        this.categories = categories;
        this.metadata = metadata;
    }

    public SerialisableCFGFlowNode(FlowNodeLike current) {
        this(current.id(), current.label(), current.name(), current.originalText(), current.type(),
                current.categories(), current.metadata());
    }
}
