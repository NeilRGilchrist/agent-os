---
id: IDEA-0056
title: Decision-rights gates and breaking-revision cascade generator (WS4+H5)
status: parked
tags:
- template
- gate
- deploy-gate
- indexer
- decision-rights
- versioning
- impact-analysis
- dispatch
size: L
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0056: Decision-rights gates and breaking-revision cascade generator (WS4+H5)

## Description

Extend the spec-graph validator and deploy gate: every DEC has tier, rationale, and authorised_by or invokes_exception; every DEC links to a GOAL; every in-scope FR has a TR and every TR resolves to DECs; ratifying-tier DECs cannot be ratified without a record; 'satisfies GOAL-x via ADR-y' is valid traceability. Versioning integrity (revisions resolve to DECs whose revises points back; version == len(revisions)+1; last_breaking_revision matches the newest breaking DEC). Supersession symmetry, and no live implementers on superseded objects without a migration-window DEC. Undeclared-overlap check on new FRs (serves_roles x use_case x data elements) requiring extends or depends_on. Breaking cascade (H5): a breaking DEC must be accompanied by work items for every artifact citing the revised object; the hub enumerates them from H3 citations and emits them into the backlog, and the gate fails if any are unaccounted for; stale implementers flagged. Honesty check returns a breaking:false DEC whose diff touches an SC, test, or implemented_by interface. Add a design-doc gate stage to dispatch.py before handoff. Fixtures drawn from the WS0 baseline corpus, which is client material and must stay out of the hub tree.

## Originating context

Project A proposal decision-rights-implementation-plan.md WS4 (phase 3) plus cos-agent-hub-changes.md H5 (wave C), triaged via /cos 2026-09-07. Related: IDEA-0025 graph-computed blast radius is the same shape (impact propagation over a graph) on a different substrate; link, not merge.

## Value hypothesis

Converts the ad-hoc reconciliation PRs seen in ai-hub-poc into planned, traceable work enumerated at decision time, and changes what agents optimise for from literal FR text-matching to classified, justified decisions.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0038 there). Personal-project names generalised.

(none)
