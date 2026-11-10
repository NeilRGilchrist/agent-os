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
- ACs within an FR are numbered `AC-1`, `AC-2`, ... sequentially and are also never reused: an AC that is deferred, withdrawn or superseded keeps its number and its text (see "Deferred, withdrawn and superseded ACs" below)

This stability is what makes `@covers FR-XXXX:AC-Y` annotations meaningful across time.

## Index

Run `python3 scripts/index-specs.py` to regenerate `specs/INDEX.md` — a flat listing of the **default-view** FRs (see below) with status, version, lifecycle, owner, and dependencies, followed by `## Technical requirements` and `## Decisions` tables when `TR-*.md` / `decisions/DEC-*.md` files exist, an `## Architecture decision records` table when `decisions/ADR-*.md` files exist, then — only when non-empty — `## Provisional decisions` (default-view DECs with a `provisional_until`; columns `ID | Title | Trigger | Revises | Updated`) and, last, `## Retired objects` (everything outside the default view; columns `ID | Type | Title | Why | Updated`, where `Why` is `superseded by <ID>`, `superseded`, `rejected` or `pre-breaking (<target> v<p+1> < v<last_breaking_revision>)`). `INDEX.md` never evaluates dates, so it is byte-stable across days and identical whether `index-specs.py` or `deploy-gate.py` wrote it; a provisional DEC past its date trigger is reported on stderr only (`Provisional past trigger: DEC-nnnn (<trigger>)`). This is the cheapest way for an agent to orient before picking up work.

## Deferred, withdrawn and superseded ACs

An AC that is deliberately not delivered in this pass is recorded in the FR's `ac_state`, never by editing its text out of the gate's sight. The entry names one of three states and a `moved_to` pointer saying where the work went:

```yaml
ac_state:
  11: {state: deferred, moved_to: IDEA-0049}
  12: {state: withdrawn, moved_to: null, reason: "Not needed for the pilot; no follow-up planned"}
  9:  {state: superseded, moved_to: FR-0011, reason: "Capture path replaced (ADR-0002)"}
```

**Choosing the state** (consistent with "Revision vs supersession" in `decisions/README.md`):

- `deferred` — the AC is still part of this FR's need and will be delivered, just not now. Its text stays under `## Acceptance criteria`. `moved_to` names where the work is tracked: a parked IDEA, a follow-up FR, or this FR itself. It is listed under `## Open deferrals` until the entry is deleted and a test covers the AC.
- `withdrawn` — the AC is no longer wanted and nothing replaces it. `moved_to` is usually `null` with a `reason`, or the DEC or ADR that withdrew it. An AC "deferred to no target" is `withdrawn`, not `deferred`: nothing will deliver it, so listing it as open would be noise.
- `superseded` — another object now carries the AC's need. `moved_to` names the successor FR, or the DEC or ADR that moved it. The ratification meaning of `superseded` (a ratified AC replaced by newer text) is the same idea, so one state serves both.

Changing an AC's state is a spec change: record it in the Changelog, and as a DEC when the project tracks revisions.

**The `moved_to` rule.** `moved_to` is required, and is `FR-NNNN`, `IDEA-NNNN`, `ADR-NNNN`, `DEC-NNNN` or `null`. `null` is allowed only for `deferred` and `withdrawn`, and only with a non-empty `reason`; `superseded` always needs a non-null pointer. `reason` is otherwise optional, as are `source`, `ratified` and `hash`. An `FR-NNNN` must name an FR in this project, a `DEC-NNNN` a `decisions/DEC-NNNN-*.md` that parses, and an `ADR-NNNN` a `decisions/ADR-NNNN-*.md` file; a pointer that does not resolve is warned about. `moved_to` may name the FR's own ID in any exemption state; for `superseded` it means another AC of the same FR replaced it. An `IDEA-NNNN` is checked for shape only in `INDEX.md` and by the gate, which never look outside the project. When `index-specs.py` can find the hub (`DISPATCH_HUB_ROOT`, or the first ancestor holding `scripts/parking.py` and `parking-lot/`), it also checks each IDEA pointer against the hub parking lot and prints `Deferral pointer warnings` on stderr for a missing or archived IDEA. That check never reaches `INDEX.md` or the exit code. An entry that breaks any of these rules is **not honoured**: its AC is live again, so the gate fails closed. Every problem is a warning under `## AC ratification warnings`; the indexer's exit code never changes. Entries in these three states alone do not opt an FR into ratification tracking (no `no ac_state entry for …` warning).

**Gate effects.** `deploy-gate.py` learns the honoured entries from the indexer (`coverage_exemptions`) and reads nothing else: no section heading or AC-text tag such as `[P2]` or `[DEPRECATED]` exempts an AC.

- Check 2 accepts a covering annotation on an exempt AC even when its text is in a form the gate does not detect, so tests that carry history need not be deleted. An annotation on an AC that is neither detected nor exempt still fails `covers-unknown-ac`.
- Check 3 (`review` and `full`) skips exempt ACs and lists only the live ones that are missing.
- An entry that is not honoured is printed under `Deploy gate WARNINGS:` at every stage, with the warning class `ac-exemption-invalid`.
- An `in-review` or `merged` FR whose every AC is exempt gets the warning `every AC is deferred, withdrawn or superseded` and the class `ac-all-exempt`, never a failure. The fix is usually `status: deprecated` or `lifecycle: superseded`.

**The `## Withdrawn acceptance criteria` section** holds the text of `withdrawn` and `superseded` ACs in the ordinary `- **AC-N:** <original text>` form, or the labelled `- **AC-N (L):** <original text>` form. `deferred` ACs stay under `## Acceptance criteria`. `ac_state` wins: the indexer warns when the section and `ac_state` disagree (an AC under the section with no entry, or an entry that is not honoured, is live for coverage (a honoured `deferred` AC there stays exempt, and gets the next warning instead); a honoured withdrawn or superseded AC still under `## Acceptance criteria`; a `deferred` AC under the section; one AC in both sections; an entry whose AC has no text anywhere). Other lines in the section are ignored.

**`## Open deferrals`** in `INDEX.md` lists every honoured `deferred` entry, on any FR, with its FR status, pointer (`none` for `null`) and reason, sorted by FR then AC. It sits after `## AC ratification warnings` and is omitted when there is none.

**Migrating a hand-written convention.** For each AC written as `- **[DEPRECATED] AC-N** (withdrawn ...)` under `## Withdrawn acceptance criteria`:

1. Add `N: {state: withdrawn|superseded, moved_to: <ID or null>, reason: "<the parenthetical>"}` to `ac_state`.
2. Rewrite the bullet as `- **AC-N:** <original text>`, dropping the `[DEPRECATED]` marker and any `>` quote. Keep the section's introductory paragraph, but delete any "No test may cover them" sentence.
3. Optionally restore deleted tests that carry history; check 2 now accepts them.
4. For each tagged AC to defer (for example `[P2]`), add `N: {state: deferred, moved_to: IDEA-NNNN}`. Park the IDEA first, so the pointer names a real file.
5. Run `index-specs.py`. `## AC ratification warnings` should list nothing new for the FR, and `## Open deferrals` should list the deferrals.

Skipping step 2 is safe, because the gate still honours the entry; the "has no text in this FR" warning stays until the bullet is fixed.

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
| `scripts/deploy-gate.py` | The `INDEX.md` it writes is the default view (it calls the indexer's `render_index`). Its coverage and `@implements` gates still iterate every parsed FR by *workflow* `status`, so a `merged` FR that is later superseded still requires its tests. Coverage skips ACs exempt by a honoured `deferred`, `withdrawn` or `superseded` `ac_state` entry (see "Deferred, withdrawn and superseded ACs") | Index yes; gates no (whether gates should skip superseded FRs is a later integrity-gate decision) |
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
