# `gates/` fixtures (FR-0008)

Synthetic fixtures for FR-0008's Reviewer tests — declared gates.
Generated, never derived from a real record (see `../README.md`).

- `frontmatter/` — one FR per AC-1 outcome: `valid-two-gates.md` and the
  three shapes that mean "no gates" parse clean; every other file is one
  error class (`--validate` must name the FR and the offending gate).
- `evidence/` — AC-2 evidence files: one per `gate_status` outcome.
