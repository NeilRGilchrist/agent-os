---
id: IDEA-0042
title: 'aitk: keep PHI-shaped values out of artifact ids and filenames that reach
  CI logs'
status: parked
tags:
- ai-productivity-toolkit
- phi
- privacy
- distill
- ci
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0042: aitk: keep PHI-shaped values out of artifact ids and filenames that reach CI logs

## Description

R3 assumes PHI-shaped ids only arise from protected sources (e.g. meeting titles), which ADR-0002 capture/scrub/review controls. Two paths bypass that: ids typed by hand (case or ticket numbers), and FR-0003 model-chosen ids derived from approved bodies. AC-10(b) still fails the file, but AC-10(e) prints its path verbatim, including in GitHub Actions logs on the team KB repo (FR-0002 AC-11). Cheap options for later: FR-0003 generates ids without digit runs, or the FR-0001 id pattern disallows SIN/HCN/SSN-shaped suffixes. A product decision; R3 itself stands.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. Architect observation on FR-0002 AC-10 ruling R3 (spec 843b543).

## Value hypothesis

Closes the one leak path human ruling R3 (no path masking) leaves open: a hand-typed or model-chosen id carrying a digit run gets printed verbatim in retained CI logs even though the file itself fails validation.

## Notes

(none)
