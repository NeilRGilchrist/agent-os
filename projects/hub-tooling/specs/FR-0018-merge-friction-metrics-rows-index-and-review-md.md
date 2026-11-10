---
id: FR-0018
title: "Merge friction removed at the source: an agent's gate rows land in the primary checkout's log instead of its branch, and revalidate resolves a `specs/INDEX.md` conflict mechanically (the `REVIEW.md` halves moved to FR-0025, DEC-0025)"
status: merged
owner: architect
depends_on: [FR-0016, FR-0025]
tags: [dispatch, finalize, metrics, branch-lifecycle, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/scripts/metrics_log.py
  - template/specs/_metrics/README.md
  - template/tests/unit/scripts/test_merge_friction.py
  - template/tests/fixtures/merge-friction/**
reads:
  - template/scripts/deploy-gate.py
  - template/scripts/escalation-log.py
  - template/scripts/index-specs.py
  - template/.gitattributes
  - template/.github/workflows/agent-gates.yml
  - template/tests/unit/scripts/test_metrics_log.py
  - template/tests/unit/scripts/test_deploy_gate_metrics.py
  - template/tests/unit/scripts/test_deploy_gate_gates.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_postapprove.py
  - template/tests/unit/scripts/test_dispatch_review_artifact.py
  - template/tests/unit/scripts/test_dispatch_finalize.py
  - specs/decisions/DEC-0011-fr0013-revalidate-gate-runs-in-the-worktree-status-only.md
  - specs/decisions/DEC-0021-fr0002-agent-worktree-metrics-rows-go-to-the-primary-log.md
  - specs/decisions/DEC-0022-fr0013-revalidate-resolves-generated-conflicts-and-inherited-review-md-is-not-own.md
  - specs/decisions/DEC-0024-fr0013-ac2-files-the-review-and-ac7-carve-out-narrows-to-index-md.md
  - specs/decisions/DEC-0025-fr0018-drops-its-review-md-halves-and-depends-on-fr0025.md
  - template/tests/unit/scripts/test_review_library.py
  - template/scripts/project_layout.py
gates: []
derived_from: IDEA-0079
pattern: null
ac_state:
  5: {state: withdrawn, moved_to: DEC-0025, reason: "The inherited-REVIEW.md rule moved to FR-0025 AC-1 (DEC-0025)"}
version: 3
lifecycle: live
revisions: [DEC-0025, DEC-0030]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0002, FR-0006, FR-0013]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - How `metrics_log` compares `REPO_ROOT` with `DISPATCH_WORKTREE` (resolved paths; case-insensitive on Windows), as long as a copied script in any other directory never follows the redirect.
    - Exact wording of the `MERGE-RESOLVED` line, as long as it names the path, and the tag contains neither `REVALIDATE` nor `ERROR` (existing tests count those).
  fixed:
    - "No history is rewritten: the conflict resolution concludes the merge with `git commit --no-edit`, never `merge --continue`, `reset`, `checkout -f` or a new merge invocation."
    - "A clean revalidate merge is unchanged; nothing is regenerated after it (DEC-0011)."
    - "`index-specs.py`, `deploy-gate.py`, `escalation-log.py` and `template/.gitattributes` are not edited; `merge=union` stays."
    - "No new metrics record kind or field."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-11-03
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session) from IDEA-0079. Grounded in:
> - two read-only audits run for this session: every metrics emitter and its call site, and every revalidate, review-artifact and metrics test that the proposed changes could move, with test ids and mechanisms;
> - the template CI's checkout, which uses the default `pull_request` merge ref.
>
> The metrics option was reserved for Neil (wave-2 plan §9.4). It is recommended here as DEC-0021 option (a), recorded `neil`-tier and `proposed`. · source_class: agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0018: Merge friction removed at the source

## Why

All 13 Project A PRs so far, and most of hub-tooling wave 1's, needed the same routine before GitHub would merge them: a local `git merge origin/main`, an INDEX regenerate and a push. That is about ten minutes and one error-prone manual step per PR (Project A L62, and Project A's 2026-09-25 handoff: "still happens on every PR"). Three files cause it:

1. **The metrics log.** `specs/_metrics/<month>.ndjson` carries `merge=union`, but GitHub applies no merge drivers. Any branch that appended rows conflicts with a `main` that also did. The rows on role branches come only from agents running the gate or `escalation-log.py` in their worktree. The dispatcher already writes to the primary checkout.
2. **`specs/INDEX.md`.** It is regenerated on both sides and conflicts. Its resolution is always "regenerate".
3. **The root `REVIEW.md`.** It is committed per FR and conflicts once another FR's has landed. Its resolution is always "keep the branch's".

The third file also hides a correctness bug. Once any FR's `REVIEW.md` is on `main`, every later Reviewer branch inherits it. `finalize --role rev` then prints `REVIEW-KEPT` for another FR's review, and the rework precondition passes on it. Project A's `main` already carries one (FR-0004, `bf2b133`).

**Since v2 (DEC-0025), the third file is FR-0025's.** It files each review per FR and round under `specs/_reviews/`, so no branch carries a root `REVIEW.md`, and its AC-1 owns the inherited-file rule. This FR keeps the first two.

## What

After this FR, a dispatched agent's gate and escalation records are appended to the primary checkout's log, uncommitted there and committed from `main` only. Role branches no longer carry metrics rows, so the month files stop conflicting. A test suite that copies the scripts into temporary repositories is unaffected (DEC-0021).

`finalize --revalidate` resolves a merge conflict confined to `specs/INDEX.md` itself: it regenerates the index with the worktree's indexer and concludes the merge. Every other conflict, `REVIEW.md` included, is still left for a human (DEC-0022 as narrowed by DEC-0024 and DEC-0025).

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **The dispatcher tells a spawned agent where the metrics log lives.** When `spawn_role` spawns an agent, it sets these two variables in the environment, around `adapter.spawn`, beside `DISPATCH_RUN_ID`:
  - `DISPATCH_METRICS_DIR`: the absolute path of `<REPO_ROOT>/specs/_metrics`;
  - `DISPATCH_WORKTREE`: the absolute path of the project root inside the role worktree. Today that is the worktree path itself, because the dispatcher supports only a project at the repository top. Once FR-0024 lands it is `<worktree>/<prefix>`, the directory whose `scripts/metrics_log.py` the agent runs (DEC-0030).

  It restores `os.environ` right after, exactly as it restores `DISPATCH_RUN_ID` and `METRICS_PROJECT`: a variable that was absent before is absent after, and one that was set keeps its value. Verified with a fake adapter that samples `os.environ` inside `spawn`, plus a before/after equality check of the whole `os.environ` mapping. Test both cases: the variables absent before the spawn, and pre-set to other values.

- **AC-2:** **`metrics_log` follows the redirect only from inside that worktree.** At import:
  - `metrics_log.METRICS_DIR` is `Path(DISPATCH_METRICS_DIR)` when both AC-1 variables are set and `metrics_log`'s own `REPO_ROOT` resolves to the same directory as `DISPATCH_WORKTREE`.
  - In every other case it is `REPO_ROOT / "specs" / "_metrics"`, as today. That includes a copy of the scripts in any other directory while the variables are set.
  - An explicit `metrics_dir=` argument, `--metrics-dir`, and a monkeypatched `METRICS_DIR` still take precedence.
  - `main()`'s `--metrics-dir` help text does not raise when `METRICS_DIR` lies outside `REPO_ROOT`.

  Verified against a real repository with a linked worktree (`git worktree add`):
  - with the variables set, running the **worktree's** `scripts/deploy-gate.py` (not `--status-only`; it now loads the project layout first, FR-0023) appends one `gate.run` record to the primary checkout's month file. `git -C <wt> status --porcelain -- specs/_metrics` is empty. The record carries the `DISPATCH_RUN_ID` set.
  - the same with the worktree's `scripts/escalation-log.py`.
  - with the variables set but the scripts copied to a temporary repository, the record lands in that repository, as today.
  - `python <wt>/scripts/metrics_log.py --help` exits 0 with the variables set.

- **AC-3:** **The redirect never leaks into a test suite or the real log.** The whole `template/tests/` suite passes when it is run from inside a linked worktree of a repository bootstrapped from the modified template, with `DISPATCH_METRICS_DIR` and `DISPATCH_WORKTREE` set as AC-1 sets them. The primary checkout's `specs/_metrics/` is byte-identical before and after the run. Verified by the Reviewer running it for real (Notes). A test that goes red here, or a changed byte in the primary log, is a `## FINDINGS` line naming the test.

- **AC-4:** **Revalidate resolves a conflict confined to `specs/INDEX.md` (DEC-0022 Decision 1, narrowed by DEC-0024 and DEC-0025).**
  - **When it applies:** the `git merge origin/main` in `_finalize_revalidate_stale_branch` conflicts, and every conflicted path is `specs/INDEX.md`.
  - **What it does:**
    - `specs/INDEX.md` is regenerated by `<wt>/scripts/index-specs.py` run with `cwd=<wt>`, never the dispatcher's own copy.
    - **Only `specs/INDEX.md` changes (DEC-0030).** The resolution names the set of other paths the worktree indexer can write, relative to the project root; today that set is `CODEOWNERS`. Before running the indexer, it records whether each such path exists and its bytes. After the indexer returns, on success and on failure, it puts back any that changed: rewritten bytes are restored, and a path that did not exist before is removed. It uses file writes, not git commands.
    - `specs/INDEX.md` alone is staged, and the merge is concluded with `git commit --no-edit`, which leaves a two-parent tip. The commit holds the textual merge of every other path, as a clean merge does (DEC-0011), and the worktree is left with no uncommitted tracked change.
    - One `MERGE-RESOLVED` line names the path and its resolution.
    - The post-merge gate re-run and the `REVALIDATE` line follow exactly as today.
  - **When it does not apply:** today's `ERROR` holds, with a non-zero exit, no push, and the conflict left in place, if any of these is true:
    - any other path also conflicts, `REVIEW.md` included;
    - `INDEX.md` conflicts and `<wt>/scripts/index-specs.py` is absent;
    - the indexer exits non-zero. That includes a malformed `.agent-team/layout.yaml`, which the indexer has reported first since FR-0023 (DEC-0030).
  - **Clean merges are unchanged.**

  Verified against a real repository with a bare origin, in the manner of `test_dispatch_postapprove.py`, for:
  - an `INDEX.md`-only conflict: resolved, two parents, and `INDEX.md` equal to a fresh regenerate of the merged tree;
  - `INDEX.md` plus `REVIEW.md`: `ERROR` and both left in place, with neither resolved;
  - `INDEX.md` plus `README.md`: `ERROR` and `UU` left in place, with neither resolved;
  - `INDEX.md` with no worktree indexer: `ERROR`;
  - with `.agent-team/codeowners-config.yaml` present:
    - a merged `CODEOWNERS` that a regenerate would change is resolved, and the worktree is clean afterwards (`_rev_worktree_dirty_paths` is empty). `CODEOWNERS` at the tip equals its textual merge.
    - with `CODEOWNERS` absent, a regenerate that would create it leaves it absent;
    - an indexer that rewrites `CODEOWNERS` and then exits non-zero gives `ERROR`, with `CODEOWNERS` restored and `INDEX.md`'s conflict back in place;
  - dry-run of each: nothing mutates (FR-0013 AC-9).

- **AC-6:** **The metrics README says where rows go.** `template/specs/_metrics/README.md` states:
  - an agent's gate and escalation-log records land in the primary checkout's log, uncommitted, through `DISPATCH_METRICS_DIR`;
  - rows are committed from `main` only;
  - `merge=union` still covers local merges.

  Its sentence telling existing projects to add the union line by hand is replaced by a pointer to FR-0020, whose managed `.gitattributes` block carries it. No README content any test pins changes (the `gate.decision` rows).

- **AC-7:** **Nothing else changes.**
  - Every test that passed before this FR passes unedited. The IDEA-0079 audit names the ones at risk, all confirmed green under this design. They are named by test id since DEC-0030; the audit's line numbers predate this repository.
    - `test_dispatch_postapprove.py`:
      - `test_stale_branch_without_the_flag_is_one_warn_naming_the_count_and_remedy`
      - `test_revalidate_merges_origin_main_with_a_two_parent_commit_and_regates`
      - `test_merge_conflict_is_one_error_no_push_and_the_conflict_is_left_for_a_human` (its conflict is on `README.md`, so it stays an `ERROR`)
      - `test_red_before_and_after_proceeds_and_the_revalidate_line_does_not_claim_pass`
      - `test_pr_opened_cites_the_post_merge_gate_run_and_reflects_the_merged_head`
      - `test_revalidate_writes_nothing_so_the_worktree_stays_clean_for_the_fast_forward`
      - `test_dry_run_revalidate_on_a_conflicting_branch_still_mutates_nothing`
      - `test_no_git_argv_rewrites_history_and_every_merge_is_ff_only_or_the_ac7_exception`
      - `test_existing_callers_are_unaffected_by_the_keyword_only_additions`
      - `test_cli_wires_the_three_new_finalize_flags`
    - every test in `test_dispatch_review_artifact.py`, `test_review_library.py` and `test_dispatch_finalize.py`, as FR-0025 left them;
    - every `test_deploy_gate_metrics.py` and `test_metrics_log.py` harness.
  - No new metrics record kind or field. No change to `--revalidate`'s opt-in default or to `wave`'s auto-revalidate rule.
  - A pre-existing test that goes red is a `## FINDINGS` line for the Architect.

## Withdrawn acceptance criteria

These ACs are no longer delivered by this FR. Each one's `ac_state` entry records the state and where the work went. The numbers are retired, not reused.

- **AC-5:** **Withdrawn by DEC-0025 (v2).** The inherited-`REVIEW.md` rule is FR-0025 AC-1's, with the same merge-base comparison. The number is retired, not reused.

## Out of scope

- **Automatic revalidate** whenever `origin/main` has moved. It reverses FR-0013 AC-7's Open-question default and moves five pinned tests (DEC-0022 alternatives). The template CI already tests the `pull_request` merge ref, so a stale red is refreshed by any push. Park it if still wanted after this FR.
- **The review artifact path and the inherited-`REVIEW.md` rule.** Both are FR-0025's (DEC-0023, DEC-0025).
- Regenerating `INDEX.md` after a clean merge (DEC-0011).
- Editing `deploy-gate.py`, `escalation-log.py` or `index-specs.py`. They follow `metrics_log`'s default and are owned elsewhere this wave (FR-0021).
- Committing metrics rows from `main`: an Orchestrator routine, not dispatcher behaviour.
- The GitHub-side merge itself, which cannot be tested locally. AC-2 and AC-4 test the structural property instead: a role branch's diff never carries a metrics path, and the two generated-file conflicts resolve without a human.

## Open questions

- **Q (for Neil, wave-2 plan §9.4):** metrics option (a), a redirect to the primary checkout (DEC-0021), or (b), one file per branch?
  - **Default:** (a), as recommended in DEC-0021. If the Reviewer's AC-3 run finds the primary checkout unwritable from inside an agent's sandbox, the append fails with one `WARN` (FR-0002 AC-9: emit never raises) and the record is lost. That is a finding, not a failure, and (b) becomes the fallback.
- **Q:** Should the root `REVIEW.md` move to a per-FR path so it never conflicts?
  - **Closed by DEC-0023 and DEC-0025 (2026-09-26):** yes, in FR-0025, which lands before this FR. Hub PRs #10 to #12 each paid a `REVIEW.md`-only conflict (a merge, about 6 minutes of suite and a push), so the per-wave cost outweighs the one-time cascade. The cascade is smaller than first estimated: the Reviewer's handoff stays `REVIEW.md`, so no command, conduct block or permission changes. This FR's `REVIEW.md` halves (AC-4's `REVIEW.md` case and AC-5) are withdrawn.

## Dependencies

- **FR-0016** (merged): the same two files (`dispatch.py`, `metrics_log.py`). FR-0016's UTF-8 guard covers this FR's new `index-specs.py` and `git` calls.
- **FR-0002** (revised by DEC-0021) and **FR-0013** (revised by DEC-0022): the behaviours this FR changes.
- **FR-0025** (merged, PR #25; DEC-0025): it owns the review library, `--review-round` and the inherited-file rule. The library adds no generated or shared file, since each review is its own `specs/_reviews/<FR>-r<N>.md`. So AC-4's carve-out stays `specs/INDEX.md` only. AC-7's pins refer to FR-0025's tests.
- **FR-0023** (merged, PR #26): `metrics_log.REPO_ROOT` is still the project root, the directory above `scripts/`, and FR-0023 did not touch `metrics_log.py`. The worktree indexer AC-4 runs now validates the project layout first (AC-4; DEC-0030).
- **FR-0027** (merged, PR #24): no interaction. This FR does not read ACs.
- **FR-0024** (ready) depends on this FR. When it puts an agent in `<worktree>/<prefix>`, it sets `DISPATCH_WORKTREE` to that directory (AC-1, DEC-0030). It also adapts AC-4's `specs/INDEX.md` and `scripts/index-specs.py` paths to its prefix coordinates (its AC-4).
- **FR-0026** (ready) also owns `metrics_log.py` and `template/specs/_metrics/README.md`. The edits are disjoint:
  - this FR: `METRICS_DIR`'s resolution and the `--metrics-dir` help, in `metrics_log.py`; the union paragraph, in the README;
  - FR-0026: the `GATE_WARNING_CLASSES` literal, in `metrics_log.py`; the `warning_classes` row, in the README.
- **FR-0020**: owns `template/.gitattributes`, where the union line lives inside the managed block. This FR does not touch it.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file. Dispatch in `mnt` mode with the `owns:` above as the write surface, after Neil approves this FR and DEC-0021 (recorded in the Changelog). Edit `../../template/**`, never this project's bootstrap-output copies.
- **Lane A order.** FR-0015, FR-0016, FR-0025 and this FR run one at a time on `dispatch.py`, followed by FR-0024. This FR depends on FR-0016 and FR-0025 (DEC-0025).
- **Implementation traps the audit found:**
  - `test_no_git_argv_rewrites_history_and_every_merge_is_ff_only_or_the_ac7_exception` (L2040) scans for merge, reset and checkout argv literals. Conclude the merge with `["commit", "--no-edit"]`, never `["merge", "--continue"]`.
  - Line tags containing `REVALIDATE` or `ERROR` are counted by L1434 and the revalidate `ERROR` tests.
  - `index-specs.py` roots at its own file, so run the worktree's copy.
  - AC-1's variables must be restored, not just set. No test catches a leak, and a leaked variable would redirect every later in-process emit in the dispatcher's own process.
- **Reviewer:**
  - Drive AC-4 against real merges with a bare origin. Stubbing git proves nothing here.
  - AC-3 is a real run: bootstrap a throwaway, create a linked worktree, export the two variables pointing at it, and run `python -m pytest tests/` from the worktree. Compare `git -C <primary> status --porcelain -- specs/_metrics` and a hash of each month file before and after.
  - Bite check AC-2 and AC-4 against the base commit's `dispatch.py` and `metrics_log.py`, loaded as second modules. The base commit is the `main` commit the Developer branches from, recorded as a constant in the test. The earlier `a8889df` is not in this repository (ADR-0002; DEC-0030).
- **Reviewer dogfood (AGENTS.md).**
  1. In a throwaway with a bare origin, cut `claude/dev-FR-0001`.
  2. Have `main` gain a regenerated `specs/INDEX.md`.
  3. Run `finalize FR-0001 --role dev --revalidate --apply` with `gh` stubbed.
  4. Confirm `MERGE-RESOLVED`, a two-parent tip, and an `INDEX.md` equal to a regenerate.
  5. Run the throwaway's `index-specs.py --validate` and `deploy-gate.py`.
  6. Delete the throwaway.
- **After merge.** Tell the Project A Orchestrator that metrics rows stop appearing on role branches after Project A's next upgrade. The Orchestrator's commit-rows-from-main routine is unchanged, but the per-branch restore step can retire once it has been verified once.

## Changelog

- 2026-09-25: created from IDEA-0079. Companion decisions DEC-0021 (revises FR-0002; the §9.4 metrics option, `neil` tier, proposed) and DEC-0022 (revises FR-0013 AC-2 and AC-7; architect tier, proposed). Awaiting Neil's approval before dispatch.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified this FR's `neil`-tier DECs. No normative change.
- 2026-09-26: v2 — DEC-0025 (breaking: false). The `REVIEW.md` halves move to FR-0025: AC-4 narrows to `specs/INDEX.md`, AC-5 is withdrawn, and the per-FR-path Open question is closed. `depends_on` gains FR-0025. The metrics ACs and DEC-0021 are unchanged. No tests existed yet.
- 2026-11-02: v3 — DEC-0030 (breaking: false). Revalidated against merged FR-0025, FR-0023 and FR-0027.
  - `DISPATCH_WORKTREE` is the project root inside the role worktree.
  - AC-4's indexer failure includes a malformed layout.
  - AC-7's stale line numbers become test ids.
  - The bite-check base is the Developer's base commit.
  - Dependencies are updated.
  - No AC is added or withdrawn, and `owns:` is unchanged.
- 2026-11-02: still v3 — DEC-0030 item 6 (breaking: false), from the r1 review at `497cfa6` (E-1; Neil chose "restore side-writes"). AC-4's resolution now restores every path the indexer writes other than `specs/INDEX.md` (today `CODEOWNERS`), on success and on failure, and gains three verification cases. DEC-0030 is unmerged, so `version` stays 3.
- 2026-11-03: status `ready` → `merged`. PR [#29](https://github.com/NeilRGilchrist/cos-agent-hub/pull/29) merged into `main` as commit `f719f89`. First CI run on the PR (Validate run 41722108828: template suite 2458 passed, 227 skipped; hub suite 208 passed, 78 skipped): no test failures. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
- 2026-11-04: AC-5's withdrawal recorded in `ac_state` (`withdrawn`, `moved_to: DEC-0025`), and its bullet moved under a new `## Withdrawn acceptance criteria` section, as FR-0026 and `template/specs/README.md` prescribe. This puts DEC-0025's ratified decision into the field the gate reads, so check 3 no longer treats AC-5 as live. No normative change: no DEC and no version bump (ADR-0001 rule 2).
