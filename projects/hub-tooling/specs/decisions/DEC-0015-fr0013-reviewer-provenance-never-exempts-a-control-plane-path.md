---
id: DEC-0015
title: "FR-0013 AC-5(a)'s Reviewer-provenance exemption never covers a control-plane path. A path matching `MNT_PROTECTED_GLOBS` and outside `owns:` refuses `finalize --role mnt`, whoever committed it."
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0010, FR-0015]
revises: FR-0013
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave AC-5(a) as it is and rely on FR-0015 AC-2 refusing the Reviewer's own finalize"
  - "Replace provenance with a path pattern (tests/** and REVIEW.md only)"
  - "Exempt a Reviewer-landed control-plane path when its diff is content-free"
  - "Reopen FR-0013 with a follow-on owns: (the chore(FR-NNNN) pattern) instead of implementing under FR-0015"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  AC-5(a) was written so the footprint check would stop refusing the Reviewer's
  tests after an approve (Project A L39). As worded, it exempts *any* path the
  Reviewer's fast-forwarded commits touched. `rev` holds `Bash(python *)`
  statically, plus every stack grant, so a Reviewer-authored edit to
  `scripts/deploy-gate.py` rides into a maintainer PR past the one automated
  check DEC-0014 names as the control-plane boundary. No Reviewer has a reason
  to change a control-plane path, so exempting none costs nothing.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0015: Reviewer provenance never exempts a control-plane path

## Context

FR-0013 AC-5 has two exemptions from `mnt_footprint_violations`: (a) paths whose every change on `<base>..<branch>` came from a commit AC-1 fast-forwarded in from `claude/rev-<FR>`, recorded as `ff_commits` (DEC-0009); and (b) `specs/_metrics/**`. The motivating case (Project A L39) was the Reviewer's own adversarial tests, which sit outside a maintainer FR's `owns:` and which the terminal state of an approve requires on the PR. The Open question and DEC-0009 settled *how* to identify Reviewer-landed paths: by provenance, never by path pattern. Nobody asked *which* paths it should cover, and the text answers "all of them".

DEC-0014 records that command-level narrowing is not the control-plane boundary; the artifact-level check at finalize is. For a maintainer-mode FR, `_mnt_provenance_exemptions` is a hole in exactly that check. `rev` holds `Bash(python *)` statically and every stack grant through FR-0010 AC-4, and the FR-0010 Reviewer demonstrated a denied-path write from inside a `rev` worktree. The dispatcher commits whatever the Reviewer staged (FR-0006), fast-forwards it onto `claude/mnt-<FR>` on an approve (FR-0013 AC-1), and AC-5(a) then exempts it. A control-plane edit authored by the Reviewer therefore reaches the maintainer PR with no automated check at all.

## Decision

1. **AC-5(a) never exempts a path that matches `MNT_PROTECTED_GLOBS`.** Such a path is on the violation list only because it lies outside `owns:`, so it stays a violation, and `finalize --role mnt` refuses exactly as it would without AC-5. In place of AC-5(a)'s `NOTE`, one line says why the path was not exempted. AC-5(b) (`specs/_metrics/**` is not a protected path) and AC-6 (`--allow-crossing`, which *proves* a diff is content-free) are unchanged.

2. **FR-0013 AC-5's text is amended in place.** One sentence records the carve-out and cites this DEC. No other AC of FR-0013 changes, and FR-0013's `owns:` does not change.

3. **The work is done under FR-0015, not by reopening FR-0013.** FR-0015 AC-1 is the implementing criterion and FR-0015's `owns:` carries `template/scripts/dispatch.py`. FR-0015 makes the same finalize block refuse control-plane paths for every role (AC-2, AC-3, AC-4). A separate `chore(FR-0013)` round on `_mnt_provenance_exemptions` would put two FRs on one function in the same wave.

4. **Tests.** No pinned expectation in `template/tests/unit/scripts/test_dispatch_postapprove.py` changes. None of its AC-5 tests exempts a protected path. The only protected path in that file is the stand-in `scripts/deploy-gate.py`, which the tests commit on `main`, outside `<base>..<branch>`. FR-0015's Reviewer adds the new tests in `test_dispatch_grant_hardening.py`. An existing test that goes red is a `## FINDINGS` line (FR-0015 AC-6), not an edit.

**`breaking: true`** (ADR-0001 rule 4): `_mnt_provenance_exemptions` implements AC-5(a) and must change. FR-0013 goes to `version: 6` with `last_breaking_revision: 6`. Rule 5 was checked: FR-0013's identity, the post-approve and Reviewer-artifact lifecycle, is unchanged.

**Why `neil`.** It is a security ruling (escalation matrix). Neil approved it as D2 in the Architect session of 2026-09-25, and it is recorded `ratified` on that approval, consistent with DEC-0014. FR-0015's merge is when it takes effect in code.

## Alternatives considered

- **Leave AC-5(a) and rely on FR-0015 AC-2 refusing the Reviewer's own finalize.** Rejected. AC-2 runs only when the Reviewer is finalized through a dispatcher at FR-0015's version. A Reviewer branch landed by hand, or fast-forwarded in a project not yet upgraded, would still pass through the exemption. The check belongs where the exemption is granted. FR-0015 has both, deliberately.
- **Replace provenance with a path pattern.** Already rejected by FR-0013's Open question and DEC-0009: a pattern lets a maintainer write `tests/**` directly past a check whose purpose is that it cannot.
- **Exempt a Reviewer-landed control-plane path when its diff is content-free.** Rejected as redundant. FR-0013 AC-6's `--allow-crossing` already offers a *verified* content-free crossing for any path, asserted by the operator rather than inferred.
- **Reopen FR-0013 with a follow-on `owns:`.** Rejected: Decision 3.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0013-post-approve-and-reviewer-artifact-lifecycle.md`: AC-5 gains one sentence citing this DEC; `version: 6`, `revisions` gains DEC-0015, `last_breaking_revision: 6`, `updated: 2026-09-25`; one Changelog line. `owns:` unchanged. Done in this commit.
- `template/scripts/dispatch.py::_mnt_provenance_exemptions`: FR-0015 AC-1, **Developer, maintainer mode**. It skips any path matching `MNT_PROTECTED_GLOBS` and prints the replacement line.
- `template/tests/unit/scripts/test_dispatch_grant_hardening.py` (new, FR-0015-owned): FR-0015's Reviewer covers AC-1's three scenarios.
- `template/tests/unit/scripts/test_dispatch_postapprove.py`: **no change** (Decision 4).
- FR-0006, FR-0010: no change from this DEC. FR-0010 is revised separately by DEC-0014.

## Changelog

- 2026-09-25: created and ratified. Neil approved D2 (close the finalize check's Reviewer-provenance gap) in the hub-tooling Architect session.
