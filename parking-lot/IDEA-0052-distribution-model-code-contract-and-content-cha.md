---
id: IDEA-0052
title: 'Distribution model: code, contract and content channels, no model-triggered
  upgrades'
status: parked
tags:
- ai-productivity-toolkit
- distribution
- upgrade
- architecture
size: L
created: '2026-10-23'
updated: '2026-10-23'
last_reviewed: '2026-10-23'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0052: Distribution model: code, contract and content channels, no model-triggered upgrades

## Description

How schema, skills, prompts, policy layers and tooling reach each person's local KB. Three channels with separate cadences: code (versioned aitk releases via OS-scheduled job or user-run CLI, pinned and verified), contract (schema versions; MINOR needs nothing, MAJOR needs a local backed-up reversible migrate), content (per-layer bundles pulled from each layer owner; the personal layer is never pushed up). Skills may ride the org Claude Code plugin catalog. MCP may report version skew read-only but never triggers an upgrade (prompt-injection path to the guardrails). Promotion validates against the team KB's pinned schema. Secrets (e.g. an org-scoped token key) need the strictest channel; Okta AI Agents is the intended store.

## Originating context

CoS session 2026-10-23; user approved the direction. Needed for Phase 2 rollout; future ADR in ai-productivity-toolkit.

## Value hypothesis

Makes rollout beyond the three-person pilot safe and repeatable: every local KB stays on a supported schema and toolset without manual installs or model-reachable upgrade paths.

## Notes

(none)
