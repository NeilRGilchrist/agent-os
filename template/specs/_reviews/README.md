# Review library (`specs/_reviews/`)

One committed file per FR per review round: the Reviewer's review of record,
filed by the dispatcher (FR-0025, DEC-0023). It replaces the single root
`REVIEW.md` every Reviewer branch used to commit, which conflicted on every
merge after the first in a wave and let one FR inherit another's review.

## Path scheme

`specs/_reviews/<FR>-r<N>.md`, for example `specs/_reviews/FR-0007-r2.md`.

- `<FR>` is the FR under review.
- `N` is the review round, in decimal without padding (`r1`, `r2`, `r10`).
  `finalize --role rev` takes it from `--review-round N` when that is passed,
  else from the Reviewer run's own round (the run context or its lock), else 1.
  Pass `--review-round` for a hand-run Reviewer whose later round has no lock.
- If round N is already filed with different content, the new review is filed
  at the lowest free round above the highest filed one, with one `WARN`.
  A filed round is never overwritten.

## Who writes it

- Only `scripts/dispatch.py finalize <FR> --role rev --apply` writes here. The
  Reviewer itself still writes and stages `REVIEW.md` at its worktree root
  (its handoff, unchanged); finalize files that file here byte for byte and
  takes the root file off the branch in the same commit. When the Reviewer
  wrote none, or an empty one, finalize files the synthesised review (the
  Reviewer's final message, or `--verdict-file`) instead.
- One commit per round, `review(<FR>): round <N> verdict=<verdict>`. Re-running
  finalize for a round that is already filed adds no commit.
- Files are never edited after they are filed. A correction is a new round.
- The verdict of record is unchanged: the Reviewer's final message or
  `--verdict-file`. This file is the review of record, not the verdict source.

## Who reads it

The dispatcher reads the **newest round** (the highest N) for an FR and
nothing else: never the root `REVIEW.md`, never another FR's files, and never
a name outside the scheme (`FR-0007-r01.md`, `FR-0007-final.md`). The rework
precondition, the rework brief and the verdict fallback all use it.

`scripts/index-specs.py` only reads `specs/FR-*.md`, so it never sees this
directory.

## Notes: migrating a legacy root `REVIEW.md`

A project that predates this library may carry a root `REVIEW.md` on `main`.
Finalize never files, moves or deletes it: a root `REVIEW.md` whose content
equals the one at the branch's merge-base with `main` is inherited, gets one
`WARN`, and is left in place. Neither the dispatcher nor `bootstrap.py
--upgrade` migrates it. Do it once, by hand, in one commit on `main`, at a
wave boundary:

1. Find the FR and round it belongs to, e.g. from
   `git log -1 --format=%s -- REVIEW.md`.
2. `git mv REVIEW.md specs/_reviews/<FR>-r<N>.md` and commit.
3. Merge or re-finalize, first, any open PR whose branch changed the root
   `REVIEW.md`; otherwise that PR meets one modify/delete conflict.
