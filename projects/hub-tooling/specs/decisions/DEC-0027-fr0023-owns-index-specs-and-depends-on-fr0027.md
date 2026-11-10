---
id: DEC-0027
title: "FR-0023 owns `template/scripts/index-specs.py` for AC-1's layout error, states the empty-value rule, depends on FR-0027 instead of `0eef0f0`, checks AC-6's overlaps by rule rather than by a stale list, and refuses drive-letter gate directories in the layout"
tier: neil
status: ratified  # proposed | ratified | rejected | superseded — items 1, 3 and 6 decided by Neil 2026-10-30; the whole ratified by Neil merging the FR-0023 PR (#26) on 2026-11-02
satisfies: []
constrained_by: [FR-0021, FR-0026]
revises: FR-0023
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep index-specs.py in reads: and drop the indexer half of AC-1"
  - "Keep the 0eef0f0 dependency and cherry-pick it from the other hub"
  - "Keep AC-6's overlap list and update it by hand at review"
  - "Reject drive-letter entries in spec_footprint._validate_glob, for owns: too"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  AC-1 v1 required index-specs.py to report a malformed layout, but the file
  was only in reads:, so the Developer could not deliver it. Neil approved
  the widening and replaced the unreachable 0eef0f0 dependency with FR-0027.
  The other edits make implicit rules explicit (empty values, error position,
  one message in the gate) and replace an overlap list that went stale when
  wave 2 merged. Neil also decided that the layout alone refuses a
  drive-letter gate directory, which AC-3's no-ValueError promise needs.
created: 2026-10-30
updated: 2026-11-02
---

# DEC-0027: FR-0023 owns `index-specs.py` for AC-1 and depends on FR-0027

## Context

FR-0023 (ready, dispatched) was implemented at `9d48fd7` on branch `worktree-agent-a35b8f0f879bb5704`. The Developer escalated two items and two smaller findings.

1. **Footprint gap.** AC-1 requires `index-specs.py --validate` and plain mode to print a malformed-layout error under `Spec validation FAILED:` and exit 1. `template/scripts/index-specs.py` was only in `reads:`, and it is a hub `CLAUDE.md` human-approval file.
2. **Unreachable dependency.** FR-0023's Dependencies required the labelled-AC fix `0eef0f0` to merge before AC-6's layout reaches `main`. That commit exists only in the other hub (ADR-0002) and is not in this repository.
3. **Stale wording.** AC-6 expected the wave-2 overlaps (FR-0015/16/18 on `dispatch.py`, FR-0019/20/22 on `bootstrap.py`). Those FRs have merged, so `find_overlaps` no longer reports them.
4. **Unstated rule.** The Developer rejected an empty layout file and `gate: {}`, which the spec implied but did not say.
5. **Drive-letter gap** (Reviewer r1 ESCALATION on AC-1/AC-3, `specs/_reviews/FR-0023-r1.md` at `ab588d9`). Gate directories reuse the `owns:` rules, and `spec_footprint._validate_glob` rejects only a leading `/`. A Windows path such as `C:/…` in `gate.source_dirs` therefore passes validation. `root / "C:/…"` then discards the root, and `deploy-gate.py` crashes with `ValueError` from `relative_to` (`script-error`). AC-3 says that no longer happens. `solution_space.fixed` keeps `owns:` syntax unchanged, so the Developer could not close the gap alone.

## Decision

1. **`owns:` gains `template/scripts/index-specs.py`**, scoped by comment to AC-1, and it leaves `reads:`. Neil approved this on 2026-10-30.
2. **AC-1 states the indexer half precisely.**
   - Optional import, as in `deploy-gate.py`.
   - `collect_graph()` puts the `LayoutInvalid` message **first** in `errors`, so `validate_spec_graph()` returns it too.
   - Plain, `--validate`, `--list`, `--slice` and `--provisional` print it under `Spec validation FAILED:`, exit 1 and write nothing. `--ac-hashes` is unaffected.
   - The gate shows the message exactly once. It already de-duplicates its error list, so its own load and the indexer's entry collapse into one line.
3. **FR-0027 replaces `0eef0f0`.** Neil decided on 2026-10-30 that a new FR fixes labelled-AC detection and lands before FR-0023 merges. The constraint is unchanged: AC-6's layout must not reach `main` before FR-0027 merges. Both FRs own `deploy-gate.py` and `index-specs.py`, so whichever merges second rebases. `depends_on` gains `FR-0027` in the rebase that brings FR-0027 onto this branch. It cannot be added now, because the indexer rejects an unknown FR.
4. **Empty values.**
   - A layout file that parses to no mapping is malformed: empty, comments only, or `null`.
   - `gate: {}` and `gate: null` are malformed.
   - A top-level `{}` is valid and loads as the default layout. "Keys drawn only from" allows zero keys. `gate`'s "`source_dirs` and/or `test_dirs`" requires at least one.
5. **AC-6's overlap check becomes a rule.** The expected `## Footprint warnings` are exactly `find_overlaps` over the copy's active FRs, recomputed by the Reviewer. The list at 2026-10-30 is given for reference. It names FR-0023 ↔ FR-0026 on both `deploy-gate.py` and `index-specs.py`, the second of which item 1 creates. AC-6's expected residual failure is restated: none once FR-0027 lands with its `@covers FR-0001:AC-12` annotation, otherwise `coverage-missing` for FR-0001 AC-12 at `--stage full`. This was simulated on 2026-10-30 against the hub's `tests/` and `template/tests/` with labelled detection on.
6. **The layout refuses drive-letter gate directories.** Neil decided this on 2026-10-30, adopting the Reviewer's proposed default.
   - `project_layout` rejects any `gate.source_dirs` or `gate.test_dirs` entry whose `PureWindowsPath(entry).drive` is non-empty, on every platform. That covers a drive letter (`C:/x`, `c:x`) and a UNC root.
   - It raises `LayoutInvalid` naming `gate.<key>`, so the indexer and the gate report it like any malformed layout (item 2), under `spec-validation`.
   - **Layout only.** `owns:`/`reads:` entries and `spec_footprint._validate_glob` are unchanged, so `solution_space.fixed`'s "`owns:` / `reads:` entry syntax is unchanged" still holds.
   - AC-1 lists the rule among the malformed cases. AC-3 says the `relative_to` `ValueError` is now prevented at load time.
7. **The git bound is per `load()` call** (Reviewer r1 N-2). `solution_space.open` now says each `load()` call runs git at most once. A process may call `load()` more than once, for example the gate's own load plus `validate_spec_graph()`. Memoising is allowed but not required. The cost of not memoising is one extra git process per run under `footprint_root: repo`.

**`breaking: false`.** Under ADR-0001 rule 3, the code at `9d48fd7` is no less correct after this revision. Items 2, 4, 5 and 7 restate what it already does or what its tests already check. Two pieces were still missing, and each delivers a promise v1 already made:
- AC-1's indexer half, which v1 required and item 1 makes buildable;
- item 6's rejection, the mechanism for AC-3 v1's promise that a directory outside the project raises no `ValueError` from `relative_to`. Code that crashes on a drive-letter entry already fails AC-3 v1.

Item 6 is folded into this DEC, not a new one, because DEC-0027 is still `proposed` and unmerged, so both items belong to the same version 2. FR-0023 goes to `version: 2` with `revisions: [DEC-0027]`, and `last_breaking_revision` stays `null`. Rule 5 was checked: identity unchanged.

`tier: neil`: item 1 widens a maintainer-mode write surface into a human-approval file. Item 3 is Neil's sequencing decision, and item 6 is his scoping decision.

## Alternatives considered

- **Keep `index-specs.py` in `reads:` and drop the indexer half of AC-1.** Rejected. Then `--validate`, which the spec-validation hook runs after every spec edit, would pass on a malformed layout that the gate then fails. The two tools would disagree on the same tree, which FR-0021 exists to prevent.
- **Cherry-pick `0eef0f0` from the other hub.** Rejected by Neil. The commit was never reviewed in this repository, and it has no FR here to carry its ACs or tests.
- **Keep AC-6's list and update it by hand at review.** Rejected. The list changes every time an FR merges, so any fixed list goes stale. The rule also checks what AC-6 is for: hub-relative footprints overlap-check.
- **Reject drive-letter entries in `_validate_glob`, for `owns:` too.** Rejected by Neil. It would change `owns:` syntax, which `solution_space.fixed` keeps unchanged, and it would reach every FR's footprint for a defect that only bites the gate's directory scan. A human authors the layout under the protected `.agent-team/`, so a load-time error is loud and cheap.

## Cascade

Non-breaking. Updated in this commit:
- `projects/hub-tooling/specs/FR-0023-project-layout-footprint-root-and-gate-dirs.md`: `owns:`/`reads:`, AC-1, AC-6, Out of scope, Dependencies, Notes (Maintainer mode), `version: 2`, `revisions: [DEC-0027]`, `updated: 2026-10-30`, and a Changelog line.
- Items 6 and 7, in a later commit: FR-0023 AC-1 (drive-letter rejection and its verification cases), AC-3 (the `relative_to` sentence), `solution_space.open` (the git bound), and a Changelog line.

Developer round 2, maintainer mode: AC-1's indexer half in `template/scripts/index-specs.py`, with tests in `template/tests/unit/scripts/test_project_layout.py`. No change to `deploy-gate.py` is required.

Tests on the FR-0023 branch:
- **Unchanged:** `test_hub_tooling_declares_its_layout`. It pins only the layout's content and the resolved roots, not the overlap list.
- **Unchanged:** every existing case in `_MALFORMED` and `test_gate_fails_spec_validation_on_a_malformed_layout_before_writing`.
- **New cases to add:** top-level `{}` loads as the default, and the subprocess indexer in each of the five modes plus `--ac-hashes` (AC-1's verification list). These are additions, not edits.
- **Item 6, Developer round 2:** the rejection in `project_layout`. `_MALFORMED` gains `C:/…`, `c:x` and UNC entries under `gate.source_dirs` and `gate.test_dirs`. A gate subprocess case with a drive-letter entry shows `spec-validation`, not `script-error`, and no traceback. Existing cases are unchanged. `test_spec_footprint.py`'s rejection pins stay unedited, because `_validate_glob` does not change.
- **Item 7:** no test change. The Developer's per-`load()` reading is the specified one.

## Changelog

- 2026-10-30: created (proposed). Items 1 and 3 decided by Neil.
- 2026-10-30: items 6 and 7 added, still proposed and non-breaking.
  - Item 6 comes from the Reviewer's r1 ESCALATION (`ab588d9`) and Neil's decision of the same day.
  - Item 7 clarifies r1 N-2.
  - FR-0023 stays at `version: 2`.
- 2026-11-02: status `proposed` → `ratified`. Neil merged PR [#26](https://github.com/NeilRGilchrist/cos-agent-hub/pull/26) (commit `ddbe9e5`), whose description stated that merging ratifies this DEC. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
