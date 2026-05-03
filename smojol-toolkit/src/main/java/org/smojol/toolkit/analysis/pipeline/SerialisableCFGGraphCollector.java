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

    public SerialisableCFGGraphCollector(IdProvider idProvider) {
        this.idProvider = idProvider;
    }

    @Override
    public void visit(FlowNode node, List<FlowNode> outgoingNodes, List<FlowNode> incomingNodes, VisitContext context, FlowNodeService nodeService) {
        nodes.add(new SerialisableCFGFlowNode(node));
        edges.addAll(outgoingNodes.stream()
                .map(o -> new SerialisableEdge(idProvider.next(), node.id(), o.id(), NodeRelations.FOLLOWED_BY)).toList());
    }

    @Override
    public void visitParentChildLink(FlowNode parent, FlowNode internalTreeRoot, VisitContext ctx, FlowNodeService nodeService) {
        visitParentChildLink(parent, internalTreeRoot, ctx, nodeService, FlowNodeCondition.ALWAYS_SHOW);
    }

    @Override
    public void visitParentChildLink(FlowNode parent, FlowNode internalTreeRoot, VisitContext ctx, FlowNodeService nodeService, FlowNodeCondition hideStrategy) {
        edges.add(new SerialisableEdge(idProvider.next(), parent.id(),
                internalTreeRoot.id(), NodeRelations.STARTS_WITH));
    }

    @Override
    public void visitControlTransfer(FlowNode from, FlowNode to, VisitContext visitContext) {
        edges.add(new SerialisableEdge(idProvider.next(), from.id(),
                to.id(), NodeRelations.JUMPS_TO));
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
    }
}
