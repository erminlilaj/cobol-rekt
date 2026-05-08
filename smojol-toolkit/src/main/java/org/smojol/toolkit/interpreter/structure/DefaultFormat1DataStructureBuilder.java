package org.smojol.toolkit.interpreter.structure;

import org.eclipse.lsp.cobol.core.CobolParser;
import org.smojol.common.structure.SourceSection;
import org.smojol.common.vm.strategy.UnresolvedReferenceStrategy;
import org.smojol.common.vm.structure.*;

import java.util.logging.Logger;

public class DefaultFormat1DataStructureBuilder implements Format1DataStructureBuildStrategy {
    private static final Logger LOGGER = Logger.getLogger(DefaultFormat1DataStructureBuilder.class.getName());

    @Override
    public Format1DataStructure build(CobolParser.DataDescriptionEntryFormat1Context format1Structure, UnresolvedReferenceStrategy strategy, SourceSection sourceSection) {
        if (format1Structure.dataOccursClause() == null || format1Structure.dataOccursClause().isEmpty()) {
            return new Format1DataStructure(format1Structure, strategy, sourceSection);
        }
        CobolParser.DataOccursClauseContext occursClause = format1Structure.dataOccursClause().getFirst();
        int numOccurrences;
        if (occursClause.integerLiteral() != null) {
            numOccurrences = Integer.parseInt(occursClause.integerLiteral().getText());
            // OCCURS x TO y DEPENDING ON z — use max (y) for static allocation
            if (occursClause.dataOccursTo() != null && occursClause.dataOccursTo().integerLiteral() != null) {
                numOccurrences = Integer.parseInt(occursClause.dataOccursTo().integerLiteral().getText());
                LOGGER.info("OCCURS DEPENDING ON — using max count " + numOccurrences);
            }
        } else {
            // UNBOUNDED — use 1 as minimum estimate
            numOccurrences = 1;
            LOGGER.warning("OCCURS UNBOUNDED — using count=1 as minimum estimate");
        }
        return new TableDataStructure(format1Structure, numOccurrences, strategy, sourceSection);
    }
}
