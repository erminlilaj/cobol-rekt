package org.smojol.toolkit.analysis.task.analysis;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.stream.JsonWriter;
import org.smojol.common.ast.FlowNode;
import com.mojo.algorithms.id.IdProvider;
import org.smojol.common.resource.ResourceOperations;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import org.smojol.toolkit.analysis.staticvalue.DataflowAnalysisResult;
import org.smojol.toolkit.analysis.staticvalue.StaticValueDataflowPass;
import org.smojol.toolkit.analysis.pipeline.SerialisableCFGGraphCollector;
import com.mojo.algorithms.task.AnalysisTask;
import com.mojo.algorithms.task.AnalysisTaskResult;
import org.smojol.toolkit.analysis.pipeline.config.CFGOutputConfig;

import java.io.IOException;
import java.nio.file.Path;

public class WriteControlFlowGraphTask implements AnalysisTask {
    private final FlowNode astRoot;
    private final IdProvider idProvider;
    private final CFGOutputConfig cfgOutputConfig;
    private final ResourceOperations resourceOperations;

    public WriteControlFlowGraphTask(FlowNode astRoot, IdProvider idProvider, CFGOutputConfig cfgOutputConfig, ResourceOperations resourceOperations) {
        this.astRoot = astRoot;
        this.idProvider = idProvider;
        this.cfgOutputConfig = cfgOutputConfig;
        this.resourceOperations = resourceOperations;
    }

    @Override
    public AnalysisTaskResult run() {
        SerialisableCFGGraphCollector cfgGraphCollector = new SerialisableCFGGraphCollector(idProvider);
        astRoot.accept(cfgGraphCollector, -1);
        cfgGraphCollector.annotateReachability();
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        try {
//            Files.createDirectories(cfgOutputConfig.outputDir());
            resourceOperations.createDirectories(cfgOutputConfig.outputDir());
        } catch (IOException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.WRITE_CFG);
        }
//        try (JsonWriter writer = new JsonWriter(new FileWriter(cfgOutputConfig.outputPath()))) {
        try (JsonWriter writer = new JsonWriter(resourceOperations.fileWriter(cfgOutputConfig.outputPath()))) {
            writer.setIndent("  ");  // Optional: for pretty printing
            gson.toJson(cfgGraphCollector, SerialisableCFGGraphCollector.class, writer);
            writeDataflowSkeleton(gson, cfgGraphCollector);
            return AnalysisTaskResult.OK(CommandLineAnalysisTask.WRITE_CFG);
        } catch (IOException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.WRITE_CFG);
        }
    }

    private void writeDataflowSkeleton(Gson gson, SerialisableCFGGraphCollector cfgGraphCollector) throws IOException {
        Path staticAnalysisDir = cfgOutputConfig.outputDir().getParent().resolve("static_analysis");
        resourceOperations.createDirectories(staticAnalysisDir);
        DataflowAnalysisResult result = new StaticValueDataflowPass()
                .buildSkeleton(programName(), cfgGraphCollector.nodes(), cfgGraphCollector.edges());
        try (JsonWriter writer = new JsonWriter(resourceOperations.fileWriter(
                staticAnalysisDir.resolve("dataflow.json").toAbsolutePath().normalize().toString()))) {
            writer.setIndent("  ");
            gson.toJson(result, DataflowAnalysisResult.class, writer);
        }
    }

    private String programName() {
        String filename = Path.of(cfgOutputConfig.outputPath()).getFileName().toString();
        if (filename.startsWith("cfg-") && filename.endsWith(".json")) {
            return filename.substring(4, filename.length() - 5);
        }
        return filename;
    }
}
