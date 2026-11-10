---
id: IDEA-0077
title: 'Chore lane: a lightweight dispatch path for hygiene changes without a DEC,
  new ACs, or a full adversarial Reviewer round'
status: parked
tags:
- dispatch
- template
- process
- cost
- chore-lane
- decision-rights
size: M
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0077: Chore lane: a lightweight dispatch path for hygiene changes without a DEC, new ACs, or a full adversarial Reviewer round

## Description

Today the only way to land a hygiene change (line endings, a lint scope string, a dependency pin, a README command) is the full FR path: a DEC that revises the FR, new numbered ACs, a provenance row, index regeneration, a maintainer spawn, a Reviewer round writing adversarial tests per AC, and a gate that is red on coverage-missing from the spec commit until those tests land. Add a declared chore lane: an FR (or the Architect on a merged FR) may tag a change 'chore' with a checklist instead of ACs; the dispatcher runs it as a single maintainer phase with a bounded Reviewer scope (verify the checklist, run the gate, no new @covers required; the gate's coverage check treats checklist items as non-AC); DEC minting stays optional and is required only when the change bends a ratified ADR or an AC's meaning; finalize accepts the chore's declared footprint including content-free crossings (renormalise, generated stubs). Sessions for chore work get a compiled slice (IDEA-0053) or a minimal read list instead of the full AGENTS.md/roles/ADR/DEC-template read.

## Originating context

Neil's question after the DEC-0036 round, 2026-09-20: why did a line-endings fix cost this much? Numbers from the subagent usage reports in the CoS session. Related: IDEA-0053 (compiled context slices, the read-cost half), IDEA-0067 (finalize footprint exemptions), FR-0008 (declared gates: a chore lane is a gate declaration of 'checklist' instead of 'AC coverage'). Touches template/scripts/dispatch.py, deploy-gate.py, the FR template and role commands (human-approval). Home: hub-tooling.

## Value hypothesis

The Project A DEC-0036 round on 2026-09-20 (two lines of .gitattributes, one ruff scope string, two pyproject excludes; a human does it in ~15 min) cost ~560k tokens and ~40 min of agent time: Architect 240k/19 min, maintainer attempt+retry 133k+/11 min, Reviewer 188k/12 min writing 20 tests for two ACs, plus a dispatcher failure and a hand-opened PR. Roughly a third to a half of each session was cold-start reading. A chore lane at one maintainer phase plus a checklist review would land the same change in ~150k tokens and ~15 min; over the 12 remaining Project A FRs, hygiene re-entries at the observed rate (2 in the first 2 FRs) save ~2-3 h and ~2M tokens, and stop the 'spec commit turns the gate red' window for changes that never needed an AC.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0059 there). Personal-project names generalised.

(none)
