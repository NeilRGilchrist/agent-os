---
id: IDEA-0045
title: FDE triage cross-session decision memory and prior-art graph
status: parked
tags:
- fde
- triage
- persistent-memory
- prior-art
- feedback-loop
size: L
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: PATTERN-0002
archive_reason: null
---

# IDEA-0045: FDE triage cross-session decision memory and prior-art graph

## Description

Phase 4 of IDEA-0024, re-parked on its own. Persist triage outcomes across sessions so ac-fde-triage can cite prior art: (1) session memory store of decisions, divergences and outcomes indexed by customer, category and disposition; (2) prior-art graph linking ticket -> session hub page -> final disposition -> similar future intakes; (3) prompt-version provenance per recommendation, correlated with reconcile accuracy. The skill's returning-ticket flag (Step 3) is the lightweight precursor already shipped. Candidate backends: FDE KB pipeline, a hub-style ledger, or a JSON ledger beside the skill config. Needs an architecture decision on freshness contract, write path, and scope (per-engagement, per-customer, or team-wide FDE corpus). Depends on the reconcile skill (IDEA-0044) for divergence data; may compose with IDEA-0023.

## Originating context

Split from IDEA-0024 on 2026-10-22 (CoS review). Phases 1-2 of IDEA-0024 shipped as ~/.agents/skills/ac-fde-triage; this phase was out of scope for the pilot and never built.

## Value hypothesis

Repeat-pattern misses drove a large share of the 2026-06-30 errors (OOB automation, returning ticket, FDE-owned app); a decision corpus that grows ~10 tickets/session lets the agent route like an experienced Architect instead of cold-reading each intake, and makes routing consistent across Architects.

## Notes

- Split from IDEA-0024 (archived 2026-10-22); see its Notes for the 2026-06-30 pilot outcomes and reconciliation table.
