---
id: IDEA-0105
title: finalize reads the Reviewer's REVIEW.md verdict when the Reviewer dies before
  its final message
status: parked
tags:
- dispatch
- reviewer
- verdict
- finalize
size: S
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0105: finalize reads the Reviewer's REVIEW.md verdict when the Reviewer dies before its final message

## Description

_extract_review_verdict reads only the Reviewer's last chat message in the rev log. The FR-0028 Reviewer was killed before writing one, so finalize posted verdict=comment even though REVIEW.md declared Approve. The post-approve fast-forward (FR-0013 AC-1) then did not run, and PR #35 lacked the tests until the CoS fast-forwarded claude/dev-FR-0028 by hand. Proposal: when the log has no final message, fall back to a declared verdict on REVIEW.md's first lines, and say which source was used.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; related IDEA-0074 (bot identity for verdicts)

## Value hypothesis

A killed Reviewer that already wrote 'Verdict: Approve' still gets the post-approve fast-forward, so its tests reach the PR without a hand-run git merge --ff-only.

## Notes

(none)
