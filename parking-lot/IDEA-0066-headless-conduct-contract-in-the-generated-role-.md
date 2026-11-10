---
id: IDEA-0066
title: Headless conduct contract in the generated role commands
status: promoted
tags:
- dispatch
- agent-team
- commands
- headless
- control-plane
size: S
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: hub-tooling/FR-0012
pattern: null
archive_reason: null
---
# IDEA-0066: Headless conduct contract in the generated role commands

## Description

Add a headless-behaviour block to template/.agent-team/commands/{developer,reviewer,maintainer,reviewer-backfill}.md (regenerated into .claude/ and .cursor/ wrappers): you run under claude -p, a denied tool call is a hard stop for that path or an ## ESCALATION block, never a question; bare git stash is forbidden (WIP commit or stash push -m <tag> + apply by SHA); a dependency or tool substitution forced by the host environment is at least a ## FINDINGS item; the gate's specs/_metrics record is committed only from main by the Orchestrator, restore it on role branches; live-data test anchors assert existence and well-formedness, never a mutable field; no blanket regex substitutions across annotation-bearing files. Restate the review contract as 'Reviewer posts the verdict-of-record; human approves and merges' in reviewer.md and orchestrator.md (L24). Whether the factory gets a bot identity for formal GitHub reviews is a separate human decision.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L6 (twice), L11b, L22, L24, L40, L44, L45; recurrence of the 2026-09-13 FR-0015 headless stop. Files are human-approval (template/.agent-team/commands/**); dispatch as a maintainer-mode FR in hub-tooling. Home: hub-tooling.

## Value hypothesis

Two phases in the FR-0001 wave ended by asking a human nobody could answer; each ask drops a phase (2 min spawn + 15-20 min subagent retry). Harness-guarded paths, gh and host policy still deny after the allowlist fix, so at the observed 2 asks/wave over 12 FRs even a quarter surviving costs 1.5-2 h. The silent psycopg driver substitution (L11) cost a DEC, a chore PR and a Reviewer round (~50 min) that a FINDINGS rule would have surfaced at review time.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0048 there). Personal-project names generalised.

(none)
