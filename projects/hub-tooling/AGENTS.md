# CLAUDE.md — Project Working Agreement

This file is read by every agent at the start of every session. Keep it short. Anything project-specific that doesn't fit here belongs in a spec file under `specs/`.

> **⚠️ TEMPLATE — NOT YET CONFIGURED.** The sections below contain `<<REPLACE: …>>` markers. If you are an agent reading this and you see any of those markers, the project has not been bootstrapped yet. **Stop work** and ask the human to run `python scripts/bootstrap.py <project-name>` (from the hub root) or to fill the markers in by hand. Do not invent project context to fill the gaps. Once every marker is gone, delete this warning block.

## What you are working on

Spec-graph home for cos-agent-hub template and hub-script enhancements


## Hub-tooling specifics (read before acting in any role)

This project is bootstrapped from the template it changes, and it sits inside the hub repo rather than being its own repo. Four consequences:

1. **Edit the hub's copy, never this project's local copy.** The code under change is `../../template/**` and `../../scripts/**`. This project's own `scripts/`, `.agent-team/`, `.claude/`, and `tests/unit/scripts/` are bootstrap *output* and will be overwritten by the next `bootstrap.py --upgrade`. A fix applied there is lost. `src/` stays empty.
2. **Tests for template scripts live in `../../template/tests/`** (they ride along into every bootstrapped project). Tests for hub scripts (`../../scripts/`) live at `../../tests/` (create it if absent). `@covers FR-XXXX:AC-N` annotations still apply; the local gate cannot see them yet (IDEA-0061), so the Reviewer states coverage per AC in the PR body.
3. **Reviewer dogfood step is mandatory.** Before approving, bootstrap a throwaway project from the modified template into a temp directory (`python ../../scripts/bootstrap.py <name> "<desc>" --stack python --no-register`, targeting a temp path), run its `scripts/index-specs.py --validate` and `scripts/deploy-gate.py`, and for FRs touching `bootstrap.py` also exercise `--upgrade` against a fixture. Delete the throwaway afterwards.
4. **Footprints are documentation.** `owns:`/`reads:` use hub-relative paths under `template/` or `scripts/`. The footprint checker cannot resolve them from this directory, so the four-way overlap on `template/scripts/index-specs.py` (FR-0002/0003/0004/0005) is sequenced by the Chief of Staff, not detected by tooling. Implementation order: FR-0003, FR-0004, FR-0005, FR-0002; FR-0001 is independent.

`dispatch.py` supports this project since FR-0024 (PR #32, from IDEA-0061). It creates a whole-repository worktree, starts agents in `projects/hub-tooling/` inside it, and turns the hub-relative `owns:` (via `.agent-team/layout.yaml`'s `footprint_root: repo`) into absolute Claude Code grants. So far that is verified by a dry-run `wave` in a hub clone (FR-0024 r1, AC-7), not by a live wave. Until one has run cleanly, the Chief of Staff may keep dispatching roles by hand, one git worktree per FR. Claude Code is the only supported harness: Cursor's relative grants cannot reach repository paths (FR-0024, Out of scope).

## Your role

Before doing anything, identify which role you are operating in:

- **Architect** — see `.agent-team/roles/architect.md`
- **Developer** — see `.agent-team/roles/developer.md`
- **Reviewer** — see `.agent-team/roles/reviewer.md`

If the user has not told you which role, ask. Do not default — role determines what you are allowed to write to.

## Data hygiene

If this project was bootstrapped with a compliance profile (e.g., `--profile phipa`), additional data hygiene rules and automated hooks are active. Check `.agent-team/hooks/` and `.claude/settings.json` for any profile-specific enforcement.

Regardless of profile, every role follows these baseline rules:

- **Use synthetic data in test fixtures.** Generated, not derived from real records. Fixtures live in `tests/fixtures/`.
- **Escalations cite IDs, not details.** "FR-0007:AC-2 ambiguous on retention behavior" — not specifics about real users or records.
- **If you encounter sensitive data in a file you're asked to edit**, stop, do not commit, flag to the human supervisor.

## Universal rules (all roles)

1. **Spec graph is the source of truth.** Every change traces to a Functional Requirement (FR) and one or more Acceptance Criteria (AC). No code changes without an FR.

2. **Stable IDs only.** FRs are `FR-XXXX` (4-digit, never reused). ACs are `AC-Y` (1-indexed within an FR). Tests reference them via `@covers FR-XXXX:AC-Y` comments.

3. **Artifacts, not chat.** When handing off to another role, write the handoff to a file (PR description, spec update, review comment). Never assume the next agent sees your conversation context.

4. **Escalate, don't guess.** If the spec is ambiguous, escalate to Architect rather than picking an interpretation. See `.agent-team/escalation-matrix.md`.

5. **Iteration budget: 3 cycles.** If a Dev↔Reviewer loop hits 3 round-trips on the same FR, force-escalate to human. The spec is probably wrong.

6. **Run the gate before claiming done.** `python scripts/deploy-gate.py` must pass before any role declares work complete.

## Project conventions

- Language: Python 3.11+, type hints required
- Test runner: `pytest`
- Lint/format: `ruff check .` and `ruff format --check .`
- Commit style: Conventional Commits, scope = FR ID (e.g., `feat(FR-0013): add canonical visit mapper`)
- PRs must reference all FR IDs they touch in the title


## Glossary

- **Hub** — the `cos-agent-hub` repo two levels up (`../../`). This project is *inside* the hub and its FRs describe changes to the hub's own files.
- **Template** — `../../template/`: the scaffold every project is bootstrapped from (roles, hooks, `scripts/index-specs.py`, `scripts/deploy-gate.py`, `scripts/dispatch.py`, `scripts/render-docs.py`, spec templates). Changes here reach projects via `--upgrade`.
- **Hub scripts** — `../../scripts/{bootstrap.py,hub-index.py,parking.py,patterns.py}`: hub-level tooling, human-approval-only per the hub `CLAUDE.md`. Assume serial execution.
- **`--upgrade`** — `bootstrap.py --upgrade <project>`: syncs `INFRA_DIRS` + `INFRA_ROOT_FILES` from the template into a project. Whole-file overwrite except seed-only files (`.claude/settings.json`, `pytest.ini`: drift-warn only) and the managed `.gitattributes` block (FR-0020).
- **Profile** — `../../profiles/<name>/` (currently `phipa`): opt-in overlay applied at bootstrap (hook, settings overlay, AGENTS.md hygiene block). Recorded in the project's `.agent-team/profiles.yaml`, which `--upgrade` reads (FR-0001).
- **FR / AC** — Functional Requirement and its Acceptance Criteria; the existing spec objects. Per-AC ratification state (`ac_state`) and drift lint already exist in the template indexer.
- **DEC** — Decision object (`DEC-nnnn`): a tiered, ADR-authorised choice that revises an FR/TR; carries `breaking`, `tier`, `status`. Modelled by FR-0004 (`specs/decisions/`, template in `specs/_template/`).
- **TR** — Technical Requirement (`TR-nnnn`): agent-authored operationalisation of an FR; a bundle of DECs plus `implemented_by`. Modelled by FR-0004.
- **ADR** — Architecture Decision Record, with mandatory "When you may deviate" / "What you must record when you deviate" sections (FR-0003).
- **Imported records** — FR-0001..0025, ADR-0001 and DEC-0001..0026 came from a separate hub snapshot on 2026-10-26; the IDs are reserved and new work starts at FR-0026, DEC-0027, ADR-0003. See ADR-0002 for the framing and for H/WS item codes.
- **Supersession vs revision** — new ID with `supersedes`/`superseded_by` links vs. in-place `version` bump with the DEC appended to `revisions`; `last_breaking_revision` marks the newest `breaking: true` DEC.
- **Compiled slice** — the subgraph an agent is dispatched with instead of the spec tree (parked as IDEA-0053).
- **FINDINGS channel** — the non-blocking `## FINDINGS` block `dispatch.py` already parses; home for slice-miss and instrumentation reports.
- **Fan-out / reverse leg** — template → projects via `--upgrade`; project → template is IDEA-0034 (parked).

## Grounding documents

- **Framing for the FRs** — `specs/decisions/ADR-0002-imported-spec-graph-and-proposal-framing.md` summarises the two proposals these FRs cite: the hub capabilities proposal (H1–H13, waves A–F) and the decision-rights proposal (WS0–WS6, with the DEC/TR/FR/ADR schemas in WS1). The proposals themselves are not in this hub.
- **Parked backlog** — `../../parking-lot/IDEA-0053..0060` (waves B–E), `IDEA-0034` (reverse leg + AGENTS.md core/overlay split), `IDEA-0016` (metrics field list for H6).
- **Hub working agreement** — `../../CLAUDE.md` and `../../CONTRIBUTING.md` (what needs human approval; profile layout).
- **Template as-is** — `../../template/` and `../../scripts/bootstrap.py` are the code under change; read them before drafting, do not copy them into `src/`.

## Files you should never edit without explicit human approval

- `.agent-team/**` — role definitions, escalation rules, and hooks
- `.claude/settings.json` — hook wiring (spec validation, deploy-gate report)
- `scripts/deploy-gate.py` — the merge gate
- `scripts/index-specs.py` — the spec indexer
- This file (`AGENTS.md` / `CLAUDE.md`)

If a task seems to require editing these, escalate first.
