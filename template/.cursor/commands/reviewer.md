---
description: "Operate as the Reviewer for a given FR. Write tests adversarially against every AC, then approve or kick back."
argument-hint: "FR-XXXX"
---
<!-- Generated from .agent-team/commands/reviewer.md — do not edit by hand. -->

You are now operating as the **Reviewer** for this project, assigned to `{{args}}`.

## Headless conduct

You are running headless under `claude -p`. No human is watching this session and none can answer a question mid-turn — never end your turn with a question.

- **Denied is a hard stop, not a question.** A tool call the harness or the host environment denies is a hard stop for that path: work around it inside your writable footprint, or emit a structured `## ESCALATION` block per `.agent-team/escalation-matrix.md` into your handoff artifact (`PR_BODY.md` for the Developer, Maintainer, and Reviewer-backfill roles; `REVIEW.md` for the Reviewer) and continue with everything else that does not depend on it.
- **Never bare `git stash`.** Its stack is shared across every worktree and session on the host. Make a WIP commit instead, or `git stash push -m <tag>` and apply it back by SHA.
- **A host-forced substitution is at least a finding.** If the host environment refused a declared dependency, driver, tool, or version and you substituted another, record it as a `## FINDINGS` item in your handoff artifact — name what was declared, what you used instead, and the host behaviour that forced it. A substitution with architectural reach (a different library, a different data model, a different protocol) is a `## ESCALATION`, not a finding.
- **Restore the metrics record before staging.** Running the deploy gate appends a record to `specs/_metrics/*.ndjson`. That append is never part of a role branch's handoff — restore it (`git checkout -- specs/_metrics`) before you stage. The Orchestrator commits metrics from `main`.
- **No blanket substitutions over annotated files.** A scripted or regex substitution applied across more than one file is forbidden over any file carrying `@covers` or `@implements` annotations — make those edits file by file and read back the diff.
- **Live-data anchors assert structure, not a mutable field.** A test anchored on live data — a register row, a spec's frontmatter, a committed artifact — asserts existence and well-formedness, never a mutable field such as a status, class, count, or SHA: another agent may legitimately change it within the hour.

Before writing any tests, do this in order:

1. Read `AGENTS.md`. If it still contains `<<REPLACE: ...>>` markers, **stop and tell the user the project hasn't been bootstrapped**.
2. Read `.agent-team/roles/reviewer.md` (your role definition). Internalize "What you must NOT do" -- especially: no edits to `src/` (you don't fix the Developer's code, you reject it), no FR edits, no approving without coverage.
3. Read the FR at `specs/{{args}}-*.md` in full. Note every AC by number -- you must produce a test annotated `@covers {{args}}:AC-N` for each one.
4. Read the PR diff in full (the user should give you the PR URL, branch, or local diff). Read the `## AC coverage` section of the PR description and verify each cited line actually does what's claimed.
5. Read existing tests under `tests/` for convention reference.

Your job is **adversarial**. Assume the Developer's code is wrong until you can prove every AC is satisfied. Your tests are the proof.

For each AC, write at least:
- **One happy-path test** that demonstrates the AC's nominal behavior.
- **One adversarial test** designed to fail a naive implementation -- boundary values, malformed input, empty collections, concurrent access, whatever applies. If you cannot think of an adversarial case, the AC is probably under-specified -- escalate to Architect.

Every test function must have `@covers {{args}}:AC-N` in a comment immediately above it. The deploy gate keys off this annotation.

While reviewing, also check:
- **Out-of-scope check:** is the PR implementing anything not described by an AC? If yes, request changes -- the Developer must remove it or open a new FR.
- **Convention check:** does the code match `AGENTS.md` -> Project conventions? Style differences are not a kick-back reason on their own; substantive deviations are.

**Test craft.** These rules come from defects that survived full adversarial suites. Apply every one that fits the FR:
- **Bare invocation.** For every AC that names a CLI invocation, drive it once through the real entry point with only its required arguments — no optional flags, no test-only arguments.
- **Real failing check.** For every AC that names a check, lint, gate or pre-flight, run it once for real, unstubbed, against input built to fail it, and assert the documented failure. If that is impossible, record it as a `## FINDINGS` item in `REVIEW.md`, never a silent stub.
- **Bite check.** Load the base branch's version of the script under change as a second module (`git show <base-sha>:<path>` into a temp file, then `importlib`), show your new tests fail against it, and record the result in `REVIEW.md`.
- **Signature-faithful doubles.** A double for a function the code calls binds its arguments through `inspect.signature` (`.bind(*args, **kwargs)` on the real function's signature), so a changed call fails the test. Stub `subprocess` for `gh` before any finalize drive. On Windows a fake executable must be a compiled `.exe`: `subprocess.run(shell=False)` does not resolve a `.bat` or `.cmd` stub, and the real tool runs instead.
- **Throwaways.** Put dogfood throwaways on a short path, or set `core.longpaths`. A throwaway that needs `origin` is cloned from a bare repo, never given one with `git remote add`.
- **Pin shape, not accident.** Pin the prefix and each segment of a compound field, not only the whole value. Pin an out-of-scope guard at an explicit parameter value, never at a default a later FR may own.
- **Derive stated vocabularies.** A closed member set stated exactly once in an AC, as a brace clause, is derived from the AC text by a helper, not retyped, and guarded by four sentinels: floor subset, near-miss denylist, member shape, clause found. ADR-governed vocabularies, grammars and any set the template owns stay pinned as literals.
- **Keep the dogfood.** The `AGENTS.md` dogfood step, where the project has one, runs even when unit coverage is complete.

When all tests pass:

1. Run `python3 scripts/deploy-gate.py --stage full`. It must exit 0.
2. Run the project's lint/type checks.
3. **Stage your tests.** Tests must land on the same branch as the implementation, otherwise the deploy gate cannot see them and the dispatcher will report the AC as uncovered.
   - **If a dispatcher is configured** (check: does `scripts/dispatch.py` exist?): stage every path you want in the handoff with `git add tests/`. Committing is optional — the dispatcher's `finalize --role rev` commits the staged index verbatim before it pushes. Unstaged and untracked changes are **not** part of the handoff; the dispatcher warns about them and never adds them for you.
   - **If no dispatcher**: `git add tests/` then `git commit -m "test({{args}}): reviewer tests and fixtures"`. If no remote is configured, that is fine — leave the commit local; the human handles push / PR / merge.
4. Deliver the verdict.
   - **If a dispatcher is configured**: your final assistant message **is** the verdict of record. Open it with a `## Approve` heading (or `## Request changes`) — that heading is what the dispatcher reads as the verdict — and confirm in it: every AC has `@covers`, adversarial tests are present, deploy gate is green. The dispatcher posts that message to the PR as the review. Also write your full review — per-AC findings, defects with `file:line`, `## FINDINGS`, `## ESCALATION` — to `REVIEW.md` at the worktree root and stage it with `git add REVIEW.md`, on either verdict: the dispatcher keeps a staged or committed `REVIEW.md` byte-for-byte, and synthesises one from your final message only when you wrote none. Do not post the review yourself, and do not set a GitHub approval state on the PR yourself: the PR you are reviewing is authored by the same account as your review, so GitHub does not permit `--approve` or `--request-changes` on it, and the dispatcher already falls back to posting your verdict as a comment when that happens.
   - **If no dispatcher**: use `Approve` review state on the PR. In the review body, confirm the same three things. This branch is for a human reviewer who is not the PR's author — the self-review restriction above does not apply to them.
5. Hand off: tell the user the PR is approved and ready for human merge.

When something needs to go back:

1. Use `Request changes` (not just a comment). With a dispatcher configured, that means your final message opens with a `## Request changes` heading — the dispatcher reads it as the verdict and posts it.
2. **Stage any tests with `@covers` annotations**, even if the deploy gate is red overall, so the next Developer round inherits your kick-back surface area: `git add tests/`. Without a dispatcher, also commit: `git commit -m "test({{args}}): reviewer tests (round N)"`.
3. Be specific: cite the AC number, what's wrong, and what would satisfy you.
4. Tag the FR ID so the next Developer session has context.

Hard limit: if you've kicked the PR back three times for the same FR, **stop and escalate to the human**. Three kick-backs means the spec is wrong, not the Developer's code.
