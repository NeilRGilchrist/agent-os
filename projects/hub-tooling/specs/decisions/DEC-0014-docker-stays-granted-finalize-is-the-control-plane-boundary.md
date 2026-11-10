---
id: DEC-0014
title: "`Bash(docker *)` stays in the stack-grant table for every role, `mnt` included. `mnt`'s command-level narrowing is friction, not a boundary; the control-plane boundary is the artifact-level check at finalize plus the human merge. Stack detection keeps reading the primary checkout."
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0013, FR-0015]
revises: FR-0010
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Exclude docker from mnt only (handoff option 1)"
  - "Grant docker to any role only when an accepted ADR's stack_tools: names it (handoff option 2)"
  - "Keep the default and add a WARN whenever docker is granted to mnt (handoff option 3 as written)"
  - "Exclude docker from mnt and WARN for dev/rev (handoff option 4)"
  - "Narrow every code-executing mnt stack grant to named subcommands (uv lock/sync, npm ci --ignore-scripts, docker compose up/down/ps/logs)"
  - "Re-point stack detection from REPO_ROOT to the role worktree (FR-0010 Reviewer finding g)"
reversibility: high
provisional_until: "a process sandbox or container confines dispatched agents (IDEA-0064); docker's grant must then be re-decided, because the daemon writes outside any process sandbox"
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  For `mnt`, docker is one of at least five grants that execute arbitrary code
  and reach a role-denied path. In Project A today, `uv run python -c` (AC-6 lifts
  the uv deny), `alembic upgrade` and the sanctioned `python -m pytest` over any
  owned file all do what the Reviewer's bind mount did. The last of these cannot
  be closed without stopping `mnt` from doing its job. Excluding docker would
  close one path, cost a breaking AC-4 revision and four pinned tests, and tell
  every later reader that `mnt`'s Bash surface is a security boundary, which it
  cannot be. The boundary is the artifact-level check at finalize, which already
  exists for `mnt` and which FR-0015 completes for every role, plus the human
  merge. Writes outside the worktree are accepted until IDEA-0064, at which
  point docker, the one grant a process sandbox would not confine, is
  re-decided.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0014: `Bash(docker *)` stays granted to every role; finalize is the control-plane boundary

## Context

FR-0010's second Open question asked whether `Bash(docker *)` should be granted at all, given that a container can mount the repo and write denied paths. The default was yes when the stack declares compose. `mnt` would get docker through AC-4's union while keeping every AC-6 deny, and the Reviewer's dogfood would probe it. The FR-0010 Reviewer did (`_dispatch/FR-0010.rev.REVIEW.md` finding (e), hub PR #4). A `docker run -v <worktree>:/wt …` appended to `scripts/deploy-gate.py` inside the `rev` worktree, a path `rev`'s deny list covers. The Reviewer let the default stand for `dev`/`rev`, where `Bash(python *)` already offers the same escape. It recommended excluding docker from `mnt`, whose "interpreter access is deliberately narrowed", or gating it behind an ADR. Neil deferred resolution to a follow-up PR. The Orchestrator's handoff (`_dispatch/handoff-architect-docker-grant-security.md`) set out four options without recommending one.

What made this non-obvious is that the finding is correct and the proposed fix is not. For `mnt`, "stack grant" and "interpreter" are the same thing. `MNT_BASH_NOT_INHERITED`'s own comment gives its reason: "Interpreters and package installers execute arbitrary code". Every entry of the stack-grant table matches that description. In a project declaring `python`, `uv`, `alembic` and compose (Project A's stack on 2026-09-25), `mnt` holds:

| Grant | How `mnt` gets it | How it writes a denied path |
|---|---|---|
| `Bash(uv *)` | FR-0010 AC-6 lifts the `uv` deny | `uv run python -c "…"` — `Bash(python -c*)` is prefix-matched and does not match a command that starts with `uv` |
| `Bash(alembic *)` | FR-0010 AC-4 union | `alembic upgrade` imports `env.py` and every migration module |
| `Bash(docker *)` | FR-0010 AC-4 union | a bind mount (live-probed by the FR-0010 Reviewer) |
| `Bash(node *)`, `Bash(npx *)`, `Bash(npm *)` | AC-6 / AC-4, when `package.json` is present | `node -e`, any package binary, `npm exec` and lifecycle scripts |
| `Bash(<venv-python> -m pytest*)` | `MNT_SANCTIONED_ENTRYPOINTS`, every stack | executes every owned module and test `mnt` just wrote |

Only the docker row has been probed live. The others are read from the permission derivation and the harness's prefix matching; FR-0015's Reviewer dogfood probes `uv run`. The last row does not depend on the stack at all. It cannot be closed, because running the suite over the code it changed is what `mnt` is for.

The code already knows this. `mnt_footprint_violations`' docstring says that write-time enforcement has holes ("any interpreter or shell construct the allow-list did not anticipate is a silent hole") and that the artifact-level check at finalize is what catches them. That check is the real control. What the finding exposed is that it has gaps. FR-0013 AC-5(a) exempts Reviewer-landed paths whatever they are (DEC-0015). `dev`, `rev` and `bkf` have no such check. Uncommitted changes are never examined. FR-0015 closes all three.

## Decision

1. **Docker stays in the table for every role, `mnt` included.** FR-0010 AC-3, AC-4 and AC-6 and the default of its second Open question stand as written. No AC text changes, no code changes, no test changes. FR-0010 is revised only to record this resolution (v4, non-breaking).

2. **The threat model, stated once so later grant decisions can cite it.** `mnt`'s command-level narrowing (`MNT_BASH_NOT_INHERITED`, `MNT_BASH_DENIES`, `MNT_SANCTIONED_ENTRYPOINTS`) is *friction against the casual reach*: the one-liner an agent under pressure types to make a red gate green. It is not a boundary and cannot become one. The control-plane boundary is two things:
   - the **artifact-level check at finalize**: `mnt_footprint_violations` today, extended by FR-0015 to Reviewer-landed paths, to `dev`/`rev`/`bkf` branches, to uncommitted worktree changes and to the permission file;
   - the **human merge**.

   A later proposal to narrow a Bash grant *for security* must name the escape it closes that the finalize check does not already catch. A narrowing that closes one of several equivalent paths is not adopted on security grounds. It may still be adopted for friction or for other reasons, and must say so.

3. **Accepted residual risk.** Any role holding any code-executing grant can write outside its worktree: to the primary checkout, other worktrees, or the user-level harness settings. Every role but `gat` holds one statically. No dispatcher check can see such writes, and they are accepted until a process sandbox or container confines dispatched agents (IDEA-0064). Docker is the one grant such a sandbox would *not* confine, because the daemon performs the write outside the sandboxed process. That is why this decision is `provisional_until` IDEA-0064: when a sandbox lands, docker's grant must be re-decided rather than inherited.

4. **FR-0010 Reviewer finding (g) is by design.** `detected_stack_tools` reads `REPO_ROOT`, the primary checkout, not the role worktree. Reading the worktree would let a branch widen its own grants by committing a marker (`docker-compose.yml`) or an `accepted` ADR declaring `stack_tools:`. Grants must come from state a human controls. The cost is that an FR which *introduces* a marker gets its grants only after it merges; that is accepted. FR-0015's Developer replaces the docstring sentence that invites re-pointing ("One call site so detection can be re-pointed later without touching every caller.") with one citing this DEC. That one sentence is the whole permitted edit (FR-0015 Notes).

5. **No `WARN`.** Option 3's observability line is not adopted. It would print on every Project A `mnt` spawn and say nothing FR-0015's refusals do not say better at the moment it matters.

6. **Disposition of the related findings.** FR-0010 finding (a), the malformed-`owns:` refusal only for `dev`, becomes FR-0015 AC-5. FR-0013 AC-5(a)'s reach is DEC-0015, implemented by FR-0015 AC-1. IDEA-0083 item 3, the implicit self-spec grant, moves to IDEA-0084: it *widens* a footprint, and FR-0015 only narrows.

**Why `neil`.** It is a security ruling, which the escalation matrix routes to the human in every case. It also resolves a Reviewer finding Neil explicitly deferred on PR #4. Neil approved Decisions 1–6 in the Architect session of 2026-09-25 (D1 and D3). There is no implementation PR to merge for this DEC, so it is recorded `ratified` on that approval.

**ADR-0001.** This is a revision, not a supersession (rule 5 checked: FR-0010's identity is untouched), and it is non-breaking (rule 3: the code at `main` already implements what this DEC confirms; no implementer must change). `version: 4`, `revisions` gains DEC-0014, and `last_breaking_revision` stays 3.

## Alternatives considered

- **Exclude docker from `mnt` only (option 1).** This was the Reviewer's recommendation and IDEA-0083's framing. Rejected. It closes one of at least five equivalent paths and leaves `uv run` and `alembic` open in Project A today. It costs a breaking AC-4 revision and edits to four pinned tests: `test_every_role_gets_every_stack_grant_and_no_deny_entry_moves[mnt]`, `test_mnt_allow_is_pre_fr_allow_plus_stack_grants`, the `mnt` half of `test_a_stack_grant_present_in_a_role_deny_list_is_written_to_both_never_hidden`, and `test_cursor_mnt_lifts_the_three_shell_denies_and_unions_shell_grants`. `mnt` would also lose `docker compose up`, though tests that shell out to docker would be unaffected, because the harness gates only the agent's top-level command. Worst, it would record in the spec graph that `mnt`'s Bash surface is a boundary, inviting the next reviewer to close the next path one at a time.
- **Grant docker only via an ADR `stack_tools:` (option 2).** Rejected. It leaves `mnt`'s other code-executing grants open. It also brings back FR-0010's motivating failure (Project A L18/L20: a Reviewer that cannot bring up the stack, two hidden defects) for every compose project until someone writes an ADR.
- **Keep the default and `WARN` (option 3 as written).** Adopted without the `WARN` (Decision 5).
- **Option 1 plus a `WARN` for `dev`/`rev` (option 4).** Rejected for both reasons above.
- **Narrow every code-executing `mnt` grant to named subcommands.** This is the only alternative that would make the command surface meaningfully narrower. Rejected: it leaks by construction (`uv sync` and `npm ci` run build backends and lifecycle scripts; a compose file declares its own volumes), it churns most of FR-0010's `mnt` tests, and the sanctioned `-m pytest` entrypoint still executes owned code.
- **Re-point stack detection to the worktree (finding g).** Rejected: Decision 4.

## Cascade

Non-breaking; no implementer must change. For the record:

- `projects/hub-tooling/specs/FR-0010-stack-aware-grants-and-lock-provisioned-venv.md`: the second Open question gains a "Resolved (DEC-0014)" line; a Notes entry for v4; `version: 4`, `revisions: [DEC-0003, DEC-0005, DEC-0014]`, `last_breaking_revision: 3` (unchanged), `updated: 2026-09-25`; one Changelog line. No AC text changes. Done in this commit.
- `template/scripts/stack_profile.py`, `STACK_BASH_GRANTS`, `CURSOR_STACK_SHELL_GRANTS`, `_union_grants`, `_mnt_bash_denies`: **no change.** FR-0015 AC-6 pins that.
- `template/tests/unit/scripts/test_stack_profile.py`, `test_dispatch_stack_grants.py`: **no change.**
- `template/scripts/dispatch.py::detected_stack_tools` docstring: one sentence, by FR-0015's Developer (Decision 4).
- FR-0015: created in this commit. It carries the finalize-boundary work this decision relies on, hence `constrained_by`.
- IDEA-0083: promoted to FR-0015; its item 3 is appended to IDEA-0084's Notes.
- Project A: no spec change. Until FR-0015 reaches Project A through `--upgrade`, read Reviewer-authored commits on control-plane PRs by eye.

## Changelog

- 2026-09-25: created and ratified. Neil approved the Architect's recommendation (D1: keep docker for every role and record the threat model; D3: finding (a) into FR-0015, finding (g) by design, item (iii) to IDEA-0084) in the hub-tooling Architect session.
