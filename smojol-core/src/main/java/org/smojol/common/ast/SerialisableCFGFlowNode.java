package org.smojol.common.ast;

import com.mojo.algorithms.transpiler.FlowNodeLike;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.Token;
import org.antlr.v4.runtime.tree.TerminalNode;

import java.util.ArrayList;
import java.util.LinkedHashMap;
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
    private final Integer sourceLine;
    private final Integer sourceColumn;
    private final Integer sourceEndLine;
    private final Integer sourceEndColumn;
    private final String lineOrigin;
    private final String sourceLocationSource;
    private final String nodeType = "CODE_VERTEX";
    private Boolean reachable;
    private String reachabilitySource;
    private Boolean deadCodeCandidate;

    protected SerialisableCFGFlowNode(String id, String label, String name, String originalText, FlowNodeType type,
                                      List<SemanticCategory> categories, Map<String, Object> metadata,
                                      List<String> variablesRead, List<String> variablesModified,
                                      String variableUsageSource, SourceLocation sourceLocation) {
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
        this.sourceLine = sourceLocation.sourceLine();
        this.sourceColumn = sourceLocation.sourceColumn();
        this.sourceEndLine = sourceLocation.sourceEndLine();
        this.sourceEndColumn = sourceLocation.sourceEndColumn();
        this.lineOrigin = sourceLocation.lineOrigin();
        this.sourceLocationSource = sourceLocation.sourceLocationSource();
    }

    protected SerialisableCFGFlowNode(String id, String label, String name, String originalText, FlowNodeType type,
                                      List<SemanticCategory> categories, Map<?, ?> metadata,
                                      List<?> variablesRead, List<?> variablesModified,
                                      String variableUsageSource) {
        this(id, label, name, originalText, type, categories, stringKeyMap(metadata),
                stringList(variablesRead), stringList(variablesModified), variableUsageSource, SourceLocation.empty());
    }

    public SerialisableCFGFlowNode(FlowNodeLike current) {
        this(current.id(), current.label(), current.name(), current.originalText(), current.type(),
                current.categories(), current.metadata(), variablesRead(current), variablesModified(current),
                "java_flow_node_expressions", sourceLocation(current));
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

    private static Map<String, Object> stringKeyMap(Map<?, ?> values) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : values.entrySet()) {
            result.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        return result;
    }

    private static List<String> stringList(List<?> values) {
        List<String> result = new ArrayList<>();
        for (Object value : values) {
            result.add(String.valueOf(value));
        }
        return result;
    }

    private static SourceLocation sourceLocation(FlowNodeLike current) {
        if (!(current instanceof FlowNode flowNode)) return SourceLocation.empty();
        Token start = startToken(flowNode);
        if (start == null) return SourceLocation.empty();
        Token stop = stopToken(flowNode);
        return new SourceLocation(
                start.getLine(),
                start.getCharPositionInLine(),
                stop == null ? start.getLine() : stop.getLine(),
                stop == null ? start.getCharPositionInLine() : stop.getCharPositionInLine(),
                "parser_source",
                "java_parser_token"
        );
    }

    private static Token startToken(FlowNode flowNode) {
        if (flowNode.getExecutionContext() instanceof TerminalNode terminalNode) {
            return terminalNode.getSymbol();
        }
        if (flowNode.getExecutionContext() instanceof ParserRuleContext parserRuleContext) {
            return parserRuleContext.getStart();
        }
        return null;
    }

    private static Token stopToken(FlowNode flowNode) {
        if (flowNode.getExecutionContext() instanceof TerminalNode terminalNode) {
            return terminalNode.getSymbol();
        }
        if (flowNode.getExecutionContext() instanceof ParserRuleContext parserRuleContext) {
            return parserRuleContext.getStop();
        }
        return null;
    }

    public void annotateReachability(boolean isReachable, String source) {
        reachable = isReachable;
        reachabilitySource = source;
        if (type == FlowNodeType.PARAGRAPH) {
            deadCodeCandidate = !isReachable;
        }
    }

    public void annotateCallResolution(String target, String targetSource, String confidence, String note) {
        if (target != null && !target.isBlank()) metadata.put("resolved_call_target", target);
        metadata.put("call_target_source", targetSource);
        metadata.put("dynamic_call_resolution_confidence", confidence);
        if (note != null && !note.isBlank()) metadata.put("dynamic_call_resolution_note", note);
    }

    private record SourceLocation(
            Integer sourceLine,
            Integer sourceColumn,
            Integer sourceEndLine,
            Integer sourceEndColumn,
            String lineOrigin,
            String sourceLocationSource) {
        private static SourceLocation empty() {
            return new SourceLocation(null, null, null, null, null, null);
        }
    }
}
