---
id: DEC-0016
title: "FR-0012 AC-9's wrapper body is the source body after the source's own frontmatter block, and AC-10's \"nothing else changed\" residual check is anchored to FR-0012's merge commit `f037978`, not to the live sources"
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0008, FR-0019]
revises: FR-0012
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep command metadata in a sidecar file so the sources never gain frontmatter and no FR-0012 test moves"
  - "Extend AC-10's residual check with a permitted-edit list for the frontmatter block, as DEC-0012 item 2(g) did for FR-0008's orchestrator block"
  - "Drop AC-10's residual test entirely"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0019 moves each command's wrapper metadata out of the hub script's
  COMMAND_META and into a frontmatter block at the top of the command source.
  FR-0012's tests read "the source" as the whole file, so every wrapper-body
  comparison and every AC-10 residual diff goes red on a change that alters no
  instruction. AC-10 was always a statement about FR-0012's own diff, yet its
  test compares against HEAD. That makes it a perpetual freeze on five command
  files that every later command FR must buy its way past: DEC-0012 already
  did so once, FR-0019 would be second, FR-0022 third. Anchoring it to
  FR-0012's merge commit restores what it asserts and ends the tax.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0016: FR-0012's wrapper body follows the source's own frontmatter; AC-10 anchors to FR-0012's merge

## Context

FR-0019 (IDEA-0063) makes each of the 11 canonical command sources under `template/.agent-team/commands/` open with its own YAML frontmatter block. That block carries the `description` / `argument-hint` / `model` / `effort` / `allowed-tools` metadata that `scripts/bootstrap.py::COMMAND_META` holds today. `generate_commands` then renders the wrapper frontmatter from it and strips it from the body. DEC-0013's `alternatives` named this fix. The generated wrappers come out byte-identical to today's (FR-0019 AC-4).

Two FR-0012 statements, and the tests that implement them, assume the source *is* the body:
- **AC-9:** "each wrapper differs from its source only by the generated-file banner, the frontmatter block `generate_commands` adds, and — for the Cursor variant — the `$ARGUMENTS` to `{{args}}` substitution." `test_headless_conduct.py::_wrapper_failures` implements it as `wrapper body == source.strip() + "\n"`. With a source frontmatter block, the block is not in the wrapper body, so every comparison fails.
- **AC-10:** "Apart from the added block, AC-8's restatement, and the regenerated wrapper frontmatter, the five sources are unchanged." `test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8` implements it by diffing **HEAD**'s five sources against the pre-FR ref `bd46dd3`. A statement about what FR-0012 changed became a freeze on every later change to those five files. FR-0008 already paid for this once (DEC-0012 item 2(g) widened the orchestrator expectation to nine lines). FR-0019's frontmatter lines would be the second payment, and FR-0022's craft-rule sections the third.

Only one commit has touched the command sources since FR-0012 merged at `f037978` (PR #5): `681d661` (FR-0008: seven lines in `orchestrator.md` and the new `gate-review.md`). So at `f037978` the sources are exactly FR-0012's result.

## Decision

1. **AC-9: the body is the source body after its own frontmatter.** A canonical source may open with a frontmatter block (FR-0019 AC-2). Each wrapper then differs from its source only by:
   - the frontmatter block, which `generate_commands` renders from the source's own block, or from its unknown-name fallback when there is none;
   - the generated-file banner;
   - for the Cursor variant, the `$ARGUMENTS` → `{{args}}` substitution.

   The wrapper body equals the source text after its frontmatter block and the one blank line that follows it. The "normalise `\r\n` before comparing" clause stays harmless but becomes moot once FR-0019 AC-1 makes the generator emit LF.

2. **AC-10 is a statement about FR-0012's own diff, and its residual check is anchored there.**
   - `test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8` and `test_any_other_changed_line_is_reported` compare the pre-FR ref `bd46dd3` against the five sources **at FR-0012's merge commit `f037978`** (`git show f037978:template/.agent-team/commands/<name>.md`), not against HEAD. Both still skip where that object is unreachable, as they do today inside bootstrapped projects.
   - At `f037978` the orchestrator residual is the two-line AC-8 insert. DEC-0012 item 2(g)'s nine-line expectation, which exists only because FR-0008's block arrived later, is withdrawn from this test. The other four residuals are as the test states them today.
   - `test_named_existing_instructions_survive_verbatim` **stays on HEAD**. The named instructions (the staging contract, the maintainer footprint rules, the backfill prohibitions, the orchestrator's wave-first default and hard limits) must keep surviving in later FRs. A later FR that must remove one needs its own DEC.
   - The conduct-block identity pins are unchanged and stay on HEAD: AC-1's `_CORE_SHA256` and `_REVIEWER_SHA256`, the placement before the first numbered step, and the AC-7 exclusivity checks. They are invariants, not diffs.

3. **The tests change as bounded here, by FR-0019's Reviewer only.** FR-0019's `owns:` carries both test files for this purpose and no other. Each changed test keeps pinning what it pinned.

**`breaking: true`** (ADR-0001 rule 4). `generate_commands` and the named tests must change. FR-0012 goes to `version: 3`, with `revisions: [DEC-0004, DEC-0016]` and `last_breaking_revision: 3`. Rule 5 was checked: FR-0012's identity, one headless-conduct contract in generated role commands, is unchanged.

**Why `neil`.** It revises a merged control-plane FR's guarantee, and it rides on a hub-script FR that Neil must approve anyway (hub `CLAUDE.md`). Recorded `proposed`. It is live now (ADR-0001 rule 8) and is ratified by Neil's approval of FR-0019.

## Alternatives considered

- **A sidecar metadata file (`commands/_meta.yaml`).** Rejected. It avoids this cascade once, but it recreates `COMMAND_META`'s problem in a new place: one shared file that every command FR edits. It also leaves AC-10's freeze in place for FR-0022 and every later command FR. See FR-0019's Open questions.
- **Extend the residual check with a permitted-edit list for the frontmatter block (DEC-0012's approach).** Rejected. It pays the tax again, and every later FR pays it once more. The test would accumulate a history of other FRs' edits.
- **Drop AC-10's residual test.** Rejected. As a statement about FR-0012's diff it is correct and cheap once anchored. The adversarial `test_any_other_changed_line_is_reported` shows the check has teeth.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0012-headless-conduct-contract-in-role-commands.md`, done in this commit:
  - AC-9 and AC-10 each gain one sentence citing this DEC;
  - `version: 3`, `revisions` gains DEC-0016, `last_breaking_revision: 3`, `updated: 2026-09-25`;
  - one Changelog line.
- `scripts/bootstrap.py::generate_commands` and `COMMAND_META`: FR-0019 AC-3, **maintainer mode**.
- `template/.agent-team/commands/*.md` (11 files, frontmatter only): FR-0019 AC-2.
- `template/tests/unit/scripts/test_headless_conduct.py`, FR-0019's Reviewer:
  - `_wrapper_failures`: the expected body is the source after its leading frontmatter block, if any. This carries `test_every_canonical_command_has_both_wrappers_in_generated_form`, `test_a_hand_edited_wrapper_fails_both_checks`, `test_a_missing_wrapper_and_a_stale_stub_wrapper_fail` and `test_a_crlf_wrapper_is_reported_even_when_its_content_matches`. Their assertions do not change.
  - `test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8[developer|reviewer|maintainer|reviewer-backfill|orchestrator]`: the head side reads `f037978`. The orchestrator branch expects the two-line AC-8 insert, and the seven-line FR-0008 block assertion is removed (Decision 2).
  - `test_any_other_changed_line_is_reported`: the untampered `head` is `f037978`'s `maintainer.md`. The tamper-and-detect assertion is unchanged.
  - Docstrings that name `COMMAND_META` may say "the source's frontmatter" in the same edit.
- `template/tests/unit/scripts/test_dispatch_gates.py::test_both_gate_review_wrappers_are_generator_output_with_the_dec0013_frontmatter[.claude|.cursor]`, FR-0019's Reviewer: the expected body is `gate-review.md` after its frontmatter block. The description and argument-hint pins are unchanged. FR-0008 AC-12's text ("differ from the sources only by the generated-file banner and frontmatter") still holds, so FR-0008 is not revised.
- No other test changes. In particular `test_committed_wrappers_equal_generate_commands_output_after_lf_normalisation`, `test_cursor_wrapper_differs_from_claude_only_by_claude_only_keys_and_args`, `test_docs_wrapper_carries_the_claude_only_keys_from_command_meta` and every AC-1 to AC-8 test pass unedited, because the wrappers are byte-identical (FR-0019 AC-4).
- FR-0006 AC-7's wrapper clause ("frontmatter the renderer already adds") stays true in substance. Its wording is refreshed by DEC-0018, which revises AC-7 for FR-0022.
- Downstream: FR-0022 (lane C) relies on Decision 2. Its new sections in `developer.md`, `reviewer.md` and `orchestrator.md` no longer trip the residual check.

## Changelog

- 2026-09-25: created (proposed), with FR-0019, in the wave-2 Architect drafting session.
- 2026-09-25: ratified by Neil, with his approval of FR-0019.
