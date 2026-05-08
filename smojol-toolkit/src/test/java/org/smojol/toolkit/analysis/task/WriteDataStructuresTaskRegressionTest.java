package org.smojol.toolkit.analysis.task;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import org.smojol.toolkit.analysis.pipeline.SerialisableCobolDataStructure;
import com.mojo.algorithms.task.AnalysisTaskResult;
import com.mojo.algorithms.task.AnalysisTaskResultOK;
import com.mojo.algorithms.task.CommandLineAnalysisTask;
import org.smojol.toolkit.interpreter.structure.DefaultFormat1DataStructureBuilder;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WriteDataStructuresTaskRegressionTest {
    @Test
    void canCreateDataStructures() throws IOException {
        AnalysisTaskResult taskResult = new TestTaskRunner("no-branches.cbl", "test-code/flow-ast")
                .runTask(CommandLineAnalysisTask.WRITE_DATA_STRUCTURES);
        assertTrue(taskResult.isSuccess());
        SerialisableCobolDataStructure root = ((AnalysisTaskResultOK) taskResult).getDetail();
    }

    @Test
    void exportsStructuredFieldDetailsForRagChunks() throws IOException {
        AnalysisTaskResult taskResult = new TestTaskRunner("data-export-features.cbl", "test-code/flow-ast")
                .runTask2(CommandLineAnalysisTask.WRITE_DATA_STRUCTURES, new DefaultFormat1DataStructureBuilder());
        assertTrue(taskResult.isSuccess());

        SerialisableCobolDataStructure root = ((AnalysisTaskResultOK) taskResult).getDetail();
        JsonObject rootJson = new Gson().toJsonTree(root).getAsJsonObject();
        JsonObject customerId = findByName(rootJson, "CUSTOMER-ID");
        JsonObject itemTable = findByName(rootJson, "ITEM-TABLE");

        assertNotNull(customerId);
        assertEquals("9(5)", customerId.get("pictureClause").getAsString());
        assertEquals("COMP-3", customerId.get("usage").getAsString());
        assertEquals(5, customerId.get("byteSize").getAsInt());
        assertTrue(customerId.has("byteOffset"));
        assertTrue(customerId.has("sourceLine"));
        assertEquals("12345", customerId.getAsJsonArray("valueLiterals").get(0).getAsString());
        JsonObject declarationFact = customerId.getAsJsonArray("declarationFacts").get(0).getAsJsonObject();
        assertEquals("CUSTOMER-ID", declarationFact.get("target_variable").getAsString());
        assertEquals("12345", declarationFact.get("source_value").getAsString());
        assertEquals("java_data_value_clause", declarationFact.get("provenance_source").getAsString());

        assertNotNull(itemTable);
        assertEquals(3, itemTable.get("occursCount").getAsInt());
        assertEquals("ITEM-COUNT", itemTable.get("occursDependingOn").getAsString());
    }

    @Test
    void exportsCopybookOriginFromOriginalSourceMapping() throws IOException {
        AnalysisTaskResult taskResult = new TestTaskRunner("copybook-owner.cbl", "test-code/flow-ast")
                .runTask2(CommandLineAnalysisTask.WRITE_DATA_STRUCTURES, new DefaultFormat1DataStructureBuilder());
        assertTrue(taskResult.isSuccess());

        SerialisableCobolDataStructure root = ((AnalysisTaskResultOK) taskResult).getDetail();
        JsonObject rootJson = new Gson().toJsonTree(root).getAsJsonObject();
        JsonObject localField = findByName(rootJson, "LOCAL-FIELD");
        JsonObject copyField = findByName(rootJson, "COPY-FIELD");

        assertNotNull(localField);
        assertNotNull(copyField);
        assertTrue(localField.has("originalSourceUri"));
        assertTrue(copyField.has("originalSourceUri"));
        assertTrue(copyField.get("originalSourceUri").getAsString().endsWith("OWNCPY.cpy"));
        assertEquals("OWNCPY", copyField.get("copybookOrigin").getAsString());
        assertTrue(copyField.getAsJsonArray("declarationFacts").get(0).getAsJsonObject().has("copybook_origin"));
        assertTrue(!localField.has("copybookOrigin"));
    }

    private static JsonObject findByName(JsonObject node, String name) {
        if (node.has("name") && name.equals(node.get("name").getAsString())) return node;
        if (!node.has("children")) return null;
        JsonArray children = node.getAsJsonArray("children");
        for (int i = 0; i < children.size(); i++) {
            JsonObject result = findByName(children.get(i).getAsJsonObject(), name);
            if (result != null) return result;
        }
        return null;
    }
}
