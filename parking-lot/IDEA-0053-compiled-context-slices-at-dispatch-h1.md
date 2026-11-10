---
id: IDEA-0053
title: Compiled context slices at dispatch (H1)
status: parked
tags:
- template
- dispatch
- indexer
- context-slices
- agent-team
- decision-rights
size: L
created: '2026-09-07'
updated: '2026-09-20'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0053: Compiled context slices at dispatch (H1)

## Description

dispatch.py asks the spec indexer for a slice before invoking a delivery agent: the subgraph reachable from the assigned FR/TR (linked GOAL and success criteria, applicable ADRs by decision-space tag, live DECs since last_breaking_revision, data elements, role definitions, project overlay), serialised as one context document sized to the task. The agent receives the slice and nothing else from the spec repo. Slice misses are logged via the existing ## FINDINGS channel (H6) rather than worked around. Depends on WS1 schemas and H2 live-only indexing; pairs with the AGENTS.md rule 'do not walk the spec repo' (WS3b). Done when a delivery agent can complete a TR task with zero file reads outside its slice.

## Originating context

Project A proposal the hub capabilities proposal (H1-H13) section H1 (wave B), triaged via /cos 2026-09-07. Same move as the integration-viz compile skill, applied to spec.

## Value hypothesis

Minimum agent context by construction instead of by agent discipline: a stale or irrelevant spec object physically cannot reach an agent because the compiler never emits it, removing the maze problem before the Project A spec repo exceeds a few dozen objects.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0035 there). Personal-project names generalised.

**2026-09-20 amendment (Neil, after the TypeSafe Jev fit assessment for Project A):** add a semantic pre-filter on top of the structural slice. The compiler's reachable set is the *candidate* list; before serialising, hand the assigned FR text plus each candidate object's frontmatter and purpose line (what `index-specs.py` already emits) to a cheap System One classifier (TypeSafe Jev) as one request: a Noul per candidate, "does this object bear on this task?", with a relevance threshold and confidence-gated inclusion. Fifty candidates fit in one request under Jev's 32k state limit, ~100 ms, cost rounds to zero. Rationale: the expensive thing in a dispatch run is the working agent's context re-sent every turn (the one recorded FR-0015 dev run pulled ~14M input tokens over 89 tool calls, 20 of them file reads), so every object kept out of the slice compounds. Constraints: (1) Jev reads literally, so a relevance miss is silent; the existing rule that slice misses are logged via the findings channel is the backstop, and a miss is a labelled example for tuning the threshold. (2) State must never include unscrubbed discovery transcripts (US-hosted model); spec objects are `project_original`, no PHI, so this use is clean. (3) The TypeSafe skill needs an `ip_class` line under ADR-0003 before commit. Companion: the dynamic per-dispatch model-routing idea parked the same day.
