---
id: ADR-XXXX
title: <one-line title — the decision, not the topic>
status: proposed  # proposed | accepted | superseded | rejected | deprecated
owner: architect
supersedes: null  # ADR ID (ADR-NNNN) or null — set on the NEW ADR when it replaces an older one
superseded_by: null  # ADR ID (ADR-NNNN) or null — set on the OLD ADR; also set its status to `superseded`
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# ADR-XXXX: <title>

## Context

What situation forces a decision, and which FRs feel it. One or two paragraphs. Cite the FR IDs and any prior ADR this touches. State the constraints that are not up for debate (regulatory, contractual, platform) separately from the ones that are.

## Decision

The decision, stated as numbered rules an agent can apply without re-reading the context. Each rule should be checkable: "do X when Y" rather than "prefer X". Name the fields, files, or interfaces the rule governs.

1. <rule>
2. <rule>

## When you may deviate

Mandatory. State the exception condition as a **testable claim** — something an agent can verify from the spec index, the code, or the environment, not a judgement call. If no deviation is permitted, say so: "No deviation is permitted; supersede this ADR instead."

- You may <deviation> only when **all** of the following hold: <condition 1>; <condition 2>.
- No other exception is permitted; in particular, <a tempting but disallowed reason> is never grounds for deviating.

## What you must record when you deviate

Mandatory. The fields a Decision (DEC) must carry when it invokes the exception above, so the deviation is auditable without re-deriving it:

- `invokes_exception: ADR-XXXX§when-you-may-deviate`
- Which exception clause applied.
- Evidence for the condition (the index query, the measurement, the reference).
- Expected cost of the deviation and who bears it.
- `breaking: <bool>` on the DEC, set honestly.

## Consequences

What becomes easier, what becomes harder, and what other objects (FRs, ADRs, gates, scripts) must change as a result. Include the signal that would tell you this decision was wrong.

## Alternatives considered

One bullet per alternative: what it was, why it was rejected. Keep the ones a future reader is likely to propose again.

- **<Alternative>.** Rejected: <reason>.

## Changelog

- YYYY-MM-DD: created (proposed)
