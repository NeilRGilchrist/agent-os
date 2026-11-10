---
id: IDEA-0092
title: 'aitk seed: two load edge cases (--check exit code, pre-check targets)'
status: parked
tags:
- ai-productivity-toolkit
- seed
- polish
size: S
created: '2026-10-26'
updated: '2026-10-26'
last_reviewed: '2026-10-26'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0092: aitk seed: two load edge cases (--check exit code, pre-check targets)

## Description

(O3) AC-6 doesn't say what --check exits with when files are only missing from the target (code exits 0); decide and pin it. (O4) A directory where a target file should be makes load die with an uncaught PermissionError traceback, possibly after earlier files were copied; pre-check all targets before writing anything, and exit 2 with a fixed message.

## Originating context

aitk FR-0007 Reviewer round-1 observations O3, O4 (REVIEW-FR-0007). Queued 2026-10-23 during the hub parking pause.

## Value hypothesis

Makes seed load --check exit codes unambiguous and stops a half-applied load on a bad target layout.

## Notes

(none)
