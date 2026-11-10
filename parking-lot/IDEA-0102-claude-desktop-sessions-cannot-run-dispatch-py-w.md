---
id: IDEA-0102
title: 'Claude Desktop sessions cannot run dispatch.py wave --apply: spawned claude
  -p fails with 401'
status: parked
tags:
- dispatch
- harness
- auth
- orchestrator
- desktop
size: S
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0102: Claude Desktop sessions cannot run dispatch.py wave --apply: spawned claude -p fails with 401

## Description

A Desktop-hosted session authenticates through the app: its environment carries ANTHROPIC_BASE_URL (app proxy), ANTHROPIC_AUTH_TOKEN and a host-auth-refresh flag. claude -p children inherit these, cannot authenticate, and exit 401 'Not logged in' (apiKeySource: none). A terminal claude session uses the stored CLI login and works. Inference from the environment and the dev log, not yet tested variable by variable. Options, undecided: (a) ClaudeCodeAdapter.spawn drops host-injected auth variables so children fall back to the stored login; (b) the orchestrator role is documented as terminal-only, with the escalation route to the CoS stated. Either way, preflight should detect the condition before spawning.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; first Orchestrator-session trial; related IDEA-0086 (env passed to spawned agents)

## Value hypothesis

Lets an Orchestrator session in the Desktop app run waves itself, so the human is no longer the relay for every spawn and the Sonnet-orchestrator / Opus-CoS split works end to end.

## Notes

(none)
