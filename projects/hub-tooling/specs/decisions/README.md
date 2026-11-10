# Decisions: ADRs and DECs

This directory holds two kinds of decision object, told apart by filename prefix:

- **ADRs (`ADR-NNNN-<slug>.md`) — principles.** Cross-FR architectural rules that tell an agent which way to do X here, and — via two mandatory sections — when the rule may bend and what must be recorded when it does.
- **DECs (`DEC-NNNN-<slug>.md`) — choices made under a principle.** One concrete choice, made at a declared authority `tier`, citing the ADR(s) that authorise it (`authorised_by`) and, when it changes an existing FR or TR, `revises: <ID>` with an honest `breaking` flag. Copy `../_template/DEC-XXXX-template.md` to start one; see "Decisions (DEC)" below.

## Architectural Decision Records (ADRs)

Cross-FR architectural choices live here as ADRs. An ADR is appropriate when a decision applies across multiple FRs and a Developer or Reviewer would otherwise have no canonical answer to "which way do we do X here?".

## When to write an ADR

- Choosing between two technologies that affect more than one FR (e.g., Postgres vs SQLite, REST vs gRPC)
- Establishing a convention that crosses FRs (error handling style, logging format, auth model)
- Recording a trade-off the team will need to remember six months from now

## When NOT to write an ADR

- Decisions scoped to a single FR — put them in the FR's Notes section instead
- Style preferences with no real cost either way — pick one and document in `CLAUDE.md`

## ADR file format

`ADR-NNNN-<short-slug>.md`, sequentially numbered, never reused. Copy `../_template/ADR-XXXX-template.md` to start one. Frontmatter: `id`, `title`, `status` (`proposed | accepted | superseded | rejected | deprecated`), `owner`, `supersedes`, `superseded_by`, `created`, `updated`. Body sections, in order: Context, Decision, When you may deviate, What you must record when you deviate, Consequences, Alternatives considered, Changelog.

The indexer (`scripts/index-specs.py`) discovers every `ADR-*.md` here, lists it under `## Architecture decision records` in `specs/INDEX.md`, and reports structural problems (missing frontmatter, `id` not matching the filename, `status` outside the enum, a missing mandatory section) under `## ADR warnings`. These are warnings, never errors — ADRs written before this template are not broken by it.

## Decisions (DEC)

`DEC-NNNN-<short-slug>.md`, sequentially numbered, never reused, `id` equal to the filename prefix. Copy `../_template/DEC-XXXX-template.md` to start one. Required frontmatter: `id`, `title`, `tier` (a free string here — the vocabulary is the project profile's), `status` (`proposed | ratified | rejected | superseded`; `proposed` and `ratified` are *live* — the design proceeds on them), `rationale`, `created`, `updated`. Optional, with defaults: `satisfies`, `constrained_by`, `revises`, `breaking` (required when `revises` is set), `authorised_by`, `invokes_exception`, `alternatives`, `reversibility`, `provisional_until`, `client_visible`, `supersedes`, `superseded_by`. Body sections: Context, Alternatives considered, Cascade (mandatory when `breaking: true`), Changelog.

Unlike ADRs, DECs are validated hard: a missing required field, a value outside its enum, a `revises` / `constrained_by` / `supersedes` / `superseded_by` that resolves to no FR, TR or DEC in this project, or an `@` in `revises` (`TR-0014@v2`) fails `scripts/index-specs.py`. An `authorised_by` entry with no matching `ADR-*.md` is a warning. Every DEC renders under `## Decisions` in `specs/INDEX.md`; reciprocity between a DEC's `revises` and the target's `revisions` is checked warn-only under `## Versioning warnings` (a `rejected` or `superseded` DEC legitimately has `revises` set and never enters `revisions`).

## Mandatory sections

Every ADR carries two sections that tell an agent how far a principle bends:

- `## When you may deviate` — the exception condition, stated as a testable claim (something an agent can check from the index, the code, or the environment — not a judgement call).
- `## What you must record when you deviate` — the fields a Decision (DEC) must carry when it invokes the exception: which condition applied, the evidence for it, the expected cost, and `invokes_exception: ADR-NNNN§when-you-may-deviate`.

An ADR with no legitimate exception says so explicitly under the first heading ("No deviation is permitted; supersede this ADR instead."). The template at `_template/ADR-XXXX-template.md` includes both headings; `INDEX.md` shows `yes` in the "Deviation sections" column only when both are present.

## Revision vs supersession

Normative summary of the rule versioned spec objects (FRs and TRs) follow when they change. Every project that adopts decision rights numbers its own copy of the full ADR; until then this section is the rule.

- **The ID stands for identity; content is versioned under it.** For an FR the identity is the *need* (which information, for which role, at which point in which use case). Everything else is content and may change under the same ID. Code, tests, and other objects cite the stable ID only — never `FR-0007@v2`.
- **Every change is a DEC.** A revision or a supersession is recorded as a Decision object with `revises` pointing at the object changed and `breaking` set honestly; the object's Changelog cites it (`YYYY-MM-DD: v<N> — DEC-NNNN (breaking: <bool>): <summary>`). Typo fixes and reflows that do not alter meaning are not changes.
- **Revise in place when current implementers stay correct.** Bump `version` by one and append the DEC to `revisions`, so that `version == len(revisions) + 1`. Bump `updated`.
- **A change that forces implementers to change is still a revision — a breaking one.** Set `breaking: true` on the DEC, bump `version`, append the DEC, and set `last_breaking_revision` to the new `version` (so it is always `<= version`). The DEC enumerates the cascade: every implementer, test, and dependent object that must change.
- **Supersede only when identity changes, or the old object must coexist with the new one for a migration window.** Mint a new ID with `supersedes: <old>`; on the old object set `superseded_by: <new>` and `lifecycle: superseded`. The links are symmetric. The old object keeps its workflow `status`; `deprecated` remains the workflow status for an object abandoned without a successor. "The diff is large" is never grounds for a new ID.
- **History stays with the object that made it.** A superseded object keeps its `revisions`; the successor starts at `version: 1, revisions: []`, and earlier history is reachable through `supersedes`.

The indexer checks the arithmetic (`version == len(revisions) + 1`, `last_breaking_revision <= version`) and the supersession links (`lifecycle: superseded` <-> `superseded_by` set; `supersedes`/`superseded_by` symmetric) and reports violations under `## Versioning warnings` in `INDEX.md`. They are warnings, not gate failures, until integrity enforcement lands.
