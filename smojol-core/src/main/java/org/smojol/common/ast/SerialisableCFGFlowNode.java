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
    private final List<String> variablesRead;
    private final List<String> variablesModified;
    private final String variableUsageSource;
    private final String nodeType = "CODE_VERTEX";
    private Boolean reachable;
    private String reachabilitySource;
    private Boolean deadCodeCandidate;

    protected SerialisableCFGFlowNode(String id, String label, String name, String originalText, FlowNodeType type,
                                      List<SemanticCategory> categories, Map<String, Object> metadata,
                                      List<String> variablesRead, List<String> variablesModified,
                                      String variableUsageSource) {
        this.id = id;
        this.label = label;
        this.name = name;
        this.originalText = originalText;
        this.type = type;
        this.categories = categories;
        this.metadata = metadata;
        this.variablesRead = emptyToNull(variablesRead);
        this.variablesModified = emptyToNull(variablesModified);
        this.variableUsageSource = this.variablesRead != null || this.variablesModified != null
                ? variableUsageSource : null;
    }

    public SerialisableCFGFlowNode(FlowNodeLike current) {
        this(current.id(), current.label(), current.name(), current.originalText(), current.type(),
                current.categories(), current.metadata(), variablesRead(current), variablesModified(current),
                "java_flow_node_expressions");
    }

    private static List<String> variablesRead(FlowNodeLike current) {
        if (current instanceof VariableUsageProvider provider) return provider.variablesRead();
        return List.of();
    }

    private static List<String> variablesModified(FlowNodeLike current) {
        if (current instanceof VariableUsageProvider provider) return provider.variablesModified();
        return List.of();
    }

    private static List<String> emptyToNull(List<String> values) {
        return values == null || values.isEmpty() ? null : values;
    }

    public void annotateReachability(boolean isReachable, String source) {
        reachable = isReachable;
        reachabilitySource = source;
        if (type == FlowNodeType.PARAGRAPH) {
            deadCodeCandidate = !isReachable;
        }
    }
}
