---
id: FR-0002
title: Pipeline instrumentation — append-only per-project metrics log (H6)
status: merged
owner: architect
depends_on: []
tags: [observability, template, dispatch, metrics]
# Footprint is expressed as HUB-relative paths under template/ (see Notes):
# the code under change lives in the hub's template, not in this project's src/.
owns:
  - template/scripts/metrics_log.py
  - template/scripts/dispatch.py
  - template/scripts/deploy-gate.py
  - template/scripts/escalation-log.py
  - template/scripts/index-specs.py
  - template/specs/_metrics/**
  - template/.gitattributes
  - template/tests/fixtures/metrics/**
reads:
  - template/scripts/spec_footprint.py
  - template/scripts/agent-status.py
  - template/.agent-team/observability.md
  - template/.agent-team/escalation-matrix.md
  - template/.agent-team/hooks/phi_regex_check.py
  - template/.claude/settings.json
  - template/.gitignore
  - scripts/bootstrap.py
derived_from: IDEA-0016
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0021]
last_breaking_revision: 2
created: 2026-09-07
updated: 2026-09-25
---

# FR-0002: Pipeline instrumentation — append-only per-project metrics log (H6)

## Why

IDEA-0016 measured agent effectiveness by hand-mining 7 parent sessions and 13 subagent transcripts, and the headline finding was that the measurement itself was the hard part: raw JSONL transcripts were the only data source, with no outcome annotations, no session metadata (tool calls, elapsed time, retries) and no aggregation layer. The numbers it did extract are the ones worth keeping: roughly 20-30% of tool calls wasted on shell/permission trial-and-error (15-20 calls in the worst case), a Developer session at ~75 tool calls and a full FR lifecycle at ~150, three commit-push-CI-fail cycles for one Python-version mismatch, one silently stalled subagent, and 0 of 7 sessions writing to the escalation log. Every one of those signals already passes through code we control: `dispatch.py` knows the role, FR, harness, outcome class, per-tool call counts, tool errors, rework rounds and reviewer verdicts; `deploy-gate.py` knows whether it passed and which check failed; finalize knows the PR number, the diff and how many test files changed. Today that knowledge is printed to a console or written to `_dispatch/`, which is gitignored and overwritten per FR/role, so the history is lost the moment the next wave runs. H6's framing is the sharpening: these signals should be *emitted at the source* as structured records, not *inferred from transcripts afterwards* by a 300-500 line parser per harness that still cannot see gate outcomes. One `append()` per event replaces the parser, and the resulting log is what H7 dashboards (IDEA-0057) and the H9 review agent read instead of the repo.

Compounding value, in rough numbers: IDEA-0016 estimated 2-3 actionable template improvements per monthly analysis cycle. With records emitted at the source the analysis cost drops from "a day of transcript mining" to "run a named query", so the same cadence costs ~zero marginal effort, and the two hand-measured baselines (tool calls per FR, retries) become regression tests on the pipeline itself rather than one-off observations.

## What

After this FR lands, every bootstrapped project has a per-project, append-only NDJSON metrics log under `specs/_metrics/`, written through one shared emitter/reader module `scripts/metrics_log.py` that also provides a filter/aggregate query CLI and named reports. `dispatch.py` emits a record at agent spawn, at agent-outcome evaluation, at PR open/review/merge and at wave synthesis; `deploy-gate.py` emits one record per run with a machine-readable outcome and failure class; `escalation-log.py` emits one record per escalation appended or resolved. Agents can flag context-slice misses with a `[slice-miss]` tag in the existing `## FINDINGS` block and the dispatcher records them structurally. The spec indexer renders a per-FR metrics summary alongside the spec index. Records never contain transcript text or PHI, emission never changes the behaviour or exit code of the emitting command, and fields that depend on objects that do not exist yet (DEC, TR, tiers, supersession, slices) are reserved as optional so H1-H5 / WS1-WS4 can back-fill them without a schema break.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Record envelope and minimum field set.** Every record is a single JSON object on a single line carrying, at minimum: `schema_version` (integer, initially `1`), `record_id` (unique per record), `ts` (UTC ISO-8601), `project` (string), `kind` (one of the kinds enumerated in AC-3 to AC-7), `source` (`dispatch` | `gate` | `escalation-log` | `manual`), `role` (`architect` | `dev` | `rev` | `bkf` | `mnt` | `docs` | `orchestrator` | `null`), `object_ids` (list of spec-object IDs the record is about; `FR-XXXX` today, `TR-`/`DEC-` later), and `run_id` (nullable; identical across every record produced by one agent invocation, so spawn, run, gate and PR records can be joined). `metrics_log.validate(record)` rejects a record missing any envelope field, with an unknown `kind` or `source`, or missing a kind-specific required field named in AC-3 to AC-7, and accepts a record carrying fields the schema does not know (forward compatibility).

- **AC-2:** **Reserved optional fields for objects that do not exist yet.** The schema reserves, as nullable and optional, `dec_id`, `tr_id`, `tier`, `ratification_outcome` (`ratified` | `rejected` | `null`), `revision_event` (`revision` | `supersession` | `null`), `breaking_declared` (bool | null), `breaking_observed` (bool | null; the WS4 honesty-check result), `dec_proposed_at`, `dec_ratified_at` and `slice_id`. A record carrying any subset of them validates, round-trips through append and query byte-for-byte, and a record carrying none of them validates. The schema document (AC-14) marks each as "back-filled by H1-H5 / WS1-WS4; no emitter populates it in this FR".

- **AC-3:** **Dispatch emits spawn, run and wave records.** With `--apply`, `dispatch.py` appends (a) one `dispatch.spawn` record when `spawn_role` returns `spawned`, carrying `harness`, `worktree_status`, `base_branch`, `model` (nullable) and `round`; (b) one `dispatch.run` record when an agent outcome is evaluated (tick/wave/rework paths alike), carrying `status` (`success` | `error` | `escalation` | `timeout` | `no-log`), `tool_calls_total`, `tool_calls_by_tool` (name -> count), `tool_errors_total`, `tool_errors_by_tool`, `tokens_in` and `tokens_out` (populated from the harness result line when it carries usage — the Claude Code NDJSON `result` object does; `null` when the harness log has no usage, never estimated), `duration_s` (from lock `started_at` to evaluation), `round`, `verdict` (rev only) and `findings` (list per AC-7); and (c) one `dispatch.wave` record at synthesis, carrying FR count, completed, dev-only and dropped counts, `drop_reasons` (list of `{fr_id, phase}`), `rounds_ran` per FR and the force-escalated FR list. Dry-run (`apply=False`) emits nothing. Verified with a fake harness adapter over a synthetic NDJSON log fixture: the log contains exactly the expected records with every listed field populated from the fixture.

- **AC-4:** **Every gate run emits a classified outcome.** Each `deploy-gate.py` invocation, except `--status-only` (a read-only reporting surface by contract; it must not dirty the tree), appends one `gate.run` record carrying `stage`, `outcome` (`pass` | `fail` | `error`), `failure_classes` (list drawn from a fixed enum: `spec-validation`, `covers-unknown-fr`, `covers-malformed-ac`, `covers-unknown-ac`, `coverage-missing`, `script-error`), `warning_classes` (`implements-missing`, `implements-unknown-fr`, `ac-format`), `counts` (`frs`, `covers`, `implements`), `invoked_by` (`dispatch-finalize` | `hook` | `ci` | `manual`; taken from an environment variable the dispatcher sets, defaulting to `manual`), and `object_ids` = the FR IDs named in failures. When the dispatcher's finalize preflight overrides a red gate, the record additionally carries `forced: true` or `draft_exempt: true`. The gate's exit code, stdout and stderr are byte-identical to today for every branch. Verified by driving each failure branch from a synthetic specs/tests fixture and asserting the class list.

- **AC-5:** **PR events are recorded with change-size fields.** At Developer / one-shot finalize the dispatcher appends `pr.opened` (or `pr.refreshed` when the PR already existed) carrying `pr_number`, `pr_url`, `draft`, `head_sha`, `commits_ahead`, `files_touched` (count and list of repo-relative paths in the branch diff against its base), `tests_changed` (count of those paths under `tests/`), `covers_delta` (net change in `@covers` annotation count against the base) and `gate_record_id` (the `record_id` of the preflight `gate.run`). At Reviewer finalize it appends `pr.review` carrying `parent_pr_number`, `verdict`, `posted_as` and `round`. When `reconcile_merged_prs` flips an FR to merged it appends `pr.merged` carrying `pr_number` and `merge_sha`. Verified with `gh`/`git` subprocess stubs; no network.

- **AC-6:** **Escalations are recorded without duplicating the human log.** `escalation-log.py append` still writes its Markdown row and additionally appends an `escalation` record carrying `role`, `object_ids` and `trigger_class` (the matrix row, normalised to kebab-case, or `other`); `escalation-log.py resolve` appends `escalation.resolved` carrying the same identifiers. `.agent-team/escalation-log.md` remains the human-readable projection that `agent-status.py` reads; the dispatcher does not emit a separate `escalation` record for an agent's `## ESCALATION` block because the `dispatch.run` record already carries `status: escalation`. Neither record carries the escalation summary text.

- **AC-7:** **Slice-miss FINDINGS tag.** The `## FINDINGS` line parser accepts `[slice-miss]` alongside `scope`, `spec` and `doc`. For every finding, the `dispatch.run` record's `findings` list carries `{tag, refs, chars}` where `refs` is the list of spec-object IDs (`FR-`/`TR-`/`DEC-`/`ADR-`/`GOAL-` patterns) and repo-relative paths found in the finding text, and `chars` is its length; the finding text itself is not stored (it continues to reach the wave synthesis and `--park-findings` exactly as today). Given a final message containing `- [slice-miss] needed specs/FR-0009-extraction-agent.md to satisfy AC-3`, the record carries a finding with `tag: slice-miss`, `refs` containing `specs/FR-0009-extraction-agent.md` and `FR-0009`, and no other text.

- **AC-8:** **Append-only semantics and location.** Records are written to `specs/_metrics/<YYYY-MM>.ndjson` (UTC month of `ts`), directory and file created on first write, opened in append mode, one record per line, flushed per record. The module exposes append and read only — no update, delete or rewrite — and the CLI has no mutating subcommand other than `emit`. `template/.gitattributes` declares `specs/_metrics/*.ndjson merge=union` so concurrent appends on different branches merge without conflict. **Revised by DEC-0021 (v2, breaking):** GitHub applies no merge drivers, so role branches must not carry rows at all. A dispatched agent's gate and escalation-log records go to the primary checkout's log (`DISPATCH_METRICS_DIR`, honoured only from inside the dispatched worktree), and rows are committed from `main` only. `merge=union` stays for local merges. Implemented by FR-0018. Given two writers appending concurrently to the same file, every line still parses as a complete record, and the file's bytes before the second write are a prefix of its bytes after.

- **AC-9:** **Emission is never load-bearing.** Any failure inside the emitter (unwritable directory, invalid record, disk error) is caught, reported as exactly one `WARN: metrics:` line on stderr, and leaves the calling command's exit code and stdout unchanged. Setting `METRICS_LOG_DISABLED=1` suppresses all emission (so the existing test suites of `dispatch.py`, `deploy-gate.py` and `index-specs.py` remain byte-identical in behaviour). Given a read-only `specs/_metrics/`, `deploy-gate.py` exits with the same code and stdout it produced before this FR.

- **AC-10:** **Query surface simple enough that a dashboard is a query.** `python scripts/metrics_log.py query` accepts `--kind` (repeatable), `--fr`, `--role`, `--since`, `--until` and streams matching records as NDJSON (default) or a table (`--table`); `--group-by <field>` with `--agg count|sum:<field>|avg:<field>|max:<field>` returns aggregates; `report <name>` executes a named report defined as a data file (a dict of the same filters and aggregations, under `specs/_metrics/reports/`) so adding a dashboard means adding a file, not code. Queries read every month file, tolerate records with unknown `kind` or extra fields, and exit 0 with empty output when no log exists.

- **AC-11:** **Baseline reports reproduce IDEA-0016's hand measurements.** Two reports ship: `tool-calls-per-fr` (sum of `tool_calls_total` per FR, broken down by role, plus the lifecycle total) and `retries-per-fr` (per FR: rework rounds beyond the first, `tool_errors_total`, and `gate.run` failures with their classes). Against the shipped synthetic fixture modelling one FR lifecycle after IDEA-0016's FR-0020 case (Architect, Developer at ~75 tool calls, Reviewer, one rework round, three failed gate runs), both reports return exactly the fixture's numbers.

- **AC-12:** **Indexed alongside the spec graph.** When `specs/_metrics/` contains records, `index-specs.py` renders a `## Pipeline metrics` section at the end of `specs/INDEX.md` with one row per FR that has records: latest `dispatch.run` status per role, total tool calls, retries (as defined in AC-11), last gate outcome and last PR number. When no records exist the generated `INDEX.md` is byte-identical to today's output. `--validate` and `--ac-hashes` do not read the log.

- **AC-13:** **No transcript text or PHI in records.** No record field carries agent prose, transcript excerpts, PR or review bodies, commit messages, tool error messages or file contents; permitted value types are identifiers, enumerations, counts, durations, timestamps, repo-relative paths, PR numbers, SHAs, URLs of the project's own PRs, and booleans. `validate()` rejects any string value longer than 200 characters and any string-bearing field not on the schema's allow-list. When `.agent-team/hooks/phi_regex_check.py` exists in the project (compliance profile active), the emitter runs every string value through its patterns and drops the whole record with a `WARN: metrics:` line on a match. Given a record with a 500-character string, validation fails; given a record matching a synthetic PHI pattern under an active profile, nothing is appended.

- **AC-14:** **Schema is documented and a reusable fixture ships.** `specs/_metrics/README.md` in the template documents every envelope, kind-specific and reserved field with type, nullability, emitting source and the AC that introduced it, plus the `[slice-miss]` convention and the two baseline reports. `tests/fixtures/metrics/` ships the synthetic one-lifecycle NDJSON fixture used by AC-11 with no real identifiers, so H7 (IDEA-0057) can build dashboards against it.

## Out of scope

- The `dashboards/` folder, the H7 dashboard set and their paired quality counter-metrics beyond the two baseline reports in AC-11 — IDEA-0057.
- The H8 projection library (per-role guides, release notes, roadmap) — IDEA-0057.
- Modelling DEC, TR, tiers, ratification, supersession/revision or the `breaking` honesty check — decision-rights WS1/WS2/WS4. This FR only reserves their fields (AC-2).
- Compiled context slices themselves — IDEA-0053 / H1. This FR defines only how a miss is recorded (AC-7).
- The transcript-parsing analysis tool originally described in IDEA-0016; it is replaced by emission at the source and must not be built.
- Changing the format of `.agent-team/escalation-log.md` or the output of `agent-status.py` (IDEA-0018, promoted as ai-hub-poc/FR-0022).
- Cross-project aggregation in the hub (`hub-index.py` or a hub-level metrics roll-up). Hub scripts are human-approval-only; a follow-on FR.
- The GitHub `agent:*` label state machine in `observability.md`.
- Retention, rotation, compaction or archiving of month files.
- Any change to the exit codes, stdout or control flow of `dispatch.py` or `deploy-gate.py` other than the additive emission calls.
- Emission from `bootstrap.py`, `render-docs.py` or hub scripts.
- Changes to `scripts/bootstrap.py --upgrade` sync lists (see Open questions Q2).

## Open questions

If unresolved, propose a default. The default is what gets implemented if the FR ships without further clarification.

- **Q1: Is the log committed, or local-only like `_dispatch/`?**
  - **Default:** committed, under `specs/_metrics/<YYYY-MM>.ndjson`, with the `merge=union` attribute (AC-8). Rationale: H7 says generators run at gate time and H9 reads dashboards from CI or another machine; a gitignored log is invisible to both. The `--status-only` Stop-hook path never writes (AC-4) so observation cannot dirty the tree. The alternative — `_dispatch/metrics/` local-only — is a one-line path change if Neil prefers it; the PHI guard (AC-13) exists precisely so the committed default is safe.
  - **Decided 2026-09-07 (Neil):** committed monthly NDJSON log under `specs/_metrics/`, as defaulted.
- **Q2: How does `template/.gitattributes` reach existing projects?** `INFRA_ROOT_FILES` in `scripts/bootstrap.py` lists only `pytest.ini`, and that script is human-approval-only.
  - **Default:** ship the file in the template for new projects; existing projects add it by hand when they first run this FR's code; adding it to `INFRA_ROOT_FILES` is a one-line follow-on for Neil. Not blocking.
- **Q3: Where does `project` come from?**
  - **Default:** the repository root directory name, overridable with `METRICS_PROJECT=<name>`; the hub registry can rewrite it during cross-project roll-up later.
- **Q4: Do gate runs inside agent worktrees emit?** A Developer running `deploy-gate.py` before claiming done writes to the worktree's copy of the log, which lands on the FR branch.
  - **Default:** yes — those are exactly the retry signal IDEA-0016 measured. They carry the `run_id` from `DISPATCH_RUN_ID`, which the dispatcher sets in the spawned agent's environment, and merge via `union`. **Reversed by DEC-0021 (v2):** those records still carry `DISPATCH_RUN_ID`, but they are appended to the primary checkout's log rather than the worktree's, so they never land on the FR branch.
- **Q5: Should `dispatch.run` record per-tool error clusters (IDEA-0016's "shell/permission" pattern)?**
  - **Default:** counts only (`tool_errors_by_tool`), no error messages; classifying error text is a later report over the records, and storing messages would violate AC-13.
- **Q6: Where do this project's `@covers` tests live?** This project's gate scans `projects/hub-tooling/tests/`, but the code under change is `template/scripts/*`. FR-0001 and FR-0003 face the same question.
  - **Default:** the Reviewer writes the tests under `template/tests/unit/scripts/` so they ship with the template, and adds a thin `projects/hub-tooling/tests/unit/scripts/test_fr0002_metrics_log.py` that imports the template module by hub-relative path and carries the `@covers FR-0002:AC-N` annotations. Candidate for this project's first ADR; flagged to the Chief of Staff.

## Dependencies

None. This FR is wave A in the proposal: "can start now and back-fill fields as H1-H5 land". Consumers: IDEA-0057 (H7/H8), IDEA-0059 (H9 review agent).

## Notes

- **Footprint paths are hub-relative.** `owns:`/`reads:` above are relative to the hub root (`template/...`, `scripts/bootstrap.py`), not to this project, because the code under change is the template. `spec_footprint` rejects `..` segments, so hub-relative is the only expressible form; consequently the indexer's overlap detection (matched against this project's `git ls-files`) will not fire against FR-0001/FR-0003 — cross-check shared files by hand.
- **Human approval needed before implementation, not before this spec.** `template/scripts/dispatch.py` and `template/scripts/deploy-gate.py` are on the hub `CLAUDE.md` approval-only list; so are `template/.claude/commands/**` (the FINDINGS block description agents read) and `template/.agent-team/observability.md`. The normative schema documentation therefore lives in `specs/_metrics/README.md` (AC-14), so the approval-only edits reduce to one-line pointers ("metrics log: see specs/_metrics/README.md"; "`[slice-miss]` tag accepted"). Neil should approve the dispatch/gate edits before `/developer FR-0002` is dispatched.
- **Integration with existing observability, not duplication.** `observability.md` stays the human-facing convention (labels, FR status, escalation log); `agent-status.py` keeps reading the Markdown escalation log; `_dispatch/*.pr.json` and `*.lock` stay as the dispatcher's working state. The metrics log is the durable, machine-facing record; AC-6 makes the escalation helper write both.
- **Related parked work.** IDEA-0057 (H7 dashboards + H8 projections) is the consumer of this log; IDEA-0053 (H1 compiled slices) is the producer of `[slice-miss]` findings; IDEA-0018 (escalation-log automation) was promoted earlier as ai-hub-poc/FR-0022 and is why AC-6 reuses `escalation-log.py` rather than inventing a second path; IDEA-0014 (review strain metrics) is a likely later report.
- **Grounding observations from the template code** the Developer should know: `AgentLogSummary` today captures `tool_counts`, `error_objs`, `last_text` and `result_subtype` but drops the harness `usage` block, hence AC-3's token fields; `_FINDING_LINE` silently treats an unknown tag as untagged text, hence AC-7; the `dispatch.run` duration can be derived from the lock's `started_at`; `_run_deploy_gate` returns only `(ok, text)`, so AC-4's classes must come from the gate's own emission or a structured return, not from parsing stdout; `deploy-gate.py` exits 2 on script error (`script-error` class). There are currently no unit tests for `dispatch.py` at all, so the fake-adapter harness in AC-3 is new test infrastructure.
- **Tests are synthetic.** All fixture logs and PR/gate stubs use synthetic FR IDs and paths; no real transcripts are checked in (hub `CLAUDE.md` rule 7).

## Changelog

- 2026-09-07: created (derived from IDEA-0016; source proposal H6 in `projects/project_a/.agent-team/docs/cos-agent-hub-changes.md`)
- 2026-09-07: recorded Neil's confirmation of Q1 (committed log)
- 2026-09-07 — merged to main via fr/FR-0002 (feat c26ad16, fix 363dd8c, tests bfaae79 + 35ba03b); Reviewer APPROVE round 2. Status ready -> merged (CoS bookkeeping). Follow-ups for Neil: .gitattributes not in INFRA_ROOT_FILES and specs/ in UPGRADE_EXCLUDE (existing projects miss merge=union and _metrics README/reports on --upgrade); _finalize_gate_preflight is dead code so gate_record_id is always null on the live path.
- 2026-09-25: v2 — DEC-0021 (breaking: true): an agent's in-worktree gate and escalation-log records go to the primary checkout's log, so role branches carry no metrics rows (Q4 reversed; the AC-8 union rationale corrected for GitHub). Wave-2 plan §9.4 option (a), `neil` tier, proposed. Implemented by FR-0018.
