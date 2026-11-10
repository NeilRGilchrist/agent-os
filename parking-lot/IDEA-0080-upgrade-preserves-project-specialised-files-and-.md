---
id: IDEA-0080
title: --upgrade preserves project-specialised files and reports the files it added
  (pytest.ini clobber; provenance-register trigger)
status: promoted
tags:
- bootstrap
- upgrade
- hub-scripts
- template
- provenance
- drift
size: M
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0020
pattern: null
archive_reason: null
---
# IDEA-0080: --upgrade preserves project-specialised files and reports the files it added (pytest.ini clobber; provenance-register trigger)

## Description

bootstrap.py --upgrade whole-file overwrites everything in INFRA_ROOT_FILES and INFRA_DIRS. pytest.ini is in INFRA_ROOT_FILES, so every upgrade replaces Project A's FR-0001 AC-4 configuration (testpaths, the integration marker) with the bare template; it has been restored by hand after all three Project A upgrades. The same class covers stack-injected .cursor/rules and agent-gates.yml. Fix shapes: a project-section marker the upgrader preserves, a 3-way merge, or dropping pytest.ini from INFRA_ROOT_FILES for python-stack projects. Second half: --upgrade adds new template files (stack_profile.py, env_preflight.py, the gate-review wrappers) without saying so, so a project with a provenance register (Project A FR-0015: every file under scripts/ needs a row) gets an unregistered file and a red test, which reached CI once. --upgrade should print the files it added (distinct from the ones it overwrote) and, when the project carries specs/knowledge/provenance-register.md (or a generic post-upgrade hook), a one-line reminder that each needs a row before commit. Root cause per Project A L50: a template upgrade is not a role action, so no role's 'mint a row for every new in-scope file' rule ever fires.

## Originating context

hub-tooling _dispatch/learnings-wave1.md ('Post-merge steps after FR-0010') and synthesis-wave1-2026-09-22 follow-up #3; Project A L50 (Neil, 2026-09-21: hub-level fix, handed to the CoS); Project A handoff-hub-upgrade-2026-09-21-b and -2026-09-22-wave1-complete step 2 ('restore the known clobber ... re-check after every upgrade until it is fixed'). Related: IDEA-0034 (reverse leg + AGENTS.md core/overlay split - the general solution; this is the narrow no-clobber fix and does not need it). The hub-tooling Orchestrator asked that scripts/bootstrap.py be opened once: promote together with IDEA-0063 (generate_commands LF + per-command frontmatter) and consider IDEA-0073. Touches scripts/bootstrap.py (hub script, human approval). Home: hub-tooling. Proposed wave 2, lane B.

## Value hypothesis

Each of the three Project A upgrades so far needed a hand-restore of pytest.ini plus a provenance-register surprise (one reached CI red on Project A PR #10), and every future template script addition hits the provenance half again; the fix turns a ~15-min checklist with a silent failure mode into a one-command upgrade.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0062 there). Personal-project names generalised.

(none)
