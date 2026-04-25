package org.smojol.toolkit.ast;

import com.google.common.collect.ImmutableList;
import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.domain.SemanticCategory;
import lombok.Getter;
import org.antlr.v4.runtime.tree.ParseTree;
import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.ast.*;
import org.smojol.common.vm.stack.StackFrames;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public class CallFlowNode extends CobolFlowNode implements ExternalControlFlowNode {
    @Getter
    private final CallTarget callTarget;

    public CallFlowNode(ParseTree parseTree, FlowNode scope, FlowNodeService nodeService, StackFrames stackFrames) {
        super(parseTree, scope, nodeService, stackFrames);
        CobolParser.CallStatementContext callStmt = new SyntaxIdentity<CobolParser.CallStatementContext>(getExecutionContext()).get();
        callTarget = CallTargetBuilder.target(callStmt);
    }

    @Override
    public String label() {
        return originalText();
    }

    @Override
    public FlowNodeType type() {
        return FlowNodeType.CALL;
    }

    @Override
    public CallTarget callTarget() {
        return callTarget;
    }

    @Override
    public Map<String, Object> metadata() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("call_target", callTarget.getName());
        metadata.put("program_reference_type", callTarget.getProgramReferenceType().name());
        metadata.put("dynamic_call", callTarget.getProgramReferenceType() == ProgramReferenceType.DYNAMIC);
        List<Map<String, Object>> usingParameters = usingParameters(originalText());
        if (!usingParameters.isEmpty()) metadata.put("using_parameters", usingParameters);
        return metadata;
    }

    @Override
    public List<SemanticCategory> categories() {
        return ImmutableList.of(SemanticCategory.CONTROL_FLOW);
    }

    private List<Map<String, Object>> usingParameters(String text) {
        String upper = text.toUpperCase(Locale.ROOT);
        int usingIndex = upper.indexOf(" USING ");
        if (usingIndex < 0) return List.of();
        String usingText = upper.substring(usingIndex + " USING ".length())
                .replace(".", " ")
                .replace(",", " ");
        int endCallIndex = usingText.indexOf(" END-CALL");
        if (endCallIndex >= 0) usingText = usingText.substring(0, endCallIndex);

        List<Map<String, Object>> parameters = new ArrayList<>();
        String mode = "REFERENCE";
        for (String token : usingText.split("\\s+")) {
            if (token.isBlank()) continue;
            if ("BY".equals(token)) continue;
            if ("REFERENCE".equals(token) || "CONTENT".equals(token) || "VALUE".equals(token)) {
                mode = token;
                continue;
            }
            if (isUsingNoise(token)) continue;
            Map<String, Object> parameter = new LinkedHashMap<>();
            parameter.put("name", token);
            parameter.put("mode", mode);
            parameters.add(parameter);
        }
        return parameters;
    }

    private boolean isUsingNoise(String token) {
        return "ADDRESS".equals(token) || "OF".equals(token) || "LENGTH".equals(token)
                || "OMITTED".equals(token) || "NULL".equals(token);
    }
}
