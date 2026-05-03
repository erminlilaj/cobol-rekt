package org.smojol.common.ast;

import java.util.List;

public interface VariableUsageProvider {
    List<String> variablesRead();
    List<String> variablesModified();
}
