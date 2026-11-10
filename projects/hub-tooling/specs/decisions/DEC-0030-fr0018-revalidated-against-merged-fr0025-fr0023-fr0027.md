---
id: DEC-0030
title: "FR-0018 revalidated against merged FR-0025, FR-0023 and FR-0027: `DISPATCH_WORKTREE` names the project root inside the role worktree, AC-4's indexer failure includes a malformed layout, AC-7 names its pinned tests by id, the bite-check base is the Developer's base commit, and AC-4 restores the indexer's side-writes"
tier: architect
status: ratified  # proposed | ratified | rejected | superseded — ratified by Neil merging #29 on 2026-11-03
satisfies: []
constrained_by: [FR-0023, FR-0024, FR-0025]
revises: FR-0018
breaking: false
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Leave DISPATCH_WORKTREE as the worktree path and let FR-0024 redefine it"
  - "Leave AC-7's line numbers and let the Developer map them"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0018 still stands in substance after FR-0025, FR-0023 and FR-0027
  merged. Four statements had drifted: the redirect's worktree check would
  silently never fire for a subdirectory project, AC-4 did not say that a
  malformed layout now fails the indexer, AC-7 cites line numbers from
  another repository, and the bite-check base a8889df is unreachable here.
created: 2026-11-02
updated: 2026-11-03
---

# DEC-0030: FR-0018 revalidated against merged FR-0025, FR-0023 and FR-0027

## Context

FR-0018 (ready, v2, DEC-0025; `depends_on: [FR-0016, FR-0025]`) has not been dispatched. Under the architect role's rebase-and-revalidate rule it was read against `main` at `ddbe9e5`, after FR-0027 (#24), FR-0025 (#25) and FR-0023 (#26) merged.

- **FR-0025.** The library files each review at its own `specs/_reviews/<FR>-r<N>.md` and adds no generated or shared file. `_finalize_revalidate_stale_branch` still merges `origin/main` and leaves any conflict for a human, so AC-4's carve-out (`specs/INDEX.md` only) is still the whole need. FR-0018's `REVIEW.md` halves were already withdrawn by DEC-0025.
- **FR-0023.**
  - `metrics_log.py` is untouched, and its `REPO_ROOT` is still the directory above `scripts/`: the project root.
  - For a subdirectory project, the agent's project root inside a whole-repo worktree is `<wt>/<prefix>` (FR-0024), not `<wt>`. So AC-2's comparison against "the role worktree" would never match, and the redirect would silently stay off.
  - The worktree's `index-specs.py`, which AC-4 runs, now validates the layout first.
- **FR-0027.** It does not interact with FR-0018. FR-0018 reads no ACs.
- **AC-7's line numbers** (`L1289` … `L2159`, `L394`, `L505`, `L529`) come from the imported audit. In this repository several point at blank lines. They map, with a constant offset of +3 in `test_dispatch_postapprove.py`, to ten named tests. The `test_dispatch_review_artifact.py` and `test_dispatch_finalize.py` lines no longer map, because FR-0025 rewrote those files.
- **Notes' bite-check base `a8889df`** is not in this repository (ADR-0002).

## Decision

1. **`DISPATCH_WORKTREE` names the project root inside the role worktree.** That is the worktree path today, and `<worktree>/<prefix>` once FR-0024 lands. AC-1 says so. AC-2's rule ("`metrics_log`'s own `REPO_ROOT` resolves to the same directory as `DISPATCH_WORKTREE`") is unchanged and now holds for both layouts. `DISPATCH_METRICS_DIR` is unchanged: the dispatcher's `REPO_ROOT` is already the primary project root. For a project at the repository top, nothing observable changes.
2. **AC-4's "indexer exits non-zero" includes a malformed layout.** No new case is needed: it is an `ERROR` with the conflict left in place. AC-2's verification notes that the worktree gate loads the layout first.
3. **AC-7 names its pinned tests by id:**
   - the ten `test_dispatch_postapprove.py` tests above (listed in the FR);
   - every test in `test_dispatch_review_artifact.py`, `test_review_library.py` and `test_dispatch_finalize.py` as FR-0025 left them;
   - every `test_deploy_gate_metrics.py` and `test_metrics_log.py` harness, as before.
4. **The bite-check base is the Developer's base commit**, recorded as a constant, in place of `a8889df`.
5. **Dependencies.**
   - FR-0016 and FR-0025 are marked merged.
   - FR-0023 and FR-0027 are added (merged; the interactions above).
   - FR-0024's obligation from item 1 is recorded.
   - FR-0026's overlap on `metrics_log.py` and the metrics README is recorded as disjoint hunks.

   `depends_on` is unchanged. `reads:` gains `template/scripts/project_layout.py`.
6. **AC-4's resolution changes nothing but `specs/INDEX.md`: the indexer's side-writes are restored** (FR-0018 r1 review E-1, `specs/_reviews/FR-0018-r1.md` at `497cfa6`; Neil chose this resolution on 2026-11-02, the Reviewer's recommended default).
   - **The gap.** The worktree's `index-specs.py`, in plain mode, also rewrites `CODEOWNERS` whenever `.agent-team/codeowners-config.yaml` exists. AC-4 stages only `specs/INDEX.md`. So a regenerated `CODEOWNERS` that differs from the merged one is left as ` M CODEOWNERS` after `git commit --no-edit`. FR-0013 AC-1's later fast-forward and a second `--revalidate` then refuse the dirty worktree, and a human is needed.
   - **The side-write set.** The resolution names, in one place, the paths other than `specs/INDEX.md` that the worktree indexer can write, relative to the project root. Today that set is exactly `CODEOWNERS`. A later FR that gives the indexer another output adds it to the set.
   - **Snapshot and restore.**
     - Before running the indexer, the resolution records, for each path in the set, whether it exists and its exact bytes.
     - After the indexer returns, on success and on failure alike, it puts back every path whose state changed. Changed bytes are rewritten exactly. A path that did not exist before is removed again. A path the indexer deleted is recreated.
     - On success this happens before `git add -- specs/INDEX.md` and `git commit --no-edit`. On failure it happens alongside the existing restore of the conflicted `INDEX.md` bytes.
   - **The outcome.**
     - The merge commit holds the textual merge of every side-write path, exactly as a clean revalidate merge does under DEC-0011.
     - Only `specs/INDEX.md` is staged.
     - On success the worktree has no uncommitted tracked change: `_rev_worktree_dirty_paths` is empty.
     - No new git argv is introduced. The restore is a file write or unlink, never `checkout`, `restore`, `reset` or `stash`.
   - **AC-4** states this as a fourth "What it does" bullet and gains one verification case.

**`breaking: false`.** Items 1 to 5 were written before FR-0018 had any implementation. For a top-level project, item 1 is the v2 behaviour exactly, and items 2 to 5 restate or relocate existing requirements.

Item 6 was added after round 1 (`497cfa6`), and it does require a Developer change. It is still non-breaking. It delivers a promise FR-0018 already made: "the two generated-file conflicts resolve without a human" (Out of scope). The round-1 code does not keep that promise when `CODEOWNERS` is configured. The round-2 change narrows what the resolution leaves behind and changes no behaviour any other AC or pinned test relies on. This is the reasoning DEC-0027 item 6 used for FR-0023. FR-0018 goes to `version: 3` with `revisions: [DEC-0025, DEC-0030]`, and `last_breaking_revision` stays `null`. Rule 5 was checked: identity unchanged. `owns:` is unchanged, so the maintainer-mode approval of 2026-09-25 still covers the write surface.

## Alternatives considered

- **Leave `DISPATCH_WORKTREE` as the worktree path and let FR-0024 redefine it.** Rejected. FR-0024 is drafted and ready, and does not mention the variable. The redirect would ship correct for top-level projects and silently inert for hub-tooling, the one subdirectory project. Defining it as the project root costs nothing now.
- **Item 6: stage `CODEOWNERS` with `INDEX.md`.** Rejected by Neil. It widens AC-4's "staged" beyond the conflicted path, and puts a non-conflicted file's regenerated content into a merge commit. A clean revalidate merge never does that (DEC-0011).
- **Leave AC-7's line numbers.** Rejected. Several point at blank lines here, so "passes unedited" would be checked against the wrong tests.

## Cascade

Non-breaking. Updated in this commit:
- `projects/hub-tooling/specs/FR-0018-merge-friction-metrics-rows-index-and-review-md.md`: AC-1, AC-2's verification, AC-4, AC-7, Notes (Reviewer), Dependencies, `reads:`, `version: 3`, `revisions`, `updated`, and a Changelog line.

Item 6, in a later commit: FR-0018 AC-4 gains a fourth "What it does" bullet and one verification case, plus a Changelog line. FR-0018 stays at `version: 3`, because DEC-0030 is unmerged.
- **Developer round 2:** implement the side-write set, the snapshot and the restore in the AC-4 resolution in `template/scripts/dispatch.py`.
- **Reviewer:** `test_merge_friction_adversarial.py::test_a_codeowners_rewrite_by_the_indexer_does_not_leave_the_worktree_dirty` is `xfail(strict=True)`. Drop the marker, so it becomes a plain test. Add the AC-4 verification cases:
  - an absent `CODEOWNERS` that the indexer would create is absent again;
  - an indexer that rewrites `CODEOWNERS` and then fails leaves it restored.
- No other test changes.

Follow-ups outside this DEC, for FR-0024's DEC to pick up when it is next revised or rebased:
- FR-0024's dispatcher half sets `DISPATCH_WORKTREE` to `<worktree>/<prefix>` (item 1).
- **r1 N-1.** AC-4's `wt_path`-relative `scripts/index-specs.py` and `specs/INDEX.md` must be derived from `_worktree_project_root(wt_path)`, so the project root has one definition. Today `_resolve_index_only_merge_conflict` uses `wt_path / "scripts" / "index-specs.py"` and the repo-relative `specs/INDEX.md`. Item 6's side-write paths (`CODEOWNERS`) follow the same root.

## Changelog

- 2026-11-02: created (proposed), before FR-0018's dispatch.
- 2026-11-02: item 6 added, still proposed and non-breaking. It comes from the r1 ESCALATION E-1 at `497cfa6` and Neil's choice of the Reviewer's default. The cascade records r1 N-1 for FR-0024.
- 2026-11-03: status `proposed` → `ratified`. Neil merged PR [#29](https://github.com/NeilRGilchrist/cos-agent-hub/pull/29) (commit `f719f89`), whose description stated that merging ratifies this DEC. The description asked Neil to confirm `breaking: false` for item 6; he merged without asking for a change, so the flag stands. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it.
