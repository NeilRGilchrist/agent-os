---
id: FR-0025
title: "Reviews are filed per FR and per round under `specs/_reviews/`: the root `REVIEW.md` stays the Reviewer's handoff but never lands on a branch, so review files stop conflicting and another FR's review is never read as this one's"
status: merged
owner: architect
depends_on: [FR-0016]
tags: [dispatch, finalize, reviewer, branch-lifecycle, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/specs/_reviews/README.md
  - template/tests/unit/scripts/test_review_library.py
  - template/tests/fixtures/review-library/**
  # DEC-0023 / DEC-0024 cascade. Reviewer only, bounded to the test ids those DECs name:
  - template/tests/unit/scripts/test_dispatch_finalize.py
  - template/tests/unit/scripts/test_dispatch_review_artifact.py
  - template/tests/unit/scripts/test_dispatch_postapprove.py
reads:
  - template/.agent-team/commands/reviewer.md
  - template/tests/unit/scripts/test_headless_conduct.py
  - template/tests/unit/scripts/test_dispatch_wave_finalize.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/fixtures/postapprove/**
  - specs/decisions/DEC-0001-reviewer-authored-review-md-wins.md
  - specs/decisions/DEC-0018-fr0006-ac7-reviewer-writes-and-stages-its-own-review-md.md
  - specs/decisions/DEC-0022-fr0013-revalidate-resolves-generated-conflicts-and-inherited-review-md-is-not-own.md
  - specs/decisions/DEC-0023-fr0006-ac6-reviews-are-filed-per-round-under-specs-reviews.md
  - specs/decisions/DEC-0024-fr0013-ac2-files-the-review-and-ac7-carve-out-narrows-to-index-md.md
gates: []
derived_from: null
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0028]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0006, FR-0013]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - The helper names and how the filing step is split between `_existing_review_md_source` and `_materialise_review_md`, as long as `_read_review_md_on_branch(fr_id)` keeps its signature and its None-when-absent contract.
    - The exact wording of the `REVIEW-KEPT` / `REVIEW-WRITTEN` / `WOULD-*` lines, as long as each names the library path, the byte count and the source (`branch`, `staged` or `synthesised`), and the tags themselves are unchanged (FR-0013 AC-9's vocabulary).
    - The exact wording of the two new `WARN` lines (inherited root file; round collision or guessed round).
    - The prose of `template/specs/_reviews/README.md`, within AC-6.
  fixed:
    - "The Reviewer's handoff stays `REVIEW.md` at the worktree root, staged. No command text, no `## Headless conduct` block, no `ROLE_PERMISSIONS` entry and no wrapper changes. FR-0022 AC-2's text stays true."
    - "The verdict of record is unchanged: the Reviewer's final message, or `--verdict-file`. The library file is the review of record, not the verdict source."
    - "No history is rewritten. The filing is one ordinary commit on `claude/rev-<FR>`; never `reset`, `rebase`, `commit --amend`, `checkout -f` or a force push."
    - "A library file's blob is the Reviewer's blob, byte for byte (CRLF, BOM and multi-byte characters included). It is moved in the index, never re-read through the working tree and re-added."
    - "No new metrics record kind or field."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-26
updated: 2026-11-02
---

> **Provenance:** Drafted 2026-09-26 by the hub-tooling Architect, dispatched by the Orchestrator (`_dispatch/handoff-architect-review-path.md`) on Neil's question of the same day: should reviews live in a per-FR, per-round library instead of one root file? Grounded in:
> - the hub's merge history: `9588271`, `87eb1f4` and `2d375c0` each resolved a `REVIEW.md`-only conflict (PRs #10 to #12). The one wave-1 `specs/INDEX.md` conflict was `d56107b`;
> - a read of every `REVIEW.md` site in `template/scripts/dispatch.py` and every test in `template/tests/` that pins one, at `6738b1e`;
> - the Orchestrator's gitignored per-round archive (`_dispatch/FR-XXXX.rev.REVIEW-roundN.md`, 17 files in hub-tooling alone).
>
> Companion decisions: DEC-0023 (revises FR-0006, `neil`), DEC-0024 (revises FR-0013), DEC-0025 (revises FR-0018), DEC-0026 (revises FR-0024). · source_class: neil_position+agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0025: Reviews are filed per FR and per round under `specs/_reviews/`

## Why

Every Reviewer branch commits the same root file, `REVIEW.md`. After the first merge in a wave, every other open PR conflicts on it:
- In hub wave 2, three of the first three merges needed a merge of `main`, a full-suite re-run (about 6 minutes) and a push. The conflict was on `REVIEW.md` alone each time.
- Project A reports the same on every PR.

The resolution is always "keep the branch's". It costs about 10 minutes of Orchestrator time and one CI run per PR, or 1 to 1.5 hours per wave per project.

The single path also causes a correctness bug. `main` carries the last merged FR's review, so every later Reviewer branch inherits it. `finalize --role rev` then keeps another FR's review as "the Reviewer's own", and the rework precondition passes on it. FR-0018 AC-5 was drafted to patch this.

Meanwhile the Orchestrator keeps each round's review in a gitignored `_dispatch/` archive, because the root file holds only the latest round of the latest FR.

## What

After this FR, the Reviewer still writes and stages `REVIEW.md` at its worktree root, exactly as its command says. `finalize --role rev` files it at `specs/_reviews/<FR>-r<N>.md`, where N is the review round, and removes the root file in the same commit. When the Reviewer wrote none, the synthesised review is filed there instead.

Every reader, including the rework precondition, the rework brief and the verdict fallback, reads the newest round in the library. The root `REVIEW.md` never reaches a pushed branch, so two FRs' reviews never touch the same path. The library is committed history: one file per FR per round, replacing the `_dispatch/` archive.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **The review is filed at `specs/_reviews/<FR>-r<N>.md` (DEC-0023, DEC-0024).** `finalize <FR> --role rev --apply` runs one filing step. It runs where `_materialise_review_md` runs today: after the commit step and FR-0015's control-plane check, and before the post and the push.
  - **The round N** is `--review-round N` when that is passed (AC-4), else the run-context round (`_run_context(fr_id, "rev")["round"]`), else 1.
  - **The library path** is `specs/_reviews/<FR>-r<N>.md`, relative to the project root: `REPO_ROOT` today, `<prefix>` once FR-0024 lands. N is written in decimal without padding.
  - **The pending root file** is a `REVIEW.md` at the root of `claude/rev-<FR>`'s tip that is not inherited. A root `REVIEW.md` is **inherited** when its blob equals `REVIEW.md` at `git merge-base claude/rev-<FR> main`. When no merge-base can be computed, nothing is inherited.
  - **The source:**
    - the pending root file, when it is non-empty (not whitespace-only). This is the Reviewer's own; it is filed byte for byte and reported as `REVIEW-KEPT`.
    - otherwise the synthesised body, exactly as today (`_extract_review_verdict` over the final message or the `--verdict-file`, LF, one trailing newline), reported as `REVIEW-WRITTEN`. An empty pending root file still gets today's one empty-file `WARN`.
  - **One commit** with subject `review(<FR>): round <N> verdict=<verdict>`. It adds the library file and removes a pending root file, whether or not that file was empty. The library blob is the root blob, moved in the index. When the merge-base carries a legacy root `REVIEW.md` that the Reviewer overwrote, the commit restores the merge-base blob at the root instead of removing the file, so the legacy file stays unchanged on `main`; this is DEC-0023 Decision 3's exception (DEC-0028).
  - **Nothing to file:** there is no pending root file, and the library file for N already exists on the branch, empty or not. No commit is made, and one `REVIEW-KEPT` line names the file as already filed. So re-running finalize never adds a commit. When that file is empty or whitespace-only, one `WARN` names it as empty, and it is the only `WARN` (DEC-0028).
  - **Guessed round:** the case above, with no `--review-round` and no run-context round, and a non-empty file whose bytes differ from the synthesised body. The file is kept, and one `WARN` says the round was assumed and names `--review-round` as the remedy if this is a later round.
  - **Round collision:** a pending root file whose bytes differ from an existing library file for N. It is filed at the lowest free round above the highest filed one, with one `WARN` naming both numbers. When the bytes are equal, the commit only removes the root file.
  - **Inherited root file:** never filed and never removed. One `WARN` says it was inherited from `main` and is not this FR's review. The source is then the synthesised body.
  - **An untracked root `REVIEW.md`** is not part of the handoff (FR-0006 AC-3). It is left in the worktree untouched, and the synthesised body is filed.
  - **Dry-run** prints `WOULD-KEEP-REVIEW` (the source `staged` or `branch`) or `WOULD-WRITE-REVIEW`. Each line names the library path. Nothing mutates (FR-0013 AC-9).

  Verified against a real repository with a bare origin and `gh` stubbed, for:
  - the Reviewer committed its own; staged its own (CRLF and an em dash, byte for byte); wrote none; left one untracked; committed an empty one;
  - a re-run over each, which adds no commit;
  - a re-run over an empty library file already filed for N, which adds no commit (DEC-0028);
  - `main` carrying an inherited root `REVIEW.md`;
  - a round collision;
  - rounds 1, 2 and 10;
  - dry-run of each.

- **AC-2:** **Readers find the newest round and nothing else.** `_read_review_md_on_branch(<FR>)` returns the library file with the highest N on `claude/rev-<FR>`, decoded as UTF-8, or None when there is none.
  - N is ordered numerically, so `r10` is newer than `r9`.
  - It never reads the root `REVIEW.md`, another FR's library file, or a name that does not match `^<FR>-r[1-9][0-9]*\.md$`.
  - `_resolve_rework_verdict` and `_reviewer_final_text` therefore see the newest round.

  Verified with a branch carrying `r1`, `r2` and `r10`, a decoy root `REVIEW.md`, another FR's `r3`, and `FR-0001-r01.md` and `FR-0001-final.md` decoys.

- **AC-3:** **The rework precondition and brief use the library.** `_prepare_dev_worktree_for_rework` passes only when, after its merge, the dev worktree carries the library file `_read_review_md_on_branch` returns, byte for byte, and an `@covers` test. A failure note names the missing library path. The rework brief's fallback line and the Developer's rework prompt name that path instead of `REVIEW.md`. Verified end to end: finalize a request-changes, then prepare, and check the dev worktree's library file bytes. A root `REVIEW.md` alone in the dev worktree does not satisfy the precondition.

- **AC-4:** **`--review-round N` names the round when the dispatcher cannot know it.** `finalize --role rev` accepts `--review-round N` (an integer ≥ 1). It overrides the run-context round for the library path and the commit subject. It is one `ERROR` with a non-zero exit, and nothing done, for:
  - any other role;
  - N < 1;
  - a non-integer.

  This covers a hand-run Reviewer (a subagent with `--verdict-file`, or a re-dispatch outside `wave`) whose later round has no lock. Verified with a hand-run round 2 over a branch that already has `r1`: `r2` is filed and `r1` is unchanged.

- **AC-5:** **Two FRs' reviews merge without conflict.** Take two Reviewer branches cut from the same `main`, each finalized with its own staged `REVIEW.md` and approved, so each implementation branch is fast-forwarded. Merge the first implementation branch into `main` with a real `git merge`. Then merge the second: it is clean.
  - Neither branch's tip carries a root `REVIEW.md`.
  - `main` ends with both library files.

  Repeat with `main` carrying a legacy root `REVIEW.md`: both merges are clean, and the legacy file is unchanged. This is the structural property GitHub's merge relies on, since it cannot be tested locally.

- **AC-6:** **The library explains itself.** `template/specs/_reviews/README.md` states:
  - the path scheme and how N is chosen;
  - that files are written only by `finalize --role rev`, one commit per round, and never edited afterwards;
  - that the newest round is the one the dispatcher reads;
  - the one-time migration of a legacy root `REVIEW.md` (Notes).

  No test pins its prose beyond those four statements.

- **AC-7:** **Nothing else changes.**
  - The verdict of record, `REVIEW-POSTED`, the own-PR comment fallback and the approve fast-forward are unchanged, except that the fast-forwarded range now includes the filing commit.
  - Unchanged: `ROLE_PERMISSIONS`, every command source and wrapper, and FR-0012's block hashes.
  - No new metrics record kind or field.
  - Every test that passed before this FR passes, except the test ids DEC-0023 and DEC-0024 name, each changed only as those DECs bound it.
  - A pre-existing test that goes red outside those lists is a `## FINDINGS` line for the Architect.

## Out of scope

- **Renaming the Reviewer's handoff file** or changing the reviewer command. The Reviewer keeps writing `REVIEW.md` (FR-0022 AC-2). Only the dispatcher knows the round, so it files the review.
- **Denying the Reviewer write access to `specs/_reviews/**`.** The library is written by the dispatcher. A Reviewer that edits an earlier round's file shows in the diff and the human merge.
- **Deleting or moving a legacy root `REVIEW.md` from any dispatcher or `--upgrade` path.** `--upgrade` never touches `specs/` or a project's root files (FR-0020). The migration is one Orchestrator commit on `main` (Notes).
- **Backfilling the library from history.** It is optional and recipe-only (Notes).
- **`reviewer-backfill` (`bkf`).** It materialises no review today.
- **PR_BODY.md.** It is never committed, so it never conflicts.

## Open questions

- **Q:** Per round, or one file per FR rewritten each round?
  - **Default:** Per round. A per-FR file brings back the inheritance bug inside one FR: round 2 keeps round 1's file when the round-2 Reviewer writes none. The fix would need a round-start marker the dispatcher does not record. Per-round files make "already filed" a path-existence check, and they replace the `_dispatch/` archive.
- **Q:** Should the library live at `reviews/` or `specs/_reviews/`?
  - **Default:** `specs/_reviews/`, beside `specs/_gates/` and `specs/_metrics/`. `index-specs.py` globs `specs/FR-*.md` non-recursively, so the library is invisible to it.

## Dependencies

- **FR-0016** (lane A): the same file, `dispatch.py`. This FR rebases after it. FR-0016's UTF-8 guard then covers this FR's new `git` calls.
- **FR-0015** (lane A, in flight): its AC-2 check runs before this FR's filing step. "No `REVIEW.md` materialised" there reads as "no review filed" here. FR-0015 is not edited.
- **FR-0018** (DEC-0025) now `depends_on` this FR. Its AC-5 is absorbed into AC-1's inherited rule, and its AC-4 is narrowed to `specs/INDEX.md`.
- **FR-0024** (DEC-0026): its prefix applies to the library path and to the staged-root index read.
- **FR-0022** is independent. Its AC-2 text is true before and after this FR.

## Notes

- **Lane A order:** FR-0015 (in flight), FR-0016, **FR-0025**, FR-0018, FR-0024. Each runs one at a time on `dispatch.py`.
- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file. Dispatch in `mnt` mode with the `owns:` above as the write surface, after Neil ratifies DEC-0023 and approves the control-plane edit. Record both in the Changelog. Edit `../../template/**`, never this project's bootstrap-output copies.
- **Implementation traps:**
  - `test_no_git_argv_rewrites_history_and_every_merge_is_ff_only_or_the_ac7_exception` scans for merge, reset and checkout argv literals. Move the file with `git mv` or `update-index`. Never use `checkout -- <path>`.
  - `_show_bytes` in `test_dispatch_review_artifact.py` defaults to the root path. `test_pre_fr_dispatcher_overwrote_the_agents_file_so_the_keep_tests_bite` drives the pre-FR module and must keep reading the root.
  - `test_already_current_and_ahead_implementation_branches_get_one_note_and_no_push` re-runs finalize after an approve. It is the live guard for "nothing to file".
- **Reviewer:**
  - Drive AC-1 and AC-5 against real repositories with a bare origin; stubbing git proves nothing here.
  - Bite check AC-1 to AC-3 against `6738b1e`'s `dispatch.py` loaded as a second module. On that module, AC-5's second merge conflicts.
  - Annotate the new tests `# covers hub-tooling FR-0025:AC-N`.
- **Reviewer dogfood (AGENTS.md).**
  1. Bootstrap a throwaway from the modified template (short path, `--no-register`), with a bare origin.
  2. Cut two FRs' dev branches. Finalize a request-changes round 1 and an approve round 2 on one. Confirm `specs/_reviews/FR-0001-r1.md` and `-r2.md`, and no root `REVIEW.md` on any pushed branch.
  3. Merge both implementation branches into `main`. Neither conflicts.
  4. Run the throwaway's `index-specs.py --validate` and `deploy-gate.py`.
  5. Delete the throwaway.
- **Interim for the hub (now, no code needed).** hub-tooling is hand-orchestrated, so the Orchestrator can stop the hub's conflicts today:
  - Reviewers keep writing `REVIEW.md` in their worktree.
  - Before pushing, the Orchestrator runs `git mv REVIEW.md projects/hub-tooling/specs/_reviews/<FR>-r<N>.md`, then commits.
  - Do this once DEC-0023 is ratified, from the next FR whose Reviewer has not yet committed.
- **Migration (one Orchestrator commit on each project's `main`, at a wave boundary).**
  - **Hub:** `git mv REVIEW.md projects/hub-tooling/specs/_reviews/FR-0019-r1.md`. The root file is FR-0019's verdict, `c72162c`.
  - **Project A:** in the same commit as the `--upgrade` that brings this FR, `git mv REVIEW.md specs/_reviews/FR-0004-r<N>.md`, with N taken from `git log -1 --format=%s -- REVIEW.md` (`bf2b133`).
  - Merge or re-finalize any open PR whose branch changed the root file first. Otherwise that PR meets one modify/delete conflict.
  - Until the migration, AC-1's inherited rule keeps branches cut from `main` from filing the legacy file.
- **Optional backfill (hub).** Populate the library with `git show <sha>:REVIEW.md > projects/hub-tooling/specs/_reviews/<FR>-r<N>.md`:
  - FR-0009: `1bd340b` (r1), `4bc09fe` (r2);
  - FR-0010: `900ab56`;
  - FR-0011: `e77c346`, `0160ad3`;
  - FR-0014: `7ff0b34`;
  - FR-0013: `5a43a25`, `f057c6c`, `61c269e`;
  - FR-0008: `102c70e`, `b7027c0`.

  The rest come from the gitignored `_dispatch/FR-XXXX.rev.REVIEW*.md` archive. The archive can then retire.

## Changelog

- 2026-09-26: created (ready) with DEC-0023 (revises FR-0006; `neil` tier, proposed), DEC-0024 (revises FR-0013), DEC-0025 (revises FR-0018) and DEC-0026 (revises FR-0024). Not dispatched until Neil ratifies DEC-0023 and approves the control-plane edit.
- 2026-09-26: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified DEC-0023. No normative change.
- 2026-10-30: v2 — DEC-0028 (breaking: false): AC-1's "nothing to file" now covers an empty filed round (no commit, one `REVIEW-KEPT`, one `WARN` naming the empty file), in response to the round-1 Reviewer's escalation (N1), decided by Neil on 2026-10-30; and AC-1 states that over a legacy root `REVIEW.md` the Reviewer overwrote, the filing commit restores the merge-base blob (finding N4, the Reviewer's round-1 ruling). `neil` tier, ratified.
- 2026-11-02: status `ready` → `merged`. PR [#25](https://github.com/NeilRGilchrist/cos-agent-hub/pull/25) merged into `main` as commit `53d20a8`. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
