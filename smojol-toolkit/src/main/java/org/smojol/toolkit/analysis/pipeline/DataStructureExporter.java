package org.smojol.toolkit.analysis.pipeline;

import lombok.Getter;
import org.eclipse.lsp.cobol.common.mapping.ExtendedDocument;
import org.eclipse.lsp.cobol.core.semantics.CopybooksRepository;
import org.smojol.common.vm.structure.ScopedDataStructureVisitor;
import org.smojol.common.vm.structure.CobolDataStructure;

public class DataStructureExporter implements ScopedDataStructureVisitor {
    @Getter private final SerialisableCobolDataStructure root;
    private final ExtendedDocument extendedDocument;
    private final CopybooksRepository copybooksRepository;

    public DataStructureExporter(SerialisableCobolDataStructure root) {
        this(root, null, null);
    }

    public DataStructureExporter(SerialisableCobolDataStructure root, ExtendedDocument extendedDocument,
                                 CopybooksRepository copybooksRepository) {
        this.root = root;
        this.extendedDocument = extendedDocument;
        this.copybooksRepository = copybooksRepository;
    }

    @Override
    public ScopedDataStructureVisitor visit(CobolDataStructure data) {
        SerialisableCobolDataStructure child = new SerialisableCobolDataStructure(data, extendedDocument, copybooksRepository);
        this.root.add(child);
        return new DataStructureExporter(child, extendedDocument, copybooksRepository);
    }
}
