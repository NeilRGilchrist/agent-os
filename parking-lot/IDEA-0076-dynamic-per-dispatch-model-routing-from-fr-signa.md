---
id: IDEA-0076
title: Dynamic per-dispatch model routing from FR signals (Jev / System One router)
status: parked
tags:
- dispatch
- template
- observability
- feedback-loop
size: M
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0076: Dynamic per-dispatch model routing from FR signals (Jev / System One router)

## Description

Replace dispatch.py's static per-role model mapping (dev=sonnet, rev=opus, bkf=opus, mnt=sonnet, env-overridable) with a per-spawn decision: code computes size signals for the assigned FR (file counts under owns globs, LOC touched, depends_on count, whether any never-edit or control-plane path is in scope, migration required), hands them plus the FR text to a cheap System One classifier (TypeSafe Jev: Score 0-3 complexity, Nouls for touches-control-plane / needs-migration / cross-cutting), and picks the model per spawn. Low confidence falls back to the static mapping; thresholds bias upward because under-routing costs Reviewer cycles (3-cycle budget) while over-routing only costs tokens. The routing policy is earned, not hand-tuned: the metrics log already records role, model, tokens_in/out, tool calls, status, round and verdict per dispatch.run, so the autoresearch pattern (LLM proposes features, Jev answers them per FR, a small model predicts review outcome / iteration count) validates the router once ~30 runs exist. Only for headless dispatch; inside an interactive orchestrator session the model choice is a near-free planning decision and a router saves nothing. Touches scripts/dispatch.py (never-edit list: draft, approve, apply) and needs an ip_class line for the TypeSafe skill under ADR-0003 before commit.

## Originating context

captured via /park 2026-09-20 after a Jev (TypeSafe System One) fit assessment for Project A; Neil's counterpoint: Jev as an agent router. Trigger to act: >=30 dispatch.run records in specs/_metrics. Companion: IDEA-0053 amendment (Jev as semantic pre-filter in the context-slice compiler).

## Value hypothesis

Per-spawn model choice driven by measured outcomes rather than a static role constant should cut dispatch inference spend on small FRs without raising Reviewer kick-back rate, and the metrics log makes the claim testable before the router is trusted.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0058 there). Personal-project names generalised.

(none)
