---
id: DEC-0021
title: "FR-0002's Q4 flips: a gate or escalation-log run inside a dispatched agent's worktree appends its record to the primary checkout's log, not the worktree's, so role branches never carry metrics rows and the per-month files never conflict on GitHub (wave-2 plan §9.4, option (a))"
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0018]
revises: FR-0002
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "(b) one metrics file per branch or run, so two branches never write the same path"
  - "(c) keep rows on branches and document the local-merge step"
  - "Strip metrics paths from the agent's staged index at finalize"
  - "Honour the redirect variable unconditionally in metrics_log"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0002 chose a committed log with merge=union, expecting branch appends
  to merge cleanly. GitHub applies no merge drivers server-side, so every PR
  whose branch and main both appended rows conflicts. All 13 Project A PRs so far,
  and most of hub-tooling wave 1's, needed a local merge. The only rows that
  reach a role branch come from agents running the gate (or escalation-log)
  in their worktree, since the dispatcher already writes to the primary
  checkout. Sending those rows there too removes the conflict class while
  keeping the retry signal FR-0002 Q4 wanted, with the same run_id join. A
  guard (the emitting script's root must be the dispatched worktree) keeps
  test suites that copy the scripts into temporary repositories from
  following the redirect.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0021: Agent-worktree metrics rows go to the primary checkout's log

## Context

FR-0002 AC-8 declares `specs/_metrics/*.ndjson merge=union` "so concurrent appends on different branches merge without conflict". Its Q4 defaults "yes": a Developer's gate run "writes to the worktree's copy of the log, which lands on the FR branch … and merge[s] via `union`". Neil decided the log is committed (Q1, 2026-09-07).

GitHub does not apply merge drivers when it merges a PR, so the union rule never fires where it matters. Every PR whose branch and `main` both appended to the same month file shows a conflict and cannot be merged from the UI. That was Project A L62, and it still happens on every PR per Project A's 2026-09-25 handoff; hub-tooling wave 1 saw the same. The FR-0012 conduct rule "restore the metrics record before staging" is prose, it does not remove a new untracked month file, and agents break it under pressure.

The IDEA-0079 audit found that every dispatcher emit already writes to the primary checkout (`_metrics_emit` uses the default directory of the dispatcher's own `metrics_log`). The rows that reach a role branch come only from agents that run `scripts/deploy-gate.py` (or `escalation-log.py`) inside their worktree, whose `metrics_log` roots at the worktree.

The wave-2 plan §9.4 reserved the choice among (a) no rows on role branches, (b) one file per branch, and (c) documenting the local merge for Neil, if escalated. This DEC is that escalation, with a recommendation.

## Decision

1. **Option (a), made mechanical at the source.** When `spawn_role` spawns an agent, it exports two more variables beside `DISPATCH_RUN_ID` and `METRICS_PROJECT`, restored right after the spawn exactly as those two are:
   - `DISPATCH_METRICS_DIR`: the absolute path of the primary checkout's `specs/_metrics`.
   - `DISPATCH_WORKTREE`: the absolute path of the role worktree.

2. **`metrics_log` honours the redirect only from inside that worktree.** At import, `metrics_log.METRICS_DIR` becomes `Path(DISPATCH_METRICS_DIR)` when:
   - both variables are set; and
   - `metrics_log`'s own `REPO_ROOT` resolves to the same path as `DISPATCH_WORKTREE`.

   Otherwise it is `REPO_ROOT / "specs" / "_metrics"` as today. Precedence is unchanged: an explicit `metrics_dir=` argument, `--metrics-dir`, and a monkeypatched `METRICS_DIR` all still win. `deploy-gate.py` and `escalation-log.py` inherit the redirect through `metrics_log`'s default, so neither is edited. `index-specs.py` keeps reading `specs/_metrics` under its own tree for INDEX.md's metrics section, so a worktree's INDEX never renders the primary checkout's uncommitted rows.

3. **Rows are committed from `main` only**, as the FR-0012 conduct rule already says. The rule now describes the mechanism rather than an agent obligation.

4. **Kept unchanged:**
   - `merge=union`, which still helps local merges and is pinned by `test_metrics_log.py::test_gitattributes_declares_union_merge_for_month_files_and_git_applies_it`;
   - the month-file naming;
   - every record kind and field.

**`breaking: true`** (ADR-0001 rule 4). `metrics_log.py` must change, and Q4's default is reversed. FR-0002 goes to `version: 2`, with `revisions: [DEC-0021]` and `last_breaking_revision: 2`. Rule 5 was checked: FR-0002's identity, an append-only per-project metrics log, is unchanged.

**Why `neil`.** The wave-2 plan §9.4 names the metrics option as Neil's decision. It also reverses a default on an FR whose Q1 Neil decided. It is recorded `proposed` and live, and is ratified by Neil's approval of FR-0018.

## Alternatives considered

- **(b) One file per branch or run.** Rejected. It removes the path collision, but it multiplies files. It also breaks the month-file naming pins (`test_metrics_log.py` L402's exact glob; `test_deploy_gate_metrics.py`'s `_one_gate_record` readers), and the INDEX metrics section would still diverge. A later FR can revisit it if the primary checkout ever becomes unreachable from agents (IDEA-0064's sandbox).
- **(c) Document the local merge.** Rejected. That is the status quo, at about 10 minutes and one error-prone step per PR.
- **Strip metrics paths from the staged index at finalize.** Rejected. It breaks FR-0006's "commit the index verbatim" contract, and it cannot remove rows an agent committed itself without rewriting history.
- **Honour the variable unconditionally.** Rejected on evidence. Agents run the template suite inside their worktree with the variables inherited. Dozens of subprocess harnesses copy the scripts into temporary repositories and read that repository's log (`test_deploy_gate_metrics.py`, `test_deploy_gate_gates.py`, `test_metrics_log.py`'s `_esc`). Unguarded, every one would go red and write synthetic rows into the real log. The root-equals-worktree guard makes a copied script ignore the redirect.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0002-pipeline-instrumentation-metrics-log.md`, done in this commit:
  - AC-8 and Q4 each gain one sentence citing this DEC;
  - `version: 2`, `revisions: [DEC-0021]`, `last_breaking_revision: 2`, `updated: 2026-09-25`;
  - one Changelog line.
- `template/scripts/metrics_log.py`: the import-time resolution. `main()`'s `--metrics-dir` help text no longer calls `METRICS_DIR.relative_to(REPO_ROOT)`, which raises when the directory is outside the root. FR-0018 AC-2, **maintainer mode**.
- `template/scripts/dispatch.py::spawn_role`: the two variables. FR-0018 AC-1.
- `template/specs/_metrics/README.md`: where agent rows go, and the hand-added union line now points at FR-0020's managed block. FR-0018 AC-6.
- Tests: **none change.** The IDEA-0079 audit found no test that sets or asserts these variables. Every subprocess harness copies the scripts into a temporary repository, which the guard excludes. The in-process tests monkeypatch `METRICS_DIR`, which wins. FR-0018 AC-3 proves it by running the suite inside a worktree with the variables set.
- Unaffected: FR-0013 AC-5(b)'s `specs/_metrics/**` exemption, a path literal that still covers rows committed by hand; FR-0012's conduct bullet, whose text stays true.

## Changelog

- 2026-09-25: created (proposed) with FR-0018 — the wave-2 plan §9.4 metrics choice, escalated to Neil with option (a) recommended.
- 2026-09-25: ratified by Neil, with his approval of FR-0018. Option (a) confirmed for the wave-2 plan §9.4 metrics choice.
