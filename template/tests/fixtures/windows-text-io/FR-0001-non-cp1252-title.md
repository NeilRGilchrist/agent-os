---
id: FR-0001
title: Synthetic “quoted” title ← arrows (FR-0016 dogfood shape)
status: in-review
owner: architect
depends_on: []
tags: []
owns: ["src/**"]
reads: []
derived_from: null
pattern: null
ac_state: {}
created: 2026-01-01
updated: 2026-01-01
---

# FR-0001: Synthetic “quoted” title ← arrows

Synthetic fixture for FR-0016 (hub-tooling). The title carries U+201D and
U+2190; U+201D's UTF-8 bytes end in 0x9D, which cp1252 cannot decode.

## Acceptance criteria

- **AC-1:** does the first thing

## Changelog

- 2026-01-01: created.
