package org.smojol.common.structure;

import org.antlr.v4.runtime.tree.ParseTree;
import org.eclipse.lsp.cobol.core.CobolParser;
import com.mojo.algorithms.id.IdProvider;
import org.smojol.common.navigation.CobolEntityNavigator;
import org.smojol.common.vm.reference.DetachedDataStructure;
import org.smojol.common.vm.strategy.UnresolvedReferenceStrategy;
import org.smojol.common.vm.structure.*;
import com.mojo.algorithms.types.CobolDataType;
import com.mojo.algorithms.domain.TypedRecord;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;
import java.util.logging.Logger;

public class CobolDataStructureBuilder {
    private static final Logger LOGGER = Logger.getLogger(CobolDataStructureBuilder.class.getName());
    private final CobolEntityNavigator navigator;
    private final UnresolvedReferenceStrategy unresolvedReferenceStrategy;
    private CobolDataStructure zerothStructure;
    private final Format1DataStructureBuildStrategy format1DataStructureBuilder;
    private final IdProvider idProvider;
    private final List<SkippedVariable> skippedVariables = new ArrayList<>();

    public CobolDataStructureBuilder(CobolEntityNavigator navigator, UnresolvedReferenceStrategy unresolvedReferenceStrategy, Format1DataStructureBuildStrategy format1DataStructureBuilder, IdProvider idProvider) {
        this.navigator = navigator;
        this.unresolvedReferenceStrategy = unresolvedReferenceStrategy;
        this.format1DataStructureBuilder = format1DataStructureBuilder;
        this.idProvider = idProvider;
    }

    public List<SkippedVariable> getSkippedVariables() {
        return List.copyOf(skippedVariables);
    }

    public CobolDataStructure build() {
        zerothStructure = new Format1DataStructure(0, unresolvedReferenceStrategy);
        ParseTree dataDivision = navigator.dataDivisionBody(navigator.getRoot());
        CobolParser.DataDivisionContext dataDivisionBody = (CobolParser.DataDivisionContext) dataDivision;
        extractFromWorkingStorage(dataDivisionBody);
        extractFromLinkage(dataDivisionBody);
        extractFromFileSection(dataDivisionBody);
        try {
            zerothStructure.expandTables();
        } catch (RuntimeException e) {
            LOGGER.warning("Table expansion failed: " + e.getMessage());
            skippedVariables.add(new SkippedVariable("TABLE_EXPANSION", e.getMessage(), "ALL"));
        }
        try {
            zerothStructure.calculateMemoryRequirements();
        } catch (RuntimeException e) {
            LOGGER.warning("Memory calculation failed: " + e.getMessage());
            skippedVariables.add(new SkippedVariable("MEMORY_CALCULATION", e.getMessage(), "ALL"));
        }
        zerothStructure.allocateRecordPointers();
        int i = 0;
        while (zerothStructure.buildRedefinitions(zerothStructure)) {
            LOGGER.info("Building redefinitions...");
        }
        addGlobalSystemStructures();
        addUnreferencedStructures();
        if (!skippedVariables.isEmpty()) {
            LOGGER.warning("Data structure building completed with " + skippedVariables.size()
                + " skipped variable(s). See parse_diagnostics.json for details.");
        }
        return zerothStructure;
    }

    private void addGlobalSystemStructures() {
        zerothStructure.addChild(new StaticDataStructure("WHEN-COMPILED", 1, CobolDataType.STRING, TypedRecord.typedString("01-01-2024")));
    }

    private void addUnreferencedStructures() {
        List<ParseTree> unreferencedVariables = new UnreferencedVariableSearch().run(navigator, zerothStructure);
        List<? extends CobolDataStructure> unreferencedStructures = unreferencedVariables.stream().map(uv -> new DetachedDataStructure(uv.getText(), TypedRecord.typedNumber(1))).toList();
        zerothStructure.addChildren(unreferencedStructures);

    }

    private void extractFromFileSection(CobolParser.DataDivisionContext dataDivisionBody) {
        Optional<CobolParser.DataDivisionSectionContext> maybeFileSection = dataDivisionBody.dataDivisionSection().stream().filter(s -> s.fileSection() != null).findFirst();
        if (maybeFileSection.isEmpty()) return;
        CobolParser.FileSectionContext fileSection = maybeFileSection.get().fileSection();
        List<CobolParser.DataDescriptionEntryContext> allDataDescriptions = fileSection.fileDescriptionEntry().stream().flatMap(fd -> fd.dataDescriptionEntry().stream()).toList();
        extractFrom(allDataDescriptions, zerothStructure, this::fileDescriptorData, SourceSection.FILE_DESCRIPTOR);
    }

    private void extractFromLinkage(CobolParser.DataDivisionContext dataDivisionBody) {
        Optional<CobolParser.DataDivisionSectionContext> maybeLinkageSection = dataDivisionBody.dataDivisionSection().stream().filter(s -> s.linkageSection() != null).findFirst();
        if (maybeLinkageSection.isEmpty()) return;
        CobolParser.LinkageSectionContext linkageSection = maybeLinkageSection.get().linkageSection();
        List<CobolParser.DataDescriptionEntryForWorkingStorageAndLinkageSectionContext> linkageSectionDataLayouts = linkageSection.dataDescriptionEntryForWorkingStorageAndLinkageSection();
        extractFrom(linkageSectionDataLayouts, zerothStructure, this::linkageData, SourceSection.LINKAGE);
    }

    private void extractFromWorkingStorage(CobolParser.DataDivisionContext dataDivisionBody) {
        Optional<CobolParser.DataDivisionSectionContext> maybeWorkingStorage = dataDivisionBody.dataDivisionSection().stream().filter(s -> s.workingStorageSection() != null).findFirst();
        if (maybeWorkingStorage.isEmpty()) return;
        CobolParser.WorkingStorageSectionContext workingStorageSection = maybeWorkingStorage.get().workingStorageSection();
        List<CobolParser.DataDescriptionEntryForWorkingStorageSectionContext> workingStorageDataLayouts = workingStorageSection.dataDescriptionEntryForWorkingStorageSection();
        extractFrom(workingStorageDataLayouts, zerothStructure, this::wsData, SourceSection.WORKING_STORAGE);
    }

    private CobolParser.DataDescriptionEntryContext wsData(CobolParser.DataDescriptionEntryForWorkingStorageSectionContext e) {
        return e.dataDescriptionEntryForWorkingStorageAndLinkageSection().dataDescriptionEntry();
    }

    private CobolParser.DataDescriptionEntryContext linkageData(CobolParser.DataDescriptionEntryForWorkingStorageAndLinkageSectionContext e) {
        return e.dataDescriptionEntry();
    }

    private CobolParser.DataDescriptionEntryContext fileDescriptorData(CobolParser.DataDescriptionEntryContext e) {
        return e;
    }

    // TODO: Refactor to state machine maybe
    // TODO: Refactor to use builder in addChild(), addPeer() to inject parent directly into constructor
    private <T> void extractFrom(List<T> dataLayouts, CobolDataStructure root, Function<T, CobolParser.DataDescriptionEntryContext> retriever, SourceSection sourceSection) {
        int currentLevel = 0;
        CobolDataStructure dataStructure = root;
        // TODO: Does not check if you are adding a structure under a level 77 structure, which is invalid
        for (T dataDescriptionEntry : dataLayouts) {
            try {
                CobolParser.DataDescriptionEntryContext dataDescription = retriever.apply(dataDescriptionEntry);
                if (dataDescription.dataDescriptionEntryFormat1() != null) {
                    CobolParser.DataDescriptionEntryFormat1Context format1 = dataDescription.dataDescriptionEntryFormat1();
                    int entryLevel = Integer.parseInt(format1.levelNumber().LEVEL_NUMBER().getSymbol().getText());
                    if (currentLevel == 0) {
                        if (entryLevel != 1) {
                            LOGGER.warning("Top level variable is not level 01");
                            // TODO: Should we be strict or lax regarding top level variables not being level 01???
//                        throw new RuntimeException("Top Level entry must be 01");
                        }
                        dataStructure = dataStructure.addChild(format1(format1, unresolvedReferenceStrategy, sourceSection));
                    } else if (entryLevel == currentLevel) {
                        dataStructure = dataStructure.addPeer(format1(format1, unresolvedReferenceStrategy, sourceSection));
                    } else if (entryLevel > currentLevel) {
                        dataStructure = dataStructure.addChild(format1(format1, unresolvedReferenceStrategy, sourceSection));
                    } else if (entryLevel == 77) {
                        dataStructure = root.addChild(format1(format1, unresolvedReferenceStrategy, sourceSection));
                        currentLevel = 0;
                        continue;
                    } else if (entryLevel == 66) {
                        // Level 66 RENAME — preserve variable name as detached node
                        String renameName = format1.entryName() != null
                            ? format1.entryName().getText() : "UNNAMED_RENAME";
                        LOGGER.info("Recording Level 66 RENAME alias: " + renameName);
                        root.addChild(new DetachedDataStructure(renameName, TypedRecord.typedString("RENAME_ALIAS")));
                        continue;
                    } else {
                        // This is for adding a structure at a lower level than the current level's parent.
                        dataStructure = dataStructure.parent(entryLevel).addChild(format1(format1, unresolvedReferenceStrategy, sourceSection));
                    }
                } else if (dataDescription.dataDescriptionEntryFormat3() != null) {
                    CobolParser.DataDescriptionEntryFormat3Context conditionalFormat = dataDescription.dataDescriptionEntryFormat3();
                    dataStructure = dataStructure.addConditionalVariable(new ConditionalDataStructure(conditionalFormat, dataStructure, sourceSection));
                }
                currentLevel = dataStructure.level();
            } catch (RuntimeException e) {
                String varName = extractVariableName(dataDescriptionEntry, retriever);
                LOGGER.warning("Skipping variable '" + varName + "' in " + sourceSection.name()
                    + " due to: " + e.getMessage());
                skippedVariables.add(new SkippedVariable(varName, e.getMessage(), sourceSection.name()));
                // Do not update currentLevel or dataStructure — next variable
                // will be processed relative to the last successful position
            }
        }
    }

    private <T> String extractVariableName(T dataDescriptionEntry, Function<T, CobolParser.DataDescriptionEntryContext> retriever) {
        try {
            CobolParser.DataDescriptionEntryContext desc = retriever.apply(dataDescriptionEntry);
            if (desc.dataDescriptionEntryFormat1() != null) {
                CobolParser.DataDescriptionEntryFormat1Context format1 = desc.dataDescriptionEntryFormat1();
                return format1.entryName() != null ? format1.entryName().getText() : "UNNAMED";
            }
            if (desc.dataDescriptionEntryFormat3() != null) {
                CobolParser.DataDescriptionEntryFormat3Context format3 = desc.dataDescriptionEntryFormat3();
                return format3.entryName() != null
                    ? format3.entryName().getText() : "UNNAMED_88";
            }
            return "UNKNOWN_FORMAT";
        } catch (Exception ignored) {
            return "UNKNOWN";
        }
    }

    private CobolDataStructure format1(CobolParser.DataDescriptionEntryFormat1Context format1Context, UnresolvedReferenceStrategy unresolvedReferenceStrategy, SourceSection sourceSection) {
        return format1DataStructureBuilder.build(format1Context, unresolvedReferenceStrategy, sourceSection);
    }


}
