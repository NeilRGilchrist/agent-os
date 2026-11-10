---
id: IDEA-0098
title: The dispatcher pins --permission-mode default so the worktree settings file
  is a closed footprint
status: promoted
tags:
- dispatch
- harness
- permissions
- control-plane
- security
size: S
created: '2026-11-04'
updated: '2026-11-04'
last_reviewed: '2026-11-04'
promoted_to: hub-tooling/FR-0028
pattern: null
archive_reason: null
---
# IDEA-0098: The dispatcher pins --permission-mode default so the worktree settings file is a closed footprint

## Description

ClaudeCodeAdapter.spawn passes no --permission-mode. On a host whose user settings set defaultMode: auto, an edit the worktree's .claude/settings.local.json neither allows nor denies goes to the auto-mode classifier instead of being refused, so the footprint is open by host configuration and violations surface only at finalize. Fix: pass an explicit --permission-mode default from spawn, plus a pin test. Open questions: does any role rely on auto mode today, and does non-interactive default mode refuse cleanly in headless runs.

## Originating context

FR-0024 r1 finding F-5 (pre-existing, not FR-0024); observed during the AC-5 live run, which needed --permission-mode default

## Value hypothesis

Makes the per-worktree permission file the whole policy again regardless of host settings, refusing out-of-footprint edits at edit time rather than at finalize, for one argv token and a pin test.

## Notes

(none)
