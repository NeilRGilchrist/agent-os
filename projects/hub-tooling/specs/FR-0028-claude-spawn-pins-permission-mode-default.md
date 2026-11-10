---
id: FR-0028
title: The Claude Code adapter starts every role with an explicit `--permission-mode default`, so the worktree's permission file is the whole policy whatever the host's `defaultMode`, and nothing else the dispatcher emits changes
status: merged
owner: architect
depends_on: [FR-0024]
tags: [dispatch, harness, permissions, control-plane, security, template]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics" and
# `.agent-team/layout.yaml`: `footprint_root: repo`).
owns:
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_dispatch_permission_mode.py   # new: this FR's pin, override and byte-identity tests
reads:
  - template/tests/unit/scripts/test_dispatch_subdirectory.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_gates.py
  - template/tests/unit/scripts/test_dispatch_postapprove.py
  - template/tests/unit/scripts/test_merge_friction_adversarial.py
  - template/tests/unit/scripts/test_windows_text_io.py
  - template/.agent-team/commands/developer.md
  - template/.agent-team/commands/reviewer.md
  - template/.agent-team/commands/reviewer-backfill.md
  - template/.agent-team/commands/maintainer.md
  - template/.agent-team/commands/gate-review.md
  - projects/hub-tooling/specs/FR-0024-subdirectory-aware-dispatcher.md
  - projects/hub-tooling/specs/decisions/DEC-0031-fr0024-revalidated-against-wave2-merges.md
gates: []
derived_from: IDEA-0098
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0009, FR-0024]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - "Where the value lives (a module constant, a `ClaudeCodeAdapter` class attribute, or a literal in `spawn`), and its name, as long as it is read by `ClaudeCodeAdapter.spawn` only and AC-2 holds."
  fixed:
    - "The value is the literal `default`, the same for every role. No other mode (`auto`, `acceptEdits`, `plan`, `bypassPermissions`, `dontAsk`) is ever passed."
    - "The two tokens sit immediately after `--verbose` and before `--model`, so the argv order is fixed (AC-1)."
    - "No environment variable, CLI flag, settings key or FR field changes the value (AC-2)."
    - "`CursorAdapter`, both adapters' `dry_run_preview`, every permission file, every printed line and every metrics record are byte-identical to the base ref's (AC-3). No new metrics record kind or field."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-11-04
updated: 2026-11-05
---

> **Provenance:** Drafted 2026-11-04 by the hub-tooling Architect, dispatched by the hub's Chief of Staff, from IDEA-0098 (FR-0024 r1 finding F-5). Grounded in a read of:
> - `template/scripts/dispatch.py`: `ClaudeCodeAdapter.spawn`, `dry_run_preview`, `ROLE_PERMISSIONS`, `mnt_permissions`, `dev_permissions`, `gat_permissions`, `_mnt_bash_allow`, `_resolve_model`, `ROLE_MODEL`, `CursorAdapter.spawn`, `_finalize_commit_step`;
> - the five headless role commands under `template/.agent-team/commands/` (developer, reviewer, reviewer-backfill, maintainer, gate-review), for the commands each one tells the agent to run;
> - every template test that fakes `subprocess.Popen` around a real `ClaudeCodeAdapter.spawn`, or scans `dispatch.py`'s argv literals;
> - this host's user settings, `permissions` block only;
> - an aggregate scan of 133 dispatched-run logs under the hub's `projects/ai-hub-poc/_dispatch/` (2026-05-28 to 2026-09-04): session-init `permissionMode`, result subtype, and the tool name and first command word of each `permission_denials` entry. Nothing else was read from those logs.
>
> · source_class: neil_position+agent_observation · role: architect · model: opus · ip_class: hub_original.

# FR-0028: The Claude Code spawn pins `--permission-mode default`

## Why

The dispatcher's isolation model is that each role's `.claude/settings.local.json` in its worktree is the whole permission policy. Allowed paths and commands go ahead. Everything else is refused at the moment the agent tries it.

`ClaudeCodeAdapter.spawn` passes no `--permission-mode`. The session therefore takes the mode from the host's settings. This host's user settings say `defaultMode: auto`. Under auto mode, an edit or command that the worktree file neither allows nor denies goes to the auto-mode classifier and may be approved, so the footprint is open. Whether a role's footprint is closed then depends on host configuration, not on the dispatcher. A violation surfaces only at finalize, when the footprint and control-plane checks (FR-0009, FR-0015) refuse the branch, after the work is spent.

FR-0024 r1 found this as F-5, outside FR-0024's scope. Its AC-5 live run had to pass `--permission-mode default` by hand to get a clean answer. With that flag, the run refused the unowned edit and left the file unchanged. `permission_denials` named the `Edit` (Neil, 2026-11-04; DEC-0031 item 12; FR-0024 Notes, "Result").

So the flag works headlessly, refuses cleanly, and is one argv token pair. This FR makes the dispatcher pass it. The worktree file is then the whole policy again, on any host.

## What

After this FR, every Claude Code session the dispatcher starts carries `--permission-mode default`, for every role. That covers `dev`, `rev`, `bkf`, `mnt` and `gat`, and any role added later. The value is fixed and cannot be overridden. Everything else is unchanged:
- the rest of the argv;
- the Cursor adapter;
- the dry-run preview text;
- every permission file;
- every printed line;
- every metrics record.

A pin test fails if the flag is dropped, moved or changed.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Every Claude Code spawn carries `--permission-mode default` at a fixed place.**
  - **The argv:** `ClaudeCodeAdapter.spawn` hands `subprocess.Popen` exactly this list, with `<model>` being `_resolve_model(role)`:
    - `[<claude binary>, "-p", <prompt>, "--output-format", "stream-json", "--verbose", "--permission-mode", "default"]`;
    - followed by `["--model", <model>]` when `<model>` is not `None`, and by nothing when it is `None`.
  - **Exactly once:** `"--permission-mode"` occurs once in the argv, and the next element is `"default"`.
  - **Unchanged:** `<prompt>` is built as today, and so are the other `Popen` arguments (`cwd`, `stdout`, `stderr`, `stdin`, `close_fds`) and the return value `("spawned", <pid>)`.
  - **The double:** monkeypatch `dispatch.shutil.which` to return a synthetic binary path. Monkeypatch `dispatch.subprocess.Popen` with a fake that records its positional argv and keyword arguments and returns an object with a `pid`. This is the seam `test_dispatch_subdirectory.py::test_the_claude_harness_is_launched_with_the_project_as_its_cwd` uses. No real `claude` runs.
  - **Verified** across this matrix:
    - each of `dev`, `rev`, `bkf`, `mnt` and `gat`;
    - `gat` with a `gate_id`, which is also the no-`--model` case, because `gat` is absent from `ROLE_MODEL`;
    - one role with an `extra_prompt`;
    - `dev` with `DISPATCH_MODEL_DEV` set, where only the `--model` value changes;
    - prefix `""` and a subdirectory fixture (FR-0024), where only `cwd` differs.

- **AC-2:** **The mode cannot be overridden.** The dispatcher reads the value from no environment variable, CLI flag, settings key or FR field.
  - **Verified:** with each of these set, the argv from AC-1 is unchanged for `dev` and `gat`:
    - `DISPATCH_PERMISSION_MODE=auto`;
    - `DISPATCH_PERMISSION_MODE_DEV=bypassPermissions`;
    - `DISPATCH_PERMISSION_MODE_GAT=acceptEdits`.
  - **Source scan:** `template/scripts/dispatch.py` contains no `DISPATCH_PERMISSION_MODE` substring. The string literal `"--permission-mode"` occurs in it exactly once.

- **AC-3:** **Nothing else changes.** Compared with the base ref's `dispatch.py` (Notes, "Base ref"), loaded as a second module from `git show` and given the same inputs and the same doubles:
  - **Claude Code argv:** deleting the adjacent pair `"--permission-mode", "default"` from this FR's argv gives exactly the base ref's argv. This holds for every case in AC-1's matrix.
  - **Cursor:** `CursorAdapter.spawn`'s argv and `Popen` keyword arguments are equal to the base ref's, for `dev` and `rev`.
  - **Dry-run preview:** `dry_run_preview` returns the same string under both adapters, for `dev` and for `gat` with a `gate_id`. The preview does not mention the mode.
  - **Permission files:** `ClaudeCodeAdapter.write_worktree_settings` writes byte-identical files for `dev`, `rev`, `bkf`, `mnt` and `gat`, at prefix `""`.
  - **Base ref unreachable:** the comparison skips, as FR-0023 AC-7's and FR-0027 AC-4's baseline tests do.
  - **The rest of the suite:** every test that passed before this FR passes unedited. No existing test pins `spawn`'s argv (Open questions, last question), so none needs a change. A pre-existing test that goes red is a `## FINDINGS` line for the Architect, never a test edit.
  - **Metrics:** there is no new metrics record kind or field.

**Annotation.** Template tests ride into every bootstrapped project. Annotate them with the ride-along form `# covers hub-tooling FR-0028:AC-N`, as `.agent-team/layout.yaml` and FR-0023 require. Never use the at-sign form, which would fail every other project's gate as an unknown FR.

## Out of scope

- **The Bash friction default mode already has.** In the logged runs, every role saw some denials:
  - `git -C <path> …`, which no static grant matches;
  - `cd <path> && …` compounds whose `cd` segment is not granted;
  - bare `rm` and PowerShell cmdlets;
  - `git commit` (Open questions).

  The roles recovered from them, and every logged run ended `success`. This FR restores the mode those runs had. It does not widen any grant.
- **`gat`'s missing `git add` grant** (Open questions). It is a pre-existing gap in default mode, ruled out of this FR.
- **Cursor.** It is no longer supported at AlayaCare (Neil, 2026-11-04). It gets no permission-mode work here. AC-3 only proves it is untouched.
- **A configurable mode,** per role or global. See the Open questions.
- **Host settings.** This FR does not edit or read any user, project or managed settings file. The CLI flag takes precedence over `defaultMode` in every settings scope, which is what makes the fix host-independent.
- **The dry-run preview and metrics.** Neither records the mode (AC-3). A `spawn` record field for it would be a new metrics field.
- **hub-tooling's own bootstrap copy** `projects/hub-tooling/scripts/dispatch.py`. It changes only through a refresh or `--upgrade` (Notes, "After merge"). IDEA-0099 covers running the template's scripts directly.

## Open questions

- **Q:** Does any role rely on auto mode today? Would something it needs be refused once default mode is pinned?
  - **Default:** No role relies on it. The pin restores how every role worked before this host switched to auto. The evidence follows.
  - **History:** 133 dispatched runs on this host, from 2026-05-28 to 2026-09-04 (Claude Code 2.1.126), are logged under `projects/ai-hub-poc/_dispatch/`. They cover `dev` 48, `rev` 46, `bkf` 13 and `mnt` 12, plus re-runs. Every one began with `permissionMode: default`, and every one ended with result `success`. Auto mode reached this host after them.
  - **Per role,** each command the role's headless command tells it to run, checked against that role's static grants:
    - **`dev`:**
      - `python3 scripts/deploy-gate.py --stage dev` and `python3 scripts/agent-status.py --fr …` match `Bash(python3 *)`.
      - `git add …`, `git checkout -- specs/_metrics` and `git stash push -m …` match `Bash(git add *)`, `Bash(git checkout *)` and `Bash(git stash*)`.
      - Owned edits are granted from `owns:` (FR-0009; absolute under FR-0024 AC-5).
    - **`rev`:**
      - `python3 scripts/deploy-gate.py --stage full` and pytest (`python -m pytest …`, `pytest …`) match `Bash(python3 *)`, `Bash(python *)` and `Bash(pytest *)`.
      - `git show <sha>:<path>`, `git add tests/` and `git add REVIEW.md` match `Bash(git show*)` and `Bash(git add *)`.
      - hub-tooling's dogfood step (`python ../../scripts/bootstrap.py … --no-register`) and its `template/tests` runs match `Bash(python *)`. Reads of `../../template/**` match the bare `Read` grant and sit under the worktree root, which FR-0024 AC-5 adds to `additionalDirectories`.
    - **`bkf`:** the same surface as `rev` for everything its command runs.
    - **`mnt`:**
      - The gate, the indexer, `agent-status.py` and `dispatch.py` match `_mnt_bash_allow`'s sanctioned entrypoints, as do `-m pytest` and `-m ruff`.
      - `pytest` and `ruff` match their own grants.
      - `git add`, `git checkout` and `git stash` are inherited from `dev`.
    - **`gat`:** the evidence `Edit`/`Write` is granted.
  - **Two things are refused under default mode.** Neither is caused by the pin, and neither blocks a role.
    1. **`git commit`.** This host's user settings carry `ask: Bash(git commit *)`. An ask rule beats every allow, and a headless session cannot answer it, so it is refused. That is the source of the logged `git commit` denials. No role needs to commit: `finalize` commits the staged index for every role (FR-0006 AC-1, `_finalize_commit_step`). `gate-review.md` already says so, and `reviewer-backfill.md`'s `git commit` falls back to the same path.
    2. **`gat`'s `git add specs/_gates/<FR>-<gate>.md`** (`gate-review.md`, "Deliverables"). `gat_permissions` grants no `git add`. On this host the user settings allow `Bash(git add *)`, so it goes ahead under either mode. On a host without that grant, it is refused under default mode. That is today's behaviour on any host not set to `auto`, so the pin does not create the gap.
       - **Ruled out of this FR.** Granting it would change `gat`'s permission file. Two tests pin that file byte-identical to the pre-FR-0024 dispatcher: `test_dispatch_subdirectory.py::test_a_project_rooted_subdirectory_permission_file_is_byte_identical_to_todays[gat]` and its top-level counterpart. The change therefore needs its own FR with its own cascade. No hub-tooling FR declares a gate, so no `gat` spawn is planned.
       - **Proposed follow-up:** the Chief of Staff parks an IDEA, "`gat` is granted `git add` on its one evidence file".
- **Q:** Should there be an environment override, as `DISPATCH_MODEL_<ROLE>` is for models?
  - **Default:** No. The value is fixed at `default` (AC-2).
    - A model override changes how capable an agent is. A permission-mode override changes what the agent may do, and its only uses are to reopen the footprint (`auto`, `acceptEdits`) or to remove it (`bypassPermissions`). Either brings back the defect this FR removes, now through the environment instead of settings.
    - If a role ever needs another mode, that is an FR, with the static grants it implies.
- **Q:** Is the value pinned per adapter? Is Cursor touched?
  - **Default:** It is a Claude Code adapter value only. `CursorAdapter.spawn` and its permission file are byte-identical (AC-3). Cursor is no longer supported at AlayaCare (Neil, 2026-11-04), so it gets no equivalent. AC-3 keeps it from breaking.
- **Q:** At prefix `""`, which existing tests see the new argv tokens? May any of them be updated?
  - **Default:** None needs updating, and none may be updated (AC-3).
    - **The `Popen` double:** the only template test that fakes `Popen` around a real `ClaudeCodeAdapter.spawn` is `test_dispatch_subdirectory.py::test_the_claude_harness_is_launched_with_the_project_as_its_cwd`. It records `Popen`'s keyword arguments (`cwd`) only, not argv.
    - **Fake adapters:** every other spawn path in the suite goes through a test-local fake adapter, which never calls the real `spawn`. That covers permissions, stack grants, env preflight, gates, metrics, runnability, wave finalize, postapprove and nested manifests.
    - **The AST scans** in `test_dispatch_postapprove.py`, `test_merge_friction_adversarial.py` and `test_windows_text_io.py` look at git argv literals and at text and encoding keywords. A new non-git list element touches neither.
    - **Model tests:** `test_dispatch_metrics.py`'s model tests read `_resolve_model` and `ROLE_MODEL`, which are unchanged.

    So `owns:` names no existing test file.

## Dependencies

- **FR-0024** (merged, PR #32): `spawn`'s `cwd` is `_worktree_project_root(wt_path)`, and its AC-5 live run is the evidence that `--permission-mode default` refuses an unowned edit cleanly in a headless run (DEC-0031 item 12). AC-1's subdirectory case reuses FR-0024's fixture shape. No FR-0024 behaviour changes.
- **FR-0009 / FR-0010 / FR-0013 / FR-0015 / FR-0008**: the permission files and finalize backstops this FR makes effective at edit time. None is revised, and every permission file is byte-identical (AC-3).
- **FR-0006**: `finalize` commits the staged index, which is why a refused `git commit` blocks no role.
- **No other FR is active.** Every other hub-tooling FR is `merged` (INDEX, 2026-11-04), so nothing overlaps on `template/scripts/dispatch.py` and this FR is unblocked.

## Notes

- **Dispatch.** This is the first hub-tooling FR dispatched by `dispatch.py wave`.
  - `template/scripts/dispatch.py` is treated as a human-approval file (FR-0024 Notes). Neil ratifies this FR, and approves the edit, by merging the PR that adds it.
  - Under `footprint_root: repo` it is not hub-tooling's own control plane (FR-0024 AC-4), so the Developer gets an absolute grant for it.
  - Edit `template/**`, never this project's bootstrap copies.
  - The sessions that implement this FR are started by the pre-FR dispatcher, so they run under the host's `auto` mode. For them, finalize's footprint checks are the backstop.
- **Base ref.** AC-3 and the bite check compare against `main` at the commit this FR is dispatched from. Pin that SHA in the test as `_BASELINE_REF`, as FR-0023 and FR-0027 do. Load the base ref's `dispatch.py` and its sibling modules with `git show`, as `test_dispatch_subdirectory.py`'s `pre_fr_dispatch` fixture does.
- **Isolation.** No test starts a real `claude` or `cursor-agent`. The seam is `dispatch.shutil.which` plus `dispatch.subprocess.Popen` on the module under test, and on the base-ref module for AC-3. The `stdout` handle `spawn` opens is closed in the test (FR-0024's test shows how). Any FR-0024 fixture repository is synthetic and lives under `tmp_path`.
- **Reviewer, bite check (mandatory).** Run AC-1's pin test against the base ref's `dispatch.py`, loaded as a second module with the same doubles. Show that it fails there, because `"--permission-mode"` is absent. Then mutate this FR's copy in memory three ways and show the pin fails each time:
  1. drop the pair;
  2. change `"default"` to `"auto"`;
  3. move the pair after `--model`.

  Record the three failures and the base-ref failure in `REVIEW.md`.
- **Reviewer dogfood (AGENTS.md).**
  1. Bootstrap a throwaway project from the modified template, with an explicit short path and `--no-register`.
  2. Run its `scripts/index-specs.py --validate` and `scripts/deploy-gate.py`.
  3. Add a synthetic `ready` FR. Run `python scripts/dispatch.py tick`, which is a dry run by default. Confirm that the `WOULD-SPAWN` line has the form `claude -p '/developer <FR>'  (cwd=…; perms via .claude/settings.local.json; model=sonnet)` and does not mention the mode (AC-3).
  4. Delete the throwaway.

  A live headless run is not required, because DEC-0031 item 12 already observed the flag's behaviour.
- **After merge.** hub-tooling's `scripts/dispatch.py` is a bootstrap copy (refreshed by `6e2a268`). The pin reaches hub-tooling's own waves after the next refresh, or after `bootstrap.py --upgrade projects/hub-tooling --yes`. Every other project gets it on its next `--upgrade`.

## Changelog

- 2026-11-04: created (ready) from IDEA-0098 (FR-0024 r1 F-5). The four open questions are settled with defaults:
  - no role relies on auto mode;
  - there is no environment override;
  - the value is pinned in the Claude Code adapter only, and Cursor is untouched;
  - no existing test pins `spawn`'s argv, so `owns:` names none.

  `gat`'s missing `git add` grant is ruled out, with a proposed follow-up IDEA. Neil ratifies by merging the PR that adds this FR.
- 2026-11-05: status `in-progress` → `merged`. PR [#35](https://github.com/NeilRGilchrist/cos-agent-hub/pull/35) merged into `main` as commit `7b803ac`. It was implemented by the first live `dispatch.py wave` in this project (Developer on Sonnet, Reviewer on Opus). The Reviewer hit the 1h phase timeout while running the full template suite, after it had written its Approve review and 61 tests; it was finalized with `finalize --role rev`, and CI's `Validate` job (runs 42057651100, 42057654786: success) stood in for the full suite, with Neil's approval. Recorded by the Chief of Staff: `dispatch.py reconcile-merged` requires the primary worktree on `main`.
