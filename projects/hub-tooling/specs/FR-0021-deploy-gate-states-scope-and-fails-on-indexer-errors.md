---
id: FR-0021
title: The deploy gate fails, before writing anything, on every spec-graph error the indexer refuses — DEC, TR and cross-object errors included — and its PASSED line states what it checked and that it ran no tests
status: merged
owner: architect
depends_on: []
tags: [gate, deploy-gate, indexer, quality-gate, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/deploy-gate.py
  - template/scripts/index-specs.py
  - template/tests/unit/scripts/test_deploy_gate_scope.py
  - template/tests/fixtures/deploy-gate-scope/**
  - template/.agent-team/roles/orchestrator.md
  - template/.agent-team/roles/reviewer.md
reads:
  - template/scripts/metrics_log.py
  - template/specs/_metrics/README.md
  - template/.github/workflows/agent-gates.yml
  - template/.claude/settings.json
  - template/.agent-team/commands/gate.md
  - template/tests/unit/scripts/test_deploy_gate.py
  - template/tests/unit/scripts/test_deploy_gate_metrics.py
  - template/tests/unit/scripts/test_deploy_gate_gates.py
  - template/tests/unit/scripts/test_index_specs_dec_tr.py
  - template/tests/unit/scripts/test_index_specs_versioning.py
  - template/tests/unit/scripts/test_spec_query.py
  - template/tests/unit/scripts/test_metrics_log.py
gates: []
derived_from: IDEA-0081
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0034]
last_breaking_revision: 2
supersedes: null
superseded_by: null
extends: [FR-0002, FR-0004, FR-0008]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - The name and exact signature of the one validation function `index-specs.py` exports for the gate, as long as AC-2's source constraints hold and it reports exactly the errors `index-specs.py --validate` reports.
    - Whether the gate's existing FR-only `validate_graph` call is replaced by the new function or kept beside it, as long as each distinct error is printed once.
  fixed:
    - "The gate never writes `specs/INDEX.md` (or anything else) when any validation error exists."
    - "An indexer failure is reported under the existing failure class `spec-validation`. No metrics enum, record kind, field or `counts` key changes."
    - "`deploy-gate.py` gains no DEC, TR or supersession logic of its own; it delegates to the indexer (FR-0004 AC-9, FR-0005 AC-10 intent)."
    - "The PASSED line stays ASCII and deterministic: two runs over the same tree print identical stdout."
    - "The gate runs no test suite (Out of scope)."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-11-05
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session) from IDEA-0081. Grounded in:
> - a read of `template/scripts/deploy-gate.py` and `index-specs.py` at `a8889df`;
> - a scratch reproduction of the partial-INDEX defect: an FR with `revisions: [DEC-0001]` and a DEC with `status: accepted`. `index-specs.py` refused, exiting 1 and writing no INDEX. `deploy-gate.py` printed PASSED, exited 0, and wrote an INDEX.md with no `## Decisions`;
> - a grep of every template test that pins the gate's output or source.
>
> · source_class: agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0021: The deploy gate fails on every indexer error and states its scope

## Why

AGENTS.md rule 6 says "run the gate before claiming done", so the gate's PASSED line is what every role reports as done. That line overstates the gate in two ways.

**It says nothing about tests, and the gate runs none.** In Project A's FR-0016/FR-0002 wave, the maintainer, the Reviewer and the Orchestrator all reported "gate green" while two knowledge tests failed (Project A L51), and one CI red reached a PR.

**It validates only part of the spec graph.** The gate imports the indexer's `collect_frs` and `validate_graph`, which cover FR parsing and the FR graph only. Its `render_index` call falls back to `collect_decs()` and discards DEC parse errors by design. That fallback is library behaviour; the indexer's own `main()` hard-validates through `collect_graph()`.

So when hub-tooling's DEC-0001 was ratified with the ADR token `accepted` instead of `ratified`, three things happened:
- `index-specs.py` refused.
- The gate printed PASSED, exited 0, and rewrote `specs/INDEX.md` without its `## Decisions` table, because DEC-0001 was the only DEC and it failed to parse.
- The missing table looked like a gate/indexer discrepancy for a whole FR round before anyone found the cause (hub-tooling wave-1 learnings, FR-0009 and FR-0010 sections).

The Stop hook runs the gate on every turn with `--status-only 2>&1 || true`, and it would have shown PASSED too.

## What

After this FR, the gate refuses on exactly the errors the indexer refuses on, before writing anything, and reports them in the indexer's own words under the existing `spec-validation` failure class. It does this by calling one validation function the indexer exports, so it still has no DEC or TR logic of its own. Its PASSED line keeps today's text as a prefix and appends what it checked and that it ran no tests. Two role files that describe the gate wrongly are corrected.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Any indexer validation error fails the gate before anything is written.** Take the indexer's validation errors to be exactly the set `index-specs.py --validate` reports: FR, TR and DEC parse errors, graph errors, and cross-object reference errors. When that set is non-empty, `deploy-gate.py` behaves the same at every `--stage`, with or without `--status-only`:
  - It prints the existing step-1 failure header (`Spec index validation failed:`) to stderr, followed by one `  <error>` line per distinct error, in the indexer's wording.
  - It exits 1.
  - It writes no `specs/INDEX.md`. An existing file is byte-identical afterwards.
  - Without `--status-only`, it emits its `gate.run` record with `outcome: fail` and failure class `spec-validation`, as it does today for an FR graph error.

  Verified with the DEC-0001 shape (an FR with `revisions: [DEC-0001]` and `DEC-0001` with `status: accepted`): FAILED, both indexer errors named, and INDEX.md byte-identical before and after. Also verified with a TR parse error, and with an unresolvable `supersedes`. Each is driven through the real script as a subprocess, once with only its required arguments (none) and once per stage.

- **AC-2:** **One validator, delegated.** The gate obtains AC-1's errors by calling one function that `index-specs.py` exports for that purpose. That function returns what `collect_graph()` collects: every error `--validate` would print, and nothing else. `deploy-gate.py` gains no DEC, TR or supersession parsing or vocabulary. These source pins stay green **unedited**:
  - `test_index_specs_dec_tr.py::test_deploy_gate_source_has_no_dec_tr_awareness_and_imports_resolve` (FR-0004 AC-9). No `collect_trs`, `collect_decs`, `collect_graph`, `DEC(`, `TR(` or `is_live_dec` token appears in the gate's source, and `render_index(parsed_frs, repo_files)` remains.
  - `test_spec_query.py::test_deploy_gate_source_unchanged_and_imports_intact` (FR-0005 AC-10). No `spec_query`, `in_default_view` or `retired`, compared case-insensitively and including in comments.
  - `test_spec_query.py::test_consumer_scripts_do_not_import_spec_query`.
  - `test_index_specs_versioning.py::test_deploy_gate_imports_still_resolve` (FR-0003 AC-8).

  The new function's name must avoid every token listed above.

- **AC-3:** **Valid graphs behave exactly as today.** On a tree the indexer validates, the gate writes the same `specs/INDEX.md` it writes today. It stays byte-identical to the indexer's, as these tests pin:
  - `test_index_specs_versioning.py::test_deploy_gate_and_indexer_write_byte_identical_index`
  - `test_index_specs_dec_tr.py::test_deploy_gate_stage_full_passes_and_writes_byte_identical_index`
  - `test_spec_query.py`'s byte-identical-index test with the new sections
  - `test_deploy_gate_metrics.py`'s two byte-identical-index tests, with and without records

  The `gate.run` record's fields, `counts` keys, stage and outcome are unchanged. Every existing gate, indexer and metrics test passes unedited, including the failure-class and warning-class set pins in `test_deploy_gate_metrics.py` and `test_deploy_gate_gates.py`.

- **AC-4:** **The PASSED line states the gate's scope.** The line keeps its current text exactly, `Deploy gate PASSED (stage=<stage>): <n> FRs, <c> @covers annotations, <i> @implements annotations`, and appends:
  - at `--stage dev`: `; scope: spec graph, annotations; tests not run`
  - at `--stage review` and `--stage full`: `; scope: spec graph, annotations, AC coverage, gate evidence; tests not run`

  The line is ASCII-only. Two runs over the same tree print identical stdout, so every existing stdout-comparison test stays green. Examples are `test_deploy_gate_metrics.py::test_every_branch_is_byte_identical_with_emission_on_and_off` and `test_deploy_gate_gates.py::test_the_bare_deploy_gate_invocation_runs_the_lint_at_stage_full`. So do the substring pins on `Deploy gate PASSED` (`test_deploy_gate.py` L83, `test_deploy_gate_metrics.py` L349). The FAILED and WARNINGS formats are unchanged. Verified at each stage through the real script.

- **AC-5:** **The role files describe the gate correctly.**
  - In `template/.agent-team/roles/orchestrator.md`, the "After Architect phase" invocation `python scripts/deploy-gate.py --stage spec` becomes `python scripts/index-specs.py --validate`. `--stage spec` is not a valid choice; argparse exits 2.
  - In `template/.agent-team/roles/reviewer.md`, the rejection step's parenthetical "the gate uses review state" is replaced by a statement that the dispatcher reads the verdict from the Reviewer's final message heading (see the reviewer command). The deploy gate reads no review state.

  No other line of either file changes. Verified by content assertions.

  **Revised by DEC-0034 (v2, breaking):** in `roles/reviewer.md`, the rejection step records a `## Request changes` verdict, which the dispatcher reads from the Reviewer's final message heading (see the reviewer command and `## Recording your verdict`, FR-0030 AC-2). The deploy gate reads no review state, and the role file says so. "No other line of either file changes" is a statement about this FR's own commit; `roles/reviewer.md` changes further under FR-0030. The orchestrator half is unchanged.

## Out of scope

- **Running the test suite from the gate (`--stage full` running pytest, or an opt-in flag).** Three hazards were found and are unsolved:
  - Recursion: a Project A test runs the gate at `--stage full` inside pytest, and many template tests run the gate at the default stage in temporary repos.
  - The Stop hook runs the gate on every turn.
  - The dispatcher's `_run_deploy_gate` has a 180 s timeout.

  AC-4 makes the gap visible instead. Park a follow-up if a suite hook is still wanted.
- The `render_index` default path's silent DEC/TR error drop inside `index-specs.py`. It is library behaviour the indexer's own `main()` never relies on, and AC-1 makes the gate validate before it renders.
- `template/.agent-team/commands/gate.md`'s "When green, report…" line. It is a command source whose wrappers regenerate through `scripts/bootstrap.py`. FR-0022 or a later command FR can mention the scope clause.
- Windows stdout encoding of the gate's stderr failure lines: FR-0016 is scoped to the dispatcher. The PASSED line stays ASCII (AC-4).
- Any change to `--status-only`, the Stop hook, or the metrics schema.

## Open questions

- **Q:** Should the scope clause be a separate line rather than a suffix?
  - **Default:** A suffix. A second line would change the stdout of every gate run that tests compare line-by-line. The suffix keeps every `"Deploy gate PASSED" in stdout` pin and every run-versus-run comparison green.
- **Q:** Should an indexer failure get its own failure class (`index-validation`)?
  - **Default:** No. `spec-validation` already names "the spec graph did not validate". A new class would change the closed enum that three test files pin exactly, and `specs/_metrics/README.md`.

## Dependencies

- **FR-0002**: the `gate.run` record and failure-class enum this FR must not change.
- **FR-0004 / FR-0005 / FR-0003**: the gate-source pins AC-2 keeps green, and the DEC/TR validation the gate now delegates to.
- **FR-0008**: the gate-evidence lint named in AC-4's scope clause.
- None blocking: this FR shares no owned file with any other wave-2 FR.

## Notes

- **Maintainer mode.** `template/scripts/deploy-gate.py` and `index-specs.py` are human-approval files (hub `CLAUDE.md`), and so is `template/.agent-team/**`. This FR is dispatched in `mnt` mode with the `owns:` above as its write surface. The human's approval of this FR is the approval for those edits. Edit `../../template/**`, never this project's bootstrap-output copies.
- **Permitted incidental edit.** `deploy-gate.py`'s module docstring says it exits "2 on script error". `main()` re-raises (L278-282), so a script error exits 1 with a traceback. Correct that sentence; change nothing else outside the ACs.
- **Reviewer, following the wave-1 rule** (Project A DEC-0044; wave-2 plan §5):
  - Drive the gate through the real script (`subprocess.run([sys.executable, <gate>, …])`), once with no arguments at all.
  - Make AC-1 fail for real on a fixture whose DEC carries the ADR token `accepted`. Assert rc 1 and assert INDEX.md is byte-identical. Asserting a message alone is not enough.
  - Bite check: load `git show a8889df:template/scripts/deploy-gate.py` as a second module and show AC-1's test fails against it: it passes and writes a partial INDEX.
- **Reviewer dogfood (AGENTS.md).** Bootstrap a throwaway from the modified template, commit a DEC with `status: accepted`, and run `scripts/deploy-gate.py`, `--stage dev` and `--status-only`. Each must fail loudly and leave INDEX.md untouched. Fix the DEC, then confirm PASSED carries the scope clause. Delete the throwaway.
- **Evidence.** Project A `_dispatch/learnings-FR-0016-FR-0002-wave.md` L50(b) and L51. Hub-tooling `_dispatch/learnings-wave1.md` FR-0009 ("template defect candidate": vanishing Decisions table) and FR-0010 ("DEC vocabulary trap … root cause"). The current live trees validate clean (hub-tooling: 16 FRs and 17 DECs; Project A: 20 FRs and 52 DECs), so AC-1 turns neither red on upgrade.

## Changelog

- 2026-09-25: created from IDEA-0081.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified this FR's `neil`-tier DECs. No normative change.
- 2026-11-05: v2 — DEC-0034 (breaking: true): AC-5's reviewer half follows FR-0030. The rejection step records a `## Request changes` verdict instead of "Use `Request changes` on the PR". The test cascade is `test_deploy_gate_scope.py::test_reviewer_rejection_step_names_the_dispatcher_verdict_heading`. Implemented by FR-0030 AC-1. `neil` tier, proposed.
