---
id: FR-0023
title: A project declares its layout — name, footprint root, gate source and test directories — in `.agent-team/layout.yaml`; the footprint checker and the deploy gate honour it, project-qualified `# covers <project>` annotations count for their own project, and hub CI runs the template and hub suites
status: merged
owner: architect
depends_on: [FR-0016, FR-0021, FR-0027]
tags: [gate, deploy-gate, footprint, monorepo, template, tooling]
# Footprint is HUB-relative (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/project_layout.py
  - template/scripts/spec_footprint.py
  - template/scripts/deploy-gate.py
  - template/scripts/index-specs.py  # AC-1 only: collect_graph() reports a malformed layout (DEC-0027; Neil approved 2026-10-30)
  - template/.agent-team/layout.yaml.example
  - template/tests/unit/scripts/test_project_layout.py
  - template/tests/fixtures/project-layout/**
  - projects/hub-tooling/.agent-team/layout.yaml
  - .github/workflows/validate.yml
reads:
  - template/scripts/dispatch.py
  - template/tests/unit/scripts/test_spec_footprint.py
  - template/tests/unit/scripts/test_deploy_gate.py
  - template/tests/unit/scripts/test_deploy_gate_metrics.py
  - template/tests/unit/scripts/test_deploy_gate_gates.py
  - template/tests/unit/scripts/test_index_specs_dec_tr.py
  - template/tests/unit/scripts/test_index_specs_versioning.py
  - template/tests/unit/scripts/test_spec_query.py
  - scripts/bootstrap.py
gates: []
derived_from: IDEA-0061
pattern: null
ac_state: {}
version: 2
lifecycle: live
revisions: [DEC-0027]
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0021]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - The internal API of `project_layout.py` (a frozen dataclass plus one `load(project_root)` is the expected shape), as long as every reader goes through it and each `load()` call runs git at most once, and only when `footprint_root` is `repo`. A process that calls `load()` more than once may run git once per call. Memoising across calls is allowed but not required (DEC-0027).
    - Exact error wording, as long as each names `.agent-team/layout.yaml` and the offending key.
  fixed:
    - "With no `.agent-team/layout.yaml`, every script's output, exit code and written file is byte-identical to today's."
    - "`owns:` / `reads:` entry syntax is unchanged: absolute paths, `..` segments and backslashes are still refused. Only the root they resolve against can move."
    - "The template never ships `layout.yaml` itself (only `layout.yaml.example`), so `--upgrade` never creates or overwrites a project's layout."
    - "`deploy-gate.py` keeps FR-0003/FR-0004/FR-0005's source pins (no DEC/TR/`retired`/`spec_query` tokens; the two-argument `render_index` call)."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-11-02
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session, at Neil's request to promote IDEA-0061 now rather than in wave 3) from IDEA-0061 and its 2026-09-25 Notes. It is grounded in three read-only audits run for this session:
> - `spec_footprint.py` / `deploy-gate.py` / `index-specs.py` root resolution, existing per-project config files, and hub CI (validate.yml quoted);
> - the full list of gate and footprint test pins;
> - a simulated gate over hub-tooling with the qualified annotations recognised.
>
> This is the configuration-and-gate half. **FR-0024** is the dispatcher half and depends on this FR. · source_class: neil_position+agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0023: Project layout, footprint root and gate directories

## Why

hub-tooling lives in a subdirectory of the hub repo, and every FR it writes changes files outside that subdirectory: `template/**`, `scripts/**`, the hub's `tests/`. The template's tools assume the project root is the whole world:
- `spec_footprint._git_ls_files` runs `git ls-files` from the project root. It sees 143 project files and none under `template/`, so every hub-relative `owns:` matches nothing. The overlap check that should have flagged FR-0015/FR-0016/FR-0018 on `dispatch.py` and FR-0019/FR-0020/FR-0022 on `bootstrap.py` and 13 command files reports nothing. The Chief of Staff sequences these by hand.
- `deploy-gate.py` scans only `<project>/src` and `<project>/tests`, and recognises only `@covers`. hub-tooling's 809 test annotations live in `template/tests/` and are written `# covers hub-tooling FR-NNNN:AC-N` on purpose: those tests ride into every bootstrapped project, where a bare `@covers FR-0019` would fail that project's gate as an unknown FR. So hub-tooling's gate reports FR-0002..FR-0014 at 0% coverage, and the per-AC table in each PR body is the only evidence.
- Hub CI never runs the template suite, 1,475 tests, or the hub's own `tests/`.

IDEA-0061 was parked on 2026-09-07 with Neil's agreement to promote it after wave A. Two re-plans deferred it without recording why. Every hub-tooling FR since has been hand-orchestrated: 7 in wave 1, where FR-0013 alone took about 5 hours, and 8 in wave 2.

## What

After this FR, a project may carry `.agent-team/layout.yaml` declaring four things:
- its `project_name`;
- whether its footprints are rooted at the project or at the git repository (`footprint_root`);
- the gate's source directories;
- the gate's test directories.

One small module reads it for every script. The footprint checker lists files against the declared root, so hub-relative footprints and their overlaps resolve. The gate scans the declared directories and also counts `# covers <project_name> FR-NNNN:AC-N` for its own project name. A project without the file behaves exactly as today. hub-tooling gets its own layout. Hub CI runs both suites, non-blocking until they have been seen green on Linux.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **An optional, validated layout file read through one module.** `template/scripts/project_layout.py` exposes one loader for `<project_root>/.agent-team/layout.yaml`.
  - **When the file is absent:** it returns the default layout: no project name, `footprint_root: project`, source dirs `["src"]`, test dirs `["tests"]`. It runs no subprocess and prints nothing.
  - **When the file is present:** it must be a mapping whose keys are drawn only from:
    - `project_name`: matches `^[a-z0-9][a-z0-9-]*$`;
    - `footprint_root`: `project` or `repo`;
    - `gate`: a mapping with `source_dirs` and/or `test_dirs`, each a non-empty list of directory paths resolved under the footprint root. Entries are checked with the `owns:` rules (`spec_footprint._validate_glob`: no absolute path, no `..` segment, no backslash) plus the drive-letter rejection below.
  - **Drive-letter rejection (DEC-0027).** A `gate.source_dirs` or `gate.test_dirs` entry with a Windows drive or UNC root is malformed, on every platform: `PureWindowsPath(entry).drive` is non-empty, as in `C:/x`, `c:x` or `//server/share/x`. The `LayoutInvalid` names `gate.source_dirs` or `gate.test_dirs`. This applies to the layout only. `owns:`/`reads:` entries and `spec_footprint._validate_glob` are unchanged.
  - **Empty values (DEC-0027).**
    - A file that parses to no mapping is malformed: an empty file, a file holding only comments, or `null`.
    - `gate: {}` and `gate: null` are malformed. `gate`, when present, names at least one of its two keys.
    - A top-level empty mapping (`{}`) is valid. It declares nothing, so it loads as the default layout.
  - **When the file is malformed** (unknown key, wrong type, invalid value): it raises one error naming `.agent-team/layout.yaml` and the key.
    - **`index-specs.py`** imports `project_layout` optionally, as `deploy-gate.py` does. A copy with no sibling `project_layout.py` behaves exactly as today. `collect_graph()` loads the layout and turns the error into one entry of its `errors`, placed **first**, ahead of the FR, TR and DEC errors. So does `validate_spec_graph()`, which returns that list. Every mode that reports `collect_graph()` errors then prints `Spec validation FAILED:` on stderr, followed by `  - <error message>` as the first entry. Those modes are plain, `--validate`, `--list`, `--slice` and `--provisional`. Each exits 1 and writes neither `INDEX.md` nor `CODEOWNERS`. `--ac-hashes` does not call `collect_graph()` and is unaffected.
    - **`deploy-gate.py`** fails under the existing class `spec-validation` before writing anything. Its `Spec index validation failed:` block shows the layout error **exactly once**, as the first entry, even though both its own load and `validate_spec_graph()` report it.
  - **`footprint_root: repo`** resolves to `git rev-parse --show-toplevel` run from the project root. If that command fails, the result is the same kind of error.
  - The template ships `template/.agent-team/layout.yaml.example`, which documents every key and its default, and never ships `layout.yaml`.

  Verified per case against temporary trees:
  - the loader: absent, each valid combination (including top-level `{}`), each malformed case (including the empty file, `gate: {}`, and a `C:/…` entry and a `//server/share/…` entry under each of `gate.source_dirs` and `gate.test_dirs`), and `repo` outside any git repository;
  - the subprocess indexer, for one malformed layout plus one FR error in the same tree, in each of the five modes: stderr's first two lines and the exit code, and no `INDEX.md` or `CODEOWNERS` written;
  - `--ac-hashes` on that tree, which exits 0;
  - the subprocess gate on that tree, where the layout message appears once.

- **AC-2:** **Footprints resolve against the declared root.** `spec_footprint._git_ls_files` lists tracked files relative to the footprint root:
  - `project`: as today;
  - `repo`: `git -C <toplevel> ls-files`, whose paths are repo-relative.

  `find_overlaps`, and INDEX.md's `## Footprint warnings` built from it, therefore match repo-relative `owns:` entries. Entry validation is unchanged. Verified with a temporary repository holding a subdirectory project `proj/` with two `ready` FRs that both own `lib/x.py` outside `proj/`:
  - with `footprint_root: repo`, the overlap is reported;
  - with no layout, the file is not seen and no overlap is reported, which is today's behaviour;
  - with the project at the repository top, both settings give identical output.

- **AC-3:** **The gate scans the declared directories.** `collect_covers` scans each `gate.test_dirs` entry and `collect_implements` each `gate.source_dirs` entry, all under the footprint root. Reported paths are relative to the footprint root, so a directory outside the project root no longer raises `ValueError` from `relative_to`. A drive-letter or UNC entry, which would otherwise resolve outside the footprint root and raise that `ValueError`, is refused when the layout loads (AC-1, DEC-0027). So the gate never reaches `relative_to` with it, and fails `spec-validation` instead of `script-error`. Missing directories are skipped silently, as a missing `tests/` is today. The defaults reproduce today's `src/` and `tests/` exactly. Verified in the subdirectory fixture with `footprint_root: repo`:
  - `test_dirs: [lib_tests]` at the repo level counts a `@covers` there;
  - `source_dirs: [lib]` counts an `@implements` there;
  - the same tree with no layout counts neither.

- **AC-4:** **`# covers <project_name>` counts for its own project.** When `project_name` is `P`, the gate counts a line matching `#\s*covers\s+P\s+(FR-\d{4}):(AC-\d+)` exactly as it counts `@covers FR-NNNN:AC-N`. `P` is matched literally and bounded by whitespace. That covers every consequence: unknown-FR and unknown-AC failures, coverage and the `counts.covers` total.
  - A qualified annotation naming any other project is ignored.
  - With no `project_name`, qualified annotations are ignored, as today.
  - Placeholder lines such as `# covers P FR-00NN:AC-N` do not match.

  Verified:
  - `# covers demo FR-0001:AC-1` with `project_name: demo` covers AC-1;
  - the same line under `project_name: other`, or with no layout, is not counted;
  - `# covers demo FR-0099:AC-1` for an unknown FR fails `covers-unknown-fr` under `demo` only;
  - a placeholder line is not counted.

- **AC-5:** **Hub CI runs the hub and template suites.** In `.github/workflows/validate.yml`:
  - the checkout gains `fetch-depth: 0`, because about 13 template test files compare against historical hub SHAs and skip when those are unreachable;
  - the install step becomes `pip install pyyaml pytest`;
  - two steps run `python -m pytest tests -q` and `python -m pytest template/tests -q` as **separate** invocations. Combined, they fail on `sys.path` (`template/pytest.ini`'s `pythonpath` applies only when `template/` is the rootdir).
  - Both new steps carry `continue-on-error: true`, because neither suite has ever run on Linux.
  - The three existing steps are unchanged.

  The PR body reports the first CI run's pass and fail counts for each suite. Linux-only failures are recorded as `## FINDINGS` with test ids and are not fixed in this FR. Making the steps blocking is a follow-up once they are green.

- **AC-6:** **hub-tooling declares its layout.** `projects/hub-tooling/.agent-team/layout.yaml` sets:
  - `project_name: hub-tooling`
  - `footprint_root: repo`
  - `gate.source_dirs: [template/scripts, scripts]`
  - `gate.test_dirs: [template/tests, tests]`

  Verified in a temporary copy of the hub, never the live checkout. With the modified template's scripts copied over hub-tooling's `scripts/` in the copy, `scripts/deploy-gate.py --stage full --status-only` run from the copy's `projects/hub-tooling`:
  - counts the `# covers hub-tooling` annotations in `template/tests/` and the `@covers` in `tests/`;
  - reports FR-0002..FR-0014 fully covered;
  - reports no `covers-unknown-fr` or `covers-unknown-ac` failure. The copy's `template/scripts/` include FR-0027's labelled-AC detection (Dependencies), so FR-0001's `@covers FR-0001:AC-1`..`AC-11` in `tests/` resolve.

  `index-specs.py` in the copy reports, under `## Footprint warnings`, exactly the overlaps that `spec_footprint.find_overlaps` computes over the copy's active FRs (`ready`, `in-progress` and `in-review`) against `git ls-files` at the copy's top (DEC-0027). The list is not fixed by this AC, because it changes as FRs merge. At this revision (2026-10-30) it is:
  - FR-0018 ↔ FR-0024, FR-0018 ↔ FR-0025 and FR-0024 ↔ FR-0025 on `template/scripts/dispatch.py`;
  - FR-0018 ↔ FR-0026 on `template/scripts/metrics_log.py` and `template/specs/_metrics/README.md`;
  - FR-0023 ↔ FR-0026 on `template/scripts/deploy-gate.py` and `template/scripts/index-specs.py`.

  The Reviewer computes the expected set independently, then states it and the observed section in the PR body. The two must be equal and non-empty, and at least one shared file must lie outside `projects/hub-tooling/`.

  Any failure left is itemised in the PR body. None is expected once FR-0027 has merged with its `@covers FR-0001:AC-12` annotation. Without that annotation, one failure is expected: `coverage-missing` for FR-0001 AC-12 at `--stage full`. That AC asks for the hub tests to exist, and no test carries its annotation today.

- **AC-7:** **Nothing else changes.**
  - For a project with no `layout.yaml`, every printed line, exit code, written INDEX.md and metrics record of `index-specs.py` and `deploy-gate.py` is byte-identical to today's. In particular:
    - the `_lint_stderr` exact-stderr pins in `test_index_specs_versioning.py`, `test_spec_query.py` and `test_index_specs_dec_tr.py`;
    - Project A's `test_indexer_passes_with_no_warnings_beyond_those_present_at_dispatch`.
  - FR-0003, FR-0004 and FR-0005's gate-source pins hold unedited.
  - Every `test_spec_footprint.py` rejection pin holds unedited.
  - The failure-class and warning-class enums are unchanged.
  - Every test that passed before this FR passes unedited. A red is a `## FINDINGS` line for the Architect.

## Out of scope

- The dispatcher: prefix-aware worktrees, agent cwd, object paths and permission rules. That is **FR-0024**, which depends on this FR.
- `metrics_log.project_name` using `project_name`. It is still the git directory's name; a follow-up after FR-0018, which owns `metrics_log.py` this wave.
- Rewriting hub-tooling FRs' project-relative `reads:` entries (`specs/decisions/DEC-…`), which become wrong-rooted documentation once `footprint_root: repo`. `reads:` is documentation only. The Architect normalises them in a spec chore after this merges.
- A per-project extra protected set (for example the hub's `template/scripts/**`): IDEA-0088's family. hub-tooling keeps dispatching `template/**` FRs in maintainer mode by Architect convention.
- Making the CI steps blocking (AC-5).
- Labelled-AC detection itself (`- **AC-N (label):**`). That is **FR-0027** (Dependencies).
- Any `index-specs.py` change beyond AC-1's layout error. In particular, `parse_acs`, the AC patterns, `render_index` and the query modes' output are untouched.

## Open questions

- **Q:** Should `@implements` tags in `template/scripts/` count for hub-tooling? There are 278 of them, and they name hub-tooling FRs.
  - **Default:** Yes, through `source_dirs`. They are hub-tooling's implementation tags. The same tags ride into every project's `scripts/`, but no bootstrapped project lists `scripts/` as a source directory, and `layout.yaml.example` says not to.
- **Q:** Should the layout live somewhere other than `.agent-team/`?
  - **Default:** `.agent-team/`. `MNT_PROTECTED_GLOBS` covers it, so an agent cannot change what its own gate scans. `--upgrade` builds its plan only from template files, so a project-only `layout.yaml` is never touched.

## Dependencies

- **FR-0021**: owns `deploy-gate.py` in wave 2. This FR rebases after it merges.
- **FR-0016**: adds the encoding keywords to `spec_footprint._git_ls_files`. This FR rebases after it.
- **FR-0027: labelled-AC detection.** Neil's decision of 2026-10-30 replaces the earlier dependency on commit `0eef0f0`, which exists only in the other hub (ADR-0002). Without FR-0027, `AC_HEADING_PATTERN` does not detect FR-0001's `- **AC-N (label):**` ACs. Its 74 `@covers FR-0001` annotations in the hub's `tests/` would then fail `covers-unknown-ac`, 11 distinct failures for AC-1..AC-11, once AC-6's `test_dirs` includes `tests`. Those fail at **every** stage, which would make hub-tooling's gate red at `dev`.
  - **AC-6's layout must not be committed to `main` before FR-0027 merges.** If FR-0027 has not merged when this FR's PR is ready, the Orchestrator holds the PR and asks Neil.
  - FR-0027 also owns `deploy-gate.py` and `index-specs.py`. Whichever merges second rebases. The expected order is FR-0027 first, then this FR rebases onto it.
  - `depends_on` names FR-0027 since this branch was rebased onto it (2026-10-30), as this note prescribed.
- **FR-0026** (ready) also owns `deploy-gate.py` and `index-specs.py`, and lands **after** this FR (its own Dependencies). With `index-specs.py` now in `owns:`, the two overlap on both files (AC-6).
- **FR-0024** depends on this FR.

## Notes

- **Maintainer mode.** `template/scripts/deploy-gate.py`, `template/scripts/index-specs.py` (from v2, DEC-0027) and `template/.agent-team/**` are human-approval files. Dispatch in `mnt` mode with the `owns:` above as the write surface, after Neil approves (recorded in the Changelog). The `owns:` reaches beyond `template/` to `projects/hub-tooling/.agent-team/layout.yaml` and the hub's `.github/workflows/validate.yml`. Both are named here and nothing else outside `template/` is touched.
- **Tests.** Template tests ride into bootstrapped projects: annotate `# covers hub-tooling FR-0023:AC-N`. That form becomes gate-visible in hub-tooling through this FR. AC-5's workflow and AC-6's layout are verified by the Reviewer in the PR (the CI run) and in a temporary hub copy.
- **Reviewer dogfood: temporary hub copy, never the live checkout** (FR-0019's Notes give the procedure).
  1. Record `git -C <hub> status --porcelain` before and after.
  2. Bootstrap a throwaway from the modified template with an explicit short path and `--no-register`. With no layout, confirm the gate and indexer output is byte-identical to `main`'s template on the same tree.
  3. Add a `layout.yaml` with `footprint_root: repo` in a nested-project throwaway, and confirm AC-2 to AC-4 through the real scripts.
  4. Delete the throwaways.
- **Bite check.** Load `main`'s `spec_footprint.py` and `deploy-gate.py` as second modules and show AC-2, AC-3 and AC-4's tests fail there.
- **After merge (Orchestrator).**
  - Run `bootstrap.py --upgrade projects/hub-tooling --yes`. `layout.yaml` is project-only and already committed by this FR.
  - Run hub-tooling's gate and record the new baseline.
  - The Architect normalises hub-tooling's `reads:` roots.

## Changelog

- 2026-09-25: created from IDEA-0061 at Neil's request (promote now; joins lane C after FR-0021; FR-0024 follows in lane A). Awaiting Neil's approval of the control-plane edit before dispatch.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised). No normative change. He will brief the Orchestrator at its next pause.
- 2026-10-30: v2 — DEC-0027 (breaking: false). This responds to the Developer's escalation at `9d48fd7`.
  - Neil approved widening `owns:` to `template/scripts/index-specs.py`, a control-plane edit, so that AC-1's indexer half can be built. It was in `reads:`.
  - AC-1 now states where the layout error enters `index-specs.py`, its position, the five modes it fails, that `--ac-hashes` is unaffected, and that the gate shows it once. It also states the empty-value rule.
  - The dependency on commit `0eef0f0` is replaced by FR-0027, per Neil's decision. The constraint is unchanged: AC-6's layout does not reach `main` first.
  - AC-6's stale wave-2 overlap list is replaced by the `find_overlaps` rule and the current list. Its expected residual failure is restated.
- 2026-10-30: still v2 — DEC-0027 item 6 (breaking: false), from the Reviewer's r1 escalation on AC-1/AC-3 and Neil's decision of the same day.
  - AC-1 now refuses a `gate.source_dirs` or `gate.test_dirs` entry with a Windows drive or UNC root, in the layout only. `owns:` is unchanged.
  - AC-3 states that this prevents the `relative_to` `ValueError` at load time.
  - The `solution_space.open` git bound now reads "once per `load()` call" (r1 N-2).
  - DEC-0027 is unmerged, so this folds into the same revision and does not bump `version`.
- 2026-11-02: status `ready` → `merged`. PR [#26](https://github.com/NeilRGilchrist/cos-agent-hub/pull/26) merged into `main` as commit `ddbe9e5`. Recorded by the Chief of Staff: the branch was dispatched by hand, so `dispatch.py reconcile-merged` did not match it. AC-5, from the first CI run on the PR (Validate run 41202672002, Python 3.11, ubuntu): hub suite 208 passed, 78 skipped; template suite 2123 passed, 223 skipped, 2 failed. Both failures are the `digit-drive` cases of `test_project_layout_adversarial.py::test_every_drive_form_is_refused_under_both_keys`: Python 3.11's `PureWindowsPath` treats only letters as drives, so `1:x` has no drive there and the rule correctly lets it through. The test over-asserted; it is fixed on the same bookkeeping branch. The code and AC-1 are unchanged.
