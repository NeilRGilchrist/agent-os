---
id: IDEA-0068
title: Stack-aware environment pre-flight in wave
status: promoted
tags:
- dispatch
- preflight
- environment
- windows
- orchestrator
size: S
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: hub-tooling/FR-0011
pattern: null
archive_reason: null
---
# IDEA-0068: Stack-aware environment pre-flight in wave

## Description

wave pre-flight today checks gh and locks only (_gh_preflight). Add a stack-aware host check before any spawn: docker daemon reachable when the project declares docker-compose; uv / node / npx on PATH per pyproject.toml / package.json; Windows app-control policy state (Smart App Control / WDAC) that blocks unsigned .pyd loading; host port collisions against the ports docker-compose publishes. Fail fast with a mechanical classification in the dispatch.wave record rather than letting the phase discover it mid-run. Related: IDEA-0064 (WSL clone) removes the app-control class entirely; archived IDEA-0030 was a different check (gateway) and stays archived.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L8, L11a, L21; _dispatch/audit-downloads-FR-0001-wave.md section 6. Touches template/scripts/dispatch.py (human-approval). Home: hub-tooling, maintainer mode.

## Value hypothesis

In the FR-0001 wave a down Docker daemon cost one spawn, Smart App Control caused a silent driver substitution that cost DEC-0031 + PR #4 + a Reviewer round (~50 min), and a host-port collision cost a test failure and ASM-0017. Each environment fault costs 20-50 min after the fact and seconds before; on a laptop host expect at least one per three waves, so 1.5-3 h across the 12 remaining FRs, each landing in the metrics log as mechanical instead of as a semantic mystery.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0050 there). Personal-project names generalised.

(none)
