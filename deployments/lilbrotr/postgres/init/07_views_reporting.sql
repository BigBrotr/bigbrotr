/*
 * Brotr - 07_views_reporting.sql
 *
 * Reserved slot for regular reporting views and deployment-specific query
 * abstractions.
 *
 * The built-in deployments intentionally ship no regular reporting views.
 * The final redesign favors narrow current tables, shared analytics tables,
 * and read-core resources over default convenience views. Add a regular view
 * here only when a deployment-specific live relation genuinely earns its
 * bytes and behavior.
 *
 * Dependencies: 02_tables_core.sql, 03_tables_current.sql, 04_tables_analytics.sql
 */

-- No regular reporting views are defined in the built-in base schema.
