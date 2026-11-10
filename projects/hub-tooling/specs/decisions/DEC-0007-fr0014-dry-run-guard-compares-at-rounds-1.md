---
id: DEC-0007
title: FR-0014's byte-identical dry-run guard compares both dispatchers at an explicit `rounds=1` — the `--rounds` default is FR-0013 AC-8's to set, and the guard stops pinning it
tier: neil
status: ratified  # proposed | ratified | rejected | superseded — Neil ratifies at FR-0013 PR review
satisfies: []
constrained_by: [FR-0013]
revises: FR-0014
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Normalise the `rounds=` banner text and the `WOULD-RUN Round N/M` preview lines out of both outputs before comparing"
  - "Revise FR-0013 AC-8 to keep the `--rounds` default at 1"
  - "Delete or skip the guard test as superseded by FR-0013"
  - "Compare against a re-frozen post-FR-0013 baseline instead of the pre-FR-0014 dispatcher"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0014's Reviewer pinned an out-of-scope guard — dry-run wave stdout
  byte-identical to the pre-FR-0014 dispatcher after normalising timestamps
  and paths — so that FR-0014's per-phase flushing changed when bytes land,
  never what. Both sides of that comparison ran with the `--rounds` default,
  which FR-0013 AC-8 deliberately changes from 1 to 2; the whole diff at
  1cad878 is the two `rounds=` mentions and the one `WOULD-RUN Round 2/2`
  preview line that default drives. Passing `rounds=1` explicitly on both
  sides keeps every other byte under guard, exercises exactly the case
  FR-0013 AC-8 promises is unchanged ("`--rounds 1` still reproduces today's
  single-pass behaviour exactly"), and leaves the default where the later FR
  put it.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0007: FR-0014's byte-identical dry-run guard compares both dispatchers at an explicit `rounds=1`

## Context

FR-0014 (merged, PR #7) made `wave` flush stdout at every phase boundary (AC-5). Its Reviewer pinned, beside the AC-5 flush tests, an out-of-scope guard: `template/tests/unit/scripts/test_dispatch_wave_finalize.py::test_dry_run_output_is_byte_identical_to_the_pre_fr_dispatcher` drives `cmd_wave(apply=False)` on the current dispatcher and on the pre-FR-0014 module loaded from `git show aa6f5ee:template/scripts/dispatch.py`, normalises timestamps, elapsed times, synthesis file names and the repository path, and asserts the two outputs are equal. Its docstring states its purpose: "flushing changes *when* bytes land, never *what*." The FR's AC-5 text does not itself claim byte-identity; the guard is the Reviewer's stronger pin on FR-0014's own safety property, and it was merged under Neil's approval with the rest of the file.

FR-0013 (`depends_on: [FR-0006, FR-0011, FR-0014]`, in flight at `1cad878`) changes the `--rounds` default from 1 to 2 (AC-8), a decision the FR's Open question argued for and Neil approved with the FR. The maintainer-mode Developer implemented it as specified, and the guard went red: with no `rounds` passed, the current dispatcher prints `rounds=2` in the opening line and in the dry-run banner and adds one `WOULD-RUN  Round 2/2: Dev rework -> Reviewer re-review ...` preview line, while the pre-FR-0014 module prints `rounds=1` and no such line. The Architect re-ran the test with full diff output and confirmed that is the entire difference — three lines, all driven by the default. The Developer escalated rather than editing a test file outside FR-0013's `owns:`.

The constraint that makes this non-obvious is ADR-0001 rule 2. The guard is a merged FR's test and it now pins the absence of a change the spec graph has since decided to make — the DEC-0002 shape. Quietly editing it would be an untraced bend of FR-0014; leaving it red or skipping it would drop a guard that is still worth having on every byte the later FR did not touch. The honest record is a DEC on FR-0014 that says what the guard now guarantees and bounds the one edit that restores it.

## Decision

FR-0014 is revised in place (`version: 2`, `breaking: true`, `last_breaking_revision: 2`):

1. **AC-5** gains one scoping sentence: the byte-identity guard compares the current and the pre-FR-0014 dispatcher **with `rounds=1` passed explicitly on both sides**. The `--rounds` default is not part of what the guard pins; it belongs to FR-0013 AC-8, which is also where "`--rounds 1` still reproduces today's single-pass behaviour exactly" is specified and tested.
2. The guard test is narrowed by exactly that: `_wave(mod, _FakeAdapter(), apply=False, rounds=1)` on both runs. Nothing else in the comparison — the normalisations, the equality, the fixture repository, the pre-FR module — changes. The cascade below bounds the edit so the FR-0013 Reviewer has no discretion to widen it.

`breaking: true` under ADR-0001 rule 4 and the DEC-0002 / DEC-0005 precedent: no implementer of FR-0014 changes (`cmd_wave`'s flushing, the crash handler and both rev-leg `draft` call sites are untouched), but a merged test that pins the revised object must change for the suite to pass, and the cascade names it and bounds the change.

`tier: neil`: FR-0014 is a merged control-plane FR whose test file a human approved at PR #7, and this revision narrows a regression guard that approval covered. Recorded `proposed`; per ADR-0001 rule 8 and the indexer's `LIVE_DEC_STATUSES` the design proceeds on it. Neil ratifies at FR-0013's PR review, where this DEC rides beside DEC-0008. What Neil is ratifying, concretely: (a) `wave --rounds` defaults to 2 from FR-0013 on — already approved with FR-0013 AC-8, restated here because this is the DEC that lets a merged test stop contradicting it; (b) FR-0014's dry-run byte-identity guard is a `rounds=1` guard from now on. If Neil prefers the default to stay at 1, the change is FR-0013 AC-8's, and this DEC is rejected rather than amended — the guard then passes unchanged.

Rule 5 was checked and does not apply — FR-0014's identity (the rev-leg regression, crash visibility, per-phase flushing) is unchanged; one regression guard's condition is stated.

## Alternatives considered

- **Normalise the `rounds=` banner and `WOULD-RUN Round N/M` lines out of both outputs.** Rejected: it blinds the guard to future changes in exactly the lines FR-0013 touches — a wording drift in the rounds banner, a second preview line, a changed `WOULD-RUN` shape — and it edits the comparison logic rather than the input. Passing `rounds=1` keeps every byte compared and changes one argument.
- **Revise FR-0013 AC-8 to keep the default at 1.** Rejected: it discards an approved product default to protect a test. FR-0013's Why records the cost (Project A L3: the three-cycle budget goes unused and a request-changes verdict ends the wave), its Open question argued for 2, and Neil approved the FR with AC-8 in it. The Architect sees no reason to reopen it; if Neil does, the route is rejecting this DEC (see Decision).
- **Delete or skip the guard as superseded.** Rejected under ADR-0001 rule 2 and the DEC-0002 precedent: FR-0014's "when, never what" property is still FR-0014's and still worth pinning on every byte FR-0013 did not change; only the one default needed to leave the comparison.
- **Re-freeze the baseline at a post-FR-0013 commit.** Rejected: the guard's value is that its baseline predates FR-0014's own change; moving the baseline forward past FR-0014 would compare FR-0013's dispatcher with itself and prove nothing about flushing.

## Cascade

Breaking; every affected artifact:

- `projects/hub-tooling/specs/FR-0014-wave-rev-finalize-regression-and-crash-visibility.md` — AC-5 gains the scoping sentence; `version: 2`, `revisions: [DEC-0007]`, `last_breaking_revision: 2`, `updated` bumped; Notes and Changelog lines. Done in this commit.
- `template/tests/unit/scripts/test_dispatch_wave_finalize.py` (FR-0014-owned; FR-0013's `owns:` gains it under DEC-0008 for exactly this edit) — the FR-0013 Reviewer is authorised to make **only** these changes, in FR-0013's Reviewer phase:
  - `test_dry_run_output_is_byte_identical_to_the_pre_fr_dispatcher`: inside its `run(mod, root)` helper, the wave call becomes `_wave(mod, _FakeAdapter(), apply=False, rounds=1)`. Both sides go through the same helper, so one edit narrows both runs.
  - That test gains a one-line comment (or a docstring clause) citing `DEC-0007` and FR-0013 AC-8 as the home of the `--rounds` default. The module docstring may gain the same clause in its "pre-FR dispatcher" paragraph.
  - The `# covers hub-tooling FR-0014:AC-5` annotation stays. No normalisation regex, no assertion, no fixture, no helper (`_wave`, `_point`, `_install`, `_make_repo`, `pre_fr_dispatch`) and no other test in the file changes. In particular the AC-1/AC-2 bite checks, the AC-3/AC-4 crash tests, the flush-count tests and the subprocess tests are untouched — they pass at `1cad878`.
- `template/scripts/dispatch.py::cmd_wave` (FR-0014 implementer) — **no change**. The flushing, crash handling and rev-leg `draft` forwarding are as merged; FR-0013 AC-8's default change is FR-0013's and is verified by FR-0013's own tests (`test_dispatch_postapprove.py` / `test_dispatch_review_artifact.py`), including the "`--rounds 1` reproduces today's single-pass behaviour" clause, which is the same fact this guard now pins from the other side.
- `template/tests/unit/scripts/test_dispatch_runnability.py` (FR-0006-owned) — **no change**; its `cmd_wave` tests pass at `1cad878` (the Developer's full-suite run: 1243 passed, the two named failures only).
- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md` — `owns:` gains the FR-0014 test file for the Reviewer only, bounded as above. Done by DEC-0008 in the same commit series.
- No other object cites FR-0014 (index check 2026-09-21: FR-0013 is its only dependent, via `depends_on`).

## Changelog

- 2026-09-21: created (proposed) — from the FR-0013 maintainer-mode Developer's `## Notes for Reviewer` (AC-8 default-change fallout, `1cad878`); the three-line diff confirmed by the Architect re-running the guard with full output
- 2026-09-22: updated (ratified) - Reviewed and ratified by Neil Gilchrist in PR Review
