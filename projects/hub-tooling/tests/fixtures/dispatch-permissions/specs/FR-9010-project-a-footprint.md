---
id: FR-9010
title: Synthetic FR-9010 (FR-0009:AC-10 fixture)
status: ready
owner: architect
depends_on: []
tags: []
owns:
  - src/project_a/*.py
  - alembic.ini
  - migrations/env.py
  - migrations/script.py.mako
  - migrations/README.md
  - docker-compose.yml
  - .env.example
  - pyproject.toml
  - uv.lock
  - .python-version
  - requirements.txt
  - pytest.ini
  - tests/conftest.py
  - tests/smoke/**
  - frontend/*
  - frontend/public/**
  - frontend/src/main.tsx
  - frontend/src/App.tsx
  - frontend/src/vite-env.d.ts
  - frontend/src/api/**
  - .github/workflows/stack-ci.yml
  - README.md
reads: []
derived_from: null
pattern: null
ac_state: {}
created: 2026-01-01
updated: 2026-01-01
---

# FR-9010: Synthetic (FR-0009:AC-10 fixture)

A synthetic FR carrying the Project A FR-0001 `owns:` footprint verbatim, per
FR-0009:AC-10 — the motivating case for the `dev` `owns:` grant derivation
(a build-lane FR whose footprint is entirely outside the static `dev`
allow-list). No real project data; every path here is a synthetic stand-in
matching FR-0009's spec text.

## Acceptance criteria

- **AC-1:** does the first thing
