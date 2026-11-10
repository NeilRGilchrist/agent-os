---
id: DEC-0006
title: Pre-flight reaches the host through one dispatcher seam (`env_preflight.run_preflight`), `docker`'s absence is one finding (`docker-not-installed`), and the Windows app-control check is gated on a declared stack
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0011's PR merges
satisfies: []
constrained_by: [FR-0010]
revises: FR-0011
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave the seam implicit (a code fact) and fix the FR-0010 harness without stating the property in FR-0011"
  - "Use `--skip-env-preflight` / `DISPATCH_SKIP_ENV_PREFLIGHT` as the test isolation mechanism"
  - "Have every check honour a dedicated no-host environment variable so the dispatcher never needs stubbing"
  - "Emit both `tool-missing:docker` and `docker-not-installed:docker` for an absent docker binary, as a literal AC-3 reading requires"
  - "Run the Windows app-control check unconditionally on Windows, as a literal AC-4 reading requires"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0011 AC-10 promises that every test which passed before the FR still
  passes, and AC-9 promises pre-flight is read-only and bounded; neither says
  how a test that drives the dispatcher against a stack-declaring fixture is
  kept off the host. The implementation already has the answer — one
  module-attribute call, env_preflight.run_preflight, is the dispatcher's
  only route to the host, and each check takes its I/O as an injectable
  keyword — but a property nobody stated is a property the next refactor
  removes. Stating it makes FR-0010's harness stub (DEC-0005) traceable and
  gives every later dispatcher test the same rule. The two Developer
  judgment calls are confirmed as the FR's intent and the AC wording is
  corrected so a literal reading no longer contradicts them.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0006: Pre-flight reaches the host through one seam; `docker`'s absence is one finding; app-control is gated on a declared stack

## Context

FR-0011 is `ready`, dispatched in maintainer mode and implemented at `23020f2`. The Developer's `## ESCALATION` (cross-FR conflict with FR-0010's merged tests) is resolved by DEC-0005, whose fix on the FR-0010 side is to stub FR-0011's pre-flight in FR-0010's dispatcher harness. That fix is only honest if FR-0011 itself says the seam exists and what stubbing it guarantees; otherwise FR-0010's tests would rely on an accident of FR-0011's implementation, and a later FR-0011 refactor (say, inlining the check calls into `_run_env_preflight`, or `from env_preflight import run_preflight` at import time) would silently put eight merged FR-0010 tests back on the host.

Today the property holds by construction: `dispatch.py` does `import env_preflight` and `_run_env_preflight` calls `env_preflight.run_preflight(REPO_ROOT, tools, find_uv=_find_uv)` — one call, resolved as a module attribute — and every check in `env_preflight.py` takes its subprocess/`which`/socket/platform inputs as keyword parameters (`run=`, `which=`, `port_busy=`, `platform=`, `find_uv=`) so the module's own tests never touch the host either. AC-9 ("read-only and bounded") is where that belongs; it becomes a stated, testable clause.

The Developer's PR body also flagged two judgment calls for the spec owner. (1) AC-3 lists `docker` among the tools its generic PATH loop checks and says `tool-missing` is `block` "for `uv` and `docker`", while AC-2 already gives an absent docker binary its own, more specific `docker-not-installed` class (also `block`); the implementation reports it once, under AC-2's class. (2) AC-4 says "On Windows, pre-flight reads the host's application-control state" with no stack condition, while AC-10 says that for an empty stack "no check in this FR executes"; the implementation gates AC-4 on a non-empty stack so AC-10 holds literally. Both are the FR's intent; both are corrected in the AC text so a Reviewer reading literally does not demand the other behaviour.

Two mechanical findings from the same PR body belong in FR-0011's Notes: the `wave --dry-run` dogfood needs a throwaway with an `origin` remote (a bare repository on disk works and is not a repoint of an existing remote), and the "with Docker stopped" dogfood step has a headless-safe equivalent (a PATH without `docker`).

## Decision

FR-0011 is revised in place (`version: 2`, `breaking: false`):

1. **AC-9 gains the seam clause.** The dispatcher reaches the host for this FR's checks only through `env_preflight.run_preflight`, resolved as a module attribute at call time; each check's I/O is keyword-injectable. With that one name replaced by a stub returning a `PreflightResult` with no findings, `wave`/`tick`/`maintain` against a stack-declaring fixture spawn no pre-flight subprocess, bind no socket, print no `PREFLIGHT` line other than `PREFLIGHT OK`, and write `dispatch.spawn` records without a `preflight=` segment. A test harness driving those commands that is not testing pre-flight stubs the seam; one that is testing pre-flight uses the same seam to inject crafted findings (the FR-0011 Reviewer's route to `PREFLIGHT BLOCK`/`WARN`/`WOULD-BLOCK` and the AC-7 record shapes without a real host). The FR-0011 Reviewer pins the clause.
2. **AC-3 is corrected:** the generic PATH loop's list is `uv`, `node`, `npm`, `npx`, `pnpm`, `yarn`, `alembic`; `docker`'s absence is reported once, by AC-2's `docker-not-installed` (still `block`), never also as `tool-missing`. `tool-missing` is `block` for `uv` and `warn` for the rest. Severities are unchanged; only the double-report a literal reading required is removed.
3. **AC-4 is corrected:** the Windows check runs when the detected stack is non-empty; for an empty stack AC-10 wins and it does not run. (The check is a host attribute, not a per-tool one, so "any declared stack" is the gate, not a particular tool.)
4. **AC-10's last sentence is qualified:** every test that passed before this FR still passes, on any host — the ones that drive the dispatcher against a stack-declaring fixture doing so with the AC-9 seam stubbed (DEC-0005).
5. **`owns:` gains `template/tests/unit/scripts/test_dispatch_stack_grants.py`** with the write bounded to DEC-0005's cascade (the `_point` stub, its import, one docstring clause, one comment), for the Reviewer only — as DEC-0002 did for FR-0010 on `test_dispatch_permissions.py`.
6. **Notes** record the two judgment-call rulings, the `uv`-missing layering (DEC-0005), that `backfill` runs no environment gate, and the two dogfood mechanics.

`breaking: false`: the implementation at `23020f2` already satisfies every clause above — no line of `env_preflight.py` or `dispatch.py` changes, and FR-0011's own tests are not yet written. `last_breaking_revision` stays `null`.

`tier: architect`: FR-0011 is `ready`, dispatched but unmerged, and the Architect owns it; this states properties the implementation already has and corrects two AC sentences to the FR's own fixed points (AC-2's class specificity; AC-10's no-stack guarantee) without changing what the human approved. Recorded `proposed`; live for the design (indexer `LIVE_DEC_STATUSES`); ratified when FR-0011's PR merges, where it rides beside DEC-0005.

## Alternatives considered

- **Leave the seam implicit and fix only the FR-0010 harness.** Rejected: FR-0010's tests would then depend on an unstated fact about FR-0011's code, and the next FR-0011 refactor could put eight merged tests back on the host with no spec saying it must not. ADR-0001 rule 2 wants the guarantee written where it is made.
- **Use `--skip-env-preflight` / `DISPATCH_SKIP_ENV_PREFLIGHT` as the isolation mechanism.** Rejected: AC-8 requires the override to be *recorded* — one `PREFLIGHT SKIPPED` line and a `preflight=skipped` segment on every spawn record — so it changes exactly the record FR-0010's AC-7 test pins, and it would make an operator override double as a test switch.
- **A dedicated no-host environment variable honoured by every check.** Rejected: a second override with the same semantics as AC-8 minus the record, reachable from an operator's shell, is a foot-gun (a pre-flight silently skipped and *not* recorded is the failure AC-8 exists to prevent). The module-attribute seam is not reachable from outside the test process.
- **Emit both `tool-missing:docker` and `docker-not-installed:docker`.** Rejected: two findings for one condition, with the less specific class carrying a duplicate remedy; nothing downstream (the block decision, the `drop_reasons` entry, the human reading the log) is better for it. AC-2's class exists precisely to be the specific one.
- **Run the Windows app-control check unconditionally on Windows.** Rejected: it contradicts AC-10's "no check in this FR executes" for an empty stack and its "byte-identical to today" promise on every Windows host with an enforcing policy — the FR's safety property. The check is cheap but it is a check.

## Cascade

None — non-breaking. For the record, the artifacts this DEC touches:

- `projects/hub-tooling/specs/FR-0011-stack-aware-environment-preflight.md` — AC-3, AC-4, AC-9, AC-10 amended as above; `owns:` gains the bounded FR-0010 test file; `version: 2`, `revisions: [DEC-0006]`, `updated` bumped; Notes and Changelog. Done in this commit.
- `template/scripts/env_preflight.py`, `template/scripts/dispatch.py` — **no change**; `23020f2` satisfies the revised text.
- `template/tests/unit/scripts/test_env_preflight.py`, `test_dispatch_env_preflight.py` (FR-0011-owned; Reviewer, not yet written) — pin AC-9's seam clause (stub `env_preflight.run_preflight`, drive `cmd_tick` against a stack-declaring fixture, assert no subprocess/socket and no `preflight=` segment) and use the same seam to inject findings for AC-6/AC-7/AC-8/AC-9 dispatcher-level tests.
- `template/tests/unit/scripts/test_dispatch_stack_grants.py` — the DEC-0005 cascade edit, and nothing else.

## Changelog

- 2026-09-21: created (proposed) — companion to DEC-0005, from the FR-0011 maintainer-mode Developer's `## ESCALATION` and the two judgment calls flagged in its PR body (`23020f2`)
- 2026-09-21: updated (ratified) - By Neil Gilchrist during PR Review
