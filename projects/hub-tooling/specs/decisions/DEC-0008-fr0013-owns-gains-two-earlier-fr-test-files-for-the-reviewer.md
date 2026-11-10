---
id: DEC-0008
title: FR-0013's `owns:` gains the two earlier-FR test files its Reviewer must re-point — `test_dispatch_finalize.py` under DEC-0001's Cascade and `test_dispatch_wave_finalize.py` under DEC-0007's — for the Reviewer only and for exactly those edits
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0013's PR merges
satisfies: []
constrained_by: [FR-0006, FR-0014]
revises: FR-0013
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Treat DEC-0001's Cascade as sufficient authority and leave `test_dispatch_finalize.py` out of FR-0013's `owns:` (a Notes line only)"
  - "Have the FR-0006 and FR-0014 Reviewers (backfill runs) make the two edits under their own FRs' `owns:`"
  - "Widen `owns:` with a glob over `template/tests/unit/scripts/test_dispatch_*.py`"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  Two merged tests pin rules FR-0013 revises — FR-0006 AC-6's v1 overwrite
  (DEC-0001, ratified, whose Cascade already names the file, the fix and
  "FR-0013's Reviewer phase") and FR-0014's dry-run byte-identity at the
  `--rounds` default (DEC-0007). Both edits are the FR-0013 Reviewer's, and
  since FR-0010 AC-5 a Reviewer's write grants derive from `owns:`, so a
  cascade a DEC assigns to this Reviewer must also be in this FR's
  footprint or the Reviewer cannot make it. DEC-0003 and DEC-0006 did the
  same for FR-0010 and FR-0011; this DEC follows them and bounds each file
  to its DEC's cascade.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0008: FR-0013's `owns:` gains the two earlier-FR test files its Reviewer must re-point

## Context

FR-0013's maintainer-mode Developer implemented all ten ACs at `1cad878` with two red tests, both pins on earlier FRs:

1. `template/tests/unit/scripts/test_dispatch_finalize.py::test_review_md_overwrites_an_agent_authored_one_and_carries_the_round` (`# covers hub-tooling FR-0006:AC-6`) asserts the v1 always-overwrite rule DEC-0001 (ratified by Neil 2026-09-20) reversed. DEC-0001's Cascade already says what happens to it: "the `@covers FR-0006:AC-6` test asserting overwrite must be re-pointed at the new rule and gain the 'agent wrote one' case. Landed by FR-0013's Reviewer phase." The Developer escalated only because the file is not in FR-0013's `owns:` and maintainer mode does not write tests.
2. `template/tests/unit/scripts/test_dispatch_wave_finalize.py::test_dry_run_output_is_byte_identical_to_the_pre_fr_dispatcher` (`# covers hub-tooling FR-0014:AC-5`) compares dry-run stdout with the pre-FR-0014 dispatcher at the `--rounds` default, which FR-0013 AC-8 changes. DEC-0007 narrows that guard to an explicit `rounds=1` and bounds the edit.

The question this DEC answers is footprint, not behaviour: is a DEC's Cascade naming "FR-0013's Reviewer phase" enough for that Reviewer to edit a file FR-0013 does not own? It is not, for a mechanical reason. FR-0009 AC-4 and FR-0010 AC-5 derive the `dev`, `rev` and `bkf` write surfaces from the FR's `owns:`; a dispatched FR-0013 Reviewer has no `Edit`/`Write` grant on either file unless FR-0013 lists it. The precedent is already set twice: DEC-0002 bounded the FR-0009 test edit and DEC-0003 put `test_dispatch_permissions.py` into FR-0010's `owns:` "for exactly this edit"; DEC-0005 bounded the FR-0010 test edit and DEC-0006 put `test_dispatch_stack_grants.py` into FR-0011's `owns:` the same way. FR-0013 follows the pattern. Both files stay owned by their original FRs (FR-0006, FR-0014); FR-0013's ownership is additive, Reviewer-only, and limited to the two cascades.

## Decision

FR-0013 is revised in place (`version: 2`, `breaking: false`):

1. **`owns:` gains** `template/tests/unit/scripts/test_dispatch_finalize.py` — for the Reviewer only, write bounded to DEC-0001's Cascade as made exact below — and `template/tests/unit/scripts/test_dispatch_wave_finalize.py` — for the Reviewer only, write bounded to DEC-0007's Cascade.
2. **DEC-0001's Cascade item for `test_dispatch_finalize.py` is made exact** (DEC-0001 is ratified and is not edited; this DEC records the bound). The FR-0013 Reviewer is authorised to make **only** these changes in that file:
   - `test_review_md_overwrites_an_agent_authored_one_and_carries_the_round` is re-pointed at the v2 rule. It may be renamed to say what it now pins (for example `test_review_md_keeps_an_agent_authored_one_and_a_rerun_keeps_it_again`); the `# covers hub-tooling FR-0006:AC-6` annotation stays and may gain `# covers hub-tooling FR-0013:AC-2`. After `_finalize("rev") == 0` with the agent-committed `REVIEW.md` in place, it asserts: `git show claude/rev-<FR>:REVIEW.md` is the agent's text byte-for-byte (`"stale agent-authored text\n"`, 26 bytes); the branch head's subject is still the agent's commit (`reviewer wrote its own`) — no `review(<FR>): round N verdict=...` commit was added; stdout carries one `REVIEW-KEPT` line naming `REVIEW.md on claude/rev-<FR>`, the byte count (`26 bytes`) and the source (`branch`). The "agent wrote one, finalize re-run" case DEC-0001's Cascade calls for: a second `_finalize("rev")` returns 0, `git rev-parse` of the branch is unchanged, the file is still byte-identical, and `REVIEW-KEPT` is printed again.
   - The round-number assertion the v1 test carried (`review(<FR>): round 2 verdict=approve` from `_RUN_REGISTRY[(FR, "rev")]["round"] == 2`) is not lost: it moves to a scenario with **no** agent-authored `REVIEW.md` — either a second finalize in the same test over a fresh rev worktree, or a new test in the same file annotated `# covers hub-tooling FR-0006:AC-6` — where the synthesised commit is still made and its subject still carries the run-context round.
   - No other test, fixture (`repo`, `seams`, `_worktree`, `_stage`, `_write_rev_log`, `_finalize`), helper or annotation in that file changes. In particular `test_review_md_is_committed_before_push_with_the_posted_body`, `test_review_md_satisfies_the_rework_precondition_without_a_human` and every `mnt`-role test that relies on the `seams` fixture's 2-positional-argument `mnt_footprint_violations` stub are untouched; they pass at `1cad878`. The "agent staged one, uncommitted" case is FR-0013 AC-2's and lives in `test_dispatch_review_artifact.py`, not here.
3. **Notes** record the Architect's rulings on the Developer's implementation decisions (the AC-7 `wave` scoping in particular) so the Reviewer tests the reading the spec owner confirmed, and record two findings for later work.

`breaking: false` under ADR-0001 rule 3: the implementation at `1cad878` is correct after this revision — no AC text changes, no implementer changes, and the two cascades this DEC lets the Reviewer carry out are already recorded on their own DECs. `tier: architect`: FR-0013 is `ready`, dispatched but unmerged, the Architect owns it, and the footprint widening adds no policy — each added file is bounded to a cascade a `neil`-tier DEC already authorises (DEC-0001 ratified; DEC-0007 proposed, riding on the same PR). Recorded `proposed`; live for the design (indexer `LIVE_DEC_STATUSES`); ratified when FR-0013's PR merges, where it rides beside DEC-0007. Rule 5 does not apply — FR-0013's identity is unchanged; the footprint metadata catches up with what two DECs already assigned to its Reviewer.

## Alternatives considered

- **Treat DEC-0001's Cascade as sufficient authority; a Notes line only.** Rejected: authority and footprint are different things. DEC-0001 decides *what* changes and *who* lands it; FR-0009/FR-0010 decide what a dispatched Reviewer *can write*, from `owns:`. A Notes line leaves a Reviewer whose grants are derived from `owns:` unable to make the edit the DEC assigned it — the same gap DEC-0003 and DEC-0006 closed for FR-0010 and FR-0011. Hand-dispatched Reviewers (this project today) would not hit the wall, which is precisely why the metadata must not depend on that.
- **Have FR-0006's and FR-0014's own Reviewers (backfill runs) make the edits.** Rejected: both edits exist only because of FR-0013's behaviour change and both must land in FR-0013's PR for its suite to be green; a backfill on a merged FR that cannot pass until an unmerged FR lands is the wrong order, and it puts two extra one-shot runs where one bounded edit each will do.
- **A glob over `template/tests/unit/scripts/test_dispatch_*.py`.** Rejected: FR-0009 derives grants from `owns:` globs, so the glob would grant FR-0013's Reviewer every dispatcher test file, including FR-0002's, FR-0009's, FR-0010's and FR-0011's, none of which it may touch. Two explicit paths, each bounded to one cascade, is what a human reviewing the footprint should see (DEC-0004's reasoning).

## Cascade

None — non-breaking. For the record, the artifacts this DEC touches:

- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md` — `owns:` gains the two bounded test files; `version: 2`, `revisions: [DEC-0008]`, `updated` unchanged (same day); Notes and Changelog lines. Done in this commit.
- `template/tests/unit/scripts/test_dispatch_finalize.py` (FR-0006-owned; FR-0013 Reviewer, bounded as in Decision item 2).
- `template/tests/unit/scripts/test_dispatch_wave_finalize.py` (FR-0014-owned; FR-0013 Reviewer, bounded as in DEC-0007's Cascade).
- `template/scripts/dispatch.py` — **no change**; `1cad878` satisfies FR-0013 v2.
- `specs/decisions/DEC-0001-reviewer-authored-review-md-wins.md` — **no change** (ratified); its Cascade line for `test_dispatch_finalize.py` is bounded here rather than edited there.

## Changelog

- 2026-09-21: created (proposed) — from the FR-0013 maintainer-mode Developer's `## ESCALATION` (DEC-0001 test invalidation, `1cad878`) and the Orchestrator's escalation brief
