---
id: FR-0019
title: Hub-side writers emit LF on every platform, and each command source declares its own wrapper frontmatter — `COMMAND_META` is retired
status: merged
owner: architect
depends_on: []
tags: [hub-scripts, line-endings, commands, bootstrap, template, windows]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics"). Hub scripts are human-approval files.
owns:
  - scripts/bootstrap.py
  - scripts/parking.py
  - scripts/patterns.py
  - template/.agent-team/commands/*.md
  - template/.claude/commands/*.md
  - template/.cursor/commands/*.md
  - tests/unit/scripts/test_hub_writers_lf.py
  - tests/unit/scripts/test_command_frontmatter.py
  - tests/fixtures/command-frontmatter/**
  # DEC-0016 cascade — Reviewer only, bounded to the test ids DEC-0016 names:
  - template/tests/unit/scripts/test_headless_conduct.py
  - template/tests/unit/scripts/test_dispatch_gates.py
reads:
  - scripts/hub-index.py
  - scripts/_console.py
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_line_endings.py
  - tests/unit/scripts/test_bootstrap_profiles.py
  - specs/decisions/DEC-0004-fr0012-owns-widens-to-every-generated-wrapper.md
  - specs/decisions/DEC-0013-fr0008-owns-gains-bootstrap-command-meta-gate-review-entry.md
  - specs/decisions/DEC-0016-fr0012-wrapper-body-follows-source-frontmatter-and-ac10-anchors-to-its-merge.md
gates: []
derived_from: IDEA-0063
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0007, FR-0012]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - How the source frontmatter is parsed (PyYAML, already a hub prerequisite, or a small line parser), as long as AC-4's rendering and AC-6's refusals hold.
    - Whether the LF fix is a shared `_write_lf(path, text)` helper in each hub script or `newline="\n"` at every call site, as long as AC-1 holds for every write it names.
    - Exact wording of AC-6's warn lines, as long as each names the file and the cause (or key).
  fixed:
    - "The template's 22 committed wrappers are byte-identical before and after this FR (AC-5). The metadata moves; the output does not change."
    - "`COMMAND_META` is deleted. No second source of per-command metadata survives."
    - "No test and no dogfood step writes to the live hub: `parking-lot/`, `patterns/`, `hub/` and `projects/` are byte-identical before and after the Reviewer's session. Hub scripts are exercised only against a temporary copy of the hub (Notes)."
    - "`scripts/hub-index.py` is not edited. It already writes LF."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-09-25
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session) from IDEA-0063 and its 2026-09-25 Notes (generate_commands CRLF; per-command frontmatter), the hub-tooling Orchestrator's "open `scripts/bootstrap.py` once" request (`_dispatch/synthesis-wave1-2026-09-22.md` follow-up #2), and DEC-0013's `alternatives`. Grounded in a read of `scripts/{bootstrap,parking,patterns,hub-index}.py` and `template/tests/unit/scripts/test_headless_conduct.py` at `a8889df`. · source_class: agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0019: Hub-side writers emit LF, and command sources carry their own frontmatter

## Why

FR-0007 made the template's generated artifacts LF on every platform. It left the hub's own writers out of scope, and they still emit the host's line endings. On Windows the costs are these:
- `parking.py` and `patterns.py` write `parking-lot/INDEX.md`, `patterns/INDEX.md`, `hub/PATTERN-INDEX.md` and every IDEA or PATTERN file they touch as CRLF. That produces a whitespace-only dirty diff that every session restores by hand. 54 files in the hub index are CRLF today.
- `bootstrap.py::generate_commands` writes every `.claude/commands/*.md` and `.cursor/commands/*.md` wrapper as CRLF.
  - Both FR-0012 rounds normalised the wrappers by hand.
  - All 22 hub-tooling wrappers are committed CRLF, so every `--upgrade --yes` there reports 22 "Updated" files, which buries the "Added" list IDEA-0080 needs people to read.
  - An upgrade into an LF-normalised project (Project A) shows about 20 phantom wrapper diffs.

In the same function, `COMMAND_META` is a hub-script dict holding every command's description, hint and model. Adding a command therefore means crossing into a human-approval hub script. FR-0008 needed a `neil`-tier DEC (DEC-0013) for one key, and that DEC's own `alternatives` name the fix: per-command frontmatter in the command source. The Orchestrator asked that `bootstrap.py` be opened once, properly reviewed, for both.

## What

After this FR lands, every file `bootstrap.py`, `parking.py` and `patterns.py` writes as text is LF on every host. Each of the 11 canonical command sources under `template/.agent-team/commands/` opens with its own YAML frontmatter block. `generate_commands` reads that block, strips it from the body, and renders the wrapper frontmatter exactly as it rendered `COMMAND_META` before. `COMMAND_META` is gone. The template's wrappers come out byte-identical to today's LF wrappers, so the migration is provably lossless. A new command needs one file, with no hub-script edit.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Every hub-script text write is LF.** Each of the following writes UTF-8 with `"\n"` line endings on every host. The written file contains no `\r\n` that the script produced:
  - `scripts/bootstrap.py`:
    - the `AGENTS.md` description substitution (`substitute_description`);
    - the stack-conventions injection (`inject_stack`);
    - the Cursor rule enable (`enable_cursor_rule`);
    - the CI job uncomment (`uncomment_ci_job`);
    - both wrapper writes in `generate_commands`;
    - the profile hygiene-block append to `AGENTS.md`.
  - `scripts/parking.py`: `write_idea`, `cmd_add` and `reindex`.
  - `scripts/patterns.py`: `write_pattern`, `cmd_propose`, and both `reindex` writes (`patterns/INDEX.md`, `hub/PATTERN-INDEX.md`).

  Apart from line endings, each output is byte-identical to today's output with `\r\n` normalised to `\n`. Verified per write site, on a Windows host or by the technique `template/tests/unit/scripts/test_line_endings.py` uses (FR-0007). Every scenario runs against a temporary hub or project tree, never the live hub.

- **AC-2:** **Each canonical command source declares its own metadata.** Each of the 11 files in `template/.agent-team/commands/` has the same shape:
  - It opens with a frontmatter block: `---` on line 1, then one `key: value` line per key, then a closing `---` line, then exactly one blank line, then the body.
  - The block carries exactly the keys and values `COMMAND_META` holds for that command at this FR's base: `description`; `argument-hint` when present; and `model`, `effort`, `allowed-tools` when present.
  - Keys appear in the order `COMMAND_META` lists them. Values are written in the form `generate_commands` emits them today: `description` and `argument-hint` double-quoted, the others bare.
  - The body after the blank line is byte-identical to the whole file at this FR's base.

  Verified per file against `git show <base>:template/.agent-team/commands/<name>.md` and the base's `COMMAND_META`.

- **AC-3:** **`generate_commands` reads each source's own frontmatter; `COMMAND_META` is deleted.** For each `<name>.md` under `.agent-team/commands/`:
  - **Source opens with a well-formed block:** the generator parses it and strips it, with the blank line that follows, from the body. It renders the wrapper frontmatter from the block's keys with today's rendering rules: same key order, same quoting, `model`/`effort`/`allowed-tools` only in the `.claude` variant, then the banner, a blank line, and the body (`$ARGUMENTS` becomes `{{args}}` in the `.cursor` variant). The source's own block never appears in a wrapper body.
  - **Source does not start with `---`:** the generator behaves exactly as it does today for a name absent from `COMMAND_META`. The description is `Run the <name> command.`, there is no argument hint, and the whole file is the body.

  `COMMAND_META` no longer exists in `scripts/bootstrap.py`, and no other code path in the hub reads per-command metadata. `generate_commands(target: Path) -> int` keeps its signature and return value, the number of commands generated. Verified with a source carrying each key combination the template uses (see AC-4) and with a source that has no block.

- **AC-4:** **The migration is lossless: the template's wrappers regenerate byte-identical.** Running `generate_commands` over a copy of `template/` after this FR produces, for all 22 wrapper paths (11 commands × 2 harnesses), bytes identical to the wrappers committed at this FR's base. Those are LF, per FR-0012 AC-9. So this FR's diff to `template/.claude/commands/` and `template/.cursor/commands/` is empty. Verified by regenerating into a temporary copy and comparing to `git show <base>:<path>` for all 22 paths. The four metadata shapes the template uses must all round-trip:
  - description + hint (`architect`);
  - description + hint + `model` + `effort` (`developer`, `reviewer`);
  - description + hint + `model` + `effort` + `allowed-tools` (`docs`);
  - the DEC-0013 `gate-review` entry.

- **AC-5:** **A malformed block is refused per command; an unknown key is ignored with a warning.**
  - **Malformed block:** the source's first line is `---` and any of the following holds:
    - no closing `---` exists;
    - the block is not a mapping;
    - a value is not a single-line string;
    - a `description` or `argument-hint` value contains `"`.

    Then `generate_commands` prints one warn line naming the file and the cause. It writes neither wrapper for that command, and any existing wrapper is left byte-for-byte untouched. It does not count the command and continues with the others.
  - **Unknown key:** a key outside {`description`, `argument-hint`, `model`, `effort`, `allowed-tools`} gets one warn line naming the file and the key. The key is ignored and the wrappers are generated.
  - **Exit code:** `bootstrap.py`'s exit code is unchanged in both cases.

  Verified per case in a temporary tree.

- **AC-6:** **Existing behaviour is preserved.**
  - Every FR-0001 test in `tests/unit/scripts/test_bootstrap_profiles.py` passes unedited.
  - `bootstrap.py`'s create and `--upgrade` flows, prompts and summary lines are unchanged apart from AC-1's line endings and AC-5's new warn lines.
  - `hub-index.py` is not edited.
  - Every template test that passed before this FR still passes, except the test ids DEC-0016 names. Each of those changes only as DEC-0016 bounds it and still pins what it pinned.

## Out of scope

- `--upgrade`'s handling of project-specialised files, the added-file provenance reminder, and `.gitattributes`: **FR-0020**, which depends on this FR.
- `scripts/hub-index.py`, which already writes LF (L502, L514).
- `template/scripts/dispatch.py`'s own unguarded `write_text` calls, including `_flip_frontmatter_to_merged`, which committed FR-0006 and FR-0009 as CRLF: **FR-0016**.
- Normalising the 54 CRLF files already committed in the hub index. That is a post-merge chore on `main` (Notes), not part of this FR's branch.
- A hub-root `.gitattributes`.
- Changing any command's body text. FR-0022 does that after this FR.
- `yaml.safe_dump` reflowing long titles in `write_idea` / `write_pattern` (pre-existing; not a line-ending defect).

## Open questions

- **Q:** Should the metadata live in a sidecar (`template/.agent-team/commands/_meta.yaml`) instead of per-file frontmatter? That would avoid DEC-0016's test cascade.
  - **Default:** Per-file frontmatter. DEC-0013's `alternatives` name it. It is the form both harnesses already read, so the metadata lives with the command it describes. A single sidecar would be one more shared file that every command FR edits: the same growth problem, relocated. The cascade is paid once, and DEC-0016 re-anchors FR-0012 AC-10 so that later command FRs stop paying it.
- **Q:** Should `COMMAND_META` survive as a fallback for sources without frontmatter?
  - **Default:** No. `--upgrade` syncs `.agent-team/commands/` (it is in `INFRA_DIRS`) before it regenerates, so template sources always arrive with their block. The only sources without one are these two, and each gets today's unknown-name fallback, visible in the wrapper:
    - a project's own new command;
    - a template source the operator declined to sync in interactive mode.
- **Q:** Should the one-shot normalisation of the hub's 54 CRLF files ride this FR's branch?
  - **Default:** No. It would bury the reviewable diff under whole-file flips of IDEA files. The Orchestrator runs it on `main` after merge (Notes).

## Dependencies

- **FR-0007**: the LF convention and test technique this FR extends to the hub scripts.
- **FR-0012**: AC-9 (wrappers equal generator output) and AC-10 ("nothing else changed" residual check). DEC-0016 revises both: the wrapper body is the source body after its own frontmatter, and AC-10's residual check is anchored to FR-0012's merge commit `f037978` rather than the live sources.
- **FR-0008 / DEC-0013**: the `gate-review` `COMMAND_META` key moves into `gate-review.md`'s frontmatter. DEC-0013's one-key bound is consumed and nothing reaches past it.

## Notes

- **Human approval (hub `CLAUDE.md`).** `scripts/bootstrap.py`, `parking.py` and `patterns.py` are hub scripts, and `template/.agent-team/**` and `template/.claude/commands/**` are protected. This FR is dispatched in maintainer (`mnt`) mode with the `owns:` above as its write surface. **It must not be dispatched until Neil has approved it and the approval is recorded in the Changelog.** Wave 1's maintainer approvals do not carry over. Edit `../../scripts/**` and `../../template/**`, never this project's bootstrap-output copies.
- **Tests live at the hub root.** New hub-script tests go in `../../tests/unit/scripts/` (AGENTS.md §2). Follow `test_bootstrap_profiles.py`'s pattern for each module under test:
  - load it with `importlib.util.spec_from_file_location` (required for `hub-index.py` because of the hyphen);
  - put `scripts/` on `sys.path` for `_console`;
  - monkeypatch **every** root-derived module constant (`HUB_ROOT`, `PARKING_DIR`, `INDEX_PATH`, `PATTERNS_DIR`, `HUB_INDEX_PATH`, `TEMPLATE_ROOT`, `PROFILES_ROOT`, …) to a `tmp_path` tree. Patching `HUB_ROOT` alone is not enough, because the others are computed at import.

  Run with `python -m pytest tests/` from the hub root. Hub CI does not run pytest; the Reviewer states per-AC coverage in the PR body (AGENTS.md §2). DEC-0016's cascade edits are template tests and use the ride-along `# covers hub-tooling FR-0019:AC-N` form, as `test_headless_conduct.py` already does.
- **Reviewer dogfood: never against the live hub (mandatory).** `parking.py`, `patterns.py`, `hub-index.py` and `bootstrap.py` all root themselves at `Path(__file__).resolve().parent.parent`. Running them in place writes the live parking lot and registry. The Reviewer works on a temporary copy of the hub:
  1. Record `git -C <hub> status --porcelain -- parking-lot patterns hub projects` before starting.
  2. Copy `scripts/` (including `_console.py`), `parking-lot/`, `patterns/`, `hub/`, `template/` and `profiles/` into a short temp path such as `%LOCALAPPDATA%\Temp\claude\fr19\hub\`. Use real copies, not symlinks: `.resolve()` follows a symlink back to the live hub.
  3. Run the **copied** scripts:
     - `python <tmp>/hub/scripts/parking.py reindex` and `patterns.py reindex`: confirm no `\r` in any output;
     - `hub-index.py --allow-shrink`: its shrink guard refuses a copy whose index lists FRs the copy lacks.
  4. Bootstrap a throwaway with the copied `bootstrap.py`, always with an explicit path and `--no-register`. Never use a bare name, which lands in the live `projects/`. Never name it after a registered project (`pm-graph-poc`, `Project B`, `Project A`, `hub-tooling`): `--upgrade`'s registry name-fallback would read or write the live registry entry.
  5. Run `--upgrade <tmp>/proj --yes` twice. Confirm the wrappers are LF and the second run reports nothing updated.
  6. Run the throwaway's `scripts/index-specs.py --validate` and `scripts/deploy-gate.py` (AGENTS.md §3).
  7. Re-run the `git status --porcelain` from step 1. It must be identical. Delete the temp tree.
- **Bite check.** Load `git show <base>:scripts/bootstrap.py` as a second module and show AC-3 and AC-4's tests fail against it: it has no frontmatter parse, and against frontmatter-bearing sources it would emit the block inside the body.
- **Post-merge chore (Orchestrator, on `main`, not this branch).** Normalise the hub's committed CRLF files in one `chore(hub): normalise line endings (FR-0019)` commit:
  - `parking-lot/INDEX.md` and the CRLF IDEA files;
  - `hub/projects.yaml`, where FR-0001's registration append currently mixes an LF line into a CRLF file;
  - hub-tooling's 22 wrappers (the next `--upgrade projects/hub-tooling --yes` regenerates them LF);
  - `projects/hub-tooling/specs/FR-0006-*.md` and `FR-0009-*.md`.

  Verify the result with `git diff -w --stat`, which should be empty.
- **Downstream.** Lane C's FR-0022 edits command bodies and regenerates wrappers, so it runs after this FR merges. It relies on the LF generator and on DEC-0016's AC-10 re-anchoring. FR-0020 depends on this FR: the same file, and the 22-wrapper "Updated" noise must be gone before its added-file report is legible.

## Changelog

- 2026-09-25: created from IDEA-0063 (with the per-command frontmatter half of the Orchestrator's single-`bootstrap.py`-FR request); companion decision DEC-0016 (revises FR-0012, proposed). Awaiting Neil's approval of the hub-script edit before dispatch.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified this FR's `neil`-tier DECs. No normative change.
