---
id: DEC-0028
title: "FR-0025 AC-1: with no pending root `REVIEW.md`, a round N that is already filed counts as filed even when its library file is empty (no commit, one `REVIEW-KEPT`, one `WARN`); and over a legacy root `REVIEW.md` the Reviewer overwrote, the filing commit restores the merge-base blob instead of deleting the file"
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0006, FR-0013]
revises: FR-0025
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Treat an empty filed round as absent and overwrite it in place at round N"
  - "File the synthesised body at the next free round once, then treat that round as filed"
  - "Refuse: one ERROR and a non-zero exit until a human removes the empty file"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  AC-1 promises that re-running finalize never adds a commit, but its
  "nothing to file" rule needs a non-empty library file and its collision rule
  needs a pending root file, so an empty filed round falls between them and the
  implementation files at max+1 on every re-run. Counting any existing round N
  as filed keeps both standing rules (a filed round is never overwritten; a
  re-run never adds a commit) and flags the anomaly with one WARN. The legacy
  restore is the only reading of AC-1 that keeps AC-5's "the legacy file is
  unchanged" and DEC-0023 Decision 3's exception true; the Reviewer ruled it
  correct in round 1.
created: 2026-10-30
updated: 2026-10-30
---

# DEC-0028: FR-0025 AC-1, an empty filed round counts as filed, and the legacy root file is restored

## Context

FR-0025's round-1 review (`specs/_reviews/FR-0025-r1.md`, reviewed SHA `c537258`) raised one escalation and one wording finding against AC-1.

1. **Escalation, N1: an empty library file for round N.** AC-1 defines "nothing to file" as "no pending root file, and the library file for N already exists on the branch, non-empty". The round-collision rule applies only to "a pending root file". Neither covers the case of no pending root file and an empty or whitespace-only `specs/_reviews/<FR>-r<N>.md` already on the branch. That case arises only when someone commits such a file by hand. The implementation falls through to the collision branch and files the synthesised body at max+1 on every re-run (r2, r3, r4, and so on). That breaks AC-1's own promise, "re-running finalize never adds a commit", and DEC-0024 Decision 1's "a re-run with the round already filed adds no commit". The Reviewer pinned the case with the strict `xfail` `test_rerun_over_an_empty_filed_round_adds_no_commit` and proposed a default.
2. **Finding N4: the legacy root file the Reviewer overwrote.** AC-1's "one commit … removes a pending root file" is written for the normal case. When the merge-base carries a legacy root `REVIEW.md` and the Reviewer overwrote it, a literal removal makes every Reviewer branch delete `main`'s legacy file. That breaks AC-5 ("the legacy file is unchanged") and Out of scope ("deleting or moving a legacy root `REVIEW.md` from any dispatcher … path"). The Developer's implementation instead restores the merge-base blob at the root. The Reviewer ruled that reading correct, and two tests pin it: `test_own_review_over_a_legacy_root_file_is_filed_and_the_legacy_file_is_left_as_found` and `test_two_frs_merge_cleanly_over_a_legacy_root_review_and_leave_it_unchanged`. The Reviewer asked for one clarifying sentence in AC-1.

Neil decided the escalation on 2026-10-30, in the session that dispatched this Architect pass, by accepting the Reviewer's proposed default.

## Decision

1. **Any filed round N counts as filed when there is no pending root file.** With no pending root `REVIEW.md`, a library file for round N that exists on `claude/rev-<FR>` at all, whether empty, whitespace-only or not, means round N is already filed.
   - No commit is made. The library file is neither overwritten nor re-filed at another round.
   - One `REVIEW-KEPT` line names the file as already filed, as for a non-empty file.
   - When the file is empty or whitespace-only, one `WARN` names it as empty. This is the case's only `WARN`: the guessed-round `WARN` applies only to a non-empty filed file.
   - Dry-run prints the same lines with `WOULD-KEEP-REVIEW` (AC-1's dry-run bullet, FR-0013 AC-9's tags), and nothing mutates.
   - The rule is reached only with no pending root file. A pending root file that differs from an existing round-N file, empty or not, is still a round collision and is filed at max+1, as AC-1 v1 says.
2. **Over a legacy root file the Reviewer overwrote, the filing commit restores the merge-base blob.** When `REVIEW.md` at `git merge-base claude/rev-<FR> main` exists and the Reviewer overwrote it, the filing commit files the Reviewer's blob at the library path and puts the merge-base blob back at the root, instead of removing the root file. The branch's net change to the root `REVIEW.md` against the merge-base is nil, so the legacy file stays unchanged on `main` after the merge. This is DEC-0023 Decision 3's exception, applied to the filing commit. It restores the merge-base's blob, not `main`'s current one, so the merge stays clean if `main` has since changed or migrated the file. This decision records the reading the implementation at `c537258` already has; no code changes for it.

**`breaking: false`.**
- Decision 1 fills a case AC-1 v1 left unspecified, in the direction AC-1 v1 already promised ("re-running finalize never adds a commit"). No behaviour AC-1 v1 required is withdrawn.
- Decision 2 states what AC-1 v1 already implied, read together with AC-5 and Out of scope.
- FR-0025 is unmerged (round 1, request-changes) and has no other implementer. The one code change, Decision 1, is round-2 rework that the round-1 review already requested.

FR-0025 goes to `version: 2`, `revisions: [DEC-0028]`; `last_breaking_revision` stays null. Rule 5 was checked: FR-0025's identity is unchanged.

**Why `neil`.** Neil decided the escalation. The decision changes the dispatcher's behaviour on a control-plane path (`template/scripts/dispatch.py`, a human-approval file) and sets how a hand-edited library file is treated in every project. It is ratified: Neil accepted the Reviewer's proposed default on 2026-10-30.

## Alternatives considered

- **Treat an empty filed round as absent and overwrite it in place at round N.** Rejected. It breaks "a filed round is never overwritten" (AC-6, DEC-0023 Decision 1), and the filing commit would rewrite a committed library file. That is the edit-after-filing the library exists to prevent.
- **File the synthesised body at the next free round once, then treat that round as filed.** Rejected. "Once" needs the dispatcher to know it already compensated. With no pending file the next run sees round N empty again and has no marker telling it to stop, which is the round-start marker DEC-0023 rejected the per-FR file over. It also leaves a misnumbered round in the library.
- **Refuse with one `ERROR` and a non-zero exit until a human removes the empty file.** Rejected. A re-run is how finalize recovers from a failed post or push. Making the recovery path fail on a hand-made anomaly costs more than flagging it with a `WARN`, and the verdict of record does not come from the library file (FR-0025 Solution space, fixed).

## Cascade

Non-breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0025-reviews-filed-per-fr-and-round-under-specs-reviews.md`, done in this commit:
  - AC-1's "Nothing to file" bullet carries Decision 1, its "One commit" bullet gains Decision 2's sentence, and its verification list gains the empty-filed-round re-run;
  - `version: 2`, `revisions: [DEC-0028]`, `updated: 2026-10-30`;
  - one Changelog line.
- `template/scripts/dispatch.py`, `_materialise_review_md`: Decision 1 only. The "nothing to file" branch returns for any filed round N when there is no pending root file, and prints the empty-file `WARN` in place of the guessed-round one when the file is empty. This is FR-0025's round-2 rework, **maintainer mode**, alongside B1 and N2. Decision 2 needs no code change.
- Tests:
  - `template/tests/unit/scripts/test_review_library_adversarial.py::test_rerun_over_an_empty_filed_round_adds_no_commit`: the strict `xfail` marker comes off once Decision 1 is implemented; until then it XPASSes and fails the run. FR-0025's Reviewer may tighten its body to assert that the first run also adds no commit and prints one `REVIEW-KEPT` and one `WARN` naming the empty file. It is a Reviewer-authored test from FR-0025's own round 1, not a pre-existing test.
  - Expected unchanged, and to be confirmed green unedited: every test in `test_review_library.py`, including `test_guessed_round_keeps_the_filed_file_and_warns_only_when_the_body_differs` (non-empty filed file) and the two legacy-restore tests named in Context; every DEC-0023 and DEC-0024 cascade id; and the rest of `test_review_library_adversarial.py`.
- `template/specs/_reviews/README.md`: no change. AC-6 pins only its four statements, and none depends on either decision.
- FR-0006, FR-0013, FR-0018, FR-0024: no change. DEC-0024 Decision 1's "a re-run with the round already filed adds no commit" is what Decision 1 makes true in the empty case.

## Changelog

- 2026-10-30: created (ratified). Neil accepted the Reviewer's proposed default for FR-0025 round 1's AC-1 escalation (N1) on 2026-10-30; Decision 2 records the Reviewer's round-1 ruling on N4. Recorded by the Architect.
