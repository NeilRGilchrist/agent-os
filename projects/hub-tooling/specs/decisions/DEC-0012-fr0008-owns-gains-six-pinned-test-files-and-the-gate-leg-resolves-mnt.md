---
id: DEC-0012
title: FR-0008's `owns:` gains the six pinned test files and FR-0002's metrics fixture its Reviewer must re-point for AC-1's `Gates` column and AC-9/AC-11's authorised enum additions — Reviewer-only and bounded per test id; and the gate leg resolves the implementation role (`dev`, else `mnt`) so declared gates work on a maintainer-mode FR, with AC-8's draft refusal applying to `_finalize_oneshot` as well (AC-2, AC-3, AC-6, AC-8, AC-13)
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0008's PR merges
satisfies: []
constrained_by: [FR-0002, FR-0003, FR-0004, FR-0005, FR-0012, FR-0013]
revises: FR-0008
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave the six files out of `owns:` and let the FR-0002 / FR-0003 / FR-0004 / FR-0005 / FR-0012 Reviewers repair their own pins in backfill runs"
  - "Turn the closed-enum pins (KINDS, ROLES, GATE_FAILURE_CLASSES) into 'every emitted kind is known' reachability tests instead of extending the literals"
  - "Retire test_headless_conduct.py::test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8[orchestrator], as FR-0012's Reviewer offered"
  - "Re-point the three byte-identical pinned-baseline comparisons at 706ba9d instead of normalising the new column away"
  - "A glob over template/tests/unit/scripts/test_index_*.py and the metrics test files rather than six explicit paths"
  - "Accept gate_status / gate pass pinned to the literal claude/dev-<FR> and file the maintainer-mode gap as a follow-up FR"
  - "Two DECs in one version step (one for the footprint, one for the branch resolution)"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  Fifteen tests across six files went red at `681d661`. Every one is a
  closed-world pin that FR-0008's own human-approved ACs deliberately open:
  AC-1 adds a `Gates` column to the FR table, AC-11 adds one metrics kind
  and one role, AC-9 adds two `gate.run` failure classes, AC-12 adds a
  paragraph to `orchestrator.md`. No guarantee of FR-0002, FR-0003,
  FR-0004, FR-0005 or FR-0012 narrows — each of those FRs keeps the
  mechanism it pinned (a closed, validator-enforced enum; an index whose
  pre-FR columns are unchanged; a conduct block plus AC-8's restatement and
  nothing else) and only the membership or the anchor moves. That makes
  this the DEC-0006 / DEC-0008 / DEC-0010 kind of revision, not the
  DEC-0002 / DEC-0005 / DEC-0007 kind: architect-tier, and the footprint is
  what has to catch up, because since FR-0010 AC-5 a dispatched Reviewer's
  write grants derive from `owns:`. The second half of the DEC is a defect
  found while ruling on the first: `gate_status`, `gate pass|block` and
  `_finalize_gat`'s fast-forward are pinned to the literal `claude/dev-<FR>`,
  so a gate declared on a maintainer-mode FR can never be satisfied — the
  exact gap DEC-0009 closed on the rev leg for the same reason, on an FR
  class every wave-1 FR in this project belongs to.
created: 2026-09-22
updated: 2026-09-22
---

# DEC-0012: FR-0008's `owns:` gains six pinned test files and the metrics fixture; the gate leg resolves `dev`-else-`mnt`

## Context

FR-0008's maintainer-mode Developer implemented all thirteen ACs at `681d661`
(`fr/FR-0008`, rebased on `706ba9d`). `python -m pytest template/tests tests -q`
reports **1374 passed, 15 failed** against a `706ba9d` baseline of **1387 passed,
0 failed**; the Architect reproduced all fifteen at `681d661`. Not one is a
regression. Each is a test that pins a closed world the spec graph has since
deliberately opened, in a file outside FR-0008's `owns:`:

| File | Owner FR | Red ids | Opened by |
|---|---|---|---|
| `test_index_specs_versioning.py` | FR-0003 | `test_unversioned_index_minus_new_columns_is_unchanged`, `test_index_columns_inserted_after_status_with_defaults` | AC-1's `Gates` column |
| `test_index_specs_dec_tr.py` | FR-0004 | `test_tables_sit_after_fr_warning_sections_and_before_adr_table`, `test_fr_only_tree_gives_identical_exit_stderr_stdout_and_index_vs_pinned_baseline`, `test_fr_only_tree_with_superseded_fr_differs_from_baseline_only_by_the_default_view`, `test_template_specs_dir_identical_vs_pinned_baseline` | AC-1's `Gates` column |
| `test_spec_query.py` | FR-0005 | `test_index_fr_tr_dec_tables_contain_only_default_view_objects`, `test_unversioned_tree_identical_to_pinned_baseline_in_exit_stderr_and_index`, `test_template_specs_dir_identical_vs_pinned_baseline` | AC-1's `Gates` column |
| `test_metrics_log.py` | FR-0002 | `test_every_kind_default_record_validates_and_carries_the_full_envelope`, `test_kinds_and_sources_and_roles_are_exactly_the_spec_enums`, `test_each_kind_specific_required_field_is_enforced[gate.decision]`, `test_shipped_fixture_validates_line_by_line_and_models_one_synthetic_lifecycle` | AC-11's `gate.decision` kind and `gat` role |
| `test_deploy_gate_metrics.py` | FR-0002 | `test_failure_classes_are_the_fixed_enum_and_the_gate_only_uses_those` | AC-9's two new failure classes |
| `test_headless_conduct.py` | FR-0012 | `test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8[orchestrator]` | AC-12's `orchestrator.md` paragraph |

Three facts decide the shape.

**First, none of the five earlier FRs loses a guarantee.** FR-0003 AC-6 promises
that the index minus the columns it added is the pre-FR-0003 rendering; its own
test is already written as "minus new columns", and the `Gates` column is one
more column to subtract, not a different promise. FR-0004 AC-7 and FR-0005 AC-11
promise that a tree with no TR / DEC / retired objects renders as it did before
those FRs; the comparison, not the promise, is what the new column breaks, and
subtracting the column restores exactly the assertion those ACs describe.
FR-0002 AC-1 enumerates the kinds "in AC-3 to AC-7" and AC-4 calls the failure
classes "a fixed enum"; FR-0002 AC-14 then requires the schema document to name,
for every field and kind, "the AC that introduced it" — FR-0002 designs for
later ACs introducing members, and FR-0008 AC-9 / AC-11 are two such ACs,
documented in `template/specs/_metrics/README.md` (FR-0008-owned, FR-0002
AC-14's home). Nothing is removed or renamed; the enums stay closed and
validator-enforced. FR-0012 AC-10 says that *apart from FR-0012's own block and
AC-8's restatement* the five sources are unchanged — a statement about what
FR-0012 changed, not a prohibition on later FRs, and FR-0008 AC-12 is a later
FR editing `orchestrator.md` under its own `owns:`. The residual test's private
assumption is that HEAD equals FR-0012's own tip; FR-0008 falsifies the
assumption, not the AC. That is DEC-0010's distinction precisely.

**Second, authority and footprint are different things** (DEC-0008). FR-0009
AC-4 and FR-0010 AC-5 derive a dispatched Reviewer's `Edit` / `Write` grants
from the FR's `owns:`. An FR-0008 Reviewer told "re-point these fifteen tests"
cannot write a single one of the six files unless FR-0008 lists it. DEC-0003,
DEC-0006, DEC-0008 and DEC-0010 each closed the same gap for FR-0010, FR-0011
and FR-0013 by adding the file for the Reviewer only, bounded to the exact
edit. This DEC does the same, six times, plus the one fixture file the
shipped-fixture test reads.

**Third, the asymmetry with FR-0010 / FR-0011 is real and is the reason the
literal pins stay literal.** FR-0010 and FR-0011 were *forbidden* new metrics
kinds and fields, and `test_kinds_and_sources_and_roles_are_exactly_the_spec_enums`
is what enforced that. FR-0008 AC-11 *mandates* one. Replacing the literal set
with "every emitted kind is a known kind" would delete the guarantee that made
the prohibition enforceable: after such a change any FR could add a kind and no
test would notice. The friction is the feature — an authorised addition costs
one line in a literal set, in a diff a human reads, under a DEC that says why.
The literals are extended; they are not loosened.

While ruling on the above the Architect examined the three decisions the
Developer flagged. Two are confirmed; one is a defect.

`gate_status` (`dispatch.py:1528`, `:1552`), `cmd_gate_verdict` (`:1606` and the
worktree checks that follow), `_finalize_gat`'s fast-forward target (`:4902`)
and `cmd_wave`'s Phase 3.5 evidence read (`:8140`, `:8152`) are all pinned to
the literal `claude/dev-<FR>`. For an FR implemented in maintainer mode there is
no such branch, so: `gate pass` refuses with `ERROR: no claude/dev-<FR> branch
locally` and a human *cannot* satisfy a declared gate; `gate_status` returns
`missing` forever, so AC-4 excludes the FR from `runnable_review_frs`
permanently; and AC-9 fails the FR at `in-review`. The FR is therefore
un-reviewable and un-mergeable the moment it declares a gate. This is the same
defect DEC-0009 fixed on the rev leg — "the rev leg resolves the implementation
role (`dev`, else `mnt`) so a maintainer-mode FR is reviewable through `finalize
--role rev`" — and the Developer has *already* applied that convention to one
call site in this FR (`_base_branch_for_role`'s `gat` branch resolves through
`_implementation_branch_for_fr`), leaving the implementation internally
inconsistent. It is not a theoretical shape: every wave-1 FR in this project,
and Project A FR-0001, is `mnt`. Once the gate leg reaches maintainer-mode FRs,
AC-8's draft refusal must reach `_finalize_oneshot` too, or a maintainer-mode
PR un-drafts past an unsatisfied gate — exactly the failure the FR exists to
prevent.

## Decision

FR-0008 is revised in place (`version: 2`, `breaking: true`,
`last_breaking_revision: 2`):

### 1. `owns:` gains seven paths, Reviewer-only, bounded per file

Each file stays owned by its original FR; FR-0008's ownership is additive,
Reviewer-only, and limited to the edits enumerated in item 2. Each entry carries
a bounding comment in the `owns:` block naming this DEC.

- `template/tests/unit/scripts/test_index_specs_versioning.py` (FR-0003's)
- `template/tests/unit/scripts/test_index_specs_dec_tr.py` (FR-0004's)
- `template/tests/unit/scripts/test_spec_query.py` (FR-0005's)
- `template/tests/unit/scripts/test_metrics_log.py` (FR-0002's)
- `template/tests/unit/scripts/test_deploy_gate_metrics.py` (FR-0002's)
- `template/tests/unit/scripts/test_headless_conduct.py` (FR-0012's)
- `template/tests/fixtures/metrics/2026-08.ndjson` (FR-0002's, AC-14)

Explicit paths, not globs: FR-0009 derives grants from `owns:` globs, and a glob
over the indexer or metrics test files would hand this Reviewer FR-0009's,
FR-0010's, FR-0011's and FR-0013's test files too (DEC-0004's and DEC-0008's
reasoning). The two entries FR-0008 already carries for its *own* new tests
(`template/tests/unit/scripts/test_{dispatch,index,deploy_gate}_gates.py`,
`template/tests/fixtures/gates/**`) are unchanged.

### 2. The exact permitted changes, per file and per test id

The FR-0008 Reviewer is authorised to make **only** the changes below. Every
other test, fixture, helper, constant, docstring and annotation in these seven
files is untouched. Every file is LF in the index and the edit must preserve LF
(on Windows write with `newline="\n"`; a default `write_text` turns a two-hunk
edit into a whole-file diff — DEC-0010 item 2).

**(a) `test_index_specs_versioning.py`** — FR-0003 AC-2 / AC-6.

- `NEW_HEADER` and `NEW_SEPARATOR` (module constants, lines 88-89) gain the
  trailing ` Gates |` / `-------|` cell. `OLD_HEADER` (line 87) is **not**
  touched — it is the pre-FR-0003 pin and the whole point of the comparison.
  This closes `test_index_columns_inserted_after_status_with_defaults`; its
  `startswith` row assertion is unchanged.
- In `test_unversioned_index_minus_new_columns_is_unchanged`, the local
  `strip_new_cells` helper additionally removes the FR table's trailing `Gates`
  cell (the last populated cell; `cells[-1]` is the empty string after the
  closing pipe), and its comment and the test docstring say "the new cells"
  rather than "the two new cells". `old_expected`, `old_row` and every other
  line of the test are unchanged.

**(b) `test_index_specs_dec_tr.py`** — FR-0004 AC-6 / AC-7.

- `FR_HEADER` (module constant, line 148) gains the trailing ` Gates |` cell.
  This closes `test_tables_sit_after_fr_warning_sections_and_before_adr_table`;
  nothing else in that test changes.
- One new module-level helper is added, next to `_lf`, that returns an
  `INDEX.md`'s bytes (or lines) with the FR table's trailing `Gates` cell
  removed from its header line, its separator line and each of its data rows,
  and **nothing else altered** — the TR, DEC, ADR, Provisional and Retired
  tables, which have no such column, must come back byte-identical. The helper
  asserts it removed exactly one cell per FR-table line so a future column
  cannot slip through it silently. Its docstring records that it exists because
  FR-0008 AC-1 added a column after this baseline was pinned, and cites DEC-0012.
- The helper is applied to the **new** side of exactly three comparisons:
  `test_fr_only_tree_gives_identical_exit_stderr_stdout_and_index_vs_pinned_baseline`,
  `test_template_specs_dir_identical_vs_pinned_baseline`, and
  `test_fr_only_tree_with_superseded_fr_differs_from_baseline_only_by_the_default_view`
  (before the `removed` / `added` / `prefix` comparison, so it again finds
  exactly one removed row and exactly the four `## Retired objects` lines added).
  The exit-code, stdout and stderr equality assertions in all three are
  unchanged, as is `_BASELINE_REF`.
- `test_fr_only_tree_validate_mode_identical_vs_pinned_baseline` and
  `test_fr_only_error_tree_identical_vs_pinned_baseline` are green at `681d661`
  and are **not** edited.

**(c) `test_spec_query.py`** — FR-0005 AC-9 / AC-11. The same two edits as (b),
scoped to this file's own constants and tests: `FR_HEADER` gains the trailing
cell (closing `test_index_fr_tr_dec_tables_contain_only_default_view_objects`,
whose other assertions are unchanged), and a local copy of the same normalising
helper is applied to the new side of
`test_unversioned_tree_identical_to_pinned_baseline_in_exit_stderr_and_index`
and `test_template_specs_dir_identical_vs_pinned_baseline`. The helper is
duplicated rather than shared: these files ride independently into every
bootstrapped project and have no shared support module.

**(d) `test_metrics_log.py`** — FR-0002 AC-1 / AC-14.

- `_KIND_DEFAULTS` gains one entry, `"gate.decision"`, carrying every field
  AC-11 requires — `source: "dispatch"`, `role: "gat"`, `gate`, `after: "dev"`,
  `reviewer: "architect"`, `verdict: "pass"`, `by: "architect"`, `round: 1`,
  `head_sha` (a 40-character placeholder of the file's existing
  `"a" * 39 + "1"` shape). This alone closes both
  `test_every_kind_default_record_validates_and_carries_the_full_envelope` and
  `test_each_kind_specific_required_field_is_enforced[gate.decision]`; neither
  test body is edited.
- In `test_kinds_and_sources_and_roles_are_exactly_the_spec_enums`, the `KINDS`
  literal gains `"gate.decision"` and the `ROLES` literal gains `"gat"`.
  `SOURCES` is unchanged. The sets stay literal and exhaustive; a one-line
  comment at the edit site cites DEC-0012 and FR-0008 AC-11 as the authorisation
  for the two members. Converting either assertion to a subset or a "known kind"
  check is **not** authorised.
- In `test_shipped_fixture_validates_line_by_line_and_models_one_synthetic_lifecycle`,
  `23` becomes `24` in both places (`len(recs)` and the `"24/24 records valid"`
  CLI string). No other assertion in that test changes — in particular
  `set(kinds) == metrics_log.KINDS` stays as written, which is what makes the
  fixture edit in (e) mandatory rather than optional.
- No other test in the file is edited. `test_shipped_fixture_carries_no_real_looking_identifiers`
  must still pass unchanged against the edited fixture, and so must every
  `_fixture_dir`-driven AC-10 / AC-11 / AC-12 assertion (the Architect checked
  that all of them filter on an exact `kind`, and that `summarize_by_fr` and
  both shipped reports do too, so a `gate.decision` line is inert in every one;
  if any proves otherwise, the fix is to adjust the added record's own fields,
  never those tests).

**(e) `template/tests/fixtures/metrics/2026-08.ndjson`** — FR-0002 AC-14.
Exactly one line is added: a `gate.decision` record for the same synthetic
lifecycle, placed in `ts` order between the `pr.opened` record at
`2026-08-03T10:17:00Z` and the rev `dispatch.spawn` at `2026-08-03T10:20:00Z`
(the gate sits where FR-0008 AC-4 puts it — after the Developer's PR, before the
Reviewer spawn), with `project: "synthetic-project"`, `object_ids: ["FR-0020"]`,
`source: "dispatch"`, `role: "gat"`, `verdict: "pass"`, `by: "architect"`, a
`record_id` of the file's `f` + 31-hex shape that collides with no existing one,
and a `head_sha` equal to the `pr.opened` record's. **No existing line is
renumbered, reordered or otherwise edited.** The file stays LF with a trailing
newline and must still satisfy AC-14's no-real-identifiers test (no `@`, no
non-placeholder SHA, only `example-org/synthetic-project` URLs).

**(f) `test_deploy_gate_metrics.py`** — FR-0002 AC-4. In
`test_failure_classes_are_the_fixed_enum_and_the_gate_only_uses_those`, and
nowhere else in the file:

- The `GATE_FAILURE_CLASSES` literal gains `"gate-evidence-missing"` and
  `"gate-evidence-stale"` (eight members). `GATE_WARNING_CLASSES` and
  `GATE_INVOKED_BY` are unchanged.
- The reachability assertion is repaired. `deploy-gate.py` emits the two new
  classes through a computed local (`report.fail(cls, msg)`, with `cls` chosen
  by a ternary a few lines above it), which the test's
  `report\.fail\("([a-z-]+)"` source scrape cannot see. The final assertion
  becomes `used_fail | <the two FR-0008 classes> == metrics_log.GATE_FAILURE_CLASSES`,
  with the two names bound to a constant at the edit site and a comment of at
  most two lines recording why they are scraped differently and that their
  reachable branches are pinned by FR-0008 AC-9's own tests in
  `template/tests/unit/scripts/test_deploy_gate_gates.py`. The
  `used_fail <= metrics_log.GATE_FAILURE_CLASSES` and
  `used_warn == GATE_WARNING_CLASSES` assertions are unchanged and must still
  hold. Deleting the reachability assertion, or relaxing it to a subset check,
  is **not** authorised.

**(g) `test_headless_conduct.py`** — FR-0012 AC-10. In
`test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8`, in the
`else:  # orchestrator` branch only:

- The residual is still exactly one `insert` opcode; `len(rest) == 1 and
  rest[0][0] == "insert"` is unchanged. The inserted run is now nine lines, not
  two, because FR-0008 AC-12 appends its paragraph at the same position.
- `inserted[0]` and `inserted[1]` keep their present assertions verbatim (the
  AC-8 restatement starting `"The Reviewer's verdict is its final assistant
  message"`, containing `"GitHub approval state"`, followed by a blank line).
- `inserted[2:]` is asserted to be FR-0008 AC-12's documented block and nothing
  else: seven lines, the first starting `"**Two more per-FR wave outcomes"`, the
  run containing both `"GATE-PENDING"` and `"GATE-BLOCKED"`, and the last line
  empty. A one-line comment cites DEC-0012 and FR-0008 AC-12.
- `_PRE_FR_REF` (`bd46dd3`) is **not** re-pointed, the test is **not** retired,
  skipped or `xfail`ed, and the `developer`, `reviewer`, `maintainer` and
  `reviewer-backfill` parametrisations are untouched. Nothing else in the file
  changes — in particular `_SURVIVING_LINES`,
  `test_named_existing_instructions_survive_verbatim`,
  `test_any_other_changed_line_is_reported` and the AC-9 wrapper-equality tests,
  all green at `681d661`.

Retiring (g) was considered and rejected. It is the only exhaustive check in
the file: `test_named_existing_instructions_survive_verbatim` pins seven named
`orchestrator.md` lines and `test_any_other_changed_line_is_reported` exercises
the residual machinery through `maintainer.md`, so retiring (g) would leave
every *unnamed* line of `orchestrator.md` — the wave-first default's
surrounding prose, the Phase 3 and Phase 4 text, the hard limits' framing —
with no guard at all. Re-pointing costs three assertions and keeps FR-0012
AC-10's guarantee exact. DEC-0007 is the precedent: narrow the guard, do not
delete it.

### 3. The gate leg resolves the implementation role, `dev` else `mnt`

Every point on FR-0008's gate leg that names the Developer branch resolves it
through `_implementation_branch_for_fr` (`claude/dev-<FR>` if it exists, else
`claude/mnt-<FR>`) — DEC-0009 / FR-0013 AC-11's convention, now ratified on
`main`. The AC text changes accordingly:

- **AC-2** — `gate_status`'s default `ref` is the FR's implementation branch,
  and `stale` compares `head_sha` against that same branch's current tip. The
  `ref=None` working-tree reading and the other three outcomes are unchanged.
- **AC-3** — `gate pass|block` refuses when *no* implementation branch exists
  (naming both candidates), writes into and commits on that branch, takes
  `head_sha` from its tip and `round` from that role's run context, and checks
  the corresponding worktree. The commit subject, the `--apply` semantics, the
  `WOULD-GATE` line and "never touches `main`" are unchanged.
- **AC-6** — the `gat` worktree is cut at the implementation branch's current
  tip (the Developer's `claude/gat-<FR>` shape, confirmed below), and
  `finalize --role gat --apply` fast-forwards and pushes that same
  implementation branch.
- **AC-13** — a gate-free FR is still byte-for-byte unchanged; resolution only
  ever runs for an FR that declares a gate.

An FR implemented by a normal Developer behaves exactly as v1 described: the
`dev` branch exists, so it is the one resolved. Nothing is removed.

### 4. AC-8's draft refusal covers `_finalize_oneshot`

AC-8's "any other path that un-drafts a PR" is made explicit: the guard is
factored out of `_finalize_dev` and applied in `_finalize_oneshot` as well, so
`finalize --role mnt --ready` and `finalize --role bkf --ready` refuse with the
same single `ERROR` line while an `after: dev` gate is unsatisfied. Without item
3 this combination was unreachable; with it, it is the common case in this
project. The `## Gates` PR-body section keeps its existing behaviour on both
paths.

### 5. The Developer's other two decisions are confirmed

`gat`'s `claude/gat-<FR>` worktree branch (git refuses two worktrees on one
branch, so a new branch at the same commit plus a guarded `git update-ref`
fast-forward is the only way to satisfy AC-6's "checked out at the current tip"
literally) and the evidence file's own frontmatter as the source of truth for
`round` and `head_sha` are both confirmed as satisfying AC-6, and are recorded
in FR-0008's Notes so the Reviewer tests the reading the spec owner confirmed.
The Developer's reading of AC-11's `gat` addition to `ROLES` (needed so
`dispatch.run` / `dispatch.spawn` / `pr.*` records for `gat` sessions validate)
is likewise confirmed.

### 6. No other FR is revised

FR-0002, FR-0003, FR-0004, FR-0005 and FR-0012 take no version step, no `owns:`
change and no Changelog line. Under ADR-0001 rule 2 there is nothing to revise
on any of them: no AC sentence changes meaning, and the six tests assert the
same guarantees after the edits as before. The trace from their side is this
DEC's `constrained_by` and the `DEC-0012` comments at each edit site.

`breaking: true` under ADR-0001 rule 4: `681d661` does **not** satisfy FR-0008
v2 — items 3 and 4 require a Developer round 2 in maintainer mode. `tier:
architect`: FR-0008 is `ready`, dispatched but unmerged, and the Architect owns
it; the footprint widening adds no policy (every added file is bounded to one
authorised cascade, DEC-0008's shape) and no human-approved guarantee narrows
(the factor that made DEC-0002, DEC-0005 and DEC-0007 `neil`). Items 3 and 4
adopt a convention a ratified DEC on a merged FR already established. Recorded
`proposed`; live for the design (indexer `LIVE_DEC_STATUSES`); ratified when
FR-0008's PR merges. **Not** covered by this DEC and not added to FR-0008's
`owns:`: `scripts/bootstrap.py`, which is a hub script under the hub
`CLAUDE.md`'s human-approval rule — see FR-0008's Notes, "`COMMAND_META` has no
`gate-review` entry", and the escalation the Architect raised alongside this DEC.
ADR-0001 rule 5 was checked and does not apply: FR-0008's identity — declared
gates, enforced at the phase boundary they name, with evidence the deploy gate
lints — is unchanged.

## Alternatives considered

- **Leave the six files out of `owns:`; let their own FRs' Reviewers repair them
  in backfill runs.** Rejected for DEC-0008's and DEC-0010's reason: every one of
  the fifteen edits exists only because of FR-0008's behaviour change and all
  fifteen must land in FR-0008's PR for its suite to be green. A backfill on five
  merged FRs that cannot pass until an unmerged FR lands is the wrong order, and
  it costs five one-shot runs where one bounded Reviewer round does the work.
- **Turn the closed-enum pins into "every emitted kind is known".** Rejected —
  see Context, third fact. That test shape is right for *detecting* an unknown
  kind at runtime and wrong for *governing* which kinds exist. FR-0010 and
  FR-0011 were held to "no new kinds" by exactly these literals; loosening them
  now, in the FR that is permitted one, removes the control from every FR after
  it. A complementary reachability test ("every kind the dispatcher emits is in
  `KINDS`") is worth having and is recorded as a finding for a later metrics FR,
  not as a replacement here.
- **Retire the `orchestrator` residual test.** Rejected — see item 2(g).
- **Re-point the three byte-identical baselines at `706ba9d`.** Rejected: at
  `706ba9d` the indexer already contains FR-0003's, FR-0004's and FR-0005's own
  features, so "identical to baseline" would become a tautology and the
  "differs only by the default view" check would find zero differences — the
  failure mode the files' own header comment warns about ("backward-compat
  baselines pin a commit, never a branch name ... once merged, `main:` IS the
  code under test"). Normalising the one new column away keeps the pinned commit
  and keeps the assertion meaningful.
- **A glob over the indexer / metrics test files.** Rejected for DEC-0008's
  reason: FR-0009 derives grants from `owns:` globs, so a glob would grant this
  Reviewer test files belonging to FR-0009, FR-0010, FR-0011 and FR-0013 that it
  may not touch. Seven explicit paths are what a human reviewing the footprint
  should see.
- **Accept the `claude/dev-<FR>` pinning and file the maintainer-mode gap as a
  follow-up FR.** Rejected: it ships a feature that is inoperative on the FR
  class this project actually uses, and AC-9 would then fail every gated
  maintainer-mode FR at `in-review` with no way to clear it. DEC-0009 already
  set the convention and the Developer already applied it to one of the call
  sites; finishing the job is a bounded round-2 edit, not an FR.
- **Two DECs in one version step (footprint, branch resolution).** Rejected
  under ADR-0001 rule 3's arithmetic (`version == len(revisions) + 1`): two DECs
  on one FR are two version steps, as DEC-0008 / DEC-0009 / DEC-0010 each took
  on FR-0013 and as DEC-0009's own Alternatives record. Both halves here arise
  from the same escalation, land in the same round and are ratified together, so
  one DEC and one version step is the honest record. (`scripts/bootstrap.py` is
  genuinely a separate tier and is therefore genuinely not in this DEC — it is
  escalated, not folded in.)

## Cascade

Breaking; every affected artifact:

- `projects/hub-tooling/specs/FR-0008-declared-gates-honoured-by-dispatcher.md`
  — `owns:` gains the seven bounded paths with per-file bounding comments; AC-2,
  AC-3, AC-6 amended for implementation-role resolution; AC-8 amended to name
  `_finalize_oneshot`; AC-13 amended to enumerate the fifteen permitted test
  edits as the exception to "every test that passed before this FR still
  passes"; Notes record the confirmed Developer decisions, the `COMMAND_META`
  gap and the findings; `version: 2`, `revisions: [DEC-0012]`,
  `last_breaking_revision: 2`, `updated: 2026-09-22`; Changelog line. Done in
  this commit.
- `template/scripts/dispatch.py` (FR-0008-owned; **Developer round 2, maintainer
  mode**) — items 3 and 4. Every literal `claude/dev-{fr_id}` on the gate leg
  (`gate_status`'s default ref and its `stale` comparison, `cmd_gate_verdict`'s
  branch / worktree checks and commit target, `_finalize_gat`'s fast-forward
  target, `cmd_wave`'s Phase 3.5 evidence read and its `GATE-STALE` SHA lookup,
  and the `_pending_after_dev_gates` / `gate_pending_review_frs` /
  `explain_not_runnable` paths that reach them) resolves through
  `_implementation_branch_for_fr`; the `ERROR` line names both candidate
  branches; AC-8's guard is factored out of `_finalize_dev` and called from
  `_finalize_oneshot`. No behaviour changes for an FR with a `dev` branch and no
  behaviour at all for an FR with no gates.
- `template/tests/unit/scripts/test_index_specs_versioning.py` (FR-0003's),
  `test_index_specs_dec_tr.py` (FR-0004's), `test_spec_query.py` (FR-0005's),
  `test_metrics_log.py` and `test_deploy_gate_metrics.py` (FR-0002's),
  `test_headless_conduct.py` (FR-0012's), and
  `template/tests/fixtures/metrics/2026-08.ndjson` (FR-0002's) — **FR-0008
  Reviewer**, bounded exactly as in Decision item 2.
- `template/tests/unit/scripts/test_dispatch_gates.py`, `test_index_gates.py`,
  `test_deploy_gate_gates.py`, `template/tests/fixtures/gates/**`
  (FR-0008-owned, not yet written) — the FR-0008 Reviewer's own tests. Items 3
  and 4 are ACs and need coverage: a gate on a maintainer-mode FR
  (`claude/mnt-<FR>`, no `dev` branch) is readable, passable, blocks the
  Reviewer until passed, and `finalize --role mnt --ready` refuses while it is
  unsatisfied.
- `projects/hub-tooling/specs/FR-0002-*.md`, `FR-0003-*.md`, `FR-0004-*.md`,
  `FR-0005-*.md`, `FR-0012-*.md` — **no change** (Decision item 6).
- `scripts/bootstrap.py` — **no change**; the `COMMAND_META["gate-review"]`
  entry is escalated to the human, not decided here.
- No object `depends_on` or `extends` FR-0008; DEC-0004's Cascade mentions it in
  prose only (index check, 2026-09-22).

## Changelog

- 2026-09-22: created (proposed) — from the FR-0008 maintainer-mode Developer's `## ESCALATION` and `## Decisions` at `681d661` and the Orchestrator's escalation brief; the fifteen failures reproduced by the Architect at `681d661` (1374 passed, 15 failed vs. 1387 passed, 0 failed at `706ba9d`)
