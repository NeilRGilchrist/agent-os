---
id: IDEA-0051
title: Rule-based auto-promotion, gated on the approved-without-edits threshold
status: parked
tags:
- ai-productivity-toolkit
- promotion
- metrics
- automation
size: M
created: '2026-10-23'
updated: '2026-10-23'
last_reviewed: '2026-10-23'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0051: Rule-based auto-promotion, gated on the approved-without-edits threshold

## Description

Deterministic rules (never a model) that promote low-risk tracked items from personal to team scope without a per-item human approval, e.g. internal-only source, every item confirmed, no redaction hits, target scope team. Needs a holding window before merge because the team KB is git and a merged mistake is effectively permanent (ADR-0002 section 6). Reverses the current invariant that every promotion has a human approver, so it needs an ADR and sponsor sign-off.

## Originating context

CoS session 2026-10-23. Gate: act on this IDEA only once the pilot's approved-without-edits metric (FR-0008 pilot thresholds) reaches an agreed threshold; track until then.

## Value hypothesis

Removes the per-item approval step for the classes of items humans already approve unchanged, cutting review time in proportion to the pilot's approved-without-edits rate.

## Notes

(none)
