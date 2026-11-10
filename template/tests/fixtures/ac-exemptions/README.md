# ac-exemptions fixtures (hub-tooling FR-0026)

Synthetic FR bodies (everything after the frontmatter) for
`tests/unit/scripts/test_deploy_gate_ac_exemptions.py` and
`tests/unit/scripts/test_index_specs_ac_exemptions.py`. The tests add the
frontmatter, so one body serves several `status` / `ac_state` combinations.
Every file is generated, never derived from real records (see
`tests/fixtures/README.md`).

| Body | Shape |
|---|---|
| `bodies/adversarial.md` | AC-9: three plain ACs; the test defers AC-2 and covers it |
| `bodies/legacy-withdrawn.md` | AC-14: a hand-withdrawn AC kept as `- **[DEPRECATED] AC-3**` under `## Withdrawn acceptance criteria` |
| `bodies/p2-live.md` | AC-14: a `[P2]`-tagged AC that is still live, plus a labelled AC under `## Acceptance criteria` |
| `bodies/three-ac-supersession.md` | AC-14: three ACs superseded by hand, each kept only in the legacy `[DEPRECATED]` form |
| `bodies/migrated.md` | AC-5 / AC-7: the migrated convention: a plain and a labelled bullet under `## Withdrawn acceptance criteria`, and one legacy line the indexer ignores |

The legacy `[DEPRECATED]` lines model a convention projects used before
FR-0026: the gate's AC detection does not match them, so the gate prints its
`ac-format` warning for each.
