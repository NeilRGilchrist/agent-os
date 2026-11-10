---
id: IDEA-0090
title: 'aitk policy: downstream commands must handle PolicyError and config-load errors'
status: parked
tags:
- ai-productivity-toolkit
- policy
- capture
- interface
size: S
created: '2026-10-26'
updated: '2026-10-26'
last_reviewed: '2026-10-26'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0090: aitk policy: downstream commands must handle PolicyError and config-load errors

## Description

layers.resolve_policy raises PolicyError. Callers must catch it and exit 2. They must also guard their own config.resolve() call against yaml.YAMLError / UnicodeDecodeError / OSError, because config.resolve() (FR-0009) is warn-only and unguarded. commands/policy.py:_show is the reference pattern. Put this in the FR-0011, FR-0012 and FR-0014 ACs, or factor it into a shared helper. Pairs with the config.resolve() idea parked alongside it.

## Originating context

aitk FR-0010 Reviewer round-1 observation O1 (REVIEW-FR-0010), plus the D1 fix in 49ec6c8. Queued 2026-10-23 during the hub parking pause.

## Value hypothesis

Stops FR-0011/0012/0014 from reintroducing the traceback-on-bad-config crash FR-0010 just fixed, so every policy-reading command fails closed with exit 2.

## Notes

(none)
