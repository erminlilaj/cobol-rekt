package org.smojol.common.staticanalysis.value;

public enum StaticValueState {
    CONSTANT,
    UNKNOWN,
    NON_CONSTANT,
    UNSUPPORTED,
    UNINITIALIZED
}
