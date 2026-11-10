---
id: FR-0215
title: Synthetic FR-0215
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
    scope: First.
  - id: design-review
    after: rev
    reviewer: architect
    scope: Second, same id.
created: 2026-01-01
updated: 2026-01-01
---

# FR-0215: Synthetic

## Why

Synthetic FR for exercising FR-0008 AC-1's `gates:` validation.

## Acceptance criteria

- **AC-1:** does the first thing
