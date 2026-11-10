---
id: IDEA-0063
title: Hub-level scripts write generated indexes with platform line endings
status: promoted
tags:
- hub-scripts
- line-endings
- tooling
- ci
- bootstrap
- template
size: S
created: '2026-09-20'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0019
pattern: null
archive_reason: null
---
# IDEA-0063: Hub-level scripts write generated indexes with platform line endings

## Description

patterns.py, parking.py and hub-index.py call write_text without newline='\n', so on Windows the generated INDEX files come out CRLF and differ from the committed LF versions. Apply the FR-0007 fix to the hub scripts.

## Originating context

Observed 2026-09-20 in the hub: patterns/INDEX.md and hub/PATTERN-INDEX.md showed as modified with a whitespace-only diff; git checkout -- then python scripts/patterns.py reindex reproduced CRLF output immediately. hub-tooling FR-0007 fixed the template scripts (index-specs.py, deploy-gate.py, escalation-log.py, render-docs.py) with newline='\n' but scripts/{patterns.py,parking.py,hub-index.py} were out of its scope. Same fix shape; hub scripts are human-approval files so this is a maintainer-mode FR.

## Value hypothesis

Extends FR-0007's LF guarantee to the hub scripts so patterns.py reindex, parking.py reindex and hub-index.py produce byte-identical output on Windows and CI, removing a recurring CRLF-only dirty diff on patterns/INDEX.md and hub/PATTERN-INDEX.md.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0045 there). Personal-project names generalised.

2026-09-25 (CoS; from hub-tooling wave 1): widened to cover `scripts/bootstrap.py::generate_commands`. (1) `generate_commands` writes `.claude/commands/*.md` and `.cursor/commands/*.md` with `write_text(..., encoding="utf-8")` and no `newline="\n"`, so regenerated wrappers are CRLF on Windows: both FR-0012 rounds normalised them by hand, and every `--upgrade` into an LF-normalised project (Project A) shows ~20 whitespace-only modified wrappers that must be restored. DEC-0004 (hub-tooling, FR-0012) routed this defect here; this note records that routing. (2) Per-command frontmatter: DEC-0013 widened FR-0008's `owns:` into `scripts/bootstrap.py` for one `COMMAND_META["gate-review"]` key, and its `alternatives` record the proper fix - per-command frontmatter in `template/.agent-team/commands/*.md`, so `COMMAND_META` never grows again and a new command never needs a hub-script crossing. The hub-tooling Orchestrator asked that these be clustered into one `scripts/bootstrap.py` FR rather than two IDEAs ('open the file once, properly reviewed'). Promote together with IDEA-0080 (--upgrade no-clobber, same file) and consider IDEA-0073 (template .gitattributes; `.gitattributes` is not in INFRA_ROOT_FILES). Proposed wave 2, lane B. Sources: projects/hub-tooling/_dispatch/learnings-wave1.md (FR-0012 and FR-0008 sections); synthesis-wave1-2026-09-22 follow-up #2.
