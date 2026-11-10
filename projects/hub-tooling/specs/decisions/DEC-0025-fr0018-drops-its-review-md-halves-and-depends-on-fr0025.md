---
id: DEC-0025
title: "FR-0018 drops its `REVIEW.md` halves: AC-4's revalidate resolution narrows to `specs/INDEX.md`, AC-5 is withdrawn (absorbed into FR-0025 AC-1), the per-FR-path Open question is closed, and FR-0018 now `depends_on` FR-0025"
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified by Neil merging #29 on 2026-11-03
satisfies: []
constrained_by: [FR-0006, FR-0013, FR-0025]
revises: FR-0018
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave FR-0018 unchanged and order it before FR-0025"
  - "Fold FR-0025 into FR-0018 as new ACs"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0018 AC-4 resolves a root REVIEW.md conflict, and AC-5 excludes an
  inherited root REVIEW.md. Under DEC-0023 no pushed branch carries a root
  REVIEW.md, and FR-0025 AC-1 owns the inherited-file rule. FR-0018 has not
  been dispatched, so withdrawing those halves before it runs saves
  implementing and then re-pointing them. Its metrics redirect and its
  INDEX.md resolution are unchanged.
created: 2026-09-26
updated: 2026-11-03
---

# DEC-0025: FR-0018 drops its `REVIEW.md` halves

## Context

FR-0018 (ready, not dispatched, lane A after FR-0016) has three concerns:
- the metrics redirect (AC-1 to AC-3, AC-6; DEC-0021);
- a revalidate resolution for `specs/INDEX.md` and `REVIEW.md` conflicts (AC-4; DEC-0022 Decision 1);
- an inherited-`REVIEW.md` exclusion (AC-5; DEC-0022 Decision 2).

Its Open question recorded the per-FR review path as "not in this FR", and DEC-0022's Alternatives rejected it for FR-0018. DEC-0023 now adopts that path in FR-0025, lane A, ahead of FR-0018. DEC-0024 narrows FR-0013 AC-7's carve-out to `specs/INDEX.md` and moves the inherited rule into FR-0025 AC-1.

## Decision

1. **AC-4 narrows to `specs/INDEX.md`.** The carve-out applies when every conflicted path is `specs/INDEX.md`. `REVIEW.md` is not special: a conflict on it is left for a human, like `README.md`. Its verification cases become:
   - an `INDEX.md`-only conflict;
   - `INDEX.md` plus `REVIEW.md`, which is `ERROR`, `UU` left in place and neither resolved;
   - `INDEX.md` plus `README.md`;
   - `INDEX.md` with no worktree indexer;
   - dry-run of each.

   The `REVIEW.md`-only and "both together, resolved" cases are dropped.
2. **AC-5 is withdrawn.** Its number is retired, not reused. The rule is FR-0025 AC-1's "inherited root file", with the same merge-base comparison.
3. **The Open question on a per-FR review path is closed:** adopted by DEC-0023 in FR-0025. The matching Out-of-scope bullet is removed.
4. **`depends_on` gains FR-0025.** Lane A becomes FR-0015, FR-0016, FR-0025, FR-0018, FR-0024.
5. **Title, Why, What, AC-7 and Notes follow.**
   - The title drops the `REVIEW.md` clauses.
   - AC-7's pinned-test list is unchanged. Those tests are FR-0025's re-pointed versions by the time FR-0018 runs, and FR-0018 must pass them unedited.
   - The dogfood's `REVIEW.md` steps are dropped.

**`breaking: false`.** FR-0018 has no implementation and no tests yet, so no implementer must change. FR-0018 goes to `version: 2`, with `revisions: [DEC-0025]`. `last_breaking_revision` stays `null`. Rule 5 was checked: identity unchanged. It is still "merge friction removed at the source", with one source handed to FR-0025.

**Why `architect`.** It narrows a Neil-approved, undispatched FR, and it removes work without adding any. DEC-0021, Neil's metrics decision, is untouched. It lapses if DEC-0023 is rejected: FR-0018 would then revert to v1.

## Alternatives considered

- **Leave FR-0018 unchanged and order it before FR-0025.** Rejected. FR-0018 would implement and test AC-5 and the `REVIEW.md` half of AC-4. FR-0025 would then re-point those tests in `test_merge_friction.py` one FR later, which is two cycles of work for a rule that ends up in FR-0025 anyway.
- **Fold FR-0025 into FR-0018.** Rejected. FR-0018 already carries a real-worktree metrics AC (AC-3) that needs its own Reviewer run. The review path is a separate, Neil-tier layout decision with its own migration. Keeping them apart keeps each PR reviewable, and lets FR-0025 land even if DEC-0021's fallback (option (b)) is triggered.

## Cascade

Non-breaking. Artifacts updated in this commit:

- `projects/hub-tooling/specs/FR-0018-merge-friction-metrics-rows-index-and-review-md.md`:
  - the title, Why item 3, What, AC-4, AC-5 (withdrawn), Out of scope, Open questions, Dependencies and Notes;
  - `depends_on: [FR-0016, FR-0025]`, `version: 2`, `revisions: [DEC-0025]`, `updated: 2026-09-26`;
  - one Changelog line;
  - `reads:` gains DEC-0024 and FR-0025's library test file.

  The filename keeps its slug, because paths are cited elsewhere.
- Tests: none. FR-0018's test file does not exist yet.
- `DEC-0022`: its Changelog records the narrowing (done with DEC-0024).

## Changelog

- 2026-09-26: created (proposed) with FR-0025.
- 2026-11-03: status `proposed` → `ratified`. Neil merged PR [#29](https://github.com/NeilRGilchrist/cos-agent-hub/pull/29) (commit `f719f89`), whose description stated that merging ratifies this DEC. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
