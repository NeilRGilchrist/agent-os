---
id: IDEA-0069
title: First-class in-harness subagent dispatch mode
status: parked
tags:
- dispatch
- harness
- metrics
- control-plane
- safety
- rework
size: M
created: '2026-09-20'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0069: First-class in-harness subagent dispatch mode

## Description

When the dispatcher-spawned phase fails and a claude -p retry is refused by the auto-mode classifier, the Orchestrator falls back to an in-harness Agent subagent driven by a brief. That path today has no _dispatch/*.lock (status and wave pre-flight are blind to it), emits no dispatch.run record (metrics_log.py requires tool_calls_by_tool/tokens_in/tokens_out the harness cannot supply), and runs under the Orchestrator session's permissions so the per-role deny list in the worktree settings file is not enforced. Give dispatch.py a first-class 'spawn via host harness subagent' mode: writes the lock and the brief, accepts a completion report (final message + totals) to close the run and emit dispatch.run with a relaxed required-field set for this mode, and prints the role deny list into the brief so the agent is told what the harness will not enforce. Pairs with IDEA-0062 (follow mode).

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L7, L15, L29, L34; synthesis-2026-09-20 dispatch_mode row. Touches template/scripts/dispatch.py and metrics_log.py (FR-0002 record requirements). Home: hub-tooling, maintainer mode.

## Value hypothesis

5 of 7 phases (71%) in the FR-0001 wave ran as subagents: zero dispatch.run records, no lock, deny list unenforced with control-plane paths guarded only by the brief and the classifier. The classifier blocks claude -p --allowedTools retries, so this stays the retry path even after IDEA-0065. Making it first-class lets metrics count 100% of phases instead of ~30% and restores role isolation on every retry.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0051 there). Personal-project names generalised.

2026-09-25 (CoS; from Project A L49 / OQ-0065, OQ-0066): once `wave` drops an FR mechanically and the FR is `in-progress`, `wave` refuses to re-enter it, so the `--rounds` rework loop is unreachable and the Orchestrator hand-mirrors `_run_one_rework_round` (merge rev->dev, brief, in-harness Developer, `finalize --role dev`, `tick --role rev`, `finalize --role rev`, FF dev->rev, push). Done by hand for Project A FR-0016 and FR-0003. The in-harness retry is the path this IDEA makes first-class, so re-entry belongs here: after a retry completes, a `wave --resume` / `rework FR-XXXX` entry point should pick the FR up at the next phase with its remaining rounds budget. Also: the rework sync (`merge rev->dev`) aborts on an unstaged `specs/_metrics/*.ndjson` in the dev worktree (OQ-0066; same root as Project A L36/L40; see IDEA-0079). Check against hub 851ee34 first: FR-0013 made `--rounds 2` the default and FR-0008 lets a gate-stopped FR resume by re-running `wave --fr`, but neither covers re-entry after a mechanical drop. Sources: a downstream project's `_dispatch/learnings-FR-0016-FR-0002-wave.md` L49; synthesis-20260921T043559Z and synthesis-20260921T145928Z (hand-mirrored rounds).

2026-11-09 (CoS; from an ai-productivity-toolkit Orchestrator escalation): Architect escalations have no dispatcher role. `finalize` accepts only dev/rev/bkf/mnt/gat, ROLE_MODEL has no architect entry, and `gat` only judges a declared `reviewer: architect` gate. So `/architect` escalation passes always run in-harness, as orchestrator.md §2 Fallback directs, with no lock and no `dispatch.run` record. The first-class in-harness mode should cover the Architect too, not only dev/rev retries.
