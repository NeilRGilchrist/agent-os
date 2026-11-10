---
id: IDEA-0095
title: 'aitk seed: imprecise message for an unreadable seed file'
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

# IDEA-0095: aitk seed: imprecise message for an unreadable seed file

## Description

seed._read_or_empty returns an empty string on a read error, so an unreadable seed file is reported as 'not a seed artifact (no frontmatter)'. Behaviour is correct (it fails); the message is imprecise, and the helper's comment wrongly says the validator reports unreadable files itself. Report read errors with their own fixed reason.

## Originating context

aitk FR-0007 Reviewer round-2 observation N1 (REVIEW-FR-0007). Queued 2026-10-23 during the hub parking pause.

## Value hypothesis

Tells a user 'can't read this file' instead of the misleading 'no frontmatter'.

## Notes

(none)
