---
id: FR-XXXX
title: <one-line title>
status: draft  # draft | ready | in-progress | in-review | merged | deprecated | blocked
owner: architect
depends_on: []  # list of FR IDs this depends on
tags: []  # optional kebab-case themes; used for cross-project pattern detection
owns: []  # list of POSIX-style globs (relative to repo root) the Developer is permitted to write/edit/create. Empty list means "footprint not yet declared"; the indexer will warn. Matched against `git ls-files`. `**` matches any number of path segments. Absolute paths and `..` segments are rejected.
reads: []  # list of POSIX-style globs the Developer's implementation reads or consumes. Documentation only today; reserved for follow-on cross-commit-warning tooling. Same syntax rules as `owns`.
gates: []  # optional list of pre-review / pre-merge gates the dispatcher and deploy gate enforce (FR-0008). Default []. Each entry is a mapping with exactly the keys: id (slug, ^[a-z][a-z0-9-]{1,39}$, unique within this FR), after (dev | rev — which phase it follows), reviewer (human | architect — who judges it), scope (one-line, non-empty). Evidence lives at specs/_gates/<FR-ID>-<gate-id>.md, written by `dispatch.py gate pass|block` or a gate-review session — never hand-authored. Example:
  # - {id: design-review, after: dev, reviewer: human, scope: "Confirm the screen matches the approved mock before Reviewer sees it"}
derived_from: null  # optional "IDEA-NNNN" if this FR was promoted from a parked idea
pattern: null  # optional "PATTERN-NNNN" if this FR is recognized as an instance of a hub-level pattern
ac_state: {}  # optional per-AC ratification state (Lockstep N-4), keyed by AC number. Leave {} until you start tracking ratification; an FR with no ac_state is "unmanaged" and the indexer stays silent about it. Once you add any entry, the indexer warns about ACs you left out. Each entry is {state, source, ratified, hash}; state ∈ proposed | refined | client-review | ratified | superseded | deferred | withdrawn. deferred, withdrawn and superseded also take moved_to (FR-NNNN | IDEA-NNNN | ADR-NNNN | DEC-NNNN | null + reason): such an entry exempts the AC from the coverage gate, and entries in those three states alone do not opt the FR into ratification tracking (see specs/README.md -> "Deferred, withdrawn and superseded ACs"). Record `hash` from `python scripts/index-specs.py --ac-hashes FR-XXXX` at the moment of ratification; if a ratified AC's text later changes, the hash no longer matches and the indexer flags it for client-review. Example:
  # 1: {state: ratified, source: "fathom:rec_123#seg4", ratified: 2026-08-20, hash: "<64-hex>"}
  # 2: {state: proposed, source: null, ratified: null, hash: null}
  # 3: {state: deferred, moved_to: IDEA-NNNN, reason: "Not needed for the first release"}
# --- Versioning block (shared with TRs; see specs/decisions/README.md -> "Revision vs supersession"). Every field is optional: an absent key takes the default shown, so nothing needs backfilling. ---
version: 1  # integer >= 1; default 1. Bump by one per revision so that version == len(revisions) + 1.
lifecycle: live  # draft | live | superseded; default live. Identity lifecycle — orthogonal to the workflow `status` above. Set `superseded` (and `superseded_by`) when a new FR replaces this one.
revisions: []  # list of DEC IDs (DEC-NNNN), oldest first; default []. One entry per revision applied under this ID. Pattern-checked; resolved to DEC files once DEC objects exist.
last_breaking_revision: null  # integer >= 1 or null; default null. The `version` the newest `breaking: true` DEC produced; must be <= version.
supersedes: null  # FR ID (FR-NNNN) or null; default null. Set on the NEW object when identity changes; the old object gets `superseded_by` and `lifecycle: superseded`. Must resolve to an FR in this project.
superseded_by: null  # FR ID (FR-NNNN) or null; default null. Set on the OLD object; symmetric with the successor's `supersedes`. Must resolve to an FR in this project.
# --- Solution-space fields (FR-only). Optional; defaults shown. ---
extends: []  # list of FR IDs this FR refines or builds on (weaker than depends_on: no dispatch ordering); default []. Each must resolve to an FR in this project.
serves_roles: []  # list of role slugs (e.g. quality_risk_lead) whose need this FR serves; default []. Shape only.
solution_space:  # mapping with exactly the keys `open` and `fixed`, each a list of strings; default {open: [], fixed: []}. `open` = parts of the solution an agent may decide (and record as DECs); `fixed` = parts that are not negotiable without a client/product decision.
  open: []
  fixed: []
goal: null  # "GOAL-<slug>" or null; default null. The outcome-level goal this FR serves. Shape only; no GOAL object exists yet.
success_criteria: []  # list of SC IDs (opaque strings, e.g. SC-003-1); default []. Outcome-level criteria ACs may cite; never a replacement for an AC. Shape only. Author their text under `## Success criteria` below.
asserted_by: []  # list of provenance refs (opaque strings — a discovery-graph node, a transcript segment); default []. Shape only.
variability: null  # core | configurable | tenant_specific | null; default null (undeclared). Declare only once the project has a tenancy model.
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# FR-XXXX: <title>

## Why

One paragraph. What user/business problem does this solve? Who feels the pain today?

## What

One paragraph. What will exist after this FR is implemented that doesn't exist now? Stay at the behavior level — not implementation.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** <Specific, testable statement. E.g., "Given a malformed input X, the system returns error code Y with message Z.">
- **AC-2:** <...>
- **AC-3:** <...>

## Success criteria

Optional. Outcome-level statements (what is true for the role served once this need is met), one per SC ID listed in `success_criteria:` above. ACs are the per-FR testable statements and may cite an SC in their text; an SC never replaces an AC. This section is not parsed by the indexer.

- **SC-<id>:** <outcome-level statement, or delete this section>

## Out of scope

Explicit list. Anything you can imagine a Developer accidentally implementing belongs here.

- <Item that is NOT covered by this FR>
- <Item that belongs to a different FR — link it: "see FR-YYYY">

## Open questions

If unresolved, propose a default. The default is what gets implemented if the FR ships without further clarification.

- **Q:** <question>
  - **Default:** <what to do absent further input>

## Dependencies

If this FR depends on others, explain the nature of the dependency:

- **FR-YYYY** — needed because <reason>

## Notes

Anything that helps a Developer understand context but isn't itself an acceptance criterion. Keep it short.

## Changelog

Ratifications are recorded here with a source reference, in addition to updating
the AC's `ac_state` in the frontmatter. The source is an opaque string the
renderer never dereferences (e.g. `fathom:<recording_id>#<segment>`,
`outlook:<message_id>`):

- `YYYY-MM-DD: AC-N ratified — source: <ref>`
- `YYYY-MM-DD: AC-N flagged for re-review — text changed after ratification`

Revisions (see `specs/decisions/README.md` -> "Revision vs supersession") get
one line per DEC, citing the new `version`, the DEC that made it, and whether
it was breaking:

- `YYYY-MM-DD: v<N> — DEC-NNNN (breaking: <bool>): <summary>`

- YYYY-MM-DD: created
