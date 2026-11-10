---
id: DEC-0032
title: "FR-0006 AC-7's no-dispatcher reviewer branch changes with FR-0030: it records the verdict and review in a committed `REVIEW.md` and may post it as a plain comment, instead of setting an `Approve` review state"
tier: neil
status: proposed  # proposed | ratified | rejected | superseded — Neil ratifies by merging the PR that carries it (FR-0030's spec PR)
satisfies: []
constrained_by: [FR-0025, FR-0030]
revises: FR-0006
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep AC-7's 'non-dispatcher branches unchanged' and leave the `Approve` review-state instruction in the reviewer command"
  - "Supersede FR-0006 with a new FR"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0006 AC-7 says the non-dispatcher branches of the developer and reviewer
  commands are unchanged, which pins the reviewer's "use `Approve` review
  state on the PR" line. `/reviewer` is an agent command, and every agent
  authenticates as the account that authored the PR, so GitHub refuses that
  state and nothing reads it. FR-0030 removes it, so AC-7 must stop pinning it.
created: 2026-11-05
updated: 2026-11-05
---

# DEC-0032: FR-0006 AC-7's no-dispatcher reviewer branch sets no review state

## Context

FR-0006 AC-7 (v4, merged) states the staging contract for `developer.md` and `reviewer.md`. It ends: "The non-dispatcher branches of both commands are unchanged." DEC-0018 later revised the dispatcher-configured branch of `reviewer.md` but left the non-dispatcher one. That branch still says "use `Approve` review state on the PR … This branch is for a human reviewer who is not the PR's author."

`test_dispatch_finalize.py::test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path` implements AC-7. Its last assertion requires a line containing both `If no dispatcher` and `` `Approve` review state on the PR ``.

FR-0030 AC-1 removes the review-state contract from every reviewer document. It is the template half of ai-hub-poc's FR-0062 back-port (Wave 5 gap analysis, 2026-11-05). Neither branch of the command can set a review state that GitHub accepts. Nothing reads one: the deploy gate never queries GitHub, and `_resolve_rework_verdict` reads the Reviewer's text.

## Decision

1. **AC-7's last normative sentence is amended.** It now reads: "The developer command's non-dispatcher branch is unchanged. The reviewer command's non-dispatcher verdict bullet records the verdict and review in a committed `REVIEW.md`, opened with the `## Approve` or `## Request changes` heading, and may post it to the PR as a plain comment. It sets no review state (FR-0030 AC-1)." The rest of AC-7 stands:
   - the staging contract;
   - the dispatcher-configured branch as DEC-0018 left it;
   - the wrapper clause.

2. **The non-dispatcher staging line survives.** The reviewer command's `If no dispatcher` `git add tests/` / `git commit` line is kept (FR-0012 AC-10 names it).

**`breaking: true`.** A pinning test changes. FR-0006 goes to `version: 5`, with `revisions` gaining DEC-0032 and `last_breaking_revision: 5`. Rule 5 was checked: identity unchanged. The dispatcher still owns the commit and rework sync, and one sentence about one branch changed.

**Why `neil`.** FR-0006 is a merged control-plane FR, and this changes text a human approved. It is recorded `proposed`. Per ADR-0001 rule 8 it is live, so FR-0030 may implement it. Neil ratifies it by merging the PR that carries it.

## Alternatives considered

- **Keep AC-7's "unchanged" clause.** Rejected. FR-0030 could not remove the stale instruction without failing FR-0006's test, and the instruction cannot be followed by anyone who reads it.
- **Supersede FR-0006.** Rejected under ADR-0001 rule 5. One branch's wording changed; the need did not.

## Cascade

Breaking. Every affected artifact:

- **`projects/hub-tooling/specs/FR-0006-dispatcher-owns-commit-and-rework-sync.md`**, done in this commit:
  - AC-7 gains one sentence citing this DEC;
  - `version: 5`, `revisions` gains DEC-0032, `last_breaking_revision: 5`;
  - one Changelog line.
- **`template/.agent-team/commands/reviewer.md`** and its two wrappers: the no-dispatcher verdict bullet. Implemented by FR-0030 AC-1 and AC-7.
- **`template/tests/unit/scripts/test_dispatch_finalize.py::test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path`**, FR-0030's Reviewer: only the last assertion changes, to pin the new bullet. Its other assertions are unchanged.
- **No other FR-0006 test changes.**

## Changelog

- 2026-11-05: created (proposed) with FR-0030, at Neil's request, before the spec PR's push.
