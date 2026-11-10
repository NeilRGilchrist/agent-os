---
id: FR-0027
title: The deploy gate and the indexer detect an AC written `- **AC-N (label):**` exactly as they detect `- **AC-N:**`, so `@covers` on it resolves and coverage is required for it, and FRs with no labelled AC are byte-identical
status: merged
owner: architect
depends_on: []
tags: [gate, deploy-gate, indexer, spec-graph, template]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics").
# Documentation only; the Chief of Staff sequences the overlaps named in Dependencies.
owns:
  - template/scripts/deploy-gate.py
  - template/scripts/index-specs.py
  - template/tests/unit/scripts/test_labelled_acs.py            # new: this FR's gate and indexer tests
  - template/tests/fixtures/labelled-acs/**                       # new: synthetic fixture FRs
  - tests/unit/scripts/test_bootstrap_profiles.py                # Reviewer-only, AC-6: one `@covers FR-0001:AC-12` annotation, nothing else
reads:
  - template/scripts/render-docs.py
  - template/scripts/metrics_log.py
  - template/tests/unit/scripts/test_index_specs.py
  - template/tests/unit/scripts/test_index_specs_dec_tr.py
  - template/tests/unit/scripts/test_index_specs_versioning.py
  - template/tests/unit/scripts/test_deploy_gate.py
  - template/tests/unit/scripts/test_deploy_gate_metrics.py
  - template/tests/unit/scripts/test_deploy_gate_gates.py
  - template/tests/unit/scripts/test_deploy_gate_scope.py
  - template/tests/unit/scripts/test_spec_query.py
  - projects/hub-tooling/specs/FR-0001-profile-aware-upgrade.md
gates: []
derived_from: null
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: []
serves_roles: [architect, reviewer, orchestrator]
solution_space:
  open:
    - "The name of the labelled-form pattern(s) and of any helper, and whether `deploy-gate.py` compiles its own or reuses one from `index-specs.py` (it already imports that module), as long as AC-5's source pins hold."
    - "How `parse_acs` folds the label into the AC text, as long as the resulting text and hash are exactly AC-2's."
  fixed:
    - "`AC_LINE_PATTERN` (index-specs.py) and `AC_HEADING_PATTERN` / `AC_LOOSE_PATTERN` (deploy-gate.py) keep their names and their values. The labelled form is recognised by an additional pattern, never by loosening an existing one."
    - "The gate keeps its own AC detection over the whole body. It does not switch to the indexer's `parse_acs`."
    - "No new failure class, warning class, `counts` key, record kind or field. `metrics_log.py` is untouched."
    - "The `ac-format` warning's text and class are unchanged."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-10-30
updated: 2026-11-02
---

> **Provenance:** Drafted 2026-10-30 by the hub-tooling Architect at Neil's decision. A new FR fixes labelled-AC detection and lands before FR-0023 merges, replacing FR-0023's dependency on commit `0eef0f0`, which exists only in the other hub (ADR-0002). Grounded in a read of:
> - `template/scripts/deploy-gate.py`: `AC_HEADING_PATTERN`, `AC_LOOSE_PATTERN`, `_load_fr_summaries`, checks 2 and 3;
> - `template/scripts/index-specs.py`: `AC_LINE_PATTERN`, `parse_acs`, `normalize_ac_text`, `ac_hash`, `_ac_state_warnings`, `--ac-hashes`, `_object_fields`;
> - `template/scripts/render-docs.py`'s own `AC_LINE_PATTERN`;
> - the gate-source pins in `test_index_specs_dec_tr.py`, `test_spec_query.py` and `test_index_specs_versioning.py`.
>
> Two scans back it:
> - every FR in this repository and in each registered project, for AC bullet variants;
> - a simulation of the gate's checks 2 and 3 over hub-tooling with FR-0023's layout, with and without labelled detection.
>
> · source_class: neil_position+agent_observation · role: architect · model: opus · ip_class: hub_original.

# FR-0027: Labelled ACs are detected like plain ACs

## Why

The FR template writes ACs as `- **AC-N:** <text>`. Some FRs add a short label: `- **AC-N (<label>):** <text>`. The two tools that read ACs both miss that form.
- **`deploy-gate.py`.** `AC_HEADING_PATTERN` allows optional bold around `AC-N`, then a colon. A space and a parenthesis after the number defeat it, so the gate detects **no** AC in such an FR. Check 2 fails every `@covers` on it as `covers-unknown-ac`, at every stage. Check 3 requires nothing for it. Every mention of its ACs raises `ac-format`.
- **`index-specs.py`.** `AC_LINE_PATTERN` (`^-\s+\*\*AC-(\d+):\*\*`) misses the same lines. `parse_acs` returns nothing, `--ac-hashes` prints nothing, and an `ac_state` entry for such an AC is reported as having "no matching AC".

**Where it bites.** hub-tooling's FR-0001 (merged) writes all 12 of its ACs in labelled form. The hub's `tests/unit/scripts/test_bootstrap_profiles.py` carries 74 `@covers FR-0001:AC-N` annotations for AC-1..AC-11. Today no gate scans them. FR-0023 AC-6 gives hub-tooling `test_dirs: [template/tests, tests]`, and the gate then fails 11 `covers-unknown-ac` at every stage, including `dev`. A simulation on 2026-10-30 found exactly those 11 and nothing else. With labelled detection on, check 2 is clean and one failure remains at `review`/`full`: `coverage-missing` for FR-0001 AC-12, which no test is annotated for.

**Other projects.** A scan of every registered project found the labelled form in two more FRs, both `merged`, in one project (FR-0032 AC-4 and FR-0033 AC-12, each an "optional"/"stretch" AC). No other variant of a bold AC bullet with a parenthesised label occurs in any FR.

## What

After this FR, a labelled AC bullet is an AC to both tools, with the same number and the same consequences as the plain form:
- the gate counts it for checks 2 and 3 and for `ac-format`;
- the indexer returns it from `parse_acs`, hashes it, prints it from `--ac-hashes` and checks it against `ac_state`.

The label is part of the AC's text for hashing. A tree with no labelled bullet behaves byte-for-byte as today. The hub's FR-0001 becomes fully gate-visible, and its one unannotated AC gets its annotation.

## Terms

- **Labelled bullet:** a line of the form `- **AC-N (L):** R`. In order, it has:
  - `-` and whitespace;
  - `**AC-`, then the digits `N`;
  - one or more spaces or tabs, then `(`;
  - a non-empty label `L`;
  - `)` immediately followed by `:**`;
  - the rest of the line, `R`, which may be empty.

  `L` ends at the first `):**` on the line. It may contain backticks, commas, dashes and parentheses. FR-0001 AC-8's label, `` `--yes` is unattended and safe ``, is one example.
- **Not labelled:** these keep exactly today's treatment.
  - `- **AC-N:** (L) R`. This is a plain bullet whose text happens to start with a parenthesis.
  - `- **AC-N (L)**:` and `- **AC-N** (L):`, where the colon sits outside the bold.
  - `- **AC-N ():**`, whose label is empty.
  - `- **[DEPRECATED] AC-N** (...)`.
  - `- **AC-N rationale.**` and any other bold `AC-N` lead-in without the `(L):**` shape.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **The indexer parses a labelled bullet as an AC.** Inside `## Acceptance criteria`, `parse_acs` treats a labelled bullet that starts at column 0 exactly as it treats a plain `- **AC-N:**` bullet at column 0:
  - it starts AC `N` and ends the previous AC;
  - the continuation lines that follow belong to it, up to the next AC bullet of either form;
  - outside the section it is ignored, as a plain bullet is.

  An FR may mix the two forms. A number that appears twice, in either form, behaves as two plain bullets with that number do today. Lines that are not labelled bullets (Terms) produce no AC.

  Verified through `index_specs.parse_acs` on:
  - an all-labelled body, a mixed body, and a labelled AC with continuation lines;
  - a labelled bullet outside the section;
  - one body per "not labelled" shape in Terms;
  - a label holding backticks and a nested `(...)`.

- **AC-2:** **A labelled AC hashes as `(L) R`.** The text `parse_acs` returns for a labelled AC is `(L)`, a single space, then `R` and its continuation lines, exactly as a plain AC's text is `R` and its continuation lines. When `R` and its continuation lines are empty, the text is `(L)`. `ac_hash` and `normalize_ac_text` are unchanged. So:
  - `- **AC-N (L):** R` has the same hash as `- **AC-N:** (L) R`. An author may move between the two forms without flagging ratification drift.
  - Changing only the label changes the hash.
  - `--ac-hashes` prints one `FR-NNNN AC-N: <hash>` line per labelled AC, in number order with the plain ones.
  - An `ac_state` entry keyed on a labelled AC's number raises no "no matching AC" warning, and a ratified hash recorded from `--ac-hashes` matches.

  Verified with:
  - a fixture FR in each form whose `--ac-hashes` lines are equal;
  - a relabelled copy whose hash differs;
  - a subprocess `index-specs.py` run over a labelled FR with a ratified `ac_state` entry, which reports no AC ratification warning for it.

- **AC-3:** **The gate detects a labelled bullet as an AC.** The gate's detected AC set for an FR is today's `AC_HEADING_PATTERN` matches, plus the number of every labelled bullet in the body. It is computed over the whole body after the frontmatter, the same scope as today, and a labelled bullet may be indented by whitespace. Consequences, each through the subprocess gate:
  - **Check 2:** `@covers FR-NNNN:AC-N` on a labelled AC passes at `--stage dev` and `--stage full`. A `@covers` on a number that is neither labelled nor plain still fails `covers-unknown-ac` with today's message.
  - **Check 3:** at `in-review` or `merged`, an uncovered labelled AC fails `coverage-missing` with today's message at `review` and `full`. A covered one does not.
  - **`ac-format`:** a body mention of `AC-N`, where N is a labelled AC, no longer raises the warning. A mention of an AC that neither form detects still does, with today's text.

  Verified on fixture FRs: all-labelled, mixed, and a labelled bullet indented two spaces.

- **AC-4:** **No labelled bullet, no change.** For a tree in which no FR body contains a labelled bullet, both scripts behave byte-for-byte as at the base ref. That covers every printed line (stdout and stderr), exit code, written `INDEX.md` and `CODEOWNERS`, and `gate.run` metrics record (volatile fields excepted).
  - **Indexer runs:** plain, `--validate`, `--ac-hashes '*'`, `--list all --json` and `--slice <FR> --json`.
  - **Gate runs:** `--stage dev`, `--stage review`, `--stage full` and `--status-only`.
  - **The tree** covers every path: plain ACs, every "not labelled" shape from Terms, an `ac-format` trigger, a covered AC, an uncovered AC on a `merged` FR, an unknown-AC `@covers`, and a ratified `ac_state` entry.
  - **The comparison** runs the base ref's `index-specs.py`, `deploy-gate.py` and their sibling modules, loaded with `git show`, against this FR's copies on the same tree. It skips when the base ref is unreachable, as FR-0023 AC-7's baseline test does.

  For a tree that *does* hold a labelled FR, `INDEX.md` differs only in `## AC ratification warnings`, and only for an FR with a non-empty `ac_state`. `INDEX.md` renders no AC text or count.

- **AC-5:** **Pins and enums hold.** These stay green **unedited**:
  - `test_index_specs_dec_tr.py::test_deploy_gate_source_has_no_dec_tr_awareness_and_imports_resolve`. It forbids `collect_trs`, `collect_decs`, `collect_graph`, `DEC(`, `TR(` and `is_live_dec` in the gate's source, comments included.
  - `test_spec_query.py::test_deploy_gate_source_unchanged_and_imports_intact`. It forbids `spec_query` and `in_default_view`, and forbids `retired` case-insensitively.
  - `test_spec_query.py::test_consumer_scripts_do_not_import_spec_query`.
  - `test_index_specs_versioning.py::test_deploy_gate_imports_still_resolve`.
  - every existing `parse_acs`, `ac_hash` and `--ac-hashes` test in `test_index_specs.py` and `test_index_specs_dec_tr.py`;
  - the warning- and failure-class literals in `test_deploy_gate_metrics.py` and `test_deploy_gate_gates.py`.

  `AC_LINE_PATTERN`, `AC_HEADING_PATTERN` and `AC_LOOSE_PATTERN` compare equal, pattern and flags, to their base-ref values. Every test that passed before this FR passes unedited. A red is a `## FINDINGS` line for the Architect.

- **AC-6:** **The hub's FR-0001 is gate-visible and fully annotated.**
  - Run against the hub's real `projects/hub-tooling/specs/FR-0001-profile-aware-upgrade.md`, the gate's detection yields exactly AC-1..AC-12, and `parse_acs` yields 12 ACs, each text starting with its label in parentheses.
  - Every `@covers FR-0001:AC-N` in the hub's `tests/` names one of those 12.
  - The hub's `tests/` carries at least one `@covers FR-0001:AC-12`. It sits on a test that builds both FR-0001 fixture shapes, profiled and unprofiled, under a temporary directory. That AC's own text says "Tests carry `@covers FR-0001:AC-N` comments". The Reviewer adds the one annotation to `tests/unit/scripts/test_bootstrap_profiles.py`, on an existing test that requests both fixtures or on one new test that does, and changes nothing else in that file.
  - So, under FR-0023's layout, FR-0001 has no check 2 or check 3 failure at any stage.

  Verified by a template test that reads the hub's files and skips outside the hub, as FR-0023's AC-6 test does, and by `python -m pytest tests -q` from the hub root.

## Out of scope

- **`render-docs.py`.** It has its own `AC_LINE_PATTERN` and still omits labelled ACs from rendered docs. No doc spec renders FR-0001 today. See Open questions.
- **Other near-miss forms** (`**AC-N (L)**:`, `**AC-N** (L):`, the `[DEPRECATED]` form). They keep today's treatment, and the gate's `ac-format` warning keeps flagging them. FR-0026 owns the withdrawn/deprecated convention.
- **Rewriting FR-0001**, or any FR in any project, into the plain form. Both forms are now first-class.
- **A new indexer warning** for near-miss forms. The indexer gains no warning in this FR.
- **Other projects' consequences.** In the one other project with labelled ACs, FR-0032 AC-4 and FR-0033 AC-12 become detected after its next `--upgrade`. Neither has an `@covers` under `tests/`, so that project's gate gains `coverage-missing` for them at `review`/`full`. Covering them, or recording them as `deferred` once FR-0026 lands, is that project's work.
- **FR-0023's layout and `# covers <project>` annotations.** That is FR-0023.

## Open questions

- **Q:** Should the label be part of the hashed text, or stripped?
  - **Default:** Part of it, as `(L) R` (AC-2). The label states what the AC is about, so a relabel is a change a ratifier should see. The `(L) R` form also makes the hash equal to the plain-form rewrite, so converting between forms costs nothing.
- **Q:** Should the near-miss forms (`**AC-N (L)**:`, `**AC-N** (L):`) also count?
  - **Default:** No. None occurs in any FR in this repository or in any registered project (scan of 2026-10-30), and the `ac-format` warning already points authors at the template form. Widen only if one appears.
- **Q:** Should `render-docs.py` learn the labelled form in this FR?
  - **Default:** No. It is not a gate or indexer path, and no doc spec renders a labelled FR today. Park a one-line follow-up IDEA when this FR merges, so the three AC readers can be brought into one shared pattern later.
- **Q:** Should this FR add FR-0001 AC-12's annotation (AC-6), or leave it as FR-0023 AC-6's itemised residual?
  - **Default:** Add it here. Coverage becoming required for labelled ACs is this FR's consequence. The annotation is one line on a test that already exercises both fixture shapes. It is inert until FR-0023's layout makes the hub's `tests/` visible, and from then on hub-tooling's gate has no FR-0001 failure at any stage.

## Dependencies

- **None blocking.** FR-0027 lands first in its lane.
- **FR-0023** (ready; implemented at `9d48fd7`, DEC-0027 on its branch) owns `deploy-gate.py` and `index-specs.py`. Neil decided on 2026-10-30 that this FR lands before FR-0023 merges. FR-0023's AC-6 layout must not reach `main` first, because it makes the hub's `tests/` visible and FR-0001's labelled ACs would fail check 2 at every stage. FR-0023 rebases onto this FR, adds `FR-0027` to its `depends_on`, and keeps its own edits disjoint: `collect_graph()`'s layout error, and the gate's `collect_covers`/`collect_implements`.
- **FR-0026** (ready) owns `deploy-gate.py` and `index-specs.py`, and lands after FR-0023, so after this FR. Several of its statements name `AC_HEADING_PATTERN` as the gate's whole AC detection: its `solution_space.fixed`, AC-6's first sub-bullet, AC-7's "detected by `AC_HEADING_PATTERN`", the Out-of-scope bullet "Any change to the gate's AC detection", and Notes "Why the gate keeps its own AC detection". After this FR they should read "the gate's AC detection as FR-0027 leaves it". That needs a non-breaking DEC on FR-0026 before it is dispatched. Whether FR-0026 AC-5's Withdrawn-section parser, which matches `AC_LINE_PATTERN`, also accepts labelled bullets is that DEC's call. The proposed default is yes, through the same parse.
- **FR-0001** (merged) is the evidence, and only its hub test gains one annotation (AC-6).

## Notes

- **Maintainer mode.** `template/scripts/deploy-gate.py` and `template/scripts/index-specs.py` are human-approval files (hub `CLAUDE.md`). Neil has decided this FR should exist. **Approval of the control-plane edit is pending** and is recorded in the Changelog when given. Dispatch in `mnt` mode with the `owns:` above as the write surface. Edit `../../template/**` and the hub's `tests/`, never this project's bootstrap-output copies.
- **Tests.** Template tests ride into bootstrapped projects, so annotate them `# covers hub-tooling FR-0027:AC-N`. Do not use `@covers`, which would fail every other project's gate as an unknown FR. The one hub-test annotation in AC-6 is `@covers FR-0001:AC-12`, because the hub's `tests/` do not ride along.
- **Isolation.** Gate and indexer behaviour runs through subprocess copies of the scripts in `tmp_path`, as `test_deploy_gate.py`'s `_build_repo` does. Copy `index-specs.py`, `deploy-gate.py`, `spec_footprint.py` and `spec_query.py`, plus `metrics_log.py` when a test reads a record. Fixture FRs are synthetic. AC-6's hub read is the only test that touches real files, and it only reads them.
- **Base ref.** AC-4 and the bite check compare against `main` at the commit this FR is dispatched from. Pin that SHA in the test, as FR-0023 pins `_BASELINE_REF`.
- **Bite check.** Load the base ref's `deploy-gate.py` and `index-specs.py` as second modules and show AC-1, AC-2, AC-3 and AC-6's detection tests fail there.
- **hub-tooling's own gate copy.** `projects/hub-tooling/scripts/` changes only on `--upgrade`. An upgrade after this FR but before FR-0023 makes FR-0001's 12 ACs visible with none of its tests visible (no layout yet). That adds `coverage-missing` for FR-0001 at `review`/`full`, stages that are already red there (FR-0023's Why: FR-0002..FR-0014 at 0%). `dev` is unchanged. Upgrading after FR-0023 avoids that step.
- **Reviewer dogfood (AGENTS.md).**
  1. Bootstrap a throwaway from the modified template, with an explicit short path and `--no-register`.
  2. Add a `merged` FR whose ACs are AC-1 plain and AC-2 labelled, and a test covering only AC-1.
  3. Run `deploy-gate.py`. It fails `coverage-missing` for AC-2 only.
  4. Add the AC-2 annotation and re-run. It passes, and no `ac-format` warning is raised.
  5. Run `index-specs.py --ac-hashes '*'`. It prints both ACs.
  6. Delete the throwaway.

## Changelog

- 2026-10-30: created (draft) at Neil's decision to replace FR-0023's `0eef0f0` dependency with an FR in this repository. Awaiting Neil's ratification and approval of the control-plane edit to `template/scripts/deploy-gate.py` and `template/scripts/index-specs.py`.
- 2026-10-30: Neil ratified (draft → ready), accepting the four Open-question defaults as written (the label is part of the AC hash; near-miss forms are not labelled ACs; render-docs.py is out of scope with a follow-up IDEA; FR-0001 AC-12 is annotated here), and approved the control-plane edit to `template/scripts/deploy-gate.py` and `template/scripts/index-specs.py` (maintainer-mode dispatch authorised). No normative change.
- 2026-11-02: status `ready` → `merged`. PR [#24](https://github.com/NeilRGilchrist/cos-agent-hub/pull/24) merged into `main` as commit `f1a17a7`. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
