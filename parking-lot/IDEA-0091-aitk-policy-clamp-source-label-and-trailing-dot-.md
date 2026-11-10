---
id: IDEA-0091
title: 'aitk policy: clamp source label and trailing-dot internal domain'
status: parked
tags:
- ai-productivity-toolkit
- policy
- polish
size: S
created: '2026-10-26'
updated: '2026-10-26'
last_reviewed: '2026-10-26'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0091: aitk policy: clamp source label and trailing-dot internal domain

## Description

(O2) When a business unit sets a limited key past the hard limit and it clamps back to the AlayaCare default, the source is still reported as business_unit; consider reporting 'alayacare (clamped)'. (O3) alayacare.com. (trailing dot) is not treated as the internal domain; add trailing-dot normalisation to the AC-5 domain rule. Low risk, since it fails toward external.

## Originating context

aitk FR-0010 Reviewer round-1 observations O2, O3 (REVIEW-FR-0010). Queued 2026-10-23 during the hub parking pause.

## Value hypothesis

Keeps policy show from telling a user a business-unit override is in effect when it was clamped away, and closes a minor domain-matching gap.

## Notes

(none)
