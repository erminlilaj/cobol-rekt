package org.smojol.toolkit.flowchart;

import org.antlr.v4.runtime.tree.ParseTree;
import org.smojol.toolkit.analysis.pipeline.config.SourceConfig;
import org.smojol.common.navigation.CobolEntityNavigator;
import org.smojol.toolkit.analysis.task.analysis.SummaryInjectingChartOverlay;
import org.smojol.toolkit.analysis.task.analysis.BuildFlowchartMarkupTask;
import org.smojol.toolkit.ast.BuildFlowNodesTask;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public class FlowchartOutputWriter {
    private final FlowchartGenerationStrategy flowchartGenerationStrategy;
    private final Path dotFileOutputDir;
    private final Path imageOutputDir;

    public FlowchartOutputWriter(FlowchartGenerationStrategy flowchartGenerationStrategy, Path dotFileOutputDir,
            Path imageOutputDir) {
        this.flowchartGenerationStrategy = flowchartGenerationStrategy;
        this.dotFileOutputDir = dotFileOutputDir;
        this.imageOutputDir = imageOutputDir;
    }

    public void draw(CobolEntityNavigator navigator, ParseTree root, SourceConfig sourceConfig,
            java.util.Map<String, String> methodSummaries) throws IOException, InterruptedException {
        org.smojol.common.flowchart.ChartOverlay overlay = methodSummaries != null ? new SummaryInjectingChartOverlay(
                BuildFlowchartMarkupTask.buildOverlay(new org.smojol.toolkit.ast.BuildFlowNodesTask(
                        new org.smojol.toolkit.ast.FlowNodeServiceImpl(navigator,
                                new org.smojol.common.vm.structure.Format1DataStructure(0,
                                        new org.smojol.common.vm.strategy.UnresolvedReferenceDoNothingStrategy()),
                                new com.mojo.algorithms.id.UUIDProvider()))
                        .run(root)),
                methodSummaries) : null;
        flowchartGenerationStrategy.draw(navigator, root, dotFileOutputDir, imageOutputDir, sourceConfig.programName(),
                overlay);
    }

    public void draw(CobolEntityNavigator navigator, ParseTree root, SourceConfig sourceConfig)
            throws IOException, InterruptedException {
        draw(navigator, root, sourceConfig, null);
    }

    public void createOutputDirs() throws IOException {
        Files.createDirectories(dotFileOutputDir);
        Files.createDirectories(imageOutputDir);
    }
}
