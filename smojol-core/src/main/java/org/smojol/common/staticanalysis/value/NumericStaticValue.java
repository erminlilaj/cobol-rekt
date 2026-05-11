package org.smojol.common.staticanalysis.value;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;

public record NumericStaticValue(String decimal, int scale, int precision, String sign) {
    public static NumericStaticValue from(BigDecimal value) {
        BigDecimal normalized = value.stripTrailingZeros();
        if (normalized.scale() < 0) {
            normalized = normalized.setScale(0);
        }
        return new NumericStaticValue(
                normalized.toPlainString(),
                normalized.scale(),
                normalized.precision(),
                signOf(normalized)
        );
    }

    public Map<String, Object> toJsonMap() {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("decimal", decimal);
        json.put("scale", scale);
        json.put("precision", precision);
        json.put("sign", sign);
        return json;
    }

    private static String signOf(BigDecimal value) {
        int signum = value.signum();
        if (signum < 0) return "NEGATIVE";
        if (signum > 0) return "POSITIVE";
        return "ZERO";
    }
}
