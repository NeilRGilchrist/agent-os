---
id: IDEA-0097
title: 'Protected owns: entries are detected in footprint coordinates under footprint_root:
  repo'
status: parked
tags:
- dispatch
- permissions
- footprint
- monorepo
- control-plane
size: S
created: '2026-11-04'
updated: '2026-11-04'
last_reviewed: '2026-11-04'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0097: Protected owns: entries are detected in footprint coordinates under footprint_root: repo

## Description

Under footprint_root: repo in a subdirectory project, _owns_entry_protected and mnt_permission_rules compare repo-relative owns: globs against project-relative protected globs. A repo-rooted FR naming its own project's control plane (e.g. projects/demo/scripts/dispatch.py) gets an absolute grant for dev, despite FR-0009 AC-2's 'withheld, granted nothing'; finalize (FR-0015 AC-2) and the relative deny still refuse it, so it fails closed. For mnt the protected glob is not narrowed, so mnt cannot maintain the project's own control plane. Fix: strip <prefix> from repo-rooted owns: before the protection checks; roughly one function and two tests.

## Originating context

FR-0024 r1 finding F-4; recorded as a known limitation in FR-0024 Out of scope (DEC-0031 item 11)

## Value hypothesis

Withholding the grant up front instead of refusing at finalize saves one wasted Developer round (~30-60 min) per occurrence and makes mnt usable for a repo-rooted project's own .agent-team/ and scripts/, which today needs a hand-run session.

## Notes

(none)
