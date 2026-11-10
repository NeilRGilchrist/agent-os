---
id: FR-0020
title: "`--upgrade` stops clobbering project-specialised files: `pytest.ini` is seeded not synced, stack-injected files are rendered for the project's stack, added files carry a provenance reminder, and `.gitattributes` gains a managed LF block that never overwrites the project's own rules"
status: merged
owner: architect
depends_on: [FR-0019]
tags: [bootstrap, upgrade, hub-scripts, line-endings, provenance, template]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics"). scripts/bootstrap.py is a hub script and a human-approval file.
owns:
  - scripts/bootstrap.py
  - template/.gitattributes
  - tests/unit/scripts/test_bootstrap_upgrade.py
  - tests/fixtures/bootstrap-upgrade/**
reads:
  - tests/unit/scripts/test_bootstrap_profiles.py
  - template/pytest.ini
  - template/.cursor/rules/20-python.mdc
  - template/.cursor/rules/20-node.mdc
  - template/.github/workflows/agent-gates.yml
  - template/specs/_metrics/README.md
  - template/tests/unit/scripts/test_metrics_log.py
  - hub/projects.yaml
  - specs/FR-0001-profile-aware-upgrade.md
gates: []
derived_from: IDEA-0080
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0001]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - Whether the seed-only set is a module constant or a generalisation of the existing `.claude/settings.json` branch, as long as there is one home for the rule and `settings.json`'s behaviour is byte-identical.
    - How `enable_cursor_rule` / `uncomment_ci_job` are refactored into pure text transforms usable both at create (on disk) and at upgrade (in memory), as long as create's output is byte-identical to today's.
    - The exact marker comment lines of the `.gitattributes` managed block and the binary-exception list, as long as AC-4's minimum set is present and every line inside the block is a valid gitattributes line.
    - Exact wording of the new notice, provenance and renormalize lines.
  fixed:
    - "`--upgrade` never runs git: no `git add --renormalize`, no commit. It prints what the human should run."
    - "No line of a project's `.gitattributes` outside the managed block is ever changed, moved or removed."
    - "Existing FR-0001 behaviour, prompts and summary wording are unchanged except where an AC here says otherwise; every test in `tests/unit/scripts/test_bootstrap_profiles.py` passes unedited."
    - "No test and no dogfood step writes to the live hub: `parking-lot/`, `patterns/`, `hub/` and `projects/` are byte-identical before and after the Reviewer's session (Notes)."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-09-25
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session) from IDEA-0080 and IDEA-0073 (with its 2026-09-20 Project A Architect note), grounded in a read of `scripts/bootstrap.py` at `a8889df` (`INFRA_ROOT_FILES` L81, `build_sync_plan` L1229, `run_upgrade` L1335, the stack injectors L337–429, `find_registry_entry` L707) and in Project A's and hub-tooling's committed `pytest.ini`, `.gitattributes`, `.cursor/rules/20-python.mdc` and `agent-gates.yml`. · source_class: agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0020: `--upgrade` stops clobbering project-specialised files and syncs a managed `.gitattributes` block

## Why

`bootstrap.py --upgrade` whole-file overwrites every path in `INFRA_DIRS` and `INFRA_ROOT_FILES` that differs from the template. That fails in four ways.

1. **`pytest.ini` is clobbered.** Project A's `pytest.ini` is the template's plus an appended project section (FR-0001 AC-4: `testpaths`, an `integration` marker). Every one of Project A's three upgrades replaced it, and it was restored by hand each time.
2. **Stack injection is silently reverted.** At create, a `--stack python` project gets two edits: `.cursor/rules/20-python.mdc` is enabled and the `python-tests` CI job uncommented. `--upgrade` never learns the stack, so it reverts both to the template's disabled form. This has already happened: hub-tooling's self-upgrade `2a786a0` undid its own `0194bb5`.
3. **Added files arrive silently.** New template files such as `stack_profile.py`, `env_preflight.py` and the gate-review wrappers arrive without the one thing a provenance-registered project needs. Project A FR-0015 requires a register row for every file under `scripts/`. A template upgrade is not a role action, so no role's "mint a row" rule fires (Project A L50), and one such file reached CI red on Project A PR #10. The summary does list "Added:", but 22 CRLF wrapper "Updated" lines bury it (fixed by FR-0019) and nothing says what an added file needs.
4. **`.gitattributes` is never synced.** It is copied at create but not in the upgrade plan, so the template's `merge=union` metrics rule reaches existing projects only by hand (`template/specs/_metrics/README.md` says so), and hub-tooling has no `.gitattributes` at all. IDEA-0073 wants repo-wide `* text=auto eol=lf` in the template, after the CRLF problem was fixed three times in three places. Adding the file to the whole-file overwrite set would clobber Project A's own rules: `*.pptx -text` (DEC-0036) and its `specs/INDEX.md` pin.

## What

After this FR, `--upgrade` does five things differently:
- It treats `pytest.ini` like `.claude/settings.json`: seeded when absent, never overwritten, and drift reported.
- It renders the two stack-injected files for the project's registered stack before comparing, so an upgrade keeps them enabled and still delivers template changes to them.
- When the project carries a provenance register, it names every added file that needs a row.
- It owns only a marked block at the top of `.gitattributes`, replacing that block and inserting it when absent, and never touches the project's own lines.
- It prints the renormalize command when that block changes.

The template's `.gitattributes` becomes that managed block, with `* text=auto eol=lf`, binary exceptions and the existing metrics union rule.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **`pytest.ini` is seeded, never overwritten.** `pytest.ini` joins `.claude/settings.json` in one named set of seed-only paths:
  - **Absent:** it is added as today.
  - **Present and different from the template:** it is **not** overwritten, in `--yes` or interactive mode. One line in the existing drift form is printed: `! pytest.ini differs from template — NOT changed (drift; reconcile by hand)`. It is listed under the summary's `Drift:` block. Interactive mode prints the diff without prompting, as it does for `settings.json`.

  `.claude/settings.json`'s behaviour and output are byte-identical to today's. Verified with Project A's shape (the template's bytes followed by an appended project section), which is byte-identical after `--upgrade --yes`, and with a project whose `pytest.ini` is absent, which receives the template's.

- **AC-2:** **Stack-injected files are compared against the project's stack rendering.**
  - **Resolving the stack:** `--upgrade` reads the project's stack from its registry entry, found by `find_registry_entry` (resolved path, then name, with `hub/projects.local.yaml` overlaid) and its `stack:` value.
  - **Resolved `python` or `node`:** before comparing `.cursor/rules/20-<stack>.mdc` and `.github/workflows/agent-gates.yml`, the upgrader applies to the template's text in memory the same transforms create applies (`enable_cursor_rule`, `uncomment_ci_job`). It then compares and writes that rendering.
  - **`none`:** the template bytes are used, as today.
  - **Unresolved** (no registry entry, unreadable registry, or a `stack:` outside `python | node | none`): those two paths join AC-1's seed-only set for this run, and one notice line says the stack is unknown and names both paths.
  - `AGENTS.md` is still never in the plan. Create's output is byte-identical to today's.

  Verified:
  - A fresh `--stack python` throwaway registered in a temporary hub, upgraded `--yes` with an unchanged template, reports neither file.
  - With a changed `agent-gates.yml` in the temporary template, the same project receives the change with its `python-tests` job still uncommented.
  - An unregistered throwaway whose two files differ from the template keeps them, with the notice.

- **AC-3:** **Added files carry a provenance reminder when the project keeps a register.** When `specs/knowledge/provenance-register.md` exists in the project and the upgrade added at least one file, whether template- or profile-sourced, one line follows the summary's `Added:` block: `Provenance: <N> added file(s) need a row in specs/knowledge/provenance-register.md before commit:`. It is followed by one line per added path. Nothing extra is printed when nothing was added or the register is absent. The existing summary lines are unchanged (FR-0001 pins `Updated:`, `Added:`, `+ <path>`, `NEW: <path>`). Verified with and without the register, and with zero and two added files.

- **AC-4:** **The template's `.gitattributes` is a managed block.** `template/.gitattributes` consists of one block delimited by two marker comment lines that name `bootstrap.py --upgrade` as its owner. The block contains:
  - `* text=auto eol=lf`;
  - `binary` rules for at least `*.png`, `*.jpg`, `*.jpeg`, `*.gif`, `*.ico`, `*.pdf`, `*.zip`, `*.pptx`, `*.docx` and `*.xlsx`;
  - the existing `specs/_metrics/*.ndjson merge=union` rule with its comment. `test_metrics_log.py::test_gitattributes_declares_union_merge_for_month_files_and_git_applies_it` stays green unedited.

  Create copies the file as today. Within the hub repo, every tracked text file under `template/` is already LF, so the new rule changes no index entry there. Verified by `git check-attr` on a fresh throwaway: `text`/`eol` for a `.py` file, `binary` for a `.png`, `merge: union` for a month file.

- **AC-5:** **`--upgrade` syncs the managed block and never touches the project's own lines.** `.gitattributes` joins the upgrade plan with this rule:
  - **Absent:** the template's file is added, reported like any added file.
  - **Present with both markers:** the lines from the opening marker through the closing marker are replaced by the template's block, and every other line is kept byte-for-byte in place. An identical block is not reported.
  - **Present without markers** (every existing project today): the template's block is inserted at the top, followed by one blank line and then every existing line in its original order. Under git's rule that a later matching line wins, the project's own lines keep overriding the block, so Project A's `*.pptx -text` still applies.
  - **Duplicates:** a project line outside the block that is identical to a line inside it is kept. One `NOTE` line names such lines.
  - **Markers damaged** (only one present, or reversed): the file is not changed, and one drift line names it.
  - **Reporting:** a replaced or inserted block is reported as `Updated`. Interactive mode shows the diff and prompts as for any other file.

  When the block was inserted or changed, one line reminds the human to run `git add --renormalize .` and commit the result, and `--upgrade` runs no git command. Verified against:
  - a project with no `.gitattributes`;
  - Project A's shape (four rules, no markers): after the upgrade the four lines follow the block unchanged;
  - a project whose block is current: no change, no line;
  - a project whose block is stale: the block is replaced and the outside lines are byte-identical;
  - a file with one marker only: unchanged, with a drift line.

- **AC-6:** **Upgrades are idempotent.** A second `--upgrade --yes` immediately after the first changes no byte in the project, and reports "Everything is already up to date." plus any seed-only drift lines. Verified over each AC-1, AC-2 and AC-5 fixture.

- **AC-7:** **Existing behaviour is preserved.**
  - Every test in `tests/unit/scripts/test_bootstrap_profiles.py` passes unedited.
  - Profile sync, profile verification, `.claude/settings.json` drift, the `--yes` and interactive semantics, and the exit code (0) are unchanged apart from these ACs.
  - `UPGRADE_EXCLUDE`, which is unreferenced, is neither used nor removed by this FR.

## Out of scope

- A general project-overlay or three-way merge for infrastructure files, and splitting `AGENTS.md` into core and overlay: IDEA-0034. This FR is the narrow no-clobber fix.
- A generic post-upgrade hook. AC-3 is the one concrete trigger the evidence supports.
- Recording the stack in the project itself, like FR-0001's `profiles.yaml`. AC-2 reads the registry field every registered project already has, and the unresolved case is safe.
- Running `git add --renormalize` or committing anything.
- The LF writers and `COMMAND_META`: **FR-0019**, which this FR depends on.
- A hub-root `.gitattributes`.
- Removing Project A's local `specs/INDEX.md text eol=lf` line. That is Project A's call once the managed block lands; the line is harmless after the block.

## Open questions

- **Q:** Should `pytest.ini` still receive template changes, for example via a prefix rule that updates the template-owned leading section and keeps the rest?
  - **Default:** No. Drift reporting with the diff is honest and matches the `settings.json` precedent. The template's `pytest.ini` has changed once in its life, so an inferred merge rule would be guessing. IDEA-0034's overlay split is the general answer.
- **Q:** Should AC-2's unresolved-stack case prompt for the stack instead?
  - **Default:** No. `--yes` runs must not block, and seed-only is the safe no-op. The notice names the fix: register the project, or set its `stack:`.
- **Q:** hub-tooling is registered `stack: python`, but its two stack files are in template form after `2a786a0`. The first upgrade after this FR re-enables them. Is that wanted?
  - **Default:** Yes. It restores what create did in `0194bb5`. The CI job under `projects/hub-tooling/.github/workflows/` is not run by GitHub (only the hub root's workflows are), so nothing new runs. The Orchestrator notes it in the post-merge upgrade commit.

## Dependencies

- **FR-0019**: the same file. After FR-0019, the wrappers regenerate LF, which removes the 22 "Updated" lines that would bury AC-3's report, and the stack injectors write LF.
- **FR-0001**: the upgrade plan, the drift rule, `find_registry_entry` and the summary wording this FR extends. FR-0001 is not revised: every statement it makes still holds, and its tests pass unedited (AC-7).

## Notes

- **Human approval (hub `CLAUDE.md`).** `scripts/bootstrap.py` is a hub script. This FR is dispatched in maintainer (`mnt`) mode with the `owns:` above as its write surface. **It must not be dispatched until Neil has approved it and the approval is recorded in the Changelog.** Edit `../../scripts/bootstrap.py` and `../../template/.gitattributes`, never this project's copies.
- **Tests live at the hub root** in `../../tests/unit/scripts/`. Follow `test_bootstrap_profiles.py`'s fake-hub pattern: a `tmp_path` hub with `template/`, `profiles/` and `hub/projects.yaml`, and every module root constant monkeypatched (`HUB_ROOT`, `TEMPLATE_ROOT`, `PROFILES_ROOT`, and any registry path). Run with `python -m pytest tests/`. The Reviewer states per-AC coverage in the PR body (AGENTS.md §2).
- **Reviewer dogfood: never against the live hub (mandatory).** `bootstrap.py` roots itself at `Path(__file__).resolve().parent.parent`, and `--upgrade` reads, and with `--profile` writes, `hub/projects.yaml` by resolved path and then **by project name**. Work on a temporary copy of the hub, as FR-0019's Notes describe:
  1. Record `git -C <hub> status --porcelain -- parking-lot patterns hub projects` before starting.
  2. Copy `scripts/`, `template/`, `profiles/`, `hub/`, `parking-lot/` and `patterns/` into a short temp path. Use real copies: symlinks resolve back to the live hub.
  3. Register the fixture projects in the **copy's** `hub/projects.yaml`.
  4. Run the copied `bootstrap.py` with explicit paths and `--no-register` for creates. Never use a bare name. Never name a throwaway after a registered project (`pm-graph-poc`, `Project B`, `Project A`, `hub-tooling`).
  5. Exercise every AC fixture:
     - a customised `pytest.ini` (survives);
     - a `--stack python` project (neither stack file clobbered, and a template change still arrives);
     - a `specs/knowledge/provenance-register.md` (the reminder prints);
     - Project A's `.gitattributes` shape (block inserted on top, Project A's lines intact);
     - the `phipa` profile recorded in `.agent-team/profiles.yaml` (the hook and `settings.json` still survive).

     Then run each throwaway's `scripts/index-specs.py --validate` and `scripts/deploy-gate.py` (AGENTS.md §3).
  6. Re-run the step-1 `git status --porcelain`. It must be identical. Delete the temp tree.
- **Bite check.** Load `git show <base>:scripts/bootstrap.py` as a second module and show AC-1, AC-2 and AC-5's tests fail against it.
- **Post-merge (Orchestrator).**
  - `--upgrade projects/hub-tooling --yes` now inserts the managed `.gitattributes` and re-enables the python rule and CI job (Open question 3). Then run `git add --renormalize projects/hub-tooling` and commit.
  - Tell the Project A Orchestrator that the next Project A upgrade no longer needs the `pytest.ini` restore step, and will insert the block above Project A's own four rules. Verify once, then retire the checklist step.
- **Overlap with FR-0018.** `template/.gitattributes` may also be touched by FR-0018 (IDEA-0079) if it changes the metrics `merge=union` line. Whichever merges second rebases. The union line lives inside the managed block, so FR-0018 edits it there.

## Changelog

- 2026-09-25: created from IDEA-0080 with IDEA-0073 (template `.gitattributes`, not in `INFRA_ROOT_FILES`) folded in; the LF and `COMMAND_META` half of the lane went to FR-0019. Awaiting Neil's approval of the hub-script edit before dispatch.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified this FR's `neil`-tier DECs. No normative change.
