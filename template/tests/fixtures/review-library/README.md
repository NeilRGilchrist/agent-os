# review-library fixtures (FR-0025)

Synthetic inputs for `tests/unit/scripts/test_review_library.py`. Nothing
here is derived from a real review, repository, or person.

- `reviewer-authored-REVIEW.md` — a Reviewer-shaped root `REVIEW.md` the
  tests commit or stage on a synthetic `claude/rev-FR-0001` branch to prove
  `finalize --role rev` files it at `specs/_reviews/FR-0001-r<N>.md` byte for
  byte (AC-1). It contains multi-byte characters (an em dash, an arrow) so
  byte counts are checked against bytes, not characters, and a `Verdict:`
  first line so it doubles as a `--verdict-file` (AC-4).

Line endings are LF (`.gitattributes` normalises text to LF). Tests that need
CRLF bytes generate them in-test.
