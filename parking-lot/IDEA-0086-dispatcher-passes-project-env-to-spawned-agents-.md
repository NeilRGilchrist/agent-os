---
id: IDEA-0086
title: Dispatcher passes project env to spawned agents; the port pre-flight reads
  .env
status: parked
tags:
- dispatch
- environment
- preflight
- template
- developer-experience
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0086: Dispatcher passes project env to spawned agents; the port pre-flight reads .env

## Description

The dispatcher does not carry the project's DB connection environment into spawned agents: Project A exports DATABASE_URL, TEST_DATABASE_URL, POSTGRES_PORT and DB_PORT on the wave/tick/maintain process by hand every session so agents inherit them (L53). Offer a documented --env-file / .env.dispatch, or read the project .env - never committing it and never echoing values into logs, metrics or briefs. Related gap: FR-0011's port pre-flight does not read .env, so a project that remaps its Postgres port there (Project A: 15432) is probed on the default port.

## Originating context

Project A L53 (a downstream project's `_dispatch/learnings-FR-0016-FR-0002-wave.md`); Project A HANDOFF-next-session-2026-09-21 section 4 and HANDOFF 2026-09-25 section 4 (still manual); hub-tooling handoff-hub-upgrade-2026-09-21-b ('.env not read by the port pre-flight'). Related: IDEA-0068 / FR-0011 (environment pre-flight). Touches template/scripts/dispatch.py and env_preflight.py (maintainer mode). Home: hub-tooling. Proposed wave 3.

## Value hypothesis

Removes a per-session manual step every Project A DB FR depends on (forgetting it costs a dropped phase) and makes the pre-flight probe the port the project actually uses.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0068 there). Personal-project names generalised.

(none)
