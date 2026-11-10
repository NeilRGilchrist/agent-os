---
id: IDEA-0106
title: 'Dispatcher wave-4 residue: mid-pipeline resume, lock hygiene, dry-run grants,
  metrics project name'
status: parked
tags:
- dispatch
- wave
- orchestrator
- metrics
- layout
size: M
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0106: Dispatcher wave-4 residue: mid-pipeline resume, lock hygiene, dry-run grants, metrics project name

## Description

Observed in Wave 4: (1) a wave cannot resume at the review step after the dev leg handed off; it aborts and recovery is manual tick --role rev plus finalize; (2) a dry-run wave auto-prunes dead locks, so the dry run mutates state; (3) a successful dev phase leaves a dead lock behind; (4) the dry run prints owns-grants=N but not the resolved grant strings, so absolute grants (FR-0024) can only be checked after spawning; (5) summary needs fr_id --role and cannot show a timeline; (6) the orchestrator role names _dispatch/synthesis-<ts>.md but the wave writes _dispatch/wave-<ts>.md; (7) metrics rows from hub-tooling record project 'Code' (the repo directory) rather than 'hub-tooling', a FR-0024 subdirectory gap.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; Orchestrator trial friction 3-7; follows IDEA-0084 (wave-1 residue)

## Value hypothesis

Cuts manual recovery after a partial wave from several hand-run commands to one, and keeps subdirectory projects' metrics attributable.

## Notes

2026-11-09 (CoS; from an ai-productivity-toolkit Orchestrator escalation, FR-0012/FR-0013): resume should also adopt an implementation branch the dispatcher did not create (e.g. `feat/FR-XXXX`), or refuse it with a clear message, instead of silently branching off main. Every handoff/rework lookup (`_handed_off_reason`, `_prepare_dev_worktree_for_rework`, the rev/gat branch resolution) keys on `claude/dev-<FR>`, so the existing `feat/FR-0012` / `feat/FR-0013` branches were invisible and `wave --rounds` would have started a fresh Developer from main. The Orchestrator fell back to native Agent calls for the rework.
