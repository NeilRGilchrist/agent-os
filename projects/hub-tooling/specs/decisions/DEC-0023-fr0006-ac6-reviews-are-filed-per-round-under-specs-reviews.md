---
id: DEC-0023
title: "FR-0006 AC-6's committed review moves from the root `REVIEW.md` to a per-FR, per-round library file, `specs/_reviews/<FR>-r<N>.md`; the Reviewer's root `REVIEW.md` stays its handoff, and finalize files it there and removes it from the branch"
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0013, FR-0018, FR-0022, FR-0025]
revises: FR-0006
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep the root REVIEW.md and resolve its conflict mechanically (FR-0018 AC-4 and AC-5 as drafted)"
  - "One file per FR (specs/_reviews/FR-XXXX.md), rewritten each round"
  - "The Reviewer writes the library file itself, at a path its prompt or command names"
  - "A top-level reviews/ directory instead of specs/_reviews/"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  Every Reviewer branch commits the same root REVIEW.md, so after the first
  merge in a wave every other open PR conflicts on it. Hub PRs #10 to #12
  paid a merge, a 6-minute suite re-run and a push each, and Project A pays it on
  every PR. The single path also makes one FR inherit another's review. Filing
  each round at its own path removes the conflict outright instead of
  automating its resolution, and it replaces the Orchestrator's gitignored
  per-round archive with committed history. Leaving the Reviewer's handoff at
  the root keeps the agent-facing contract (FR-0022, FR-0012) untouched:
  only the dispatcher knows the round.
created: 2026-09-26
updated: 2026-09-26
---

# DEC-0023: Reviews are filed per FR and per round under `specs/_reviews/`

## Context

FR-0006 AC-6 guarantees "a committed `REVIEW.md`" on `claude/rev-<FR>`. DEC-0001 decided *whose* review that is: the Reviewer's own when it wrote one, synthesised otherwise. Neither decided *where* it lives. Every FR's review therefore goes to the same root path, and three costs follow:

1. **Conflicts.** After the first PR in a wave merges, every other open PR conflicts on `REVIEW.md`. The hub's merges `9588271`, `87eb1f4` and `2d375c0` (PRs #10 to #12) each resolved a `REVIEW.md`-only conflict by keeping the branch's side. Each cost a merge of `main`, a full-suite re-run of about 6 minutes, a push and a CI run: about 10 minutes of Orchestrator time. Project A reports the same on every PR.
2. **Inheritance.** `main` carries the last merged FR's review, so every later Reviewer branch inherits it. The keep rule then treats it as the Reviewer's own. FR-0018 AC-5 (DEC-0022 Decision 2) was drafted to patch this.
3. **Lost rounds.** Only the latest round of the latest FR is visible. The Orchestrator keeps each round in a gitignored `_dispatch/FR-XXXX.rev.REVIEW-roundN.md` archive: 17 files in hub-tooling. FR-0008's evidence model assumes committed review artifacts.

Neil asked on 2026-09-26 whether reviews should live in a per-FR, possibly per-round library. He accepts the repository-size cost, which is negligible: git already stores every version of the root file.

## Decision

1. **The library path.** FR-0006 AC-6's committed review lives at `specs/_reviews/<FR>-r<N>.md`, relative to the project root. N is the review round, taken from `--review-round`, else the run-context round, else 1. There is one file per round, committed once and never edited afterwards. The newest round is the review every reader uses: the rework precondition, `_read_review_md_on_branch`, `_resolve_rework_verdict` and the rework brief.
2. **The handoff is unchanged.** The Reviewer still writes and stages `REVIEW.md` at its worktree root (DEC-0018, FR-0022 AC-2). `finalize --role rev` files that file byte for byte at the library path, moving its blob in the index, and removes it from the root in the same commit, `review(<FR>): round <N> verdict=<v>`. When the Reviewer wrote none, or wrote an empty one, the synthesised body is filed instead. DEC-0001's rule (the Reviewer's own wins, and one is synthesised only when absent) is unchanged; only the location moves.
3. **The root file never reaches a pushed branch.** The one exception is a legacy root `REVIEW.md` inherited unchanged from `main`, which is left alone and never filed (FR-0013 AC-2 as revised by DEC-0024).
4. **Rework precondition.** AC-6's "passes on `REVIEW.md` presence" becomes "passes when the dev worktree carries the newest library file after the sync".
5. **Implemented by FR-0025** in lane A, after FR-0016 and before FR-0018.

**`breaking: true`.** `_materialise_review_md`, `_existing_review_md_source`, `_read_review_md_on_branch` and `_prepare_dev_worktree_for_rework` must change, and so do the pinned tests below. FR-0006 goes to `version: 4`, `revisions: [DEC-0001, DEC-0018, DEC-0023]`, `last_breaking_revision: 4`. Rule 5 was checked: FR-0006's identity is unchanged. The dispatcher still owns the review artifact and the rework sync.

**Why `neil`.** It revises a merged control-plane FR's artifact contract that DEC-0001 (Neil-ratified) shaped. It changes the committed layout of every project, Project A included, and it needs a one-time migration commit on each project's `main`. It is recorded `proposed` and is live now (ADR-0001 rule 8), but FR-0025 is not dispatched until Neil ratifies it.

## Alternatives considered

- **Keep the root file and resolve its conflict mechanically (FR-0018 AC-4/AC-5 as drafted).** Rejected.
  - FR-0018 AC-4 fires only under `finalize --revalidate`, which is opt-in. It still costs the 6-minute gate re-run, a push and a CI run per conflicting PR. It does nothing for the hub, which is hand-orchestrated until FR-0024.
  - AC-5 needs merge-base logic to undo an inheritance the single path creates.
  - Per wave that is about (PRs − 1) × 10 minutes per project. The one-time cascade below is about one maintainer/Reviewer cycle, and part of FR-0018's work is withdrawn in exchange (DEC-0025). It pays back within one wave.
- **One file per FR, rewritten each round.** Rejected. Round 2 would inherit round 1's file whenever the round-2 Reviewer wrote none, which is the inheritance bug inside one FR. Telling a fresh round-2 file from a re-run would need a round-start marker the dispatcher does not record. The approve fast-forward rules out the implementation-tip comparison (DEC-0022 Alternatives). Per-round files turn "already filed" into a path-existence check.
- **The Reviewer writes the library file itself.** Rejected. The agent does not know its round: `spawn_role` passes no round to the rev prompt. Adding one moves the rev spawn argv pins and every adapter double. It would also change the reviewer command a second time after FR-0022, the `## Headless conduct` block (which names "`REVIEW.md` for the Reviewer" and is hash-pinned by FR-0012) and `ROLE_PERMISSIONS`. Filing in the dispatcher changes none of them.
- **A top-level `reviews/` directory.** Rejected. `specs/_reviews/` sits beside `specs/_gates/` and `specs/_metrics/`, the other dispatcher-written spec artifacts. `index-specs.py` globs `specs/FR-*.md` non-recursively, so the library is invisible to it.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0006-dispatcher-owns-commit-and-rework-sync.md`, done in this commit:
  - AC-6 gains one sentence citing this DEC;
  - `version: 4`, `revisions` gains DEC-0023, `last_breaking_revision: 4`, `updated: 2026-09-26`;
  - one Changelog line.
- `template/scripts/dispatch.py`: `_materialise_review_md`, `_existing_review_md_source`, `_read_review_md_on_branch`, `_prepare_dev_worktree_for_rework`, and the rework brief and prompt text. This is FR-0025 AC-1 to AC-3, **maintainer mode**.
- Tests in `template/tests/unit/scripts/test_dispatch_finalize.py` (FR-0006's). FR-0025's Reviewer re-points each from the root `REVIEW.md` to the library path, and each changes only as follows:
  - `test_review_md_is_committed_before_push_with_the_posted_body`: the path read on the branch and in the worktree becomes `specs/_reviews/FR-…-r1.md`. The rev worktree has no root `REVIEW.md` afterwards. The ahead-count (2) and the subject are unchanged.
  - `test_review_md_keeps_an_agent_authored_one_and_a_rerun_keeps_it_again`: the agent's committed root file is now filed by one `review(…): round 2 …` commit. The "last subject is `reviewer wrote its own`" and "no `review(` commit" assertions become "exactly one filing commit, whose library blob equals the agent's bytes". The re-run still adds no commit and prints one `REVIEW-KEPT`.
  - `test_synthesised_review_md_carries_the_run_context_round`: the path becomes `…-r2.md`. The subject is unchanged.
  - `test_review_md_satisfies_the_rework_precondition_without_a_human`: `(dev_wt / "REVIEW.md").exists()` becomes the library path.
- Expected unchanged, and to be confirmed green unedited:
  - `test_finalize_commits_exactly_the_staged_index_for_every_role`: rev is still two commits, and the filing commit replaces the synthesis commit;
  - `test_dry_run_previews_commit_review_and_finalize_and_changes_nothing`;
  - `test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path`, which is FR-0022's and bounded by DEC-0018.
- `test_dispatch_finalize.py` joins FR-0025's `owns:` (Reviewer only, bounded to the four ids above) in this commit. FR-0022 also carries it; lane order serialises them.
- **FR-0012 / `test_headless_conduct.py`: no change.** The conduct block and the verdict bullet still name `REVIEW.md` as the Reviewer's handoff, and that stays true.
- **FR-0008: no change.** Its evidence reader, `gate_status`, reads only `specs/_gates/<FR>-<gate>.md`. No gate path reads `REVIEW.md`. DEC-0001's and DEC-0018's remark that FR-0008 "reads committed review artifacts" describes the model, not a code path, and the library strengthens it.
- **FR-0013:** DEC-0024. **FR-0018:** DEC-0025. **FR-0024:** DEC-0026.
- **Migration:** one Orchestrator commit on each project's `main` (FR-0025 Notes). `--upgrade` does nothing to a root `REVIEW.md`.

## Changelog

- 2026-09-26: created (proposed) with FR-0025, on Neil's per-FR review-library question of 2026-09-26.
- 2026-09-26: ratified by Neil (recorded by the Orchestrator).
