package org.smojol.toolkit.analysis.task.analysis;

import org.antlr.v4.runtime.tree.ParseTree;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.navigation.CobolEntityNavigator;
import org.smojol.common.resource.ResourceOperations;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import com.mojo.algorithms.task.AnalysisTask;
import com.mojo.algorithms.task.AnalysisTaskResult;
import org.smojol.toolkit.analysis.pipeline.config.SourceConfig;
import org.smojol.toolkit.flowchart.FlowchartOutputWriter;

import java.io.IOException;

public class DrawFlowchartTask implements AnalysisTask {
    private final SourceConfig sourceConfig;
    private final FlowchartOutputWriter flowchartOutputWriter;
    private final CobolEntityNavigator navigator;

    public DrawFlowchartTask(CobolEntityNavigator navigator, FlowchartOutputWriter flowchartOutputWriter,
            SourceConfig sourceConfig, ResourceOperations resourceOperations, FlowNode flowRoot) {
        this.sourceConfig = sourceConfig;
        this.flowchartOutputWriter = flowchartOutputWriter;
        this.navigator = navigator;
    }

    @Override
    public AnalysisTaskResult run() {
        ParseTree root = navigator.procedureDivisionBody(navigator.getRoot());
        try {
            java.nio.file.Path summaryPath = java.nio.file.Paths.get(sourceConfig.sourceDir())
                    .resolve("llm_summary.json");
            java.util.Map<String, String> methodSummaries = null;
            if (java.nio.file.Files.exists(summaryPath)) {
                com.google.gson.Gson gson = new com.google.gson.Gson();
                java.lang.reflect.Type collectionType = new com.google.gson.reflect.TypeToken<java.util.Map<String, org.smojol.toolkit.analysis.task.analysis.SummaryTree>>() {
                }.getType();
                java.util.Map<String, org.smojol.toolkit.analysis.task.analysis.SummaryTree> fullSummary = gson
                        .fromJson(java.nio.file.Files.newBufferedReader(summaryPath), collectionType);
                if (fullSummary != null && fullSummary.containsKey("codeSummary")) {
                    methodSummaries = flatten(fullSummary.get("codeSummary"));
                }
            }

            flowchartOutputWriter.createOutputDirs();
            flowchartOutputWriter.draw(navigator, root, sourceConfig, methodSummaries);
            return AnalysisTaskResult.OK(CommandLineAnalysisTask.DRAW_FLOWCHART);
        } catch (IOException | InterruptedException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.DRAW_FLOWCHART);
        }
    }

    private java.util.Map<String, String> flatten(org.smojol.toolkit.analysis.task.analysis.SummaryTree summaryTree) {
        java.util.Map<String, String> map = new java.util.HashMap<>();
        flattenRecursive(summaryTree, map);
        return map;
    }

    private void flattenRecursive(org.smojol.toolkit.analysis.task.analysis.SummaryTree tree,
            java.util.Map<String, String> map) {
        map.put(tree.id(), tree.summary());
        for (org.smojol.toolkit.analysis.task.analysis.SummaryTree child : tree.children()) {
            flattenRecursive(child, map);
        }
    }
}
