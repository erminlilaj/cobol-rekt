package org.smojol.toolkit.analysis.pipeline;

import org.antlr.v4.runtime.tree.ParseTree;
import org.eclipse.lsp.cobol.common.mapping.ExtendedDocument;
import org.eclipse.lsp.cobol.core.semantics.CopybooksRepository;
import org.smojol.common.ast.CobolContextAugmentedTreeNode;
import org.smojol.common.ast.FlowNode;
import org.smojol.common.navigation.CobolEntityNavigator;
import org.smojol.common.pseudocode.SmojolSymbolTable;
import org.smojol.common.vm.structure.CobolDataStructure;

public record BaseAnalysisModel(CobolEntityNavigator navigator,
                                ParseTree rawAST,
                                CobolDataStructure dataStructures,
                                SmojolSymbolTable symbolTable,
                                FlowNode flowRoot,
                                CobolContextAugmentedTreeNode serialisableAST,
                                ExtendedDocument extendedDocument,
                                CopybooksRepository copybooksRepository) {
    public ParseTree rawAST() {
        return rawAST;
    }

    public CobolDataStructure dataStructures() {
        return dataStructures;
    }

    public SmojolSymbolTable symbolTable() {
        return symbolTable;
    }

    public FlowNode flowRoot() {
        return flowRoot;
    }
}
