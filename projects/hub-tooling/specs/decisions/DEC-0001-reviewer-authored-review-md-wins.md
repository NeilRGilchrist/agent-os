---
id: DEC-0001
title: The Reviewer's own committed REVIEW.md is the artifact of record; finalize synthesises one only when none is present
tier: neil
status: ratified  # proposed | ratified | rejected | superseded — ratified by Neil 2026-09-20 (commit 49b3e13); token corrected from the ADR-vocabulary `accepted` on 2026-09-21, decision unchanged
satisfies: []
constrained_by: []
revises: FR-0006
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep FR-0006 AC-6's always-overwrite and have the Reviewer stop writing REVIEW.md at all"
  - "Write the synthesised body to a second path (REVIEW.dispatch.md) and leave the agent's file alone"
  - "Append the synthesised body to the agent's REVIEW.md instead of replacing it"
  - "Supersede FR-0006 with a new FR rather than revising it"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0006 AC-6 chose always-overwrite to guarantee the rework precondition
  (a committed REVIEW.md on the Reviewer branch) was met without relying on
  agent compliance. The Project A FR-0001 wave showed the cost of the guarantee:
  the Reviewer's own 11 KB round-1 review — verified-passing list, nits,
  findings, knowledge-base candidates — was overwritten by the 3 KB final
  message, and had to be rescued by hand. The precondition is satisfiable
  without destroying anything: synthesise only when the branch carries no
  REVIEW.md, which is exactly the case the guarantee was built for.
created: 2026-09-20
updated: 2026-09-21
---

# DEC-0001: The Reviewer's own committed REVIEW.md is the artifact of record

## Context

FR-0006 AC-6 made the dispatcher write the review body it posts to GitHub to `REVIEW.md` at the root of the Reviewer worktree, "overwriting any existing file", and commit it on `claude/rev-<FR>` before the push. Its Open question recorded the choice explicitly: *"Should the dispatcher-authored `REVIEW.md` defer to a `REVIEW.md` the Reviewer wrote and staged itself, or always overwrite?" — Default: always overwrite. The Reviewer's final message is the verdict of record; two sources of truth for the same round is how the current inconsistency arose.* The reasoning was sound for the failure it was fixing: `_prepare_dev_worktree_for_rework` requires a committed `REVIEW.md`, no role file or command ever asked for one, and the Orchestrator had been placing it by hand.

The Project A FR-0001 wave on 2026-09-20 ran the other failure. The round-1 Reviewer wrote a substantial `REVIEW.md` of its own — roughly 11 KB carrying the per-AC verified-passing list, three defects with `file:line`, nits, findings routed to the Architect and the human, and knowledge-base candidates. `finalize --role rev` replaced it with the ~3 KB final assistant message and committed that. The Orchestrator noticed and preserved the original at `_dispatch/FR-0001.rev.REVIEW-round1-full.md`, which is gitignored (learnings L17). Nothing in the branch history carries the full text. FR-0008's gate-evidence model reads committed review artifacts, so the loss is not only archival.

The constraint that made this non-obvious is that the two artifacts are not redundant. The final assistant message is what GitHub receives and what the verdict is extracted from; the agent's `REVIEW.md` is the fuller working document it wrote while reviewing. FR-0006 treated them as duplicates of one thing. They are two things with one filename.

## Decision

`finalize --role rev` keeps a `REVIEW.md` the Reviewer staged or committed in its worktree and synthesises one from the posted body only when the branch carries none. The rework precondition is unchanged and still guaranteed: after finalize, `claude/rev-<FR>` always has a committed `REVIEW.md`, by one route or the other. The verdict of record is unchanged: it still comes from the Reviewer's final message (or, once FR-0013 lands, from `--verdict-file`), and it is still what is posted to the PR.

`breaking: true`. `template/scripts/dispatch.py::_materialise_review_md` implements the overwrite today and must change; the FR-0006 finalize tests assert it. FR-0006 goes to `version: 2` with `last_breaking_revision: 2`, and FR-0006 AC-6's normative sentence and its Open question are amended to state the new rule.

`tier: neil`: FR-0006 is a merged control-plane FR and this revision changes behaviour a human already approved. Recorded `proposed` pending Neil's ratification; per ADR-0001 rule 8 a proposed DEC is live, so FR-0013 may implement it.

## Alternatives considered

- **Keep always-overwrite and stop the Reviewer writing `REVIEW.md` at all.** Rejected: the reviewer command already tells the dispatcher-configured Reviewer not to write one (FR-0006 AC-7), and an opus Reviewer wrote a better one anyway. Instructing a capable agent not to produce its best artifact to protect a mechanism is backwards; the mechanism is the cheaper thing to change.
- **Write the synthesised body to a second path (`REVIEW.dispatch.md`).** Rejected: it creates the two-sources-of-truth state FR-0006's Open question was right to avoid, and every consumer — the rework precondition, `_read_review_md_on_branch`, FR-0008's evidence reader — would have to learn which file to prefer.
- **Append the synthesised body to the agent's `REVIEW.md`.** Rejected: the posted body is usually a summary of the file it would be appended to, so the artifact becomes self-duplicating, and a re-run of finalize appends again.
- **Supersede FR-0006 with a new FR.** Rejected under ADR-0001 rule 5: FR-0006's identity — the need for the dispatcher to own the commit, refuse empty finalization, materialise the review artifact and keep role branches in sync — is unchanged. One AC's default flipped. That is a revision.

## Cascade

- `template/scripts/dispatch.py::_materialise_review_md` — must check the Reviewer branch and worktree for an existing `REVIEW.md` (staged or committed) and skip the write when one is present; the `@implements FR-0006:AC-6` annotation stays and moves to the new logic. Implemented by **FR-0013:AC-2**.
- `template/tests/unit/scripts/test_dispatch_finalize.py` — the `@covers FR-0006:AC-6` test asserting overwrite must be re-pointed at the new rule and gain the "agent wrote one" case. Landed by FR-0013's Reviewer phase.
- `projects/hub-tooling/specs/FR-0006-dispatcher-owns-commit-and-rework-sync.md` — AC-6 sentence and the first Open question amended; `version: 2`, `revisions: [DEC-0001]`, `last_breaking_revision: 2`. Done in this commit.
- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md` — the implementer; `extends: [FR-0006]`, AC-2 carries the new rule.
- No other object cites FR-0006 AC-6. FR-0008 (`extends: [FR-0006]`, `depends_on: [FR-0006]`) reads committed review artifacts as gate evidence and is strictly better off; no change required there.

## Changelog

- 2026-09-20: created (proposed) — from IDEA-0067, Project A `_dispatch/learnings-FR-0001-wave.md` L17
- 2026-09-20: ratified by Neil (commit `49b3e13`); recorded with the ADR-style token `accepted`
- 2026-09-21: status token corrected `accepted` -> `ratified` (DEC vocabulary is `proposed | ratified | rejected | superseded`); decision unchanged
