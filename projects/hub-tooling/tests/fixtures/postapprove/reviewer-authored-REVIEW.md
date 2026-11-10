Verdict: approve

## FR-0001 review — **Approve** (round 1 of 3)

Synthetic Reviewer artifact. Everything below is invented for the test
suite — no real project, person, or record is referenced.

### Verified passing

- AC-1 — `tests/test_ac1.py::test_first_thing` → green
- AC-2 — `tests/test_ac2.py::test_second_thing` → green, plus the
  boundary case (empty collection) the naive implementation missed

### Nits (not blocking)

- `src/thing.py:12` — the docstring says "returns None" but the function
  returns an empty list; harmless, worth a follow-up.
- The error message on the malformed-input path could name the field.

### Findings routed onward

- [spec] AC-2's "empty" is ambiguous between "no items" and "not
  provided" — resolved here as "no items"; the Architect may want to say so.

### Knowledge-base candidates

- Pattern: a fast-forward-only sync between role branches is the cheapest
  way to keep two worktrees honest about which commits they share.

— end of synthetic review —
