---
id: IDEA-0036
title: PHI regex SIN pattern misses digits directly preceded by letters (template
  hook + aitk)
status: parked
tags:
- template
- phi
- privacy
- hooks
- bug
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0036: PHI regex SIN pattern misses digits directly preceded by letters (template hook + aitk)

## Description

The Canadian SIN pattern is anchored with a word boundary, so a SIN-shaped digit group immediately preceded by a letter does not match. Same pattern in template .agent-team/hooks/phi_regex_check.py (protected) and in ai-productivity-toolkit FR-0002 validator. Decide with privacy reviewer whether to use digit-only lookarounds instead of word boundaries (and accept the false-positive cost), then change template + project together.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. Found while diagnosing FR-0002 Reviewer test D3 (REVIEW-FR-0002).

## Value hypothesis

Closes a cheap evasion of the write-time PHI guard: a SIN run directly into letters currently passes both the hook and the toolkit validator.

## Notes

(none)
