# postapprove fixtures (FR-0013)

Synthetic inputs for `tests/unit/scripts/test_dispatch_review_artifact.py`
and `test_dispatch_postapprove.py`. Nothing here is derived from a real
review, repository, or person.

- `reviewer-authored-REVIEW.md` — a Reviewer-shaped `REVIEW.md` the tests
  commit onto a synthetic `claude/rev-FR-0001` branch to prove `finalize`
  keeps it byte-for-byte (AC-2). It deliberately contains multi-byte
  characters (em dashes, an arrow) so the `REVIEW-KEPT` byte count is
  checked against bytes, not characters, and a `Verdict:` first line so the
  same file doubles as a `--verdict-file` (AC-4).
- `verdict-request-changes.md` — a `--verdict-file` whose first line
  declares `request-changes` while the heading below it says the opposite
  (AC-3 tier 1 beats tier 2; AC-4 precedence over the log).

Line endings are LF. Tests that need CRLF bytes generate them in-test.
