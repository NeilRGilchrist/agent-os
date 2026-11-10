---
id: DEC-0024
title: "FR-0013 follows DEC-0023: AC-2's keep-or-synthesise rule applies to the round's library file (`specs/_reviews/<FR>-r<N>.md`), the inherited-file rule moves into the filing step, and AC-7's revalidate carve-out narrows to `specs/INDEX.md`"
tier: architect
status: proposed
satisfies: []
constrained_by: [FR-0006, FR-0018, FR-0025]
revises: FR-0013
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep AC-7's REVIEW.md half as a transition aid"
  - "Keep DEC-0022 Decision 2 in FR-0018 and have FR-0025 reuse its helper"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0013 AC-2 implements DEC-0001 at the root path, and AC-7 (via DEC-0022)
  resolves a root REVIEW.md conflict. Under DEC-0023 the review is filed per
  round and the root file never reaches a pushed branch. AC-2's rule must name
  the library file, DEC-0022's inherited-file rule becomes part of the filing
  step, and AC-7's REVIEW.md carve-out has nothing left to resolve. ADR-0001
  rule 7 allows one revises target per DEC, so this is DEC-0023's twin.
created: 2026-09-26
updated: 2026-09-26
---

# DEC-0024: FR-0013 follows DEC-0023

## Context

FR-0013 AC-2 (v3, DEC-0009) keeps the Reviewer's own `REVIEW.md` byte for byte. It synthesises one only when absent, treats an empty file as absent, and reads the file as UTF-8. DEC-0022 (v7) added two things:
- an inherited-from-`main` exclusion to AC-2, by merge-base comparison;
- a carve-out to AC-7 that resolves a revalidate conflict confined to `specs/INDEX.md` and `REVIEW.md`.

FR-0018 implements both and has not been dispatched. DEC-0023 now moves the committed review to `specs/_reviews/<FR>-r<N>.md` and removes the root file from every pushed branch.

## Decision

1. **AC-2 applies to the library file.**
   - The Reviewer's own staged or committed root `REVIEW.md` is still kept byte for byte (`REVIEW-KEPT`). An empty or absent one is still replaced by the synthesised body (`REVIEW-WRITTEN`, one `WARN` for an empty file).
   - "Kept" now means filed at the round's library path by one filing commit that also removes the root file (FR-0025 AC-1).
   - The byte count is the library blob's size. The UTF-8 reading rule is unchanged.
   - A re-run with the round already filed adds no commit.
2. **The inherited-file rule moves into the filing step.** A root `REVIEW.md` whose blob equals the one at `git merge-base claude/rev-<FR> main` is never filed and never removed, and one `WARN` says so. This is DEC-0022 Decision 2's comparison, unchanged, now owned by FR-0025 AC-1 instead of FR-0018 AC-5. After each project's one-time migration it never fires.
3. **AC-7's carve-out narrows to `specs/INDEX.md`.** DEC-0022 Decision 1's resolution applies when every conflicted path is `specs/INDEX.md`: regenerate with the worktree's indexer, conclude with `git commit --no-edit`, one `MERGE-RESOLVED` line. A `REVIEW.md` conflict is now left for a human like any other path. None arises once branches stop carrying the root file. During the migration window, a modify/delete conflict could not be resolved by "take ours" anyway.
4. **AC-9's tags are unchanged:** `WOULD-KEEP-REVIEW` and `WOULD-WRITE-REVIEW`. Their lines name the library path.

**`breaking: true`.** `_materialise_review_md` and `_existing_review_md_source` must change, and so must the tests below. FR-0013 goes to `version: 8`, `revisions` gains DEC-0024, `last_breaking_revision: 8`. DEC-0022 stays live for Decision 1's `INDEX.md` half; its Changelog records the narrowing. Rule 5 was checked: identity unchanged.

**Why `architect`.** It is a mechanical consequence of DEC-0023 (`neil`). Decision 3 removes a resolution that has nothing left to resolve. It widens no role's reach and changes no verdict. It lapses if DEC-0023 is rejected, and it ratifies at FR-0025's merge.

## Alternatives considered

- **Keep AC-7's `REVIEW.md` half as a transition aid.** Rejected. The only transition conflict is modify/delete, between an old-scheme branch that changed the root file and a `main` whose migration removed it. `git checkout --ours` cannot resolve that when ours is the deletion. Keeping the half would be code and tests for a case that cannot occur after the migration.
- **Keep DEC-0022 Decision 2 in FR-0018 and have FR-0025 reuse its helper.** Rejected. FR-0018 AC-5's cases assert `REVIEW-WRITTEN` at the root path, and FR-0025 would re-point them one FR later. Moving the rule saves implementing it twice.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md`, done in this commit:
  - AC-2 and AC-7 each gain one sentence citing this DEC;
  - `version: 8`, `revisions` gains DEC-0024, `last_breaking_revision: 8`, `updated: 2026-09-26`;
  - one Changelog line.
- `specs/decisions/DEC-0022-…md`: one Changelog line recording the narrowing, done in this commit. Its Decision text is left as history.
- `template/scripts/dispatch.py`: FR-0025 AC-1, **maintainer mode**.
- `template/tests/unit/scripts/test_dispatch_review_artifact.py` (FR-0013's). FR-0025's Reviewer re-points these from the root path to the library path: the `_show_bytes` helper gains the library path at each call site; `(wt / "REVIEW.md")` becomes the library path; commit-subject and count assertions allow exactly one filing commit.
  - `test_agent_committed_review_md_is_kept_byte_for_byte_and_not_recommitted`: plus one filing commit. "Tip unchanged" becomes "tip is the filing commit".
  - `test_agent_staged_uncommitted_review_md_is_folded_in_by_the_commit_step_and_kept`: the subjects list gains the filing commit at the tip. CRLF and em dash survive in the library blob.
  - `test_no_agent_review_md_is_synthesised_committed_and_kept_on_rerun`.
  - `test_rerun_over_an_agent_committed_file_is_idempotent`: the first run adds one filing commit, and the second adds none.
  - `test_untracked_review_md_is_not_the_agents_handoff_and_a_synthesised_one_is_committed`: the untracked root file is also still present and untracked.
  - `test_empty_committed_review_md_counts_as_absent_and_is_replaced_with_one_warn`, all three parameters: the empty root file is removed by the filing commit.
  - `test_empty_staged_review_md_counts_as_absent_in_dry_run_and_on_apply`, both parameters.
  - `test_utf8_body_with_em_dashes_survives_into_the_rework_brief_and_verdict`.
  - `test_verdict_file_finalizes_without_a_rev_log_and_is_announced_exactly_once`.
  - `test_verdict_file_takes_precedence_over_a_conflicting_log`.
  - `test_verdict_file_with_an_agent_committed_review_md_keeps_the_file_and_posts_the_verdict`.
- `template/tests/unit/scripts/test_dispatch_postapprove.py` (FR-0013's). Each gains the filing commit in a count or range:
  - `test_ff_commits_is_exactly_the_fast_forwarded_range_and_unions_across_rounds`: `round1` is taken after finalize, or it includes the filing commit;
  - `test_refreshed_pr_record_reflects_the_post_fast_forward_state_and_validates`: `commits_ahead == 3` becomes 4;
  - `test_mnt_only_fr_is_reviewed_approved_fast_forwarded_and_recorded_through_the_rev_leg`: `len(ff_commits) == 2` becomes 3;
  - `test_dev_present_rev_leg_is_byte_identical_to_the_round1_dispatcher`: the byte-identity against `1cad878` now excepts the filing commit and the `REVIEW-KEPT` line's path, as DEC-0009's `ff_commits` exception does. Everything else stays byte-identical.
- Expected unchanged, and to be confirmed green unedited:
  - in `test_dispatch_review_artifact.py`:
    - `test_agent_staged_review_md_previews_as_kept_from_the_index_in_dry_run`;
    - `test_keep_rule_does_not_swallow_a_missing_log`;
    - `test_pre_fr_dispatcher_overwrote_the_agents_file_so_the_keep_tests_bite`, which drives the pre-FR module and keeps `_show_bytes`'s root default;
    - `test_declared_verdict_drives_the_posted_flag_and_the_rework_resolution`;
    - `test_verdict_file_is_announced_once_in_dry_run_too`;
    - `test_missing_or_empty_verdict_file_is_one_error_with_no_push_no_gh_and_no_record`;
  - in `test_dispatch_postapprove.py`:
    - `test_approve_fast_forwards_the_implementation_branch_onto_the_rev_tip_and_pushes`;
    - `test_already_current_and_ahead_implementation_branches_get_one_note_and_no_push`, the idempotency guard;
    - `test_refused_fast_forward_exits_one_with_the_review_posted_and_says_so`;
    - `test_dry_run_rev_approve_previews_keep_and_ff_push_and_changes_nothing`;
    - `test_both_branches_present_every_rev_leg_resolver_picks_dev`;
    - every revalidate test (L1289 to L2159), since none finalizes `rev`.
  - Stubs of `_prepare_dev_worktree_for_rework` in `test_dispatch_metrics.py`, `test_dispatch_runnability.py` and `test_dispatch_wave_finalize.py`.
- Both test files join FR-0025's `owns:` (Reviewer only, bounded to the ids above) in this commit.
- Decision 3 moves no existing test. The `INDEX.md` and `REVIEW.md` conflict cases exist only in FR-0018's unwritten test file (DEC-0025).

## Changelog

- 2026-09-26: created (proposed) with FR-0025, as DEC-0023's twin on FR-0013.
