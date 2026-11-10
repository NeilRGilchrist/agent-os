---
id: FR-0014
title: Wave rev-finalize regression — both rev-leg `cmd_finalize` call sites pass `draft`, a signature-faithful regression test covers Phase 6 and the rework rev leg, a wave crash is visible (non-zero exit, traceback in the log, synthesis still written), and stdout flushes per phase
status: merged
owner: architect
depends_on: [FR-0006]
tags: [dispatch, control-plane, finalize, rework, observability, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_dispatch_wave_finalize.py
  - template/tests/fixtures/wave-finalize/**
reads:
  - template/scripts/metrics_log.py
  - template/tests/unit/scripts/test_dispatch_runnability.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_finalize.py
  - template/.agent-team/commands/orchestrator.md
  - scripts/bootstrap.py
derived_from: null
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0007]
last_breaking_revision: 2
supersedes: null
superseded_by: null
extends: [FR-0006]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - Whether the crash handling (AC-3, AC-4) is one `try`/`except` around the phase chain in `cmd_wave` or a per-phase wrapper, as long as every phase after Phase 0 is covered and the synthesis path is shared with the normal exit.
    - Whether per-phase flushing (AC-5) is `flush=True` on the phase-boundary prints, a `sys.stdout.reconfigure(line_buffering=True)` at `cmd_wave` entry, or an explicit `sys.stdout.flush()` helper, as long as AC-5's observable holds under redirection.
    - The exact exit code for a crashed wave, as long as it is non-zero and distinct from the existing `1` (dropped) and `2` (bad `--rounds`) codes; `3` is the proposed default.
    - Exact wording of the `CRASHED` / `<phase>-crash` markers, as long as each carries the identifiers the ACs name.
  fixed:
    - "Every rev-leg call of `cmd_finalize` forwards the wave's `draft` value unchanged; the Reviewer leg never re-derives or hard-codes it."
    - "A test double for `cmd_finalize` in the wave tests binds the real function's signature (`inspect.signature(dispatch.cmd_finalize).bind(...)`) before returning; a double that accepts `*a, **k` unconditionally does not satisfy AC-1 or AC-2."
    - "The crash handler never swallows the exception: the traceback is printed and the exit code is non-zero. It does not retry the phase, re-dispatch an agent, or touch git/GitHub."
    - "Dry-run (`apply=False`) mutates nothing: no synthesis file on crash, no metrics record, no flush-related side effect beyond stdout."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-21
updated: 2026-09-21
---

# FR-0014: Wave rev-finalize regression — both rev-leg `cmd_finalize` call sites pass `draft`, a signature-faithful regression test covers Phase 6 and the rework rev leg, a wave crash is visible, and stdout flushes per phase

## Why

The maintainer commit `4aba846` (mnt role) removed the default on `cmd_finalize`'s `draft` parameter, but only the *dev*-leg callers were updated. The two *rev*-leg callers — `cmd_wave` Phase 6 (`template/scripts/dispatch.py:6244`) and `_run_one_rework_round` (`:5752`) — still call `cmd_finalize(fr_id, "rev", apply=True, adapter=adapter)`. The template's own wave tests did not catch this because they stub `cmd_finalize` with `lambda *a, **k: 0` (`test_dispatch_runnability.py:552`), which accepts any call shape. The regression shipped to `Project A` via the FR-0010 upgrade (`118cc1c`) and surfaced as Project A learning L57 (`_dispatch/learnings-FR-0016-FR-0002-wave.md`): on the FR-0003 wave, `dispatch.py wave --rounds 2 --apply` crashed at Phase 6 with `TypeError: cmd_finalize() missing 1 required positional argument: 'draft'`, so the Reviewer's verdict was never posted, the staged tests were left uncommitted, the rework loop never ran, and no synthesis or `dispatch.wave` record was written. Two second-order failures made this expensive to diagnose: the Orchestrator observed exit code 0 with the traceback lost in the redirected stderr, and the wave's stdout was block-buffered under redirection so the log was empty until the process ended. The Orchestrator had to hand-mirror `finalize --role rev` plus a full rework round (L49). Every project that takes the next `--upgrade` inherits the same crash.

## What

After this FR, both rev-leg `cmd_finalize` calls forward the wave's `draft` value; a regression test drives `cmd_wave` in apply mode through Phase 6 — and, with `--rounds 2`, through the rework rev leg — against a stub `HarnessAdapter` and a `cmd_finalize` double that enforces the real signature, asserting that rev finalize ran and the `dispatch.wave` record was appended. Independently of this specific bug, an uncaught exception in any wave phase after pre-flight is no longer silent: the traceback is written to the wave's own stdout (i.e. the redirected log) as well as stderr, the synthesis report and `dispatch.wave` record are still written with the in-flight FRs marked as crashed at that phase, and the process exits non-zero with a code distinct from the existing "dropped" and "bad arguments" codes. Finally, `wave` flushes stdout at every phase boundary, so a redirected log shows phase progress while the wave is still running, regardless of whether the caller passed `python -u`.

## Acceptance criteria

- **AC-1: Phase 6 rev finalize passes `draft` and is covered by a signature-faithful regression test.** `cmd_wave`'s Phase 6 call to `cmd_finalize` for role `rev` passes `draft=<the wave's draft argument>` (in addition to `apply=True` and `adapter`). A test in `test_dispatch_wave_finalize.py` drives `cmd_wave(apply=True, draft=D, adapter=<stub HarnessAdapter>, fr_filter=[FR])` through Phase 6 in a temp project with a single ready FR, with `spawn_role`, `_wait_for_phase`, `_evaluate_agent_outcome` (returning `success` / `approve`) and the worktree helpers monkeypatched as the existing wave tests do, and with `cmd_finalize` replaced by a double that (a) calls `inspect.signature(dispatch.cmd_finalize).bind(*args, **kwargs)` and lets any `TypeError` propagate, (b) records each `(fr_id, role, bound.arguments)`, and (c) returns 0. The test asserts: the double was called once with `role == "rev"`, `apply is True` and `draft == D` for both `D=True` and `D=False`; `cmd_wave` returned 0; and the metrics dir (repointed via `metrics_log.METRICS_DIR` as `test_dispatch_metrics.py` does) contains exactly one `dispatch.wave` record with `completed == 1` and `dropped == 0`. The test fails against the pre-FR call site with the `missing 1 required positional argument: 'draft'` `TypeError`.

- **AC-2: Rework rev leg passes `draft` and is covered by the same kind of test.** `_run_one_rework_round`'s rev-leg call to `cmd_finalize` passes `draft=<the wave's draft argument>`. A test drives `cmd_wave(apply=True, draft=D, rounds=2, ...)` with the round-1 Reviewer outcome `request-changes` and the round-2 outcome `approve`, using the same signature-faithful double as AC-1. The test asserts: the double saw a `rev` call in round 1 and a `rev` call in round 2, both with `draft == D`; the dev-leg calls in both rounds also carry `draft == D`; `cmd_wave` returned 0; and the single `dispatch.wave` record has `rounds_ran[FR] == 2`. The test fails against the pre-FR call site with the same `TypeError`.

- **AC-3: A wave crash is visible — traceback in the log, non-zero distinct exit code.** When any phase of `cmd_wave` after Phase 0 (Phases 1–6, the rework rounds, or synthesis) raises an exception that the phase does not itself handle, `cmd_wave` (a) prints `CRASHED — <phase name>: <ExceptionType>: <message>` followed by the full `traceback.format_exc()` to **stdout**, flushed, and also writes the traceback to stderr; (b) returns a non-zero exit code distinct from `1` (some FR dropped, none completed) and `2` (`--rounds` out of range) — proposed `3`; and (c) `main()` propagates that code unchanged so `python scripts/dispatch.py wave ...` exits with it. A test monkeypatches `_evaluate_agent_outcome` to raise `RuntimeError("boom")` during Phase 6 and asserts, with stdout captured to a buffer (`capsys` or a redirected `io.StringIO`): the `CRASHED` line names Phase 6, the buffer contains `RuntimeError: boom` and the `Traceback (most recent call last):` header, and the return code is the crash code. A second parametrisation raises in Phase 3 (dev evaluate) and asserts the same shape. A test of `main()` with `["wave", "--apply", "--fr", FR]` (harness stubbed via `get_adapter`) asserts the process-level return value equals `cmd_wave`'s crash code.

- **AC-4: On a crash, the synthesis and `dispatch.wave` record are still written.** In apply mode, after printing the traceback (AC-3) and before returning, `cmd_wave` writes the synthesis report via `_write_wave_synthesis(...)` with `emit_record=True`, with every FR in `results_by_id` that has not already reached a terminal state (`completed_e2e`, or `dropped_at` set) marked `dropped_at = "<phase-slug>-crash"` (e.g. `rev-evaluate-crash`) and `drop_reason = "<ExceptionType>: <message>"`. The `dispatch.wave` record therefore lists those FRs under `drop_reasons` with that `phase`. The AC-3 Phase 6 test additionally asserts: the `_dispatch/wave-<ts>.md` synthesis file exists, its text contains the FR id and `rev-evaluate-crash`, and the single `dispatch.wave` record has `dropped == 1` and `drop_reasons == [{"fr_id": FR, "phase": "rev-evaluate-crash"}]`. In dry-run (`apply=False`) a crash still prints the traceback and returns the crash code but writes no synthesis file and no metrics record.

- **AC-5: `wave` flushes stdout at every phase boundary.** Each `--- Phase N: ... ---` banner, each per-FR outcome line printed inside a phase (`DROPPED`, `REVIEW-POSTED`, `PR-OPENED`, etc.), the rework-round banner, and the `CRASHED` line of AC-3 reach the underlying stream before the wave proceeds, even when stdout is a block-buffered file or pipe. A test runs `cmd_wave(apply=False, ...)` (dry-run is sufficient — the banners are the same code path) with `sys.stdout` replaced by an `io.TextIOWrapper` over an `io.BytesIO` with `write_through=False` and a large buffer, records the wrapper's `flush()` call count, and asserts at least one flush occurred after each phase banner (i.e. `flush_count >= number of "--- Phase" banners in the captured text`). A second assertion runs `python scripts/dispatch.py wave --fr FR` as a subprocess with stdout redirected to a file and `PYTHONUNBUFFERED` unset, lets it reach Phase 1 (dry-run exits there with no runnable work in the fixture), and asserts the file contains the `--- Phase 0: Pre-flight ---` banner — the subprocess check is the one that would fail on a block-buffered stdout that only flushes at exit if the process were killed mid-wave, so the Developer may substitute a kill-after-Phase-0 variant if the fixture cannot exit early. The orchestrator command text (`template/.agent-team/commands/orchestrator.md`) is **not** changed by this FR; the wave is self-sufficient. **Revised by DEC-0007 (v2, breaking):** the out-of-scope guard the Reviewer pinned on this AC — dry-run wave stdout byte-identical to the pre-FR-0014 dispatcher after normalising timestamps, elapsed times, synthesis file names and the repository path — compares the two dispatchers **with `rounds=1` passed explicitly on both sides**. The `--rounds` default is not part of what the guard pins: FR-0013 AC-8 sets it (2 from FR-0013 on) and specifies and tests that `--rounds 1` reproduces the single-pass behaviour exactly, which is the same fact this guard pins from the other side.

## Out of scope

- Any change to `cmd_finalize` itself, its `draft` semantics, or the dev-leg call sites (already correct; FR-0006 / `4aba846` own that behaviour).
- Post-approve fast-forward, REVIEW.md survival, declarable verdicts, footprint exemption for approved work — **see FR-0013**, which now depends on this FR and lands after it.
- A `wave --resume` / `rework FR-XXXX` entry point for re-entering a dropped wave (Project A L49 / OQ-0065) — a separate FR; park if not already parked.
- Making `wave` recover from a crash (retry the phase, re-spawn the agent, clean up worktrees or branches). This FR makes the crash *visible*; recovery stays manual.
- Changing `deploy-gate.py`, `metrics_log.py`'s schema, or the `dispatch.wave` record's field set beyond what `drop_reasons` already carries.
- Adding `-u` / `PYTHONUNBUFFERED` to the orchestrator command or any wrapper script (AC-5 makes the wave self-flushing instead; see Open questions).
- Replacing the `lambda *a, **k: 0` double in `test_dispatch_runnability.py:552` — that file is FR-0006's; the Developer may leave it as is. The new signature-faithful double lives in the new test module (and may be shared via a fixture in that module only).
- Delivering the fix to `Project A` / other projects — that is a `--upgrade` after merge, run by the human per the hub working agreement.

## Open questions

- **Q:** Should the orchestrator command additionally recommend `python -u scripts/dispatch.py wave ...` as belt-and-braces?
  - **Default:** No. AC-5 makes the wave flush itself so the fix travels with `dispatch.py` and does not depend on how it is invoked. Leave `orchestrator.md` untouched.
- **Q:** Should a crash in Phase 0 (pre-flight) or during argument validation also get the AC-3 treatment?
  - **Default:** No. Those paths already return `1`/`2` with their own messages before any agent is spawned, and no `results` exist to synthesise. AC-3 starts at Phase 1.
- **Q:** Exit code value for a crashed wave?
  - **Default:** `3`. Document it in `cmd_wave`'s docstring next to the existing meanings of `0`, `1`, `2`.
- **Q:** Should the crash also emit a `dispatch.run` record for the in-flight role (as the `timeout` branch does via `_emit_dispatch_run(fr_id, role, "timeout", None)`)?
  - **Default:** No. The `dispatch.wave` record's `drop_reasons` entry (AC-4) is the observability signal; adding a new `dispatch.run` outcome value would widen FR-0002's schema.

## Dependencies

- **FR-0006** — the rev-leg finalize behaviour, the `_run_one_rework_round` sync steps and the wave synthesis this FR guards are FR-0006's; `extends: [FR-0006]` and `depends_on: [FR-0006]` (merged, so no dispatch wait).
- **FR-0013** (reverse) — FR-0013 revises the same `cmd_finalize`/wave rev leg and now carries `depends_on: [FR-0006, FR-0011, FR-0014]`: land this fix first so FR-0013's Developer builds on a Phase 6 that actually runs, and so FR-0013's wave-driven tests can reuse the AC-1 signature-faithful double.

## Notes

- **Grounding.** `cmd_finalize` signature at `template/scripts/dispatch.py:3710` (`fr_id, role, apply, draft, adapter=None`); dev-leg callers at `:4199`, `:5722`, `:6130` and the CLI at `:6535` already pass `draft`; the two rev-leg callers at `:5752` (`_run_one_rework_round`) and `:6244` (`cmd_wave` Phase 6) do not. `cmd_wave` receives `draft` at `:5870` and `main()` derives it as `draft=not args.ready` at `:6548`. Line numbers are as of hub `f037978`.
- **Why the existing tests missed it.** `test_dispatch_runnability.py:552` stubs `cmd_finalize` with `lambda *a, **k: 0`; every existing `cmd_wave` test is either dry-run (Phase 6 never reached) or uses that double. Hence the `fixed` rule that any `cmd_finalize` double in the new module binds the real signature.
- **Why "traceback to stdout".** The Orchestrator runs `wave` with stdout redirected to a log (Project A L57: exit code observed 0, traceback lost in the redirected stderr, log empty until exit because of block buffering). Putting the traceback on the same stream as the phase output, flushed, guarantees the failure is in the artefact the Orchestrator actually reads, whatever the shell's redirect semantics.
- **Synthesis on crash (AC-4)** reuses `_write_wave_synthesis` unchanged; only the `WaveFRResult.dropped_at` / `drop_reason` values are new. `completed_e2e` FRs (both legs already finalized in an earlier round) are not re-marked.
- **Sequencing for the Chief of Staff.** Four ready FRs own `template/scripts/dispatch.py`: FR-0008, FR-0011, FR-0013, FR-0014. This one is small and blocks FR-0013; land it first, then FR-0011 → FR-0013, with FR-0008 sequenced by the COS. The footprint checker cannot see this overlap from the hub-tooling directory (AGENTS.md §4).
- Source of the requirement: Project A `_dispatch/learnings-FR-0016-FR-0002-wave.md` L57 (with L49 for the manual workaround). Regression introduced in `4aba846`, delivered to Project A in `118cc1c`.
- **DEC-0007 (2026-09-21).** The AC-5 byte-identity guard (`test_dispatch_wave_finalize.py::test_dry_run_output_is_byte_identical_to_the_pre_fr_dispatcher`) went red at FR-0013 `1cad878` because FR-0013 AC-8 changes the `--rounds` default; the whole diff was the two `rounds=` mentions and the `WOULD-RUN  Round 2/2` preview line. DEC-0007 narrows the guard to an explicit `rounds=1` on both sides and bounds the edit to that one argument plus a citing comment; FR-0013's `owns:` gains the file for its Reviewer only (DEC-0008). The flush tests, crash tests and bite checks in that file are unchanged.

## Changelog

- 2026-09-21: created from Project A learning L57 (Architect session, Neil's brief). AC-4 (synthesis + record still written on crash) is an Architect addition beyond the three candidate ACs in the brief — it is the cheap half of "the synthesis was never written" and reuses the existing synthesis path; drop it if unwanted.
- 2026-09-21: merged via hub PR #7 (`a984db3`); status merged
- 2026-09-21: v2 — DEC-0007 (breaking: true): the AC-5 byte-identity guard compares at an explicit `rounds=1`; the `--rounds` default is FR-0013 AC-8's. One FR-0014 test narrowed by one argument, in FR-0013's Reviewer phase.
