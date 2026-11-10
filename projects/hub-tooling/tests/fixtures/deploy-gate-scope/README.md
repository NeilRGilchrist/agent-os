# deploy-gate-scope fixtures

Synthetic spec trees for `tests/unit/scripts/test_deploy_gate_scope.py`
(hub-tooling FR-0021). Every file is generated; no real records.

- `dec-accepted/specs/` - the DEC-0001 shape: an FR with `revisions: [DEC-0001]`
  and a DEC whose `status` is the ADR token `accepted` rather than one of the DEC
  statuses. The indexer refuses this tree with two errors (the DEC parse error
  and the FR's now-unresolvable `revisions` entry). Before FR-0021 the deploy
  gate printed PASSED on it and rewrote INDEX.md without its Decisions table.
