---
id: DEC-0034
title: "FR-0021 AC-5's reviewer half follows FR-0030: the rejection step records a `## Request changes` verdict instead of \"Use `Request changes` on the PR\", and other lines of `roles/reviewer.md` may now change under FR-0030"
tier: neil
status: proposed  # proposed | ratified | rejected | superseded — Neil ratifies by merging the PR that carries it (FR-0030's spec PR)
satisfies: []
constrained_by: [FR-0030]
revises: FR-0021
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep AC-5's exact rejection-step line and add FR-0030's contract around it"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0021 AC-5 replaced "the gate uses review state" with a pointer to the
  dispatcher's heading rule, but kept "Use `Request changes` on the PR". It
  is the stale instruction FR-0030 removes at `roles/reviewer.md:81`. Its
  test pins the exact line, so AC-5 must say what replaces it.
created: 2026-11-05
updated: 2026-11-05
---

# DEC-0034: FR-0021 AC-5's rejection step records a `## Request changes` verdict

## Context

FR-0021 AC-5 (v1, merged) has two halves.
- **The orchestrator half** fixes an invalid `--stage spec` invocation in `roles/orchestrator.md`. FR-0030 does not touch it.
- **The reviewer half** replaces the parenthetical "the gate uses review state" in `roles/reviewer.md`'s rejection step with a statement that the dispatcher reads the verdict from the final message heading. It adds "No other line of either file changes."

`test_deploy_gate_scope.py::test_reviewer_rejection_step_names_the_dispatcher_verdict_heading` pins:
- the whole line `1. Use \`Request changes\` on the PR (not just a comment — …)`;
- its neighbours;
- that the role file never contains `review state`.

The commit-anchored test `test_the_fr0021_commit_changed_one_line_of_each_role_file` compares two fixed refs and is unaffected.

FR-0030 AC-1 removes "Use `Request changes` on the PR" and "not just a comment" from the role file, because no Reviewer sets a review state. FR-0030 AC-2 adds a rationale that ends "not because any check consumes a review state", which ai-hub-poc's FR-0062 test pins.

## Decision

1. **The reviewer half of AC-5 is amended.** It now reads: "In `template/.agent-team/roles/reviewer.md`, the rejection step records a `## Request changes` verdict, which the dispatcher reads from the Reviewer's final message heading (see the reviewer command and `## Recording your verdict`, FR-0030 AC-2). The deploy gate reads no review state, and the role file says so."
2. **"No other line of either file changes"** stays true of FR-0021's own commit, which the commit-anchored test checks. It no longer constrains later FRs: `roles/reviewer.md` changes further under FR-0030.
3. **The orchestrator half is unchanged.**

**`breaking: true`.** A pinning test changes. FR-0021 goes to `version: 2`, with `revisions: [DEC-0034]` and `last_breaking_revision: 2`. Rule 5 was checked: identity unchanged. The gate still states its scope correctly.

**Why `neil`.** FR-0021 is a merged FR whose control-plane edits Neil approved (FR-0021 Changelog, 2026-09-25). It is recorded `proposed`, and Neil ratifies it by merging the PR that carries it.

## Alternatives considered

- **Keep AC-5's exact line.** Rejected. It tells the Reviewer to set a review state that GitHub refuses on the owner's PR and nothing reads, which is the defect FR-0030 exists to remove.

## Cascade

Breaking. Every affected artifact:

- **`projects/hub-tooling/specs/FR-0021-deploy-gate-states-scope-and-fails-on-indexer-errors.md`**, done in this commit:
  - AC-5 gains one sentence citing this DEC;
  - `version: 2`, `revisions: [DEC-0034]`, `last_breaking_revision: 2`;
  - one Changelog line.
- **`template/.agent-team/roles/reviewer.md`:** the rejection step. Implemented by FR-0030 AC-1.
- **`template/tests/unit/scripts/test_deploy_gate_scope.py::test_reviewer_rejection_step_names_the_dispatcher_verdict_heading`**, FR-0030's Reviewer. It is retargeted:
  - to pin the new rejection step and its position under `On rejection:`;
  - with the bare "`review state` not in the role file" assertion replaced by "the role file says nothing gates on GitHub review state".

  Its command and deploy-gate assertions are unchanged.
- **No other FR-0021 test changes.**

## Changelog

- 2026-11-05: created (proposed) with FR-0030, at Neil's request, before the spec PR's push.
