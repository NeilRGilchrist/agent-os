---
id: FR-0029
title: "Dispatcher catch-up from ai-hub-poc: reconcile refuses when local `main` is behind `origin/main`, attributes a non-`claude/*` merged PR by its title scope, the `rev` tick picks up maintainer-only FRs, and `mnt` may write the `specs/` paths it owns and, where the layout says so, its own FR's tests"
status: ready
owner: architect
depends_on: [FR-0024, FR-0028]
tags: [dispatch, reconcile, maintainer, permissions, footprint, layout, template]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics" and
# `.agent-team/layout.yaml`: `footprint_root: repo`). Disjoint from FR-0030's,
# so one `dispatch.py wave --fr FR-0029,FR-0030` can run both Developers.
owns:
  - template/scripts/dispatch.py
  - template/scripts/project_layout.py
  - template/.agent-team/layout.yaml.example
  - template/tests/unit/scripts/test_dispatch_catchup.py          # new: AC-1 to AC-4
  - template/tests/unit/scripts/test_dispatch_mnt_narrowing.py    # new: AC-5 to AC-8
  - template/tests/fixtures/dispatch-mnt-narrowing/**             # new, optional
reads:
  - template/scripts/spec_footprint.py
  - template/scripts/metrics_log.py
  - template/.agent-team/commands/maintainer.md
  - template/tests/unit/scripts/test_dispatch_permission_mode.py
  - template/tests/unit/scripts/test_dispatch_subdirectory.py
  - template/tests/unit/scripts/test_dispatch_permissions.py
  - template/tests/unit/scripts/test_dispatch_grant_hardening.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_gates.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - template/tests/unit/scripts/test_windows_text_io.py
  - template/tests/unit/scripts/test_project_layout.py
  - template/tests/unit/scripts/test_project_layout_adversarial.py
  - projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md
  - projects/hub-tooling/specs/FR-0023-project-layout-footprint-root-and-gate-dirs.md
  - projects/hub-tooling/specs/FR-0024-subdirectory-aware-dispatcher.md
  - projects/hub-tooling/specs/FR-0028-claude-spawn-pins-permission-mode-default.md
  - projects/hub-tooling/specs/decisions/DEC-0031-fr0024-revalidated-against-wave2-merges.md
  - projects/hub-tooling/specs/decisions/DEC-0035-fr0024-ac6-dispatcher-reads-the-layout-at-prefix-empty-for-mnt-own-test-globs-only.md
gates: []
derived_from: null
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0013, FR-0023, FR-0024]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - "How the derivation hands its three deny classes (protected, `tests/test_*.py`, `specs/**`) to the two adapters, as long as AC-8's byte-identity holds."
    - "Whether the title-attributed slot is called `ext` (ai-hub-poc's name) or something else; it is internal."
    - "The exact wording of AC-2's `NOTE` line, as long as it names `origin/main` and `git pull --ff-only`."
  fixed:
    - "The ai-hub-poc names are kept where this FR uses them: `ReconcileSummary.behind_origin`, `MNT_SPECS_NEVER_WRITABLE`, `_mnt_own_test_globs(fr_id)`, `mnt_permission_rules(owns, fr_id=None)`. `fr_id` is optional, so every existing one-argument caller keeps working."
    - "`MNT_PROTECTED_GLOBS`, `MNT_NEVER_WRITABLE`, `HARNESS_GUARDED_GLOBS`, `_owns_entry_protected`, `dev_owns_grants` and `_project_control_plane_path` are unchanged. `specs/**` and `tests/test_*.py` are not added to `MNT_PROTECTED_GLOBS`: that set also drives FR-0009's `dev` withholding and FR-0015's control-plane refusal."
    - "The layout key is `mnt_own_test_globs`, its placeholder is `{num}`, and its default is no globs (AC-6)."
    - "FR-0028's argv, including the one `--permission-mode` literal, is untouched."
    - "No new metrics record kind or field."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-11-05
updated: 2026-11-05
---

> **Provenance:** Drafted 2026-11-05 by the hub-tooling Architect, dispatched by the hub's Chief of Staff, from the Wave 5 gap analysis of ai-hub-poc's upgrade to the current template (2026-11-05). That analysis found 90 ai-hub-poc tests failing after `--upgrade`, 41 of them real template gaps (class C) and 5 partial (class B). This FR is the dispatcher half ("HT-a"); FR-0030 is the role-doc half. Grounded in a read of:
> - `template/scripts/dispatch.py` at `a14b8e6`: `reconcile_merged_prs`, `cmd_reconcile_merged`, `fr_ids_from_pr_title`, `_git_fetch_origin_main`, `_commits_behind_origin_main`, `cmd_tick`, `cmd_wave`, `runnable_review_frs`, `explain_not_runnable`, `_implementation_branch_for_fr`, both adapters' `mnt_permissions`, `mnt_permission_rules`, `mnt_footprint_violations`, `_off_limits_worktree_paths`, `cmd_oneshot`, `ROLE_PERMISSIONS["dev"]`, `_layout_refusal`, `_layout_footprint_root`;
> - `template/scripts/project_layout.py` and `template/.agent-team/layout.yaml.example`;
> - ai-hub-poc's baseline worktree (read-only): its FR-0013, FR-0057, FR-0081 specs, its `scripts/dispatch.py` and its `tests/test_dispatch_reconcile.py`, `test_fr_0057_*.py` and `test_fr_0081_*.py`;
> - every template test that pins a `mnt` permission file or calls the real `reconcile_merged_prs`.
>
> · source_class: neil_position+agent_observation · role: architect · model: opus · ip_class: hub_original.

# FR-0029: Dispatcher catch-up from ai-hub-poc

## Why

ai-hub-poc built four dispatcher fixes in its own copy of `dispatch.py`. The template back-ported part of that work in `aacb473` but left the rest unwired. Upgrading ai-hub-poc to the current template therefore loses behaviour its own FRs require, and the gap analysis attributes about 20 of its failing tests to this file:

1. **Reconcile on a stale `main`.** `_git_fetch_origin_main` and `_commits_behind_origin_main` exist in the template but nothing calls them. `reconcile-merged` (and the reconcile step inside `tick` and `wave`) runs against a local `main` that may be behind `origin/main`. It then flips or cleans up against a stale tree, and its commits land on a `main` that cannot fast-forward. This is ai-hub-poc FR-0013.
2. **Merged PRs from hand-named branches.** `fr_ids_from_pr_title` exists but nothing calls it. A PR merged from a `feat/…` branch never reaches its FR, which stays `ready` and blocks its dependents. This is ai-hub-poc FR-0057 AC-5.
3. **A maintainer cannot write what it owns under `specs/`, or its own tests.** Both adapters append `specs/**` and `tests/test_*.py` to the `mnt` deny list unconditionally. Deny beats allow, so an `mnt` FR that owns `specs/_template/…` cannot write it. A project whose CI lets a maintainer keep its own FR's tests in step cannot do so either. This is ai-hub-poc FR-0081 AC-1 to AC-5.
4. **The `rev` tick ignores maintainer-only FRs.** hub-tooling FR-0013 AC-11 made the `rev` leg resolve `claude/dev-<FR>`, else `claude/mnt-<FR>`. `explain_not_runnable` does, but `runnable_review_frs` still requires a `claude/dev-<FR>` branch. So `tick --role rev --fr FR-NNNN` reviews a maintainer PR, but a bare `tick --role rev` never offers it. This is the rest of FR-0013 AC-11, and ai-hub-poc FR-0081 AC-6.

## What

After this FR:
- `reconcile-merged` fetches `origin/main` and refuses, changing nothing and exiting 1, when local `main` is behind it. `tick` and `wave` note the refusal and carry on without reconciling.
- A merged PR whose branch is not `claude/<role>-FR-NNNN` is attributed by its conventional-commit title scope when that names exactly one FR, and skipped by PR number otherwise.
- `runnable_review_frs` offers an FR that has only a maintainer branch.
- A `mnt` run can write a `specs/` path its FR owns, but never an FR body or `specs/INDEX.md`.
- A project can name, in `.agent-team/layout.yaml`, the test files that belong to an FR. A `mnt` run may then write its own FR's files and no other test file.
- With no such key and no owned `specs/` path, every permission file is byte-identical to today's.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **`reconcile-merged` refuses when local `main` is behind `origin/main`.**
  - **Order:** `reconcile_merged_prs(apply, verbose)` first calls `_git_fetch_origin_main()`, then `_commits_behind_origin_main()`. Both run before `_gh_preflight` and before any `gh` query, flip, commit or cleanup. They run in dry-run as well as with `--apply`.
  - **Fetch failure** is not fatal. With `verbose`, it prints one line naming the failure, then continues to the behind check.
  - **Behind:** when the count is greater than 0, the function returns a `ReconcileSummary` with `behind_origin=True` and empty `flipped`, `cleaned` and `skipped`. No spec file, worktree, branch, lock or metrics record is touched. With `verbose` it prints exactly one line: `reconcile-merged: local main is <N> commit(s) behind origin/main; run 'git pull --ff-only' first, then re-run reconcile`.
  - **The field:** `ReconcileSummary` gains `behind_origin: bool = False`.
  - **The command:** `cmd_reconcile_merged` prints `reconcile-merged: refused (local behind origin/main)` and returns 1 when `behind_origin` is set. It checks this before `gh_unavailable`.
  - **The helpers** keep their signatures and their fail-open behaviour: a failed `rev-list` counts as 0.
  - **Verified:**
    - with doubles for both helpers: a count of 3 refuses in both modes with nothing flipped, and the fetch is called exactly once even when `gh` is unavailable;
    - against a real repository whose bare `origin` has one commit that local `main` lacks, with `gh` stubbed: `--apply` exits 1 and leaves a `ready` spec and a `claude/dev-<FR>` worktree, branch and lock untouched;
    - after `git pull --ff-only`, the same run reconciles.

- **AC-2:** **`tick` and `wave` note a behind `main` and carry on.**
  - When the reconcile they run reports `behind_origin`, `cmd_tick` (both modes) and `cmd_wave` (both modes) each print one `NOTE` line naming `origin/main` and `git pull --ff-only`.
  - They then continue exactly as when reconcile flips nothing: no flip, cleanup, `Reconciled merged PRs` or `WOULD reconcile` line. `wave` still records the empty `merged_this_run` set (hub-tooling FR-0013 AC-7).
  - When local `main` is not behind, every printed line is unchanged.
  - **Verified** for `tick` and `wave`, dry-run and `--apply`, with `reconcile_merged_prs` returning a `behind_origin` summary.

- **AC-3:** **A merged PR from a non-`claude/*` branch is attributed by its title scope.** In `reconcile_merged_prs`, a merged PR whose `headRefName` does not match `_FR_BRANCH_RE` is resolved through `fr_ids_from_pr_title(title)`.
  - **Exactly one FR, and the title's type is not `spec`:** the PR is attributed to that FR in a title-attributed slot.
    - It can trigger the status flip. The flip PR is the newest of the FR's `dev`, then `mnt`, then `rev`, then title-attributed PRs, in that precedence.
    - The flip, its commit and its `pr.merged` record are today's. The record's `role` is `null` when the title-attributed PR is the one that triggered the flip, since no dispatcher role produced it.
    - A title-attributed PR never triggers worktree, branch or lock cleanup.
  - **Type `spec`** (an Architect's spec PR, such as `spec(FR-0029): …`): skipped, never flipped. A merged spec PR does not mean the FR is implemented.
  - **Zero FRs or more than one:** skipped.
  - **What a skip records:** a skipped PR is appended to `summary.skipped` as `("PR#<number>", <reason>)`. The reason names the head branch and one of: `no FR`, `<k> FRs (<ids>)`, or `spec PR`. With `verbose`, a skip prints `  PR#<number>  SKIP — <reason>`.
  - **The branch wins:** a PR on `claude/dev-FR-0001` titled `chore(FR-0002): …` is attributed to FR-0001 only, as today.
  - **The no-match line:** when no PR matches either way, the line says neither a branch nor a title scope names exactly one FR.
  - **Verified** with `_gh_merged_prs` stubbed, over:
    - `feat/x` titled `feat(FR-0801): …`, which flips;
    - `feat/x` titled `feat(FR-0801,FR-0802): …` and `hotfix/y` titled `Merge pull request #78 …`, both skipped with those reasons;
    - `spec/x` titled `spec(FR-0801): …`, skipped;
    - the branch-wins case;
    - an FR with both a `claude/dev-*` PR and a title PR, which flips once from the `dev` PR and cleans up `dev` and `rev` as today.

- **AC-4:** **The `rev` tick offers an FR that has only a maintainer branch.** `runnable_review_frs` resolves each FR through `_implementation_branch_for_fr`: `claude/dev-<FR>`, else `claude/mnt-<FR>`, else the FR is not offered.
  - **Status:** the effective status is read from that branch, falling back to the FR's status on `main`.
  - **Lock:** the held-lock check is on that branch's role (`dev` or `mnt`).
  - **Unchanged:** the FR-0008 AC-4 gate exclusion.
  - **One branch:** when both branches exist, the FR is offered once, against `claude/dev-<FR>`.
  - **The empty message:** `cmd_tick`'s empty-set message for `rev` names a dev or maintainer branch and a held dev or maintainer lock.
  - **Dev-only FRs** produce the same runnable set as today, at prefix `""` and in FR-0024's subdirectory fixture.
  - **Verified** for four cases, with `_git_branch_exists`, `_fr_status_on_branch` and `lock_state` doubled:
    - mnt-only: offered;
    - mnt-only with a held `mnt` lock: not offered;
    - both branches: offered once;
    - neither: not offered.

- **AC-5:** **A maintainer may write the `specs/` paths it owns, but never an FR body or the index.**
  - **The constant:** `MNT_SPECS_NEVER_WRITABLE = ("specs/FR-*.md", "specs/INDEX.md")`.
  - **Granted:** `mnt_permission_rules(owns, fr_id=None)` returns `granted` as today, minus every entry that matches a `MNT_SPECS_NEVER_WRITABLE` pattern (by `fnmatch`).
  - **Untouched case:** when no `owns:` entry lies at or under `specs/`, `denies` carries `specs/**` as today.
  - **Narrowed case:** otherwise `specs/**` is replaced, as the protected globs are narrowed today, by:
    - one deny for each file under `specs/` that `owns:` does not cover;
    - one deny for each existing file matching a `MNT_SPECS_NEVER_WRITABLE` pattern, whether owned or not;
    - the two `MNT_SPECS_NEVER_WRITABLE` patterns themselves, so a new FR body is denied too.
  - **Coordinates:** an `owns:` entry is tested against `specs/` in project coordinates, as FR-0024 AC-4 converts paths:
    - as written at prefix `""` or under `footprint_root: project`;
    - with `<prefix>` stripped under `footprint_root: repo`. An entry outside the project never narrows the project's `specs/**`; hub-tooling's `template/specs/…` entries are such entries.
  - **Denies stay relative** to the agent's working directory, and grants follow FR-0024 AC-5's anchor.
  - **Verified:**
    - `owns: [specs/_template/FR-XXXX-template.md]` yields an `Edit`/`Write` allow for it and no deny that matches it, keeps an unowned FR body denied, and drops the blanket `specs/**`;
    - `owns: [specs/FR-0001-a.md, specs/INDEX.md]` grants neither and denies both;
    - in FR-0024's `repo`-rooted subdirectory fixture, `owns: [projects/demo/specs/_template/x.md]` narrows, and `owns: [lib/specs/x.md]` does not.

- **AC-6:** **The layout names each FR's own test files, and a maintainer may write its own FR's files and no others.**
  - **The key:** `project_layout.load` accepts an optional top-level key `mnt_own_test_globs`.
    - It is a non-empty list of strings.
    - Each string contains `{num}` at least once and no other `{` or `}`.
    - With `{num}` replaced by `0000`, each string passes `spec_footprint._validate_glob` and starts with `<d>/` for some entry `d` of the layout's `gate.test_dirs`, so it can never name a control-plane, spec or `.claude/` path.
    - Anything else raises `LayoutInvalid` naming `.agent-team/layout.yaml` and `mnt_own_test_globs`.
  - **The field:** `ProjectLayout` gains `mnt_own_test_globs: tuple[str, ...] = ()`. The default, with no file or no key, is `()`.
  - **The example:** `layout.yaml.example` documents the key, commented out like every other key. It gives ai-hub-poc's convention as the example (`["tests/test_fr_{num}*.py", "tests/test_fr{num}*.py"]`) and says `Default: none`.
  - **The helper:** `_mnt_own_test_globs(fr_id)` returns the layout's globs, in declared order, with `{num}` replaced by the FR's four digits. It returns `[]` when there is no sibling `project_layout.py`, no layout file, or no key.
    - **Read at every prefix:** it reads the layout through `project_layout.load(REPO_ROOT)` at every prefix, including `""`. This narrows FR-0024 AC-6's "at prefix `""` the dispatcher does not read the layout" to: it reads it there only for this key, and only for `mnt` (DEC-0035).
  - **Malformed layout:** when `_mnt_own_test_globs` is needed and the layout is malformed, `dispatch.py maintain <FR>` and `dispatch.py finalize <FR> --role mnt`, in dry-run and with `--apply`, each print one `ERROR` line naming the file and exit non-zero. They do this before any worktree is created or any file is written. No other role reads the key, so no other role changes behaviour.
  - **Folding in:** `mnt_permission_rules(owns, fr_id)` folds the FR's own globs into `granted`, after the `MNT_NEVER_WRITABLE` and `MNT_SPECS_NEVER_WRITABLE` filters.
  - **The `tests/test_*.py` deny:**
    - It is narrowed only when an own glob, in project coordinates, starts with `tests/test_`. It is then replaced by one deny for each existing `tests/test_*.py` file that no own glob matches.
    - An `owns:` entry matching `tests/test_*.py` never narrows it. Such a path is granted and still shadowed, as today.
    - With `fr_id=None`, or no own globs, `denies` carries `tests/test_*.py` as today.
  - **Unchanged:** `.claude/**` is not in `MNT_PROTECTED_GLOBS` or `MNT_SPECS_NEVER_WRITABLE`. `mnt_unwritable_grants` and `mnt_unwritable_hint` are unchanged and still warn for a `.claude/**` entry.
  - **Verified:**
    - the loader accepts ai-hub-poc's two globs and refuses each malformed case: no `{num}`, a stray brace, `..`, an absolute path, a path outside `test_dirs`, an empty list, and a non-list;
    - with the two globs configured, `_mnt_own_test_globs("FR-0081") == ["tests/test_fr_0081*.py", "tests/test_fr0081*.py"]`;
    - `mnt_permission_rules(["scripts/dispatch.py"], "FR-0081")` grants both, denies another FR's existing `tests/test_fr_0057_x.py`, and does not deny `tests/test_fr_0081_y.py`;
    - `mnt_permission_rules(["scripts/dispatch.py"])` still denies `tests/test_*.py`;
    - with a malformed layout at prefix `""`, `maintain <FR>` refuses and `backfill <FR>` does not.

- **AC-7:** **Both adapters, the spawn line and the finalize backstop agree with the derivation.**
  - **Both adapters:** `ClaudeCodeAdapter.mnt_permissions` and `CursorAdapter.mnt_permissions` both call `mnt_permission_rules(owns, fr_id)`. For the same `owns:` and FR, each of AC-5's and AC-6's path classes comes out the same in both:
    - an owned `specs/` path is writable in both;
    - an FR body or the index is writable in neither;
    - the FR's own test glob is writable in both;
    - another FR's test is denied in both.
  - **Callers:** `cmd_oneshot`'s `FOOTPRINT` line and `_off_limits_worktree_paths` pass the FR too.
  - **Footprint check:** `mnt_footprint_violations` does not report a path that, in footprint coordinates, matches one of the FR's own test globs. Every other result is unchanged.
  - **Verified:**
    - with ai-hub-poc's two globs configured, a `claude/mnt-<FR>` branch committing `tests/test_fr_<num>_x.py` passes the footprint check of `finalize <FR> --role mnt` (dry run);
    - the same branch committing another FR's test file is refused as today.

- **AC-8:** **Nothing else changes.**
  - **When nothing narrows:** with no layout file, or a layout without `mnt_own_test_globs`, and an `owns:` with nothing at or under `specs/`, these are byte-identical to today's:
    - every permission file, for every role and both adapters, at prefix `""` and in FR-0024's subdirectory fixtures;
    - the `FOOTPRINT` line, `mnt_footprint_violations` and `_off_limits_worktree_paths`.
  - **These pinned tests pass unedited:**
    - `test_dispatch_permission_mode.py::test_permission_files_are_byte_identical_to_the_base_refs[mnt]`;
    - `test_dispatch_subdirectory.py::test_a_project_rooted_subdirectory_permission_file_is_byte_identical_to_todays[mnt]`;
    - `test_dispatch_subdirectory.py::test_a_repo_rooted_layout_in_a_project_that_is_its_own_repository_writes_todays_file[mnt]`;
    - every test that calls the real `reconcile_merged_prs` (`test_dispatch_metrics.py`, `test_dispatch_gates.py`);
    - `test_project_layout.py::test_template_ships_the_example_documenting_every_key_and_never_the_layout`;
    - every other test that passed before this FR.

    A pre-existing test that goes red is a `## FINDINGS` line for the Architect, never a test edit.
  - **Reconcile:** for branch-matched PRs with local `main` not behind, its printed lines and records are unchanged.
  - **Untouched:** `dev_permissions`, `_owns_entry_protected`, `MNT_PROTECTED_GLOBS`, `_project_control_plane_path` and FR-0028's argv.
  - **Metrics:** there is no new metrics record kind or field.

**Annotation.** These tests ride into every bootstrapped project. Annotate them `# covers hub-tooling FR-0029:AC-N`, as `.agent-team/layout.yaml` and FR-0023 require. Never use the at-sign form: in any other project it would name an unknown FR and fail that project's gate.

## Out of scope

- **Retargeting ai-hub-poc's own tests.** About 44 of ai-hub-poc's 90 failures are tests that pin superseded behaviour (class A). Examples:
  - the `--force` finalize-gate tests;
  - the FR-0011 fixture's missing sibling modules;
  - `_rev_source_branch`, which is now `_implementation_branch_for_fr`;
  - the `--rounds` default of 2.

  They are fixed in ai-hub-poc, not here. This FR keeps no alias for `_rev_source_branch`.
- **ai-hub-poc's layout file.** Its `.agent-team/layout.yaml` setting `mnt_own_test_globs` is written in ai-hub-poc as part of its upgrade. `--upgrade` never creates a layout (FR-0023).
- **Maintainer command prose about own tests.** `maintainer.md` still says `tests/test_*.py` is denied. That stays true unless a project sets the key. Telling a maintainer about the exception is a follow-up for the Chief of Staff to park. FR-0030 owns that file and does not change that sentence.
- **New-file gaps under a narrowed directory.** A narrowed `specs/**` or `tests/test_*.py` denies existing siblings by name. `mnt` inherits `dev`'s `Edit(*.md)` and `Edit(*.py)`, so it could still create a new, unowned file there. This is the gap the protected-glob narrowing already has. `mnt_footprint_violations` at finalize is the backstop, as it is today.
- **Refusing `wave` or `tick` outright** on a behind `main` (Open questions).
- **`tick`'s or `wave`'s reconcile running without `gh`.** It still needs `gh`.
- **Any change to `dev`, `rev`, `bkf`, `gat` or `docs` permissions.**
- **Cursor work beyond AC-7's parity.** Cursor is unsupported at AlayaCare (Neil, 2026-11-04). Its adapter is kept in parity only because the shared derivation feeds both.

## Open questions

- **Q:** What should the default for `mnt_own_test_globs` be?
  - **Default:** no globs.
    - **Why not ai-hub-poc's convention:** the template has no per-FR test-file convention. Its own tests are `tests/unit/scripts/test_<area>.py`, and `reviewer-backfill.md` suggests `tests/test_<fr_module>.py`. A default of `tests/test_fr_{num}*.py` would grant every project's maintainer a test surface its CI does not recognise.
    - **Byte-identity:** it would also change every `mnt` permission file. That turns three pinned FR-0024 and FR-0028 tests red (AC-8).
    - **Cost:** ai-hub-poc adds two lines to its layout.
- **Q:** Should `tick` and `wave` refuse, rather than note, a behind `main`?
  - **Default:** no, note and carry on (AC-2).
    - ai-hub-poc's dispatcher carries on silently. Refusing would change the exit and output of every `tick` and `wave` on a host that forgot to pull, and FR-0014's wave tests pin that output.
    - The `NOTE` line makes the skipped reconcile visible.
    - If a wave on a stale `main` re-dispatches an already-merged FR, that is a new FR.
- **Q:** Should a title-scope PR of another type also be skipped, such as `docs(FR-NNNN)` or `chore(FR-NNNN)`?
  - **Default:** only `spec` is skipped.
    - ai-hub-poc's tests attribute `feat` and `docs`. `chore(FR-NNNN): record the #N merge` names an FR that is already `merged`, so it is a no-op.
    - `spec` is the one type the Architect's handoff uses for a PR that adds or revises a `ready` FR. Attributing it would flip an unimplemented FR to `merged`. That is the defect ai-hub-poc FR-0057 split itself to avoid.
- **Q:** Is item 3 (AC-5 to AC-7) too big to share an FR with items 1, 2 and 4?
  - **Default:** no, keep one FR.
    - All four edit `template/scripts/dispatch.py`. Splitting them makes two FRs own one file, so they must be serialised, which is the overlap the Architect role warns against.
    - Items 1, 2 and 4 are small: about 80 lines plus tests. The narrowing is about 150 lines plus tests.
  - **Fallback if the Chief of Staff prefers:** split AC-5 to AC-7 into a follow-up FR that `depends_on: [FR-0029]` and runs after it. Neither FR's ACs change.

## Dependencies

- **FR-0024** (merged): `_project_prefix`, `_project_relpath`, `_footprint_relpath_fn`, `_absolute_grant_anchor` and `_layout_refusal`. AC-5 and AC-6 compare in its coordinates, and grants keep its anchor.
- **FR-0028** (merged): its pinned argv and its byte-identity test for the `mnt` permission file. AC-8 keeps both green.
- **FR-0013** (merged): AC-4 completes its AC-11 ("the `rev` tick's eligibility check"). Its AC-7 `merged_this_run` set is kept by AC-2.
- **FR-0023** (merged): AC-6 adds one key to its loader, under its validation rules.
- **FR-0030** is independent. It owns no file this FR owns.

## Notes

- **Revision of FR-0024.** AC-6's "Read at every prefix" narrows FR-0024 AC-6 and DEC-0031 item 9. DEC-0035 (`neil`, non-breaking, proposed) records it and bumps FR-0024 to v4. Neil ratifies DEC-0035 by merging the PR that carries it.
- **Dispatch.** `template/scripts/dispatch.py`, `template/scripts/project_layout.py` and `template/.agent-team/layout.yaml.example` are human-approval files (hub `CLAUDE.md`). Neil ratifies this FR, and approves the edits, by merging the PR that implements it. Under `footprint_root: repo` none of them is hub-tooling's own control plane (FR-0024 AC-4), so the Developer gets absolute grants. Edit `template/**`, never this project's bootstrap copies.
- **Base ref.** The bite check and AC-8's comparisons are against `main` at the commit this FR is dispatched from. Pin that SHA in the tests as `_BASELINE_REF`, as FR-0023, FR-0027 and FR-0028 do. Load the base ref's `dispatch.py` and its sibling modules with `git show`, as `test_dispatch_subdirectory.py`'s `pre_fr_dispatch` fixture does. Skip when the ref is unreachable.
- **Isolation.**
  - Every new test that reaches `reconcile_merged_prs` doubles `_git_fetch_origin_main`, or points `REPO_ROOT` at a fixture repository whose `origin` is a bare repository under `tmp_path`. No test fetches from a real remote.
  - `gh` is always stubbed.
  - The tests that already call the real `reconcile_merged_prs` (`test_dispatch_metrics.py`, `test_dispatch_gates.py`) now also fetch. Their fixture `REPO_ROOT` has no reachable `origin`, so the fetch fails fast and the behind count is 0. The Developer confirms they pass unedited (AC-8).
- **Reviewer, bite check (mandatory).** Load the base ref's `dispatch.py` and `project_layout.py` as second modules, with the same doubles, and show:
  - AC-1's refusal test fails there, because `behind_origin` is absent;
  - AC-3's `feat/x` flip fails there;
  - AC-4's mnt-only case is not offered there;
  - AC-5's owned `specs/_template` path is shadowed there by `specs/**`;
  - the loader there refuses `mnt_own_test_globs` as an unknown key.

  Record each in `REVIEW.md`.
- **Reviewer, targeted tests only.** Run this FR's two new files, plus every file AC-8 names. Do not run the full template suite. CI's `Validate` job runs it, and locally it takes about 1.5 hours, beyond the 1-hour wave phase (hub IDEA-0104). Name CI's run as the full-suite evidence in `REVIEW.md`.
- **Reviewer dogfood (AGENTS.md).**
  1. Bootstrap a throwaway project from the modified template, with a short path and `--no-register`.
  2. Run its `scripts/index-specs.py --validate` and `scripts/deploy-gate.py`.
  3. Add a synthetic `ready` FR owning `specs/_template/FR-XXXX-template.md` and `scripts/dispatch.py`, and a layout with ai-hub-poc's two globs.
  4. Run `python scripts/dispatch.py maintain <FR>` (a dry run by default). The `FOOTPRINT` line names both `owns:` entries and both own globs.
  5. Run `python scripts/dispatch.py reconcile-merged` with `gh` unavailable. It fetches, then reports `gh` unavailable.
  6. Delete the throwaway.
- **Which ai-hub-poc tests each AC is meant to turn green after the upgrade.** These are ai-hub-poc FR numbers.
  - **AC-1:** `tests/test_dispatch_reconcile.py`, the six of its seven tests that fail today (ai-hub-poc FR-0013).
  - **AC-3:** ai-hub-poc FR-0057 AC-5's `test_reconcile_attributes_a_non_claude_branch_by_title_scope` and `test_reconcile_skips_ambiguous_titles_naming_the_pr_number`.
  - **AC-4:** ai-hub-poc FR-0081 AC-6/AC-8's runnable-set tests. The two that call `_rev_source_branch` stay class A.
  - **AC-5 to AC-7:** ai-hub-poc FR-0081 AC-1 to AC-5 (8 tests) and ai-hub-poc FR-0069's maintainer-permissions test. This assumes ai-hub-poc's layout sets `mnt_own_test_globs: ["tests/test_fr_{num}*.py", "tests/test_fr{num}*.py"]`, in that order. Those tests read the project's real `REPO_ROOT`, so they pick the layout up unchanged.
- **After merge.** hub-tooling's `scripts/dispatch.py` and `scripts/project_layout.py` are bootstrap copies. They change on the next refresh or `bootstrap.py --upgrade projects/hub-tooling --yes`. ai-hub-poc gets this on the Wave 5 upgrade, once FR-0030 is also merged.

## Changelog

- 2026-11-05: created (ready) from the 2026-11-05 Wave 5 gap analysis of ai-hub-poc's upgrade (dispatcher half, "HT-a"). Four open questions are settled with defaults:
  - the own-test layout key defaults to no globs;
  - `tick` and `wave` note a behind `main` rather than refuse;
  - only `spec` PRs are excluded from title attribution;
  - the four items stay in one FR, with a split named as the fallback.

  Neil ratifies by merging the PR that implements this FR.
- 2026-11-05: cites DEC-0035, which records the narrowing of FR-0024 AC-6 that AC-6 needs. No normative change.
