---
id: FR-0200
title: Synthetic FR-0200
status: ready
owner: architect
depends_on: []
tags: []
owns: []
reads: []
derived_from: null
pattern: null
ac_state: {}
gates:
  - id: design-review
    after: dev
    reviewer: human
    scope: The human signs off the rendered screens before the Reviewer runs.
  - id: tier-map-review
    after: rev
    reviewer: architect
    scope: The Architect checks the legacy-ID tier map before merge.
created: 2026-01-01
updated: 2026-01-01
---

# FR-0200: Synthetic

## Why

Synthetic FR for exercising FR-0008 AC-1's `gates:` validation.

## Acceptance criteria

- **AC-1:** does the first thing
