---
id: FR-0001
title: Profile-aware `bootstrap.py --upgrade` and append-only project registration
status: merged  # draft | ready | in-progress | in-review | merged | deprecated | blocked
owner: architect
depends_on: []  # list of FR IDs this depends on
tags: [bootstrap, profiles, template, tooling]
owns: []  # Footprint is hub-level (../../scripts/bootstrap.py etc.); the indexer rejects `..` segments, so it is documented under Notes instead. Empty on purpose.
reads: []  # See Notes for the hub-relative read set.
derived_from: null  # net-new (overlap check: carved out of parked IDEA-0060, not derived from it)
pattern: null
ac_state: {}
created: 2026-09-07
updated: 2026-09-07
---

# FR-0001: Profile-aware `bootstrap.py --upgrade` and append-only project registration

## Why

`bootstrap.py` applies a compliance profile (today: `phipa`) at creation time and then forgets it: `register_project()` writes only `name/path/created/stack/private`, and nothing project-local says "this project carries profile X". `--upgrade` walks `INFRA_DIRS` against `template/` alone, so on a profiled project it offers to replace the profile-sourced `.agent-team/hooks/phi_regex_check.py` with the template's base copy — and in `--yes` mode it does so silently. `projects/project-a` is the live case: it was bootstrapped with `--profile phipa`, its hook equals `profiles/phipa/phi_regex_check.py`, and a routine `--upgrade --yes` would downgrade a PHIPA control. Separately, `register_project()` round-trips `hub/projects.yaml` through `yaml.safe_dump`, which discards every inline comment in the registry (there are several, explaining why entries are private/submodules) and, on Windows, emitted CRLF endings into a repo that pins LF. The registry is hand-annotated; the tool should append, not rewrite.

## What

After this FR, the set of profiles applied to a project is recorded durably at bootstrap time, both in the project itself and in its registry entry, and can be backfilled onto projects created before this FR. `--upgrade` reads that record and treats profile-owned files as owned by the profile source rather than the template: it never proposes or applies the template base copy over a profile-owned file, syncs profile-owned files from `profiles/<name>/` using the same confirm/`--yes` semantics as template files, and verifies (without editing) that the profile's `settings.json` overlay and `AGENTS.md` block are still present. Unprofiled projects behave exactly as today. Registering a project appends a new entry to `hub/projects.yaml` while leaving every existing byte, comment, and line ending untouched.

## Acceptance criteria

Each AC is independently testable against a temporary hub checkout or a fixture project; none requires network or a real profiled project.

- **AC-1 (profile set is recorded at creation):** Given `bootstrap.py <name> "<desc>" --profile phipa`, after the run (a) the project contains a project-local profile record listing exactly `["phipa"]`, in a file under `.agent-team/` that `--upgrade` can read without consulting the hub registry, and (b) the new `hub/projects.yaml` entry carries `profiles: [phipa]`. Given the same command without `--profile`, the local record exists and lists an empty set, and the registry entry carries `profiles: []`. Multiple `--profile` flags record all names in the order given, deduplicated.

- **AC-2 (profile set is resolved on upgrade, with a defined fallback):** `--upgrade` determines the project's profile set from the project-local record. If the record is absent, it falls back to the registry entry (`hub/projects.yaml`, overlaid by `hub/projects.local.yaml` when present). If neither source names any profile, the project is treated as unprofiled and a single notice is printed stating that profile state is unrecorded and how to backfill it (AC-7). If both sources exist and disagree, `--upgrade` uses the project-local record and prints the disagreement; it does not silently pick one. Names not present under `profiles/` are rejected with the same error path `--profile` uses at creation.

- **AC-3 (profile-owned files are never overwritten with the template base copy):** For a project whose resolved profile set includes `phipa`, `--upgrade` compares `.agent-team/hooks/phi_regex_check.py` against `profiles/phipa/phi_regex_check.py`, never against `template/.agent-team/hooks/phi_regex_check.py`. When the project file equals the profile source it is reported as up to date (or omitted from the change list); when it differs, the diff shown and the content offered are the profile source's. There is no code path — interactive or `--yes` — that writes the template base copy of a profile-owned file into a profiled project. "Profile-owned" is defined per profile as the set of project-relative paths that profile installs; for `phipa` that set is exactly `.agent-team/hooks/phi_regex_check.py`.

- **AC-4 (profile-owned files sync from the profile source with standard semantics):** For a profile-owned file that differs from its profile source, interactive `--upgrade` shows the diff (project → profile) and applies the profile source only on explicit `y`; `--upgrade --yes` applies it and lists the path under "Updated". If a profile-owned file is missing from the project, it is offered/added from the profile source, not from the template. The summary distinguishes profile-sourced changes from template-sourced ones (e.g. an annotation such as `(from profile: phipa)`).

- **AC-5 (settings overlay is verified, not edited):** For each resolved profile that ships a `settings_overlay.json`, `--upgrade` checks that every hook entry in the overlay is present in the project's `.claude/settings.json` (structural containment, not byte equality). A missing entry is reported under a heading distinct from generic drift (e.g. "Profile overlay missing"), naming the profile and the entry. `.claude/settings.json` is never written by `--upgrade`, in any mode — the existing drift-warn-only policy is unchanged (interim per IDEA-0034). When the overlay is fully present, nothing is reported for it.

- **AC-6 (AGENTS.md profile block is verified, not edited):** For each resolved profile that ships an `AGENTS.md` block (for `phipa`: `phi_hygiene_block.md`), `--upgrade` reports one of three states: present and identical to the current profile text (silent), present but different (reported as "profile block differs", with a diff in interactive mode), or absent (reported as "profile block missing"). `AGENTS.md` is never written by `--upgrade`; it remains in `UPGRADE_EXCLUDE`.

- **AC-7 (backfill for pre-existing profiled projects):** `--upgrade <path> --profile <name>` (repeatable) is accepted. It validates the names against `profiles/`, writes the project-local record with exactly the given set (replacing any prior record), updates the project's `hub/projects.yaml` entry to carry `profiles: [...]` when that entry exists and can be located unambiguously — otherwise prints the exact line to add and continues — and then performs the profile-aware upgrade using that set. Backfilling `projects/project-a` with `--profile phipa` followed by `--upgrade projects/project-a --yes` results in zero changes to `.agent-team/hooks/phi_regex_check.py` and no "profile overlay missing" or "profile block missing" report (Project A's block is verbatim today).

- **AC-8 (`--yes` is unattended and safe):** On a profiled fixture project, `--upgrade --yes` completes without prompting, exits 0, and afterwards every profile-owned file equals its profile source and no file equals the template base copy of a profile-owned path. Its output includes a line naming the resolved profile set (e.g. `Profiles: phipa`) or `Profiles: (none)`.

- **AC-9 (unprofiled projects are unchanged):** On a fixture project whose resolved profile set is empty, `--upgrade` produces the same file-level decisions as before this FR: `.agent-team/hooks/phi_regex_check.py` is compared against and synced from the template copy, `.claude/settings.json` is drift-warned only, `AGENTS.md` is untouched, and no profile-related headings appear in the summary other than the single "unrecorded" notice from AC-2 when applicable.

- **AC-10 (registration is append-only and preserves the file):** Given a `hub/projects.yaml` containing comments (header, and comments nested inside entries) and LF line endings, `register_project()` for a new name produces a file whose content up to the appended entry is byte-identical to the original, whose appended entry is a valid list item under `projects:` with keys `name, path, created, stack, private, profiles` in that order, and which contains no `\r\n` on any platform. `yaml.safe_load` of the result yields the original entries plus the new one. Registering an already-registered name leaves the file byte-identical and prints the existing warning. `scripts/hub-index.py --check` still parses the resulting registry.

- **AC-11 (profile application is idempotent on settings.json):** Applying `profiles/phipa/settings_overlay.json` to a `.claude/settings.json` that already contains an identical hook entry (which `template/.claude/settings.json` does today) does not add a second copy of that entry. A fresh `--profile phipa` bootstrap therefore yields exactly one `phi_regex_check.py` PreToolUse hook. Distinct entries are still appended as today.

- **AC-12 (hub-level tests exist for both fixture shapes):** A pytest suite at the hub level (not under `template/tests/`) exercises AC-1, AC-3, AC-4, AC-8, AC-9, AC-10 and AC-11 using two synthetic fixture projects built in a temp directory: one profiled (`phipa` record + profile-sourced hook) and one unprofiled. Tests do not touch `projects/`, `hub/projects.yaml`, or any real project, and pass on Windows and POSIX (no shell-specific assumptions, no reliance on `core.autocrlf`). Tests carry `@covers FR-0001:AC-N` comments.

## Out of scope

- Generalising profiles beyond data hygiene (tier sets, ADR packs, `embedded-alayacare` / `greenfield-saas`) — that is IDEA-0060 (H12), of which this FR is the carved-out "upgrade respects the profile" clause.
- Auto-reconciling `.claude/settings.json` or `AGENTS.md` on upgrade (core/overlay split, hunk-level merge) — IDEA-0034. This FR only verifies and reports.
- The reverse leg (project → template harvest), `--upgrade --all`, and template-hash stamping — IDEA-0034.
- Adding new profiles or changing the content of `profiles/phipa/*`.
- Making `phi_regex_check.py` project-customisable in a way `--upgrade` preserves (the profile README's "edit the hook to adjust patterns" guidance is in tension with any sync; see Open questions).
- Wiring the new pytest suite into `.github/workflows/validate.yml` (a one-line follow-up; noted so it is not forgotten, but not gated here).
- Fixing `scripts/agent-status.py`'s cp1252 crash on Windows (IDEA-0028, unrelated).
- Committing the project-local record inside submodule projects (Project A, Project B) — the backfill writes the file; the submodule commit is a human step.

## Open questions

- **Q1:** Where is the canonical profile record — project-local marker, registry entry, or both?
  - **Default:** Both are written; the project-local record is canonical for `--upgrade` and the registry field is informational/for `/hub-status` (AC-2 precedence). Trade-off: the local record survives out-of-tree and `--no-register` projects and travels with a submodule; the registry field is visible cross-project without opening the project but is unavailable for `--no-register` projects and lives in a hand-annotated file that AC-10 says we should not rewrite. Writing both costs little; disagreements are surfaced, not resolved.

- **Q2:** Exact name/format of the project-local record.
  - **Default:** `.agent-team/profiles.yaml` with `profiles: [phipa]` (empty list when unprofiled). YAML matches every other `.agent-team/` config. It must be excluded from `--upgrade`'s template-sync walk (the template ships no such file, so today it would never be offered; the Developer should assert this rather than assume it).

- **Q3:** Should `--yes` overwrite a locally-edited profile-owned file with the profile source, given `profiles/phipa/README.md` invites per-project edits to the hook?
  - **Default:** Yes — mirror the template-file semantics exactly (AC-4). Anything else creates a third file class with its own rules. If per-project hook tuning turns out to matter, that is a profile-design question for IDEA-0060 (e.g. an exemptions file the hook reads, which the profile README already hints at).

- **Q4:** How does backfill update an existing registry entry (Project A's has comment lines inside the entry) without violating AC-10's byte-preservation?
  - **Default:** Targeted insertion of a single `  profiles: [phipa]` line immediately after the entry's `private:` line, touching no other bytes. If the entry cannot be located as a unique `- name: <name>` block, print the line and continue (AC-7). `yaml.safe_dump` is never used on this file again.

- **Q5:** Where do hub-level bootstrap tests live, given the hub has no `tests/` today?
  - **Default:** `<hub>/tests/unit/scripts/test_bootstrap.py`, mirroring `template/tests/unit/scripts/`. Run with `python -m pytest tests/` from the hub root. `bootstrap.py` imports `_console` from `scripts/`, so tests add `scripts/` to `sys.path` or use `importlib` with the same path.

## Dependencies

None. This FR is independent of FR-0002 and FR-0003+ being drafted in parallel; the CoS should confirm none of them declares a hub-relative footprint that includes `scripts/bootstrap.py` or `hub/projects.yaml`.

## Notes

- **Footprint (hub-relative; cannot be expressed in `owns:`/`reads:` because `spec_footprint.py` rejects `..` segments and this project is at `<hub>/projects/hub-tooling/`).**
  Owns: `scripts/bootstrap.py`, `hub/projects.yaml` (append/insert only), `tests/unit/scripts/test_bootstrap.py` (new), `profiles/phipa/README.md` (only if the "customisation" paragraph needs a one-line pointer to upgrade behaviour), `GETTING-STARTED.md` / `CONTRIBUTING.md` (`--upgrade --profile` mention).
  Reads: `template/**`, `profiles/phipa/**`, `hub/projects.local.yaml(.example)`, `scripts/hub-index.py` (registry loader, for AC-10 compatibility), `scripts/_console.py`.
- **Human approval at implementation time.** `scripts/bootstrap.py` is on the hub `CLAUDE.md` human-approval-only list. Neil has approved *drafting* this FR; the Developer must obtain explicit approval before the first edit to `scripts/bootstrap.py` lands, and the Reviewer should treat that approval as a merge precondition. Record it in the PR description.
- **Related parked ideas (not `derived_from`).** IDEA-0060 is the larger H12 item this was carved out of; its description names this FR's problem verbatim. IDEA-0034 governs the settings.json / AGENTS.md drift-warn interim policy that AC-5 and AC-6 deliberately keep; when IDEA-0034 lands, AC-5/AC-6 become auto-reconcile candidates.
- **Ground-truth facts the Developer should not re-derive:** `template/.agent-team/hooks/phi_regex_check.py` and `profiles/phipa/phi_regex_check.py` differ (comments, `CLAUDE.md` vs `AGENTS.md` wording); Project A's hook equals the profile copy. `template/.claude/settings.json` already wires the PHI hook for all projects (commit 567d864), which is why Project A's settings.json equals the template byte-for-byte and why AC-11 is needed. `hub/projects.yaml` is currently LF-only with 0 CRLF; `core.autocrlf=false`; no `.gitattributes`. `hub-index.py` reads entries as dicts and tolerates extra keys, so `profiles:` is safe to add.
- **Profile-owned file set is per profile, declared in code for now.** `apply_profiles()` hard-codes phipa's install steps; the Developer may express the owned-path set the same way (a small table keyed by profile name). Moving it into a `profiles/<name>/manifest.yaml` is a reasonable refactor but is not required by any AC and would touch every future profile's contract — defer unless it falls out naturally.
- **Windows.** `scripts/agent-status.py` may crash with a cp1252 encoding error on Windows (IDEA-0028); it did not during drafting, but do not depend on it in tests.

## Changelog

- 2026-09-07: created (Architect, dispatched by Chief of Staff; overlap check pre-answered as net-new, option c)
- 2026-09-07 — merged to main via fr/FR-0001 (feat ec85941, fix eb22e50, tests fdaec96 + f2ab789); Reviewer APPROVE round 2. Status ready -> merged (CoS bookkeeping). Project A backfill (--upgrade a downstream project --profile phipa) is a pending human step.
