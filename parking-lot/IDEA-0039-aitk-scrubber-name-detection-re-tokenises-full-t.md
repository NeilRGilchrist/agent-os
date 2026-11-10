---
id: IDEA-0039
title: 'aitk scrubber: name detection re-tokenises full text per detected name (~14s
  per 10k words)'
status: parked
tags:
- ai-productivity-toolkit
- performance
- scrubber
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0039: aitk scrubber: name detection re-tokenises full text per detected name (~14s per 10k words)

## Description

aitk.scrub re-tokenises the whole text for every detected name, so cost grows with names x length (~14 s on a 10.8k-word synthetic transcript). FR-0004:AC-3 parity lock means the fix is a deliberate, versioned parity break; bundle with the scrubber name-detection enhancement.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0004 Reviewer observation 2 (REVIEW-FR-0004); behaviour inherited from ai-hub-poc.

## Value hypothesis

Keeps scrub time from becoming part of the pilot's time-on-status-reporting cost as transcripts get longer.

## Notes

(none)
