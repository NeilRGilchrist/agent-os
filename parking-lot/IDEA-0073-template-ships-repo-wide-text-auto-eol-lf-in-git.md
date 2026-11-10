---
id: IDEA-0073
title: Template ships repo-wide '* text=auto eol=lf' in .gitattributes (cross-project
  line-ending pattern)
status: promoted
tags:
- template
- windows
- line-endings
- cross-platform
- bootstrap
size: S
created: '2026-09-20'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0020
pattern: null
archive_reason: null
---
# IDEA-0073: Template ships repo-wide '* text=auto eol=lf' in .gitattributes (cross-project line-ending pattern)

## Description

template/.gitattributes carries only the specs/_metrics merge=union rule; Project A added its own 'specs/INDEX.md text eol=lf' line by hand. On a Windows host with core.autocrlf=false, any agent write_text round-trip can rewrite a whole LF file to CRLF (an 834-line phantom diff in the FR-0015 backfill). Add '* text=auto eol=lf' (plus binary exceptions) to template/.gitattributes, confirm bootstrap.py treats .gitattributes as an INFRA_ROOT_FILE so --upgrade propagates it, and drop the Project A-local INDEX.md line once the template rule lands. Same class as FR-0007 (template scripts) and IDEA-0063 (hub scripts); this closes it at the repo level for every project.

## Originating context

Project A _dispatch/learnings-FR-0001-wave.md L37 (relayed from the backfill Reviewer); recurrences: hub-tooling FR-0007 (merged), IDEA-0063 (parked 2026-09-20), Project A .gitattributes edit of 2026-09-13. Pattern signal across 3 repos; pulled up from the Project A-level hygiene list for that reason. Home: hub-tooling (template + bootstrap).

## Value hypothesis

The CRLF problem has been fixed three times in three places (FR-0007, IDEA-0063, Project A's .gitattributes pin) and still produced a phantom diff and a PHI-hook false-positive vector in the same week; one attribute line in the template, fanned out by --upgrade, closes the class for every current and future project on a Windows host and removes the per-project rediscovery (~30 min each time it bites, including a Reviewer catching and reverting it).

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0055 there). Personal-project names generalised.

- 2026-09-20 (Project A Architect, Item B of `_dispatch/handoff-architect-wave2-prep.md`): `.gitattributes` is not in `bootstrap.py` `INFRA_ROOT_FILES`, so adding it there starts whole-file-overwriting each project's copy, including the `specs/_metrics/*.ndjson merge=union` rule the metrics log depends on and Project A's own `*.pptx -text` exception (DEC-0036 / FR-0001 AC-11). Land the template rule as a merge-friendly overlay or keep the file out of the overwrite set. Also: a repo that already has CRLF files in the index needs a one-shot `git add --renormalize .` commit when the rule lands (Project A had 27 of 235).
