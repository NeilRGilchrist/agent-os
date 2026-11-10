---
id: IDEA-0079
title: 'Merge friction on every PR: GitHub ignores merge=union for the metrics log,
  generated INDEX.md and root REVIEW.md conflict, stale branches need a manual revalidate'
status: promoted
tags:
- dispatch
- finalize
- metrics
- github
- branch-lifecycle
- template
size: M
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0018
pattern: null
archive_reason: null
---
# IDEA-0079: Merge friction on every PR: GitHub ignores merge=union for the metrics log, generated INDEX.md and root REVIEW.md conflict, stale branches need a manual revalidate

## Description

Three generated or append-only files make every role branch conflict with main, and GitHub can resolve none of them. (1) specs/_metrics/*.ndjson carries merge=union in .gitattributes, but GitHub does not apply merge drivers server-side, so any PR whose branch and main both appended rows shows a conflict and cannot be merged from the UI. (2) specs/INDEX.md is regenerated on both sides and always conflicts; the resolution is always 'regenerate', so finalize/revalidate should regenerate it rather than merge it. (3) The root-level REVIEW.md committed per branch conflicts on every merge of main once one FR's REVIEW.md has landed. Metrics fix options: (a) role branches never commit metrics rows - the gate writes to _dispatch/ inside a worktree and only the Orchestrator commits rows from main (Project A's L36/L40 convention, made mechanical); (b) one metrics file per branch or run so two branches never touch the same path; (c) document the local-merge step. (a) or (b) removes the class. Stale branches: a role branch cut before a main fix stays red in CI until main is merged in. FR-0013 added --revalidate (status-only, run by hand) but nothing triggers it; finalize could revalidate automatically before un-drafting when main has moved past the branch base.

## Originating context

Project A L62 (PR #13, FR-0004) and Project A HANDOFF 2026-09-25 section 4 ('still happens on every PR'); Project A L52 (= L46 recurrence; PR #10 red on a provenance row that landed on main after the branch was cut); hub-tooling _dispatch/learnings-wave1.md FR-0011/FR-0012 and FR-0014 sections (UU REVIEW.md and UU specs/INDEX.md on every merge of main; 'finalize should regenerate rather than merge'). Related: IDEA-0067 / FR-0013 (fixed the worktree metrics-row footprint refusal, not the GitHub merge), IDEA-0003 (reconcile fetch). Touches template/scripts/dispatch.py, metrics_log.py, template/.gitattributes, template/specs/_metrics/README.md (maintainer mode). Home: hub-tooling. Proposed wave 2, lane A, order 4.

## Value hypothesis

All 13 Project A PRs so far, and most hub-tooling wave-1 PRs, needed a local git merge origin/main, an INDEX regenerate and a push before GitHub would merge them (~10 min and one error-prone manual step per PR); removing the class makes UI merges work and stops stale-branch CI reds reaching the human.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0061 there). Personal-project names generalised.

(none)
