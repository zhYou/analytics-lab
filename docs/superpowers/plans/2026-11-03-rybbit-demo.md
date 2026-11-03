# Rybbit Demo Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement and verify this deployment inline.

**Goal:** Add a working Rybbit instance with synthetic events, native session funnels, retention and user profiles.
**Architecture:** Six namespaced Compose services (proxy, frontend, backend, ClickHouse, PostgreSQL, Redis) extend analytics-lab. An idempotent bootstrap uses authenticated APIs for account/site/funnel setup and seeds only the dedicated synthetic databases.
**Tech Stack:** Rybbit 2.9.2, upstream database image versions, Caddy, Python standard library.
**Spec:** docs/superpowers/specs/2026-11-03-rybbit-design.md

## Global Constraints

- All commands run in /home/zhouyou/my/github/zhYou/analytics-lab; all exposed ports bind 127.0.0.1.
- Existing credentials and source/BI volumes remain intact; use independent Rybbit databases.
- Private artifacts stay ignored; update ACCESS.txt privately and publish source code to the existing authorized repository.
- Preserve native Rybbit metric semantics; distinguish sessions/first-activity cohorts from the BI definitions.

## Review Focus

- Repeat initialization cannot duplicate events, users, sites or funnels.
- Rybbit credentials, site keys and auth secrets do not appear in tracked files.
- Both native APIs and rendered pages show real data, including nonempty funnel/retention/user results.
- All existing BI checks still pass and ports remain loopback-only.
- Lifecycle commands consistently start, stop and verify the new services too.

## Tasks

- [x] Add and run a failing Rybbit health check; extend Compose and start pinned upstream images.
- [x] Bootstrap the account/private site, generate compatible synthetic event records and profiles, and save native funnels; verify API counts and repeated initialization.
- [x] Extend lab.py, ACCESS.txt, README and browser checks. Run all integrations and browser checks, obtain final read-only review, then commit and push.

## Verification record

- Health test observed RED (connection refused) before starting services; current Rybbit health is GREEN.
- Repeated bootstrap and full `lab.py up` preserve site/funnel identities and event counts; existing five BI checks and four Rybbit checks pass.
- Extra-funnel regression: create a valid third native funnel → verifier RED (3 != 2); change validation to require seeded IDs/names as a subset → all four checks GREEN; temporary funnel removed.
- Browser traverses six native analysis pages and then clicks a user from All Time Users list to preserve upstream date state. The fictional hostname's external favicon 404 is recorded separately.
- Read-only review found no Critical issues. Findings about extra funnels and profile navigation were addressed; direct profile refresh/date-state behavior is documented as an upstream limitation.

Final browser run: native sidebar navigation through six analysis pages plus Users→user detail, all seven with zero JS/application HTTP errors and nonempty data. Full updated deployment exited 0; all nine integration checks pass.
