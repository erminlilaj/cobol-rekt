package org.smojol.common.ast;

public record SerialisableEdge(
        String id,
        String fromNodeID,
        String toNodeID,
        String edgeType,
        String fromLabel,
        String toLabel,
        String evidence,
        String condition,
        Integer sourceLine,
        Integer sourceColumn,
        String lineOrigin) {
    public SerialisableEdge(String id, String fromNodeID, String toNodeID, String edgeType) {
        this(id, fromNodeID, toNodeID, edgeType, null, null, null, null, null, null, null);
    }
}
