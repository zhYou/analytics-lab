# Local analytics preview implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement and verify this deployment.

**Goal:** Run Superset and Metabase on this host with synthetic ClickHouse, MySQL, and OpenObserve data and ready-to-view dashboards.

**Architecture:** An isolated Docker Compose project owns its databases and persistent volumes. ClickHouse and MySQL connect directly to each BI. A repeatable job reads aggregate results from OpenObserve's search API and loads them into a clearly labelled ClickHouse database for BI access.

**Tech Stack:** Superset 6.1.0, Metabase 0.65.2, ClickHouse 26.6, MySQL 8.0, PostgreSQL 18, OpenObserve, Python standard library.

**Spec:** The user's deployment request and clarification in this conversation: three new independent source instances populated with synthetic data, including MySQL.

## Global constraints

- Use the new analytics-lab repository under ~/my/github/zhYou/; change no tracked Codex configuration or existing workloads. The user explicitly requested a public GitHub repository and migration away from the temporary directory.
- Bind published ports to 127.0.0.1; retain data in project-owned Docker volumes.
- Store generated credentials in a private .env file; never commit them.
- Use the same fixtures and reporting definitions in both BIs.
- Label OpenObserve's API-derived datasets explicitly.

## Review focus

- The two BIs authenticate, render dashboards, and execute every saved query.
- Source counts and aggregate values agree with the generated fixtures.
- OpenObserve data really travels through its search API before reaching BI datasets.
- Reruns preserve application credentials and avoid duplicate demo dashboards or data.
- Services and cleanup commands are scoped to this Compose project.

## Tasks

- [x] 1. Write and run an integration smoke check before starting the services; create isolated Compose configuration and private credentials.
- [x] 2. Start source services, generate deterministic business/event fixtures, and verify ingestion in all three sources.
- [x] 3. Initialize both BIs, add data sources, and create matching business and behavior dashboards.
- [x] 4. Run health, authentication, chart-query, source reconciliation, and network-binding checks; inspect browser rendering where available.
- [x] 5. Record access and lifecycle instructions and leave services running for user review.

Publish deployment code and templates to the user-authorized public repository zhYou/analytics-lab on main. Keep all runtime credentials, generated fixtures and local screenshots private. Verification exercises deployed services directly.

## Verification evidence

- Full `python3 lab.py up` rerun completed successfully; source totals and chart/dashboard IDs remained stable.
- Five integration checks pass, including all 26 BI queries, revenue reconciliation, funnel order and retention bounds.
- Chromium logged in and rendered all four dashboards (8 business + 5 user charts per BI), with zero JavaScript/HTTP errors.
- Credentials are mode 600; private artifacts are ignored and excluded from the Docker build context.
- Fresh read-only review found no Critical/Important issues. Deferred minor: fixed fixture data ages while retention maturity uses the current date; this limitation is documented in README.
- Production hardening, continuous ingestion and recovery from interrupted partial ingestion are outside this local demo's scope; partial mismatched loads stop rather than overwrite existing data.
