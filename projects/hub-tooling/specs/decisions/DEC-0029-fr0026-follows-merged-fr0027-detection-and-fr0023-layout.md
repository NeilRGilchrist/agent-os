---
id: DEC-0029
title: "FR-0026 follows merged FR-0027 and FR-0023: \"detected\" is `AC_HEADING_PATTERN` together with `AC_LABELLED_PATTERN`, labelled bullets count under the Withdrawn section, \"`@covers`\" means any annotation `collect_covers` counts in the layout's test directories, and AC-5(a) and AC-2's self-pointer match the code"
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified by Neil merging #28 on 2026-11-03
satisfies: []
constrained_by: [FR-0023, FR-0027]
revises: FR-0026
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave FR-0026 as written and let its Developer escalate"
  - "Keep the Withdrawn-section parser on AC_LINE_PATTERN only"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0026 was ratified before FR-0027 and FR-0023 merged. Five places treat
  AC_HEADING_PATTERN as the gate's whole AC detection, its Withdrawn-section
  parser names only AC_LINE_PATTERN, and it says "@covers" and "tests/" where
  the gate now counts qualified annotations in declared directories. Restating
  them before dispatch keeps the spec true without changing FR-0026's
  identity, footprint or cascade.
created: 2026-11-02
updated: 2026-11-03
---

# DEC-0029: FR-0026 follows merged FR-0027 and FR-0023

## Context

FR-0026 (ready, v1, not dispatched) was ratified by Neil on 2026-10-30, together with his approval of the control-plane edit. Since then three FRs have merged to `main` (`ddbe9e5`):
- **FR-0027 (#24):** `deploy-gate.py`'s detected set is now `AC_HEADING_PATTERN` matches together with `AC_LABELLED_PATTERN` matches (`_load_fr_summaries`). `index-specs.py`'s `parse_acs` accepts `AC_LINE_PATTERN` or `AC_LABELLED_LINE_PATTERN`, and a labelled AC's text is `(L) R`.
- **FR-0023 (#26):**
  - `collect_covers(layout)` scans `gate.test_dirs` (default `tests/`) and also counts `# covers <project_name>` when the layout declares a name.
  - `collect_implements(layout)` scans `gate.source_dirs`.
  - `index-specs.py`'s `collect_graph()` reports `_layout_errors()` first.
- **FR-0025 (#25):** it does not touch FR-0026's files.

FR-0026's text predates the first two.

## Decision

1. **"Detected" means both patterns.** A new Terms entry defines a detected AC as an `AC_HEADING_PATTERN` or `AC_LABELLED_PATTERN` match over the body. Five places are restated against it:
   - the `solution_space.fixed` line;
   - AC-6's first sub-bullet;
   - AC-7's "detected by `AC_HEADING_PATTERN`";
   - the Out-of-scope bullet on the gate's AC detection;
   - Notes, "Why the gate keeps its own AC detection".

   The `ac-format` warning and the gate's whole-body scope are unchanged. The Why bullet about aitk's `[DEPRECATED]` rewrite is history and stays.
2. **Labelled bullets count under `## Withdrawn acceptance criteria`.** The section parser uses exactly `parse_acs`'s bullet rules: `AC_LINE_PATTERN` or `AC_LABELLED_LINE_PATTERN` at column 0, with a labelled text of `(L) R`. This follows FR-0027's principle that the two forms are equivalent. The gate already detects a labelled bullet anywhere in the body, so a parser that missed one in this section would raise AC-5(a)'s warning on a correctly migrated AC. The What section, AC-5 and AC-14 say so, and AC-5 gains one labelled fixture.
3. **"`@covers`" means a covering annotation.** A new Terms entry says that wherever FR-0026 says "`@covers`" or "a `@covers` test", it means anything `collect_covers` counts in the gate's test directories. That includes FR-0023's qualified form. Two verification cases are added:
   - AC-7: a qualified annotation in `gate.test_dirs` on a honoured `superseded` AC passes check 2;
   - AC-8: a live AC covered only by a qualified annotation is not missing.

   Nothing in FR-0026 changes `collect_covers` or `collect_implements`. The Out-of-scope bullet now says so.
4. **The layout reaches the tests.**
   - AC-14's base ref already carries FR-0023 and FR-0027, so its comparison copies `project_layout.py` on both sides. It runs with no layout and again with a layout declaring `project_name` and `gate.test_dirs`.
   - Notes' isolation copies gain `project_layout.py`.
   - A malformed layout needs no new wording. `collect_graph()` fails on it first, so the indexer prints only `Spec validation FAILED:` and none of FR-0026's warnings. The gate fails `spec-validation` before checks 2 and 3, so the exemption function is never reached.
5. **Dependencies.**
   - `depends_on` gains FR-0023 and FR-0027, both merged.
   - The FR-0023 bullet says it has landed.
   - A new FR-0027 bullet is added.
   - The FR-0018 bullet is unchanged. The edits are still disjoint: `metrics_log.py` around line 58 and the `--metrics-dir` help, against FR-0026's `GATE_WARNING_CLASSES` at line 106; the metrics README's union paragraph against its `warning_classes` row.
6. **AC-5(a) and AC-2's self-pointer match the code** (FR-0026 r1 review, `specs/_reviews/FR-0026-r1.md` at `4e86dd8`).
   - **E-1.** Read literally, AC-5(a) ("its entry is not a honoured `withdrawn` or `superseded`") also fired for a honoured `deferred` AC under the Withdrawn section. Its message, "it is live for coverage", is then false: AC-8 exempts that AC, and (c) already warns. The code fires (a) only when the entry is absent or not honoured. AC-5(a) now reads "has no entry, or its entry is not honoured". It also says a honoured `deferred` AC there gets (c), not (a). This is the Reviewer's recommended default.
   - **N-2.** AC-2 allowed a self-pointer only for `deferred`, and the code honours one in every exemption state. AC-2 now allows it in all three. For `superseded`, the successor is another AC of the same FR, which is the ratification meaning of `superseded` (Notes, "Choosing the state"). For `withdrawn`, the FR records the withdrawal itself. Refusing it was rejected: that would make the implementer change, which is breaking, and would refuse a legitimate in-FR replacement.

**`breaking: false`.** FR-0026 has no implementation and no tests, so no implementer must change. The decisions restate the merged reality and add verification cases. Item 6 was added after round 1 had implemented FR-0026. It restates the spec to match that implementation, so no implementer changes. `owns:`, the AC count, the warning classes and AC-12's cascade are unchanged. FR-0026 goes to `version: 2` with `revisions: [DEC-0029]`, and `last_breaking_revision` stays `null`. Rule 5 was checked: identity unchanged.

`tier: architect`: no footprint or control-plane change, and the one choice (item 2) follows FR-0027's ratified principle. Neil ratifies.

## Alternatives considered

- **Leave FR-0026 as written.** Rejected. Its Developer would find `AC_HEADING_PATTERN` named as the whole detection, which it no longer is, and would escalate in round 1.
- **Item 6: keep AC-5(a)'s literal scope, or refuse self-pointers outside `deferred`.** Rejected. The first makes (a) state that an exempt AC is live, contradicting AC-8. The second forces a code change and forbids an in-FR supersession.
- **Keep the Withdrawn-section parser on `AC_LINE_PATTERN` only.** Rejected. The gate counts a labelled bullet in that section as detected while the indexer would not see its text. That splits the two tools on one tree and raises false AC-5(a) warnings.

## Cascade

Non-breaking. Updated in this commit:
- `projects/hub-tooling/specs/FR-0026-deferred-withdrawn-and-superseded-acs-exempt-from-coverage.md`: Terms, the What section, `solution_space.fixed`, AC-5, AC-6, AC-7, AC-8, AC-14, Out of scope, Dependencies, Notes, `depends_on`, `version: 2`, `revisions: [DEC-0029]`, `updated`, and a Changelog line.

Tests: none existed for FR-0026 when items 1 to 5 were written.

Item 6, in a later commit:
- FR-0026 AC-5(a), AC-2 and a Changelog line.
- **Developer round 2:** `template/specs/README.md` line 75. Replace the parenthetical's first clause, "an AC under the section with no honoured `withdrawn` or `superseded` entry is live for coverage", with "an AC under the section with no entry, or an entry that is not honoured, is live for coverage (a honoured `deferred` AC there stays exempt, and gets the next warning instead)". The rest of the parenthetical is unchanged. The README section should also gain one sentence: "`moved_to` may name the FR's own ID in any exemption state; for `superseded` it means another AC of the same FR replaced it."
- **Code:** no change. `index-specs.py` already fires (a) only for an absent or unhonoured entry, and already honours self-pointers.
- **Tests:** no existing test changes. `test_labelled_acs_in_each_state_under_the_withdrawn_section` leaves the E-1 line unpinned. Round 2 may pin it, and may add one self-pointer case each for `superseded` and `withdrawn`.

## Changelog

- 2026-11-02: created (proposed), before FR-0026's dispatch.
- 2026-11-02: item 6 added, still proposed and non-breaking, from the r1 review at `4e86dd8` (E-1, with the Reviewer's default; N-2).
- 2026-11-03: status `proposed` → `ratified`. Neil merged PR [#28](https://github.com/NeilRGilchrist/cos-agent-hub/pull/28) (commit `9a35bb3`), whose description stated that merging ratifies this DEC. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
