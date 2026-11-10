---
id: IDEA-0100
title: Hub scripts run via uv run with inline dependency metadata instead of a global
  pip install
status: parked
tags:
- bootstrap
- tooling
- uv
- python
- cross-platform
size: M
created: '2026-11-05'
updated: '2026-11-05'
last_reviewed: '2026-11-05'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0100: Hub scripts run via uv run with inline dependency metadata instead of a global pip install

## Description

The dispatcher already standardises on uv for worktree environments (uv venv, uv pip install, uv sync --frozen; env_preflight blocks without uv). The hub layer does not: bootstrap.py, hub-index.py, parking.py, patterns.py and dispatch.py itself run on the system Python and need a global pip install pyyaml (GETTING-STARTED.md; dispatch.py's missing-pyyaml message says pip install). Add PEP 723 inline script metadata declaring pyyaml to each script and invoke them as uv run scripts/<name>.py, updating slash commands, GETTING-STARTED.md and CI. Every touched file is on the human-approval list, so this needs an FR.

## Originating context

Wave 4 (FR-0028, PRs #34/#35), 2026-11-05; Neil asked whether uv was considered

## Value hypothesis

Removes the global pip install pyyaml prerequisite and pins each hub script's dependencies, so a fresh machine or CI runner runs the hub with one tool (uv) and no version drift.

## Notes

(none)
