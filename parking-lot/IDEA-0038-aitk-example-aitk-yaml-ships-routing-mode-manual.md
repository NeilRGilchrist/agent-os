---
id: IDEA-0038
title: 'aitk: example aitk.yaml ships routing.mode manual, which halts capture'
status: parked
tags:
- ai-productivity-toolkit
- config
- bug
- developer-experience
size: S
created: '2026-10-22'
updated: '2026-10-22'
last_reviewed: '2026-10-22'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0038: aitk: example aitk.yaml ships routing.mode manual, which halts capture

## Description

FR-0009 config/aitk.example.yaml sets routing.mode: manual; FR-0005:AC-8 correctly fails closed on any mode but team_only, so copying the example stops capture. Align the example with whatever routing modes exist after the classification FR (FR-0012) lands.

## Originating context

ai-productivity-toolkit orchestrator session 2026-10-22. FR-0005 Reviewer low-priority note (REVIEW-FR-0005).

## Value hypothesis

A copied example config should work out of the box instead of making every route check exit 2.

## Notes

(none)
