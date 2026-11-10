---
id: DEC-0013
title: FR-0008's `owns:` gains the hub script `scripts/bootstrap.py`, bounded to one new `COMMAND_META["gate-review"]` key and nothing else, so the two generated `gate-review` wrappers carry a real description and argument hint — Neil-approved, and the precedent for a template FR reaching into a hub script (AC-12)
tier: neil
status: ratified  # proposed | ratified | rejected | superseded — ratified when FR-0008's PR merges
satisfies: []
constrained_by: [FR-0001, FR-0012]
revises: FR-0008
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Ship the generic fallback wrapper and file the COMMAND_META entry as a follow-up FR (the other half of the Architect's 2026-09-22 escalation)"
  - "Fold the entry into FR-0001, the FR whose Notes already claim scripts/bootstrap.py as its intended owns:"
  - "Widen owns: to scripts/bootstrap.py unbounded, on the grounds that FR-0008 is dispatched in maintainer mode anyway"
  - "Give gat a model: / effort: in the same entry rather than letting it fall to the harness default like architect"
  - "Hand-edit the two gate-review wrappers instead of touching the generator's metadata"
  - "Add per-command frontmatter to .agent-team/commands/*.md so COMMAND_META never has to grow again"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0008 AC-12 adds a tenth-plus canonical command,
  `template/.agent-team/commands/gate-review.md`, and owns both of its
  generated wrappers. `scripts/bootstrap.py::COMMAND_META` has no entry for
  it, so `generate_commands` falls back to `description: "Run the gate-review
  command."` with no `argument-hint` — a wrapper whose frontmatter tells the
  harness nothing about a two-token invocation (`FR-XXXX gate-id`) and which
  every `--upgrade` regenerates identically into every project. AC-12 is
  satisfied as written either way (the wrapper body is the canonical source
  verbatim; the frontmatter is all that differs), so this is a cosmetic gap,
  not an AC gap — but the fix costs one dict key and the gap is permanent
  until someone pays it. What made it an escalation rather than a DEC-0012
  item is authority, not size: `scripts/bootstrap.py` is a hub script on the
  hub `CLAUDE.md`'s explicit-human-approval list, no FR owns it, and FR-0008
  carries it under `reads:` precisely because DEC-0012 declined to reach it.
  Neil approved option (a) of that escalation on 2026-09-22. This DEC records
  the approval, moves the path from `reads:` to `owns:` bounded to the single
  named symbol, and fixes the precedent: a template FR may reach into a hub
  script only under a `neil`-tier DEC that names the symbols it may touch.
created: 2026-09-22
updated: 2026-09-22
---

# DEC-0013: FR-0008's `owns:` gains `scripts/bootstrap.py`, bounded to one `COMMAND_META["gate-review"]` key

## Context

FR-0008 AC-12 requires `template/.agent-team/commands/gate-review.md` to exist
with the AC-6 instructions and the standard role preamble, and requires the two
generated wrappers under `template/.claude/commands/` and
`template/.cursor/commands/` to differ from that source "only by the
generated-file banner and frontmatter". At `681d661` the maintainer-mode
Developer delivered exactly that, and the Architect confirmed AC-12 satisfied.

The frontmatter, however, is the generator's fallback. `generate_commands`
(`scripts/bootstrap.py:447`) does `meta = COMMAND_META.get(name, {})` and then
`desc = meta.get("description", f"Run the {name} command.")`, `hint =
meta.get("argument-hint", "")`. `COMMAND_META` (`:144`ff) has entries for
`architect`, `developer`, `reviewer`, `reviewer-backfill`, `escalate`, `gate`,
`status`, `maintainer`, `orchestrator` and `docs` — and none for `gate-review`.
So both committed wrappers carry:

```
---
description: "Run the gate-review command."
---
```

with no `argument-hint`, although the command takes two positional tokens
(`FR-0006 design-review`). The same generic line is what every `bootstrap.py
--upgrade` will write into every project from the day FR-0008 merges, and the
`gate` entry three keys above it — `"Run the agent gate locally. Use before
declaring any work complete."` with `argument-hint: "--stage full (or dev)"` —
is a near-neighbour a human scanning the command palette will read beside it.

Closing the gap is one dict key. What it is *not* is one dict key's worth of
authority. `scripts/bootstrap.py` is on the hub `CLAUDE.md`'s list of files
"you should never edit without explicit human approval", alongside the other
three hub scripts and the template's control plane. No FR in this project owns
it; nine FRs (FR-0002, FR-0006, FR-0008, FR-0009, FR-0010, FR-0011, FR-0012,
FR-0013, FR-0014) carry it under `reads:`, and FR-0012 went out of its way to
put "Changing `generate_commands` in `scripts/bootstrap.py`" in Out of scope
and to route the generator's CRLF defect to IDEA-0063 rather than fix it in
place. FR-0001 (`profile-aware --upgrade`, not yet dispatched) documents
`scripts/bootstrap.py` under Notes as its intended `owns:` and states that "the
Developer must obtain explicit approval before the first edit to
`scripts/bootstrap.py` lands". That is the standing convention, and DEC-0012
therefore declined to widen `owns:` to reach it — it said so explicitly, and
the Architect escalated the question to Neil as a standalone decision with two
options: a `neil`-tier DEC bounded to the single entry, or a follow-up FR.

**Neil approved the bounded DEC (option (a)) on 2026-09-22.** This DEC records
that approval.

One mechanical fact shapes the Decision below. `template/tests/unit/scripts/
test_headless_conduct.py` — FR-0012's, and already in FR-0008's `owns:` under
DEC-0012 item 2(g) for an unrelated bounded edit — imports the *live*
`generate_commands` from the hub's `scripts/bootstrap.py` and asserts in
`test_committed_wrappers_equal_generate_commands_output_after_lf_normalisation`
and `test_every_canonical_command_has_both_wrappers_in_generated_form` that
every committed wrapper equals the generator's output over the canonical
sources, byte for byte, with no `\r`. Both tests are green at `681d661` and
must stay green. They bind the two halves of this change together: the
`COMMAND_META` key without the regenerated wrappers goes red, and the
regenerated wrappers without the key are unreachable. They also make the
LF requirement enforced rather than advisory — `generate_commands` writes with
`Path.write_text` and emits CRLF on Windows (FR-0012's round-1 finding,
IDEA-0063), so the regenerated bytes must be normalised before they are
committed, exactly as FR-0012's two wrapper rounds did.

## Decision

FR-0008 is revised in place (`version: 3`, `breaking: true`,
`last_breaking_revision: 3`).

### 1. `owns:` gains `scripts/bootstrap.py`, bounded to one named symbol

`scripts/bootstrap.py` moves from FR-0008's `reads:` to its `owns:`, carrying a
bounding comment in the DEC-0012 style that names this DEC and the symbol. It
is the only hub-level (non-`template/`) path in the footprint, and the first
time any FR in this project has owned a hub script.

The grant is to the FR-0008 **Developer, round 2**, and is exhausted by item 2.
The file is not FR-0008's: it remains a hub script under the hub `CLAUDE.md`'s
human-approval rule, and FR-0001's future claim on it is unaffected.

### 2. The exact permitted change to `scripts/bootstrap.py`

Exactly one new key is added to the `COMMAND_META` dict:

```python
"gate-review": {
    "description": "Operate as the Architect in gate-review mode for one declared gate. One-shot; writes only the evidence file.",
    "argument-hint": "FR-XXXX gate-id",
},
```

- The two field values are **verbatim** as above — they are what Neil approved,
  not a starting point to improve on.
- The entry carries **no `model`, no `effort`, no `allowed-tools`**, matching
  the `architect` entry, which carries none either. This is the mechanical
  consequence of the Architect's round-1 ruling recorded in FR-0008's Notes:
  the Open question's default for `gat`'s model is "same as `architect` in the
  model table", and read literally against the actual model table that means
  the harness default. If a `model:` for `gat` is ever wanted it belongs in
  this same entry, under its own DEC.
- Placement: appended after the `"docs"` entry, at the end of the dict, with a
  comment of at most two lines citing FR-0008 AC-12 and DEC-0013. Appending
  keeps the diff a pure insertion — no existing line moves, and a human reading
  the PR sees added lines only.
- **Nothing else in `scripts/bootstrap.py` may change.** Not
  `generate_commands` (FR-0012 Out of scope; the CRLF defect stays IDEA-0063's),
  not `INFRA_DIRS` or `INFRA_ROOT_FILES`, not `PROJECTS_YAML_HEADER`, not any
  other `COMMAND_META` entry — including no reordering, reflowing or
  reformatting of the existing ten — and no import, docstring, comment or
  blank line outside the inserted block. The diff on this file is the inserted
  entry and its comment, and nothing else. `ruff format` is not run over the
  file.

### 3. The only other permitted output is the two regenerated wrappers

After the edit the Developer re-runs `generate_commands` over `template/` and
commits the resulting `template/.claude/commands/gate-review.md` and
`template/.cursor/commands/gate-review.md` — both already in FR-0008's `owns:`
under AC-12, so no further widening is needed.

- Each wrapper's diff is one changed `description:` line and one added
  `argument-hint:` line. The banner, the body, the `$ARGUMENTS` → `{{args}}`
  substitution in the Cursor variant, and the trailing newline are all
  unchanged.
- The regeneration touches every command's wrappers; **the other eighteen
  wrapper files must come back byte-identical and are not committed.** If any
  does not, that is a `## FINDINGS` line, not an edit.
- Both files are LF with a trailing newline in the index. On Windows the
  generator emits CRLF, so normalise before staging (FR-0012's precedent) and
  verify with `git diff --stat` that exactly two files under
  `template/*/commands/` changed.
- Verification is FR-0012 AC-9's own tests, unchanged:
  `test_committed_wrappers_equal_generate_commands_output_after_lf_normalisation`,
  `test_every_canonical_command_has_both_wrappers_in_generated_form`,
  `test_cursor_wrapper_differs_from_claude_only_by_claude_only_keys_and_args[gate-review]`
  and `test_generator_is_deterministic_over_the_template_sources` must all be
  green after the change. None of them is edited: they are FR-0012's, and
  FR-0008's grant on `test_headless_conduct.py` is bounded by DEC-0012 item
  2(g) to the `orchestrator` residual branch only.

### 4. No AC text changes; AC-12's record is corrected

AC-12's sentence stands as written — the wrappers are the renderer's genuine
output over the canonical source and differ from it only by the banner and
frontmatter, before and after this change. What changes is the frontmatter the
renderer produces, which AC-12 never constrained. No AC is reworded, added or
removed by this DEC.

FR-0008's Notes entry "`scripts/bootstrap.py::COMMAND_META` has no
`gate-review` entry" is rewritten to record the resolution — the gap is closed
by this DEC, Neil approved on 2026-09-22, and the work is Developer round 2 —
rather than leaving a pointer to an open escalation. The `gat` needs no
`ROLE_MODEL` Note is updated to point at this DEC as the entry's home.

### 5. Why `neil` and not `architect`, and the precedent this sets

DEC-0012 was `architect`: every path it added is a `template/` file this
project's FRs already govern, and no human-approved guarantee narrowed. This
DEC is `neil` for one reason only — the file. The hub `CLAUDE.md` names
`scripts/bootstrap.py` under "Files you should never edit without explicit
human approval" and instructs "if a task seems to require editing these,
escalate first". An FR's `owns:` is the mechanism that turns a spec into a
write grant (FR-0009 AC-4, FR-0010 AC-5); widening `owns:` to a
human-approval file *is* the edit decision, taken in advance. An Architect may
not self-authorise it however small the diff, and the size of this diff is the
argument for approving it, not for skipping the approval.

The precedent, for every FR after this one: **a `template/` FR may reach into a
hub script (`scripts/bootstrap.py`, `hub-index.py`, `parking.py`,
`patterns.py`) only under a `neil`-tier DEC that names the symbols it may
touch.** Not "the file", not "the function" — the named keys, constants or
functions, with an explicit statement of what may not change, as item 2 does.
An FR that needs more than a named-symbol bound needs its own FR, with Neil
approving the scope up front, which is what FR-0001 is. This DEC does not open
`scripts/bootstrap.py` to FR-0008 generally, and it does not create a standing
grant for any other FR.

`breaking: true` under ADR-0001 rule 4: `681d661` does not satisfy FR-0008 v3.
Items 2 and 3 are a required Developer round-2 change, landing in the same
round as DEC-0012's items 3 and 4. Recorded `proposed`; live for the design
(indexer `LIVE_DEC_STATUSES`); ratified when FR-0008's PR merges, alongside
DEC-0012 — Neil's approval of 2026-09-22 authorises the work, and the merge
ratifies the record, which is this project's convention for a DEC on an
in-flight FR. ADR-0001 rule 5 was checked and does not apply: FR-0008's
identity — declared gates, enforced at the phase boundary they name, with
evidence the deploy gate lints — is untouched by a command's frontmatter.

### 6. No other object is revised

FR-0001, FR-0012 and the seven other FRs carrying `scripts/bootstrap.py` under
`reads:` take no version step, no `owns:` change and no Changelog line. A
`reads:` entry is documentation, not a grant (the dispatcher derives no
permission from it), and none of them loses anything by FR-0008 owning one key
of the file for one round. The trace from FR-0001's and FR-0012's side is this
DEC's `constrained_by`.

## Alternatives considered

- **Ship the generic fallback and file a follow-up FR.** This was the other
  option in the escalation Neil answered, and it is defensible: AC-12 is
  satisfied as written, the wrapper body an agent reads is the canonical source
  verbatim, and the cost of being wrong is cosmetic. Rejected because Neil
  chose otherwise, and because the follow-up FR would be an FR whose entire
  content is one dict key — the ceremony would exceed the change by an order of
  magnitude, and until it landed every `--upgrade` would propagate the generic
  wrapper into every project, making the debt wider, not older.
- **Fold the entry into FR-0001.** FR-0001 already names `scripts/bootstrap.py`
  as its intended `owns:` and already requires Neil's approval at
  implementation time, so the key could ride along. Rejected: FR-0001 is not
  dispatched and has no date; FR-0008's wrappers would ship generic in the
  meantime and every `--upgrade` between now and then would spread them. It
  also couples a gate-review detail to a profile-persistence FR for no reason
  other than file adjacency. If FR-0001 later reworks `COMMAND_META`, this
  entry is one of eleven it inherits.
- **Widen `owns:` to `scripts/bootstrap.py` unbounded.** Rejected. FR-0008 is
  dispatched in maintainer mode, so its `owns:` is the whole write surface
  (FR-0009 AC-4 / FR-0010 AC-5) and an unbounded entry would hand a
  maintainer-mode round-2 session the entire hub bootstrapper — `INFRA_DIRS`,
  the profile overlay, `generate_commands`, `--upgrade`'s sync — with the
  temptation to "just fix" the CRLF defect on the way past. The bounding
  comment plus item 2's explicit non-permissions is what makes a human
  reviewing the footprint able to see the size of the grant without reading the
  diff. Same reasoning as DEC-0008's and DEC-0012's explicit paths over globs.
- **Give `gat` a `model:` / `effort:` in the same entry.** Rejected, and the
  Architect ruled on it in round 1: FR-0008's Open question sets `gat`'s model
  to "same as `architect` in the model table", and `architect` carries no
  `model` key, so the faithful implementation of that default is no key. Adding
  one would be a decision the FR does not authorise, taken inside a DEC whose
  whole point is being minimal.
- **Hand-edit the two wrappers.** Rejected on FR-0012's rule, which this FR
  inherits: the wrappers are generated, never hand-edited, and
  `test_committed_wrappers_equal_generate_commands_output_after_lf_normalisation`
  enforces it against the live generator. A hand-edited wrapper is red in CI
  and silently reverted by the next `--upgrade` in every project.
- **Per-command frontmatter in `.agent-team/commands/*.md`, so `COMMAND_META`
  never grows.** The honest long-term fix: the metadata would live beside the
  command it describes, every new command would carry its own, and no template
  FR would ever need to reach into a hub script for this again. Rejected here
  because it is a `generate_commands` change — a real feature with a parser, a
  precedence rule against the existing dict, a migration for ten entries and a
  test surface — which FR-0012 explicitly placed out of scope and which the hub
  `CLAUDE.md` would put in front of Neil as its own FR. Worth parking; not
  worth blocking FR-0008's round 2 on.

## Cascade

Breaking; every affected artifact:

- `projects/hub-tooling/specs/FR-0008-declared-gates-honoured-by-dispatcher.md`
  — `scripts/bootstrap.py` moves from `reads:` to `owns:` with a bounding
  comment citing this DEC; the `COMMAND_META` Note is rewritten to record the
  resolution and the `gat`-model Note re-pointed at this DEC; `version: 3`,
  `revisions: [DEC-0012, DEC-0013]`, `last_breaking_revision: 3`,
  `updated: 2026-09-22`; Changelog line. No AC text changes. Done in this
  commit.
- `scripts/bootstrap.py` (hub script; **Developer round 2, maintainer mode**) —
  one added `COMMAND_META["gate-review"]` entry, exactly as Decision item 2
  specifies. Nothing else.
- `template/.claude/commands/gate-review.md`,
  `template/.cursor/commands/gate-review.md` (FR-0008-owned under AC-12;
  **Developer round 2**) — regenerated, LF-normalised; one changed
  `description:` line and one added `argument-hint:` line each.
- `template/tests/unit/scripts/test_headless_conduct.py` (FR-0012's) — **no
  change under this DEC.** Its AC-9 wrapper tests are the verification of items
  2 and 3 and must pass unedited; FR-0008's bounded grant on the file remains
  DEC-0012 item 2(g)'s `orchestrator` residual branch alone.
- `projects/hub-tooling/specs/FR-0001-profile-aware-upgrade.md`,
  `FR-0012-*.md` — **no change** (Decision item 6). FR-0001's Notes claim on
  `scripts/bootstrap.py` is unaffected; when it is dispatched it inherits an
  eleventh `COMMAND_META` entry.
- The other seven FRs carrying `scripts/bootstrap.py` under `reads:` — no
  change.
- Hub `CLAUDE.md` — **no change.** The human-approval rule is honoured by this
  DEC, not amended by it.

## Changelog

- 2026-09-22: created (proposed) — Neil approved option (a) of the Architect's 2026-09-22 escalation (recorded in FR-0008's Notes and DEC-0012's closing paragraph); mints the bounded `neil`-tier authorisation so FR-0008's Developer round 2 can absorb it
- 2026-09-22: update (ratified) - Ratified by Neil Gilchrist on PR review (DEC indicates it ratifies on merge, but I believe the orchestrator will only apply that rule to Architect tier DECs, so I went ahead and made the edits
