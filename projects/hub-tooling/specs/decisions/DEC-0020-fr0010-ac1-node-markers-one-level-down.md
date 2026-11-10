---
id: DEC-0020
title: "FR-0010 AC-1's marker table gains one nested rule: a node manifest or lockfile (`package.json`, `pnpm-lock.yaml`, `yarn.lock`) in an immediate, non-dot, non-symlink subdirectory of the primary checkout's root implies the same tools as at the root; every other marker stays root-only"
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0017]
revises: FR-0010
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Walk one level for every marker (python, uv, pip, alembic, compose included)"
  - "Recursive walk"
  - "No walk; Project A declares node through an accepted ADR's stack_tools"
  - "Read the stack from hub/projects.yaml instead of markers"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  Project A's frontend lives in frontend/, so detection never sees node, and every
  frontend FR burns its one retry on an in-harness Developer phase to regenerate
  schema.d.ts by hand (Project A L48). Detection keeps reading only the primary
  checkout (DEC-0014 Decision 4), so a role branch still cannot widen its own
  grants. The walk is one level, node-only and skips dot-directories,
  node_modules and symlinks. That is the narrowest rule that covers the evidence,
  and it leaves python/uv provisioning (which reads the root lock) consistent
  with its grants.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0020: FR-0010 AC-1 detects node markers one level down

## Context

FR-0010 AC-1 decides a project's stack tools from marker files. `test_stack_profile.py::test_marker_rules_boundaries` pins "nested markers are not the repo's markers" with the case `(["sub/pyproject.toml", "frontend/package.json", "deploy/uv.lock"], [])`. Project A keeps its frontend in `frontend/` (`frontend/package.json`), so `node`, `npm` and `npx` are never detected. Dispatched roles are therefore never granted `Bash(npm *)` / `Bash(node *)`, and the FR-0016 maintainer round had to hand-regenerate `schema.d.ts` (Project A L48). Project A FR-0014 is entirely frontend and, per Project A's 2026-09-25 handoff, is expected to drop at dev-evaluate for the same reason.

IDEA-0078 also asked that detection read the role worktree. DEC-0014 Decision 4 (ratified) overruled that half. Detection reads `REPO_ROOT`, the primary checkout, so that a branch cannot widen its own grants. This DEC keeps that property.

## Decision

1. **One nested rule, node only.** In addition to the root markers, each **immediate** subdirectory `<root>/<d>/` implies the same tools the root rule does for these markers:
   - `package.json` → `node`, `npm`, `npx`
   - `pnpm-lock.yaml` → `pnpm`
   - `yarn.lock` → `yarn`

   `<d>` qualifies when all of these hold:
   - it is a real directory, not a symlink;
   - its name does not start with `.`, which excludes `.git`, `.venv`, `.claude` and so the dispatch worktrees under `.claude/worktrees/`;
   - its name is not `node_modules`.
2. **Every other marker stays root-only:** `pyproject.toml`, `uv.lock`, `requirements.txt`, `alembic.ini`, and the compose files. `ensure_dev_venv` provisions from the root lock only, so a nested `uv.lock` grant would have no environment behind it.
3. **Unchanged:** presence-only detection, the pure/read-only property, the closed vocabulary, the ADR `stack_tools:` and `DISPATCH_STACK_TOOLS` sources, and `REPO_ROOT` as the root (DEC-0014 Decision 4). Grants, the `mnt` deny-lifting, pre-flight and the spawn record's `stack=` segment follow detection as they do for root markers. No consumer changes.

**`breaking: true`.** `stack_profile.py::_marker_tools` and one pinned test case must change. FR-0010 goes to `version: 5`, with `revisions: [DEC-0003, DEC-0005, DEC-0014, DEC-0020]` and `last_breaking_revision: 5`. Rule 5 was checked: FR-0010's identity is unchanged.

**Why `neil`.** It widens what roles are granted. It adds `Bash(node *)`, `Bash(npm *)` and `Bash(npx *)` for every role in a project with a nested manifest, and lifts `mnt`'s `node` / `npx` denies there. Grant changes are in DEC-0014's domain, which Neil ruled on. It is recorded `proposed`, is live now, and is ratified by Neil's approval of FR-0017.

## Alternatives considered

- **Walk one level for every marker.** Rejected. A nested `pyproject.toml` or `uv.lock` would grant `uv` with no provisioned environment, and nested compose files and `alembic.ini` are rarer and unevidenced.
- **Recursive walk.** Rejected. It would pick up `tests/fixtures/**` trees, vendored packages and anything under `node_modules`. The cost is unbounded and the grant surface is surprising.
- **No walk; Project A declares node through an accepted ADR.** Rejected as the fix, but still available. It works today for Project A alone, and every future project with a `frontend/` would rediscover the gap. The ADR route stays open for layouts deeper than one level.
- **Read the stack from `hub/projects.yaml`.** Rejected. The registry's `stack:` is one value (`python | node | none`), while detection yields a tool set. Out-of-tree projects may not be registered.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0010-stack-aware-grants-and-lock-provisioned-venv.md`, done in this commit:
  - AC-1 gains one sentence citing this DEC;
  - `version: 5`, `revisions` gains DEC-0020, `last_breaking_revision: 5`, `updated: 2026-09-25`;
  - one Changelog line.
- `template/scripts/stack_profile.py::_marker_tools`: FR-0017 AC-1, **maintainer mode**.
- `template/tests/unit/scripts/test_stack_profile.py::test_marker_rules_boundaries`, FR-0017's Reviewer:
  - the parametrised case `(["sub/pyproject.toml", "frontend/package.json", "deploy/uv.lock"], [])` becomes `["node", "npm", "npx"]`, and its comment is updated;
  - one case is added that keeps `sub/pyproject.toml` and `deploy/uv.lock` alone at `[]`;
  - no other test in the file changes. The fixture trees under `tests/fixtures/stack-profile/trees/` contain no nested manifests, so `test_fixture_trees_detect_exactly_the_ac1_vocabulary` and the exact-list tests are unaffected.
- Unaffected, verified by read:
  - `test_dispatch_stack_grants.py`: its repos have root markers only, and worktree manifests sit under `.claude/`;
  - `test_dispatch_env_preflight.py`: `dispatch.py` is not edited, so the seam call shape is unchanged;
  - `test_env_preflight.py`: its remedy check is a substring, so `package.json` still matches.

## Changelog

- 2026-09-25: created (proposed) with FR-0017, from IDEA-0078's nested-manifest half (its worktree half was overruled by DEC-0014 Decision 4).
- 2026-09-25: ratified by Neil, with his approval of FR-0017.
