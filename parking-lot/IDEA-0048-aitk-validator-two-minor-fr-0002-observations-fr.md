---
id: IDEA-0048
title: 'aitk validator: two minor FR-0002 observations from final review'
status: parked
tags:
- ai-productivity-toolkit
- validator
- polish
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0048: aitk validator: two minor FR-0002 observations from final review

## Description

(1) aitk.frontmatter now exposes more than the parse/dump API FR-0002's Notes describe. Decide whether the extra helpers are public (document and test them) or private (underscore them) before downstream FRs import them. (2) The AC-13 date-time check uses \d, which also matches non-ASCII Unicode digits; use [0-9] or re.ASCII so only ASCII digits pass.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0002 Reviewer round-3 non-blocking observations (REVIEW-FR-0002).

## Value hypothesis

Keeps the validator's public surface and date parsing tight before other FRs (FR-0003, FR-0006, FR-0007) start depending on them.

## Notes

(none)
