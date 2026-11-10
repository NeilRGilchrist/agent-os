---
id: FR-0004
title: Decision (DEC) and Technical Requirement (TR) object types — templates, indexer discovery and parse, cross-object resolution
status: merged  # draft | ready | in-progress | in-review | merged | deprecated | blocked
owner: architect
depends_on: [FR-0003]
tags: [schema, template, indexer, decision-rights, versioning]
owns:
  - template/specs/_template/DEC-XXXX-template.md
  - template/specs/_template/TR-XXXX-template.md
  - template/scripts/index-specs.py
  - template/specs/README.md
  - template/specs/decisions/README.md
reads:
  - template/specs/_template/FR-XXXX-template.md
  - template/specs/_template/ADR-XXXX-template.md
  - template/scripts/spec_footprint.py
  - template/scripts/deploy-gate.py
  - template/scripts/render-docs.py
  - template/scripts/dispatch.py
  - specs/decisions/ADR-0001-revision-vs-supersession.md
derived_from: null
pattern: null
ac_state: {}
created: 2026-09-07
updated: 2026-09-07
---

# FR-0004: Decision (DEC) and Technical Requirement (TR) object types — templates, indexer discovery and parse, cross-object resolution

## Why

The plan's target behaviour (§2) is an agent that never leaves a design incomplete: it makes every non-obvious choice, records it with a declared authority tier, and cites the ADR that permits it. That is only possible if a *Decision* is a first-class spec object with a stable ID, and if the agent-authored *how* of an FR has a home of its own — the Technical Requirement — so that FRs can stay at the business-outcome level and TRs can be revised by DECs without touching the FR. Today neither object exists: choices live in prose, the FR carries the implementation, and the indexer knows only `FR-*.md`. FR-0003 lands the shared versioning block on existing types; this FR adds the two new types that carry it, so that H2 (supersession-aware indexing), H3/H4 (code cites TR), WS4 (gates) and WS5 (review queues) have objects to index, gate, and project.

## What

After this FR: (1) the hub template ships `DEC-XXXX-template.md` and `TR-XXXX-template.md` under `specs/_template/` (which `--upgrade` already syncs); (2) DEC files live at `specs/decisions/DEC-NNNN-<slug>.md` and TR files at `specs/TR-NNNN-<slug>.md`; (3) `template/scripts/index-specs.py` discovers both, parses them into `DEC` and `TR` dataclasses whose attribute names equal the frontmatter keys, hard-fails on shape, required-field, ID and unresolvable-reference errors (including under `--validate`), resolves FR/TR `revisions` entries to DEC files (deferred from FR-0003), runs warn-only reciprocity and breaking-revision checks, and renders `## Technical requirements` and `## Decisions` tables into `INDEX.md`; (4) `deploy-gate.py` is untouched and still writes an identical `INDEX.md`.

### DEC object — `specs/decisions/DEC-NNNN-<slug>.md`

Field names are the plan's WS1a vocabulary verbatim, plus `created`/`updated` (hub convention: every indexed object has them; the index tables render `updated`). No field is renamed.

| Field | Type | Required? / default | Validation |
|---|---|---|---|
| `id` | `^DEC-\d{4}$` | required | error if absent, malformed, not matching the filename prefix, or duplicated |
| `title` | non-empty string | required | error if absent/empty |
| `tier` | non-empty string | required | **string shape only** — the tier vocabulary is a project-profile overlay (WS2, IDEA-0055); this FR does not know the enum |
| `status` | enum `proposed` / `ratified` / `rejected` / `superseded` | required | error if not in enum |
| `satisfies` | list of `^GOAL-[A-Za-z0-9-]+$` | `[]` | shape only; not resolved (no GOAL object) |
| `constrained_by` | list of FR IDs | `[]` | error if any entry does not resolve to an FR in this project |
| `revises` | one FR ID or TR ID, or `null` | `null` (a DEC that *creates* a TR) | error if non-null and unresolvable; error if the value contains `@` (versions are never cited) |
| `breaking` | boolean | required when `revises` is non-null; `false` when `revises` is null | error if absent while `revises` is set, or if not a boolean |
| `authorised_by` | list of ADR IDs `^ADR-\d{4}$` | `[]` | pattern is an error; an ID with no matching `specs/decisions/ADR-*.md` is a **warning** (ADRs are warn-only per FR-0003) |
| `invokes_exception` | string (e.g. `ADR-0001§when-you-may-deviate`) or `null` | `null` | shape only |
| `alternatives` | list of non-empty strings | `[]` | shape only |
| `reversibility` | enum `high` / `medium` / `low` or `null` | `null` | error if not in enum or null |
| `provisional_until` | string (date or event) or `null` | `null` | shape only |
| `client_visible` | boolean | `false` | error if not boolean |
| `supersedes` | DEC ID or `null` | `null` | error if unresolvable; asymmetry is a warning |
| `superseded_by` | DEC ID or `null` | `null` | error if unresolvable; `superseded_by` set while `status` is not `superseded` is a warning |
| `rationale` | non-empty string (folded scalar) | required | error if absent/empty |
| `created`, `updated` | dates | required | error if absent |

The body is free-form Markdown (the template provides `## Context`, `## Alternatives considered`, `## Cascade` — the last is where a `breaking: true` DEC enumerates the artifacts that must change; content is not parsed in this FR).

### TR object — `specs/TR-NNNN-<slug>.md`

Field names are the plan's WS1d vocabulary, with two deliberate deltas recorded here: `status: live` becomes **`lifecycle`** (same reason and same enum as FR-0003 — the shared block must be identical across FR and TR), and `title`, `created`, `updated` are added (hub convention).

| Field | Type | Required? / default | Validation |
|---|---|---|---|
| `id` | `^TR-\d{4}$` | required | error if absent, malformed, not matching filename prefix, or duplicated |
| `title` | non-empty string | required | error if absent/empty |
| `operationalises` | non-empty list of FR IDs | required | error if absent, empty, not a list, or any entry unresolvable |
| `version` | integer ≥ 1 | `1` | identical to FR-0003 |
| `lifecycle` | `draft` / `live` / `superseded` | `live` when absent (the **template pre-fills `draft`**) | identical to FR-0003 |
| `revisions` | list of DEC IDs, oldest first | `[]` | pattern error per FR-0003; **in this FR each entry must resolve to a DEC file** (error otherwise) |
| `last_breaking_revision` | integer ≥ 1 or `null` | `null` | identical to FR-0003 |
| `supersedes`, `superseded_by` | TR ID or `null` | `null` | error if unresolvable to a TR; symmetry warnings per FR-0003 |
| `implemented_by` | list of non-empty strings (repo-relative paths, globs, or component names) | `[]` | shape only; error if any entry contains `@` (code cites the stable ID, never `TR-0014@v2`); H3 (IDEA-0054) later derives this from code citations |
| `success_criteria` | list of non-empty strings | `[]` | shape only (opaque, as in FR-0003) |
| `tests` | list of non-empty strings (paths or globs) | `[]` | shape only; `@` is an error as above |
| `created`, `updated` | dates | required | error if absent |

TRs have no workflow `status`; readiness is expressed by `lifecycle: draft → live`, and gating is WS4's job. The template body provides `## Approach`, `## Decisions` (a bullet per DEC in `revisions`, for human reading), `## Components`, `## Open questions`, `## Changelog`.

### Cross-object resolution and lint

Resolution **errors** (exit 1, also under `--validate`): every reference field above marked "error if unresolvable" resolves within this project's `specs/` tree only; FR and TR `revisions` entries must resolve to a DEC file (this completes the deferral in FR-0003).

Warn-only checks, rendered under the `## Versioning warnings` section FR-0003 introduced, one line each naming both objects: (a) **reciprocity** — for each DEC listed in an object's `revisions`, that DEC's `revises` should equal the object's ID (regardless of the DEC's `status`: being listed asserts it was applied); and for each **live** DEC (`is_live_dec`, i.e. `status` in `proposed`/`ratified`) whose `revises` names an object, the object's `revisions` should contain the DEC. DECs with `status: rejected` or `status: superseded` are exempt from this second direction: a rejected proposal, or one replaced before it was applied, legitimately has `revises` set and never enters `revisions`, and would otherwise warn forever. A `proposed` DEC is **not** exempt — the design proceeds on it (liveness, below), so its change is applied and it is appended to `revisions` at proposal time; a proposed DEC absent from `revisions` is the forgotten-append defect this check exists to catch (ADR-0001 rule 2); (b) **breaking marker** — when any DEC in `revisions` has `breaking: true`, `last_breaking_revision` should equal `1 + (1-based position of the newest breaking DEC in revisions)` (i.e. the `version` that revision produced); when none does, `last_breaking_revision` should be `null`; (c) **superseded with implementers** — a TR with `lifecycle: superseded` and non-empty `implemented_by` (the migration-window case; WS4 will require a DEC to justify it); (d) **DEC supersession symmetry** as in FR-0003.

Liveness for downstream consumers (normative, so H2 has one table): FR/TR — `lifecycle == "live"` (FR-0003's `is_live`); DEC — `status in {"proposed", "ratified"}`; the module exports `is_live_dec(dec) -> bool` alongside `is_live`.

### INDEX.md rendering

After the FR table (and its warning sections) and before the ADR table: `## Technical requirements` with columns `ID | Title | Operationalises | Ver | Lifecycle | Last breaking | Implemented by | Updated`, then `## Decisions` with columns `ID | Title | Tier | Status | Revises | Breaking | Authorised by | Updated`. Both tables are sorted by ID, both are omitted entirely when the project has no objects of that type (so existing projects' `INDEX.md` is unchanged by this FR beyond FR-0003's columns), and list cells are comma-joined with an em-dash for empty, matching the FR table's conventions.

### Python API

`index-specs.py` gains dataclasses `DEC` and `TR` (attributes named exactly as the frontmatter keys above, plus `path`), functions `collect_decs()` and `collect_trs()` mirroring `collect_frs()` (returning `(objects, errors)`), and `collect_graph()` returning a single object holding `frs`, `trs`, `decs`, `adrs` plus the merged error list. `collect_frs()`, `validate_graph(frs)`, `render_index(frs, repo_files)`, `FR`, `INDEX_PATH` keep their existing signatures and behaviour so `deploy-gate.py` keeps working unmodified.

## Acceptance criteria

Each AC must be independently testable. Conventions as in FR-0003: "error" = stderr message naming file and field, exit 1; "warning" = line under the named `INDEX.md` section and on stderr, exit 0.

- **AC-1:** `template/specs/_template/DEC-XXXX-template.md` and `template/specs/_template/TR-XXXX-template.md` exist; each contains every field in its table above with an inline comment stating type, allowed values, and default, pre-filled with the default (or a placeholder for required fields); the TR template pre-fills `lifecycle: draft`; and a copy of each with placeholders replaced by valid values (pointing at an existing FR, and for the DEC at an existing TR) passes `index-specs.py --validate` with exit 0 and no warnings.
- **AC-2:** Discovery and identity: files matching `specs/decisions/DEC-*.md` and `specs/TR-*.md` are parsed; a filename not matching `DEC-\d{4}-<slug>.md` / `TR-\d{4}-<slug>.md`, an `id` not matching the filename prefix, a duplicate `id` across two files, or any missing required field (`id`, `title`, `tier`, `status`, `rationale`, `created`, `updated` for DEC; `id`, `title`, `operationalises`, `created`, `updated` for TR) is an error naming the file and the field; `specs/decisions/ADR-*.md` files are not parsed as DECs and `specs/FR-*.md` files are not parsed as TRs.
- **AC-3:** Shape and enum validation: each of the following is an error naming the file and field — DEC `status: accepted`; `breaking: "no"`; `breaking` absent while `revises: TR-0001`; `client_visible: 1`; `reversibility: partial`; `revises: TR-0001@v2`; `authorised_by: [ADR-1]`; `satisfies: [G-3]`; `rationale: ""`; TR `operationalises: []`, `operationalises: FR-0001` (not a list); `implemented_by: ["src/x.py@2"]`; `tests: [""]`; plus every shared-block case listed in FR-0003's shape AC applied to a TR. Each is exercised by at least one fixture.
- **AC-4:** Reference resolution errors: DEC `constrained_by`, `revises`, `supersedes`, `superseded_by` and TR `operationalises`, `supersedes`, `superseded_by` naming an ID with no matching file of the right type in this project is an error naming the field and the ID; an FR or TR whose `revisions` lists a DEC with no matching `specs/decisions/DEC-<id>-*.md` is an error (the case FR-0003 explicitly deferred); `revises: FR-0002` on a DEC resolves against FRs and `revises: TR-0002` against TRs; `authorised_by: [ADR-0099]` with no such ADR is a warning, not an error.
- **AC-5:** Warn-only cross-checks: a fixture tree containing (i) a TR with `revisions: [DEC-0001]` where DEC-0001 has `revises: TR-0002`, (ii) a DEC with `status: proposed` and `revises: TR-0001` not listed in TR-0001's `revisions`, (iii) a TR with `revisions: [DEC-0001, DEC-0002]`, DEC-0002 `breaking: true`, and `last_breaking_revision: null`, (iv) a TR with no breaking DEC and `last_breaking_revision: 2`, (v) a TR with `lifecycle: superseded` and `implemented_by: [api/x]`, and (vi) a DEC with `supersedes: DEC-0001` where DEC-0001 has `superseded_by: null` produces exactly one warning line per case under `## Versioning warnings`, exits 0, and `--validate` reports OK; in the same tree, (vii) a DEC with `status: rejected` and `revises: TR-0001` not listed in TR-0001's `revisions`, and (viii) a DEC with `status: superseded` (symmetrically linked to its successor DEC) and `revises: TR-0001` likewise unlisted, each produce **no** reciprocity warning line; a consistent tree (correct reciprocity, `last_breaking_revision: 3` for the breaking DEC in position 2) produces no warnings.
- **AC-6:** `INDEX.md` renders `## Technical requirements` and `## Decisions` tables with exactly the columns and order given under "INDEX.md rendering", sorted by ID, placed after the FR table and its warning sections and before the ADR table; both sections are omitted when there are no TRs/DECs; two runs on an unchanged tree produce identical bytes.
- **AC-7:** Backward compatibility: for a project with no `TR-*.md` and no `DEC-*.md` files (including `template/` itself and every project registered in `<hub>/hub/projects.yaml` at implementation time), the indexer's exit code, stderr, and `INDEX.md` are identical to the FR-0003 baseline.
- **AC-8:** `--validate` includes DEC/TR parse and resolution errors in its non-zero exit and writes nothing; `--ac-hashes` output is unchanged by the presence of DEC/TR files.
- **AC-9:** `template/scripts/deploy-gate.py` is not modified by this FR, still imports `collect_frs`, `validate_graph`, `render_index`, `FR`, `INDEX_PATH` unchanged, passes `--stage full` on a fixture tree containing valid DECs and TRs, and writes an `INDEX.md` byte-identical to the one `index-specs.py` writes on the same tree (i.e. the TR and DEC tables appear in both).
- **AC-10:** The module exposes `DEC` and `TR` dataclasses with attribute names equal to the frontmatter keys in the two tables (plus `path`), `collect_decs()`, `collect_trs()`, `collect_graph()` as described, and `is_live_dec(dec) -> bool` returning `dec.status in {"proposed", "ratified"}`; unit tests importing the module by path assert the attribute names and the two liveness predicates on fixtures covering every `status`/`lifecycle` value.
- **AC-11:** `template/specs/README.md` layout block lists `DEC-XXXX-template.md`, `TR-XXXX-template.md`, the `specs/TR-NNNN-<slug>.md` location and the `specs/decisions/DEC-NNNN-<slug>.md` location, and states the ID-allocation rule (sequential, never reused) for TR and DEC; `template/specs/decisions/README.md` states that the directory holds both ADRs (principles) and DECs (choices made under a principle, tiered) and links the DEC template.

## Out of scope

- Tier vocabulary and classification rules (`tier` is a string here) — IDEA-0055 (WS2/WS3). Enforcing "every DEC has a GOAL" or "every FR has a TR" — IDEA-0056 (WS4).
- Ratification records, review queues, `status: ratified` write-back — WS5 (IDEA-0058).
- Turning any warning in this FR into an error; the breaking cascade generator and honesty check — IDEA-0056 (WS4 + H5).
- Deriving `implemented_by` from code headers, stale-implementer detection, SC→test binding — IDEA-0054 (H3 + H4).
- Live-only default queries, slice compilation, provisional-past-trigger dashboards — H2 (the fourth Architect's FR), IDEA-0053, IDEA-0057.
- GOAL and SC object types; resolving `satisfies`, `goal`, `success_criteria`.
- Any change to `deploy-gate.py`, `dispatch.py` (including dispatching a TR as a work unit), `render-docs.py`, `agent-status.py`, `bootstrap.py`, `hub-index.py`. The hub's cross-project `FR-INDEX.json` does not learn about DECs/TRs in this FR.
- Migrating any existing prose decisions into DEC files.

## Open questions

If unresolved, propose a default. The default is what gets implemented if the FR ships without further clarification.

- **Q (plan §8):** One DEC per choice, or may a DEC bundle tightly coupled choices?
  - **Default:** One DEC per choice. Bundling is permitted only when the choices are inseparable (reversing one necessarily reverses the other); such a DEC says so in its `rationale`. Nothing in this FR enforces it; WS4 may.
- **Q (plan §8):** When a TR is superseded, are its DECs carried onto the new TR's `revisions`, or left behind under the old TR?
  - **Default:** Left behind — history follows the object that made it (ADR-0001). The new TR starts at `version: 1, revisions: []`, and the old TR's history is reachable via `supersedes`. The reciprocity check above assumes this: a DEC has exactly one `revises` target.
- **Q:** DEC file location — `specs/decisions/` alongside ADRs, or a new `specs/dec/`?
  - **Default:** `specs/decisions/`. Both are decisions; the filename prefix disambiguates, `render-docs.py` globs `ADR-*` only so it ignores DECs, and no new directory needs bootstrapping. H1 says files are for humans and diffs, so directory size is not a navigation concern.
- **Q:** TR file location — top-level `specs/TR-NNNN-*.md` beside FRs, or `specs/tr/`?
  - **Default:** Top level. TRs are requirements; the existing `FR-*.md` glob is unaffected; `dispatch.py` looks up `specs/{fr_id}-*.md` by ID so a `TR-` prefix cannot collide.
- **Q:** Is `breaking` required on every DEC, or only when `revises` is set?
  - **Default:** Required when `revises` is non-null (an honest value matters most there); defaults to `false` for a creating DEC. Making it universally required is a one-line tightening WS4 can apply.
- **Q:** `rationale` in frontmatter (plan) versus a `## Rationale` body section?
  - **Default:** Frontmatter, as the plan shows, so slices and projections (H1, WS5) get it without Markdown parsing. The body stays free-form.
- **Q:** Should TRs carry an `owner`/`author` field (which role or agent wrote them)?
  - **Default:** No. TRs are agent-authored by definition; provenance belongs in H6 metrics, not the object. Revisit if the review agent (H9) needs it.
- **Q:** Should DEC liveness treat `proposed` as live for slice purposes, given a proposed `neil`-tier DEC is not yet ratified?
  - **Default:** Yes — a proposed decision is the current best recommendation and the design proceeds on it (plan §2, §8 first question). H2 may expose a stricter `ratified`-only filter for client projections.

## Dependencies

- **FR-0003** — defines the shared versioning block (`version`, `lifecycle`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by`), its defaults, its shape rules, `is_live`, the `## Versioning warnings` section, ADR discovery (which `authorised_by` resolution warns against), and the `render_index` compatibility constraint. This FR reuses all of it and completes the `revisions` resolution FR-0003 deferred. Do not dispatch until FR-0003 is merged.

## Notes

- **Footprint is hub-relative** under `<hub>/template/` (see FR-0003 Notes for why the globs match nothing in this project's `git ls-files`). The shared `owns:` on `index-specs.py` and the two READMEs with FR-0003 is deliberate and linearised by `depends_on`.
- **Human approval required** before the Developer edits `template/scripts/index-specs.py` (hub human-approval-only list). Note, not a blocking escalation.
- **ID conventions.** Plan examples use `TR-014` (three digits); this FR uses four digits for TR and DEC to match FR/ADR/IDEA/PATTERN conventions across the hub. Code and tests cite `TR-0014`, never `TR-0014@v2`; the `@` rejection in `revises`, `implemented_by`, `tests` is the mechanical guard for that rule. The version an artifact was built against is recorded on the artifact (H3), not in the TR.
- **Consumers of these names** (do not rename without updating them): H2 indexer (this project, fourth Architect), IDEA-0053 (`last_breaking_revision`, `lifecycle`, DEC `status`), IDEA-0054 (`implemented_by`, `success_criteria`, `tests`), IDEA-0055 (`tier`, `authorised_by`, `invokes_exception`), IDEA-0056 (all versioning and `breaking`), IDEA-0058 (`client_visible`, `tier`, `status`).
- **Tests** live in this project's `tests/`, import `template/scripts/index-specs.py` by path, and run against synthetic fixture trees under `tests/fixtures/`. A tree with one FR, one TR operationalising it, and two DECs (one breaking) is the canonical happy-path fixture; the six warning cases in the cross-check AC are one fixture each.
- **Plan mapping.** The rule DECs and TRs revise under is `specs/decisions/ADR-0001-revision-vs-supersession.md` here (plan "ADR-006").

## Changelog

- 2026-09-07: created
- 2026-09-07: amended reciprocity check (a) and AC-5 in response to FR-0005's Architect — forward reciprocity applies to live DECs only (`is_live_dec`); `rejected` and `superseded` DECs are exempt, `proposed` DECs are not; AC-5 gains no-warning cases (vii)–(viii) and pins case (ii) to `status: proposed`
- 2026-09-07 — merged to main via fr/FR-0004 (feat 9854ceb, fix 40d09d8, tests f12c274); Reviewer APPROVE round 2. Status ready -> merged (CoS bookkeeping). Architect follow-up flagged: FR-0003 AC-5 literal breaking-gt-version example now also trips FR-0004 marker check (b); fixture isolated, spec text may want tightening.
