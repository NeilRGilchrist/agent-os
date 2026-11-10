---
id: DEC-0035
title: "FR-0024 AC-6 and DEC-0031 are narrowed for FR-0029: at prefix `\"\"` the dispatcher still never reads the layout for footprint conversions, but reads it for `mnt_own_test_globs` when deriving a `mnt` footprint, and a malformed layout then refuses `mnt` only"
tier: neil
status: proposed  # proposed | ratified | rejected | superseded — Neil ratifies by merging the PR that carries it (FR-0029's spec PR)
satisfies: []
constrained_by: [FR-0023, FR-0029]
revises: FR-0024
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Read `mnt_own_test_globs` only in a subdirectory project, as AC-6 reads the layout today"
  - "Configure the own-test globs somewhere other than `.agent-team/layout.yaml`"
  - "Hard-code ai-hub-poc's `tests/test_fr_{num}*.py` convention in the dispatcher"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0024 AC-6 and DEC-0031 item 9 say the dispatcher does not read the layout
  at prefix "". FR-0029 AC-6 adds a layout key for a `mnt` run's own test
  files, and the project that needs it (ai-hub-poc) is its own repository. So
  the statement is narrowed to the footprint conversions it was about. Nothing
  FR-0024 implemented changes, so nothing breaks.
created: 2026-11-05
updated: 2026-11-05
---

# DEC-0035: FR-0024 AC-6's prefix-`""` rule is narrowed to footprint conversions

## Context

FR-0024 AC-6 (v3, merged) says: "At prefix `""` the dispatcher does not read the layout (DEC-0031). Both of AC-4's conversions are the identity there, so `footprint_root` changes nothing, and the fixed byte-identity clause holds." DEC-0031 item 9 made that rule, so that a malformed layout at prefix `""` could not turn FR-0018's `[bad-layout]` test red.

FR-0029 AC-6 adds `mnt_own_test_globs` to `.agent-team/layout.yaml`. It names the test files that belong to an FR, so a maintainer may keep its own FR's tests in step. ai-hub-poc needs it, and ai-hub-poc is its own repository (prefix `""`). If the rule held literally, the key could only ever work in a subdirectory project.

## Decision

1. **AC-6's second paragraph is narrowed.** Its opening sentence now reads: "At prefix `""` the dispatcher does not read the layout for AC-4's conversions or AC-5's anchor (DEC-0031). It reads it only for `mnt_own_test_globs`, and only when deriving a `mnt` footprint (FR-0029 AC-6, DEC-0035)." The rest of the paragraph stands:
   - both conversions are the identity at prefix `""`;
   - `footprint_root` changes nothing;
   - a malformed layout is refused by the project's own gate and indexer.
2. **The refusal for `mnt` is FR-0029's.** When a `mnt` derivation needs the key and the layout is malformed, `maintain` and `finalize --role mnt` refuse with one `ERROR` before any worktree is created or file written (FR-0029 AC-6). No other role reads the key, so every other role's behaviour at prefix `""` is unchanged.
3. **Byte-identity holds.** With no layout file, or a layout without the key, every permission file and printed line at prefix `""` is unchanged (FR-0029 AC-8). The `[bad-layout]` test does not dispatch `mnt` and stays unedited and green.
4. **DEC-0031 item 9 is read with this narrowing.** It is not edited: a ratified DEC is history.

**`breaking: false`.** No FR-0024 implementer or test changes. `_layout_refusal`, `_layout_footprint_root` and `_footprint_relpath_fn` keep their behaviour, and FR-0029 adds a separate reader. FR-0024 goes to `version: 4`, with `revisions` gaining DEC-0035. `last_breaking_revision` stays `null`.

**Why `neil`.** FR-0024 is a merged control-plane FR (PR #32), and its byte-identity clause was approved by Neil. It is recorded `proposed`, and Neil ratifies it by merging the PR that carries it.

## Alternatives considered

- **Read the key only in a subdirectory project.** Rejected. The key would be dead in every project that is its own repository, and that includes the only project that needs it.
- **Configure the globs outside the layout.** Rejected. `layout.yaml` is already the one validated, agent-unwritable place for a project's shape (FR-0023), and a second file would need a second loader.
- **Hard-code ai-hub-poc's convention.** Rejected. The template has no per-FR test naming, so a hard-coded glob would grant every project's maintainer a test surface its CI does not recognise. It would also change every `mnt` permission file, turning FR-0024's and FR-0028's pinned `[mnt]` byte-identity tests red.

## Cascade

None — non-breaking. For the record:
- **`projects/hub-tooling/specs/FR-0024-subdirectory-aware-dispatcher.md`**, done in this commit:
  - AC-6 gains one sentence citing this DEC;
  - `version: 4`, `revisions` gains DEC-0035;
  - one Changelog line.
- **The code** lands with FR-0029's implementation (`_mnt_own_test_globs`). No FR-0024 test changes.

## Changelog

- 2026-11-05: created (proposed) with FR-0029, at Neil's request, before the spec PR's push.
