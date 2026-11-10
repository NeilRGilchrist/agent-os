---
id: IDEA-0078
title: Stack detection finds nested manifests (frontend/package.json) and reads the
  role worktree, not the outer repo root
status: promoted
tags:
- dispatch
- control-plane
- stack
- template
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0017
pattern: null
archive_reason: null
---
# IDEA-0078: Stack detection finds nested manifests (frontend/package.json) and reads the role worktree, not the outer repo root

## Description

template/scripts/stack_profile.py::detect_stack only checks for a package.json at the repo root (line 73), so a project whose frontend lives in a subdirectory (Project A: frontend/package.json) never has node/npm/npx detected, and dispatched roles are never granted Bash(npm *) / Bash(node *). Extend detection to walk one level of subdirectories for node manifests and lockfiles, or honour an explicit hint (a stack: key in hub/projects.yaml or FR frontmatter; FR-0010 AC-2's ADR stack_tools: already exists but needs an accepted ADR). Separately, the FR-0010 Reviewer found (finding g) that detection runs against the dispatcher's outer REPO_ROOT rather than the role worktree, so a branch that adds or removes a manifest is detected against main's tree. Detect against the worktree the role will run in.

## Originating context

Project A L48 (a downstream project's `_dispatch/learnings-FR-0016-FR-0002-wave.md`, 2026-09-21): the FR-0016 maintainer round had to hand-regenerate schema.d.ts because npm was not granted. Still open against hub 851ee34 per Project A HANDOFF-orchestrator-wave-FR-0005-FR-0014-2026-09-25 section 3: FR-0014 is entirely frontend and is expected to drop at dev-evaluate and need the in-harness retry. Hub-tooling FR-0010 Reviewer FINDINGS (g), hub PR #4. Extends hub-tooling FR-0010 (AC-1 marker table). Possible interim for Project A (not verified, Project A Architect's call): an accepted Project A ADR declaring stack_tools: [node, npm, npx]. Touches template/scripts/stack_profile.py and the detect_stack call site in dispatch.py (maintainer mode). Home: hub-tooling. Proposed wave 2, lane A, order 2.

## Value hypothesis

Every Project A FR touching frontend/** (FR-0014 next, then FR-0006/0007/0009 and every API-shaped FR that regenerates schema.d.ts) currently burns its one retry on an in-harness Developer phase (~20-30 min of Orchestrator time each); fixing detection lets those cycles run unattended, as Project A L58 showed for python/uv/docker stacks.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0060 there). Personal-project names generalised.

(none)
