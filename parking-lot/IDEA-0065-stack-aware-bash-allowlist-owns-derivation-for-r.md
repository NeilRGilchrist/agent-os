---
id: IDEA-0065
title: 'Stack-aware Bash allowlist + owns: derivation for rev/bkf/mnt (extends FR-0009)'
status: promoted
tags:
- dispatch
- control-plane
- footprint
- stack
- template
size: M
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: hub-tooling/FR-0010
pattern: null
archive_reason: null
---
# IDEA-0065: Stack-aware Bash allowlist + owns: derivation for rev/bkf/mnt (extends FR-0009)

## Description

FR-0009 grants dev Edit/Write on the FR's owns: globs but leaves Bash command grants static per role and rev/bkf unchanged. No role's Bash allow contains uv, npm, npx, node, docker or alembic, and MNT_BASH_DENIES denies uv/node/npx outright. Union each role's static list with (1) Edit/Write grants from owns: for rev and bkf as FR-0009 does for dev, and (2) a stack-command allowlist derived from the project's declared stack (ADR-0001 / pyproject.toml / package.json / docker-compose presence), and stop denying uv/node/npx in maintainer mode. Role deny lists still win.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L5, L18, L20, L34, L39 and the PR #4 maintainer attempt (uv denied). Extends hub-tooling FR-0009 (ready); both own template/scripts/dispatch.py so sequence after FR-0009 and before FR-0008 rebases. Home: hub-tooling, maintainer mode.

## Value hypothesis

After FR-0009 every one of the 12 remaining Project A stack FRs still stops at its first uv/npm/docker call: 3 of 3 dispatcher spawns failed on permissions in the FR-0001 wave and the Reviewer's 11 environment-skips hid 2 of 5 round-2 defects. Fixing this recovers most of the ~36 wasted spawns and ~10 h of hand orchestration and removes ~40% of rework rounds (12 x 0.4 x 25 min = ~2 h).

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0047 there). Personal-project names generalised.

(none)
