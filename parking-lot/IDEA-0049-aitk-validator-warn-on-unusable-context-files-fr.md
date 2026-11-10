---
id: IDEA-0049
title: 'aitk validator: warn on unusable --context files (FR-0002 AC-14, deferred)'
status: parked
tags:
- ai-productivity-toolkit
- validator
- deferred
- developer-experience
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0049: aitk validator: warn on unusable --context files (FR-0002 AC-14, deferred)

## Description

Original FR-0002 AC-14: a --context file that opens a frontmatter fence but cannot be read or parsed, or whose frontmatter has no string id, is excluded from the context set and reported on stderr as 'WARN <path>: context file ignored (<reason>)', reason one of unreadable / invalid frontmatter / no id (fixed labels, no YAML text or content). Files with no opening fence and README.md are skipped silently. Warnings are sorted by path, appear in text and --format json, and don't change the exit code. Never implemented. Pick up when the team KB is used as a --context set in CI (FR-0002 AC-11 template), where silent skips are hardest to debug.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0002 AC-14 [P2] withdrawn as a deferral at merge (human-approved approach, as FR-0004 AC-12).

## Value hypothesis

Stops a broken context file from silently turning a resolvable reference into 'unresolved', which today gives the user no hint why validation failed.

## Notes

(none)
