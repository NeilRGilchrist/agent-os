---
id: FR-0007
title: Generated spec artifacts are written with LF line endings on every platform
status: merged
owner: architect
depends_on: []
tags: [template, windows, cross-platform, indexer]
# Footprint is expressed as HUB-relative paths under template/ (see Notes):
# the code under change lives in the hub's template, not in this project's src/.
owns:
  - template/scripts/index-specs.py
  - template/scripts/deploy-gate.py
  - template/scripts/escalation-log.py
  - template/scripts/render-docs.py
  - template/tests/unit/scripts/test_line_endings.py
reads:
  - template/scripts/metrics_log.py
  - template/.github/workflows/agent-gates.yml
  - scripts/hub-index.py
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
serves_roles: []
solution_space:
  open:
    - Whether the fix is `newline="\n"` at each `write_text` / `open` call or one shared `_write_lf(path, text)` helper per script. Scripts must stay single-file (no shared module import between them — they ride into bootstrapped projects individually).
  fixed:
    - "No change to the rendered content: byte-for-byte identical to today's Linux output."
    - No `.gitattributes` `eol=` policy is added by this FR; the fix lives in the writer so it holds regardless of checkout configuration.
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-13
updated: 2026-09-13
---

# FR-0007: Generated spec artifacts are written with LF line endings on every platform

## Why

A push from Windows on 2026-09-13 failed the template's `agent-gates.yml` "spec index is up to date" check. `index-specs.py` writes `specs/INDEX.md` with `Path.write_text(..., encoding="utf-8")`, which uses platform newline translation, so on Windows it emits `\r\n`. CI regenerates the index on Linux with `\n`, `git status --porcelain specs/INDEX.md` reports the file as modified, and all 78 lines show as changed even though their content is identical. The same writer pattern is used for `CODEOWNERS` (index-specs.py), the INDEX rewrite inside `deploy-gate.py`, `.agent-team/escalation-log.md` (escalation-log.py), and the rendered client docs, render stamp and gaps file (render-docs.py) — every one of them a regenerable artifact that is committed and diffed. `metrics_log.py` (FR-0002) and the hub's `hub-index.py` (FR-0001) already open with `newline="\n"` for exactly this reason; the older writers never caught up. The hub's working agreement promises native Windows support for all scripts, and a CI check that fails for every Windows contributor on every regeneration breaks that promise.

## What

After this FR lands, every file the template scripts generate or rewrite — `specs/INDEX.md`, `CODEOWNERS`, `.agent-team/escalation-log.md`, `docs/client/*.md`, the render stamp and the gaps file — is written with `\n` line endings on Windows, macOS and Linux alike, so a regeneration on any platform is byte-identical to CI's, and a guard test keeps it that way.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **`index-specs.py` writes LF.** Running `python scripts/index-specs.py` on any platform produces a `specs/INDEX.md` whose bytes contain no `\r`; when `.agent-team/codeowners-config.yaml` is present the written `CODEOWNERS` likewise contains no `\r`. On a platform whose `os.linesep` is `\r\n` the output is byte-identical to the output on a platform whose `os.linesep` is `\n`. Verified by monkeypatching the writer environment (or asserting on bytes) in a temporary repository; no reliance on the CI runner's OS.

- **AC-2:** **`deploy-gate.py` writes the same bytes as `index-specs.py`.** The INDEX rewrite inside `deploy-gate.py` (skipped under `--status-only`, unchanged) produces bytes identical to AC-1's for the same spec tree; in particular it contains no `\r`. Verified by running both against one fixture and comparing bytes.

- **AC-3:** **`escalation-log.py` and `render-docs.py` write LF.** `escalation-log.py append` and `resolve` (including the header-creation path) and `render-docs.py` (rendered docs, `RENDER_STAMP`, `GAPS_PATH`) produce files with no `\r` on any platform. Content is otherwise byte-identical to today's Linux output.

- **AC-4:** **A guard test fails on regression.** `template/tests/unit/scripts/test_line_endings.py` exercises each writer named in AC-1 to AC-3 against a fixture under a temporary directory and asserts no `\r` in the written bytes. The test runs on every platform (it must not be skipped on Windows) and passes on Linux CI both before and after the change, so its value is on Windows.

- **AC-5:** **Existing files are not rewritten unnecessarily.** Running `index-specs.py` twice in a row on a clean tree leaves `git status --porcelain specs/INDEX.md` empty on every platform; the CI check in `template/.github/workflows/agent-gates.yml` is unchanged and passes for an index regenerated on Windows.

## Out of scope

- The hub-level scripts `scripts/parking.py`, `scripts/patterns.py` and `scripts/bootstrap.py`, which use the same `write_text` pattern for parking-lot files, pattern files, `AGENTS.md`, rendered command wrappers and the CI workflow. Same defect class, different approval scope (hub scripts); file as a follow-up hub-tooling FR or fold into IDEA-0034's reverse leg.
- Adding `* text=auto eol=lf` to `template/.gitattributes` or the hub's `.gitattributes`. A checkout-side policy would mask the writer defect rather than fix it; revisit if a second artifact class needs it.
- Normalising line endings of files agents write by hand (`PR_BODY.md`, `REVIEW.md`, spec files). Those are authored, not generated.
- Any change to what the generated files contain.

## Open questions

- **Q:** Should `index-specs.py` also *read* with universal newlines so a CRLF-checked-out spec file hashes the same as its LF twin (`--ac-hashes`)?
  - **Default:** Not in this FR. `read_text` already applies universal-newline translation on read, so hashes are computed over `\n` text today; leave it and add a test only if a CRLF fixture proves otherwise.

## Dependencies

None.

## Notes

- Footprint paths are hub-relative under `template/`. `template/scripts/{deploy-gate.py,index-specs.py}` are human-approval files; this FR is dispatched in maintainer (`mnt`) mode with the `owns:` above as the write surface, and the human's approval of this FR is the approval for those edits.
- Precedent to copy: `template/scripts/metrics_log.py` (`path.open("a", encoding="utf-8", newline="\n")`) and `scripts/hub-index.py` (`write_text(..., encoding="utf-8", newline="\n")`; `Path.write_text` accepts `newline` from Python 3.10, and the template requires 3.11+).
- Write sites today: `index-specs.py` lines ~1965 and ~1983; `deploy-gate.py` ~299; `escalation-log.py` 55, 63, 94; `render-docs.py` 482, 486, 492. Line numbers are as of 2026-09-13 and will drift.
- Reviewer dogfood step (AGENTS.md) applies: bootstrap a throwaway project from the modified template and run its `index-specs.py` and `deploy-gate.py`; on Windows, assert the resulting `specs/INDEX.md` has no `\r`.

## Changelog

- 2026-09-13: created — Windows CRLF push failure against `agent-gates.yml` "spec index is up to date"
