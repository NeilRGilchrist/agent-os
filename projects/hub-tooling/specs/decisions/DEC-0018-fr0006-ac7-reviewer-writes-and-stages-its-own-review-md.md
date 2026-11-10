---
id: DEC-0018
title: "FR-0006 AC-7's reviewer command tells the Reviewer to write and stage its own `REVIEW.md` — the dispatcher keeps it and synthesises one only when absent — instead of \"the dispatcher records it as `REVIEW.md`; do not write `REVIEW.md`\""
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0013, FR-0022]
revises: FR-0006
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave the sentence; the dispatcher keeps a Reviewer-written REVIEW.md anyway, so the wrong advice is harmless"
  - "Say nothing about REVIEW.md in the command and let the role file carry it"
  - "Fold the change into DEC-0001 retroactively"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  DEC-0001 made the Reviewer's own committed REVIEW.md the artifact of record
  and rejected "stop the Reviewer writing REVIEW.md at all"; FR-0013 AC-2
  implemented it. FR-0006 AC-7 still requires the reviewer command to say the
  dispatcher "records it as REVIEW.md". The command says "do not write
  REVIEW.md", and a test pins both phrases. So every dispatched Reviewer is told
  not to produce the artifact the dispatcher now preserves and FR-0008's
  gate-evidence model reads. The owed follow-up is recorded in FR-0013's Notes;
  DEC-0001's cascade missed it.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0018: The reviewer command asks for the Reviewer's own `REVIEW.md`

## Context

FR-0006 AC-7 requires `template/.agent-team/commands/reviewer.md`'s dispatcher-configured branch to say that "the final assistant message is the verdict of record — the dispatcher posts it to the PR and records it as `REVIEW.md`". The command implements that as "…records it on your branch as `REVIEW.md` — do not write `REVIEW.md` or post the review yourself…" (`reviewer.md` L42). `test_dispatch_finalize.py::test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path` (L673-691) pins both phrases.

DEC-0001, ratified by Neil on 2026-09-20, flipped FR-0006 AC-6. The Reviewer's own staged or committed `REVIEW.md` is kept byte-for-byte, and one is synthesised from the final message only when none exists. DEC-0001 explicitly rejected "have the Reviewer stop writing `REVIEW.md` at all". FR-0013 AC-2 implemented it. The command still tells every dispatched Reviewer not to write the file. The command's own headless-conduct block (L7) meanwhile names "`REVIEW.md` for the Reviewer" as the handoff artifact for `## ESCALATION` blocks. Two instructions in one file therefore contradict each other. FR-0013's Notes (2026-09-21) recorded this follow-up as owed by the Architect after FR-0013 merged: a breaking DEC on FR-0006 AC-7, with the command text and the pinning test in one cascade. FR-0012 AC-8 repeats the stale clause and is revised separately by DEC-0019 (ADR-0001 rule 7: one `revises` target per DEC).

## Decision

1. **FR-0006 AC-7's reviewer sentence is amended.** The reviewer command's dispatcher-configured branch says, in substance:
   - the final assistant message is the verdict of record, and the dispatcher posts it to the PR;
   - the Reviewer writes its full review to `REVIEW.md` at the worktree root and stages it;
   - the dispatcher keeps a staged or committed `REVIEW.md` byte-for-byte and synthesises one from the final message only when the Reviewer wrote none (DEC-0001, FR-0013 AC-2).

   It no longer instructs the Reviewer to `git commit`, to post the review itself, or to set PR review state itself. The staging contract for tests, the developer-command half of AC-7, and both non-dispatcher branches are unchanged.

2. **AC-7's wrapper clause is refreshed.** "Differ from the sources only by the generated-file banner and frontmatter the renderer already adds" becomes "…the frontmatter `generate_commands` renders (from the source's own frontmatter block since FR-0019 and DEC-0016), and, for the Cursor variant, the `$ARGUMENTS` → `{{args}}` substitution". This is a wording refresh with no change in meaning.

3. **Implemented under FR-0022** (lane C, after FR-0019). FR-0022's `owns:` carries `reviewer.md`, its two wrappers and `test_dispatch_finalize.py`. The test file is there for the Reviewer only, bounded to the one test named in the Cascade.

**`breaking: true`** (ADR-0001 rule 4). The implementing command text and its pinning test must change. FR-0006 goes to `version: 3`, `revisions: [DEC-0001, DEC-0018]`, `last_breaking_revision: 3`. Rule 5 was checked: FR-0006's identity (the dispatcher owns the commit and the review artifact) is unchanged.

**Why `neil`.** It revises a merged control-plane FR's contract with every dispatched Reviewer, completing a decision (DEC-0001) Neil ratified. It is recorded `proposed` and is live now (ADR-0001 rule 8). It is ratified by Neil's approval of FR-0022.

## Alternatives considered

- **Leave the sentence; the dispatcher keeps a Reviewer-written file anyway.** Rejected. The command is how a Reviewer learns what to produce. An obedient Reviewer writes nothing, and the synthesised 3 KB final message replaces the full review DEC-0001 was written to protect (Project A L17). The advice is harmless only for agents that ignore it.
- **Say nothing in the command and let the role file carry it.** Rejected. FR-0006 AC-7 and FR-0012 AC-8 exist precisely so that the command states the handoff contract. The role file is read less reliably in headless runs.
- **Fold it into DEC-0001 retroactively.** Rejected. DEC-0001 is ratified and its cascade is closed. ADR-0001 rule 2 records a new change as a new DEC.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0006-dispatcher-owns-commit-and-rework-sync.md`, done in this commit:
  - AC-7 gains one sentence citing this DEC;
  - `version: 3`, `revisions` gains DEC-0018, `last_breaking_revision: 3`, `updated: 2026-09-25`;
  - one Changelog line.
- `template/.agent-team/commands/reviewer.md`: the dispatcher-configured verdict bullet (FR-0022 AC-2, **maintainer mode**). The bullet also stays within FR-0012 AC-8's constraints as revised by DEC-0019.
- `template/.claude/commands/reviewer.md` and `template/.cursor/commands/reviewer.md`: regenerated by `generate_commands` (FR-0022 AC-7).
- `template/tests/unit/scripts/test_dispatch_finalize.py::test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path`, FR-0022's Reviewer:
  - replace the two needles `records it on your branch as \`REVIEW.md\`` and `do not write \`REVIEW.md\`` with needles for Decision 1's three clauses (the Reviewer writes and stages `REVIEW.md`; the dispatcher keeps it; it synthesises one only when absent);
  - every other assertion is unchanged, including the dispatcher-line bans on `git commit` and "review state on the PR".
- No other FR-0006 test changes. `test_developer_command_states_the_staging_contract`, `test_verdict_headings_named_in_the_command_are_what_the_extractor_reads` and `test_template_wrappers_still_point_at_the_edited_sources` pass unedited.
- FR-0013: no change. It already implements the behaviour this sentence now describes.

## Changelog

- 2026-09-25: created (proposed) with FR-0022, discharging the follow-up recorded in FR-0013's Notes on 2026-09-21.
- 2026-09-25: ratified by Neil, with his approval of FR-0022.
