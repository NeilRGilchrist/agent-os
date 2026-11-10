---
id: DEC-0026
title: "FR-0024's `REVIEW.md` read sites follow FR-0025: the prefix applies to the `specs/_reviews/` library reads and the staged root `REVIEW.md` index read, and the decoy check asserts the library, not the root"
tier: architect
status: ratified  # ratified by Neil on 2026-11-04, recorded in PR #33
satisfies: []
constrained_by: [FR-0025]
revises: FR-0024
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave FR-0024 as written and let its Developer escalate"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0024 AC-2 and AC-3 enumerate REVIEW.md reads at the root path. FR-0025
  lands first in lane A, and it replaces those reads with library reads
  (specs/_reviews/<FR>-r<N>.md) plus a staged-root index read. Restating the
  sites now keeps FR-0024's site list true when it is dispatched, without
  changing its prefix rule.
created: 2026-09-26
updated: 2026-11-04
---

# DEC-0026: FR-0024's review read sites follow FR-0025

## Context

FR-0024 (ready, not dispatched, lane A after FR-0018) makes every worktree file and every `<rev>:<path>` read prefix-correct. AC-2 lists "`PR_BODY.md` and `REVIEW.md`, read and written". AC-3 counts 10 object-read sites, including "the `REVIEW.md` `cat-file` and `show` reads" and the index form `:REVIEW.md`. Its decoy check asserts that `_read_review_md_on_branch` returns "the project's `REVIEW.md`". After FR-0025, which now precedes FR-0024, those reads are library reads, and the root `REVIEW.md` is read only from the Reviewer's index or tip as the pending handoff.

## Decision

1. **AC-2's list** reads "`PR_BODY.md`, the Reviewer's root `REVIEW.md` handoff, and the `specs/_reviews/` library file (FR-0025), read and written".
2. **AC-3's site list** reads "the review reads: the library listing and `show`/`cat-file` of `specs/_reviews/<FR>-r<N>.md`, and the root `REVIEW.md` reads FR-0025 AC-1 makes, at the tip, in the index and at the merge-base". Each names `<prefix><path>`. The count "10" becomes "every", since FR-0025 changes the number. The decoy fixture keeps a decoy root `REVIEW.md` and gains a decoy `specs/_reviews/<FR>-r1.md` at the repository top. `_read_review_md_on_branch` returns the project's library file, and finalize never files or reports the decoy.
3. **`depends_on` is unchanged.** FR-0024 already follows FR-0018, which now follows FR-0025.

**`breaking: false`.** FR-0024 has no implementation. It goes to `version: 2`, `revisions: [DEC-0026]`. Rule 5 was checked: identity unchanged.

## Alternatives considered

- **Leave FR-0024 as written.** Rejected. Its Developer would find a site list that no longer matches `dispatch.py` and would escalate. That is one Architect pass spent later instead of now.

## Cascade

Non-breaking. Updated in this commit:
- `projects/hub-tooling/specs/FR-0024-subdirectory-aware-dispatcher.md`:
  - AC-2 and AC-3 each gain one sentence citing this DEC;
  - `version: 2`, `revisions: [DEC-0026]`, `updated: 2026-09-26`;
  - one Changelog line.

Tests: none. FR-0024's test file does not exist yet.

## Changelog

- 2026-09-26: created (proposed) with FR-0025.
- 2026-11-04: status `proposed` → `ratified`. Neil ratified it after FR-0024 merged in PR [#32](https://github.com/NeilRGilchrist/cos-agent-hub/pull/32) (commit `1c1e69b`), whose implementation follows it: the review reads use FR-0025's `specs/_reviews/` library under the project prefix (FR-0024 AC-2, AC-3). #32's description named only DEC-0031, so this DEC was left `proposed` at merge. Recorded by the Chief of Staff in PR [#33](https://github.com/NeilRGilchrist/cos-agent-hub/pull/33).
