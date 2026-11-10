# Pipeline metrics log (`specs/_metrics/`)

Append-only, per-project NDJSON log of what the agent pipeline did — emitted
at the source by `scripts/dispatch.py`, `scripts/deploy-gate.py` and
`scripts/escalation-log.py` through one shared module, `scripts/metrics_log.py`
(FR-0002 / proposal H6, derived from IDEA-0016). This file is the normative
schema; the module is its executable form.

- **Location:** `specs/_metrics/<YYYY-MM>.ndjson`, UTC month of the record's `ts`.
  Directory and file are created on first write. One JSON object per line.
- **Committed**, not local-only (decided 2026-09-07). `.gitattributes` declares
  `specs/_metrics/*.ndjson merge=union` so appends on different branches merge
  without conflict. Existing projects add that line by hand until
  `bootstrap.py --upgrade` syncs `.gitattributes`.
- **Append-only.** The module exposes append and read only; the CLI's only
  mutating subcommand is `emit`. Nothing here is ever rewritten, so a month
  file's bytes before a write are always a prefix of its bytes after. Each
  record is written as one complete line under an exclusive OS-level lock on
  the month file (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere), so
  concurrent writers never interleave or lose records and a reader never
  sees a partial line; a lock that cannot be taken within `LOCK_TIMEOUT_S`
  is just another non-load-bearing emitter failure (one `WARN: metrics:`).
- **Never load-bearing.** Any emitter failure is exactly one `WARN: metrics:`
  line on stderr; the emitting command's exit code and stdout are unchanged.
  `METRICS_LOG_DISABLED=1` suppresses all emission.
- **No transcript text, no PHI.** Records carry identifiers, enumerations,
  counts, durations, timestamps, repo-relative paths, PR numbers, SHAs, the
  project's own PR URLs and booleans — never agent prose, review or PR bodies,
  commit messages, tool error messages or file contents. `validate()` rejects
  any string longer than 200 characters and any string under a field that is
  not on the allow-list (`metrics_log.STRING_FIELDS`). When
  `.agent-team/hooks/phi_regex_check.py` is present (compliance profile), every
  string is run through its `PHI_PATTERNS`; a match drops the whole record with
  a `WARN: metrics:` line.

## CLI

```
python scripts/metrics_log.py query [--kind K]... [--fr FR-XXXX] [--role R]
        [--since ISO] [--until ISO] [--where '["field","op",value]']...
        [--group-by FIELD]... [--agg count|sum:F|avg:F|max:F|min:F|distinct:F]... [--table]
python scripts/metrics_log.py report <name> [--table | --json]
python scripts/metrics_log.py validate [FILE]        # read-only
python scripts/metrics_log.py emit --kind KIND [--source manual] [--role R]
        [--object-id ID]... [--run-id ID] [--json '{...}']
```

`query` streams matching records as NDJSON (default) or a table; with
`--group-by`/`--agg` it returns aggregate rows. Every month file is read;
records with unknown `kind` or extra fields are tolerated; with no log the
command exits 0 with empty output. `--metrics-dir` (before the subcommand)
points at another directory — useful against `tests/fixtures/metrics/`.

The virtual field **`fr`** (usable in `--fr`, `--group-by`, `--where` and report
definitions) is the FR IDs in `object_ids`, or — when there are none — the FRs
of the `dispatch.*` records sharing the record's `run_id`. That is how a
Developer's gate runs inside a worktree, which name no FR, join their FR.

## Named reports (`specs/_metrics/reports/<name>.json`)

A report is a data file, so adding a dashboard means adding a file, not code:

```json
{
  "description": "...",
  "sections": [
    { "name": "by_role",
      "filters": { "kind": ["dispatch.run"], "role": null, "fr": null, "since": null, "until": null },
      "where":   [["round", "gt", 1]],
      "group_by": ["fr", "role"],
      "aggs": { "runs": "count", "tool_calls": "sum:tool_calls_total" } }
  ]
}
```

A file without `sections` is a single section. `where` clauses are
`[field, op, value]` with `op` in `eq ne gt gte lt lte in not-in contains`;
dotted fields (`counts.frs`) reach into nested objects. Rows are sorted by
group key, so output is deterministic.

### Baseline reports (reproduce IDEA-0016's hand measurements)

| Report | Sections | Definition |
|---|---|---|
| `tool-calls-per-fr` | `by_role`, `lifecycle_total` | sum of `dispatch.run.tool_calls_total` per FR by role, and per FR overall |
| `retries-per-fr` | `rework_rounds`, `tool_errors`, `gate_failures` | count of `dispatch.run` with `role: dev` and `round > 1`; sum of `tool_errors_total`; count of `gate.run` with `outcome != pass` plus the distinct `failure_classes` |

Against the shipped fixture `tests/fixtures/metrics/2026-08.ndjson` (one
synthetic FR-0020 lifecycle after IDEA-0016's case: Architect 25 calls,
Developer 75 then a rework round of 18, Reviewer 20 then 12, three failed gate
runs) the reports return: architect 25 / dev 93 / rev 32, lifecycle total 150;
rework rounds 1, tool errors 18, gate failures 3 with classes
`coverage-missing`, `covers-unknown-ac`, `spec-validation`.

```
python scripts/metrics_log.py --metrics-dir <dir-with-fixture-and-reports> report tool-calls-per-fr --table
```

(`report` looks for `reports/` under the metrics dir, so copy or symlink
`specs/_metrics/reports/` next to the fixture when running it out of tree.)

## INDEX.md

When the log holds records attributable to an FR, `scripts/index-specs.py` (and
`scripts/deploy-gate.py`, through the same `render_index`) appends a
`## Pipeline metrics` section to `specs/INDEX.md`: one row per FR with the
latest `dispatch.run` status per role, total tool calls, the three retry
measures above, the last gate outcome and the last PR number. With no records
the file is byte-identical to a project without this log. `--validate`,
`--ac-hashes` and the query modes never read the log.

## Record envelope

Every record carries these fields (AC-1). Types are JSON types; "nullable"
means `null` is a legal value, the key is still present.

| Field | Type | Nullable | Meaning |
|---|---|---|---|
| `schema_version` | integer | no | `1` |
| `record_id` | string | no | unique per record (32 hex chars) |
| `ts` | string | no | UTC ISO-8601, e.g. `2026-09-07T12:34:56Z` |
| `project` | string | no | `METRICS_PROJECT` if set, else the primary checkout's root directory name (resolved through `git rev-parse --git-common-dir`, so worktrees report the project, not `dev-FR-XXXX`) |
| `kind` | enum | no | one of the kinds below |
| `source` | enum | no | `dispatch` \| `gate` \| `escalation-log` \| `manual` |
| `role` | enum | yes | `architect` \| `dev` \| `rev` \| `bkf` \| `mnt` \| `docs` \| `orchestrator` \| `null` |
| `object_ids` | list of string | no (may be empty) | spec-object IDs the record is about — `FR-XXXX` today, `TR-`/`DEC-` later |
| `run_id` | string | yes | identical across every record produced by one agent invocation: `dispatch.spawn`, `dispatch.run`, the gate runs the agent performs (via the `DISPATCH_RUN_ID` environment variable the dispatcher sets in the agent's environment) and the PR events at finalize |

Unknown fields are accepted (forward compatibility) **provided they carry no
strings**; a string under a field outside the allow-list fails validation
(AC-13). Dict keys (tool names, FR ids) are identifiers and are only
length-checked.

## Kinds and kind-specific fields

### `dispatch.spawn` — `source: dispatch` (AC-3)

Emitted by `dispatch.py` when `spawn_role` returns `spawned` (never on dry-run).

| Field | Type | Nullable | Meaning |
|---|---|---|---|
| `harness` | string | no | `claude-code` \| `cursor` |
| `worktree_status` | string | no | `created` \| `reused`, optionally followed by comma-separated segments present only when non-empty, in order: `stack=<ids joined by '+'>` (FR-0010 AC-7), `venv=<classification>` (FR-0010 AC-9), `preflight=...` (FR-0011) |
| `base_branch` | string | no | branch the worktree was based on |
| `model` | string | yes | resolved model override (`DISPATCH_MODEL_<ROLE>` / role default), `null` when none |
| `round` | integer | no | Dev↔Reviewer round (1 = base pipeline) |

### `dispatch.run` — `source: dispatch` (AC-3, AC-7)

Emitted when an agent's outcome is evaluated (wave phases, rework rounds,
phase timeouts, one-shot roles). Counts come from the harness NDJSON log.

| Field | Type | Nullable | Meaning |
|---|---|---|---|
| `status` | enum | no | `success` \| `error` \| `escalation` \| `timeout` \| `no-log` |
| `tool_calls_total` | integer | no | number of `tool_use` blocks |
| `tool_calls_by_tool` | object name→integer | no | per-tool counts |
| `tool_errors_total` | integer | no | number of `tool_result` blocks with `is_error` |
| `tool_errors_by_tool` | object name→integer | no | per-tool error counts (counts only; never messages — Q5) |
| `tokens_in` | integer | yes | from the harness `result` line's `usage`: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`; `null` when the log carries no usage — never estimated |
| `tokens_out` | integer | yes | `usage.output_tokens`; `null` when absent |
| `duration_s` | number | yes | seconds from the lock's `started_at` to evaluation; `null` when no lock was found |
| `round` | integer | no | round the run belonged to |
| `verdict` | string | yes | Reviewer only: `approve` \| `request-changes` \| `comment` |
| `findings` | list of `{tag, refs, chars}` | no (may be empty) | one entry per `## FINDINGS` line: `tag` ∈ `scope` \| `spec` \| `doc` \| `slice-miss` \| `""`; `refs` = spec-object IDs (`FR-`/`TR-`/`DEC-`/`ADR-`/`GOAL-`) and repo-relative paths found in the finding; `chars` = its length. The finding text is **not** stored (it still reaches the wave synthesis and `--park-findings`) |

**`[slice-miss]` convention.** An agent that had to read a spec object or file
its dispatched context did not include writes, in its final message:

```
## FINDINGS
- [slice-miss] needed specs/FR-0009-extraction-agent.md to satisfy AC-3
```

The dispatcher records `{ "tag": "slice-miss", "refs": ["FR-0009",
"specs/FR-0009-extraction-agent.md"], "chars": 61 }`. H1 (compiled slices,
IDEA-0053) reads these to tune what a slice must carry.

### `dispatch.wave` — `source: dispatch`, `role: orchestrator` (AC-3)

One per `dispatch.py wave --apply` synthesis. `object_ids` = every FR in the wave.

| Field | Type | Meaning |
|---|---|---|
| `fr_count` | integer | FRs processed |
| `completed` | integer | completed end-to-end |
| `dev_only` | integer | Developer finalized, Reviewer pending/dropped |
| `dropped` | integer | dropped FRs |
| `drop_reasons` | list of `{fr_id, phase}` | phase = `dev-tick` \| `dev-monitor` \| `dev-evaluate` \| `dev-finalize` \| `rev-monitor` \| `rev-evaluate` \| `rev-finalize` \| `rework-round-N` (no free text) |
| `rounds_ran` | object fr_id→integer | rounds per FR |
| `force_escalated` | list of string | FR ids whose budget was exhausted without approval |

### `gate.run` — `source: gate` (AC-4)

One per `deploy-gate.py` invocation except `--status-only`. `object_ids` = FR
ids named in failures (empty on a pass).

| Field | Type | Meaning |
|---|---|---|
| `stage` | string | `dev` \| `review` \| `full` |
| `outcome` | enum | `pass` \| `fail` \| `error` |
| `failure_classes` | list of enum | `spec-validation` \| `covers-unknown-fr` \| `covers-malformed-ac` \| `covers-unknown-ac` \| `coverage-missing` \| `script-error` \| `gate-evidence-missing` \| `gate-evidence-stale` (FR-0008 AC-9: a declared gate's evidence is missing, or `pass` but stale) |
| `warning_classes` | list of enum | `implements-missing` \| `implements-unknown-fr` \| `ac-format` |
| `counts` | `{frs, covers, implements}` | integers |
| `invoked_by` | enum | `dispatch-finalize` \| `hook` \| `ci` \| `manual` — from `METRICS_INVOKED_BY`, default `manual` |
| `forced` | boolean | optional; present (`true`) when the dispatcher's finalize preflight ran under `--force` |
| `draft_exempt` | boolean | optional; present (`true`) when a red gate was overridden because the PR is a draft |

The dispatcher passes `METRICS_GATE_RECORD_ID` so the gate's record id is known
in advance and can be cited by `pr.opened.gate_record_id`, and
`METRICS_GATE_OVERRIDE=forced|draft-exempt` to set the two optional flags.

### `pr.opened` / `pr.refreshed` — `source: dispatch` (AC-5)

At Developer / one-shot (`bkf`, `mnt`) finalize; `refreshed` when the PR already existed.

| Field | Type | Nullable | Meaning |
|---|---|---|---|
| `pr_number` | integer | yes | |
| `pr_url` | string | yes | URL of the project's own PR |
| `draft` | boolean | no | |
| `head_sha` | string | yes | |
| `commits_ahead` | integer | yes | commits on the branch that `main` lacks |
| `files_touched` | integer | no | count of paths in `git diff --name-only main...branch` |
| `files_touched_paths` | list of string | no | those repo-relative paths |
| `tests_changed` | integer | no | count of those paths under `tests/` |
| `covers_delta` | integer | no | added minus removed `@covers FR-XXXX:AC-N` lines under `tests/` in that diff |
| `gate_record_id` | string | yes | `record_id` of the finalize-preflight `gate.run`; `null` when no preflight gate ran |

### `pr.review` — `source: dispatch`, `role: rev` (AC-5)

| Field | Type | Meaning |
|---|---|---|
| `parent_pr_number` | integer | the Developer PR reviewed |
| `verdict` | string | `approve` \| `request-changes` \| `comment` |
| `posted_as` | string | how `gh pr review` accepted it (`comment (intended approve)` on the own-PR fallback) |
| `round` | integer | |

### `pr.merged` — `source: dispatch` (AC-5)

Emitted when `reconcile_merged_prs --apply` flips an FR to `merged`.

| Field | Type | Meaning |
|---|---|---|
| `pr_number` | integer | |
| `merge_sha` | string | |

### `gate.decision` — `source: dispatch` (FR-0008 AC-11)

One per declared-gate (`gates:` frontmatter, FR-0008 AC-1) verdict. Distinct
from `gate.run` above (a deploy-gate invocation): this records a human's or
an Architect gate-review session's verdict on one named gate, or a merge that
bypassed one. `object_ids` = the FR the gate is declared on. Emitted by
`dispatch.py gate pass|block` (`role: null` — a human-invoked CLI, not a
dispatched role), by `finalize --role gat` (`role: architect`), and by
`reconcile-merged` when a PR merged past an unsatisfied gate (`role` = the
implementation role that merged; `verdict: bypassed`).

`role` here is the *session* role that recorded the verdict, and the three
emitters disagree by design of their contexts — that is documented above,
not a defect to fix. Gate-throughput and turnaround queries should group by
`verdict` / `reviewer` / `by`, never by `role`.

| Field | Type | Nullable | Meaning |
|---|---|---|---|
| `gate` | string | no | the gate's `id` (FR-0008 AC-1) |
| `after` | enum | no | `dev` \| `rev` — which phase the gate follows |
| `reviewer` | enum | no | `human` \| `architect` — who judges it |
| `verdict` | enum | no | `pass` \| `changes-requested` \| `bypassed` |
| `by` | string | no | free text: a name, `architect`, or `reconcile-merged` |
| `round` | integer | no | the evidence file's `round` (>= 1) |
| `head_sha` | string | yes | the Developer branch tip the verdict was given against; `null` only if the evidence carried none |

### `escalation` / `escalation.resolved` — `source: escalation-log` (AC-6)

`escalation-log.py append` still writes its Markdown row (the human-readable
projection `agent-status.py` reads) and additionally emits `escalation`;
`resolve` emits `escalation.resolved` with the same identifiers. Neither
carries the summary or resolution text. The dispatcher does **not** emit an
escalation record for an agent's `## ESCALATION` block — `dispatch.run`
already carries `status: escalation`.

| Field | Type | Meaning |
|---|---|---|
| `trigger_class` | string | the escalation-matrix decision-tree row, kebab-case (`spec-is-ambiguous`, `code-doesnt-satisfy-ac`, `ac-has-no-test`, `test-reveals-spec-gap`, `code-outside-fr-scope`, `two-acs-contradict`, `fr-contradicts-user-intent`, `cross-fr-conflict`, `security-privacy-legal-concern`, `dev-reviewer-loop-hits-3-cycles`, `architect-is-being-asked-to-override-an-existing-adr`), or `other` |

## Reserved fields (AC-2)

All nullable and optional; **back-filled by H1-H5 / WS1-WS4; no emitter
populates them in this FR**. A record carrying any subset validates and
round-trips through append and query byte-for-byte.

| Field | Type | Back-filled by |
|---|---|---|
| `dec_id` | string (`DEC-nnnn`) | FR-0004 / WS1 |
| `tr_id` | string (`TR-nnnn`) | FR-0004 / WS1 |
| `tier` | string | WS2 (IDEA-0055) |
| `ratification_outcome` | `ratified` \| `rejected` \| null | WS2 |
| `revision_event` | `revision` \| `supersession` \| null | FR-0003 / ADR-0001 |
| `breaking_declared` | boolean \| null | FR-0004 |
| `breaking_observed` | boolean \| null | WS4 honesty check (IDEA-0056) |
| `dec_proposed_at` | ISO-8601 string \| null | WS2 |
| `dec_ratified_at` | ISO-8601 string \| null | WS2 |
| `slice_id` | string \| null | H1 (IDEA-0053) |

## Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `METRICS_LOG_DISABLED=1` | all emitters | no records written |
| `METRICS_PROJECT` | all emitters | overrides `project` |
| `DISPATCH_RUN_ID` | gate, `emit` CLI | `run_id` for the record; set by the dispatcher in every spawned agent's environment |
| `METRICS_INVOKED_BY` | gate | `invoked_by` (`dispatch-finalize` \| `hook` \| `ci` \| `manual`) |
| `METRICS_GATE_RECORD_ID` | gate | pre-assigned `record_id` (set by the dispatcher's finalize preflight) |
| `METRICS_GATE_OVERRIDE` | gate | `forced` or `draft-exempt` → the optional flags above |

## Fixture

`tests/fixtures/metrics/2026-08.ndjson` is the synthetic one-lifecycle log the
baseline reports are specified against (AC-11). It uses the fictitious
`synthetic-project`, `FR-0020`, PR #42, placeholder SHAs and hex run ids — no
real identifiers. H7 (IDEA-0057) dashboards should build against it.

## Out of scope here

Dashboards beyond the two baseline reports (IDEA-0057), cross-project roll-up
in the hub, retention/rotation of month files, and the DEC/TR/tier objects
whose fields are only reserved above.
