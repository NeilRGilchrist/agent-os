---
id: DEC-0019
title: "FR-0012 AC-8's restated review contract follows DEC-0018: the dispatcher posts the final message and keeps the Reviewer's own `REVIEW.md`, synthesising one only when absent; AC-8's detector stops requiring FR-0006's retired `REVIEW.md` phrases"
tier: neil
status: ratified
satisfies: []
constrained_by: [FR-0006, FR-0022]
revises: FR-0012
breaking: true
authorised_by: [ADR-0001]
invokes_exception: null
alternatives:
  - "Revise only FR-0006 AC-7 and leave FR-0012 AC-8's wording"
  - "Keep the pre-FR prefix assertion and append the new clause after the retired one"
reversibility: high
provisional_until: null
client_visible: false
supersedes: null
superseded_by: null
rationale: >
  FR-0012 AC-8 restates the review contract as "the dispatcher posts [the final
  message] to the PR and records [it] as REVIEW.md". Its round-1 ruling kept FR-0006
  AC-7's REVIEW.md phrases verbatim because AC-7 was unrevised then. DEC-0018 now
  revises AC-7. Unless AC-8 and the `_ac8_gaps` detector follow, the stale
  sentence stays pinned twice. ADR-0001 rule 7 allows one `revises` target per
  DEC, so this is DEC-0018's twin.
created: 2026-09-25
updated: 2026-09-25
---

# DEC-0019: FR-0012 AC-8 follows DEC-0018

## Context

FR-0012 AC-8 says `reviewer.md` and `orchestrator.md` "state that the Reviewer posts the verdict of record — its final assistant message, which the dispatcher posts to the PR and records as `REVIEW.md` — and that the human approves and merges". The FR-0012 round-1 Architect ruling (FR-0012 Notes, 2026-09-21) kept FR-0006 AC-7's literal phrases "records it on your branch as `REVIEW.md`" and "do not write `REVIEW.md`" in the verdict bullet, because AC-7 was then unrevised. `test_headless_conduct.py` implements AC-8 through the `_ac8_gaps` detector, which requires both phrases. It also requires, through `test_pre_fr_verdict_bullet_fails_the_ac8_detector_and_the_new_one_extends_it`, that the live bullet starts with the whole pre-FR bullet: "extended, not replaced". DEC-0018 retires exactly those phrases.

## Decision

1. **AC-8's parenthesis is amended.** It becomes: "its final assistant message, which the dispatcher posts to the PR; the Reviewer's own staged `REVIEW.md` is kept as the review of record, and the dispatcher synthesises one from that message only when the Reviewer wrote none (DEC-0001, DEC-0018)". The rest of AC-8 is unchanged:
   - no agent sets a GitHub approval state on the owner's own PR;
   - a self-review is downgraded to a comment;
   - the human merges;
   - the no-dispatcher branch keeps `Approve`.

2. **The detector follows.** `_ac8_gaps` drops the two retired FR-0006 needles and requires DEC-0018's three clauses instead. Its AC-8 additions and its forbidden list (`git commit`, "review state on the PR") are unchanged.

3. **"Extended, not replaced" is narrowed to the part that survives.** The live bullet must start with the pre-FR bullet's text up to and including "The dispatcher posts that message to the PR as the review". The verdict-of-record sentence, the heading rule and the three confirmations are still extended, not replaced. The retired `REVIEW.md` clause is replaced, as DEC-0018 decides.

4. **Unaffected.** AC-10's residual check for `reviewer` is not touched by this DEC. DEC-0016 anchors that check to `f037978`, where the bullet still has its FR-0012 form. FR-0022 depends on FR-0019 for that reason.

**`breaking: true`.** The pinning tests change. FR-0012 goes to `version: 4`, with `revisions: [DEC-0004, DEC-0016, DEC-0019]` and `last_breaking_revision: 4`. Rule 5 was checked: identity unchanged.

**Why `neil`.** Same as DEC-0018, of which this is the twin. It is recorded `proposed`, is live now, and is ratified by Neil's approval of FR-0022.

## Alternatives considered

- **Revise only FR-0006 AC-7.** Rejected. AC-8's text and its detector would still require the retired phrases, so FR-0022 could not satisfy both FRs.
- **Keep the pre-FR prefix assertion and append the new clause.** Rejected. The bullet would still say "do not write `REVIEW.md`" and then contradict itself in the same sentence.

## Cascade

Breaking. Every affected artifact:

- `projects/hub-tooling/specs/FR-0012-headless-conduct-contract-in-role-commands.md`, done in this commit:
  - AC-8 gains one sentence citing this DEC;
  - `version: 4`, `revisions` gains DEC-0019, `last_breaking_revision: 4`;
  - one Changelog line.
- `template/.agent-team/commands/reviewer.md`: the verdict bullet (FR-0022 AC-2, the same edit DEC-0018 cascades). `orchestrator.md`'s verdict paragraph needs no change: it says the verdict is posted and the human merges, and it never mentions `REVIEW.md`.
- `template/tests/unit/scripts/test_headless_conduct.py`, FR-0022's Reviewer:
  - `_ac8_gaps`: per Decision 2.
  - `test_reviewer_dispatcher_path_keeps_fr0006_phrases_and_adds_the_no_self_approval_rule`: it runs through `_ac8_gaps`. Its other three assertions are unchanged. It may be renamed to drop "fr0006_phrases".
  - `test_pre_fr_verdict_bullet_fails_the_ac8_detector_and_the_new_one_extends_it`:
    - the expected `gaps` list for the pre-FR bullet becomes whatever the Decision-2 detector reports: the three AC-8 additions plus the missing DEC-0018 clauses;
    - the prefix assertion follows Decision 3.
- No other FR-0012 test changes because of this DEC. The block hashes, AC-2 to AC-7, AC-9, and AC-10 (anchored by DEC-0016) are unaffected.

## Changelog

- 2026-09-25: created (proposed) with FR-0022, as DEC-0018's twin on FR-0012.
- 2026-09-25: ratified by Neil, with his approval of FR-0022.
