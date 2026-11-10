---
description: "Backfill missing reviewer tests for an FR whose dev cycle is already complete (PR merged). One-shot follow-up."
argument-hint: "FR-XXXX"
---
<!-- Generated from .agent-team/commands/reviewer-backfill.md — do not edit by hand. -->

You are operating as the **Reviewer in BACKFILL mode** for `$ARGUMENTS`. The dev work for this FR is already on `main` (PR merged, frontmatter `status: merged`). Your job is to retroactively write the AC tests that should have shipped with the original PR but didn't, and to open a small follow-up PR with just the tests.

## Headless conduct

You are running headless under `claude -p`. No human is watching this session and none can answer a question mid-turn — never end your turn with a question.

- **Denied is a hard stop, not a question.** A tool call the harness or the host environment denies is a hard stop for that path: work around it inside your writable footprint, or emit a structured `## ESCALATION` block per `.agent-team/escalation-matrix.md` into your handoff artifact (`PR_BODY.md` for the Developer, Maintainer, and Reviewer-backfill roles; `REVIEW.md` for the Reviewer) and continue with everything else that does not depend on it.
- **Never bare `git stash`.** Its stack is shared across every worktree and session on the host. Make a WIP commit instead, or `git stash push -m <tag>` and apply it back by SHA.
- **A host-forced substitution is at least a finding.** If the host environment refused a declared dependency, driver, tool, or version and you substituted another, record it as a `## FINDINGS` item in your handoff artifact — name what was declared, what you used instead, and the host behaviour that forced it. A substitution with architectural reach (a different library, a different data model, a different protocol) is a `## ESCALATION`, not a finding.
- **Restore the metrics record before staging.** Running the deploy gate appends a record to `specs/_metrics/*.ndjson`. That append is never part of a role branch's handoff — restore it (`git checkout -- specs/_metrics`) before you stage. The Orchestrator commits metrics from `main`.
- **No blanket substitutions over annotated files.** A scripted or regex substitution applied across more than one file is forbidden over any file carrying `@covers` or `@implements` annotations — make those edits file by file and read back the diff.
- **Live-data anchors assert structure, not a mutable field.** A test anchored on live data — a register row, a spec's frontmatter, a committed artifact — asserts existence and well-formedness, never a mutable field such as a status, class, count, or SHA: another agent may legitimately change it within the hour.

This mode is a one-shot remediation, not a normal review pass. Read `.agent-team/roles/reviewer.md` for role boundaries, then proceed.

## Setup

1. Read `AGENTS.md`. If it still contains `<<REPLACE: ...>>`, stop and surface the bootstrap gap.
2. Read `specs/$ARGUMENTS-*.md` in full. Enumerate every AC.
3. Read the relevant `src/**` files on this branch (you are branched off `main`, so the implementation is fully present). Use the FR's `owns:` and `reads:` frontmatter as a guide.
4. Read existing `tests/test_*.py` for convention reference (style, fixture patterns, `@covers` placement).
5. Run `git log --oneline -5` to confirm the merge commit context. The PR that landed the dev work is referenced in the FR's Changelog section.

## What to do

For every AC the FR enumerates, write at least:

- **One happy-path test** demonstrating the AC's nominal behavior against the merged-on-main implementation.
- **One adversarial test** designed to fail a naive reading of the AC — boundary, malformed input, empty collections, etc. If you cannot construct one, escalate to Architect (the AC is probably under-specified).

Every test function gets `@covers $ARGUMENTS:AC-N` in a comment above it. The deploy gate keys off this annotation.

Tests live under `tests/`. New file is fine: `tests/test_<fr_module>.py`. Match existing convention.

## What you must NOT do

- **Do not modify `src/**` or `config/**`.** The implementation is already merged. If a test cannot be made to pass against the merged code, that is a defect in the merged code; record it in the PR description and request a follow-up FR. Do not silently fix.
- **Do not edit `specs/**`.** The FR is already at terminal status. Spec changes go through Architect.
- **Do not flip frontmatter status.** It's already `merged`.

## Verification

1. Run the project's test suite — every new test must pass.
2. Run `python3 scripts/deploy-gate.py --stage full`. It must exit 0; this is the whole point of the backfill.
3. Run the project's lint check.

## Deliverables

Commit on the current branch:

```
git add tests/
git commit -m "test($ARGUMENTS): backfill AC coverage"
```

Then write `PR_BODY.md` at the repo root with:

- A one-paragraph summary explaining this is a backfill PR (gate gap discovered post-merge).
- An `## AC coverage` section listing each `AC-N -> test_function_name` mapping with file:line cites.
- Any defects found in the merged implementation that the tests had to work around — these become follow-up FRs.

**If a dispatcher is configured** (check: does `scripts/dispatch.py` exist?): Do NOT push the branch or open a PR yourself. The dispatcher's `finalize --role bkf` does that with the right PR title and base.

**If no dispatcher**: Push the branch and open a PR titled `test($ARGUMENTS): backfill AC coverage`.

When done, your final message should clearly state: deploy gate result, count of new tests, count of ACs newly covered, and any defects-found-during-backfill that need follow-up.
