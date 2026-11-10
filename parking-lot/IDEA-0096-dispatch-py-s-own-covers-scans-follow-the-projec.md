---
id: IDEA-0096
title: dispatch.py's own @covers scans follow the project layout
status: parked
tags:
- dispatch
- metrics
- layout
- hub-tooling
size: S
created: '2026-11-04'
updated: '2026-11-04'
last_reviewed: '2026-11-04'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0096: dispatch.py's own @covers scans follow the project layout

## Description

FR-0024 (DEC-0031) keeps dispatch.py's two @covers scans, _covers_tests_present (the rework precondition) and _pr_change_size (which fills pr.opened's tests_changed and covers_delta), on <prefix>tests/ and the plain @covers form. In hub-tooling that folder holds bootstrap copies of the template tests; the real tests are in template/tests (written '# covers hub-tooling') and the hub's tests/. Make both scans read FR-0023's layout: gate.test_dirs under the footprint root, counting '# covers <project_name>' as the gate's collect_covers does, ideally by calling it. The gate, which decides merges, already does this. This changes pr.opened's fields for any project with a layout, so it needs its own FR and a note on the metrics schema.

## Originating context

Neil chose option (a) for DEC-0031's open question on 2026-11-04: keep FR-0024's scope and park this follow-up.

## Value hypothesis

A project with a layout (hub-tooling today) gets a rework precondition that actually checks its tests, and real tests_changed and covers_delta in pr.opened, instead of a check that passes trivially and metrics that count almost nothing.

## Notes

(none)
