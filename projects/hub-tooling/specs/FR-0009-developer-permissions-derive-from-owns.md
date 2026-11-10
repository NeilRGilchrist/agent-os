---
id: FR-0009
title: Developer worktree permissions derive from the FR's `owns:` footprint — the maintainer derivation, generalised to `dev`
status: merged
owner: architect
depends_on: []
tags: [dispatch, harness, control-plane, footprint, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_dispatch_permissions.py
  - template/tests/fixtures/dispatch-permissions/**
reads:
  - template/scripts/spec_footprint.py
  - template/.agent-team/roles/developer.md
  - template/.agent-team/commands/developer.md
  - template/.agent-team/commands/orchestrator.md
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - scripts/bootstrap.py
derived_from: null
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0002]
last_breaking_revision: 2
supersedes: null
superseded_by: null
extends: [FR-0006]
serves_roles: []
solution_space:
  open: []
  fixed: []
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-20
updated: 2026-09-21
---

> **Provenance:** Drafted 2026-09-20 by the Architect from the Project A `_dispatch/learnings-FR-0001-wave.md` post-run entry L5 (the first build-lane wave in Project A, dropped at dev-evaluate). Net-new; no parked IDEA covers it. Closest neighbour is IDEA-0031 (worktrees under `.claude/`), which is a different failure and stays parked.

# FR-0009: Developer worktree permissions derive from the FR's `owns:` footprint — the maintainer derivation, generalised to `dev`

## Why

A dispatched Developer runs headless (`claude -p`), where every tool call the worktree allow-list does not match is auto-denied with nobody to answer the prompt. Today that allow-list is the static `ClaudeCodeAdapter.ROLE_PERMISSIONS["dev"]` block in `template/scripts/dispatch.py`: a fixed set of path globs (`src/**`, `docs/**`, `*.py`, `*.md`, `*.toml`, a few config extensions) chosen for a Python-service repo. The FR's own `owns:` footprint — the spec graph's declared write surface, already validated by the indexer and already enforced for `mnt` — plays no part in what the Developer may write. The Project A FR-0001 wave on 2026-09-20 shows the cost: the FR owns `.python-version`, `.env.example`, `alembic.ini`, `uv.lock`, `migrations/**`, `frontend/**` and `.github/workflows/stack-ci.yml`; none match a static grant, the Developer hit repeated denials on the first of them within two minutes, ended its turn asking a human for approval, never wrote `PR_BODY.md`, and the dispatcher dropped the FR. The spec said what the Developer could touch; the harness said otherwise. The maintainer role already solves exactly this (`mnt_permissions` re-scopes `dev`'s surface to `owns:`); the Developer should get the same derivation, additively.

## What

After this FR lands, when the dispatcher writes a Developer worktree's permission file it grants `Edit`/`Write` on every glob in the FR's `owns:` in addition to the static `dev` grants, so a footprint the Architect declared and the indexer accepted is a footprint the Developer can actually write. The role deny-list keeps winning: protected control-plane paths and Reviewer-owned tests are never granted to `dev` no matter what an FR claims, and the dispatcher says so at spawn time instead of letting the agent discover it by denial. Globs the harness guards on its own (`.claude/**`) are reported as unwritable with the sanctioned route, as `mnt` already does. Dry-run previews the derived grants and writes nothing. The `mnt` derivation, and every other role, are unchanged.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **The Developer's permission file unions the FR's `owns:` into the static grants.** Given an FR whose `owns:` is non-empty, `write_worktree_settings(wt_path, "dev", <FR>)` on the Claude Code adapter writes `.claude/settings.local.json` whose `allow` list contains every entry of `ROLE_PERMISSIONS["dev"]["allow"]` unchanged and, in addition, `Edit(<glob>)` and `Write(<glob>)` for every glob in `owns:` that AC-2 and AC-3 do not withhold. Globs are written verbatim (POSIX form, as declared). Verified with an `owns:` containing a root dotfile (`.python-version`), a nested `**` glob (`migrations/**`), a single-segment wildcard (`frontend/*`), and a path under a directory the static grants never mention (`.github/workflows/stack-ci.yml`): all four appear as both `Edit(...)` and `Write(...)`.

- **AC-2:** **Protected paths are never granted to `dev`, and the withholding is reported.** For every `owns:` glob that falls under a `MNT_PROTECTED_GLOBS` entry, matches `tests/test_*.py`, or is in `MNT_NEVER_WRITABLE`, no `Edit`/`Write` grant is written, the static `dev` deny list is written unchanged (no narrowing of `.agent-team/**` into per-file denies — that is `mnt`'s privilege), and the spawn path prints exactly one `WARN` line per withheld glob naming the glob and stating that the path needs maintainer (`mnt`) mode. The spawn proceeds. Verified with an `owns:` that includes `scripts/deploy-gate.py`, `.agent-team/roles/developer.md`, `tests/test_foo.py`, and `CLAUDE.md`: four WARN lines, zero corresponding grants, deny list byte-identical to the static one.

- **AC-3:** **Harness-guarded globs are reported, not silently granted.** For every `owns:` glob that `mnt_unwritable_grants` would classify as harness-guarded (`HARNESS_GUARDED_GLOBS`), the spawn path prints exactly one `WARN` line naming the glob, stating that the harness guards it independently of the settings file, and appending the `mnt_unwritable_hint` route when one exists. Whether the grant is also written is the Developer's choice (see Open questions), but the WARN must appear before the `SPAWNED` line. Verified with `owns: [".claude/commands/developer.md"]`.

- **AC-4:** **An FR with no `owns:` behaves exactly as today.** When `fr_owns_globs(<FR>)` is empty, the Developer's permission file is byte-identical to the one the current dispatcher writes for `dev`, no WARN is printed about the footprint, and the spawn is not refused (unlike `mnt`, which returns `None` and must not run). Verified by snapshotting the file written by the pre-FR dispatcher for an ownerless fixture FR and comparing. **Scoped by DEC-0002 (v2):** this and every other comparison against the pre-FR dispatcher in this FR is stated for a project with no detected stack (the condition FR-0010's no-stack byte-identity AC states); with a detected stack, FR-0010 AC-4 unions stack-derived `Bash(...)` grants into every role's allow-list by design.

- **AC-5:** **Malformed globs refuse the spawn with the indexer's rule.** An `owns:` entry that is absolute, contains a `..` segment, or is not a string is not granted; the dispatcher prints one `ERROR` line naming the FR and the offending entry, and `spawn_role` for `dev` does not spawn (no worktree settings written, no process started, no `dispatch.spawn` metrics record). The rule is the same one `spec_footprint._validate_glob` applies, so the indexer and the dispatcher never disagree about which footprints are legal.

- **AC-6:** **The derivation runs on every spawn, including worktree reuse.** When `ensure_role_worktree` reuses an existing `dev` worktree, the permission file is rewritten from the FR's current `owns:`; an `owns:` glob added to the spec after the worktree was created appears in the rewritten file. Verified by creating the worktree, editing the fixture FR's `owns:`, spawning again, and asserting the new grant is present.

- **AC-7:** **The spawn report states the derived grant count.** The line the dispatcher prints for a `dev` spawn (`SPAWNED` in apply mode, `WOULD-SPAWN` in dry-run) — or a line immediately preceding it — carries `owns-grants=<n>` where `<n>` is the number of `owns:` globs granted after AC-2/AC-3 withholding. In dry-run this is computed without writing any file: after a `tick --dry-run` / `wave --dry-run` the worktree tree (if it exists) and `.claude/settings.local.json` are byte-identical to before.

- **AC-8:** **The Cursor adapter applies the same derivation.** `CursorAdapter.write_worktree_settings(wt_path, "dev", <FR>)` writes `.cursor/cli.json` whose allow list is the static Cursor `dev` allow list plus the AC-1 grants in that adapter's permission syntax, with AC-2/AC-3 withholding applied identically. Verified with the same four-glob fixture as AC-1.

- **AC-9:** **`mnt`, `rev`, and `bkf` are unchanged by this FR.** For the same fixture FR, `mnt_permissions(<FR>)` returns a structure equal to what the pre-FR dispatcher returned (the maintainer derivation is reused, not modified). **Revised by DEC-0002 (v2, breaking):** the permission files written for `rev` and `bkf` are byte-identical to the pre-FR files **for an FR with no `owns:`** — the same scoping AC-4 gives `dev`. For an FR with a non-empty `owns:`, FR-0010 AC-5 extends the `owns:` derivation this FR built for `dev` to `rev` and `bkf`, and those files are specified and tested there. As in AC-4, the comparisons are made in a project with no detected stack; with one, FR-0010 AC-4 and AC-6 change every role's allow-list and the maintainer deny list by design. The v1 text claimed `rev`/`bkf` byte-identity for every `owns:`; the four `test_dispatch_permissions.py` parametrisations that pinned it are narrowed exactly as DEC-0002's cascade states, in FR-0010's Reviewer phase. Every test that passed before this FR still passes.

- **AC-10:** **The derived grants are enough for the motivating case.** Using a fixture FR whose `owns:` is the Project A FR-0001 footprint verbatim (`src/project_a/*.py`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/README.md`, `docker-compose.yml`, `.env.example`, `pyproject.toml`, `uv.lock`, `.python-version`, `requirements.txt`, `pytest.ini`, `tests/conftest.py`, `tests/smoke/**`, `frontend/*`, `frontend/public/**`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/vite-env.d.ts`, `frontend/src/api/**`, `.github/workflows/stack-ci.yml`, `README.md`), the written allow list contains an `Edit` and a `Write` grant for every one of those globs, and no WARN is printed for any of them.

## Out of scope

- Deriving `Bash(...)` command grants from the FR (for example `uv`, `npm`, `alembic`, `docker compose`). Tool-command grants stay static per role; a stack-aware command allow-list is the archived IDEA-0015 theme and would be its own FR — that FR is FR-0010 (see DEC-0002).
- Narrowing protected denies into per-file denies for `dev` (AC-2 forbids it). An FR that must touch the control plane is dispatched in `mnt` mode; that is the whole point of the maintainer role.
- Relocating dispatch worktrees out of `.claude/` so harness-guarded paths become writable — IDEA-0031, parked.
- Deriving Read grants from `reads:`. `Read`, `Glob`, `Grep` are already blanket-allowed for every role.
- Changing what `owns:` means, its syntax, or the indexer's validation of it (`spec_footprint.py` is read, not edited).
- Any change to `finalize`, the footprint check on the maintainer branch (`mnt_footprint_violations`), or the rework loop. FR-0006 owns those behaviours and is merged.
- Declared gates and phase-boundary enforcement — FR-0008.
- Retrying or re-prompting an agent that hit a denial. This FR removes the denial; it does not add recovery for denials that remain.

## Open questions

- **Q:** Should the `owns:` grants be written for `.claude/**` globs at all (AC-3), given the harness guards them regardless?
  - **Default:** Write them (consistent with what `mnt` does today) and rely on the WARN. Omitting them would make the settings file lie in the other direction — the Developer would see no grant and might conclude the path is out of scope rather than harness-guarded.
- **Q:** Does a `Write(<glob>)` grant also satisfy the harness's check on Bash output redirection to a matching path? The Project A run had one Bash redirect denied alongside the `Write` denials.
  - **Default:** Assume yes and do not add redirect-specific grants. The Reviewer's dogfood step should include one `Bash(echo x > <owned path>)` probe in a throwaway project; if the harness denies it, record the finding under `## FINDINGS` and leave it for a follow-on FR rather than widening this one.
- **Q:** Should a glob that matches nothing in `git ls-files` (a file the FR will create, like `.python-version`) be granted?
  - **Default:** Yes — that is precisely the create case that failed. Grants are written from the declared globs, never expanded against the tracked file list; `expand_globs` is for overlap detection, not for permissions.
- **Q:** Should `dev`'s static `Edit(*.py)` / `Write(*.py)` root-scratch grants be removed now that `owns:` can express them?
  - **Default:** No. AC-1 and AC-4 keep the static list intact so that projects whose FRs have sparse or empty `owns:` are not regressed. Tightening the static list is a separate decision with its own evidence.

## Dependencies

None hard. `extends: [FR-0006]` records that this generalises the maintainer derivation FR-0006 relied on; FR-0006 is merged. FR-0008 (ready) also owns `template/scripts/dispatch.py`; see Notes for sequencing.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file; this FR is dispatched in `mnt` mode with the `owns:` above as the write surface, and the human's approval of this FR is the approval for that edit. The hub-tooling AGENTS.md caveat applies: edit `../../template/scripts/dispatch.py`, never this project's bootstrap-output copy.
- **Reuse, don't fork.** The derivation exists: `fr_owns_globs`, `mnt_permission_rules` (its `granted` half), `mnt_unwritable_grants`, `mnt_unwritable_hint`, and the `MNT_PROTECTED_GLOBS` / `MNT_NEVER_WRITABLE` / `HARNESS_GUARDED_GLOBS` constants. The Developer path needs the *grant* half of `mnt_permission_rules` and must discard the *protected_denies* half (AC-2). Factor accordingly rather than duplicating the glob logic.
- **Where it plugs in.** `ensure_role_worktree` calls `adapter.write_worktree_settings(wt_path, role, fr_id)` on both the create and the reuse path, which is why AC-6 comes for free if the derivation lives inside `write_worktree_settings` (or a helper it calls) rather than at worktree creation.
- **Footprint overlap with FR-0008.** Both own `template/scripts/dispatch.py`. This FR is small and unblocks the Project A build lane; the recommended order is FR-0009 first, then FR-0008 rebases (the "rebase-and-revalidate" pattern in the architect role file). The Chief of Staff sequences; the overlap is not tool-detected from this directory (AGENTS.md, Hub-tooling specifics 4).
- **Reviewer dogfood step (AGENTS.md).** Bootstrap a throwaway project from the modified template, add a fixture FR whose `owns:` includes a root dotfile and a `frontend/**` glob, run `dispatch.py tick --role dev --fr <FR> --dry-run` and confirm the `owns-grants=<n>` line and that no settings file was written; then `--apply` far enough to inspect the written `.claude/settings.local.json`, and run the redirect probe from the open questions.
- **Evidence.** Project A `_dispatch/FR-0001.dev.log` (2026-09-20, three `permission_denied` events on `.python-version`, one on a Bash redirect, turn ended with a request for human approval); Project A `_dispatch/wave-2026-09-20T18-27-26+00-00.md` (dropped at dev-evaluate); Project A `_dispatch/learnings-FR-0001-wave.md` L5.

## Changelog

- 2026-09-20: created from Project A learnings L5 (FR-0001 wave dropped on static allow-list vs `owns:` mismatch)
- 2026-09-20: human approved the control-plane edit to `template/scripts/dispatch.py` (maintainer-mode dispatch authorised)
- 2026-09-21: v2 — DEC-0002 (breaking: true): AC-9's `rev`/`bkf` byte-identity narrowed to an FR with no `owns:` (FR-0010 AC-5 extends the derivation to those roles); AC-4/AC-9 pre-FR comparisons scoped to a no-stack project. Four `test_dispatch_permissions.py` parametrisations narrowed per the DEC's cascade in FR-0010's Reviewer phase.
