---
id: IDEA-0089
title: Linux/macOS worktree agents inherit the main checkout's .claude/settings.local.json
  allow rules
status: parked
tags:
- dispatch
- control-plane
- security
- wsl
- harness
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0089: Linux/macOS worktree agents inherit the main checkout's .claude/settings.local.json allow rules

## Description

Claude Code (v2.1.211+) on macOS/Linux stores and reads .claude/settings.local.json at the git repository root, and for a linked worktree at the MAIN checkout's root, while still reading a file in the starting directory; permission rules from both files apply (code.claude.com/docs/en/settings, 'Where Claude Code keeps the local file in a git repository'). A dispatched agent in a worktree therefore inherits whatever allow rules the human has accumulated in the primary checkout's settings.local.json, on top of the dispatcher-written per-role file. On Windows the local file stays in the starting directory, so this is not live today. Options: have the dispatcher refuse or warn when the primary checkout's settings.local.json carries allow rules beyond a baseline; move worktrees outside the main checkout; or confine agents in a sandbox (IDEA-0064). Verify with a live headless run on WSL before designing.

## Originating context

Surfaced 2026-09-25 by the FR-0024 grounding audit (hub-tooling wave-2 Architect session) reading Claude Code's settings docs; relevant to FR-0015's threat model (DEC-0014) and IDEA-0064. Home: hub-tooling.

## Value hypothesis

Closes a grant-widening path that DEC-0014's finalize boundary does not see (it inspects the role worktree only), before the factory moves to WSL under IDEA-0064, where it becomes live for every dispatched role.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0071 there). Personal-project names generalised.

(none)
