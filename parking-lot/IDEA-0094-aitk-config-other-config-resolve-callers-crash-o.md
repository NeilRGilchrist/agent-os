---
id: IDEA-0094
title: 'aitk config: other config.resolve() callers crash on malformed aitk.yaml'
status: parked
tags:
- ai-productivity-toolkit
- config
- bug
- fail-closed
size: S
created: '2026-10-26'
updated: '2026-10-26'
last_reviewed: '2026-10-26'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0094: aitk config: other config.resolve() callers crash on malformed aitk.yaml

## Description

config show, route and scrub call FR-0009's config.resolve(), whose yaml.safe_load is unguarded and warn-only, so a malformed or undecodable aitk.yaml gives a traceback and exit 1. Fix once, centrally: a follow-up FR against FR-0009 adds a guarded resolve (any YAML load/construct exception -> fixed message, exit 2), plus the PolicyError caller contract parked alongside it.

## Originating context

aitk FR-0010 Reviewer round-2 observation O8; same failure class as FR-0002 D11 and FR-0010 D1/D4. Queued 2026-10-23 during the hub parking pause.

## Value hypothesis

Gives every aitk command the same exit-2, no-traceback behaviour on a broken aitk.yaml that FR-0010's policy show now has.

## Notes

- 2026-10-26, FR-0010 round-3 Reviewer observation O10: FR-0010's fix (merged `51c2969`) wraps `config.resolve()` in `policy show` with `except Exception`, so a genuine bug *inside* `config.resolve()` would also be reported as "cannot read aitk.yaml" (still exit 2, fails closed). The central fix here should give `config` a typed load error (e.g. `ConfigLoadError` raised only from the YAML load/construct call), so callers catch that instead of `Exception`. Same failure class as FR-0002 D11 and FR-0010 D1/D4.
