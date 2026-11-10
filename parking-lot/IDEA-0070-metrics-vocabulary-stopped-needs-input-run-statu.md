---
id: IDEA-0070
title: 'Metrics vocabulary: stopped-needs-input run status and kb.mint kind (revises
  FR-0002)'
status: parked
tags:
- metrics
- observability
- dispatch
- decision-rights
- template
size: S
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0070: Metrics vocabulary: stopped-needs-input run status and kb.mint kind (revises FR-0002)

## Description

Two additions to the closed vocabularies in template/scripts/metrics_log.py and the dispatch.run emitter: (1) _evaluate_agent_outcome classifies a run that ended with end_turn, no ESCALATION block and no handoff artifact (PR_BODY.md for dev/mnt/bkf, a verdict heading for rev) as status stopped-needs-input rather than success, so wave can retry with a headless brief automatically; (2) a kb.mint record kind (object_ids, register, source_class, role, model) emitted when an agent mints an ASM/OQ/glossary/TR row, so ADR-0003's role/model provenance tags are countable from the log without scanning registers. Free-text fields stay banned.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L28, L43. Revises hub-tooling FR-0002 (KINDS closed by design, AC-3 status vocabulary) via a DEC. Home: hub-tooling, maintainer mode.

## Value hypothesis

Dev attempt 1 in the FR-0001 wave was logged success with zero work delivered, so the dispatcher success rate reads 100% against an actual 0% for that phase kind; every dashboard on the log (IDEA-0057, IDEA-0016 baselines) is wrong by the headless-stop fraction, 1 in 3 spawns here, and each miss costs 5-10 min of human diagnosis noticing PR_BODY.md is absent. kb.mint turns 'agent KB contribution rate' into a one-line query.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0052 there). Personal-project names generalised.

(none)
