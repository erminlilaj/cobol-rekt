package org.smojol.common.staticanalysis.value;

import java.util.LinkedHashMap;
import java.util.Map;

public record TypeContext(String picture, String usage, String category) {
    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("picture", picture);
        json.put("usage", usage);
        json.put("category", category);
        return json;
    }
}
