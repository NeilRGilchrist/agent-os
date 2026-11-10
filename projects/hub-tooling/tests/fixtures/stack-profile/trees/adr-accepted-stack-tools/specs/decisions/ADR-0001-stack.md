---
id: ADR-0001
title: Synthetic accepted stack declaration
status: accepted
owner: architect
supersedes: null
superseded_by: null
stack_tools: [uv, docker, kubectl]
created: 2026-01-01
updated: 2026-01-01
---

# ADR-0001: Synthetic accepted stack declaration

## Context

Synthetic fixture for FR-0010:AC-2. `kubectl` is outside the closed
vocabulary on purpose, to exercise the one-WARN-per-unrecognised-entry path.

## Decision

Synthetic.

## When you may deviate

No deviation is permitted; supersede this ADR instead.
