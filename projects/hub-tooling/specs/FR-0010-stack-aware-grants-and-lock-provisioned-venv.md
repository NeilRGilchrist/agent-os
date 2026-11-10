---
id: FR-0010
title: Stack-aware Bash grants, `owns:`-derived write grants for `rev`/`bkf`, and a dispatch venv provisioned from the project's lock
status: merged
owner: architect
depends_on: [FR-0009]
tags: [dispatch, harness, control-plane, footprint, stack, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/stack_profile.py
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_stack_profile.py
  - template/tests/unit/scripts/test_dispatch_stack_grants.py
  - template/tests/fixtures/stack-profile/**
  # v2 (DEC-0003): the schema row for `worktree_status` (one row; FR-0008 also owns this file and rebases last).
  - template/specs/_metrics/README.md
  # v2 (DEC-0002): write bounded to the four parametrisations DEC-0002's cascade names; nothing else in the file.
  - template/tests/unit/scripts/test_dispatch_permissions.py
reads:
  - template/scripts/spec_footprint.py
  - template/scripts/metrics_log.py
  - template/.agent-team/roles/developer.md
  - template/.agent-team/roles/reviewer.md
  - template/.agent-team/commands/maintainer.md
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - scripts/bootstrap.py
derived_from: IDEA-0065
pattern: null
ac_state: {}
version: 5
lifecycle: live
revisions: [DEC-0003, DEC-0005, DEC-0014, DEC-0020]
last_breaking_revision: 5
supersedes: null
superseded_by: null
extends: [FR-0009]
serves_roles: [developer, reviewer, orchestrator]
solution_space:
  open:
    - Whether stack detection lives in a new `template/scripts/stack_profile.py` or inside `dispatch.py`, as long as the detector is importable and testable without spawning anything. The `owns:` above assumes the separate module (architect role file, "extract-and-land-first").
    - Exact wording of the `STACK` / `WARN` / `VENV` lines, as long as each carries the identifiers the ACs name.
    - Whether the lock-based venv install shells out to `uv sync`, `uv pip sync` or `uv pip install -r`, as long as AC-8's determinism and AC-9's soft-fail hold.
  fixed:
    - "Detection is read-only: reading marker files and frontmatter. Nothing is executed, resolved, downloaded, or installed to decide what the stack is."
    - "Tool id -> Bash grant is a closed table in the dispatcher. A name the table does not know never produces a grant, whatever declares it."
    - Role deny lists still win. A stack grant never un-denies a path grant, and never re-grants a path a role is denied.
    - "Dry-run (`apply=False`) mutates nothing: no venv created, no settings file written."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-20
updated: 2026-09-25
---

> **Provenance:** Drafted 2026-09-20 by the hub-tooling Architect from IDEA-0065 (Chief of Staff triage of the Project A FR-0001 wave, promotion confirmed by Neil 2026-09-20) and IDEA-0032 (the `.venv-dispatch` provisioning gap, parked 2026-08-12 from the ai-hub-poc FR-0058 maintainer run), grounded in Project A `_dispatch/learnings-FR-0001-wave.md` L5, L18, L20, L34, L39 and `_dispatch/FR-0001.mnt-brief-round2.md`. · source_class: neil_position+agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0010: Stack-aware Bash grants, `owns:`-derived write grants for `rev`/`bkf`, and a dispatch venv provisioned from the project's lock

## Why

FR-0009 fixes *which files* a dispatched Developer may write. It leaves untouched *which commands* any role may run, and it leaves `rev` and `bkf` on the static write surface. The Project A FR-0001 wave shows what remains after FR-0009 lands. No role's Bash allow-list contains `uv`, `npm`, `npx`, `node`, `docker` or `alembic` — the entire stack Project A's own ADR declares — so the dispatcher-spawned Reviewer was denied `uv sync`, `docker` and `npm ci`, built a non-lock-exact pip venv on the wrong Python, skipped 11 environment-dependent tests, and missed two real defects that only surfaced in round 2 when Docker and npm happened to be available (L18, L20). `MNT_BASH_DENIES` denies `uv`, `node` and `npx` outright, so the maintainer chore PR could not regenerate `uv.lock` or run the suite and stopped with an escalation (L39); today's round-2 maintainer attempt stopped again, this time on a denied `pip install` into `.venv-dispatch`. And `ensure_dev_venv` installs a fixed `pyyaml,ruff,pytest` regardless of the project, which is IDEA-0032's defect verbatim: the venv the dispatcher provisions cannot import the project's own dependencies, so an agent told by `AGENTS.md` rule 6 to run the gate before claiming done cannot run the suite at all, and either reports an unverifiable result or spends its turn trying to install packages it is denied. Each of those is a whole dispatched phase lost: three of three spawns in the FR-0001 wave failed on permissions, and the environment-blind Reviewer round hid two of five round-2 defects.

## What

After this FR lands, the dispatcher reads the project's declared stack from its own files — `pyproject.toml`, `uv.lock`, `requirements.txt`, `package.json` and its lockfiles, `docker-compose*.yml`, `alembic.ini` — plus any `stack_tools:` an accepted ADR declares, maps each recognised tool through a closed table to a small set of Bash grants, and unions those grants into every role's allow-list. `rev` and `bkf` gain the `owns:`-derived `Edit`/`Write` grants FR-0009 gave `dev`, with each role's own deny list still winning. `uv`, `node` and `npx` leave the maintainer deny-list when the stack declares them and stay denied when it does not. And the worktree venv is provisioned from the project's lock rather than from a hard-coded package list, so a dispatched agent of any role can run the project's tests without installing anything. A project that declares no stack behaves exactly as it does today.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Stack detection is a pure, read-only function over marker files.** `detect_stack(repo_root)` returns a sorted, de-duplicated list of tool ids drawn from a closed vocabulary, decided only by reading files: `pyproject.toml` present -> `python`; `uv.lock` present -> `uv`; `requirements.txt` present and no `uv.lock` -> `pip`; `package.json` present -> `node`, `npm`, `npx`; `pnpm-lock.yaml` -> `pnpm`; `yarn.lock` -> `yarn`; any `docker-compose*.y[a]ml` or `compose.y[a]ml` -> `docker`; `alembic.ini` -> `alembic`. It executes nothing, spawns no subprocess, opens no socket, and never writes. A repo root with none of these markers returns `[]`. Verified against fixture trees for: empty, python-only, uv+python, node-only, python+node+compose, and a tree whose `pyproject.toml` is unparseable (returns `python` and no error). **Revised by DEC-0020 (v5, breaking):** a `package.json`, `pnpm-lock.yaml` or `yarn.lock` in an immediate subdirectory of the root implies the same tools as at the root. The subdirectory must be a real directory (not a symlink), must not be a dot-directory, and must not be `node_modules`. Every other marker stays root-only, and detection still reads the primary checkout (DEC-0014 Decision 4). Implemented by FR-0017.

- **AC-2:** **Declared tools are unioned in from an accepted ADR and from the environment, and unknown names are dropped with a warning.** In addition to AC-1's markers, `detect_stack` unions: every entry of a `stack_tools:` list in the frontmatter of any `specs/decisions/ADR-*.md` whose `status` is `accepted`, and every comma-separated entry of `DISPATCH_STACK_TOOLS`. An entry that is not in the closed vocabulary is not returned and produces exactly one `WARN` line naming the entry and its source (the ADR id, or the env var). A `stack_tools:` that is not a list of strings is ignored with one `WARN` naming the ADR. Verified with an accepted ADR declaring `[uv, docker, kubectl]` (returns `uv`, `docker`; one WARN for `kubectl`), a `proposed` ADR declaring `[docker]` (contributes nothing), and `DISPATCH_STACK_TOOLS="npm, nonsense"`.

- **AC-3:** **Tool id to Bash grant is a closed table; nothing else can widen the allow-list.** A module-level mapping turns each vocabulary tool id into a fixed tuple of Claude-Code Bash patterns (for example `uv` -> `Bash(uv *)`, `node` -> `Bash(node *)`, `npm` -> `Bash(npm *)`, `npx` -> `Bash(npx *)`, `docker` -> `Bash(docker *)`, `alembic` -> `Bash(alembic *)`). `stack_bash_grants(tools)` returns the union, sorted and de-duplicated, and returns `[]` for `[]`. A tool id absent from the table yields no grant even if it reaches the function. No grant produced by this table is a path grant (`Edit(...)` / `Write(...)`), and none contains a shell metacharacter beyond the trailing ` *`. Verified by asserting the returned set for each vocabulary entry and that `stack_bash_grants(["kubectl"]) == []`.

- **AC-4:** **Every role's allow-list unions the stack grants; deny still wins.** For each of `dev`, `rev`, `bkf` and `mnt`, the permission file `write_worktree_settings` writes contains every entry of that role's pre-FR static `allow` list unchanged, plus every AC-3 grant for the detected stack. A stack grant that is also present in that role's `deny` list is still written to `allow` and still present in `deny` (deny beats allow in the harness; the settings file is not silently edited to hide the conflict), except where AC-6 removes the deny. No role's `deny` list gains or loses an entry because of stack detection. Verified for all four roles against a python+uv+node+docker fixture.

- **AC-5:** **`rev` and `bkf` derive `Edit`/`Write` grants from `owns:` exactly as FR-0009 does for `dev`.** Given an FR with a non-empty `owns:`, the permission files for `rev` and `bkf` contain `Edit(<glob>)` and `Write(<glob>)` for every glob in `owns:` that FR-0009's AC-2/AC-3 withholding rules do not withhold, computed by the same helper FR-0009 factored out. The role's own path denies still win and are written unchanged: an `owns:` containing `src/**` produces the grant *and* leaves `Edit(src/**)`/`Write(src/**)` in `rev`'s deny list, and an `owns:` containing `specs/**` leaves `bkf`'s `specs/**` deny in place. Withheld globs produce one `WARN` line each, as FR-0009 AC-2 specifies. An FR with empty `owns:` yields permission files byte-identical to the pre-FR ones for these two roles.

- **AC-6:** **`uv`, `node` and `npx` leave `MNT_BASH_DENIES` when — and only when — the stack declares them.** The maintainer deny list is computed per spawn: for each of `uv`, `node`, `npx`, the corresponding `Bash(... *)` deny is omitted when that tool id is in the detected stack and present otherwise. Every other entry of `MNT_BASH_DENIES` is unchanged in every case — in particular `Bash(pip *)`, `Bash(bash *)`, `Bash(sh *)`, `Bash(powershell *)`, `Bash(python -c*)`, `Bash(tee *)`, `Bash(sed -i*)`, `Bash(cp *)` and `Bash(mv *)` are still denied to `mnt` whatever the stack says. Verified with a uv+node fixture (three denies absent, all others present, order otherwise preserved) and a marker-less fixture (deny list byte-identical to today's).

- **AC-7:** **The spawn report names the detected stack.** The line the dispatcher prints for a spawn — or a line immediately preceding it — carries `stack=<comma-separated tool ids>` (`stack=none` when empty) and `stack-grants=<n>`. In dry-run the same information appears on the `WOULD-SPAWN` line or the line immediately preceding it. **Revised by DEC-0003 (v2, breaking):** the `dispatch.spawn` metrics record's `worktree_status` value is the pre-FR base status (`created` | `reused`) followed, **only when the detected stack is non-empty**, by one comma-separated segment `stack=<ids joined by '+'>`; when the stack is empty nothing is appended and the value is byte-identical to the pre-FR record (`stack=none` is a console spelling, never a metrics one). No new metrics field or record kind is introduced and `metrics_log.py` is not edited; the `worktree_status` row of `template/specs/_metrics/README.md` documents the optional segments and their order (`stack=`, then AC-9's `venv=`, then FR-0011's `preflight=`). The v1 text appended the segment unconditionally, which contradicted AC-12 and FR-0002's schema (`created` | `reused`).

- **AC-8:** **The dispatch venv is provisioned from the project's lock.** `ensure_dev_venv(wt_path)` installs the project's own dependencies before the agent starts: with `uv.lock` present it syncs from that lock; with `requirements.txt` (or a `requirements*.lock`) and no `uv.lock` it installs from that file; with neither it installs today's `VENV_PACKAGES`. In every case the dispatcher's own tooling (`VENV_PACKAGES` — `pyyaml`, `ruff`, `pytest`) is present in the venv afterwards, so a project that does not depend on pytest still gets a runnable gate. Verified in a temporary project fixture by asserting that a package named only in the lock is importable from the provisioned interpreter and that `pytest` is importable in all three cases.

- **AC-9:** **Provisioning failure is a soft failure that is reported, never a spawn abort.** When any provisioning step fails or `uv` is absent, `ensure_dev_venv` returns `(False, "<classification>")` with the classification drawn from a closed set (`uv-not-found`, `venv-create-failed`, `lock-sync-failed`, `requirements-install-failed`, `packages-install-failed`), `ensure_role_worktree` still returns the worktree path with the classification in its status string as it does today, the spawn proceeds, and exactly one `WARN` line names the classification and the lock or requirements file it was reading. The agent is never left with a half-built venv silently. **Revised by DEC-0003 (v2, breaking):** when provisioning failed, the `dispatch.spawn` record's `worktree_status` carries one additional comma-separated segment `venv=<classification>` — the closed-set classification alone, never the `:`-suffixed detail `ensure_dev_venv` may attach — placed after AC-7's `stack=` segment when that is present; on success (`venv-created`, `venv-reused`, `venv-resynced`) no `venv=` segment is written, so the success-path record is unchanged. The lock file keeps the full status string as today. (The v1 sentence assumed the record carried the lock's full string; since FR-0002 it carries the base status only.) **Revised by DEC-0005 (v3, breaking):** this AC is the provisioner's contract and holds for every spawn that reaches `ensure_dev_venv`. Whether a spawn is reached at all when the *declared* stack's `uv` is absent from the host is FR-0011's decision, not this AC's: FR-0011 AC-3/AC-6 block `wave`/`tick`/`maintain` at the environment pre-flight gate on a declared-but-missing `uv` (overridable and recorded via `--skip-env-preflight`, FR-0011 AC-8), before any worktree or venv exists. The soft-fail here remains the behaviour wherever `ensure_dev_venv` runs without `uv` — a project whose stack does not declare `uv` (the provisioner needs `uv` to create any venv, lock or not), a skipped pre-flight, `backfill` (which runs no environment gate), and direct `spawn_role` callers. The tests that pin this AC through `cmd_tick` run with FR-0011's pre-flight seam stubbed (DEC-0005 cascade), so they exercise this layer alone and never depend on the test host's PATH, Docker daemon or Windows policy.

- **AC-10:** **Provisioning is idempotent and bounded.** A second `ensure_dev_venv` against a worktree whose venv already exists and whose lock file is unchanged since provisioning re-installs nothing and returns `(True, "venv-reused")`. A lock file whose content hash differs from the one recorded at provisioning time re-syncs and returns `(True, "venv-resynced")`. Every subprocess the function runs carries an explicit timeout. Verified by provisioning, touching the lock with identical content (reused), then changing it (resynced).

- **AC-11:** **The Cursor adapter applies the same derivation.** `CursorAdapter.write_worktree_settings` writes AC-4's stack grants, AC-5's `owns:` grants and AC-6's maintainer deny computation in that adapter's permission syntax, with identical withholding. Verified with the same python+uv+node+docker fixture as AC-4.

- **AC-12:** **A project that declares no stack is byte-identical to today, and dry-run mutates nothing.** For a fixture repo with no stack markers, no `stack_tools:` ADR and no env override, every role's permission file equals the file the pre-FR dispatcher writes, `ensure_dev_venv` behaves exactly as before, and **(DEC-0003, v2)** the `dispatch.spawn` record's `worktree_status` is exactly the pre-FR value (`created` | `reused`) whenever the venv provisioned, so FR-0002's `test_dispatch_metrics.py` passes unchanged. Without `--apply`, `tick` / `wave` / `maintain` print the AC-7 lines but create no venv and write no settings file: the worktree tree (where one exists) is byte-identical before and after. Every test that passed before this FR still passes, including FR-0009's permission suite.

## Out of scope

- Detecting whether a declared tool is actually installed, reachable, or healthy. That is pre-flight — FR-0011, which consumes this FR's detector.
- Any change to what `owns:` means, its syntax, or `spec_footprint.py`'s validation of it.
- Granting `dev` its `owns:`-derived write grants — FR-0009 does that; this FR reuses the helper and extends the roles it is applied to.
- Deriving Read grants from `reads:`. `Read`, `Glob` and `Grep` remain blanket-allowed for every role.
- Running the agent's builds in a container or WSL so the host's toolchain stops mattering (Project A learnings L11(c); parked as IDEA-0064).
- Relaxing any deny other than the three AC-6 names. In particular `pip` stays denied to `mnt`: AC-8 removes the reason a maintainer would reach for it.
- Recording the stack in the spec graph, `hub/projects.yaml`, or `.agent-team/`. Detection is per-spawn and file-derived; no new persisted schema.
- Declared gates and phase-boundary enforcement — FR-0008.
- The headless conduct text that tells an agent what to do when a grant is still missing — FR-0012.

## Open questions

- **Q:** Where should a project declare a tool the markers cannot reveal (a system binary an ADR mandates)?
  - **Default:** AC-2's two channels — `stack_tools:` in an accepted ADR's frontmatter (the durable, reviewable one) and `DISPATCH_STACK_TOOLS` (the operator escape hatch). No new file, no `.agent-team/` change, so nothing further needs human approval.
- **Q:** Should `Bash(docker *)` be granted at all, given a container can mount the repo and write denied paths?
  - **Default:** Yes when the stack declares compose. The threat already exists through `Bash(python *)` for `dev`, and the alternative — a Reviewer that cannot bring up the stack — cost two hidden defects in the FR-0001 wave. `mnt`, whose deny list is the one that actually guards the control plane, gets `docker` only through AC-4's union and keeps every AC-6 deny; if the Reviewer's dogfood probe shows a container can reach a denied path, record it under `## FINDINGS` and let the Architect narrow the table.
  - **Resolved 2026-09-25 (DEC-0014).** The probe fired: the FR-0010 Reviewer wrote a denied path through a bind mount (finding (e)). The table is **not** narrowed. For `mnt`, docker is one of at least five code-executing grants that reach the same paths: `uv run python -c` (AC-6 lifts the `uv` deny), `alembic`, the `node`/`npx`/`npm` grants, and the sanctioned `python -m pytest` over owned code. Narrowing command grants cannot make `mnt`'s surface a boundary. The control-plane boundary is the artifact-level check at finalize, which FR-0015 completes, plus the human merge. The default stands for every role. Docker is re-decided when a process sandbox lands (IDEA-0064), because it is the one grant such a sandbox would not confine.
- **Q:** Should the venv sync use the lock's own Python version rather than `VENV_PYTHON_VERSION`?
  - **Default:** No. Keep `VENV_PYTHON_VERSION` (and `.python-version` when `uv` honours it on its own). Pinning from the lock is a second decision with its own failure modes; AC-8 only requires that the project's dependencies import.
- **Q:** Should an unrecognised `stack_tools:` entry fail the spawn rather than warn?
  - **Default:** Warn and continue (AC-2). A typo in an ADR should not stop a wave, and the missing grant surfaces as a denial the agent reports.

## Dependencies

- **FR-0009** — hard. This FR reuses the `owns:`-to-grant helper FR-0009 factors out of `mnt_permission_rules`, and AC-5 is defined as "what FR-0009 does for `dev`, for `rev` and `bkf`". Both own `template/scripts/dispatch.py`; FR-0009 lands first.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file; this FR is dispatched in `mnt` mode with the `owns:` above as the write surface, and the human's approval of this FR is the approval for that edit. `template/scripts/stack_profile.py` is a new file under `template/scripts/` and is not one of the four named protected scripts, but it is created in the same maintainer run. The hub-tooling AGENTS.md caveat applies: edit `../../template/**`, never this project's bootstrap-output copy.
- **IDEA-0032 is the venv half.** AC-8/AC-9/AC-10 are IDEA-0032 ("`.venv-dispatch` cannot collect tests, so dispatched agents cannot self-verify", parked 2026-08-12 from the ai-hub-poc FR-0058 run: `No module named pydantic` in the dispatch venv while the ambient interpreter ran the same suite green). It is promoted into this FR alongside IDEA-0065 because the two share `ensure_dev_venv` and the maintainer deny list — splitting them would put two FRs on the same function. `derived_from:` carries IDEA-0065; IDEA-0032's `promoted_to` points here too.
- **Reuse, don't fork.** The grant derivation is FR-0009's (`fr_owns_globs`, the `granted` half of `mnt_permission_rules`, `mnt_unwritable_grants`, `mnt_unwritable_hint`). This FR adds a detector and a table and changes which roles the existing derivation is applied to; it does not re-implement glob logic.
- **Revisions (v2, 2026-09-21).** DEC-0003 fixed the metrics contract for `worktree_status` (AC-7, AC-9, AC-12: optional segments only when non-empty; a no-stack, healthy-venv record is byte-identical to today) after the round-1 implementation at `82a9467` appended `,stack=` unconditionally and broke two FR-0002 tests. DEC-0002 narrowed FR-0009 AC-9 so that AC-5 could land: the FR-0010 Reviewer is authorised to narrow exactly the four `test_dispatch_permissions.py` parametrisations DEC-0002's cascade names (`[rev]`/`[bkf]` of `test_non_dev_role_settings_files_are_byte_identical_to_pre_fr` and `test_static_roles_still_write_exactly_their_static_payload` run against an FR with empty `owns:`), and nothing else in that file. `test_dispatch_metrics.py` is read, not owned: it must pass unchanged.
- **Revisions (v3, 2026-09-21).** DEC-0005 scoped AC-9 to the provisioner's layer after FR-0011's pre-flight gate (correctly) stopped a `uv`-declaring tick before `ensure_dev_venv` was reached, failing `test_uv_absent_spawn_proceeds_with_one_warn_naming_classification_and_lock`, and after FR-0011's `preflight=` segment reached the record `test_env_declared_stack_reaches_console_and_record_with_plus_joined_ids` pins exactly. Neither assertion changes: the fix is that `test_dispatch_stack_grants.py`'s `_point` harness stubs `env_preflight.run_preflight` (the seam FR-0011 AC-9 v2 states), which also takes the eight `stack_repo` tests that drive `cmd_tick`/`cmd_wave`/`cmd_oneshot` off the host — before DEC-0005 they ran `docker info` and a PowerShell policy query and failed on any host without a reachable Docker daemon. The FR-0011 Reviewer makes that one bounded edit (DEC-0005 cascade); this FR's `owns:` is unchanged.
- **Revisions (v4, 2026-09-25).** DEC-0014 (neil, non-breaking) resolves the second Open question after the Reviewer's finding (e): `Bash(docker *)` stays granted to every role, `mnt` included, and the DEC records the threat model later grant decisions cite. The DEC also rules the Reviewer's finding (g) by design: detection reads `REPO_ROOT`, not the worktree, so a branch cannot grant itself tools by committing a marker or a `stack_tools:` ADR. Finding (a), the malformed-`owns:` refusal only for `dev`, is FR-0015 AC-5. No AC text, code, test or `owns:` change here.
- **Where it plugs in.** `ensure_role_worktree` already calls `adapter.write_worktree_settings(...)` then `ensure_dev_venv(...)` on both the create and the reuse path, so AC-4..AC-6 and AC-8..AC-10 land inside those two functions and reach every entry point for free.
- **Footprint overlap.** FR-0008, FR-0009, FR-0011 and FR-0013 all own `template/scripts/dispatch.py`. Recommended order: FR-0009 -> FR-0010 -> FR-0011 -> FR-0013, with FR-0008 rebasing last (the "rebase-and-revalidate" pattern in the architect role file). FR-0012 touches no dispatcher code and can run beside them. The Chief of Staff sequences; the overlap is not tool-detected from this directory (AGENTS.md, "Hub-tooling specifics" 4).
- **Reviewer dogfood step (AGENTS.md).** Bootstrap a throwaway project from the modified template, give it a `pyproject.toml` + `uv.lock` + `package.json` + `docker-compose.yml`, run `dispatch.py tick --role rev --fr <FR> --dry-run` and confirm the `stack=` / `stack-grants=` line and that nothing was written; then `--apply` far enough to inspect `.claude/settings.local.json` and the provisioned venv, and probe whether a granted `Bash(docker *)` can reach a denied path (open question 2).
- **Evidence.** Project A `_dispatch/learnings-FR-0001-wave.md` L5 (static allow-list vs `owns:`; Bash allow has no stack tool), L18 and L20 (Reviewer's pip-venv workaround, 11 skipped tests, two hidden defects), L34 (subagent path loses the worktree deny list), L39 (`uv` in `MNT_BASH_DENIES` stopped the chore PR); `_dispatch/FR-0001.mnt-brief-round2.md` provenance (round-2 `maintain` stopped on a denied `pip install` into `.venv-dispatch`); IDEA-0032 originating context (ai-hub-poc FR-0058, 2026-08-12).

## Changelog

- 2026-09-20: created from IDEA-0065 (+ IDEA-0032 for the venv half); promoted in the wave-1 Architect session Neil confirmed 2026-09-20
- 2026-09-21: v2 — DEC-0003 (breaking: true): AC-7/AC-9/AC-12 — `dispatch.spawn` `worktree_status` gains `stack=` / `venv=` segments only when non-empty; no-stack record byte-identical to today. `owns:` gains `template/specs/_metrics/README.md` and (bounded by DEC-0002) `template/tests/unit/scripts/test_dispatch_permissions.py`; `test_dispatch_metrics.py` moved to `reads:`.
- 2026-09-21: v3 — DEC-0005 (breaking: true): AC-9 scoped to the provisioner's layer — a declared-but-missing `uv` is FR-0011's pre-flight gate's decision; the soft-fail governs wherever `ensure_dev_venv` is reached. `test_dispatch_stack_grants.py` runs with FR-0011's pre-flight seam stubbed (one bounded harness edit, FR-0011 Reviewer); no assertion, code or `owns:` change.
- 2026-09-25: v4 — DEC-0014 (breaking: false): second Open question resolved. Docker stays granted to every role, including `mnt`. `mnt`'s command narrowing is friction; the control-plane boundary is the finalize check (completed by FR-0015) plus the human merge. Reviewer finding (g) ruled by design. No AC text, code, test or `owns:` change.
- 2026-09-25: v5 — DEC-0020 (breaking: true): AC-1 detects node markers (`package.json`, `pnpm-lock.yaml`, `yarn.lock`) one level below the primary checkout's root, excluding dot-directories, `node_modules` and symlinks; every other marker stays root-only. Implemented by FR-0017; the test cascade is one `test_marker_rules_boundaries` case.
