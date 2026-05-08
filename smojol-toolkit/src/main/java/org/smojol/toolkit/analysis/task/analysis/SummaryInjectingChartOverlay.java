package org.smojol.toolkit.analysis.task.analysis;

import org.smojol.common.ast.DecoratedFlowNode;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.flowchart.ChartOverlay;

import java.util.Map;

public class SummaryInjectingChartOverlay implements ChartOverlay {
    private final ChartOverlay inner;
    private final Map<String, String> summaries;

    public SummaryInjectingChartOverlay(ChartOverlay inner, Map<String, String> summaries) {
        this.inner = inner;
        this.summaries = summaries;
    }

    @Override
    public FlowNode block(FlowNode node) {
        FlowNode blockedNode = inner.block(node);
        if (summaries.containsKey(blockedNode.id())) {
            return new DecoratedFlowNode(blockedNode, summaries.get(blockedNode.id()));
        }
        return blockedNode;
    }
}
