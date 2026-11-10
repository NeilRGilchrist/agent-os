---
id: IDEA-0101
title: gate-review role has no git add grant for its evidence file
status: parked
tags:
- dispatch
- permissions
- gate
- footprint
size: S
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0101: gate-review role has no git add grant for its evidence file

## Description

gat's static grants do not include git add for the evidence file it writes. On Neil's host a user-level Bash(git add *) allow rule covers it; elsewhere it is already refused under default mode, and FR-0028 makes default mode universal. Ruled out of FR-0028 because two FR-0024 tests pin gat's permission file byte for byte and no hub-tooling FR declares a gate. Add a narrowly scoped grant (the evidence path only) and update the pinned fixtures.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; FR-0028 Architect finding

## Value hypothesis

Gate-review runs succeed on any host instead of only where a user-level Bash(git add *) rule happens to cover the evidence file.

## Notes

(none)
