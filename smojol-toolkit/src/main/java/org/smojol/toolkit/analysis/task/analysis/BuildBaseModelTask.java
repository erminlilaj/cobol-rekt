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
import org.smojol.toolkit.analysis.error.BaseModelValidationException;
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
            if (navigator == null || navigator.getRoot() == null) {
                throw new BaseModelValidationException("MISSING_PARSE_TREE",
                        "Parser did not produce a navigable COBOL parse tree");
            }
            CobolParser.IdentificationDivisionContext identDiv = navigator.findByCondition(
                    navigator.getRoot(), CobolParser.IdentificationDivisionContext.class);
            if (identDiv == null || identDiv.exception != null) {
                throw new BaseModelValidationException("MISSING_IDENTIFICATION_DIVISION",
                        "COBOL program is missing IDENTIFICATION DIVISION (or ID DIVISION) header");
            }
            CobolParser.ProcedureDivisionBodyContext rawAST = navigator.procedureDivisionBody(navigator.getRoot());
            if (rawAST == null) {
                throw new BaseModelValidationException("MISSING_PROCEDURE_DIVISION_BODY",
                        "COBOL parse tree does not contain a PROCEDURE DIVISION body");
            }
            CobolContextAugmentedTreeNode serialisableAST = new BuildSerialisableASTTask().run(rawAST, navigator);
            CobolDataStructure dataStructures = pipeline.getDataStructures();
            if (dataStructures == null) {
                throw new BaseModelValidationException("MISSING_DATA_STRUCTURES",
                        "Base analysis did not produce a data-structure root");
            }
//            FlowchartBuilder flowcharter = pipeline.flowcharter();
            SmojolSymbolTable symbolTable = new SmojolSymbolTable(dataStructures, new SymbolReferenceBuilder(idProvider));
            FlowNodeService nodeService = new FlowNodeServiceImpl(navigator, dataStructures, idProvider);
            FlowNode flowRoot = new BuildFlowNodesTask(nodeService).run(rawAST);
            if (flowRoot == null) {
                throw new BaseModelValidationException("MISSING_FLOW_ROOT",
                        "Base analysis did not produce a flow-tree root");
            }
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
        } catch (BaseModelValidationException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.BUILD_BASE_ANALYSIS);
        } catch (IOException e) {
            return AnalysisTaskResult.ERROR(e, CommandLineAnalysisTask.BUILD_BASE_ANALYSIS);
        } catch (NullPointerException e) {
            BaseModelValidationException diagnostic = new BaseModelValidationException("BASE_MODEL_NULL_STRUCTURE",
                    "Base analysis encountered missing structural data: " + e.getMessage(), e);
            return AnalysisTaskResult.ERROR(diagnostic, CommandLineAnalysisTask.BUILD_BASE_ANALYSIS);
        }
    }
}
