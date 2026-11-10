---
id: FR-0017
title: Stack detection finds a node manifest one directory below the primary checkout's root (`frontend/package.json`), so every role in such a project is granted node, npm and npx exactly as a root manifest grants them
status: merged
owner: architect
depends_on: []
tags: [dispatch, stack, control-plane, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/stack_profile.py
  - template/tests/unit/scripts/test_stack_nested_manifests.py
  - template/tests/fixtures/stack-nested/**
  # DEC-0020 cascade — Reviewer only, bounded to the one parametrised case DEC-0020 names:
  - template/tests/unit/scripts/test_stack_profile.py
reads:
  - template/scripts/dispatch.py
  - template/scripts/env_preflight.py
  - template/tests/unit/scripts/test_dispatch_stack_grants.py
  - template/tests/unit/scripts/test_dispatch_env_preflight.py
  - template/tests/unit/scripts/test_env_preflight.py
  - template/tests/fixtures/stack-profile/**
  - specs/decisions/DEC-0014-docker-stays-granted-finalize-is-the-control-plane-boundary.md
  - specs/decisions/DEC-0020-fr0010-ac1-node-markers-one-level-down.md
gates: []
derived_from: IDEA-0078
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0010]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - How the immediate subdirectories are listed (one `iterdir` shared with the compose glob, or separate), as long as detection stays presence-only and read-only.
  fixed:
    - "Detection reads the primary checkout (`REPO_ROOT`), never a role worktree (DEC-0014 Decision 4). A manifest that exists only on a role branch grants nothing."
    - "`template/scripts/dispatch.py` is not edited. Every consumer (grants, `mnt` deny-lifting, pre-flight, the spawn record's `stack=` segment) follows detection unchanged."
    - "Only `package.json`, `pnpm-lock.yaml` and `yarn.lock` are read one level down; every other marker stays root-only (DEC-0020 Decision 2)."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-09-25
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session) from IDEA-0078's nested-manifest half. Its worktree half was overruled by DEC-0014 Decision 4. Grounded in a read of `template/scripts/stack_profile.py` at `a8889df` (`_marker_tools` L61-87), every consumer of `detected_stack_tools` in `dispatch.py`, and every test that pins detection output. · source_class: agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0017: Stack detection finds a node manifest one directory down

## Why

Stack detection (FR-0010 AC-1) looks for `package.json` only at the repo root. Project A's frontend is in `frontend/`, so node is never detected there, and no dispatched role is granted `npm` or `node`. The FR-0016 maintainer round had to hand-regenerate `schema.d.ts` because `npm` was denied (Project A L48). Every Project A FR that touches `frontend/**` hits the same wall: FR-0014 next, then FR-0006, FR-0007, FR-0009, and every API-shaped FR that regenerates the schema. Each burns its one retry on an in-harness Developer phase, about 20-30 minutes of Orchestrator time apiece, where python/uv/docker stacks already run unattended (Project A L58).

## What

After this FR, a `package.json`, `pnpm-lock.yaml` or `yarn.lock` in an immediate subdirectory of the primary checkout's root implies the same tools as at the root. Dot-directories, `node_modules` and symlinked directories are excluded. Everything downstream follows with no code change: grants, `mnt`'s deny-lifting, pre-flight, and the `stack=` segment. Detection still reads only the primary checkout, so a role branch cannot widen its own grants.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Node markers are detected one level down.** `detect_stack(root).tools` includes, for each immediate subdirectory `<root>/<d>/`:
  - `node`, `npm` and `npx` when `<d>/package.json` is a file;
  - `pnpm` when `<d>/pnpm-lock.yaml` is a file;
  - `yarn` when `<d>/yarn.lock` is a file.

  `<d>` qualifies when it is a real directory, not a symlink, its name does not start with `.`, and it is not named `node_modules`. The result stays sorted and de-duplicated. A root marker and a nested one together yield each tool once. Verified with fixture trees:
  - `frontend/package.json` alone → `["node", "npm", "npx"]`
  - `web/pnpm-lock.yaml` alone → `["pnpm"]`
  - `app/yarn.lock` alone → `["yarn"]`
  - `pyproject.toml` + `uv.lock` + `frontend/package.json` (Project A's shape) → `["node", "npm", "npx", "python", "uv"]`, plus `docker` when a root compose file is present
  - root `package.json` + `frontend/package.json` → the node trio once

- **AC-2:** **Everything else stays root-only, and the excluded directories are excluded.** These each yield `[]`:
  - `sub/pyproject.toml`, `deploy/uv.lock`, `api/requirements.txt`, `db/alembic.ini` and `infra/docker-compose.yml`, each alone;
  - `a/b/package.json` (two levels);
  - `.hidden/package.json`, `node_modules/package.json`, and `.claude/worktrees/x/package.json`;
  - a symlinked directory pointing at a tree with `package.json`, where the platform supports symlinks (skipped with a reason otherwise);
  - a *directory* named `package.json` inside `frontend/`.

  Detection is still presence-only and read-only. An unparseable nested `package.json` counts, and no file content is read.

- **AC-3:** **A nested manifest grants through the unchanged dispatcher, from the primary checkout only.** In a temporary repository whose primary checkout has `frontend/package.json` and no root `package.json`:
  - every role's permission file written by `write_worktree_settings` (`dev`, `rev`, `bkf`, `mnt`) contains `Bash(npm *)`, `Bash(node *)` and `Bash(npx *)`, exactly as a root `package.json` makes it today;
  - `mnt`'s `node` / `npx` denies are lifted as FR-0010 AC-6 lifts them for a root manifest;
  - the spawn record's `worktree_status` carries the `stack=` segment with `node,npm,npx`.

  A `frontend/package.json` committed only on a role branch, and absent from the primary checkout, grants nothing: every role's permission file is byte-identical to a no-stack project's. Verified with the real `dispatch.py` and the real adapter, as `test_dispatch_stack_grants.py` does it.

- **AC-4:** **Nothing else changes.**
  - `dispatch.py`, `env_preflight.py`, `STACK_BASH_GRANTS` and every consumer are not edited.
  - A project with no nested manifests gets byte-identical detection, grants, pre-flight output and spawn records.
  - Every test that passed before this FR passes unedited, except the one `test_marker_rules_boundaries` case DEC-0020 names, changed only as DEC-0020 bounds it.

## Out of scope

- Detecting against a role worktree: overruled by DEC-0014 Decision 4.
- Nested python, uv, pip, alembic or compose markers (DEC-0020 Decision 2), and deeper than one level. An accepted ADR's `stack_tools:` covers other layouts.
- Running `npm install` / `npm ci` or provisioning `node_modules` for a role. The grant lets the agent run it; nothing is run on its behalf.
- Pre-flight remedy text naming the nested path (`env_preflight._TOOL_DECLARED_BY` still says `package.json`).
- New stack hints (a registry `stack:` or FR frontmatter): IDEA-0078's other suggestions, not needed for the evidence.

## Open questions

- **Q:** Should a project with nested manifests in two subdirectories (`web/` and `admin/`) behave any differently?
  - **Default:** No. Tools are a set, so two manifests yield the node trio once (AC-1).
- **Q:** Does detecting node newly start pre-flight on a project whose only stack is a nested `package.json`, including the Windows app-control probe?
  - **Default:** Yes, by design, exactly as a root `package.json` does. `node`, `npm` and `npx` missing from PATH is a `warn` finding, not a block. The pre-flight OK line changes from `PREFLIGHT OK (no stack declared)` to the `ran:` form. That is the correct report for such a project.

## Dependencies

- **FR-0010**: AC-1's marker table, revised by DEC-0020 (v5, breaking), and every consumer this FR relies on unchanged.
- **DEC-0014**: Decision 4, detection reads the primary checkout, which this FR keeps.
- None on the `dispatch.py` chain. This FR does not touch `dispatch.py`, so it can run beside FR-0015, FR-0016 and FR-0018 rather than after them.

## Notes

- **Maintainer mode.** `template/scripts/stack_profile.py` feeds the permission derivation, and DEC-0020 is `neil`-tier because it widens grants. Dispatch in `mnt` mode with the `owns:` above as its write surface, after Neil approves (recorded in the Changelog). Edit `../../template/**`, never this project's bootstrap-output copy.
- **Fixtures.** Put new trees under `template/tests/fixtures/stack-nested/**`, not under `stack-profile/trees/`. `test_fixture_trees_detect_exactly_the_ac1_vocabulary` enumerates that directory with exact expectations, and a new tree there would move a pin DEC-0020 does not authorise.
- **Reviewer:**
  - Bite check: load `a8889df`'s `stack_profile.py` as a second module and show AC-1's Project A-shape case yields no node there.
  - For AC-3, drive the real adapter. Unit-level detection alone does not prove a permission file changed.
- **Reviewer dogfood (AGENTS.md).**
  1. Bootstrap a throwaway (short path, `--no-register`) with `frontend/package.json` only, commit it, and spawn each role with `--dry-run`, or read the permission files `ensure_role_worktree` writes. Confirm `Bash(npm *)` in every role's file.
  2. Check out a role branch that adds `admin/package.json` and remove `frontend/package.json` from the primary checkout. Confirm no node grant (the DEC-0014 Decision 4 property).
  3. Run the throwaway's `index-specs.py --validate` and `deploy-gate.py`.
  4. Delete the throwaway.
- **Project A checkpoint.** After this merges, `--upgrade projects/project-a --yes` retires Project A's npm in-harness retry (wave-2 plan §7). Tell the Project A Orchestrator rather than upgrading mid-Project A-wave.

## Changelog

- 2026-09-25: created from IDEA-0078 (nested-manifest half only; DEC-0014 Decision 4 keeps detection on the primary checkout). Companion decision DEC-0020 (revises FR-0010 AC-1, `neil` tier, proposed). Awaiting Neil's approval before dispatch.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified this FR's `neil`-tier DECs. No normative change.
