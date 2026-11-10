---
id: IDEA-0057
title: Dashboards as prescribed queries + projection library (H7+H8)
status: parked
tags:
- template
- observability
- dashboards
- projections
- docs
- indexer
size: M
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0057: Dashboards as prescribed queries + projection library (H7+H8)

## Description

H7: a dashboards/ folder of named queries over the spec index and the H6 metrics log, each efficiency signal paired with a quality counter-metric: PR cost (tokens and retries vs defect escapes), test rigidity (tests changed per FR change vs SC coverage), decision flow (DEC proposed-to-ratified time and queue depth vs rejection and rubber-stamp rate), spec health (orphans, stale implementers, provisional past trigger), stability (supersession:revision ratio vs ADR churn), coverage (GOALs without FR, FRs without TR, SCs without test), honesty (breaking mis-mark rate per role), adoption (post-launch). H8: generalise the client-doc projection in render-docs.py into generators run at gate time: per-role user guide, API reference, release notes as DEC/TR diff between tags in outcome language, roadmap as unbuilt canonical FRs ordered by value weight with derived status, sales collateral (FR + GOAL + asserted_by), prospect-validate sheet. Depends on H2, H3, H6.

## Originating context

Project A proposal cos-agent-hub-changes.md H7 and H8 (wave C), triaged via /cos 2026-09-07. Seed in template: docs role and render-docs.py client projections.

## Value hypothesis

Prescribed queries let a periodic reviewer synthesise without reading the repo, and pairing every efficiency metric with a quality metric guards against loosening things that should not loosen; every documentation artifact becomes a projection so nobody hand-maintains status, roadmap, or changelog.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0039 there). Personal-project names generalised.

(none)
