---
id: IDEA-0047
title: 'parking.py: link an idea to a pattern without merging it (keep status parked)'
status: parked
tags:
- hub-scripts
- parking-lot
- patterns
- bidirectional-links
- tooling
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0047: parking.py: link an idea to a pattern without merging it (keep status parked)

## Description

parking.py has no way to set an idea's pattern: field without also setting status: merged-into-pattern (cmd_merge). That fits when a pattern replaces the idea, but not when the idea is still separate work that is one instance of a pattern. Add a link-only path, e.g. 'parking.py link IDEA-NNNN --pattern PATTERN-NNNN' (and --unlink), that sets pattern:, bumps last_reviewed, leaves status alone, and reindexes. Optionally have patterns.py propose/accept --ideas call it, so creating a pattern sets both directions in one step. Interim: on 2026-10-22, IDEA-0016/0041/0044/0045 had pattern: PATTERN-0002 set by hand with the user's approval. parking.py is a protected hub script, so the change needs explicit human approval and its own PR.

## Originating context

CoS session 2026-10-22, while accepting PATTERN-0002 (agent-outcome ledger).

## Value hypothesis

Keeps the CLAUDE.md promise that the scripts maintain idea-pattern links in both directions. Without it, every accepted pattern with ideas still being built needs a hand edit or a wrong merged status, and the second option silently drops those ideas from the parked list and the stale-idea check.

## Notes

(none)
