package org.smojol.toolkit.analysis.staticvalue;

import com.mojo.algorithms.domain.FlowNodeType;
import org.antlr.v4.runtime.Token;
import org.smojol.common.ast.SerialisableCFGFlowNode;
import org.smojol.common.ast.SerialisableEdge;
import org.smojol.common.vm.structure.CobolDataStructure;
import org.smojol.common.vm.structure.Format1DataStructure;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

public class StaticValueDataflowPass {
    private static final String SCHEMA_VERSION = "1.0";
    private static final String ANALYSIS_VERSION = "0.4";
    private static final String SUMMARY_SOURCE = "java_static_value_dataflow";

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges) {
        return buildSkeleton(program, nodes, edges, null);
    }

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges,
                                                CobolDataStructure dataStructures) {
        Map<String, ParagraphSummary> paragraphSummaries = paragraphSummaries(nodes);
        Map<String, AliasSetSummary> aliasSets = aliasSets(dataStructures);
        Map<String, DataflowNodeState> nodeStates = nodeStates(nodes, aliasSets);
        int killCount = nodeStates.values().stream().mapToInt(state -> state.kills().size()).sum();

        return new DataflowAnalysisResult(
                program,
                SCHEMA_VERSION,
                "static_value_dataflow",
                ANALYSIS_VERSION,
                "alias_kill_skeleton",
                config(),
                summary(nodes.size(), edges.size(), paragraphSummaries.size(), aliasSets.size(), killCount),
                nodeStates,
                aliasSets,
                paragraphSummaries,
                List.of()
        );
    }

    private Map<String, Object> config() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("constant_propagation_enabled", false);
        config.put("path_sensitive_targets_enabled", false);
        config.put("paragraph_summaries_enabled", true);
        config.put("alias_analysis_enabled", true);
        config.put("alias_kills_enabled", true);
        config.put("mode", "alias_kill_skeleton");
        return config;
    }

    private Map<String, Object> summary(int nodeCount, int edgeCount, int paragraphSummaryCount, int aliasSetCount,
                                        int killCount) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("node_count", nodeCount);
        summary.put("edge_count", edgeCount);
        summary.put("entry_constant_count", 0);
        summary.put("exit_constant_count", 0);
        summary.put("kill_count", killCount);
        summary.put("diagnostic_count", 0);
        summary.put("alias_set_count", aliasSetCount);
        summary.put("paragraph_summary_count", paragraphSummaryCount);
        return summary;
    }

    private Map<String, DataflowNodeState> nodeStates(List<SerialisableCFGFlowNode> nodes,
                                                      Map<String, AliasSetSummary> aliasSets) {
        Map<String, DataflowNodeState> nodeStates = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeStates.put(node.getId(), new DataflowNodeState(
                    new LinkedHashMap<>(), new LinkedHashMap<>(), aliasKills(node, aliasSets), List.of()));
        }
        return nodeStates;
    }

    private List<Map<String, Object>> aliasKills(SerialisableCFGFlowNode node,
                                                 Map<String, AliasSetSummary> aliasSets) {
        if (!canEmitAliasKills(node) || node.getVariablesModified() == null
                || node.getVariablesModified().isEmpty() || aliasSets.isEmpty()) {
            return List.of();
        }

        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (String writtenVariable : sortedStrings(node.getVariablesModified())) {
            String canonicalWritten = canonicalVariable(writtenVariable);
            for (AliasSetSummary aliasSet : aliasSets.values()) {
                if (!aliasSet.members().contains(canonicalWritten)) continue;
                for (String killedVariable : aliasSet.members()) {
                    Map<String, Object> kill = aliasKill(node, canonicalWritten, killedVariable, aliasSet);
                    kills.put(killKey(kill), kill);
                }
            }
        }
        return new ArrayList<>(kills.values());
    }

    private boolean canEmitAliasKills(SerialisableCFGFlowNode node) {
        return switch (node.getType()) {
            case ACCEPT, ADD, COMPUTE, DIVIDE, INITIALIZE, INSPECT, MOVE, MULTIPLY, READ, REWRITE, RETURN,
                 SET, STRING, SUBTRACT, UNSTRING, WRITE -> true;
            default -> false;
        };
    }

    private String killKey(Map<String, Object> kill) {
        return kill.get("variable") + "\u0000" + kill.get("alias_set_id") + "\u0000" + kill.get("written_variable");
    }

    private Map<String, Object> aliasKill(SerialisableCFGFlowNode node, String writtenVariable, String killedVariable,
                                          AliasSetSummary aliasSet) {
        Map<String, Object> kill = new LinkedHashMap<>();
        kill.put("code", "ALIAS_CONSERVATIVE_KILL");
        kill.put("variable", killedVariable);
        kill.put("written_variable", writtenVariable);
        kill.put("reason", aliasSet.aliasKind().toLowerCase(Locale.ROOT));
        kill.put("alias_set_id", aliasSet.aliasSetId());
        kill.put("alias_kind", aliasSet.aliasKind());
        kill.put("kill_scope", aliasSet.killScope());
        kill.put("confidence", "conservative");
        kill.put("statement_type", node.getType().name());
        putIfPresent(kill, "statement_text", node.getOriginalText());
        putIfPresent(kill, "source_line", node.getSourceLine());
        putIfPresent(kill, "source_column", node.getSourceColumn());
        kill.put("provenance_source", SUMMARY_SOURCE);
        return kill;
    }

    private String canonicalVariable(String variable) {
        if (variable == null) return "";
        String canonical = variable.trim().toUpperCase(Locale.ROOT);
        int subscriptStart = canonical.indexOf('(');
        return subscriptStart < 0 ? canonical : canonical.substring(0, subscriptStart);
    }

    private Map<String, AliasSetSummary> aliasSets(CobolDataStructure dataStructures) {
        List<DataItem> items = flattenedDataItems(dataStructures);
        Map<String, DataItem> byName = firstByName(items);
        Map<String, AliasSetSummary> candidates = new TreeMap<>();
        addGroupChildAliasSets(items, candidates);
        addOccursAliasSets(items, candidates);
        addRedefinesAliasSets(items, byName, candidates);
        return new LinkedHashMap<>(candidates);
    }

    private List<DataItem> flattenedDataItems(CobolDataStructure root) {
        if (root == null) return List.of();
        List<DataItem> items = new ArrayList<>();
        Set<CobolDataStructure> visited = Collections.newSetFromMap(new IdentityHashMap<>());
        flatten(root, null, items, visited);
        return items.stream()
                .filter(item -> item.name() != null)
                .filter(item -> !item.name().isBlank())
                .filter(item -> !"[ROOT]".equals(item.name()) && !"ROOT".equals(item.name()))
                .sorted(Comparator.comparing(DataItem::name))
                .toList();
    }

    private void flatten(CobolDataStructure current, String parent, List<DataItem> items,
                         Set<CobolDataStructure> visited) {
        if (current == null || !visited.add(current)) return;
        DataItem item = dataItem(current, parent);
        items.add(item);
        for (CobolDataStructure child : current.subStructures()) {
            flatten(child, current.name(), items, visited);
        }
    }

    private DataItem dataItem(CobolDataStructure data, String parent) {
        return new DataItem(
                data.name(),
                parent,
                data.getLevelNumber(),
                data.isRedefinition(),
                redefines(data),
                dataType(data),
                occursCount(data),
                occursDependingOn(data),
                null,
                null,
                sourceLine(data)
        );
    }

    private Map<String, DataItem> firstByName(List<DataItem> items) {
        Map<String, DataItem> byName = new TreeMap<>();
        for (DataItem item : items) byName.putIfAbsent(item.name(), item);
        return byName;
    }

    private void addGroupChildAliasSets(List<DataItem> items, Map<String, AliasSetSummary> candidates) {
        for (DataItem item : items) {
            List<DataItem> members = descendantsAndSelf(item, items);
            if (members.size() <= 1) continue;
            String id = "group_child:" + item.name();
            candidates.put(id, aliasSet(id, "GROUP_CHILD_STORAGE", item, members, "all_members"));
        }
    }

    private void addOccursAliasSets(List<DataItem> items, Map<String, AliasSetSummary> candidates) {
        for (DataItem item : items) {
            if (item.occursCount() == null && blank(item.occursDependingOn())) continue;
            List<DataItem> members = descendantsAndSelf(item, items);
            String id = "occurs:" + item.name();
            candidates.put(id, aliasSet(id, "OCCURS_STORAGE", item, members, "all_occurrences_and_children"));
        }
    }

    private void addRedefinesAliasSets(List<DataItem> items, Map<String, DataItem> byName,
                                       Map<String, AliasSetSummary> candidates) {
        Map<String, List<DataItem>> redefinersByBase = new TreeMap<>();
        for (DataItem item : items) {
            if (item.isRedefinition() && !blank(item.redefines())) {
                redefinersByBase.computeIfAbsent(item.redefines(), ignored -> new ArrayList<>()).add(item);
            }
        }
        for (Map.Entry<String, List<DataItem>> entry : redefinersByBase.entrySet()) {
            String baseName = entry.getKey();
            List<DataItem> members = new ArrayList<>();
            DataItem base = byName.get(baseName);
            if (base != null) members.addAll(descendantsAndSelf(base, items));
            for (DataItem redefiner : entry.getValue()) {
                members.addAll(descendantsAndSelf(redefiner, items));
            }
            if (members.isEmpty()) {
                members.add(new DataItem(baseName));
            }
            String id = "redefines:" + baseName;
            candidates.put(id, aliasSet(id, "REDEFINES_OVERLAP", base == null ? members.getFirst() : base,
                    uniqueByName(members), "all_overlapping_members"));
        }
    }

    private List<DataItem> descendantsAndSelf(DataItem item, List<DataItem> items) {
        List<DataItem> result = new ArrayList<>();
        result.add(item);
        Set<String> seenNames = new TreeSet<>();
        seenNames.add(item.name());
        addDescendants(item.name(), items, result, seenNames);
        return uniqueByName(result);
    }

    private void addDescendants(String parent, List<DataItem> items, List<DataItem> result, Set<String> seenNames) {
        for (DataItem item : items) {
            if (!parent.equals(item.parent())) continue;
            if (!seenNames.add(item.name())) continue;
            result.add(item);
            addDescendants(item.name(), items, result, seenNames);
        }
    }

    private List<DataItem> uniqueByName(List<DataItem> items) {
        Map<String, DataItem> byName = new TreeMap<>();
        for (DataItem item : items) byName.putIfAbsent(item.name(), item);
        return new ArrayList<>(byName.values());
    }

    private AliasSetSummary aliasSet(String id, String kind, DataItem base, List<DataItem> members, String killScope) {
        List<DataItem> sortedMembers = uniqueByName(members);
        return new AliasSetSummary(
                id,
                kind,
                base.name(),
                sortedMembers.stream().map(DataItem::name).toList(),
                killScope,
                "conservative",
                layout(base),
                sortedMembers.stream().map(item -> evidence(kind, item)).toList(),
                SUMMARY_SOURCE
        );
    }

    private Map<String, Object> layout(DataItem item) {
        Map<String, Object> layout = new LinkedHashMap<>();
        layout.put("layout_source", "java_data_structure_layout");
        putIfPresent(layout, "base_byte_offset", item.byteOffset());
        putIfPresent(layout, "base_byte_size", item.byteSize());
        return layout;
    }

    private Map<String, Object> evidence(String kind, DataItem item) {
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("variable", item.name());
        evidence.put("alias_kind", kind);
        evidence.put("level_number", item.levelNumber());
        putIfPresent(evidence, "data_type", item.dataType());
        putIfPresent(evidence, "parent", item.parent());
        putIfPresent(evidence, "redefines", item.redefines());
        putIfPresent(evidence, "occurs_count", item.occursCount());
        putIfPresent(evidence, "occurs_depending_on", item.occursDependingOn());
        putIfPresent(evidence, "byte_offset", item.byteOffset());
        putIfPresent(evidence, "byte_size", item.byteSize());
        putIfPresent(evidence, "source_line", item.sourceLine());
        return evidence;
    }

    private String redefines(CobolDataStructure data) {
        if (!(data instanceof Format1DataStructure format1) || !data.isRedefinition()) return "";
        if (format1.getDataDescription() == null || format1.getDataDescription().dataRedefinesClause().isEmpty()) {
            return "";
        }
        return format1.getDataDescription().dataRedefinesClause().getFirst().dataName().getText();
    }

    private String dataType(CobolDataStructure data) {
        if (data.getDataType() == null || data.getDataType().abstractType() == null) return "UNKNOWN";
        return data.getDataType().abstractType().name();
    }

    private Integer occursCount(CobolDataStructure data) {
        if (!(data instanceof Format1DataStructure format1)) return null;
        if (format1.getDataDescription() == null || format1.getDataDescription().dataOccursClause().isEmpty()) {
            return null;
        }
        var occursClause = format1.getDataDescription().dataOccursClause().getFirst();
        if (occursClause.dataOccursTo() != null && occursClause.dataOccursTo().integerLiteral() != null) {
            return Integer.parseInt(occursClause.dataOccursTo().integerLiteral().getText());
        }
        if (occursClause.integerLiteral() != null) return Integer.parseInt(occursClause.integerLiteral().getText());
        return null;
    }

    private String occursDependingOn(CobolDataStructure data) {
        if (!(data instanceof Format1DataStructure format1)) return null;
        if (format1.getDataDescription() == null || format1.getDataDescription().dataOccursClause().isEmpty()) {
            return null;
        }
        var occursClause = format1.getDataDescription().dataOccursClause().getFirst();
        return occursClause.qualifiedDataName() == null ? null : occursClause.qualifiedDataName().getText();
    }

    private Integer sourceLine(CobolDataStructure data) {
        if (!(data instanceof Format1DataStructure format1) || format1.getDataDescription() == null) return null;
        Token start = format1.getDataDescription().getStart();
        return start == null ? null : start.getLine();
    }

    private void putIfPresent(Map<String, Object> map, String key, Object value) {
        if (value == null) return;
        if (value instanceof String string && string.isBlank()) return;
        map.put(key, value);
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private Map<String, ParagraphSummary> paragraphSummaries(List<SerialisableCFGFlowNode> nodes) {
        Map<String, ParagraphSummary> result = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode paragraph : nodes) {
            if (paragraph.getType() != FlowNodeType.PARAGRAPH) continue;
            List<SerialisableCFGFlowNode> containedNodes = containedNodes(paragraph, nodes);
            Set<String> callsParagraphs = new TreeSet<>();
            Set<String> calledPrograms = new TreeSet<>();
            Set<String> externalSideEffects = new TreeSet<>();
            for (SerialisableCFGFlowNode node : containedNodes) {
                collectParagraphCalls(node, callsParagraphs);
                collectCalledPrograms(node, calledPrograms);
                collectExternalSideEffects(node, externalSideEffects);
            }
            boolean transitiveComplete = callsParagraphs.isEmpty();
            List<String> variablesReadDirect = sortedStrings(paragraph.getVariablesRead());
            List<String> variablesModifiedDirect = sortedStrings(paragraph.getVariablesModified());
            result.put(paragraph.getName(), new ParagraphSummary(
                    paragraph.getName(),
                    paragraph.getId(),
                    containedNodes.stream().map(SerialisableCFGFlowNode::getId).toList(),
                    variablesReadDirect,
                    variablesModifiedDirect,
                    transitiveComplete ? variablesReadDirect : List.of(),
                    transitiveComplete ? variablesModifiedDirect : List.of(),
                    callsParagraphs.stream().toList(),
                    calledPrograms.stream().toList(),
                    externalSideEffects.stream().toList(),
                    unsupportedConstructs(callsParagraphs, transitiveComplete),
                    false,
                    transitiveComplete ? "complete_no_paragraph_calls" : "not_computed_perform_targets_present",
                    SUMMARY_SOURCE
            ));
        }
        return result;
    }

    private List<SerialisableCFGFlowNode> containedNodes(SerialisableCFGFlowNode paragraph,
                                                        List<SerialisableCFGFlowNode> nodes) {
        Integer start = paragraph.getSourceLine();
        Integer end = paragraph.getSourceEndLine();
        if (start == null || end == null) return List.of();
        return nodes.stream()
                .filter(node -> !Objects.equals(node.getId(), paragraph.getId()))
                .filter(node -> node.getSourceLine() != null && node.getSourceEndLine() != null)
                .filter(node -> node.getSourceLine() >= start && node.getSourceEndLine() <= end)
                .filter(node -> node.getType() != FlowNodeType.PROCEDURE_DIVISION_BODY)
                .filter(node -> node.getType() != FlowNodeType.PARAGRAPHS)
                .filter(node -> node.getType() != FlowNodeType.PARAGRAPH)
                .toList();
    }

    private List<String> sortedStrings(List<String> values) {
        if (values == null) return List.of();
        Set<String> sorted = new TreeSet<>();
        values.stream().filter(Objects::nonNull).forEach(sorted::add);
        return sorted.stream().toList();
    }

    private void collectParagraphCalls(SerialisableCFGFlowNode node, Set<String> callsParagraphs) {
        Object resolvedStart = node.getMetadata().get("resolved_start");
        if (resolvedStart instanceof String target && !target.isBlank()) callsParagraphs.add(target);
        Object targets = node.getMetadata().get("perform_targets");
        if (!(targets instanceof List<?> targetList)) return;
        for (Object target : targetList) {
            if (target instanceof String targetName && !targetName.isBlank()) callsParagraphs.add(targetName);
        }
    }

    private void collectCalledPrograms(SerialisableCFGFlowNode node, Set<String> calledPrograms) {
        Object resolvedCallTarget = node.getMetadata().get("resolved_call_target");
        if (resolvedCallTarget instanceof String target && !target.isBlank()) {
            calledPrograms.add(target);
            return;
        }
        Object callTarget = node.getMetadata().get("call_target");
        if (callTarget instanceof String target && !target.isBlank()) calledPrograms.add(target);
    }

    private void collectExternalSideEffects(SerialisableCFGFlowNode node, Set<String> externalSideEffects) {
        FlowNodeType type = node.getType();
        if (node.getMetadata().containsKey("call_target")) externalSideEffects.add("CALL");
        if (node.getMetadata().containsKey("cics_command")) externalSideEffects.add("EXEC_CICS");
        if (List.of("ACCEPT", "READ", "WRITE", "OPEN", "CLOSE", "DELETE", "REWRITE", "START")
                .contains(type.name())) {
            externalSideEffects.add(type.name());
        }
    }

    private List<Map<String, Object>> unsupportedConstructs(Set<String> callsParagraphs, boolean transitiveComplete) {
        if (transitiveComplete) return List.of();
        Map<String, Object> unsupported = new LinkedHashMap<>();
        unsupported.put("code", "PARAGRAPH_TRANSITIVE_SUMMARY_NOT_COMPUTED");
        unsupported.put("severity", "info");
        unsupported.put("category", "deferred");
        unsupported.put("message", "PERFORM target summaries are recorded but not expanded transitively in Phase 2.2.");
        unsupported.put("calls_paragraphs", callsParagraphs.stream().toList());
        return List.of(unsupported);
    }

    private record DataItem(String name, String parent, int levelNumber, boolean isRedefinition, String redefines,
                            String dataType, Integer occursCount, String occursDependingOn, Integer byteOffset,
                            Integer byteSize, Integer sourceLine) {
        private DataItem(String missingName) {
            this(missingName, null, 0, false, "", "UNKNOWN", null, null, null, null, null);
        }
    }
}
