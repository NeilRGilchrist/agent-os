---
id: FR-0011
title: Stack-aware environment pre-flight — `wave`, `tick` and `maintain` check the host before spawning and classify what they find
status: merged
owner: architect
depends_on: [FR-0010]
tags: [dispatch, preflight, environment, windows, orchestrator, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/env_preflight.py
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_env_preflight.py
  - template/tests/unit/scripts/test_dispatch_env_preflight.py
  - template/tests/fixtures/env-preflight/**
  # v2 (DEC-0006): write bounded to DEC-0005's cascade — the `_point` harness stub of
  # `env_preflight.run_preflight`, its import, one docstring clause, one comment. Reviewer only.
  - template/tests/unit/scripts/test_dispatch_stack_grants.py
reads:
  - template/scripts/stack_profile.py
  - template/scripts/metrics_log.py
  - template/specs/_metrics/README.md
  - template/.agent-team/roles/orchestrator.md
  - template/.agent-team/commands/orchestrator.md
  - scripts/bootstrap.py
derived_from: IDEA-0068
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0006]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: []
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - Whether the checks live in a new `template/scripts/env_preflight.py` or inside `dispatch.py`, as long as each check is callable and testable in isolation without spawning an agent. The `owns:` above assumes the separate module.
    - Exact wording of the `PREFLIGHT` / `WOULD-PREFLIGHT` lines, as long as each carries the class, the resource and the remedy.
    - How the Windows app-control state is read (registry value, `Get-MpComputerStatus`-style query, or a policy API), as long as it is read-only, bounded by a timeout, and degrades to `unknown` rather than raising.
  fixed:
    - "Pre-flight never installs, starts, stops, configures or repairs anything. It reads state and reports."
    - "Every finding carries a class from a closed vocabulary. There is no free-text finding, and no finding without a class."
    - "A check whose stack marker is absent does not run, and its absence is not a finding."
    - "A blocking finding stops the run before any worktree, venv, branch or agent process is created."
    - "No new metrics record kind and no new metrics field: classifications ride existing string fields."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-20
updated: 2026-09-21
---

> **Provenance:** Drafted 2026-09-20 by the hub-tooling Architect from IDEA-0068 (Chief of Staff triage of the Project A FR-0001 wave, promotion confirmed by Neil 2026-09-20), grounded in Project A `_dispatch/learnings-FR-0001-wave.md` L8, L11, L21 and `_dispatch/audit-downloads-FR-0001-wave.md` §6. · source_class: neil_position+agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0011: Stack-aware environment pre-flight — `wave`, `tick` and `maintain` check the host before spawning and classify what they find

## Why

`wave`'s pre-flight checks exactly two things: that `gh` is on PATH and authenticated with an `origin` remote (`_gh_preflight`), and that no dead locks are lying around. Everything else about the host is discovered by an agent, mid-phase, as a failure. The Project A FR-0001 wave paid for that three times in ninety minutes. Docker Desktop's daemon was down at wave start, so the phase that needed the database burned a spawn and the Orchestrator started Docker by hand (L8). Windows Smart App Control silently refused to load the unsigned `psycopg_binary/_psycopg.pyd` and `sqlalchemy/cyextension/*.pyd` wheels, so the Developer — behaving correctly for a headless agent — swapped the database driver and documented why, which cost a decision record, a chore PR and a full Reviewer round, roughly fifty minutes, for a choice no ADR ever made (L11, audit §6). Host port 5432 was already taken by an unrelated project's Postgres, so a Reviewer test that reads `.env.example` through pydantic-settings failed against the ambient override while CI passed, and the round closed with an assumption record instead of a green suite (L21). Each of these is knowable in seconds from the host, before anything is spawned, and each cost twenty to fifty minutes once it was discovered afterwards — and landed in the metrics log as a semantic mystery rather than as a mechanical fault. On a laptop host, expect at least one per three waves: one and a half to three hours across the twelve remaining Project A FRs.

## What

After this FR lands, `wave`, `tick` and `maintain` run a stack-aware environment pre-flight against the host before they create a worktree or spawn anything. The checks are chosen by the stack FR-0010 detects, so a project with no compose file is never asked about Docker: the daemon's reachability when compose is declared, the presence on PATH of each declared tool, the host's application-control policy state on Windows, and whether anything is already listening on the host ports the compose file publishes. Each finding carries a class from a closed vocabulary and a remedy; blocking classes stop the run before any side effect, advisory classes print and continue. The classification reaches the `dispatch.wave` and `dispatch.spawn` records through the fields those records already carry, so a human reading the metrics log later sees `port-collision` rather than a test failure with no cause. An operator who knows better can override, and the override is recorded.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Findings are typed, and the vocabulary is closed.** Every check returns zero or more findings, each a structure carrying `cls` from the closed set `{docker-daemon-unreachable, docker-not-installed, tool-missing, app-control-enforced, port-collision, preflight-check-error}`, a `resource` string naming what was checked (a tool id, a port number, a policy name), a `severity` of `block` or `warn`, and a one-line `remedy`. There is no finding without a class, and constructing one with a class outside the set raises. The module exposes the set as a constant so tests and the dispatcher share it.

- **AC-2:** **Docker is checked only when the stack declares compose, and the two failure modes are distinguished.** When `docker` is in `detect_stack(repo_root)`, pre-flight runs a single bounded, read-only daemon probe. Docker absent from PATH yields one `docker-not-installed` finding; present but with an unreachable daemon yields one `docker-daemon-unreachable`; a reachable daemon yields none. Both failures are `severity: block` by default. When `docker` is not in the detected stack the probe is not executed at all — verified by asserting no subprocess was spawned — and its absence produces no finding.

- **AC-3:** **Each declared tool is checked for presence on PATH.** For every tool id in the detected stack that maps to an executable other than `docker` (`uv`, `node`, `npm`, `npx`, `pnpm`, `yarn`, `alembic`), pre-flight resolves it on PATH and emits one `tool-missing` finding per unresolved tool, naming the tool in `resource` and, in `remedy`, how the project declares it (the marker file or the ADR id from FR-0010 AC-2). `uv` resolution reuses the dispatcher's existing `_find_uv` fallback so a `~/.local/bin` install is not reported missing. `tool-missing` is `severity: block` for `uv` and `warn` for the rest. **Revised by DEC-0006 (v2):** an absent `docker` binary is reported exactly once, by AC-2's more specific `docker-not-installed` (`block`), never also as `tool-missing` — the v1 list named `docker` here too, which a literal reading turned into two findings for one condition.

- **AC-4:** **Windows application-control policy state is read, never assumed.** On Windows, when the detected stack is non-empty (**DEC-0006, v2:** AC-10 wins for an empty stack — this is a host attribute with no per-tool marker, so any declared stack is its gate), pre-flight reads the host's application-control state (Smart App Control and WDAC/Device Guard policy enforcement) with a bounded, read-only query and emits one `app-control-enforced` finding, `severity: warn`, when either is enforcing, with a remedy naming the observed policy and the consequence (unsigned compiled extension modules may fail to load, which an agent will experience as an import error and may work around by changing a dependency — see FR-0012's `## FINDINGS` rule). A query that fails, times out, or is unavailable yields one `preflight-check-error` finding, `severity: warn`, and never an exception. On non-Windows platforms the check does not run and produces no finding.

- **AC-5:** **Host port collisions are detected against the ports compose publishes.** When `docker` is in the detected stack, pre-flight parses the published host ports out of every `docker-compose*.y[a]ml` / `compose.y[a]ml` in the repo root by reading the file — the long form (`published:`) and the short `"HOST:CONTAINER"` form, with an environment-variable default (`"${DB_PORT:-5432}:5432"`) resolved to its default when the variable is unset — and attempts to bind each resulting host port. A port that cannot be bound yields one `port-collision` finding, `severity: warn`, whose `resource` is the port and whose remedy names the compose file and service. An unparseable compose file yields one `preflight-check-error`, `severity: warn`, and no port findings from that file. Verified against fixtures covering all three port spellings, a file with no published ports, and a malformed file.

- **AC-6:** **`wave`, `tick` and `maintain` run pre-flight before any side effect, and a blocking finding stops them.** In `wave` the pre-flight runs in Phase 0 after `_gh_preflight`; in `tick` and `maintain` it runs before `ensure_role_worktree`. When any finding has `severity: block`, the command prints one `PREFLIGHT BLOCK` line per blocking finding carrying the class, the resource and the remedy, exits non-zero, and creates no worktree, no branch, no venv, no lock file and no agent process. When every finding is `warn`, one `PREFLIGHT WARN` line is printed per finding and the run proceeds unchanged. With no findings, exactly one `PREFLIGHT OK` line names the checks that ran.

- **AC-7:** **The classification reaches the metrics log through existing fields.** When pre-flight blocks a `wave`, the wave still emits its `dispatch.wave` record, and `drop_reasons` carries one entry per blocking finding of the shape `{"fr_id": <id or null>, "phase": "preflight-env", "class": <cls>, "resource": <resource>}`, with `fr_count` reflecting the FRs that were selected and `completed`/`dev_only` zero. When pre-flight produces only warnings and the run proceeds, each spawn's `dispatch.spawn` record carries the warning classes appended to `worktree_status` as one comma-separated segment `preflight=<classes joined by '+'>`. No new record kind, no new top-level field, and `template/scripts/metrics_log.py` is not edited — verified by asserting the emitted records validate against the unmodified validator.

- **AC-8:** **Pre-flight is overridable, and the override is recorded.** `wave`, `tick` and `maintain` accept `--skip-env-preflight`, which skips every check in this FR (never `_gh_preflight`). The command then prints exactly one `PREFLIGHT SKIPPED` line, and the `dispatch.wave` record's `drop_reasons` — or, for `tick`/`maintain`, the spawn's `worktree_status` — carries the segment `preflight=skipped`. `DISPATCH_SKIP_ENV_PREFLIGHT=1` has the same effect and the same record. Nothing else about the run changes.

- **AC-9:** **Pre-flight is read-only and bounded, in apply mode and dry-run alike.** No check writes a file, starts or stops a service, installs anything, or mutates the repository; every subprocess and socket operation carries an explicit timeout, and the whole pre-flight returns within a bounded wall-clock budget even when every check fails. Without `--apply`, the checks still run (they are read-only) and their findings are reported on `WOULD-PREFLIGHT` lines; a blocking finding is reported as `WOULD-BLOCK` and the dry-run continues to print the remaining plan rather than exiting non-zero. After a dry run, `git for-each-ref`, every worktree's `git status --porcelain`, `_dispatch/` and `specs/_metrics/` are byte-identical to before. **Revised by DEC-0006 (v2) — host contact is contained in one seam:** the dispatcher reaches the host for this FR's checks only through `env_preflight.run_preflight`, which `_run_env_preflight` resolves as a module attribute at call time, and every check takes its I/O as keyword-injectable parameters (`run=`, `which=`, `port_busy=`, `platform=`, `find_uv=`) so the module is unit-testable without the host. With `env_preflight.run_preflight` replaced by a stub returning a `PreflightResult` with no findings, `wave`/`tick`/`maintain` against a stack-declaring fixture spawn no pre-flight subprocess, bind no socket, print no `PREFLIGHT` line other than `PREFLIGHT OK`, and write `dispatch.spawn` records with no `preflight=` segment. A test harness that drives those commands and is not testing pre-flight stubs that seam (FR-0010's `test_dispatch_stack_grants.py` does so under DEC-0005); one that is testing pre-flight uses the same seam to inject crafted findings.

- **AC-10:** **A project that declares no stack is byte-identical to today.** For a repo whose `detect_stack` returns `[]`, no check in this FR executes, no `PREFLIGHT` line other than `PREFLIGHT OK (no stack declared)` is printed, no finding is produced, and `wave` / `tick` / `maintain` behave exactly as they do before this FR. Every test that passed before this FR still passes, on any host — the ones that drive the dispatcher against a stack-declaring fixture doing so with the AC-9 seam stubbed (**DEC-0006, v2**; the edit itself is DEC-0005's).

## Out of scope

- Fixing anything pre-flight finds: starting the Docker daemon, installing a missing tool, freeing a port, or changing a Windows policy. Pre-flight reports; the human or the Orchestrator acts.
- Choosing an alternate port, or rewriting the project's compose file or `.env` to avoid a collision.
- Running agents in a container or WSL so host policy stops mattering (Project A L11(c); parked as IDEA-0064). That removes the `app-control-enforced` class entirely and is a different change.
- Any new metrics record kind or field, including a `preflight` kind. AC-7 is explicit that existing fields carry the classification.
- Checking GitHub, locks, or merged-PR reconciliation — `_gh_preflight` and `prune_dead_locks` already own those and are unchanged.
- Detecting the stack. FR-0010 owns `detect_stack`; this FR reads it.
- Health checks of anything inside a running container (migrations applied, schema present). Reachability of the daemon is the boundary.
- Classifying an agent run that ended with a question as `stopped-needs-input` (Project A L28). Same theme, different code path; not promoted yet.

## Open questions

- **Q:** Should a `port-collision` block rather than warn?
  - **Default:** Warn. In the FR-0001 wave the collision was survivable — Project A genuinely runs on 15432 — and blocking would have stopped a wave that went on to produce a merged PR. The finding plus the class in the metrics record is what was missing, not the refusal.
- **Q:** Should `tool-missing` for `node`/`npm` block, given a Reviewer that cannot run `npm ci` under-reviews a frontend FR (L20)?
  - **Default:** Warn (AC-3). FR-0010 grants the commands; whether the host has them is the human's environment. Promote to `block` only with evidence that a warned wave still produced an under-reviewed FR.
- **Q:** Should the compose port parse shell out to `docker compose config` for accuracy?
  - **Default:** No. AC-5 parses the file. Executing compose needs the daemon that AC-2 may have just reported down, and it is a side-effecting command in a read-only phase.
- **Q:** How should an unresolvable `${VAR}` with no default in a published-port spelling be treated?
  - **Default:** Skip that port, emit no finding for it, and include it in the `PREFLIGHT OK`/`WARN` line's list of ports that could not be resolved. Guessing a port produces false collisions.

## Dependencies

- **FR-0010** — hard. Every check is selected by `detect_stack`, and AC-3's remedy text cites the marker or ADR id FR-0010's detector recorded. Both own `template/scripts/dispatch.py`; FR-0010 lands first.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file; this FR is dispatched in `mnt` mode with the `owns:` above as the write surface, and the human's approval of this FR is the approval for that edit. `template/scripts/env_preflight.py` is new under `template/scripts/` and is not one of the four named protected scripts, but it is created in the same maintainer run. Edit `../../template/**`, never this project's bootstrap-output copy (AGENTS.md).
- **Why a separate module.** Three of the checks are platform-specific and all four are subprocess- or socket-bound. Keeping them out of `dispatch.py` is the architect role file's "extract-and-land-first" pattern and is what lets AC-1..AC-5 be tested without a dispatcher, a repo or an agent.
- **Footprint overlap.** FR-0008, FR-0009, FR-0010 and FR-0013 all own `template/scripts/dispatch.py`. Recommended order: FR-0009 -> FR-0010 -> FR-0011 -> FR-0013, FR-0008 rebasing last. FR-0012 can run beside them. The Chief of Staff sequences; the overlap is not tool-detected from this directory (AGENTS.md, "Hub-tooling specifics" 4).
- **Reviewer dogfood step (AGENTS.md).** Bootstrap a throwaway project from the modified template, give it a `docker-compose.yml` publishing a port you then occupy, run `dispatch.py wave --dry-run` and confirm the `WOULD-PREFLIGHT` / `WOULD-BLOCK` lines and that nothing was created; then run `tick --role dev --fr <FR>` with Docker stopped — or, since headless rules forbid starting or stopping services, with a `PATH` that omits the `docker` binary, which exercises `docker-not-installed` (the Architect did exactly this during the DEC-0005 escalation) — and confirm the block, the exit code, and that no worktree appeared. Confirm `--skip-env-preflight` proceeds and records the skip. **The throwaway needs an `origin` remote** for `wave --dry-run` to get past `_gh_preflight`: `git init --bare <tmp>/origin.git` and `git remote add origin <that path>` at bootstrap time is a new remote on a fresh repository, not a repoint of an existing one (the FR-0011 Developer's dogfood could not exercise `wave` because the host's auto-mode classifier denied adding a remote to a throwaway that had none; `tick`/`maintain` exercise the same `_run_env_preflight`). Delete the throwaway.
- **Rulings on the round-1 implementation (DEC-0006).** Two Developer judgment calls at `23020f2` are confirmed as the FR's intent and folded into the AC text: `docker`'s absence is one finding (AC-2's `docker-not-installed`, `block`), so `env_preflight.CHECKED_TOOLS` correctly excludes `docker`; and the Windows app-control check is gated on a non-empty detected stack so AC-10 holds literally. Also confirmed: the gate runs once per `tick` invocation (host-level, not per FR); in `maintain` it runs before FR-0010's `STACK` line so that line stays adjacent to `SPAWNED`/`WOULD-SPAWN`; `backfill` (`cmd_oneshot` with `role == "bkf"`) runs no environment gate because AC-6/AC-8 name only `wave`, `tick` and `maintain`.
- **Who decides on a missing `uv` (DEC-0005).** When the declared stack contains `uv` and the host lacks it, this FR's gate blocks (AC-3/AC-6) and `--skip-env-preflight` is the recorded override (AC-8). FR-0010 AC-9's soft-fail (`uv-not-found`, spawn proceeds with one WARN) is the provisioner's contract and stays live wherever `ensure_dev_venv` runs without `uv`: a project that does not declare `uv`, a skipped pre-flight, `backfill`, a direct `spawn_role` call. Neither AC changed severity; FR-0010 AC-9 (v3) says which layer it governs.
- **Not IDEA-0030.** The archived IDEA-0030 pre-flight was a gateway check and stays archived; IDEA-0064 (WSL clone) removes the `app-control-enforced` class rather than competing with this FR.
- **Evidence.** Project A `_dispatch/learnings-FR-0001-wave.md` L8 (Docker daemon down at wave start, one spawn lost, started by hand), L11 (Smart App Control blocked unsigned `.pyd` loading; silent driver substitution costing DEC-0031, PR #4 and a Reviewer round), L21 (host port 5432 taken, `.env.example` override, ASM-0017); `_dispatch/audit-downloads-FR-0001-wave.md` §6.

## Changelog

- 2026-09-20: created from IDEA-0068; promoted in the wave-1 Architect session Neil confirmed 2026-09-20
- 2026-09-21: v2 — DEC-0006 (breaking: false): AC-9 states the one host-contact seam (`env_preflight.run_preflight`, module-attribute call; keyword-injectable check I/O); AC-3 drops `docker` from the generic PATH loop (AC-2's `docker-not-installed` is its one finding); AC-4 gated on a non-empty stack (AC-10 wins); AC-10's last sentence qualified. `owns:` gains `template/tests/unit/scripts/test_dispatch_stack_grants.py` bounded to DEC-0005's cascade (Reviewer only). Notes: judgment-call rulings, `uv`-missing layering (DEC-0005), dogfood mechanics (`origin` remote for `wave`; PATH-without-docker for the block). No code change.
