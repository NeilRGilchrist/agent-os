---
id: DEC-0033
title: "FR-0012 AC-8's no-dispatcher reviewer branch drops the `Approve` review-state instruction with FR-0030; AC-8's dispatcher-path restatement and its detector are unchanged"
tier: neil
status: proposed  # proposed | ratified | rejected | superseded — Neil ratifies by merging the PR that carries it (FR-0030's spec PR)
satisfies: []
constrained_by: [FR-0006, FR-0030]
revises: FR-0012
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Revise only FR-0006 AC-7 and leave FR-0012 AC-8's no-dispatcher clause"
  - "Keep the human-reviewer branch under a new heading outside the agent command"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0012 AC-8 says the no-dispatcher branch keeps its `Approve` review-state
  instruction for a human reviewer who is not the PR author. `/reviewer` is
  read by agents, which share the author's account, so the instruction is
  unfollowable. FR-0030 removes it. ADR-0001 rule 7 allows one `revises` per
  DEC, so this is DEC-0032's twin on FR-0012.
created: 2026-11-05
updated: 2026-11-05
---

# DEC-0033: FR-0012 AC-8's no-dispatcher branch drops the `Approve` review state

## Context

FR-0012 AC-8 (v4, DEC-0019, merged) restates the review contract. Its third sentence says: "The existing dispatcher-configured / no-dispatcher split in `reviewer.md` is preserved: the no-dispatcher branch keeps its `Approve` review-state instruction, which is the case where a human reviewer is not the PR author."

`test_headless_conduct.py::test_reviewer_no_dispatcher_branch_keeps_the_approve_review_state_for_a_human_reviewer` pins that line.

FR-0030 AC-1 removes the review-state contract from every reviewer document. A human reviewer does not run the agent command to approve a PR. An agent that runs it authenticates as the PR's author, and GitHub refuses the state.

## Decision

1. **AC-8's third sentence is amended.** It now reads: "The existing dispatcher-configured / no-dispatcher split in `reviewer.md` is preserved. The no-dispatcher branch records the verdict and review in a committed `REVIEW.md` and may post it as a plain comment. It sets no review state (FR-0030 AC-1, DEC-0032)."

2. **The rest of AC-8 is unchanged:**
   - the dispatcher-path parenthesis as DEC-0019 left it;
   - no agent sets a GitHub approval state on the owner's own PR;
   - a self-review is downgraded to a comment;
   - the human merges.

3. **The pinning detectors are unchanged:** `_ac8_gaps`, `test_neither_file_instructs_an_agent_to_set_an_approval_state_on_the_owners_pr` and `test_pre_fr_verdict_bullet_fails_the_ac8_detector_and_the_new_one_extends_it`. FR-0030 keeps the dispatcher verdict bullet byte-identical and must pass them unedited.

4. **AC-10 is unaffected.** DEC-0016 anchors its residual check to `f037978`. The hand-off line `5. Hand off: tell the user the PR is approved and ready for human merge.` still survives at HEAD.

**`breaking: true`.** A pinning test changes. FR-0012 goes to `version: 5`, with `revisions` gaining DEC-0033 and `last_breaking_revision: 5`. Rule 5 was checked: identity unchanged.

**Why `neil`.** The same reasons as DEC-0032, of which this is the twin. It is recorded `proposed`, and Neil ratifies it by merging the PR that carries it.

## Alternatives considered

- **Revise only FR-0006 AC-7.** Rejected. AC-8's text and its test would still require the instruction, so FR-0030 could not satisfy both FRs.
- **Move the human-reviewer branch out of the agent command.** Rejected. No template document is addressed to a human reviewer, and adding one is not FR-0030's scope.

## Cascade

Breaking. Every affected artifact:

- **`projects/hub-tooling/specs/FR-0012-headless-conduct-contract-in-role-commands.md`**, done in this commit:
  - AC-8 gains one sentence citing this DEC;
  - `version: 5`, `revisions` gains DEC-0033, `last_breaking_revision: 5`;
  - one Changelog line.
- **`template/.agent-team/commands/reviewer.md`** and its two wrappers: the no-dispatcher verdict bullet. Implemented by FR-0030 AC-1.
- **`template/tests/unit/scripts/test_headless_conduct.py::test_reviewer_no_dispatcher_branch_keeps_the_approve_review_state_for_a_human_reviewer`**, FR-0030's Reviewer: it is retargeted to pin the new bullet, and keeps its assertion on the hand-off line. It may be renamed.
- **No other FR-0012 test changes.**

## Changelog

- 2026-11-05: created (proposed) with FR-0030, at Neil's request, before the spec PR's push.
