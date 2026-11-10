---
id: IDEA-0055
title: Authority tiers, classification rules, foundational ADRs, and the decide-classify-flag
  agent default (WS2+WS3)
status: parked
tags:
- template
- decision-rights
- agents-md
- adr
- authority-tiers
- agent-team
- core-overlay
size: L
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0055: Authority tiers, classification rules, foundational ADRs, and the decide-classify-flag agent default (WS2+WS3)

## Description

WS2: authority tiers (agent / neil / client for the embedded profile; agent / neil / oliver / prospect-validate for greenfield-saas) with ordered first-match classification rules in AGENTS.md core, validated against a hand-labelled seed set (>= 90% agreement). Tier vocabulary and trigger additions live in the project overlay, so this depends on the AGENTS.md core/overlay split (IDEA-0034 phase 4). WS3a: initial ADR set (ADR-001 app-DB minimalism and data-source order, ADR-002 custom endpoint placement, ADR-003 role restriction is an FR concern, ADR-004 PHI boundary, ADR-005 client-visible decisions in outcome language, ADR-006 revision vs supersession), each with mandatory 'When you may deviate' and 'What you must record' sections. WS3b: AGENTS.md core replaces 'ask before deviating from an FR' with decide-classify-flag; a design doc is incomplete if any decision lacks tier, rationale, and an authorising ADR or exception; context is the compiled slice; set breaking honestly. WS3c: solution-design skill emits ## Decisions and ## For client review sections; the only permitted halt is a missing GOAL link or uncovered decision space, both logged as hub defects.

## Originating context

Project A proposal the decision-rights proposal (WS0-WS6) WS2 and WS3 (phase 2), triaged via /cos 2026-09-07. Depends on IDEA-0034 (core/overlay split, formerly IDEA-0015).

## Value hypothesis

Roughly half of agent halts in solution designs are technical choices the agent should have made within existing principles; declared authority plus exception-carrying ADRs converts halt-and-ask into decide-classify-flag so every delivered design is complete, with mis-tier rate and review-queue depth as the guardrails.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0037 there). Personal-project names generalised.

(none)
