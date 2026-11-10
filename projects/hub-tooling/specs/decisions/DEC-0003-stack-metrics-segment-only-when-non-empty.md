---
id: DEC-0003
title: The `dispatch.spawn` record's `worktree_status` gains optional segments (`stack=`, `venv=`) only when they carry something; a no-stack, healthy-venv spawn record is byte-identical to today
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0010's PR merges
satisfies: []
constrained_by: [FR-0002]
revises: FR-0010
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Keep AC-7's unconditional `,stack=` append and relax FR-0002's two metrics assertions to prefix matches"
  - "Drop the metrics clause from AC-7 entirely: report the stack on the console line only"
  - "Append `stack=none` when the stack is empty, mirroring the console line"
  - "Add a new `stack` field (or record kind) to the `dispatch.spawn` schema"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0010 AC-7 was drafted as if the dispatch.spawn record carried the lock
  file's full status string; it does not — since FR-0002 the record carries
  the first segment only, and FR-0002's schema documents the field as the
  enumeration `created | reused`. Appending `,stack=` unconditionally changes
  every project's record, including the no-stack project AC-12 and the FR's
  What section promise is byte-identical to today, and would turn two merged
  FR-0002 tests into prefix matches for no FR-0002 reason. Appending a segment
  only when it has content keeps AC-12 true, leaves FR-0002's tests untouched,
  and matches the convention FR-0011 AC-7/AC-8 already use for `preflight=`.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0003: `worktree_status` gains optional `stack=` / `venv=` segments only when they carry something

## Context

FR-0010 AC-7 says the detected stack "is also appended to the `worktree_status` string the `dispatch.spawn` metrics record carries, as one comma-separated segment `stack=<ids joined by '+'>`", with no empty-stack rule — the console line's `stack=none` fallback is specified, the metrics segment's is not. The maintainer-mode Developer implemented it literally at `82a9467`: `spawn_role` emits `f"{wt_status.split(',')[0]},{stack=...}"`, so a project with no markers now records `created,stack=`. Two merged FR-0002 AC-3 tests in `template/tests/unit/scripts/test_dispatch_metrics.py` assert `rec["worktree_status"] == "created"` / `== "reused"` and fail. The Developer escalated: prefix-match the assertions, or revise AC-7.

Two facts settle it. First, the pre-FR-0010 dispatcher already normalised the metrics field: `write_lock` receives the full status string (`created,venv-created`, `reused,fast-forwarded,venv-reused`, ...) but `_metrics_emit("dispatch.spawn", worktree_status=wt_status.split(",")[0], ...)` deliberately reduced it to the base status, and FR-0002 AC-14's normative schema (`template/specs/_metrics/README.md`) documents the field as `created | reused`. AC-7 was drafted against the lock's shape, not the record's. Second, FR-0010's own AC-12 and its What section promise that "a project that declares no stack behaves exactly as it does today"; an unconditional `,stack=` breaks that for every such project's metrics log. AC-12 is the FR's safety property; AC-7's metrics clause was a convenience that must yield to it.

The same field has a second latent conflict in the same FR: AC-9's last sentence says "a failed sync leaves the classification in `worktree_status` on the `dispatch.spawn` record", which the `split(",")[0]` normalisation has never done (the classification reaches the lock file only). The code at `82a9467` does not satisfy that sentence either; the Reviewer would have found it next. It is the same question — what may this enumerated field carry beyond its base value — so this DEC answers it once, with one rule.

## Decision

The `dispatch.spawn` record's `worktree_status` value is the pre-FR base status (`created` | `reused`) followed by zero or more optional comma-separated segments, **each present only when it has something to say**, in this order:

1. `stack=<tool ids joined by '+'>` — present only when the detected stack is non-empty (FR-0010 AC-7). An empty stack appends nothing; `stack=none` is a console-line spelling, never a metrics one.
2. `venv=<classification>` — present only when `ensure_dev_venv` returned `(False, ...)` (FR-0010 AC-9). The value is the closed-set classification alone (`uv-not-found`, `venv-create-failed`, `lock-sync-failed`, `requirements-install-failed`, `packages-install-failed`), never the `:`-suffixed detail the function may attach and never a success string (`venv-created`, `venv-reused`, `venv-resynced`, or the pre-FR `venv reused` spelling). A successful or reused venv appends nothing.
3. Any further segment a later FR defines the same way — FR-0011 AC-7/AC-8's `preflight=<classes joined by '+'>` / `preflight=skipped` already follows this convention and goes after `venv=`.

Consequently a spawn in a project with no detected stack and a healthy venv records exactly `created` or `reused`, byte-identical to the pre-FR-0010 record — which is what AC-12 promises, what FR-0002's schema says, and what the two FR-0002 tests pin. Those tests are the AC-12 regression guard for this field and **do not change**. The lock file's `worktree_status` keeps the full status string as today (FR-0006's `test_dispatch_runnability.py:405` prefix match is unaffected).

One wording clarification rides along: AC-7's dry-run sentence now reads "on the `WOULD-SPAWN` line or the line immediately preceding it", matching the apply-mode sentence and the placement the round-1 implementation chose (a separate `STACK` line, forced by FR-0009's `owns-grants=<n>` end-of-line test). Not a behaviour change.

`breaking: true` under ADR-0001 rule 4: the implementation at `82a9467` appends unconditionally and must change; FR-0010's Reviewer tests for AC-7/AC-9/AC-12 must pin the new rule. FR-0010 goes to `version: 2`, `last_breaking_revision: 2`; AC-7, AC-9 and AC-12 are amended, and `owns:` gains `template/specs/_metrics/README.md` (the schema row must document the optional segments) and `template/tests/unit/scripts/test_dispatch_permissions.py` (moved from `reads:`; the write is bounded by DEC-0002's cascade).

FR-0002 is **not** revised. Its AC-3 text names the field without fixing its values; AC-14 requires every field to be documented, and the README row is updated by FR-0010 under this DEC, so both ACs stay true. Its tests are untouched. The README row edit is FR-0010's work, traced here.

`tier: architect`: FR-0010 is `ready`, dispatched but unmerged, and the Architect owns it; this corrects two ACs to the FR's own stated intent without changing what the human approved (the maintainer-mode edit to `dispatch.py` under this FR's `owns:`). Recorded `proposed`; it is live for the design (indexer `LIVE_DEC_STATUSES`) and is ratified when Neil merges FR-0010's PR, where it rides beside DEC-0002.

## Alternatives considered

- **Keep the unconditional append and relax FR-0002's two assertions to `.startswith(...)`.** Rejected: it edits two merged FR-0002 tests for a change FR-0002 never made, records `created,stack=` (an empty-valued segment) for every project without a stack, contradicts FR-0010 AC-12 and the FR-0002 schema row, and fragments any future `--group-by worktree_status` report into per-stack buckets for the base status. The saving — no further Developer round — is one conditional.
- **Drop the metrics clause from AC-7 and report the stack on the console only.** Rejected: the console line is not durable (`_dispatch/` is gitignored and overwritten per FR/role — FR-0002's Why), and FR-0011 will need the same field for `preflight=`; the segment convention has to be defined somewhere, and this FR is where the first segment lands. The record also has to carry the AC-9 venv classification regardless.
- **Append `stack=none` when the stack is empty.** Rejected: still changes every no-stack project's record (`created,stack=none`), so AC-12 still fails and the two FR-0002 tests still need editing; it only removes the empty-value wart.
- **Add a new `stack` field or record kind.** Rejected: FR-0010 AC-7 rules it out by design ("no new metrics field or record kind ... `metrics_log.py` is not edited"); the schema's kind-specific required-field tuples would change, and FR-0002 AC-1's validator and README would both need a revision for a value that fits the existing field.

## Cascade

Breaking; every affected artifact:

- `template/scripts/dispatch.py::spawn_role` (FR-0010-owned; Developer round 2) — build the metrics `worktree_status` as: base = `wt_status.split(",")[0]`; append `,stack=<ids joined by '+'>` only if `detected_stack_tools()` is non-empty; append `,venv=<classification>` only if some later segment of `wt_status`, split on `,`, has the form `<classification>` or `<classification>:<detail>` with `<classification>` in AC-9's closed set. `_stack_metrics_segment` may stay as the formatter. Nothing else in the function changes; the lock's `worktree_status` is unchanged.
- `template/specs/_metrics/README.md` (FR-0002 AC-14's schema; FR-0010's `owns:` gains it) — the `dispatch.spawn` row for `worktree_status` becomes: `created` \| `reused`, optionally followed by comma-separated segments present only when non-empty, in order `stack=<ids joined by '+'>` (FR-0010 AC-7), `venv=<classification>` (FR-0010 AC-9), then `preflight=...` (FR-0011). One row; no other README change. This file is also in FR-0008's `owns:` (`ready`, not dispatched); FR-0008 rebases last per the sequencing note in FR-0010, so the overlap is a documentation fact, not a conflict.
- `template/tests/unit/scripts/test_dispatch_stack_grants.py` (FR-0010-owned; Reviewer) — pin: (a) non-empty stack -> record ends `,stack=<ids joined by '+'>` and the base status is intact; (b) empty stack -> record equals the base status exactly; (c) `ensure_dev_venv` failure -> `,venv=<classification>` with no `:` detail, ordered after `stack=` when both are present; (d) success strings (`venv-created`, `venv-reused`, `venv-resynced`, `venv reused`) and `fast-forwarded` never produce a segment. The FR-0010 test module must clear `DISPATCH_STACK_TOOLS` in its isolation fixture so an operator's environment cannot leak into detection; the FR-0002 metrics tests rely on a marker-less `REPO_ROOT` and an unset `DISPATCH_STACK_TOOLS` for their byte-identity, which is the pre-existing contract of any test that runs the dispatcher.
- `template/tests/unit/scripts/test_dispatch_metrics.py` (FR-0002-owned) — **no change**. `test_spawn_emits_one_spawn_record_exports_run_id_to_the_agent_and_restores_the_environment` and `test_spawn_round_defaults_to_one_and_reused_worktree_and_model_override_are_recorded` pass under the revised rule and stay as the AC-12 guard for this field. Not in FR-0010's `owns:`; the Reviewer is not authorised to edit it.
- `projects/hub-tooling/specs/FR-0010-stack-aware-grants-and-lock-provisioned-venv.md` — AC-7, AC-9, AC-12 amended; `owns:` gains `template/specs/_metrics/README.md` and `template/tests/unit/scripts/test_dispatch_permissions.py` (the latter moved from `reads:`); `version: 2`, `revisions: [DEC-0003]`, `last_breaking_revision: 2`, `updated` bumped; Notes and Changelog. Done in this commit.
- `projects/hub-tooling/specs/FR-0011-stack-aware-environment-preflight.md` (`depends_on: [FR-0010]`) — no change required: AC-7/AC-8 already append `preflight=` conditionally; the segment order above places it after `venv=`. Its `reads:` already includes the README.
- FR-0002 — no revision (see Decision).

## Changelog

- 2026-09-21: created (proposed) — from the FR-0010 maintainer-mode Developer's `## ESCALATION` (FR-0002 AC-3 metrics tests vs FR-0010 AC-7, `82a9467`); AC-9's metrics sentence folded in as the same question
- 2026-09-21: updated (ratified) - by Neil Gilchrist upon PR review
