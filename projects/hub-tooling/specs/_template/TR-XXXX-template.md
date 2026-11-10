---
id: TR-XXXX  # TR-NNNN, required; no default. Must equal the filename prefix (specs/TR-NNNN-<slug>.md). Allocated sequentially, never reused.
title: <one-line title — the approach, not the need>  # non-empty string, required; no default.
operationalises: [FR-XXXX]  # non-empty list of FR IDs (FR-NNNN) this TR is the agent-authored "how" for; required, no default. Each must resolve to an FR in this project.
# --- Versioning block (identical to the FR block; see specs/decisions/README.md -> "Revision vs supersession"). Every field is optional: an absent key takes the default shown. ---
version: 1  # integer >= 1; default 1. Bump by one per revision so that version == len(revisions) + 1.
lifecycle: draft  # draft | live | superseded; default live when absent (this template pre-fills draft: set `live` once the approach is settled). Identity lifecycle; TRs have no workflow `status`.
revisions: []  # list of DEC IDs (DEC-NNNN), oldest first; default []. One entry per revision applied under this ID. Each must resolve to a specs/decisions/DEC-NNNN-*.md whose `revises` names this TR.
last_breaking_revision: null  # integer >= 1 or null; default null. The `version` the newest `breaking: true` DEC in `revisions` produced (1 + its 1-based position); must be <= version.
supersedes: null  # TR ID (TR-NNNN) or null; default null. Set on the NEW object when identity changes; the old object gets `superseded_by` and `lifecycle: superseded`. Must resolve to a TR in this project.
superseded_by: null  # TR ID (TR-NNNN) or null; default null. Set on the OLD object; symmetric with the successor's `supersedes`. Must resolve to a TR in this project.
# --- TR-only fields. Optional; defaults shown. ---
implemented_by: []  # list of non-empty strings (repo-relative paths, globs, or component names); default []. Cite the stable ID from code, never `TR-NNNN@v2` — an `@` in an entry is an error. A superseded TR with a non-empty list is a warning (migration window).
success_criteria: []  # list of SC IDs (opaque strings, e.g. SC-003-1); default []. Shape-checked only. Author their text under `## Success criteria` in the FR.
tests: []  # list of non-empty strings (test paths or globs); default []. Shape-checked only; an `@` in an entry is an error.
created: YYYY-MM-DD  # date, required; no default.
updated: YYYY-MM-DD  # date, required; no default. Bump on every revision (see Changelog).
---

# TR-XXXX: <title>

## Approach

One or two paragraphs. How the FR(s) in `operationalises` will be met: the shape of the solution, the components involved, the constraints taken from the FR's `solution_space.fixed`, and the choices made inside `solution_space.open` (each of which is a DEC).

## Decisions

One bullet per DEC in `revisions:` above, oldest first, for human reading (the indexer reads the frontmatter list, not this section).

- **DEC-NNNN** — <one line: what was decided and whether it was breaking>

## Components

The pieces that implement this TR, matching `implemented_by:` above. One bullet each: what it does and which FR AC(s) it serves.

- `<path or component>` — <responsibility>

## Open questions

If unresolved, propose a default. The default is what gets built if the TR proceeds without further clarification.

- **Q:** <question>
  - **Default:** <what to do absent further input>

## Changelog

Revisions get one line per DEC, citing the new `version`, the DEC that made it, and whether it was breaking:

- `YYYY-MM-DD: v<N> — DEC-NNNN (breaking: <bool>): <summary>`

- YYYY-MM-DD: created (draft)
