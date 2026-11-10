---
id: IDEA-0061
title: 'Subdirectory-aware dispatch and gate: project root != repo root'
status: promoted
tags:
- template
- dispatch
- deploy-gate
- tooling
- monorepo
- footprint
size: M
created: '2026-09-07'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0023
pattern: null
archive_reason: null
---
# IDEA-0061: Subdirectory-aware dispatch and gate: project root != repo root

## Description

dispatch.py sets REPO_ROOT to the project directory and runs git worktree/ls-tree there; when the project is a subdirectory of its repo (projects/hub-tooling inside the hub; any project in a monorepo) the worktree checks out the whole repo with the agent pointed at the wrong level and ls-tree looks for specs/ at the repo root. deploy-gate.py scans only the project's own src/ and tests/, and spec_footprint.py rejects .. in owns:/reads:, so footprints for code outside the project root are decorative and Maintainer-mode permission enforcement cannot resolve them. Make both tools derive the repo root from git rev-parse --show-toplevel and carry a project-relative prefix; let the gate's source and test directories be configured per project (hub-tooling: template/, scripts/, template/tests/); allow footprints to name repo-relative paths so the overlap check and the per-spawn settings file work again. Also: hub CI should run template/tests directly.

## Originating context

Surfaced 2026-09-07 while starting wave A in projects/hub-tooling: five FRs (FR-0001..0005) had to be drafted and will be implemented via hand-dispatched subagents because dispatch.py and the gate assume project root == repo root. Neil confirmed parking it and promoting after wave A.

## Value hypothesis

Restores dispatch.py wave, footprint overlap detection, and Maintainer-mode enforcement for any project that is not its own repo, starting with the hub's own tooling project, so hub work stops needing hand orchestration by the Chief of Staff.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0043 there). Personal-project names generalised.

2026-09-25 (CoS; from hub-tooling wave 1): two more costs of project root != repo root, seen while hand-orchestrating wave 1 at the hub root. (1) No Reviewer branch convention: git refuses a second worktree on the same branch, so the plan's 'second worktree on the branch tip' for the Reviewer did not work; the workaround was removing the maintainer worktree (the branch survives) and re-adding it for the Reviewer. The dispatcher's `claude/rev-<FR>` branch, fast-forwarded at finalize, is the convention to inherit once `wave` works here. (2) Reviewer tests in `template/tests/` must use `# covers hub-tooling FR-NNNN:AC-N` (a literal `@covers` would fail every bootstrapped project's gate as 'unknown FR'), so the local gate sees no coverage and the per-AC table in the PR body is the only coverage evidence. Wave 1 was hand-orchestrated for 7 FRs over 2026-09-20..22 (FR-0013 alone ~5 h across 10 phases). Proposed to lead wave 3 so later hub-tooling FRs can go through `wave`. Source: projects/hub-tooling/_dispatch/learnings-wave1.md (FR-0009 section).
