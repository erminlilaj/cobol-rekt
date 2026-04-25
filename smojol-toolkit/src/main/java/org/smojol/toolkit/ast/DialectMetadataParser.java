package org.smojol.toolkit.ast;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class DialectMetadataParser {
    private static final Pattern CICS_COMMAND = Pattern.compile("\\bEXEC\\s+CICS\\s+([A-Z0-9-]+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern PROGRAM_LITERAL = Pattern.compile("\\bPROGRAM\\s*\\(\\s*['\"]([^'\"]+)['\"]\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern PROGRAM_VARIABLE = Pattern.compile("\\bPROGRAM\\s*\\(\\s*(?!['\"])([A-Z][A-Z0-9-]*)\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern MAP_LITERAL = Pattern.compile("\\bMAP\\s*\\(\\s*['\"]?([A-Z0-9-]+)['\"]?\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern QUEUE_LITERAL = Pattern.compile("\\bQUEUE\\s*\\(\\s*['\"]?([A-Z0-9-]+)['\"]?\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern FILE_LITERAL = Pattern.compile("\\b(FILE|DATASET)\\s*\\(\\s*['\"]?([A-Z0-9-]+)['\"]?\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern SQL_OPERATION = Pattern.compile("\\b(SELECT|INSERT|UPDATE|DELETE|DECLARE|OPEN|FETCH|CLOSE|PREPARE|EXECUTE|CALL|MERGE|CREATE|DROP|ALTER)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern SQL_TABLE = Pattern.compile("\\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\\s+([A-Z][A-Z0-9_.$-]*)", Pattern.CASE_INSENSITIVE);
    private static final Pattern SQL_CURSOR = Pattern.compile("\\bCURSOR\\s+([A-Z][A-Z0-9_-]*)|\\b(?:OPEN|FETCH|CLOSE)\\s+([A-Z][A-Z0-9_-]*)", Pattern.CASE_INSENSITIVE);
    private static final Pattern HOST_VARIABLE = Pattern.compile(":([A-Z][A-Z0-9_-]*)", Pattern.CASE_INSENSITIVE);

    public static Map<String, Object> parse(String text) {
        String normalized = normalize(text);
        Map<String, Object> metadata = new LinkedHashMap<>();
        if (normalized.contains("EXEC CICS")) {
            parseCics(normalized, metadata);
        } else if (normalized.contains("EXEC SQL")) {
            parseSql(normalized, metadata);
        } else {
            parseOtherDialect(normalized, metadata);
        }
        return metadata;
    }

    private static void parseCics(String text, Map<String, Object> metadata) {
        metadata.put("dialect_family", "CICS");
        Matcher commandMatcher = CICS_COMMAND.matcher(text);
        if (commandMatcher.find()) metadata.put("cics_command", commandMatcher.group(1).toUpperCase(Locale.ROOT));
        addFirstGroup(metadata, "cics_target_program", PROGRAM_LITERAL.matcher(text));
        addFirstGroup(metadata, "cics_target_variable", PROGRAM_VARIABLE.matcher(text));
        addFirstGroup(metadata, "cics_map", MAP_LITERAL.matcher(text));
        addFirstGroup(metadata, "cics_queue", QUEUE_LITERAL.matcher(text));
        Matcher fileMatcher = FILE_LITERAL.matcher(text);
        if (fileMatcher.find()) metadata.put("cics_file", fileMatcher.group(2).toUpperCase(Locale.ROOT));
        metadata.put("dialect_semantics_status", "metadata_only");
    }

    private static void parseSql(String text, Map<String, Object> metadata) {
        metadata.put("dialect_family", "DB2_SQL");
        Matcher operationMatcher = SQL_OPERATION.matcher(text);
        if (operationMatcher.find()) metadata.put("sql_operation", operationMatcher.group(1).toUpperCase(Locale.ROOT));
        else metadata.put("sql_operation", "UNKNOWN");
        metadata.put("tables", allMatches(SQL_TABLE.matcher(text)));
        metadata.put("host_variables", allMatches(HOST_VARIABLE.matcher(text)));
        List<String> cursors = allCursorMatches(SQL_CURSOR.matcher(text));
        if (!cursors.isEmpty()) metadata.put("cursor_names", cursors);
        metadata.put("dynamic_sql", text.contains("PREPARE") || text.contains("EXECUTE IMMEDIATE"));
        metadata.put("dialect_semantics_status", "metadata_only");
    }

    private static void parseOtherDialect(String text, Map<String, Object> metadata) {
        if (text.contains("EXEC DLI") || text.contains("IMS")) metadata.put("dialect_family", "IMS");
        else if (text.contains("MQ")) metadata.put("dialect_family", "MQ");
        else if (text.contains("MAP ") || text.contains("BMS")) metadata.put("dialect_family", "BMS_OR_IDMS");
        else metadata.put("dialect_family", "UNKNOWN");
        metadata.put("dialect_semantics_status", "raw_text_preserved_only");
    }

    private static void addFirstGroup(Map<String, Object> metadata, String key, Matcher matcher) {
        if (matcher.find()) metadata.put(key, matcher.group(1).toUpperCase(Locale.ROOT));
    }

    private static List<String> allMatches(Matcher matcher) {
        List<String> matches = new ArrayList<>();
        while (matcher.find()) {
            matches.add(matcher.group(1).toUpperCase(Locale.ROOT));
        }
        return matches.stream().distinct().toList();
    }

    private static List<String> allCursorMatches(Matcher matcher) {
        List<String> matches = new ArrayList<>();
        while (matcher.find()) {
            String value = matcher.group(1) != null ? matcher.group(1) : matcher.group(2);
            if (value != null) matches.add(value.toUpperCase(Locale.ROOT));
        }
        return matches.stream().distinct().toList();
    }

    private static String normalize(String text) {
        return text == null ? "" : text.replaceAll("\\s+", " ").trim().toUpperCase(Locale.ROOT);
    }
}
