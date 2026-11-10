---
id: IDEA-0067
title: Post-approve and Reviewer-artifact lifecycle in finalize/wave (revises FR-0006)
status: promoted
tags:
- dispatch
- control-plane
- finalize
- rework
- template
size: M
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: hub-tooling/FR-0013
pattern: null
archive_reason: null
---
# IDEA-0067: Post-approve and Reviewer-artifact lifecycle in finalize/wave (revises FR-0006)

## Description

Close the lifecycle gaps the FR-0001 wave hit after FR-0006: (1) on an approve, fast-forward the dev/mnt branch onto the rev tip and push so the PR carries round-N Reviewer commits (L25); (2) finalize --role rev keeps the agent's own staged REVIEW.md and only synthesises one when absent, revising FR-0006 AC-6's always-overwrite default (L17); (3) accept the verdict marker anywhere in the first heading or mandate a fixed first line 'Verdict: approve|request-changes' instead of line-start regex sniffing (L16); (4) finalize --role rev takes --verdict-file so a subagent-run Reviewer with no _dispatch/*.rev.log is finalizable (L15); (5) the maintainer footprint check exempts Reviewer-owned paths (tests/**, REVIEW.md) landed by the rev role and specs/_metrics/** (L36, L39); (6) a rebase-and-revalidate step (merge main, re-run gate) when a dependent PR merges or an Architect edits the FR mid-PR (L30, L46); (7) default wave --rounds to 2 so the 3-cycle budget is used (L3).

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L3, L15, L16, L17, L25, L30, L36, L39, L46; synthesis-2026-09-20 findings 1(c)(d). Revises hub-tooling FR-0006 (merged; AC-6 default and the 'no sync in the other direction' out-of-scope line) via a DEC; owns template/scripts/dispatch.py so sequence with FR-0008/FR-0009/IDEA-0065. Home: hub-tooling, maintainer mode.

## Value hypothesis

FR-0001 needed five hand steps here (preserving the 11 KB round-1 review finalize overwrote, FF dev onto rev + push, restoring the gate-appended metrics record twice, a plain push past the footprint check, a main-merge to fix PR #4's stale CI): 25-30 min of Orchestrator time per FR, ~5-6 h over the 12 remaining FRs, plus loss of the review text FR-0008's gate-evidence model depends on.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0049 there). Personal-project names generalised.

(none)
