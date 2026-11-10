---
id: FR-0005
title: Supersession-aware indexer — live-only query surface, reachable-subgraph (slice) query, and retired/provisional views in INDEX.md (H2)
status: merged  # draft | ready | in-progress | in-review | merged | deprecated | blocked
owner: architect
depends_on: [FR-0003, FR-0004]
tags: [indexer, template, decision-rights, versioning]
# Footprint is expressed as HUB-relative paths under template/ (see Notes):
# the code under change lives in the hub's template, not in this project's src/.
owns:
  - template/scripts/spec_query.py
  - template/scripts/index-specs.py
  - template/specs/README.md
reads:
  - template/scripts/spec_footprint.py
  - template/scripts/deploy-gate.py
  - template/scripts/dispatch.py
  - template/scripts/render-docs.py
  - template/scripts/agent-status.py
  - template/specs/_template/FR-XXXX-template.md
  - template/specs/_template/TR-XXXX-template.md
  - template/specs/_template/DEC-XXXX-template.md
  - template/specs/_template/ADR-XXXX-template.md
  - specs/decisions/ADR-0001-revision-vs-supersession.md
derived_from: null
pattern: null
ac_state: {}
created: 2026-09-07
updated: 2026-09-07
---

# FR-0005: Supersession-aware indexer — live-only query surface, reachable-subgraph (slice) query, and retired/provisional views in INDEX.md (H2)

## Why

FR-0003 and FR-0004 give every spec object a lifecycle (`lifecycle` on FR/TR, `status` on DEC), a revision history (`revisions`, `last_breaking_revision`) and supersession links — but nothing *reads* them yet. Today every consumer of `specs/` (`index-specs.py`, `deploy-gate.py`, `dispatch.py`, `render-docs.py`, `agent-status.py`) globs `FR-*.md` and treats whatever it finds as current. Once a project has its first superseded TR or breaking revision, a stale decision is one file read away from any agent, and the only defence is agent discipline — the maze problem the proposal (H2) calls the single biggest navigability risk before the Project A spec repo grows past a few dozen objects. ADR-0001 rule 8 already states the outcome ("slices carry the present: current content plus DECs since `last_breaking_revision`; earlier history and superseded objects reach an agent only when its task is the migration") and defers the mechanism to this FR. Compiled slices (H1, IDEA-0053), the spec-health dashboard row "provisional past trigger" (H7, IDEA-0057), and the integrity gates (WS4, IDEA-0056) all need one query layer that answers "what is live?" the same way, so the answer is computed once, in the indexer, and never re-derived by an agent.

## What

After this FR: (1) the template ships a pure sibling module `template/scripts/spec_query.py` (same shape as `spec_footprint.py`: no I/O, no imports of the hyphenated `index-specs.py`, duck-typed on the `FR`/`TR`/`DEC`/ADR objects FR-0003/FR-0004 define) exporting a **visibility predicate**, a **default-view selector** with explicit opt-ins for `superseded`, `rejected`, `history`, `all`, a **revision-window** function, a **reachable-subgraph (slice)** query rooted at any FR or TR with `current` and `migration` modes, and a **provisional report**; (2) `template/scripts/index-specs.py` imports it, gains read-only CLI query modes (`--list`, `--slice`, `--provisional`, each with `--json`) that write nothing, and renders **only default-view objects** in the FR, TR and DEC tables of `INDEX.md`, moving everything else into a `## Retired objects` section and listing live provisional DECs under `## Provisional decisions`; (3) `deploy-gate.py`'s `render_index(frs, repo_files)` call produces a byte-identical `INDEX.md`; (4) a project with no versioning fields, or no TR/DEC files, sees output identical to the FR-0004 baseline; (5) `--validate` gains no new errors and no new warning lines — this FR filters, it does not lint.

### Visibility classes (normative — H1, H7 and WS4 read these)

`visibility(obj)` returns exactly one of four classes. "Live" for FR/TR is FR-0003's `is_live`; for DEC it is FR-0004's `is_live_dec`. ADRs are not covered by either FR and are defined here; an ADR whose frontmatter is missing or whose `status` is outside the enum is treated as `live` (ADRs are warn-only per FR-0003; a malformed object is never hidden because it is malformed).

| Class | FR / TR (`lifecycle`) | DEC (`status`) | ADR (`status`) |
|---|---|---|---|
| `live` | `live` (the default when absent) | `proposed`, `ratified` | `proposed`, `accepted`, absent/unknown |
| `draft` | `draft` | — (no such status) | — |
| `superseded` | `superseded` | `superseded` | `superseded`, `deprecated` |
| `rejected` | — | `rejected` | `rejected` |

**Default view** = `live` ∪ `draft`. Drafts are present-tense objects (the TR template pre-fills `lifecycle: draft`, and `INDEX.md` already shows `status: draft` FRs), so hiding them would hide work in flight; H2's target is hiding the *past*. **Opt-ins**: `superseded` adds that class; `rejected` adds that class; `history` adds pre-breaking DECs (below); `all` adds everything. Any other value is a `ValueError`. A stricter `ratified`-only DEC filter for client projections (FR-0004 Open questions) is not in this FR.

### Revision window (normative — the "since `last_breaking_revision`" rule)

Per FR-0004's breaking-marker arithmetic, the DEC at 1-based position `p` in an object's `revisions` produced `version p + 1`. For an object `X`:

- if `X.last_breaking_revision` is `null`, every DEC in `X.revisions` is **current**;
- otherwise a DEC at position `p` is **current** iff `p + 1 >= X.last_breaking_revision` — the breaking DEC itself is current (it defines the contract in force) and so is everything after it; DECs before it are **pre-breaking** (`history`).

The window uses the *recorded* `last_breaking_revision`, not a recomputation from `breaking` flags; when the two disagree, FR-0004's lint has already warned and WS4 (IDEA-0056) will make it an error. A DEC with `revises: null` (a creating DEC) or whose `revises` target does not list it in `revisions` (reciprocity gap, warned by FR-0004) cannot be placed in a window and is treated as **current** — the conservative direction is to show more, not less, and the lint line is the signal to fix it. A current-window DEC whose own class is `superseded` or `rejected` stays hidden by default: class wins over window.

### Reachable subgraph — the slice query (the H1 seam)

`slice(graph, root_id, mode="current") -> Slice`. The root may be any FR or TR ID of any class (asking for it by ID is the explicit request); a DEC or ADR root, or an unknown ID, is an error. Edges followed, one hop from the root for object-to-object edges, then DEC windows for every FR/TR in the set, then ADRs for every DEC in the set:

| From | Edge | To | Included when |
|---|---|---|---|
| TR root | `operationalises` | FR | default view |
| FR root | reverse `operationalises` | TR | default view |
| FR (root only) | `extends`, `depends_on` | FR | default view |
| every FR/TR in the set | `revisions` ∩ current window | DEC | default view |
| every DEC in the set | `constrained_by` | FR | default view |
| every DEC in the set | `authorised_by`; the `ADR-nnnn` prefix of `invokes_exception` | ADR | default view (ADR resolution missing → recorded as a note, never an error) |
| root only, **`migration` mode** | `supersedes`, `superseded_by` | FR / TR | **any class** — then that object's current-window DECs and their ADRs, by the rows above |

Not followed: `supersedes`/`superseded_by` in `current` mode; `revisions` outside the window; `satisfies`, `goal`, `success_criteria` (no object types exist); `implemented_by`, `tests` (paths — H3, IDEA-0054); `derived_from`, `pattern` (hub-level). Every object reached along a followed edge but not included is recorded in `Slice.excluded` as `(id, class, via)` so H1 can log slice-miss diagnostics and tests can assert exclusions. Every included object carries its class, so a `draft` FR in a slice is visible as such. Object order in the result is by type (FR, TR, DEC, ADR) then ID — deterministic. Under ADR-0001 rules 6, 7 and 9 the DEC that performed a migration-window supersession revises the *old* object with `breaking: true`, so the old object's current window *is* the migration DEC (with its `provisional_until`); `migration` mode therefore delivers exactly what a migration task needs and nothing older.

The slice returns parsed objects (paths and frontmatter fields); it does not read or serialise Markdown bodies. H1 owns the context document.

### Provisional report

`provisional(decs, as_of: date) -> ProvisionalReport` considers only default-view DECs with non-null `provisional_until` and classifies each as **`past`** (`provisional_until` parses as an ISO `YYYY-MM-DD` date `<= as_of`), **`pending`** (parses, `> as_of`), or **`event`** (any other string — an event trigger, checked by a human; H7 lists these separately). `as_of` is a parameter so tests and dashboards are deterministic; the CLI defaults it to today.

### CLI (index-specs.py) — read-only query modes

All three modes behave like `--validate` with respect to writing: they write nothing, and on a tree with hard errors they print the same `Spec validation FAILED` listing and exit 1 (a slice over a broken graph is exactly the stale-context risk H2 exists to prevent).

- `--list {fr,tr,dec,adr,all} [--include superseded,rejected,history,all] [--json]` — IDs (one per line) or a JSON array of objects each carrying at least `id`, `type`, `title`, `visibility`, `path`, plus `version` and `lifecycle` (FR/TR) or `status` (DEC/ADR).
- `--slice <FR-nnnn|TR-nnnn> [--mode current|migration] [--json]` — human summary or a JSON object with `root`, `mode`, `objects` (as above, plus each object's non-null frontmatter fields), `excluded` (`id`, `class`, `via`), `notes`. Unknown root, or a DEC/ADR root: stderr message naming the ID, exit 1.
- `--provisional [--as-of YYYY-MM-DD] [--json]` — the report, grouped `past` / `pending` / `event`; `past` first.

`--json` output uses repo-relative POSIX paths and is the contract H1 (`dispatch.py`) and H7 consume; keys named here are stable.

### INDEX.md

- The FR table (FR-0003 columns), `## Technical requirements` and `## Decisions` tables (FR-0004) list **default-view objects only**. The `## Architecture decision records` table is unchanged (it already carries a Status column and is warn-only territory).
- New section `## Retired objects`, placed after the ADR table (last), columns `ID | Type | Title | Why | Updated`, sorted by ID, where `Why` is one of `superseded by <ID>`, `superseded` (no link recorded), `rejected`, `pre-breaking (<revises-target> v<p+1> < v<last_breaking_revision>)`. Omitted when empty.
- New section `## Provisional decisions`, placed immediately before `## Retired objects`, columns `ID | Title | Trigger | Revises | Updated`, listing every default-view DEC with non-null `provisional_until`, sorted by ID. It **never evaluates dates** — the file must be byte-stable across days and across the two writers — so `past`/`pending` appears only in the CLI report and as stderr lines at index time (`Provisional past trigger: DEC-nnnn (<trigger>)`), which never change the exit code. Omitted when empty.
- Because `deploy-gate.py` calls `render_index(frs, repo_files)` with FRs only, the TR/DEC collection and both new sections must be reachable from inside `render_index` (the constraint FR-0004 already imposes for its own tables).

### Consumers — who uses the live-only default, and who is listed with a reason

| Consumer | After this FR | Modified here? |
|---|---|---|
| `index-specs.py` (`INDEX.md`, CLI) | Default view everywhere; opt-ins explicit | **Yes** |
| `deploy-gate.py` | `INDEX.md` it writes is the default view (via `render_index`). Its coverage and `@implements` gates still iterate every parsed FR by *workflow* `status`, so a `merged` FR that is later superseded still requires its tests | No — owned by FR-0002, human-approval-only; whether gates should skip superseded FRs is IDEA-0056's call (Open questions) |
| `dispatch.py` | Unchanged: own frontmatter parser (`load_frs`, `fr_owns_globs`), dispatches on `status: ready` with no lifecycle awareness | No — owned by FR-0002; H1 (IDEA-0053) is where dispatch adopts `--slice --json` and the live-only default; interim risk recorded in Open questions |
| `render-docs.py` | Unchanged: renders only the FRs/ADRs a `docs/_spec/*.yaml` names explicitly, never discovers; globs `ADR-*`/`FR-*` so it ignores DEC and TR files. Naming a superseded FR in a doc spec is a deliberate act; its gap report may list a superseded active-status FR as "uncovered" | No — H8 (IDEA-0057) generalises projections; no accidental rendering of superseded objects can start here |
| `agent-status.py` | Unchanged: lists open FRs by workflow status, so it shows superseded FRs | No — human read-only helper; H7 dashboards replace it |
| `<hub>/scripts/hub-index.py` (`FR-INDEX.json`) | Unchanged; the cross-project index does not learn lifecycle here | No — hub script, out of scope; separate FR if wanted |

## Acceptance criteria

Each AC must be independently testable. Conventions as in FR-0003/FR-0004: "the indexer" is `template/scripts/index-specs.py` run from a project root; "error" = stderr message naming the file/field/ID and exit 1; "warning" = line under a named `INDEX.md` section and on stderr, exit 0. "The fixture tree" is the synthetic tree described in AC-12.

- **AC-1:** `template/scripts/spec_query.py` exports `visibility(obj) -> str` returning exactly the class in the visibility table for every value of FR/TR `lifecycle` (including absent → `live`), DEC `status`, and ADR `status` (including absent or out-of-enum → `live`); `visibility` agrees with FR-0003's `is_live` and FR-0004's `is_live_dec` (`visibility(x) == "live"` iff the predicate is true) on every FR/TR/DEC fixture; the module performs no file or subprocess I/O and does not import `index-specs.py`.
- **AC-2:** `select(objs, include=frozenset())` returns, in ID order, exactly the `live` and `draft` objects when `include` is empty; `{"superseded"}` adds exactly the `superseded` class, `{"rejected"}` exactly the `rejected` class, `{"history"}` exactly the pre-breaking DECs, `{"all"}` every object; the sets compose (`{"superseded", "rejected"}` is the union); any other value raises `ValueError` naming the bad value.
- **AC-3:** `revision_window(obj, decs_by_id) -> (current, history)`: for a TR with `revisions: [DEC-0001, DEC-0002, DEC-0003]`, `DEC-0002` `breaking: true`, `last_breaking_revision: 3`, `current == [DEC-0002, DEC-0003]` and `history == [DEC-0001]`; with `last_breaking_revision: null` all three are current; with `last_breaking_revision: 4` only `DEC-0003` is current; the split uses the recorded field even when it disagrees with the `breaking` flags (the FR-0004 warn case); a DEC with `revises: null`, or one whose target does not list it, is classified current and named in a note; a current-window DEC with `status: rejected` or `status: superseded` is not returned by `select` without the matching opt-in.
- **AC-4:** `slice(graph, root_id)` in `current` mode, rooted at the fixture tree's live successor TR, returns the root, the live FR it operationalises, the current-window DECs of the root and of that FR, the live ADRs those DECs cite via `authorised_by` and via the `ADR-nnnn` prefix of `invokes_exception`, and the default-view FRs in those DECs' `constrained_by`; it contains **no** object whose class is `superseded` or `rejected` and **no** pre-breaking DEC; each such object reached along a followed edge appears in `Slice.excluded` as `(id, class, via)`; objects are ordered FR, TR, DEC, ADR then by ID; two calls on the same graph return equal results.
- **AC-5:** `slice(graph, root_id, mode="migration")` returns everything `current` mode returns plus, for the root only, the object named by `supersedes` and the object named by `superseded_by` regardless of class, each with its own current-window DECs and their ADRs — so for the fixture successor TR it adds the superseded predecessor TR and the migration-window DEC (`breaking: true`, non-null `provisional_until`, `invokes_exception` set) and nothing older; for a root with `supersedes: null` and `superseded_by: null` the result equals `current` mode plus one note saying so; `mode` outside `{current, migration}` raises `ValueError`.
- **AC-6:** Root rules: `slice` accepts any FR or TR ID present in the graph, of any class (a `superseded` root is returned as the root with `visibility: superseded`); an FR root includes the default-view TRs whose `operationalises` names it and the default-view FRs in its `extends` and `depends_on`; a DEC ID, an ADR ID, or an ID not in the graph raises `KeyError`/`ValueError` naming the ID, and the CLI maps it to a stderr message naming the ID with exit 1.
- **AC-7:** `provisional(decs, as_of)`: only default-view DECs with non-null `provisional_until` are reported; `2026-06-30` with `as_of = 2026-09-07` is `past`, `2026-12-31` is `pending`, `after Project A pilot tenant 2 onboards` is `event`; a `rejected` or `superseded` DEC with a past date is not reported; results are sorted by ID within each group; two calls with the same `as_of` are equal.
- **AC-8:** CLI: `--list fr|tr|dec|adr|all`, `--slice <ID>`, and `--provisional` each write nothing (no change to `INDEX.md`, `CODEOWNERS`, or any tracked file — asserted the way the existing `--validate` test does), exit 0 on a valid tree, and on a tree with a hard error print the same `Spec validation FAILED` listing as `--validate` and exit 1; `--include` accepts a comma-separated subset of `superseded,rejected,history,all` and rejects anything else with exit 1; `--json` output parses as JSON and carries the keys named under "CLI" (`id`, `type`, `title`, `visibility`, `path` per object; `root`, `mode`, `objects`, `excluded`, `notes` for a slice; `past`, `pending`, `event` for the report), with `path` values repo-relative POSIX; `--as-of` overrides today and `--provisional` output for the fixture tree with `--as-of 2026-09-07` lists exactly the AC-7 classification.
- **AC-9:** `INDEX.md` default view: on the fixture tree the FR, `## Technical requirements` and `## Decisions` tables contain only default-view objects; a `## Retired objects` table with columns `ID | Type | Title | Why | Updated` appears after the `## Architecture decision records` table listing every superseded FR/TR/DEC, rejected DEC and pre-breaking DEC with the `Why` wording given above; a `## Provisional decisions` table with columns `ID | Title | Trigger | Revises | Updated` appears immediately before it listing every default-view DEC with non-null `provisional_until`; both sections are omitted when they would be empty; the ADR table is unchanged from FR-0003; the file contains no `past`/`pending` word and is byte-identical across two runs on the same tree regardless of the system date; past-trigger lines appear on stderr only and the exit code is 0.
- **AC-10:** `template/scripts/deploy-gate.py` is not modified by this FR, still imports `collect_frs`, `validate_graph`, `render_index`, `FR`, `INDEX_PATH` unchanged, passes `--stage full` on the fixture tree, and the `INDEX.md` it writes is byte-identical to the one `index-specs.py` writes on the same tree — including `## Retired objects` and `## Provisional decisions`.
- **AC-11:** Backward compatibility: for `template/` itself, for every project registered in `<hub>/hub/projects.yaml` at implementation time, and for a fixture tree with no versioning fields and no TR/DEC files, the indexer's exit code, stderr, and `INDEX.md` are identical to the FR-0004 baseline (no `## Retired objects`, no `## Provisional decisions`, no new stderr lines); `--validate` on the full fixture tree exits 0 with `Spec graph OK` and produces exactly the warning lines FR-0003/FR-0004 define for it and no others — this FR adds no error and no warning line.
- **AC-12:** A synthetic fixture tree under this project's `tests/fixtures/spec_query/` contains at least: a superseded FR (`lifecycle: superseded`, `superseded_by` set) and its live successor; a superseded TR whose current window is exactly one migration-window DEC (`revises: <old TR>`, `breaking: true`, `provisional_until` a past date, `invokes_exception: ADR-0001§when-you-may-deviate`, `authorised_by: [ADR-0001]`) and its live successor TR at `version: 1`; a live TR with `revisions: [DEC-a, DEC-b, DEC-c]`, `DEC-b` breaking, `last_breaking_revision: 3` (so `DEC-a` is pre-breaking); a rejected DEC that `revises` a live TR; a live DEC with `provisional_until` in the future and one with an event string; and one ADR of each of `accepted`, `proposed`, `superseded`. Every AC above cites the object(s) in this tree it exercises, and the tree passes `--validate`.
- **AC-13:** `template/specs/README.md` documents the visibility table, the default-view rule, the three CLI query modes with their flags and JSON keys, and the consumer table above; and the implementing PR's diff is empty for `template/scripts/deploy-gate.py`, `template/scripts/dispatch.py`, `template/scripts/render-docs.py`, and `template/scripts/agent-status.py`.

## Out of scope

- Compiling the slice into a context document, sizing it, delivering it to an agent, or changing `dispatch.py` to call `--slice` — **H1, IDEA-0053**. This FR ends at the JSON contract.
- Dashboards, the `dashboards/` folder, pairing metrics, the projection library — **H7/H8, IDEA-0057**. `--provisional` and `--list --include all` are the queries they call.
- Any new hard error or warning: versioning integrity, supersession symmetry, "superseded object with live implementers", `ready` + `superseded` — **IDEA-0056 (WS4 + H5)**. This FR consumes FR-0003/FR-0004's lint output; it emits none.
- Any modification to `deploy-gate.py`, `dispatch.py`, `render-docs.py`, `agent-status.py`, `spec_footprint.py`, `bootstrap.py`, or `hub-index.py` (see the consumer table for why each is left alone).
- A `ratified`-only DEC filter for client projections; tier-aware filtering; `client_visible` filtering — **IDEA-0058 (WS5)**.
- Slice depth beyond one object-to-object hop; following `implemented_by`/`tests` into code — **IDEA-0054 (H3/H4)**.
- GOAL / SC objects and following `satisfies`, `goal`, `success_criteria`.
- Rewriting any existing spec file, in any project, to add versioning fields. Defaults remain implicit (FR-0003).
- Teaching the hub's `FR-INDEX.json` about lifecycle or DEC/TR objects.
- Serialising Markdown bodies in `--slice --json`.

## Open questions

If unresolved, propose a default. The default is what gets implemented if the FR ships without further clarification.

- **Q:** Should `draft` objects be in the default view, given H2 says "live objects only"?
  - **Default:** Yes. Drafts are the future, not the past; `INDEX.md` already shows `status: draft` FRs and the TR template pre-fills `lifecycle: draft`. H2's harm is stale content reaching an agent, and a draft is not stale. If Neil wants strict liveness, `select` gains an `exclude_draft=True` flag — one line — and the slice keeps drafts (an agent dispatched on a draft TR needs it).
- **Q:** Should pre-breaking DECs stay in `INDEX.md`'s `## Decisions` table (they are still `ratified`) or move to `## Retired objects`?
  - **Default:** Move them. ADR-0001 rule 8 says the present is "current content plus DECs since `last_breaking_revision`"; the Decisions table should be the present. The `Why` column names the target and the version arithmetic so nothing is lost for a human reader, and `--include history` recovers them.
- **Q:** New sibling module `spec_query.py` versus growing `index-specs.py`?
  - **Default:** Sibling module, pure, duck-typed. It mirrors `spec_footprint.py`, keeps the human-approval-only file's diff to CLI flags and two render sections, and shrinks the three-way `owns:` overlap on `index-specs.py`. `--upgrade` syncs `scripts/`, so it fans out without a bootstrap change.
  - **Decided 2026-09-07 (Neil):** sibling `spec_query.py` module, as defaulted.
- **Q:** `dispatch.py` will still dispatch an FR with `status: ready` and `lifecycle: superseded`. Fix here?
  - **Default:** No. `dispatch.py` is FR-0002's footprint and has its own frontmatter parser; the right fix is H1 making it consume `--slice --json` (which carries `visibility`) rather than a second lifecycle check. Interim exposure is tiny: nothing in any registered project is superseded today, and a `ready`+`superseded` object is a human error IDEA-0056 should make a hard error.
- **Q:** Should `deploy-gate.py` stop requiring `@covers` tests for a `merged` FR that has since been superseded (tests get deleted during the migration)?
  - **Default:** Not in this FR — the gate is approval-only and FR-0002's. Record for IDEA-0056: a superseded object's coverage requirement should end when the migration DEC's `provisional_until` trigger fires, not before.
- **Q:** ADR liveness — is `proposed` live for slice purposes?
  - **Default:** Yes (`proposed`, `accepted`), matching FR-0004's decision that a `proposed` DEC is the current best recommendation. `render-docs.py` treats `proposed` as broken *for client documents*, a different audience; the two need not agree.
- **Q:** Should `INDEX.md` show which provisional DECs are past their trigger?
  - **Default:** No — that would make the file depend on the system date, breaking byte-identity between `deploy-gate.py` and `index-specs.py` across a midnight and dirtying trees with no spec change. The file lists all provisional DECs; the CLI and stderr do the date math; H7 renders the dashboard.
- **Q:** A DEC that `revises` X but is not in `X.revisions` — include in X's slice or exclude?
  - **Default:** Include as current, with a note. Excluding hides a decision an author clearly meant to attach; FR-0004's reciprocity warning is the fix signal.
- **Q (FR-0004 defect, recorded here per dispatch):** FR-0004's reciprocity check (a) — "for each DEC whose `revises` names an object, the object's `revisions` should contain the DEC" — does not exempt `status: rejected` DECs. A rejected proposal legitimately has `revises` set and is legitimately absent from `revisions` (it never revised anything), so every rejected DEC would warn forever. This FR's fixture (AC-12) contains exactly such a DEC and AC-11 requires `--validate` output to equal "the warnings FR-0003/FR-0004 define for it", so the fixture will carry that warning until FR-0004 is amended.
  - **Default:** Ask the FR-0004 Architect to exempt `status: rejected` (and arguably `status: superseded`) DECs from reciprocity check (a). Until then, the Reviewer's expected-warnings list for the fixture includes that line; this FR's filtering already treats rejected DECs as excluded regardless.
  - **Resolved in FR-0004 changelog 2026-09-07:** forward reciprocity now applies to live DECs only (`is_live_dec`); `rejected` and `superseded` DECs are exempt, `proposed` DECs are not. The AC-12 rejected DEC carries no warning.

## Dependencies

- **FR-0003** — defines `lifecycle`, `version`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by`, `extends` on FRs, the `is_live` predicate, ADR discovery, the `## Versioning warnings` section, and the `render_index(frs, repo_files)` compatibility constraint. Every predicate here reads those names.
- **FR-0004** — defines the `DEC` and `TR` dataclasses, `status` liveness (`is_live_dec`), `revises`, `breaking`, `authorised_by`, `invokes_exception`, `constrained_by`, `provisional_until`, `operationalises`, `collect_graph()`, and the breaking-marker arithmetic (`last_breaking_revision == position + 1`) the revision window relies on. Do not dispatch until FR-0004 is merged.

## Notes

- **Overlap check outcome (pre-answered by the Chief of Staff): net-new, option (c).** Cited, not derived: **IDEA-0053** (H1 compiled slices — the primary consumer; `slice()`/`--slice --json` is the seam it calls), **IDEA-0056** (WS4 gates — adds the hard integrity errors; this FR deliberately adds none), **IDEA-0057** (H7 dashboards — consumer of `provisional()` and `select(include={"all"})`). Also related: IDEA-0054 (H3, will follow `implemented_by` from a slice later), IDEA-0058 (WS5, stricter `ratified`-only view).
- **Footprint is hub-relative** under `<hub>/template/`, as in FR-0002/FR-0003/FR-0004. This project sits inside the hub repo but `git ls-files` from the project root returns project-relative paths, so these globs match nothing here: no `CODEOWNERS` line and no overlap warning fires. They are documentation for the Developer and the Chief of Staff.
- **Human approval required before implementation.** `template/scripts/index-specs.py` is on the hub's human-approval-only list (`<hub>/CLAUDE.md`). The Developer needs Neil's explicit go-ahead before editing it. Note, not a blocking escalation, per the dispatch. `spec_query.py` is new and not on the list.
- **Three-way (now four-way) overlap on `template/scripts/index-specs.py`** with FR-0002, FR-0003, FR-0004. The Chief of Staff sequences these; the natural order is **FR-0003 → FR-0004 → FR-0005 → FR-0002** (FR-0002's touch is a metrics hook, independent of the object model). This FR does not attempt to resolve the overlap.
- **`render_index` is the single choke point.** `deploy-gate.py` calls `render_index(frs, repo_files)` and rewrites `INDEX.md`; if the retired/provisional sections were only reachable from `main()`, the two writers would flip-flop the file. FR-0004 already requires TR/DEC collection inside `render_index`; this FR's sections ride the same path.
- **JSON is the contract.** H1 will call `python scripts/index-specs.py --slice TR-nnnn --json` from `dispatch.py` (it already shells out to the indexer); H7 will call `--provisional --json` and `--list all --include all --json`. Keep the keys named under "CLI" stable; add, never rename.
- **Where tests go.** This project's `tests/unit/scripts/` imports `template/scripts/spec_query.py` (importable by name — no hyphen) and `index-specs.py` by path via `importlib.util.spec_from_file_location`, exactly as `tests/unit/scripts/test_index_specs.py` does today; CLI ACs run via `subprocess` against a copy of the fixture tree so "writes nothing" is provable. Add `spec_query.py` to that test module's `_COPY_SCRIPTS` tuple. Fixtures are synthetic (`tests/fixtures/README.md`).
- **`agent-status.py` did not crash** with a cp1252 error this session — it already carries `_ascii_fold`/`safe_print` guards. No action.
- **What surprised the Architect.** Three consumers (`dispatch.py` — 5,156 lines — `render-docs.py`, `agent-status.py`) each carry their *own* frontmatter parser and never import `index-specs.py`; the live-only default therefore cannot reach them by construction, only by adoption (H1 for dispatch, H7/H8 for the other two). That is why the consumer table lists rather than fixes them.

## Changelog

- 2026-09-07: created
- 2026-09-07: recorded Neil's confirmation of the sibling `spec_query.py` default; noted the FR-0004 reciprocity defect as resolved in FR-0004's 2026-09-07 changelog
- 2026-09-07 — merged to main via fr/FR-0005 (feat 9a8fad3, fix fa2e3a4, tests a84dba6); Reviewer APPROVE. Status ready -> merged (CoS bookkeeping). Non-blocking follow-ups from review: provisional() two-arg form classifies by class only (pass objs_by_id; README line for H7); --json/--include without a query flag fall through to the write path; constrained_by FRs get no revision window (Architect to pin).
