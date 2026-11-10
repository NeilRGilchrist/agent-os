# labelled-acs fixtures

Synthetic FR bodies for `tests/unit/scripts/test_labelled_acs.py`
(hub-tooling FR-0027). Every file is generated; no real records.

Each file under `bodies/` is the Markdown that follows an FR's frontmatter. The
test prepends a synthetic frontmatter block (id, status, `ac_state`) so one
body serves several FRs.

- `all-labelled.md` - every AC is a labelled bullet `- **AC-N (L):** R`: a
  label with backticks, commas, a dash and a nested `(...)`, an AC with
  continuation lines, and an AC whose rest `R` is empty. The Why section
  mentions two of the ACs in prose.
- `mixed.md` - plain and labelled bullets in one section.
- `indented.md` - a labelled bullet indented two spaces (the gate detects it;
  the indexer reads it as a continuation line of the AC above).
- `outside-section.md` - a labelled bullet outside `## Acceptance criteria`.
- `plain.md` - plain bullets only, three ACs.
- `near-misses.md` - one bullet per shape that is *not* a labelled bullet
  (FR-0027 Terms). The test also splits it into one body per shape.
