---
id: IDEA-0054
title: 'Code and tests cite spec: backward traceability + success criteria as the
  binding contract (H3+H4)'
status: parked
tags:
- template
- traceability
- gate
- testing
- indexer
- decision-rights
size: L
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0054: Code and tests cite spec: backward traceability + success criteria as the binding contract (H3+H4)

## Description

H3: every component, endpoint, migration, and test carries a header or manifest entry citing the TR stable ID it implements and the TR version it was built against; TR implemented_by is derived from these citations, not hand-maintained. The orphan gate runs both directions (spec object with no implementer past build phase; artifact citing no spec object or a superseded one) and flags stale implementers where built_against < last_breaking_revision. H4: every success criterion is realised as at least one acceptance test citing the SC ID; test generation is a gated agent task keyed off the SC; SCs are outcome-level and the FR solution_space gate rejects SCs that encode implementation. Tests-changed-per-FR-change becomes a tracked rigidity metric (H6). Depends on WS1d TR object and H2.

## Originating context

Project A proposal cos-agent-hub-changes.md sections H3 and H4 (wave B), triaged via /cos 2026-09-07. Seed in template: per-AC ratification state and drift lint in index-specs.py.

## Value hypothesis

Closes spec-vs-code drift (generation from one source only closes docs-vs-spec drift) and makes tests, not TR prose, the thing that binds code to spec, with rigidity measured rather than feared.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0036 there). Personal-project names generalised.

(none)
