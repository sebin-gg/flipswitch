# ADR-0001: Selection of PostgreSQL & TimescaleDB for Telemetry Pipeline

* **Status:** Accepted
* **Deciders:** Engineering Team (via Switch Room)
* **Date:** 2026-11-07

## Context and Problem Statement
Team needs to select primary operational database for ingesting telemetry, metrics, and trace spans from edge gateways. Evaluated PostgreSQL vs ClickHouse vs MongoDB.

## Decision Outcome
Chosen option: **Adopt PostgreSQL with TimescaleDB extension. Provides ACID transactions, mature SQL tooling, automated time-series hypertable chunking, and continuous aggregations.**

### Positive Consequences
* Good, because Familiar SQL syntax with zero new language onboarding required for engineers
* Good, because Built-in hypertable chunking maintains sub-50ms query latencies under sustained write load
* Good, because Direct compatibility with Grafana, Metabase, and existing BI dashboards

### Negative Consequences / Trade-offs
* Bad, because Requires dedicated vacuum tuning and autovacuum monitoring for write-heavy tables
* Bad, because Higher disk footprint compared to ClickHouse columnar compression

## Pros and Cons of the Options
### Considered Alternatives
* ClickHouse: superior compression but team has zero operational experience
* MongoDB: flexible schema but lacked robust analytical time-bucket aggregations

## Rollback & Failure Strategy
Maintain parallel streaming ingest into Amazon Aurora read-replicas during migration; if Timescale hypertable chunking exceeds 85% disk I/O, switch read traffic back to Aurora via Route53 DNS weighted routing within 5 minutes.

---
*Generated collaboratively by Switch ADR Architect Agent.*
