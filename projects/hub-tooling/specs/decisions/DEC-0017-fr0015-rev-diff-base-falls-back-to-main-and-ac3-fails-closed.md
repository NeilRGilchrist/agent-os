---
id: DEC-0017
title: "FR-0015 before dispatch: AC-2's diff base falls back to `main` when a Reviewer has no implementation branch; AC-3's leftover-work read fails closed instead of reusing FR-0006's fail-open helpers; AC-4's digest record lives under the call-time `DISPATCH_DIR`, hashes the bytes read back, and never changes how the permission file is written"
tier: architect
status: ratified
satisfies: []
constrained_by: [FR-0006, FR-0013]
revises: FR-0015
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Add test_dispatch_postapprove.py to FR-0015's owns: and re-point the two red tests"
  - "Change _finalize_base_branch to return main when no implementation branch exists"
  - "Route AC-3 through _unstaged_paths/_untracked_paths as the Notes said, and accept that a failed git read passes"
  - "Store the AC-4 digest in the lock file or the spawn record"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  A prototype of FR-0015 as written, run against a clean clone at a8889df,
  turned exactly two existing tests red. For a Reviewer with no implementation
  branch, AC-2 diffs against a claude/dev-<FR> that does not exist, and "a diff
  that cannot run is a refusal" fires. The Reviewer's worktree was cut from
  main in that case, so main is the true base; saying so keeps both tests green
  unedited and keeps FR-0015 owning no existing test file. The same audit found
  that AC-3's recommended helpers return [] when git fails, which contradicts
  FR-0015's own fixed rule that a check that cannot run is a refusal. It also
  found four ways AC-4's record could leak into, or change, byte-identity tests.
  All three are clarifications to an FR with no implementer yet.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0017: FR-0015 before dispatch — rev diff base, fail-closed AC-3, AC-4 record placement

## Context

Before FR-0015 dispatched, the wave-2 Architect session had an agent audit it. The agent read-only audited the ten dispatcher test files FR-0015 lists in `reads:`, plus `test_dispatch_review_artifact.py`, `test_dispatch_gates.py`, `test_dispatch_metrics.py`, `test_dispatch_wave_finalize.py` and `test_dispatch_env_preflight.py`. It then prototyped AC-1 to AC-5 exactly as written in a throwaway clone at `a8889df`:
- AC-2 used `_git_capture(["diff", "--name-only", f"{base}...{branch}"])`, placed after `gat`'s early return and before `_finalize_revalidate_stale_branch`.
- AC-3 used `_unstaged_paths` / `_untracked_paths`.
- AC-4's digest was stored under `DISPATCH_DIR`.
- AC-5 was widened to `rev`, `bkf` and `mnt`.

The unmodified dispatcher passed 566 tests. The prototype passed 564 and failed 2, the two a static read predicted:
- `test_dispatch_postapprove.py::test_no_implementation_branch_is_one_note_and_not_an_error` (L559). This rev finalize has neither `claude/dev-<FR>` nor `claude/mnt-<FR>`. `_finalize_base_branch` (dispatch.py L4076) then returns `claude/dev-<FR>` by name even though it does not exist. `git diff claude/dev-FR-0001...claude/rev-FR-0001` exits 128, and AC-2's "a `git diff` that cannot run is a refusal" turns rc 0 into rc 1 plus an `ERROR`.
- `test_dispatch_postapprove.py::test_neither_branch_is_the_existing_error_naming_both_candidates` (L2364). Same fixture. The rc stays 1, but the single `ERROR` is now the diff failure, not "no parent PR".

FR-0015 owns no existing test file (AC-6). An `owns:` widening is the precedent (DEC-0008, DEC-0010, DEC-0012), but here the red is a defect in AC-2's wording, not in the tests. For a Reviewer with no implementation branch, `_base_branch_for_role` (L2613-2617) already cuts the worktree from `main`. So `main` is exactly the set of commits "the Reviewer's own" means.

The same audit found two more problems:
- **AC-3.** `_unstaged_paths` and `_untracked_paths` return `[]` when git fails (L3997-3998, L4056-4057). FR-0006 AC-3 needs that, because its `WARN` is advisory. FR-0015's fixed rules say "A check that cannot run is a refusal, not a pass", yet its Notes recommend routing AC-3 through exactly those helpers.
- **AC-4.** The implementation has four ways to break byte-identity tests FR-0015 does not own:
  - taking the permission-file path from the `adapter` argument, which the CLI and most tests pass as `None`;
  - a record store that is not the monkeypatched, call-time `DISPATCH_DIR`;
  - hashing by changing *how* the file is written, for example switching to `write_bytes` or `newline="\n"`. `Path.write_text` emits CRLF on Windows, and five tests compare against the pre-FR module's bytes;
  - putting the digest in the lock or the `worktree_status` segment.

## Decision

1. **AC-2's diff base.** `<finalize-base>` is `_finalize_base_branch`'s answer when that branch exists. When it does not exist, the diff base is `main`, the ref `_base_branch_for_role` cut the worktree from. This happens only for `rev` with neither `claude/dev-<FR>` nor `claude/mnt-<FR>`. A diff that still cannot run is a refusal, as before. `_finalize_base_branch` itself is **not** changed: the "adds no commits" measure and FR-0013 AC-11's `NOTE` stay exactly as today. The two tests above stay green unedited.

2. **AC-3 fails closed.** The two sets are computed with the same git commands FR-0006 AC-3's helpers run: `git diff --name-only` for tracked-but-unstaged changes, and `git ls-files --others --exclude-standard` for untracked, non-ignored files. They run through a path that reports failure, for example `_git_capture`'s `(ok, out)`. A command that fails is a refusal: one `ERROR` line, or `WOULD-REFUSE` in dry-run, naming the role, AC-3's check and the cause. `_unstaged_paths`, `_untracked_paths` and `_report_leftover_work` are unchanged, and FR-0006 AC-3's `WARN` lines stay byte-identical. The Notes sentence recommending those helpers for AC-3 is withdrawn.

3. **AC-4's record.**
   - **Where it lives:** in a file under the **call-time** `DISPATCH_DIR`, read as `dispatch.DISPATCH_DIR` at the moment of the call so that fixtures which monkeypatch it are honoured. For example `DISPATCH_DIR/<FR>.<role>.settings.sha256`.
   - **What it holds:** the permission file's path and the SHA-256 of the bytes **read back from disk** right after the write.
   - **Who writes it:** each adapter's `write_worktree_settings`, after its own write.
   - **What does not change:**
     - How the permission file is written: no switch to `write_bytes`, no `newline=` change. Permission files stay byte-identical on every host.
     - How finalize finds the file: from the record, never from the `adapter` argument.
     - Where the digest goes: never into the lock file or the spawn record's `worktree_status`.

4. **Constraints on the shared footprint helper.** `cmd_finalize`'s existing call stays exactly `mnt_footprint_violations(fr_id, branch)`, called once, and AC-2 and AC-3 do not call it. `test_dispatch_finalize.py`'s `seams` fixture pins the two-argument shape, and `test_commit_happens_before_push_and_footprint_check` pins the order `["footprint", "push"]`. FR-0015's `solution_space.open` bullet 2 is narrowed to match: the check helpers may share a private predicate, but `mnt_footprint_violations`'s signature, call site and output do not move.

5. **Error text names the cause.** Where a refusal quotes git's stderr, it quotes the first non-empty line. On an unknown revision the last line is git's usage text, and the `lines[-1]` pattern in `mnt_footprint_violations` prints that instead of the cause.

6. **The Notes' "Test doubles" paragraph is corrected** to match the audit:
   - `test_dispatch_finalize.py` drives `cmd_finalize` against a real temporary repository with a few stubs, not through doubles.
   - `test_dispatch_postapprove.py`, `test_dispatch_review_artifact.py` and `test_dispatch_gates.py` also execute the real `cmd_finalize`. They intercept only `gh`.
   - `test_dispatch_runnability.py` never runs it.

   `reads:` gains `test_dispatch_review_artifact.py` and `test_dispatch_gates.py`.

**`breaking: false`.** ADR-0001 rule 4 keys on implementers that must change. FR-0015 is `ready`, has never been dispatched, and has no implementer or citation, so no implementation is invalidated. FR-0015 goes to `version: 2` with `last_breaking_revision` unchanged (`null`).

**Why `architect`.** Each decision keeps FR-0015's intent and its Neil-approved scope. Decision 1 is a correct statement of "the Reviewer's own commits" in a case the text missed. Decisions 2 and 5 enforce a rule the FR already fixed. Decisions 3, 4 and 6 are placement. None changes what is refused on a real crossing. It ratifies at FR-0015's merge (the wave-1 convention; IDEA-0087).

## Alternatives considered

- **Add `test_dispatch_postapprove.py` to FR-0015's `owns:` and re-point the two tests.** Rejected. The tests are right: a Reviewer finalize with no implementation branch is today's legitimate `NOTE` path, and AC-2's wording, not the tests, mis-described it. Widening `owns:` would also hand a security FR's maintainer a 2,497-line test file.
- **Change `_finalize_base_branch` to return `main` when no implementation branch exists.** Rejected. Its answer also drives the "adds no commits" check and FR-0013 AC-11's `NOTE` naming both candidate branches, which the same two tests pin. Only AC-2's diff needs the fallback.
- **Keep the helpers and accept that a failed read passes.** Rejected. It contradicts FR-0015's fixed rule and DEC-0014's premise that the finalize check is the boundary.
- **Store the digest in the lock or the spawn record.** Rejected. Five byte-identity tests pin the lock key set and the `worktree_status` shape (`test_dispatch_env_preflight.py` L1373; `test_dispatch_stack_grants.py` L924, L969, L1530). AC-6 forbids a new metrics field.

## Cascade

None — non-breaking. No test changes. The spec edits (all in `projects/hub-tooling/specs/FR-0015-control-plane-paths-refused-at-finalize.md`, done in this commit):
- AC-2 gains the base fallback;
- AC-3 gains the fail-closed read;
- AC-4 gains the record placement;
- `solution_space.open` bullet 2 is narrowed;
- the Notes "Test doubles" and "Footprint overlap" paragraphs are rewritten;
- `reads:` gains two test files;
- `version: 2`, `revisions: [DEC-0017]`, and one Changelog line.

## Changelog

- 2026-09-25: created (proposed). From the wave-2 Architect session's pre-dispatch audit of FR-0015 (prototype at `a8889df`: 566 → 564 passing, the two failures named above).
- 2026-09-26: ratified by the merge of FR-0015 (PR #13, `e960543`), architect tier.
