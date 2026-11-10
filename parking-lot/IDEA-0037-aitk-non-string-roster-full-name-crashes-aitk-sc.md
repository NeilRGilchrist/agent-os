---
id: IDEA-0037
title: 'aitk: non-string roster full_name crashes aitk scrub and echoes the roster
  value'
status: parked
tags:
- ai-productivity-toolkit
- bug
- roster
- scrubber
- phi
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0037: aitk: non-string roster full_name crashes aitk scrub and echoes the roster value

## Description

A roster entry whose full_name is not a string passes the FR-0009 roster loader, then aitk scrub crashes with a pydantic traceback (exit 1) that includes the value. Fix in the FR-0009 loader (type-check full_name/aliases) plus a non-echoing error. Follow-up FR against FR-0009.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0004 Reviewer observation 1 (REVIEW-FR-0004).

## Value hypothesis

Turns a crash that prints a roster value into a clean validation error at load time.

## Notes

(none)
