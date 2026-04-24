package org.smojol.toolkit.analysis.task.analysis;

import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.ast.BuildSerialisableASTTask;
import org.smojol.common.ast.CobolContextAugmentedTreeNode;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.ast.FlowNodeService;
import com.mojo.algorithms.id.IdProvider;
import org.smojol.common.navigation.CobolEntityNavigator;
import org.smojol.common.pseudocode.SmojolSymbolTable;
import org.smojol.common.pseudocode.SymbolReferenceBuilder;
import org.smojol.common.vm.structure.CobolDataStructure;
import org.smojol.toolkit.analysis.pipeline.BaseAnalysisModel;
import org.smojol.toolkit.analysis.pipeline.ParsePipeline;
import org.smojol.toolkit.ast.BuildFlowNodesTask;
import org.smojol.toolkit.ast.FlowNodeServiceImpl;
import com.mojo.algorithms.task.AnalysisTask;
import com.mojo.algorithms.task.AnalysisTaskResult;
import com.mojo.algorithms.task.CommandLineAnalysisTask;

import java.io.IOException;
import java.util.logging.Logger;

public class BuildBaseModelTask implements AnalysisTask {
    private static final Logger LOGGER = Logger.getLogger(BuildBaseModelTask.class.getName());
    private final ParsePipeline pipeline;
    private final IdProvider idProvider;

    public BuildBaseModelTask(ParsePipeline pipeline, IdProvider idProvider) {
        this.pipeline = pipeline;
        this.idProvider = idProvider;
    }

    @Override
    public AnalysisTaskResult run() {
        try {
            CobolEntityNavigator navigator = pipeline.parse();
            CobolParser.ProcedureDivisionBodyContext rawAST = navigator.procedureDivisionBody(navigator.getRoot());
            CobolContextAugmentedTreeNode serialisableAST = new BuildSerialisableASTTask().run(rawAST, navigator);
            CobolDataStructure dataStructures = pipeline.getDataStructures();
//            FlowchartBuilder flowcharter = pipeline.flowcharter();
            SmojolSymbolTable symbolTable = new SmojolSymbolTable(dataStructures, new SymbolReferenceBuilder(idProvider));
            FlowNodeService nodeService = new FlowNodeServiceImpl(navigator, dataStructures, idProvider);
            FlowNode flowRoot = new BuildFlowNodesTask(nodeService).run(rawAST);
//            flowcharter.buildFlowAST(rawAST).buildControlFlow().buildOverlay();
//            FlowNode flowRoot = flowcharter.getRoot();
            try {
                flowRoot.resolve(symbolTable, dataStructures);
            } catch (RuntimeException e) {
                if (!pipeline.isLenient()) throw e;
                LOGGER.warning("LENIENT MODE: Expression resolution failed on partial parse tree: "
                    + e.getMessage() + ". Continuing with unresolved expressions.");
            }
            return AnalysisTaskResult.OK(CommandLineAnalysisTask.BUILD_BASE_ANALYSIS, new BaseAnalysisModel(navigator, rawAST, dataStructures,
                    symbolTable, flowRoot, serialisableAST));
        } catch (IOException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.BUILD_BASE_ANALYSIS);
        }
    }
}
