---
id: DEC-0002
title: FR-0009's "rev/bkf unchanged" guarantee is narrowed to an FR with no `owns:`, and its pre-FR comparisons to a no-stack project — FR-0010 extends the derivation to those roles
tier: neil
status: ratified  # proposed | ratified | rejected | superseded — Neil ratifies at FR-0010 PR review
satisfies: []
constrained_by: [FR-0010]
revises: FR-0009
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave FR-0009 AC-9 as written and delete or skip the four failing parametrisations as 'superseded by FR-0010'"
  - "Supersede FR-0009 with a new FR that covers dev, rev and bkf together"
  - "Revise FR-0010 AC-5 instead: keep rev/bkf on the static write surface and grant owns: to dev only"
  - "Keep the four tests running against a rich owns: but compare to an owns-aware expectation instead of the pre-FR file"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0009 AC-9 pinned the rev/bkf permission files byte-identical to the
  pre-FR-0009 dispatcher for every owns:, as a regression guard on FR-0009's
  own change. FR-0010 AC-5 deliberately extends the owns: derivation to those
  two roles, so the guard now pins the absence of a feature the spec graph
  has since decided to build. Narrowing the guarantee to the case both FRs
  agree on (empty owns:, no detected stack) keeps FR-0009 honest without
  changing what it built; the rich-owns: rev/bkf behaviour is FR-0010 AC-5's
  to specify and test.
created: 2026-09-21
updated: 2026-09-21
---

# DEC-0002: FR-0009's "rev/bkf unchanged" guarantee is narrowed to an FR with no `owns:`, and its pre-FR comparisons to a no-stack project

## Context

FR-0009 (merged, PR #3) generalised the maintainer's `owns:`-to-grant derivation to `dev`. Its AC-9 — "`mnt`, `rev`, and `bkf` are unchanged" — was written as a regression guard on that one change: for the same fixture FR, `mnt_permissions` equals the pre-FR derivation and "the permission files written for `rev` and `bkf` are byte-identical to the pre-FR files". The Reviewer pinned it adversarially, against a rich `owns:` (`_AC10_OWNS`, the Project A FR-0001 footprint) and against the pre-FR-0009 module loaded from `git show 647f353:template/scripts/dispatch.py`, in four parametrisations of `template/tests/unit/scripts/test_dispatch_permissions.py`.

FR-0010 (`extends: [FR-0009]`, `depends_on: [FR-0009]`), drafted the same day, decides the opposite for the same roles: AC-5 says `rev` and `bkf` "derive `Edit`/`Write` grants from `owns:` exactly as FR-0009 does for `dev`", and AC-4 unions stack-derived Bash grants into every role's allow-list. The FR-0010 maintainer-mode Developer implemented AC-5 as specified (`82a9467`) and four FR-0009 tests fail, exactly as FR-0010's dispatch brief had anticipated. The Developer escalated rather than editing a test file outside FR-0010's `owns:` (`.agent-team/escalation-matrix.md`: "Test reveals spec gap" / "Cross-FR conflict").

The constraint that makes this non-obvious is ADR-0001 rule 2: there are no untraced edits to a live object's normative content. FR-0009 AC-9 as written is now false by design of a later FR, and a test that simply stops running would leave the spec claiming a guarantee nobody holds — the "earlier FR quietly bent to fit a newer one" failure ADR-0001 exists to prevent. The honest record is a DEC that says what FR-0009 still guarantees, and who guarantees the rest.

Two of FR-0009's claims are affected, in different ways:

- **AC-9's `rev`/`bkf` byte-identity** holds for an FR with empty `owns:` under FR-0010 too (AC-5's last sentence says so explicitly: "An FR with empty `owns:` yields permission files byte-identical to the pre-FR ones for these two roles"). It no longer holds for a non-empty `owns:`. This is the narrowing FR-0009 AC-4 already applies to `dev`.
- **AC-4's and AC-9's comparisons against the pre-FR dispatcher** (dev-ownerless byte-identity, `mnt_permissions` equality, `rev`/`bkf` byte-identity) all implicitly assume no detected stack: FR-0010 AC-4 adds `Bash(...)` grants to every role and AC-6 lifts three maintainer denies when the project declares `uv`/`node`/`npx`. The existing tests run in marker-less temporary repositories, so they keep passing; the spec text just needs to say the condition out loud.

## Decision

FR-0009 is revised in place (`version: 2`, `breaking: true`, `last_breaking_revision: 2`):

1. **AC-9** now guarantees, for `rev` and `bkf`, byte-identity to the pre-FR-0009 permission files **for an FR with no `owns:`** (the same scoping AC-4 gives `dev`). For an FR with a non-empty `owns:`, the `rev`/`bkf` permission files are governed by FR-0010 AC-5 and verified by FR-0010's tests. The `mnt_permissions` equality claim is unchanged.
2. **AC-4 and AC-9** state that every comparison against the pre-FR dispatcher is made in a project with no detected stack (FR-0010 AC-12's condition). With a detected stack, FR-0010 AC-4 and AC-6 change every role's allow-list and the maintainer deny list by design, and those differences are FR-0010's to specify.
3. FR-0009's first Out-of-scope bullet ("a stack-aware command allow-list ... would be its own FR") is annotated: that FR is FR-0010.

`breaking: true` under ADR-0001 rule 4: four existing FR-0009 test parametrisations pin the v1 wording and must change. The cascade below names them and bounds the permitted edit so the FR-0010 Reviewer has no discretion to widen it.

`tier: neil`: FR-0009 is a merged control-plane FR whose implementation a human approved; this revision changes a guarantee that approval covered. Recorded `proposed`; per ADR-0001 rule 8 and the indexer's `LIVE_DEC_STATUSES`, the design proceeds on it. Neil ratifies at FR-0010's PR review, where this DEC rides.

## Alternatives considered

- **Leave FR-0009 AC-9 as written and delete or skip the four parametrisations as "superseded by FR-0010".** Rejected: FR-0009 would then assert byte-identity for `rev`/`bkf` that no test checks and no code provides — an untraced bend of a merged FR (ADR-0001 rule 2). The narrowed guarantee is still worth pinning, and pinning it needs the spec to say what it is.
- **Supersede FR-0009 with a new FR covering `dev`, `rev` and `bkf` together.** Rejected under ADR-0001 rule 5: FR-0009's identity — the Developer's write surface derives from the FR's declared footprint — is unchanged. One regression guard's scope narrows. That is a revision, and the `rev`/`bkf` extension already has a home (FR-0010 AC-5).
- **Revise FR-0010 AC-5 instead: keep `rev`/`bkf` on the static write surface.** Rejected: it discards the feature to protect a test. FR-0010's Why records the cost of the static surface for the Reviewer (Project A learnings L18/L20 — a Reviewer that cannot write its own test fixtures under the FR's footprint), and AC-5 was approved with the FR.
- **Keep the four tests on a rich `owns:` but compare to an `owns:`-aware expectation.** Rejected: that expectation is FR-0010 AC-5's contract, and FR-0010's Reviewer tests it in FR-0010's own test file. Duplicating it inside FR-0009's file would put two FRs' tests on one behaviour and make the next revision a two-file edit.

## Cascade

Breaking; every affected artifact:

- `projects/hub-tooling/specs/FR-0009-developer-permissions-derive-from-owns.md` — AC-4 and AC-9 amended as above; Out-of-scope bullet 1 annotated; `version: 2`, `revisions: [DEC-0002]`, `last_breaking_revision: 2`, `updated` bumped; Changelog line. Done in this commit.
- `template/tests/unit/scripts/test_dispatch_permissions.py` (FR-0009-owned; FR-0010's `owns:` gains it under DEC-0003 for exactly this edit) — the FR-0010 Reviewer is authorised to make **only** these changes, in FR-0010's Reviewer phase:
  - `test_non_dev_role_settings_files_are_byte_identical_to_pre_fr[rev]` and `[bkf]`: the fixture FR these two parametrisations write must have an **empty `owns:`** (`_fr_md(_FR, [])`). The `[docs]` and `[mnt]` parametrisations keep the rich `owns:` (`_AC10_OWNS + [".agent-team/roles/developer.md"]`). The comparison itself — both adapters, `.exists()` parity, byte-identity to the `647f353` module's output — is unchanged.
  - `test_static_roles_still_write_exactly_their_static_payload[rev]` and `[bkf]`: same narrowing — the fixture FR for these two parametrisations has an empty `owns:`; `[docs]` keeps `_AC10_OWNS`. The assertion (file equals the bare `ROLE_PERMISSIONS[role]` payload) is unchanged.
  - Each narrowed parametrisation gains a one-line comment citing `DEC-0002` and FR-0010 AC-5 as the home of the rich-`owns:` case; the module docstring's AC-9 sentence may be amended to "(for an ownerless FR — DEC-0002)". The `# covers hub-tooling FR-0009:AC-9` annotations stay.
  - No other test, fixture, helper or annotation in that file changes. In particular `test_mnt_permissions_equal_the_pre_fr_derivation`, `test_fr_owns_globs_is_unchanged_by_the_frontmatter_refactor` and every AC-1..AC-8/AC-10 test are untouched (they pass at `82a9467`).
- `template/tests/unit/scripts/test_dispatch_stack_grants.py` (FR-0010-owned) — the rich-`owns:` `rev`/`bkf` case moves here as FR-0010 AC-5 coverage: `Edit`/`Write` grants present for every non-withheld glob, the role's own path denies written unchanged, one WARN per withheld glob, and the empty-`owns:` case byte-identical (AC-5's last sentence, which is the same fact the narrowed FR-0009 tests pin from the other side).
- `projects/hub-tooling/specs/FR-0010-stack-aware-grants-and-lock-provisioned-venv.md` — `extends: [FR-0009]` unchanged; `owns:` gains `template/tests/unit/scripts/test_dispatch_permissions.py` (moved from `reads:`) with the write limited to this cascade. Done by DEC-0003 in the same commit series.
- No other object cites FR-0009 AC-4 or AC-9. FR-0011 and FR-0013 (`depends_on`/`extends` chains through FR-0010) are unaffected.

## Changelog

- 2026-09-21: created (proposed) — from the FR-0010 maintainer-mode Developer's `## ESCALATION` (cross-FR test conflict, `82a9467`)
- 2026-09-21: updated (ratified) - by Neil Gilchrist upon PR review
