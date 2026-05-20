package org.smojol.toolkit.analysis.staticvalue;

import com.mojo.algorithms.domain.FlowNodeType;
import org.antlr.v4.runtime.Token;
import org.smojol.common.ast.SerialisableCFGFlowNode;
import org.smojol.common.ast.SerialisableEdge;
import org.smojol.common.structure.SourceSection;
import org.smojol.common.staticanalysis.value.ConstantStaticValue;
import org.smojol.common.vm.structure.ConditionalDataStructure;
import org.smojol.common.vm.structure.CobolDataStructure;
import org.smojol.common.vm.structure.Format1DataStructure;

import java.math.BigDecimal;
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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class StaticValueDataflowPass {
    private static final String SCHEMA_VERSION = "1.0";
    private static final String ANALYSIS_VERSION = "1.10";
    private static final String SUMMARY_SOURCE = "java_static_value_dataflow";
    private static final int MAX_ITERATIONS = 1000;
    private static final Pattern ACCEPT_TARGET = Pattern.compile(
            "^\\s*ACCEPT\\s+([A-Z][A-Z0-9-]*(?:\\s*\\([^)]*\\))?)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern READ_INTO_TARGET = Pattern.compile(
            "\\bINTO\\s+([A-Z][A-Z0-9-]*(?:\\s*\\([^)]*\\))?)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern STRING_INTO_TARGET = Pattern.compile(
            "\\bINTO\\s+([A-Z][A-Z0-9-]*(?:\\s*\\([^)]*\\))?)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern UNSTRING_INTO_TARGET = Pattern.compile(
            "\\bINTO\\s+([A-Z][A-Z0-9-]*(?:\\s*\\([^)]*\\))?)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern INSPECT_TARGET = Pattern.compile(
            "^\\s*INSPECT\\s+([A-Z][A-Z0-9-]*(?:\\s*\\([^)]*\\))?)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern INSPECT_TALLYING_TARGET = Pattern.compile(
            "\\bTALLYING\\s+([A-Z][A-Z0-9-]*(?:\\s*\\([^)]*\\))?)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern SET_CONDITION_TARGET = Pattern.compile(
            "^\\s*SET\\s+([A-Z][A-Z0-9-]*)\\s+TO\\s+TRUE\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern PICTURE_X_RUN = Pattern.compile("X(?:\\((\\d+)\\))?", Pattern.CASE_INSENSITIVE);
    private static final Pattern PICTURE_NUMERIC_TOKEN = Pattern.compile("([S9V])(?:\\((\\d+)\\))?",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern DATA_REFERENCE_WITH_PARENS = Pattern.compile("\\b[A-Z][A-Z0-9-]*\\s*\\([^)]*\\)",
            Pattern.CASE_INSENSITIVE);
    private static final Set<String> CICS_OUTPUT_ARGUMENTS = Set.of("INTO", "SET", "RESP", "RESP2");

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges) {
        return buildSkeleton(program, nodes, edges, null);
    }

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges,
                                                CobolDataStructure dataStructures) {
        return buildSkeleton(program, nodes, edges, dataStructures, false);
    }

    public DataflowAnalysisResult buildSkeleton(String program, List<SerialisableCFGFlowNode> nodes,
                                                List<SerialisableEdge> edges,
                                                CobolDataStructure dataStructures,
                                                boolean pathSensitiveTargetsEnabled) {
        Map<String, ParagraphSummary> paragraphSummaries = paragraphSummaries(nodes);
        Map<String, AliasSetSummary> aliasSets = aliasSets(dataStructures);
        Map<String, Integer> alphanumericLengths = alphanumericLengths(dataStructures);
        Map<String, NumericPicture> numericPictures = numericPictures(dataStructures);
        Set<String> fileDescriptorVariables = fileDescriptorVariables(dataStructures);
        Map<String, String> conditionParents = conditionParents(dataStructures);
        PropagationResult propagationResult = propagate(nodes, edges, aliasSets, paragraphSummaries,
                alphanumericLengths, numericPictures, fileDescriptorVariables, conditionParents,
                dataStructures != null);
        Map<String, DataflowNodeState> nodeStates = propagationResult.nodeStates();
        int killCount = nodeStates.values().stream().mapToInt(state -> state.kills().size()).sum();
        String status = pathSensitiveTargetsEnabled
                ? "flow_sensitive_call_cics_targets" : "alphanumeric_constant_propagation";

        return new DataflowAnalysisResult(
                program,
                SCHEMA_VERSION,
                "static_value_dataflow",
                ANALYSIS_VERSION,
                status,
                config(pathSensitiveTargetsEnabled, status),
                summary(nodes.size(), edges.size(), paragraphSummaries.size(), aliasSets.size(), killCount,
                        nodeStates, propagationResult.iterationCount(), propagationResult.converged()),
                nodeStates,
                aliasSets,
                paragraphSummaries,
                propagationResult.diagnostics()
        );
    }

    private Map<String, Object> config(boolean pathSensitiveTargetsEnabled, String mode) {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("constant_propagation_enabled", true);
        config.put("path_sensitive_targets_enabled", pathSensitiveTargetsEnabled);
        config.put("paragraph_summaries_enabled", true);
        config.put("alias_analysis_enabled", true);
        config.put("alias_kills_enabled", true);
        config.put("mode", mode);
        config.put("max_iterations", MAX_ITERATIONS);
        return config;
    }

    private Map<String, Object> summary(int nodeCount, int edgeCount, int paragraphSummaryCount, int aliasSetCount,
                                        int killCount, Map<String, DataflowNodeState> nodeStates,
                                        int iterationCount, boolean converged) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("node_count", nodeCount);
        summary.put("edge_count", edgeCount);
        summary.put("entry_constant_count", nodeStates.values().stream()
                .mapToInt(state -> state.entryConstants().size()).sum());
        summary.put("exit_constant_count", nodeStates.values().stream()
                .mapToInt(state -> state.exitConstants().size()).sum());
        summary.put("kill_count", killCount);
        int nodeDiagnosticCount = nodeStates.values().stream()
                .mapToInt(state -> state.diagnostics().size()).sum();
        summary.put("diagnostic_count", nodeDiagnosticCount + (converged ? 0 : 1));
        summary.put("alias_set_count", aliasSetCount);
        summary.put("paragraph_summary_count", paragraphSummaryCount);
        summary.put("iteration_count", iterationCount);
        summary.put("max_iterations", MAX_ITERATIONS);
        summary.put("converged", converged);
        return summary;
    }

    private PropagationResult propagate(List<SerialisableCFGFlowNode> nodes, List<SerialisableEdge> edges,
                                        Map<String, AliasSetSummary> aliasSets,
                                        Map<String, ParagraphSummary> paragraphSummaries,
                                        Map<String, Integer> alphanumericLengths,
                                        Map<String, NumericPicture> numericPictures,
                                        Set<String> fileDescriptorVariables,
                                        Map<String, String> conditionParents,
                                        boolean numericPictureGatingEnabled) {
        Map<String, List<String>> transitiveModifiedVariablesByParagraph =
                transitiveModifiedVariablesByParagraph(paragraphSummaries);
        Map<String, List<Map<String, Object>>> killsByNode =
                killsByNode(nodes, aliasSets, transitiveModifiedVariablesByParagraph,
                        fileDescriptorVariables, conditionParents);
        Map<String, List<String>> predecessors = predecessors(nodes, edges);
        Map<String, Map<String, Map<String, Object>>> entryStates = emptyStates(nodes);
        Map<String, Map<String, Map<String, Object>>> exitStates = emptyStates(nodes);
        boolean converged = false;
        int iterationCount = 0;

        for (int iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
            iterationCount = iteration;
            boolean changed = false;
            for (SerialisableCFGFlowNode node : nodes) {
                Map<String, Map<String, Object>> entry = joinedEntry(predecessors.get(node.getId()), exitStates);
                Map<String, Map<String, Object>> exit = transfer(node, entry, killsByNode.get(node.getId()),
                        alphanumericLengths, numericPictures, numericPictureGatingEnabled);
                if (!entry.equals(entryStates.get(node.getId())) || !exit.equals(exitStates.get(node.getId()))) {
                    changed = true;
                    entryStates.put(node.getId(), entry);
                    exitStates.put(node.getId(), exit);
                }
            }
            if (!changed) {
                converged = true;
                break;
            }
        }

        Map<String, List<Map<String, Object>>> mergeDiagnosticsByNode =
                mergeDiagnosticsByNode(nodes, predecessors, exitStates);
        Map<String, List<Map<String, Object>>> nodeDiagnostics =
                appendDiagnostics(mergeDiagnosticsByNode, loopDiagnosticsByNode(nodes, edges));
        Map<String, DataflowNodeState> nodeStates = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeStates.put(node.getId(), new DataflowNodeState(
                    outputState(entryStates.get(node.getId())),
                    outputState(exitStates.get(node.getId())),
                    killsByNode.get(node.getId()),
                    nodeDiagnostics.get(node.getId())));
        }
        return new PropagationResult(nodeStates, iterationCount, converged, diagnostics(converged));
    }

    private Map<String, List<Map<String, Object>>> appendDiagnostics(
            Map<String, List<Map<String, Object>>> primary,
            Map<String, List<Map<String, Object>>> additional) {
        Map<String, List<Map<String, Object>>> combined = new LinkedHashMap<>();
        for (Map.Entry<String, List<Map<String, Object>>> entry : primary.entrySet()) {
            List<Map<String, Object>> diagnostics = new ArrayList<>(entry.getValue());
            diagnostics.addAll(additional.getOrDefault(entry.getKey(), List.of()));
            combined.put(entry.getKey(), diagnostics);
        }
        return combined;
    }

    private Map<String, List<Map<String, Object>>> mergeDiagnosticsByNode(List<SerialisableCFGFlowNode> nodes,
            Map<String, List<String>> predecessors,
            Map<String, Map<String, Map<String, Object>>> exitStates) {
        Map<String, List<Map<String, Object>>> diagnosticsByNode = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) diagnosticsByNode.put(node.getId(), List.of());

        for (SerialisableCFGFlowNode node : nodes) {
            List<String> predecessorIds = sortedStrings(predecessors.get(node.getId()));
            if (predecessorIds.size() < 2) continue;

            Set<String> variables = new TreeSet<>();
            for (String predecessorId : predecessorIds) variables.addAll(exitStates.get(predecessorId).keySet());

            List<Map<String, Object>> diagnostics = new ArrayList<>();
            for (String variable : variables) {
                List<Map<String, Object>> incomingValues = incomingValues(variable, predecessorIds, exitStates);
                List<Map<String, Object>> presentValues = incomingValues.stream()
                        .filter(incoming -> Boolean.TRUE.equals(incoming.get("present")))
                        .map(this::compactIncomingValue)
                        .toList();
                if (presentValues.size() != predecessorIds.size() || allValuesEqual(presentValues)) continue;
                diagnostics.add(mergeDiagnostic(variable, predecessorIds, incomingValues));
            }
            if (!diagnostics.isEmpty()) diagnosticsByNode.put(node.getId(), diagnostics);
        }
        return diagnosticsByNode;
    }

    private List<Map<String, Object>> incomingValues(String variable, List<String> predecessorIds,
            Map<String, Map<String, Map<String, Object>>> exitStates) {
        List<Map<String, Object>> values = new ArrayList<>();
        for (String predecessorId : predecessorIds) {
            Map<String, Object> value = exitStates.get(predecessorId).get(variable);
            Map<String, Object> incoming = new LinkedHashMap<>();
            incoming.put("predecessor_node_id", predecessorId);
            incoming.put("present", value != null);
            if (value != null) incoming.putAll(compactValue(value));
            values.add(incoming);
        }
        return values;
    }

    private Map<String, Object> compactIncomingValue(Map<String, Object> incomingValue) {
        Map<String, Object> compact = new LinkedHashMap<>();
        for (String key : List.of("state", "kind", "normalized_value", "display_value")) {
            compact.put(key, incomingValue.get(key));
        }
        return compact;
    }

    private Map<String, Object> compactValue(Map<String, Object> value) {
        Map<String, Object> compact = new LinkedHashMap<>();
        for (String key : List.of("state", "kind", "normalized_value", "display_value")) {
            if (value.containsKey(key)) compact.put(key, value.get(key));
        }
        return compact;
    }

    private boolean allValuesEqual(List<Map<String, Object>> values) {
        if (values.isEmpty()) return true;
        Map<String, Object> first = values.getFirst();
        return values.stream().allMatch(first::equals);
    }

    private Map<String, Object> mergeDiagnostic(String variable, List<String> predecessorIds,
                                                List<Map<String, Object>> incomingValues) {
        Map<String, Object> diagnostic = new LinkedHashMap<>();
        diagnostic.put("code", "DATAFLOW_CONSTANT_DROPPED_AT_JOIN");
        diagnostic.put("severity", "info");
        diagnostic.put("category", "merge");
        diagnostic.put("variable", variable);
        diagnostic.put("reason", "conflicting_predecessor_constants");
        diagnostic.put("predecessor_node_ids", predecessorIds);
        diagnostic.put("incoming_values", incomingValues);
        diagnostic.put("message", "Constant for " + variable
                + " was dropped at CFG join because predecessor paths prove different values.");
        diagnostic.put("provenance_source", SUMMARY_SOURCE);
        return diagnostic;
    }

    private Map<String, List<Map<String, Object>>> loopDiagnosticsByNode(List<SerialisableCFGFlowNode> nodes,
                                                                         List<SerialisableEdge> edges) {
        Map<String, List<Map<String, Object>>> diagnosticsByNode = new LinkedHashMap<>();
        Map<String, SerialisableCFGFlowNode> nodesById = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            diagnosticsByNode.put(node.getId(), List.of());
            nodesById.put(node.getId(), node);
        }

        for (Set<String> component : stronglyConnectedComponents(nodes, edges)) {
            if (!isCycleComponent(component, edges)) continue;
            List<String> componentNodeIds = component.stream().sorted().toList();
            for (String nodeId : componentNodeIds) {
                SerialisableCFGFlowNode node = nodesById.get(nodeId);
                if (node == null) continue;
                List<Map<String, Object>> diagnostics = new ArrayList<>();
                for (String variable : sortedStrings(node.getVariablesModified())) {
                    diagnostics.add(loopDiagnostic(node, variable, componentNodeIds));
                }
                if (!diagnostics.isEmpty()) diagnosticsByNode.put(nodeId, diagnostics);
            }
        }
        return diagnosticsByNode;
    }

    private List<Set<String>> stronglyConnectedComponents(List<SerialisableCFGFlowNode> nodes,
                                                          List<SerialisableEdge> edges) {
        Map<String, List<String>> successors = successors(nodes, edges);
        Map<String, Integer> indexes = new TreeMap<>();
        Map<String, Integer> lowlinks = new TreeMap<>();
        List<String> stack = new ArrayList<>();
        Set<String> onStack = new TreeSet<>();
        List<Set<String>> components = new ArrayList<>();
        int[] nextIndex = {0};

        for (String nodeId : successors.keySet()) {
            if (!indexes.containsKey(nodeId)) {
                strongConnect(nodeId, successors, indexes, lowlinks, stack, onStack, components, nextIndex);
            }
        }
        return components;
    }

    private void strongConnect(String nodeId, Map<String, List<String>> successors, Map<String, Integer> indexes,
                               Map<String, Integer> lowlinks, List<String> stack, Set<String> onStack,
                               List<Set<String>> components, int[] nextIndex) {
        indexes.put(nodeId, nextIndex[0]);
        lowlinks.put(nodeId, nextIndex[0]);
        nextIndex[0]++;
        stack.add(nodeId);
        onStack.add(nodeId);

        for (String successorId : successors.getOrDefault(nodeId, List.of())) {
            if (!indexes.containsKey(successorId)) {
                strongConnect(successorId, successors, indexes, lowlinks, stack, onStack, components, nextIndex);
                lowlinks.put(nodeId, Math.min(lowlinks.get(nodeId), lowlinks.get(successorId)));
            } else if (onStack.contains(successorId)) {
                lowlinks.put(nodeId, Math.min(lowlinks.get(nodeId), indexes.get(successorId)));
            }
        }

        if (!Objects.equals(lowlinks.get(nodeId), indexes.get(nodeId))) return;
        Set<String> component = new TreeSet<>();
        while (!stack.isEmpty()) {
            String member = stack.removeLast();
            onStack.remove(member);
            component.add(member);
            if (member.equals(nodeId)) break;
        }
        components.add(component);
    }

    private Map<String, List<String>> successors(List<SerialisableCFGFlowNode> nodes, List<SerialisableEdge> edges) {
        Set<String> nodeIds = new TreeSet<>();
        Map<String, List<String>> successors = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeIds.add(node.getId());
            successors.put(node.getId(), new ArrayList<>());
        }
        for (SerialisableEdge edge : edges) {
            if (!nodeIds.contains(edge.fromNodeID()) || !nodeIds.contains(edge.toNodeID())) continue;
            successors.get(edge.fromNodeID()).add(edge.toNodeID());
        }
        successors.replaceAll((ignored, values) -> sortedStrings(values));
        return successors;
    }

    private boolean isCycleComponent(Set<String> component, List<SerialisableEdge> edges) {
        if (component.size() > 1) return true;
        String onlyNode = component.stream().findFirst().orElse(null);
        if (onlyNode == null) return false;
        return edges.stream().anyMatch(edge -> onlyNode.equals(edge.fromNodeID()) && onlyNode.equals(edge.toNodeID()));
    }

    private Map<String, Object> loopDiagnostic(SerialisableCFGFlowNode node, String variable,
                                               List<String> componentNodeIds) {
        Map<String, Object> diagnostic = new LinkedHashMap<>();
        diagnostic.put("code", "DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED");
        diagnostic.put("severity", "info");
        diagnostic.put("category", "loop");
        diagnostic.put("variable", canonicalVariable(variable));
        diagnostic.put("reason", "modified_inside_cfg_cycle");
        diagnostic.put("component_node_ids", componentNodeIds);
        diagnostic.put("statement_type", node.getType().name());
        putIfPresent(diagnostic, "statement_text", node.getOriginalText());
        putIfPresent(diagnostic, "source_line", node.getSourceLine());
        putIfPresent(diagnostic, "source_column", node.getSourceColumn());
        diagnostic.put("message", "Loop-carried constant for " + canonicalVariable(variable)
                + " is not inferred because the variable is modified inside a CFG cycle.");
        diagnostic.put("provenance_source", SUMMARY_SOURCE);
        return diagnostic;
    }

    private Map<String, List<Map<String, Object>>> killsByNode(List<SerialisableCFGFlowNode> nodes,
                                                               Map<String, AliasSetSummary> aliasSets,
                                                               Map<String, List<String>>
                                                                       transitiveModifiedVariablesByParagraph,
                                                               Set<String> fileDescriptorVariables,
                                                               Map<String, String> conditionParents) {
        Map<String, List<Map<String, Object>>> result = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            result.put(node.getId(), killFacts(node, aliasSets, transitiveModifiedVariablesByParagraph,
                    fileDescriptorVariables, conditionParents));
        }
        return result;
    }

    private List<Map<String, Object>> killFacts(SerialisableCFGFlowNode node,
                                                Map<String, AliasSetSummary> aliasSets,
                                                Map<String, List<String>>
                                                        transitiveModifiedVariablesByParagraph,
                                                Set<String> fileDescriptorVariables,
                                                Map<String, String> conditionParents) {
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (Map<String, Object> kill : aliasKills(node, aliasSets)) kills.put(killKey(kill), kill);
        for (Map<String, Object> kill : dataflowKills(node, transitiveModifiedVariablesByParagraph,
                fileDescriptorVariables, conditionParents)) {
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private Map<String, Map<String, Map<String, Object>>> emptyStates(List<SerialisableCFGFlowNode> nodes) {
        Map<String, Map<String, Map<String, Object>>> states = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            states.put(node.getId(), new TreeMap<>());
        }
        return states;
    }

    private Map<String, List<String>> predecessors(List<SerialisableCFGFlowNode> nodes, List<SerialisableEdge> edges) {
        Set<String> nodeIds = new TreeSet<>();
        Map<String, List<String>> predecessors = new LinkedHashMap<>();
        for (SerialisableCFGFlowNode node : nodes) {
            nodeIds.add(node.getId());
            predecessors.put(node.getId(), new ArrayList<>());
        }
        for (SerialisableEdge edge : edges) {
            if (!nodeIds.contains(edge.fromNodeID()) || !nodeIds.contains(edge.toNodeID())) continue;
            predecessors.get(edge.toNodeID()).add(edge.fromNodeID());
        }
        return predecessors;
    }

    private Map<String, Map<String, Object>> joinedEntry(List<String> predecessorIds,
            Map<String, Map<String, Map<String, Object>>> exitStates) {
        if (predecessorIds == null || predecessorIds.isEmpty()) return new TreeMap<>();
        Map<String, Map<String, Object>> joined = new TreeMap<>(exitStates.get(predecessorIds.getFirst()));
        for (int i = 1; i < predecessorIds.size(); i++) {
            Map<String, Map<String, Object>> predecessorState = exitStates.get(predecessorIds.get(i));
            joined.entrySet().removeIf(entry -> !predecessorState.containsKey(entry.getKey())
                    || !entry.getValue().equals(predecessorState.get(entry.getKey())));
        }
        return joined;
    }

    private Map<String, Map<String, Object>> transfer(SerialisableCFGFlowNode node,
            Map<String, Map<String, Object>> entry, List<Map<String, Object>> kills,
            Map<String, Integer> alphanumericLengths, Map<String, NumericPicture> numericPictures,
            boolean numericPictureGatingEnabled) {
        Map<String, Map<String, Object>> exit = new TreeMap<>(entry);
        for (Map<String, Object> kill : kills) {
            Object variable = kill.get("variable");
            if (variable instanceof String variableName) exit.remove(canonicalVariable(variableName));
        }

        Map<String, Map<String, Object>> producedConstants = producedConstants(node, entry, alphanumericLengths,
                numericPictures, numericPictureGatingEnabled);
        Set<String> producedTargets = producedConstants.keySet();
        for (String modifiedVariable : sortedStrings(node.getVariablesModified())) {
            String canonicalModified = canonicalVariable(modifiedVariable);
            if (!producedTargets.contains(canonicalModified)) exit.remove(canonicalModified);
        }
        producedConstants.forEach(exit::put);
        return exit;
    }

    private Map<String, Map<String, Object>> producedConstants(SerialisableCFGFlowNode node,
                                                               Map<String, Map<String, Object>> entry,
                                                               Map<String, Integer> alphanumericLengths,
                                                               Map<String, NumericPicture> numericPictures,
                                                               boolean numericPictureGatingEnabled) {
        Map<String, Map<String, Object>> constants = new TreeMap<>();
        Object foldedFacts = node.getMetadata().get("folded_value_facts");
        if (foldedFacts instanceof List<?> foldedFactList) {
            for (Object fact : foldedFactList) {
                addFoldedConstant(constants, fact, node, numericPictures, numericPictureGatingEnabled);
            }
        }

        Object assignmentFacts = node.getMetadata().get("assignment_facts");
        if (assignmentFacts instanceof List<?> assignmentFactList) {
            for (Object fact : assignmentFactList) {
                addAssignmentConstant(constants, fact, entry, alphanumericLengths, numericPictures,
                        numericPictureGatingEnabled);
            }
        }
        addMoveCopyConstants(constants, node, entry, alphanumericLengths, numericPictures,
                numericPictureGatingEnabled);
        addDataflowExpressionConstants(constants, node, entry, numericPictures, numericPictureGatingEnabled);
        return constants;
    }

    private void addDataflowExpressionConstants(Map<String, Map<String, Object>> constants,
                                                SerialisableCFGFlowNode node,
                                                Map<String, Map<String, Object>> entry,
                                                Map<String, NumericPicture> numericPictures,
                                                boolean numericPictureGatingEnabled) {
        if (node.getType() != FlowNodeType.COMPUTE || node.getOriginalText() == null) return;
        List<String> modifiedVariables = sortedStrings(node.getVariablesModified());
        if (modifiedVariables.size() != 1) return;
        if (hasUnsupportedComputeSemantics(node.getOriginalText())) return;
        if (hasSubscriptOrReferenceModification(node.getOriginalText())) return;
        Object expressionFacts = node.getMetadata().get("dataflow_expression_facts");
        if (!(expressionFacts instanceof List<?> facts)) return;
        for (Object fact : facts) {
            if (!(fact instanceof Map<?, ?> rawFact)) continue;
            Map<String, Object> expressionFact = stringKeyMap(rawFact);
            Object target = expressionFact.get("target_variable");
            Object expression = expressionFact.get("expression");
            if (!(target instanceof String targetVariable) || !(expression instanceof Map<?, ?> rawExpression)) {
                continue;
            }
            if (hasSubscriptOrReferenceModification(targetVariable)) continue;
            evaluateDataflowExpression(stringKeyMap(rawExpression), entry).ifPresent(value -> {
                Map<String, Object> valueMap = ConstantStaticValue.numeric(value, value.toPlainString()).toJsonMap();
                if (fitsNumericTarget(targetVariable, valueMap, numericPictures, numericPictureGatingEnabled)) {
                    constants.put(canonicalVariable(targetVariable), valueMap);
                }
            });
        }
    }

    private java.util.Optional<BigDecimal> evaluateDataflowExpression(Map<String, Object> expression,
                                                                      Map<String, Map<String, Object>> entry) {
        Object kind = expression.get("kind");
        if ("numeric_literal".equals(kind)) {
            Object normalized = expression.get("normalized_value");
            if (!(normalized instanceof String text)) return java.util.Optional.empty();
            return decimalValue(text);
        }
        if ("variable".equals(kind)) {
            Object name = expression.get("name");
            if (!(name instanceof String variable)) return java.util.Optional.empty();
            Map<String, Object> value = entry.get(canonicalVariable(variable));
            if (value == null || !"CONSTANT".equals(value.get("state")) || !"NUMERIC".equals(value.get("kind"))) {
                return java.util.Optional.empty();
            }
            Object normalized = value.get("normalized_value");
            if (!(normalized instanceof String text)) return java.util.Optional.empty();
            return decimalValue(text);
        }
        if ("unary".equals(kind)) {
            Object operator = expression.get("operator");
            Object operand = expression.get("operand");
            if (!"NEGATE".equals(operator) || !(operand instanceof Map<?, ?> rawOperand)) {
                return java.util.Optional.empty();
            }
            return evaluateDataflowExpression(stringKeyMap(rawOperand), entry).map(BigDecimal::negate);
        }
        if ("binary".equals(kind)) {
            Object operator = expression.get("operator");
            Object left = expression.get("left");
            Object right = expression.get("right");
            if (!(operator instanceof String op) || !(left instanceof Map<?, ?> rawLeft)
                    || !(right instanceof Map<?, ?> rawRight)) {
                return java.util.Optional.empty();
            }
            java.util.Optional<BigDecimal> leftValue = evaluateDataflowExpression(stringKeyMap(rawLeft), entry);
            java.util.Optional<BigDecimal> rightValue = evaluateDataflowExpression(stringKeyMap(rawRight), entry);
            if (leftValue.isEmpty() || rightValue.isEmpty()) return java.util.Optional.empty();
            return evaluateBinaryDataflowExpression(op, leftValue.get(), rightValue.get());
        }
        return java.util.Optional.empty();
    }

    private java.util.Optional<BigDecimal> evaluateBinaryDataflowExpression(String operator, BigDecimal left,
                                                                           BigDecimal right) {
        return switch (operator) {
            case "ADD" -> java.util.Optional.of(left.add(right));
            case "SUBTRACT" -> java.util.Optional.of(left.subtract(right));
            case "MULTIPLY" -> java.util.Optional.of(left.multiply(right));
            case "DIVIDE" -> {
                if (right.compareTo(BigDecimal.ZERO) == 0) yield java.util.Optional.empty();
                try {
                    yield java.util.Optional.of(left.divide(right));
                } catch (ArithmeticException ignored) {
                    yield java.util.Optional.empty();
                }
            }
            default -> java.util.Optional.empty();
        };
    }

    private boolean hasUnsupportedComputeSemantics(String statementText) {
        String upper = statementText.toUpperCase(Locale.ROOT);
        return upper.contains(" ROUNDED") || upper.contains(" ON SIZE ERROR")
                || upper.contains(" NOT ON SIZE ERROR");
    }

    private void addMoveCopyConstants(Map<String, Map<String, Object>> constants, SerialisableCFGFlowNode node,
                                      Map<String, Map<String, Object>> entry,
                                      Map<String, Integer> alphanumericLengths,
                                      Map<String, NumericPicture> numericPictures,
                                      boolean numericPictureGatingEnabled) {
        if (node.getType() != FlowNodeType.MOVE) return;
        if (hasSubscriptOrReferenceModification(node.getOriginalText())) return;
        List<String> sourceVariables = sortedStrings(node.getVariablesRead());
        if (sourceVariables.size() != 1) return;
        if (hasSubscriptOrReferenceModification(sourceVariables.get(0))) return;
        Map<String, Object> sourceValue = entry.get(canonicalVariable(sourceVariables.get(0)));
        if (sourceValue == null || !isSupportedCopyConstant(sourceValue)) return;
        for (String targetVariable : sortedStrings(node.getVariablesModified())) {
            if (hasSubscriptOrReferenceModification(targetVariable)) continue;
            if (!fitsAlphanumericTarget(targetVariable, sourceValue, alphanumericLengths)) continue;
            if (!fitsNumericTarget(targetVariable, sourceValue, numericPictures, numericPictureGatingEnabled)) continue;
            constants.put(canonicalVariable(targetVariable), new LinkedHashMap<>(sourceValue));
        }
    }

    private void addFoldedConstant(Map<String, Map<String, Object>> constants, Object fact,
                                   SerialisableCFGFlowNode node, Map<String, NumericPicture> numericPictures,
                                   boolean numericPictureGatingEnabled) {
        if (node.getOriginalText() != null && hasUnsupportedComputeSemantics(node.getOriginalText())) return;
        if (!(fact instanceof Map<?, ?> rawFact)) return;
        Map<String, Object> foldedFact = stringKeyMap(rawFact);
        Object target = foldedFact.get("target_variable");
        Object value = foldedFact.get("value");
        if (!(target instanceof String targetVariable) || !(value instanceof Map<?, ?> rawValue)) return;
        if (hasSubscriptOrReferenceModification(targetVariable)) return;
        Map<String, Object> valueMap = stringKeyMap(rawValue);
        if (!isNumericConstant(valueMap)) return;
        if (!fitsNumericTarget(targetVariable, valueMap, numericPictures, numericPictureGatingEnabled)) return;
        constants.put(canonicalVariable(targetVariable), valueMap);
    }

    private void addAssignmentConstant(Map<String, Map<String, Object>> constants, Object fact,
                                       Map<String, Map<String, Object>> entry,
                                       Map<String, Integer> alphanumericLengths,
                                       Map<String, NumericPicture> numericPictures,
                                       boolean numericPictureGatingEnabled) {
        if (!(fact instanceof Map<?, ?> rawFact)) return;
        Map<String, Object> assignmentFact = stringKeyMap(rawFact);
        Object target = assignmentFact.get("target_variable");
        Object sourceValue = assignmentFact.get("source_value");
        if (!(target instanceof String targetVariable) || !(sourceValue instanceof String literal)) return;
        if (hasSubscriptOrReferenceModification(targetVariable) || hasSubscriptOrReferenceModification(literal)) return;
        numericLiteralValue(literal).ifPresent(value -> {
            if (fitsNumericTarget(targetVariable, value, numericPictures, numericPictureGatingEnabled)) {
                constants.put(canonicalVariable(targetVariable), value);
            }
        });
        alphanumericLiteralValue(literal, targetVariable, alphanumericLengths).ifPresent(value ->
                constants.put(canonicalVariable(targetVariable), value));
        String canonicalSource = canonicalVariable(literal);
        if (!entry.containsKey(canonicalSource)) return;
        if (!fitsAlphanumericTarget(targetVariable, entry.get(canonicalSource), alphanumericLengths)) return;
        if (!fitsNumericTarget(targetVariable, entry.get(canonicalSource), numericPictures,
                numericPictureGatingEnabled)) {
            return;
        }
        constants.put(canonicalVariable(targetVariable), new LinkedHashMap<>(entry.get(canonicalSource)));
    }

    private boolean hasSubscriptOrReferenceModification(String text) {
        return text != null && DATA_REFERENCE_WITH_PARENS.matcher(text).find();
    }

    private java.util.Optional<Map<String, Object>> numericLiteralValue(String literal) {
        if (literal == null || !literal.matches("[+-]?\\d+(\\.\\d+)?")) return java.util.Optional.empty();
        try {
            return java.util.Optional.of(ConstantStaticValue.numeric(new BigDecimal(literal), literal).toJsonMap());
        } catch (NumberFormatException ignored) {
            return java.util.Optional.empty();
        }
    }

    private java.util.Optional<Map<String, Object>> alphanumericLiteralValue(String literal, String targetVariable,
                                                                             Map<String, Integer> alphanumericLengths) {
        if (!isQuotedLiteral(literal)) return java.util.Optional.empty();
        String normalized = literal.substring(1, literal.length() - 1).toUpperCase(Locale.ROOT);
        if (!fitsAlphanumericTarget(targetVariable, normalized, alphanumericLengths)) return java.util.Optional.empty();
        return java.util.Optional.of(ConstantStaticValue.alphanumeric(literal, normalized).toJsonMap());
    }

    private boolean fitsAlphanumericTarget(String targetVariable, Map<String, Object> value,
                                           Map<String, Integer> alphanumericLengths) {
        if (!"CONSTANT".equals(value.get("state")) || !"ALPHANUMERIC".equals(value.get("kind"))) return true;
        Object normalized = value.get("normalized_value");
        return !(normalized instanceof String stringValue)
                || fitsAlphanumericTarget(targetVariable, stringValue, alphanumericLengths);
    }

    private boolean fitsAlphanumericTarget(String targetVariable, String normalizedValue,
                                           Map<String, Integer> alphanumericLengths) {
        Integer targetLength = alphanumericLengths.get(canonicalVariable(targetVariable));
        return targetLength == null || normalizedValue.length() <= targetLength;
    }

    private boolean fitsNumericTarget(String targetVariable, Map<String, Object> value,
                                      Map<String, NumericPicture> numericPictures,
                                      boolean numericPictureGatingEnabled) {
        if (!isNumericConstant(value)) return true;
        if (!numericPictureGatingEnabled) return true;
        NumericPicture picture = numericPictures.get(canonicalVariable(targetVariable));
        if (picture == null) return false;
        return numericDecimal(value).map(picture::fits).orElse(false);
    }

    private java.util.Optional<BigDecimal> numericDecimal(Map<String, Object> value) {
        Object rawNumeric = value.get("numeric");
        if (rawNumeric instanceof Map<?, ?> rawNumericMap) {
            Object decimal = stringKeyMap(rawNumericMap).get("decimal");
            if (decimal instanceof String decimalValue) return decimalValue(decimalValue);
        }
        Object normalized = value.get("normalized_value");
        return normalized instanceof String normalizedValue
                ? decimalValue(normalizedValue) : java.util.Optional.empty();
    }

    private java.util.Optional<BigDecimal> decimalValue(String value) {
        try {
            return java.util.Optional.of(new BigDecimal(value));
        } catch (NumberFormatException ignored) {
            return java.util.Optional.empty();
        }
    }

    private boolean isQuotedLiteral(String literal) {
        if (literal == null || literal.length() < 2) return false;
        char first = literal.charAt(0);
        char last = literal.charAt(literal.length() - 1);
        return (first == '\'' && last == '\'') || (first == '"' && last == '"');
    }

    private boolean isSupportedCopyConstant(Map<String, Object> value) {
        if (!"CONSTANT".equals(value.get("state"))) return false;
        Object kind = value.get("kind");
        return "NUMERIC".equals(kind) || "ALPHANUMERIC".equals(kind);
    }

    private boolean isNumericConstant(Map<String, Object> value) {
        return "CONSTANT".equals(value.get("state")) && "NUMERIC".equals(value.get("kind"));
    }

    private Map<String, Object> stringKeyMap(Map<?, ?> rawMap) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : rawMap.entrySet()) {
            result.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        return result;
    }

    private Map<String, Object> outputState(Map<String, Map<String, Object>> state) {
        Map<String, Object> output = new LinkedHashMap<>();
        state.forEach(output::put);
        return output;
    }

    private List<Map<String, Object>> diagnostics(boolean converged) {
        if (converged) return List.of();
        Map<String, Object> diagnostic = new LinkedHashMap<>();
        diagnostic.put("code", "DATAFLOW_MAX_ITERATIONS_REACHED");
        diagnostic.put("severity", "warning");
        diagnostic.put("category", "limit");
        diagnostic.put("message", "Static value propagation stopped before convergence.");
        diagnostic.put("max_iterations", MAX_ITERATIONS);
        return List.of(diagnostic);
    }

    private List<Map<String, Object>> dataflowKills(SerialisableCFGFlowNode node,
                                                    Map<String, List<String>>
                                                            transitiveModifiedVariablesByParagraph,
                                                    Set<String> fileDescriptorVariables,
                                                    Map<String, String> conditionParents) {
        return switch (node.getType()) {
            case ACCEPT -> acceptKills(node);
            case CALL -> callUsingKills(node);
            case DIALECT -> dialectOutputKills(node);
            case INITIALIZE -> targetKills(node, "INITIALIZE_TARGET_KILL", "initialize_target");
            case INSPECT -> inspectKills(node);
            case READ -> readKills(node, fileDescriptorVariables);
            case SET -> setConditionParentKills(node, conditionParents);
            case STRING -> originalTextTargetKills(node, STRING_INTO_TARGET, "STRING_OUTPUT_KILL", "string_into");
            case UNSTRING -> originalTextTargetKills(node, UNSTRING_INTO_TARGET, "UNSTRING_OUTPUT_KILL", "unstring_into");
            case PERFORM -> performTransitiveKills(node, transitiveModifiedVariablesByParagraph);
            default -> List.of();
        };
    }

    private List<Map<String, Object>> performTransitiveKills(SerialisableCFGFlowNode node,
            Map<String, List<String>> transitiveModifiedVariablesByParagraph) {
        Set<String> targets = new TreeSet<>();
        collectParagraphCalls(node, targets);
        if (targets.isEmpty()) return List.of();

        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (String target : targets) {
            for (String variable : transitiveModifiedVariablesByParagraph.getOrDefault(paragraphName(target),
                    List.of())) {
                Map<String, Object> kill = performTransitiveKill(node, variable, target);
                kills.put(killKey(kill), kill);
            }
        }
        return new ArrayList<>(kills.values());
    }

    private Map<String, Object> performTransitiveKill(SerialisableCFGFlowNode node, String variable,
                                                      String performedParagraph) {
        Map<String, Object> kill = dataflowKill(node, variable,
                "PERFORM_TRANSITIVE_KILL", "perform_transitive_modified_variable");
        kill.put("kill_scope", "paragraph_transitive");
        kill.put("performed_paragraph", paragraphName(performedParagraph));
        return kill;
    }

    private List<Map<String, Object>> acceptKills(SerialisableCFGFlowNode node) {
        if (node.getOriginalText() == null) return List.of();
        Matcher matcher = ACCEPT_TARGET.matcher(node.getOriginalText());
        if (!matcher.find()) return List.of();
        return List.of(dataflowKill(node, matcher.group(1), "RUNTIME_INPUT_KILL", "runtime_accept"));
    }

    private List<Map<String, Object>> originalTextTargetKills(SerialisableCFGFlowNode node, Pattern pattern,
                                                              String code, String reason) {
        if (node.getOriginalText() == null) return List.of();
        Matcher matcher = pattern.matcher(node.getOriginalText());
        if (!matcher.find()) return List.of();
        return List.of(dataflowKill(node, matcher.group(1), code, reason));
    }

    private List<Map<String, Object>> readKills(SerialisableCFGFlowNode node, Set<String> fileDescriptorVariables) {
        if (node.getOriginalText() == null) return List.of();
        Matcher intoMatcher = READ_INTO_TARGET.matcher(node.getOriginalText());
        if (intoMatcher.find()) {
            return List.of(dataflowKill(node, intoMatcher.group(1), "READ_INTO_KILL", "read_into"));
        }

        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (String variable : fileDescriptorVariables) {
            Map<String, Object> kill = dataflowKill(node, variable, "READ_RECORD_BUFFER_KILL",
                    "read_record_buffer");
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private List<Map<String, Object>> inspectKills(SerialisableCFGFlowNode node) {
        if (node.getOriginalText() == null) return List.of();
        String upper = node.getOriginalText().toUpperCase(Locale.ROOT);
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        if (upper.contains(" REPLACING ")) {
            Matcher targetMatcher = INSPECT_TARGET.matcher(node.getOriginalText());
            if (targetMatcher.find()) {
                Map<String, Object> kill = dataflowKill(node, targetMatcher.group(1),
                        "INSPECT_TARGET_KILL", "inspect_target");
                kills.put(killKey(kill), kill);
            }
        }
        Matcher tallyingMatcher = INSPECT_TALLYING_TARGET.matcher(node.getOriginalText());
        while (tallyingMatcher.find()) {
            Map<String, Object> kill = dataflowKill(node, tallyingMatcher.group(1),
                    "INSPECT_TALLYING_KILL", "inspect_tallying");
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private List<Map<String, Object>> setConditionParentKills(SerialisableCFGFlowNode node,
                                                              Map<String, String> conditionParents) {
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        Set<String> conditionNames = new TreeSet<>(sortedStrings(node.getVariablesModified()));
        if (node.getOriginalText() != null) {
            Matcher matcher = SET_CONDITION_TARGET.matcher(node.getOriginalText());
            if (matcher.find()) conditionNames.add(matcher.group(1));
        }
        for (String modifiedVariable : conditionNames) addConditionParentKill(node, conditionParents, kills,
                modifiedVariable);
        return new ArrayList<>(kills.values());
    }

    private void addConditionParentKill(SerialisableCFGFlowNode node, Map<String, String> conditionParents,
                                        Map<String, Map<String, Object>> kills, String modifiedVariable) {
        String parent = conditionParents.get(canonicalVariable(modifiedVariable));
        if (parent == null) return;
        Map<String, Object> kill = dataflowKill(node, parent,
                "SET_CONDITION_PARENT_KILL", "set_condition_name_parent");
        kill.put("condition_name", canonicalVariable(modifiedVariable));
        kills.put(killKey(kill), kill);
    }

    private List<Map<String, Object>> callUsingKills(SerialisableCFGFlowNode node) {
        Object usingParameters = node.getMetadata().get("using_parameters");
        if (!(usingParameters instanceof List<?> parameterList)) return callUsingFallbackKills(node);
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (Object parameter : parameterList) {
            if (!(parameter instanceof Map<?, ?> rawParameter)) continue;
            Map<String, Object> usingParameter = stringKeyMap(rawParameter);
            Object name = usingParameter.get("name");
            Object mode = usingParameter.get("mode");
            if (!(name instanceof String variableName)) continue;
            String parameterMode = mode instanceof String modeName
                    ? modeName.toUpperCase(Locale.ROOT) : "REFERENCE";
            if (!"REFERENCE".equals(parameterMode)) continue;
            Map<String, Object> kill = dataflowKill(node, variableName,
                    "CALL_USING_REFERENCE_KILL", "call_using_reference");
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private List<Map<String, Object>> callUsingFallbackKills(SerialisableCFGFlowNode node) {
        if (node.getOriginalText() == null) return List.of();
        String upper = node.getOriginalText().toUpperCase(Locale.ROOT);
        int usingIndex = upper.indexOf(" USING ");
        if (usingIndex < 0) return List.of();
        String usingText = upper.substring(usingIndex + " USING ".length())
                .replace(".", " ")
                .replace(",", " ");
        int endCallIndex = usingText.indexOf(" END-CALL");
        if (endCallIndex >= 0) usingText = usingText.substring(0, endCallIndex);

        Map<String, Map<String, Object>> kills = new TreeMap<>();
        String mode = "REFERENCE";
        for (String token : usingText.split("\\s+")) {
            if (token.isBlank() || "BY".equals(token)) continue;
            if ("REFERENCE".equals(token) || "CONTENT".equals(token) || "VALUE".equals(token)) {
                mode = token;
                continue;
            }
            if (isCallUsingNoise(token) || isQuotedLiteral(token) || "CONTENT".equals(mode) || "VALUE".equals(mode)) {
                continue;
            }
            Map<String, Object> kill = dataflowKill(node, token,
                    "CALL_USING_REFERENCE_KILL", "call_using_reference_fallback");
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private boolean isCallUsingNoise(String token) {
        return "ADDRESS".equals(token) || "OF".equals(token) || "LENGTH".equals(token)
                || "OMITTED".equals(token) || "NULL".equals(token);
    }

    private List<Map<String, Object>> dialectOutputKills(SerialisableCFGFlowNode node) {
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (Map<String, Object> kill : cicsOutputKills(node)) kills.put(killKey(kill), kill);
        for (Map<String, Object> kill : sqlOutputKills(node)) kills.put(killKey(kill), kill);
        return new ArrayList<>(kills.values());
    }

    private List<Map<String, Object>> cicsOutputKills(SerialisableCFGFlowNode node) {
        Object cicsArguments = node.getMetadata().get("cics_arguments");
        if (!(cicsArguments instanceof List<?> argumentList)) return List.of();
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (Object argument : argumentList) {
            if (!(argument instanceof Map<?, ?> rawArgument)) continue;
            Map<String, Object> cicsArgument = stringKeyMap(rawArgument);
            Object name = cicsArgument.get("name");
            Object value = cicsArgument.get("value");
            if (!(name instanceof String argumentName) || !(value instanceof String variableName)) continue;
            if (!CICS_OUTPUT_ARGUMENTS.contains(argumentName.toUpperCase(Locale.ROOT))) continue;
            Map<String, Object> kill = dataflowKill(node, variableName, "CICS_OUTPUT_KILL", "cics_output_argument");
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private List<Map<String, Object>> sqlOutputKills(SerialisableCFGFlowNode node) {
        Object operation = node.getMetadata().get("sql_operation");
        if (!(operation instanceof String sqlOperation)) return List.of();
        if (node.getOriginalText() == null
                || !node.getOriginalText().toUpperCase(Locale.ROOT).contains(" INTO ")) return List.of();
        String upper = node.getOriginalText().toUpperCase(Locale.ROOT);
        boolean knownOutputForm = Set.of("SELECT", "FETCH").contains(sqlOperation.toUpperCase(Locale.ROOT))
                || upper.contains(" RETURNING ");
        if (!knownOutputForm) return List.of();

        Object hostVariables = node.getMetadata().get("host_variables");
        if (!(hostVariables instanceof List<?> hostVariableList)) return List.of();
        Map<String, Map<String, Object>> kills = new TreeMap<>();
        for (Object hostVariable : hostVariableList) {
            if (!(hostVariable instanceof String variableName)) continue;
            Map<String, Object> kill = dataflowKill(node, variableName, "SQL_OUTPUT_KILL", "sql_output_host_variable");
            kills.put(killKey(kill), kill);
        }
        return new ArrayList<>(kills.values());
    }

    private List<Map<String, Object>> targetKills(SerialisableCFGFlowNode node, String code, String reason) {
        return sortedStrings(node.getVariablesModified()).stream()
                .map(variable -> dataflowKill(node, variable, code, reason))
                .toList();
    }

    private Map<String, Object> dataflowKill(SerialisableCFGFlowNode node, String variable, String code,
                                             String reason) {
        Map<String, Object> kill = new LinkedHashMap<>();
        kill.put("code", code);
        kill.put("variable", canonicalVariable(variable));
        kill.put("reason", reason);
        kill.put("kill_scope", "direct_variable");
        kill.put("confidence", "conservative");
        kill.put("statement_type", node.getType().name());
        putIfPresent(kill, "statement_text", node.getOriginalText());
        putIfPresent(kill, "source_line", node.getSourceLine());
        putIfPresent(kill, "source_column", node.getSourceColumn());
        kill.put("provenance_source", SUMMARY_SOURCE);
        return kill;
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
        return kill.get("variable") + "\u0000" + kill.get("code") + "\u0000" + kill.get("alias_set_id")
                + "\u0000" + kill.get("written_variable");
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

    private static String canonicalVariable(String variable) {
        if (variable == null) return "";
        String canonical = variable.trim().toUpperCase(Locale.ROOT);
        int subscriptStart = canonical.indexOf('(');
        return subscriptStart < 0 ? canonical : canonical.substring(0, subscriptStart);
    }

    private Map<String, Integer> alphanumericLengths(CobolDataStructure dataStructures) {
        Map<String, Integer> lengths = new TreeMap<>();
        for (DataItem item : flattenedDataItems(dataStructures)) {
            if (item.alphanumericLength() == null) continue;
            lengths.put(canonicalVariable(item.name()), item.alphanumericLength());
        }
        return lengths;
    }

    private Map<String, NumericPicture> numericPictures(CobolDataStructure dataStructures) {
        Map<String, NumericPicture> pictures = new TreeMap<>();
        for (DataItem item : flattenedDataItems(dataStructures)) {
            if (item.numericPicture() == null) continue;
            pictures.put(canonicalVariable(item.name()), item.numericPicture());
        }
        return pictures;
    }

    private Set<String> fileDescriptorVariables(CobolDataStructure dataStructures) {
        if (dataStructures == null) return Set.of();
        Set<String> variables = new TreeSet<>();
        dataStructures.accept((data, parent, root) -> {
            if (data.getSourceSection() == SourceSection.FILE_DESCRIPTOR) {
                variables.add(canonicalVariable(data.name()));
            }
            return data;
        }, null, ignored -> false, dataStructures);
        variables.remove("");
        return variables;
    }

    private Map<String, String> conditionParents(CobolDataStructure dataStructures) {
        if (dataStructures == null) return Map.of();
        Map<String, String> parents = new TreeMap<>();
        dataStructures.accept((data, parent, root) -> {
            if (data instanceof ConditionalDataStructure && parent != null) {
                parents.put(canonicalVariable(data.name()), canonicalVariable(parent.name()));
            }
            return data;
        }, null, ignored -> false, dataStructures);
        return parents;
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
                alphanumericLength(data),
                numericPicture(data),
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

    private Integer alphanumericLength(CobolDataStructure data) {
        if (!(data instanceof Format1DataStructure format1)) return null;
        if (format1.getDataDescription() == null || format1.getDataDescription().dataPictureClause().isEmpty()) {
            return null;
        }
        String picture = format1.getDataDescription().dataPictureClause().getFirst()
                .pictureString().getFirst().getText();
        return alphanumericPictureLength(picture);
    }

    private Integer alphanumericPictureLength(String picture) {
        if (picture == null || picture.isBlank()) return null;
        Matcher matcher = PICTURE_X_RUN.matcher(picture.toUpperCase(Locale.ROOT).replace(" ", ""));
        int length = 0;
        while (matcher.find()) {
            String repeated = matcher.group(1);
            length += repeated == null ? 1 : Integer.parseInt(repeated);
        }
        return length == 0 ? null : length;
    }

    private NumericPicture numericPicture(CobolDataStructure data) {
        if (!(data instanceof Format1DataStructure format1)) return null;
        if (format1.getDataDescription() == null || format1.getDataDescription().dataPictureClause().isEmpty()) {
            return null;
        }
        String picture = format1.getDataDescription().dataPictureClause().getFirst()
                .pictureString().getFirst().getText();
        return numericPicture(picture);
    }

    private NumericPicture numericPicture(String picture) {
        if (picture == null || picture.isBlank()) return null;
        String normalized = picture.toUpperCase(Locale.ROOT).replace(" ", "");
        Matcher matcher = PICTURE_NUMERIC_TOKEN.matcher(normalized);
        int position = 0;
        int integerDigits = 0;
        int fractionalDigits = 0;
        boolean signed = false;
        boolean afterDecimal = false;
        boolean sawDigit = false;
        while (matcher.find()) {
            if (matcher.start() != position) return null;
            String token = matcher.group(1).toUpperCase(Locale.ROOT);
            String repeated = matcher.group(2);
            int count = repeated == null ? 1 : Integer.parseInt(repeated);
            switch (token) {
                case "S" -> {
                    if (repeated != null || signed || sawDigit || afterDecimal) return null;
                    signed = true;
                }
                case "V" -> {
                    if (repeated != null || afterDecimal) return null;
                    afterDecimal = true;
                }
                case "9" -> {
                    sawDigit = true;
                    if (afterDecimal) fractionalDigits += count;
                    else integerDigits += count;
                }
                default -> {
                    return null;
                }
            }
            position = matcher.end();
        }
        if (position != normalized.length() || !sawDigit) return null;
        return new NumericPicture(integerDigits, fractionalDigits, signed);
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

    private Map<String, List<String>> transitiveModifiedVariablesByParagraph(
            Map<String, ParagraphSummary> paragraphSummaries) {
        Map<String, Set<String>> modified = new TreeMap<>();
        Map<String, List<String>> calls = new TreeMap<>();

        for (ParagraphSummary summary : paragraphSummaries.values()) {
            String paragraph = paragraphName(summary.paragraph());
            Set<String> directModified = new TreeSet<>();
            for (String variable : summary.variablesModifiedDirect()) {
                directModified.add(canonicalVariable(variable));
            }
            modified.put(paragraph, directModified);
            calls.put(paragraph, summary.callsParagraphs().stream()
                    .map(this::paragraphName)
                    .filter(target -> !target.isBlank())
                    .sorted()
                    .toList());
        }

        boolean changed;
        do {
            changed = false;
            for (Map.Entry<String, List<String>> entry : calls.entrySet()) {
                Set<String> paragraphModified = modified.get(entry.getKey());
                for (String targetParagraph : entry.getValue()) {
                    Set<String> targetModified = modified.get(targetParagraph);
                    if (targetModified == null) continue;
                    changed |= paragraphModified.addAll(targetModified);
                }
            }
        } while (changed);

        Map<String, List<String>> result = new LinkedHashMap<>();
        for (String paragraph : modified.keySet()) {
            result.put(paragraph, modified.get(paragraph).stream().toList());
        }
        return result;
    }

    private String paragraphName(String paragraph) {
        return paragraph == null ? "" : paragraph.trim().toUpperCase(Locale.ROOT);
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
                            String dataType, Integer occursCount, String occursDependingOn,
                            Integer alphanumericLength, NumericPicture numericPicture,
                            Integer byteOffset, Integer byteSize, Integer sourceLine) {
        private DataItem(String missingName) {
            this(missingName, null, 0, false, "", "UNKNOWN", null, null, null, null, null, null, null);
        }
    }

    private record NumericPicture(int integerDigits, int fractionalDigits, boolean signed) {
        private boolean fits(BigDecimal value) {
            BigDecimal normalized = value.stripTrailingZeros();
            int scale = Math.max(normalized.scale(), 0);
            int digitsBeforeDecimal = Math.max(normalized.precision() - normalized.scale(), 0);
            if (normalized.signum() == 0) digitsBeforeDecimal = 1;
            return scale <= fractionalDigits
                    && digitsBeforeDecimal <= integerDigits
                    && (signed || normalized.signum() >= 0);
        }
    }

    private record PropagationResult(Map<String, DataflowNodeState> nodeStates, int iterationCount,
                                     boolean converged, List<Map<String, Object>> diagnostics) {
    }

}
