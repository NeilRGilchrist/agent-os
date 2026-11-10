---
id: ADR-0002
title: Imported spec graph, reserved IDs, and the proposal framing the FRs cite
status: accepted  # proposed | accepted | superseded | rejected | deprecated — ratified by Neil 2026-10-23 (convergence decisions 1-7)
owner: architect
supersedes: null
superseded_by: null
created: 2026-10-26
updated: 2026-10-26
---

# ADR-0002: Imported spec graph, reserved IDs, and the proposal framing the FRs cite

## Context

FR-0001..0025, ADR-0001, DEC-0001..0026 and the reviews under `specs/_reviews/` were imported on 2026-10-26 from a separate hub snapshot, together with that hub's template and hub scripts. The two hubs keep evolving independently afterwards; this was a one-time copy, not a sync.

The imported FRs cite two proposals by item code: the **hub capabilities proposal** (H1–H13, delivered in waves A–F) and the **decision-rights proposal** (WS0–WS6). Both lived in a downstream project of the other hub and were not imported. Without a summary, the item codes in FR rationale, DEC context and IDEA titles are unresolvable from this hub.

## Decision

1. **IDs are kept, and the ranges are reserved.** FR-0001..0025, ADR-0001 and DEC-0001..0026 keep the IDs they had, so citations in tests (`@covers`), code (`@implements`), DECs and reviews still resolve. New work in this project starts at **FR-0026, DEC-0027 and ADR-0003**; this ADR takes ADR-0002, the first ID after the reserved range.
2. **Imported content is generalised, not rewritten.** Names of the other hub's personal projects became *Project A/B/C* or "a downstream project"; paths into those projects became neutral descriptions. Requirements, ACs, decisions and review verdicts are unchanged. Parked ideas cited as IDEA-0035..0071 in the other hub are IDEA-0053..0089 here (+18), and every citation was rewritten.
3. **Imported `merged` status describes the other hub.** The template code those FRs describe was imported in the same convergence and is what this hub now runs, so the FRs are accurate descriptions. Their `@covers` tests live in `../../template/tests/`, which this project's local gate cannot see until FR-0023/FR-0024 land (see AGENTS.md, "Hub-tooling specifics" item 2), so the local gate reports them uncovered. That is a known gap, not a regression.
4. **The proposals are summarised here, not reproduced.** The table below is the reference for item codes. It records only what the imported FRs and IDEAs say about each item.

### Hub capabilities proposal (H1–H13)

| Item | What it is | Where it lives here |
|---|---|---|
| H1 | Compiled context slices at dispatch: agents get the reachable subgraph of the spec graph, not the whole tree | IDEA-0053; FR-0005 provides `--slice` |
| H2 | Supersession-aware indexing: a live-only query surface and retired/provisional views | FR-0005 |
| H3 + H4 | Code and tests cite spec (backward traceability); success criteria as the binding contract | IDEA-0054 |
| H5 | Breaking-revision cascade generator (paired with WS4 gates) | IDEA-0056 |
| H6 | Pipeline instrumentation: an append-only per-project metrics log | FR-0002 |
| H7 + H8 | Dashboards as prescribed queries over the metrics log; a projection library | IDEA-0057 |
| H9 | Review agent role: engineering-manager synthesis over the dashboards | IDEA-0059 |
| H10, H11 | Discovery graph and spec boundary in the downstream project | Context only; nothing imported |
| H12 | Project-profile tier sets and foundational ADR packs | IDEA-0060; FR-0001 carves out the profile-aware `--upgrade` part |
| H13 | Reverse leg, project to hub (triggered, not scheduled) | IDEA-0034 (imported note) |

### Decision-rights proposal (WS0–WS6)

| Item | What it is | Where it lives here |
|---|---|---|
| WS0 | Baseline corpus | Client material; deliberately not imported |
| WS1 | Spec object schemas: shared versioning block (WS1a), FR solution-space fields (WS1c), ADR deviation sections (WS1d), the revision-vs-supersession rule (WS1e) | FR-0003, FR-0004, ADR-0001 |
| WS2 + WS3 | Authority tiers, classification rules, foundational ADRs, and the decide-classify-flag agent default | IDEA-0055; depends on IDEA-0034 phase 4 |
| WS4 | Decision-rights gates (paired with H5) | IDEA-0056 |
| WS5 | Client projections of decisions and per-tier review queues | IDEA-0058 |
| WS6 | Not cited by any imported FR | — |

## Consequences

- An FR, DEC or review that names an H or WS item resolves through this ADR.
- Imported `merged` FRs show as uncovered in this project's local gate until FR-0023/FR-0024 are delivered.
- The 16 `gate.run` records in `specs/_metrics/2026-09.ndjson` came from the other hub. They are kept append-only; only their `project` field was changed to `hub-tooling`.
- Divergence after 2026-10-26 is expected. Nothing here tracks the other hub.

## When you may deviate

Never for the ID reservation in Decision 1. Any FR, DEC or ADR minted in this project must use IDs above the reserved ranges.

## What you must record when you deviate

Deviation from Decision 1 is not permitted. For any other import from a separate hub, record a new ADR that states its reserved ranges and its renumbering map, as this one does.
