---
id: IDEA-0074
title: 'Factory bot identity for Reviewer verdicts: dispatch.py posts PR reviews under
  a machine-user token'
status: parked
tags:
- dispatch
- github
- identity
- control-plane
- template
size: S
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0074: Factory bot identity for Reviewer verdicts: dispatch.py posts PR reviews under a machine-user token

## Description

Neil decided 2026-09-20: a dedicated GitHub machine-user account (not a GitHub App) with a fine-grained PAT scoped to the factory repos (pull requests: write, contents: read). dispatch.py reads the token from an environment variable (e.g. DISPATCH_GH_TOKEN) and passes it as GH_TOKEN only to the gh pr review subprocess in finalize --role rev, so the Reviewer's verdict lands as a real APPROVE / REQUEST_CHANGES review from the bot on a PR the human's account opened; the existing own-PR comment fallback stays when the variable is absent. Document the branch-protection pairing: if required approvals are on, also require review from code owners with the human as owner so a bot approval never satisfies the merge rule by itself. Account and token creation are human-only; the token never enters chat or a commit. Revisit as a GitHub App only if the factory serves an org with several humans.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L24; synthesis-2026-09-20 finding 3; CoS recommendation and Neil's decision 2026-09-20 (machine user over App). Companion to IDEA-0066, which only restates the contract wording. Touches template/scripts/dispatch.py (human-approval). Home: hub-tooling, maintainer mode.

## Value hypothesis

Every Reviewer verdict in the FR-0001 and FR-0015 waves (5 of 5) was downgraded to a COMMENT, once by GitHub's self-review rule and once by the harness Self-Approval block, so pr.review metrics and FR-0008's gate-evidence model cannot read the verdict state from GitHub and the human re-derives it from comment text on every PR (~2-3 min each, 12+ PRs to come). A bot identity restores formal review states at the cost of one env var and one gh auth login.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0056 there). Personal-project names generalised.

(none)
