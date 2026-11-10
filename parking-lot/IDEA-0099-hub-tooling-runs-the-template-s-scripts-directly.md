---
id: IDEA-0099
title: hub-tooling runs the template's scripts directly instead of a bootstrapped
  copy
status: parked
tags:
- hub-tooling
- dispatch
- bootstrap
- layout
- dogfood
size: M
created: '2026-11-04'
updated: '2026-11-04'
last_reviewed: '2026-11-04'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0099: hub-tooling runs the template's scripts directly instead of a bootstrapped copy

## Description

hub-tooling is bootstrapped from the template it changes, so its scripts/ is a copy that goes stale whenever an FR changes template/scripts/**. Every such FR needs a separate bootstrap --upgrade PR before hub-tooling can dispatch with its own change (PR #31 before FR-0024; stale again after #32: projects/hub-tooling/scripts/dispatch.py lacks _project_prefix). Options: a layout.yaml setting (e.g. scripts_root) that dispatch, gate and indexer entry points honour; thin wrapper scripts that exec ../../template/scripts/*; or symlinks (fragile on Windows). Must keep FR-0020's upgrade-preserves-project-files behaviour and the other projects' copy semantics unchanged.

## Originating context

Hub enhancements run, Waves 3-4 (2026-11-04); Neil asked to park it after the parity estimate

## Value hypothesis

Removes one upgrade PR per dispatcher-changing FR (2 of the last 3 waves needed one) and lets hub-tooling dogfood each template change in the same wave it lands, so a regression in dispatch.py shows up on the very next hub-tooling wave instead of after a manual refresh.

## Notes

(none)
