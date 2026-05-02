/*
 * Brotr - 06_functions_cleanup.sql
 *
 * No schema-level orphan cleanup functions are defined.
 *
 * The shared storage contract intentionally does not assume that an event must
 * always have an event_observation row or that a document must always have a
 * relay_document row. Storage rows may outlive current junction rows, and any
 * future reclamation policy must be explicit and deployment-specific rather
 * than encoded as a default shared invariant.
 *
 * Dependencies: 02_tables_core.sql
 */
