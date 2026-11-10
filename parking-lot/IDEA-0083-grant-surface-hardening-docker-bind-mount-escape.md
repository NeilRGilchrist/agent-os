---
id: IDEA-0083
title: 'Grant-surface hardening: docker bind-mount escape for mnt, malformed owns:
  refused for every role, implicit self-spec grant'
status: promoted
tags:
- dispatch
- control-plane
- security
- footprint
- stack
- template
size: S
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0015
pattern: null
archive_reason: null
---
# IDEA-0083: Grant-surface hardening: docker bind-mount escape for mnt, malformed owns: refused for every role, implicit self-spec grant

## Description

Three findings on the permission surface FR-0009/FR-0010/FR-0013 built. (1) Security: a granted Bash(docker *) lets a role write role-denied paths through a bind mount (docker run -v <worktree>:/wt ... appended to scripts/deploy-gate.py in the rev worktree, confirmed live by the FR-0010 Reviewer). For mnt, whose deny list guards the control plane and whose interpreter surface is deliberately narrowed (MNT_BASH_NOT_INHERITED), this re-opens exactly the hole the deny closes. Options (from the Architect handoff): exclude docker from mnt; gate docker behind an ADR stack_tools: declaration for every role; record the accepted risk with a WARN; or exclude plus WARN. (2) ensure_role_worktree refuses a malformed owns: only for dev (FR-0010 finding a). (3) An implicit self-spec grant in fr_owns_globs (FR-0013 Architect follow-up iii).

## Originating context

hub-tooling FR-0010 Reviewer FINDINGS (e) and (a), hub PR #4 REVIEW.md @ 900ab56; Neil's disposition on PR #4: 'Resolution deferred to a follow-up PR'. Architect handoff: projects/hub-tooling/_dispatch/handoff-architect-docker-grant-security.md (Neil runs that session). Item (3): projects/hub-tooling/_dispatch/handoff-cos-dec-object-overload.md follow-up (iii). Needs an Architect ruling (a DEC revising FR-0010 AC-4 / Open question 2) before any code; no DEC exists yet (checked 2026-09-25). For Project A until fixed: treat a mnt role with docker granted as able to touch the control plane. Touches template/scripts/stack_profile.py and dispatch.py (maintainer mode). Home: hub-tooling. Proposed wave 2, lane A, order 3 (slips to wave 3 if the ruling is not ready).

## Value hypothesis

Closes a confirmed privilege escape on the one role whose restrictions exist to protect the merge gate and the dispatcher; the code change is small once the ruling exists, and the two hardening items ride along at near-zero marginal cost.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0065 there). Personal-project names generalised.

- 2026-09-25 (hub-tooling Architect, approved by Neil): items (1) and (2) promoted as hub-tooling FR-0015. The docker ruling went the other way from this idea's options. Docker stays granted to every role (DEC-0014), because for `mnt` it is one of at least five code-executing grants. The fix is instead to close the finalize check's gaps: Reviewer-provenance laundering (DEC-0015 revises FR-0013 AC-5(a)), control-plane paths on `dev`/`rev`/`bkf` branches, uncommitted tampering, and a rewritten permission file. Item (3), the implicit self-spec grant, moved to IDEA-0084: it widens a footprint, and FR-0015 only narrows.
