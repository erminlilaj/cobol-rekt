package org.smojol.toolkit.analysis.pipeline;

import com.google.common.collect.ImmutableList;
import org.antlr.v4.runtime.Token;
import org.smojol.common.structure.DataStructureContext;
import org.smojol.common.structure.SourceSection;
import org.smojol.common.vm.memory.MemoryAccess;
import org.smojol.common.vm.structure.CobolDataStructure;
import org.smojol.common.vm.structure.Format1DataStructure;

import java.util.ArrayList;
import java.util.List;

public class SerialisableCobolDataStructure {
    private String id;
    private final String name;
    private String content;
    private int levelNumber;
    private String rawText;
    private final List<SerialisableCobolDataStructure> children = new ArrayList<>();
    private boolean isRedefinition;
    private String redefines;
    private final String nodeType = "DATA_VERTEX";
    private String dataType;
    private List<DataStructureContext> categories;
    private SourceSection sourceSection;
    private String pictureClause;
    private String usage;
    private Integer occursCount;
    private String occursDependingOn;
    private Integer byteSize;
    private Integer byteOffset;
    private Integer sourceLine;
    private Integer sourceColumn;
    private String sourceName;

    public SerialisableCobolDataStructure(CobolDataStructure data) {
        name = data.name();
        dataType = data.getDataType().abstractType().name();
        content = data.content();
        id = data.getId();
        levelNumber = data.getLevelNumber();
        rawText = data.getRawText();
        categories = ImmutableList.of(data.dataCategory());
        sourceSection = data.getSourceSection();
        isRedefinition = data.getClass() == Format1DataStructure.class && data.isRedefinition();
        if (data instanceof Format1DataStructure format1) {
            redefines = isRedefinition ? format1.getDataDescription().dataRedefinesClause().getFirst().dataName().getText() : "";
            pictureClause = pictureClause(format1);
            usage = usage(format1);
            occursCount = occursCount(format1);
            occursDependingOn = occursDependingOn(format1);
            sourceLine = sourceLine(format1);
            sourceColumn = sourceColumn(format1);
            sourceName = sourceName(format1);
        } else {
            redefines = "";
        }
        byteSize = byteSize(data);
        byteOffset = byteOffset(data);
    }

    public SerialisableCobolDataStructure() {
        this.name = "ROOT";
    }

    public void add(SerialisableCobolDataStructure child) {
        children.add(child);
    }

    public SerialisableCobolDataStructure getChild(int i) {
        return children.get(i);
    }

    private static String pictureClause(Format1DataStructure data) {
        if (data.getDataDescription() == null || data.getDataDescription().dataPictureClause().isEmpty()) return null;
        return data.getDataDescription().dataPictureClause().getFirst().pictureString().getFirst().getText();
    }

    private static String usage(Format1DataStructure data) {
        if (data.getDataDescription() == null || data.getDataDescription().dataUsageClause().isEmpty()) return null;
        return data.getDataDescription().dataUsageClause().getFirst().usageFormat().getText();
    }

    private static Integer occursCount(Format1DataStructure data) {
        if (data.getDataDescription() == null || data.getDataDescription().dataOccursClause().isEmpty()) return null;
        var occursClause = data.getDataDescription().dataOccursClause().getFirst();
        if (occursClause.dataOccursTo() != null && occursClause.dataOccursTo().integerLiteral() != null) {
            return Integer.parseInt(occursClause.dataOccursTo().integerLiteral().getText());
        }
        if (occursClause.integerLiteral() != null) {
            return Integer.parseInt(occursClause.integerLiteral().getText());
        }
        return null;
    }

    private static String occursDependingOn(Format1DataStructure data) {
        if (data.getDataDescription() == null || data.getDataDescription().dataOccursClause().isEmpty()) return null;
        var occursClause = data.getDataDescription().dataOccursClause().getFirst();
        return occursClause.qualifiedDataName() == null ? null : occursClause.qualifiedDataName().getText();
    }

    private static Integer byteSize(CobolDataStructure data) {
        try {
            return data.size();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static Integer byteOffset(CobolDataStructure data) {
        try {
            if (data.layout() == null) return null;
            MemoryAccess access = data.layout().getAccess();
            return access == null ? null : access.fromIndex();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static Integer sourceLine(Format1DataStructure data) {
        Token start = sourceToken(data);
        return start == null ? null : start.getLine();
    }

    private static Integer sourceColumn(Format1DataStructure data) {
        Token start = sourceToken(data);
        return start == null ? null : start.getCharPositionInLine();
    }

    private static String sourceName(Format1DataStructure data) {
        Token start = sourceToken(data);
        if (start == null || start.getTokenSource() == null) return null;
        return start.getTokenSource().getSourceName();
    }

    private static Token sourceToken(Format1DataStructure data) {
        return data.getDataDescription() == null ? null : data.getDataDescription().getStart();
    }
}
