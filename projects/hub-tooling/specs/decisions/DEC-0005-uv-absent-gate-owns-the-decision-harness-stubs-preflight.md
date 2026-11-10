---
id: DEC-0005
title: A declared-but-missing `uv` is decided at FR-0011's pre-flight gate; FR-0010 AC-9's soft-fail governs the provisioner whenever it is reached — and FR-0010's dispatcher test harness runs with the pre-flight seam stubbed
tier: neil
status: ratified  # proposed | ratified | rejected | superseded — Neil ratifies at FR-0011 PR review
satisfies: []
constrained_by: [FR-0011]
revises: FR-0010
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Narrow the two failing FR-0010 assertions in place: segment-aware match on `worktree_status`, and `--skip-env-preflight` in the `uv`-absent test"
  - "Revise FR-0011 AC-3 so a declared-but-missing `uv` warns instead of blocks, leaving AC-9's soft-fail as the single reporting point"
  - "Revise FR-0010 AC-9 to 'the spawn proceeds only when pre-flight is skipped or `uv` is present' and re-pin its test through the gate"
  - "Delete or skip the two FR-0010 tests as superseded by FR-0011"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0010 AC-9 is the provisioner's contract (ensure_dev_venv never aborts a
  spawn it is asked to provision) and FR-0011 AC-3 is the gate's (a declared
  tool the host lacks stops the run before anything is created). They only
  collide in a test that drives cmd_tick end-to-end against the real host,
  and that test is host-dependent by construction under FR-0011 whatever its
  assertion says: on this machine it fails on a missing pnpm and an enforcing
  WDAC policy, and every stack_repo test in the same file fails as soon as
  docker leaves PATH. Scoping AC-9 to the layer it governs and stubbing the
  one pre-flight seam in FR-0010's harness keeps both ACs true, both
  approved product defaults unchanged, and the merged suite host-independent.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0005: A declared-but-missing `uv` is decided at the pre-flight gate; AC-9 governs the provisioner when it is reached; FR-0010's harness stubs the seam

## Context

FR-0011 (`depends_on: [FR-0010]`, in flight at `23020f2`) adds a stack-aware environment pre-flight to `wave`, `tick` and `maintain`. Its maintainer-mode Developer implemented all ten ACs as written and raised a `## ESCALATION` (cross-FR conflict): two merged FR-0010 Reviewer tests in `template/tests/unit/scripts/test_dispatch_stack_grants.py` fail under a correct FR-0011.

1. `test_env_declared_stack_reaches_console_and_record_with_plus_joined_ids` (FR-0010 AC-7) runs the real `cmd_tick` with `DISPATCH_STACK_TOOLS=alembic,pnpm` and pins `rec["worktree_status"] == "created,stack=alembic+pnpm"`. Under FR-0011 AC-7 the record on this host is `created,stack=alembic+pnpm,preflight=app-control-enforced+tool-missing` — `pnpm` is not on PATH and WDAC is enforcing, both genuine `warn` findings in FR-0011's closed vocabulary.
2. `test_uv_absent_spawn_proceeds_with_one_warn_naming_classification_and_lock` (FR-0010 AC-9) fakes `_find_uv -> None` against a `docker+node+npm+npx+python+uv` fixture and asserts `cmd_tick` returns 0 with one WARN and a `venv=uv-not-found` record. Under FR-0011 AC-3, `tool-missing` for a *declared* `uv` is `severity: block`, so `cmd_tick` returns 1 at the gate before `ensure_role_worktree` / `ensure_dev_venv` run.

The Architect reproduced both, then established the fact that settles the shape of the fix: **the two failures are the visible edge of a host dependency the whole file now carries.** Every FR-0010 test that drives `cmd_tick` / `cmd_wave` / `cmd_oneshot` against the `stack_repo` fixture (eight tests: `test_dev_tick_reports_stack_and_grant_count_in_dry_run_and_apply`, `test_rev_tick_bkf_and_mnt_oneshot_report_stack_before_their_spawn_line`, `test_wave_reports_stack_before_the_dev_spawn_line`, `test_env_declared_stack_reaches_console_and_record_with_plus_joined_ids`, `test_uv_absent_spawn_proceeds_with_one_warn_naming_classification_and_lock`, `test_dry_run_tick_wave_and_oneshot_create_no_venv_and_write_no_settings`, `test_dry_run_leaves_an_existing_worktree_byte_identical_even_when_grants_changed`, `test_detected_but_ungranted_tools_are_reported_and_grant_nothing`) now executes `docker info` and a PowerShell policy query on the test host. They pass on the Developer's machine only because Docker Desktop is installed with its daemon up. Re-running `test_dev_tick_reports_stack_and_grant_count_in_dry_run_and_apply` on the same machine with `docker` removed from PATH fails it with `PREFLIGHT BLOCK docker-not-installed` — a merged test the escalation did not name. A CI runner without Docker, or the WSL clone IDEA-0064 plans, fails the FR-0010 suite wholesale. Narrowing the two named assertions (the DEC-0002 shape) would leave that in place.

The second constraint is ADR-0001 rule 2: FR-0010 AC-9's sentence "the spawn proceeds ... never a spawn abort" is a normative claim that is now false for `wave`/`tick`/`maintain` on a project that declares `uv` the host lacks. FR-0010 is merged and human-approved; its text cannot quietly bend to FR-0011. It has to say which layer it governs.

## Decision

**Conflict 2 — layering, not a severity change.** Both ACs stand, each in its own layer:

- **The gate owns the decision to proceed.** When the *declared* stack contains `uv` and the host lacks it, FR-0011 AC-3/AC-6 block `wave`/`tick`/`maintain` before any worktree, venv, branch, lock or process exists. `--skip-env-preflight` / `DISPATCH_SKIP_ENV_PREFLIGHT` (AC-8) is the recorded override. This is the product default Neil approved with FR-0011 (AC-3's `block` for `uv` is a fixed AC, not an open question; the open question was `node`/`npm`), and FR-0010's own Why explains why it is right: an agent handed a worktree with no venv "either reports an unverifiable result or spends its turn trying to install packages it is denied" — a whole dispatched phase lost, knowable in seconds from the host.
- **The provisioner owns what happens when it is reached.** FR-0010 AC-9's soft-fail is unchanged: `ensure_dev_venv` returns `(False, "uv-not-found")`, the spawn it was asked to provision proceeds, one WARN names the classification and the file, the record carries `venv=uv-not-found`. That path remains live and meaningful: `ensure_dev_venv` needs `uv` to create *any* venv (lock, requirements or bare `VENV_PACKAGES`), so a project whose stack does not declare `uv` — a `requirements.txt`-only or marker-less project — reaches it with no gate in front; so does a skipped pre-flight, `backfill` (`cmd_oneshot` with `role == "bkf"` runs no environment gate — AC-6/AC-8 name only the three commands), and any direct `spawn_role` caller.

FR-0010 AC-9 is revised in place to say so (v3). No severity in FR-0011 changes; no code in either FR changes.

**Conflict 1 — the harness stubs the seam; no assertion is narrowed.** A unit test that drives the dispatcher must not depend on the test host's Docker daemon, PATH or Windows policy. FR-0011's `_run_env_preflight` reaches the host through exactly one name, `env_preflight.run_preflight`, resolved as a module attribute at call time (DEC-0006 makes that a stated FR-0011 AC-9 property). FR-0010's harness fixture `_point` — which already stubs `_gh_preflight`, `reconcile_merged_prs`, `prune_dead_locks` and `ensure_dev_venv` for the same reason — gains one stub of that name returning a `PreflightResult` with no findings. With the seam stubbed, both named tests pass **with their assertions untouched**: the AC-7 record is exactly `created,stack=alembic+pnpm`, and the AC-9 test exercises the provisioner's soft-fail in the layer it belongs to. The eight host-dependent tests become host-independent in the same edit.

`breaking: true` under ADR-0001 rule 4 and the DEC-0002 precedent: no implementer of FR-0010 changes (`ensure_dev_venv`, `spawn_role`, `ensure_role_worktree` are untouched), but the file that pins AC-9 must change for the suite to pass, and the cascade below bounds that edit so the FR-0011 Reviewer has no discretion to widen it. FR-0010 goes to `version: 3`, `last_breaking_revision: 3`.

`tier: neil`: FR-0010 is a merged control-plane FR whose implementation a human approved, and this revision scopes a guarantee that approval covered. Recorded `proposed`; per ADR-0001 rule 8 the design proceeds on it. Neil ratifies at FR-0011's PR review, where this DEC rides with DEC-0006. What Neil is ratifying, concretely: (a) a project that declares `uv` and lacks it on the host stops at the gate rather than spawning without a venv — FR-0011 AC-3 as approved; (b) FR-0010's dispatcher-level tests run with FR-0011's pre-flight stubbed. If Neil prefers a missing `uv` to warn, the change is one entry in `env_preflight._BLOCK_ON_MISSING` plus an FR-0011 AC-3 revision — this DEC's layering text stays correct either way.

## Alternatives considered

- **Narrow the two failing assertions in place (segment-aware `worktree_status` match; `--skip-env-preflight` in the `uv`-absent test).** Rejected: it fixes the two tests the escalation named and leaves eight merged tests running `docker info` and PowerShell on the host, one of which already fails on this machine with `docker` off PATH. It also turns the AC-7 test into one whose recorded segments vary by host — the opposite of what a `+`-joining pin is for — and makes the AC-9 test assert `preflight=skipped` in a record about venv provisioning.
- **Revise FR-0011 AC-3 so a declared-but-missing `uv` warns.** Rejected: it discards an approved product default to protect a test, and the default is the better one — FR-0010's Why is explicit about the cost of an agent with no venv, and FR-0011's Why is about paying that cost before a spawn rather than after. The FR-0010 test would still be host-dependent (its WARN-line count includes `PREFLIGHT WARN` lines, so `app-control-enforced` alone fails `len(warns) == 1` on Windows).
- **Revise FR-0010 AC-9 to "proceeds only when pre-flight is skipped or `uv` is present" and re-pin through the gate.** Rejected: it would make AC-9's text depend on a command-line flag of a later FR and still run the real gate in the test; the provisioner's contract does not change when a gate is put in front of it. The scoping sentence adopted here says who decides, without re-stating FR-0011 inside FR-0010.
- **Delete or skip the two tests as superseded.** Rejected under ADR-0001 rule 2: AC-7's `+`-joined record and AC-9's soft-fail are still FR-0010's guarantees and still worth pinning; only the harness needed to stop touching the host.

## Cascade

Breaking; every affected artifact:

- `projects/hub-tooling/specs/FR-0010-stack-aware-grants-and-lock-provisioned-venv.md` — AC-9 gains the v3 scoping paragraph (which layer decides; where the soft-fail remains reachable; the harness runs with the seam stubbed); `version: 3`, `revisions: [DEC-0003, DEC-0005]`, `last_breaking_revision: 3`, `updated` bumped; Notes and Changelog. Done in this commit.
- `template/tests/unit/scripts/test_dispatch_stack_grants.py` (FR-0010-owned; FR-0011's `owns:` gains it under DEC-0006 for exactly this edit) — the FR-0011 Reviewer is authorised to make **only** these changes, in FR-0011's Reviewer phase:
  - `_point(monkeypatch, mod, r)` gains one line stubbing the seam so no pre-flight check runs: `monkeypatch.setattr(env_preflight, "run_preflight", lambda *a, **k: env_preflight.PreflightResult())`, with `import env_preflight` added beside the existing `import metrics_log` / `import stack_profile` (the `sys.path` insert above them already makes it importable). The stub may equivalently target `mod.env_preflight`; it is the same module object.
  - The module docstring's "Harness:" paragraph may gain one clause: FR-0011's environment pre-flight is stubbed (DEC-0005).
  - `test_uv_absent_spawn_proceeds_with_one_warn_naming_classification_and_lock` may gain a one-line comment citing DEC-0005 (the gate, not this test, decides whether a declared-but-missing `uv` reaches the provisioner).
  - **No assertion, parametrisation, expected string, helper, fixture or `# covers` annotation otherwise changes.** In particular `test_env_declared_stack_reaches_console_and_record_with_plus_joined_ids` keeps `== "created,stack=alembic+pnpm"` and the `uv`-absent test keeps `== 0`, `len(warns) == 1` and `"created,stack=docker+node+npm+npx+python+uv,venv=uv-not-found"`. Both pass once the fixture stubs the seam; the Reviewer verifies this on a PATH without `docker` as well as with it.
- `template/scripts/dispatch.py::ensure_dev_venv`, `::ensure_role_worktree`, `::spawn_role` (FR-0010 implementers) — **no change**. AC-9's code is correct in its layer.
- `template/scripts/env_preflight.py::_BLOCK_ON_MISSING` (FR-0011) — **no change**: `uv` stays `block`. FR-0011 AC-3's severity is unchanged by this DEC (DEC-0006 clarifies its `docker` wording only).
- `template/tests/unit/scripts/test_dispatch_metrics.py`, `test_dispatch_runnability.py`, `test_dispatch_permissions.py`, `test_dispatch_finalize.py` — **no change**: they drive the dispatcher against marker-less repositories, so FR-0011 AC-10 short-circuits before any host contact. Not in FR-0011's `owns:`; the Reviewer is not authorised to edit them.
- `projects/hub-tooling/specs/FR-0011-stack-aware-environment-preflight.md` — the seam becomes a stated AC-9 property and `owns:` gains the FR-0010 test file (bounded as above). Done by DEC-0006 in the same commit series.
- FR-0013 and FR-0008 (`depends_on`/`extends` chains through FR-0010) — no text change; their future dispatcher-level tests against stack-declaring fixtures inherit the rule: stub the seam unless testing pre-flight itself.

## Changelog

- 2026-09-21: created (proposed) — from the FR-0011 maintainer-mode Developer's `## ESCALATION` (cross-FR test conflict with FR-0010 AC-7/AC-9 tests, `23020f2`); host-dependence of the wider `stack_repo` suite established by re-running a merged FR-0010 test with `docker` off PATH
- 2026-09-21: updated (ratified) - By Neil Gilchrist furing PR Review
