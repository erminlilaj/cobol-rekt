package org.smojol.common.staticanalysis.value;

import java.util.LinkedHashMap;
import java.util.Map;

public record FigurativeStaticValue(String name, String normalizedName) {
    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("name", name);
        json.put("normalized_name", normalizedName);
        return json;
    }
}
