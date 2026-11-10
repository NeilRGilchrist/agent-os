---
id: IDEA-0035
title: 'Deploy gate: let deferred ACs skip the @covers requirement (template)'
status: parked
tags:
- template
- deploy-gate
- spec-graph
- tooling
- process
size: M
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0035: Deploy gate: let deferred ACs skip the @covers requirement (template)

## Description

deploy-gate.py (template/scripts, identical in projects) requires @covers for every AC of an FR at in-review or merged; it has no notion of a deferred AC. Projects tag deferral in AC text (e.g. [P2]), which the template must not key on. Proposal: a structured deferral marker (e.g. an ac_state state 'deferred' with a required pointer to the follow-up FR/IDEA), so the gate skips coverage for it, index-specs lists open deferrals, and deferred work cannot be silently lost. Touches protected template files (deploy-gate.py, index-specs.py, FR template): needs human approval. Consider designing with the spec-revision-provenance idea if parked. Related: IDEA-0034.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0001 could not flip to merged until its [P2] AC-9 test was backfilled; FR-0002 (AC-11, AC-14), FR-0004 (AC-12), FR-0005 (AC-11) will hit the same wall.

## Value hypothesis

Stops every FR with a deliberately deferred AC from failing the gate at merge, without hand-written placeholder tests or spec surgery; fix once in template, propagate via bootstrap --upgrade.

## Notes

- 2026-10-22, second instance. It covers **withdrawn** ACs too, not just deferred ones: ai-productivity-toolkit FR-0005 could not record the human-approved withdrawal of AC-9/10/11 (superseded by FR-0011). Check 2 fails any `@covers` that points at an AC no longer detected by `AC_HEADING_PATTERN`. Check 3 fails an uncovered live AC once the FR is `merged`. No spec format satisfies both without editing tests or the gate. Interim workaround (human option B): delete the superseded tests, then strike the ACs through. Design requirement surfaced: a withdrawn/deferred AC marker must be (a) skipped by check 3 and (b) still a valid `@covers` target for check 2, so history-bearing tests aren't forced out. Human chose to keep this parked for now (likely pairs with IDEA-0041; both touch the FR template).
