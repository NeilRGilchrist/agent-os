---
id: IDEA-0075
title: Reviewer vocabulary tests derive from the AC clause with sentinels; DEC template
  gains a Cascade note (template pattern from Project A DEC-0037)
status: promoted
tags:
- template
- testing
- reviewer
- indexer
- decision-rights
- versioning
size: S
created: '2026-09-20'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0022
pattern: null
archive_reason: null
---
# IDEA-0075: Reviewer vocabulary tests derive from the AC clause with sentinels; DEC template gains a Cascade note (template pattern from Project A DEC-0037)

## Description

Project A DEC-0037 (2026-09-20) settled the rule for its Reviewer suite: a closed member vocabulary that an FR AC states as a brace clause (e.g. lanes, statuses) is derived from that clause by a stated_vocabulary(ac, name) helper and guarded by sentinel tests (floor subset, near-miss denylist, member shape, clause found), so an additive widening ratified by a DEC flows into the tests without a backfill round, while ADR-governed vocabularies and every grammar stay pinned as literals. Two hub-side pieces: (1) ship the helper shape and the sentinel pattern in the template's reviewer guidance (role file / reviewer command or a tests/_helpers module), since every bootstrapped project's Reviewer suite grows the same literals; (2) add to specs/_template/DEC-XXXX-template.md under Cascade: 'If this decision changes a vocabulary, a schema or a grammar that a test pins as a literal, say so here and name the backfill command. A spec commit that widens a pinned set turns the verification suite red on the base branch from the moment it lands; the round that clears it is part of this decision's cost.' Related: the general shape where adding an AC to a merged FR turns the full gate red on coverage-missing until the next Reviewer round (Project A Item B finding) belongs with FR-0008's gate model.

## Originating context

Project A DEC-0037 and FR-0015 v5 Notes 'Vocabulary sourcing' (Architect Item C, _dispatch/handoff-architect-wave2-prep.md, 2026-09-20); learnings L31. specs/_template/ is synced by bootstrap --upgrade, so the template wording is hub-owned. Sits beside IDEA-0071 (indexer supersession/retirement). Home: hub-tooling.

## Value hypothesis

In Project A, three register-schema DECs in one week (DEC-0029, DEC-0032, DEC-0033) each cost a Reviewer backfill round (15-30 min plus a PR re-entry); one in three was a pure member widening that derivation makes free, and the Cascade note makes the other two a budgeted cost instead of a surprise red gate. Every bootstrapped project with registers will reproduce the same three literals, so the pattern pays once per project per schema decision.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0057 there). Personal-project names generalised.

(none)
