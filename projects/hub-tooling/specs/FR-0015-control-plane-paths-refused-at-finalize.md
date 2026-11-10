---
id: FR-0015
title: Control-plane paths are refused at finalize whoever wrote them — no Reviewer-provenance exemption, no uncommitted tampering, no rewritten permission file — and a malformed `owns:` is refused for every role that derives grants from it
status: merged
owner: architect
depends_on: [FR-0006, FR-0009, FR-0010, FR-0013]
tags: [dispatch, control-plane, footprint, finalize, security, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_dispatch_grant_hardening.py
  - template/tests/fixtures/grant-hardening/**
reads:
  - template/scripts/stack_profile.py
  - template/scripts/spec_footprint.py
  - template/tests/unit/scripts/test_dispatch_finalize.py
  - template/tests/unit/scripts/test_dispatch_postapprove.py
  - template/tests/unit/scripts/test_dispatch_permissions.py
  - template/tests/unit/scripts/test_dispatch_stack_grants.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - template/tests/unit/scripts/test_dispatch_review_artifact.py
  - template/tests/unit/scripts/test_dispatch_gates.py
  - specs/decisions/DEC-0017-fr0015-rev-diff-base-falls-back-to-main-and-ac3-fails-closed.md
  - specs/decisions/DEC-0014-docker-stays-granted-finalize-is-the-control-plane-boundary.md
  - specs/decisions/DEC-0015-fr0013-reviewer-provenance-never-exempts-a-control-plane-path.md
  - scripts/bootstrap.py
gates: []
derived_from: IDEA-0083
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0017]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0009, FR-0010, FR-0013]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - Where the permission-file digest (AC-4) is stored, as long as it is outside the role worktree, never committed, not a metrics record, and written by the same call that writes the file.
    - Whether AC-2 and AC-3 share one helper or a private off-limits predicate, as long as `mnt`'s existing output for non-protected paths is byte-identical. `mnt_footprint_violations` keeps its signature and its single call site `mnt_footprint_violations(fr_id, branch)` in `cmd_finalize`, and AC-2/AC-3 do not call it (DEC-0017 Decision 4).
    - Exact wording of the new `ERROR` / `WOULD-REFUSE` lines, as long as each names the role, every offending path (or the file, for AC-4), and which check fired (Reviewer provenance, committed, uncommitted, or permission file).
  fixed:
    - "Refuse, never repair: the dispatcher never restores, reverts, stages, unstages or deletes a path or file it refuses on. The worktree is left as found, for a human."
    - "Nothing in this FR widens any role's allow-list, lifts any deny, or changes the stack-grant table (DEC-0014)."
    - "The off-limits set derives from `MNT_PROTECTED_GLOBS`, `MNT_NEVER_WRITABLE` and the FR's `owns:` — the constants and helper the permission derivation already uses. No second list."
    - "A check that cannot run is a refusal, not a pass."
    - "Dry-run (`apply=False`) mutates nothing."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-09-25
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect from IDEA-0083 (Chief of Staff triage 2026-09-25) and `_dispatch/handoff-architect-docker-grant-security.md`, grounded in the FR-0010 Reviewer's `## FINDINGS` (a) and (e) (`_dispatch/FR-0010.rev.REVIEW.md`, hub PR #4) and a read of `template/scripts/dispatch.py` at `e623564`. Scope approved by Neil in the Architect session of 2026-09-25 (decisions D1–D3). · source_class: neil_position+agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0015: Control-plane paths refused at finalize, whoever wrote them

## Why

The FR-0010 Reviewer showed, live, that a granted `Bash(docker *)` writes a role-denied path through a bind mount. The Architect's analysis (DEC-0014) found that docker is not special. For `mnt` in a project that declares `uv` and `alembic`, which Project A does today, `uv run python -c …`, `alembic upgrade` and the sanctioned `python -m pytest` run over any owned file all reach the same paths. In every project, `dev` and `rev` hold `Bash(python *)` statically. Restricting commands at write time cannot be the boundary, because a role's job is to edit and run code. DEC-0014 therefore records that the control-plane boundary is the artifact-level check at finalize plus the human merge. That check has four gaps. (1) FR-0013 AC-5(a) exempts from `mnt`'s footprint check any path the Reviewer's fast-forwarded commits touched, whatever it is. A Reviewer-authored edit to `scripts/deploy-gate.py` therefore reaches a maintainer PR unchecked, and the FR-0010 Reviewer's probe ran in exactly that worktree. (2) `dev`, `rev` and `bkf` have no artifact-level check at all, so a control-plane path on their branches meets only the human reviewer. (3) Uncommitted changes are never checked. Yet a control-plane file modified in place, never staged, changes what every gate run in that worktree reports: the agent's own self-check, and FR-0013 AC-7's in-worktree revalidate. A permission file rewritten from an interpreter changes what the agent may do for the rest of its run. (4) A malformed `owns:` is refused only for `dev` (FR-0010 finding (a)). `mnt` turns `owns:` entries into `Edit(...)`/`Write(...)` grants verbatim, so a malformed entry there is a malformed grant.

## What

After this FR lands, `finalize` refuses for `dev`, `rev`, `bkf` and `mnt` when a control-plane path the role may not write turns up anywhere: committed on the branch, whoever committed it, or left uncommitted in the worktree. It also refuses when the role's permission file no longer matches what the dispatcher wrote. The dispatcher names what it found and changes nothing. `rev`, `bkf` and `mnt` refuse a malformed `owns:` before anything is written, as `dev` already does. Nothing is granted, lifted or narrowed at write time: every permission file is byte-identical to today's (DEC-0014).

**Term used below.** A path is *off-limits* for a role when it matches a `MNT_PROTECTED_GLOBS` entry (by the same `fnmatch` rule `_owned` applies) and is not granted to that role. For `dev`, `rev` and `bkf` every protected path is off-limits: FR-0009 AC-2 withholds them under any `owns:`. For `mnt`, a protected path is off-limits unless it is in `mnt_permission_rules`'s `granted` set for the FR, so `MNT_NEVER_WRITABLE` is always off-limits.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Reviewer provenance never exempts a control-plane path (FR-0013 AC-5(a) as revised by DEC-0015).** `_mnt_provenance_exemptions` never exempts a path that matches `MNT_PROTECTED_GLOBS`. Such a path is on the violation list only because it is outside `owns:`, so it is off-limits for `mnt`. It stays a violation, and `finalize --role mnt` refuses with the existing footprint `ERROR` line. In place of AC-5(a)'s `NOTE`, one line precedes that `ERROR`, naming the path and stating that Reviewer provenance does not exempt a control-plane path. AC-5(b) (`specs/_metrics/**`) and FR-0013 AC-6 (`--allow-crossing`, content-free proof) are unchanged. Verified against a temporary repository with `gh` stubbed:
  - an `mnt` branch onto which FR-0013 AC-1's fast-forward brought a Reviewer commit touching `scripts/deploy-gate.py`, not in `owns:`, refuses;
  - the same fast-forward bringing a Reviewer test under `tests/**` is still exempt, with today's `NOTE`;
  - a Reviewer commit touching `.agent-team/roles/reviewer.md`, not in `owns:`, refuses.

- **AC-2:** **A `dev`, `rev` or `bkf` branch carrying a control-plane path never reaches a push, a review post or a PR.** Immediately after the commit step (`_finalize_commit_step`), `finalize --role dev|rev|bkf` computes the paths changed on `<finalize-base>...<branch>`, where `<finalize-base>` is `_finalize_base_branch`'s answer. For `rev` that is the implementation branch (FR-0013 AC-11), so only the Reviewer's own commits count. When that branch does not exist, which happens only for a `rev` with neither `claude/dev-<FR>` nor `claude/mnt-<FR>`, the base is `main`, the ref the Reviewer worktree was cut from (`_base_branch_for_role`). `_finalize_base_branch` itself is unchanged (DEC-0017 Decision 1). In dry-run the set also includes the staged index the commit step would commit. If any path in the set matches `MNT_PROTECTED_GLOBS`:
  - finalize prints one `ERROR` line (`WOULD-REFUSE` in dry-run) naming the role and every such path;
  - it stops there: no revalidate merge, no `REVIEW.md` materialised, no `gh` call, no review posted, no fast-forward, no push, and no PR record written or refreshed;
  - under `--apply` it exits non-zero; in dry-run it exits as `_finalize_commit_step`'s existing `WOULD-REFUSE` does.

  A `git diff` that cannot run is a refusal, as it already is in `mnt_footprint_violations`. A refusal that quotes git's stderr quotes its first non-empty line, not the usage text git prints last (DEC-0017 Decision 5). There is no exemption of any kind, because no protected path is ever writable for these roles. Verified for:
  - a `dev` branch committing `.agent-team/roles/developer.md`;
  - a `rev` branch committing `scripts/deploy-gate.py`: refused before `gh pr review` is invoked, with the implementation branch not fast-forwarded;
  - a `bkf` branch committing `CLAUDE.md`;
  - a `dev` branch touching only `src/**`: every line and the exit code identical to today.

- **AC-3:** **Uncommitted changes to an off-limits path refuse finalize for every role.** Immediately after the commit step, and after FR-0006 AC-3's `WARN` lines (printed unchanged), `finalize --role dev|rev|bkf|mnt` inspects the role worktree. It looks at the same two sets FR-0006 AC-3 reports: tracked-but-unstaged modifications, including deletions (`git diff --name-only`), and untracked non-ignored files (`git ls-files --others --exclude-standard`). Both are computed with the same git commands FR-0006 AC-3's helpers run, but through a path that reports failure. A read that fails is a refusal, with one `ERROR` line (`WOULD-REFUSE` in dry-run) naming the role, this check and the cause. `_unstaged_paths`, `_untracked_paths` and FR-0006 AC-3's `WARN` output are unchanged; they stay fail-open because that report is advisory (DEC-0017 Decision 2). If any path in either set is off-limits for the role:
  - finalize prints one `ERROR` line (`WOULD-REFUSE` in dry-run) naming the role and every such path;
  - it stops at the same point as AC-2, and for `mnt` also before the footprint check;
  - exit codes are as in AC-2.

  The dispatcher does not restore, stage, unstage, revert or delete anything. Verified for each of the four roles with:
  - an unstaged modification to `scripts/deploy-gate.py` written by a subprocess (standing in for any interpreter or container): refused;
  - an untracked file under `.agent-team/`: refused;
  - for `mnt` only, an unstaged modification to a protected path its `owns:` grants: not refused, only today's `WARN`, because it is unfinished work rather than a crossing.

- **AC-4:** **A permission file the agent rewrote refuses finalize.** Each time `write_worktree_settings` writes a role's permission file, in either adapter, the dispatcher records the SHA-256 of the exact bytes written. For Claude Code the file is `<wt>/.claude/settings.local.json`; Cursor uses that adapter's own file. The record replaces any earlier record for that FR and role, and is placed as follows (DEC-0017 Decision 3):
  - **Where it lives:** in a file under the call-time `DISPATCH_DIR`, outside the role worktree.
  - **What it holds:** the permission file's path and the SHA-256 of the bytes read back from disk right after the write.
  - **Who writes it:** each adapter's `write_worktree_settings`, after its own write.
  - **What does not change:**
    - how the permission file is written;
    - how finalize finds the file: from the record, never from the `adapter` argument;
    - the lock file and the spawn record's `worktree_status`: the digest goes in neither. At finalize for `dev`, `rev`, `bkf` and `mnt`, if a record exists and the file is missing or its SHA-256 differs:
  - finalize prints one `ERROR` line (`WOULD-REFUSE` in dry-run) naming the file and the first 12 hex characters of both digests (`missing` when the file is absent);
  - it stops at the same point as AC-3, with the same exit codes.

  When no record exists (a worktree created before this FR, or by hand), the check is skipped silently. The record is dispatcher state: never committed, never inside the worktree, not a metrics record. Verified by:
  - spawning a role: file written, record present;
  - rewriting the file with one added `allow` entry via a subprocess: refused;
  - deleting the file: refused, reported as `missing`;
  - re-entering `ensure_role_worktree` on the reuse path, which rewrites the file: record refreshed, finalize proceeds;
  - a worktree with no record: no extra line, no refusal.

- **AC-5:** **A malformed `owns:` is refused for every role that derives grants from it.** `ensure_role_worktree` refuses a `rev`, `bkf` or `mnt` spawn whose FR has an `owns:` entry `_invalid_owns_entries` reports. The refusal is exactly what `dev` gets today under FR-0009 AC-5: the same error text, returned before any worktree is created or reused (including `rev`'s reuse fast-forward), any settings file is written, any venv is provisioned, any process is spawned, or any spawn record is written. `mnt`'s existing empty-`owns:` refusal is unchanged and runs first. A valid or empty `owns:` for `rev`/`bkf` behaves exactly as today. Verified per role with an `owns:` containing an absolute path (refused, nothing written), one containing a `..` segment (refused, nothing written), and a valid `owns:` (unchanged).

- **AC-6:** **Nothing widens, and clean runs are byte-identical.** For every role, FR and stack, the permission files `write_worktree_settings` writes are byte-identical to today's. `stack_profile.py`, `STACK_BASH_GRANTS`, `CURSOR_STACK_SHELL_GRANTS`, `_union_grants`, `_mnt_bash_denies`, `MNT_BASH_NOT_INHERITED`, `MNT_BASH_DENIES` and `MNT_PROTECTED_GLOBS` are not edited (DEC-0014). A finalize is clean when its branch and worktree hold no off-limits path and its permission file matches its record, or has none. For a clean finalize, every printed line, exit code, PR record and metrics record is byte-identical to today's. No new metrics record kind or field is introduced. Every test that passed before this FR passes unedited. This FR owns no existing test file, so a pre-existing test that goes red is a `## FINDINGS` line for the Architect, not an edit.

## Out of scope

- Any change to what a role may run or write at spawn time: the stack-grant table, `mnt`'s Bash narrowing, any deny list, and `MNT_PROTECTED_GLOBS` itself (DEC-0014; AC-6).
- Writes outside the role worktree: the primary checkout, other worktrees, and the user-level harness settings. No dispatcher check can see them; the fix is a process sandbox or container (IDEA-0064, DEC-0014 Decision 3).
- A Reviewer editing *owned* implementation files through an interpreter. That is not a control-plane crossing, and the human merge reviews it.
- The implicit self-spec grant in `fr_owns_globs` (IDEA-0083 item 3). It widens a footprint, so it moved to IDEA-0084 (DEC-0014 Decision 6).
- The `gat` role (no code-executing grant; writes one evidence file) and the `docs` role (not finalized through `cmd_finalize`).
- Existing dry-run vocabulary residue and `mnt_footprint_violations`'s unused `extra=` parameter (IDEA-0084 item 5).
- Repairing anything. The dispatcher refuses and names; a human restores.

## Open questions

- **Q:** Should `MNT_PROTECTED_GLOBS` also cover `AGENTS.md` and `.claude/settings.json`? Both are on this project's human-approval list, and `AGENTS.md` is the working agreement that `CLAUDE.md` only imports.
  - **Default:** Not in this FR. Changing the constant changes every `mnt` permission file and the deny lists FR-0009/FR-0010 tests pin byte-for-byte, which is a breaking DEC on FR-0009, and AC-6 forbids it here. Parked as IDEA-0088 on 2026-09-25 at Neil's request, to land after this FR.
- **Q:** Should the dispatcher also compare the primary checkout's `git status` before and after a spawn?
  - **Default:** No. A human works in the primary checkout concurrently, so the check would raise false refusals. Writes outside the worktree wait for IDEA-0064.
- **Q:** AC-4 assumes a headless spawn never rewrites its own permission file. What if the harness itself does, for example to persist an "always allow"?
  - **Default:** Refuse, as written. Headless spawns get no permission prompts, so the harness has no reason to write the file. If a real run shows the harness rewriting it, the Reviewer records it under `## FINDINGS` and the Architect narrows AC-4.

## Dependencies

- **FR-0006**: the commit step and FR-0006 AC-3's leftover-work helpers, which AC-3 reuses. FR-0006 is not revised. AC-3's `WARN` report is unchanged and still continues; the refusal here is a separate later step, and no sentence of FR-0006 changes meaning (ADR-0001 rule 2 checked).
- **FR-0009**: `_invalid_owns_entries` and the AC-2 withholding rule that makes every protected path off-limits for `dev`/`rev`/`bkf`.
- **FR-0010**: the grants this FR leaves untouched. DEC-0014 revises it (v4, non-breaking) to record why.
- **FR-0013**: `_finalize_base_branch`'s implementation-branch resolution for `rev` (AC-11), and AC-5(a), which DEC-0015 narrows and AC-1 implements.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file. This FR is dispatched in `mnt` mode, with the `owns:` above as the write surface; Neil's approval of this FR on 2026-09-25 is the approval for that edit. Edit `../../template/**`, never this project's bootstrap-output copy (AGENTS.md).
- **Permitted incidental edit (DEC-0014 Decision 4).** Replace the last sentence of `detected_stack_tools`'s docstring ("One call site so detection can be re-pointed later without touching every caller.") with one sentence stating that reading `REPO_ROOT` rather than the worktree is deliberate and citing DEC-0014. Nothing else outside the ACs' call sites changes.
- **Where the checks sit.** In `cmd_finalize`, AC-2, AC-3 and AC-4 run immediately after `_finalize_commit_step` and after `gat`'s early return, and before `_finalize_revalidate_stale_branch`. That placement matters: after AC-7's `origin/main` merge, `<base>...<branch>` could include upstream commits to protected paths (a template `--upgrade`) and refuse wrongly. AC-1 sits inside `_mnt_provenance_exemptions`, in the existing footprint block.
- **Threat model (DEC-0014).** These are detective controls against an agent that reaches for a workaround under pressure, not against an adversary. An interpreter can rewrite the AC-4 record too. The checks make a crossing visible and stop it before a PR; they do not make one impossible. Only a sandbox does that.
- **Reviewer dogfood (AGENTS.md).** Bootstrap a throwaway project from the modified template, give it `pyproject.toml`, `uv.lock` and `docker-compose.yml`, then:
  - as `mnt`, write `scripts/deploy-gate.py` via `uv run python -c …` and, where Docker is available, via `docker run -v`, once committed (FR-0013 AC-5 footprint check, and AC-1 when landed by a Reviewer fast-forward) and once left unstaged (AC-3); confirm both refuse;
  - rewrite `.claude/settings.local.json` and confirm AC-4 refuses;
  - report under `## FINDINGS` whether the harness blocked `uv run python -c` outright. DEC-0014 asserts it does not, from reading the code and not from a live probe.

  Delete the throwaway afterwards.
- **Which tests execute the real `cmd_finalize` (DEC-0017 Decision 6).** Four files run it:
  - `test_dispatch_finalize.py`, against a real temporary repository with a few seams stubbed (`_push_branch`, `_gh_preflight`, the `_finalize_*` legs, and a strict two-argument `mnt_footprint_violations`);
  - `test_dispatch_postapprove.py`, `test_dispatch_review_artifact.py` and `test_dispatch_gates.py`, each against a real repository plus a bare origin. They intercept only `gh`, so git runs for real, and a diff against a missing ref genuinely fails (hence Decision 1).

  `test_dispatch_runnability.py` and `test_dispatch_wave_finalize.py` never run it: they replace `cmd_finalize` with a double. Route AC-2 through `_git_capture`.
- **Pre-dispatch audit (2026-09-25).** AC-1 to AC-5 were prototyped exactly as v1 worded them, against a clean clone at `a8889df`, and run across all ten dispatcher test files. The result was 566 passing → 564, with the two red tests DEC-0017 names. v2 removes both, so an implementation that follows v2 is expected to leave all 566 green. Any other pre-existing red is AC-6's `## FINDINGS` line: stop the phase and route it to the Architect, never edit the test. Five implementation shapes are known to break byte-identity tests and are excluded by DEC-0017 Decisions 3 and 4:
  - reading the permission-file path from `adapter`;
  - a record store other than the call-time `DISPATCH_DIR`;
  - changing how the permission file is written;
  - putting the digest in the lock or `worktree_status`;
  - reusing or re-signing `mnt_footprint_violations`.
- **Footprint overlap.** In wave 2, FR-0015, FR-0016 (IDEA-0028) and FR-0018 (IDEA-0079) all own `template/scripts/dispatch.py` and run one at a time, in the order the Orchestrator sets. Neil confirmed on 2026-09-25 that this FR goes first (wave-2 plan §2.1). Each later FR rebases on the previous merge: the rebase-and-revalidate pattern in the architect role file. FR-0017 (IDEA-0078) does not touch `dispatch.py` and is not in this chain. AC-6's "today" means this FR's base at dispatch. The Chief of Staff sequences; tooling does not detect the overlap from this directory.
- **Interim, until this lands.** On any control-plane PR, read the Reviewer-authored commits by eye. AC-1's gap is open today in every project.

## Changelog

- 2026-09-25: created from IDEA-0083 (items 1–2 and FR-0010 finding (a); item 3 moved to IDEA-0084). Scope approved by Neil 2026-09-25 (D2, D3). Companion decisions: DEC-0014 (revises FR-0010, docker ruling and threat model) and DEC-0015 (revises FR-0013 AC-5(a), implemented by AC-1 here).
- 2026-09-25: Open questions only (no normative change, no version bump). Neil confirmed AC-2 as written, including its extension past D2 to `dev`/`rev`/`bkf` branches. The first Open question's protected-set gap is parked as IDEA-0088.
- 2026-09-25: v2 — DEC-0017 (breaking: false; no implementer yet), from the pre-dispatch test-pin audit:
  - AC-2's diff base falls back to `main` for a `rev` with no implementation branch, which keeps `test_dispatch_postapprove.py` L559 and L2364 green unedited;
  - AC-3's leftover-work read fails closed;
  - AC-4's record is placed under the call-time `DISPATCH_DIR`, hashes the bytes read back, and does not change how the permission file is written;
  - the `mnt_footprint_violations` call stays fixed;
  - Notes are corrected on which tests execute `cmd_finalize` and on the lane-A order;
  - `reads:` gains two test files.
- 2026-09-25: Notes only (no normative change, no version bump). Neil confirmed FR-0015 v2 goes first in wave-2 lane A.
