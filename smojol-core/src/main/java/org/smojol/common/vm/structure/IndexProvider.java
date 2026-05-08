package org.smojol.common.vm.structure;

import java.util.List;
import java.util.logging.Logger;

public class IndexProvider {
    private static final Logger LOGGER = Logger.getLogger(IndexProvider.class.getName());
    private final List<Integer> indices;
    private int counter;

    public IndexProvider(List<Integer> indices) {
        this.counter = 0;
        this.indices = indices;
    }

    public int next() {
        if (counter >= indices.size()) {
            LOGGER.warning("IndexProvider: counter (" + counter + ") exceeds indices size (" + indices.size() + "), defaulting to index 1");
            counter++;
            return 1;
        }
        Integer nextIndex = indices.get(counter);
        counter++;
        return nextIndex;
    }

}
