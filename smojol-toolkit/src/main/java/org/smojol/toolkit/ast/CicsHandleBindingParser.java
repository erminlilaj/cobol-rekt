package org.smojol.toolkit.ast;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class CicsHandleBindingParser {
    private static final Pattern HANDLE_ABEND_TARGET = Pattern.compile("\\b(LABEL|PROGRAM)\\s*\\(([^)]*)\\)",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern HANDLE_TOKEN = Pattern.compile("\\b([A-Z0-9-]+)\\b\\s*(?:\\(([^)]*)\\))?",
            Pattern.CASE_INSENSITIVE);

    private CicsHandleBindingParser() {
    }

    static List<Map<String, Object>> parse(String originalText) {
        String normalized = originalText.replaceAll("\\s+", " ").trim();
        String upper = normalized.toUpperCase(Locale.ROOT);
        if (!upper.contains("HANDLE")) return List.of();
        if (upper.contains("HANDLE ABEND")) return parseAbend(normalized, upper);
        if (upper.contains("HANDLE CONDITION")) return parseBindings(normalized, upper, "CONDITION");
        if (upper.contains("HANDLE AID")) return parseBindings(normalized, upper, "AID");
        return List.of();
    }

    private static List<Map<String, Object>> parseAbend(String normalized, String upper) {
        List<Map<String, Object>> bindings = new ArrayList<>();
        if (upper.contains(" RESET")) {
            bindings.add(binding("ABEND", "RESET", null, "reset"));
            return bindings;
        }
        if (upper.contains(" CANCEL")) {
            bindings.add(binding("ABEND", "CANCEL", null, "cancel"));
            return bindings;
        }

        Matcher matcher = HANDLE_ABEND_TARGET.matcher(normalized);
        while (matcher.find()) {
            bindings.add(binding("ABEND", matcher.group(1).toUpperCase(Locale.ROOT), matcher.group(2), "set"));
        }
        return bindings;
    }

    private static List<Map<String, Object>> parseBindings(String normalized, String upper, String kind) {
        int start = upper.indexOf("HANDLE " + kind);
        if (start < 0) return List.of();

        String payload = normalized.substring(start + ("HANDLE " + kind).length()).trim();
        int endExecIndex = payload.toUpperCase(Locale.ROOT).indexOf("END-EXEC");
        if (endExecIndex >= 0) payload = payload.substring(0, endExecIndex).trim();

        List<Map<String, Object>> bindings = new ArrayList<>();
        Matcher matcher = HANDLE_TOKEN.matcher(payload);
        while (matcher.find()) {
            String name = matcher.group(1).toUpperCase(Locale.ROOT);
            if (name.equals("EXEC") || name.equals("CICS") || name.equals("HANDLE")
                    || name.equals("CONDITION") || name.equals("AID")) {
                continue;
            }

            String target = matcher.group(2);
            String action = (target == null || target.isBlank()) ? "reset" : "set";
            bindings.add(binding(kind, name, target, action));
        }
        return bindings;
    }

    private static Map<String, Object> binding(String kind, String name, String target, String action) {
        Map<String, Object> binding = new LinkedHashMap<>();
        binding.put("handler_kind", kind);
        binding.put("handled_key", name);
        binding.put("target", target);
        binding.put("action", action);
        return binding;
    }
}
