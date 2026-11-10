---
id: FR-0024
title: The dispatcher works for a project in a subdirectory of its repository — agents start in the project directory inside a whole-repo worktree, branch reads and git-returned paths are prefix-correct, and a repo-rooted footprint becomes absolute permission grants — with byte-identical behaviour when the project is the repository
status: merged
owner: architect
depends_on: [FR-0023, FR-0018]
tags: [dispatch, harness, control-plane, footprint, monorepo, template]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_dispatch_subdirectory.py
  - template/tests/fixtures/dispatch-subdirectory/**
  - projects/hub-tooling/.gitignore
reads:
  - template/scripts/project_layout.py
  - template/scripts/metrics_log.py
  - template/scripts/spec_footprint.py
  - template/scripts/stack_profile.py
  - template/tests/unit/scripts/test_dispatch_permissions.py
  - template/tests/unit/scripts/test_dispatch_stack_grants.py
  - template/tests/unit/scripts/test_dispatch_env_preflight.py
  - template/tests/unit/scripts/test_dispatch_postapprove.py
  - template/tests/unit/scripts/test_dispatch_review_artifact.py
  - template/tests/unit/scripts/test_dispatch_gates.py
  - template/tests/unit/scripts/test_dispatch_wave_finalize.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_finalize.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - template/tests/unit/scripts/test_merge_friction.py
  - template/tests/unit/scripts/test_merge_friction_adversarial.py
  - template/tests/unit/scripts/test_review_library.py
  - template/tests/unit/scripts/test_project_layout.py
  - projects/hub-tooling/specs/FR-0015-control-plane-paths-refused-at-finalize.md
gates: []
derived_from: IDEA-0061
pattern: null
ac_state: {}
version: 4
lifecycle: live
revisions: [DEC-0026, DEC-0031, DEC-0035]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0009, FR-0010, FR-0013, FR-0015, FR-0023]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - How the prefix, worktree root and project-in-worktree directory are represented (a small frozen dataclass, or three helpers), as long as the prefix is computed at call time from the current `REPO_ROOT` and cached per `REPO_ROOT`.
    - The exact absolute-path spelling for Claude Code rules on Windows (`//c/…` vs `//C:/…`), which the documentation leaves open. **Settled by the live run of 2026-11-04 (DEC-0031):** `//c/…`, with a lower-case drive and no colon, over the worktree root's `os.path.realpath`. AC-5 states it.
  fixed:
    - "When the project directory is the repository top level (prefix `\"\"`), every printed line, git argv, permission file, lock file, PR record and metrics record is byte-identical to today's; every existing dispatcher test passes unedited."
    - "The prefix is never computed at import time (tests load `template/scripts/dispatch.py` from inside the hub, where the import-time prefix is `template/`, then re-point `REPO_ROOT`) and never inside `ensure_dev_venv` (its reuse path must run zero subprocesses)."
    - "`--relative` and subtree-limited `ls-files` are never used to compare paths: they hide changes outside the project."
    - "Nothing widens a grant beyond what the FR's `owns:` names; protected-path denies and the static role permissions stay relative to the agent's working directory."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-11-05
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session, at Neil's request to promote IDEA-0061 now) from IDEA-0061. Grounded in three sources:
> - a read-only audit of `template/scripts/dispatch.py` at `82670a5`: every `REPO_ROOT` use classified; 10 `<rev>:<path>` object reads; about 9 comparisons of git-returned paths against globs; worktree, cwd and settings-file sites;
> - empirical git behaviour from a subdirectory (git 2.53, Windows);
> - Claude Code's documented settings and permission-path semantics (`code.claude.com/docs/en/settings`, `/permissions`).
>
> This is the dispatcher half; FR-0023 is the configuration-and-gate half. · source_class: neil_position+agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0024: A subdirectory-aware dispatcher

## Why

`dispatch.py wave` does not work for a project that lives in a subdirectory of its repository. hub-tooling is one, inside the hub, and so is any monorepo project. Wave 1 and wave 2 were hand-orchestrated because of it: 15 FRs and counting. The audit found five failure classes, none of which the tests can see, because every fixture puts the project at the repository top:

1. **Object reads miss.** `git show <branch>:specs/…`, `<branch>:REVIEW.md` and `<branch>:PR_BODY.md` resolve from the repository top. From `projects/hub-tooling` they fail with `path 'projects/hub-tooling/specs/…' exists, but not 'specs/…'`. That affects 10 sites. Some fail silently:
   - `_fr_status_on_branch` always falls back to `main`'s status;
   - `branch:REVIEW.md` reads the hub's own tracked root `REVIEW.md` and prints a false `REVIEW-KEPT`.
2. **Agents start at the wrong level.** A worktree is a whole-repository checkout, and the agent's cwd is its root. The agent sees the hub's `CLAUDE.md`, `scripts/` (with no `deploy-gate.py`) and `tests/`, and `/developer` does not exist there. `_run_deploy_gate(cwd=wt)` finds no gate. `@covers` and pytest scan the hub's `tests/`. The venv lookup finds the hub's `requirements.txt`.
3. **The permission file is not read.** On Windows, Claude Code reads `.claude/settings.local.json` from the session's starting directory. An agent started in the project directory would ignore the dispatcher's `<wt>/.claude/settings.local.json`.
4. **Path comparisons mix coordinate systems.** `git diff --name-only` returns repo-relative paths, while `owns:` and `MNT_PROTECTED_GLOBS` are compared as if they were project-relative:
   - project-relative `owns:` flags every change as a violation;
   - hub-tooling's hub-relative `owns:` matches only by accident;
   - `MNT_PROTECTED_GLOBS` would match the hub's own `scripts/*`.
5. **Grants cannot reach outside the project.** Relative permission rules resolve from the agent's cwd, and `spec_footprint` refuses `..`. So once agents start in the project directory, a relative `Edit(template/**)` rule cannot reach the hub's `template/`.

## What

After this FR, the dispatcher works out the project's prefix inside its repository at call time: `projects/hub-tooling/` for hub-tooling, `""` for every project that is its own repository. It uses the prefix in five places:
- **Worktrees:** created, locked and removed at the worktree root as today.
- **Agent and files:** the agent starts in `<worktree>/<prefix>`, the permission file is written there, and every worktree file the dispatcher reads or writes is found there.
- **Branch reads:** they name `<prefix><path>`.
- **Git-returned paths:** converted into the FR's footprint coordinates (FR-0023's `footprint_root`) before any comparison.
- **Repo-rooted footprints:** their grants become absolute rules anchored at the worktree root, and the worktree root joins the session's additional directories.

With prefix `""` nothing changes, byte for byte. hub-tooling can then run `wave`.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **The prefix is computed at call time, and prefix `""` is byte-identical.**
  - **How it is computed:** from `git -C <REPO_ROOT> rev-parse --show-prefix`, normalised to POSIX with one trailing `/`, or `""`. It is computed at call time from the current value of `REPO_ROOT` and cached per `REPO_ROOT`.
  - **When it is `""`:** when `REPO_ROOT` is the repository top level, or is not inside a git repository.
  - **Where it is never computed:** at import, and inside `ensure_dev_venv`. The latter keeps `test_dispatch_stack_grants.py`'s pins: zero subprocess calls on the venv-reuse path, and exactly the pre-FR subprocess list on the provisioning path.
  - **Verified** in two ways:
    - A subdirectory fixture gives `projects/demo/`, and a top-level fixture gives `""`.
    - The whole existing dispatcher suite passes unedited. It includes every byte-identity comparison against pre-FR modules: permissions, stack grants, env preflight, postapprove, review artifact, gates, wave finalize (including the dry-run `cwd=` line) and metrics.

- **AC-2:** **Agents and worktree files use the project directory inside the worktree.**
  - **Unchanged:** worktrees are still created, reused, locked, removed and branch-deleted at `REPO_ROOT/.claude/worktrees/<role>-<FR>` (the worktree root), with git `-C` at that root where the command acts on the whole checkout.
  - **Now under `<worktree root>/<prefix>`:**
    - the agent's cwd, for both adapters, and the dry-run preview's `cwd=`;
    - the permission file (`.claude/settings.local.json`; Cursor's `.cursor/cli.json`);
    - `PR_BODY.md` and `REVIEW.md`, read and written;
    - gate-evidence writes;
    - the rework brief under `_dispatch/`;
    - the gate and indexer scripts run in the worktree (`scripts/deploy-gate.py`, `scripts/index-specs.py`);
    - the `tests/` scan for `@covers` deltas and the pytest cwd;
    - `.venv-dispatch`, and the lock-file and `requirements.txt` lookup.

    **Revised by DEC-0026 (v2):** after FR-0025, "`REVIEW.md`" in this list means the Reviewer's root `REVIEW.md` handoff and the `specs/_reviews/` library file. Both live under `<worktree root>/<prefix>`.
  - **One helper:** the path formula is written once. The audit counted it duplicated in 11 places. **Since DEC-0031 (v3):**
    - That helper is FR-0018's `_worktree_project_root(wt_path)`, or `_worktree_project_root` is defined through it. Either way there is one definition of the project root inside a worktree, and it returns `<worktree root>/<prefix>`.
    - `spawn_role`'s `DISPATCH_WORKTREE`, which FR-0018 AC-1 sets to `abspath(_worktree_project_root(wt_path))`, therefore names the project directory inside the worktree. This FR owns that change of value (DEC-0030 item 1). `metrics_log`'s comparison and FR-0018's single-producer seam are unchanged.
  - **Verified** in a subdirectory fixture:
    - the spawn preview prints `cwd=<wt>/projects/demo`;
    - the permission file is at `<wt>/projects/demo/.claude/settings.local.json`;
    - finalize reads `<wt>/projects/demo/PR_BODY.md`, not a decoy `PR_BODY.md` at the worktree root;
    - `_run_deploy_gate(cwd=…)` runs `<wt>/projects/demo/scripts/deploy-gate.py`.
    - **The metrics redirect (DEC-0031):** a real `spawn_role` exports `DISPATCH_WORKTREE=<wt>/projects/demo` and `DISPATCH_METRICS_DIR=<primary>/projects/demo/specs/_metrics`. With those variables set:
      - `<wt>/projects/demo/scripts/deploy-gate.py` appends its `gate.run` record to the primary checkout's log, and the worktree's `specs/_metrics` stays clean;
      - a copy of the scripts at the worktree root (`<wt>/scripts/`) keeps its own log;
      - so does a copy in a sibling project (`<wt>/projects/other/scripts/`).
      At prefix `""`, FR-0018's tests pass unedited, including `test_dry_run_spawn_sets_nothing_and_the_project_root_today_is_the_worktree` and `test_the_worktree_variable_has_one_producer_in_the_dispatcher`.

- **AC-3:** **Branch reads and pathspecs are prefix-correct.**
  - Every `<rev>:<path>` object read names `<rev>:<prefix><path>`. There are 10 sites: `gate_status`, `_fr_status_on_branch`, the `REVIEW.md` `cat-file` and `show` reads, both `PR_BODY.md` fallbacks, wave Phase 3's `PR_BODY.md` probe, and the wave `GATE-STALE` evidence read. The index form `:REVIEW.md` names `:<prefix>REVIEW.md`.
  - **Revised by DEC-0026 (v2):** after FR-0025, the review reads are the library listing, the `show`/`cat-file` of `specs/_reviews/<FR>-r<N>.md`, and the root `REVIEW.md` reads at the tip, in the index and at the merge-base. Each names `<prefix><path>`. "10 sites" reads "every site". The decoy fixture also carries a decoy `specs/_reviews/<FR>-r1.md` at the repository top. `_read_review_md_on_branch` returns the project's library file, and finalize never files or reports a decoy.
  - **Revised by DEC-0031 (v3):** FR-0025's filing step writes as well as reads.
    - Its one commit adds `<prefix>specs/_reviews/<FR>-r<N>.md`, and removes the pending `<prefix>REVIEW.md`.
    - When the merge-base carries a legacy `<prefix>REVIEW.md`, DEC-0028's restore reads `<merge-base>:<prefix>REVIEW.md`. The inherited-file comparison reads the same path.
    - None of these ever touches a `REVIEW.md` or `specs/_reviews/` path at the repository top.
    - `--review-round` is unchanged.
  - The provenance `git log -- <path>` in `_mnt_provenance_exemptions` uses a top-anchored pathspec (`:(top)<path>`) for a repo-relative path.
  - Paths already returned repo-relative by `diff --name-only` are left as they are. One example is the `specs/_gates/<FR>-*.md` evidence paths that finalize and `_mnt_provenance_exemptions` collect.

  Verified in a subdirectory fixture whose repository top also carries a decoy `REVIEW.md` and `PR_BODY.md`:
  - `_fr_status_on_branch` returns the role branch's committed status, not `main`'s;
  - `_read_review_md_on_branch` returns the project's `REVIEW.md`;
  - finalize never reports `REVIEW-KEPT` for the decoy;
  - `gate_status` reads `projects/demo/specs/_gates/…`;
  - **DEC-0031:** a Reviewer finalize files `projects/demo/specs/_reviews/<FR>-r1.md`, removes `projects/demo/REVIEW.md`, and leaves the decoy root `REVIEW.md` byte-identical. A legacy `projects/demo/REVIEW.md` on the merge-base is restored, not removed (DEC-0028).

- **AC-4:** **Git-returned paths are compared in footprint coordinates.** The FR's `footprint_root` is read only through FR-0023's `project_layout.load(REPO_ROOT)`. It is imported optionally, as `deploy-gate.py` and `index-specs.py` do, and a copy with no sibling `project_layout.py` behaves as `footprint_root: project`. Should the dispatcher ever need a tracked-file listing, it comes from `spec_footprint._git_ls_files(layout)` rather than a second derivation. Today it lists none (DEC-0031). Paths from `diff --name-only`, `status --porcelain`, `ls-files` and `rev-list`-driven diffs are repo-relative. Before any comparison with `owns:`, `MNT_PROTECTED_GLOBS`, `MNT_NEVER_WRITABLE` or a fixed project prefix (`specs/_metrics/`, `specs/_gates/`, `tests/`), they are converted:
  - **`footprint_root: project`** (the default): strip the prefix. A path outside the project is **outside**. It never matches `owns:` or a protected glob, and for `mnt` it is a footprint violation, as any unowned path is.
  - **`footprint_root: repo`:** compare repo-relative paths with `owns:` directly. Protected globs are evaluated as `<prefix><glob>`, the project's own control plane, and so are the fixed prefixes.

  This applies to all of the following:
  - `mnt_footprint_violations` and its callers;
  - `_mnt_provenance_exemptions` and the `--allow-crossing` check;
  - the `specs/_gates/` and `specs/_metrics/` prefix tests;
  - `_pr_change_size`'s `tests/` count;
  - FR-0015's AC-2 and AC-3 checks;
  - **FR-0018 AC-4's revalidate resolution (DEC-0031; FR-0018 r1 N-1, recorded in DEC-0030).**
    - The conflicted-path test compares `diff --diff-filter=U` output with `<prefix>specs/INDEX.md`. A conflict on a repository-top `specs/INDEX.md` outside the project is not special: it gets today's `ERROR`.
    - The regenerating indexer is `_worktree_project_root(wt_path)/scripts/index-specs.py`, run with that directory as its cwd.
    - The `specs/INDEX.md` snapshot and every `_INDEXER_SIDE_WRITES` path (today `CODEOWNERS`) are rooted at `_worktree_project_root(wt_path)`.
    - `git add` stages `<prefix>specs/INDEX.md`.

  With prefix `""` both conversions are the identity. Verified in subdirectory fixtures:
  - `project` root, `mnt` with `owns: [src/**]`, a branch touching `projects/demo/src/a.py` and `other/b.py`: exactly `other/b.py` is reported.
  - `repo` root with `owns: [lib/**]`: `lib/x.py` passes.
  - A `dev` branch committing `projects/demo/scripts/deploy-gate.py` is refused by FR-0015 AC-2.
  - A `dev` branch committing the repository-level `scripts/deploy-gate.py`, outside the project, is **not** refused by FR-0015 AC-2. It is not the project's control plane. It is still refused as an unowned path if it is outside `owns:`.
  - **DEC-0031:** a `--revalidate` whose only conflict is `projects/demo/specs/INDEX.md` resolves:
    - the regenerate is run by `projects/demo/scripts/index-specs.py`;
    - a configured `projects/demo/CODEOWNERS` is put back;
    - the worktree is left clean.

    A conflict confined to the repository-top `specs/INDEX.md` gets `ERROR`.

- **AC-5:** **A repo-rooted footprint becomes absolute grants.** When the prefix is non-empty and `footprint_root` is `repo`:
  - **Absolute grants:** every `owns:`-derived `Edit(...)` / `Write(...)` grant is emitted as an absolute rule anchored at the worktree root. This covers `dev`, `rev`, `bkf` and `mnt`, and Cursor's equivalent. For Claude Code the form is `//` followed by the worktree root's POSIX path and the glob. **On Windows (confirmed by the live run, DEC-0031)**, that is `Edit(//c/<realpath of the worktree root>/<glob>)`, and the same for `Write(...)`. The drive is lower-case with no colon, and the path is `os.path.realpath`, so it never carries an 8.3 short name. `//C:/…` is not read as a drive root.
  - **Additional directory:** the worktree root is added to the permission file's `permissions.additionalDirectories`. On Windows it is spelled `C:/<realpath of the worktree root>` (upper-case drive, forward slashes). The live run confirmed that adding it does not widen the static relative `dev` grants: an unowned `.py` file at the repository level was still denied (DEC-0031).
  - **Still relative to the agent's cwd:** protected-path denies, the static role permissions, the `gat` evidence grant and stack grants.
  - **Otherwise:** in every other case (prefix `""`, or `footprint_root: project`) the permission file is byte-identical to today's.
  - **Cursor:** if its adapter has no additional-directories equivalent, that is recorded under `## FINDINGS` and Cursor keeps relative rules.
  - **Verified:**
    - by unit assertions on the permission file for a `repo`-rooted subdirectory fixture;
    - by the Reviewer's live run (Notes), where a real headless `claude -p` started in `<wt>/projects/demo` edits an owned repository-level file and is denied an unowned one.

- **AC-6:** **A malformed layout refuses early, in a subdirectory project.** This applies when the project's prefix is non-empty and FR-0023's loader raises for the project's `.agent-team/layout.yaml`. `spawn_role`, `tick`, `wave` and `finalize` then print one `ERROR` line naming the file, and do so before any worktree is created or reused, any file is written or any process is spawned. They then exit non-zero. `wave` still writes its synthesis, as FR-0014 requires.

  At prefix `""` the dispatcher does not read the layout (DEC-0031). **Revised by DEC-0035 (v4, non-breaking):** it does not read it there for AC-4's conversions or AC-5's anchor. It reads it only for `mnt_own_test_globs`, and only when deriving a `mnt` footprint (FR-0029 AC-6), where a malformed layout refuses `mnt` alone. Both of AC-4's conversions are the identity there, so `footprint_root` changes nothing, and the fixed byte-identity clause holds. A malformed layout is then refused by the project's own gate and indexer, as today (FR-0023 AC-1). This includes the worktree indexer that FR-0018 AC-4's resolution runs.

  Verified:
  - per entry point, in dry-run and with `--apply`, in a subdirectory fixture;
  - at prefix `""`, by `test_merge_friction.py::test_index_conflict_without_a_working_indexer_is_one_error_and_left_in_place[bad-layout]` passing unedited.

- **AC-7:** **hub-tooling's `.gitignore` covers dispatch artifacts, and `wave` plans correctly there.**
  - `projects/hub-tooling/.gitignore` gains `.claude/settings.local.json` and `.venv-dispatch/`. The hub's root `.gitignore` covers only `/.claude/settings.local.json` at the repository top.
  - Verified by the Reviewer in a temporary copy of the hub (FR-0019's procedure), where hub-tooling has FR-0023's layout and scripts copied from the modified template:
    - `python scripts/dispatch.py wave --fr <synthetic ready FR> --dry-run`, run from the copy's `projects/hub-tooling`, plans the Developer spawn with `cwd=<wt>/projects/hub-tooling` and a permission file there carrying absolute grants for the FR's hub-relative `owns:`;
    - `tick --role rev --dry-run` sees a status flip committed on the role branch.

- **AC-8:** **Nothing else changes.** Every test that passed before this FR passes unedited (AC-1). There is no new metrics record kind or field, and `gh` calls are unchanged: they all pass `--repo` and absolute body files. A pre-existing test that goes red is a `## FINDINGS` line for the Architect.

## Out of scope

- **More than one dispatching project in one repository.**
  - Branch names `claude/<role>-<FR>` are repository-global, so `reconcile-merged` attributes any merged `claude/dev-FR-NNNN` to this project.
  - Reconcile's commit takes the primary checkout's whole index.

  Neither bites in the hub today (hub-tooling is the only in-repository project; Project A and Project B are submodules). Park it if a second project appears.
- `metrics_log.project_name` (FR-0023 Out of scope).
- Ignoring `.claude/settings.local.json` / `.venv-dispatch/` in `template/.gitignore` for new projects (`.gitignore` is not synced by `--upgrade`), and the `dev` `Edit(*.py)`-any-depth versus anchored-`tests/test_*.py`-deny asymmetry the audit noticed. Both are pre-existing. The asymmetry is IDEA-0084 item (11).
- The finding that on macOS/Linux, Claude Code (v2.1.211+) also applies the **main checkout's** `.claude/settings.local.json` inside a worktree. That matters for FR-0015's threat model and IDEA-0064's move to WSL. It is parked as IDEA-0089 and not fixed here.
- A per-project extra protected set (IDEA-0088's family).
- **Known limitations (FR-0024 r1, DEC-0031).** Both fail closed, and neither affects hub-tooling today.
  - **Cursor and a repo-rooted footprint (F-3).** Cursor's `cli.json` has no additional-directories equivalent. Its `owns:` grants therefore stay relative to `<wt>/<prefix>` (AC-5), and cannot reach repository paths. Cursor cannot run a repo-rooted project's FRs that own paths outside the project. Claude Code can.
  - **Protected `owns:` entries under `footprint_root: repo` (F-4).** `_owns_entry_protected` and `mnt_permission_rules` still compare `owns:` with `MNT_PROTECTED_GLOBS` in project coordinates. Take an FR that names its own project's control plane in repository coordinates, such as `projects/<p>/.agent-team/**` or `projects/<p>/scripts/deploy-gate.py`. That entry is not withheld for `dev`, as FR-0009 AC-2 requires, and not narrowed for `mnt`: an absolute grant is written. The relative deny still covers the path, so the agent cannot make the edit. Finalize also refuses the path, in this FR's AC-4 coordinates, though not in the same way for every role (DEC-0031, r2 F-7):
    - for `dev`, `rev` and `bkf`, a committed or uncommitted change is refused (FR-0015 AC-2);
    - for `mnt`, only an uncommitted change is refused (FR-0015 AC-3). FR-0015 AC-2 does not apply to `mnt`, so a change committed on `claude/mnt-<FR>` passes `mnt`'s footprint check as owned.

    So nothing unsafe lands, but only because the agent cannot make the edit. `dev`'s permission file does not match FR-0009's letter, and `mnt` cannot maintain a repo-rooted project's own control plane. hub-tooling's FRs own `template/**` and `scripts/**`, never `projects/hub-tooling/` control-plane paths. Parked as IDEA-0097, "Protected owns: entries are detected in footprint coordinates under footprint_root: repo" (`2480bc9`).

## Open questions

- **Q:** Why not start agents at the worktree root, where relative rules would reach `template/**` without absolute paths?
  - **Default:** No. Everything project-relative would break: `/developer` and the other commands, `AGENTS.md`, `scripts/deploy-gate.py`, `specs/`, and FR-0012's conduct block's relative paths. Deny rules with a single leading segment, such as `Edit(.agent-team/**)`, would also match at any depth and defeat `mnt` grants on `template/.agent-team/**`. Absolute grants plus an additional directory is the documented way to reach outside the starting directory.
- **Q (closed by Neil, 2026-11-04; DEC-0031):** Should the dispatcher's own `@covers` checks follow FR-0023's layout? There are two such checks:
  - `_covers_tests_present`, the rework precondition;
  - `_pr_change_size`'s `tests_changed` and `covers_delta`, which go into the `pr.opened` record.

  Following the layout would mean scanning `gate.test_dirs` under the footprint root and counting `# covers <project_name>` as the gate does. As written, both scan only `<prefix>tests/` for `@covers`. For hub-tooling, that directory holds bootstrap copies of the template tests, so the precondition passes vacuously and the PR metrics count almost nothing.
  - **Default:** No, not in this FR. Keep `<prefix>tests/` and `@covers`, as AC-2 and AC-4 say. Park the layout-aware scan as a follow-up IDEA. Following the layout changes FR-0002's `pr.opened` fields for any project with a layout, so it would also have to narrow this FR's fixed byte-identity clause. That is a scope decision, not a consequence of FR-0023.
  - **Decided (Neil, 2026-11-04): option (a), keep scope.** `_covers_tests_present` and `_pr_change_size` keep scanning `<prefix>tests/`, and count only the plain `@covers` form. The layout-aware scan is parked as IDEA-0096, "dispatch.py's own @covers scans follow the project layout".
- **Q:** What if the harness rejects absolute rules or `additionalDirectories` in headless mode?
  - **Default:** The Reviewer's live run (AC-5) settles it. A rejection is a `## FINDINGS` line routed to the Architect before approval, not a Developer workaround.
  - **Closed (2026-11-04, DEC-0031):** the harness accepts both in headless mode. Neil's live run applied the owned edit and refused the unowned one.

## Dependencies

- **FR-0023** (merged, PR #26): `project_layout.py`, `footprint_root` and `_git_ls_files(layout)`, which this FR reads (AC-4). Its layout error, including DEC-0027's drive-letter rejection, is what AC-6 refuses on.
- **FR-0018** (merged, PR #29): the last of wave 2's `dispatch.py` chain (FR-0015 → FR-0016 → FR-0025 → FR-0018). This FR adapts FR-0015's AC-2 and AC-3 checks to AC-4's coordinates. It moves `_worktree_project_root`, and with it `DISPATCH_WORKTREE` (AC-2), and FR-0018 AC-4's resolution paths (AC-4), to the prefix (DEC-0030 cascade, DEC-0031).
- **FR-0025** (merged, PR #25): the review library whose reads (DEC-0026) and filing writes (DEC-0031) AC-2 and AC-3 make prefix-correct.
- **FR-0026 and FR-0027** (merged): no interaction. The dispatcher reads no ACs and no `ac_state`. The gate it runs in `<wt>/<prefix>` applies both.
- **Lane A** is complete apart from this FR, and no other active FR owns `template/scripts/dispatch.py`. Both `depends_on` entries are merged, so this FR is unblocked.
- **FR-0009 / FR-0010 / FR-0013**: the permission derivation, the stack grants and the post-approve and provenance paths this FR re-points. None is revised: each behaves byte-identically at prefix `""`, and a subdirectory project is a case none of them specified.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file. Dispatch in `mnt` mode with the `owns:` above, after Neil approves (recorded in the Changelog). `projects/hub-tooling/.gitignore` is the only path outside `template/`.
- **Implementation traps the audit found:**
  - `git worktree remove <wt>/<prefix>` fails ("is not a working tree"), so removal must use the worktree root.
  - `git show :./x` resolves against the `-C` directory's prefix. From the worktree root it names the wrong file, so build `<prefix><path>` explicitly.
  - `git diff --cached --name-only --relative` from the project directory hides staged changes outside the project. For hub-tooling that is all of them, so it would report "nothing staged".
  - `git ls-files --others` from the project directory sees only its subtree. Use `-- ':/' --full-name` or run it from the worktree root.
  - Windows returns forward slashes and may return 8.3 short names from path APIs. Derive the prefix from `--show-prefix`, never by comparing resolved paths.
  - `test_dispatch_postapprove.py::test_no_git_argv_rewrites_history_and_every_merge_is_ff_only_or_the_ac7_exception` and `::test_pre_fr_git_argv_shapes_are_all_still_present` scan the AST for merge, rebase, reset, checkout and push argv literals. Adding a pathspec does not touch them. New literals of those kinds would. The same goes for FR-0018's `commit --no-edit` exception and its `test_merge_friction_adversarial.py` argv checks.
  - FR-0018 AC-4's `_INDEX_MD_RELPATH` is used today both as a repo-relative path, in the conflict test and `git add`, and as a project-relative path, in the snapshot. Under a prefix those are two different strings (AC-4, DEC-0031).
- **Tests.** `test_dispatch_subdirectory.py` builds its repositories with the project in `projects/demo/`, which no existing fixture does. Annotate `# covers hub-tooling FR-0024:AC-N`.
- **Reviewer, live run (mandatory for AC-5).**
  1. In a short temporary path, create a repository with `projects/demo/` bootstrapped from the modified template, plus a layout with `footprint_root: repo`.
  2. Create a worktree the way the dispatcher does, and write the permission file through `write_worktree_settings` for an FR owning `lib/**`.
  3. Run `claude -p` headless from `<wt>/projects/demo` with a prompt that edits `lib/x.py` and then `other/y.py`.
  4. Record which succeeded, and the exact absolute-rule spelling that worked on Windows, under `## FINDINGS`.

  **Result (Neil, 2026-11-04, recorded in DEC-0031).**
  - **Setup:** a logged-in shell; Claude Code with Haiku and `--permission-mode default`. The repository was `C:\t24\live`, holding a `projects/demo` project with `footprint_root: repo` and a synthetic FR-0001 owning `lib/**`. The session started in `<wt>\projects\demo`.
  - **Owned edit:** `../../lib/x.py` was edited (`x = 2`).
  - **Unowned edit:** `../../other/y.py` was refused. `y = 1` was unchanged, and `permission_denials` listed the `Edit` on `<wt>\other\y.py`.
  - **Confirmed spelling:** `Edit/Write(//c/<realpath of the worktree root>/<glob>)` plus `additionalDirectories: ["C:/<realpath of the worktree root>"]`.
  5. Delete the repository.
- **Bite check.** Load `main`'s `dispatch.py` as a second module against the subdirectory fixtures and show AC-2, AC-3 and AC-4's tests fail there.
- **After merge.**
  - Run `--upgrade projects/hub-tooling --yes`. This is already done if the hub-tooling upgrade PR (`chore/hub-tooling-upgrade`) has merged. That PR runs the upgrade before this FR is dispatched, because hub-tooling's `scripts/` were still the pre-FR-0026 bootstrap copy on 2026-11-04. Run it again only if `template/` has changed since.
  - The next hub-tooling wave is dispatched with `wave` rather than by hand. The Orchestrator records the first run's learnings.
  - hub-tooling's `AGENTS.md` still says "`dispatch.py wave` does not work here until IDEA-0061 lands". That file is a human-approval file, so Neil edits it, or approves the edit, after this merges (DEC-0031).

## Changelog

- 2026-09-25: created from IDEA-0061 at Neil's request (promote now); the dispatcher half, after FR-0023. Joins wave-2 lane A after FR-0018. Awaiting Neil's approval of the control-plane edit before dispatch.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised). No normative change. He will brief the Orchestrator at its next pause.
- 2026-09-26: v2 — DEC-0026 (breaking: false): the `REVIEW.md` read sites in AC-2 and AC-3 follow FR-0025's review library, which now lands before this FR in lane A. The prefix rule is unchanged.
- 2026-11-04: v3 — DEC-0031 (breaking: false). Revalidated against merged FR-0027, FR-0025, FR-0023, FR-0026 and FR-0018 before dispatch.
  - `_worktree_project_root` is AC-2's one helper, and `DISPATCH_WORKTREE` follows it to `<wt>/<prefix>`.
  - FR-0018 AC-4's indexer, snapshot, side-writes and `git add` move to the prefix (r1 N-1).
  - FR-0025's filing commit and DEC-0028's restore are prefix-correct.
  - `footprint_root` is read only through `project_layout.load`.
  - Stale line references become names, and `reads:` is normalised to hub-relative paths and extended.
  - Dependencies are updated.
  - One Open question, the layout-aware `@covers` scan, is for Neil, with the default "not in this FR".
  - `owns:` is unchanged.
- 2026-11-04: still v3, DEC-0031. Neil chose option (a) on the Open question: keep scope. The dispatcher's `@covers` checks stay on `<prefix>tests/`, plain form only, and the layout-aware scan is parked as IDEA-0096. The after-merge `--upgrade` step now points at the separate hub-tooling upgrade PR. DEC-0031 is unmerged, so `version` stays 3.
- 2026-11-04: still v3 — DEC-0031 items 9 to 11, from the r1 review at `44aaae5`.
  - AC-6's early refusal applies only at a non-empty prefix (F-1). At prefix `""` the gate and indexer refuse a bad layout, as today, matching the implementation and AC-1/AC-8.
  - AC-4's tracked-file sentence is now conditional (F-6).
  - Cursor's reach (F-3) and protected `owns:` entries under `footprint_root: repo` (F-4) are recorded as known limitations under Out of scope.
  - DEC-0031 is unmerged, so `version` stays 3.
- 2026-11-04: still v3 — DEC-0031 item 12 (F-2). Neil's AC-5 live run passed. AC-5 and the solution space now state the confirmed Windows spelling: `//c/<realpath>/<glob>` rules plus `additionalDirectories: ["C:/<realpath>"]`. The run also showed the additional directory does not widen the static relative `dev` grants. The Open question on headless rejection is closed. DEC-0031 is unmerged, so `version` stays 3.
- 2026-11-04: still v3 — DEC-0031 item 11 restated (r2 F-7, `1d52c54`). The F-4 limitation now says finalize refuses the path for `dev`, `rev` and `bkf` (FR-0015 AC-2), and only an uncommitted change for `mnt` (FR-0015 AC-3), so for `mnt` the relative deny is the only stop. It cites IDEA-0097 (`2480bc9`). DEC-0031 is unmerged, so `version` stays 3.
- 2026-11-04: status `ready` → `merged`. PR [#32](https://github.com/NeilRGilchrist/cos-agent-hub/pull/32) merged into `main` as commit `1c1e69b`. First CI run on the PR (Validate run 41944522118: template suite 2529 passed, 227 skipped; hub suite 208 passed, 78 skipped): no test failures. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
- 2026-11-05: v4 — DEC-0035 (breaking: false): AC-6's prefix-`""` rule is narrowed to footprint conversions, so FR-0029 can read `mnt_own_test_globs` from the layout of a project that is its own repository. No FR-0024 implementer or test changes. `neil` tier, proposed.
