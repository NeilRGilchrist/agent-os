---
id: FR-0006
title: Dispatcher owns the commit, refuses empty finalization, materialises REVIEW.md, and keeps role branches in sync across rework rounds
status: merged
owner: architect
depends_on: []
tags: [dispatch, harness, control-plane, template]
# Footprint is expressed as HUB-relative paths under template/ (see Notes):
# the code under change lives in the hub's template, not in this project's src/.
owns:
  - template/scripts/dispatch.py
  - template/.agent-team/commands/developer.md
  - template/.agent-team/commands/reviewer.md
  - template/.claude/commands/developer.md
  - template/.claude/commands/reviewer.md
  - template/.cursor/commands/developer.md
  - template/.cursor/commands/reviewer.md
  - template/tests/unit/scripts/test_dispatch_finalize.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - template/tests/fixtures/dispatch/**
reads:
  - template/.agent-team/roles/developer.md
  - template/.agent-team/roles/reviewer.md
  - template/.agent-team/handoff-protocols.md
  - template/scripts/metrics_log.py
  - template/scripts/deploy-gate.py
  - scripts/bootstrap.py
derived_from: IDEA-0029
pattern: null
ac_state: {}
version: 5
lifecycle: live
revisions: [DEC-0001, DEC-0018, DEC-0023, DEC-0032]
last_breaking_revision: 5
supersedes: null
superseded_by: null
extends: []
serves_roles: []
solution_space:
  open:
    - Where in `dispatch.py` the commit / fast-forward steps live (helper vs. inline in `cmd_finalize` / `ensure_role_worktree`), as long as every entry point named in the ACs goes through them.
    - Exact wording of the WARN / ERROR / NOTE / WOULD- lines, as long as each carries the identifiers the ACs name.
    - Whether the REVIEW.md commit and the staged-tests commit on the Reviewer branch are one commit or two.
  fixed:
    - Staging is the agent's signal of intent. The dispatcher commits the index verbatim and never runs `git add` on the agent's behalf.
    - "The dispatcher never rewrites history on a role branch: no `merge` (other than `--ff-only`), `rebase`, `reset --hard` or forced push."
    - "Dry-run (`apply=False`) mutates nothing: no commit, no file write, no fast-forward."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-13
updated: 2026-11-05
---

# FR-0006: Dispatcher owns the commit, refuses empty finalization, materialises REVIEW.md, and keeps role branches in sync across rework rounds

## Why

IDEA-0029 recorded the failure and its root cause: dispatched agents run under `claude -p`, which is non-interactive, and a user-level `"ask": ["Bash(git commit *)"]` rule opens a prompt nobody can answer, so `git commit` is refused deterministically no matter what the per-worktree allow-list says. Wave 2026-08-07 lost 4 of 4 Developer outputs to this. The Project A FR-0015 orchestration run on 2026-09-13 reproduced it against the current template and found that the mitigation already written for it — `dispatch.py::_commit_staged_work`, which commits the agent's staged index at finalize — is defined but never called. The consequences cascaded: `finalize --role dev` pushed an empty branch and still opened PR #1 with no migration in it; the Orchestrator had to commit the Developer's staged index by hand; the rework loop's precondition demands a committed `REVIEW.md` on the Reviewer branch that neither the reviewer role file nor the reviewer command ever asks for, so the Orchestrator placed one by hand; `wave --fr FR-0015` offered to re-spawn a fresh Developer for an FR whose dev branch already read `in-progress`, because Developer runnability is read from `main`; and on the round-2 re-review the Reviewer worktree was reused as-is, so nothing moved `claude/rev-FR-0015` onto the Developer's new tip and the Reviewer would have re-reviewed round-1 code unless someone ran `git merge --ff-only` first. Every one of these is a mechanical failure inside code the dispatcher already owns. Each occurrence costs a full FR of human recovery (IDEA-0029's estimate), and until they are fixed every wave needs a human sitting beside it to do the commit, the REVIEW.md, and the fast-forward by hand — which is exactly the labour the dispatcher exists to remove.

## What

After this FR lands, `finalize` is the single owner of the commit for every dispatched role: it commits whatever the agent staged (and only that), refuses to push or open a PR for a branch that adds nothing over its base, and writes the Reviewer's posted verdict onto the Reviewer branch as `REVIEW.md` itself so the rework precondition is met by the harness rather than by agent compliance. Developer (and maintainer) runnability reads the FR's status from the role branch when one exists, so a handed-off FR is never re-dispatched as fresh work. A reused Reviewer worktree is fast-forwarded onto the Developer's current tip before the Reviewer is spawned, and refused — never force-synced — when a fast-forward is impossible. The developer and reviewer commands describe the staging contract in one place each so agents stop being told to do something the harness will refuse. Dry-run behaviour stays a faithful preview of all of it.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Finalize commits the staged index, verbatim, before pushing.** For every role `finalize` accepts (`dev`, `rev`, `bkf`, `mnt`): given a role worktree whose index contains staged paths, `finalize <FR> --role <role> --apply` creates exactly one commit on `claude/<role>-<FR>` before any push or `gh` call. The committed tree equals the staged index: a tracked file modified but not staged, and an untracked file, are both absent from the commit. The commit subject is the role's Conventional-Commits subject (`feat(FR-XXXX): <title>` for dev, `test(FR-XXXX): AC coverage` for rev, the existing `bkf` / `mnt` subjects). Given a worktree with nothing staged and a branch that already carries commits over its base (the agent committed itself), no commit is created and finalize proceeds. Verified against a real temporary git repository; no `gh` calls reach the network.

- **AC-2:** **A commit step that cannot complete aborts finalize before the push.** If the role worktree is missing, is on a branch other than `claude/<role>-<FR>` (including detached HEAD), or `git commit` fails, finalize prints one `ERROR` line naming the worktree path and the cause, exits non-zero, and performs no push, no `gh pr create`, no `gh pr review`, and writes no PR record (`_dispatch/<FR>.<role>.pr.json` is unchanged). Verified by checking out a different branch in the worktree before calling finalize.

- **AC-3:** **Work the agent left unstaged is reported, never silently dropped or silently added.** After the commit step, if the worktree still has tracked-but-unstaged modifications or untracked, non-ignored files, finalize prints exactly one `WARN` line per category carrying the count and up to ten repo-relative paths, then continues. It never runs `git add`. A worktree with only ignored paths outstanding (e.g. the dispatch venv, `__pycache__/`) prints no WARN. Verified with one staged file, one modified-unstaged file, one untracked file and one ignored file.

- **AC-4:** **PR-opening roles refuse to finalize a branch with zero commits over base.** For `dev`, `bkf` and `mnt`: after the commit step, if `git rev-list --count main..claude/<role>-<FR>` is `0` — or cannot be computed — finalize prints one `ERROR` line stating that the branch adds no commits over `main`, naming the worktree path and the recovery (stage the work in the worktree and re-run finalize), exits non-zero, does not push, does not run `gh pr create`, and writes no PR record. Given the FR-0015 shape (agent finished, nothing staged, nothing committed), the result is this error and no PR.

- **AC-5:** **The Reviewer is not refused for adding no commits.** For `rev`, the base for the ahead-count is `claude/dev-<FR>`. A Reviewer branch with zero commits over the dev branch (a round-2 approve that adds no new tests is legitimate) still posts its review and exits 0; finalize prints one `NOTE` line saying the Reviewer branch adds no commits over the dev branch. Verified with a rev branch equal to the dev tip.

- **AC-6:** **The dispatcher guarantees a committed `REVIEW.md` on the Reviewer branch.** `finalize <FR> --role rev --apply` ensures `claude/rev-<FR>` carries a committed `REVIEW.md` before the push. **Revised by DEC-0001 (v2, breaking):** when the Reviewer committed or staged a `REVIEW.md` of its own, that file is kept byte-for-byte and no synthesised file is written; only when the branch and the worktree carry none does the dispatcher write the review body it is about to post — the text produced by `_extract_review_verdict` over the Reviewer's final message, before any own-PR fallback prefix — to `REVIEW.md` at the root of the Reviewer worktree and commit it on `claude/rev-<FR>` before the push, with the round number and verdict in the commit subject (e.g. `review(FR-XXXX): round 2 verdict=request-changes`). The v1 rule was to overwrite any existing file unconditionally; see DEC-0001 and FR-0013 AC-2 for the implementation. Afterwards `git show claude/rev-<FR>:REVIEW.md` returns that body byte-for-byte and `_read_review_md_on_branch(<FR>)` returns it. Given a Reviewer run that wrote no `REVIEW.md` of its own, the rework precondition in `_prepare_dev_worktree_for_rework` passes on `REVIEW.md` presence without any human action. Verified against a temporary repository with `gh pr review` stubbed. **Revised by DEC-0023 (v4, breaking):** the committed review lives at `specs/_reviews/<FR>-r<N>.md` (one file per round, N the review round), not at the root. The Reviewer's staged or committed root `REVIEW.md` is still kept byte for byte (DEC-0001): `finalize` files it at the library path and removes it from the root in one `review(<FR>): round <N> verdict=<v>` commit, and files the synthesised body there when the Reviewer wrote none. `_read_review_md_on_branch` returns the newest round, and the rework precondition passes when the dev worktree carries that file after the sync. The root `REVIEW.md` never reaches a pushed branch. Implemented by FR-0025.

- **AC-7:** **The developer and reviewer commands state the staging contract, and nothing they say contradicts the dispatcher.** In `template/.agent-team/commands/developer.md` and `reviewer.md`, the dispatcher-configured branch of the handoff instructions says, in substance: stage every path you want in the handoff with `git add`; committing is optional because the dispatcher commits the staged index verbatim at finalize; unstaged and untracked changes are not part of the handoff. The reviewer command additionally says the final assistant message is the verdict of record — the dispatcher posts it to the PR and records it as `REVIEW.md` — and no longer instructs the Reviewer to `git commit` or to set PR review state itself when a dispatcher is configured. The non-dispatcher branches of both commands are unchanged. The generated wrappers under `template/.claude/commands/` and `template/.cursor/commands/` are regenerated from the edited sources by the existing bootstrap renderer and differ from the sources only by the generated-file banner and frontmatter the renderer already adds. Verified by content assertions on all six files. **Revised by DEC-0018 (v3, breaking):** the reviewer command's dispatcher-configured branch now says the final assistant message is the verdict of record, which the dispatcher posts to the PR. The Reviewer writes its full review to `REVIEW.md` at the worktree root and stages it. The dispatcher keeps a staged or committed `REVIEW.md` byte-for-byte and synthesises one from the final message only when the Reviewer wrote none (DEC-0001, FR-0013 AC-2). The branch no longer says the dispatcher "records it as `REVIEW.md`", and no longer instructs the Reviewer to `git commit`, post the review, or set PR review state itself. The wrappers differ from the sources only by the banner, the frontmatter `generate_commands` renders (from the source's own block since FR-0019 and DEC-0016), and the Cursor `{{args}}` substitution. Implemented by FR-0022 AC-2. **Revised by DEC-0032 (v5, breaking):** "The non-dispatcher branches of both commands are unchanged" now reads: the developer command's non-dispatcher branch is unchanged. The reviewer command's non-dispatcher verdict bullet records the verdict and review in a committed `REVIEW.md`, opened with the `## Approve` or `## Request changes` heading, and may post it to the PR as a plain comment. It sets no review state (FR-0030 AC-1).

- **AC-8:** **Targeted Developer runnability honours the role branch's status.** For role `dev` (and `mnt`, against `claude/mnt-<FR>`): when `claude/<role>-<FR>` exists locally and the FR's `status` as committed on that branch is `in-progress` or `in-review`, `explain_not_runnable(<FR>, frs, "<role>")` returns a reason naming the branch and that status and pointing at the Reviewer tick / rework path, and `wave --fr <FR>` and `tick --role <role> --fr <FR>` abort with that reason and spawn nothing — even though `main` still reads `ready`. When the role branch exists but its committed status is still `ready` (the agent exited before flipping it), the FR remains runnable and the existing worktree is reused. Verified with a temporary repository holding a dev branch whose spec frontmatter reads `in-progress` while `main` reads `ready`.

- **AC-9:** **Unfiltered Developer selection applies the same rule.** `runnable_frs` excludes any FR that AC-8 would refuse, so an unfiltered `wave` / `tick --role dev` neither lists nor spawns it, and prints one `SKIP` line per excluded FR carrying the AC-8 reason. FRs with no role branch behave exactly as today.

- **AC-10:** **A reused Reviewer worktree is fast-forwarded onto the Developer's tip before the Reviewer is spawned.** Whenever `ensure_role_worktree(<FR>, "rev", …)` reuses an existing worktree — the rework loop's round-2+ re-review and a re-run `tick --role rev` alike — and `claude/dev-<FR>` is ahead of `claude/rev-<FR>`, the dispatcher runs `git merge --ff-only claude/dev-<FR>` in the Reviewer worktree before returning, so the Reviewer's HEAD equals the dev branch tip when the agent starts. When the branches are already equal or the dev branch is an ancestor of the rev branch, nothing is run. Verified by asserting `rev-parse HEAD` in the rev worktree equals the dev tip after a simulated round-1 sync plus Developer rework commit.

- **AC-11:** **An impossible fast-forward refuses the spawn; it never force-syncs.** If the fast-forward in AC-10 cannot complete — the branches have diverged, or the Reviewer worktree has uncommitted tracked changes — `ensure_role_worktree` returns an `error:` status naming the two branches and the cause, `spawn_role` does not spawn, and in the rework loop the round stops as a mechanical failure (`(None, "precondition: …")`, no budget round consumed). The dispatcher never runs `merge` without `--ff-only`, `rebase`, `reset --hard` or `checkout -f` on a role branch or worktree. Verified with a diverged rev branch and, separately, with a dirty rev worktree.

- **AC-12:** **Dry-run previews every new step and mutates nothing.** Without `--apply`, `finalize` prints `WOULD-COMMIT` (with the staged-path count), `WOULD-WRITE-REVIEW` (rev only), and the existing `WOULD-FINALIZE` line, and `spawn_role` / `wave --dry-run` prints `WOULD-FAST-FORWARD` when AC-10 would fire; the zero-commit refusal of AC-4 is reported as `WOULD-REFUSE` rather than an error. After a dry run the repository — every branch tip, every worktree's index and working tree, and `_dispatch/` — is byte-identical to before. Verified by snapshotting `git for-each-ref` and `git status --porcelain` in each worktree before and after.

- **AC-13:** **Existing behaviour and metrics are preserved.** Every test that passed before this FR still passes; the `pr.opened` / `pr.refreshed` / `pr.review` records introduced by FR-0002 still validate and `commits_ahead` on `pr.opened` reflects the post-commit count. `finalize` for a worktree whose agent committed its own work and staged nothing behaves exactly as today apart from the new NOTE/WARN lines. No new metrics record kind is introduced.

## Out of scope

- `finalize --role dev` on an existing PR refreshing the body from `PR_BODY.md` or honouring `--ready` (harness gap 5 in the Project A handoff). Same file, separate behaviour; file as its own FR if wanted.
- Relocating dispatch worktrees out of `.claude/` (IDEA-0031).
- Changing the user-level `~/.claude/settings.json` `ask` rule, or any per-harness permission model. This FR makes the dispatcher indifferent to whether the agent can commit.
- Auto-staging untracked or unstaged files on the agent's behalf (AC-3 reports them; it never adds them).
- Any merge strategy other than fast-forward for the Reviewer branch (AC-11), or any sync in the other direction beyond what `_prepare_dev_worktree_for_rework` already does.
- Changes to `template/.agent-team/roles/*.md`, `handoff-protocols.md`, or the orchestrator command. The role files are read, not edited; if the Developer finds they contradict AC-7, raise a `## FINDINGS` line rather than editing them.
- GitHub's own-PR review restriction (verdict downgraded to COMMENTED). Already handled by the existing fallback; unchanged.
- Windows line-ending normalisation of generated artifacts — see FR-0007.

## Open questions

- **Q:** Should the dispatcher-authored `REVIEW.md` (AC-6) defer to a `REVIEW.md` the Reviewer wrote and staged itself, or always overwrite?
  - **Closed by DEC-0001 (2026-09-20, breaking):** defer. The v1 default was always-overwrite, on the reasoning that the Reviewer's final message is the verdict of record and two sources of truth for the same round is how the original inconsistency arose. The Project A FR-0001 wave showed the two artifacts are not duplicates — an 11 KB working review was replaced by the 3 KB posted body — so the dispatcher now synthesises only when the branch carries none. The verdict of record is unchanged. The allow-list entry for `Write(REVIEW.md)` stays.
- **Q:** For `rev` with zero commits over the dev branch (AC-5), should finalize skip the push?
  - **Default:** Push as today (a no-op fast-forward); only the NOTE is new. Skipping introduces a second code path for no benefit.
- **Q:** Should untracked files under `tests/` in a Reviewer worktree (the FR-0064 case in IDEA-0029) be treated as staged-by-intent?
  - **Default:** No. AC-3 warns; the staging contract in AC-7 is the fix. Auto-adding would reintroduce the guesswork the contract removes.
- **Q:** Should `runnable_frs` (AC-9) also refuse when a `claude/dev-<FR>` branch exists with status `ready` but has commits over `main` (agent did work, never flipped)?
  - **Default:** No. Status on the branch is the signal; the worktree is reused so the work is not lost. Widening the rule needs evidence of the failure first.

## Dependencies

None. FR-0002's metrics emitters are read for AC-13 but are not changed.

## Notes

- Footprint paths are hub-relative under `template/` (see AGENTS.md "Hub-tooling specifics"). `template/.agent-team/commands/**` and `template/.claude/commands/**` are human-approval files; this FR is dispatched in maintainer (`mnt`) mode with the `owns:` above as the write surface, and the human's approval of this FR is the approval for those edits.
- All the helpers the ACs need already exist and are currently dead code: `_commit_staged_work`, `_staged_paths`, `_unstaged_paths`, `_commits_ahead`, `_finalize_commit_subject`, `_read_review_md_on_branch`. Wire them; do not fork them.
- Round number for the AC-6 commit subject is available from `_run_context(fr_id, "rev")["round"]` (falls back to 1, as the metrics emitters do).
- `_prepare_dev_worktree_for_rework` merges the Reviewer branch into the dev worktree before every rework round, so on the Reviewer's next spawn `claude/rev-<FR>` is an ancestor of `claude/dev-<FR>` and AC-10's `--ff-only` succeeds by construction. If it does not, something outside the harness moved a branch — which is exactly when AC-11 should stop and say so.
- The generated command wrappers are produced by `scripts/bootstrap.py` (`<!-- Generated from .agent-team/commands/<name> -->`). Regenerate rather than hand-edit; the Reviewer's dogfood bootstrap will catch drift.
- Reviewer dogfood step (AGENTS.md) applies: bootstrap a throwaway project from the modified template, run its `index-specs.py --validate` and `deploy-gate.py`, and exercise `dispatch.py finalize --role dev` (dry-run) inside it.
- Source of the defect list: Project A `_dispatch/handoff-architect-FR-0015.md` (gaps 1-4) and `_dispatch/synthesis-2026-09-13T17-00-00Z.md`.

## Changelog

- 2026-09-13: created from IDEA-0029; scope confirmed against the Project A FR-0015 orchestration escalation of 2026-09-13
- 2026-09-20: merged via hub PR #2 (`16843d4`); status merged
- 2026-09-20: v2 — DEC-0001 (breaking: true): AC-6 defers to a Reviewer-authored `REVIEW.md` and synthesises only when absent; implemented by FR-0013:AC-2
- 2026-09-25: v3 — DEC-0018 (breaking: true): AC-7's reviewer sentence now asks the Reviewer to write and stage its own `REVIEW.md` (kept by the dispatcher; synthesised only when absent) instead of "the dispatcher records it as `REVIEW.md`"; the wrapper clause is refreshed for FR-0019's source frontmatter. Implemented by FR-0022 AC-2; the test cascade is `test_dispatch_finalize.py::test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path`. Discharges the follow-up recorded in FR-0013's Notes.
- 2026-09-26: v4 — DEC-0023 (breaking: true): AC-6's committed review moves from the root `REVIEW.md` to the per-round library file `specs/_reviews/<FR>-r<N>.md`; the Reviewer's root `REVIEW.md` stays its handoff and is filed there byte for byte. Implemented by FR-0025; the test cascade is four ids in `test_dispatch_finalize.py`, listed in DEC-0023. `neil` tier, proposed.
- 2026-11-05: v5 — DEC-0032 (breaking: true): AC-7's reviewer non-dispatcher branch no longer keeps the `Approve` review-state instruction. It records the verdict and review in a committed `REVIEW.md` and may post it as a plain comment. Implemented by FR-0030 AC-1; the test cascade is the last assertion of `test_dispatch_finalize.py::test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path`. `neil` tier, proposed.
