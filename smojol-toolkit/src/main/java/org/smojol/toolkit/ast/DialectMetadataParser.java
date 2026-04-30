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
    private static final Pattern MAP_QUOTED = Pattern.compile("\\bMAP\\s*\\(\\s*['\"]([A-Z0-9-]+)['\"]\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern MAP_UNQUOTED = Pattern.compile("\\bMAP\\s*\\(\\s*(?!['\"])([A-Z][A-Z0-9-]*)\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern QUEUE_QUOTED = Pattern.compile("\\bQUEUE\\s*\\(\\s*['\"]([A-Z0-9-]+)['\"]\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern QUEUE_UNQUOTED = Pattern.compile("\\bQUEUE\\s*\\(\\s*(?!['\"])([A-Z][A-Z0-9-]*)\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern FILE_QUOTED = Pattern.compile("\\b(FILE|DATASET)\\s*\\(\\s*['\"]([A-Z0-9-]+)['\"]\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern FILE_UNQUOTED = Pattern.compile("\\b(FILE|DATASET)\\s*\\(\\s*(?!['\"])([A-Z][A-Z0-9-]*)\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern TRANSID_QUOTED = Pattern.compile("\\bTRANSID\\s*\\(\\s*['\"]([A-Z0-9-]+)['\"]\\s*\\)", Pattern.CASE_INSENSITIVE);
    private static final Pattern TRANSID_UNQUOTED = Pattern.compile("\\bTRANSID\\s*\\(\\s*(?!['\"])([A-Z][A-Z0-9-]*)\\s*\\)", Pattern.CASE_INSENSITIVE);
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
        String command = null;
        if (commandMatcher.find()) {
            command = commandMatcher.group(1).toUpperCase(Locale.ROOT);
            metadata.put("cics_command", command);
        }
        addFirstGroup(metadata, "cics_target_program", PROGRAM_LITERAL.matcher(text));
        addFirstGroup(metadata, "cics_target_variable", PROGRAM_VARIABLE.matcher(text));
        addFirstGroupWithSource(metadata, "cics_map", text, MAP_QUOTED, MAP_UNQUOTED);
        addFirstGroupWithSource(metadata, "cics_queue", text, QUEUE_QUOTED, QUEUE_UNQUOTED);
        addFirstGroupWithSource(metadata, "cics_transid", text, TRANSID_QUOTED, TRANSID_UNQUOTED);
        Matcher fileQuotedMatcher = FILE_QUOTED.matcher(text);
        Matcher fileUnquotedMatcher = FILE_UNQUOTED.matcher(text);
        if (fileQuotedMatcher.find()) {
            metadata.put("cics_file_keyword", fileQuotedMatcher.group(1).toUpperCase(Locale.ROOT));
            metadata.put("cics_file", fileQuotedMatcher.group(2).toUpperCase(Locale.ROOT));
            metadata.put("cics_file_source", "literal");
        } else if (fileUnquotedMatcher.find()) {
            metadata.put("cics_file_keyword", fileUnquotedMatcher.group(1).toUpperCase(Locale.ROOT));
            metadata.put("cics_file", fileUnquotedMatcher.group(2).toUpperCase(Locale.ROOT));
            metadata.put("cics_file_source", "identifier");
        }
        if (command != null) metadata.put("cics_operation_type", classifyOperationType(command));
        resolveTargetKindAndSource(metadata);
        metadata.put("dialect_semantics_status", "metadata_only");
    }

    private static String classifyOperationType(String command) {
        return switch (command) {
            case "LINK", "XCTL", "RETURN" -> "program_transfer";
            case "START" -> "transaction_start";
            case "READ" -> "file_read";
            case "STARTBR", "READNEXT", "READPREV", "ENDBR", "RESETBR" -> "browse";
            case "WRITE", "REWRITE" -> "file_write";
            case "DELETE" -> "file_delete";
            default -> "other";
        };
    }

    private static void resolveTargetKindAndSource(Map<String, Object> metadata) {
        if (metadata.containsKey("cics_target_program")) {
            metadata.put("cics_target_kind", "PROGRAM");
            metadata.put("cics_target", metadata.get("cics_target_program"));
            metadata.put("cics_target_source", "literal");
        } else if (metadata.containsKey("cics_target_variable")) {
            metadata.put("cics_target_kind", "PROGRAM");
            metadata.put("cics_target", metadata.get("cics_target_variable"));
            metadata.put("cics_target_source", "identifier");
        } else if (metadata.containsKey("cics_file")) {
            String keyword = (String) metadata.getOrDefault("cics_file_keyword", "FILE");
            metadata.put("cics_target_kind", keyword);
            metadata.put("cics_target", metadata.get("cics_file"));
            metadata.put("cics_target_source", metadata.getOrDefault("cics_file_source", "literal"));
        } else if (metadata.containsKey("cics_map")) {
            metadata.put("cics_target_kind", "MAP");
            metadata.put("cics_target", metadata.get("cics_map"));
            metadata.put("cics_target_source", metadata.getOrDefault("cics_map_source", "literal"));
        } else if (metadata.containsKey("cics_queue")) {
            metadata.put("cics_target_kind", "QUEUE");
            metadata.put("cics_target", metadata.get("cics_queue"));
            metadata.put("cics_target_source", metadata.getOrDefault("cics_queue_source", "literal"));
        } else if (metadata.containsKey("cics_transid")) {
            metadata.put("cics_target_kind", "TRANSID");
            metadata.put("cics_target", metadata.get("cics_transid"));
            metadata.put("cics_target_source", metadata.getOrDefault("cics_transid_source", "literal"));
        } else {
            metadata.put("cics_target_kind", "UNKNOWN");
            metadata.put("cics_target_source", "unknown");
        }
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

    private static void addFirstGroupWithSource(Map<String, Object> metadata, String key, String text,
            Pattern quotedPattern, Pattern unquotedPattern) {
        Matcher qm = quotedPattern.matcher(text);
        if (qm.find()) {
            metadata.put(key, qm.group(1).toUpperCase(Locale.ROOT));
            metadata.put(key + "_source", "literal");
        } else {
            Matcher um = unquotedPattern.matcher(text);
            if (um.find()) {
                metadata.put(key, um.group(1).toUpperCase(Locale.ROOT));
                metadata.put(key + "_source", "identifier");
            }
        }
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
