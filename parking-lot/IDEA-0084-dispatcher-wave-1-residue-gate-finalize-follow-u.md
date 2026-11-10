---
id: IDEA-0084
title: 'Dispatcher wave-1 residue: gate/finalize follow-ups, output housekeeping,
  signature-faithful test doubles, dead-code lint'
status: parked
tags:
- dispatch
- control-plane
- gate
- finalize
- testing
- template
size: M
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0084: Dispatcher wave-1 residue: gate/finalize follow-ups, output housekeeping, signature-faithful test doubles, dead-code lint

## Description

Follow-ups named during hub-tooling FR-0008/FR-0013 that no FR owns: (1) the unfiltered tick --role rev discovers maintainer-mode FRs (FR-0013 AC-11's remaining leg); (2) the two gate-evidence readers should share one parse (FR-0008's bare 'gate pass' defect lived in the divergence); (3) the role files should document the gat gate-review mode; (4) gate-record relocation for dispatcher-invoked worktree runs; (5) output housekeeping - dry-run WOULD-REFUSE vocabulary, untracked REVIEW.md clobber WARN, extra= never passed, ff_commits WARN, and gate_warning_at_finalize accumulating across finalize attempts (any 'record of last outcome' field must be rewritten on every attempt); (6) finalize evaluates declared gates before pushing; (7) replace permissive stubs (lambda *a, **k: 0 for cmd_finalize in test_dispatch_runnability.py) with a shared signature-faithful double in conftest for every dispatcher call site tests replace - the permissive stub hid the FR-0014 / Project A L57 'draft' regression that crashed a Project A wave; (8) a 'no unreferenced functions in dispatch.py' lint - _finalize_gate_preflight had no caller from aacb473 until FR-0013 and turned out to gate the wrong checkout; (9) the template metrics README does not document the preflight-env drop phase (no owner; noted on hub PR #6).

## Originating context

hub-tooling _dispatch/synthesis-wave1-2026-09-22 follow-ups #4-#10; _dispatch/learnings-wave1.md FR-0013 and FR-0014 sections; _dispatch/handoff-cos-dec-object-overload.md follow-ups (i) and (ii); Project A handoff-hub-upgrade-2026-09-21-b (metrics README). Touches template/scripts/dispatch.py, its tests, role files and the metrics README (maintainer mode). Likely splits into two FRs: gate/finalize behaviour, and test-infra plus housekeeping. Home: hub-tooling. Proposed wave 3.

## Value hypothesis

Clears nine named follow-ups before they become the next wave's escalations; FR-0013 showed what deferred control-plane debt costs when it comes due (four Architect passes and ~5 h of wall time vs ~1 h for FR-0009), and the signature-faithful double alone would have caught a regression that crashed a Project A wave.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0066 there). Personal-project names generalised.

- 2026-09-25 (hub-tooling Architect): item (10) added, moved from IDEA-0083 item 3 — **implicit self-spec grant for the implementation role**. `fr_owns_globs` grants no `specs/<FR>-*.md` write. So a `mnt` (or `dev`) agent flipping its own FR's `status` on the role branch trips the footprint check unless `owns:` lists the spec, while the `rev` tick's eligibility for a `mnt` FR reads that very flip from the branch. Source: FR-0013 Notes follow-up (iii). It widens a footprint, so it was kept out of the restrictive FR-0015. Bound it to the FR's own spec file, and ideally to its `status:` line.

- 2026-09-25 (hub-tooling Architect, from the FR-0024 grounding audit): item (11). There is a **`dev` grant/deny depth asymmetry**, inferred from Claude Code's documented path rules and not yet probed live. `dev` is allowed `Edit(*.py)`, and a bare filename matches at any depth, but it is denied only `Edit(tests/test_*.py)`, which is anchored at the cwd. So nested tests such as `tests/unit/test_x.py` are probably writable by `dev` today in every project. Confirm with a live headless run, then either anchor the allow or deny `tests/**`. A deny change narrows a grant, so DEC-0014 Decision 2 applies: name the escape it closes that the finalize check does not already catch.
