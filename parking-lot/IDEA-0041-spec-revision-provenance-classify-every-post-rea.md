---
id: IDEA-0041
title: 'Spec revision provenance: classify every post-ready FR change by cause (defect
  / enhancement / external direction)'
status: parked
tags:
- template
- spec-graph
- metrics
- agent-effectiveness
- process
- feedback-loop
size: M
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: PATTERN-0002
archive_reason: null
---

# IDEA-0041: Spec revision provenance: classify every post-ready FR change by cause (defect / enhancement / external direction)

## Description

See the orchestrator's proposal in the originating conversation: a required cause on each Changelog entry after first ready, fixed taxonomy, a sources field for external decisions, enhancements as new FRs with an extends link, and an index-specs/hub-index rollup. Complements IDEA-0016 (agent effectiveness analysis), which measures sessions; this measures specs. Pair with IDEA-0035 (deferred ACs) since both change the FR template.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. Human asked how to tell rework from enhancement from direction change; this session alone produced all three kinds (FR-0001 AC-9 backfill, FR-0002 AC-2 rewording, FR-0005 AC-9-11 superseded by the capture redesign).

## Value hypothesis

Lets the hub measure first-pass Architect spec quality (rework rate) separately from legitimate evolution and from externally imposed change, instead of all three looking identical in git history.

## Notes

(none)
