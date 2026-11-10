---
id: DEC-0010
title: FR-0013's `owns:` gains FR-0002's `test_dispatch_metrics.py` for the Reviewer only, bounded to one harness repair — the `pr.review` test's `subprocess.run` stub locates `gh pr review` by argv instead of assuming it is the first call, because AC-11 resolves the implementation branch with `git show-ref` first
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0013's PR merges
satisfies: []
constrained_by: [FR-0002]
revises: FR-0013
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Revise FR-0002 in place (`revises: FR-0002`, version bump) as DEC-0002 and DEC-0007 did for FR-0009 and FR-0014"
  - "Have FR-0002's own Reviewer (a backfill run) repair the stub under FR-0002"
  - "Have the Developer order `_finalize_rev` so `gh pr review` stays the first subprocess call"
  - "Mark the three parametrisations `xfail` or skip them until a later housekeeping FR"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  The three red cases pin FR-0002 AC-5's guarantee — one `pr.review`
  record with `verdict`, `posted_as` and `round` — and that guarantee is
  intact at `0bf67c8`; what broke is the stub's private assumption that
  `_finalize_rev`'s first `subprocess.run` is `gh pr review`, which FR-0013
  AC-11 (DEC-0009) falsifies by running `git show-ref` first. No FR-0002
  sentence changes, so under ADR-0001 rule 2 there is nothing to revise on
  FR-0002; what changes is FR-0013's footprint, from which FR-0009/FR-0010
  derive the Reviewer's write grants, and DEC-0008 is the precedent for
  recording exactly that. The edit is bounded to the one stub and the one
  assertion so the Reviewer has no discretion to widen it.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0010: FR-0013's `owns:` gains FR-0002's `test_dispatch_metrics.py` for one bounded harness repair

## Context

FR-0013's maintainer-mode Developer round 2 (`0bf67c8`) implemented DEC-0009 / FR-0013 v3 in full, including AC-11: every point on the rev leg resolves the implementation role through `_implementation_branch_for_fr`, and `_finalize_rev` now does so *first* — `git show-ref` for `claude/dev-<FR>`, then `claude/mnt-<FR>` — before it loads the PR record and posts the review. One FR-0002 test went red in all three of its parametrised cases:

`template/tests/unit/scripts/test_dispatch_metrics.py::test_reviewer_finalize_emits_pr_review_with_verdict_posted_as_and_round` (`# covers hub-tooling FR-0002:AC-5`) replaces `dispatch.subprocess` wholesale with a `fake_run` whose canned return is indexed by call position (`rc = gh_rc if len(calls) == 1 else 0` — "first call fails with the own-PR message when asked; the `--comment` retry succeeds") and then asserts `calls[0][:3] == ["gh", "pr", "review"]`. At `0bf67c8` the first call is `git … show-ref …`. The two `gh_rc == 0` cases reach `REVIEW-POSTED`, emit the correct `pr.review` record, and fail only on `calls[0]`; the own-PR case (`gh_rc == 1`) hands its canned failure to `git show-ref claude/dev-FR-0100` instead of to `gh`, so the resolver falls through to `mnt`, finds no `mnt` PR record, and `_finalize_rev` exits 1 with AC-11's "no parent PR" error before any `gh` call. The Architect reproduced all three at `0bf67c8`. The sibling `test_reviewer_finalize_that_fails_at_gh_emits_nothing` returns failure for every argv and indexes nothing, so it is green.

Two facts decide the shape. First, the behaviour FR-0002 AC-5 pins is intact: the record's `kind`, `role`, `object_ids`, `run_id`, `parent_pr_number`, `verdict`, `posted_as` and `round` are exactly what the test expects once the stub stops mis-routing the canned failure — verified by the Architect in a throwaway copy of `template/` outside the repository (the whole file: 25 passed, 1 skipped, the skip being the pinned-baseline test that needs the hub checkout). AC-5's own verification clause is "Verified with `gh`/`git` subprocess stubs; no network", so a stub that answers `git` argv is inside FR-0002's stated method, not a change to it. Second, the file is outside FR-0013's `owns:` and outside DEC-0008's bounded list. FR-0009 AC-4 and FR-0010 AC-5 derive a dispatched Reviewer's `Edit`/`Write` grants from the FR's `owns:`, so without a DEC the FR-0013 Reviewer cannot make the edit; and FR-0010's Notes and AC-12 name this very file as one that "must pass unchanged" — for FR-0010's own change, whose guard is the two `dispatch.spawn` tests, not this one. (FR-0002's `owns:` predates the practice of listing test files and names only `template/tests/fixtures/metrics/**`; the file was written by FR-0002's Reviewer, carries only FR-0002 annotations, and DEC-0003 and DEC-0005 both call it FR-0002-owned. FR-0010 and FR-0014 list it under `reads:`.)

The constraint that made the shape non-obvious is the precedent split. DEC-0002 (FR-0009), DEC-0005 (FR-0010) and DEC-0007 (FR-0014) each revised the *merged* FR at `tier: neil` with `breaking: true` — but in each of those a guarantee the human had approved narrowed (an AC sentence changed) and the test was re-pointed at the narrowed guarantee. DEC-0006 and DEC-0008 were `tier: architect`, `breaking: false`, and revised the *in-flight* FR: nothing a human approved changed; a footprint or a seam caught up with a decision already made. This item is the second kind. No FR-0002 guarantee narrows, no FR-0002 sentence changes, and the test asserts the same record after the repair as before. ADR-0001 rule 2's carve-out ("edits that do not alter meaning are not changes") is the reason a DEC on FR-0002 would be recording a revision that did not happen and charging a merged FR a version step for it.

## Decision

FR-0013 is revised in place (`version: 4`, `breaking: false`, `last_breaking_revision` stays 3):

1. **`owns:` gains** `template/tests/unit/scripts/test_dispatch_metrics.py` — for the Reviewer only, write bounded to item 2. The file stays FR-0002's; FR-0013's ownership is additive, Reviewer-only, and limited to this repair, exactly as DEC-0008 did for `test_dispatch_finalize.py` and `test_dispatch_wave_finalize.py`.
2. **The exact permitted change.** In `test_reviewer_finalize_emits_pr_review_with_verdict_posted_as_and_round`, and nowhere else in the file, the FR-0013 Reviewer is authorised to make **only** these changes:
   - `fake_run` returns a neutral success — `SimpleNamespace(returncode=0, stdout="", stderr="")` — for any argv whose first element is not `"gh"`, after appending the argv to `calls` as it does today. (An empty `stdout` is deliberate: `_ff_push_impl_onto_rev`'s `rev-parse` calls then see equal head SHAs and take the "already at the rev tip" `NOTE` path, which is what the `gh_rc == 0` cases already print at `0bf67c8`.)
   - The canned-return rule counts `gh` calls only: the **first `gh` argv** returns `gh_rc` with `gh_stderr`, every later `gh` argv returns 0 (the `--comment` retry). The existing comment line is reworded to say so.
   - `assert calls and calls[0][:3] == ["gh", "pr", "review"]` becomes a by-argv locate — `next(c for c in calls if c[:3] == ["gh", "pr", "review"])` or an equivalent `any(...)` assertion — so the test states "a `gh pr review` was issued" without assuming its position.
   - A one-line comment citing `DEC-0010` and FR-0013 AC-11 is permitted at each of the two edit sites (the stub and the assertion), at most one line each. The module docstring is not edited.
   - Everything else stands: the `# covers hub-tooling FR-0002:AC-5` annotation, the parametrisation table and its five columns, the `_save_pr_record` / `_write_log` / `_lock` setup, the five-positional-argument `_finalize_rev` call (FR-0013 Notes record that this file pins that signature), the `rc == 0` assertion, the record assertions, the transcript-leak assertion and the `REVIEW-POSTED` assertion. No other test, fixture, helper or annotation in the file changes — in particular `test_reviewer_finalize_that_fails_at_gh_emits_nothing` (green at `0bf67c8`), the two `dispatch.spawn` tests FR-0010 AC-12 cites as its guard, and `test_role_permissions_and_finding_line_are_unchanged_against_the_pinned_baseline`.
   - The file is LF in the index; the edit must preserve LF (on Windows, write with `newline="\n"` or an editor that keeps the file's endings — a default `write_text` rewrites every line as CRLF and turns a two-hunk edit into a whole-file diff).
3. **AC-10's exception clause is made complete.** AC-10's sentence "Every test that passed before this FR still passes except the FR-0006 AC-6 overwrite test, which DEC-0001's cascade re-points" gains the two further tests that DEC-0007 and this DEC bound, each with the reason, so the AC the Reviewer pins AC-10 against names every merged test this FR's PR may touch. No behaviour changes; the sentence was already incomplete after DEC-0007 and DEC-0008 left it to Notes.
4. **FR-0002 is not revised.** No AC text, `owns:`, version or Changelog on FR-0002 changes; it stays at its implicit `version: 1`. The trace from FR-0002's side is this DEC's `constrained_by: [FR-0002]` and the `DEC-0010` comment in the test.

`breaking: false` under ADR-0001 rule 3: the implementation at `0bf67c8` is correct after this revision — no AC changes meaning, no implementer changes, and the repair this DEC authorises restores a test to asserting what it already asserted. `tier: architect`: FR-0013 is `ready`, dispatched but unmerged, the Architect owns it; the footprint widening adds no policy, no human-approved guarantee narrows (the factor that made DEC-0002, DEC-0005 and DEC-0007 `neil`), and the underlying behaviour change is DEC-0009's AC-11, which rides on the same PR. Recorded `proposed`; live for the design (indexer `LIVE_DEC_STATUSES`); ratified when FR-0013's PR merges, where Neil sees the two-hunk diff to the FR-0002 test beside DEC-0007, DEC-0008 and DEC-0009. What Neil ratifies, concretely: (a) FR-0013's Reviewer may make the one bounded edit in FR-0002's test file; (b) that edit is a harness repair, not a revision of FR-0002, so FR-0002 takes no version step. If Neil reads (b) the other way, the route is a `neil`-tier DEC revising FR-0002 in place of this one — the test edit itself is the same. Rule 5 does not apply — FR-0013's identity is unchanged.

## Alternatives considered

- **Revise FR-0002 in place (`revises: FR-0002`, version bump), per DEC-0002 / DEC-0007.** Rejected: those DECs recorded a guarantee that narrowed and re-pointed the test at the narrower guarantee. Here no FR-0002 sentence changes and the test asserts the same record after the edit; a DEC on FR-0002 would record a revision that did not happen, put a merged FR at `version: 2` for a stub's call-ordering assumption, and — since the change would have to be `breaking: false` (no implementer changes) — leave a DEC in FR-0002's live slice that says nothing about FR-0002. ADR-0001 rule 2 carves exactly this out. The footprint is what changes, and DEC-0008 is the precedent for recording that on FR-0013.
- **Have FR-0002's own Reviewer (a backfill run) repair the stub.** Rejected for DEC-0008's reason: the repair exists only because of FR-0013's behaviour change and must land in FR-0013's PR for its suite to be green; a backfill on a merged FR that cannot pass until an unmerged FR lands is the wrong order, and it costs a one-shot run where one two-hunk edit will do.
- **Have the Developer reorder `_finalize_rev` so `gh pr review` stays the first subprocess call.** Rejected: AC-11 says `_finalize_rev` resolves the parent PR from the implementation role's record, which needs the role, which needs `show-ref`; deferring that until after the `gh` call would mean posting a review before knowing which PR to post it to. A test's private assumption about call order is not a contract the implementation should bend to, and `test_reviewer_finalize_that_fails_at_gh_emits_nothing` in the same file already shows the harness works without it.
- **`xfail` / skip the three cases until a housekeeping FR.** Rejected under ADR-0001 rule 2 and the DEC-0002 precedent: FR-0002 AC-5's `pr.review` guarantee is still worth pinning and is pinned by nothing else; the repair is two hunks and the Reviewer round that needs it is running anyway.

## Cascade

None — non-breaking. For the record, the artifacts this DEC touches:

- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md` — `owns:` gains the bounded FR-0002 test file; AC-10's exception clause completed (item 3); `version: 4`, `revisions: [DEC-0008, DEC-0009, DEC-0010]`, `last_breaking_revision: 3`, `updated` unchanged (same day); Notes and Changelog lines. Done in this commit.
- `template/tests/unit/scripts/test_dispatch_metrics.py` (FR-0002's; FR-0013 Reviewer, round 2, bounded as in Decision item 2).
- `template/scripts/dispatch.py` — **no change**; `0bf67c8` satisfies FR-0013 v4.
- `projects/hub-tooling/specs/FR-0002-pipeline-instrumentation-metrics-log.md` — **no change** (Decision item 4).
- `template/tests/unit/scripts/test_dispatch_finalize.py`, `test_dispatch_wave_finalize.py` — **no change** beyond DEC-0008's bounds; `test_dispatch_postapprove.py`, `test_dispatch_review_artifact.py` — FR-0013-owned, DEC-0009's Cascade governs.
- `specs/decisions/DEC-0008-*.md`, `DEC-0009-*.md` — **no change** (proposed, ride on the same PR).

## Changelog

- 2026-09-21: created (proposed) — from the Orchestrator's round-3 escalation brief (three red FR-0002 AC-5 parametrisations at `0bf67c8` after DEC-0009's AC-11); failure shape and the bounded repair reproduced by the Architect.
