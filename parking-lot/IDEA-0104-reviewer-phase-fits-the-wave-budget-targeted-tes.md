---
id: IDEA-0104
title: 'Reviewer phase fits the wave budget: targeted tests locally, full suite left
  to CI'
status: parked
tags:
- dispatch
- reviewer
- timeouts
- ci
- roles
size: S
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0104: Reviewer phase fits the wave budget: targeted tests locally, full suite left to CI

## Description

The wave applies one flat --phase-timeout (default 1h) to every role, but Reviewers routinely run the full template suite, which takes about 1.5h locally on Windows and about 4 min in CI. The FR-0028 Reviewer finished its review in 11 minutes and then waited 50 minutes on the suite until it was killed. Options: the reviewer role says run targeted tests and cite CI's Validate job for the full suite; or per-role phase timeouts; or both. Role files are on the human-approval list.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; the FR-0028 Reviewer was killed at the 1h phase timeout waiting on the 1.5h full template suite

## Value hypothesis

Saves about 1.5h of Opus wall-clock per Reviewer round on this host and stops finished reviews from being dropped by the phase timeout.

## Notes

(none)
