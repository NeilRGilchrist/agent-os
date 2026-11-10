# Specs

This directory contains the spec graph: every Functional Requirement (FR) the project tracks, the Technical Requirements (TRs) that operationalise them, and the decisions made along the way — Architecture Decision Records (ADRs, principles) and Decisions (DECs, tiered choices made under a principle).

## Layout

```
specs/
├── _template/
│   ├── FR-XXXX-template.md      # Copy this to start a new FR
│   ├── TR-XXXX-template.md      # Copy this to start a new Technical Requirement (lands at specs/TR-NNNN-<slug>.md)
│   ├── DEC-XXXX-template.md     # Copy this to start a new Decision (lands at specs/decisions/DEC-NNNN-<slug>.md)
│   └── ADR-XXXX-template.md     # Copy this to start a new ADR (under decisions/)
├── _escalations/                 # Optional: escalation files when PR comments aren't enough
├── _gates/                        # Evidence for FRs' declared gates: <FR-ID>-<gate-id>.md (see "Declared gates" below)
├── decisions/                    # ADRs (principles: ADR-NNNN-<slug>.md) and DECs (tiered choices: DEC-NNNN-<slug>.md)
├── FR-0001-<slug>.md
├── FR-0002-<slug>.md
├── TR-0001-<slug>.md             # TRs live at the top level beside the FRs they operationalise
└── ...
```

## Technical requirements and decisions

- **TR (`specs/TR-NNNN-<slug>.md`)** — the agent-authored *how* for one or more FRs (`operationalises: [FR-NNNN]`). A TR carries the same versioning block as an FR, has no workflow `status` (readiness is `lifecycle: draft -> live`), and lists its implementers (`implemented_by`), success criteria and tests. Copy `_template/TR-XXXX-template.md`.
- **DEC (`specs/decisions/DEC-NNNN-<slug>.md`)** — one choice, made at a declared authority `tier`, with `status` (`proposed | ratified | rejected | superseded`), `rationale`, the ADR(s) that authorise it (`authorised_by`), and — when it changes an existing object — `revises: <FR or TR ID>` plus an honest `breaking` flag. The revised object appends the DEC to its `revisions`. Copy `_template/DEC-XXXX-template.md`. ADRs (principles) and DECs (choices under a principle) share `decisions/`; see `decisions/README.md`.

Cite stable IDs only — `TR-0014`, never `TR-0014@v2`; the indexer rejects `@` in `revises`, `implemented_by` and `tests`.

## Versioned objects

Every FR and TR carries an optional versioning block — `version`, `lifecycle`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by` — plus solution-space fields (`extends`, `serves_roles`, `solution_space`, `goal`, `success_criteria`, `asserted_by`, `variability`). All of them default when absent (`version: 1`, `lifecycle: live`, empty lists, `null`), so an FR written before the block existed needs no edits (the TR template pre-fills `lifecycle: draft`). `lifecycle` is the identity axis (is this object current?) and is independent of the workflow `status`. The rule for when to bump `version` versus mint a new ID is in `decisions/README.md` -> "Revision vs supersession"; the indexer lints the arithmetic, supersession links, DEC reciprocity (`revisions` <-> `revises`) and the `last_breaking_revision` marker as warnings under `## Versioning warnings` in `INDEX.md`, and fails the build when a `revisions` entry names a DEC with no file.

## ID allocation

- FR IDs are allocated sequentially: `FR-0001`, `FR-0002`, ...
- TR IDs (`TR-0001`, `TR-0002`, ...) and DEC IDs (`DEC-0001`, `DEC-0002`, ...) are allocated the same way — sequentially within their own type, next available number, four digits
- IDs are **never reused**, even when an FR is deprecated, a TR is superseded, or a DEC is rejected; the `id` must equal the filename prefix
- ACs within an FR are numbered `AC-1`, `AC-2`, ... and are also never reused (deprecated ACs stay in the file marked `[DEPRECATED]`)

This stability is what makes `@covers FR-XXXX:AC-Y` annotations meaningful across time.

## Index

Run `python3 scripts/index-specs.py` to regenerate `specs/INDEX.md` — a flat listing of the **default-view** FRs (see below) with status, version, lifecycle, owner, and dependencies, followed by `## Technical requirements` and `## Decisions` tables when `TR-*.md` / `decisions/DEC-*.md` files exist, an `## Architecture decision records` table when `decisions/ADR-*.md` files exist, then — only when non-empty — `## Provisional decisions` (default-view DECs with a `provisional_until`; columns `ID | Title | Trigger | Revises | Updated`) and, last, `## Retired objects` (everything outside the default view; columns `ID | Type | Title | Why | Updated`, where `Why` is `superseded by <ID>`, `superseded`, `rejected` or `pre-breaking (<target> v<p+1> < v<last_breaking_revision>)`). `INDEX.md` never evaluates dates, so it is byte-stable across days and identical whether `index-specs.py` or `deploy-gate.py` wrote it; a provisional DEC past its date trigger is reported on stderr only (`Provisional past trigger: DEC-nnnn (<trigger>)`). This is the cheapest way for an agent to orient before picking up work.

## Visibility and the default view

Every object has exactly one visibility class, computed by `scripts/spec_query.py` (a pure sibling module the indexer imports; the same predicate `is_live` / `is_live_dec` used elsewhere agrees with it: `visibility(x) == "live"` iff the predicate is true):

| Class | FR / TR (`lifecycle`) | DEC (`status`) | ADR (`status`) |
|---|---|---|---|
| `live` | `live` (the default when absent) | `proposed`, `ratified` | `proposed`, `accepted`, absent/unknown |
| `draft` | `draft` | — | — |
| `superseded` | `superseded` | `superseded` | `superseded`, `deprecated` |
| `rejected` | — | `rejected` | `rejected` |

**Default view** = `live` ∪ `draft`, minus **pre-breaking DECs** — a DEC at 1-based position `p` in its target's `revisions` produced version `p + 1` and is *current* iff `p + 1 >= last_breaking_revision` (the breaking DEC itself is current; a `null` marker makes every DEC current; a DEC that cannot be placed — `revises: null`, or not listed by its target — is treated as current). Drafts are present-tense work in flight, so they stay visible; the default hides the *past*. Class wins over window: a current-window DEC that is `rejected` or `superseded` is hidden without its opt-in. A malformed object is never hidden because it is malformed — unknown values fall to `live`; the indexer's warnings are the fix signal. Opt-ins: `superseded`, `rejected`, `history` (pre-breaking DECs), `all`.

## Query modes (read-only)

All three write nothing (no change to `INDEX.md`, `CODEOWNERS` or any tracked file), exit 0 on a valid tree, and on a tree with a hard error print the same `Spec validation FAILED` listing as `--validate` and exit 1. `--json` output uses repo-relative POSIX paths and is the contract H1 (`dispatch.py`) and H7 dashboards consume — keys are stable; new keys may be added, none renamed.

- `--list {fr,tr,dec,adr,all} [--include superseded,rejected,history,all] [--json]` — IDs one per line, or a JSON array of objects each carrying `id`, `type`, `title`, `visibility`, `path`, plus `version` and `lifecycle` (FR/TR) or `status` (DEC/ADR); DECs also carry `window` (`current` | `history`). An `--include` value outside the four opt-ins exits 1.
- `--slice <FR-nnnn|TR-nnnn> [--mode current|migration] [--json]` — the reachable subgraph: the root (any class — asking by ID is the explicit request); one object-to-object hop (TR root → `operationalises` FRs; FR root → TRs that operationalise it, its `extends` and `depends_on` FRs; default view only); the current-window DECs of every FR/TR in the set (plus DECs that `revises` one of them without being listed, with a note); those DECs' `constrained_by` FRs; and the ADRs they cite via `authorised_by` or the `ADR-nnnn` prefix of `invokes_exception`. `migration` mode additionally follows the root's `supersedes` / `superseded_by` (any class) and adds that neighbour's current window and ADRs — exactly what a migration task needs and nothing older. JSON keys: `root`, `mode`, `objects` (summaries as above plus `via` and every non-null frontmatter field), `excluded` (`id`, `class`, `via` — every object reached but not included, for slice-miss diagnostics), `notes`. Objects are ordered FR, TR, DEC, ADR then by ID. Not followed: `supersedes`/`superseded_by` in `current` mode, `revisions` outside the window, `satisfies`/`goal`/`success_criteria`, `implemented_by`/`tests`, `derived_from`/`pattern`. An unknown root, or a DEC/ADR root, is a stderr message naming the ID and exit 1.
- `--provisional [--as-of YYYY-MM-DD] [--json]` — default-view DECs with a non-null `provisional_until`, grouped `past` (ISO date `<= as_of`), `pending` (later date) and `event` (any other string — a trigger a human checks), `past` first, sorted by ID within each group. JSON keys: `as_of`, `past`, `pending`, `event` (entries: `id`, `title`, `trigger`, `revises`, `updated`, `path`). `--as-of` defaults to today.

## Consumers of the default view

| Consumer | Behaviour | Lifecycle-aware? |
|---|---|---|
| `scripts/index-specs.py` (`INDEX.md`, `--list`, `--slice`, `--provisional`) | Default view everywhere; opt-ins explicit | **Yes** |
| `scripts/deploy-gate.py` | The `INDEX.md` it writes is the default view (it calls the indexer's `render_index`). Its coverage and `@implements` gates still iterate every parsed FR by *workflow* `status`, so a `merged` FR that is later superseded still requires its tests | Index yes; gates no (whether gates should skip superseded FRs is a later integrity-gate decision) |
| `scripts/dispatch.py` | Own frontmatter parser; dispatches on `status: ready` with no lifecycle check. The compiled-slice work (H1) is where it adopts `--slice --json`, which carries `visibility` | No |
| `scripts/render-docs.py` | Renders only the FRs/ADRs a `docs/_spec/*.yaml` names explicitly; never discovers, and ignores DEC/TR files. Naming a superseded FR in a doc spec is a deliberate act | No |
| `scripts/agent-status.py` | Lists open FRs by workflow status, so it shows superseded FRs; human read-only helper | No |
| Hub `FR-INDEX.json` (`hub-index.py`) | Cross-project index; does not learn lifecycle or DEC/TR objects | No |

## Declared gates (FR-0008)

An FR may declare `gates:` in frontmatter — an optional list of mappings,
each with exactly `id` (slug, `^[a-z][a-z0-9-]{1,39}$`, unique within the
FR), `after` (`dev` | `rev` — the phase it follows), `reviewer` (`human` |
`architect` — who judges it) and `scope` (one-line, non-empty). The indexer
validates the shape and renders a `Gates` column in `INDEX.md`
(`<id>:<after>:<reviewer>` joined by `, `, or `—`). The dispatcher
(`dispatch.py`) enforces a declared `after: dev` gate before spawning a
Reviewer and before a PR leaves draft; the deploy gate (`deploy-gate.py`)
lints that a `merged` FR's gates, and an `in-review` FR's `after: dev`
gates, all carry passing evidence.

**Evidence** lives at `specs/_gates/<FR-ID>-<gate-id>.md`, one file per
declared gate, with YAML frontmatter `fr`, `gate`, `verdict` (`pass` |
`changes-requested`), `by` (a name, or `architect`), `date` (ISO date),
`round` (integer >= 1), `head_sha` (the Developer branch tip the verdict
was given against), and a free-text Markdown body (the rationale). It is a
tracked file, committed on the Developer branch — never a PR comment, never
under `_dispatch/` (gitignored) — so the deploy gate can lint it and a
human merging past a red one is a visible, auditable fact. Written by
`dispatch.py gate pass|block <FR> <gate-id> --by <who> ... --apply` (human
gates) or by a one-shot Architect gate-review session that `finalize --role
gat --apply` commits (architect gates). Never hand-edit an evidence file;
use `dispatch.py gate pass|block`.

## Writing a new FR

1. Copy `_template/FR-XXXX-template.md` to `FR-NNNN-<short-slug>.md` (next available number)
2. Fill in frontmatter
3. Write the four required sections: Why, What, Acceptance criteria, Out of scope
4. Set `status: ready` only when all four are complete and acceptance criteria are individually testable
5. Run `python3 scripts/index-specs.py`
