---
id: IDEA-0103
title: 'Wave outcomes surface as escalations: auth failures, timeouts and total drops
  are not reported as success'
status: parked
tags:
- dispatch
- wave
- orchestrator
- escalation
- observability
size: S
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0103: Wave outcomes surface as escalations: auth failures, timeouts and total drops are not reported as success

## Description

Observed in Wave 4: a 401 spawn is reported as 'agent error: success' (only the raw log shows the cause); a wave that drops every FR exits 0 and its synthesis says 'Open Escalations (none)'; a Reviewer killed at the phase timeout is only visible in the per-FR line. Proposal: classify spawn failures (auth, timeout, permission) in the wave output, mark them mechanical, list every dropped FR under Open Escalations, and exit non-zero when nothing completed.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; Orchestrator trial friction 1, 2 and the Reviewer timeout

## Value hypothesis

An Orchestrator (or human) reading wave output can tell a failed wave from a clean one without opening raw JSON logs, which is the precondition for a cheaper model handling the happy path.

## Notes

(none)
