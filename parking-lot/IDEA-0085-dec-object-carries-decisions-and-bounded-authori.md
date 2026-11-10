---
id: IDEA-0085
title: 'DEC object carries decisions and bounded authorizations: add kind: decision or authorization
  and a spent status'
status: parked
tags:
- decision-rights
- indexer
- template
- adr
- versioning
size: M
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0085: DEC object carries decisions and bounded authorizations: add kind: decision or authorization and a spent status

## Description

Hub-tooling wave 1's DECs are three different things: durable rules (DEC-0001/0003/0006/0009/0011), guarantee narrowings (0002/0005/0007), and bounded authorizations - 'FR-N's Reviewer may edit these named test files, in exactly these ways' - that expire when the FR merges (0004/0008/0010). Symptoms: the tier question was re-litigated four times; DEC-0010 was minted partly to satisfy the indexer's version == len(revisions)+1 lint; ADR-0001 rule 8 retires DECs by last_breaking_revision, so ## Retired objects lists rules still in force while spent authorizations clutter the live log; breaking: true is true-by-construction on a footprint widening. The ratification route already differs by kind in practice (neil-tier: explicit act; architect-tier: rides the merge). Orchestrator's lean: a kind: discriminator (the indexer renders two tables, slices drop spent authorizations, tier semantics per kind) plus a spent lifecycle status set when the revised FR merges, and authorizations excluded from the last_breaking_revision arithmetic. Rule to make explicit: an authorization must also widen owns: or it cannot be executed. Keep the object: owns: is the permission surface since FR-0010 AC-5, so an auditable record of who authorised which agent to write which file is correct, and the bounded test-id lists made FR-0013's later rounds mechanical.

## Originating context

projects/hub-tooling/_dispatch/handoff-cos-dec-object-overload.md (hub-tooling Orchestrator, 2026-09-22, at Neil's request; options 1-4 cheapest first; lean 1+2). Related: IDEA-0071 (DEC retirement from status, not version arithmetic) - promote together, same indexer retirement code; IDEA-0053 (compiled slices make the noise load-bearing). Touches ADR-0001 (Architect), template/specs/_template/DEC-XXXX-template.md and template/scripts/index-specs.py (human approval). Lands after FR-0008 (merged). Home: hub-tooling. Proposed wave 3.

## Value hypothesis

3 of 13 wave-1 DECs were permission slips and 4 Architect passes re-argued tier; splitting the kind removes that recurring argument (~10 min per pass), stops lint-driven minting, and keeps the live decision log about rules before compiled slices (IDEA-0053) start handing it to every dispatched agent.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0067 there). Personal-project names generalised.

(none)
