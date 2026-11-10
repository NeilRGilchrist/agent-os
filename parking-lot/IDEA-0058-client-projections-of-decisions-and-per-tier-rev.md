---
id: IDEA-0058
title: Client projections of decisions and per-tier review queues (WS5)
status: parked
tags:
- template
- projections
- review-queue
- decision-rights
- docs
- human-review
size: M
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0058: Client projections of decisions and per-tier review queues (WS5)

## Description

Extend the client-doc generator to render client_visible DECs as a 'Recommendations and why' section in outcome language, with tier:client DECs rendered as explicit questions carrying the agent's recommended answer. Review queues per ratifying tier (neil; oliver on the Project A profile): proposed DECs surface in one list per ratifier (Slack review surface matching the ai-hub override-ledger pattern, or in-repo; open question); ratification writes status:ratified back, rejection writes status:rejected with a reason and reopens the TR; rejections feed H6 metrics. Prospect-validate projection for the Project A profile as a one-page what-we-heard / what-we-are-building / does-this-match sheet. Ratified DECs ingested into ai-hub so downstream projects see prior decisions and rationale. Depends on WS1 and WS3.

## Originating context

Project A proposal decision-rights-implementation-plan.md WS5 (phase 4), triaged via /cos 2026-09-07. Related parked: IDEA-0012 web review console, IDEA-0014 review strain metrics.

## Value hypothesis

Makes the design-it-then-explain-why step generated rather than hand-written, and gives the ratifier one place to act so the neil tier does not become the new bottleneck.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0040 there). Personal-project names generalised.

(none)
