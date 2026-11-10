---
id: DEC-0031
title: "FR-0024 revalidated against merged FR-0027, FR-0025, FR-0023, FR-0026 and FR-0018: `_worktree_project_root` is the one project-root helper and `DISPATCH_WORKTREE` follows it, FR-0018 AC-4's resolution and FR-0025's filing writes are prefix-correct, `footprint_root` is read only through `project_layout`, and stale references are restated"
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified by Neil merging #32 on 2026-11-04
satisfies: []
constrained_by: [FR-0018, FR-0023, FR-0025]
revises: FR-0024
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave FR-0024 at v2 and let its Developer find the merged sites"
  - "Give FR-0024 a second project-root helper beside _worktree_project_root"
  - "Make the dispatcher's @covers checks follow the layout in this FR"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  Five FRs merged after FR-0024 was ratified. FR-0018 added a project-root
  seam, the metrics redirect and a revalidate resolution with wt_path-relative
  paths. FR-0025 added library writes. FR-0023 made project_layout the one
  loader. Restating where each meets FR-0024's prefix keeps one definition of
  the project root and keeps the Developer from finding the gaps in review.
  FR-0024 has no implementation, so nothing breaks.
created: 2026-11-04
updated: 2026-11-04
---

# DEC-0031: FR-0024 revalidated against the wave-2 merges

## Context

FR-0024 (ready, v2, DEC-0026; `depends_on: [FR-0023, FR-0018]`) has not been dispatched. Under the architect role's rebase-and-revalidate rule it was read against `main` at `f719f89`, which carries FR-0027 (#24), FR-0025 (#25), FR-0023 (#26), FR-0026 (#28) and FR-0018 (#29). The dispatcher there has:

- **FR-0018:**
  - `_worktree_project_root(wt_path)`, which returns `wt_path`, and `spawn_role` exporting `DISPATCH_WORKTREE = abspath(_worktree_project_root(wt_path))`. Two tests pin it as the variable's one producer.
  - `_resolve_index_only_merge_conflict`, which uses one string, `_INDEX_MD_RELPATH = "specs/INDEX.md"`, both as a repo-relative path (the `diff --diff-filter=U` test and `git add`) and as a `wt_path`-relative path (the snapshot). It also runs `wt_path / "scripts" / "index-specs.py"` with `cwd=wt_path`, and snapshots `_INDEXER_SIDE_WRITES` (`CODEOWNERS`) under `wt_path`. FR-0018 r1 N-1 and DEC-0030's cascade left these for FR-0024.
- **FR-0025 and DEC-0028:** a filing commit that adds `specs/_reviews/<FR>-r<N>.md`, removes a pending root `REVIEW.md`, or restores a legacy merge-base `REVIEW.md`. DEC-0026 covered the reads, not these writes.
- **FR-0023:** `project_layout.load` as the one layout reader, imported optionally by the gate and the indexer, and `spec_footprint._git_ls_files(layout)`. `dispatch.py` does not import `project_layout` yet.
- **FR-0026 and FR-0027:** nothing in `dispatch.py`. It parses no ACs and no `ac_state`.

FR-0024 also carried stale references:
- AC-3's "gate evidence at L4957";
- Notes' "`test_dispatch_postapprove.py` L2040 and L2064";
- a project-rooted `reads:` entry (`specs/FR-0015-…`), which FR-0023's Out of scope said the Architect would normalise once `footprint_root: repo` landed;
- a Dependencies section written before any of these merged.

## Decision

1. **`_worktree_project_root` is AC-2's one helper, and `DISPATCH_WORKTREE` follows it.**
   - FR-0024 makes `_worktree_project_root(wt_path)` return `<worktree root>/<prefix>`, either as the "one helper" AC-2 requires or defined through it. There is one definition of the project root inside a worktree.
   - FR-0018's export is unchanged code, so `DISPATCH_WORKTREE` becomes `<wt>/<prefix>`. FR-0024 owns that change of value (DEC-0030 item 1).
   - **Verified** in AC-2's subdirectory fixture with a real `spawn_role`:
     - `<wt>/projects/demo/scripts/deploy-gate.py` appends to the primary checkout's `projects/demo/specs/_metrics`;
     - copies at `<wt>/scripts/` (the worktree root) and `<wt>/projects/other/scripts/` (a sibling) keep their own logs.
   - At prefix `""`, FR-0018's pinned tests pass unedited.
2. **FR-0018 AC-4's resolution moves to the prefix** (FR-0018 r1 N-1). AC-4 of FR-0024 lists it.
   - The conflicted-path test compares against `<prefix>specs/INDEX.md`, and `git add` stages that path.
   - The indexer is `_worktree_project_root(wt_path)/scripts/index-specs.py`, run with that cwd.
   - The `INDEX.md` snapshot and every `_INDEXER_SIDE_WRITES` path are rooted there.
   - A conflict confined to a repository-top `specs/INDEX.md`, outside the project, gets today's `ERROR`.
   - AC-4 gains one subdirectory verification case.
3. **FR-0025's filing writes are prefix-correct** (AC-3, extending DEC-0026 from reads to writes).
   - The filing commit adds `<prefix>specs/_reviews/<FR>-r<N>.md` and removes `<prefix>REVIEW.md`.
   - DEC-0028's legacy restore and the inherited-file comparison read `<merge-base>:<prefix>REVIEW.md`.
   - Nothing at the repository top is filed, removed or reported.
   - `--review-round` is unchanged.
   - AC-3 gains one verification case with the decoys.
4. **`footprint_root` is read only through `project_layout.load(REPO_ROOT)`.**
   - The import is optional, as in `deploy-gate.py` and `index-specs.py`. With no sibling `project_layout.py`, the footprint root is `project`.
   - Tracked files come from `spec_footprint._git_ls_files(layout)`. Item 10 narrows this.
   - This is FR-0023's "every reader goes through it". AC-6's refusal covers every `LayoutInvalid`, including DEC-0027's drive-letter rejection, at a non-empty prefix (item 9).
5. **No interaction with FR-0026 or FR-0027.** The dispatcher runs the gate in `<wt>/<prefix>`, and that gate applies exemptions and labelled detection. Stated in Dependencies so no Developer goes looking.
6. **Stale references restated.**
   - AC-3's line reference becomes a description: the `specs/_gates/<FR>-*.md` evidence paths collected from `diff --name-only`.
   - Notes' line numbers become test ids.
   - `reads:` normalises `specs/FR-0015-…` to `projects/hub-tooling/specs/FR-0015-…`, and gains `metrics_log.py`, `test_merge_friction.py`, `test_merge_friction_adversarial.py`, `test_review_library.py` and `test_project_layout.py`.
   - Notes gains the `_INDEX_MD_RELPATH` trap.
   - Notes' After-merge section gains:
     - hub-tooling's scripts are stale, so run `--upgrade` first;
     - hub-tooling's `AGENTS.md` sentence "`dispatch.py wave` does not work here" needs Neil's edit or approval. It is a human-approval file.
7. **Dependencies and ordering.**
   - `depends_on` stays `[FR-0023, FR-0018]`, both merged, so FR-0024 is unblocked.
   - Lane A (FR-0015 → FR-0016 → FR-0025 → FR-0018 → FR-0024) has only FR-0024 left, and no other active FR owns `template/scripts/dispatch.py`. Its `owns:` therefore overlaps no active FR. Overlaps with merged FRs are not overlaps: `find_overlaps` considers only `ready`, `in-progress` and `in-review`.
   - FR-0025, FR-0026 and FR-0027 are added as context.
8. **The dispatcher's own `@covers` checks keep FR-0024's scope** (decided by Neil, 2026-11-04). `_covers_tests_present` and `_pr_change_size` keep scanning `<prefix>tests/`, and count only the plain `@covers` form. The layout-aware scan is parked as IDEA-0096. The options he chose between are below.
9. **AC-6's early refusal applies only at a non-empty prefix** (FR-0024 r1 F-1, H-2; `specs/_reviews/FR-0024-r1.md` at `44aaae5`).
   - As written, AC-6 refused a malformed layout at every prefix. That contradicts AC-1, AC-8 and the fixed byte-identity clause at prefix `""`. The Reviewer reproduced it: an unconditional refusal turns FR-0018's `test_index_conflict_without_a_working_indexer_is_one_error_and_left_in_place[bad-layout]` red.
   - AC-6 now applies when the prefix is non-empty. At prefix `""` the dispatcher does not read the layout. AC-4's conversions are the identity there, so `footprint_root` cannot matter. The project's gate and indexer refuse the bad layout as today, including the worktree indexer in FR-0018 AC-4's resolution.
   - The implementation at `44aaae5` already behaves this way.
10. **AC-4's tracked-file sentence is conditional** (r1 F-6). `dispatch.py` lists no tracked files, so "tracked files come from `_git_ls_files(layout)`" had nothing to apply to. It now reads: should the dispatcher ever need a listing, it comes from `spec_footprint._git_ls_files(layout)`; today it lists none. The rule is kept rather than dropped, so a future listing does not re-derive the footprint root.
11. **Two known limitations are recorded under Out of scope** (r1 F-3, F-4). Both fail closed, and neither affects hub-tooling.
    - **F-3:** Cursor has no additional-directories equivalent. A repo-rooted FR that owns paths outside the project cannot be run through Cursor. AC-5 already allowed this; it is now stated as a limitation.
    - **F-4:** under `footprint_root: repo`, `_owns_entry_protected` and `mnt_permission_rules` compare `owns:` with `MNT_PROTECTED_GLOBS` in project coordinates. An `owns:` entry naming the project's own control plane in repository coordinates is therefore granted absolutely, rather than withheld (`dev`, FR-0009 AC-2) or narrowed (`mnt`). The relative deny still stops the agent from making the edit, so nothing unsafe lands. But `mnt` cannot maintain a repo-rooted project's own control plane.
      - **Restated by r2 F-7 (`specs/_reviews/FR-0024-r2.md` at `1d52c54`).** Finalize refuses the path differently by role. For `dev`, `rev` and `bkf` it refuses the change (FR-0015 AC-2). For `mnt` it refuses only an uncommitted change (FR-0015 AC-3). FR-0015 AC-2 does not apply to `mnt`, so a change committed on `claude/mnt-<FR>` passes `mnt`'s footprint check as owned.
      - So for `mnt` the relative deny is the only stop. The earlier text said "finalize's checks still refuse the path" for every role, and that was not true for `mnt`. The round-2 test at `37cda15` pins all three cases.
    - **Parking:**
      - Neil parked F-4's follow-up as IDEA-0097, "Protected owns: entries are detected in footprint coordinates under footprint_root: repo" (`2480bc9`). The FR-0024 limitation cites it.
      - F-3 is not parked.
      - F-5, the pre-existing `--permission-mode` gap, is IDEA-0098 and outside FR-0024.
      - This DEC parks nothing itself.
12. **AC-5's Windows spelling is confirmed by the live run** (r1 F-2, H-1; Neil, 2026-11-04).
    - **The run:** a logged-in shell, Claude Code with Haiku and `--permission-mode default`. The repository was `C:\t24\live`, a `projects/demo` project with `footprint_root: repo` and a synthetic FR-0001 owning `lib/**`. The session started in `<wt>\projects\demo`.
    - **Result:** `../../lib/x.py` was edited (`x = 2`). `../../other/y.py` was refused: `y = 1` was unchanged, and `permission_denials` named the `Edit` on `<wt>\other\y.py`.
    - **Confirmed spelling:** `Edit(//c/<realpath of the worktree root>/<glob>)`, and the same for `Write(...)`: lower-case drive, no colon, `os.path.realpath`, so no 8.3 short names. The additional directory is `"C:/<realpath of the worktree root>"`. `//C:/…` is not read as a drive root (Claude Code 2.1.302 and 2.1.317, per the Reviewer).
    - **No widening:** adding the worktree root to `additionalDirectories` does not widen the static relative `dev` grants. `other/y.py` is a `.py` file and was still denied.
    - **Spec changes:** AC-5 and the `solution_space.open` line state the spelling. The Notes' live-run step records the result. The Open question on headless rejection is closed.
    - The implementation at `44aaae5` already emits this spelling.

**`breaking: false`.**
- FR-0024 has no implementation and no tests, so no implementer must change (ADR-0001 rule 3).
- At prefix `""`, every item is today's behaviour, so the fixed byte-identity clause holds unchanged. Item 9 restores that property where AC-6's v3 text had broken it.
- Items 9 to 12 were added after round 1 implemented FR-0024 (`44aaae5`). They restate the spec to match that implementation, or record limitations outside it. No implementer changes.
- `owns:` is unchanged, so Neil's 2026-09-25 maintainer-mode approval still covers the write surface.
- FR-0024 goes to `version: 3` with `revisions: [DEC-0026, DEC-0031]`, and `last_breaking_revision` stays `null`. Rule 5 was checked: identity unchanged.

## Item 8: the question Neil answered

The dispatcher has two `@covers` checks of its own, both on `tests/`:
- `_covers_tests_present`, the rework precondition;
- `_pr_change_size`, which feeds FR-0002's `pr.opened` record (`tests_changed`, `covers_delta`).

Under FR-0024 v2 both look at `<prefix>tests/` only, for `@covers` only. For hub-tooling that directory holds bootstrap copies of the template tests: the precondition passes vacuously, and the PR metrics count almost nothing. The real tests are in `template/tests/` (qualified `# covers hub-tooling`) and the hub's `tests/`.

- **(a) Keep FR-0024's scope** (recommended default). `<prefix>tests/` and `@covers`, as written. Park a follow-up IDEA for a layout-aware scan. Cost: hub-tooling's rework precondition and PR change-size fields stay low-fidelity until then. The gate, which is what decides merges, already follows the layout.
- **(b) Follow the layout in FR-0024.** Scan `gate.test_dirs` under the footprint root and count `# covers <project_name>`, as the gate does. Cost: it changes FR-0002 `pr.opened` fields for any project with a layout, including a top-level one. So it has to narrow FR-0024's fixed byte-identity clause to "no layout, or a layout declaring neither `project_name` nor `gate.test_dirs`". It also adds a third concern to an FR already at three.

Neither option follows from ratified work: FR-0023 scoped the gate, and FR-0024 v2 says `tests/`. So the choice is Neil's.

**Closed, 2026-11-04: Neil chose (a), "Keep scope, park IDEA".** FR-0024's AC-2 and AC-4 stand as written for these two checks: `<prefix>tests/`, plain `@covers` only. The layout-aware scan is IDEA-0096, "dispatch.py's own @covers scans follow the project layout", parked on `chore/hub-tooling-upgrade`. FR-0024's Open question is closed with the same text.

## Alternatives considered

- **Leave FR-0024 at v2.** Rejected. Its Developer would meet FR-0018's seam pins, the `_INDEX_MD_RELPATH` double use and the library writes cold, and would escalate each in round 1.
- **A second project-root helper beside `_worktree_project_root`.** Rejected. It would break FR-0018's single-producer pin, and allow the metrics redirect and the agent cwd to disagree.
- **Make the dispatcher's `@covers` checks follow the layout here.** Rejected by Neil on 2026-11-04 (item 8). Parked as IDEA-0096.

## Cascade

Non-breaking. Updated in this commit:
- `projects/hub-tooling/specs/FR-0024-subdirectory-aware-dispatcher.md`:
  - `reads:`, AC-2, AC-3, AC-4, Open questions, Dependencies and Notes;
  - `version: 3`, `revisions: [DEC-0026, DEC-0031]`, `updated: 2026-11-04`;
  - one Changelog line.

Items 9 to 11, in a later commit:
- FR-0024 AC-6 (prefix condition and two verification lines);
- AC-4's tracked-file sentence;
- two Out-of-scope limitations;
- a Changelog line.

No code or test changes. The `[bad-layout]` test stays unedited and green.

Tests: none existed for FR-0024 when items 1 to 8 were written. Its Developer must keep the existing pins green unedited:
- FR-0018's seam and argv pins in `test_merge_friction.py` and `test_merge_friction_adversarial.py`;
- FR-0025's `test_review_library.py`.

## Changelog

- 2026-11-04: created (proposed), before FR-0024's dispatch. Item 8 awaits Neil.
- 2026-11-04: item 8 closed. Neil chose (a): keep scope, and park the layout-aware scan as IDEA-0096. Still proposed and non-breaking. FR-0024 stays at v3.
- 2026-11-04: items 9 to 11 added from the r1 review at `44aaae5` (F-1, F-6, F-3, F-4). Still proposed and non-breaking. FR-0024 stays at v3. F-2, the AC-5 Windows spelling, awaits Neil's live run.
- 2026-11-04: item 12 added. Neil's AC-5 live run passed and the Windows spelling is confirmed (r1 F-2). Still proposed and non-breaking. FR-0024 stays at v3.
- 2026-11-04: item 11 restated from the r2 review at `1d52c54` (F-7): for `mnt`, finalize refuses only an uncommitted control-plane change (FR-0015 AC-3), not a committed one, so the relative deny is the only stop. F-4's follow-up is parked as IDEA-0097 (`2480bc9`). Still proposed and non-breaking. FR-0024 stays at v3.
- 2026-11-04: status `proposed` → `ratified`. Neil merged PR [#32](https://github.com/NeilRGilchrist/cos-agent-hub/pull/32) (commit `1c1e69b`), whose description stated that merging ratifies this DEC. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
