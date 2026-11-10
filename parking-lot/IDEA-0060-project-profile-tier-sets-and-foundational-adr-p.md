---
id: IDEA-0060
title: Project-profile tier sets and foundational ADR packs (H12)
status: parked
tags:
- template
- profiles
- bootstrap
- adr
- authority-tiers
- decision-rights
size: M
created: '2026-09-07'
updated: '2026-09-07'
last_reviewed: '2026-09-07'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0060: Project-profile tier sets and foundational ADR packs (H12)

## Description

The hub template carries profiles (embedded-alayacare, greenfield-saas) that define the tier vocabulary, tier trigger additions, and a foundational ADR pack to instantiate before any agent runs on the project. Bootstrapping selects a profile. Greenfield profiles start with an empty decision space and need seeding (tenancy and isolation, RBAC and role taxonomy, record immutability and audit, residency, integration boundary, configurability model, notifications) in place of the legacy-platform ADRs the embedded profile carries. The upgrade-respects-the-profile clause of H12 is carved out as an immediate S-sized FR in hub-tooling (profile-aware upgrade), because today bootstrap records applied profiles nowhere and upgrade offers to overwrite the Project A PHIPA hook with the template base copy. Depends on WS2, WS3a, IDEA-0034 core/overlay split.

## Originating context

Project A proposal cos-agent-hub-changes.md H12 (wave D), triaged via /cos 2026-09-07. Compliance profiles already exist under profiles/ (phipa); this generalises them beyond data hygiene.

## Value hypothesis

Decision rights vary by delivery context; profile-carried tier sets and ADR packs mean a new project's agents have a non-empty, correct decision space on day one instead of generating an ADR backlog through halts.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0042 there). Personal-project names generalised.

(none)
