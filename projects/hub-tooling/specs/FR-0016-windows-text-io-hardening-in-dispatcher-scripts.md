---
id: FR-0016
title: Windows text I/O hardening in the dispatcher scripts — every text-mode subprocess read decodes UTF-8 with replacement, `_git_capture` never reports an undecoded capture as success, Python children the dispatcher reads emit UTF-8, and committed files the dispatcher writes are LF
status: merged
owner: architect
depends_on: []
tags: [windows, encoding, cross-platform, dispatch, template]
# Footprint is HUB-relative under template/ (see AGENTS.md "Hub-tooling specifics").
owns:
  - template/scripts/dispatch.py
  - template/scripts/metrics_log.py
  - template/scripts/spec_footprint.py
  - template/scripts/env_preflight.py
  - template/tests/unit/scripts/test_windows_text_io.py
  - template/tests/fixtures/windows-text-io/**
reads:
  - template/scripts/agent-status.py
  - template/tests/unit/scripts/test_dispatch_stack_grants.py
  - template/tests/unit/scripts/test_env_preflight.py
  - template/tests/unit/scripts/test_dispatch_metrics.py
  - template/tests/unit/scripts/test_dispatch_postapprove.py
  - template/tests/unit/scripts/test_dispatch_permissions.py
  - template/tests/unit/scripts/test_line_endings.py
  - scripts/_console.py
gates: []
derived_from: IDEA-0028
pattern: null
ac_state: {}
version: 1
lifecycle: live
revisions: []
last_breaking_revision: null
supersedes: null
superseded_by: null
extends: [FR-0006, FR-0007, FR-0013]
serves_roles: [orchestrator, human_supervisor]
solution_space:
  open:
    - Whether the encoding kwargs are added at each call site or through a small shared wrapper, as long as AC-1's guard holds for every call and no test double that replaces `dispatch.subprocess` wholesale (`SimpleNamespace(run, TimeoutExpired, CalledProcessError, PIPE)` in `test_dispatch_metrics.py`) needs any other attribute.
    - How AC-3's environment is built, as long as it is a copy of `os.environ` (never a mutation of it) and any existing `env_extra` / `UV_PROJECT_ENVIRONMENT` entries are still merged.
  fixed:
    - "Bytes-mode calls (the agent `Popen`s, `show-ref --quiet`, `taskkill`, `diff --cached --quiet`, `gh --version`, `gh auth status`, `_park_findings`) are unchanged."
    - "Dispatcher-private files (permission files, lock files, PR records, fingerprints, synthesis reports, briefs under `_dispatch/`) are written exactly as today. Several are compared byte-for-byte with the pre-FR module's output on the host running the tests."
    - "No agent's spawn environment changes (IDEA-0086)."
goal: null
success_criteria: []
asserted_by: []
variability: null
created: 2026-09-25
updated: 2026-09-25
---

> **Provenance:** Drafted 2026-09-25 by the hub-tooling Architect (wave-2 drafting session) from IDEA-0028 and its 2026-09-25 Notes (Project A L54, L61). Grounded in an AST enumeration of every `subprocess` call in `template/scripts/*.py` at `a8889df`: 51 calls, 41 of them text mode with no `encoding=`. The failure was verified on this host (Python 3.12.10, cp1252 locale): a child writing the UTF-8 bytes of `”` gives `returncode 0, stdout None` under `text=True`, and the undecodable cp1252 bytes are 0x81, 0x8D, 0x8F, 0x90 and 0x9D. · source_class: agent_observation+session_analysis · role: architect · model: opus · ip_class: hub_original.

# FR-0016: Windows text I/O hardening in the dispatcher scripts

## Why

Of the 47 `subprocess` calls in `template/scripts/dispatch.py`, 37 read git, `gh`, `uv` or Python output with `text=True` and no `encoding=`, so on Windows they decode with the locale codec (cp1252). When a spec or commit contains a byte cp1252 cannot decode, the decode fails in subprocess's reader thread. `stdout` then arrives as `None` while the return code is still 0. There are three consequences:

1. **Crashes.** `_fr_status_on_branch` runs `git show <branch>:<spec>` and feeds `None` to `FRONTMATTER_PATTERN.match`. `tick --role rev` crashed with a `TypeError` on Project A FR-0004 v4 (L61). Project A now runs every dispatcher command with `PYTHONUTF8=1`, and still must against hub `851ee34`.
2. **Mojibake.** `git show <branch>:PR_BODY.md` is decoded as cp1252 and written back as UTF-8, so a PR body with `—` or `→` comes out mojibaked, or empty when it contains `”`.
3. **A control-plane check that fails open.** `_git_capture` returns `(True, (proc.stdout or "").strip())`, so a failed decode looks like a successful empty read. FR-0013 AC-6's `--allow-crossing` check (L4782-4793) treats an empty content diff as "content-free" and prints `CROSSING-ALLOWED`. On Windows, a real change to a control-plane path whose diff contains `”` or `←` is let through.

The same class appears in `metrics_log.py` (`project_name`), `spec_footprint.py` (`_git_ls_files`) and `env_preflight.py` (docker and PowerShell probes through its `run` seam).

There is also a write-side gap. `_flip_frontmatter_to_merged` writes the spec it then commits with the host's line endings, which is how hub-tooling's FR-0006 and FR-0009 were committed CRLF.

IDEA-0028's original crash, in `agent-status.py`, is already fixed in the template (`_configure_stdio`, `safe_print`). Only the `ai-hub-poc` copy lacked it.

## What

After this FR, every text-mode subprocess call in the four scripts the dispatcher runs through decodes UTF-8 with replacement, so a read never arrives as `None`, and a guard test keeps it that way for later FRs. `_git_capture` refuses a capture that has no output object, whatever the return code. The Python children whose output the dispatcher reads (the deploy gate, the indexer, pytest) run with `PYTHONIOENCODING=utf-8`, so both ends of the pipe agree. The two committed files `dispatch.py` writes are LF. Project A's `PYTHONUTF8=1` workaround can be retired.

## Acceptance criteria

Each AC must be independently testable. Number them; the numbers are stable for the life of the FR.

- **AC-1:** **Every text-mode subprocess read decodes UTF-8 with replacement, and a guard keeps it so.** In `template/scripts/dispatch.py`, `metrics_log.py`, `spec_footprint.py` and `env_preflight.py`, every call expression that passes `text=True` (or `universal_newlines=True`) also passes `encoding="utf-8"` and `errors="replace"`. That includes calls made through an injected `run` seam, and the two existing `encoding="utf-8"` calls that lack `errors=` (`_existing_review_md_source`, `_read_review_md_on_branch`). A test walks the AST of those four files and fails, naming file and line, for any call with `text=True` or `universal_newlines=True` that lacks either keyword. That guard fails against `a8889df`'s files, and each adversarial mutation fails it: one call's `encoding=` removed, or one call's `errors=` removed. Behaviour on ASCII output is byte-identical to today.

- **AC-2:** **A capture with no output object is never a success.** `_git_capture` returns `(False, <message>)` when the process exits 0 but its `stdout` is `None`. The message says the output could not be read. Every caller treats that as it treats a failed git command today. In particular, FR-0013 AC-6's content-free check refuses rather than prints `CROSSING-ALLOWED`. Verified in two ways:
  - with a `subprocess.run` double returning `CompletedProcess(returncode=0, stdout=None)` for the content diff: `finalize --role mnt --allow-crossing` refuses;
  - with a real repository whose control-plane diff contains `”` (U+201D) and `←` (U+2190): the crossing is refused as content-carrying, on every host.

- **AC-3:** **The dispatcher's Python children write UTF-8 to the pipes it reads.** `_run_deploy_gate`, `_refresh_spec_index` and `_collect_failing_tests` run their child with an environment that is a copy of `os.environ` plus `PYTHONIOENCODING=utf-8`, plus any `env_extra` as today. `os.environ` is never mutated. Verified by a spy on `subprocess.run` for each of the three: the `env` passed contains `PYTHONIOENCODING=utf-8` and every `env_extra` key, and `os.environ` is unchanged after the call. Also verified with a real child that prints a non-cp1252 character to stdout and stderr: the dispatcher-side text contains it.

- **AC-4:** **Branch-read paths no longer crash on non-cp1252 content.** `_fr_status_on_branch`, `_finalize_dev` / `_finalize_oneshot`'s `git show <branch>:PR_BODY.md`, `_gh_merged_prs`'s `gh pr list --json` parse, and `uv sync`'s stderr read each handle output containing `”` and `←`: the value is correct, or replacement characters where bytes are invalid, and nothing raises `TypeError` or `AttributeError`. Verified for `_fr_status_on_branch` against a real repository whose role-branch spec has a title containing `”` and `←`, reached through `runnable_review_frs` (the `tick --role rev` path): it returns the branch's status. The others are verified with doubles returning those characters.

- **AC-5:** **Committed files the dispatcher writes are LF.** `_flip_frontmatter_to_merged` (the spec it then commits) and `_prepend_forced_gate_banner` (a gate evidence file) write with `encoding="utf-8", newline="\n"`. Verified by the technique `test_line_endings.py` uses (FR-0007): the written bytes contain no `\r\n`. No other `write_text` in `dispatch.py` changes (fixed rule 2).

- **AC-6:** **Nothing else changes.**
  - Every test that passed before this FR passes unedited, including these:
    - `test_dispatch_stack_grants.py`'s `env["UV_PROJECT_ENVIRONMENT"]` and timeout assertions, and its exact-argv comparison with the pre-FR `ensure_dev_venv`;
    - `test_env_preflight.py`'s `_recording_run(argv, **kwargs)` double;
    - `test_dispatch_metrics.py`'s wholesale `dispatch.subprocess` replacement.
  - No printed line, exit code, metrics record or permission file changes for ASCII input.
  - No test file other than this FR's own is edited. A pre-existing test that goes red is a `## FINDINGS` line for the Architect.

## Out of scope

- stdout reconfiguration in `index-specs.py`, `deploy-gate.py`, `render-docs.py` and `escalation-log.py`. `dispatch.py`, `agent-status.py` and `metrics_log.py`'s CLI already reconfigure. The gate's PASSED line is ASCII, and FR-0021 owns the gate and the indexer in this wave.
- Unifying the `errors=` handler for stdout reconfiguration (`replace` in some scripts, `backslashreplace` in others).
- The environment of spawned agents: `PYTHONUTF8` for the harness's own tool calls. That is IDEA-0086 (env carry).
- Routing the 20 git calls that bypass `_git_capture` through it. AC-1 covers them where they are.
- Dispatcher-private writes (fixed rule 2) and the hub scripts (FR-0019).

## Open questions

- **Q:** `errors="replace"` or `errors="strict"` with a clear error?
  - **Default:** `replace`. The reads are status, frontmatter, PR bodies and diffs. A replacement character is visible and harmless in all of them, while a strict failure would stop a wave over one byte. For the one security-relevant read (AC-2's content diff), replacement characters are content, so the check still refuses.
- **Q:** Should the dispatcher set `PYTHONUTF8=1` for its children instead of `PYTHONIOENCODING=utf-8`?
  - **Default:** `PYTHONIOENCODING`. It changes only the pipes. `PYTHONUTF8` also changes the children's default `open()` encoding, which every template script already sets explicitly, so it would be a wider change for no gain.

## Dependencies

- **FR-0013**: AC-6's content-free check, which AC-2 closes, and the two `REVIEW.md` reads it made UTF-8.
- **FR-0007**: the LF convention and its test technique.
- **FR-0006**: `_git_capture`'s callers in the finalize path.

## Notes

- **Maintainer mode.** `template/scripts/dispatch.py` is a human-approval file. This FR is dispatched in `mnt` mode with the `owns:` above as its write surface. The human's approval of this FR is the approval for that edit. Edit `../../template/**`, never this project's bootstrap-output copy.
- **Lane A order.** This FR, FR-0015 and FR-0018 all own `dispatch.py`, and they run one at a time in the order the Orchestrator sets (wave-2 plan §2.1). If FR-0015 lands first, its new git reads fall under AC-1's guard and get the kwargs in this FR. If this FR lands first, FR-0015's maintainer adds them itself, because the guard test fails otherwise.
- **Reviewer:**
  - Run the AST guard against `a8889df`'s four files and show it fails there (the bite check).
  - For AC-2, build the real repository case. A double alone does not prove the crossing refuses.
- **Reviewer dogfood (Windows, mandatory).**
  1. In a throwaway bootstrapped from the modified template, commit a spec whose title contains `”` and `←` onto a `claude/dev-<FR>` branch with `status: in-review`.
  2. Run `python scripts/dispatch.py tick --role rev --dry-run` **without** `PYTHONUTF8` and `PYTHONIOENCODING` in the environment. It must list the FR, not crash.
  3. Report under `## FINDINGS` whether any other dispatcher command still needs `PYTHONUTF8=1`.
  4. Run the throwaway's `index-specs.py --validate` and `deploy-gate.py`.
  5. Delete the throwaway.
- **After merge.** Tell the Project A Orchestrator that `PYTHONUTF8=1` can be dropped after Project A's next upgrade, once the dogfood's finding is clean (wave-2 plan §7).

## Changelog

- 2026-09-25: created from IDEA-0028 (retitled 2026-09-25: Windows encoding hardening); widened by the Architect to `_git_capture`'s fail-open, which is security-relevant through FR-0013 AC-6, and to the two committed-file writes, both found in the grounding read.
- 2026-09-25: Neil approved the control-plane edit (maintainer-mode dispatch authorised) and ratified this FR's `neil`-tier DECs. No normative change.
