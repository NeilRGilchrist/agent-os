---
id: IDEA-0072
title: Tracked home for wave learnings; demote wave --park-findings to opt-in
status: parked
tags:
- dispatch
- orchestrator
- process
- parking-lot
- template
size: S
created: '2026-09-20'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0072: Tracked home for wave learnings; demote wave --park-findings to opt-in

## Description

_dispatch/ is gitignored, so wave syntheses, learnings files, download audits and preserved reviews are local to one machine. wave --park-findings exists (dispatch.py _park_findings) but parks one IDEA per ## FINDINGS row with the placeholder value '(surfaced by a dispatched agent; triage before promote)', which breaks hub rule 5 and would have produced ~46 IDEAs from the FR-0001 wave. Proposal: a tracked, PHI-hook-checked runs directory in the template (e.g. specs/_runs/<wave-id>/ or .agent-team/runs/) that wave writes the synthesis and learnings into, exempted from the maintainer footprint check like specs/_metrics/**; /cos at the hub stays the clustering step; --park-findings stays opt-in and gains a --min-value guard or is removed.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L26; synthesis-2026-09-20 finding 6. Decision for the human: is --park-findings canonical? CoS recommendation: no. Touches template/.gitignore, template/scripts/dispatch.py wave output paths. Home: hub-tooling.

## Value hypothesis

This wave's 46 learnings and the audit exist only on one laptop, and the 2026-09-13 synthesis being local was why L1 had to be re-carried by hand; a tracked home makes every wave's learnings diffable, greppable by the next Orchestrator, and citable from IDEAs and DEC provenance. Keeping /cos as the clustering step avoids ~40 placeholder IDEAs per wave polluting the parking lot.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0054 there). Personal-project names generalised.

2026-09-25 (CoS): evidence from triaging hub-tooling wave 1 and the Project A FR-0016/FR-0002/FR-0003/FR-0004 waves. The learnings lived in four gitignored files (projects/hub-tooling/_dispatch/learnings-wave1.md, synthesis-wave1-2026-09-22.md, handoff-cos-dec-object-overload.md; a downstream project's `_dispatch/learnings-FR-0016-FR-0002-wave.md`) plus six per-session syntheses and handoffs: about 70 raw items, which came down to 10 new IDEAs (IDEA-0078..0087) and 5 appends. Several items had been flagged 'for the COS' days earlier (Project A L50, L57, L61, L62 on 2026-09-21) and reached the parking lot only because the human asked for a sweep; two conventions Neil confirmed (architect-tier ratify-by-merge, hub-script crossings) were recorded nowhere tracked (now IDEA-0087). A tracked learnings home with a per-item triage status would have made this a diff instead of a hunt through gitignored files.
