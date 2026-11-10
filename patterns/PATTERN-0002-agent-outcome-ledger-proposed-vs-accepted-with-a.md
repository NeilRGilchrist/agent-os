---
id: PATTERN-0002
name: 'Agent-outcome ledger: proposed vs accepted, with a fixed cause taxonomy'
status: accepted
tags:
- feedback-loop
- agent-effectiveness
- metrics
- convention
- pilot-metrics
created: '2026-10-22'
updated: '2026-10-22'
instances: []
ideas:
- IDEA-0016
- IDEA-0041
- IDEA-0044
- IDEA-0045
rejection_reason: null
---
# PATTERN-0002: Agent-outcome ledger: proposed vs accepted, with a fixed cause taxonomy

## Description

A shared convention plus a small library for recording what happens to agent output after a human sees it. Each record holds: the stable ID of the item (FR-XXXX:AC-Y, artifact ID, ticket key, session ID); a reference to what the agent proposed; what the human decided (accepted as-is / edited / overridden); a divergence class from a fixed core taxonomy that each project can extend (e.g. exact/partial/miss for decisions; defect/enhancement/external for spec revisions); cause and source citation; and the prompt or skill version that produced the proposal. Records are schema-versioned YAML/JSONL inside each project; a hub rollup (hub-index.py-style) aggregates counts and trends. Records are about artifacts and decisions, never people: no per-person fields, scores or rankings (aitk's employee-monitoring ban applies across the pattern). Distinct from golden-fixture eval harnesses (ai-hub-poc FR-0028, pm-graph-poc FR-0016), which test model output against fixed expected answers before shipping; this records what humans did with output after shipping, and could later supply those harnesses with fixtures. Members: IDEA-0016 (pilot and session outcomes; Claude Desktop-first for aitk), IDEA-0041 (spec revision cause), IDEA-0044 (FDE triage reconcile), IDEA-0045 (cross-session memory; reads the ledger). Build order: draft the convention, build the first instance (IDEA-0044 or aitk pilot measurement) against it, then generalise from what worked.

## Compounding-value hypothesis

Without a shared shape, the 3 recording ideas (IDEA-0016/0041/0044) each build their own format, cause list and rollup at roughly 1-2 days each, 3-6 days in total, and their results can't be compared. A shared convention costs about 2 days once and each new use about half a day, so 3.5 days instead of up to 6. The bigger payoff: the AI Transformation mandate needs a cross-initiative answer to 'how often is agent output accepted as-is, and why not when it isn't?' across the aitk pilot, FDE triage and the spec graph, and that number only exists if the records share a shape. Each later agent workflow (Docs role, CoS triage accuracy, future aitk skills) then adds to the same report instead of starting one, and IDEA-0045 gets its data and prompt-version provenance without extra work.

## Constituent signals

- IDEA-0016 — (fill in: how this fits)
- IDEA-0041 — (fill in: how this fits)
- IDEA-0044 — (fill in: how this fits)
- IDEA-0045 — (fill in: how this fits)

## Proposed shape

(fill in)

## Alternatives considered

- **Don't build it.** Cost: (fill in)

## Notes

(none)
