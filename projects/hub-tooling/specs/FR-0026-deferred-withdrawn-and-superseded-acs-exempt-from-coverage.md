---
id: FR-0026
title: An AC recorded in `ac_state` as `deferred`, `withdrawn` or `superseded`, with a pointer to where its work went, is exempt from the deploy gate's coverage check but stays a valid `@covers` target, and the indexer lists every open deferral
status: merged
owner: architect
depends_on: [FR-0023, FR-0027]
tags: [gate, deploy-gate, indexer, spec-graph, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
# Documentation only; the Chief of Staff sequences the overlaps named in Dependencies.
owns:
  - template/scripts/deploy-gate.py
  - template/scripts/index-specs.py
  - template/scripts/metrics_log.py                          # AC-12: two warning classes added to GATE_WARNING_CLASSES, nothing else
  - template/specs/_template/FR-XXXX-template.md
  - template/specs/README.md
  - template/specs/_metrics/README.md                        # AC-12: the two warning classes documented, nothing else
  - template/tests/unit/scripts/test_deploy_gate_ac_exemptions.py   # new: this FR's gate tests
  - template/tests/unit/scripts/test_index_specs_ac_exemptions.py   # new: this FR's indexer tests
  - template/tests/fixtures/ac-exemptions/**                 # new: synthetic fixtures (AC-9, AC-14)
  # Reviewer-only, each bounded to the pinned-literal edit named in AC-12's cascade:
  - template/tests/unit/scripts/test_deploy_gate_metrics.py  # FR-0002's; the GATE_WARNING_CLASSES literal and the warning-branch parametrisations
  - template/tests/unit/scripts/test_deploy_gate_gates.py    # FR-0008's; the GATE_WARNING_CLASSES literal in test_no_other_kinds_required_fields_or_enums_moved
reads:
  - template/scripts/spec_query.py
  - template/scripts/spec_footprint.py
  - template/scripts/dispatch.py                             # _find_hub_root: the hub-discovery rule AC-9 mirrors
  - template/scripts/render-docs.py
  - template/specs/decisions/README.md
  - template/tests/unit/scripts/test_deploy_gate.py
  - template/tests/unit/scripts/test_deploy_gate_scope.py
  - template/tests/unit/scripts/test_index_specs.py
  - template/tests/unit/scripts/test_index_specs_dec_tr.py
  - template/tests/unit/scripts/test_index_specs_versioning.py
  - template/tests/unit/scripts/test_index_gates.py
  - template/tests/unit/scripts/test_spec_query.py
  - template/tests/unit/scripts/test_metrics_log.py
  - scripts/parking.py
gates: []
derived_from: IDEA-0035
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0029]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0002, FR-0021]
serves_roles: [architect, reviewer, orchestrator, human_supervisor]
solution_space:
  open:
    - "The name and signature of the one function `index-specs.py` exports for the gate to learn an FR's exempt ACs and its unhonoured exemption entries, as long as AC-7's source constraints hold."
    - "How `index-specs.py` stores the parsed `## Withdrawn acceptance criteria` bodies on the FR object, as long as `--slice --json` does not serialise them (they are body text, like `acs`)."
    - "The exact wording of each new warning, as long as it names the FR, the AC number and the fix, and the INDEX.md text is a deterministic function of the tree."
  fixed:
    - "`ac_state` is the only thing the gate reads to decide an AC is exempt. A section heading, a `[P2]` tag or any other body text never exempts an AC."
    - "The AC set the gate detects stays what FR-0027 left it: `AC_HEADING_PATTERN` matches together with `AC_LABELLED_PATTERN` matches, over the whole body. So an FR with `ac_state: {}` gates byte-identically to the base ref (DEC-0029)."
    - "No new failure class, `counts` key, record kind or field. Two new warning classes only (AC-12)."
    - "`INDEX.md` never depends on anything outside the project tree: not the hub, not the clock, not the network."
    - "Every new check is warn-only in the indexer. The indexer's exit code changes for no input."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-10-26
updated: 2026-11-03
---

> **Provenance:** Drafted 2026-10-26 by the hub-tooling Architect from IDEA-0035, under convergence decision 7 (human-accepted 2026-10-23). Grounded in a read of `template/scripts/deploy-gate.py` (`_load_fr_summaries`, checks 2 and 3), `template/scripts/index-specs.py` (`AC_STATES`, `parse_acs`, `_ac_state_warnings`, `render_index`, `_object_fields`), `template/scripts/metrics_log.py` (`GATE_WARNING_CLASSES`), the gate-source pins in `test_spec_query.py` and `test_index_specs_dec_tr.py`, and the `ai-productivity-toolkit` (aitk) FRs listed under Why (read-only).
>
> · source_class: agent_observation · role: architect · model: opus · ip_class: hub_original.

# FR-0026: Deferred, withdrawn and superseded ACs are exempt from coverage

## Why

`deploy-gate.py` requires an `@covers` test for every AC of an FR at `in-review` or `merged` (check 3). It has no notion of an AC that is deliberately not delivered in this pass. Projects write such ACs all the time. Some are tightly in scope but not needed yet (aitk tags them `[P2]`). Others are withdrawn or superseded after review. Today such an FR cannot reach `merged` without a placeholder test or spec surgery that hides the AC from the gate. The surgery then breaks check 2, which fails any `@covers` aimed at an AC the gate no longer detects. In aitk alone:

- FR-0001 AC-9 `[P2]`: a test was written early only so the FR could merge.
- FR-0002 AC-11 `[P2]` and FR-0003 AC-10 `[P2]`: deferred, and each will block its FR's merge.
- FR-0002 AC-14 and FR-0004 AC-12: withdrawn by hand. Each was moved under a `## Withdrawn acceptance criteria` section and rewritten as `**[DEPRECATED] AC-N**` so `AC_HEADING_PATTERN` stops matching it.
- FR-0005 AC-9/10/11: superseded by FR-0011. The AC-9 and AC-10 tests had to be deleted, because check 2 fails a `@covers` on an AC the gate no longer detects.
- FR-0006 is still draft and already carries 12 `[P2]` ACs.

Every aitk FR has `ac_state: {}`. The deferral lives only in prose, so nothing lists it, and deferred work can be lost silently.

## What

After this FR, an author records a deliberate non-delivery in the FR's existing `ac_state` frontmatter. The entry gives one of three states (`deferred`, `withdrawn`, `superseded`), a `moved_to` pointer naming where the work went, and optionally a `reason`. The indexer validates the entry, warn-only. The gate reads the entry through the indexer and does two things with it. It does not require coverage for that AC (check 3). It keeps accepting `@covers` for that AC (check 2), so tests that carry history need not be deleted. The `## Withdrawn acceptance criteria` section becomes a documented convention that holds the text of withdrawn and superseded ACs, in the normal `- **AC-N:**` form or FR-0027's labelled `- **AC-N (L):**` form. `ac_state` stays authoritative, and the indexer warns when the two disagree. `specs/INDEX.md` gains a `## Open deferrals` section listing every `deferred` AC with its pointer. Recording a deferral does not opt an FR into full ratification tracking. An FR with `ac_state: {}` behaves exactly as it does today.

## Terms

- **Exemption state:** one of `deferred`, `withdrawn`, `superseded` in `ac_state.<n>.state`.
- **Exemption entry:** an `ac_state` entry whose state is an exemption state.
- **Honoured:** an exemption entry that passes every check in AC-1 and AC-2. Only a honoured entry changes what the gate does. An exemption entry that is not honoured leaves its AC **live**: the gate treats it exactly as it would with no entry (fail closed, AC-10).
- **Live AC:** any AC the gate detects that has no honoured exemption entry.
- **Detected AC (DEC-0029):** an AC number the gate's detection finds in the FR body after the frontmatter: an `AC_HEADING_PATTERN` match or an `AC_LABELLED_PATTERN` match (FR-0027 AC-3). "Detected" in this FR always means the combination of the two.
- **Covering annotation (DEC-0029):** anything `collect_covers` counts. That is `@covers FR-NNNN:AC-N` in the gate's test directories, plus `# covers <project_name> FR-NNNN:AC-N` when the project's layout declares `project_name` (FR-0023 AC-3, AC-4). The test directories are `tests/` by default, or `gate.test_dirs`. Wherever this FR says "a `@covers` test" or "`@covers`", it means a covering annotation.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Two new states and one entry shape.** `index-specs.py`'s `AC_STATES` becomes `proposed | refined | client-review | ratified | superseded | deferred | withdrawn`. An exemption entry has this shape:

  ```yaml
  ac_state:
    11: {state: deferred, moved_to: IDEA-0049}
    12: {state: withdrawn, moved_to: null, reason: "Not needed for the pilot; no follow-up planned"}
    9:  {state: superseded, moved_to: FR-0011, reason: "Capture path replaced (ADR-0002)"}
  ```

  - `moved_to` is required. Its value is a string matching `^(FR|IDEA|ADR|DEC)-\d{4}$`, or `null`.
  - `null` is allowed only for `deferred` and `withdrawn`, and only with a `reason` that is a non-empty string after stripping whitespace.
  - `superseded` always needs a non-null `moved_to`: a superseded AC has a successor by definition (ADR-0001 rule 5).
  - `reason` is optional otherwise. `source`, `ratified` and `hash` are optional on an exemption entry, and keys outside these five are ignored.

  Each of these cases is a warning under `## AC ratification warnings` in `INDEX.md`, and on stderr in both indexer modes, and leaves the entry not honoured. Every message starts `FR-NNNN AC-N: ` and ends `; not honoured, AC-N still requires coverage`:
  - `moved_to` key absent;
  - `moved_to` not a string or not matching the pattern (the message quotes the value);
  - `moved_to: null` with no usable `reason`;
  - `superseded` with `moved_to: null`.

  A `moved_to` on a non-exemption state produces the warning `FR-NNNN AC-N: moved_to applies only to deferred, withdrawn or superseded; ignored`. The indexer's exit code never changes. Verified with one in-memory `FR` per case through `_ac_state_warnings` (the `_make_fr` double in `test_index_specs.py`), plus one subprocess run asserting exit 0.

- **AC-2:** **Local pointers must resolve; IDEA pointers are shape-checked only.** For a well-formed exemption entry:
  - `moved_to: FR-NNNN` must name a parsed FR in this project. `DEC-NNNN` must name a `specs/decisions/DEC-NNNN-*.md` that parsed, and `ADR-NNNN` a `specs/decisions/ADR-NNNN-*.md` file. Otherwise the entry gets the warning `FR-NNNN AC-N: moved_to <ID> does not resolve in this project; not honoured, AC-N still requires coverage` and is not honoured.
  - `moved_to: IDEA-NNNN` is honoured on shape alone. Neither `INDEX.md` nor the gate ever looks outside the project tree; AC-3 is the only place IDEA pointers are resolved.
  - `moved_to` may name the FR's own ID, in any exemption state (DEC-0029):
    - for `deferred`, it means "later in this FR";
    - for `superseded`, the successor is another AC of this FR, and `reason` should name it. This is the ratification meaning of `superseded`: an AC replaced by newer text.
    - for `withdrawn`, the FR itself records the withdrawal, for example in its Changelog.

  Verified by fixture repos run through `index-specs.py` and `deploy-gate.py` as subprocesses: one dangling FR pointer, one dangling DEC, one dangling ADR, one IDEA pointer that names no file anywhere. Only the IDEA entry is honoured.

- **AC-3:** **IDEA pointers are checked against the hub when it is reachable, on stderr only.** When `index-specs.py` runs (write mode or `--validate`), it looks for the hub with the rule `dispatch.py`'s `_find_hub_root` uses: the `DISPATCH_HUB_ROOT` environment variable when it names a directory holding `scripts/parking.py`, else the first ancestor of the project root holding both `scripts/parking.py` and `parking-lot/`. The indexer re-implements this rule; it does not import `dispatch.py`. When a hub is found, each honoured entry with `moved_to: IDEA-NNNN` on a default-view FR is checked:
  - no `parking-lot/IDEA-NNNN-*.md` gives `FR-NNNN AC-N: moved_to IDEA-NNNN not found in the hub parking lot`;
  - a file whose frontmatter `status` is `archived` gives `FR-NNNN AC-N: moved_to IDEA-NNNN is archived; the work has no live home`.

  These lines print to stderr under `Deferral pointer warnings (<n>):`, in `_print_warnings`' format. They never appear in `INDEX.md`. They never change the exit code, never make an entry not honoured, and never run in `deploy-gate.py`. With no hub found, nothing prints. The isolation seam is `DISPATCH_HUB_ROOT` pointed at a synthetic hub under `tmp_path`, with one present, one archived and one missing IDEA. Also verified: `INDEX.md` is byte-identical with the variable set and unset.

- **AC-4:** **Recording an exemption does not opt an FR into ratification tracking.** `_ac_state_warnings` reports `no ac_state entry for …` only when the FR has at least one entry whose state is **not** an exemption state. Verified with these in-memory FRs:
  - an FR with five ACs and a single `deferred` entry: no `no ac_state entry` warning;
  - the same FR plus one `ratified` entry with a matching hash: one warning, listing the three ACs with no entry and naming neither the deferred nor the ratified AC;
  - an FR with only `withdrawn` and `superseded` entries: no `no ac_state entry` warning.

  The existing `test_ac_state_opted_in_warns_about_uncovered_acs` stays green unedited.

- **AC-5:** **The `## Withdrawn acceptance criteria` section is formalised, and `ac_state` wins.** The section holds the text of `withdrawn` and `superseded` ACs in the ordinary `- **AC-N:** <original text>` form, or in FR-0027's labelled form `- **AC-N (L):** <original text>` (DEC-0029). Its heading is matched case-insensitively, as `_section_body` does. `deferred` ACs stay under `## Acceptance criteria`, because their text is still the spec.
  - The indexer parses the section into a field separate from `FR.acs`, with exactly `parse_acs`'s bullet rules: `AC_LINE_PATTERN` or `AC_LABELLED_LINE_PATTERN` at column 0. A labelled bullet's text is `(L) R`, as in FR-0027 AC-2. `acs`, its hashes and `--ac-hashes` output are unchanged, and `--slice --json` does not serialise the new field.
  - The field has a default, so `index_specs.FR(...)` built without it still works (the `_make_fr` double).
  - An `ac_state` entry for an AC found in either section does not get the `has no matching acceptance criterion` warning.

  The section and `ac_state` can disagree in four ways. Each is a warning under `## AC ratification warnings`, and in every case the gate does what `ac_state` says:
  - (a) An AC under the section has no entry, or its entry is not honoured (DEC-0029). A honoured `deferred` AC under the section is exempt, and gets (c) instead, not (a): `FR-NNNN AC-N: listed under Withdrawn acceptance criteria but ac_state is <state, or 'absent'>; it is live for coverage`.
  - (b) A honoured `withdrawn` or `superseded` AC is still under `## Acceptance criteria`: `FR-NNNN AC-N: <state> but still under Acceptance criteria; move it under ## Withdrawn acceptance criteria`.
  - (c) A honoured `deferred` AC is under the section: `FR-NNNN AC-N: deferred ACs stay under Acceptance criteria`.
  - (d) The same AC number appears in both sections: `FR-NNNN AC-N: appears under both Acceptance criteria and Withdrawn acceptance criteria`.

  Two more cases:
  - A honoured exemption entry for an AC found in neither section stays honoured. It warns `FR-NNNN AC-N: <state> but has no text in this FR; keep its original text under ## Withdrawn acceptance criteria`.
  - Lines in the section that match neither `AC_LINE_PATTERN` nor `AC_LABELLED_LINE_PATTERN` are ignored by the indexer and produce no new warning. The legacy `- **[DEPRECATED] AC-14** (...)` form is one such line.

  Verified with one fixture FR per case through the subprocess indexer. Each case is also run through the gate to show its coverage verdict. One more fixture puts a labelled `withdrawn` bullet under the section: it is parsed, has no AC-5(a) warning, and its `@covers` passes check 2 (DEC-0029).

- **AC-6:** **The gate learns exemptions from the indexer, not from the body.** `deploy-gate.py` calls one function that `index-specs.py` exports for this purpose. The function returns each FR's honoured exempt AC numbers, and the warning text for its exemption entries that are not honoured. It applies AC-1 and AC-2 exactly. Local DEC/ADR resolution happens inside the indexer, so the gate gains no DEC, ADR or TR vocabulary.
  - The gate's detected AC set (Terms: `AC_HEADING_PATTERN` together with `AC_LABELLED_PATTERN`, over the whole body) is unchanged, and so is the `ac-format` warning (DEC-0029).
  - No section name, `[P2]`, `[DEPRECATED]` or other body text affects whether an AC is exempt.

  These source pins stay green **unedited**:
  - `test_index_specs_dec_tr.py::test_deploy_gate_source_has_no_dec_tr_awareness_and_imports_resolve`.
  - `test_spec_query.py::test_deploy_gate_source_unchanged_and_imports_intact`. This pin forbids `spec_query` and `in_default_view`, and forbids `retired` case-insensitively, comments included.
  - `test_spec_query.py::test_consumer_scripts_do_not_import_spec_query`.
  - `test_index_specs_versioning.py::test_deploy_gate_imports_still_resolve`.

  The exported function's name, and every new line of `deploy-gate.py`, avoid each forbidden token. Verified by those pins. A second test monkeypatches the exported function to return a fixed exemption for an AC that has no `ac_state` entry, then shows check 3 follows it. That proves the gate reads the function rather than parsing for itself.

- **AC-7:** **Check 2 accepts `@covers` on an exempt AC.** A `@covers FR-NNNN:AC-N` passes check 2 when AC-N is either detected (Terms) or exempt by a honoured entry. It passes even when the AC's text uses the legacy `[DEPRECATED]` form that detection misses. Neither case adds a warning. A `@covers` on an AC that is neither detected nor exempt still fails with today's message (`@covers references FR-NNNN:AC-N but that AC is not in the FR`) and class `covers-unknown-ac`. That includes an AC whose exemption entry is not honoured. Verified through the subprocess gate at `--stage dev` and `--stage full`, with:
  - a test covering a `withdrawn` AC whose text sits under `## Withdrawn acceptance criteria` in the `- **AC-N:**` form;
  - a test covering a honoured `superseded` AC whose text survives only as `- **[DEPRECATED] AC-9** (...)`;
  - a test covering an AC whose only entry is `{state: withdrawn}`, with no `moved_to` and its text in the legacy form. This one fails `covers-unknown-ac`.
  - under a layout declaring `project_name: demo` and `gate.test_dirs: [lib_tests]`, a qualified `# covers demo FR-NNNN:AC-N` in `lib_tests/` on a honoured `superseded` legacy-form AC. It passes check 2 exactly as the `@covers` case does (DEC-0029).

- **AC-8:** **Check 3 skips honoured exempt ACs and nothing else.** For an FR at `in-review` or `merged`, check 3 requires a `@covers` for every detected AC minus its honoured exempt ACs. The failure line keeps today's format and lists only the live ACs that are missing. Exempt ACs never appear in it. An FR at `merged` whose every live AC is covered passes, whatever number of `deferred` ACs it has. `--stage dev` still skips check 3. Verified through the subprocess gate at `--stage review` and `--stage full` for each of `deferred`, `withdrawn` and `superseded`. One extra case: under AC-7's layout, a live AC covered only by a qualified annotation in `gate.test_dirs` is not missing, and a `deferred` AC with no annotation anywhere is not listed (DEC-0029).

- **AC-9:** **Adversarial: an exempt target never masks a live gap.** Fixture: `FR-0100` at `in-review` with three ACs.
  - AC-1 is live and uncovered.
  - AC-2 is `{state: deferred, moved_to: IDEA-0001}` and **has** a `@covers FR-0100:AC-2` test.
  - AC-3 is live and covered.

  `deploy-gate.py --stage full` exits 1. Its stderr has exactly one failure line, `FR-0100 (in-review): no @covers test for AC-1`, and no `covers-unknown-ac` line. The `gate.run` record's `failure_classes` is exactly `["coverage-missing"]` and its `object_ids` is `["FR-0100"]`. Add a `@covers FR-0100:AC-1` test to the same tree and set the status to `merged`: the gate prints `Deploy gate PASSED (stage=full): ...` and exits 0. Then delete AC-2's `ac_state` entry: the gate still exits 0, because AC-2 is covered. A bite check runs the AC-9 fixture against the base-ref gate (see AC-14) and shows the outcomes differ only on the exempt AC.

- **AC-10:** **An exemption entry that is not honoured fails closed and is reported by the gate.** For each FR, the gate prints each indexer warning about an exemption entry that is not honoured (AC-1, AC-2) under `Deploy gate WARNINGS:`, at every stage, in the existing `  - <warning>` form. It records the warning class `ac-exemption-invalid` once per run. The AC is live, so an uncovered one on an `in-review` or `merged` FR fails check 3 with today's message. Verified with the four AC-1 shape failures and the three AC-2 dangling pointers. Each runs through the subprocess gate on a `merged` FR with the AC uncovered, and asserts exit 1, the warning line, and both classes in the record.

- **AC-11:** **An FR with no live AC gets a warning, not a failure.** Take an FR at `in-review` or `merged` with at least one detected AC, every one of them exempt. The gate prints `FR-NNNN (<status>): every AC is deferred, withdrawn or superseded; nothing in this FR is delivered` under `Deploy gate WARNINGS:` and records the warning class `ac-all-exempt`. The exit code is unaffected. This check runs at `review` and `full` only, beside check 3. An FR with zero detected ACs adds nothing, as today. Verified with an all-`deferred` `merged` FR (exit 0, warning, class) and with the same FR at `--stage dev` (no warning).

- **AC-12:** **Two new warning classes; nothing else in the metrics schema moves.** `metrics_log.GATE_WARNING_CLASSES` becomes `implements-missing | implements-unknown-fr | ac-format | ac-exemption-invalid | ac-all-exempt`. The gate emits each one through a literal `report.warn("<class>")` call, so the source scrape in `test_failure_classes_are_the_fixed_enum_and_the_gate_only_uses_those` still finds every warning class. `specs/_metrics/README.md`'s `warning_classes` row lists both new classes, each citing hub-tooling FR-0026, so `test_metrics_log.py`'s README test stays green unedited. Nothing else changes: failure classes, kinds, fields and `counts` keys stay as they are. The cascade is exactly these two Reviewer edits, and no other existing test may be edited:
  - `test_deploy_gate_metrics.py::test_failure_classes_are_the_fixed_enum_and_the_gate_only_uses_those`: the `GATE_WARNING_CLASSES` literal gains the two classes.
  - `test_deploy_gate_gates.py::test_no_other_kinds_required_fields_or_enums_moved`: the same literal edit.

  Verified by those two tests after the edit, and by new tests that drive each class through the subprocess gate and read the `gate.run` record.

- **AC-13:** **`INDEX.md` lists every open deferral.** `render_index` emits `## Open deferrals` when at least one FR (any lifecycle, any status) has a honoured `deferred` entry. It is omitted otherwise. The section sits immediately after `## AC ratification warnings`, or where that section would be, and before `## Versioning warnings`. It has one line of text and a table:

  ```
  ## Open deferrals

  _ACs deliberately not delivered yet, from `ac_state`. Each names where the work went._

  | FR | AC | FR status | Moved to | Reason |
  |----|----|-----------|----------|--------|
  | [FR-0002](FR-0002-x.md) | AC-11 | `merged` | IDEA-0049 | — |
  | [FR-0003](FR-0003-y.md) | AC-10 | `in-review` | none | Pilot feedback first |
  ```

  - Rows are sorted by FR ID, then AC number.
  - `Moved to` is the pointer, or `none` for `null`. `Reason` is the reason with each `|` escaped as `\|` and newlines collapsed to spaces, or `—` when absent.
  - `withdrawn` and `superseded` entries, and exemption entries that are not honoured, are not listed.
  - `deploy-gate.py` writes the same bytes, through `render_index(parsed_frs, repo_files)` unchanged, so the gate-vs-indexer byte-identity tests stay green. The section never reads the hub or the clock.

  Verified by an INDEX.md assertion on a fixture with two deferrals on two FRs (one `merged`, one `lifecycle: superseded`), one `withdrawn` entry and one unhonoured `deferred` entry. A second fixture checks that `test_tables_sit_after_fr_warning_sections_and_before_adr_table`'s ordering still holds with the new section present.

- **AC-14:** **Unmanaged FRs behave exactly as today.** Take a spec tree where every FR has `ac_state: {}`, or no `ac_state` key, and no `- **AC-N:**` or labelled `- **AC-N (L):**` line under a `## Withdrawn acceptance criteria` heading. Every existing aitk and hub-tooling FR qualifies, the legacy `[DEPRECATED]` form included. Over such a tree, the new scripts and the base-ref scripts produce the same results:
  - `index-specs.py` writes a byte-identical `INDEX.md`;
  - `index-specs.py --validate` prints byte-identical stdout and stderr, with no hub reachable;
  - `deploy-gate.py` at each stage gives a byte-identical exit code, stdout and stderr, and a `gate.run` record identical apart from `ts` and `record_id`.

  The base-ref scripts come from `git show <base>:template/scripts/...`, as in FR-0021's bite check. The base ref is the `main` commit the Developer branches from, recorded as a constant in the test. That commit already carries FR-0023's `project_layout.py` and FR-0027's labelled detection, so both sides are copied with `project_layout.py`. The comparison runs over the tree as described, which has no `layout.yaml`, and again with a `layout.yaml` declaring `project_name` and `gate.test_dirs` (DEC-0029).

  Pre-existing FRs that do carry `ac_state` keep their gate verdict exactly. Two kinds of FR do gain new warnings:
  - an FR with a legacy `{state: superseded}` and no `moved_to` gains AC-1's warning, while staying live and uncovered-fails as before;
  - an `ac_state: {}` FR with a `- **AC-N:**` or labelled line under the Withdrawn section gains AC-5(a)'s warning. That is a migration left half done, and the warning is the point.

  Verified with synthetic fixtures modelled on the aitk shapes: the legacy `[DEPRECATED] AC-14` section, a `[P2]`-tagged live AC, the three-AC supersession, and a `@covers` on a legacy-form AC (which still fails `covers-unknown-ac`, as today).

- **AC-15:** **The FR template and `specs/README.md` document the rule and the migration.**
  - **FR template.** The `ac_state` line in `template/specs/_template/FR-XXXX-template.md` stays `ac_state: {}` with its comment. The comment's state list gains `deferred | withdrawn`. It says those two and `superseded` take `moved_to` (`FR-NNNN | IDEA-NNNN | ADR-NNNN | DEC-NNNN | null` + `reason`), exempt the AC from the coverage gate, and do not opt the FR into ratification tracking. The commented example gains one `deferred` line. No new frontmatter key or body heading is added. `test_filled_fr_template_validates_with_no_warnings`, `test_filled_templates_validate_with_exit_0_and_no_warnings` and `test_fr_template_lists_every_new_field_with_default_and_comment` stay green unedited.
  - **`template/specs/README.md`.** It gains a `## Deferred, withdrawn and superseded ACs` section. The section states:
    - when to use each state (Notes, "Choosing the state");
    - the `moved_to` rule and what resolves where (AC-2, AC-3);
    - the gate effects (AC-7, AC-8, AC-11);
    - the `## Withdrawn acceptance criteria` convention and that `ac_state` wins (AC-5);
    - `## Open deferrals` (AC-13);
    - the migration recipe in Notes, as numbered steps.
  - The ID-allocation bullet `deprecated ACs stay in the file marked [DEPRECATED]` is reworded to point at that section, and still contains `sequentially` and `never reused`. The `deploy-gate.py` row of `## Consumers of the default view` notes that coverage skips exempt ACs. Every existing README content pin stays green unedited.

  Verified by content assertions on both files.

## Out of scope

- **Spec revision provenance (IDEA-0041).** A required cause on Changelog entries, the cause taxonomy and its rollup all touch the same FR template, but they are a separate FR. This FR adds no Changelog field. The aitk `**Cause: deferral**` prose stays prose.
- **Keying on `[P2]`, `[T]`, `[DEPRECATED]` or any other AC-text tag.** Tags are project vocabulary. The template keys only on `ac_state`.
- **Resolving IDEA pointers in the gate or in `INDEX.md`**, or failing anything on a dangling IDEA. See AC-3 and Open questions.
- **Making the gate skip whole superseded FRs.** `specs/README.md` leaves that to a later integrity-gate decision (IDEA-0056). This FR is per-AC only.
- **Hub `FR-INDEX.json` (`hub-index.py`) and `/hub-status` learning about deferrals.** Both are hub scripts and need human approval. A rollup of open deferrals across projects is a candidate follow-up IDEA.
- **`render-docs.py`.** It ignores the new states, and its sections 1 and 2 are unchanged. An FR whose only entries are exemptions now counts as having `ac_state` there, so it renders "Nothing has been signed off yet." instead of the "not enabled" note. That is accepted and not tested here.
- **`dispatch.py`, `agent-status.py` and the role files.** The Reviewer role's "every AC" wording is not edited. The gate's output is the contract, and a role-file note can ride a later craft-rules FR.
- **Migrating aitk's FRs.** That is aitk's work, done after `--upgrade`, by the recipe in Notes.
- **A command or flag to set an entry** (for example `index-specs.py --defer FR:AC IDEA-NNNN`). Hand-editing frontmatter is the interface.
- **Any change to the gate's AC detection** (`AC_HEADING_PATTERN` together with `AC_LABELLED_PATTERN` since FR-0027), **the `ac-format` warning, check 4 or check 5.** The same goes for FR-0023's layout handling: test and source directories, qualified annotations, and the layout error.

## Open questions

- **Q:** Should a dangling `IDEA-NNNN` pointer, or one pointing at an archived IDEA, fail anything when the hub is reachable?
  - **Default:** No. Stderr warning from the indexer only (AC-3). `INDEX.md` must be byte-stable across machines and across hub and non-hub checkouts, and CI often has no hub. A warning that fires locally is enough to stop silent loss. Revisit if the Open deferrals rollup shows rot.
- **Q:** Should local pointers (`FR`, `DEC`, `ADR`) that do not resolve be hard indexer errors instead of a fail-closed warning?
  - **Default:** No. Fail closed is already strict: the AC needs coverage again, so the gate fails a `merged` FR that relies on a broken pointer. A hard error would make a typo in one FR stop every gate run in the project. It would also break the fixed rule that the indexer's exit code changes for no input.
- **Q:** Should an all-exempt FR (AC-11) fail at `merged`?
  - **Default:** No; warn with `ac-all-exempt`. An FR whose every AC moved elsewhere is legitimate history, as aitk FR-0005 nearly was. The right fix there is usually `deprecated` or `lifecycle: superseded`, and the warning points that way. Make it a failure only if the metrics show it being abused.
- **Q:** Should the field be called `moved_to`, or `pointer`, `target` or `successor`?
  - **Default:** `moved_to`. It reads correctly for all three states: "the work moved to IDEA-0049", "moved to FR-0011". It is distinct from the FR-level `superseded_by`, which is about identity, not work, so a reader never confuses the two. `pointer` and `target` say nothing about direction. `successor` is wrong for `deferred` to the same FR. A scalar plus an optional `reason` keeps the YAML one line per AC, matching existing `ac_state` entries.
- **Q:** Should a `deferred` AC whose `moved_to` names another FR require a mirroring AC in that FR?
  - **Default:** No. The pointer names a home, not a contract. When the destination FR is drafted, its Architect cites the source AC in prose.

## Dependencies

- **FR-0002**: the `gate.run` record and warning-class enum AC-12 extends.
- **FR-0021**: the delegation rule (the gate asks the indexer; it does not parse) that AC-6 follows, and the base-ref bite-check technique AC-9 and AC-14 use.
- **FR-0023 (merged, PR #26)** also owns `template/scripts/deploy-gate.py`. It changed `collect_covers`; this FR changes checks 2 and 3. There is no semantic conflict, and FR-0023 has landed first. Its `# covers <project>` lines then count toward exempt ACs exactly as `@covers` does, which follows from AC-7 and AC-8 without change.
- **FR-0027 (merged, PR #24)** added labelled-AC detection to both scripts. This FR's "detected" and its Withdrawn-section parse follow it (Terms, AC-5; DEC-0029).
- **FR-0018 (ready)** also owns `template/scripts/metrics_log.py` and `template/specs/_metrics/README.md`. The edits are disjoint: its worktree redirect, and this FR's enum literal and one README row. Sequence by hand.
- None blocking.

## Notes

- **Choosing the state.** Consistent with ADR-0001 (revision vs supersession):
  - **`deferred`**: the AC is still part of this FR's need and will be delivered, just not in this pass. Its text stays under `## Acceptance criteria`. `moved_to` names where the work is tracked: a parked IDEA, a follow-up FR, or this FR itself. It is listed under `## Open deferrals` until a later change makes it live again (delete the entry) and a test covers it.
  - **`withdrawn`**: the AC is no longer wanted and nothing replaces it. `moved_to` is usually `null` with a `reason`, or the DEC or ADR that withdrew it. aitk FR-0002 AC-14 and FR-0004 AC-12 ("deferred to no target") are `withdrawn` with `moved_to: null`, not `deferred`: nothing will deliver them, so listing them as open would be noise.
  - **`superseded`**: another object now carries the AC's need. This is the per-AC analogue of ADR-0001 rule 5. `moved_to` names the successor FR, or the DEC or ADR that moved it. aitk FR-0005 AC-9/10/11, moved to FR-0011, are `superseded`. The existing ratification meaning of `superseded` (a ratified AC replaced by newer text) is the same idea, so one state serves both. An old `{state: superseded}` entry with no `moved_to` stays live until a pointer is added (AC-14).
  - Changing an AC's state is a spec change. Record it in the Changelog, and as a DEC when the project tracks revisions (ADR-0001 rule 2). This FR does not enforce that.
- **Migration recipe for aitk's convention.** This goes in `specs/README.md` (AC-15). For each AC currently written as `- **[DEPRECATED] AC-N** (withdrawn ...)` under `## Withdrawn acceptance criteria`:
  1. Add `N: {state: withdrawn|superseded, moved_to: <ID or null>, reason: "<the parenthetical>"}` to `ac_state`.
  2. Rewrite the bullet as `- **AC-N:** <original text>`, dropping the `[DEPRECATED]` marker and the `>` quote. Keep the section's introductory paragraph, but delete "No test may cover them".
  3. Optionally restore deleted tests that carry history (aitk FR-0005 AC-9/10, retired in `0952361`). Check 2 now accepts them.
  4. For each `[P2]` AC to defer, add `N: {state: deferred, moved_to: IDEA-NNNN}`. Park the IDEA first, so the pointer names a real file.
  5. Run `index-specs.py`. `## AC ratification warnings` should list nothing new for the FR, and `## Open deferrals` should list the deferrals.

  Skipping step 2 is safe, because the gate still honours the entry. The cost is that the AC-5 "no text in this FR" warning stays until the bullet is fixed.
- **Why the gate keeps its own AC detection.** Replacing the gate's detection (`AC_HEADING_PATTERN` together with `AC_LABELLED_PATTERN`) with the indexer's `parse_acs` would change which ACs the gate sees. Any FR whose ACs are written in neither the `- **AC-N:**` nor the `- **AC-N (L):**` column-0 form would be affected, and AC-14 forbids that. The gate asks the indexer only what it cannot answer itself: which ACs are honoured exemptions.
- **Isolation seams.** Gate and indexer behaviour runs through subprocess copies of the scripts in `tmp_path`, as `test_deploy_gate.py`'s `_build_repo` does. Copy `index-specs.py`, `deploy-gate.py`, `spec_footprint.py`, `spec_query.py` and `project_layout.py` (DEC-0029), plus `metrics_log.py` when a test reads a record. The hub lookup (AC-3) is tested by pointing `DISPATCH_HUB_ROOT` at a synthetic hub, and by leaving it unset. Neither `INDEX.md` nor the gate reads the network, the clock or the real hub.
- **First-live helpers.** Three helpers run for the first time and need their own tests: the indexer's hub-root finder (AC-3), the Withdrawn-section parser (AC-5) and the exported exemption function (AC-6).
- **Maintainer mode.** `template/scripts/deploy-gate.py` and `index-specs.py` are human-approval files (hub `CLAUDE.md`). Dispatch in `mnt` mode with the `owns:` above, after the human approves the control-plane edit, and record the approval in the Changelog. Edit `../../template/**`, never this project's bootstrap-output copies.
- **Reviewer dogfood (AGENTS.md).**
  1. Bootstrap a throwaway from the modified template.
  2. Add an FR at `merged` with one covered AC, one `deferred` AC pointing at an IDEA, and one `withdrawn` AC under the section with a `@covers`.
  3. Run `index-specs.py`, `deploy-gate.py`, `--stage dev` and `--status-only`. Each passes, and `INDEX.md` shows the deferral.
  4. Remove the `moved_to` and re-run. The gate fails with `coverage-missing` and warns `ac-exemption-invalid`.
  5. Delete the throwaway.
- **Related idea, out of scope:** IDEA-0041 (spec revision provenance: a cause field on Changelog entries) touches the same FR template. Design it to sit beside `ac_state`, not inside it.
- **Evidence.** aitk `specs/FR-0001` to `FR-0006` in the primary checkout, read 2026-10-26. IDEA-0035, including its 2026-10-22 note. Convergence decision 7 (2026-10-23).

## Changelog

- 2026-10-26: created from IDEA-0035 under convergence decision 7.
- 2026-10-30: Neil ratified (draft → ready), accepting the five Open-question defaults as written, and approved the control-plane edit to `template/scripts/deploy-gate.py` and `template/scripts/index-specs.py` (maintainer-mode dispatch authorised). Dispatch after FR-0023 lands. No normative change.
- 2026-11-02: v2 — DEC-0029 (breaking: false). Brought in line with merged FR-0027 and FR-0023 before dispatch.
  - "Detected" means `AC_HEADING_PATTERN` together with `AC_LABELLED_PATTERN`, in five places.
  - Labelled bullets count under `## Withdrawn acceptance criteria`.
  - "`@covers`" means any annotation `collect_covers` counts, in the layout's test directories.
  - Layout cases are added to AC-7, AC-8 and AC-14, and `project_layout.py` to the isolation copies.
  - `depends_on` gains FR-0023 and FR-0027.
  - `owns:`, the AC count and the cascade are unchanged.
- 2026-11-02: still v2 — DEC-0029 item 6 (breaking: false), from the r1 review at `4e86dd8` (E-1, N-2).
  - AC-5(a) fires only when an AC under the Withdrawn section has no entry, or its entry is not honoured. A honoured `deferred` AC there gets (c) alone. This matches the code.
  - AC-2 allows a self-pointer in every exemption state, which the code already honours.
  - DEC-0029 is unmerged, so `version` stays 2.
- 2026-11-03: status `ready` → `merged`. PR [#28](https://github.com/NeilRGilchrist/cos-agent-hub/pull/28) merged into `main` as commit `9a35bb3`. First CI run on the PR (Validate run 41560392115: template suite 2382 passed, 223 skipped; hub suite 208 passed, 78 skipped): no test failures. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
