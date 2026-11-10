---
id: IDEA-0044
title: 'FDE triage reconcile skill: diff agent recommendations against Architect decisions
  from the session transcript'
status: parked
tags:
- fde
- triage
- feedback-loop
- prompt-tuning
- agent-effectiveness
size: M
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: PATTERN-0002
archive_reason: null
---

# IDEA-0044: FDE triage reconcile skill: diff agent recommendations against Architect decisions from the session transcript

## Description

Phase 3 of IDEA-0024, re-parked on its own. An ac-fde-triage-reconcile skill that ingests the triage call transcript (Fathom or manual paste) and reconciles it against the session hub page and ac-fde-triage pre-work: (1) per-ticket decision diff (agent rec vs actual disposition), (2) rationale extraction for divergences, (3) classify divergences into prompt-tuning signals (rubric miscalibration, research gap, classification error, intake-threshold issue), (4) write a reconciliation report to the session Confluence page and optionally draft HITL edits to the prompt pages. The 2026-06-30 manual reconciliation (0/10 exact, 6 partial, 4 miss; 7 ranked tuning signals) is the worked example and rubric seed. Open questions carried from IDEA-0024: transcript source (Fathom auto-ingest vs paste); prompt versioning (Confluence page versions vs explicit tags in the session hub). Shares transcript-parsing infra with IDEA-0016.

## Originating context

Split from IDEA-0024 on 2026-10-22 (CoS review). Phases 1-2 of IDEA-0024 shipped as ~/.agents/skills/ac-fde-triage; this phase was never built.

## Value hypothesis

The one manual reconciliation produced 7 tuning signals, 5 of which fed straight into the ac-fde-triage skill; automating it at ~4 sessions/month turns prompt tuning from ad hoc into a measured loop and gives an accuracy trend (exact/partial/miss per session) to show whether the skill is earning its keep.

## Notes

- Split from IDEA-0024 (archived 2026-10-22); see its Notes for the 2026-06-30 pilot outcomes and reconciliation table.
