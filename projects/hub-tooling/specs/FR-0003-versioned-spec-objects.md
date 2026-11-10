---
id: FR-0003
title: Versioned spec objects — shared versioning block, FR solution-space fields, ADR deviation sections, and the revision-vs-supersession rule
status: merged  # draft | ready | in-progress | in-review | merged | deprecated | blocked
owner: architect
depends_on: []
tags: [schema, template, indexer, decision-rights, versioning]
owns:
  - template/specs/_template/FR-XXXX-template.md
  - template/specs/_template/ADR-XXXX-template.md
  - template/specs/decisions/README.md
  - template/specs/README.md
  - template/scripts/index-specs.py
reads:
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

# FR-0003: Versioned spec objects — shared versioning block, FR solution-space fields, ADR deviation sections, and the revision-vs-supersession rule

## Why

Agents writing solution designs treat FRs as fixed and implementation-prescriptive because the FR object cannot say otherwise: there is no field that declares which parts of the solution are open, no way to revise an FR without rewriting history, and no ADR structure that tells an agent when a principle may be bent and what to record when it is. The result (decision-rights plan §1) is that roughly half of agent halts are technical choices the agent should have made, and the other half are reconciliation edits to earlier FRs with no record of why. Every downstream capability in the plan — Decision objects (FR-0004), supersession-aware indexing (H2), backward traceability (H3/H4, IDEA-0054), gates (WS4, IDEA-0056) — reads fields that do not exist yet. This FR is the shared-type micro-FR that adds them to the object types that already exist (FR, ADR), so the new object types in FR-0004 can reuse the same block rather than invent their own.

## What

After this FR: (1) every FR carries an optional **versioning block** — `version`, `lifecycle`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by` — plus the **solution-space fields** from the plan's WS1c (`extends`, `serves_roles`, `solution_space`, `goal`, `success_criteria`, `asserted_by`, `variability`), all optional with defaults so every existing FR in every project keeps validating unchanged; (2) the hub template ships an **ADR template** with two mandatory sections, `## When you may deviate` and `## What you must record when you deviate`, and the template indexer discovers ADRs and lints them (warn-only); (3) the **revision-vs-supersession rule** (plan WS1e / plan "ADR-006") is recorded as `specs/decisions/ADR-0001-revision-vs-supersession.md` in this project and summarised normatively in the template's `specs/decisions/README.md`; (4) `template/scripts/index-specs.py` parses the new fields into the `FR` dataclass under their frontmatter names, shape-validates them, resolves the FR-typed references, renders `Ver` and `Lifecycle` columns plus warn-only versioning and ADR sections into `INDEX.md`, and stays import-compatible with `deploy-gate.py`.

### Field vocabulary (normative — FR-0004 and the H2 indexer read these names verbatim)

**Shared versioning block.** Defined here for FRs; FR-0004 applies the identical block to TRs. "Absent" means the key is not present in the frontmatter; the indexer supplies the default and stays silent.

| Field | Type | Default when absent | Validation in this FR |
|---|---|---|---|
| `version` | integer ≥ 1 | `1` | error if present and not an integer ≥ 1 |
| `lifecycle` | enum `draft` / `live` / `superseded` | `live` | error if present and not in the enum |
| `revisions` | list of DEC IDs matching `^DEC-\d{4}$`, oldest first | `[]` | error if not a list or any entry fails the pattern; entries are **not resolved** to DEC files here (FR-0004 adds resolution) |
| `last_breaking_revision` | integer ≥ 1 or `null` | `null` | error if present and not an integer ≥ 1 or null; warn (not error) if greater than `version` |
| `supersedes` | ID of the same object type or `null` | `null` | error if it does not resolve to an FR in this project's `specs/` |
| `superseded_by` | ID of the same object type or `null` | `null` | error if it does not resolve to an FR in this project's `specs/` |

**FR-only additions.**

| Field | Type | Default when absent | Validation in this FR |
|---|---|---|---|
| `extends` | list of FR IDs | `[]` | error if any entry does not resolve to an FR in this project (same rule as `depends_on`) |
| `serves_roles` | list of non-empty strings (role slugs, e.g. `quality_risk_lead`) | `[]` | shape only |
| `solution_space` | mapping with exactly the keys `open` and `fixed`, each a list of non-empty strings | `{open: [], fixed: []}` | error if not a mapping, if either key is missing when the mapping is present, if unknown keys are present, or if a value is not a list of strings |
| `goal` | string matching `^GOAL-[A-Za-z0-9-]+$` or `null` | `null` | shape only; not resolved (no GOAL object exists yet) |
| `success_criteria` | list of non-empty strings (SC IDs; opaque) | `[]` | shape only; not resolved (see Open questions) |
| `asserted_by` | list of non-empty strings (provenance refs; opaque) | `[]` | shape only |
| `variability` | enum `core` / `configurable` / `tenant_specific` or `null` | `null` | error if present and not in the enum or null |

**Renamed from the plan, and why.** The plan's WS1c uses `status: live | superseded` on FRs. `status` is already the FR's *workflow* field (`draft | ready | in-progress | in-review | merged | deprecated | blocked`) and is load-bearing in `index-specs.py` (`VALID_STATUSES`), `deploy-gate.py` (coverage gating on `in-review`/`merged`), `dispatch.py` (dispatches only `ready`, flips to `merged`), and `render-docs.py` (`ACTIVE_STATUSES`). Identity lifecycle and workflow state are orthogonal (a `merged` FR gets superseded; a `draft` FR can already be `superseded_by` a rewrite), so the lifecycle axis gets its own field, **`lifecycle`**, and the same name is used on TRs in FR-0004 so the shared block is identical across object types and the H2 liveness predicate is one function: `is_live(obj) := obj.lifecycle == "live"`. No other plan field is renamed.

**Relationship to `ac_state` and ACs.** ACs and the per-AC `ac_state` ratification block stay exactly as they are. `success_criteria` names outcome-level objects that ACs (and, later, tests via H4) may cite; an SC is never a replacement for an AC and no AC is removed or renumbered by this FR.

**Versioning arithmetic (lint only in this FR).** Per ADR-0001: a revision appends one DEC to `revisions` and bumps `version`, so `version == len(revisions) + 1` on a consistent object; `last_breaking_revision` is the `version` value that the newest `breaking: true` DEC produced, so it is `≤ version`. The indexer reports violations under `## Versioning warnings` and never fails the build on them; enforcement is IDEA-0056 (WS4).

**Supersession consistency (lint only in this FR).** `supersedes` on the new object and `superseded_by` on the old must be symmetric; an object with `superseded_by` set should have `lifecycle: superseded`; an object with `lifecycle: superseded` should have `superseded_by` set. All three are warn-only here.

### ADR template and lint

`template/specs/_template/ADR-XXXX-template.md` is new. Frontmatter: `id` (`ADR-XXXX`), `title`, `status` (`proposed | accepted | superseded | rejected | deprecated` — the vocabulary `render-docs.py` already keys off), `owner`, `supersedes`, `superseded_by`, `created`, `updated`. Body sections in order: `## Context`, `## Decision`, `## When you may deviate`, `## What you must record when you deviate`, `## Consequences`, `## Alternatives considered`, `## Changelog`. The two deviation sections are mandatory: the first states the exception condition as a testable claim; the second lists the fields a DEC (FR-0004) must carry when it invokes the exception (which condition applied, evidence, expected cost). The indexer discovers `specs/decisions/ADR-*.md`, and — because existing projects have ADRs written before this template — every ADR check is **warn-only**: missing or unparseable frontmatter, `id` not matching the filename prefix, `status` outside the enum, and absence of either deviation section.

### Documentation

`template/specs/decisions/README.md` gains a `## Revision vs supersession` section carrying the normative rule (the bullets under "Decision" in ADR-0001, condensed) and a `## Mandatory sections` note about the deviation sections, and points at the new ADR template. `template/specs/README.md` lists `ADR-XXXX-template.md` in the layout. The FR template gains the new fields with inline comments and defaults, an optional `## Success criteria` section (interim home for outcome-level SC text; not parsed), and a Changelog line format for revisions: `YYYY-MM-DD: v<N> — DEC-NNNN (breaking: <bool>): <summary>`.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR. "The indexer" means `template/scripts/index-specs.py` run from a project root; "error" means a message on stderr naming the file and the field and exit code 1; "warning" means a line under the named `INDEX.md` section and on stderr with exit code 0.

- **AC-1:** `template/specs/_template/FR-XXXX-template.md` contains every field in the two tables above (`version`, `lifecycle`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by`, `extends`, `serves_roles`, `solution_space` with `open` and `fixed`, `goal`, `success_criteria`, `asserted_by`, `variability`), each with an inline comment stating its type, allowed values, and default, pre-filled with the default value; the template body contains an optional `## Success criteria` section and a Changelog line showing the `v<N> — DEC-NNNN (breaking: <bool>)` revision format; and a copy of the template with `FR-XXXX`/`YYYY-MM-DD` placeholders replaced by valid values passes `index-specs.py --validate` with exit code 0 and no warnings.
- **AC-2:** Backward compatibility: an FR whose frontmatter contains none of the new fields — `template/specs/FR-0001-example.md` verbatim, and every `specs/FR-*.md` in every project registered in `<hub>/hub/projects.yaml` at implementation time — produces the same errors and the same warnings as before this FR (i.e. zero new ones), and the parsed `FR` object carries the defaults `version=1`, `lifecycle="live"`, `revisions=[]`, `last_breaking_revision=None`, `supersedes=None`, `superseded_by=None`, `extends=[]`, `serves_roles=[]`, `solution_space={"open": [], "fixed": []}`, `goal=None`, `success_criteria=[]`, `asserted_by=[]`, `variability=None`.
- **AC-3:** Shape validation: each of the following, present in an otherwise valid FR, is an error naming the file and the field — `version: 0`, `version: "2"`, `version: 1.5`; `lifecycle: retired`; `revisions: DEC-0001` (not a list), `revisions: [DEC-1]`, `revisions: [FR-0001]`; `last_breaking_revision: 0`, `last_breaking_revision: "1"`; `solution_space: []`, `solution_space: {open: []}` (missing `fixed`), `solution_space: {open: [], fixed: [], other: []}`, `solution_space: {open: "x", fixed: []}`; `variability: shared`; `goal: 3`; `serves_roles: quality` (not a list); `success_criteria: [""]`. Each is exercised by at least one test fixture.
- **AC-4:** Reference resolution: `extends`, `supersedes`, or `superseded_by` naming an FR ID with no matching `specs/FR-<id>-*.md` in the project is an error naming the field and the unknown ID, using the same wording pattern as the existing `depends_on references unknown FR` error; `revisions: [DEC-0042]` with no DEC file present is **not** an error in this FR (pattern-valid, resolution deferred to FR-0004).
- **AC-5:** Versioning lint is warn-only: an FR with `version: 3, revisions: [DEC-0001]` (arithmetic mismatch), `version: 2, last_breaking_revision: 3` (breaking > version), `lifecycle: superseded` with `superseded_by: null`, `lifecycle: live` with `superseded_by: FR-0009`, or `supersedes: FR-0001` where FR-0001 has `superseded_by: null` (asymmetry) each produce exactly one warning line naming the FR and the condition under a `## Versioning warnings` section in `INDEX.md` and on stderr; the process exits 0 and `--validate` reports `Spec graph OK`; the section is omitted entirely when there are no warnings.
- **AC-6:** `INDEX.md`'s FR table gains two columns, `Ver` and `Lifecycle`, inserted immediately after `Status`, showing the effective (defaulted) values; every pre-existing column keeps its name, order, and formatting; output is deterministic (two runs on an unchanged tree produce identical bytes).
- **AC-7:** `template/specs/_template/ADR-XXXX-template.md` exists with the frontmatter fields and the seven body sections listed under "ADR template and lint", in that order; the indexer discovers `specs/decisions/ADR-*.md` and renders an `## Architecture decision records` table in `INDEX.md` (columns: ID, Title, Status, Deviation sections, Updated — where Deviation sections is `yes` only when both mandatory sections are present); an ADR lacking either deviation section, with `status` outside the enum, with `id` not matching its filename prefix, or with unparseable frontmatter produces one warning each under `## ADR warnings`, never an error; a project with no `specs/decisions/ADR-*.md` files renders neither section.
- **AC-8:** `template/scripts/deploy-gate.py` is not modified by this FR; it still imports `collect_frs`, `validate_graph`, `render_index`, `FR`, and `INDEX_PATH` from `index-specs.py` and passes `--stage full` on the template project; and the `INDEX.md` written by `deploy-gate.py` (which calls `render_index(frs, repo_files)` with two positional arguments) is byte-identical to the one written by `index-specs.py` on the same tree — including the new columns and warning sections.
- **AC-9:** `template/specs/decisions/README.md` contains a `## Revision vs supersession` section that states, at minimum: the ID stands for identity and content is versioned under it; revise in place when current implementers stay correct (bump `version`, append the DEC); a change that forces implementers to change is still a revision but `breaking: true` and `last_breaking_revision` is bumped; supersede (new ID, `supersedes`/`superseded_by`, old object `lifecycle: superseded`) only when identity changes or the old object must coexist for a migration window; and history stays with the object that made it. The same file has a `## Mandatory sections` note naming the two deviation sections and pointing at `_template/ADR-XXXX-template.md`. `template/specs/README.md` lists the ADR template in its layout block.
- **AC-10:** The `FR` dataclass in `index-specs.py` exposes the parsed fields under exactly their frontmatter names (`version`, `lifecycle`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by`, `extends`, `serves_roles`, `solution_space`, `goal`, `success_criteria`, `asserted_by`, `variability`), and the module exports a pure function `is_live(obj) -> bool` that returns `obj.lifecycle == "live"` for any object with a `lifecycle` attribute; both are covered by unit tests that import the module from `template/scripts/` by path.

## Out of scope

- The DEC and TR object types, their templates, and their discovery/parse — **FR-0004** (which depends on this FR for the shared block).
- Live-only query and filter behaviour, slice compilation, dashboards — H2/H1/H7 (the fourth Architect's FR reads this FR's field names; IDEA-0053, IDEA-0057).
- Turning any warning in this FR into a gate failure; versioning integrity, supersession integrity, undeclared-overlap, and breaking-cascade enforcement — IDEA-0056 (WS4 + H5).
- GOAL and SC object types, their files, their resolution — goals-as-spec-objects work, not yet an FR anywhere.
- Tier vocabulary, classification rules, AGENTS.md changes, foundational ADR content (plan ADR-001…005) — IDEA-0055 (WS2 + WS3), IDEA-0034 phase 4.
- Rewriting existing FR files in any project to add `version: 1` etc. Defaults are implicit; no backfill script.
- Changes to `deploy-gate.py`, `dispatch.py`, `render-docs.py`, `agent-status.py`, `spec_footprint.py`, or any hub-level script (`hub-index.py`, `bootstrap.py`). `--upgrade` already syncs `specs/_template/`, so the new templates fan out without a bootstrap change.
- Deriving `implemented_by`/`asserted_by` from code or the discovery graph — H3 (IDEA-0054), H10.

## Open questions

If unresolved, propose a default. The default is what gets implemented if the FR ships without further clarification.

- **Q:** Migration default — is implicit `version: 1`, `lifecycle: live` (no key present, no file rewritten) acceptable for every existing FR in every project, or should the template ship a one-off backfill that writes the keys?
  - **Default:** Implicit. `--upgrade` never touches `specs/`, and a backfill would dirty every project's history for no behavioural gain. An FR opts into explicit versioning the first time it is revised.
  - **Decided 2026-09-07 (Neil):** implicit migration, as defaulted; no backfill.
- **Q:** Field name for identity lifecycle — the plan says `status: live | superseded`; this FR renames it `lifecycle` because `status` is the workflow field.
  - **Default:** `lifecycle`, on FRs and (FR-0004) TRs alike. If Neil prefers the plan's name, the alternative is a *new* workflow field on FRs, which would break four scripts; not recommended.
  - **Decided 2026-09-07 (Neil):** `lifecycle` rename confirmed, as defaulted.
- **Q:** Where do SCs live and what do their IDs look like? The plan cites `SC-003-1` (GOAL-scoped) but defines no SC object; ACs already exist.
  - **Default:** `success_criteria` entries are opaque non-empty strings, shape-checked only. Interim authoring home is the FR's optional `## Success criteria` section (not parsed). SCs are outcome-level; ACs remain the per-FR testable statements and may cite an SC in their text; tests cite ACs today and SCs once H4 lands. No AC is removed or renumbered.
- **Q:** Default for `variability` when absent — `null` (undeclared) or `core`?
  - **Default:** `null`. `core` is only meaningful once a project has a tenancy model; for embedded single-client projects an implied `core` would be false precision. H10 promotes Project A FRs with an explicit value.
- **Q:** Should `draft` stay in the `lifecycle` enum for FRs, given `status: draft` already exists?
  - **Default:** Keep it (one enum for FR and TR keeps the H2 predicate uniform; TRs have no workflow `status`). On FRs `lifecycle: draft` is legal but redundant; the FR template pre-fills `live` and the indexer does not cross-check it against `status`.
- **Q:** Should the versioning arithmetic and supersession-symmetry checks be errors rather than warnings from day one, since no existing FR can trip them?
  - **Default:** Warnings. Measurement before enforcement is the established precedent (`ac_state`); IDEA-0056 turns them into gate failures with fixtures.
- **Q:** Should the template ship the revision-vs-supersession rule as a numbered ADR file (say `ADR-0000`) so DECs in every project can cite it in `authorised_by`, instead of README prose?
  - **Default:** No. `--upgrade` does not sync `specs/decisions/`, and a template-level ID would collide with projects' own numbering habits. Projects adopting decision rights get it as part of the foundational ADR pack (IDEA-0055 / plan WS3a "ADR-006"), which they number themselves.

## Dependencies

None. This is the extract-and-land-first FR; FR-0004 depends on it.

## Notes

- **Footprint is hub-relative.** `owns:`/`reads:` are paths under `<hub>/template/` (and this project's ADR), written relative to the hub root because the code under change lives there, not in this project's `src/`. This project sits inside the hub repo, but `git ls-files` run from the project root returns project-relative paths, so these globs match nothing here: no `CODEOWNERS` line and no overlap detection will fire. They are documentation for the Developer and the Chief of Staff.
- **Human approval required before implementation.** `template/scripts/index-specs.py` is on the hub's human-approval-only list (`<hub>/CLAUDE.md`). The Developer must have Neil's explicit go-ahead before editing it. Recorded here as a note, not a blocking escalation, per the dispatch.
- **Plan mapping.** The plan calls the revision-vs-supersession rule "ADR-006". In this project it is `specs/decisions/ADR-0001-revision-vs-supersession.md` (first ADR here). `ADR-0001` status is `proposed` until Neil ratifies.
- **Shared-owns with FR-0004.** Both FRs list `template/scripts/index-specs.py` and the two README files. They are linearised by `depends_on` (FR-0004 → FR-0003); dispatch FR-0004 only after FR-0003 is merged.
- **Related parked ideas (cite, not derive):** IDEA-0055 consumes `tier` and the ADR deviation sections; IDEA-0056 consumes the versioning fields for integrity gates; IDEA-0054 consumes `success_criteria` and (via FR-0004) `implemented_by`; IDEA-0034 phase 4 is where the AGENTS.md rules that reference ADR-0001 will land; IDEA-0053 (H1) reads `lifecycle`/`last_breaking_revision` for slices. pm-graph-poc's "Schema and Extractor Versioning Policy" FR versions an *extraction schema*, not spec objects — not relevant beyond the shared word.
- **Where tests go.** This project's `tests/` imports `template/scripts/index-specs.py` by path (the module name has a hyphen; use `importlib.util.spec_from_file_location`, exactly as `deploy-gate.py` does) and runs it against fixture spec trees under `tests/fixtures/`. Fixtures are synthetic.
- **ADR vocabulary reuse.** ADR `status` enum is taken from `render-docs.py`'s `BROKEN_ADR_STATUSES` plus `accepted` so the two scripts agree without either being changed.
- **`render_index` signature.** Because `deploy-gate.py` calls `render_index(frs, repo_files)` and rewrites `INDEX.md`, the ADR discovery and lint must be reachable from inside `render_index` (or via a default-argument path) so the two writers do not flip-flop the file.

## Changelog

- 2026-09-07: created
- 2026-09-07: recorded Neil's confirmation of the `lifecycle` rename and implicit-migration defaults
- 2026-09-07 — merged to main via fr/FR-0003 (feat 2941562, tests 643c232); Reviewer APPROVE. Status ready -> merged (CoS bookkeeping).
