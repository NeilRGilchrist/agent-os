---
id: IDEA-0062
title: 'Wave follow mode: first-class wait on a detached dispatch wave'
status: parked
tags:
- dispatch
- harness
- orchestrator
- observability
size: S
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0062: Wave follow mode: first-class wait on a detached dispatch wave

## Description

dispatch.py has no primitive for waiting on a detached wave. Add either a blocking follow mode or a machine-readable status subcommand so orchestrators and hub Monitor recipes can wait on, and detect early exit of, a wave they did not start in the foreground.

## Originating context

Surfaced 2026-09-20 in a downstream project's `_dispatch/learnings-FR-0001-wave.md` (L2, L7). The harness caps foreground commands at 10 min, so wave runs are launched detached (PowerShell Start-Process) and the Orchestrator had to hand-assemble a session-length Monitor over _dispatch/wave-FR-0001.console.log. That Monitor had no signal for the run ending early (the FR-0001 wave exited after 2 min). Candidate shapes: dispatch.py wave --follow (blocks, exits with the wave's status), or wave status --json reading the pid file plus the latest wave-*.md synthesis and reporting running/finished/dropped per FR.

## Value hypothesis

Removes the hand-assembled Monitor-over-console-log that every detached wave run currently needs, so an Orchestrator can block on a wave (or poll a stable status contract) and react to early exits instead of tailing a log.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0044 there). Personal-project names generalised.

(none)
