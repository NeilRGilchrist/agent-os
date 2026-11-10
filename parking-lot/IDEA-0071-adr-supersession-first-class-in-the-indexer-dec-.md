---
id: IDEA-0071
title: ADR supersession first-class in the indexer; DEC retirement from status, not
  version arithmetic (revises FR-0003/FR-0005)
status: parked
tags:
- indexer
- adr
- supersession
- versioning
- template
- decision-rights
size: S
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0071: ADR supersession first-class in the indexer; DEC retirement from status, not version arithmetic (revises FR-0003/FR-0005)

## Description

Three indexer gaps surfaced by Project A's first ADR supersession (ADR-0002 -> ADR-0003): (1) index-specs.py keys ADRs by filename prefix, so supersession must take a new ID; state this in specs/decisions/README.md and the ADR template and reconcile it with the '-v2 slug' wording so the stable-ID rule and the ADR instructions do not conflict (L41); (2) the ADR table renders no supersedes/superseded_by column and _cross_object_warnings checks supersession symmetry for FR/TR/DEC only, so an asymmetric ADR link passes silently (L42); (3) the Retired-objects section retires any DEC whose produced version is below a later last_breaking_revision ('pre-breaking'), which falsely retired DEC-0029 when DEC-0032 was briefly marked breaking; retirement should come from the DEC's own status/supersession, with version-window history as a separate opt-in view (L32).

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L32, L41, L42 (relayed from the Architect and backfill Reviewer); synthesis-2026-09-20 addendum finding 4. Revises hub-tooling FR-0003 (ADR template/README) and FR-0005 (retired-objects rule) via DECs; owns template/scripts/index-specs.py and template/specs/decisions/README.md. Home: hub-tooling, maintainer mode.

## Value hypothesis

Project A minted 34 DECs and 3 ADRs in three weeks, so supersessions and breaking flags will recur tens of times; each false retirement is a stale decision read into every agent slice, the exact risk FR-0005 exists to remove, and each asymmetric ADR link is an unlinted maze edge. Cost of not fixing is silent; the fix is a few dozen lines plus README wording.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0053 there). Personal-project names generalised.

(none)
