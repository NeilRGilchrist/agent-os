---
id: IDEA-0082
title: 'Wave-1 craft rules into the role commands: Reviewer, Architect, Orchestrator
  and Developer'
status: promoted
tags:
- template
- agent-team
- commands
- reviewer
- testing
- process
size: M
created: '2026-09-25'
updated: '2026-09-25'
last_reviewed: '2026-09-25'
promoted_to: hub-tooling/FR-0022
pattern: null
archive_reason: null
---
# IDEA-0082: Wave-1 craft rules into the role commands: Reviewer, Architect, Orchestrator and Developer

## Description

Write the rules hub-tooling wave 1 and the Project A waves converged on into template/.agent-team/commands/*.md, so every project gets them on its next upgrade instead of through per-brief watch-outs. REVIEWER: (1) for every AC that names a CLI invocation, drive it once with only its required arguments; for every AC that names a check or gate, run it once for real and make it fail (Project A DEC-0044, which Project A carries locally until the template adopts it); (2) bite check - load git show <main-sha>:<script> as a second module and prove the new tests fail there; (3) on Windows a fake gh must be a compiled .exe - a .bat/.cmd stub is not found by subprocess.run(shell=False) and the real gh runs; (4) dogfood throwaways on short paths or with core.longpaths (MAX_PATH inside venvs); (5) throwaway repos that need origin are cloned from a bare repo (auto mode denies git remote add); (6) pin prefixes/segments on compound fields, and pin out-of-scope guards at explicit parameter values, never at defaults a later FR may own; (7) fix the stale 'do not write REVIEW.md' sentence in reviewer.md (line 42), wrong since FR-0013 / DEC-0001 - the DEC revising FR-0006 AC-7 is owed by the hub Architect. ARCHITECT: write ACs as test specifications (FR-0014: 0 escalations, 0 kick-backs); before drafting a wave, grep earlier FRs' tests for exact-equality pins on fields the new FR changes and pre-write the DEC; name an isolation seam for any host-touching feature; an AC's verification tool's blast radius must fit owns:; flag helpers an FR makes live for the first time; a DEC cascade naming a test file another FR's Reviewer will edit adds it to that FR's owns: in the same commit; when FR N sets a resolution rule, check later FRs naming the same branch literal against it; run index-specs.py --validate before committing a DEC. ORCHESTRATOR: hand out a range of free DEC numbers per brief; report the cycle budget at cycle 2; a zero-discretion brief for a final round; budget the last FR of a dispatch.py chain at 3-4x the first; write cascades as explicit test-id lists; architect-tier DECs ratify at merge (IDEA-0087). DEVELOPER: a defect found in your own verification is developer work, not a Reviewer kick-back.

## Originating context

hub-tooling _dispatch/learnings-wave1.md (every per-FR section; 'The sharpest lesson of the wave') and synthesis-wave1-2026-09-22 ('one-line fix for the Reviewer command'); Project A DEC-0044 (ratified, Project A c911c32/fd0155a) and Project A HANDOFF 2026-09-25 section 6 ('Project A carries DEC-0044 locally until the template reviewer command adopts the rule'); Project A handoff-hub-upgrade-2026-09-22-wave1-complete section 4 (FR-0006 AC-7 cascade due). Promote together with IDEA-0075 (derive-with-sentinels test pattern; DEC template Cascade note). Regenerates the wrappers through generate_commands, so land after the IDEA-0063 LF fix. Touches template/.agent-team/commands/** and the .claude/.cursor wrappers (human approval). Home: hub-tooling. Proposed wave 2, lane C, order 2.

## Value hypothesis

Three wave-1 defects survived 135+-test adversarial suites and were caught only because a dogfood happened to use the bare invocation or a real gate, and 5 of 12 escalations were predictable assertion overlaps at ~10-15 min of Architect time each; putting the rules in the commands makes them default behaviour in every project instead of depending on the Orchestrator remembering them in each brief.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0064 there). Personal-project names generalised.

(none)
