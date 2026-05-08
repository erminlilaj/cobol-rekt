package org.smojol.common.structure;

/**
 * Records a variable that was skipped during data structure building due to a processing error.
 * @param name The variable name (or "UNKNOWN" if name extraction also failed)
 * @param error The error message describing why it was skipped
 * @param section The source section (WORKING_STORAGE, LINKAGE, FILE_DESCRIPTOR)
 */
public record SkippedVariable(String name, String error, String section) {}
