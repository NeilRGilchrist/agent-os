---
id: DEC-0009
title: FR-0013 AC-5(a)'s provenance is the dispatcher's own record of what AC-1 fast-forwarded (`ff_commits`), never ancestry of `claude/rev-<FR>`; a refused post-approve fast-forward exits non-zero; an empty `REVIEW.md` counts as absent; and the rev leg resolves the implementation role (`dev`, else `mnt`) so a maintainer-mode FR is reviewable through `finalize --role rev` (AC-11)
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0013's PR merges
satisfies: []
constrained_by: [FR-0006, FR-0002]
revises: FR-0013
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "E1 route (b): the Open question's contingency — exempt `tests/**`, `REVIEW.md` and the metrics log by path pattern"
  - "E1 hybrid: ancestry of `claude/rev-<FR>` while the implementation branch is ahead of the Reviewer tip, the record once it sits on it"
  - "E1: record the pre-fast-forward tip (`ff_base`) instead of the SHA list and re-derive the range at check time"
  - "E2: a follow-up FR for the rev leg's mnt resolution, with a Notes caveat that AC-1's mnt clause is unreachable in production"
  - "E3: exit 0 with a WARN after a refused fast-forward, since the review was posted"
  - "E4: keep a 0-byte committed `REVIEW.md` byte-for-byte and let the rework precondition fail"
  - "Two DECs (DEC-0009 for AC-5, DEC-0010 for AC-11) in one version step"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  The Reviewer's round-1 tests proved that "every touching commit is an
  ancestor of `claude/rev-<FR>`" exempts every path once the implementation
  branch sits on the Reviewer's tip — the only shape AC-1 produces — which is
  wider than the path-pattern exemption the FR's Open question rejected. The
  dispatcher performs that fast-forward itself and knows the exact range, so
  recording it is AC-5's literal text made exact with no change to the
  approved semantics (provenance, never pattern). The same round showed the
  rev leg cannot reach a maintainer-mode FR at all, that a refused
  fast-forward returned 0 and read as completed under `wave` (the L25 state),
  and that AC-2 contradicted itself on an empty file; all four are pinned in
  one revision because they land in one Developer round and one PR.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0009: AC-5(a)'s provenance is the dispatcher's fast-forward record; the rev leg resolves `mnt`; a refused fast-forward exits non-zero; an empty `REVIEW.md` is absent

## Context

FR-0013 v2 was implemented at `1cad878` (maintainer mode) and reviewed at `194cf54`/`5a43a25` (`Verdict: request-changes`, round 1 of 3). Seven of ten ACs are pinned green. The Reviewer's `## ESCALATION` raised four spec-level items, one of them blocking the Developer's round 2:

- **E1 / K1 — AC-5(a).** `_mnt_provenance_exemptions` (`dispatch.py:4009`) exempts a path when every commit touching it on `main..<branch>` is an ancestor of `claude/rev-<FR>`. DEC-0008's Notes confirmed that mechanism as "the Open question's default". It is vacuous in the shape AC-1 produces: the Reviewer branches from the implementation tip, so after the post-approve fast-forward the implementation branch *is* the Reviewer tip and every commit on it — including anything the maintainer committed before the Reviewer branched — is such an ancestor. `test_unowned_source_file_still_refuses_after_the_reviewer_fast_forward` (the AC's own four-item scenario) prints `src_outside/unowned.py exempt (fast-forwarded from claude/rev-FR-0001 — AC-5a)`, pushes and opens the PR. The FR's Open question said: "the path-pattern form is the fallback if provenance proves unreliable across the fast-forward; record it under `## FINDINGS` before changing the AC" — the Reviewer recorded it, so the trigger has fired and the AC is the Architect's to settle.
- **E2 — AC-1's mnt case is unreachable.** `_finalize_rev` (`:4574`) resolves the parent PR only from `_dispatch/<FR>.dev.pr.json` and `claude/dev-<FR>`; `_base_branch_for_role("rev")` (`:2107`) bases a fresh Reviewer worktree on `main` when only `claude/mnt-<FR>` exists. A maintainer-mode FR — Project A FR-0001, this FR's motivating case — therefore cannot be reviewed through the dispatcher at all, and the Reviewer's mnt test passes only because it writes a dev PR record by hand. Pre-existing, but AC-1 names the mnt case as verified.
- **E3 — exit code on a refused fast-forward.** `_finalize_rev` discards `_ff_push_impl_onto_rev`'s return: a diverged or dirty implementation branch prints one `ERROR` and finalize returns 0. Under `wave` the FR reads as completed with the Reviewer's commits off the PR — exactly the L25 state AC-1 exists to end.
- **E4 — AC-2 and a 0-byte `REVIEW.md`.** "Left byte-for-byte untouched" and "`_read_review_md_on_branch` returns a non-empty body" cannot both hold for an empty committed file; the code keeps it.

Two of the Reviewer's `## FINDINGS` bear on scope: `_read_review_md_on_branch` decodes with the host locale (pre-existing FR-0006; mojibakes em dashes on Windows and is why K5's byte count is wrong), and an untracked `REVIEW.md` is silently overwritten by the synthesised one. K2/K3 (AC-7's draft exemption turning green→red into "same or better", and `REVALIDATE … gate=pass` for a draft-exempt red gate) and K4/K5 are code defects against the ACs as written.

The constraint that made E1 non-obvious: the two adversarial pins `test_maintainer_writing_tests_directly_is_still_refused` and `test_mixed_provenance_on_one_path_is_not_exempt` are the whole point of "provenance, not path pattern", and any route had to keep them green.

## Decision

FR-0013 is revised in place (`version: 3`, `breaking: true`, `last_breaking_revision: 3`):

1. **AC-5(a): provenance is the dispatcher's record (E1, route a).** `_ff_push_impl_onto_rev` knows `<impl-tip>..<rev-tip>` at the moment it merges; on a successful fast-forward it writes those full SHAs as `ff_commits` on the implementation role's `_dispatch/<FR>.<role>.pr.json` — the record AC-1 already refreshes `head_sha` on — unioned with any earlier value so a round-2 approve keeps round 1's. The refused and nothing-to-do cases leave the key as it was; dry-run writes nothing (AC-9). `_mnt_provenance_exemptions` exempts a path only when every commit touching it on `main..<branch>` is in that set. No ancestry test remains. With no record, or with any touching commit outside it, the path is not exempt and the refusal is today's. The PR record is dispatcher state, not a metrics record; AC-10's "no new metrics record kind or field" is untouched. Both adversarial pins survive unchanged: a maintainer-written `tests/**` commit is not in the record; a maintainer edit after the fast-forward is not in the record. The four-item scenario now refuses the inherited unowned commit because `<impl-tip>..<rev-tip>` does not contain it.
2. **AC-1 gains the refused case (E3).** A refused fast-forward (diverged, worktree missing or dirty, merge or push failure) leaves the review posted, the branch and worktree untouched, prints one `ERROR` that says the review was already posted, and exits non-zero. The nothing-to-do `NOTE` cases exit 0. Under `wave` the FR is dropped at `rev-finalize` — the honest state.
3. **AC-2 gains two sentences (E4 + folded finding).** An empty or whitespace-only committed/staged `REVIEW.md` counts as absent: the synthesised one replaces it with one `WARN`. `_read_review_md_on_branch` and the byte count decode the file as UTF-8, never the host locale.
4. **AC-11 (E2).** Every point on the rev leg of the bare commands that names the Developer's branch or PR record resolves through `_implementation_branch_for_fr` (`dev` if `claude/dev-<FR>` exists, else `mnt`, else none): `_base_branch_for_role("rev")`, `_rev_sync_plan` / `_fast_forward_rev_worktree`, `_finalize_base_branch("rev")`, the `rev` tick's eligibility check, `cmd_finalize`'s dry-run parent-PR lookup, and `_finalize_rev`'s parent-PR resolution (implementation role's PR record, then the open PR for the implementation branch; the "no parent PR" error names that branch and remedy). `wave` is unchanged. When `claude/dev-<FR>` exists, output and records are byte-identical to today.
5. **K2/K3 confirmed** as the Reviewer reads AC-7 — no AC text change: newly red is one `ERROR`, non-zero exit, no push, draft or not; the `REVALIDATE` line never says `gate=pass` for a draft-exempt red gate and names the exemption.
6. **Scope of the two findings.** The locale-decode fix is folded (item 3). The untracked-`REVIEW.md` `WARN` and the dry-run vocabulary on a content-carrying crossing are not; both are recorded in FR-0013 Notes for a later housekeeping FR.
7. **Notes and Open question.** DEC-0008's AC-5 ruling is withdrawn in place with the reason; the AC-5 Open question records the fired trigger and its resolution; Notes carry the rulings above and the hand-sync consequence (a Reviewer branch merged into `claude/mnt-<FR>` by hand is not dispatcher-landed and is refused; Project A's maintainer round 2 was a re-entry from `main`, so the shape this FR was drafted from is the post-approve one AC-1 now performs and records).

`breaking: true` under ADR-0001 rule 4: the implementation at `1cad878` must change — `_mnt_provenance_exemptions` drops the ancestry test for the record, `_ff_push_impl_onto_rev` writes it, `_finalize_rev` propagates the refusal and resolves `mnt`, five more rev-leg sites resolve through `_implementation_branch_for_fr`, `_existing_review_md_source` / `_read_review_md_on_branch` change their empty-file and decoding behaviour — and the Reviewer's AC-5 harness must land the Reviewer branch through AC-1's step rather than a hand `--ff-only`. DEC-0003 set the precedent for `breaking: true` on an in-flight FR whose implementation must change.

`tier: architect`: FR-0013 is `ready`, dispatched but unmerged, and the Architect owns it. Item 1 keeps the semantics the human approved — provenance, never pattern — and makes the AC's own text exact; items 2–3 close gaps the AC left open; item 4 adds an AC whose whole content is "the code the FR already has, applied where the FR's own AC-1 needs it", inside the FR's existing `owns:`. Nothing here changes what the human approved (the maintainer-mode edit to `dispatch.py` under this FR's `owns:`). Recorded `proposed`; live for the design (indexer `LIVE_DEC_STATUSES`); ratified when FR-0013's PR merges, where it rides beside DEC-0007 and DEC-0008. Rule 5 does not apply — FR-0013's identity is unchanged.

One DEC, not two: ADR-0001 rule 3 makes each DEC one version step (`version == len(revisions) + 1`), so two DECs revising FR-0013 would be v3 and v4 for changes that come from one review round and land in one PR. DEC-0010 is not minted.

## Alternatives considered

- **E1 route (b): path-pattern exemption (`tests/**`, `REVIEW.md`, metrics log).** Rejected, as the Open question already rejected it: it is precisely the hole `test_maintainer_writing_tests_directly_is_still_refused` pins, and that test could not survive it. Record-free convenience is not worth a check that cannot do the one thing it exists for.
- **E1 hybrid: ancestry while the implementation branch is ahead of the Reviewer tip, the record once it sits on it.** Rejected: two mechanisms are two holes to reason about, and ancestry still launders anything the maintainer committed between opening the PR and the Reviewer branching (the four-item scenario's inherited commit). The record is exact in every shape the dispatcher produces; the shape it does not cover (a hand merge of the Reviewer branch into the maintainer branch) is not one the dispatcher performed and should not be one it vouches for.
- **E1: record `ff_base` (the pre-fast-forward tip) instead of the SHA list.** Rejected on a small margin: the list is a membership check with no second `rev-list` at check time, survives a later move of either branch, and unions cleanly across rounds. Either is correct; the Reviewer's suggested shape is the simpler one to pin.
- **E2: a follow-up FR.** Rejected: AC-1 names the mnt case as verified; AC-5(a)'s record is written by the very step E2 makes unreachable, so without AC-11 the AC-5 mechanism has no production path for the maintainer-mode FRs it was drafted for; the fix is one existing resolver applied at six sites in a file this FR owns; and a Developer round 2 is running anyway. A Notes caveat would leave AC-1's mnt clause honest only on paper.
- **E3: exit 0 with a WARN.** Rejected: it reproduces the L25 state silently — `wave` marks the FR complete, the Reviewer's commits are off the PR, and nobody is told. The duplicate review a re-run posts is FR-0006's idempotency model and is named in the `ERROR` line so it is a choice, not a surprise.
- **E4: keep a 0-byte file byte-for-byte.** Rejected: DEC-0001 protects the Reviewer's content, and an empty file has none; the non-empty-body guarantee is what FR-0006's rework precondition and FR-0008's gate evidence rely on. A `WARN` keeps the replacement visible.
- **Two DECs in one version step.** Rejected under ADR-0001 rule 3's arithmetic; see above.

## Cascade

- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md` — AC-1, AC-2, AC-5 amended; AC-11 added; AC-5 Open question resolved; DEC-0008's AC-5 ruling withdrawn in Notes; Notes carry the E1–E4 and K2/K3 rulings and the scope of the two findings; `version: 3`, `revisions: [DEC-0008, DEC-0009]`, `last_breaking_revision: 3`; Changelog. Done in this commit.
- `template/scripts/dispatch.py` (FR-0013-owned; maintainer-mode Developer, round 2) — K1 per item 1 (`_ff_push_impl_onto_rev` writes `ff_commits`; `_mnt_provenance_exemptions` checks membership, no ancestry); E3 per item 2 (`_finalize_rev` returns 1 when `_ff_push_impl_onto_rev` returns False, `ERROR` text says the review was posted); E4 and the UTF-8 decode per item 3; AC-11 per item 4; K2, K3, K4, K5 as the Reviewer specified.
- `template/tests/unit/scripts/test_dispatch_postapprove.py` (FR-0013-owned; Reviewer, round 2) — the AC-5 harness `_mnt_with_rev_landed_tests` lands the Reviewer branch through `_ff_push_impl_onto_rev` (or writes the `ff_commits` record it would write) instead of a hand `git merge --ff-only`; new pins for the refused-fast-forward exit code (AC-1), a hand-merged Reviewer branch with no record being refused (AC-5), and AC-11's four cases. Every existing assertion in the six AC-5 tests, and in every other test in the file, stands.
- `template/tests/unit/scripts/test_dispatch_review_artifact.py` (FR-0013-owned; Reviewer, round 2) — new pins for the empty-`REVIEW.md` case and the UTF-8 body (AC-2). Existing tests stand.
- `template/tests/unit/scripts/test_dispatch_finalize.py`, `test_dispatch_wave_finalize.py` — **no change** beyond DEC-0008's bounds.
- `specs/decisions/DEC-0008-*.md` — **no change** (proposed, rides on the same PR); its Notes-level AC-5 ruling is withdrawn in FR-0013's Notes, not edited here.
- FR-0006 — **not revised**: AC-11 changes which branch the rev leg resolves, not FR-0006's sync or commit rules; every FR-0006 test passes unchanged when `claude/dev-<FR>` exists (FR-0013 AC-10).

## Changelog

- 2026-09-21: created (proposed) — from the FR-0013 Reviewer's round-1 `## ESCALATION` E1–E4 (`REVIEW.md` @ `5a43a25`) and the Orchestrator's round-2 escalation brief.
