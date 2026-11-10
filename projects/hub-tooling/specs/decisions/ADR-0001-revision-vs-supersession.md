---
id: ADR-0001
title: Revision vs supersession for versioned spec objects (FR, TR)
status: accepted  # proposed | accepted | superseded | rejected | deprecated — ratified by Neil 2026-09-07
owner: architect
supersedes: null
superseded_by: null
created: 2026-09-07
updated: 2026-09-07
---

> **Provenance:** Drafted 2026-09-07 by the Architect from `projects/project_a/.agent-team/docs/decision-rights-implementation-plan.md` rev 2, §4 WS1e and §3 "Stable identity, versioned content". The plan names this rule **ADR-006**; in this project it is ADR-0001 (first ADR allocated here). Governs FR-0003 and FR-0004. Supersede with a new ADR, do not edit in place, once accepted.

# ADR-0001: Revision vs supersession for versioned spec objects

## Context

FRs and, from FR-0004, TRs are identified by stable IDs that code, tests, and other spec objects cite (`@covers FR-XXXX:AC-Y`, `implemented_by`, `depends_on`, `extends`, `operationalises`). Once a requirement changes there are two ways to record it: change the content under the same ID, or retire the ID and mint a new one. Without a rule, agents pick whichever is convenient. Two failure modes follow. Edits under the same ID with no record of *why* produce the reconciliation PRs seen in ai-hub-poc — an earlier FR quietly bent to fit a newer one. Minting new IDs for refinements breaks every citation and makes "what does this component implement" unanswerable.

FR-0003 adds the fields that make the choice explicit (`version`, `lifecycle`, `revisions`, `last_breaking_revision`, `supersedes`, `superseded_by`); FR-0004 adds the DEC object that records each change. This ADR states when to use which, so the fields are populated consistently and the compiled context slice (H1) and gates (WS4) can rely on them.

## Decision

1. **The ID stands for identity; content is versioned under it.** For an FR the identity is the *need* (which information, for which role, at which point in which use case). For a TR the identity is the *approach* to operationalising a given FR. Everything else about the object is content and may change under the same ID.

2. **Every change is a DEC.** A revision or a supersession is recorded as a Decision object (`DEC-nnnn`, FR-0004) with `revises` pointing at the object changed and `breaking` set honestly. The DEC is the change log; the object's Changelog line cites it (`v<N> — DEC-NNNN (breaking: <bool>): <summary>`). There are no untraced edits to a live object's normative content. (Typo fixes and reflows that do not alter meaning are not changes; the AC hash contract in the indexer already treats whitespace-only edits as no change.)

3. **Revise in place when code implementing the current object is still correct after the change.** Bump `version` by one and append the DEC to `revisions` (so `version == len(revisions) + 1`). Bump `updated`.

4. **A change that forces implementers to change is still a revision — a breaking one.** Set `breaking: true` on the DEC, bump `version`, append the DEC, and set `last_breaking_revision` to the new `version`. A breaking DEC enumerates its cascade — every component (`implemented_by`), success criterion, test, and dependent object (`depends_on`, `extends`, `operationalises`) citing the revised object — as work items in its `## Cascade` section at decision time (plan WS4; generator is H5 / IDEA-0056).

5. **Supersede — new ID, `supersedes` on the new object, `superseded_by` and `lifecycle: superseded` on the old — only when identity changes.** Concretely, any of: the TR no longer operationalises the same FR; the approach is replaced wholesale (custom endpoint → platform-native, say) rather than refined; the FR's need has changed in who / what / when / role scope; or the old object must remain live alongside the new one for a migration window. Supersession is for coexistence and replacement; revision is for refinement. Supersession links are symmetric and the old object keeps its workflow `status` (typically `merged`); `deprecated` remains the workflow status for an object abandoned without a successor.

6. **Authority.** FR supersession is a client- or product-owner-tier event by definition (the need itself changed). TR supersession is at least `neil`-tier when it touches an ADR exception clause, `agent`-tier otherwise. The tier is declared on the DEC that performs the supersession (`revises: <old object>`, `breaking: true`). Tier vocabulary is the project profile's (WS2, IDEA-0055).

7. **History follows the object that made it.** A superseded object keeps its `revisions`; the new object starts at `version: 1, revisions: []`. Earlier history is reachable through `supersedes`. A DEC has exactly one `revises` target and is never copied onto a successor.

8. **Slices carry the present.** The compiled context slice (H1) for a live object carries the current content plus the DECs since `last_breaking_revision`; DECs before that point and superseded objects reach an agent only when its task is the migration. This is a consequence for H2's filtering, not an instruction to agents.

9. **A migration-window supersession must record**, on its DEC: the window's end trigger (`provisional_until`: date or event), which implementers stay on the old object and why, and the DEC or work item that will retire the old object. Until that DEC lands, the old object may legitimately have `lifecycle: superseded` and non-empty `implemented_by`; the indexer warns on that combination (FR-0004) and WS4 will require the migration DEC to silence it.

## When you may deviate

You may revise in place an object whose identity *has* changed — instead of superseding — only when **all** of the following hold: the object has no live implementers (`implemented_by` empty and no `@covers`/`@implements` citations) and no live dependents (`depends_on`, `extends`, `operationalises` from any live object); its workflow `status` is `draft` or `ready` (never dispatched); and the change is recorded as a `breaking: true` DEC. The condition is testable from the index alone: an object with zero inbound citations and zero inbound links that has never left `draft`/`ready` has no identity anyone else relies on, so a new ID would only add noise.

You may supersede where a revision would have sufficed only when the old object must keep serving live implementers while the new one is built (a migration window, rule 5 last clause). No other exception is permitted; in particular, "the diff is large" is never grounds for a new ID.

## What you must record when you deviate

On the DEC that performs the deviation:

- `invokes_exception: ADR-0001§when-you-may-deviate`
- Which of the two exceptions applied (revise-despite-identity-change, or supersede-for-migration-window).
- Evidence for the condition: for the first, the index query result showing zero inbound citations/links and the object's workflow status at the time; for the second, the list of live implementers that must stay on the old object.
- Expected cost: for the first, none beyond the DEC; for the second, the migration work item(s) and the `provisional_until` trigger (rule 9).
- `breaking: true` in both cases.

## Consequences

- FR-0003 and FR-0004 encode the field semantics above; the indexer lints arithmetic (`version == len(revisions) + 1`, `last_breaking_revision ≤ version`), symmetry, and reciprocity as warnings. IDEA-0056 (WS4) turns them into gate failures and adds the cascade completeness and `breaking` honesty checks.
- Code and tests cite the stable ID only (`TR-0014`, never `TR-0014@v2`); the version they were built against is recorded on the implementing artifact (H3, IDEA-0054), and staleness is `built_against < last_breaking_revision`.
- A rising supersession : revision ratio is a signal the identity rule is being misapplied or the ADRs beneath are unstable (plan §6); H7's Stability dashboard tracks it per ADR decision space.
- Existing FRs in every project are implicitly `version: 1, lifecycle: live, revisions: []`. Nothing is rewritten. The rule applies from the first change made after FR-0003 lands.
- Agents need this rule in their working agreement to apply it; that text change to AGENTS.md core is IDEA-0055 (WS3b) / IDEA-0034 phase 4, not this ADR.
- The template carries a normative summary in `specs/decisions/README.md` (FR-0003) so new projects see the rule; projects that adopt decision rights fully number their own copy of this ADR as part of the foundational ADR pack.

## Alternatives considered

- **Always supersede (immutable objects, new ID per change).** Rejected: breaks every `@covers`/`implemented_by` citation on each refinement; makes traceability an ID-chasing exercise; the plan's success criterion is a *low* supersession rate.
- **Always revise (never mint a new ID).** Rejected: hides identity changes; a TR that now operationalises a different FR under the same ID makes "what does this component implement" a lie, and a migration window has no representation.
- **Version in the ID (`TR-0014-v2` as a distinct object).** Rejected: same breakage as always-supersede with extra parsing; the plan explicitly forbids `TR@version` citations.
- **Git history as the change log (no DEC).** Rejected: not queryable by the indexer or slices, carries no tier or `breaking` flag, and is exactly the state that produced the ai-hub-poc reconciliation PRs.
- **Reuse the workflow `status` field for `live | superseded` (as the plan's YAML shows).** Rejected in FR-0003: `status` is load-bearing in four scripts and is orthogonal to identity lifecycle.

## Open questions

- **Q:** Should a superseded object's DECs be carried onto the successor (full history under the new ID)?
  - **Default:** No — rule 7. Left behind, reachable via `supersedes`. Reopen if the review agent (H9) finds migration tasks routinely need the old history in-slice.
- **Q:** Does a `breaking: true` DEC on an FR always imply its TRs need a revision too?
  - **Default:** Not automatically; the cascade enumeration (rule 4) names which TRs are affected, and each gets its own DEC. WS4 checks the list is complete.

## Changelog

- 2026-09-07: created (proposed; awaiting Neil's ratification). Plan ADR-006 → this project's ADR-0001.
- 2026-09-07: accepted — ratified by Neil as written ("strong and valid"); decision text unchanged. The two Open questions remain open with their stated defaults.
