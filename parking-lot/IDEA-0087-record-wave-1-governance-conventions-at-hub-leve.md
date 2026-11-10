---
id: IDEA-0087
title: 'Record wave-1 governance conventions at hub level: hub-script crossings, architect-tier
  ratify-by-merge, hub .gitignore'
status: parked
tags:
- hub
- governance
- decision-rights
- process
- docs
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0087: Record wave-1 governance conventions at hub level: hub-script crossings, architect-tier ratify-by-merge, hub .gitignore

## Description

Three conventions Neil confirmed during hub-tooling wave 1 live only in gitignored _dispatch/ files. (1) A template FR may reach into a hub script only under a neil-tier DEC bounded to named symbols; the FR's blanket maintainer-mode approval does not cover it, and the hub CLAUDE.md 'escalate first' means before the change, not at merge (DEC-0013 precedent). (2) An architect-tier DEC whose frontmatter says 'ratified when <FR>'s PR merges', carried on that PR and covered by the human's approval, is ratified by the merge: the Orchestrator flips proposed -> ratified in the same revertible commit as the FR's merged flip and says so; neil-tier DECs get an explicit act (confirmed by Neil for DEC-0008..0011 on PR #8, 2026-09-22). (3) The hub-root .gitignore gains .claude/worktrees/ and PR_BODY.md (today only projects/hub-tooling/.gitignore and a local .git/info/exclude cover them, so a hub-root worktree can show as untracked and a PR_BODY.md can be committed by accident).

## Originating context

hub-tooling _dispatch/learnings-wave1.md ('Setup observations'; 'Convention confirmed: ratification of architect-tier DECs (2026-09-22)'; FR-0008 'The wave's first hub-script crossing'). (1) and (2) belong in hub CLAUDE.md and/or hub-tooling ADR-0001 plus the Orchestrator command (IDEA-0082); CLAUDE.md is a human-approval file, so Neil edits or approves it. (3) is a chore. Related: IDEA-0077 (chore lane), IDEA-0085 (ratification route differs by DEC kind). Home: hub root / hub-tooling.

## Value hypothesis

Without a written record the next Orchestrator or Architect re-asks questions Neil has already answered (the DEC-0013 stop and the DEC-0008..0011 ratification each cost a human round-trip); writing them down makes the precedent citable instead of remembered.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0069 there). Personal-project names generalised.

(none)
