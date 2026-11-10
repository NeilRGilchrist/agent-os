---
id: IDEA-0088
title: 'Protected set covers the whole working agreement: AGENTS.md, .claude/settings.json
  and .claude/commands/** join MNT_PROTECTED_GLOBS'
status: parked
tags:
- dispatch
- control-plane
- security
- footprint
- template
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0088: Protected set covers the whole working agreement: AGENTS.md, .claude/settings.json and .claude/commands/** join MNT_PROTECTED_GLOBS

## Description

MNT_PROTECTED_GLOBS (template/scripts/dispatch.py) is .agent-team/**, the four control-plane scripts and CLAUDE.md. It omits AGENTS.md, which is the working agreement CLAUDE.md only imports, and .claude/settings.json (hook wiring). Both are on every bootstrapped project's human-approval list. It also omits .claude/commands/** (generated role commands). Only the docs role denies AGENTS.md. .claude/** is harness-guarded against the Edit tool but not against interpreter writes, and because none of these paths is in the protected set, FR-0015's finalize checks (DEC-0014: the finalize check is the control-plane boundary) would not catch a committed or uncommitted change to them. Scope carefully: add .claude/settings.json and .claude/commands/**, never .claude/**. The dispatcher writes .claude/settings.local.json into every worktree and it shows as untracked there (FR-0010 Reviewer finding i), so a .claude/** entry would make FR-0015 AC-3 refuse every finalize. Changing the constant changes every mnt permission file and the deny lists FR-0009/FR-0010 tests pin byte-for-byte, so it needs a breaking DEC on FR-0009 (and likely FR-0010) with the test cascade named. MNT_NEVER_WRITABLE should probably gain AGENTS.md alongside CLAUDE.md, for the reason its comment gives.

## Originating context

hub-tooling FR-0015 Open question 1, raised by the Architect 2026-09-25 while ruling on the docker grant (DEC-0014/DEC-0015); Neil asked to park it the same day. Land after FR-0015 (same file, same predicate). Home: hub-tooling, maintainer mode.

## Value hypothesis

Closes the one remaining gap in the finalize boundary DEC-0014 relies on: an agent that can rewrite AGENTS.md or the hook wiring can rewrite its own constraints, and today no automated check would notice before the PR.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0070 there). Personal-project names generalised.

(none)
