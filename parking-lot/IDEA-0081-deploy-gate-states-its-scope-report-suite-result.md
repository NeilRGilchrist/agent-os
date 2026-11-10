---
id: IDEA-0081
title: 'Deploy gate states its scope: report suite results or say it did not run them,
  and fail loudly instead of writing a partial INDEX.md'
status: promoted
tags:
- gate
- deploy-gate
- indexer
- template
- quality-gate
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0021
pattern: null
archive_reason: null
---
# IDEA-0081: Deploy gate states its scope: report suite results or say it did not run them, and fail loudly instead of writing a partial INDEX.md

## Description

deploy-gate.py checks annotations and spec shape, never test results, so 'gate green' does not mean 'suite green': in Project A the maintainer, the Reviewer and the Orchestrator all reported gate green while two knowledge tests failed (L51). Either the PASSED line says so explicitly ('annotations and spec shape only; tests not run'), or --stage full runs the project's suite or a declared fast subset (e.g. Project A's ~5 s provenance test, L50 option b). Second defect in the same area: when index-specs.py exits non-zero (hub-tooling DEC-0001 ratified with the ADR token 'accepted' instead of 'ratified'), the gate rewrote specs/INDEX.md without its ## Decisions table instead of failing, and the missing table looked like a gate/indexer discrepancy for a whole FR round before it was root-caused. The gate should surface the indexer failure, not write a partial INDEX.

## Originating context

Project A L51 and L50(b) (a downstream project's `_dispatch/learnings-FR-0016-FR-0002-wave.md`); hub-tooling _dispatch/learnings-wave1.md FR-0009 section ('template defect candidate': vanishing Decisions table) and FR-0010 section ('DEC vocabulary trap ... root cause'). Touches template/scripts/deploy-gate.py (human approval) and possibly index-specs.py. Home: hub-tooling. Proposed wave 2, lane C, order 1.

## Value hypothesis

Removes a false-confidence class: three roles in one wave declared done on a green gate over a red suite and one CI red reached a PR; AGENTS.md rule 6 ('run the gate before claiming done') is only as honest as the gate's PASSED line.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0063 there). Personal-project names generalised.

(none)
