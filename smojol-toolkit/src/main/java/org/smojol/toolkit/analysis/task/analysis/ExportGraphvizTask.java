package org.smojol.toolkit.analysis.task.analysis;

import com.mojo.algorithms.domain.FlowNodeType;
import com.mojo.algorithms.task.AnalysisTask;
import com.mojo.algorithms.task.AnalysisTaskResult;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import com.mojo.algorithms.visualisation.FlowchartOutputFormat;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.navigation.FlowNodeNavigator;
import org.smojol.common.resource.ResourceOperations;
import org.smojol.toolkit.analysis.pipeline.config.OutputArtifactConfig;
import org.smojol.toolkit.ast.FlowchartBuilder;

import java.nio.file.Paths;
import java.util.List;

public class ExportGraphvizTask implements AnalysisTask {
    private final FlowNode flowRoot;
    private final OutputArtifactConfig graphvizOutputConfig;
    private final ResourceOperations resourceOperations;

    public ExportGraphvizTask(FlowNode flowRoot, OutputArtifactConfig graphvizOutputConfig,
            ResourceOperations resourceOperations) {
        this.flowRoot = flowRoot;
        this.graphvizOutputConfig = graphvizOutputConfig;
        this.resourceOperations = resourceOperations;
    }

    @Override
    public AnalysisTaskResult run() {
        List<FlowNode> sections = new FlowNodeNavigator(flowRoot)
                .findAllByCondition(fn -> fn.type() == FlowNodeType.SECTION);
        try {
            resourceOperations.createDirectories(graphvizOutputConfig.outputDir());
            // Always generate for the root (Program level)
            writeCodeBlock(flowRoot);

            // Also generate for sections if present
            for (FlowNode section : sections) {
                writeCodeBlock(section);
            }
            return AnalysisTaskResult.OK(CommandLineAnalysisTask.EXPORT_GRAPHVIZ);
        } catch (Exception e) {

            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.EXPORT_GRAPHVIZ);
        }
    }

    private void writeCodeBlock(FlowNode s) {
        String filename = s.type() == FlowNodeType.PROCEDURE_DIVISION_BODY ? s.id() : s.name();
        String dotFilePath = Paths.get(graphvizOutputConfig.outputDir().toString(), filename + ".dot").toString();
        // Dummy image output path as we are only interested in DOT generation here.
        // The image generation will be handled by the Python viewer or separate process
        // if needed.
        // However, FlowchartBuilder requires a valid path format.
        // We use SVG format to ensure FlowchartBuilder logic works (it assumes some
        // format).
        String imageFilePath = Paths.get(graphvizOutputConfig.outputDir().toString(), filename + ".svg").toString();

        try {
            // We use FlowchartBuilder to generate the DOT file.
            // Ideally we would suppress image generation if it's slow, but the current
            // implementation
            // of FlowchartBuilder seems to do both in build().
            // If we want ONLY dot, we might need to modify FlowchartBuilder or accept the
            // overhead/dependency.
            // Since the user asked for efficiency, and we have 'dot' on the system, let's
            // just let it run.
            // But wait, if we run it here, we generate SVGs in the 'graphviz' folder.
            // Then generate_viewer.py can just pick them up!
            // That's actually BETTER than having Python run 'dot'.
            // Java uses guru.nidi.graphviz which wraps 'dot'.
            // So if this works, we get .dot AND .svg files.
            // So if this works, we get .dot AND .svg files.
            new FlowchartBuilder(s).build(dotFilePath, imageFilePath, FlowchartOutputFormat.SVG);
        } catch (Exception e) {

            throw new RuntimeException("Error generating Graphviz for section " + filename, e);
        }
    }
}
