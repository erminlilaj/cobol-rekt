package org.smojol.common.staticanalysis.value;

import java.util.LinkedHashMap;
import java.util.Map;

public record NonConstantStaticValue(StaticValueKind kind, String reason) implements StaticValue {
    @Override
    public StaticValueState state() {
        return StaticValueState.NON_CONSTANT;
    }

    @Override
    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("state", state().name());
        json.put("kind", kind.name());
        json.put("reason", reason);
        return json;
    }
}
