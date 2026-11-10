---
id: IDEA-0050
title: Contextual confidential-term pseudonymization, applied at promotion
status: parked
tags:
- ai-productivity-toolkit
- scrubber
- privacy
- policy
- promotion
size: M
created: '2026-10-23'
updated: '2026-10-23'
last_reviewed: '2026-10-23'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0050: Contextual confidential-term pseudonymization, applied at promotion

## Description

Layered, contextual deny-list rules (e.g. for Customer X, scrub any mention of application Z) applied when an entity is promoted to a wider scope, not at capture. PHI stays scrubbed at capture everywhere; commercial confidentiality depends on the destination audience. Prefer pseudonymization via surface-keyed replacement tokens over removal so account linkability survives. Open issues: the deny-list is itself confidential (lives under kb_root/config, needs distribution); cross-person linkability needs an org-scoped token key (today the HMAC secret is per person); needs a single compiled matcher.

## Originating context

CoS session 2026-10-23 on aitk end state; deferred by the user in favour of promoting IDEA-0039 first. Depends on IDEA-0039 (scrubber performance) and ADR-0004 (scope dimension).

## Value hypothesis

Lets team- and org-scope artifacts be shared more widely without manual confidential-term redaction on every promotion, while personal KBs keep full context.

## Notes

(none)
