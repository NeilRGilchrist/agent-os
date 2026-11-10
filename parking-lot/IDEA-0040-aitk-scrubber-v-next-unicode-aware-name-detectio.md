---
id: IDEA-0040
title: 'aitk scrubber v-next: Unicode-aware name detection and roster match inside
  longer spans'
status: parked
tags:
- ai-productivity-toolkit
- scrubber
- phi
- privacy
- enhancement
size: M
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0040: aitk scrubber v-next: Unicode-aware name detection and roster match inside longer spans

## Description

FR-0004 merged with its parity-locked (AC-3) ASCII-only name regex. E2: accented names, all-caps names, and apostrophe prefixes are not detected (leak). E1: the AC-4 fixture 'Person A' cannot be matched as one span, and a capitalised word before a roster name gets absorbed, so consented names are over-redacted. Enhancement FR: deliberate parity break, MINOR scrubber version bump, amend AC-4 fixture; bundle IDEA-0039 perf fix. Needs privacy-reviewer input; should land before real customer transcripts are scrubbed (or human redaction review, FR-0013/FR-0014, is the backstop).

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0004 Reviewer escalations E1 (contradicting ACs) and E2 (privacy), REVIEW-FR-0004. Human decision: merge FR-0004 as-is, follow up as an enhancement.

## Value hypothesis

Closes the under-redaction leak for accented/all-caps/apostrophe names, which matter more now that customer calls are in scope; also recovers roster names swallowed by sentence-start words, which feeds the approved-without-edits metric.

## Notes

(none)
