package org.smojol.common.staticanalysis.value;

import java.util.Map;

public sealed interface StaticValue permits ConstantStaticValue, UnknownStaticValue, NonConstantStaticValue,
        UnsupportedStaticValue, UninitializedStaticValue {
    StaticValueState state();

    StaticValueKind kind();

    Map<String, Object> toJsonMap();
}
