---
id: DEC-XXXX  # DEC-NNNN, required; no default. Must equal the filename prefix (specs/decisions/DEC-NNNN-<slug>.md). Allocated sequentially, never reused.
title: <one-line title — the choice made, not the topic>  # non-empty string, required; no default.
tier: <tier>  # non-empty string, required; no default. The authority tier that may make this decision (vocabulary comes from the project profile — see specs/decisions/README.md).
status: proposed  # proposed | ratified | rejected | superseded; required, no default. `proposed` and `ratified` are live (the design proceeds on them); `rejected` and `superseded` are not.
satisfies: []  # list of "GOAL-<slug>" IDs (^GOAL-[A-Za-z0-9-]+$); default []. Shape-checked only — no GOAL object exists yet.
constrained_by: []  # list of FR IDs (FR-NNNN); default []. Each must resolve to an FR in this project.
revises: null  # one FR ID (FR-NNNN) or TR ID (TR-NNNN), or null; default null (a DEC that creates a TR). Must resolve to an object in this project. Cite the stable ID only — `TR-0014@v2` is an error.
breaking: false  # boolean; required when `revises` is set, defaults to false when `revises` is null. `true` when implementers of the revised object must change (ADR rule: then bump its `last_breaking_revision`).
authorised_by: []  # list of ADR IDs (ADR-NNNN); default []. An ADR ID with no matching specs/decisions/ADR-*.md is a warning, not an error.
invokes_exception: null  # string (e.g. "ADR-0001§when-you-may-deviate") or null; default null. Set when this DEC uses an ADR's deviation clause; then record what that ADR's "What you must record when you deviate" section asks for, below.
alternatives: []  # list of non-empty strings (one per alternative considered); default []. Shape-checked only; expand under `## Alternatives considered`.
reversibility: null  # high | medium | low | null; default null. How cheaply this choice can be undone.
provisional_until: null  # string (a YYYY-MM-DD date or an event trigger) or null; default null. When set, the decision is provisional until the date passes or the event occurs.
client_visible: false  # boolean; default false. `true` when the client must see or ratify this decision.
supersedes: null  # DEC ID (DEC-NNNN) or null; default null. Set on the NEW decision when it replaces an older one. Must resolve to a DEC in this project; asymmetry with the old DEC's `superseded_by` is a warning.
superseded_by: null  # DEC ID (DEC-NNNN) or null; default null. Set on the OLD decision (and set its `status: superseded`). Must resolve to a DEC in this project.
rationale: >  # non-empty folded string, required; no default. Why this option over the alternatives, in one or two sentences an agent can read without the body.
  <why this choice, in prose that stands on its own>
created: YYYY-MM-DD  # date, required; no default.
updated: YYYY-MM-DD  # date, required; no default. Bump on every change.
---

# DEC-XXXX: <title>

## Context

What choice had to be made, which FR or TR it belongs to (`revises` / `constrained_by` above), and which ADR principle it was made under (`authorised_by`). One or two paragraphs. Name the constraint that made this non-obvious.

## Alternatives considered

One bullet per entry in `alternatives:` above — what it was and why it lost. Keep the ones a future reader is likely to propose again.

- **<Alternative>.** Rejected: <reason>.

## Cascade

Mandatory when `breaking: true`; otherwise write "None — non-breaking." Enumerate every artifact that must change because of this decision, as work items: each implementer (`implemented_by` of the revised object), each test, each dependent object (`depends_on`, `extends`, `operationalises` pointing at the revised object). Not parsed by the indexer in this version of the template. If this decision changes a vocabulary, a schema or a grammar that a test pins as a literal, name each such test by id here and the command that backfills it. A spec commit that widens a pinned set turns the verification suite red on the base branch from the moment it lands; the round that clears it is part of this decision's cost.

- <artifact> — <what changes>

## Changelog

- YYYY-MM-DD: created (proposed)
