---
id: IDEA-0046
title: 'aitk: batch scrub command (aitk scrub --dir) for back-fill and re-scrub'
status: parked
tags:
- ai-productivity-toolkit
- scrubber
- cli
- deferred
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0046: aitk: batch scrub command (aitk scrub --dir) for back-fill and re-scrub

## Description

Original FR-0004 AC-12: 'python -m aitk scrub --dir <kb_root>/raw scrubs every *.txt in raw/ that has no scrubbed counterpart yet and prints a one-line summary per file.' Deferred with no target because in Phase 1 every raw file arrives via FR-0011 capture, which scrubs on capture and handles its own --no-scrub deferrals, and single-file aitk scrub covers one-offs. Revisit if: (1) a non-capture ingestion path appears (manual drops, Zoom/Gong adapters before they scrub inline); or (2) a scrubber version bump (e.g. IDEA-0040) needs re-scrubbing of unreviewed files. FR-0004 says re-scrub-on-version-bump is out of scope, so that would need its own AC.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0004 AC-12 [P2] withdrawn as a deferral (spec a513f9c, human-approved option 2).

## Value hypothesis

Lets a user scrub or re-scrub a folder of raw files in one command, which only matters once raw files can arrive outside FR-0011 capture or after a scrubber version bump.

## Notes

(none)
