package org.smojol.common.ast;

import org.smojol.common.vm.expression.CobolExpression;
import org.smojol.common.vm.expression.VariableExpression;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.function.Function;

public final class VariableUsageCollector {
    private VariableUsageCollector() {
    }

    public static List<String> variableNamesIn(CobolExpression expression) {
        if (expression == null) return List.of();
        Set<String> names = new LinkedHashSet<>();
        collect(expression, names);
        return List.copyOf(names);
    }

    public static List<String> variableNamesIn(Collection<CobolExpression> expressions) {
        if (expressions == null || expressions.isEmpty()) return List.of();
        Set<String> names = new LinkedHashSet<>();
        expressions.forEach(expression -> names.addAll(variableNamesIn(expression)));
        return List.copyOf(names);
    }

    public static List<String> merge(Collection<FlowNode> nodes,
                                     Function<VariableUsageProvider, List<String>> accessor) {
        if (nodes == null || nodes.isEmpty()) return List.of();
        Set<String> names = new LinkedHashSet<>();
        for (FlowNode node : nodes) {
            if (node instanceof VariableUsageProvider provider) {
                List<String> values = accessor.apply(provider);
                if (values != null) values.forEach(value -> addNormalised(names, value));
            }
        }
        return List.copyOf(names);
    }

    public static List<String> combine(Collection<String> first, Collection<String> second) {
        List<String> merged = new ArrayList<>();
        if (first != null) merged.addAll(first);
        if (second != null) merged.addAll(second);
        return distinct(merged);
    }

    public static List<String> distinct(Collection<String> names) {
        if (names == null || names.isEmpty()) return List.of();
        Set<String> result = new LinkedHashSet<>();
        names.forEach(name -> addNormalised(result, name));
        return List.copyOf(result);
    }

    private static void addNormalised(Set<String> names, String name) {
        if (name == null || name.isBlank()) return;
        names.add(name.trim().toUpperCase(Locale.ROOT));
    }

    private static void collect(CobolExpression expression, Set<String> names) {
        if (expression instanceof VariableExpression variableExpression) {
            addNormalised(names, variableExpression.getName());
        }
        expression.getChildren().forEach(child -> collect(child, names));
    }
}
