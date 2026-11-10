---
id: IDEA-0059
title: 'Review agent role: engineering-manager synthesis over dashboards (H9)'
status: parked
tags:
- template
- agent-team
- roles
- observability
- feedback-loop
- decision-rights
size: M
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0059: Review agent role: engineering-manager synthesis over dashboards (H9)

## Description

A periodic (weekly) agent role that reads the H7 dashboards, samples PRs and design docs against dashboard anomalies, and produces a synthesis: what is working, what is not, and proposed changes to ADRs, classification rules, slice compilation, SC authoring guidance, or agent prompts. Every proposal is a neil-tier DEC with revises pointing at the ADR or rule it changes and must cite both an efficiency and a quality signal; efficiency-only proposals are returned. The agent has no write access to ADRs, only DECs; its own mis-proposal rate is a dashboard. Ratified proposals land in the hub and reach every agent on the next compile. Depends on H6, H7, WS2, WS5.

## Originating context

Project A proposal cos-agent-hub-changes.md H9 (wave E), triaged via /cos 2026-09-07.

## Value hypothesis

The learning loop without model learning: the engineering department improves through ratified principle changes, so humans-govern-machines-propose applies to the factory itself, and the first ratified change is the trigger that justifies building the reverse leg (IDEA-0034).

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0041 there). Personal-project names generalised.

(none)
