package org.smojol.toolkit.analysis.task.analysis;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.stream.JsonWriter;
import org.smojol.common.resource.ResourceOperations;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import org.eclipse.lsp.cobol.common.mapping.ExtendedDocument;
import org.eclipse.lsp.cobol.core.semantics.CopybooksRepository;
import org.smojol.toolkit.analysis.pipeline.DataStructureExporter;
import org.smojol.toolkit.analysis.pipeline.SerialisableCobolDataStructure;
import com.mojo.algorithms.task.AnalysisTask;
import com.mojo.algorithms.task.AnalysisTaskResult;
import org.smojol.common.vm.structure.CobolDataStructure;
import org.smojol.toolkit.analysis.pipeline.config.OutputArtifactConfig;

import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;

public class WriteDataStructuresTask implements AnalysisTask {
    private final CobolDataStructure dataStructures;
    private final OutputArtifactConfig outputArtifactConfig;
    private final ExtendedDocument extendedDocument;
    private final CopybooksRepository copybooksRepository;

    public WriteDataStructuresTask(CobolDataStructure dataStructures, OutputArtifactConfig outputArtifactConfig,
                                   ResourceOperations resourceOperations, ExtendedDocument extendedDocument,
                                   CopybooksRepository copybooksRepository) {
        this.dataStructures = dataStructures;
        this.outputArtifactConfig = outputArtifactConfig;
        this.extendedDocument = extendedDocument;
        this.copybooksRepository = copybooksRepository;
    }

    @Override
    public AnalysisTaskResult run() {
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        SerialisableCobolDataStructure root = new SerialisableCobolDataStructure();
        DataStructureExporter visitor = new DataStructureExporter(root, extendedDocument, copybooksRepository);
        dataStructures.acceptScopedVisitor(visitor);
        SerialisableCobolDataStructure realRoot = root.getChild(0);
        try {
            Files.createDirectories(outputArtifactConfig.outputDir());
        } catch (IOException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.WRITE_DATA_STRUCTURES);
        }
        try (JsonWriter writer = new JsonWriter(new FileWriter(outputArtifactConfig.fullPath()))) {
            writer.setIndent("  ");
            gson.toJson(realRoot, SerialisableCobolDataStructure.class, writer);
        } catch (IOException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.WRITE_DATA_STRUCTURES);
        }
        return AnalysisTaskResult.OK(CommandLineAnalysisTask.WRITE_DATA_STRUCTURES, realRoot);
    }
}
