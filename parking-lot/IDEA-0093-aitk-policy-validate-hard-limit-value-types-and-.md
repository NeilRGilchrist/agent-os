---
id: IDEA-0093
title: 'aitk policy: validate hard-limit value types and reject duplicate YAML keys'
status: parked
tags:
- ai-productivity-toolkit
- policy
- fail-closed
size: S
created: '2026-10-26'
updated: '2026-10-26'
last_reviewed: '2026-10-26'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0093: aitk policy: validate hard-limit value types and reject duplicate YAML keys

## Description

(O6) The resolver checks a hard limit's shape and kind but not the types of its values: allowed: "false" (a string) is truthy and lets a business unit's true through. The limits live in a code constant that only changes via reviewed commits, so risk is low; still, validate limit value types at import. (O7) Duplicate YAML keys in layer files are silently last-wins; consider a loader that rejects duplicates, at least for policy: maps.

## Originating context

aitk FR-0010 Reviewer round-2 observations O6, O7 (REVIEW-FR-0010). Queued 2026-10-23 during the hub parking pause.

## Value hypothesis

Closes two remaining ways a policy file could silently mean something other than what it says.

## Notes

(none)
