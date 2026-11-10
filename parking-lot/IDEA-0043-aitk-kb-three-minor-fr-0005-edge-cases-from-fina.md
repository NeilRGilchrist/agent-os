---
id: IDEA-0043
title: 'aitk kb: three minor FR-0005 edge cases from final review'
status: parked
tags:
- ai-productivity-toolkit
- kb
- bug
- polish
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0043: aitk kb: three minor FR-0005 edge cases from final review

## Description

(1) kb doctor's raw/ flat FAIL detail still says 'subdirectory/symlink entries' though it now also counts junctions, FIFOs, reparse files (cosmetic; count correct). (2) kb init on a kb_root that is an existing file crashes with FileExistsError (exit 1); unspecified by FR-0005, AC-12 does not cover kb_root itself. Probably should be exit 2 with a usage message. (3) When a directory occupies a sidecar position, sweep moves it first and the raw file lands as <stem>.dup1.txt; nothing lost (AC-7 satisfied) but naming is confusing. Follow-up FR against FR-0005 after merge (FR-0011 now owns routing.py).

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0005 Reviewer round-3 non-blocking observations 2-4 (REVIEW-FR-0005).

## Value hypothesis

Clears small rough edges in kb doctor/init/sweep before pilot users hit them; none affects data safety.

## Notes

(none)
