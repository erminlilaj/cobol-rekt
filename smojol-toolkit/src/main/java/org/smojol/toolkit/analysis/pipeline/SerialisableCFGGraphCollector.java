package org.smojol.toolkit.analysis.pipeline;


import com.mojo.woof.NodeRelations;
import com.mojo.algorithms.domain.FlowNodeType;
import org.smojol.common.ast.*;
import com.mojo.algorithms.id.IdProvider;

import java.util.ArrayList;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class SerialisableCFGGraphCollector implements FlowNodeVisitor {
    private static final String REACHABILITY_SOURCE = "java_cfg_graph_traversal";
    private final List<SerialisableCFGFlowNode> nodes = new ArrayList<>();
    private final List<SerialisableEdge> edges = new ArrayList<>();
    private final IdProvider idProvider;
    private final Map<String, Integer> parentChildEdgeCounts = new HashMap<>();

    public SerialisableCFGGraphCollector(IdProvider idProvider) {
        this.idProvider = idProvider;
    }

    @Override
    public void visit(FlowNode node, List<FlowNode> outgoingNodes, List<FlowNode> incomingNodes, VisitContext context, FlowNodeService nodeService) {
        nodes.add(new SerialisableCFGFlowNode(node));
        edges.addAll(outgoingNodes.stream()
                .map(o -> edge(node, o, NodeRelations.FOLLOWED_BY, null)).toList());
    }

    @Override
    public void visitParentChildLink(FlowNode parent, FlowNode internalTreeRoot, VisitContext ctx, FlowNodeService nodeService) {
        visitParentChildLink(parent, internalTreeRoot, ctx, nodeService, FlowNodeCondition.ALWAYS_SHOW);
    }

    @Override
    public void visitParentChildLink(FlowNode parent, FlowNode internalTreeRoot, VisitContext ctx, FlowNodeService nodeService, FlowNodeCondition hideStrategy) {
        edges.add(edge(parent, internalTreeRoot, NodeRelations.STARTS_WITH, branchCondition(parent)));
    }

    @Override
    public void visitControlTransfer(FlowNode from, FlowNode to, VisitContext visitContext) {
        edges.add(edge(from, to, NodeRelations.JUMPS_TO, null));
    }

    @Override
    public FlowNodeVisitor newScope(FlowNode enclosingScope) {
        return this;
    }

    @Override
    public void group(FlowNode root) {

    }

    public void annotateReachability() {
        if (nodes.isEmpty()) return;
        Map<String, SerialisableCFGFlowNode> nodeById = new HashMap<>();
        Map<String, List<String>> outgoing = new HashMap<>();
        Set<String> incoming = new HashSet<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeById.put(node.getId(), node);
        }
        for (SerialisableEdge edge : edges) {
            outgoing.computeIfAbsent(edge.fromNodeID(), ignored -> new ArrayList<>()).add(edge.toNodeID());
            incoming.add(edge.toNodeID());
        }

        ArrayDeque<String> queue = new ArrayDeque<>();
        nodes.stream()
                .filter(node -> node.getType() == FlowNodeType.PROCEDURE_DIVISION_BODY)
                .map(SerialisableCFGFlowNode::getId)
                .forEach(queue::add);
        if (queue.isEmpty()) {
            nodes.stream()
                    .filter(node -> !incoming.contains(node.getId()))
                    .map(SerialisableCFGFlowNode::getId)
                    .forEach(queue::add);
        }
        if (queue.isEmpty()) {
            queue.add(nodes.getFirst().getId());
        }

        Set<String> reachable = new HashSet<>();
        while (!queue.isEmpty()) {
            String id = queue.removeFirst();
            if (!reachable.add(id)) continue;
            for (String target : outgoing.getOrDefault(id, List.of())) {
                if (!reachable.contains(target)) queue.add(target);
            }
        }

        for (SerialisableCFGFlowNode node : nodes) {
            node.annotateReachability(reachable.contains(node.getId()), REACHABILITY_SOURCE);
        }
        annotateDynamicCallResolution();
    }

    private SerialisableEdge edge(FlowNode from, FlowNode to, String edgeType, String condition) {
        return new SerialisableEdge(
                idProvider.next(),
                from.id(),
                to.id(),
                edgeType,
                from.label(),
                to.label(),
                from.originalText(),
                condition,
                sourceLine(from),
                sourceColumn(from),
                "parser_source"
        );
    }

    private String branchCondition(FlowNode parent) {
        if (parent.type() != FlowNodeType.IF_BRANCH) return null;
        Object rawCondition = parent.metadata().get("condition_text");
        if (!(rawCondition instanceof String condition) || condition.isBlank()) return null;
        int edgeIndex = parentChildEdgeCounts.merge(parent.id(), 1, Integer::sum);
        if (edgeIndex == 1) return condition;
        if (edgeIndex == 2) return "NOT (" + condition + ")";
        return null;
    }

    private Integer sourceLine(FlowNode node) {
        if (node.getExecutionContext() instanceof org.antlr.v4.runtime.ParserRuleContext ctx
                && ctx.getStart() != null) {
            return ctx.getStart().getLine();
        }
        if (node.getExecutionContext() instanceof org.antlr.v4.runtime.tree.TerminalNode terminalNode
                && terminalNode.getSymbol() != null) {
            return terminalNode.getSymbol().getLine();
        }
        return null;
    }

    private Integer sourceColumn(FlowNode node) {
        if (node.getExecutionContext() instanceof org.antlr.v4.runtime.ParserRuleContext ctx
                && ctx.getStart() != null) {
            return ctx.getStart().getCharPositionInLine();
        }
        if (node.getExecutionContext() instanceof org.antlr.v4.runtime.tree.TerminalNode terminalNode
                && terminalNode.getSymbol() != null) {
            return terminalNode.getSymbol().getCharPositionInLine();
        }
        return null;
    }

    private void annotateDynamicCallResolution() {
        Map<String, String> latestLiteralAssignments = new HashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            Object assignmentFacts = node.getMetadata().get("assignment_facts");
            if (assignmentFacts instanceof List<?> facts) {
                for (Object fact : facts) {
                    if (!(fact instanceof Map<?, ?> assignment)) continue;
                    Object target = assignment.get("target_variable");
                    Object value = assignment.get("source_value");
                    Object kind = assignment.get("source_kind");
                    if (target instanceof String targetVariable && value instanceof String sourceValue
                            && ("literal".equals(kind) || isQuotedLiteral(sourceValue))) {
                        latestLiteralAssignments.put(targetVariable, unquote(sourceValue));
                    }
                }
            }

            Object referenceType = node.getMetadata().get("program_reference_type");
            Object callTarget = node.getMetadata().get("call_target");
            if (referenceType instanceof String && callTarget instanceof String target) {
                if ("STATIC".equals(referenceType)) {
                    node.annotateCallResolution(target, "literal", "high", null);
                } else if ("DYNAMIC".equals(referenceType)) {
                    node.getMetadata().put("call_target_identifier", target);
                    String resolved = latestLiteralAssignments.get(target);
                    if (resolved != null && !resolved.isBlank()) {
                        node.annotateCallResolution(
                                resolved,
                                "inferred_literal_assignment",
                                "medium",
                                "Resolved from the latest Java CFG literal assignment to the dynamic call identifier; not path-sensitive."
                        );
                    } else {
                        node.annotateCallResolution(
                                target,
                                "unresolved_identifier",
                                "low",
                                "Dynamic call target identifier is preserved, but no Java CFG literal assignment was found before this node."
                        );
                    }
                }
            }
            annotateCicsResolution(node, latestLiteralAssignments);
        }
    }

    private void annotateCicsResolution(SerialisableCFGFlowNode node, Map<String, String> latestLiteralAssignments) {
        Object command = node.getMetadata().get("cics_command");
        if (!(command instanceof String)) return;
        Object targetSource = node.getMetadata().get("cics_target_source");
        Object target = node.getMetadata().get("cics_target");
        if (!(target instanceof String targetValue)) return;

        if ("literal".equals(targetSource)) {
            putCicsResolution(node, targetValue, "literal", "high", null);
            return;
        }
        if (!"identifier".equals(targetSource)) return;

        node.getMetadata().put("cics_target_identifier", targetValue);
        String resolved = latestLiteralAssignments.get(targetValue);
        if (resolved != null && !resolved.isBlank()) {
            putCicsResolution(
                    node,
                    resolved,
                    "inferred_literal_assignment",
                    "medium",
                    "Resolved from the latest Java CFG literal assignment to the CICS target identifier; not path-sensitive."
            );
        } else {
            putCicsResolution(
                    node,
                    targetValue,
                    "unresolved_identifier",
                    "low",
                    "CICS target identifier is preserved, but no Java CFG literal assignment was found before this node."
            );
        }
    }

    @SuppressWarnings("unchecked")
    private void putCicsResolution(SerialisableCFGFlowNode node, String target, String targetSource,
                                   String confidence, String note) {
        node.getMetadata().put("resolved_cics_target", target);
        node.getMetadata().put("cics_target_source", targetSource);
        node.getMetadata().put("cics_dynamic_resolution_confidence", confidence);
        if (note != null && !note.isBlank()) node.getMetadata().put("cics_dynamic_resolution_note", note);
        Object operation = node.getMetadata().get("cics_operation");
        if (operation instanceof Map<?, ?> rawOperation) {
            Map<String, Object> cicsOperation = (Map<String, Object>) rawOperation;
            cicsOperation.put("target", target);
            cicsOperation.put("target_source", targetSource);
            cicsOperation.put("resolution_confidence", confidence);
        }
        Object arguments = node.getMetadata().get("cics_arguments");
        if (arguments instanceof List<?> argumentList) {
            for (Object item : argumentList) {
                if (!(item instanceof Map<?, ?> rawArgument)) continue;
                Map<String, Object> argument = (Map<String, Object>) rawArgument;
                String name = String.valueOf(argument.get("name"));
                if (!List.of("PROGRAM", "FILE", "DATASET", "MAP", "QUEUE", "QNAME", "TRANSID").contains(name)) continue;
                if ("identifier".equals(argument.get("value_source"))) {
                    argument.put("resolved_value", target);
                    argument.put("resolved_value_source", targetSource);
                }
            }
        }
    }

    private boolean isQuotedLiteral(String value) {
        return (value.startsWith("'") && value.endsWith("'"))
                || (value.startsWith("\"") && value.endsWith("\""));
    }

    private String unquote(String value) {
        if (isQuotedLiteral(value) && value.length() >= 2) {
            return value.substring(1, value.length() - 1);
        }
        return value;
    }
}
