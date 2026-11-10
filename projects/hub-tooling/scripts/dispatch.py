#!/usr/bin/env python3
"""
dispatch.py — Optional orchestration layer for multi-agent FR dispatch.

This is the headless multi-agent dispatcher. It reads the spec graph,
spawns per-FR agent sessions in isolated git worktrees, manages lockfiles
for idempotency, and owns the GitHub PR lifecycle (push, create, review).

Projects can use this script for fully automated agent waves, or ignore
it entirely and run agents interactively via slash commands.

Reads specs/FR-*.md frontmatter and spawns headless agent sessions in
per-FR worktrees. Idempotent via per-(FR, role) lockfile.

Two roles are dispatchable today:

  * dev (default) — picks FRs with status=ready whose depends_on are all
    in TERMINAL_STATUSES. Worktree branches off `main`.
  * rev           — picks FRs with status in {in-progress, in-review} for
    which a `claude/dev-FR-XXXX` branch exists locally and no Developer
    is currently running. Worktree branches off the Dev branch so the
    Reviewer's tree contains the Developer's diff.

The headless session can run on either of two harnesses:

  * claude-code (default) — `claude -p "/developer FR-XXXX"` (or `/reviewer`)
  * cursor               — `cursor-agent -p --force --trust --approve-mcps
                              --output-format stream-json "<rendered prompt>"`

Pick a harness with `--harness {claude-code,cursor}` or the env var
`DISPATCH_HARNESS`. All other dispatch logic (worktrees, venv
provisioning, locks, prune/kill, escalation surfacing) is
harness-agnostic.

Designed to run from a git post-merge hook on `main`, but safe to invoke
manually.

Usage:
  python scripts/dispatch.py tick                            # Dev wave, dry-run
  python scripts/dispatch.py tick --apply                    # Dev wave, spawn
  python scripts/dispatch.py tick --role rev                 # Reviewer wave, dry-run
  python scripts/dispatch.py tick --role rev --apply         # Reviewer wave, spawn
  python scripts/dispatch.py tick --harness cursor --apply   # Dev wave on Cursor
  python scripts/dispatch.py status                          # liveness/idle/dead per lock
  python scripts/dispatch.py prune                           # remove dead locks
  python scripts/dispatch.py kill FR-XXXX --role {dev,rev}   # force-terminate + remove lock
  python scripts/dispatch.py summary FR-XXXX --role {dev,rev}  # parsed log summary
  python scripts/dispatch.py finalize FR-XXXX --role dev     # push + open PR (dry-run)
  python scripts/dispatch.py finalize FR-XXXX --role dev --apply  # actually push + open
  python scripts/dispatch.py finalize FR-XXXX --role rev --apply  # post gh pr review
  python scripts/dispatch.py finalize-all --role dev --apply      # finalize every dev branch with a complete log
  python scripts/dispatch.py reconcile-merged                # show post-merge cleanup plan (dry-run)
  python scripts/dispatch.py reconcile-merged --apply        # flip merged FR status, prune worktrees/branches/locks
  python scripts/dispatch.py backfill FR-XXXX                # show one-shot Reviewer-backfill plan (dry-run)
  python scripts/dispatch.py backfill FR-XXXX --apply        # spawn Reviewer to write missing AC tests for an already-merged FR
  python scripts/dispatch.py finalize FR-XXXX --role bkf --apply  # push + open `test(FR-XXXX): backfill AC coverage` PR
  python scripts/dispatch.py maintain FR-XXXX                # show one-shot maintainer plan (dry-run)
  python scripts/dispatch.py maintain FR-XXXX --apply        # spawn Developer-in-maintainer-mode for a control-plane FR (footprint from `owns:`)
  python scripts/dispatch.py finalize FR-XXXX --role mnt --apply  # push + open `chore(FR-XXXX): <title>` PR

GitHub PR integration (finalize):
  Agents do NOT touch GitHub directly. The dispatcher owns:
    * `git push -u origin <branch>` (no force; round-2+ commits land as fast-forwards)
    * `gh pr create --draft --base main --head <branch> --body-file PR_BODY.md`
    * `gh pr review <num> {--approve|--request-changes|--comment} --body <reviewer text>`
  Finalize records the PR number in `_dispatch/<fr>.<role>.pr.json` so re-runs are
  idempotent (push happens; create no-ops; review is posted as a new review thread).

Prerequisites for finalize:
  * `gh` CLI installed and `gh auth status` green (run `gh auth login` if not)
  * a remote named `origin` configured on the repo
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Protocol

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Pipeline metrics log (FR-0002 / H6): spawn, run, wave and PR records emitted
# at the source. Optional import — a project whose scripts/ predates the module
# dispatches exactly as before — and emission is never load-bearing.
try:
    import metrics_log as _metrics
except ImportError:  # pragma: no cover
    _metrics = None

# env_preflight is the pure, read-only, stack-aware host pre-flight (FR-0011):
# Docker reachability, PATH tools, Windows app-control policy, host port
# collisions. Kept out of this file for the same reason as spec_footprint /
# stack_profile below — each check is importable and unit-testable without a
# dispatcher, a repo, or an agent.
# spec_footprint is the indexer's own pure-function glob validator
# (FR-0009:AC-5). Reused so the dispatcher and the indexer never disagree
# about which `owns:` entries are legal — required, not optional, since
# both scripts always ship together as sibling template files.
# stack_profile is the pure, read-only stack detector + closed Bash-grant
# table (FR-0010). Reused rather than re-implemented here so the closed
# vocabulary and grant table have exactly one definition.
import env_preflight
import spec_footprint
import stack_profile

# project_layout is FR-0023's one reader of `.agent-team/layout.yaml`; the
# dispatcher reads `footprint_root` only through it (FR-0024 AC-4, DEC-0031).
# Optional, as in `deploy-gate.py` and `index-specs.py`: a copy with no
# sibling `project_layout.py` behaves as `footprint_root: project`.
try:
    import project_layout as _project_layout
except ImportError:  # pragma: no cover
    _project_layout = None

# Cursor and Claude agents emit Unicode freely (em-dashes, arrows, smart
# quotes). On Windows, Python's default stdout encoding is cp1252 and any
# such character makes `print` raise UnicodeEncodeError mid-summary. Force
# UTF-8 with a lossy fallback so the dispatcher never crashes mid-output.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass


REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
DISPATCH_DIR = REPO_ROOT / "_dispatch"
ESCALATIONS_DIR = REPO_ROOT / "specs" / "_escalations"
LAST_TICK_FILE = DISPATCH_DIR / ".last-tick"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TERMINAL_STATUSES = {"done", "merged", "deployed"}
STALE_LOCK_SECONDS = 2 * 60 * 60
IDLE_LOG_THRESHOLD_SECONDS = 5 * 60

SLASH_COMMAND_NAMES = {
    "dev": "developer",
    "rev": "reviewer",
    # `bkf` is a one-shot Reviewer-in-backfill-mode used when an FR was
    # merged without proper @covers test coverage (the deploy-gate gap
    # surfaced after `reconcile-merged` flips status to merged). Branches
    # off `main` (the dev work is already there); opens a small follow-up
    # PR titled `test(FR-XXXX): backfill AC coverage`.
    "bkf": "reviewer-backfill",
    # `mnt` is a one-shot Developer-in-maintainer-mode used for FRs whose
    # declared `owns:` footprint intersects the control-plane paths every
    # other role denies (`.agent-team/**`, the gate/indexer/dispatcher
    # scripts). Its writable footprint is derived from that FR's `owns:` —
    # see MNT_PROTECTED_GLOBS and mnt_permission_rules. Dev-shaped:
    # branches off `main`, authors PR_BODY.md, opens its own PR.
    "mnt": "maintainer",
    # `docs` regenerates the client-doc projection from the doc spec + spec
    # graph and emits ## FINDINGS instead of editing specs. Its mechanical
    # deny on specs/** comes from ROLE_PERMISSIONS below when dispatched into a
    # worktree; interactively it is a role contract. Dispatch wiring (one-shot
    # after reconcile-merged) lands in Lockstep S-6.
    "docs": "docs",
    # `gat` is a one-shot Architect gate-review session (FR-0008:AC-6): a
    # narrow-footprint spawn (writable only: the one declared gate's
    # evidence file) whose worktree branches off the implementation
    # branch's current tip. Dispatched per-gate, never tick-scheduled.
    "gat": "gate-review",
}

# Role -> Claude Code --model alias. The Reviewer and its backfill variant run
# on the stronger model (adversarial coverage review benefits most from it);
# the implementation roles (dev, mnt) run on the faster model. Override per
# role with env DISPATCH_MODEL_<ROLE> (e.g. DISPATCH_MODEL_DEV=opus). A role
# absent from this map and unset in the env gets no --model flag, so the
# harness default applies. Only the Claude Code adapter consumes this; Cursor
# selects models through its own config.
ROLE_MODEL: dict[str, str] = {
    "dev": "sonnet",
    "rev": "opus",
    "bkf": "opus",
    "gat": "opus",
    "mnt": "sonnet",
    # NOTE: `docs` is intentionally absent until it is dispatched (Lockstep
    # S-6). When added, it must equal the `model:` in the generated docs
    # command frontmatter (sonnet) so the interactive and dispatch model
    # choices do not drift.
}


def _resolve_model(role: str) -> str | None:
    """Resolve the Claude Code --model alias for a role.

    Env override DISPATCH_MODEL_<ROLE> (role uppercased) wins; otherwise
    ROLE_MODEL supplies the default. Returns None when neither is set, in
    which case the caller passes no --model flag and the harness default
    applies.
    """
    override = os.environ.get(f"DISPATCH_MODEL_{role.upper()}")
    if override and override.strip():
        return override.strip()
    return ROLE_MODEL.get(role)


DEFAULT_HARNESS = os.environ.get("DISPATCH_HARNESS", "claude-code")

# Worktree venv configuration. Override via environment variables or edit
# these defaults to match your project's dependency footprint. Defined here
# (before the adapter classes) because ROLE_PERMISSIONS interpolates
# VENV_DIRNAME at class-definition time.
VENV_DIRNAME = os.environ.get("DISPATCH_VENV_DIRNAME", ".venv-dispatch")
VENV_PACKAGES = (os.environ.get("DISPATCH_VENV_PACKAGES") or "pyyaml,ruff,pytest").split(",")
VENV_PYTHON_VERSION = os.environ.get("DISPATCH_VENV_PYTHON", "3.11")

# Paths every role's harness permissions deny. `mnt` un-denies exactly the
# subset the target FR declares in `owns:` — never more, and never CLAUDE.md.
MNT_PROTECTED_GLOBS = (
    ".agent-team/**",
    "scripts/deploy-gate.py",
    "scripts/index-specs.py",
    "scripts/dispatch.py",
    "scripts/agent-status.py",
    "CLAUDE.md",
)

# An agent that can rewrite the working agreement can rewrite its own
# constraints, so this is denied to `mnt` whatever an FR claims to own.
MNT_NEVER_WRITABLE = ("CLAUDE.md",)

# Paths the harness write-guards on its own, independently of any settings
# file. Granting one reads as permission the agent does not actually have,
# which pushes it toward writing the file from an interpreter instead. A
# `mnt` spawn whose `owns:` intersects these is warned about by name, and
# the canonical source is named in the warning.
HARNESS_GUARDED_GLOBS = (".claude/**",)

# `.claude/commands/<x>.md` is generated from `.agent-team/commands/<x>.md`
# by the hub bootstrapper, which is the sanctioned way to change it.
HARNESS_GUARDED_SOURCE_HINT = {
    ".claude/commands/": (
        "edit `.agent-team/commands/<name>.md` (the canonical source) and "
        "regenerate with `python <hub>/scripts/bootstrap.py --upgrade <project>`"
    ),
}

# Interpreters and entrypoints `mnt` may invoke. `dev` holds a blanket
# `Bash(python *)`, which makes every Edit/Write deny bypassable by writing
# the file from an interpreter — decorative denials in a role whose deny list
# guards the control plane. `mnt` therefore inherits `dev`'s Bash surface
# minus anything that executes arbitrary code or redirects output, plus these
# sanctioned entrypoints.
MNT_INTERPRETERS = (
    "python",
    "python3",
    "py",
    f"{VENV_DIRNAME}/Scripts/python.exe",
    f"{VENV_DIRNAME}/Scripts/python",
    f"{VENV_DIRNAME}/bin/python",
)
MNT_SANCTIONED_ENTRYPOINTS = (
    "scripts/deploy-gate.py",
    "scripts/index-specs.py",
    "scripts/dispatch.py",
    "scripts/agent-status.py",
    "-m pytest",
    "-m ruff",
)

# `dev` Bash grants `mnt` does not inherit. Interpreters and package
# installers execute arbitrary code; `echo` and the compound-shell wildcards
# reach denied paths through redirection.
MNT_BASH_NOT_INHERITED = (
    "Bash(python *)",
    "Bash(python3 *)",
    "Bash(py *)",
    "Bash(pip *)",
    f"Bash({VENV_DIRNAME}/Scripts/python.exe *)",
    f"Bash({VENV_DIRNAME}/Scripts/python *)",
    f"Bash({VENV_DIRNAME}/Scripts/pip *)",
    f"Bash({VENV_DIRNAME}/bin/python *)",
    f"Bash({VENV_DIRNAME}/bin/pip *)",
    "Bash(echo *)",
    "Bash(* && *)",
    "Bash(* || *)",
    "Bash(* | *)",
    "Bash(* ; *)",
)

# Deny beats allow, so these are belt-and-braces over the narrowed allow
# list: they state the intent explicitly rather than relying on absence.
MNT_BASH_DENIES = (
    "Bash(python -c*)",
    "Bash(python3 -c*)",
    "Bash(py -c*)",
    "Bash(python)",
    "Bash(python3)",
    "Bash(pip *)",
    "Bash(uv *)",
    "Bash(node *)",
    "Bash(npx *)",
    "Bash(bash *)",
    "Bash(sh *)",
    "Bash(powershell *)",
    "Bash(pwsh *)",
    "Bash(cmd *)",
    "Bash(perl *)",
    "Bash(ruby *)",
    "Bash(tee *)",
    "Bash(sed -i*)",
    "Bash(cp *)",
    "Bash(mv *)",
)


# ---------------------------------------------------------------------------
# Harness adapter abstraction
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AgentLogSummary:
    """Harness-agnostic, post-hoc view of a single agent run's NDJSON log."""

    result_subtype: str | None = None
    is_error: bool = False
    tool_counts: dict[str, int] = dataclasses.field(default_factory=dict)
    error_objs: list[dict] = dataclasses.field(default_factory=list)
    last_text: str | None = None
    # FR-0002 AC-3: per-tool error counts and the harness `result` line's
    # usage block (None when the log carries none — never estimated).
    tool_error_counts: dict[str, int] = dataclasses.field(default_factory=dict)
    tokens_in: int | None = None
    tokens_out: int | None = None


def _apply_usage(s: AgentLogSummary, usage: object) -> None:
    """Populate token counts from a harness `usage` object (Claude Code's
    `result` line carries one; Cursor's may). Input tokens sum every
    input-side counter so cache reads are not silently dropped."""
    if not isinstance(usage, dict):
        return
    in_keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    if any(isinstance(usage.get(k), int) for k in in_keys):
        s.tokens_in = sum(v for v in (usage.get(k) for k in in_keys) if isinstance(v, int))
    if isinstance(usage.get("output_tokens"), int):
        s.tokens_out = usage["output_tokens"]


class HarnessAdapter(Protocol):
    name: str
    binary_name: str

    def write_worktree_settings(
        self, wt_path: Path, role: str, fr_id: str, gate_id: str | None = None
    ) -> None: ...
    def spawn(
        self,
        fr_id: str,
        role: str,
        wt_path: Path,
        log_path: Path,
        extra_prompt: str | None = None,
        gate_id: str | None = None,
    ) -> tuple[str, int | None]: ...
    def parse_log(self, log_path: Path) -> AgentLogSummary: ...
    def dry_run_preview(
        self, fr_id: str, role: str, wt_preview: Path, gate_id: str | None = None
    ) -> str: ...


def _slash_command_body(slash_name: str) -> str:
    """Return the body of `.claude/commands/<slash_name>.md` with YAML
    frontmatter stripped. Both harnesses derive their role-prompt template
    from this single source so the role definition isn't duplicated.
    """
    p = COMMANDS_DIR / f"{slash_name}.md"
    if not p.exists():
        raise FileNotFoundError(f"slash command template missing: {p}")
    text = p.read_text(encoding="utf-8")
    m = FRONTMATTER_PATTERN.match(text)
    if m:
        text = text[m.end() :]
    return text.strip()


# ---------------------------------------------------------------------------
# Claude Code adapter (preserves today's behaviour byte-for-byte)
# ---------------------------------------------------------------------------


class ClaudeCodeAdapter:
    """Headless `claude -p '/role FR-XXXX'` invocation.

    Permissions are written into each worktree as .claude/settings.local.json
    rather than passed via --allowedTools. This avoids the brittleness of CLI
    escaping on Windows and matches the format the agent itself reaches for
    (and which survives across resume / continue sessions).
    """

    name = "claude-code"
    binary_name = "claude"

    # Per-role settings are merged into the worktree's
    # .claude/settings.local.json at worktree-create time. Globs use
    # Claude Code's permission syntax.
    ROLE_PERMISSIONS: dict[str, dict[str, list[str]]] = {
        # Docs role (Lockstep N-1). Regenerates the client-doc projection and
        # emits ## FINDINGS; it must never touch the spec graph, source, tests,
        # or the control plane. The allow-list is deliberately narrow: only the
        # generated projection (docs/client), the doc spec (docs/_spec), the
        # renderer's stamp/gap outputs, and FINDINGS.md. The hand-maintained
        # docs (docs/architecture, docs/sources, docs/workflow, …) are NOT
        # allowed and NOT broadly denied — they fall through to default-deny,
        # so a `Deny(docs/**)` (which would also kill docs/client) is avoided.
        "docs": {
            "allow": [
                "Read",
                "Glob",
                "Grep",
                "TodoWrite",
                # The generated projection + doc spec + renderer outputs.
                "Edit(docs/client/**)",
                "Write(docs/client/**)",
                "Edit(docs/_spec/**)",
                "Write(docs/_spec/**)",
                "Write(docs/_gaps.md)",
                "Write(docs/_render.json)",
                # Discrepancies exit via FINDINGS, never via a spec edit.
                "Edit(FINDINGS.md)",
                "Write(FINDINGS.md)",
                "Edit(PR_BODY.md)",
                "Write(PR_BODY.md)",
                # Runs the renderer / lint.
                "Bash(python *)",
                "Bash(python3 *)",
                "Bash(py *)",
                f"Bash({VENV_DIRNAME}/Scripts/python.exe *)",
                f"Bash({VENV_DIRNAME}/Scripts/python *)",
                f"Bash({VENV_DIRNAME}/bin/python *)",
                # Filesystem inspection.
                "Bash(ls *)",
                "Bash(ls)",
                "Bash(cat *)",
                "Bash(head *)",
                "Bash(tail *)",
                "Bash(echo *)",
                "Bash(pwd)",
                # Git: inspect + local commit (dispatcher owns push & PR).
                "Bash(git status*)",
                "Bash(git diff*)",
                "Bash(git log*)",
                "Bash(git show*)",
                "Bash(git add *)",
                "Bash(git commit *)",
                "Bash(git commit)",
                "Bash(git checkout *)",
                "Bash(git branch*)",
                "Bash(git restore *)",
                # Compound shells that reduce to permitted parts.
                "Bash(* && *)",
                "Bash(* || *)",
                "Bash(* | *)",
                "Bash(* ; *)",
            ],
            "deny": [
                # The whole point of the role: never the spec graph, source,
                # tests, or the control plane. Discrepancies exit via FINDINGS.
                "Edit(specs/**)",
                "Write(specs/**)",
                "Edit(src/**)",
                "Write(src/**)",
                "Edit(tests/**)",
                "Write(tests/**)",
                "Edit(.agent-team/**)",
                "Write(.agent-team/**)",
                "Edit(scripts/**)",
                "Write(scripts/**)",
                "Edit(CLAUDE.md)",
                "Write(CLAUDE.md)",
                "Edit(AGENTS.md)",
                "Write(AGENTS.md)",
                # Destructive git — denied to every role.
                "Bash(git push*)",
                "Bash(git reset --hard*)",
                "Bash(rm -rf*)",
            ],
        },
        "dev": {
            "allow": [
                # Pure read tools — always safe
                "Read",
                "Glob",
                "Grep",
                "TodoWrite",
                # Production code, specs (frontmatter only), docs, PR body
                "Edit(src/**)",
                "Write(src/**)",
                "Edit(specs/FR-*.md)",
                "Edit(docs/**)",
                "Write(docs/**)",
                "Edit(PR_BODY.md)",
                "Write(PR_BODY.md)",
                # Repo-root scratch files agents commonly need (e.g. AC scripts
                # whose final home is scripts/ but which the dev can't write to
                # directly — they land at root and the next role relocates).
                "Edit(*.py)",
                "Write(*.py)",
                "Edit(*.md)",
                "Write(*.md)",
                # Test fixtures + conftest are infrastructure, not test code.
                # Test files themselves remain Reviewer-only (see deny list).
                "Edit(tests/fixtures/**)",
                "Write(tests/fixtures/**)",
                "Edit(tests/conftest.py)",
                "Write(tests/conftest.py)",
                # Docker, deploy, and infrastructure config files
                "Edit(deploy/**)",
                "Write(deploy/**)",
                "Edit(.dockerignore)",
                "Write(.dockerignore)",
                "Edit(Dockerfile*)",
                "Write(Dockerfile*)",
                "Edit(docker-compose*)",
                "Write(docker-compose*)",
                "Edit(*.yaml)",
                "Write(*.yaml)",
                "Edit(*.yml)",
                "Write(*.yml)",
                "Edit(*.toml)",
                "Write(*.toml)",
                "Edit(*.cfg)",
                "Write(*.cfg)",
                "Edit(*.txt)",
                "Write(*.txt)",
                "Edit(*.sh)",
                "Write(*.sh)",
                # Python / venv / test runners — both system python and the
                # pre-provisioned worktree venv (see VENV_DIRNAME)
                "Bash(python *)",
                "Bash(python3 *)",
                "Bash(py *)",
                f"Bash({VENV_DIRNAME}/Scripts/python.exe *)",
                f"Bash({VENV_DIRNAME}/Scripts/python *)",
                f"Bash({VENV_DIRNAME}/Scripts/pip *)",
                f"Bash({VENV_DIRNAME}/Scripts/ruff *)",
                f"Bash({VENV_DIRNAME}/Scripts/pytest *)",
                f"Bash({VENV_DIRNAME}/bin/python *)",
                f"Bash({VENV_DIRNAME}/bin/pip *)",
                f"Bash({VENV_DIRNAME}/bin/ruff *)",
                f"Bash({VENV_DIRNAME}/bin/pytest *)",
                "Bash(ruff *)",
                "Bash(pytest *)",
                "Bash(pip *)",
                # Filesystem inspection
                "Bash(ls *)",
                "Bash(ls)",
                "Bash(cat *)",
                "Bash(head *)",
                "Bash(tail *)",
                "Bash(echo *)",
                "Bash(pwd)",
                "Bash(where *)",
                "Bash(which *)",
                # Git: status/inspect, plus add/commit/checkout/branch/show/stash
                # (push/origin handled below by deny-list; see Notes)
                "Bash(git status*)",
                "Bash(git diff*)",
                "Bash(git log*)",
                "Bash(git show*)",
                "Bash(git remote*)",
                "Bash(git add *)",
                "Bash(git commit *)",
                "Bash(git commit)",
                "Bash(git checkout *)",
                "Bash(git checkout)",
                "Bash(git branch*)",
                "Bash(git stash*)",
                "Bash(git restore *)",
                "Bash(git reset)",
                # Push + GitHub CLI removed: dispatcher owns push & PR creation.
                # Agents commit locally and write PR_BODY.md; `finalize` does the rest.
                # Compound shells that reduce to permitted parts. Claude Code
                # interprets `Bash(* && *)` etc. as a permission to allow
                # multi-segment commands provided each segment matches an
                # individually allowed pattern. This keeps `cd path && python …`
                # from popping permission prompts.
                "Bash(* && *)",
                "Bash(* || *)",
                "Bash(* | *)",
                "Bash(* ; *)",
            ],
            "deny": [
                # Spec graph + role boundaries (universal)
                "Edit(.agent-team/**)",
                "Write(.agent-team/**)",
                # Specific gate / dispatch scripts only — bootstrap/setup
                # scripts an FR may need to author live elsewhere under
                # scripts/ and stay write-allowable.
                "Edit(scripts/deploy-gate.py)",
                "Write(scripts/deploy-gate.py)",
                "Edit(scripts/index-specs.py)",
                "Write(scripts/index-specs.py)",
                "Edit(scripts/dispatch.py)",
                "Write(scripts/dispatch.py)",
                "Edit(scripts/agent-status.py)",
                "Write(scripts/agent-status.py)",
                "Edit(CLAUDE.md)",
                "Write(CLAUDE.md)",
                # Developer must NOT write tests — that's the Reviewer's job.
                # Fixtures and conftest are explicitly allowed above.
                "Edit(tests/test_*.py)",
                "Write(tests/test_*.py)",
                # Destructive git ops
                "Bash(git push --force*)",
                "Bash(git push -f*)",
                "Bash(git reset --hard*)",
                "Bash(rm -rf*)",
                "Bash(rm -r *)",
            ],
        },
        "rev": {
            "allow": [
                # Pure read tools — always safe
                "Read",
                "Glob",
                "Grep",
                "TodoWrite",
                # Tests are the Reviewer's primary deliverable.
                "Edit(tests/**)",
                "Write(tests/**)",
                # Review artefact + spec frontmatter (status flips to
                # in-review / approved are allowed; AC body is Architect-only)
                "Edit(REVIEW.md)",
                "Write(REVIEW.md)",
                "Edit(specs/FR-*.md)",
                # Repo-root scratch the Reviewer commonly drafts
                "Edit(*.md)",
                "Write(*.md)",
                # Same Python / venv / test-runner posture as Dev so the
                # Reviewer can run pytest, ruff, the deploy gate, etc.
                "Bash(python *)",
                "Bash(python3 *)",
                "Bash(py *)",
                f"Bash({VENV_DIRNAME}/Scripts/python.exe *)",
                f"Bash({VENV_DIRNAME}/Scripts/python *)",
                f"Bash({VENV_DIRNAME}/Scripts/pip *)",
                f"Bash({VENV_DIRNAME}/Scripts/ruff *)",
                f"Bash({VENV_DIRNAME}/Scripts/pytest *)",
                f"Bash({VENV_DIRNAME}/bin/python *)",
                f"Bash({VENV_DIRNAME}/bin/pip *)",
                f"Bash({VENV_DIRNAME}/bin/ruff *)",
                f"Bash({VENV_DIRNAME}/bin/pytest *)",
                "Bash(ruff *)",
                "Bash(pytest *)",
                "Bash(pip *)",
                # Filesystem inspection
                "Bash(ls *)",
                "Bash(ls)",
                "Bash(cat *)",
                "Bash(head *)",
                "Bash(tail *)",
                "Bash(echo *)",
                "Bash(pwd)",
                "Bash(where *)",
                "Bash(which *)",
                # Git: same posture as Dev (commit/push the rev branch,
                # inspect diffs); destructive variants denied below.
                "Bash(git status*)",
                "Bash(git diff*)",
                "Bash(git log*)",
                "Bash(git show*)",
                "Bash(git remote*)",
                "Bash(git add *)",
                "Bash(git commit *)",
                "Bash(git commit)",
                "Bash(git checkout *)",
                "Bash(git checkout)",
                "Bash(git branch*)",
                "Bash(git stash*)",
                "Bash(git restore *)",
                "Bash(git reset)",
                # Push + GitHub CLI removed: dispatcher owns push & PR creation.
                # Reviewer feedback flows through `finalize --role rev`.
                # Compound shells with each segment individually permitted
                "Bash(* && *)",
                "Bash(* || *)",
                "Bash(* | *)",
                "Bash(* ; *)",
            ],
            "deny": [
                # Reviewer must NOT modify production code — kicks back via
                # PR review state, doesn't fix.
                "Edit(src/**)",
                "Write(src/**)",
                # Same protected scripts as Dev
                "Edit(.agent-team/**)",
                "Write(.agent-team/**)",
                "Edit(scripts/deploy-gate.py)",
                "Write(scripts/deploy-gate.py)",
                "Edit(scripts/index-specs.py)",
                "Write(scripts/index-specs.py)",
                "Edit(scripts/dispatch.py)",
                "Write(scripts/dispatch.py)",
                "Edit(scripts/agent-status.py)",
                "Write(scripts/agent-status.py)",
                "Edit(CLAUDE.md)",
                "Write(CLAUDE.md)",
                # Reviewer must NOT modify the Developer's PR_BODY — they
                # respond via gh pr review.
                "Edit(PR_BODY.md)",
                "Write(PR_BODY.md)",
                # Destructive git ops
                "Bash(git push --force*)",
                "Bash(git push -f*)",
                "Bash(git reset --hard*)",
                "Bash(rm -rf*)",
                "Bash(rm -r *)",
            ],
        },
    }
    # `bkf` (Reviewer in backfill mode) runs against an already-merged FR.
    # Same surface as `rev` (write tests, run gate, draft PR_BODY) but
    # tighter: no spec edits (FR is at terminal status), and PR_BODY is
    # the agent's own deliverable rather than the Developer's, so allow
    # writing it.
    ROLE_PERMISSIONS["bkf"] = {
        "allow": [a for a in ROLE_PERMISSIONS["rev"]["allow"] if a != "Edit(specs/FR-*.md)"]
        + ["Edit(PR_BODY.md)", "Write(PR_BODY.md)"],
        "deny": [d for d in ROLE_PERMISSIONS["rev"]["deny"] if d not in ("Edit(PR_BODY.md)", "Write(PR_BODY.md)")]
        + ["Edit(specs/**)", "Write(specs/**)"],
    }

    def mnt_permissions(
        self, fr_id: str, *, anchor: str = ""
    ) -> dict[str, list[str]] | None:
        """`dev`'s surface, re-scoped to the target FR's `owns:` footprint.

        `anchor` (FR-0024 AC-5) prefixes every `owns:`-derived grant — "" for
        today's relative rules, an absolute rule root for a repo-rooted
        footprint in a subdirectory project; denies stay relative.

        Returns None when the FR declares no `owns:` — `mnt` has nothing to
        derive a footprint from and must not run.

        Two ways this is *narrower* than `dev`, both required to make the
        derived footprint enforced rather than advisory: arbitrary interpreter
        invocation is replaced by a sanctioned entrypoint list, and `specs/**`
        is denied outright — an FR body is the Architect's, and
        `reconcile-merged` owns the status flip, so a `mnt` run has no reason
        to touch one. That also keeps every path a `mnt` branch touches inside
        `owns:`.
        """
        owns = fr_owns_globs(fr_id)
        if not owns:
            return None
        granted, protected_denies = mnt_permission_rules(owns)
        base = self.ROLE_PERMISSIONS["dev"]
        keep = [d for d in base["deny"] if not d.startswith(("Edit(", "Write("))]
        inherited = [
            a
            for a in base["allow"]
            if a not in MNT_BASH_NOT_INHERITED and a != "Edit(specs/FR-*.md)"
        ]
        tools = detected_stack_tools()
        perms = {
            "allow": inherited
            + _mnt_bash_allow()
            + [f"Edit({anchor}{g})" for g in granted]
            + [f"Write({anchor}{g})" for g in granted],
            # Rebuild the write denials from the derived protected set; keep
            # the non-path denials (destructive git) exactly as `dev` has them.
            "deny": [f"Edit({d})" for d in protected_denies]
            + [f"Write({d})" for d in protected_denies]
            + ["Edit(tests/test_*.py)", "Write(tests/test_*.py)"]
            + ["Edit(specs/**)", "Write(specs/**)"]
            # @implements FR-0010:AC-6 — uv/node/npx lift when the stack
            # declares them; every other entry (Bash(pip *) in particular)
            # is unconditional.
            + _mnt_bash_denies(tools)
            + keep,
        }
        # @implements FR-0010:AC-4
        return _union_grants(perms, stack_profile.stack_bash_grants(tools))

    def dev_permissions(
        self, fr_id: str, *, anchor: str = ""
    ) -> dict[str, list[str]]:
        """`dev`'s static grants unioned with the FR's `owns:` footprint.
        `anchor` prefixes the `owns:` grants only (FR-0024 AC-5).

        @implements FR-0009:AC-1
        @implements FR-0009:AC-2
        @implements FR-0009:AC-4

        Withheld/protected globs (AC-2) get no grant at all — no narrowing,
        the static deny list is untouched. An FR with no (valid) `owns:`
        degrades to exactly the static `dev` grants (AC-4): unlike
        `mnt_permissions`, this never returns None — `dev` always runs.
        Malformed `owns:` (AC-5) is refused earlier, in
        `ensure_role_worktree`, before this is ever called for a real
        spawn; if it is called anyway, the safe fallback is the static
        grants only (an empty `granted` list).
        """
        base = self.ROLE_PERMISSIONS["dev"]
        granted = dev_owns_derivation(fr_id)["granted"]
        perms = {
            "allow": list(base["allow"])
            + [f"Edit({anchor}{g})" for g in granted]
            + [f"Write({anchor}{g})" for g in granted],
            "deny": list(base["deny"]),
        }
        # @implements FR-0010:AC-4
        return _union_grants(
            perms, stack_profile.stack_bash_grants(detected_stack_tools())
        )

    def gat_permissions(self, fr_id: str, gate_id: str | None) -> dict[str, list[str]]:
        """Architect gate-review footprint (FR-0008:AC-6): exactly the one
        declared gate's evidence file, plus read-only inspection. Nothing
        else is granted (implicit default-deny covers the rest, the same
        mechanism every other role's unlisted paths rely on) — in
        particular no blanket `specs/**` deny, which would also deny the
        one path this role exists to write.
        """
        evidence = _gate_evidence_path(fr_id, gate_id or "")
        return {
            "allow": [
                "Read", "Glob", "Grep", "TodoWrite",
                f"Edit({evidence})", f"Write({evidence})",
                "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
                "Bash(ls *)", "Bash(ls)", "Bash(cat *)", "Bash(pwd)",
            ],
            "deny": [
                "Edit(.agent-team/**)", "Write(.agent-team/**)",
                "Edit(scripts/deploy-gate.py)", "Write(scripts/deploy-gate.py)",
                "Edit(scripts/index-specs.py)", "Write(scripts/index-specs.py)",
                "Edit(scripts/dispatch.py)", "Write(scripts/dispatch.py)",
                "Edit(scripts/agent-status.py)", "Write(scripts/agent-status.py)",
                "Edit(CLAUDE.md)", "Write(CLAUDE.md)",
                "Edit(PR_BODY.md)", "Write(PR_BODY.md)",
                "Bash(git push --force*)", "Bash(git push -f*)",
                "Bash(git reset --hard*)", "Bash(rm -rf*)", "Bash(rm -r *)",
            ],
        }

    def write_worktree_settings(
        self, wt_path: Path, role: str, fr_id: str, gate_id: str | None = None
    ) -> None:
        # @implements FR-0024:AC-5 — a repo-rooted footprint in a
        # subdirectory project: the `owns:` grants become absolute rules
        # anchored at the worktree root, and that root joins the session's
        # additional directories. "" (every other case) changes nothing; the
        # keyword is passed only when set, so a narrower override still works.
        anchor = (
            _absolute_grant_anchor(wt_path) if role in ("dev", "rev", "bkf", "mnt") else ""
        )
        owns_kw = {"anchor": anchor} if anchor else {}
        if role == "mnt":
            perms = self.mnt_permissions(fr_id, **owns_kw)
        elif role == "dev":
            # @implements FR-0009:AC-6 — re-derives from `owns:` on every
            # call, including worktree reuse (`ensure_role_worktree` calls
            # this unconditionally on both the create and the reuse path).
            perms = self.dev_permissions(fr_id, **owns_kw)
        elif role in ("rev", "bkf"):
            # @implements FR-0010:AC-5
            base = self.ROLE_PERMISSIONS[role]
            perms = owns_derived_permissions(role, base, fr_id, **owns_kw)
            perms = _union_grants(
                perms, stack_profile.stack_bash_grants(detected_stack_tools())
            )
        elif role == "gat":
            # @implements FR-0008:AC-6
            perms = self.gat_permissions(fr_id, gate_id)
        else:
            perms = self.ROLE_PERMISSIONS.get(role)
        if perms is None:
            return
        # @implements FR-0024:AC-2 — Claude Code reads the file from the
        # session's starting directory, the project inside the worktree.
        settings_dir = _worktree_project_root(wt_path) / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        payload: dict = {"permissions": {"allow": perms["allow"], "deny": perms["deny"]}}
        if anchor:
            payload["permissions"]["additionalDirectories"] = [
                Path(os.path.realpath(wt_path)).as_posix()
            ]
        settings_path = settings_dir / "settings.local.json"
        settings_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        # @implements FR-0015:AC-4
        _record_settings_digest(fr_id, role, settings_path)

    def spawn(
        self,
        fr_id: str,
        role: str,
        wt_path: Path,
        log_path: Path,
        extra_prompt: str | None = None,
        gate_id: str | None = None,
    ) -> tuple[str, int | None]:
        claude_bin = shutil.which(self.binary_name)
        if claude_bin is None:
            return ("binary-not-found", None)
        slash = SLASH_COMMAND_NAMES.get(role, role)
        # `extra_prompt` carries a generated rework brief on kick-back rounds.
        # It is appended after the slash invocation on its own lines so
        # `$ARGUMENTS` still resolves to the bare FR id.
        # @implements FR-0008:AC-6 — the gate-review command takes the FR id
        # and the gate id as arguments.
        args = f"{fr_id} {gate_id}" if gate_id else fr_id
        prompt = f"/{slash} {args}"
        if extra_prompt:
            prompt = f"{prompt}\n\n{extra_prompt}"
        cmd = [
            claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            # @implements FR-0028:AC-1 — pinned, never configurable (AC-2): the
            # worktree's permission file is the whole policy whatever the
            # host's `defaultMode`.
            "--permission-mode",
            "default",
        ]
        model = _resolve_model(role)
        if model:
            cmd += ["--model", model]
        log_fh = log_path.open("wb")
        try:
            # @implements FR-0024:AC-2 — the agent starts in the project.
            proc = subprocess.Popen(
                cmd,
                cwd=_worktree_project_root(wt_path),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            log_fh.close()
            return ("spawn-failed", None)
        return ("spawned", proc.pid)

    def dry_run_preview(
        self, fr_id: str, role: str, wt_preview: Path, gate_id: str | None = None
    ) -> str:
        slash = SLASH_COMMAND_NAMES.get(role, role)
        model = _resolve_model(role)
        model_note = f"; model={model}" if model else ""
        args = f"{fr_id} {gate_id}" if gate_id else fr_id
        # @implements FR-0024:AC-2
        cwd = _worktree_project_root(wt_preview)
        return (
            f"claude -p '/{slash} {args}'  "
            f"(cwd={cwd}; perms via .claude/settings.local.json{model_note})"
        )

    def parse_log(self, log_path: Path) -> AgentLogSummary:
        s = AgentLogSummary()
        tool_names_by_id: dict[str, str] = {}
        with log_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "assistant":
                    for c in obj.get("message", {}).get("content", []) or []:
                        if c.get("type") == "text":
                            s.last_text = c.get("text", "")
                        elif c.get("type") == "tool_use":
                            name = c.get("name", "?")
                            s.tool_counts[name] = s.tool_counts.get(name, 0) + 1
                            if c.get("id"):
                                tool_names_by_id[str(c["id"])] = name
                elif t == "result":
                    s.result_subtype = obj.get("subtype") or "unknown"
                    s.is_error = bool(obj.get("is_error"))
                    _apply_usage(s, obj.get("usage"))
                elif t == "user":
                    for c in obj.get("message", {}).get("content", []) or []:
                        if c.get("type") == "tool_result" and c.get("is_error"):
                            s.error_objs.append(c)
                            name = tool_names_by_id.get(str(c.get("tool_use_id", "")), "?")
                            s.tool_error_counts[name] = s.tool_error_counts.get(name, 0) + 1
        return s


# ---------------------------------------------------------------------------
# Cursor adapter
# ---------------------------------------------------------------------------


class CursorAdapter:
    """Headless `cursor-agent -p ...` invocation.

    Differences vs Claude Code:
      * Permissions live at <worktree>/.cursor/cli.json with token syntax
        Shell(cmd[:args]), Read(glob), Write(glob), WebFetch(domain),
        Mcp(server:tool). No Edit-vs-Write split — Write covers both.
      * Slash commands aren't reachable from headless mode in the same
        `--print` ergonomic way, so we render the body of
        `.claude/commands/<role>.md` (frontmatter stripped, $ARGUMENTS
        substituted) into the positional prompt argument. This keeps a
        single source of truth for the role prompt.
      * NDJSON event shapes are different: type=tool_call with
        subtype=started|completed; type=result with subtype=success|error.
    """

    name = "cursor"
    binary_name = "cursor-agent"

    # Cursor permission tokens are coarser than Claude's. Translation is
    # deliberately on the safer side: Cursor's Write(src/**) covers both
    # edit and create, so we only emit Write tokens. Read tools are
    # default-allow in Cursor and don't need explicit grants.
    ROLE_PERMISSIONS: dict[str, dict[str, list[str]]] = {
        "dev": {
            "allow": [
                # Production code, specs (frontmatter only), docs, PR body
                "Write(src/**)",
                "Write(specs/FR-*.md)",
                "Write(docs/**)",
                "Write(PR_BODY.md)",
                "Write(*.py)",
                "Write(*.md)",
                # Test fixtures + conftest — infrastructure, not test code
                "Write(tests/fixtures/**)",
                "Write(tests/conftest.py)",
                # Python interpreters / runners. Cursor's Shell(cmd:args)
                # syntax is per-command, so we whitelist by command name.
                "Shell(python)",
                "Shell(python3)",
                "Shell(py)",
                "Shell(pip)",
                "Shell(ruff)",
                "Shell(pytest)",
                "Shell(uv)",
                # Filesystem inspection
                "Shell(ls)",
                "Shell(cat)",
                "Shell(head)",
                "Shell(tail)",
                "Shell(echo)",
                "Shell(pwd)",
                "Shell(where)",
                "Shell(which)",
                # Git: rely on per-command gating; destructive variants + push
                # are denied below by argument pattern.
                "Shell(git)",
                # GitHub CLI removed: dispatcher owns push & PR creation.
            ],
            "deny": [
                "Write(.agent-team/**)",
                "Write(scripts/deploy-gate.py)",
                "Write(scripts/index-specs.py)",
                "Write(scripts/dispatch.py)",
                "Write(scripts/agent-status.py)",
                "Write(CLAUDE.md)",
                "Write(tests/test_*.py)",
                # Destructive git ops — Cursor token form is Shell(cmd:args*)
                "Shell(git:push --force*)",
                "Shell(git:push -f*)",
                # Plain push also denied — dispatcher owns push.
                "Shell(git:push)",
                "Shell(git:push *)",
                "Shell(git:reset --hard*)",
                "Shell(rm)",
            ],
        },
        "rev": {
            "allow": [
                # Tests are the Reviewer's primary deliverable.
                "Write(tests/**)",
                # Review artefact + spec frontmatter
                "Write(REVIEW.md)",
                "Write(specs/FR-*.md)",
                "Write(*.md)",
                # Same Python / runner posture as Dev
                "Shell(python)",
                "Shell(python3)",
                "Shell(py)",
                "Shell(pip)",
                "Shell(ruff)",
                "Shell(pytest)",
                "Shell(uv)",
                # Filesystem inspection
                "Shell(ls)",
                "Shell(cat)",
                "Shell(head)",
                "Shell(tail)",
                "Shell(echo)",
                "Shell(pwd)",
                "Shell(where)",
                "Shell(which)",
                # Git for inspection; push denied below. GitHub CLI removed:
                # dispatcher owns push & PR creation via `finalize --role rev`.
                "Shell(git)",
            ],
            "deny": [
                # Reviewer must NOT modify production code.
                "Write(src/**)",
                # Reviewer must NOT modify the Developer's PR body.
                "Write(PR_BODY.md)",
                "Write(.agent-team/**)",
                "Write(scripts/deploy-gate.py)",
                "Write(scripts/index-specs.py)",
                "Write(scripts/dispatch.py)",
                "Write(scripts/agent-status.py)",
                "Write(CLAUDE.md)",
                "Shell(git:push --force*)",
                "Shell(git:push -f*)",
                # Plain push also denied — dispatcher owns push.
                "Shell(git:push)",
                "Shell(git:push *)",
                "Shell(git:reset --hard*)",
                "Shell(rm)",
            ],
        },
    }
    # See ClaudeAdapter.ROLE_PERMISSIONS["bkf"] for rationale: cloned from
    # `rev` but tightened (no spec edits) and PR_BODY allowed (the
    # backfill agent owns the PR body).
    ROLE_PERMISSIONS["bkf"] = {
        "allow": [a for a in ROLE_PERMISSIONS["rev"]["allow"] if a != "Write(specs/FR-*.md)"]
        + ["Write(PR_BODY.md)"],
        "deny": [d for d in ROLE_PERMISSIONS["rev"]["deny"] if d != "Write(PR_BODY.md)"]
        + ["Write(specs/**)"],
    }

    # Cursor's Shell token is per-command, so the interpreter narrowing is the
    # same idea in a different syntax: drop the bare interpreter grants and
    # re-add them bound to a sanctioned entrypoint via `Shell(cmd:args*)`.
    MNT_SHELL_NOT_INHERITED = (
        "Shell(python)",
        "Shell(python3)",
        "Shell(py)",
        "Shell(pip)",
        "Shell(uv)",
        "Shell(echo)",
    )
    MNT_SHELL_DENIES = (
        "Shell(python:-c*)",
        "Shell(python3:-c*)",
        "Shell(py:-c*)",
        "Shell(pip)",
        "Shell(uv)",
        "Shell(node)",
        "Shell(npx)",
        "Shell(bash)",
        "Shell(sh)",
        "Shell(powershell)",
        "Shell(pwsh)",
        "Shell(cmd)",
        "Shell(perl)",
        "Shell(ruby)",
        "Shell(tee)",
        "Shell(sed)",
        "Shell(cp)",
        "Shell(mv)",
    )

    def mnt_permissions(self, fr_id: str) -> dict[str, list[str]] | None:
        """Cursor equivalent of ClaudeCodeAdapter.mnt_permissions.

        Cursor has no separate edit token, so only `Write(...)` is emitted.
        """
        owns = fr_owns_globs(fr_id)
        if not owns:
            return None
        granted, protected_denies = mnt_permission_rules(owns)
        base = self.ROLE_PERMISSIONS["dev"]
        keep = [d for d in base["deny"] if not d.startswith("Write(")]
        inherited = [
            a
            for a in base["allow"]
            if a not in self.MNT_SHELL_NOT_INHERITED and a != "Write(specs/FR-*.md)"
        ]
        sanctioned = [
            f"Shell({interp}:{entry}*)"
            for interp in ("python", "python3", "py")
            for entry in MNT_SANCTIONED_ENTRYPOINTS
        ]
        tools = detected_stack_tools()
        lifted = {v for k, v in CURSOR_MNT_STACK_TOGGLED_DENIES.items() if k in tools}
        perms = {
            "allow": inherited + sanctioned + [f"Write({g})" for g in granted],
            # @implements FR-0010:AC-6 @implements FR-0010:AC-11
            "deny": [f"Write({d})" for d in protected_denies]
            + ["Write(tests/test_*.py)", "Write(specs/**)"]
            + [d for d in self.MNT_SHELL_DENIES if d not in lifted]
            + keep,
        }
        # @implements FR-0010:AC-4 @implements FR-0010:AC-11
        return _union_grants(perms, cursor_stack_grants(tools))

    def dev_permissions(self, fr_id: str) -> dict[str, list[str]]:
        """Cursor equivalent of `ClaudeCodeAdapter.dev_permissions`.

        @implements FR-0009:AC-8

        Cursor has no separate edit token, so only `Write(...)` is emitted
        for the `owns:` grants, same as `mnt_permissions` above.
        """
        base = self.ROLE_PERMISSIONS["dev"]
        granted = dev_owns_derivation(fr_id)["granted"]
        perms = {
            "allow": list(base["allow"]) + [f"Write({g})" for g in granted],
            "deny": list(base["deny"]),
        }
        # @implements FR-0010:AC-4 @implements FR-0010:AC-11
        return _union_grants(perms, cursor_stack_grants(detected_stack_tools()))

    def gat_permissions(self, fr_id: str, gate_id: str | None) -> dict[str, list[str]]:
        """Cursor equivalent of `ClaudeCodeAdapter.gat_permissions`. Cursor
        has no separate edit token, so only `Write(...)` is emitted."""
        evidence = _gate_evidence_path(fr_id, gate_id or "")
        return {
            "allow": [
                f"Write({evidence})",
                "Shell(git)",
                "Shell(ls)", "Shell(cat)", "Shell(pwd)",
            ],
            "deny": [
                "Write(.agent-team/**)",
                "Write(scripts/deploy-gate.py)",
                "Write(scripts/index-specs.py)",
                "Write(scripts/dispatch.py)",
                "Write(scripts/agent-status.py)",
                "Write(CLAUDE.md)",
                "Write(PR_BODY.md)",
                "Shell(git:push --force*)", "Shell(git:push -f*)",
                "Shell(git:push)", "Shell(git:push *)",
                "Shell(git:reset --hard*)", "Shell(rm)",
            ],
        }

    def write_worktree_settings(
        self, wt_path: Path, role: str, fr_id: str, gate_id: str | None = None
    ) -> None:
        if role == "mnt":
            perms = self.mnt_permissions(fr_id)
        elif role == "dev":
            # @implements FR-0009:AC-6/AC-8
            perms = self.dev_permissions(fr_id)
        elif role in ("rev", "bkf"):
            # @implements FR-0010:AC-5 @implements FR-0010:AC-11
            base = self.ROLE_PERMISSIONS[role]
            perms = cursor_owns_derived_permissions(base, fr_id)
            perms = _union_grants(perms, cursor_stack_grants(detected_stack_tools()))
        elif role == "gat":
            # @implements FR-0008:AC-6
            perms = self.gat_permissions(fr_id, gate_id)
        else:
            perms = self.ROLE_PERMISSIONS.get(role)
        if perms is None:
            return
        # @implements FR-0024:AC-2 — beside the agent's starting directory.
        # FR-0024 AC-5: Cursor's `cli.json` has no additional-directories
        # equivalent, so its `owns:` grants stay relative (recorded under
        # FINDINGS).
        settings_dir = _worktree_project_root(wt_path) / ".cursor"
        settings_dir.mkdir(parents=True, exist_ok=True)
        payload = {"permissions": {"allow": perms["allow"], "deny": perms["deny"]}}
        settings_path = settings_dir / "cli.json"
        settings_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        # @implements FR-0015:AC-4
        _record_settings_digest(fr_id, role, settings_path)

    def _render_prompt(self, fr_id: str, role: str, gate_id: str | None = None) -> str:
        slash = SLASH_COMMAND_NAMES.get(role, role)
        body = _slash_command_body(slash)
        # @implements FR-0008:AC-6
        args = f"{fr_id} {gate_id}" if gate_id else fr_id
        return body.replace("$ARGUMENTS", args)

    @staticmethod
    def _resolve_node_entrypoint(cursor_bin: str) -> tuple[str, str] | None:
        """Resolve (node.exe, index.js) inside the cursor-agent install dir.

        On Windows, `cursor-agent` on PATH is a `.cmd` shim that calls into
        a `.ps1` script which in turn calls `node.exe versions/<latest>/index.js`.
        Both shim layers chop multi-line argv at the first `\\n` (CMD `%*`
        and PowerShell `$args` quirks), which silently truncates our role
        prompt down to its first line. We bypass the shims by invoking
        node + index.js directly via subprocess.Popen, which uses
        CreateProcess and preserves argv exactly.

        Returns None on non-Windows or if the install layout doesn't match.
        """
        if sys.platform != "win32":
            return None
        install_dir = Path(cursor_bin).resolve().parent
        versions_dir = install_dir / "versions"
        if not versions_dir.is_dir():
            return None
        version_re = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})-[a-f0-9]+$")
        candidates: list[tuple[tuple[int, int, int], Path]] = []
        for entry in versions_dir.iterdir():
            if not entry.is_dir():
                continue
            m = version_re.match(entry.name)
            if not m:
                continue
            key = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            candidates.append((key, entry))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        latest = candidates[0][1]
        node_exe = latest / "node.exe"
        index_js = latest / "index.js"
        if not node_exe.exists() or not index_js.exists():
            return None
        return (str(node_exe), str(index_js))

    def spawn(
        self,
        fr_id: str,
        role: str,
        wt_path: Path,
        log_path: Path,
        extra_prompt: str | None = None,
        gate_id: str | None = None,
    ) -> tuple[str, int | None]:
        cursor_bin = shutil.which(self.binary_name)
        if cursor_bin is None:
            return ("binary-not-found", None)
        prompt = self._render_prompt(fr_id, role, gate_id=gate_id)
        # A generated rework brief is appended to the rendered role prompt. The
        # node-entrypoint path below preserves multi-line argv on Windows, so
        # the brief survives the shim-truncation quirk documented in
        # `_resolve_node_entrypoint`.
        if extra_prompt:
            prompt = f"{prompt}\n\n{extra_prompt}"
        node_pair = self._resolve_node_entrypoint(cursor_bin)
        if node_pair is not None:
            node_exe, index_js = node_pair
            cmd = [
                node_exe,
                index_js,
                "-p",
                "--force",
                "--trust",
                "--approve-mcps",
                "--output-format",
                "stream-json",
                prompt,
            ]
        else:
            # Non-Windows or unrecognised install layout — fall back to the
            # PATH binary. On macOS/Linux this is a real ELF/Mach-O, so the
            # multi-line argv issue doesn't apply.
            cmd = [
                cursor_bin,
                "-p",
                "--force",
                "--trust",
                "--approve-mcps",
                "--output-format",
                "stream-json",
                prompt,
            ]
        log_fh = log_path.open("wb")
        try:
            # @implements FR-0024:AC-2 — the agent starts in the project.
            proc = subprocess.Popen(
                cmd,
                cwd=_worktree_project_root(wt_path),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            log_fh.close()
            return ("spawn-failed", None)
        return ("spawned", proc.pid)

    def dry_run_preview(
        self, fr_id: str, role: str, wt_preview: Path, gate_id: str | None = None
    ) -> str:
        slash = SLASH_COMMAND_NAMES.get(role, role)
        label = f"{fr_id} {gate_id}" if gate_id else fr_id
        # @implements FR-0024:AC-2
        cwd = _worktree_project_root(wt_preview)
        return (
            f"cursor-agent -p --force --trust --approve-mcps "
            f"--output-format stream-json '<{slash} prompt for {label}>'  "
            f"(cwd={cwd}; perms via .cursor/cli.json)"
        )

    def parse_log(self, log_path: Path) -> AgentLogSummary:
        s = AgentLogSummary()
        with log_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "result":
                    sub = obj.get("subtype") or "unknown"
                    s.result_subtype = sub
                    s.is_error = sub != "success"
                    _apply_usage(s, obj.get("usage"))
                elif t == "tool_call":
                    sub = obj.get("subtype")
                    if sub == "started":
                        name = obj.get("name") or obj.get("tool") or "?"
                        s.tool_counts[name] = s.tool_counts.get(name, 0) + 1
                    elif sub == "completed" and obj.get("is_error"):
                        s.error_objs.append(obj)
                        name = obj.get("name") or obj.get("tool") or "?"
                        s.tool_error_counts[name] = s.tool_error_counts.get(name, 0) + 1
                elif t == "assistant":
                    msg = obj.get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, str):
                        s.last_text = content
                    elif isinstance(content, list):
                        parts = [
                            c.get("text", "")
                            for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        ]
                        if parts:
                            s.last_text = "".join(parts)
        return s


_ADAPTERS: dict[str, type] = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter,
    CursorAdapter.name: CursorAdapter,
}


def get_adapter(name: str) -> HarnessAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        valid = ", ".join(sorted(_ADAPTERS))
        raise SystemExit(f"unknown harness {name!r}; expected one of: {valid}")
    return cls()


# ---------------------------------------------------------------------------
# FR loading + lock management (harness-agnostic)
# ---------------------------------------------------------------------------


def load_frs() -> list[dict]:
    out: list[dict] = []
    for path in sorted(SPECS_DIR.glob("FR-*.md")):
        text = path.read_text(encoding="utf-8")
        m = FRONTMATTER_PATTERN.match(text)
        if not m:
            continue
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        fr_id = str(meta.get("id", ""))
        if not fr_id.startswith("FR-"):
            continue
        out.append(
            {
                "id": fr_id,
                "status": str(meta.get("status", "")),
                "depends_on": list(meta.get("depends_on") or []),
                "path": path,
                # @implements FR-0008:AC-1 — declared gates, best-effort
                # parsed (`index-specs.py --validate` is the shape's
                # authority; a malformed `gates:` here degrades to "no
                # gates" rather than crashing the dispatcher).
                "gates": _parse_gates(meta),
            }
        )
    return out


# @implements FR-0008:AC-1 — closed vocabularies shared with index-specs.py
# (kept as a second, independent definition: the two scripts are shipped as
# sibling template files with no import between them today).
_GATE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_GATE_AFTER_VALUES = {"dev", "rev"}
_GATE_REVIEWER_VALUES = {"human", "architect"}
_GATE_ALLOWED_KEYS = {"id", "after", "reviewer", "scope"}


def _parse_gates(meta: dict) -> tuple[dict, ...]:
    """Best-effort lift of an FR's `gates:` frontmatter.

    Silently degrades a malformed list to `()` (no gates) rather than
    raising: `index-specs.py --validate` is the shape's authority and the
    dispatcher must never crash on a spec it can otherwise dispatch.
    """
    raw = meta.get("gates")
    if not isinstance(raw, list):
        return ()
    seen_ids: set[str] = set()
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry.keys()) != _GATE_ALLOWED_KEYS:
            continue
        gate_id = str(entry.get("id", ""))
        after = str(entry.get("after", ""))
        reviewer = str(entry.get("reviewer", ""))
        scope = entry.get("scope")
        if (
            not _GATE_ID_RE.match(gate_id)
            or gate_id in seen_ids
            or after not in _GATE_AFTER_VALUES
            or reviewer not in _GATE_REVIEWER_VALUES
            or not isinstance(scope, str)
            or not scope.strip()
        ):
            continue
        seen_ids.add(gate_id)
        out.append(
            {
                "id": gate_id,
                "after": after,
                "reviewer": reviewer,
                "scope": scope.strip(),
            }
        )
    return tuple(out)


_GATE_EVIDENCE_UNSET = object()


def _gate_evidence_path(fr_id: str, gate: str) -> str:
    return f"specs/_gates/{fr_id}-{gate}.md"


def gate_status(
    fr_id: str,
    gate: str,
    ref: str | None = _GATE_EVIDENCE_UNSET,  # type: ignore[assignment]
) -> str:
    """`missing` | `pass` | `changes-requested` | `stale` for one declared gate.

    Reads the AC-2 evidence file (`specs/_gates/<FR>-<gate>.md`) **as
    committed on `ref`** — default (the keyword omitted entirely) is the
    FR's implementation branch, resolved through `_implementation_branch_for_fr`
    (`claude/dev-<FR>` if it exists, else `claude/mnt-<FR>`; DEC-0012 item 3);
    passing `ref=None` explicitly reads the working tree instead (the deploy
    gate's "current tree" reading, AC-9). Any other string reads that ref (a
    merge SHA, `main`, ...).

    `stale`: `verdict: pass` but the evidence's `head_sha` is not an
    ancestor-or-equal of that same implementation branch's *current* tip —
    an evidence file from a branch that was later rewritten. If no
    implementation branch exists locally there is nothing to compare against
    (most commonly: the FR already merged and its branch was cleaned up), so
    a `pass` verdict is trusted at face value.

    @implements FR-0008:AC-2
    """
    if ref is _GATE_EVIDENCE_UNSET:
        found = _implementation_branch_for_fr(fr_id)
        ref = found[0] if found is not None else f"claude/dev-{fr_id}"
    path = _gate_evidence_path(fr_id, gate)
    if ref is None:
        p = REPO_ROOT / path
        if not p.exists():
            return "missing"
        text = p.read_text(encoding="utf-8")
    else:
        # @implements FR-0024:AC-3 — an object read names `<prefix><path>`.
        ok, text = _git_capture(["show", f"{ref}:{_repo_path(path)}"], REPO_ROOT)
        if not ok:
            return "missing"
    # @implements FR-0008:AC-2 — round 4 defect 1: `_git_capture` strips the
    # text it returns, so a body-less evidence file (no `--note`, the
    # documented `gate pass` happy path) loses its trailing "\n\n" entirely
    # and ends at the closing "---" with no newline after it —
    # `FRONTMATTER_PATTERN` requires one and never matches. Restore a single
    # trailing newline before matching so a body-less file parses exactly
    # like one with a note. The `ref is None` (working-tree) read is
    # unaffected — `Path.read_text` never strips — so this is a no-op there.
    if text and not text.endswith("\n"):
        text += "\n"
    m = FRONTMATTER_PATTERN.match(text)
    if m is None:
        return "missing"
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return "missing"
    verdict = meta.get("verdict")
    if verdict == "changes-requested":
        return "changes-requested"
    if verdict != "pass":
        return "missing"
    head_sha = meta.get("head_sha")
    found = _implementation_branch_for_fr(fr_id)
    impl_branch = found[0] if found is not None else f"claude/dev-{fr_id}"
    # @implements FR-0008:AC-2 — round 3 ruling (ii): only an absent/empty
    # `head_sha`, or no implementation branch to compare against, keeps the
    # documented face-value `pass`. A `head_sha` that is merely *present* —
    # including a value YAML parsed as something other than a string, e.g.
    # an all-digit 40-character SHA becoming int `0` — is coerced to its
    # string form below and actually checked, rather than trusted. Coercing
    # via `str(meta.get("head_sha") or "")` would not achieve this: falsy
    # int `0` maps back to `""` and stays trusted, so the check here is
    # keyed on `is not None` (and non-empty), never on truthiness.
    if head_sha is None or head_sha == "" or not _git_branch_exists(impl_branch):
        return "pass"
    is_ancestor, _ = _git_capture(
        ["merge-base", "--is-ancestor", str(head_sha), impl_branch], REPO_ROOT
    )
    return "pass" if is_ancestor else "stale"


def cmd_gate_list(fr_id: str) -> int:
    """`dispatch.py gate list <FR>` — one line per declared gate with its
    current status. @implements FR-0008:AC-3"""
    by_id = {fr["id"]: fr for fr in load_frs()}
    fr = by_id.get(fr_id)
    if fr is None:
        print(f"ERROR: unknown FR id {fr_id!r} (no specs/{fr_id}-*.md with readable frontmatter)")
        return 1
    gates = fr.get("gates") or ()
    if not gates:
        print(f"{fr_id}: no declared gates")
        return 0
    for g in gates:
        status = gate_status(fr_id, g["id"])
        print(
            f"  {fr_id}  {g['id']}  after={g['after']}  reviewer={g['reviewer']}  "
            f"status={status}  — {g['scope']}"
        )
    return 0


def cmd_gate_verdict(
    fr_id: str, gate_id: str, verdict: str, *, by: str, note: str | None, apply: bool
) -> int:
    """`dispatch.py gate pass|block <FR> <gate-id> --by <who> [--note <text>] [--apply]`.

    Writes the AC-2 evidence file into the implementation worktree and
    commits it on the FR's implementation branch (`claude/dev-<FR>` if it
    exists, else `claude/mnt-<FR>`; resolved through
    `_implementation_branch_for_fr`, DEC-0012 item 3) — never on `main`.
    Without `--apply`, prints `WOULD-GATE <FR> <gate-id> <verdict>` and
    mutates nothing.
    @implements FR-0008:AC-3
    """
    by_id = {fr["id"]: fr for fr in load_frs()}
    fr = by_id.get(fr_id)
    if fr is None:
        print(f"ERROR: unknown FR id {fr_id!r} (no specs/{fr_id}-*.md with readable frontmatter)")
        return 1
    gates = {g["id"]: g for g in fr.get("gates") or ()}
    gate = gates.get(gate_id)
    if gate is None:
        declared = ", ".join(sorted(gates)) or "(none)"
        print(f"ERROR: {fr_id} declares no gate {gate_id!r} (declared: {declared})")
        return 1
    if verdict == "changes-requested" and not (note and note.strip()):
        print("ERROR: `gate block` requires --note")
        return 1
    found = _implementation_branch_for_fr(fr_id)
    if found is None:
        dev_branch = _branch_for(fr_id, "dev")
        mnt_branch = _branch_for(fr_id, "mnt")
        print(f"ERROR: no implementation branch for {fr_id} ({dev_branch} or {mnt_branch})")
        return 1
    dev_branch, impl_role = found
    wt_path = _role_worktree_path(fr_id, impl_role)
    if not wt_path.exists():
        print(f"ERROR: no {impl_role} worktree at {wt_path}")
        return 1
    ok, head = _git_capture(["rev-parse", "--abbrev-ref", "HEAD"], wt_path)
    if not ok or head != dev_branch:
        print(
            f"ERROR: {impl_role} worktree at {wt_path} is on branch {head or '?'!r}, "
            f"not {dev_branch!r}"
        )
        return 1
    if not apply:
        print(f"WOULD-GATE {fr_id} {gate_id} {verdict}")
        return 0
    round_ctx = _run_context(fr_id, impl_role).get("round")
    round_num = int(round_ctx) if isinstance(round_ctx, int) and round_ctx > 0 else 1
    head_sha = _branch_head_sha(dev_branch) or ""
    # @implements FR-0024:AC-2 — evidence is written in the project inside
    # the worktree and staged by its repository path.
    wt_project = _worktree_project_root(wt_path)
    evidence_dir = wt_project / "specs" / "_gates"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_rel = _gate_evidence_path(fr_id, gate_id)
    evidence_path = wt_project / "specs" / "_gates" / f"{fr_id}-{gate_id}.md"
    today = dt.datetime.now(dt.UTC).date().isoformat()
    fm = (
        "---\n"
        f"fr: {fr_id}\n"
        f"gate: {gate_id}\n"
        f"verdict: {verdict}\n"
        f"by: {by}\n"
        f"date: {today}\n"
        f"round: {round_num}\n"
        f"head_sha: {head_sha}\n"
        "---\n"
    )
    body = (note or "").strip()
    # @implements FR-0008:AC-3 — round 4 defect 2: `Path.write_text` with the
    # default `newline=None` translates every "\n" to `os.linesep` on write,
    # which is CRLF on Windows. Evidence is a tracked file under
    # `specs/_gates/`; every other tracked file this wave writes is LF, so
    # pin `newline="\n"` to write the bytes verbatim.
    evidence_path.write_text(fm + "\n" + body + "\n", encoding="utf-8", newline="\n")
    add_ok, add_err = _git_capture(["add", "--", _repo_path(evidence_rel)], wt_path)
    if not add_ok:
        print(f"ERROR: git add failed: {add_err}")
        return 1
    subject = f"gate({fr_id}): {gate_id} {verdict} by {by}"
    commit_ok, commit_err = _git_capture(["commit", "-m", subject], wt_path)
    if not commit_ok:
        print(f"ERROR: git commit failed: {commit_err}")
        return 1
    push_ok, push_msg = _push_branch(dev_branch)
    if push_ok:
        print(f"  {fr_id}  GATED        {gate_id} {verdict} by {by} ({push_msg})")
    else:
        print(
            f"  {fr_id}  GATED        {gate_id} {verdict} by {by} "
            f"(committed; push skipped: {push_msg})"
        )
    _metrics_emit(
        "gate.decision",
        role=None,
        object_ids=[fr_id],
        run_id=None,
        gate=gate_id,
        after=gate["after"],
        reviewer=gate["reviewer"],
        verdict=verdict,
        by=by,
        round=round_num,
        head_sha=head_sha or None,
    )
    return 0


def runnable_frs(frs: list[dict]) -> list[dict]:
    """FRs a fresh Developer may start: `ready` on main, deps terminal, and
    not already handed off on a `claude/dev-<FR>` branch (see
    `handed_off_frs`)."""
    handed_off = {fr_id for fr_id, _ in handed_off_frs(frs, "dev")}
    by_id = {fr["id"]: fr for fr in frs}
    ready = []
    for fr in frs:
        if fr["status"] != "ready":
            continue
        if fr["id"] in handed_off:
            continue
        deps_ok = all(
            by_id.get(dep, {}).get("status") in TERMINAL_STATUSES
            for dep in fr["depends_on"]
        )
        if deps_ok:
            ready.append(fr)
    return ready


def _handed_off_reason(fr_id: str, role: str) -> str | None:
    """Why `role` must not be re-dispatched fresh for this FR, or None.

    A Developer (or maintainer) flips the FR to `in-progress` in its own
    worktree branch and that flip only reaches `main` through a merge. Reading
    runnability from `main` alone therefore re-offers a handed-off FR as fresh
    work — the FR-0015 failure. When the role branch exists and the FR's status
    *as committed on that branch* is one a Reviewer acts on, the FR is in the
    review / rework path, not the fresh-dispatch path. A role branch whose
    status still reads `ready` (the agent exited before flipping it) stays
    runnable and its worktree is reused.

    @implements FR-0006:AC-8
    """
    if role not in ("dev", "mnt"):
        return None
    branch = f"claude/{role}-{fr_id}"
    if not _git_branch_exists(branch):
        return None
    status = _fr_status_on_branch(fr_id, branch)
    if status not in REVIEWABLE_STATUSES:
        return None
    return (
        f"status is {status!r} on {branch} — already handed off; run "
        f"`tick --role rev --fr {fr_id}` (or a rework round) instead of a fresh {role}"
    )


def handed_off_frs(frs: list[dict], role: str = "dev") -> list[tuple[str, str]]:
    """(fr_id, reason) for every `ready` FR that `_handed_off_reason` refuses.

    Callers print one SKIP line per entry so an unfiltered tick / wave says
    why an FR it used to list is no longer runnable.

    @implements FR-0006:AC-9
    """
    out: list[tuple[str, str]] = []
    for fr in frs:
        if fr["status"] != "ready":
            continue
        reason = _handed_off_reason(fr["id"], role)
        if reason is not None:
            out.append((fr["id"], reason))
    return out


# Statuses where there's Developer work that a Reviewer should look at.
# `in-progress` is the canonical post-Dev-handoff state (Dev sets it at
# implementation start, leaves it there at handoff). `in-review` covers a
# resumed/kicked-back review pass.
REVIEWABLE_STATUSES = {"in-progress", "in-review"}


def _git_branch_exists(branch: str) -> bool:
    """True iff a local branch with this exact ref name exists."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
        timeout=10,
    )
    return proc.returncode == 0


# @implements FR-0016:AC-1, FR-0016:AC-4
def _fr_status_on_branch(fr_id: str, branch: str) -> str | None:
    """Read this FR's `status` frontmatter as it appears on `branch`.

    The Developer flips status to `in-progress` in their own worktree
    branch; in a no-PR / no-merge workflow that flip never reaches `main`,
    so a Reviewer filter that reads on-disk frontmatter would never fire.
    Reading directly from the Dev branch via `git show` closes that gap.

    Returns None if the FR file isn't present on that branch or if
    frontmatter is unreadable.
    """
    ls = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", branch, "specs/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if ls.returncode != 0:
        return None
    spec_path: str | None = None
    prefix = f"specs/{fr_id}-"
    for line in ls.stdout.splitlines():
        if line.startswith(prefix) and line.endswith(".md"):
            spec_path = line
            break
    if spec_path is None:
        return None
    # @implements FR-0024:AC-3 — `ls-tree` above runs in `REPO_ROOT`, the
    # project directory, so it prints project-relative names; the object
    # read names `<prefix><path>`.
    show = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{branch}:{_repo_path(spec_path)}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if show.returncode != 0:
        return None
    m = FRONTMATTER_PATTERN.match(show.stdout)
    if m is None:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    return str(meta.get("status", "")) or None


# @implements FR-0016:AC-1
def _fr_spec_committed_on_branch(fr_id: str, branch: str) -> bool:
    """True iff this FR's spec file is committed on `branch`.

    A role worktree is a clean checkout of `branch` (see
    `ensure_role_worktree`). If the spec was authored but never committed —
    e.g. the Architect handoff skipped the commit step — the worktree won't
    contain it and the agent fails with "FR not found". The dispatcher uses
    this to refuse the spawn with an actionable error rather than launching a
    blind agent against an invisible spec.

    Mirrors the `git ls-tree` lookup in `_fr_status_on_branch`. A `git`
    failure (e.g. the branch doesn't exist yet) is treated as "not committed"
    so the guard fails safe.
    """
    ls = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", branch, "specs/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if ls.returncode != 0:
        return False
    prefix = f"specs/{fr_id}-"
    return any(
        line.startswith(prefix) and line.endswith(".md")
        for line in ls.stdout.splitlines()
    )


def runnable_review_frs(frs: list[dict]) -> list[dict]:
    """FRs whose Developer wave has produced a branch and is no longer
    actively working — i.e. eligible for a Reviewer pass.

    Filter:
      * `claude/dev-FR-XXXX` branch exists locally — there is something to review.
      * Effective status (read from the Dev branch, falling back to main's
        on-disk value) is in {in-progress, in-review}. Reading from the
        Dev branch matters because in a no-PR workflow the Dev's
        status-flip never reaches main, and a Reviewer that filtered on
        main alone would never fire.
      * No held Dev lock — Dev is finished (or never started this round).

    The held-Rev-lock check happens later in cmd_tick (same as for dev),
    so a Reviewer that's already running surfaces as SKIP rather than
    being filtered out here.
    """
    out: list[dict] = []
    for fr in frs:
        dev_branch = f"claude/dev-{fr['id']}"
        if not _git_branch_exists(dev_branch):
            continue
        effective = _fr_status_on_branch(fr["id"], dev_branch) or fr["status"]
        if effective not in REVIEWABLE_STATUSES:
            continue
        dev_state, _ = lock_state(fr["id"], "dev")
        if dev_state == "held":
            continue
        # @implements FR-0008:AC-4 — a declared `after: dev` gate that is not
        # `pass` excludes the FR from the Reviewer's runnable set.
        if _pending_after_dev_gates(fr["id"], fr.get("gates") or ()):
            continue
        out.append(fr)
    return out


def _pending_after_dev_gates(
    fr_id: str, gates: tuple[dict, ...]
) -> list[tuple[dict, str]]:
    """`[(gate, status)]` for every declared `after: dev` gate whose
    `gate_status` is not `pass`. @implements FR-0008:AC-4"""
    out: list[tuple[dict, str]] = []
    for g in gates:
        if g["after"] != "dev":
            continue
        status = gate_status(fr_id, g["id"])
        if status != "pass":
            out.append((g, status))
    return out


def _gate_pending_skip_reason(fr_id: str, gate: dict, status: str) -> str:
    """One line naming the gate, its status, the reviewer kind, and — for a
    human gate — the exact command that satisfies it. @implements FR-0008:AC-4"""
    if gate["reviewer"] == "human":
        cmd = f"python scripts/dispatch.py gate pass {fr_id} {gate['id']} --by <you> --apply"
        return (
            f"gate '{gate['id']}' reviewer=human status={status} — "
            f"satisfy with: {cmd}"
        )
    return (
        f"gate '{gate['id']}' reviewer=architect status={status} — "
        f"run `dispatch.py tick --role gat --fr {fr_id}`"
    )


def gate_pending_review_frs(frs: list[dict]) -> list[tuple[str, str]]:
    """`(fr_id, reason)` for every FR that is otherwise Reviewer-runnable but
    has an unsatisfied declared `after: dev` gate. @implements FR-0008:AC-4"""
    out: list[tuple[str, str]] = []
    for fr in frs:
        dev_branch = f"claude/dev-{fr['id']}"
        if not _git_branch_exists(dev_branch):
            continue
        effective = _fr_status_on_branch(fr["id"], dev_branch) or fr["status"]
        if effective not in REVIEWABLE_STATUSES:
            continue
        dev_state, _ = lock_state(fr["id"], "dev")
        if dev_state == "held":
            continue
        pending = _pending_after_dev_gates(fr["id"], fr.get("gates") or ())
        if pending:
            gate, status = pending[0]
            out.append((fr["id"], _gate_pending_skip_reason(fr["id"], gate, status)))
    return out


def _fr_gates(fr_id: str) -> tuple[dict, ...]:
    """This FR's declared `gates:`, read fresh from its spec file on disk
    (the primary checkout). @implements FR-0008:AC-8"""
    paths = list(SPECS_DIR.glob(f"{fr_id}-*.md"))
    if not paths:
        return ()
    text = paths[0].read_text(encoding="utf-8")
    m = FRONTMATTER_PATTERN.match(text)
    if not m:
        return ()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return ()
    return _parse_gates(meta)


def _render_gates_section(fr_id: str) -> str:
    """`## Gates` block for the PR body: one line per declared gate,
    `- <id> (<after>, <reviewer>): <status>`. Empty string when the FR
    declares no gates. @implements FR-0008:AC-8"""
    gates = _fr_gates(fr_id)
    if not gates:
        return ""
    lines = ["", "## Gates", ""]
    for g in gates:
        status = gate_status(fr_id, g["id"])
        lines.append(f"- {g['id']} ({g['after']}, {g['reviewer']}): {status}")
    return "\n".join(lines) + "\n"


def _apply_gates_section(pr_body_path: Path, fr_id: str) -> bool:
    """Insert or replace the `## Gates` section of a PR body file in place.
    Returns True iff the file's content changed. A no-gates FR gets no
    section (and this is a no-op unless a stale one needs removing).
    @implements FR-0008:AC-8"""
    section = _render_gates_section(fr_id)
    text = pr_body_path.read_text(encoding="utf-8") if pr_body_path.exists() else ""
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line.strip() == "## Gates":
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)
    new_text = "\n".join(out).rstrip("\n")
    if section:
        new_text = (new_text + "\n" + section) if new_text else section
    new_text = new_text.rstrip("\n") + "\n" if new_text.strip() else new_text
    if new_text == text:
        return False
    pr_body_path.write_text(new_text, encoding="utf-8")
    return True


_FR_ID_RE = re.compile(r"^FR-\d{4}$")

_LOCK_BLOCKED_STATES = {
    "held": "{role} lock held (pid={pid}, since {since})",
    "stale": "stale {role} lock (pid={pid}, started {since}); not auto-clearing",
    "dead": "orphaned {role} lock (pid={pid} no longer alive); run `dispatch.py prune`",
    "corrupt": "corrupt {role} lockfile; remove it or run `dispatch.py prune`",
}


def parse_fr_selector(values: list[str] | None) -> list[str] | None:
    """Normalise `--fr` into a de-duplicated, order-preserving list of FR ids.

    Accepts a repeated flag, a comma-separated list, or both. Returns None
    when the flag was not supplied, which means "no filter" and preserves the
    whole-runnable-set behaviour exactly.
    """
    if not values:
        return None
    out: list[str] = []
    for raw in values:
        for part in str(raw).replace(",", " ").split():
            fr_id = part.strip().upper()
            if fr_id and fr_id not in out:
                out.append(fr_id)
    return out or None


def explain_not_runnable(fr_id: str, frs: list[dict], role: str) -> str | None:
    """Why `--fr <fr_id>` cannot run for `role`, or None if it can.

    Ordered most-specific-first so the message names the actual blocker rather
    than a downstream symptom. `--fr` must never silently no-op or fall back
    to the full runnable set, so every branch here returns a reason a human
    can act on.
    """
    if not _FR_ID_RE.match(fr_id):
        return "not a valid FR id (expected FR-XXXX)"
    by_id = {fr["id"]: fr for fr in frs}
    fr = by_id.get(fr_id)
    if fr is None:
        return f"unknown FR id (no specs/{fr_id}-*.md with readable frontmatter)"
    state, lock = lock_state(fr_id, role)
    if state in _LOCK_BLOCKED_STATES:
        return _LOCK_BLOCKED_STATES[state].format(
            role=role,
            pid=(lock or {}).get("pid", "?"),
            since=(lock or {}).get("started_at_iso", "?"),
        )
    if role == "rev":
        # @implements FR-0013:AC-11 — the implementation branch is
        # `claude/dev-<FR>` if it exists, else `claude/mnt-<FR>`, so a
        # maintainer-mode FR is reviewable through the same tick.
        found = _implementation_branch_for_fr(fr_id)
        if found is None:
            dev_branch = f"claude/dev-{fr_id}"
            mnt_branch = f"claude/mnt-{fr_id}"
            return (
                f"no {dev_branch} or {mnt_branch} branch locally — nothing "
                "for a Reviewer to review"
            )
        impl_branch, impl_role = found
        effective = _fr_status_on_branch(fr_id, impl_branch) or fr["status"]
        if effective not in REVIEWABLE_STATUSES:
            return (
                f"status is {effective!r} on {impl_branch}; rev tick requires one of "
                f"{sorted(REVIEWABLE_STATUSES)}"
            )
        impl_state, impl_lock = lock_state(fr_id, impl_role)
        if impl_state == "held":
            return (
                f"{ROLE_LABELS.get(impl_role, impl_role)} still running "
                f"({impl_role} lock held, pid={(impl_lock or {}).get('pid', '?')})"
            )
        # @implements FR-0008:AC-4
        pending = _pending_after_dev_gates(fr_id, fr.get("gates") or ())
        if pending:
            gate, gstatus = pending[0]
            return _gate_pending_skip_reason(fr_id, gate, gstatus)
        return None
    # @implements FR-0006:AC-8 — the role branch's committed status wins over
    # main's `ready` for the fresh-dispatch roles.
    handed_off = _handed_off_reason(fr_id, role)
    if handed_off is not None:
        return handed_off
    if fr["status"] != "ready":
        return f"status is {fr['status']!r}; {role} tick requires status='ready'"
    blocking = [
        f"{dep} (status={by_id.get(dep, {}).get('status') or 'missing'})"
        for dep in fr["depends_on"]
        if by_id.get(dep, {}).get("status") not in TERMINAL_STATUSES
    ]
    if blocking:
        return "unmet depends_on: " + ", ".join(blocking)
    return None


def filter_frs_by_selector(
    frs: list[dict], selection: list[str], role: str
) -> tuple[list[dict], list[str]]:
    """Resolve a `--fr` selection to FR records, plus per-FR blocking reasons.

    Reports every non-runnable FR in one pass: a partially-executed targeted
    wave is harder to reason about than a clean failure, so callers abort on
    any problem rather than proceeding with the runnable subset.
    """
    by_id = {fr["id"]: fr for fr in frs}
    chosen: list[dict] = []
    problems: list[str] = []
    for fr_id in selection:
        reason = explain_not_runnable(fr_id, frs, role)
        if reason is not None:
            problems.append(f"{fr_id}: {reason}")
        else:
            chosen.append(by_id[fr_id])
    return chosen, problems


# @implements FR-0015:AC-4
def _settings_digest_record_path(fr_id: str, role: str) -> Path:
    """Where the permission-file digest record for a spawn lives: under the
    call-time `DISPATCH_DIR` (read fresh here, so a test that monkeypatches
    it is honoured), outside the role worktree, never the lock file or the
    spawn record's `worktree_status` (DEC-0017 Decision 3)."""
    return DISPATCH_DIR / f"{fr_id}.{role}.settings.sha256"


# @implements FR-0015:AC-4
def _record_settings_digest(fr_id: str, role: str, settings_path: Path) -> None:
    """Record the SHA-256 of the bytes actually on disk right after a
    permission file write. Called by each adapter's `write_worktree_settings`
    after its own write; never changes how that file itself is written
    (DEC-0017 Decision 3). Silently does nothing if the file cannot be read
    back — a spawn is not aborted over a bookkeeping write.
    """
    try:
        data = settings_path.read_bytes()
    except OSError:
        return
    digest = hashlib.sha256(data).hexdigest()
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    record_path = _settings_digest_record_path(fr_id, role)
    record_path.write_text(
        json.dumps({"path": str(settings_path), "sha256": digest}) + "\n",
        encoding="utf-8",
    )


# @implements FR-0015:AC-4
def _finalize_settings_digest_violation(fr_id: str, role: str) -> str | None:
    """None when there is no digest record for this FR/role (a worktree
    created before this FR, or by hand — the check is skipped silently), or
    the permission file on disk still matches what was recorded. Otherwise a
    one-line cause naming the record or the file, for `cmd_finalize` to
    report and refuse on.

    A record that exists but cannot be read, is not valid JSON, is not a
    JSON object, or lacks `path` or `sha256` is itself a refusal: the fixed
    rule "a check that cannot run is a refusal, not a pass" applies to a
    corrupt record exactly as it does to a failed git read. `path` or
    `sha256` that is not a string, or a record that is not UTF-8, is
    refused the same way. This never raises — it only returns `None` for
    the one silent case the AC carves out, an *absent* record.
    """
    record_path = _settings_digest_record_path(fr_id, role)
    if not record_path.exists():
        return None
    try:
        text = record_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"{record_path} could not be read: {exc}"
    try:
        record = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        return f"{record_path} is not valid JSON: {exc}"
    if not isinstance(record, dict):
        return f"{record_path} is not a JSON object"
    settings_path_str = record.get("path")
    recorded_digest = record.get("sha256")
    if not isinstance(settings_path_str, str) or not isinstance(recorded_digest, str):
        return (
            f"{record_path} is missing 'path' or 'sha256' (or either is not a string)"
        )
    if not settings_path_str or not recorded_digest:
        return f"{record_path} is missing 'path' or 'sha256'"
    settings_path = Path(settings_path_str)
    if not settings_path.exists():
        return f"{settings_path} missing (recorded {recorded_digest[:12]})"
    try:
        current_digest = hashlib.sha256(settings_path.read_bytes()).hexdigest()
    except OSError:
        return f"{settings_path} unreadable (recorded {recorded_digest[:12]})"
    if current_digest != recorded_digest:
        return (
            f"{settings_path} is {current_digest[:12]}, recorded {recorded_digest[:12]}"
        )
    return None


def lock_path(fr_id: str, role: str) -> Path:
    return DISPATCH_DIR / f"{fr_id}.{role}.lock"


# @implements FR-0016:AC-1
def is_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def kill_pid(pid: int) -> bool:
    if not is_alive(pid):
        return False
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return not is_alive(pid)
    try:
        os.kill(pid, 15)
    except (OSError, ProcessLookupError):
        return False
    return True


def log_idle_seconds(fr_id: str, role: str, started_at: float = 0.0) -> float | None:
    log_path = DISPATCH_DIR / f"{fr_id}.{role}.log"
    if not log_path.exists():
        return None
    last_activity = max(log_path.stat().st_mtime, started_at)
    return dt.datetime.now(dt.timezone.utc).timestamp() - last_activity


def lock_state(fr_id: str, role: str) -> tuple[str, dict | None]:
    p = lock_path(fr_id, role)
    if not p.exists():
        return ("free", None)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("corrupt", None)
    pid = int(data.get("pid", 0))
    if not is_alive(pid):
        return ("dead", data)
    age = dt.datetime.now(dt.timezone.utc).timestamp() - data.get("started_at", 0)
    if age > STALE_LOCK_SECONDS:
        return ("stale", data)
    return ("held", data)


def write_lock(fr_id: str, role: str, pid: int, **extra: object) -> None:
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "fr_id": fr_id,
        "role": role,
        "pid": pid,
        "started_at": dt.datetime.now(dt.timezone.utc).timestamp(),
        "started_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
    }
    payload.update(extra)
    lock_path(fr_id, role).write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pipeline metrics (FR-0002): structured records emitted at the source
# ---------------------------------------------------------------------------
#
# Every emission goes through `metrics_log.emit`, which never raises: a metrics
# failure is one `WARN: metrics:` stderr line and nothing else. Nothing in this
# section changes the dispatcher's stdout, exit codes or control flow, and no
# dry-run path reaches an emitter. Schema: specs/_metrics/README.md.

# (fr_id, role) -> {"run_id", "started_at", "round"} for agents spawned by this
# process; the lock file is the fallback (and the only source across
# processes, e.g. a standalone `finalize` after a `tick`).
_RUN_REGISTRY: dict[tuple[str, str], dict] = {}
# (fr_id, role) -> record_id handed to the finalize-preflight gate run so the
# `pr.opened` record can cite it (`gate_record_id`).
_PREFLIGHT_GATE_RECORD_IDS: dict[tuple[str, str], str] = {}
_COVERS_LINE_RE = re.compile(r"@covers\s+FR-\d{4}:AC-\d+")


def _run_context(fr_id: str, role: str) -> dict:
    """run_id / started_at / round for the (fr, role) agent: in-process
    registry first, then the lock file."""
    ctx = dict(_RUN_REGISTRY.get((fr_id, role), {}))
    if not (ctx.get("run_id") and ctx.get("started_at")):
        p = lock_path(fr_id, role)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            for key in ("run_id", "started_at", "round"):
                if ctx.get(key) is None and data.get(key) is not None:
                    ctx[key] = data[key]
    return ctx


def _metrics_emit(kind: str, **fields: object) -> dict | None:
    if _metrics is None:
        return None
    return _metrics.emit(kind, source="dispatch", **fields)


def _findings_for_record(findings: list[tuple[str, str]]) -> list[dict]:
    """`{tag, refs, chars}` per finding — refs are the spec-object IDs and
    repo-relative paths in the text; the text itself is never stored.
    @implements FR-0002:AC-7"""
    return [
        {"tag": tag, "refs": _metrics.spec_refs(body), "chars": len(body)}
        for tag, body in findings
    ]


def _emit_dispatch_run(
    fr_id: str,
    role: str,
    status: str,
    summary: AgentLogSummary | None,
    verdict: str | None = None,
    findings: list[tuple[str, str]] | None = None,
) -> None:
    """Append the `dispatch.run` record for an evaluated (or timed-out) agent
    run. @implements FR-0002:AC-3, FR-0002:AC-7"""
    if _metrics is None:
        return
    try:
        ctx = _run_context(fr_id, role)
        started = ctx.get("started_at")
        duration: float | None = None
        if isinstance(started, (int, float)) and started > 0:
            duration = round(dt.datetime.now(dt.timezone.utc).timestamp() - started, 3)
        tool_counts = dict(summary.tool_counts) if summary else {}
        error_counts = dict(getattr(summary, "tool_error_counts", {}) or {}) if summary else {}
        rnd = ctx.get("round")
        _metrics_emit(
            "dispatch.run",
            role=role,
            object_ids=[fr_id],
            run_id=ctx.get("run_id"),
            status=status,
            tool_calls_total=sum(tool_counts.values()),
            tool_calls_by_tool=tool_counts,
            tool_errors_total=len(summary.error_objs) if summary else 0,
            tool_errors_by_tool=error_counts,
            tokens_in=getattr(summary, "tokens_in", None) if summary else None,
            tokens_out=getattr(summary, "tokens_out", None) if summary else None,
            duration_s=duration,
            round=int(rnd) if isinstance(rnd, int) and rnd > 0 else 1,
            verdict=verdict,
            findings=_findings_for_record(list(findings or [])),
        )
    except Exception as e:  # noqa: BLE001 — never load-bearing
        _metrics.warn(f"dispatch.run: {type(e).__name__}: {e}")


def _pr_change_size(branch: str, base: str = "main") -> dict:
    """Change-size fields for a PR record from the branch diff against its
    base: paths touched, how many are tests, and the net `@covers` delta.
    @implements FR-0002:AC-5"""
    ok, out = _git_capture(["diff", "--name-only", f"{base}...{branch}"], REPO_ROOT)
    paths = sorted(_path_lines(out)) if ok else []
    covers_delta = 0
    ok, diff = _git_capture(
        ["diff", "--unified=0", f"{base}...{branch}", "--", "tests"], REPO_ROOT
    )
    if ok:
        for line in diff.splitlines():
            if line.startswith(("+++", "---")):
                continue
            if line.startswith("+") and _COVERS_LINE_RE.search(line):
                covers_delta += 1
            elif line.startswith("-") and _COVERS_LINE_RE.search(line):
                covers_delta -= 1
    return {
        "commits_ahead": _commits_ahead(branch, base),
        "files_touched": len(paths),
        "files_touched_paths": paths,
        # @implements FR-0024:AC-4 — the project's own `tests/`, whatever
        # the footprint root. The `-- tests` pathspec above already resolves
        # from `REPO_ROOT`, the project directory.
        "tests_changed": sum(
            1 for p in paths if (_project_relpath(p) or "").startswith("tests/")
        ),
        "covers_delta": covers_delta,
    }


def _emit_pr_event(kind: str, fr_id: str, role: str, record: dict, branch: str) -> None:
    """`pr.opened` / `pr.refreshed` after a Developer or one-shot finalize.
    @implements FR-0002:AC-5"""
    if _metrics is None:
        return
    try:
        ctx = _run_context(fr_id, role)
        size = _pr_change_size(branch)
        _metrics_emit(
            kind,
            role=role,
            object_ids=[fr_id],
            run_id=ctx.get("run_id"),
            pr_number=record.get("pr_number"),
            pr_url=record.get("pr_url"),
            draft=bool(record.get("draft")),
            head_sha=record.get("head_sha"),
            gate_record_id=_PREFLIGHT_GATE_RECORD_IDS.get((fr_id, role)),
            **size,
        )
    except Exception as e:  # noqa: BLE001 — never load-bearing
        _metrics.warn(f"{kind}: {type(e).__name__}: {e}")


def _gate_metrics_env(fr_id: str, role: str) -> dict[str, str]:
    """Environment handed to a finalize-preflight gate run so its `gate.run`
    record says who invoked it, joins the agent's run_id, and carries a record
    id known in advance for `pr.opened.gate_record_id`. @implements FR-0002:AC-4"""
    if _metrics is None:
        return {}
    record_id = _metrics.new_id()
    _PREFLIGHT_GATE_RECORD_IDS[(fr_id, role)] = record_id
    env = {"METRICS_INVOKED_BY": "dispatch-finalize", "METRICS_GATE_RECORD_ID": record_id}
    run_id = _run_context(fr_id, role).get("run_id")
    if run_id:
        env[_metrics.RUN_ID_ENV] = str(run_id)
    return env


# ---------------------------------------------------------------------------
# Worktree + venv provisioning (harness-agnostic except for settings file)
# ---------------------------------------------------------------------------


def _find_uv() -> str | None:
    """Locate the `uv` binary. Preferred over `python -m venv` because the
    workflow already standardises on uv-managed virtualenvs and pip installs
    are noticeably faster.
    """
    found = shutil.which("uv")
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / ".local" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def _venv_python_exe(venv_path: Path) -> Path:
    return (
        venv_path / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else venv_path / "bin" / "python"
    )


_VENV_PROVISION_STATE_FILENAME = ".dispatch-provision.json"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provision_fingerprint(lock: Path | None, requirements: Path | None) -> str:
    """A fingerprint of whichever dependency file drives provisioning, used
    by AC-10's idempotency check. Folds in *which kind* of file it is (not
    just its content) so switching from a requirements-driven install to a
    lock-driven one on the same worktree re-syncs rather than reusing."""
    if lock is not None:
        return f"lock:{_hash_file(lock)}"
    if requirements is not None:
        return f"req:{_hash_file(requirements)}"
    return "none"


def _read_provision_state(venv_path: Path) -> dict | None:
    p = venv_path / _VENV_PROVISION_STATE_FILENAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_provision_state(venv_path: Path, fingerprint: str) -> None:
    p = venv_path / _VENV_PROVISION_STATE_FILENAME
    p.write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")


# @implements FR-0016:AC-1, FR-0016:AC-4
def _sync_dependencies(
    uv: str,
    py_exe: Path,
    venv_path: Path,
    wt_path: Path,
    lock: Path | None,
    requirements: Path | None,
) -> tuple[bool, str]:
    """Install the project's own dependencies (AC-8), then unconditionally
    top up the dispatcher's own tooling (`VENV_PACKAGES`) so a project that
    doesn't depend on pytest still gets a runnable gate. Returns (True, "")
    on success or (False, "<classification>:<stderr>") on the first failure,
    the classification drawn from AC-9's closed set.
    """
    if lock is not None:
        # `--frozen` never re-resolves or edits the checked-in lock
        # (determinism); `--no-install-project` provisions dependencies
        # only, not the local package itself, which a bare fixture
        # `pyproject.toml` may not be buildable as. `UV_PROJECT_ENVIRONMENT`
        # redirects `uv sync`'s target away from its `.venv` default and
        # onto the venv this function already created.
        env = dict(os.environ)
        env["UV_PROJECT_ENVIRONMENT"] = str(venv_path)
        sync = subprocess.run(
            [
                uv,
                "sync",
                "--frozen",
                "--no-install-project",
                "--python",
                VENV_PYTHON_VERSION,
            ],
            cwd=wt_path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        if sync.returncode != 0:
            return (False, f"lock-sync-failed:{sync.stderr.strip()[:200]}")
    elif requirements is not None:
        install = subprocess.run(
            [uv, "pip", "install", "-p", str(py_exe), "-r", str(requirements)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        if install.returncode != 0:
            return (
                False,
                f"requirements-install-failed:{install.stderr.strip()[:200]}",
            )
    base_install = subprocess.run(
        [uv, "pip", "install", "-p", str(py_exe), *VENV_PACKAGES],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if base_install.returncode != 0:
        return (False, f"packages-install-failed:{base_install.stderr.strip()[:200]}")
    return (True, "")


# @implements FR-0016:AC-1
def ensure_dev_venv(wt_path: Path) -> tuple[bool, str]:
    """Pre-provision the dispatch venv in the worktree with the deps the
    agent needs, provisioned from the project's own lock/requirements file
    rather than a fixed package list. Returns (ok, message).

    @implements FR-0010:AC-8
    @implements FR-0010:AC-9
    @implements FR-0010:AC-10

    With `uv.lock` present, dependencies are synced from that lock
    (`uv sync --frozen`); with `requirements.txt` (or a `requirements*.lock`)
    and no `uv.lock`, they are installed from that file; with neither, only
    `VENV_PACKAGES` is installed — byte-for-byte the pre-FR-0010 behaviour
    (AC-12), including the reuse fast-path below staying an unconditional
    `(True, "venv-reused")` when nothing to track is declared.

    Idempotent and bounded (AC-10): when a lock or requirements file is
    declared, a fingerprint of its content is recorded in the venv after a
    successful provision; a later call whose fingerprint still matches
    reuses the venv (`venv-reused`) instead of re-installing, and one whose
    fingerprint has changed re-syncs (`venv-resynced`). Every subprocess
    call above carries an explicit timeout.

    Soft-fail (AC-9): any failure returns `(False, "<classification>:...")`
    with the classification drawn from a closed set (`uv-not-found`,
    `venv-create-failed`, `lock-sync-failed`, `requirements-install-failed`,
    `packages-install-failed`); callers never abort the spawn on this.
    """
    venv_path = wt_path / VENV_DIRNAME
    py_exe = _venv_python_exe(venv_path)
    lock = stack_profile.find_lock_file(wt_path)
    requirements = None if lock else stack_profile.find_requirements_file(wt_path)

    if py_exe.exists():
        if lock is None and requirements is None:
            # @implements FR-0010:AC-12 — identical to the pre-FR-0010 reuse
            # fast-path for a project that declares no lock/requirements.
            return (True, "venv-reused")
        fingerprint = _provision_fingerprint(lock, requirements)
        state = _read_provision_state(venv_path)
        if state is not None and state.get("fingerprint") == fingerprint:
            return (True, "venv-reused")
        uv = _find_uv()
        if uv is None:
            return (False, "uv-not-found")
        ok, msg = _sync_dependencies(uv, py_exe, venv_path, wt_path, lock, requirements)
        if not ok:
            return (False, msg)
        _write_provision_state(venv_path, fingerprint)
        return (True, "venv-resynced")

    uv = _find_uv()
    if uv is None:
        return (False, "uv-not-found")
    create = subprocess.run(
        [uv, "venv", str(venv_path), "--python", VENV_PYTHON_VERSION],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if create.returncode != 0:
        return (False, f"venv-create-failed:{create.stderr.strip()[:200]}")
    ok, msg = _sync_dependencies(uv, py_exe, venv_path, wt_path, lock, requirements)
    if not ok:
        return (False, msg)
    if lock is not None or requirements is not None:
        _write_provision_state(venv_path, _provision_fingerprint(lock, requirements))
    return (True, "venv-created")


def _base_branch_for_role(fr_id: str, role: str) -> str:
    """Which existing ref does a fresh role worktree branch off?

      * dev — always `main` (Dev starts from latest merged work).
      * rev — the implementation branch for this FR (`claude/dev-FR-XXXX`
        if it exists, else `claude/mnt-FR-XXXX`), else `main`. Basing off
        the implementation branch is what makes the Reviewer's worktree
        actually contain the Developer's — or the maintainer's — diff
        (FR-0013 AC-11).
      * bkf — always `main`. Backfill mode runs against an already-merged
        FR; the implementation is on `main`, the dev branch may already
        have been deleted by `reconcile-merged`.
      * mnt — always `main`. Maintainer mode is dev-shaped: it implements a
        control-plane FR from scratch, so it starts from latest merged work.
      * gat — the implementation branch (`claude/dev-FR-XXXX` if it exists,
        else `claude/mnt-FR-XXXX`), else `main`. The gate-review worktree is
        a fresh branch (`claude/gat-<FR>`) cut from that tip — "checked out
        at the current `claude/dev-<FR>` tip" (FR-0008:AC-6) without the
        two-worktrees-one-branch conflict a literal same-branch checkout
        would hit.

    For roles we don't recognise, default to `main`.
    @implements FR-0013:AC-11
    @implements FR-0008:AC-6
    """
    if role in ("rev", "gat"):
        found = _implementation_branch_for_fr(fr_id)
        if found is not None:
            return found[0]
    return "main"


def _rev_sync_plan(fr_id: str) -> tuple[str, str]:
    """What bringing `claude/rev-<FR>` up to the implementation branch
    (`claude/dev-<FR>`, else `claude/mnt-<FR>`; FR-0013 AC-11) would take.

    Returns (plan, detail) with plan one of:
      * "noop"         — no implementation/rev branch pair, branches equal,
                         or the implementation branch already contained in
                         rev (nothing to do);
      * "fast-forward" — rev is an ancestor of the implementation branch;
                         `--ff-only` will succeed;
      * "diverged"     — neither contains the other; refuse, never force.
    Pure: inspects refs only.
    @implements FR-0013:AC-11
    """
    found = _implementation_branch_for_fr(fr_id)
    rev_branch = _branch_for(fr_id, "rev")
    if found is None or not _git_branch_exists(rev_branch):
        return ("noop", "no dev/rev branch pair")
    dev_branch, _impl_role = found
    dev_sha = _branch_head_sha(dev_branch) or "?"
    rev_sha = _branch_head_sha(rev_branch) or "?"
    if dev_sha == rev_sha:
        return ("noop", f"{rev_branch} already at {dev_sha[:7]}")
    dev_in_rev, _ = _git_capture(["merge-base", "--is-ancestor", dev_branch, rev_branch], REPO_ROOT)
    if dev_in_rev:
        return ("noop", f"{rev_branch} already contains {dev_branch}")
    rev_in_dev, _ = _git_capture(["merge-base", "--is-ancestor", rev_branch, dev_branch], REPO_ROOT)
    if rev_in_dev:
        return ("fast-forward", f"{rev_branch} {rev_sha[:7]} -> {dev_branch} {dev_sha[:7]}")
    return ("diverged", f"{rev_branch} ({rev_sha[:7]}) and {dev_branch} ({dev_sha[:7]}) have diverged")


def _rev_worktree_dirty_paths(wt_path: Path) -> list[str]:
    """Tracked paths with uncommitted changes in the Reviewer worktree.
    Untracked scratch does not block a fast-forward and is not listed."""
    ok, out = _git_capture(["status", "--porcelain", "--untracked-files=no"], wt_path)
    return _path_lines(out) if ok else ["<git status failed>"]


def _ff_only_merge(wt_path: Path, target_branch: str) -> tuple[bool, str]:
    """`git merge --ff-only <target_branch>` inside `wt_path`.

    Shared plumbing for `_fast_forward_rev_worktree` (FR-0006, syncs the
    *Reviewer* worktree onto the *Developer's* tip before a re-review) and
    `_ff_push_impl_onto_rev` (FR-0013 AC-1, syncs the *implementation*
    branch onto the *Reviewer's* tip after an approve) — mirror images of
    the same fast-forward-only guarantee.

    Returns (ok, message): "fast-forwarded" on success, or the last line
    of git's error output on failure.
    @implements FR-0013:AC-1
    """
    ok, err = _git_capture(["merge", "--ff-only", target_branch], wt_path)
    if not ok:
        lines = _path_lines(err)
        return (False, lines[-1] if lines else err)
    return (True, "fast-forwarded")


def _fast_forward_rev_worktree(fr_id: str, wt_path: Path) -> tuple[bool, str]:
    """Bring a *reused* Reviewer worktree onto the Developer's current tip.

    The rework loop merges the Reviewer branch into the dev worktree before
    every rework round, so by the next re-review `claude/rev-<FR>` is an
    ancestor of `claude/dev-<FR>` and a fast-forward is exactly right. Without
    this step a reused Reviewer worktree re-reviews the previous round's code.
    Anything other than a clean fast-forward is refused: the dispatcher never
    merges (other than `--ff-only`), rebases or resets a role branch.

    Returns (ok, note); on False the caller refuses the spawn.

    @implements FR-0006:AC-10
    @implements FR-0006:AC-11
    """
    plan, detail = _rev_sync_plan(fr_id)
    if plan == "noop":
        return (True, detail)
    if plan == "diverged":
        note = (
            f"{detail}; refusing to sync the Reviewer worktree (fast-forward "
            "impossible; the dispatcher never merges or rebases role branches)"
        )
        return (False, note)
    dirty = _rev_worktree_dirty_paths(wt_path)
    if dirty:
        note = (
            f"Reviewer worktree {wt_path} has uncommitted tracked changes "
            f"({', '.join(dirty[:10])}); commit or stage-and-finalize them before "
            "a re-review, or clean the worktree"
        )
        return (False, note)
    # @implements FR-0013:AC-11 — the implementation branch is the same one
    # `_rev_sync_plan` just resolved "fast-forward" against: `claude/dev-<FR>`
    # if it exists, else `claude/mnt-<FR>`.
    found = _implementation_branch_for_fr(fr_id)
    dev_branch = found[0] if found is not None else _branch_for(fr_id, "dev")
    ok, msg = _ff_only_merge(wt_path, dev_branch)
    if not ok:
        return (False, f"fast-forward of {wt_path} onto {dev_branch} failed: {msg}")
    return (True, f"fast-forwarded {detail}")


def _print_rev_sync_preview(fr_id: str, role: str, wt_preview: Path) -> bool:
    """Dry-run twin of the reused-Reviewer-worktree sync: says what
    `ensure_role_worktree` would do, and mutates nothing. Returns False when
    the apply path would refuse the spawn, so the caller can withhold its
    WOULD-SPAWN line and the preview matches what `--apply` does.

    @implements FR-0006:AC-12
    """
    if role != "rev" or not wt_preview.exists():
        return True
    plan, detail = _rev_sync_plan(fr_id)
    if plan == "fast-forward":
        print(f"  {fr_id}  WOULD-FAST-FORWARD  {detail}")
    elif plan == "diverged":
        print(f"  {fr_id}  WOULD-REFUSE  {detail}; spawn would be refused")
        return False
    return True


def _owns_preflight_for(fr_id: str, role: str) -> int | None:
    """Preflight + WARN printing for a spawn's `owns:`-derived grants,
    generalised from the `dev`-only original so `rev`/`bkf` get the same
    reporting for their FR-0010:AC-5 grants.

    @implements FR-0009:AC-2
    @implements FR-0009:AC-3
    @implements FR-0009:AC-5
    @implements FR-0009:AC-7
    @implements FR-0010:AC-5

    Runs identically whether the caller is about to preview (`--dry-run`)
    or actually spawn, so a dry-run shows exactly what `--apply` would do
    (mirroring `_print_rev_sync_preview`'s role for the Reviewer worktree
    sync). Prints one WARN line per AC-2 withheld glob and one WARN line
    per AC-3 harness-guarded glob — both before the caller's own
    WOULD-SPAWN/SPAWNED line, satisfying AC-3's ordering requirement.

    Returns the `owns-grants=<n>` count (AC-7) on success, or None when
    `owns:` is malformed (AC-5): an ERROR line has already been printed
    and the caller must skip the spawn entirely. For `dev`, `ensure_role_
    worktree` enforces the same refusal for `--apply` as defense in depth,
    so the two can never disagree about whether a spawn was allowed to
    proceed.
    """
    derivation = dev_owns_derivation(fr_id)
    if derivation["invalid"]:
        for msg in derivation["invalid"]:
            print(f"  {fr_id}.{role}  ERROR — {msg}")
        return None
    for glob in derivation["withheld"]:
        advice = (
            "dev cannot be granted it — dispatch this FR in `mnt` mode instead"
            if role == "dev"
            else f"{role} cannot be granted it — control-plane paths are `mnt`-only"
        )
        print(
            f"  {fr_id}.{role}  WARN — owns: {glob!r} is a protected control-plane path; {advice}"
        )
    for glob in derivation["harness_guarded"]:
        hint = mnt_unwritable_hint(glob)
        suffix = f"; {hint}" if hint else ""
        print(
            f"  {fr_id}.{role}  WARN — owns: {glob!r} is harness-guarded "
            f"independently of the settings file{suffix}"
        )
    return len(derivation["granted"])


def _dev_owns_preflight(fr_id: str) -> int | None:
    """`dev`'s preflight — kept as its own name (many call sites and the
    FR-0009 docstring reference it) but delegating to the role-general
    helper. Message text for `dev` is unchanged from before FR-0010."""
    return _owns_preflight_for(fr_id, "dev")


# @implements FR-0016:AC-1
def ensure_role_worktree(
    fr_id: str, role: str, adapter: HarnessAdapter, gate_id: str | None = None
) -> tuple[Path | None, str]:
    """Create or reuse a per-FR worktree at .claude/worktrees/<role>-<FR-id>.

    On (re)entry, always rewrites the harness-appropriate settings file
    (Claude: .claude/settings.local.json; Cursor: .cursor/cli.json) and
    pre-provisions the dispatch venv so the agent never has to ask for
    env-setup approval mid-task.

    The new branch is `claude/<role>-<fr_id>`, based off `main` for Dev and
    off `claude/dev-<fr_id>` for Reviewer (so the Reviewer's worktree
    actually contains the Developer's diff).

    Returns (worktree_path, status) where status is one of: "created",
    "reused", "error:<msg>".
    """
    wt_root = REPO_ROOT / ".claude" / "worktrees"
    wt_path = wt_root / f"{role}-{fr_id}"
    branch = f"claude/{role}-{fr_id}"
    base_branch = _base_branch_for_role(fr_id, role)
    # Guard: a worktree is a clean checkout of `base_branch`. If the FR's spec
    # was authored but never committed onto that branch, the worktree can't see
    # it and the agent fails with "FR not found" (the FR-0014 failure mode).
    # Refuse the spawn with an actionable error instead of launching blind.
    if not _fr_spec_committed_on_branch(fr_id, base_branch):
        return (
            None,
            f"error:{fr_id} spec is untracked on '{base_branch}' — commit it "
            f"before dispatch (git add specs/{fr_id}-*.md specs/INDEX.md "
            f"CODEOWNERS && git commit)",
        )
    # `mnt` has no static footprint — it is granted exactly what the target FR
    # declares in `owns:`. With nothing declared there is no footprint to
    # derive, so refuse rather than run unscoped.
    if role == "mnt" and not fr_owns_globs(fr_id):
        return (
            None,
            f"error:{fr_id} declares no `owns:` frontmatter — `mnt` derives its "
            f"writable footprint from it and will not run unscoped",
        )
    # @implements FR-0009:AC-5, FR-0015:AC-5 — every role that derives its
    # permission file from `owns:` (`dev_permissions`; `owns_derived_
    # permissions` / `cursor_owns_derived_permissions` for rev/bkf;
    # `mnt_permissions` for mnt) refuses a malformed entry the same way `dev`
    # already did, with the same error text — returned here, before the
    # `wt_status`/reuse block below (so before `rev`'s reuse fast-forward
    # too), any settings file is written, any venv is provisioned, any
    # process is spawned, or any spawn record is written. `mnt`'s
    # empty-`owns:` refusal above is unchanged and runs first.
    if role in ("dev", "rev", "bkf", "mnt"):
        invalid = _invalid_owns_entries(fr_id)
        if invalid:
            return (None, "error:" + "; ".join(invalid))
    wt_status: str
    if wt_path.exists():
        wt_status = "reused"
        # A reused Reviewer worktree must review the Developer's *current*
        # tip (round-2+ re-review, or a re-run rev tick). Refused rather than
        # forced when a fast-forward is impossible.
        if role == "rev":
            ff_ok, ff_note = _fast_forward_rev_worktree(fr_id, wt_path)
            if not ff_ok:
                return (None, f"error:{ff_note}")
            if ff_note.startswith("fast-forwarded"):
                wt_status = "reused,fast-forwarded"
    else:
        wt_root.mkdir(parents=True, exist_ok=True)
        add_with_new_branch = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "worktree",
                "add",
                "-b",
                branch,
                str(wt_path),
                base_branch,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if add_with_new_branch.returncode == 0:
            wt_status = "created"
        else:
            add_existing_branch = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "worktree", "add", str(wt_path), branch],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if add_existing_branch.returncode == 0:
                wt_status = "created"
            else:
                err = (
                    add_with_new_branch.stderr.strip()
                    or add_existing_branch.stderr.strip()
                )
                return (None, f"error:{err}")
    if gate_id:
        adapter.write_worktree_settings(wt_path, role, fr_id, gate_id=gate_id)
    else:
        adapter.write_worktree_settings(wt_path, role, fr_id)
    # @implements FR-0024:AC-2 — the venv, and the lock-file and
    # `requirements.txt` lookup, are the project's; the prefix is worked out
    # here, never inside `ensure_dev_venv`.
    wt_project = _worktree_project_root(wt_path)
    venv_ok, venv_msg = ensure_dev_venv(wt_project)
    if not venv_ok:
        # Soft-fail (FR-0010:AC-9): the agent can still run against system
        # python; surface the issue in the status string so the dispatcher
        # logs it but doesn't abort the spawn. One WARN line names the
        # classification and the lock/requirements file provisioning was
        # reading, before the caller's own spawn-report line.
        classification = venv_msg.split(":", 1)[0]
        lock = stack_profile.find_lock_file(wt_project)
        requirements = None if lock else stack_profile.find_requirements_file(wt_project)
        if lock is not None:
            source = f"uv.lock at {lock}"
        elif requirements is not None:
            source = f"requirements file at {requirements}"
        else:
            source = "no lock/requirements file (static VENV_PACKAGES only)"
        print(
            f"  {fr_id}.{role}  WARN — venv provisioning failed: {classification} ({source})"
        )
        return (wt_path, f"{wt_status},{venv_msg}")
    return (wt_path, f"{wt_status},{venv_msg}")


# Backwards-compat alias for any external callers (and for clarity in older
# logs / hooks). New code should use ensure_role_worktree directly.
ensure_dev_worktree = ensure_role_worktree


# FR-0018 AC-1: the two variables `spawn_role` exports beside DISPATCH_RUN_ID.
# Spelled here as well as in `metrics_log` because that import is optional.
_METRICS_DIR_ENV = "DISPATCH_METRICS_DIR"
_WORKTREE_ENV = "DISPATCH_WORKTREE"


# ---------------------------------------------------------------------------
# FR-0024: a project in a subdirectory of its repository
#
# The prefix is the project directory's path inside its repository
# (`projects/demo/`), or "" when the project is the repository. It is worked
# out at call time from the current `REPO_ROOT` (tests re-point it) and
# cached per `REPO_ROOT` — never at import and never inside
# `ensure_dev_venv`. Every helper below is the identity at prefix "".
# ---------------------------------------------------------------------------

_PROJECT_PREFIX_CACHE: dict[str, str] = {}


def _project_prefix() -> str:
    """`git -C <REPO_ROOT> rev-parse --show-prefix`, normalised to POSIX with
    one trailing `/`, or "" when `REPO_ROOT` is the repository top level or
    is not inside a git repository. Cached per `REPO_ROOT`.

    A `REPO_ROOT` that holds its own `.git` (a directory, or the file a
    linked worktree or submodule has) is a working-tree top level, so its
    prefix is "" without running git. The prefix is never derived by
    comparing resolved paths: Windows may hand back 8.3 short names.
    @implements FR-0024:AC-1
    """
    root = REPO_ROOT
    key = str(root)
    cached = _PROJECT_PREFIX_CACHE.get(key)
    if cached is not None:
        return cached
    prefix = ""
    if not (root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", key, "rev-parse", "--show-prefix"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        out = getattr(proc, "stdout", None)
        if proc is not None and proc.returncode == 0 and isinstance(out, str):
            text = out.strip().replace("\\", "/").strip("/")
            prefix = f"{text}/" if text else ""
    _PROJECT_PREFIX_CACHE[key] = prefix
    return prefix


def _repo_path(rel: str) -> str:
    """A project-relative path as the repository names it: `<prefix><rel>`.
    For `<rev>:<path>` object reads and pathspecs given from a worktree root,
    where git resolves from the repository top (`git show :./x` would
    resolve against the `-C` directory instead). @implements FR-0024:AC-3"""
    return _project_prefix() + rel


def _worktree_project_root(wt_path: Path) -> Path:
    """The project root inside the role worktree at `wt_path`:
    `<worktree root>/<prefix>`. The one definition of it (FR-0024 AC-2,
    DEC-0031 item 1): the agent's cwd, its permission file, `PR_BODY.md`,
    the review files, the gate and indexer it runs, `tests/` and the venv
    are all found here, and `spawn_role` exports it as DISPATCH_WORKTREE —
    the directory whose `scripts/metrics_log.py` the agent runs. At prefix
    "" it is the worktree itself. `metrics_log`'s comparison against it is
    unchanged (DEC-0030). Worktrees themselves are created, locked and
    removed at `wt_path`, never here (`git worktree remove <wt>/<prefix>`
    is "not a working tree").
    @implements FR-0018:AC-1
    @implements FR-0024:AC-2
    """
    prefix = _project_prefix()
    return wt_path / prefix if prefix else wt_path


def _layout_footprint_root() -> str:
    """The project's `footprint_root`, read only through
    `project_layout.load(REPO_ROOT)` (DEC-0031 item 4). `project` when there
    is no sibling `project_layout.py`, no layout file, or a layout the loader
    refuses (the entry points have already refused that case: AC-6; a helper
    reached some other way fails closed, since `project` treats every path
    outside the project as unowned and grants nothing absolute).
    @implements FR-0024:AC-4
    """
    if _project_layout is None:
        return "project"
    try:
        return _project_layout.load(REPO_ROOT).footprint_root
    except _project_layout.LayoutInvalid:
        return "project"


def _project_relpath(path: str) -> str | None:
    """A repo-relative path (as `diff --name-only`, `status --porcelain` and
    a worktree-root `ls-files` print it) relative to the project, or None
    when it lies outside the project. The coordinates of the project's own
    control plane (`MNT_PROTECTED_GLOBS`, `MNT_NEVER_WRITABLE`) and of the
    fixed project prefixes (`specs/_metrics/`, `specs/_gates/`, `tests/`)
    under either footprint root: under `repo` those are `<prefix><glob>`,
    which is the same test. @implements FR-0024:AC-4"""
    prefix = _project_prefix()
    if not prefix:
        return path
    return path[len(prefix):] if path.startswith(prefix) else None


def _footprint_relpath_fn():
    """A converter from repo-relative paths to the FR's footprint coordinates
    — what `owns:` is compared with. `footprint_root: project` (the default):
    strip the prefix, None for a path outside the project, which therefore
    never matches `owns:`. `footprint_root: repo`: the repo-relative path
    as it is. The identity at prefix "". Built once per caller so the layout
    is read once. @implements FR-0024:AC-4"""
    if not _project_prefix() or _layout_footprint_root() == "repo":
        return lambda path: path
    return _project_relpath


def _project_control_plane_path(path: str) -> bool:
    """True iff a repo-relative path is one of the project's own
    `MNT_PROTECTED_GLOBS`. A path outside the project is not its control
    plane (FR-0024 AC-4). @implements FR-0024:AC-4"""
    rel = _project_relpath(path)
    return rel is not None and _owned(rel, list(MNT_PROTECTED_GLOBS))


def _claude_absolute_rule_root(path: Path) -> str:
    """`//` plus `path`'s absolute POSIX spelling and one trailing `/`: the
    prefix of a Claude Code rule anchored at the filesystem root. On Windows
    Claude Code matches paths in POSIX form, the drive becoming its first
    segment in lower case (`C:\\x` -> `/c/x`), so the rule reads `//c/x/...`
    (the spelling the Reviewer's live run confirms, FR-0024 Notes).
    @implements FR-0024:AC-5
    """
    posix = Path(os.path.realpath(path)).as_posix()
    m = re.match(r"^([A-Za-z]):/?(.*)$", posix)
    if m:
        posix = f"/{m.group(1).lower()}/{m.group(2)}"
    return "/" + posix.rstrip("/") + "/"


def _absolute_grant_anchor(wt_path: Path) -> str:
    """The prefix each `owns:`-derived grant takes for the worktree at
    `wt_path`: "" (relative grants, today's file) unless the prefix is
    non-empty and `footprint_root` is `repo`, when `owns:` names
    repository paths an agent started in `<wt>/<prefix>` cannot reach with
    a relative rule. @implements FR-0024:AC-5"""
    if not _project_prefix() or _layout_footprint_root() != "repo":
        return ""
    return _claude_absolute_rule_root(wt_path)


def _layout_refusal() -> str | None:
    """The loader's message when the project's `.agent-team/layout.yaml` is
    malformed and the dispatcher would read it, else None. The dispatcher
    reads the layout only for a project in a subdirectory (at prefix "" every
    conversion is the identity and nothing is read), so a project that is its
    own repository dispatches exactly as before this FR whatever its layout
    holds — the fixed byte-identity clause. With no layout file this runs no
    subprocess at all. @implements FR-0024:AC-6"""
    if _project_layout is None:
        return None
    if not (REPO_ROOT / _project_layout.LAYOUT_RELPATH).is_file():
        return None
    if not _project_prefix():
        return None
    try:
        _project_layout.load(REPO_ROOT)
    except _project_layout.LayoutInvalid as e:
        return str(e)
    return None


def _spawn_extra_kwargs(preflight_segment: str) -> dict[str, str]:
    """`{"preflight_segment": ...}` only when there is something to carry —
    every `spawn_role` call site does `**_spawn_extra_kwargs(...)` rather than
    always passing the keyword, so a no-op pre-flight (AC-10: no stack, or
    `--skip-env-preflight` never used) leaves the call byte-identical to
    pre-FR-0011, including for a caller that monkeypatches `spawn_role` with a
    narrower fake signature that doesn't know this keyword exists."""
    return {"preflight_segment": preflight_segment} if preflight_segment else {}


def spawn_role(
    fr_id: str,
    role: str,
    apply: bool,
    adapter: HarnessAdapter,
    extra_prompt: str | None = None,
    round_num: int = 1,
    preflight_segment: str = "",
    gate_id: str | None = None,
) -> tuple[str, int | None, Path | None]:
    """`round_num` is the Dev<->Reviewer round this spawn belongs to (1 = the
    base pipeline); it is recorded on the lock and the metrics records only.
    `preflight_segment` is FR-0011's `EnvPreflightGate.metrics_segment` for
    this invocation (`""`, `"preflight=<classes>"` or `"preflight=skipped"`),
    computed once by the caller's single `_run_env_preflight` call and passed
    through to every spawn that invocation makes — never recomputed here.
    `gate_id` (FR-0008:AC-6) is set only for `role == "gat"`: the one
    declared gate this session reviews — threaded to the worktree's
    permission derivation and the rendered slash-command prompt."""
    # @implements FR-0024:AC-6 — a layout the loader refuses stops the spawn
    # before any worktree, file or process, in dry-run and with --apply.
    layout_err = _layout_refusal()
    if layout_err is not None:
        return (f"error:{layout_err}", None, None)
    if not apply:
        return ("dry-run", None, None)
    # Only forward `gate_id` when set: `ensure_role_worktree` doubles that
    # predate the parameter (test fakes) keep working for every non-`gat`
    # spawn, which passes none.
    if gate_id is not None:
        wt_path, wt_status = ensure_role_worktree(fr_id, role, adapter, gate_id=gate_id)
    else:
        wt_path, wt_status = ensure_role_worktree(fr_id, role, adapter)
    if wt_path is None:
        return (wt_status, None, None)
    log_path = DISPATCH_DIR / f"{fr_id}.{role}.log"
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    # FR-0002: one run_id per agent invocation, exported to the agent as
    # DISPATCH_RUN_ID (plus METRICS_PROJECT) so gate runs inside its worktree
    # join this run's records; the dispatcher's own environment is restored
    # right after the spawn.
    run_id = _metrics.new_id() if _metrics is not None else uuid.uuid4().hex
    child_env = {"DISPATCH_RUN_ID": run_id}
    if _metrics is not None and not os.environ.get(_metrics.PROJECT_ENV):
        child_env[_metrics.PROJECT_ENV] = _metrics.project_name()
    # @implements FR-0018:AC-1 — the agent's gate and escalation-log records
    # go to the primary checkout's log, not its branch: `metrics_log` follows
    # DISPATCH_METRICS_DIR only from the project root DISPATCH_WORKTREE names.
    # Restored with the rest of `child_env` below.
    child_env[_METRICS_DIR_ENV] = os.path.abspath(REPO_ROOT / "specs" / "_metrics")
    child_env[_WORKTREE_ENV] = os.path.abspath(_worktree_project_root(wt_path))
    saved_env = {k: os.environ.get(k) for k in child_env}
    os.environ.update(child_env)
    try:
        # Only forward `extra_prompt` / `gate_id` when set: adapter doubles
        # that predate either parameter (test fakes, older harnesses) keep
        # working for the common non-rework, non-gat path, which passes
        # neither.
        spawn_kwargs: dict[str, str] = {}
        if extra_prompt is not None:
            spawn_kwargs["extra_prompt"] = extra_prompt
        if gate_id is not None:
            spawn_kwargs["gate_id"] = gate_id
        result, pid = adapter.spawn(fr_id, role, wt_path, log_path, **spawn_kwargs)
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if result != "spawned":
        return (result, None, wt_path)
    base_branch = _base_branch_for_role(fr_id, role)
    write_lock(
        fr_id,
        role,
        pid,
        worktree=str(wt_path),
        branch=f"claude/{role}-{fr_id}",
        base_branch=base_branch,
        worktree_status=wt_status,
        harness=adapter.name,
        run_id=run_id,
        round=round_num,
    )
    _RUN_REGISTRY[(fr_id, role)] = {
        "run_id": run_id,
        "started_at": dt.datetime.now(dt.timezone.utc).timestamp(),
        "round": round_num,
    }
    # @implements FR-0002:AC-3 (spawn record; never on dry-run)
    # @implements FR-0010:AC-7 (DEC-0003 v2) — the detected stack is
    # appended to `worktree_status` as one comma-delimited segment,
    # `stack=<ids joined by '+'>`, only when the stack is non-empty; an
    # empty stack appends nothing so a no-stack project's record stays
    # byte-identical to the pre-FR-0010 value.
    # @implements FR-0010:AC-9 (DEC-0003 v2) — a failed venv provisioning
    # appends one further segment, `venv=<classification>` (closed-set
    # classification only, never the `:`-suffixed detail), ordered after
    # `stack=`; a successful or reused venv appends nothing.
    metrics_worktree_status = wt_status.split(",")[0]
    stack_tools = detected_stack_tools()
    if stack_tools:
        metrics_worktree_status += f",{_stack_metrics_segment(stack_tools)}"
    venv_segment = _venv_metrics_segment(wt_status)
    if venv_segment:
        metrics_worktree_status += f",{venv_segment}"
    # @implements FR-0011:AC-7, FR-0011:AC-8 — DEC-0003 order: stack, venv,
    # then preflight; only when non-empty.
    if preflight_segment:
        metrics_worktree_status += f",{preflight_segment}"
    _metrics_emit(
        "dispatch.spawn",
        role=role,
        object_ids=[fr_id],
        run_id=run_id,
        harness=adapter.name,
        worktree_status=metrics_worktree_status,
        base_branch=base_branch,
        model=_resolve_model(role) if adapter.name == "claude-code" else None,
        round=round_num,
    )
    return ("spawned", pid, wt_path)


# ---------------------------------------------------------------------------
# Reconcile-merged: project GitHub-merged PRs back into the spec graph
# ---------------------------------------------------------------------------
#
# After a PR merges on origin/main, the dispatcher's local view goes stale
# in three places:
#   1. Spec frontmatter `status` still reads `ready` / `in-progress` /
#      `in-review`. `runnable_frs` filters on this and will re-fire the
#      same FR. Worse, dependents that gate on `status in TERMINAL_STATUSES`
#      stay blocked.
#   2. The post-merge worktree, branch, and lockfile all survive locally.
#      A re-fire reuses the stale worktree at the merged tip and either
#      no-ops confusingly or piles new commits onto an already-merged
#      branch.
#   3. No-one writes the changelog entry that records the merge.
#
# `reconcile-merged` (and the auto-tick variant of the same) closes all
# three. It treats GitHub PR state as the source of truth ("this branch
# is merged") and projects it back into the spec graph + working state.
# Read-only by default; `--apply` commits the frontmatter flips and
# removes the worktrees/branches/locks. Idempotent: re-runs against
# already-merged-and-cleaned FRs are no-ops.

_FR_BRANCH_RE = re.compile(r"^claude/(dev|rev|bkf|mnt|docs)-(FR-\d{4})$")

# Conventional-commit header: `type(scope): subject`. The project convention is
# that scope is the FR id(s) a PR touches, so the scope is a second, independent
# way to identify the FR behind a merged PR.
_CC_SCOPE_BODY_RE = re.compile(r"^[a-z]+\(([^)]*)\)!?:", re.IGNORECASE)


def fr_ids_from_pr_title(title: str) -> list[str]:
    """Distinct FR ids in a PR title's conventional-commit scope.

    Only the scope is consulted, never the subject: a subject mentioning a
    neighbouring FR ("feat(FR-0041): unblock FR-0009") must not be read as
    touching it. Returns [] when the title is not a conventional-commit header
    or its scope names no FR, which callers treat as "cannot attribute".
    """
    m = _CC_SCOPE_BODY_RE.match(title.strip())
    if m is None:
        return []
    out: list[str] = []
    for fr_id in re.findall(r"FR-\d{4}", m.group(1), flags=re.IGNORECASE):
        upper = fr_id.upper()
        if upper not in out:
            out.append(upper)
    return out


@dataclasses.dataclass
class ReconcileSummary:
    flipped: list[str]
    cleaned: list[str]
    skipped: list[tuple[str, str]]
    gh_unavailable: bool = False


# @implements FR-0016:AC-1
def _git_fetch_origin_main(timeout_s: int = 15) -> tuple[bool, str]:
    """Fetch origin/main. Failure is non-fatal."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "fetch", "origin", "main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git fetch failed").strip()
        return (False, err)
    return (True, "ok")


# @implements FR-0016:AC-1
def _commits_behind_origin_main() -> int:
    """Return commit count of main..origin/main."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "rev-list",
            "--count",
            "main..origin/main",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if proc.returncode != 0:
        return 0
    try:
        return int((proc.stdout or "0").strip() or "0")
    except ValueError:
        return 0


# @implements FR-0016:AC-1, FR-0016:AC-3
def _run_deploy_gate(
    stage: str,
    env_extra: dict[str, str] | None = None,
    *,
    cwd: Path | None = None,
    status_only: bool = False,
) -> tuple[bool, str]:
    """Run deploy-gate.py; return (ok, combined output). `env_extra` carries
    the metrics variables (invoked_by, run_id, record id) for the gate's own
    `gate.run` record; the gate's behaviour is otherwise unaffected.

    `cwd` (default `REPO_ROOT`) selects which checkout's copy of the gate
    runs — the gate resolves its own `REPO_ROOT` from `__file__`, so passing
    a role worktree's path gates that worktree's tree, not the primary
    checkout (DEC-0011). `status_only`, when true, appends `--status-only`
    to the gate's argv (FR-0002 AC-4: observe without writing).
    """
    root = cwd or REPO_ROOT
    gate = root / "scripts" / "deploy-gate.py"
    argv = [sys.executable, str(gate), "--stage", stage]
    if status_only:
        argv.append("--status-only")
    proc = subprocess.run(
        argv,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env_extra or {})},
    )
    out = "\n".join(
        x for x in [(proc.stdout or "").strip(), (proc.stderr or "").strip()] if x
    )
    return proc.returncode == 0, out


# @implements FR-0016:AC-5
def _prepend_forced_gate_banner(path: Path, operator_note: str) -> None:
    banner = f"> ⚠️ Forced past red gate by {operator_note}\n\n"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if banner.strip() not in text:
            path.write_text(banner + text, encoding="utf-8", newline="\n")


def _finalize_gate_preflight(
    *,
    fr_id: str,
    role: str,
    stage: str,
    draft: bool,
    force: bool,
    pr_body_path: Path | None = None,
    cwd: Path | None = None,
    status_only: bool = False,
) -> tuple[bool, str | None]:
    """Refuse finalize when the deploy gate is red (draft PRs exempt).

    FR-0002 AC-4: the gate run is invoked with the metrics environment so its
    `gate.run` record carries `invoked_by: dispatch-finalize`, the agent's
    run_id, a record id the `pr.opened` record cites, and — when a red gate is
    overridden — `forced: true` or `draft_exempt: true`.

    `cwd` and `status_only` are threaded straight through to both
    `_run_deploy_gate` calls below (DEC-0011). When `status_only` is true no
    metrics environment is built at all — the run registers no record id, so
    nothing is left to cite.
    """
    gate_env = {} if status_only else _gate_metrics_env(fr_id, role)
    if force:
        note = os.environ.get("USER") or os.environ.get("USERNAME") or "operator"
        print(
            f"  {fr_id}.{role}  WARN — --force bypasses deploy gate ({stage})",
            file=sys.stderr,
        )
        if pr_body_path is not None:
            _prepend_forced_gate_banner(
                pr_body_path, f"{note} via dispatch finalize --force"
            )
        # The gate is bypassed, not skipped from the record: run it for its
        # `gate.run` record only (output discarded, outcome ignored) so the
        # forced-past-red signal IDEA-0016 measured is kept. Never load-bearing.
        if gate_env:
            try:
                _run_deploy_gate(
                    stage,
                    {**gate_env, "METRICS_GATE_OVERRIDE": "forced"},
                    cwd=cwd,
                    status_only=status_only,
                )
            except Exception as e:  # noqa: BLE001
                _metrics.warn(f"gate.run (forced): {type(e).__name__}: {e}")
        return (True, "forced")
    if gate_env and draft and role in ("dev", "bkf"):
        gate_env["METRICS_GATE_OVERRIDE"] = "draft-exempt"
    ok, output = _run_deploy_gate(stage, gate_env or None, cwd=cwd, status_only=status_only)
    if ok:
        return (True, None)
    print(output)
    if draft and role in ("dev", "bkf"):
        print(
            f"  {fr_id}.{role}  WARN — deploy gate failed but proceeding "
            f"(draft PR exempt)"
        )
        record = _load_pr_record(fr_id, role) or {}
        record["gate_warning_at_finalize"] = output[-2000:]
        _save_pr_record(fr_id, role, record)
        return (True, "draft-exempt")
    print(f"  {fr_id}.{role}  ERROR — deploy gate ({stage}) failed; refusing finalize")
    return (False, "gate-failed")


# @implements FR-0016:AC-1, FR-0016:AC-4
def _gh_merged_prs(limit: int = 100) -> list[dict] | None:
    """Returns parsed JSON of merged PRs, or None if gh is unavailable.

    Each row has shape:
      {"number": int, "headRefName": str, "mergedAt": str,
       "mergeCommit": {"oid": str}, "title": str}
    """
    nwo = _repo_nwo()
    if nwo is None:
        return None
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            nwo,
            "--state",
            "merged",
            "--limit",
            str(limit),
            "--json",
            "number,headRefName,mergedAt,mergeCommit,title",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None


# @implements FR-0016:AC-1
def _on_default_branch(branch: str = "main") -> bool:
    """True if the primary worktree is currently on `branch`."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    return proc.returncode == 0 and proc.stdout.strip() == branch


# @implements FR-0016:AC-5
def _flip_frontmatter_to_merged(
    spec_path: Path, prev_status: str, pr_number: int, merge_sha: str
) -> bool:
    """Edit `spec_path` in place: flip `status:` to `merged`, bump `updated:`,
    and append a Changelog entry citing the PR + merge SHA. Returns True iff
    the file was modified.

    Convention: Changelog is the
    final section in every spec, so a tail-append is the right surface.
    Falls back to creating a Changelog section if one is somehow missing.
    """
    text = spec_path.read_text(encoding="utf-8")
    m = FRONTMATTER_PATTERN.match(text)
    if m is None:
        return False
    fm_span = text[m.start() : m.end()]
    today = dt.date.today().isoformat()
    new_fm = re.sub(
        r"^status:\s*\S+",
        "status: merged",
        fm_span,
        count=1,
        flags=re.MULTILINE,
    )
    new_fm = re.sub(
        r"^updated:\s*\S+",
        f"updated: {today}",
        new_fm,
        count=1,
        flags=re.MULTILINE,
    )
    body = text[m.end() :]
    nwo = _repo_nwo() or "unknown/unknown"
    short_sha = merge_sha[:7] if merge_sha else "unknown"
    entry = (
        f"- {today}: status `{prev_status}` → `merged`. "
        f"PR [#{pr_number}](https://github.com/{nwo}/pull/{pr_number}) "
        f"merged into `main` as commit `{short_sha}`. "
        f"Auto-projected by `dispatch.py reconcile-merged`."
    )
    if "## Changelog" in body:
        body = body.rstrip() + "\n" + entry + "\n"
    else:
        body = body.rstrip() + "\n\n## Changelog\n\n" + entry + "\n"
    spec_path.write_text(new_fm + body, encoding="utf-8", newline="\n")
    return True


# @implements FR-0016:AC-1, FR-0016:AC-3
def _refresh_spec_index() -> bool:
    """Re-run `scripts/index-specs.py` so `specs/INDEX.md` catches up with
    the just-flipped frontmatter. Returns True on success (or no-op).
    """
    indexer = REPO_ROOT / "scripts" / "index-specs.py"
    if not indexer.exists():
        return True
    proc = subprocess.run(
        [sys.executable, str(indexer)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc.returncode == 0


# @implements FR-0016:AC-1
def _commit_spec_flip(fr_id: str, pr_number: int, merge_sha: str) -> tuple[bool, str]:
    """Stage + commit the frontmatter flip (and refreshed INDEX.md) on the
    primary worktree. Returns (ok, note).
    """
    _refresh_spec_index()
    add = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "add",
            "--",
            f"specs/{fr_id}-*.md",
            "specs/INDEX.md",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if add.returncode != 0:
        return (False, (add.stderr or add.stdout or "git add failed").strip())
    diff = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--cached", "--quiet"],
        capture_output=True,
        timeout=10,
    )
    if diff.returncode == 0:
        return (True, "no-op")
    short_sha = merge_sha[:7] if merge_sha else "unknown"
    msg = f"docs({fr_id}): mark merged (PR #{pr_number}, {short_sha})"
    cm = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "commit", "-m", msg],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if cm.returncode != 0:
        err = (cm.stderr or cm.stdout or "git commit failed").strip().splitlines()
        return (False, err[-1] if err else "git commit failed")
    return (True, "committed")


# @implements FR-0016:AC-1
def _git_remove_worktree(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return (True, "absent")
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return (False, err[-1] if err else "git worktree remove failed")
    return (True, "removed")


# @implements FR-0016:AC-1
def _git_delete_branch(branch: str) -> tuple[bool, str]:
    if not _git_branch_exists(branch):
        return (True, "absent")
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "branch", "-D", branch],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return (False, err[-1] if err else "git branch -D failed")
    return (True, "deleted")


def reconcile_merged_prs(
    apply: bool = False, verbose: bool = True
) -> ReconcileSummary:
    """Project every merged `claude/{dev,rev}-FR-XXXX` PR back into local state.

    For each FR with at least one merged PR on origin:
      * Flip frontmatter `status` -> `merged` (with date + Changelog entry),
        and commit `docs(FR-XXXX): mark merged (PR #N, <sha>)` per FR.
        Skipped if the primary worktree is not on `main` (commit would land
        on the wrong branch).
      * Remove the role's worktree, local branch, and lockfile. Skipped if
        the lock is currently `held` (an agent is actively running there).

    Idempotent: terminal-status FRs trigger only the cleanup step; FRs whose
    worktree/branch/lock are already gone are no-ops.
    """
    summary = ReconcileSummary(flipped=[], cleaned=[], skipped=[])
    ok, _ = _gh_preflight(verbose=False)
    if not ok:
        summary.gh_unavailable = True
        if verbose:
            print(
                "reconcile-merged: gh unavailable; skipping. Run `gh auth login` to enable."
            )
        return summary
    rows = _gh_merged_prs()
    if rows is None:
        summary.gh_unavailable = True
        if verbose:
            print("reconcile-merged: failed to query merged PRs from origin")
        return summary

    by_fr: dict[str, dict[str, dict | None]] = {}
    for row in rows:
        head = str(row.get("headRefName", ""))
        m = _FR_BRANCH_RE.match(head)
        if not m:
            continue
        role, fr_id = m.group(1), m.group(2)
        slot = by_fr.setdefault(
            fr_id, {"dev": None, "rev": None, "bkf": None, "mnt": None}
        )
        prev = slot[role]
        if prev is None or str(row.get("mergedAt", "")) > str(
            prev.get("mergedAt", "")
        ):
            slot[role] = row

    if not by_fr:
        if verbose:
            print(
                "reconcile-merged: no merged PRs match `claude/{dev,rev}-FR-XXXX`"
            )
        return summary

    on_main = _on_default_branch("main")

    for fr_id in sorted(by_fr):
        slot = by_fr[fr_id]
        # `mnt` PRs carry the FR's implementation the same way `dev` PRs do,
        # so a merged mnt PR is a valid trigger for the status flip.
        pr_for_flip = slot["dev"] or slot["mnt"] or slot["rev"]
        spec_paths = list(SPECS_DIR.glob(f"{fr_id}-*.md"))
        if not spec_paths:
            summary.skipped.append((fr_id, "no spec file under specs/"))
            if verbose:
                print(f"  {fr_id}  SKIP — no spec file")
            continue
        spec_path = spec_paths[0]
        text = spec_path.read_text(encoding="utf-8")
        m = FRONTMATTER_PATTERN.match(text)
        prev_status = ""
        meta: dict = {}
        if m:
            try:
                meta = yaml.safe_load(m.group(1)) or {}
                prev_status = str(meta.get("status", ""))
            except yaml.YAMLError:
                prev_status = ""
                meta = {}

        flip_msg = ""
        # @implements FR-0008:AC-10 — populated only in the actual-flip branch
        # below (a merge with a PR record, on main, not already terminal).
        gate_bypasses: list[tuple[dict, str]] = []
        if prev_status in TERMINAL_STATUSES:
            flip_msg = f"already {prev_status}"
        elif not pr_for_flip:
            flip_msg = "no PR record for flip (cleanup-only)"
        elif not on_main:
            summary.skipped.append(
                (
                    fr_id,
                    f"primary worktree off main; {prev_status} -> merged not committed",
                )
            )
            flip_msg = f"BLOCKED off-main; would flip {prev_status} -> merged"
        else:
            pr_num = int(pr_for_flip.get("number", 0))
            merge_sha = str((pr_for_flip.get("mergeCommit") or {}).get("oid", ""))
            # @implements FR-0008:AC-10 — check every declared gate's status
            # on the merge commit (the tree the merge actually put on
            # `main`), regardless of apply/dry-run, so a dry-run `reconcile-
            # merged` also warns.
            merge_role = "dev" if slot["dev"] else ("mnt" if slot["mnt"] else "rev")
            for g in _parse_gates(meta):
                gstatus = gate_status(fr_id, g["id"], ref=merge_sha or "main")
                if gstatus != "pass":
                    gate_bypasses.append((g, gstatus))
            if apply:
                modified = _flip_frontmatter_to_merged(
                    spec_path, prev_status, pr_num, merge_sha
                )
                if not modified:
                    summary.skipped.append(
                        (fr_id, "frontmatter unparseable; flip skipped")
                    )
                    flip_msg = "flip skipped (unparseable frontmatter)"
                else:
                    cm_ok, cm_note = _commit_spec_flip(fr_id, pr_num, merge_sha)
                    if cm_ok:
                        summary.flipped.append(fr_id)
                        flip_msg = (
                            f"flipped {prev_status} -> merged ({cm_note}, "
                            f"PR #{pr_num})"
                        )
                        # @implements FR-0002:AC-5 (pr.merged)
                        _metrics_emit(
                            "pr.merged",
                            role=merge_role,
                            object_ids=[fr_id],
                            run_id=None,
                            pr_number=pr_num,
                            merge_sha=merge_sha or None,
                        )
                        # @implements FR-0008:AC-10, FR-0008:AC-11 — the FR
                        # still flips to merged (the merge happened; AC-9's
                        # lint will fail on `main` and say why).
                        for g, gstatus in gate_bypasses:
                            _metrics_emit(
                                "gate.decision",
                                role=merge_role,
                                object_ids=[fr_id],
                                run_id=None,
                                gate=g["id"],
                                after=g["after"],
                                reviewer=g["reviewer"],
                                verdict="bypassed",
                                by="reconcile-merged",
                                round=1,
                                head_sha=merge_sha or None,
                            )
                    else:
                        summary.skipped.append(
                            (fr_id, f"git commit failed: {cm_note}")
                        )
                        flip_msg = f"flipped on disk; commit failed: {cm_note}"
            else:
                summary.flipped.append(fr_id)
                flip_msg = f"WOULD flip {prev_status} -> merged (PR #{pr_num})"

        # Cleanup runs for BOTH dev and rev role artefacts whenever the dev
        # PR is merged. Rev branches don't get their own PRs (the reviewer's
        # verdict is posted as `gh pr review` against the parent dev PR), so
        # `slot["rev"]` is almost always None even when a `rev-FR-XXXX`
        # worktree exists locally. Trigger rev cleanup off the dev merge.
        # Backfill (`bkf`) and maintainer (`mnt`) PRs DO open their own PRs,
        # so they're handled independently when their own merge appears. `mnt`
        # is dev-shaped, so a merged mnt PR also retires any rev artefacts.
        roles_to_clean: list[str] = []
        if slot["dev"] is not None:
            roles_to_clean.extend(["dev", "rev"])
        elif slot["mnt"] is not None:
            roles_to_clean.extend(["mnt", "rev"])
        elif slot["rev"] is not None:
            roles_to_clean.append("rev")
        if slot["bkf"] is not None:
            roles_to_clean.append("bkf")
        if slot["mnt"] is not None and "mnt" not in roles_to_clean:
            roles_to_clean.append("mnt")

        cleanup_msgs: list[str] = []
        any_cleaned = False
        for role in roles_to_clean:
            wt_path = REPO_ROOT / ".claude" / "worktrees" / f"{role}-{fr_id}"
            branch = _branch_for(fr_id, role)
            lock_p = lock_path(fr_id, role)
            wt_exists = wt_path.exists()
            br_exists = _git_branch_exists(branch)
            lock_exists = lock_p.exists()
            if not (wt_exists or br_exists or lock_exists):
                continue
            state, _ = lock_state(fr_id, role)
            if state == "held":
                cleanup_msgs.append(
                    f"{role}: lock held (agent running); cleanup skipped"
                )
                continue
            if apply:
                if wt_exists:
                    _, note = _git_remove_worktree(wt_path)
                    cleanup_msgs.append(f"{role}: worktree {note}")
                if br_exists:
                    _, note = _git_delete_branch(branch)
                    cleanup_msgs.append(f"{role}: branch {note}")
                if lock_exists:
                    lock_p.unlink(missing_ok=True)
                    cleanup_msgs.append(f"{role}: lock removed")
                any_cleaned = True
            else:
                parts = []
                if wt_exists:
                    parts.append("worktree")
                if br_exists:
                    parts.append("branch")
                if lock_exists:
                    parts.append("lock")
                cleanup_msgs.append(
                    f"{role}: WOULD remove {', '.join(parts)}"
                )
                any_cleaned = True

        if any_cleaned:
            summary.cleaned.append(fr_id)

        if verbose:
            print(f"  {fr_id}  {flip_msg}")
            # @implements FR-0008:AC-10
            for g, gstatus in gate_bypasses:
                print(f"  {fr_id}  WARN — merged past gate {g['id']}: status {gstatus}")
            for msg in cleanup_msgs:
                print(f"    - {msg}")

    return summary


def cmd_reconcile_merged(apply: bool) -> int:
    print(
        f"Reconciling merged PRs from origin "
        f"({'APPLY' if apply else 'dry-run'})..."
    )
    s = reconcile_merged_prs(apply=apply, verbose=True)
    if s.gh_unavailable:
        return 1
    n_flipped = len(s.flipped)
    n_cleaned = len(s.cleaned)
    n_skipped = len(s.skipped)
    print()
    verb_flip = "flipped" if apply else "would flip"
    verb_clean = "cleaned" if apply else "would clean"
    print(
        f"Summary: {verb_flip} {n_flipped} FR(s); "
        f"{verb_clean} {n_cleaned} FR worktree/branch/lock set(s); "
        f"skipped {n_skipped}"
    )
    if s.skipped:
        for fr_id, reason in s.skipped:
            print(f"  skip {fr_id}: {reason}")
    if not apply and (n_flipped or n_cleaned):
        print()
        print(
            "Re-run with --apply to commit frontmatter flips and remove "
            "worktrees/branches/locks."
        )
    return 0


# ---------------------------------------------------------------------------
# Tick / status / prune / kill / summary
# ---------------------------------------------------------------------------


def read_last_tick() -> dt.datetime | None:
    if not LAST_TICK_FILE.exists():
        return None
    try:
        return dt.datetime.fromisoformat(
            LAST_TICK_FILE.read_text(encoding="utf-8").strip()
        )
    except (OSError, ValueError):
        return None


def write_last_tick() -> None:
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    LAST_TICK_FILE.write_text(
        dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        encoding="utf-8",
    )


def new_escalations(since: dt.datetime | None) -> list[Path]:
    if not ESCALATIONS_DIR.exists():
        return []
    out = []
    for p in sorted(ESCALATIONS_DIR.glob("*.md")):
        if p.name.lower() in {"readme.md", "index.md"}:
            continue
        mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)
        if since is None or mtime > since:
            out.append(p)
    return out


ROLE_LABELS = {
    "dev": "Developer",
    "rev": "Reviewer",
    "bkf": "Reviewer (backfill)",
    "mnt": "Maintainer",
    "docs": "Docs",
    "gat": "Architect (gate review)",
}


# ---------------------------------------------------------------------------
# GitHub integration (finalize)
# ---------------------------------------------------------------------------
#
# The dispatcher owns the GitHub side of the workflow. Agents produce
# PR_BODY.md (Developer) and a structured Approve / Request-changes block
# in their final assistant text (Reviewer); finalize parses those, pushes
# the branch, and runs `gh pr create` / `gh pr review` accordingly.
#
# Idempotency model:
#   * Per-(FR, role) record at _dispatch/<fr>.<role>.pr.json. For dev:
#     {pr_number, pr_url, branch, head_sha, finalized_at}. For rev:
#     {parent_pr_number, verdict, finalized_at}. Re-running finalize on
#     the same FR re-pushes the branch (fast-forward), no-ops on the PR
#     if one is open against this head, and posts a new review thread.
#   * The dispatcher never deletes branches or PRs. Cleanup is human work.

GH_AUTH_PREFLIGHT_HINT = (
    "GitHub integration disabled: `gh` CLI not on PATH or `gh auth status` failed. "
    "Run `winget install GitHub.cli` then `gh auth login --web` to enable."
)


def _gh_available() -> bool:
    if shutil.which("gh") is None:
        return False
    try:
        proc = subprocess.run(["gh", "--version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _gh_authed() -> bool:
    if not _gh_available():
        return False
    try:
        proc = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


# @implements FR-0016:AC-1
def _remote_url(remote: str = "origin") -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "--get", f"remote.{remote}.url"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _repo_nwo() -> str | None:
    """Owner/repo string parsed from `origin`'s URL.

    Returns e.g. "owner/repo" for both
    `https://github.com/owner/repo.git` and
    `git@github.com:owner/repo.git`. None if the URL
    isn't a recognisable GitHub form.
    """
    url = _remote_url()
    if not url:
        return None
    https = re.match(r"^https?://[^/]+/([^/]+)/(.+?)(?:\.git)?/?$", url)
    if https:
        return f"{https.group(1)}/{https.group(2)}"
    ssh = re.match(r"^git@[^:]+:([^/]+)/(.+?)(?:\.git)?/?$", url)
    if ssh:
        return f"{ssh.group(1)}/{ssh.group(2)}"
    return None


def _fr_title(fr_id: str) -> str | None:
    for path in SPECS_DIR.glob(f"{fr_id}-*.md"):
        text = path.read_text(encoding="utf-8")
        m = FRONTMATTER_PATTERN.match(text)
        if m is None:
            return None
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return None
        title = meta.get("title")
        return str(title) if title else None
    return None


def _branch_for(fr_id: str, role: str) -> str:
    return f"claude/{role}-{fr_id}"


def _oneshot_pr_title(fr_id: str, role: str) -> str:
    """Conventional-Commits PR title for a one-shot role's own PR.

    `mnt` uses the `chore` type because maintainer runs target the control
    plane (role definitions, dispatcher, gate) rather than product behaviour;
    what matters for reviewability is that the `(FR-XXXX)` scope is present so
    a normal `rev` phase can pick the PR up.
    """
    if role == "mnt":
        return f"chore({fr_id}): {_fr_title(fr_id) or fr_id}"
    return f"test({fr_id}): backfill AC coverage"


def mnt_footprint_violations(
    fr_id: str,
    branch: str,
    base: str = "main",
    extra: list[str] | None = None,
) -> tuple[list[str], str | None]:
    """Paths a `mnt` branch touches that fall outside the target FR's `owns:`.

    Write-time enforcement and push-time verification fail differently: any
    interpreter or shell construct the allow-list did not anticipate is a
    silent hole in the former, and only an artifact-level check catches a
    genuine *derivation* bug, where the grant itself was wrong. `fr_owns_globs`
    is the authority for the grant in both cases. `extra` folds in paths that
    are staged but not yet committed so the check is meaningful in dry-run.

    Returns (violations, error). A non-None error means the check could not
    run, which callers must treat as a refusal rather than a pass.
    """
    owns = fr_owns_globs(fr_id)
    if not owns:
        return ([], f"{fr_id} declares no `owns:`; cannot verify footprint")
    ok, out = _git_capture(["diff", "--name-only", f"{base}...{branch}"], REPO_ROOT)
    if not ok:
        lines = _path_lines(out)
        return ([], f"git diff {base}...{branch} failed: {lines[-1] if lines else '?'}")
    touched = set(_path_lines(out)) | set(extra or [])
    # @implements FR-0024:AC-4 — git prints repo-relative paths; `owns:` is
    # compared in footprint coordinates, and a path outside the project
    # (`footprint_root: project`) is unowned. Violations keep git's spelling.
    to_footprint = _footprint_relpath_fn()

    def _violates(path: str) -> bool:
        rel = to_footprint(path)
        return rel is None or not _owned(rel, owns)

    return (sorted(p for p in touched if _violates(p)), None)


# @implements FR-0016:AC-1
def _push_branch(branch: str) -> tuple[bool, str]:
    """`git push -u origin <branch>`. Fast-forward only — no force.

    Returns (ok, message). `message` is human-readable (last line of
    git's stderr on failure; "pushed" / "up-to-date" on success).
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        last = err[-1] if err else "git push failed"
        return (False, last)
    out = (proc.stderr or proc.stdout or "").strip()
    if "Everything up-to-date" in out:
        return (True, "up-to-date")
    return (True, "pushed")


# @implements FR-0016:AC-1
def _branch_head_sha(branch: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", branch],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _role_worktree_path(fr_id: str, role: str) -> Path:
    """Where `ensure_role_worktree` put this role's checkout for this FR."""
    return REPO_ROOT / ".claude" / "worktrees" / f"{role}-{fr_id}"


# @implements FR-0016:AC-1, FR-0016:AC-2
def _git_capture(args: list[str], cwd: Path) -> tuple[bool, str]:
    """Run git in `cwd`; return (ok, trimmed stdout) or (False, stderr).

    Returns (False, <message>) when the process exits 0 but `stdout` is
    `None` — an undecoded capture is never reported as a success
    (FR-0016 AC-2); the crossing-content check this backs (FR-0013 AC-6)
    depends on that.
    """
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        return (False, (proc.stderr or proc.stdout or "").strip())
    if proc.stdout is None:
        return (False, "git output could not be decoded")
    return (True, proc.stdout.strip())


def _path_lines(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _finalize_commit_subject(fr_id: str, role: str) -> str:
    """Conventional-Commits subject for an agent's `finalize` commit."""
    if role == "rev":
        return f"test({fr_id}): AC coverage"
    if role == "bkf":
        return f"test({fr_id}): backfill AC coverage"
    if role == "mnt":
        return f"chore({fr_id}): {_fr_title(fr_id) or fr_id}"
    if role == "gat":
        # @implements FR-0008:AC-6 — `gate(<FR>): <gate-id> <verdict> by
        # architect`, read from the evidence file the session staged (its
        # frontmatter is the only place the gate id and verdict live; the
        # commit lands verbatim on `claude/dev-<FR>` via fast-forward, so
        # its subject must already be correct here).
        wt_path = _role_worktree_path(fr_id, "gat")
        staged = _staged_paths(wt_path)
        # @implements FR-0024:AC-4 — `staged` is repo-relative (read at the
        # worktree root), so it is both tested in project coordinates and
        # read from the worktree root as it is.
        ev = next(
            (
                p for p in staged
                if (_project_relpath(p) or "").startswith(f"specs/_gates/{fr_id}-")
                and p.endswith(".md")
            ),
            None,
        )
        if ev:
            try:
                text = (wt_path / ev).read_text(encoding="utf-8")
            except OSError:
                text = ""
            m = FRONTMATTER_PATTERN.match(text)
            if m:
                try:
                    meta = yaml.safe_load(m.group(1)) or {}
                except yaml.YAMLError:
                    meta = {}
                gid, verdict, by = meta.get("gate"), meta.get("verdict"), meta.get("by")
                if gid and verdict:
                    return f"gate({fr_id}): {gid} {verdict} by {by or 'architect'}"
        return f"gate({fr_id}): evidence"
    return f"feat({fr_id}): {_fr_title(fr_id) or fr_id}"


def _staged_paths(wt_path: Path) -> list[str]:
    """Paths in the role worktree's index. Empty when the worktree is gone."""
    if not wt_path.exists():
        return []
    ok, out = _git_capture(["diff", "--cached", "--name-only"], wt_path)
    return _path_lines(out) if ok else []


def _unstaged_paths(wt_path: Path) -> list[str]:
    """Tracked files modified in the worktree but not staged."""
    if not wt_path.exists():
        return []
    ok, out = _git_capture(["diff", "--name-only"], wt_path)
    return _path_lines(out) if ok else []


def _commits_ahead(branch: str, base: str) -> int | None:
    """Commits on `branch` that `base` lacks. None when git cannot tell."""
    ok, out = _git_capture(["rev-list", "--count", f"{base}..{branch}"], REPO_ROOT)
    if not ok:
        return None
    try:
        return int(out.split()[0])
    except (IndexError, ValueError):
        return None


def _commit_staged_work(fr_id: str, role: str, branch: str) -> tuple[str, list[str]]:
    """Commit whatever the agent staged in its worktree, before pushing.

    Dispatched agents cannot commit — the harness refuses `git commit` in every
    form — so the normal outcome of a *successful* run is a worktree of staged,
    gate-passing work on a branch with no commits, which is indistinguishable
    from a failed run once `finalize` pushes it. Staging is the agent's signal
    of intent, so the index is committed verbatim: plain `git commit` (no `-a`)
    cannot pick up unstaged modifications.

    Returns (outcome, staged_paths); outcome is "committed", "nothing-staged",
    or "error:<msg>".
    """
    wt_path = _role_worktree_path(fr_id, role)
    # @implements FR-0006:AC-2 — a missing worktree is an error, not "nothing
    # staged": finalize must not push a branch it cannot inspect.
    if not wt_path.exists():
        return (f"error:role worktree missing at {wt_path}", [])
    # Never commit onto a branch other than the one being finalized: a
    # worktree left on a detached HEAD or a stale branch would otherwise
    # silently land the agent's work somewhere nobody looks. Checked before
    # the staged lookup so the wrong-branch case is reported even when the
    # index is empty.
    ok, head = _git_capture(["rev-parse", "--abbrev-ref", "HEAD"], wt_path)
    if not ok:
        return (f"error:cannot read HEAD in {wt_path}", [])
    if head != branch:
        return (f"error:worktree {wt_path} is on {head}, not {branch}", [])
    staged = _staged_paths(wt_path)
    if not staged:
        return ("nothing-staged", [])
    ok, err = _git_capture(
        ["commit", "-m", _finalize_commit_subject(fr_id, role)], wt_path
    )
    if not ok:
        lines = _path_lines(err)
        return (f"error:{lines[-1] if lines else 'git commit failed'}", staged)
    return ("committed", staged)


def _untracked_paths(wt_path: Path) -> list[str]:
    """Untracked, non-ignored files in the worktree (never auto-staged)."""
    if not wt_path.exists():
        return []
    ok, out = _git_capture(["ls-files", "--others", "--exclude-standard"], wt_path)
    return _path_lines(out) if ok else []


def _finalize_base_branch(fr_id: str, role: str) -> str:
    """The ref a role branch is measured against for "adds no commits".

    PR-opening roles (dev, bkf, mnt) are measured against `main`, the PR base.
    The Reviewer branch is measured against the implementation branch it
    reviews — `claude/dev-<FR>` if it exists, else `claude/mnt-<FR>`
    (FR-0013 AC-11): a re-review that adds no new tests is legitimate and
    is not refused. The gate-review branch is measured the same way — it is
    cut from that same tip and must add its one evidence commit over it
    (FR-0008:AC-6); unlike `rev`, adding nothing IS refused (no evidence was
    written) via the generic `not ahead` branch below.
    @implements FR-0013:AC-11
    @implements FR-0008:AC-6
    """
    if role in ("rev", "gat"):
        found = _implementation_branch_for_fr(fr_id)
        return found[0] if found is not None else _branch_for(fr_id, "dev")
    return "main"


def _first_nonempty_line(text: str) -> str:
    """The first non-empty line of captured git output, for a refusal that
    quotes its cause. Never the last line: on an unknown revision that is
    git's usage text, not the failure (DEC-0017 Decision 5).
    """
    lines = _path_lines(text)
    return lines[0] if lines else "(no output)"


# @implements FR-0015:AC-2
def _control_plane_branch_paths(
    fr_id: str, role: str, branch: str, apply: bool
) -> tuple[list[str], str | None]:
    """`dev`/`rev`/`bkf` control-plane paths changed on `<finalize-base>...
    <branch>`. `<finalize-base>` is `_finalize_base_branch`'s answer when
    that branch exists; when it does not — only possible for a `rev` with
    neither `claude/dev-<FR>` nor `claude/mnt-<FR>` — the base falls back to
    `main`, the ref the Reviewer worktree was actually cut from
    (DEC-0017 Decision 1). `_finalize_base_branch` itself is unchanged.

    Every protected path is off-limits for these three roles regardless of
    `owns:` (FR-0009:AC-2), so this reuses `MNT_PROTECTED_GLOBS` directly —
    no `owns:` lookup, unlike `mnt`'s own footprint check.

    The range diff also runs a second time with `--no-renames`: git's default
    rename detection would otherwise print only a moved protected file's
    *new* name, hiding that the protected path itself changed on the branch.
    The first, renames-default call is unchanged from before this FR and is
    what a read failure is detected and reported against; the second is
    additive, widening the touched set, never narrowing it. In dry-run the
    set also includes the worktree's staged index, read here with the same
    `--no-renames` addition and failing closed — distinct from
    `_staged_paths` (FR-0006), which stays fail-open and rename-collapsing
    because `_finalize_commit_step`'s `WOULD-COMMIT` count depends on it
    unchanged.

    Returns (off_limits_paths, error). A non-None error means a read could
    not run, which the caller must treat as a refusal, not a pass.
    """
    base = _finalize_base_branch(fr_id, role)
    if not _git_branch_exists(base):
        base = "main"
    range_spec = f"{base}...{branch}"
    ok, out = _git_capture(["diff", "--name-only", range_spec], REPO_ROOT)
    if not ok:
        return ([], f"git diff {base}...{branch}: {_first_nonempty_line(out)}")
    touched = set(_path_lines(out))
    ok_nr, out_nr = _git_capture(
        ["diff", "--name-only", "--no-renames", range_spec], REPO_ROOT
    )
    if not ok_nr:
        return ([], f"git diff {base}...{branch}: {_first_nonempty_line(out_nr)}")
    touched |= set(_path_lines(out_nr))
    if not apply:
        wt_path = _role_worktree_path(fr_id, role)
        if wt_path.exists():
            staged_ok, staged_out = _git_capture(
                ["diff", "--cached", "--name-only"], wt_path
            )
            if not staged_ok:
                return ([], f"git diff --cached: {_first_nonempty_line(staged_out)}")
            touched |= set(_path_lines(staged_out))
            staged_nr_ok, staged_nr_out = _git_capture(
                ["diff", "--cached", "--name-only", "--no-renames"], wt_path
            )
            if not staged_nr_ok:
                return (
                    [],
                    f"git diff --cached: {_first_nonempty_line(staged_nr_out)}",
                )
            touched |= set(_path_lines(staged_nr_out))
    # @implements FR-0024:AC-4 — the project's own control plane, compared in
    # project coordinates; a repository path outside the project is not it.
    return (sorted(p for p in touched if _project_control_plane_path(p)), None)


# @implements FR-0015:AC-3
def _off_limits_worktree_paths(fr_id: str, role: str, paths: set[str]) -> list[str]:
    """Which of `paths` are off-limits for `role` (FR-0015's Term). A path
    matches `MNT_PROTECTED_GLOBS`, and for `mnt` is additionally off-limits
    unless the permission derivation actually grants it: it is in
    `mnt_permission_rules`'s `granted` set for the FR *and not* in that same
    call's `denies` set. Deny wins in the harness, so a broad `owns:` glob
    that happens to match a protected path (e.g. `owns: ["*.md"]` matching
    `CLAUDE.md`, or `owns: ["**"]` matching `.agent-team/**`) does not make
    it writable — `mnt_permission_rules` still denies it, concretely or via
    the glob itself. `MNT_NEVER_WRITABLE` therefore stays off-limits for
    `mnt` even when owned. For every other role, every protected path is
    off-limits (FR-0009:AC-2).
    """
    # @implements FR-0024:AC-4 — `paths` are repo-relative. The protected
    # set, `MNT_NEVER_WRITABLE` and the derived denies are the project's
    # (project coordinates); the grants are `owns:` (footprint coordinates).
    # Both are the identity at prefix "".
    protected = [p for p in paths if _project_control_plane_path(p)]
    if role != "mnt":
        return protected
    granted, denies = mnt_permission_rules(fr_owns_globs(fr_id))
    to_footprint = _footprint_relpath_fn()
    off_limits: list[str] = []
    for p in protected:
        rel = _project_relpath(p) or p
        fp = to_footprint(p)
        if (
            rel in MNT_NEVER_WRITABLE
            or fp is None
            or not _owned(fp, granted)
            or _owned(rel, denies)
        ):
            off_limits.append(p)
    return off_limits


# @implements FR-0015:AC-3
def _uncommitted_control_plane_paths(
    fr_id: str, role: str
) -> tuple[list[str], str | None]:
    """Off-limits paths left uncommitted in the role worktree: tracked-but-
    unstaged modifications (including deletions) and untracked, non-ignored
    files — the same two sets FR-0006:AC-3 reports (`git diff --name-only`
    and `git ls-files --others --exclude-standard`), read through a path
    that reports failure. `_unstaged_paths` / `_untracked_paths` and FR-0006
    AC-3's `WARN` output are unchanged and stay fail-open, because that
    report is advisory (DEC-0017 Decision 2); this is a separate, later,
    fail-closed check. A read that fails is a refusal, not a pass.

    Returns (off_limits_paths, error).
    """
    wt_path = _role_worktree_path(fr_id, role)
    unstaged_ok, unstaged_out = _git_capture(["diff", "--name-only"], wt_path)
    if not unstaged_ok:
        return ([], f"git diff: {_first_nonempty_line(unstaged_out)}")
    untracked_ok, untracked_out = _git_capture(
        ["ls-files", "--others", "--exclude-standard"], wt_path
    )
    if not untracked_ok:
        return ([], f"git ls-files: {_first_nonempty_line(untracked_out)}")
    touched = set(_path_lines(unstaged_out)) | set(_path_lines(untracked_out))
    return (sorted(_off_limits_worktree_paths(fr_id, role, touched)), None)


def _report_leftover_work(fr_id: str, role: str, wt_path: Path) -> None:
    """One WARN line per category of work the agent left out of its handoff.

    Staging is the agent's signal of intent: tracked-but-unstaged edits and
    untracked files are reported so a human can see what was dropped, and are
    never `git add`-ed on the agent's behalf. Ignored paths (the dispatch
    venv, caches) are not reported.

    @implements FR-0006:AC-3
    """
    for label, paths in (
        ("unstaged tracked modification(s)", _unstaged_paths(wt_path)),
        ("untracked file(s)", _untracked_paths(wt_path)),
    ):
        if not paths:
            continue
        shown = ", ".join(paths[:10])
        more = f", +{len(paths) - 10} more" if len(paths) > 10 else ""
        print(
            f"  {fr_id}.{role}  WARN         {len(paths)} {label} not in the "
            f"handoff (staging is intent; not added): {shown}{more}"
        )


def _finalize_commit_step(
    fr_id: str, role: str, branch: str, apply: bool
) -> tuple[bool, int | None]:
    """Commit the agent's staged index and measure the branch against its base.

    Runs before the footprint check, the gh preflight and the push, so that
    (a) staged-but-uncommitted work is part of what the footprint check and
    the PR see, and (b) nothing is pushed when the commit cannot complete.

    Returns (ok, commits_ahead). `ok` is False when finalize must stop: the
    commit step failed (AC-2) or a PR-opening role's branch adds nothing over
    `main` (AC-4). `commits_ahead` is the post-commit count (dry-run: the count
    the commit would produce) or None when git cannot tell.

    @implements FR-0006:AC-1
    @implements FR-0006:AC-4
    @implements FR-0006:AC-5
    @implements FR-0006:AC-12
    """
    wt_path = _role_worktree_path(fr_id, role)
    base = _finalize_base_branch(fr_id, role)
    if apply:
        outcome, staged = _commit_staged_work(fr_id, role, branch)
        if outcome.startswith("error:"):
            print(f"  {fr_id}.{role}  ERROR — commit step failed: {outcome[6:]}")
            return (False, None)
        if outcome == "committed":
            print(
                f"  {fr_id}.{role}  COMMITTED    {len(staged)} staged path(s) as "
                f"'{_finalize_commit_subject(fr_id, role)}'"
            )
        ahead = _commits_ahead(branch, base)
    else:
        if not wt_path.exists():
            print(f"  {fr_id}.{role}  WOULD-REFUSE role worktree missing at {wt_path}")
            return (False, None)
        staged = _staged_paths(wt_path)
        if staged:
            print(
                f"  {fr_id}.{role}  WOULD-COMMIT {len(staged)} staged path(s) as "
                f"'{_finalize_commit_subject(fr_id, role)}'"
            )
        ahead = _commits_ahead(branch, base)
        if ahead is not None:
            ahead += 1 if staged else 0
    _report_leftover_work(fr_id, role, wt_path)
    if role == "rev":
        if ahead == 0:
            print(
                f"  {fr_id}.rev  NOTE         {branch} adds no commits over {base}; "
                "the review is still posted"
            )
        return (True, ahead)
    if not ahead:
        why = "cannot count commits" if ahead is None else "adds no commits"
        tag = "ERROR —" if apply else "WOULD-REFUSE"
        print(
            f"  {fr_id}.{role}  {tag} {branch} {why} over {base}; nothing to open a PR "
            f"for. Stage the agent's work in {wt_path} and re-run finalize."
        )
        return (False, ahead)
    return (True, ahead)


def _pr_record_path(fr_id: str, role: str) -> Path:
    return DISPATCH_DIR / f"{fr_id}.{role}.pr.json"


def _load_pr_record(fr_id: str, role: str) -> dict | None:
    p = _pr_record_path(fr_id, role)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_pr_record(fr_id: str, role: str, payload: dict) -> None:
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("fr_id", fr_id)
    payload.setdefault("role", role)
    payload["finalized_at"] = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"
    )
    _pr_record_path(fr_id, role).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


# @implements FR-0016:AC-1
def _gh_pr_for_branch(branch: str) -> int | None:
    """Look up an open PR with this head branch via `gh pr list`."""
    nwo = _repo_nwo()
    if nwo is None:
        return None
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            nwo,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "1",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not rows:
        return None
    return int(rows[0].get("number") or 0) or None


# Markers the Reviewer's structured handoff includes when proposing a
# review verdict. We tolerate variation across observed forms:
#   - "### Suggested GitHub review (Approve)"
#   - "### Suggested review body (Approve):"
#   - "### Suggested GitHub review (Request changes)"
#   - "### Request changes (cannot honestly Approve yet)" / **Request changes**
#   - "Cannot honestly Approve" prose (verdict implicit)
# Both regexes use `re.search` (first match wins). For FRs that emit
# competing markers (rare), the earliest-match-in-text rule chooses the
# one nearest the reviewer's primary handoff section, which is what we
# want.
_VERDICT_RE_APPROVE = re.compile(
    r"suggested\s+(?:github\s+)?review(?:\s+body)?\s*\(\s*approve\s*\)"
    r"|(?:^|\n)\s*##+\s*approve\b"
    r"|(?:^|\n)\s*\*\*approve\*\*",
    re.IGNORECASE,
)
_VERDICT_RE_REQUEST = re.compile(
    r"suggested\s+(?:github\s+)?review(?:\s+body)?\s*\(\s*request[\s-]+changes\s*\)"
    r"|(?:^|\n)\s*##+\s*request\s+changes\b"
    r"|(?:^|\n)\s*\*\*request\s+changes\*\*"
    r"|cannot\s+(?:honestly\s+)?(?:use\s+an\s+)?approve",
    re.IGNORECASE,
)

# FR-0013 AC-3 tier 1: a verdict declared on the text's first non-empty line
# ("Verdict: approve" / "Verdict: request-changes") is authoritative.
_VERDICT_DECLARED_RE = re.compile(
    r"verdict\s*:\s*(approve|request[-\s]changes)", re.IGNORECASE
)
# AC-3 tier 2: a marker anywhere inside the first Markdown heading of the
# text — e.g. "## FR-0001 review — **Request changes** (round 1 of 3)",
# which today's tier-3 patterns miss because the marker isn't at line start.
_HEADING_LINE_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_HEADING_APPROVE_RE = re.compile(r"\bapprove\b", re.IGNORECASE)
_HEADING_REQUEST_RE = re.compile(r"\brequest[-\s]changes\b", re.IGNORECASE)


def _extract_review_verdict(text: str | None) -> tuple[str, str]:
    """Map a Reviewer's final assistant text to a (verdict, body) pair.

    verdict is one of: "approve", "request-changes", "comment".
    body is the full text passed verbatim to `gh pr review --body`. We
    do NOT attempt to slice out a sub-section: posting the entire
    structured handoff is the right surface for a human reading the PR.

    Resolution order (FR-0013 AC-3):
      1. A declared verdict on the text's first non-empty line
         ("Verdict: approve" / "Verdict: request-changes", case-
         insensitive) beats everything else.
      2. A marker ("approve" / "request changes") anywhere inside the
         first Markdown heading of the text, in any inline emphasis.
      3. Today's existing patterns, with today's earliest-match tie-break:
         when both markers match, the one that appears EARLIEST wins —
         reviewers often mention the opposite verdict in a later "what to
         do if you disagree" footnote, and the earliest match is almost
         always inside the primary handoff section.
      4. "comment" — the Reviewer still gets a review thread, just not a
         verdict, and the human can decide whether to convert it.

    @implements FR-0013:AC-3
    """
    if not text:
        return ("comment", "(reviewer log empty — finalize was called with no text)")

    # Tier 1: declared verdict on the first non-empty line only.
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _VERDICT_DECLARED_RE.search(line)
        if m:
            token = re.sub(r"\s+", "-", m.group(1).strip().lower())
            return (
                "request-changes" if token.startswith("request") else "approve",
                text,
            )
        break

    # Tier 2: marker anywhere inside the first Markdown heading, wherever
    # it occurs in the text (not necessarily the first line).
    first_heading = None
    for line in text.splitlines():
        if _HEADING_LINE_RE.match(line):
            first_heading = line
            break
    if first_heading is not None:
        # K4: strip inline-emphasis characters before matching, so
        # `_approve_`, `~approve~` and `` `approve` `` are found the same
        # as the bare word — `\b` alone only worked for `*`/`**`, which
        # aren't word characters, by accident.
        heading_stripped = re.sub(r"[*_~`]", "", first_heading)
        approve_h = _HEADING_APPROVE_RE.search(heading_stripped)
        request_h = _HEADING_REQUEST_RE.search(heading_stripped)
        if approve_h and request_h:
            return (
                "approve" if approve_h.start() <= request_h.start() else "request-changes",
                text,
            )
        if request_h:
            return ("request-changes", text)
        if approve_h:
            return ("approve", text)

    # Tier 3: today's patterns, unchanged.
    approve_match = _VERDICT_RE_APPROVE.search(text)
    request_match = _VERDICT_RE_REQUEST.search(text)
    if approve_match and request_match:
        if approve_match.start() <= request_match.start():
            return ("approve", text)
        return ("request-changes", text)
    if request_match:
        return ("request-changes", text)
    if approve_match:
        return ("approve", text)
    return ("comment", text)


def _gh_preflight(verbose: bool) -> tuple[bool, str | None]:
    """Returns (ok, error_msg). Cheap to call before any finalize work."""
    if not _gh_available():
        return (False, "gh CLI not on PATH")
    if not _gh_authed():
        return (False, "gh auth status failed (run `gh auth login`)")
    if _repo_nwo() is None:
        return (
            False,
            "no `origin` remote configured (run `git remote add origin <url>`)",
        )
    return (True, None)


def _reviewer_verdict_and_body(
    fr_id: str,
    adapter: HarnessAdapter | None,
    verdict_file: Path | None = None,
    *,
    announce: bool = True,
) -> tuple[str, str] | None:
    """(verdict, body) from `--verdict-file` when given, else from the
    Reviewer's final message in its dispatch log (today's behaviour).

    `--verdict-file` (FR-0013 AC-4) takes precedence over the log when both
    are present and does not require `_dispatch/<FR>.rev.log` to exist —
    the only way to finalize a Reviewer run as an in-harness subagent,
    which writes no dispatch log. A missing or empty file is treated as
    unavailable, same as a missing log; the caller's existing "no reviewer
    log" handling covers both, distinguished by whether `verdict_file` was
    passed. AC-3 (`_extract_review_verdict`) applies identically to either
    source. `announce=False` suppresses the `VERDICT-FROM-FILE` line for a
    second call in the same `finalize` run (materialise-then-post), so it
    prints exactly once.

    Returns None when neither source is available.
    @implements FR-0013:AC-3
    @implements FR-0013:AC-4
    """
    if verdict_file is not None:
        if not verdict_file.exists():
            return None
        text = verdict_file.read_text(encoding="utf-8")
        if not text.strip():
            return None
        if announce:
            print(f"  {fr_id}.rev  VERDICT-FROM-FILE  {verdict_file}")
        return _extract_review_verdict(text)
    log_path = DISPATCH_DIR / f"{fr_id}.rev.log"
    if not log_path.exists():
        return None
    if adapter is None:
        adapter = _adapter_for_lock(fr_id, "rev")
    summary = adapter.parse_log(log_path)
    return _extract_review_verdict(summary.last_text)


def _review_md_byte_count(ref: str, cwd: Path) -> int | None:
    """`git cat-file -s <ref>` — the object's exact byte size, never a
    locale-decoded text length (`git show` + `text=True` on Windows
    inflates every multi-byte character and drops every `\\r`). FR-0013
    AC-2, K5.
    """
    ok, out = _git_capture(["cat-file", "-s", ref], cwd)
    if not ok:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


# The review library (FR-0025, DEC-0023): one file per FR per review round,
# relative to the project root. The Reviewer's handoff stays the root
# `REVIEW.md` (FR-0022 AC-2); only the dispatcher knows the round, so only
# `finalize --role rev` files it here.
REVIEWS_DIR_REL = "specs/_reviews"
_ROOT_REVIEW = "REVIEW.md"


def _review_library_path(fr_id: str, round_num: int) -> str:
    """`specs/_reviews/<FR>-r<N>.md`, N in decimal without padding.
    @implements FR-0025:AC-1
    """
    return f"{REVIEWS_DIR_REL}/{fr_id}-r{round_num}.md"


def _parse_review_round(raw: int | str) -> int | None:
    """`--review-round`'s value as an int >= 1, or None when it is not one.
    Taken as a string so a non-integer is the dispatcher's one ERROR, not
    an argparse usage error.
    @implements FR-0025:AC-4
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    text = str(raw).strip()
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        return None
    n = int(text)
    return n if n >= 1 else None


def _review_library_rounds(fr_id: str, ref: str) -> dict[int, tuple[str, str]]:
    """`{N: (path, blob_sha)}` for every `<FR>-r<N>.md` blob directly under
    `specs/_reviews/` at `ref`; empty when there is none or `ref` is unknown.

    Only names matching `^<FR>-r[1-9][0-9]*\\.md$` count, so another FR's
    rounds, a zero-padded `r01` and a `-final.md` are never a round of this
    FR's. N is an int, so `r10` orders after `r9`.
    @implements FR-0025:AC-2
    """
    ok, out = _git_capture(["ls-tree", ref, "--", f"{REVIEWS_DIR_REL}/"], REPO_ROOT)
    if not ok:
        return {}
    name_re = re.compile(rf"^{re.escape(fr_id)}-r([1-9][0-9]*)\.md$")
    rounds: dict[int, tuple[str, str]] = {}
    for line in _path_lines(out):
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        head, _, name = path.rpartition("/")
        m = name_re.match(name)
        if head == REVIEWS_DIR_REL and m:
            rounds[int(m.group(1))] = (path, parts[2])
    return rounds


def _newest_review_on_branch(fr_id: str) -> tuple[int, str, str] | None:
    """`(N, path, blob_sha)` of the highest-numbered library file on
    `claude/rev-<FR>`, or None. The one review every reader uses.
    @implements FR-0025:AC-2
    """
    rounds = _review_library_rounds(fr_id, _branch_for(fr_id, "rev"))
    if not rounds:
        return None
    n = max(rounds)
    return (n, rounds[n][0], rounds[n][1])


def _tree_entry(ref: str, path: str, cwd: Path) -> tuple[str, str] | None:
    """`(mode, blob_sha)` of `path` in `ref`'s tree, or None when absent."""
    ok, out = _git_capture(["ls-tree", ref, "--", path], cwd)
    if not ok:
        return None
    for line in _path_lines(out):
        meta, _, p = line.partition("\t")
        parts = meta.split()
        if p == path and len(parts) == 3 and parts[1] == "blob":
            return (parts[0], parts[2])
    return None


def _index_entry(path: str, cwd: Path) -> tuple[str, str] | None:
    """`(mode, blob_sha)` of `path` in the worktree's index, or None."""
    ok, out = _git_capture(["ls-files", "--stage", "--", path], cwd)
    if not ok:
        return None
    for line in _path_lines(out):
        meta, _, p = line.partition("\t")
        parts = meta.split()
        if p == path and len(parts) == 3 and parts[2] == "0":
            return (parts[0], parts[1])
    return None


def _git_blob_bytes(sha: str, cwd: Path) -> bytes | None:
    """A blob's exact bytes (`git cat-file blob`), never decoded."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), "cat-file", "blob", sha],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _working_file_blob_sha(path: str, cwd: Path) -> str | None:
    """The blob sha git would store for the working-tree file at `path`
    (`git hash-object`, so the worktree's own clean filters apply), or None
    when there is no such file."""
    if not (cwd / path).is_file():
        return None
    ok, out = _git_capture(["hash-object", "--", path], cwd)
    return out.strip() if ok and out.strip() else None


def _working_file_holds_blob(path: str, blob: str, cwd: Path) -> bool:
    """True when the working-tree file at `path` holds blob `blob`: its raw
    bytes are the blob's bytes, or `git hash-object` (the clean filters
    applied) gives the blob's sha.

    Either test alone is wrong on some host. Under `core.autocrlf=true` a
    blob that carries CRLF checks out byte for byte, but `hash-object` hashes
    the LF-normalised text; an LF blob checks out as CRLF, and only
    `hash-object` sees it as the same blob. A locally edited file passes
    neither. FR-0025 AC-1 and AC-3.
    """
    if not (cwd / path).is_file():
        return False
    try:
        raw = (cwd / path).read_bytes()
    except OSError:
        return False
    if raw == _git_blob_bytes(blob, cwd):
        return True
    return _working_file_blob_sha(path, cwd) == blob


def _existing_review_md_source(fr_id: str, wt_path: Path, apply: bool) -> dict | None:
    """The pending root `REVIEW.md` — the Reviewer's own handoff — or None.

    Apply mode reads the root of `claude/rev-<FR>`'s tip: by the time this
    runs, `_finalize_commit_step` has folded anything the Reviewer staged
    into a commit. Dry-run reads the Reviewer worktree's index instead, which
    is what that commit step would fold in; its source is "staged" when the
    index differs from the tip and "branch" when it does not.

    A root `REVIEW.md` whose blob equals the one at `git merge-base
    claude/rev-<FR> main` is inherited, not this FR's review (DEC-0024
    Decision 2): one WARN, and None. With no merge-base nothing is
    inherited. An untracked root file is in neither the tip nor the index,
    so it is never pending (FR-0006 AC-3).

    Returns `{"source", "mode", "blob", "bytes", "empty", "base"}`: `bytes`
    is the exact object size (`git cat-file -s`, K5); `empty` is True for a
    whitespace-only file, which still gets today's one WARN and is removed by
    the filing commit, but is not filed; `base` is the merge-base's
    `(mode, blob)` for the root path, or None.

    @implements FR-0013:AC-2
    @implements FR-0016:AC-1
    @implements FR-0025:AC-1
    """
    branch = _branch_for(fr_id, "rev")
    # @implements FR-0024:AC-3 — the tip and merge-base reads are `ls-tree`
    # in `REPO_ROOT`, the project directory, so they name `<prefix>REVIEW.md`
    # and print it project-relative; the index read runs at the worktree
    # root and names it explicitly. A repository-top `REVIEW.md` is never it.
    tip = _tree_entry(branch, _ROOT_REVIEW, REPO_ROOT)
    pending, source = tip, "branch"
    if not apply and wt_path.exists():
        pending = _index_entry(_repo_path(_ROOT_REVIEW), wt_path)
        source = "branch" if pending == tip else "staged"
    if pending is None:
        return None
    mode, blob = pending
    ok, merge_base = _git_capture(["merge-base", branch, "main"], REPO_ROOT)
    base = (
        _tree_entry(merge_base, _ROOT_REVIEW, REPO_ROOT) if ok and merge_base else None
    )
    if base is not None and base[1] == blob:
        print(
            f"  {fr_id}.rev  WARN         {_ROOT_REVIEW} on {branch} is inherited "
            "from main, not this FR's review; left in place and not filed"
        )
        return None
    cwd = wt_path if source == "staged" else REPO_ROOT
    raw = _git_blob_bytes(blob, cwd)
    nbytes = _review_md_byte_count(blob, cwd)
    if nbytes is None:
        nbytes = len(raw or b"")
    empty = not (raw or b"").decode("utf-8", errors="replace").strip()
    if empty:
        where = "staged on" if source == "staged" else "on"
        print(
            f"  {fr_id}.rev  WARN         {_ROOT_REVIEW} {where} {branch} is "
            "empty; replacing with a synthesised one"
        )
    return {
        "source": source,
        "mode": mode,
        "blob": blob,
        "bytes": nbytes,
        "empty": empty,
        "base": base,
    }


def _materialise_review_md(
    fr_id: str,
    branch: str,
    adapter: HarnessAdapter | None,
    apply: bool,
    verdict_file: Path | None = None,
    review_round: int | None = None,
) -> tuple[bool, tuple[str, str] | None]:
    """File this round's review at `specs/_reviews/<FR>-r<N>.md` on
    `claude/rev-<FR>` before the push, in one commit that also takes the
    pending root `REVIEW.md` off the branch.

    The source is the Reviewer's own pending root `REVIEW.md` when it is
    non-empty — its blob is moved in the index, byte for byte, never
    re-read through the working tree (DEC-0001, DEC-0023) — else the
    synthesised body (the verdict of record, LF, one trailing newline). The
    root file never reaches a pushed branch: the filing commit removes it,
    or, when the merge-base carries a legacy root `REVIEW.md`, puts that
    inherited blob back so the branch leaves it as it found it.

    N is `review_round` (`--review-round`, AC-4), else the run-context
    round, else 1. Nothing is committed when there is no pending root file
    and round N is already filed, so a re-run never adds a commit. A pending
    file that differs from an already-filed round N is filed at the lowest
    free round above the highest filed one instead of overwriting it.

    Returns (ok, verdict_and_body). `ok` is False (after printing an
    ERROR) when finalize must stop; `verdict_and_body` is then None.
    Otherwise `verdict_and_body` is the resolved (verdict, body) pair so
    callers that also need it (the dry-run rev preview, AC-1's fast-
    forward gate, `_finalize_rev`'s post) don't re-resolve it and risk a
    second `VERDICT-FROM-FILE` line.

    @implements FR-0006:AC-6
    @implements FR-0006:AC-12
    @implements FR-0013:AC-2
    @implements FR-0025:AC-1
    @implements FR-0025:AC-4
    """
    wt_path = _role_worktree_path(fr_id, "rev")
    parsed = _reviewer_verdict_and_body(fr_id, adapter, verdict_file)
    if parsed is None:
        if verdict_file is not None:
            print(
                f"  {fr_id}.rev  ERROR — --verdict-file {verdict_file} is missing or empty"
            )
        else:
            print(f"  {fr_id}.rev  ERROR — no reviewer log at {DISPATCH_DIR / f'{fr_id}.rev.log'}")
        return (False, None)
    verdict, body = parsed
    synthesised = (body if body.endswith("\n") else body + "\n").encode("utf-8")

    ctx_rnd = _run_context(fr_id, "rev").get("round")
    ctx_round = ctx_rnd if isinstance(ctx_rnd, int) and ctx_rnd > 0 else None
    round_num = review_round or ctx_round or 1
    guessed = review_round is None and ctx_round is None

    pending = _existing_review_md_source(fr_id, wt_path, apply)
    filed = _review_library_rounds(fr_id, branch)
    keep_tag = "WOULD-KEEP-REVIEW" if not apply else "REVIEW-KEPT"

    # Nothing to file: no pending root file, and this round is already filed —
    # empty or not (DEC-0028 Decision 1). A filed round is never overwritten
    # and a re-run never adds a commit; an empty one is flagged, not refiled.
    if pending is None and round_num in filed:
        path, blob = filed[round_num]
        raw = _git_blob_bytes(blob, REPO_ROOT) or b""
        print(
            f"  {fr_id}.rev  {keep_tag}  {path} on {branch} ({len(raw)} bytes, "
            "branch) is already filed; no commit"
        )
        if not raw.decode("utf-8", errors="replace").strip():
            print(
                f"  {fr_id}.rev  WARN         {path} on {branch} is empty; kept as "
                f"round {round_num}'s filed review, not overwritten or refiled"
            )
        elif guessed and raw != synthesised:
            print(
                f"  {fr_id}.rev  WARN         round {round_num} was assumed (no "
                "--review-round and no run-context round); if this is a later "
                "round, re-run finalize with --review-round <N>"
            )
        return (True, (verdict, body))

    own = pending is not None and not pending["empty"]
    if own:
        source, nbytes = pending["source"], pending["bytes"]
        content = _git_blob_bytes(
            pending["blob"], wt_path if source == "staged" else REPO_ROOT
        )
    else:
        source, nbytes, content = "synthesised", len(synthesised), synthesised

    # Round collision: never overwrite a filed round with different bytes.
    target, write_library = round_num, True
    if round_num in filed:
        existing = _git_blob_bytes(filed[round_num][1], REPO_ROOT)
        if existing is not None and existing == content:
            write_library = False
        else:
            target = max(filed) + 1
            print(
                f"  {fr_id}.rev  WARN         round {round_num} is already filed at "
                f"{filed[round_num][0]} with different content; filing at round "
                f"{target} instead"
            )
    lib_path = _review_library_path(fr_id, target)
    subject = f"review({fr_id}): round {target} verdict={verdict}"

    if not apply:
        if not write_library:
            print(
                f"  {fr_id}.rev  {keep_tag}  {lib_path} on {branch} ({nbytes} bytes, "
                f"{source}) is already filed; would only take {_ROOT_REVIEW} off "
                f"the branch as '{subject}'"
            )
        elif own:
            print(
                f"  {fr_id}.rev  {keep_tag}  {lib_path} on {branch} ({nbytes} bytes, "
                f"{source}) is the Reviewer's own; would file as '{subject}'"
            )
        else:
            print(
                f"  {fr_id}.rev  WOULD-WRITE-REVIEW  {lib_path} ({nbytes} bytes, "
                f"synthesised) on {branch} as '{subject}'"
            )
        return (True, (verdict, body))
    if not wt_path.exists():
        print(
            f"  {fr_id}.rev  ERROR — role worktree missing at {wt_path}; cannot "
            f"file {lib_path}"
        )
        return (False, None)

    # @implements FR-0024:AC-3 (DEC-0031 item 3) — the filing commit adds
    # `<prefix>specs/_reviews/<FR>-r<N>.md` and removes (or, DEC-0028,
    # restores) `<prefix>REVIEW.md`; the git steps run at the worktree root
    # and name repository paths, the file writes land in the project.
    wt_project = _worktree_project_root(wt_path)
    repo_lib_path = _repo_path(lib_path)
    repo_root_review = _repo_path(_ROOT_REVIEW)
    steps: list[list[str]] = []
    if write_library and own:
        steps.append(
            [
                "update-index",
                "--add",
                "--cacheinfo",
                f"{pending['mode']},{pending['blob']},{repo_lib_path}",
            ]
        )
    elif write_library:
        (wt_project / lib_path).parent.mkdir(parents=True, exist_ok=True)
        (wt_project / lib_path).write_bytes(synthesised)
        steps.append(["add", "--", repo_lib_path])
    if pending is not None:
        base = pending["base"]
        if base is None:
            steps.append(["rm", "--cached", "-q", "--", repo_root_review])
        else:
            steps.append(
                ["update-index", "--cacheinfo", f"{base[0]},{base[1]},{repo_root_review}"]
            )
    steps.append(["commit", "-q", "-m", subject])
    for args in steps:
        ok, err = _git_capture(args, wt_path)
        if not ok:
            lines = _path_lines(err)
            print(
                f"  {fr_id}.rev  ERROR — could not file {lib_path}: "
                f"{lines[-1] if lines else 'git ' + args[0] + ' failed'}"
            )
            return (False, None)

    # Bring the worktree's files in line with the commit, from the blobs —
    # the moved library file appears, and the root file the commit took off
    # the branch goes (or is restored) only when it is still exactly that blob.
    if (
        write_library
        and own
        and content is not None
        and not (wt_project / lib_path).exists()
    ):
        (wt_project / lib_path).parent.mkdir(parents=True, exist_ok=True)
        (wt_project / lib_path).write_bytes(content)
    if pending is not None and _working_file_holds_blob(
        repo_root_review, pending["blob"], wt_path
    ):
        base = pending["base"]
        restored = _git_blob_bytes(base[1], wt_path) if base is not None else None
        if restored is None:
            (wt_project / _ROOT_REVIEW).unlink()
        else:
            (wt_project / _ROOT_REVIEW).write_bytes(restored)

    if not write_library:
        print(
            f"  {fr_id}.rev  REVIEW-KEPT  {lib_path} on {branch} ({nbytes} bytes, "
            f"{source}) is already filed; took {_ROOT_REVIEW} off the branch as "
            f"'{subject}'"
        )
    elif own:
        print(
            f"  {fr_id}.rev  REVIEW-KEPT  {lib_path} on {branch} ({nbytes} bytes, "
            f"{source}) is the Reviewer's own; filed as '{subject}'"
        )
    else:
        print(
            f"  {fr_id}.rev  REVIEW-WRITTEN  {lib_path} on {branch} ({nbytes} bytes, "
            f"synthesised) as '{subject}'"
        )
    return (True, (verdict, body))


def _implementation_branch_for_fr(fr_id: str) -> tuple[str, str] | None:
    """`(branch, role)` for `claude/dev-<FR>` if it exists, else
    `claude/mnt-<FR>`, else None — AC-1's post-approve fast-forward
    target: `dev` when a normal Developer implemented the FR, `mnt` when
    it was dispatched in maintainer mode.
    @implements FR-0013:AC-1
    """
    dev_branch = _branch_for(fr_id, "dev")
    if _git_branch_exists(dev_branch):
        return (dev_branch, "dev")
    mnt_branch = _branch_for(fr_id, "mnt")
    if _git_branch_exists(mnt_branch):
        return (mnt_branch, "mnt")
    return None


def _ff_push_impl_onto_rev(
    fr_id: str, rev_branch: str, apply: bool, *, posted_pr: int | None = None
) -> bool:
    """After an approve, fast-forward the implementation branch onto the
    Reviewer's tip and push it, so the open PR's head carries the
    Reviewer's commits (round-N tests, `REVIEW.md`).

    Mirror image of `_fast_forward_rev_worktree` (FR-0006), which syncs
    the *Reviewer* worktree onto the *Developer's* tip before a re-review;
    here the *implementation* branch is synced onto the *Reviewer's* tip
    after an approve. Shares `_ff_only_merge`. Anything other than a
    clean fast-forward is refused — the dispatcher never merges (other
    than `--ff-only`), rebases or force-pushes a role branch.

    Returns True unless finalize must stop; the "nothing to do" NOTE
    cases (no implementation branch, already at/ahead of the rev tip)
    still return True — they are not errors. `apply=False` previews with
    `WOULD-FF-PUSH` and mutates nothing.

    `posted_pr` is FR-0013 AC-1 (DEC-0009 / E3): when this is called with
    `apply=True`, the caller (`_finalize_rev`) has already posted the
    review against that PR number, so every refusal ERROR this function
    prints — diverged, worktree missing/dirty, merge or push failure —
    names it, so a re-run is understood to re-post it rather than being
    read as "nothing happened". `apply=False` (the dry-run preview) never
    carries a posted review, so the suffix is omitted regardless.
    @implements FR-0013:AC-1
    @implements FR-0013:AC-9
    """
    already_posted = (
        f"; the review is already posted (#{posted_pr})"
        if apply and posted_pr is not None
        else ""
    )
    found = _implementation_branch_for_fr(fr_id)
    if found is None:
        print(
            f"  {fr_id}.rev  NOTE         no implementation branch "
            f"({_branch_for(fr_id, 'dev')} or {_branch_for(fr_id, 'mnt')}); "
            "nothing to fast-forward"
        )
        return True
    impl_branch, role = found
    impl_sha = _branch_head_sha(impl_branch)
    rev_sha = _branch_head_sha(rev_branch)
    if impl_sha == rev_sha:
        print(
            f"  {fr_id}.rev  NOTE         {impl_branch} already at "
            f"{rev_branch}'s tip ({(impl_sha or '?')[:7]})"
        )
        return True
    rev_in_impl, _ = _git_capture(
        ["merge-base", "--is-ancestor", rev_branch, impl_branch], REPO_ROOT
    )
    if rev_in_impl:
        print(
            f"  {fr_id}.rev  NOTE         {impl_branch} already contains "
            f"{rev_branch} (ahead); nothing to fast-forward"
        )
        return True
    impl_in_rev, _ = _git_capture(
        ["merge-base", "--is-ancestor", impl_branch, rev_branch], REPO_ROOT
    )
    if not impl_in_rev:
        print(
            f"  {fr_id}.rev  ERROR — {impl_branch} and {rev_branch} have "
            "diverged; refusing to fast-forward (the dispatcher never "
            f"merges or rebases role branches){already_posted}"
        )
        return False
    if not apply:
        print(f"  {fr_id}.rev  WOULD-FF-PUSH  {impl_branch} -> {rev_branch}")
        return True
    wt_path = _role_worktree_path(fr_id, role)
    if not wt_path.exists():
        print(
            f"  {fr_id}.rev  ERROR — {role} worktree missing at {wt_path}; "
            f"cannot fast-forward {impl_branch}{already_posted}"
        )
        return False
    dirty = _rev_worktree_dirty_paths(wt_path)
    if dirty:
        print(
            f"  {fr_id}.rev  ERROR — {wt_path} has uncommitted tracked "
            f"changes ({', '.join(dirty[:10])}); cannot fast-forward{already_posted}"
        )
        return False
    ok, msg = _ff_only_merge(wt_path, rev_branch)
    if not ok:
        print(
            f"  {fr_id}.rev  ERROR — fast-forward of {impl_branch} onto "
            f"{rev_branch} failed: {msg}{already_posted}"
        )
        return False
    push_ok, push_msg = _push_branch(impl_branch)
    if not push_ok:
        print(f"  {fr_id}.rev  ERROR — push of {impl_branch} failed: {push_msg}{already_posted}")
        return False
    new_sha = _branch_head_sha(impl_branch)
    print(
        f"  {fr_id}.rev  FF-PUSHED    {impl_branch} -> {rev_branch} "
        f"({(new_sha or '?')[:7]})"
    )
    record = _load_pr_record(fr_id, role) or {}
    record["head_sha"] = new_sha
    # @implements FR-0013:AC-5 (DEC-0009) — record exactly what this
    # fast-forward brought in (`impl_sha..rev_sha` at the moment of the
    # merge), unioned with any earlier value so a round-2 approve keeps
    # round 1's. This is the provenance `_mnt_provenance_exemptions`
    # checks membership against — never ancestry of `claude/rev-<FR>`.
    brought_in_ok, brought_in_out = _git_capture(
        ["rev-list", f"{impl_sha}..{rev_sha}"], REPO_ROOT
    )
    if brought_in_ok:
        brought_in = set(_path_lines(brought_in_out))
        existing_ff_commits = set(record.get("ff_commits") or [])
        record["ff_commits"] = sorted(existing_ff_commits | brought_in)
    _save_pr_record(fr_id, role, record)
    return True


def _mnt_provenance_exemptions(
    fr_id: str, branch: str, base: str, violations: list[str]
) -> set[str]:
    """FR-0013 AC-5 (DEC-0009): which of `violations` (paths a `mnt` branch
    touches outside its FR's `owns:`) are exempt from the footprint check —
    (a) commit provenance: every commit on `<base>..<branch>` that touched
    the path is a member of `ff_commits` on the implementation role's PR
    record — the exact range AC-1's `_ff_push_impl_onto_rev` fast-forwarded
    in, never ancestry of `claude/rev-<FR>` (which is vacuous once the
    implementation branch sits on the Reviewer's tip: every commit on it,
    including anything the maintainer committed before the Reviewer
    branched, is such an ancestor) — or (b) the path is under
    `specs/_metrics/**`, unconditionally.

    Prints one NOTE line per exempted path. Pure w.r.t. the working tree —
    inspects refs and the dispatcher's own PR-record state only.

    Never exempts a path matching `MNT_PROTECTED_GLOBS`: such a path is on
    `violations` only because it is outside `owns:`, so it is off-limits for
    `mnt` and stays a violation whoever committed it (FR-0015:AC-1, DEC-0015
    revising FR-0013:AC-5(a)).
    @implements FR-0013:AC-5
    @implements FR-0015:AC-1
    """
    found = _implementation_branch_for_fr(fr_id)
    ff_commits: set[str] = set()
    if found is not None:
        _impl_branch, impl_role = found
        impl_record = _load_pr_record(fr_id, impl_role) or {}
        ff_commits = set(impl_record.get("ff_commits") or [])
    rev_branch = _branch_for(fr_id, "rev")
    exempt: set[str] = set()
    # @implements FR-0024:AC-4 — `violations` are repo-relative (git's
    # spelling); the fixed `specs/_metrics/` prefix and the protected set are
    # the project's, and the provenance `git log` runs in `REPO_ROOT` (the
    # project directory), so a repo-relative path is top-anchored.
    prefix = _project_prefix()
    for path in violations:
        rel = _project_relpath(path)
        if rel is not None and (
            rel == "specs/_metrics" or rel.startswith("specs/_metrics/")
        ):
            print(f"  {fr_id}.mnt  NOTE         {path} exempt (specs/_metrics/** — AC-5b)")
            exempt.add(path)
            continue
        # @implements FR-0015:AC-1
        if _project_control_plane_path(path):
            print(
                f"  {fr_id}.mnt  NOTE         {path} not exempt: Reviewer "
                "provenance never exempts a control-plane path (DEC-0015)"
            )
            continue
        if not ff_commits:
            continue
        pathspec = f":(top){path}" if prefix else path
        ok, out = _git_capture(
            ["log", "--format=%H", f"{base}..{branch}", "--", pathspec], REPO_ROOT
        )
        if not ok:
            continue
        shas = _path_lines(out)
        if not shas:
            continue
        if all(sha in ff_commits for sha in shas):
            print(
                f"  {fr_id}.mnt  NOTE         {path} exempt (fast-forwarded "
                f"from {rev_branch} — AC-5a)"
            )
            exempt.add(path)
    return exempt


def _resolve_allow_crossing(
    fr_id: str, branch: str, base: str, allow_crossing: list[str], apply: bool
) -> tuple[set[str], bool]:
    """FR-0013 AC-6: verify each `--allow-crossing <glob>` is content-free
    on `<base>...<branch>` (ignoring line-ending and whitespace changes)
    before exempting its matched paths from the `mnt` footprint check.

    Returns (exempt_paths, ok). `ok` is False when any glob's diff carries
    real content, or the glob itself is malformed (same rule as
    `spec_footprint._validate_glob`) — the caller must refuse finalize.
    A glob matching no changed path is one WARN and no exemption (not a
    refusal). `apply=False` previews with `WOULD-ALLOW-CROSSING` /
    `WOULD-REFUSE` and mutates nothing (read-only `git diff` calls only).
    @implements FR-0013:AC-6
    @implements FR-0013:AC-9
    """
    exempt: set[str] = set()
    ok = True
    # @implements FR-0024:AC-4 — a glob is in footprint coordinates, like
    # `owns:`. The diffs run in `REPO_ROOT`, the project directory, so a
    # pathspec there is project-relative already; a repo-rooted footprint in
    # a subdirectory project top-anchors it. The matched names git prints
    # are repo-relative, the spelling `violations` carries.
    top_anchor = bool(_project_prefix()) and _layout_footprint_root() == "repo"
    for glob in allow_crossing:
        try:
            spec_footprint._validate_glob(fr_id, "--allow-crossing", glob)
        except spec_footprint.FootprintInvalid as e:
            print(f"  {fr_id}.mnt  ERROR — --allow-crossing {glob!r} invalid: {e}")
            ok = False
            continue
        pathspec = f":(top){glob}" if top_anchor else glob
        names_ok, names_out = _git_capture(
            ["diff", "--name-only", f"{base}...{branch}", "--", pathspec], REPO_ROOT
        )
        matched = _path_lines(names_out) if names_ok else []
        if not matched:
            print(f"  {fr_id}.mnt  WARN         --allow-crossing {glob!r} matches no changed path")
            continue
        content_ok, content_out = _git_capture(
            [
                "diff",
                "--ignore-cr-at-eol",
                "--ignore-all-space",
                f"{base}...{branch}",
                "--",
                pathspec,
            ],
            REPO_ROOT,
        )
        if not content_ok or content_out.strip():
            tag = "WOULD-REFUSE" if not apply else "ERROR      —"
            print(
                f"  {fr_id}.mnt  {tag} --allow-crossing {glob!r} carries content "
                "beyond line-ending/whitespace changes; refusing"
            )
            ok = False
            continue
        tag = "WOULD-ALLOW-CROSSING" if not apply else "CROSSING-ALLOWED"
        print(f"  {fr_id}.mnt  {tag}  {glob!r} ({len(matched)} file(s))")
        exempt.update(matched)
    return (exempt, ok)


_INDEX_MD_RELPATH = "specs/INDEX.md"
# @implements FR-0018:AC-4 (DEC-0030 item 6) — every path other than
# specs/INDEX.md that the worktree's `index-specs.py` can write, relative to
# the project root. The AC-4 resolution puts each back as it found it, so the
# merge commit holds their textual merge (DEC-0011) and the worktree is left
# clean. A later FR that gives the indexer another output adds it here.
_INDEXER_SIDE_WRITES: tuple[str, ...] = ("CODEOWNERS",)


def _snapshot_paths(root: Path, rels: tuple[str, ...]) -> dict[str, bytes | None]:
    """Each `root`-relative path's exact bytes, or None when it is absent."""
    snap: dict[str, bytes | None] = {}
    for rel in rels:
        path = root / rel
        snap[rel] = path.read_bytes() if path.is_file() else None
    return snap


def _restore_paths(root: Path, snap: dict[str, bytes | None]) -> list[str]:
    """Put every path in `snap` back as it was: rewrite changed bytes, remove a
    path that did not exist, recreate one that was deleted. File writes and
    unlinks only, never a git command. Returns the paths it could not
    restore."""
    failed: list[str] = []
    for rel, before in snap.items():
        path = root / rel
        try:
            now = path.read_bytes() if path.is_file() else None
            if now == before and (before is not None or not path.exists()):
                continue
            if before is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(before)
        except OSError:
            failed.append(rel)
    return failed


def _merge_conflicted_paths(wt_path: Path) -> list[str] | None:
    """Repo-relative paths left unmerged in `wt_path`, or None when git
    cannot say."""
    ok, out = _git_capture(["diff", "--name-only", "--diff-filter=U", "-z"], wt_path)
    if not ok:
        return None
    return sorted({p.strip() for p in out.split("\0") if p.strip()})


# @implements FR-0018:AC-4
def _resolve_index_only_merge_conflict(
    fr_id: str, role: str, branch: str, wt_path: Path
) -> bool | None:
    """Conclude a `--revalidate` merge whose only conflict is `specs/INDEX.md`.

    Applies only when a merge is in progress in `wt_path` and every unmerged
    path is `specs/INDEX.md`; otherwise returns None and touches nothing, so
    the caller prints today's ERROR. When it applies, the index is
    regenerated by the worktree's own `scripts/index-specs.py` (the indexer
    roots at its own file, so the dispatcher's copy would index the primary
    checkout), staged, and the merge is concluded with `git commit --no-edit`,
    which records both parents. No history is rewritten and no new merge is
    started. One `MERGE-RESOLVED` line names the path.

    The indexer's side-writes (`_INDEXER_SIDE_WRITES`, today `CODEOWNERS`)
    are snapshotted before it runs and put back after it returns, on success
    and on failure, so the resolution changes nothing but `specs/INDEX.md`
    (DEC-0030 item 6).

    Returns True when resolved. A missing worktree indexer, an indexer that
    exits non-zero (a malformed `.agent-team/layout.yaml` included, DEC-0030),
    a side-write that cannot be put back, or a failed stage/commit is one
    ERROR line and False, with the conflict left in place for a human: the
    conflicted `INDEX.md` bytes are put back if the indexer changed them.
    """
    # @implements FR-0024:AC-4 (DEC-0031 item 2) — `_INDEX_MD_RELPATH` is
    # project-relative; git's conflicted path and the `git add` pathspec
    # (both at the worktree root) are its repository spelling, while the
    # indexer, its cwd, the snapshot and the side-writes are rooted at the
    # project inside the worktree. A conflict on a repository-top
    # `specs/INDEX.md` outside the project is not this one.
    index_repo_path = _repo_path(_INDEX_MD_RELPATH)
    wt_project = _worktree_project_root(wt_path)
    conflicted = _merge_conflicted_paths(wt_path)
    if conflicted != [index_repo_path]:
        return None
    merging, _ = _git_capture(["rev-parse", "-q", "--verify", "MERGE_HEAD"], wt_path)
    if not merging:
        return None
    prefix = (
        f"  {fr_id}.{role}  ERROR — merge of origin/main into {branch} "
        f"conflicted on {_INDEX_MD_RELPATH}"
    )
    indexer = wt_project / "scripts" / "index-specs.py"
    if not indexer.is_file():
        print(f"{prefix}, and {indexer} is absent; left for a human")
        return False
    index_snapshot = _snapshot_paths(wt_project, (_INDEX_MD_RELPATH,))
    side_snapshot = _snapshot_paths(wt_project, _INDEXER_SIDE_WRITES)
    try:
        proc = subprocess.run(
            [sys.executable, str(indexer)],
            cwd=str(wt_project),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        rc = proc.returncode
        detail = _path_lines((proc.stdout or "") + "\n" + (proc.stderr or ""))
    except (OSError, subprocess.TimeoutExpired) as e:
        rc, detail = None, [f"{type(e).__name__}: {e}"]
    # On success and on failure alike: the side-writes go back first.
    unrestored = _restore_paths(wt_project, side_snapshot)
    if rc != 0 or unrestored:
        _restore_paths(wt_project, index_snapshot)
        if rc != 0:
            why = f"exited {rc}" if rc is not None else "could not run"
            last = f" ({detail[-1]})" if detail else ""
            print(f"{prefix}, and {indexer} {why}{last}; left for a human")
        else:
            print(
                f"{prefix}; regenerated it, but could not put back the indexer's "
                f"other output ({', '.join(unrestored)}); left for a human"
            )
        return False
    for argv, what in (
        (["add", "--", index_repo_path], "staging the regenerated index"),
        (["commit", "--no-edit"], "concluding the merge"),
    ):
        ok, err = _git_capture(argv, wt_path)
        if not ok:
            lines = _path_lines(err)
            staged = (
                f"; {_INDEX_MD_RELPATH} is staged and the merge is still in progress"
                if argv[0] == "commit"
                else ""
            )
            print(
                f"{prefix}; regenerated it, but {what} failed: "
                f"{lines[-1] if lines else err}{staged}; left for a human"
            )
            return False
    print(
        f"  {fr_id}.{role}  MERGE-RESOLVED  {_INDEX_MD_RELPATH}: conflict resolved by "
        "regenerating it with the worktree's scripts/index-specs.py; merge concluded "
        "(git commit --no-edit)"
    )
    return True


def _finalize_revalidate_stale_branch(
    fr_id: str, role: str, branch: str, apply: bool, draft: bool, revalidate: bool
) -> bool:
    """FR-0013 AC-7: a branch whose base has moved gets a rebase-and-
    revalidate step rather than a red CI mystery.

    Checks, before the push, whether `origin/main` carries commits
    `branch` lacks. Without `--revalidate`, that is one WARN line and
    finalize proceeds exactly as today. With it, merges `origin/main`
    into the role worktree with an ordinary merge — the fixed point's one
    explicit exception to "no merge other than `--ff-only`" — re-runs the
    deploy gate (via `_finalize_gate_preflight`, against the merged tree),
    in the role worktree, `--status-only` (DEC-0011),
    and proceeds only when the post-merge result is the same or better
    than the pre-merge baseline. A merge conflict or a newly red gate is
    one ERROR line, a non-zero exit, no push — and the worktree is left
    with the conflict/merge in place for a human, never aborted.

    Returns False when finalize must stop. `apply=False` previews with
    `WOULD-REVALIDATE` and mutates nothing.

    The one conflict it resolves is one confined to `specs/INDEX.md`, a
    generated file (`_resolve_index_only_merge_conflict`, DEC-0022 as
    narrowed by DEC-0024 and DEC-0025).
    @implements FR-0013:AC-7
    @implements FR-0013:AC-9
    @implements FR-0018:AC-4
    """
    _git_fetch_origin_main()
    missing = _commits_ahead("origin/main", branch) or 0
    if not missing:
        return True
    if not revalidate:
        print(
            f"  {fr_id}.{role}  WARN — origin/main has {missing} commit(s) "
            f"{branch} lacks; pass --revalidate to merge and re-run the gate"
        )
        return True
    wt_path = _role_worktree_path(fr_id, role)
    if not apply:
        print(
            f"  {fr_id}.{role}  WOULD-REVALIDATE  merge origin/main "
            f"({missing} commit(s)) into {wt_path}; re-run the gate"
        )
        return True
    if not wt_path.exists():
        print(
            f"  {fr_id}.{role}  ERROR — {role} worktree missing at {wt_path}; "
            "cannot revalidate"
        )
        return False
    dirty = _rev_worktree_dirty_paths(wt_path)
    if dirty:
        print(
            f"  {fr_id}.{role}  ERROR — {wt_path} has uncommitted tracked "
            f"changes ({', '.join(dirty[:10])}); cannot revalidate"
        )
        return False
    # @implements FR-0024:AC-2 — the gate in the project inside the worktree.
    wt_project = _worktree_project_root(wt_path)
    pre_ok, _pre_out = _run_deploy_gate("dev", None, cwd=wt_project, status_only=True)
    ok, err = _git_capture(
        [
            "merge",
            "origin/main",
            "-m",
            f"merge origin/main into {branch} (finalize --revalidate)",
        ],
        wt_path,
    )
    if not ok:
        # @implements FR-0018:AC-4 — a conflict confined to specs/INDEX.md is
        # resolved by regenerating it; anything else is today's ERROR.
        resolved = _resolve_index_only_merge_conflict(fr_id, role, branch, wt_path)
        if resolved is None:
            lines = _path_lines(err)
            print(
                f"  {fr_id}.{role}  ERROR — merge of origin/main into {branch} failed: "
                f"{lines[-1] if lines else err}; left for a human"
            )
            return False
        if not resolved:
            return False
    post_ok, post_note = _finalize_gate_preflight(
        fr_id=fr_id,
        role=role,
        stage="dev",
        draft=draft,
        force=False,
        cwd=wt_project,
        status_only=True,
    )
    # @implements FR-0013:AC-7 (DEC-0009 K2/K3) — the draft exemption lets a
    # red gate *open* a draft PR; it does not make a green->red transition
    # the merge itself caused "same or better". Newly red is one ERROR, a
    # non-zero exit and no push, draft or not; the REVALIDATE line never
    # claims `gate=pass` for a draft-exempt red gate.
    post_red = (not post_ok) or (post_note == "draft-exempt")
    if pre_ok and post_red:
        if post_ok:
            # _finalize_gate_preflight only WARNed (it treats the gate as
            # exempted, not failed) — state the newly-red refusal explicitly.
            print(
                f"  {fr_id}.{role}  ERROR — deploy gate went from pass to red "
                "after merging origin/main (draft PR exempt does not cover a "
                "regression the merge caused); refusing"
            )
        # else: _finalize_gate_preflight already printed the ERROR/output.
        return False
    merged_sha = _branch_head_sha(branch)
    if post_note == "draft-exempt":
        outcome = "red (draft-exempt; unchanged from before the merge)"
    elif post_ok:
        outcome = "pass"
    else:
        outcome = "red (unchanged from before the merge)"
    print(
        f"  {fr_id}.{role}  REVALIDATE   merged origin/main "
        f"({(merged_sha or '?')[:7]}) into {branch}; gate={outcome}"
    )
    return True


# @implements FR-0016:AC-1
def _finalize_gat(fr_id: str, gat_branch: str, apply: bool) -> int:
    """Land a gate-review session's evidence commit onto the FR's
    implementation branch.

    `gat_branch` (`claude/gat-<FR>`) is a disposable staging branch cut from
    the implementation branch's tip; it is never pushed to origin and never
    carries its own PR. Its one evidence commit (already made by
    `_finalize_commit_step`, the FR-0006:AC-1 path, with the AC-6 subject
    `_finalize_commit_subject` derives from the evidence file) is fast-
    forwarded onto the implementation branch (`claude/dev-<FR>` if it
    exists, else `claude/mnt-<FR>`; `_base_branch_for_role` resolves it
    through `_implementation_branch_for_fr`, DEC-0012 item 3) and *that*
    branch is pushed. A `changes-requested` verdict additionally posts the
    evidence body as a comment on the open PR.
    @implements FR-0008:AC-6
    """
    fr_id_disp = fr_id
    base_branch = _base_branch_for_role(fr_id, "gat")
    if not apply:
        print(
            f"  {fr_id}.gat  WOULD-FINALIZE  {gat_branch} -> {base_branch} -> origin"
        )
        return 0
    dev_branch = base_branch
    ok, out = _git_capture(["diff", "--name-only", f"{base_branch}..{gat_branch}"], REPO_ROOT)
    # @implements FR-0024:AC-4 — tested in project coordinates; the
    # repo-relative path git printed is kept, and read as it is below.
    evidence_paths = (
        [
            p for p in _path_lines(out)
            if (_project_relpath(p) or "").startswith(f"specs/_gates/{fr_id}-")
            and p.endswith(".md")
        ]
        if ok
        else []
    )
    if len(evidence_paths) != 1:
        print(
            f"  {fr_id}.gat  ERROR — expected exactly one gate evidence file "
            f"changed on {gat_branch}, found {len(evidence_paths)}: {evidence_paths}"
        )
        return 1
    evidence_rel = evidence_paths[0]
    show_ok, evidence_text = _git_capture(["show", f"{gat_branch}:{evidence_rel}"], REPO_ROOT)
    if not show_ok:
        print(f"  {fr_id}.gat  ERROR — cannot read {evidence_rel} on {gat_branch}")
        return 1
    m = FRONTMATTER_PATTERN.match(evidence_text)
    meta: dict = {}
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
    gate_id = str(meta.get("gate") or "")
    verdict = str(meta.get("verdict") or "")
    by = str(meta.get("by") or "architect")
    round_ctx = meta.get("round")
    round_num = int(round_ctx) if isinstance(round_ctx, int) and round_ctx > 0 else 1
    head_sha = meta.get("head_sha")
    if not gate_id or verdict not in ("pass", "changes-requested"):
        print(
            f"  {fr_id_disp}.gat  ERROR — {evidence_rel} on {gat_branch} is "
            "malformed (missing/invalid gate or verdict)"
        )
        return 1
    gate_decl = {g["id"]: g for g in _fr_gates(fr_id)}.get(gate_id)
    after = gate_decl["after"] if gate_decl else "dev"
    reviewer = gate_decl["reviewer"] if gate_decl else "architect"
    dev_sha = _branch_head_sha(dev_branch)
    gat_sha = _branch_head_sha(gat_branch)
    if dev_sha != gat_sha:
        is_ancestor, _ = _git_capture(
            ["merge-base", "--is-ancestor", dev_branch, gat_branch], REPO_ROOT
        )
        if not is_ancestor:
            print(
                f"  {fr_id}.gat  ERROR — {dev_branch} and {gat_branch} have "
                "diverged; refusing to fast-forward"
            )
            return 1
        ff_ok, ff_err = _git_capture(
            ["update-ref", f"refs/heads/{dev_branch}", gat_sha or "", dev_sha or ""],
            REPO_ROOT,
        )
        if not ff_ok:
            print(
                f"  {fr_id}.gat  ERROR — fast-forward of {dev_branch} onto "
                f"{gat_branch} failed: {ff_err}"
            )
            return 1
    push_ok, push_msg = _push_branch(dev_branch)
    if not push_ok:
        print(f"  {fr_id}.gat  ERROR — push of {dev_branch} failed: {push_msg}")
        return 1
    print(
        f"  {fr_id}.gat  GATED        {gate_id} {verdict} by {by} "
        f"({dev_branch} {push_msg})"
    )
    nwo = _repo_nwo()
    if verdict == "changes-requested":
        pr_num = _gh_pr_for_branch(dev_branch)
        if pr_num is not None:
            body = evidence_text[m.end():].strip() if m else evidence_text.strip()
            comment = subprocess.run(
                [
                    "gh",
                    "pr",
                    "comment",
                    str(pr_num),
                    "--repo",
                    nwo or "",
                    "--body",
                    body or "(no rationale provided)",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if comment.returncode != 0:
                err = (comment.stderr or comment.stdout or "").strip().splitlines()
                print(
                    f"  {fr_id}.gat  WARN — gh pr comment failed: "
                    f"{err[-1] if err else 'unknown error'}"
                )
        else:
            print(
                f"  {fr_id}.gat  NOTE — no open PR for {dev_branch}; "
                "changes-requested body not posted as a comment"
            )
    # @implements FR-0008:AC-11
    _metrics_emit(
        "gate.decision",
        role="architect",
        object_ids=[fr_id],
        run_id=None,
        gate=gate_id,
        after=after,
        reviewer=reviewer,
        verdict=verdict,
        by=by,
        round=round_num,
        head_sha=str(head_sha) if head_sha else None,
    )
    return 0


def cmd_finalize(
    fr_id: str,
    role: str,
    apply: bool,
    draft: bool,
    adapter: HarnessAdapter | None = None,
    *,
    verdict_file: Path | None = None,
    allow_crossing: list[str] | None = None,
    revalidate: bool = False,
    review_round: int | str | None = None,
) -> int:
    """Push the role's branch and post the corresponding PR action.

    For role=dev: opens (or refreshes) a draft PR sourced from the
    Developer's PR_BODY.md in the worktree.

    For role=rev: posts a `gh pr review` against the parent dev PR with
    the verdict extracted from the Reviewer's final assistant text (or
    from `--verdict-file`, AC-4), files the round's review — the Reviewer's
    own `REVIEW.md` when it wrote one (AC-2) — at `specs/_reviews/<FR>-r<N>.md`
    (FR-0025 AC-1), and — on an approve — fast-forwards the
    implementation branch onto the Reviewer's tip and pushes it (AC-1).

    `verdict_file`, `allow_crossing` and `revalidate` are FR-0013 additions;
    all default to today's behaviour when omitted. `review_round` (rev only,
    FR-0025 AC-4) names the review round for the library path when the
    dispatcher cannot know it.
    """
    # @implements FR-0024:AC-6 — a layout the loader refuses stops finalize
    # before it reads a branch, writes a file or runs a process.
    layout_err = _layout_refusal()
    if layout_err is not None:
        print(f"  {fr_id}.{role}  ERROR — {layout_err}")
        return 1

    label = ROLE_LABELS.get(role, role)
    branch = _branch_for(fr_id, role)

    # @implements FR-0025:AC-4 — validated before anything else, so a bad
    # value does nothing at all.
    round_override: int | None = None
    if review_round is not None:
        if role != "rev":
            print(
                f"  {fr_id}.{role}  ERROR — --review-round applies to --role rev only"
            )
            return 1
        round_override = _parse_review_round(review_round)
        if round_override is None:
            print(
                f"  {fr_id}.rev  ERROR — --review-round must be an integer >= 1 "
                f"(got {review_round!r})"
            )
            return 1

    # Lock-state safety: if the agent is still running, finalize would
    # race with active commits. Refuse politely.
    state, _lock = lock_state(fr_id, role)
    if state == "held":
        print(
            f"  {fr_id}.{role}  SKIP — {label} still running (lock held); finalize after it exits"
        )
        return 1

    if not _git_branch_exists(branch):
        print(f"  {fr_id}.{role}  ERROR — branch {branch} does not exist locally")
        return 1

    # The dispatcher owns the commit (FR-0006). Commit the agent's staged
    # index first — before the footprint check, the gh preflight and the push —
    # so staged work is visible to everything downstream and nothing is pushed
    # when the commit cannot complete or the branch would open an empty PR.
    # Dry-run previews the same decisions and mutates nothing.
    step_ok, _ahead = _finalize_commit_step(fr_id, role, branch, apply)
    if not step_ok:
        return 1 if apply else 0

    # @implements FR-0008:AC-6 — `gat` never pushes its own branch or opens
    # a PR; it lands its one evidence commit onto `claude/dev-<FR>` and
    # pushes that branch instead. Handled entirely by `_finalize_gat`.
    if role == "gat":
        return _finalize_gat(fr_id, branch, apply)

    # @implements FR-0015:AC-2 — a dev/rev/bkf branch carrying a
    # control-plane path never reaches a push, a review post or a PR,
    # whoever committed it. Placed here, before AC-7's `origin/main` merge
    # below could pull in an unrelated upstream change to a protected path.
    if role in ("dev", "rev", "bkf"):
        cp_paths, cp_err = _control_plane_branch_paths(fr_id, role, branch, apply)
        if cp_err is not None:
            tag = "ERROR —" if apply else "WOULD-REFUSE"
            print(f"  {fr_id}.{role}  {tag} control-plane check failed: {cp_err}")
            return 1 if apply else 0
        if cp_paths:
            tag = "ERROR —" if apply else "WOULD-REFUSE"
            print(
                f"  {fr_id}.{role}  {tag} {branch} touches control-plane "
                "path(s) outside what this role may write: " + ", ".join(cp_paths)
            )
            return 1 if apply else 0

    # @implements FR-0015:AC-3 — uncommitted changes to an off-limits path
    # refuse finalize for every role. The dispatcher never restores, stages,
    # unstages or reverts what it finds.
    uncommitted_paths, uncommitted_err = _uncommitted_control_plane_paths(fr_id, role)
    if uncommitted_err is not None:
        tag = "ERROR —" if apply else "WOULD-REFUSE"
        print(f"  {fr_id}.{role}  {tag} worktree check failed: {uncommitted_err}")
        return 1 if apply else 0
    if uncommitted_paths:
        tag = "ERROR —" if apply else "WOULD-REFUSE"
        print(
            f"  {fr_id}.{role}  {tag} uncommitted control-plane path(s) in "
            "the worktree: " + ", ".join(uncommitted_paths)
        )
        return 1 if apply else 0

    # @implements FR-0015:AC-4 — a permission file the agent rewrote refuses
    # finalize.
    digest_violation = _finalize_settings_digest_violation(fr_id, role)
    if digest_violation is not None:
        tag = "ERROR —" if apply else "WOULD-REFUSE"
        print(f"  {fr_id}.{role}  {tag} permission file changed since it was "
              f"written: {digest_violation}")
        return 1 if apply else 0

    # @implements FR-0013:AC-7 — before the push, for every role that opens
    # a PR against `main`. Runs in both apply and dry-run (WOULD-REVALIDATE).
    if role in ("dev", "mnt", "bkf") and not _finalize_revalidate_stale_branch(
        fr_id, role, branch, apply, draft, revalidate
    ):
        return 1

    verdict_and_body: tuple[str, str] | None = None
    if role == "rev":
        step_ok2, verdict_and_body = _materialise_review_md(
            fr_id,
            branch,
            adapter,
            apply,
            verdict_file=verdict_file,
            review_round=round_override,
        )
        if not step_ok2:
            return 1

    # Artifact-level backstop on the derived footprint. Runs before the push
    # so a derivation or agent defect cannot reach a PR.
    if role == "mnt":
        violations, footprint_err = mnt_footprint_violations(fr_id, branch)
        if footprint_err is not None:
            print(f"  {fr_id}.mnt  ERROR — footprint check failed: {footprint_err}")
            return 1
        exempt: set[str] = set()
        if violations:
            # @implements FR-0013:AC-5
            exempt |= _mnt_provenance_exemptions(fr_id, branch, "main", violations)
        crossing_ok = True
        if allow_crossing:
            # @implements FR-0013:AC-6
            crossing_exempt, crossing_ok = _resolve_allow_crossing(
                fr_id, branch, "main", allow_crossing, apply
            )
            exempt |= crossing_exempt
        if violations:
            remaining = [v for v in violations if v not in exempt]
            if remaining:
                print(
                    f"  {fr_id}.mnt  ERROR — branch touches {len(remaining)} path(s) "
                    f"outside {fr_id} `owns:`: " + ", ".join(remaining)
                )
                return 1
        if not crossing_ok:
            return 1

    ok, err = _gh_preflight(verbose=False)
    if not ok:
        print(f"  {fr_id}.{role}  ERROR — {err}")
        return 1

    head_sha = _branch_head_sha(branch)
    nwo = _repo_nwo()

    if not apply:
        if role == "dev":
            print(
                f"  {fr_id}.dev  WOULD-FINALIZE  push {branch} -> origin; "
                f"gh pr create {'--draft ' if draft else ''}--base main --head {branch} "
                f"(repo={nwo}, head={head_sha[:7] if head_sha else '?'})"
            )
        elif role in ("bkf", "mnt"):
            print(
                f"  {fr_id}.{role}  WOULD-FINALIZE  push {branch} -> origin; "
                f"gh pr create {'--draft ' if draft else ''}--base main --head {branch} "
                f"--title '{_oneshot_pr_title(fr_id, role)}' "
                f"(repo={nwo}, head={head_sha[:7] if head_sha else '?'})"
            )
        else:
            # @implements FR-0013:AC-11 — resolve the implementation role
            # (`dev`, else `mnt`) the same way AC-1's fast-forward does.
            found = _implementation_branch_for_fr(fr_id)
            impl_role = found[1] if found is not None else "dev"
            existing = _load_pr_record(fr_id, impl_role)
            parent_pr = (existing or {}).get("pr_number")
            verdict = verdict_and_body[0] if verdict_and_body else "comment"
            # @implements FR-0013:AC-1, FR-0013:AC-9 — preview the post-
            # approve fast-forward; mutates nothing (apply=False).
            if verdict == "approve":
                _ff_push_impl_onto_rev(fr_id, branch, apply=False)
            flag = {
                "approve": "--approve",
                "request-changes": "--request-changes",
                "comment": "--comment",
            }[verdict]
            print(
                f"  {fr_id}.rev  WOULD-FINALIZE  push {branch} -> origin; "
                f"gh pr review #{parent_pr or '?'} {flag} --body <reviewer text>  "
                f"(repo={nwo})"
            )
        return 0

    # Push the role branch. Fast-forward only.
    push_ok, push_msg = _push_branch(branch)
    if not push_ok:
        print(f"  {fr_id}.{role}  ERROR — push failed: {push_msg}")
        return 1
    print(f"  {fr_id}.{role}  PUSHED       {branch} ({push_msg})")

    if role == "dev":
        return _finalize_dev(fr_id, branch, head_sha, nwo, draft)
    if role == "rev":
        if verdict_file is not None:
            return _finalize_rev(
                fr_id, branch, head_sha, nwo, adapter, verdict_file=verdict_file
            )
        return _finalize_rev(fr_id, branch, head_sha, nwo, adapter)
    if role in ("bkf", "mnt"):
        return _finalize_oneshot(
            fr_id,
            branch,
            head_sha,
            nwo,
            draft,
            role=role,
            pr_title=_oneshot_pr_title(fr_id, role),
        )
    print(f"  {fr_id}.{role}  ERROR — unknown role")
    return 1


def _gate_draft_refusal(fr_id: str, role: str, draft: bool) -> bool:
    """True (having printed the one `ERROR` line) when `draft` is False and
    this FR has a declared `after: dev` gate that is not `pass` — the AC-8
    guard shared by every path that un-drafts a PR.

    Factored out of `_finalize_dev` so `_finalize_oneshot` (`mnt` / `bkf`)
    refuses the same way; DEC-0012 item 4.
    @implements FR-0008:AC-8
    """
    if draft:
        return False
    pending = _pending_after_dev_gates(fr_id, _fr_gates(fr_id))
    if not pending:
        return False
    names = ", ".join(f"{g['id']} ({status})" for g, status in pending)
    print(
        f"  {fr_id}.{role}  ERROR — cannot open ready-for-review: "
        f"unsatisfied gate(s): {names}"
    )
    return True


# @implements FR-0016:AC-1
def _refresh_gates_section_on_existing_pr(
    pr_body_path: Path, fr_id: str, pr_number: int, nwo: str | None, role: str
) -> None:
    """Best-effort refresh of the `## Gates` section on an already-open PR.

    Shared by `_finalize_dev` and `_finalize_oneshot`'s existing-PR legs
    (round 3 ruling (i), AC-8): re-renders the section into the local
    `PR_BODY.md` and, only if it changed, pushes it with `gh pr edit`. A
    failed edit is a non-fatal `WARN`, never a finalize failure.

    @implements FR-0008:AC-8
    """
    if not _apply_gates_section(pr_body_path, fr_id):
        return
    edit = subprocess.run(
        [
            "gh",
            "pr",
            "edit",
            str(pr_number),
            "--repo",
            nwo or "",
            "--body-file",
            str(pr_body_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if edit.returncode != 0:
        err = (edit.stderr or edit.stdout or "").strip().splitlines()
        print(
            f"  {fr_id}.{role}  WARN — gh pr edit (Gates section) failed: "
            f"{err[-1] if err else 'unknown error'}"
        )


# @implements FR-0016:AC-1, FR-0016:AC-4
def _finalize_dev(
    fr_id: str, branch: str, head_sha: str | None, nwo: str | None, draft: bool
) -> int:
    """Open or refresh a (draft) PR for the Developer's branch.

    @implements FR-0008:AC-8 — refuses to open (or refresh into) a
    ready-for-review PR while a declared `after: dev` gate is unsatisfied;
    the PR stays draft.
    """
    if _gate_draft_refusal(fr_id, "dev", draft):
        return 1
    wt_path = REPO_ROOT / ".claude" / "worktrees" / f"dev-{fr_id}"
    # @implements FR-0024:AC-2, FR-0024:AC-3 — the project's PR_BODY.md, in
    # the worktree and (fallback) on the branch.
    pr_body_path = _worktree_project_root(wt_path) / "PR_BODY.md"
    if not pr_body_path.exists():
        # Try the worktree on the dev branch via git show as a fallback —
        # the body file might have been committed but worktree pruned.
        show = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "show",
                f"{branch}:{_repo_path('PR_BODY.md')}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if show.returncode != 0:
            print(
                f"  {fr_id}.dev  ERROR — PR_BODY.md not found at {pr_body_path} "
                "and not present on the branch; cannot create PR"
            )
            return 1
        # Materialise to a tempfile inside _dispatch so subsequent re-runs
        # can find it (and it survives worktree removal).
        pr_body_path = DISPATCH_DIR / f"{fr_id}.dev.pr_body.md"
        pr_body_path.write_text(show.stdout, encoding="utf-8")

    title_subject = _fr_title(fr_id) or fr_id
    pr_title = f"feat({fr_id}): {title_subject}"

    existing_pr = _gh_pr_for_branch(branch)
    record = _load_pr_record(fr_id, "dev") or {}
    if existing_pr is not None:
        # PR already open against this head: don't recreate. Surface and
        # update the local record so it stays accurate.
        nwo_url = f"https://github.com/{nwo}/pull/{existing_pr}"
        record.update(
            {
                "pr_number": existing_pr,
                "pr_url": nwo_url,
                "branch": branch,
                "head_sha": head_sha,
                "draft": draft,
                "title": pr_title,
                "note": "PR already open; commits pushed as fast-forward",
            }
        )
        _save_pr_record(fr_id, "dev", record)
        # @implements FR-0008:AC-8 — refresh the `## Gates` section on the
        # existing `pr.refreshed` path so the human sees current gate state
        # on the PR itself; best-effort, never fails the finalize.
        _refresh_gates_section_on_existing_pr(pr_body_path, fr_id, existing_pr, nwo, "dev")
        print(f"  {fr_id}.dev  PR-EXISTS    #{existing_pr}  {nwo_url}")
        _emit_pr_event("pr.refreshed", fr_id, "dev", record, branch)
        return 0

    # @implements FR-0008:AC-8 — `## Gates` section on a fresh PR body.
    _apply_gates_section(pr_body_path, fr_id)

    # Create a fresh PR.
    cmd = [
        "gh",
        "pr",
        "create",
        "--repo",
        nwo or "",
        "--base",
        "main",
        "--head",
        branch,
        "--title",
        pr_title,
        "--body-file",
        str(pr_body_path),
    ]
    if draft:
        cmd.append("--draft")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        last = err[-1] if err else "gh pr create failed"
        print(f"  {fr_id}.dev  ERROR — gh pr create failed: {last}")
        return 1
    pr_url = (proc.stdout or "").strip().splitlines()[-1]
    pr_number_match = re.search(r"/pull/(\d+)$", pr_url)
    pr_number = int(pr_number_match.group(1)) if pr_number_match else None
    record.update(
        {
            "pr_number": pr_number,
            "pr_url": pr_url,
            "branch": branch,
            "head_sha": head_sha,
            "draft": draft,
            "title": pr_title,
        }
    )
    _save_pr_record(fr_id, "dev", record)
    tag = "DRAFT-OPENED" if draft else "PR-OPENED"
    print(f"  {fr_id}.dev  {tag} #{pr_number}  {pr_url}")
    _emit_pr_event("pr.opened", fr_id, "dev", record, branch)
    return 0


# @implements FR-0016:AC-1, FR-0016:AC-4
def _finalize_oneshot(
    fr_id: str,
    branch: str,
    head_sha: str | None,
    nwo: str | None,
    draft: bool,
    role: str,
    pr_title: str,
) -> int:
    """Open or refresh a PR for a one-shot role's own branch (`bkf` / `mnt`).

    Mirrors `_finalize_dev` but uses the role's worktree path and the role's
    own PR title. PR_BODY.md is the agent's own deliverable in these modes.

    @implements FR-0008:AC-8 — the same draft refusal `_finalize_dev` applies
    (DEC-0012 item 4): a maintainer-mode PR does not un-draft past an
    unsatisfied declared `after: dev` gate either.
    """
    if _gate_draft_refusal(fr_id, role, draft):
        return 1
    wt_path = REPO_ROOT / ".claude" / "worktrees" / f"{role}-{fr_id}"
    # @implements FR-0024:AC-2, FR-0024:AC-3
    pr_body_path = _worktree_project_root(wt_path) / "PR_BODY.md"
    if not pr_body_path.exists():
        show = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "show",
                f"{branch}:{_repo_path('PR_BODY.md')}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if show.returncode != 0:
            print(
                f"  {fr_id}.{role}  ERROR — PR_BODY.md not found at {pr_body_path} "
                "and not present on the branch; cannot create PR"
            )
            return 1
        pr_body_path = DISPATCH_DIR / f"{fr_id}.{role}.pr_body.md"
        pr_body_path.write_text(show.stdout, encoding="utf-8")

    existing_pr = _gh_pr_for_branch(branch)
    record = _load_pr_record(fr_id, role) or {}
    if existing_pr is not None:
        nwo_url = f"https://github.com/{nwo}/pull/{existing_pr}"
        record.update(
            {
                "pr_number": existing_pr,
                "pr_url": nwo_url,
                "branch": branch,
                "head_sha": head_sha,
                "draft": draft,
                "title": pr_title,
                "note": "PR already open; commits pushed as fast-forward",
            }
        )
        _save_pr_record(fr_id, role, record)
        # @implements FR-0008:AC-8 — round 3 ruling (i): the maintainer-mode
        # existing-PR leg refreshes `## Gates` exactly as `_finalize_dev`
        # does, so a human reviewing a `mnt`/`bkf` PR sees current gate
        # state on the PR itself, not just on `_finalize_dev`'s output.
        _refresh_gates_section_on_existing_pr(pr_body_path, fr_id, existing_pr, nwo, role)
        print(f"  {fr_id}.{role}  PR-EXISTS    #{existing_pr}  {nwo_url}")
        _emit_pr_event("pr.refreshed", fr_id, role, record, branch)
        return 0

    # @implements FR-0008:AC-8 — round 3 ruling (i): `## Gates` section on a
    # fresh one-shot-role PR body, mirroring `_finalize_dev`'s fresh-PR leg.
    _apply_gates_section(pr_body_path, fr_id)

    cmd = [
        "gh",
        "pr",
        "create",
        "--repo",
        nwo or "",
        "--base",
        "main",
        "--head",
        branch,
        "--title",
        pr_title,
        "--body-file",
        str(pr_body_path),
    ]
    if draft:
        cmd.append("--draft")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        last = err[-1] if err else "gh pr create failed"
        print(f"  {fr_id}.{role}  ERROR — gh pr create failed: {last}")
        return 1
    pr_url = (proc.stdout or "").strip().splitlines()[-1]
    pr_number_match = re.search(r"/pull/(\d+)$", pr_url)
    pr_number = int(pr_number_match.group(1)) if pr_number_match else None
    record.update(
        {
            "pr_number": pr_number,
            "pr_url": pr_url,
            "branch": branch,
            "head_sha": head_sha,
            "draft": draft,
            "title": pr_title,
        }
    )
    _save_pr_record(fr_id, role, record)
    tag = "DRAFT-OPENED" if draft else "PR-OPENED"
    print(f"  {fr_id}.{role}  {tag} #{pr_number}  {pr_url}")
    _emit_pr_event("pr.opened", fr_id, role, record, branch)
    return 0


# @implements FR-0016:AC-1
def _finalize_rev(
    fr_id: str,
    branch: str,
    head_sha: str | None,
    nwo: str | None,
    adapter: HarnessAdapter | None,
    *,
    verdict_file: Path | None = None,
) -> int:
    """Post a gh pr review against the parent PR for the implementation
    branch — `claude/dev-<FR>` if it exists, else `claude/mnt-<FR>`
    (FR-0013 AC-11) — then, on an approve, fast-forward that branch onto
    this Reviewer tip and push it (AC-1). `verdict_file` is FR-0013 AC-4
    (subagent-run Reviewer, no dispatch log)."""
    # @implements FR-0013:AC-11
    found = _implementation_branch_for_fr(fr_id)
    if found is not None:
        impl_branch, impl_role = found
    else:
        impl_branch, impl_role = (_branch_for(fr_id, "dev"), "dev")
    impl_record = _load_pr_record(fr_id, impl_role)
    parent_pr = (impl_record or {}).get("pr_number")
    if parent_pr is None:
        # Fallback: look up the open PR for the implementation branch directly.
        parent_pr = _gh_pr_for_branch(impl_branch)
    if parent_pr is None:
        if found is None:
            print(
                f"  {fr_id}.rev  ERROR — no parent PR for {impl_branch} or "
                f"{_branch_for(fr_id, 'mnt')}; run `dispatch.py finalize "
                "FR-XXXX --role dev --apply` (or --role mnt) first"
            )
        else:
            print(
                f"  {fr_id}.rev  ERROR — no parent PR for {impl_branch}; "
                f"run `dispatch.py finalize FR-XXXX --role {impl_role} --apply` first"
            )
        return 1

    # @implements FR-0013:AC-3, FR-0013:AC-4 — `announce=False`: when this
    # is reached via `cmd_finalize`, `_materialise_review_md` already
    # resolved and announced the same (verdict, body) pair once.
    parsed = _reviewer_verdict_and_body(fr_id, adapter, verdict_file, announce=False)
    if parsed is None:
        if verdict_file is not None:
            print(f"  {fr_id}.rev  ERROR — --verdict-file {verdict_file} is missing or empty")
        else:
            print(f"  {fr_id}.rev  ERROR — no reviewer log at {DISPATCH_DIR / f'{fr_id}.rev.log'}")
        return 1
    verdict, body = parsed

    # gh pr review's body has a 65k char limit; truncate aggressively
    # and link to the log file for the full text.
    MAX_BODY = 60000
    if len(body) > MAX_BODY:
        body = (
            body[:MAX_BODY] + "\n\n---\n_Reviewer body truncated for GitHub. "
            f"Full transcript: `_dispatch/{fr_id}.rev.log`._"
        )

    body_path = DISPATCH_DIR / f"{fr_id}.rev.review_body.md"
    body_path.write_text(body, encoding="utf-8")

    flag_for_verdict = {
        "approve": "--approve",
        "request-changes": "--request-changes",
        "comment": "--comment",
    }
    flag = flag_for_verdict[verdict]

    cmd = [
        "gh",
        "pr",
        "review",
        str(parent_pr),
        "--repo",
        nwo or "",
        flag,
        "--body-file",
        str(body_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    posted_as = verdict
    fallback_note: str | None = None
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        # GitHub forbids approve/request-changes on PRs the reviewer
        # authored. When that fires, retry as a plain --comment with the
        # verdict prepended to the body so the verdict is still legible.
        own_pr = "your own pull request" in stderr.lower()
        if own_pr and verdict in ("approve", "request-changes"):
            verdict_label = "APPROVE" if verdict == "approve" else "REQUEST CHANGES"
            fallback_body = (
                f"> **Reviewer verdict: {verdict_label}**  \n"
                f"> _Posted as a comment because GitHub does not permit "
                f"`{flag}` on a PR authored by the same account. The full "
                f"reviewer handoff follows verbatim._\n\n"
                f"---\n\n{body}"
            )
            body_path.write_text(fallback_body, encoding="utf-8")
            cmd_fb = [
                "gh",
                "pr",
                "review",
                str(parent_pr),
                "--repo",
                nwo or "",
                "--comment",
                "--body-file",
                str(body_path),
            ]
            proc = subprocess.run(
                cmd_fb,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if proc.returncode == 0:
                posted_as = f"comment (intended {verdict})"
                fallback_note = "own-PR fallback to --comment"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            last = err[-1] if err else "gh pr review failed"
            print(f"  {fr_id}.rev  ERROR — gh pr review failed: {last}")
            return 1

    record = _load_pr_record(fr_id, "rev") or {}
    record.update(
        {
            "parent_pr_number": parent_pr,
            "verdict": verdict,
            "posted_as": posted_as,
            "head_sha": head_sha,
            "body_chars": len(body),
            "rev_branch_pushed": branch,
        }
    )
    if fallback_note:
        record["note"] = fallback_note
    _save_pr_record(fr_id, "rev", record)
    # @implements FR-0002:AC-5 (pr.review)
    if _metrics is not None:
        ctx = _run_context(fr_id, "rev")
        rnd = ctx.get("round")
        _metrics_emit(
            "pr.review",
            role="rev",
            object_ids=[fr_id],
            run_id=ctx.get("run_id"),
            parent_pr_number=parent_pr,
            verdict=verdict,
            posted_as=posted_as,
            round=int(rnd) if isinstance(rnd, int) and rnd > 0 else 1,
        )
    pr_url = f"https://github.com/{nwo}/pull/{parent_pr}"
    print(
        f"  {fr_id}.rev  REVIEW-POSTED  #{parent_pr}  verdict={verdict}"
        f"{' (posted as comment, see body)' if fallback_note else ''}  {pr_url}"
    )
    # @implements FR-0013:AC-1 — after the review is posted, an approve
    # fast-forwards the implementation branch onto this Reviewer tip. A
    # refusal (diverged, worktree missing/dirty, merge or push failure) is
    # a hard stop: the terminal state AC-1 requires was not reached, so
    # finalize exits non-zero. `_ff_push_impl_onto_rev`'s own ERROR line
    # already names the parent PR as already-posted (`posted_pr`), so a
    # re-run is understood to re-post it rather than as "nothing happened"
    # (DEC-0009 / E3) — no second ERROR line here.
    if verdict == "approve" and not _ff_push_impl_onto_rev(
        fr_id, branch, apply=True, posted_pr=parent_pr
    ):
        return 1
    return 0


def cmd_finalize_all(role: str, apply: bool, draft: bool) -> int:
    """Finalize every FR whose role branch exists locally and whose lock
    is not held. Useful after a wave to push everything in one shot.
    """
    ok, err = _gh_preflight(verbose=False)
    if not ok:
        print(f"finalize-all aborted: {err}")
        return 1

    candidates: list[str] = []
    for fr in load_frs():
        fr_id = fr["id"]
        branch = _branch_for(fr_id, role)
        if not _git_branch_exists(branch):
            continue
        # Don't reopen PRs for FRs that are already merged/done/deployed.
        # Their dev branches survive locally for archaeology but the PR
        # work is over.
        if fr["status"] in TERMINAL_STATUSES:
            print(f"  {fr_id}.{role}  SKIP — FR status={fr['status']} (terminal)")
            continue
        state, _ = lock_state(fr_id, role)
        if state == "held":
            print(f"  {fr_id}.{role}  SKIP — lock held")
            continue
        candidates.append(fr_id)

    if not candidates:
        print(
            f"No FRs eligible for finalize (no `claude/{role}-*` branches with finished agents)."
        )
        return 0

    print(
        f"Finalizing {role} branches for: {candidates}  "
        f"({'APPLY' if apply else 'dry-run'}, draft={draft if role == 'dev' else 'n/a'})"
    )
    rc_total = 0
    for fr_id in candidates:
        rc = cmd_finalize(fr_id, role, apply=apply, draft=draft, adapter=None)
        if rc != 0:
            rc_total = rc
    return rc_total


def cmd_oneshot(
    fr_id: str,
    role: str,
    apply: bool,
    adapter: HarnessAdapter,
    skip_env_preflight: bool = False,
) -> int:
    """One-shot per-FR spawn for a role that isn't tick-scheduled.

    `bkf` (Reviewer in backfill mode) runs when `reconcile-merged` flipped an
    FR to `merged` and the deploy gate now reports missing `@covers` because
    the original PR landed without test coverage. It writes only the missing
    tests and opens `test(FR-XXXX): backfill AC coverage`.

    `mnt` (Developer in maintainer mode) runs for an FR whose `owns:` footprint
    intersects the control-plane paths every other role denies. Its writable
    footprint is derived from that FR's `owns:` and nothing else, so it refuses
    to start against an FR that declares none.

    Both branch off `main` into `claude/<role>-FR-XXXX`, author `PR_BODY.md`,
    and open their own PR via `finalize --role <role>`. Neither is scheduled by
    `tick` — they are dispatched per-FR by hand.
    """
    label = ROLE_LABELS.get(role, role)
    state, lock = lock_state(fr_id, role)
    if state == "held":
        print(
            f"  {fr_id}.{role}  SKIP — {label} lock held "
            f"(pid={lock['pid']}, since {lock['started_at_iso']})"
        )
        return 1
    if state == "stale":
        print(
            f"  {fr_id}.{role}  WARN — stale {label} lock "
            f"(pid={lock['pid']}, started {lock['started_at_iso']}); not auto-clearing"
        )
        return 1
    if state == "dead":
        print(
            f"  {fr_id}.{role}  SKIP — orphaned lock "
            f"(pid={lock['pid']} no longer alive); run `dispatch.py prune`"
        )
        return 1
    if state == "corrupt":
        print(
            f"  {fr_id}.{role}  WARN — corrupt lockfile at {lock_path(fr_id, role)}; skipping"
        )
        return 1

    spec_paths = list(SPECS_DIR.glob(f"{fr_id}-*.md"))
    if not spec_paths:
        print(f"  {fr_id}.{role}  ERROR — no spec at specs/{fr_id}-*.md")
        return 1

    # @implements FR-0006:AC-8 — `mnt` is dev-shaped: a maintainer branch that
    # already carries the status flip is a handed-off FR, not fresh work.
    handed_off = _handed_off_reason(fr_id, role)
    if handed_off is not None:
        print(f"  {fr_id}.{role}  SKIP — {handed_off}")
        return 1

    if role == "mnt":
        owns = fr_owns_globs(fr_id)
        if not owns:
            print(
                f"  {fr_id}.mnt  ERROR — {fr_id} declares no `owns:` frontmatter; "
                "mnt derives its writable footprint from it and will not run unscoped"
            )
            return 1
        granted, _ = mnt_permission_rules(owns)
        print(f"  {fr_id}.mnt  FOOTPRINT    {', '.join(granted)}")
    elif role == "bkf":
        # @implements FR-0010:AC-5
        if _owns_preflight_for(fr_id, "bkf") is None:
            return 1

    # @implements FR-0011:AC-6, FR-0011:AC-7, FR-0011:AC-8, FR-0011:AC-9
    # Only `mnt` ("maintain") is named by AC-6/AC-8; `bkf` ("backfill") is
    # a one-shot Reviewer follow-up, not one of the three FR-0011 commands,
    # so it never runs this gate. Runs *before* the AC-7 STACK line (not
    # merely before `spawn_role`) so a pre-flight WARN/BLOCK line never sits
    # between FR-0010's STACK line and this spawn's SPAWNED/WOULD-SPAWN line
    # — the two are pinned adjacent by FR-0010's own Reviewer tests.
    preflight_segment = ""
    if role == "mnt":
        gate = _run_env_preflight(
            apply, _env_preflight_skip_requested(skip_env_preflight)
        )
        if gate.blocked:
            blocking = [f for f in gate.findings if f.severity == "block"]
            print(
                f"  {fr_id}.{role}  ERROR — environment pre-flight blocked "
                f"({len(blocking)} blocking finding(s)); no worktree created"
            )
            return 1
        preflight_segment = gate.metrics_segment

    # @implements FR-0010:AC-7
    _print_stack_report(fr_id, role, _stack_preflight(fr_id, role))

    result, pid, wt_path = spawn_role(
        fr_id, role, apply=apply, adapter=adapter, **_spawn_extra_kwargs(preflight_segment)
    )
    if result == "dry-run":
        wt_preview = REPO_ROOT / ".claude" / "worktrees" / f"{role}-{fr_id}"
        preview = adapter.dry_run_preview(fr_id, role, wt_preview)
        print(f"  {fr_id}.{role}  WOULD-SPAWN  {preview}  (base=main)")
        return 0
    if result == "spawned":
        print(
            f"  {fr_id}.{role}  SPAWNED      pid={pid}, worktree={wt_path}, "
            f"log={DISPATCH_DIR / f'{fr_id}.{role}.log'}"
        )
        return 0
    if result == "binary-not-found":
        hint = (
            "install via `winget install Anthropic.ClaudeCode`"
            if adapter.name == "claude-code"
            else "install Cursor + run `cursor-agent login`, or set DISPATCH_HARNESS=claude-code"
        )
        print(
            f"  {fr_id}.{role}  ERROR        `{adapter.binary_name}` CLI not on PATH; {hint}"
        )
        return 1
    print(f"  {fr_id}.{role}  ERROR        {result}")
    return 1


def _cmd_tick_gat(
    apply: bool, adapter: HarnessAdapter, fr_filter: list[str] | None
) -> int:
    """`dispatch.py tick --role gat --fr <FR>` — spawn a one-shot Architect
    gate-review session for the first unsatisfied `after: dev`,
    `reviewer: architect` gate declared on `<FR>`.
    @implements FR-0008:AC-6
    """
    if not fr_filter or len(fr_filter) != 1:
        print("ERROR: `tick --role gat` requires exactly one `--fr FR-XXXX`")
        return 1
    fr_id = fr_filter[0]
    by_id = {fr["id"]: fr for fr in load_frs()}
    fr = by_id.get(fr_id)
    if fr is None:
        print(f"ERROR: unknown FR id {fr_id!r} (no specs/{fr_id}-*.md with readable frontmatter)")
        return 1
    architect_pending = [
        (g, s)
        for g, s in _pending_after_dev_gates(fr_id, fr.get("gates") or ())
        if g["reviewer"] == "architect"
    ]
    if not architect_pending:
        print(f"{fr_id}: no unsatisfied `after: dev` architect gate to review")
        return 0
    gate, status = architect_pending[0]
    state, lock = lock_state(fr_id, "gat")
    if state == "held":
        print(f"  {fr_id}.gat  SKIP — lock held (pid={(lock or {}).get('pid', '?')})")
        return 1
    result, pid, wt_path = spawn_role(
        fr_id, "gat", apply=apply, adapter=adapter, gate_id=gate["id"]
    )
    if result == "dry-run":
        wt_preview = REPO_ROOT / ".claude" / "worktrees" / f"gat-{fr_id}"
        preview = adapter.dry_run_preview(fr_id, "gat", wt_preview, gate_id=gate["id"])
        base = _base_branch_for_role(fr_id, "gat")
        print(f"  {fr_id}  WOULD-SPAWN  {preview}  (base={base}, gate={gate['id']}, was {status})")
        return 0
    if result == "spawned":
        log_file = DISPATCH_DIR / f"{fr_id}.gat.log"
        print(f"  {fr_id}  SPAWNED      pid={pid}, worktree={wt_path}, log={log_file}")
        return 0
    if result == "binary-not-found":
        hint = (
            "install via `winget install Anthropic.ClaudeCode`"
            if adapter.name == "claude-code"
            else "install Cursor + run `cursor-agent login`"
        )
        print(f"  {fr_id}  ERROR        `{adapter.binary_name}` CLI not on PATH; {hint}")
        return 1
    print(f"  {fr_id}  ERROR        {result}")
    return 1


def cmd_tick(
    apply: bool,
    adapter: HarnessAdapter,
    role: str = "dev",
    fr_filter: list[str] | None = None,
    skip_env_preflight: bool = False,
) -> int:
    """`fr_filter` is None when `--fr` was not supplied, which dispatches the
    whole runnable set exactly as before. When supplied, every named FR must be
    runnable for this role or the tick aborts non-zero without spawning.
    """
    # @implements FR-0024:AC-6 — before any preflight, prune, reconcile,
    # worktree or spawn.
    layout_err = _layout_refusal()
    if layout_err is not None:
        print(f"ERROR: {layout_err}")
        return 1
    # @implements FR-0008:AC-6 — `gat` is FR+gate scoped and one-shot; it
    # never participates in the runnable-set machinery the rest of this
    # function drives, so it is handled entirely by a dedicated helper.
    if role == "gat":
        return _cmd_tick_gat(apply, adapter, fr_filter)
    role_label = ROLE_LABELS.get(role, role)
    frs = load_frs()
    if not frs:
        print("No FRs found in specs/")
        return 0

    # Warn-only preflight: tick proceeds even when gh is unavailable so
    # local-only flows aren't blocked. finalize will surface the error
    # again at finalize-time.
    gh_ok, gh_err = _gh_preflight(verbose=False)
    if not gh_ok:
        print(f"NOTE: GitHub PR finalization disabled ({gh_err}). Tick continues.")

    pruned = prune_dead_locks(verbose=False)
    if pruned:
        print(f"Auto-pruned {pruned} dead lock(s) before tick.")

    # Project merged PRs back into the spec graph + working state. Without
    # this, a `tick` after a PR merge re-fires the same FR (status still
    # reads `ready` on main) and dependents stay blocked. Runs in the same
    # mode as the surrounding tick: `--apply` commits the flips and removes
    # the worktrees; dry-run prints intent only. NO-OP when gh is offline.
    if gh_ok:
        recon = reconcile_merged_prs(apply=apply, verbose=False)
        if recon.flipped or recon.cleaned:
            verb = "Reconciled merged PRs" if apply else "WOULD reconcile merged PRs"
            bits = []
            if recon.flipped:
                bits.append(
                    f"{'flipped' if apply else 'flip'} status: {sorted(set(recon.flipped))}"
                )
            if recon.cleaned:
                bits.append(
                    f"{'cleaned' if apply else 'clean'} worktree/branch/lock for: {sorted(set(recon.cleaned))}"
                )
            print(f"{verb} — {'; '.join(bits)}")
            for fr_id, reason in recon.skipped:
                print(f"  reconcile skip {fr_id}: {reason}")
            if apply and recon.flipped:
                # Re-load FRs so runnable_frs reads the post-flip state.
                frs = load_frs()

    last_tick = read_last_tick()
    if role == "rev":
        runnable = runnable_review_frs(frs)
        empty_msg = (
            "No runnable FRs for Reviewer "
            "(need status in {in-progress,in-review}, dev branch present, no held dev lock)."
        )
    else:
        runnable = runnable_frs(frs)
        empty_msg = "No runnable FRs (none with status=ready and deps fully merged)."

    if fr_filter is not None:
        runnable, problems = filter_frs_by_selector(frs, fr_filter, role)
        if problems:
            print(f"--fr selection cannot run for {role_label}:")
            for problem in problems:
                print(f"  {problem}")
            return 1
        empty_msg = f"--fr selection is empty for {role_label}."
        print(f"--fr filter active: {[fr['id'] for fr in runnable]}")
    elif role == "dev":
        # @implements FR-0006:AC-9 — say why a `ready` FR is no longer listed.
        for skipped_id, reason in handed_off_frs(frs, role):
            print(f"  {skipped_id}  SKIP — {reason}")
    elif role == "rev":
        # @implements FR-0008:AC-4 — say why an otherwise-reviewable FR is
        # excluded by an unsatisfied declared `after: dev` gate.
        for skipped_id, reason in gate_pending_review_frs(frs):
            print(f"  {skipped_id}  SKIP — {reason}")

    if not runnable:
        print(empty_msg)
    else:
        print(
            f"Runnable FRs for {role_label} "
            f"({'APPLY' if apply else 'dry-run'}, harness={adapter.name}): "
            f"{[fr['id'] for fr in runnable]}"
        )

    # @implements FR-0011:AC-6, FR-0011:AC-7, FR-0011:AC-8, FR-0011:AC-9
    # A single, host-level check for this tick invocation — before
    # `ensure_role_worktree` runs for any FR below. A blocking finding stops
    # the whole tick (apply mode only; AC-9's dry-run never stops).
    gate = _run_env_preflight(apply, _env_preflight_skip_requested(skip_env_preflight))
    if gate.blocked:
        blocking = [f for f in gate.findings if f.severity == "block"]
        print(
            f"Tick aborted: environment pre-flight blocked "
            f"({len(blocking)} blocking finding(s))."
        )
        return 1

    for fr in runnable:
        state, lock = lock_state(fr["id"], role)
        if state == "held":
            print(
                f"  {fr['id']}  SKIP — {role_label} lock held (pid={lock['pid']}, since {lock['started_at_iso']})"
            )
            continue
        if state == "stale":
            print(
                f"  {fr['id']}  WARN — stale {role_label} lock (pid={lock['pid']}, started {lock['started_at_iso']}); not auto-clearing"
            )
            continue
        if state == "dead":
            print(
                f"  {fr['id']}  SKIP — orphaned lock (pid={lock['pid']} no longer alive); run `dispatch.py prune`"
            )
            continue
        if state == "corrupt":
            print(
                f"  {fr['id']}  WARN — corrupt lockfile at {lock_path(fr['id'], role)}; skipping"
            )
            continue
        # @implements FR-0009:AC-7 — `owns-grants=<n>` on the `dev`
        # spawn-report line; also runs the AC-2/AC-3/AC-5 WARN/ERROR checks
        # before the spawn attempt, in both dry-run and apply.
        # @implements FR-0010:AC-5 — the same preflight, generalised, for
        # `rev` (its owns:-derived grants are FR-0010's, not FR-0009's).
        owns_grants: int | None = None
        if role == "dev":
            owns_grants = _dev_owns_preflight(fr["id"])
            if owns_grants is None:
                continue
        elif role == "rev" and _owns_preflight_for(fr["id"], "rev") is None:
            continue
        owns_note = f"  owns-grants={owns_grants}" if role == "dev" else ""
        # @implements FR-0010:AC-7
        stack_tools = _stack_preflight(fr["id"], role)
        _print_stack_report(fr["id"], role, stack_tools)
        result, pid, wt_path = spawn_role(
            fr["id"],
            role,
            apply=apply,
            adapter=adapter,
            **_spawn_extra_kwargs(gate.metrics_segment),
        )
        if result == "dry-run":
            wt_preview = REPO_ROOT / ".claude" / "worktrees" / f"{role}-{fr['id']}"
            preview = adapter.dry_run_preview(fr["id"], role, wt_preview)
            base = _base_branch_for_role(fr["id"], role)
            if _print_rev_sync_preview(fr["id"], role, wt_preview):
                print(f"  {fr['id']}  WOULD-SPAWN  {preview}  (base={base}){owns_note}")
        elif result == "spawned":
            log_file = DISPATCH_DIR / "{}.{}.log".format(fr["id"], role)
            print(
                f"  {fr['id']}  SPAWNED      pid={pid}, worktree={wt_path}, log={log_file}{owns_note}"
            )
        elif result == "binary-not-found":
            hint = (
                "install via `winget install Anthropic.ClaudeCode`"
                if adapter.name == "claude-code"
                else "install Cursor + run `cursor-agent login`, or set DISPATCH_HARNESS=claude-code"
            )
            print(
                f"  {fr['id']}  ERROR        `{adapter.binary_name}` CLI not on PATH; {hint}"
            )
        elif result == "spawn-failed":
            log_file = DISPATCH_DIR / "{}.{}.log".format(fr["id"], role)
            print(
                f"  {fr['id']}  ERROR        spawn failed (OSError); see {log_file}"
            )
        elif result.startswith("error:"):
            print(f"  {fr['id']}  ERROR        worktree setup failed: {result[6:]}")

    escalations = new_escalations(last_tick)
    if escalations:
        print()
        print(f"New escalations since last tick ({last_tick or 'never'}):")
        for p in escalations:
            print(
                f"  - {p.relative_to(REPO_ROOT)}  ({dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')})"
            )

    if apply:
        write_last_tick()
    return 0


def _fmt_secs(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = divmod(s // 60, 60)
    return f"{h}h{m}m"


def cmd_status() -> int:
    print(f"Dispatch dir: {DISPATCH_DIR}")
    if not DISPATCH_DIR.exists():
        print("  (does not exist yet — no ticks have run)")
        return 0
    locks = sorted(DISPATCH_DIR.glob("*.lock"))
    if not locks:
        print("  No active locks.")
    else:
        print(f"  {len(locks)} lock(s):")
        for lp in locks:
            stem = lp.stem
            try:
                fr_id, role = stem.rsplit(".", 1)
            except ValueError:
                fr_id, role = stem, "dev"
            state, data = lock_state(fr_id, role)
            if state == "corrupt" or data is None:
                print(f"    {lp.name}  CORRUPT")
                continue
            pid = data.get("pid")
            harness = data.get("harness", "claude-code")
            started_at = data.get("started_at", 0)
            uptime = dt.datetime.now(dt.timezone.utc).timestamp() - started_at
            idle = log_idle_seconds(fr_id, role, started_at=started_at)
            log_path = DISPATCH_DIR / f"{fr_id}.{role}.log"
            log_size = log_path.stat().st_size if log_path.exists() else 0
            if state == "dead":
                tag = "DEAD     "
                hint = "(process exited; run `prune`)"
            elif state == "stale":
                tag = "STALE    "
                hint = f"(alive >{_fmt_secs(STALE_LOCK_SECONDS)} — verify manually)"
            elif idle is not None and idle > IDLE_LOG_THRESHOLD_SECONDS:
                tag = f"IDLE {_fmt_secs(idle):>5}"
                hint = "(alive but log static — likely permission-blocked)"
            else:
                tag = "WORKING  "
                hint = f"(log last write {_fmt_secs(idle) if idle is not None else '?'} ago)"
            print(
                f"    {lp.name}  pid={pid}  harness={harness}  {tag}  uptime={_fmt_secs(uptime)}  log={log_size}B  {hint}"
            )
    last = read_last_tick()
    print(f"Last tick: {last.isoformat(timespec='seconds') if last else 'never'}")
    return 0


def prune_dead_locks(verbose: bool = True) -> int:
    """Remove locks whose process is dead or whose JSON is corrupt.

    Returns the count pruned. `verbose=True` prints one line per removal;
    callers that want a quieter, summary-only output (e.g. cmd_tick) can
    pass False.
    """
    if not DISPATCH_DIR.exists():
        return 0
    pruned = 0
    for lp in sorted(DISPATCH_DIR.glob("*.lock")):
        stem = lp.stem
        try:
            fr_id, role = stem.rsplit(".", 1)
        except ValueError:
            continue
        state, data = lock_state(fr_id, role)
        if state == "dead":
            lp.unlink()
            if verbose:
                pid = data.get("pid") if data else "?"
                print(f"  pruned {lp.name} (pid={pid} no longer alive)")
            pruned += 1
        elif state == "corrupt":
            lp.unlink()
            if verbose:
                print(f"  pruned {lp.name} (corrupt)")
            pruned += 1
    return pruned


def cmd_prune() -> int:
    if not DISPATCH_DIR.exists():
        print("No dispatch dir; nothing to prune.")
        return 0
    pruned = prune_dead_locks(verbose=True)
    if pruned == 0:
        print("No prunable locks (all live processes; nothing to clean).")
    else:
        print(f"Pruned {pruned} lock(s).")
    return 0


def cmd_kill(fr_id: str, role: str) -> int:
    state, data = lock_state(fr_id, role)
    if state == "free":
        print(f"No lock for {fr_id}.{role}; nothing to kill.")
        return 0
    if state == "corrupt" or data is None:
        print(f"Lock for {fr_id}.{role} is corrupt; removing.")
        lock_path(fr_id, role).unlink(missing_ok=True)
        return 0
    pid = int(data.get("pid", 0))
    wt = data.get("worktree") if data else None
    if state == "dead":
        print(f"Process pid={pid} for {fr_id}.{role} already dead; removing lock.")
        lock_path(fr_id, role).unlink(missing_ok=True)
    else:
        killed = kill_pid(pid)
        if killed:
            print(f"Killed pid={pid} for {fr_id}.{role}.")
        else:
            print(
                f'WARN: failed to kill pid={pid}; check manually with `tasklist /FI "PID eq {pid}"`.'
            )
        lock_path(fr_id, role).unlink(missing_ok=True)
        print(f"Removed lock {lock_path(fr_id, role).name}.")
    print()
    if wt:
        print(f"Worktree at {wt} preserved (any partial work intact).")
        print("To discard and re-fire fresh, manually run:")
        print(f'  git -C "{REPO_ROOT}" worktree remove --force "{wt}"')
        print(f'  git -C "{REPO_ROOT}" branch -D claude/{role}-{fr_id}')
    print(
        "Reminder: this did NOT touch the FR frontmatter on main. If the killed agent flipped"
    )
    print(
        "the FR's status in its worktree branch, that branch is isolated — main's status is"
    )
    print(
        "untouched, so re-firing tick will see the FR as still runnable (assuming worktree removed)."
    )
    return 0


def _adapter_for_lock(fr_id: str, role: str) -> HarnessAdapter:
    """Resolve which adapter to use for log parsing/status display.

    Reads the lockfile's `harness` field if present (newer locks); falls
    back to claude-code for legacy locks written before the cursor adapter
    landed.
    """
    state, data = lock_state(fr_id, role)
    if data and isinstance(data, dict):
        return get_adapter(str(data.get("harness", "claude-code")))
    return get_adapter("claude-code")


def cmd_summary(fr_id: str, role: str, harness: str | None) -> int:
    log_path = DISPATCH_DIR / f"{fr_id}.{role}.log"
    if not log_path.exists():
        print(f"No log at {log_path}")
        return 1
    adapter = get_adapter(harness) if harness else _adapter_for_lock(fr_id, role)
    s = adapter.parse_log(log_path)
    state, lock_data = lock_state(fr_id, role)
    print(f"=== {fr_id}.{role} summary (harness={adapter.name}) ===")
    print(f"Lock state:  {state}")
    if lock_data:
        wt = lock_data.get("worktree")
        print(
            f"  pid={lock_data.get('pid')}  started={lock_data.get('started_at_iso')}"
        )
        if wt:
            print(f"  worktree={wt}")
            print(f"  branch=claude/{role}-{fr_id}")
    print(
        f"Result:      {s.result_subtype or '(no result line — process likely killed mid-run)'}{' (ERROR)' if s.is_error else ''}"
    )
    print(f"Tool calls:  {s.tool_counts or '(none recorded)'}")
    if s.error_objs:
        print(f"Tool errors: {len(s.error_objs)}")
        for e in s.error_objs[-3:]:
            content = e.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(c.get("text", "")) for c in content if isinstance(c, dict)
                )
            print(f"  - {str(content)[:200]}")
    print()
    print("Final assistant text:")
    if s.last_text:
        for line in s.last_text.splitlines():
            print(f"  {line}")
    else:
        print("  (no text emitted)")
    return 0


REVIEW_CYCLE_BUDGET = 3



def _first_spec_frontmatter(fr_id: str) -> dict | None:
    """Parsed YAML frontmatter of the first `specs/<fr_id>-*.md` match, or
    None when the spec is missing, unparseable, or its frontmatter fence
    doesn't match.

    Shared by `fr_owns_globs` (which stringifies every `owns:` entry for
    callers that only care about path text) and `_invalid_owns_entries`
    (FR-0009:AC-5), which needs the raw, unstringified values so a
    non-string entry is still detectable as invalid rather than silently
    coerced to a string that happens to validate.
    """
    for path in sorted(SPECS_DIR.glob(f"{fr_id}-*.md")):
        m = FRONTMATTER_PATTERN.match(path.read_text(encoding="utf-8"))
        if m is None:
            return None
        try:
            return yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return None
    return None


def fr_owns_globs(fr_id: str) -> list[str]:
    """The target FR's `owns:` frontmatter, as a list of path globs.

    Empty when the spec is missing, unparseable, or declares no `owns:`.
    This is the sole authority for a role run's writable footprint, so an
    empty result must abort the spawn rather than fall back to a default.
    """
    meta = _first_spec_frontmatter(fr_id)
    if meta is None:
        return []
    return [str(g) for g in (meta.get("owns") or []) if str(g).strip()]


def _owned(path: str, owns: list[str]) -> bool:
    """True iff a concrete repo-relative path is covered by an `owns:` glob."""
    return any(path == o or fnmatch.fnmatch(path, o) for o in owns)


def _protected_touched(protected: str, owns: list[str]) -> bool:
    """True iff the FR owns something at or under a protected glob."""
    if "**" in protected:
        root = protected.split("**", 1)[0]
        return any(o.startswith(root) for o in owns)
    return protected in owns


def mnt_permission_rules(owns: list[str]) -> tuple[list[str], list[str]]:
    """Derive a `mnt` run's (granted_globs, protected_denies) from `owns:`.

    A broad protected glob is *narrowed*, never dropped: Claude Code resolves
    deny over allow, so leaving `.agent-team/**` denied would silently defeat
    an `Edit(.agent-team/roles/reviewer.md)` grant. Instead the broad entry is
    replaced by a concrete deny for each currently-tracked sibling the FR does
    not own, which keeps the rest of the tree protected without granting a
    subtree-wide escape.
    """
    granted = [g for g in owns if g not in MNT_NEVER_WRITABLE]
    denies: list[str] = []
    for protected in MNT_PROTECTED_GLOBS:
        if protected in MNT_NEVER_WRITABLE or not _protected_touched(protected, owns):
            denies.append(protected)
            continue
        # The FR owns something under this glob. Deny each unowned sibling.
        root = protected.split("**", 1)[0].rstrip("/")
        siblings = sorted(
            p.relative_to(REPO_ROOT).as_posix()
            for p in (REPO_ROOT / root).rglob("*")
            if p.is_file()
        )
        denies.extend(s for s in siblings if not _owned(s, owns))
    return granted, denies


def mnt_unwritable_grants(owns: list[str]) -> list[str]:
    """`owns:` globs that are grantable in a settings file but harness-guarded.

    The derivation cannot make these writable, so a `mnt` run needs to know
    which of its declared paths it will not be able to touch — otherwise the
    only way to finish its declared work looks like bypassing the deny list.
    """
    out: list[str] = []
    for glob in owns:
        for guarded in HARNESS_GUARDED_GLOBS:
            root = guarded.split("**", 1)[0]
            if glob.startswith(root) or fnmatch.fnmatch(glob, guarded):
                out.append(glob)
                break
    return out


def mnt_unwritable_hint(glob: str) -> str | None:
    """The sanctioned route for updating a harness-guarded path, if known."""
    for prefix, hint in HARNESS_GUARDED_SOURCE_HINT.items():
        if glob.startswith(prefix):
            return hint
    return None


# ---------------------------------------------------------------------------
# FR-0009: `dev` worktree permissions derived from `owns:`
#
# `mnt_permission_rules` (above) is the maintainer derivation: a protected
# glob the FR owns is *narrowed* into per-sibling denies, because `mnt`
# exists precisely to let a control-plane FR write the control-plane paths
# it declares. `dev` gets the opposite half of the same idea: a protected
# glob is withheld outright, never narrowed — that narrowing stays `mnt`'s
# privilege, so `owns:` cannot itself upgrade a normal Developer into a
# maintainer. See FR-0009 Notes ("Reuse, don't fork").
# ---------------------------------------------------------------------------


def _owns_entry_protected(glob: str) -> bool:
    """True iff a single (already-valid) `owns:` glob is one `dev` must
    never be granted: `MNT_NEVER_WRITABLE`, at or under a
    `MNT_PROTECTED_GLOBS` entry, or the Reviewer-owned test pattern
    (FR-0009:AC-2).
    """
    if glob in MNT_NEVER_WRITABLE:
        return True
    if fnmatch.fnmatch(glob, "tests/test_*.py"):
        return True
    for protected in MNT_PROTECTED_GLOBS:
        if protected in MNT_NEVER_WRITABLE:
            continue
        if "**" in protected:
            root = protected.split("**", 1)[0]
            if glob.startswith(root):
                return True
        elif glob == protected or fnmatch.fnmatch(protected, glob):
            return True
    return False


def dev_owns_grants(owns: list[str]) -> tuple[list[str], list[str]]:
    """Split a (pre-validated) `owns:` glob list into `(granted, withheld)`
    for `dev` (FR-0009:AC-1/AC-2).

    `granted` still includes harness-guarded globs (AC-3's open-question
    default: write the grant and rely on the WARN so the settings file
    never claims a path is out of scope when it is merely harness-guarded).
    `withheld` is the AC-2 protected-path set; the caller reports it and
    the static `dev` deny list is left untouched either way — there is no
    per-sibling narrowing here, unlike `mnt_permission_rules`.
    """
    granted = [g for g in owns if not _owns_entry_protected(g)]
    withheld = [g for g in owns if _owns_entry_protected(g)]
    return granted, withheld


def _invalid_owns_entries(fr_id: str) -> list[str]:
    """Raw (pre-stringification) `owns:` entries that fail
    `spec_footprint`'s own glob validation (FR-0009:AC-5) — reused, not
    duplicated, so the indexer and the dispatcher never disagree about
    which footprints are legal. Empty when the spec, its frontmatter, or
    `owns:` is missing, or every entry already validates.

    A present `owns:` that is not itself a YAML list (`owns: "src/**"`,
    `owns: 42`, `owns: {a: b}`) is exactly the shape `spec_footprint.
    parse_footprint`'s `_lift` rejects before it ever gets to iterate
    entries; mirrored here (same message) rather than falling through to
    `fr_owns_globs`, which would iterate a scalar into bogus per-character
    grants or raise `TypeError` on a non-iterable and abort the whole
    `tick`/`wave` run (FR-0009:AC-5 kick-back item 1).
    """
    meta = _first_spec_frontmatter(fr_id)
    if meta is None:
        return []
    raw = meta.get("owns")
    if raw is None:
        return []
    if not isinstance(raw, list):
        msg = (
            f"{fr_id}: owns must be a YAML list of glob strings, "
            f"got {type(raw).__name__}: {raw!r}"
        )
        return [msg]
    bad: list[str] = []
    for entry in raw:
        try:
            spec_footprint._validate_glob(fr_id, "owns", entry)
        except spec_footprint.FootprintInvalid as e:
            bad.append(str(e))
    return bad


def dev_owns_derivation(fr_id: str) -> dict[str, list[str]]:
    """Everything the `dev` permission derivation needs from one FR.

    Returns a dict with:
      `invalid`         — AC-5 errors; non-empty means the spawn must be
                           refused and none of the other keys are usable.
      `granted`         — AC-1 grants (a subset of `owns:`).
      `withheld`        — AC-2 protected globs, granted nothing.
      `harness_guarded` — AC-3, the subset of `granted` the harness also
                           independently guards.

    Pure and side-effect-free; callers (the adapters' `dev_permissions`,
    and the dispatcher's spawn-report printing) decide what to do with it.
    """
    invalid = _invalid_owns_entries(fr_id)
    if invalid:
        return {
            "invalid": invalid,
            "granted": [],
            "withheld": [],
            "harness_guarded": [],
        }
    owns = fr_owns_globs(fr_id)
    granted, withheld = dev_owns_grants(owns)
    return {
        "invalid": [],
        "granted": granted,
        "withheld": withheld,
        "harness_guarded": mnt_unwritable_grants(granted),
    }


# ---------------------------------------------------------------------------
# FR-0010: stack-aware Bash grants, `owns:`-derived grants for `rev`/`bkf`
# ---------------------------------------------------------------------------


def detected_stack_tools() -> list[str]:
    """The project's declared stack (FR-0010:AC-1/AC-2), read from
    `REPO_ROOT` — the outer checkout every worktree is cloned from, not the
    per-FR worktree itself. This mirrors `mnt_permission_rules`'s existing
    use of the module-level `REPO_ROOT` for sibling enumeration, and keeps
    `mnt_permissions(fr_id)` / `dev_permissions(fr_id)` at the one-argument
    signature FR-0009's tests already call directly. Reading `REPO_ROOT`
    rather than the worktree is deliberate: grants must come from state a
    human controls, not from something a branch could commit to widen its
    own footprint (DEC-0014 Decision 4).
    """
    return list(stack_profile.detect_stack(REPO_ROOT).tools)


def _stack_warnings() -> list[str]:
    """AC-2's WARN-worthy strings (unrecognised ADR/env entries, or a
    malformed `stack_tools:` shape) for the project's current stack
    detection. Separate from `detected_stack_tools` so a caller that only
    wants the tool list never pays for building warning text it discards."""
    return list(stack_profile.detect_stack(REPO_ROOT).warnings)


def _union_grants(
    perms: dict[str, list[str]], grants: list[str]
) -> dict[str, list[str]]:
    """Union `grants` into `perms["allow"]`, skipping anything already
    present. `perms["deny"]` is returned unchanged — AC-6's mnt-specific
    deny lifting is a separate, narrower step callers apply before this.

    @implements FR-0010:AC-4
    """
    if not grants:
        return perms
    allow = list(perms["allow"])
    allow.extend(g for g in grants if g not in allow)
    return {"allow": allow, "deny": list(perms["deny"])}


# FR-0010:AC-6 — these three `MNT_BASH_DENIES` entries lift exactly when the
# detected stack declares the corresponding tool. Every other entry —
# `Bash(pip *)` in particular (FR-0010 Out of scope) — is unconditional.
MNT_STACK_TOGGLED_DENIES: dict[str, str] = {
    "uv": "Bash(uv *)",
    "node": "Bash(node *)",
    "npx": "Bash(npx *)",
}


def _mnt_bash_denies(tools: list[str]) -> list[str]:
    """`MNT_BASH_DENIES` with the AC-6 toggled entries lifted for a stack
    that declares them. @implements FR-0010:AC-6"""
    lifted = {v for k, v in MNT_STACK_TOGGLED_DENIES.items() if k in tools}
    return [d for d in MNT_BASH_DENIES if d not in lifted]


def _stack_ids_report(tools: list[str]) -> str:
    """`stack=<comma-separated ids>` for a console spawn-report line, or
    `stack=none` when the project declares no stack (FR-0010:AC-7)."""
    return f"stack={','.join(tools) if tools else 'none'}"


def _stack_metrics_segment(tools: list[str]) -> str:
    """`stack=<ids joined by '+'>` — the segment FR-0010:AC-7 appends to the
    `dispatch.spawn` metrics record's `worktree_status`. Tool ids are
    joined by `+` rather than `,` so the segment survives being embedded in
    that field's own comma-delimited segments. Callers append this only
    when `tools` is non-empty (DEC-0003); an empty stack contributes no
    segment at all — never `stack=` with nothing after it."""
    return f"stack={'+'.join(tools)}"


# Closed set of `ensure_dev_venv` failure classifications (FR-0010:AC-9).
# Success spellings (`venv-created`, `venv-reused`, `venv-resynced`, the
# pre-FR `venv reused`) and `fast-forwarded` are deliberately absent: they
# must never produce a `venv=` metrics segment.
_VENV_FAILURE_CLASSIFICATIONS = frozenset(
    {
        "uv-not-found",
        "venv-create-failed",
        "lock-sync-failed",
        "requirements-install-failed",
        "packages-install-failed",
    }
)


def _venv_metrics_segment(wt_status: str) -> str:
    """`venv=<classification>` — the segment FR-0010:AC-9 (DEC-0003) appends
    to the `dispatch.spawn` metrics record's `worktree_status` when venv
    provisioning failed. `wt_status` is the lock file's full status string
    (e.g. `created,venv-created`, `reused,fast-forwarded,lock-sync-failed:
    <stderr>`); each comma-delimited segment is checked against the AC-9
    closed set, ignoring any `:`-suffixed detail, and only the bare
    classification is ever emitted. Returns `""` when no segment matches —
    a successful or reused venv, or a `fast-forwarded` reuse, appends
    nothing."""
    for segment in wt_status.split(","):
        classification = segment.split(":", 1)[0]
        if classification in _VENV_FAILURE_CLASSIFICATIONS:
            return f"venv={classification}"
    return ""


# ---------------------------------------------------------------------------
# FR-0011: stack-aware environment pre-flight for wave/tick/maintain
# ---------------------------------------------------------------------------

# AC-8: the operator override. `--skip-env-preflight` on wave/tick/maintain
# has the same effect; never skips `_gh_preflight`.
ENV_SKIP_PREFLIGHT_VAR = "DISPATCH_SKIP_ENV_PREFLIGHT"


def _env_preflight_skip_requested(cli_flag: bool) -> bool:
    """AC-8: the CLI flag or the env var, either is enough."""
    if cli_flag:
        return True
    return os.environ.get(ENV_SKIP_PREFLIGHT_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _preflight_metrics_segment(findings: list[env_preflight.Finding]) -> str:
    """`preflight=<classes joined by '+'>` (DEC-0003 order: after `stack=`
    and `venv=`) — the segment a `dispatch.spawn` record carries when
    pre-flight produced only warnings and the spawn proceeded. Called with
    warning findings only; a blocking finding never reaches a spawn."""
    classes = sorted({f.cls for f in findings})
    return f"preflight={'+'.join(classes)}" if classes else ""


@dataclasses.dataclass
class EnvPreflightGate:
    """Result of running FR-0011's environment pre-flight once for a
    `wave`/`tick`/`maintain` invocation.

    `blocked` is only ever true in apply mode — AC-9 says a dry-run never
    stops the run, it only labels findings `WOULD-BLOCK`/`WOULD-PREFLIGHT`.
    `metrics_segment` is `""`, `"preflight=<classes>"`, or `"preflight=skipped"`
    — passed to every `spawn_role` call this invocation makes. `wave_drop_note`
    is `[]` unless the skip override was used, in which case it is the one
    `drop_reasons` entry AC-8 requires on the `dispatch.wave` record.
    """

    blocked: bool
    skipped: bool
    findings: list[env_preflight.Finding]
    metrics_segment: str = ""
    wave_drop_note: list[dict] = dataclasses.field(default_factory=list)


def _run_env_preflight(apply: bool, skip: bool) -> EnvPreflightGate:
    """Run (or skip) FR-0011's environment pre-flight once, printing the
    `PREFLIGHT`/`WOULD-PREFLIGHT` report before any worktree, venv, branch,
    lock file or agent process this invocation might create.

    @implements FR-0011:AC-6
    @implements FR-0011:AC-8
    @implements FR-0011:AC-9
    @implements FR-0011:AC-10
    """
    if skip:
        print(
            "  PREFLIGHT SKIPPED   (--skip-env-preflight / DISPATCH_SKIP_ENV_PREFLIGHT)"
        )
        return EnvPreflightGate(
            blocked=False,
            skipped=True,
            findings=[],
            metrics_segment="preflight=skipped",
            wave_drop_note=[
                {"fr_id": None, "phase": "preflight-env", "class": "skipped"}
            ],
        )

    tools = detected_stack_tools()
    result = env_preflight.run_preflight(REPO_ROOT, tools, find_uv=_find_uv)
    findings = list(result.findings)
    blocking = [f for f in findings if f.severity == "block"]
    warn = [f for f in findings if f.severity == "warn"]

    if not findings:
        if tools:
            ran = ", ".join(result.checks_ran) if result.checks_ran else "(none)"
            line = f"  PREFLIGHT OK        ran: {ran}"
        else:
            line = "  PREFLIGHT OK (no stack declared)"
        if result.unresolved_ports:
            line += f"  unresolved ports: {', '.join(result.unresolved_ports)}"
        print(line)
        return EnvPreflightGate(blocked=False, skipped=False, findings=[])

    block_tag = "PREFLIGHT BLOCK" if apply else "WOULD-BLOCK"
    warn_tag = "PREFLIGHT WARN" if apply else "WOULD-PREFLIGHT"
    for f in blocking:
        print(f"  {block_tag}      {f.cls}  resource={f.resource}  remedy={f.remedy}")
    for f in warn:
        print(f"  {warn_tag}   {f.cls}  resource={f.resource}  remedy={f.remedy}")
    if result.unresolved_ports:
        print(
            f"  PREFLIGHT NOTE      unresolved ports: {', '.join(result.unresolved_ports)}"
        )

    metrics_segment = _preflight_metrics_segment(warn) if not blocking else ""
    return EnvPreflightGate(
        blocked=bool(blocking) and apply,
        skipped=False,
        findings=findings,
        metrics_segment=metrics_segment,
    )


def _stack_preflight(fr_id: str, role: str) -> list[str]:
    """Detect the project's stack and print any AC-2 WARN lines (an
    unrecognised ADR/env entry, or a malformed `stack_tools:` shape) before
    the caller's own spawn-report line. Returns the sorted tool ids.

    @implements FR-0010:AC-2
    """
    detection = stack_profile.detect_stack(REPO_ROOT)
    for msg in detection.warnings:
        print(f"  {fr_id}.{role}  WARN — {msg}")
    return list(detection.tools)


def _print_stack_report(fr_id: str, role: str, tools: list[str]) -> None:
    """The `STACK` line AC-7 requires immediately before a spawn's
    WOULD-SPAWN/SPAWNED line: `stack=<ids>` and `stack-grants=<n>`. Kept on
    its own line (rather than appended to the spawn line) so it never
    collides with FR-0009's `owns-grants=<n>` line-ending assertions.

    @implements FR-0010:AC-7
    """
    n = len(stack_profile.stack_bash_grants(tools))
    print(
        f"  {fr_id}.{role}  STACK        {_stack_ids_report(tools)}  stack-grants={n}"
    )


def owns_derived_permissions(
    role: str, base: dict[str, list[str]], fr_id: str, *, anchor: str = ""
) -> dict[str, list[str]]:
    """`rev`/`bkf`'s static grants unioned with the FR's `owns:` footprint,
    exactly as `dev_permissions` does for `dev` — the same granted/withheld/
    harness-guarded split, computed by `dev_owns_derivation` (FR-0009's
    factored-out helper). The role's own static deny list — including any
    path deny that happens to overlap a granted glob (`rev` denies
    `Edit(src/**)`/`Write(src/**)`; `bkf` denies `specs/**`) — is written
    unchanged; the harness resolves deny-over-allow at runtime, so a grant
    the deny list also covers is inert, not a lie the settings file tells.

    `anchor` prefixes the `owns:` grants only (FR-0024 AC-5).

    @implements FR-0010:AC-5
    """
    granted = dev_owns_derivation(fr_id)["granted"]
    return {
        "allow": list(base["allow"])
        + [f"Edit({anchor}{g})" for g in granted]
        + [f"Write({anchor}{g})" for g in granted],
        "deny": list(base["deny"]),
    }


# Cursor's permission syntax has no Bash(...) pattern token; it gates by
# bare command name (`Shell(cmd)`). Same closed vocabulary and same six
# tool ids as `stack_profile.STACK_BASH_GRANTS`, translated.
CURSOR_STACK_SHELL_GRANTS: dict[str, tuple[str, ...]] = {
    "uv": ("Shell(uv)",),
    "node": ("Shell(node)",),
    "npm": ("Shell(npm)",),
    "npx": ("Shell(npx)",),
    "docker": ("Shell(docker)",),
    "alembic": ("Shell(alembic)",),
}


def cursor_stack_grants(tools: list[str]) -> list[str]:
    """Cursor equivalent of `stack_profile.stack_bash_grants`.
    @implements FR-0010:AC-11"""
    out: set[str] = set()
    for tool in tools:
        out.update(CURSOR_STACK_SHELL_GRANTS.get(tool, ()))
    return sorted(out)


# FR-0010:AC-6/AC-11 — Cursor's `mnt` equivalent of `MNT_STACK_TOGGLED_DENIES`.
CURSOR_MNT_STACK_TOGGLED_DENIES: dict[str, str] = {
    "uv": "Shell(uv)",
    "node": "Shell(node)",
    "npx": "Shell(npx)",
}


def cursor_owns_derived_permissions(
    base: dict[str, list[str]], fr_id: str
) -> dict[str, list[str]]:
    """Cursor equivalent of `owns_derived_permissions`: only `Write(...)` is
    emitted (Cursor has no separate edit token), same as Cursor's own
    `dev_permissions`. @implements FR-0010:AC-5 @implements FR-0010:AC-11"""
    granted = dev_owns_derivation(fr_id)["granted"]
    return {
        "allow": list(base["allow"]) + [f"Write({g})" for g in granted],
        "deny": list(base["deny"]),
    }


def _mnt_bash_allow() -> list[str]:
    """Sanctioned Bash grants for `mnt` (see MNT_SANCTIONED_ENTRYPOINTS)."""
    out = [
        f"Bash({interp} {entry}*)"
        for interp in MNT_INTERPRETERS
        for entry in MNT_SANCTIONED_ENTRYPOINTS
    ]
    out.extend(
        [
            "Bash(pytest *)",
            "Bash(pytest)",
            "Bash(ruff *)",
            f"Bash({VENV_DIRNAME}/Scripts/pytest *)",
            f"Bash({VENV_DIRNAME}/Scripts/ruff *)",
            f"Bash({VENV_DIRNAME}/bin/pytest *)",
            f"Bash({VENV_DIRNAME}/bin/ruff *)",
        ]
    )
    return out


_ESCALATION_MARKER = re.compile(r"^##\s+ESCALATION\b", re.MULTILINE)

# A ## FINDINGS block is the NON-BLOCKING sibling of ## ESCALATION: an agent
# surfaces observations worth someone's attention (a spec discrepancy, a
# coverage gap, a doc drift) that must not block or drop, but must not vanish
# either. Unlike an escalation it never changes the run's status. Each finding
# line is `- [scope|spec|doc|slice-miss] <text>`; the tag is optional.
# `[slice-miss]` (FR-0002 AC-7) flags a spec object or file the agent needed
# but its dispatched context did not carry; the dispatcher records it
# structurally (tag, refs, length — never the text) in the metrics log.
_FINDINGS_MARKER = re.compile(r"^##\s+FINDINGS\b", re.MULTILINE)
_FINDING_LINE = re.compile(r"^-\s+(?:\[(scope|spec|doc|slice-miss)\]\s*)?(.+)$")


def _parse_findings(text: str | None) -> list[tuple[str, str]]:
    """Extract (tag, text) findings from a ## FINDINGS block in the agent's
    final message. Returns [] if there is no block. The tag is one of
    scope|spec|doc|slice-miss, or "" when unlabelled; a "(none)" placeholder
    is skipped. @implements FR-0002:AC-7"""
    if not text:
        return []
    m = _FINDINGS_MARKER.search(text)
    if not m:
        return []
    findings: list[tuple[str, str]] = []
    for line in text[m.end():].splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break  # the next h2 heading closes the block
        fm = _FINDING_LINE.match(stripped)
        if not fm:
            continue
        tag = fm.group(1) or ""
        body = fm.group(2).strip()
        if not body or body.lower() == "(none)":
            continue
        findings.append((tag, body))
    return findings


def _collect_findings(results: list["WaveFRResult"]) -> list[tuple[str, str, str, str]]:
    """Flatten (fr_id, phase, tag, text) findings across a wave's results."""
    rows: list[tuple[str, str, str, str]] = []
    for r in results:
        for phase, outcome in (("dev", r.dev_outcome), ("rev", r.rev_outcome)):
            if not outcome:
                continue
            for tag, body in outcome.findings:
                rows.append((r.fr_id, phase, tag, body))
    return rows


@dataclasses.dataclass
class AgentOutcome:
    """Structured evaluation of a completed agent run."""

    status: str  # "success" | "error" | "escalation" | "timeout" | "no-log"
    summary: str
    verdict: str | None = None  # rev-only: "approve" | "request-changes" | "comment"
    # Non-blocking observations from a ## FINDINGS block. Independent of status.
    findings: list[tuple[str, str]] = dataclasses.field(default_factory=list)


def _wait_for_phase(
    targets: list[tuple[str, str]],
    poll_interval: float,
    phase_timeout: float,
) -> dict[str, str]:
    """Poll until all (fr_id, role) locks are no longer held or timeout fires.

    Returns {fr_id: "completed" | "timeout"} for each target.
    """
    results: dict[str, str] = {}
    pending = list(targets)
    deadline = time.monotonic() + phase_timeout

    while pending and time.monotonic() < deadline:
        still_pending: list[tuple[str, str]] = []
        for fr_id, role in pending:
            state, _ = lock_state(fr_id, role)
            if state == "held":
                still_pending.append((fr_id, role))
            else:
                results[fr_id] = "completed"
        pending = still_pending
        if pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, remaining))

    for fr_id, role in pending:
        state, data = lock_state(fr_id, role)
        if state == "held":
            pid = int((data or {}).get("pid", 0))
            if pid:
                kill_pid(pid)
                lock_path(fr_id, role).unlink(missing_ok=True)
                print(f"  {fr_id}.{role}  TIMEOUT — killed pid={pid}")
        results[fr_id] = "timeout"

    return results


def _evaluate_agent_outcome(
    fr_id: str,
    role: str,
    adapter: HarnessAdapter,
) -> AgentOutcome:
    """Parse the agent's NDJSON log and return a structured outcome. Every
    evaluation also appends the run's `dispatch.run` metrics record
    (FR-0002 AC-3); the outcome itself is unchanged by that."""
    log_path = DISPATCH_DIR / f"{fr_id}.{role}.log"
    if not log_path.exists():
        _emit_dispatch_run(fr_id, role, "no-log", None)
        return AgentOutcome(status="no-log", summary="no log file found")

    summary = adapter.parse_log(log_path)
    # Findings are non-blocking, so they ride along on whatever outcome we
    # return — success, error, or escalation alike — never altering the status.
    findings = _parse_findings(summary.last_text)

    if summary.is_error:
        detail = summary.result_subtype or "unknown error"
        outcome = AgentOutcome(status="error", summary=f"agent error: {detail}", findings=findings)
    elif summary.last_text and _ESCALATION_MARKER.search(summary.last_text):
        outcome = AgentOutcome(
            status="escalation", summary="agent emitted ESCALATION block", findings=findings
        )
    elif role == "rev":
        verdict, _ = _extract_review_verdict(summary.last_text)
        outcome = AgentOutcome(
            status="success", summary="reviewer completed", verdict=verdict, findings=findings
        )
    else:
        outcome = AgentOutcome(status="success", summary="agent completed successfully", findings=findings)

    _emit_dispatch_run(fr_id, role, outcome.status, summary, outcome.verdict, findings)
    return outcome



@dataclasses.dataclass
class WaveFRResult:
    """Per-FR outcome tracked through the wave pipeline."""

    fr_id: str
    dev_outcome: AgentOutcome | None = None
    dev_finalize_ok: bool = False
    pr_number: int | None = None
    pr_url: str | None = None
    rev_outcome: AgentOutcome | None = None
    rev_finalize_ok: bool = False
    rev_verdict: str | None = None
    dropped_at: str | None = None
    drop_reason: str | None = None
    # Multi-round bookkeeping. `rounds_ran` counts completed Dev->Reviewer
    # cycles (round 1 is the base pipeline); `round_verdicts` holds one verdict
    # per completed round in order; `force_escalated` is set when the budget was
    # exhausted without an approval.
    rounds_ran: int = 1
    round_verdicts: list[str] = dataclasses.field(default_factory=list)
    force_escalated: bool = False
    # @implements FR-0008:AC-5, FR-0008:AC-7 — `gate_result` is one of
    # `pending` (human gate, wave stops), `blocked` (architect gate
    # `changes-requested`), `stale` (AC-2's `stale` status), or None
    # (no unsatisfied `after: dev` gate). `gate_note` is the one-line detail
    # printed on the corresponding wave-outcome line. Distinct from
    # `dropped_at`/`drop_reason`: a gate outcome is a per-FR result, never a
    # failure and never an escalation.
    gate_result: str | None = None
    gate_note: str | None = None

    @property
    def completed_e2e(self) -> bool:
        return self.dev_finalize_ok and self.rev_finalize_ok


def _wave_exit_code(results: list[WaveFRResult], any_dropped: bool) -> int:
    """Decide a wave's exit code from its per-FR results so far.

    # @implements FR-0008:AC-5, FR-0008:AC-7 — a gated FR (human
    # GATE-PENDING, or an architect gate that finalized `changes-
    # requested`/`stale`) takes exit code 3, independent of which phase
    # (or early return) the wave stops at — distinct from a dropped FR's 1
    # and a clean wave's 0. Callers at every wave exit point (Phase 4's two
    # early returns and the normal end-of-wave path) go through this one
    # function so the decision cannot drift out of sync with how the wave
    # happened to end."""
    if any(r.gate_result for r in results):
        return 3
    return 1 if any_dropped and not any(r.completed_e2e for r in results) else 0


def _write_wave_synthesis(
    results: list[WaveFRResult],
    started_at: str,
    elapsed_s: float,
    emit_record: bool = False,
    extra_drop_reasons: list[dict] | None = None,
) -> Path:
    """Write a synthesis report to stdout and _dispatch/wave-<timestamp>.md.
    With `emit_record` (apply mode only) also append the `dispatch.wave`
    metrics record (FR-0002 AC-3); the report is unchanged by it.
    `extra_drop_reasons` (FR-0011:AC-8) appends the wave's
    `EnvPreflightGate.wave_drop_note` to the record's `drop_reasons` — `[]`
    unless `--skip-env-preflight` was used for this wave."""
    # A rework FR finalized both legs in round 1, so completed_e2e
    # stays True even if a later round dropped mechanically — exclude dropped
    # from "completed" so the drop is not masked.
    completed = [r for r in results if r.completed_e2e and not r.dropped_at]
    dropped = [r for r in results if r.dropped_at]
    # @implements FR-0008:AC-5, FR-0008:AC-7 — a gated FR is its own per-FR
    # result bucket: not a failure (`dropped`), not merely "reviewer pending"
    # (`dev_only`).
    gated = [r for r in results if r.gate_result and not r.dropped_at]
    dev_only = [
        r
        for r in results
        if r.dev_finalize_ok
        and not r.rev_finalize_ok
        and not r.dropped_at
        and not r.gate_result
    ]
    escalations = [r for r in results if r.dev_outcome and r.dev_outcome.status == "escalation"
                   or r.rev_outcome and r.rev_outcome.status == "escalation"]
    force_escalated = [r for r in results if r.force_escalated]

    lines: list[str] = []
    lines.append(f"# Wave Synthesis — {started_at}")
    lines.append("")
    lines.append("## Summary")
    gated_note = f" {len(gated)} gated (pending/blocked/stale)." if gated else ""
    lines.append(
        f"Processed {len(results)} FR(s). "
        f"{len(completed)} completed end-to-end. "
        f"{len(dev_only)} dev-only (reviewer pending/dropped). "
        f"{len(dropped)} dropped.{gated_note} "
        f"Elapsed: {_fmt_secs(elapsed_s)}."
    )
    lines.append("")
    lines.append("## Per-FR Results")
    for r in results:
        # AC-9: a multi-round run is auditable — record how many rounds ran and
        # each round's verdict. Kept off single-round lines to preserve today's
        # output exactly when --rounds is 1.
        rounds_note = ""
        if r.rounds_ran > 1 or len(r.round_verdicts) > 1:
            rounds_note = (
                f", rounds: {r.rounds_ran}, verdicts: [{', '.join(r.round_verdicts)}]"
            )
        if r.dropped_at:
            lines.append(f"- {r.fr_id}: DROPPED at {r.dropped_at} ({r.drop_reason}){rounds_note}")
        elif r.gate_result:
            # @implements FR-0008:AC-5, FR-0008:AC-7
            lines.append(
                f"- {r.fr_id}: GATE-{r.gate_result.upper()} ({r.gate_note}){rounds_note}"
            )
        elif r.completed_e2e:
            verdict_note = f", reviewer: {r.rev_verdict}" if r.rev_verdict else ""
            escalate_note = " [FORCE-ESCALATE: budget exhausted]" if r.force_escalated else ""
            pr_ref = f"PR #{r.pr_number}" if r.pr_number else "PR opened"
            lines.append(f"- {r.fr_id}: {pr_ref} (draft){verdict_note}{rounds_note}{escalate_note}")
        elif r.dev_finalize_ok:
            pr_ref = f"PR #{r.pr_number}" if r.pr_number else "PR opened"
            lines.append(f"- {r.fr_id}: {pr_ref} (draft), reviewer phase incomplete")
        else:
            lines.append(f"- {r.fr_id}: incomplete (dev not finalized)")
    lines.append("")

    # AC-2 / AC-9: budget-exhaustion force-escalations are their own section so
    # the human sees them without reading per-FR lines.
    if force_escalated:
        lines.append("## Force Escalations (budget exhausted)")
        for r in force_escalated:
            lines.append(
                f"- {r.fr_id}: {r.rounds_ran} Dev<->Reviewer cycle(s) ran, "
                f"last verdict request-changes — escalate to a human "
                f"(verdicts: [{', '.join(r.round_verdicts)}])"
            )
        lines.append("")

    if escalations:
        lines.append("## Open Escalations")
        for r in escalations:
            phase = "dev" if r.dev_outcome and r.dev_outcome.status == "escalation" else "rev"
            lines.append(f"- {r.fr_id}: escalation during {phase} (see _dispatch/{r.fr_id}.{phase}.log)")
    else:
        lines.append("## Open Escalations")
        lines.append("(none)")
    lines.append("")

    # Findings — non-blocking observations agents surfaced (## FINDINGS). Always
    # rendered so a finding is never a silent drop; separate from escalations
    # because it neither blocks nor demands a decision before the wave proceeds.
    finding_rows = _collect_findings(results)
    lines.append("## Findings")
    if finding_rows:
        for fr_id, phase, tag, body in finding_rows:
            tag_note = f"[{tag}] " if tag else ""
            lines.append(f"- {fr_id} ({phase}): {tag_note}{body}")
    else:
        lines.append("(none)")
    lines.append("")

    next_steps: list[str] = []
    mergeable = [r for r in completed if r.rev_verdict == "approve"]
    reviewable = [r for r in completed if r.rev_verdict != "approve"]
    if mergeable:
        prs = ", ".join(f"PR #{r.pr_number}" for r in mergeable if r.pr_number)
        next_steps.append(f"- Review and merge: {prs}")
    if reviewable:
        prs = ", ".join(f"PR #{r.pr_number}" for r in reviewable if r.pr_number)
        next_steps.append(f"- Address reviewer feedback: {prs}")
    if dev_only:
        ids = ", ".join(r.fr_id for r in dev_only)
        next_steps.append(f"- Reviewer phase pending: {ids}")
    for r in dropped:
        phase = r.dropped_at or "unknown"
        next_steps.append(f"- Investigate: {r.fr_id} dropped at {phase} (see _dispatch/{r.fr_id}.*.log)")

    if next_steps:
        lines.append("## Next Steps")
        lines.extend(next_steps)
    lines.append("")

    report = "\n".join(lines)
    print()
    print("=" * 60)
    for line in lines:
        print(line)
    print("=" * 60)

    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = started_at.replace(":", "-")
    report_path = DISPATCH_DIR / f"wave-{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nSynthesis written to {report_path}")
    if emit_record:
        # @implements FR-0002:AC-3 (wave record: counts, phases, rounds — no prose)
        _metrics_emit(
            "dispatch.wave",
            role="orchestrator",
            object_ids=[r.fr_id for r in results],
            run_id=None,
            fr_count=len(results),
            completed=len(completed),
            dev_only=len(dev_only),
            dropped=len(dropped),
            drop_reasons=[{"fr_id": r.fr_id, "phase": r.dropped_at} for r in dropped]
            + list(extra_drop_reasons or []),
            rounds_ran={r.fr_id: r.rounds_ran for r in results},
            force_escalated=[r.fr_id for r in force_escalated],
        )
    return report_path


# ---------------------------------------------------------------------------
# Wave rework loop: re-dispatch the Developer on a request-changes
# verdict, up to the CLAUDE.md iteration budget.
# ---------------------------------------------------------------------------


def _dev_worktree(fr_id: str) -> Path:
    """The dev worktree's root (create / merge / remove happen here)."""
    return REPO_ROOT / ".claude" / "worktrees" / f"dev-{fr_id}"


def _worktree_python(wt_path: Path) -> str:
    """The worktree's dispatch venv interpreter if present, else sys.executable.

    The venv carries the test dependencies `ensure_dev_venv` provisioned; the
    dispatcher's own interpreter may not.
    """
    for rel in (
        f"{VENV_DIRNAME}/Scripts/python.exe",
        f"{VENV_DIRNAME}/Scripts/python",
        f"{VENV_DIRNAME}/bin/python",
    ):
        cand = wt_path / rel
        if cand.exists():
            return str(cand)
    return sys.executable


_PYTEST_FAIL_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def _parse_failing_tests(pytest_output: str | None) -> list[str]:
    """Failing/erroring test node ids from a `pytest -rfE` summary, in order.

    Reads the machine-stable `FAILED <nodeid>` / `ERROR <nodeid>` summary lines,
    not human prose, so a brief names real tests rather than a paraphrase.
    De-duplicated, order-preserving.
    """
    seen: list[str] = []
    for m in _PYTEST_FAIL_RE.finditer(pytest_output or ""):
        node = m.group(1)
        if node not in seen:
            seen.append(node)
    return seen


# @implements FR-0016:AC-1, FR-0016:AC-3
def _collect_failing_tests(wt_path: Path, timeout_s: float = 900) -> list[str]:
    """Run the worktree's suite and return failing test node ids.

    The dev worktree, synced with the Reviewer's committed tests, is the ground
    truth for "what the Developer must make pass". A crash or
    timeout yields an empty list; the brief still carries the verdict text.
    """
    py = _worktree_python(wt_path)
    try:
        proc = subprocess.run(
            [py, "-m", "pytest", "-q", "--no-header", "--tb=no", "-rfE",
             "-p", "no:cacheprovider"],
            cwd=str(wt_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return _parse_failing_tests((proc.stdout or "") + "\n" + (proc.stderr or ""))


def _read_review_md_on_branch(fr_id: str) -> str | None:
    """The newest filed review on the Reviewer's branch — the library file
    `specs/_reviews/<FR>-r<N>.md` with the highest N — or None.

    Never the root `REVIEW.md` (the Reviewer's unfiled handoff, or a legacy
    one inherited from `main`), and never another FR's round (FR-0025 AC-2).
    Decoded as UTF-8 explicitly — the encoding `_materialise_review_md`
    writes and the Reviewer's editors use — never the host locale codec
    (`text=True` alone decodes with it, mojibaking multi-byte characters
    on Windows). FR-0013 AC-2 (DEC-0009 folded finding).
    @implements FR-0016:AC-1
    @implements FR-0025:AC-2
    """
    branch = _branch_for(fr_id, "rev")
    newest = _newest_review_on_branch(fr_id)
    if newest is None:
        return None
    # @implements FR-0024:AC-3 — `newest[1]` is project-relative (the
    # library listing runs in `REPO_ROOT`); the object read names
    # `<prefix><path>`, never a repository-top `specs/_reviews/` file.
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{branch}:{_repo_path(newest[1])}"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _reviewer_final_text(fr_id: str, adapter: HarnessAdapter) -> str:
    """The Reviewer's full final message, for quoting in a rework brief.

    Prefers the parsed reviewer log; falls back to the newest filed review
    (FR-0025 AC-2).
    """
    log_path = DISPATCH_DIR / f"{fr_id}.rev.log"
    if log_path.exists():
        text = adapter.parse_log(log_path).last_text
        if text:
            return text
    return _read_review_md_on_branch(fr_id) or ""


def _resolve_rework_verdict(fr_id: str, log_verdict: str | None) -> str:
    """The verdict that drives the loop, from the Reviewer's own artifacts.

    Never GitHub's `reviewDecision`. Prefer the verdict the
    dispatcher already extracts from the parsed reviewer log (the same
    `_extract_review_verdict` used to choose the `gh pr review` flag); when that
    is inconclusive ("comment"), fall back to the newest filed review
    (`specs/_reviews/<FR>-r<N>.md`, FR-0025 AC-2) and run the identical
    extraction over it. A request-changes that had to be posted
    via the own-PR `--comment` fallback still resolves to request-changes here,
    because the source is the reviewer's text — not how GitHub recorded it.

    """
    if log_verdict in ("approve", "request-changes"):
        return log_verdict
    review_text = _read_review_md_on_branch(fr_id)
    if review_text:
        verdict, _ = _extract_review_verdict(review_text)
        return verdict
    return log_verdict or "comment"


def _generate_rework_brief(
    *,
    fr_id: str,
    fr_title: str | None,
    round_num: int,
    budget: int,
    verdict_text: str,
    failing_tests: list[str],
    owns: list[str],
    review_path: str | None = None,
) -> str:
    """A generated round-2+ Developer rework brief.

    `review_path` is the newest filed review the rework sync brought into
    the worktree (FR-0025 AC-3); the fallback line names it.

    Carries the FR id + title, the round number against the budget, the
    Reviewer's verdict text, the failing test names, and the FR's `owns:`
    footprint verbatim as the authoritative permitted write surface. It does
    NOT narrow the footprint and does NOT name a file as the place a fix
    belongs — scoping within `owns` is the Developer's judgement. Naming a file
    the failing assertion never reads is the error this generated brief
    exists to prevent.

    """
    title = fr_title or fr_id
    lines: list[str] = []
    lines.append(f"# Rework brief — {fr_id}: {title}")
    lines.append("")
    lines.append(
        f"This is Dev<->Reviewer round {round_num} of a budget of {budget} "
        f"(CLAUDE.md). The Reviewer requested changes on the previous round. "
        f"Address the review, commit on the current branch, and refresh "
        f"PR_BODY.md."
    )
    lines.append("")
    lines.append("## Reviewer verdict")
    lines.append("")
    lines.append((verdict_text or "(no verdict text captured)").strip())
    lines.append("")
    lines.append("## Failing tests")
    lines.append("")
    if failing_tests:
        for node in failing_tests:
            lines.append(f"- `{node}`")
    else:
        review = review_path or f"{REVIEWS_DIR_REL}/{fr_id}-r<N>.md (newest N)"
        lines.append(
            "- (none captured mechanically — read the Reviewer verdict above "
            f"and `{review}` in your worktree)"
        )
    lines.append("")
    lines.append("## Permitted write footprint")
    lines.append("")
    lines.append(
        "These are the paths this FR declares in `owns:`. This is your "
        "authoritative and complete permitted write footprint — no narrower, "
        "no wider. Choosing which of these to change to satisfy the review is "
        "your judgement; this brief does not prescribe a file."
    )
    lines.append("")
    if owns:
        for glob in owns:
            lines.append(f"- `{glob}`")
    else:
        lines.append(
            "- (the FR declares no `owns:` — do not write code; escalate, as "
            "there is no permitted footprint)"
        )
    lines.append("")
    return "\n".join(lines)


def _write_rework_brief(wt_path: Path, fr_id: str, round_num: int, text: str) -> str:
    """Write the generated brief into the worktree and return its rel path."""
    brief_dir = wt_path / "_dispatch"
    brief_dir.mkdir(parents=True, exist_ok=True)
    rel = f"_dispatch/round{round_num}-{fr_id}-dev.md"
    (wt_path / rel).write_text(text, encoding="utf-8")
    return rel


def _covers_tests_present(wt_path: Path) -> bool:
    """True iff any file under the worktree's tests/ carries an @covers tag."""
    tests_dir = wt_path / "tests"
    if not tests_dir.is_dir():
        return False
    for path in tests_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@covers" in text:
            return True
    return False


# @implements FR-0016:AC-1
def _prepare_dev_worktree_for_rework(fr_id: str) -> tuple[bool, str]:
    """Sync the Reviewer's committed work into the dev worktree and verify it.

    Before a rework round starts, the newest filed review
    (`specs/_reviews/<FR>-r<N>.md`, the file `_read_review_md_on_branch`
    returns) and the @covers test files must be present in the Developer's
    worktree, or the round does not start. Finalize files the review onto
    `claude/rev-<FR>` (branched off the dev branch); merging that branch into
    the dev worktree is what puts them in front of the Developer. The library
    file must be that branch's blob byte for byte; a root `REVIEW.md` alone
    does not count (FR-0025 AC-3). A failed merge or a missing artifact is a
    mechanical failure that stops the round without consuming a budget round.

    @implements FR-0025:AC-3
    """
    dev_wt = _dev_worktree(fr_id)
    if not dev_wt.exists():
        return (False, f"dev worktree missing at {dev_wt}")
    rev_branch = _branch_for(fr_id, "rev")
    if not _git_branch_exists(rev_branch):
        return (False, f"reviewer branch {rev_branch} does not exist — no review to sync")
    merge = subprocess.run(
        ["git", "-C", str(dev_wt), "merge", rev_branch, "--no-edit",
         "-m", f"merge {rev_branch} into dev worktree (rework sync)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if merge.returncode != 0:
        # Abort a half-applied merge so the worktree is left usable.
        subprocess.run(
            ["git", "-C", str(dev_wt), "merge", "--abort"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        err = (merge.stderr or merge.stdout or "merge failed").strip()[:200]
        return (False, f"could not merge {rev_branch} into dev worktree: {err}")
    newest = _newest_review_on_branch(fr_id)
    if newest is None:
        return (
            False,
            f"no review filed at {REVIEWS_DIR_REL}/{fr_id}-r<N>.md on {rev_branch}; "
            "nothing for the dev worktree to carry",
        )
    _n, review_path, review_blob = newest
    # @implements FR-0024:AC-2 — the review and `tests/` are the project's,
    # inside the worktree; `review_path` is project-relative.
    dev_project = _worktree_project_root(dev_wt)
    if not _working_file_holds_blob(review_path, review_blob, dev_project):
        return (False, f"{review_path} not present in dev worktree after sync")
    if not _covers_tests_present(dev_project):
        return (False, "no @covers test files present in dev worktree after sync")
    return (True, f"synced {rev_branch} ({review_path} + @covers tests present)")


def _run_one_rework_round(
    fr_id: str,
    round_num: int,
    budget: int,
    verdict_text: str,
    draft: bool,
    adapter: HarnessAdapter,
    phase_timeout: float,
    poll_interval: float,
    preflight_segment: str = "",
) -> tuple[str | None, str]:
    """Run a single Dev->Reviewer rework cycle for one FR.

    Returns `(verdict, note)`. `verdict` is the Reviewer's resolved verdict when
    the round completed end-to-end; it is None on a mechanical failure (AC-7
    precondition, spawn/monitor/finalize error, timeout), which stops the FR
    without consuming a budget round.
    """
    ok, prep_note = _prepare_dev_worktree_for_rework(fr_id)
    if not ok:
        return (None, f"precondition: {prep_note}")

    # @implements FR-0024:AC-2 — pytest, the venv and the rework brief are
    # the project's, inside the worktree.
    dev_wt = _worktree_project_root(_dev_worktree(fr_id))
    failing = _collect_failing_tests(dev_wt)
    # @implements FR-0025:AC-3 — the brief and the prompt name the filed
    # review the precondition just checked, not the root REVIEW.md.
    newest = _newest_review_on_branch(fr_id)
    review_path = newest[1] if newest is not None else None
    brief = _generate_rework_brief(
        fr_id=fr_id,
        fr_title=_fr_title(fr_id),
        round_num=round_num,
        budget=budget,
        verdict_text=verdict_text,
        failing_tests=failing,
        owns=fr_owns_globs(fr_id),
        review_path=review_path,
    )
    rel = _write_rework_brief(dev_wt, fr_id, round_num, brief)
    review_ref = review_path or f"{REVIEWS_DIR_REL}/{fr_id}-r<N>.md (newest N)"
    extra = (
        f"You are in Dev<->Reviewer rework round {round_num} of {budget}. "
        f"A generated rework brief is at `{rel}` in this worktree: read it "
        f"first. It carries the Reviewer's verdict, the failing tests, and your "
        f"authoritative permitted write footprint (the FR's `owns:`). The "
        f"Reviewer's tests and its review, `{review_ref}`, are already in this "
        f"worktree."
    )

    # Developer rework leg
    result, _pid, _wt = spawn_role(
        fr_id,
        "dev",
        apply=True,
        adapter=adapter,
        extra_prompt=extra,
        round_num=round_num,
        **_spawn_extra_kwargs(preflight_segment),
    )
    if result != "spawned":
        return (None, f"dev re-dispatch failed: {result}")
    poll = _wait_for_phase([(fr_id, "dev")], poll_interval, phase_timeout)
    if poll.get(fr_id) == "timeout":
        _emit_dispatch_run(fr_id, "dev", "timeout", None)
        return (None, "dev rework timed out")
    dev_outcome = _evaluate_agent_outcome(fr_id, "dev", adapter)
    if dev_outcome.status != "success":
        return (None, f"dev rework did not complete: {dev_outcome.summary}")
    if cmd_finalize(fr_id, "dev", apply=True, draft=draft, adapter=adapter) != 0:
        return (None, "dev rework finalize failed")

    # Reviewer re-review leg. The reused Reviewer worktree is fast-forwarded
    # onto the Developer's new tip inside `ensure_role_worktree`; a sync that
    # cannot fast-forward is a precondition failure of this round, not a
    # verdict, so it stops the FR without consuming a budget round.
    # @implements FR-0006:AC-11
    plan, plan_detail = _rev_sync_plan(fr_id)
    if plan == "diverged":
        return (None, f"precondition: {plan_detail}")
    rev_wt = _role_worktree_path(fr_id, "rev")
    if plan == "fast-forward" and rev_wt.exists():
        dirty = _rev_worktree_dirty_paths(rev_wt)
        if dirty:
            note = (
                f"precondition: Reviewer worktree {rev_wt} has uncommitted tracked "
                f"changes ({', '.join(dirty[:10])}); cannot fast-forward for re-review"
            )
            return (None, note)
    result, _pid, _wt = spawn_role(
        fr_id,
        "rev",
        apply=True,
        adapter=adapter,
        round_num=round_num,
        **_spawn_extra_kwargs(preflight_segment),
    )
    if result != "spawned":
        return (None, f"precondition: reviewer re-dispatch failed: {result}")
    poll = _wait_for_phase([(fr_id, "rev")], poll_interval, phase_timeout)
    if poll.get(fr_id) == "timeout":
        _emit_dispatch_run(fr_id, "rev", "timeout", None)
        return (None, "reviewer re-review timed out")
    rev_outcome = _evaluate_agent_outcome(fr_id, "rev", adapter)
    if rev_outcome.status != "success":
        return (None, f"reviewer re-review did not complete: {rev_outcome.summary}")
    # @implements FR-0014:AC-2
    if cmd_finalize(fr_id, "rev", apply=True, draft=draft, adapter=adapter) != 0:
        return (None, "reviewer re-review finalize failed")

    verdict = _resolve_rework_verdict(fr_id, rev_outcome.verdict)
    return (verdict, "round completed")


def _run_rework_rounds(
    results_by_id: dict[str, WaveFRResult],
    rounds: int,
    draft: bool,
    adapter: HarnessAdapter,
    phase_timeout: float,
    poll_interval: float,
    preflight_segment: str = "",
) -> None:
    """Drive rounds 2..N for every FR whose round-1 verdict was request-changes.

    Re-dispatch Dev then Reviewer while the verdict stays
    request-changes and budget remains. Exhausting the budget without an
    approval flags a force-escalation and does not start a further round.
    """
    for fr_id, r in results_by_id.items():
        if r.rev_verdict != "request-changes" or r.dropped_at:
            continue
        while r.rounds_ran < rounds:
            round_num = r.rounds_ran + 1
            # @implements FR-0014:AC-5
            print(f"  {fr_id}  REWORK round {round_num}/{rounds} — "
                  f"reviewer requested changes", flush=True)
            verdict_text = _reviewer_final_text(fr_id, adapter)
            new_verdict, note = _run_one_rework_round(
                fr_id,
                round_num,
                rounds,
                verdict_text,
                draft,
                adapter,
                phase_timeout,
                poll_interval,
                preflight_segment=preflight_segment,
            )
            if new_verdict is None:
                # Mechanical / precondition failure: stop the FR, do not consume
                # a budget round (open-question default).
                r.dropped_at = f"rework-round-{round_num}"
                r.drop_reason = note
                print(f"  {fr_id}  REWORK STOPPED — {note}", flush=True)
                break
            r.rounds_ran = round_num
            r.round_verdicts.append(new_verdict)
            r.rev_verdict = new_verdict
            print(
                f"  {fr_id}  REWORK round {round_num} verdict={new_verdict}", flush=True
            )
            if new_verdict == "approve":
                break
            if new_verdict != "request-changes":
                # Inconclusive ("comment"): the loop only re-drives on an
                # explicit request-changes. Leave it for a human.
                break
        if (
            r.rev_verdict == "request-changes"
            and r.rounds_ran >= rounds
            and not r.dropped_at
        ):
            r.force_escalated = True
            print(f"  {fr_id}  FORCE-ESCALATE — {rounds} Dev<->Reviewer cycle(s) "
                  f"exhausted without approval; escalate to a human")


def _find_hub_root(start: Path) -> Path | None:
    """Locate the workspace hub (which owns scripts/parking.py) from a project.

    Projects nested under <hub>/projects/<name>/ resolve by walking up. Projects
    registered out-of-tree (see hub/projects.yaml) are not under the hub, so the
    walk fails — set DISPATCH_HUB_ROOT to the hub root in that case."""
    env = os.environ.get("DISPATCH_HUB_ROOT")
    if env:
        p = Path(env).expanduser()
        if (p / "scripts" / "parking.py").exists():
            return p
    for parent in [start, *start.parents]:
        if (parent / "scripts" / "parking.py").exists() and (parent / "parking-lot").is_dir():
            return parent
    return None


def _park_findings(rows: list[tuple[str, str, str, str]], started_at: str) -> None:
    """Append each wave finding to the hub parking lot via `parking.py add`.

    Serial by contract: the hub CRUD scripts read-mutate-rewrite shared indexes
    and must never run concurrently, so findings are parked one at a time from
    this single post-wave process. If the hub can't be located the findings stay
    in the wave synthesis (never dropped) and nothing is parked."""
    if not rows:
        print("No findings to park.")
        return
    hub_root = _find_hub_root(REPO_ROOT)
    if hub_root is None:
        print(
            "WARN: --park-findings: could not locate the hub parking lot. Set "
            "DISPATCH_HUB_ROOT to the hub root. Findings remain in the wave "
            "synthesis; none were parked.",
            file=sys.stderr,
        )
        return
    parking = hub_root / "scripts" / "parking.py"
    parked = 0
    for fr_id, phase, tag, body in rows:
        title = body if len(body) <= 80 else body[:77] + "..."
        tags = ",".join(t for t in (tag, "finding") if t)
        cmd = [
            sys.executable, str(parking), "add", title,
            "--tags", tags,
            "--context", f"dispatch wave {started_at} — {fr_id} ({phase})",
            "--value", "(surfaced by a dispatched agent; triage before promote)",
        ]
        try:
            subprocess.run(cmd, cwd=str(hub_root), check=True)
            parked += 1
        except subprocess.CalledProcessError as e:
            print(f"WARN: failed to park finding for {fr_id}: {e}", file=sys.stderr)
    print(f"Parked {parked}/{len(rows)} finding(s) into {hub_root / 'parking-lot'}.")


# @implements FR-0014:AC-3, FR-0014:AC-4
# Maps the `current_phase` slug tracked through `cmd_wave`'s Phase 1..6 /
# rework / synthesis body to the human-readable phase name used in the
# `CRASHED — <phase name>: ...` line. Slugs match the existing
# `WaveFRResult.dropped_at` vocabulary so a crash reuses the same
# terminology a normal drop already uses (e.g. "rev-evaluate" both here
# and in Phase 6's per-FR drop handling); `<slug>-crash` is what AC-4
# writes to `dropped_at` for FRs still in flight when the crash happened.
_WAVE_PHASE_NAMES: dict[str, str] = {
    "dev-tick": "Phase 1: Dev Tick",
    "dev-monitor": "Phase 2: Dev Monitor",
    "dev-evaluate": "Phase 3: Dev Evaluate + Finalize",
    "dev-finalize": "Phase 3: Dev Evaluate + Finalize",
    "gate-check": "Phase 3.5: Gate check",
    "rev-tick": "Phase 4: Rev Tick",
    "rev-monitor": "Phase 5: Rev Monitor",
    "rev-evaluate": "Phase 6: Rev Evaluate + Finalize",
    "rev-finalize": "Phase 6: Rev Evaluate + Finalize",
    "synthesis": "Synthesis",
}


def cmd_wave(
    apply: bool,
    adapter: HarnessAdapter,
    draft: bool = True,
    timeout: float = 7200,
    phase_timeout: float = 3600,
    poll_interval: float = 30,
    fr_filter: list[str] | None = None,
    rounds: int = 2,
    park_findings: bool = False,
    skip_env_preflight: bool = False,
) -> int:
    """Autonomous dispatch-to-PR pipeline.

    Chains: pre-flight -> dev tick -> dev monitor -> dev evaluate/finalize
    -> rev tick -> rev monitor -> rev evaluate/finalize -> synthesis.

    In dry-run mode (apply=False), previews what each phase would do
    without spawning agents, pushing branches, or touching GitHub.


    `fr_filter` restricts Phase 1's dev selection; every later phase derives
    its own worklist from that set (`results_by_id`, `dev_finalized`), so the
    filter propagates through monitor, finalize, rev tick and synthesis without
    per-phase re-filtering. None preserves the unfiltered behaviour exactly.

    `rounds` is the Dev<->Reviewer iteration budget for this wave.
    Defaults to 2 (FR-0013 AC-8): one automatic rework round on a
    request-changes verdict, inside the 3-cycle budget CLAUDE.md already
    allows. `--rounds 1` reproduces the original single-pass behaviour
    exactly. Values up to REVIEW_CYCLE_BUDGET re-dispatch the Developer on
    a request-changes verdict; a request beyond the budget is rejected
    rather than clamped.

    """
    # @implements FR-0013:AC-8
    if rounds < 1 or rounds > REVIEW_CYCLE_BUDGET:
        print(
            f"Wave aborted: --rounds {rounds} is out of range. The Dev<->Reviewer "
            f"budget is {REVIEW_CYCLE_BUDGET} cycles (CLAUDE.md); pass a value "
            f"between 1 and {REVIEW_CYCLE_BUDGET}."
        )
        return 2

    wave_start = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    print(f"Wave started at {started_at} ({'APPLY' if apply else 'dry-run'}, "
          f"harness={adapter.name}, draft={draft}, rounds={rounds})")
    print(f"Timeouts: total={_fmt_secs(timeout)}, phase={_fmt_secs(phase_timeout)}, "
          f"poll={poll_interval}s")
    print()

    # ------------------------------------------------------------------
    # Phase 0: Pre-flight
    # ------------------------------------------------------------------
    # @implements FR-0014:AC-5
    print("--- Phase 0: Pre-flight ---", flush=True)

    # @implements FR-0024:AC-6 — before the gh preflight, any prune,
    # reconcile, worktree or spawn; the synthesis is still written (FR-0014).
    layout_err = _layout_refusal()
    if layout_err is not None:
        print(f"ERROR: {layout_err}")
        _write_wave_synthesis(
            [], started_at, time.monotonic() - wave_start, emit_record=apply
        )
        return 1

    ok, err = _gh_preflight(verbose=False)
    if not ok:
        print(f"Wave aborted: GitHub integration required ({err})")
        print(GH_AUTH_PREFLIGHT_HINT)
        return 1

    pruned = prune_dead_locks(verbose=False)
    if pruned:
        print(f"Auto-pruned {pruned} dead lock(s).")

    # @implements FR-0013:AC-7 — FRs whose PR merged during this run's
    # reconcile step, so a dependent FR's dev finalize auto-revalidates
    # (default behind `--revalidate` for the bare `finalize` command;
    # automatic here per the Open question's default).
    merged_this_run: set[str] = set()
    if apply:
        recon = reconcile_merged_prs(apply=True, verbose=False)
        if recon.flipped or recon.cleaned:
            bits = []
            if recon.flipped:
                bits.append(f"flipped status: {sorted(set(recon.flipped))}")
            if recon.cleaned:
                bits.append(f"cleaned: {sorted(set(recon.cleaned))}")
            print(f"Reconciled merged PRs — {'; '.join(bits)}")
        merged_this_run = set(recon.flipped)
    else:
        recon = reconcile_merged_prs(apply=False, verbose=False)
        if recon.flipped:
            print(f"WOULD reconcile: {sorted(set(recon.flipped))}")

    frs = load_frs()
    if not frs:
        print("No FRs found in specs/")
        return 0

    runnable = runnable_frs(frs)
    if fr_filter is not None:
        runnable, problems = filter_frs_by_selector(frs, fr_filter, "dev")
        if problems:
            print("Wave aborted: --fr selection cannot run for Developer:")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(f"--fr filter active: {[fr['id'] for fr in runnable]}")
    else:
        # @implements FR-0006:AC-9 — say why a `ready` FR is no longer listed.
        for skipped_id, reason in handed_off_frs(frs, "dev"):
            print(f"  {skipped_id}  SKIP — {reason}")
    if not runnable:
        print("No runnable FRs (none with status=ready and deps fully merged).")
        print()
        _write_wave_synthesis(
            [], started_at, time.monotonic() - wave_start, emit_record=apply
        )
        return 0

    print(f"Runnable FRs for Developer: {[fr['id'] for fr in runnable]}")
    print()

    # @implements FR-0011:AC-6, FR-0011:AC-7, FR-0011:AC-8, FR-0011:AC-9
    # Phase 0, after `_gh_preflight` — before any worktree, venv, branch,
    # lock file or agent process this wave might create.
    preflight_gate = _run_env_preflight(
        apply, _env_preflight_skip_requested(skip_env_preflight)
    )
    if preflight_gate.blocked:
        blocking = [f for f in preflight_gate.findings if f.severity == "block"]
        print(
            f"Wave aborted: environment pre-flight blocked "
            f"({len(blocking)} blocking finding(s))."
        )
        _metrics_emit(
            "dispatch.wave",
            role="orchestrator",
            object_ids=[fr["id"] for fr in runnable],
            run_id=None,
            fr_count=len(runnable),
            completed=0,
            dev_only=0,
            dropped=len(runnable),
            drop_reasons=[
                {
                    "fr_id": None,
                    "phase": "preflight-env",
                    "class": f.cls,
                    "resource": f.resource,
                }
                for f in blocking
            ],
            rounds_ran={},
            force_escalated=[],
        )
        return 1
    preflight_segment = preflight_gate.metrics_segment
    preflight_drop_note = preflight_gate.wave_drop_note
    print()

    results: list[WaveFRResult] = [WaveFRResult(fr_id=fr["id"]) for fr in runnable]
    results_by_id: dict[str, WaveFRResult] = {r.fr_id: r for r in results}

    current_phase = "dev-tick"
    try:
        # ------------------------------------------------------------------
        # Phase 1: Dev Tick
        # ------------------------------------------------------------------
        print("--- Phase 1: Dev Tick ---", flush=True)

        dev_spawned: list[tuple[str, str]] = []
        for fr in runnable:
            fr_id = fr["id"]
            state, lock = lock_state(fr_id, "dev")
            if state == "held":
                print(
                    f"  {fr_id}  SKIP — Developer lock held (pid={lock['pid']})",
                    flush=True,
                )
                r = results_by_id[fr_id]
                r.dropped_at = "dev-tick"
                r.drop_reason = "lock already held"
                continue
            if state in ("stale", "dead", "corrupt"):
                print(
                    f"  {fr_id}  SKIP — lock state={state}; run prune first", flush=True
                )
                r = results_by_id[fr_id]
                r.dropped_at = "dev-tick"
                r.drop_reason = f"lock state: {state}"
                continue

            # @implements FR-0009:AC-7 — same preflight as `cmd_tick`, runs in
            # both dry-run and apply so a dry-run shows what apply would do.
            owns_grants = _dev_owns_preflight(fr_id)
            if owns_grants is None:
                r = results_by_id[fr_id]
                r.dropped_at = "dev-tick"
                r.drop_reason = "invalid owns: entry"
                continue
            # @implements FR-0010:AC-7
            _print_stack_report(fr_id, "dev", _stack_preflight(fr_id, "dev"))

            if not apply:
                wt_preview = REPO_ROOT / ".claude" / "worktrees" / f"dev-{fr_id}"
                base = _base_branch_for_role(fr_id, "dev")
                preview = adapter.dry_run_preview(fr_id, "dev", wt_preview)
                print(
                    f"  {fr_id}  WOULD-SPAWN  {preview}  (base={base})  owns-grants={owns_grants}",
                    flush=True,
                )
                continue

            result, pid, wt_path = spawn_role(
                fr_id,
                "dev",
                apply=True,
                adapter=adapter,
                **_spawn_extra_kwargs(preflight_segment),
            )
            if result == "spawned":
                log_file = DISPATCH_DIR / f"{fr_id}.dev.log"
                print(
                    f"  {fr_id}  SPAWNED      pid={pid}, worktree={wt_path}, log={log_file}  "
                    f"owns-grants={owns_grants}",
                    flush=True,
                )
                dev_spawned.append((fr_id, "dev"))
            elif result == "binary-not-found":
                hint = (
                    "install via `winget install Anthropic.ClaudeCode`"
                    if adapter.name == "claude-code"
                    else "install Cursor + run `cursor-agent login`"
                )
                print(
                    f"  {fr_id}  ERROR — `{adapter.binary_name}` not on PATH; {hint}",
                    flush=True,
                )
                results_by_id[fr_id].dropped_at = "dev-tick"
                results_by_id[fr_id].drop_reason = "binary not found"
            else:
                print(f"  {fr_id}  ERROR — {result}", flush=True)
                results_by_id[fr_id].dropped_at = "dev-tick"
                results_by_id[fr_id].drop_reason = result

        if not apply:
            selected = [fr["id"] for fr in runnable if not results_by_id[fr["id"]].dropped_at]
            print()
            print(f"--- Dry-run: remaining phases, for these FRs only (rounds={rounds}) ---")
            # @implements FR-0008:AC-13 — an FR with no `gates:` key produces
            # identical dry-run output; "Phase 3.5: Gate check" (and its
            # `WOULD-GATE` lines) is omitted entirely unless at least one
            # selected FR declares one.
            by_id = {fr["id"]: fr for fr in load_frs()}
            phases = ["Phase 2: Dev Monitor", "Phase 3: Dev Evaluate + Finalize"]
            if any(by_id.get(sel, {}).get("gates") for sel in selected):
                phases.append("Phase 3.5: Gate check")
            phases += ["Phase 4: Rev Tick", "Phase 5: Rev Monitor", "Phase 6: Rev Evaluate + Finalize"]
            for phase in phases:
                print(f"  WOULD-RUN  {phase}  {selected}", flush=True)
                if phase == "Phase 3.5: Gate check":
                    # Every `after: dev` gate this FR declares, not only ones
                    # already unsatisfied (dev hasn't run yet in dry-run, so
                    # nothing is knowable).
                    for sel in selected:
                        for g in (by_id.get(sel, {}).get("gates") or ()):
                            if g["after"] == "dev":
                                print(
                                    f"  {sel}  WOULD-GATE   {g['id']} reviewer={g['reviewer']}"
                                )
                if phase == "Phase 4: Rev Tick":
                    for sel in selected:
                        _print_rev_sync_preview(
                            sel, "rev", _role_worktree_path(sel, "rev")
                        )
            # AC-8: name the rework rounds that a request-changes verdict would drive.
            for extra_round in range(2, rounds + 1):
                print(
                    f"  WOULD-RUN  Round {extra_round}/{rounds}: Dev rework -> "
                    f"Reviewer re-review  {selected}  "
                    f"(only for FRs whose round {extra_round - 1} verdict is "
                    f"request-changes)"
                )
            print()
            _write_wave_synthesis(results, started_at, time.monotonic() - wave_start)
            return 0

        if not dev_spawned:
            print("No Developer agents spawned; nothing to do.")
            print()
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
            return 0

        # ------------------------------------------------------------------
        # Phase 2: Dev Monitor
        # ------------------------------------------------------------------
        print()
        print(f"--- Phase 2: Dev Monitor ({len(dev_spawned)} agent(s), "
              f"timeout={_fmt_secs(phase_timeout)}) ---", flush=True)

        current_phase = "dev-monitor"
        dev_poll_results = _wait_for_phase(dev_spawned, poll_interval, phase_timeout)

        # Check total wave timeout
        if time.monotonic() - wave_start > timeout:
            print("Wave total timeout reached; skipping remaining phases.")
            for fr_id, status in dev_poll_results.items():
                if status == "timeout":
                    results_by_id[fr_id].dropped_at = "dev-monitor"
                    results_by_id[fr_id].drop_reason = "phase timeout"
                    _emit_dispatch_run(fr_id, "dev", "timeout", None)
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
            return 1

        # ------------------------------------------------------------------
        # Phase 3: Dev Evaluate + Finalize
        # ------------------------------------------------------------------
        print()
        print("--- Phase 3: Dev Evaluate + Finalize ---", flush=True)

        dev_finalized: list[str] = []
        for fr_id, poll_status in dev_poll_results.items():
            r = results_by_id[fr_id]

            if poll_status == "timeout":
                r.dropped_at = "dev-monitor"
                r.drop_reason = "phase timeout (agent killed)"
                print(f"  {fr_id}  DROPPED — timeout", flush=True)
                _emit_dispatch_run(fr_id, "dev", "timeout", None)
                continue

            current_phase = "dev-evaluate"
            outcome = _evaluate_agent_outcome(fr_id, "dev", adapter)
            r.dev_outcome = outcome

            if outcome.status != "success":
                r.dropped_at = "dev-evaluate"
                r.drop_reason = outcome.summary
                print(f"  {fr_id}  DROPPED — {outcome.summary}", flush=True)
                continue

            wt_path = REPO_ROOT / ".claude" / "worktrees" / f"dev-{fr_id}"
            # @implements FR-0024:AC-2, FR-0024:AC-3
            pr_body = _worktree_project_root(wt_path) / "PR_BODY.md"
            if not pr_body.exists():
                branch = _branch_for(fr_id, "dev")
                # @implements FR-0016:AC-1
                show = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(REPO_ROOT),
                        "show",
                        f"{branch}:{_repo_path('PR_BODY.md')}",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
                if show.returncode != 0:
                    r.dropped_at = "dev-evaluate"
                    r.drop_reason = "PR_BODY.md not found"
                    print(f"  {fr_id}  DROPPED — PR_BODY.md missing", flush=True)
                    continue

            current_phase = "dev-finalize"
            # @implements FR-0013:AC-7 — automatic inside `wave` (no
            # `--revalidate` flag here) when this FR depends on one whose
            # PR merged during this run's Phase 0 reconcile.
            fr_meta = next((f for f in runnable if f["id"] == fr_id), None)
            deps = (fr_meta or {}).get("depends_on") or []
            auto_revalidate = bool(merged_this_run.intersection(deps))
            rc = cmd_finalize(
                fr_id,
                "dev",
                apply=True,
                draft=draft,
                adapter=adapter,
                revalidate=auto_revalidate,
            )
            if rc != 0:
                r.dropped_at = "dev-finalize"
                r.drop_reason = "finalize failed (see output above)"
                print(f"  {fr_id}  DROPPED — finalize failed", flush=True)
                continue

            r.dev_finalize_ok = True
            pr_record = _load_pr_record(fr_id, "dev")
            if pr_record:
                r.pr_number = pr_record.get("pr_number")
                r.pr_url = pr_record.get("pr_url")
            dev_finalized.append(fr_id)
            print(f"  {fr_id}  FINALIZED    PR #{r.pr_number or '?'}", flush=True)

        if not dev_finalized:
            print()
            print("No Developer agents succeeded; skipping Reviewer phase.")
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
            return 0

        # Check total wave timeout before rev phase
        if time.monotonic() - wave_start > timeout:
            print("Wave total timeout reached; skipping Reviewer phase.")
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
            return 0

        # ------------------------------------------------------------------
        # Phase 3.5: Gate check — declared `after: dev` gates (FR-0008)
        # ------------------------------------------------------------------
        # @implements FR-0008:AC-13 — an FR with no `gates:` key produces
        # identical wave output; this whole phase (including its header) is
        # invisible unless at least one just-finalized FR declares a gate.
        by_id_now = {fr["id"]: fr for fr in load_frs()}
        any_gates_declared = any(
            (by_id_now.get(fr_id) or {}).get("gates") for fr_id in dev_finalized
        )
        if any_gates_declared:
            print()
            current_phase = "gate-check"
            print("--- Phase 3.5: Gate check ---", flush=True)
        for fr_id in dev_finalized:
            r = results_by_id[fr_id]
            fr_meta = by_id_now.get(fr_id)
            pending = _pending_after_dev_gates(
                fr_id, (fr_meta or {}).get("gates") or ()
            )
            if not pending:
                continue
            human_pending = [(g, s) for g, s in pending if g["reviewer"] == "human"]
            architect_pending = [(g, s) for g, s in pending if g["reviewer"] == "architect"]
            if human_pending:
                # @implements FR-0008:AC-5 — a human gate stops the wave for
                # this FR; nothing here ever writes a `pass` verdict for it.
                gate, _status = human_pending[0]
                cmd = (
                    f"python scripts/dispatch.py gate pass {fr_id} {gate['id']} "
                    "--by <you> --apply"
                )
                print(
                    f"  {fr_id}  GATE-PENDING {gate['id']} reviewer=human — "
                    f"{gate['scope']} — satisfy with: {cmd}",
                    flush=True,
                )
                r.gate_result = "pending"
                r.gate_note = f"{gate['id']} reviewer=human — satisfy with: {cmd}"
                continue
            # @implements FR-0008:AC-6, FR-0008:AC-7 — an architect gate
            # spawns a one-shot gate-review session, synchronously, before
            # this FR is offered to the Reviewer.
            gate, _status = architect_pending[0]
            gat_state, _ = lock_state(fr_id, "gat")
            if gat_state == "held":
                print(f"  {fr_id}  SKIP — gat lock held", flush=True)
                r.gate_result = "pending"
                r.gate_note = f"{gate['id']} reviewer=architect — gat lock held"
                continue
            result, pid, wt_path = spawn_role(
                fr_id, "gat", apply=True, adapter=adapter, gate_id=gate["id"]
            )
            if result != "spawned":
                print(f"  {fr_id}  ERROR — gat spawn failed: {result}", flush=True)
                r.gate_result = "pending"
                r.gate_note = (
                    f"{gate['id']} reviewer=architect — spawn failed: {result}"
                )
                continue
            print(
                f"  {fr_id}  SPAWNED-GAT  pid={pid}, worktree={wt_path}, gate={gate['id']}",
                flush=True,
            )
            gat_poll = _wait_for_phase([(fr_id, "gat")], poll_interval, phase_timeout)
            if gat_poll.get(fr_id) == "timeout":
                print(
                    f"  {fr_id}  GATE-PENDING {gate['id']} reviewer=architect — "
                    "session timed out",
                    flush=True,
                )
                r.gate_result = "pending"
                r.gate_note = f"{gate['id']} reviewer=architect — session timed out"
                continue
            gat_outcome = _evaluate_agent_outcome(fr_id, "gat", adapter)
            if gat_outcome.status != "success":
                print(
                    f"  {fr_id}  GATE-PENDING {gate['id']} reviewer=architect — "
                    f"{gat_outcome.summary}",
                    flush=True,
                )
                r.gate_result = "pending"
                r.gate_note = f"{gate['id']} reviewer=architect — {gat_outcome.summary}"
                continue
            gat_fin_rc = cmd_finalize(fr_id, "gat", apply=True, draft=draft, adapter=adapter)
            if gat_fin_rc != 0:
                print(
                    f"  {fr_id}  GATE-PENDING {gate['id']} reviewer=architect — "
                    "gat finalize failed",
                    flush=True,
                )
                r.gate_result = "pending"
                r.gate_note = f"{gate['id']} reviewer=architect — finalize failed"
                continue
            final_status = gate_status(fr_id, gate["id"])
            if final_status == "pass":
                print(f"  {fr_id}  GATE-PASS    {gate['id']} by architect", flush=True)
                continue
            if final_status == "stale":
                # @implements FR-0008:AC-7 — the GATE-STALE SHA lookup reads
                # the FR's implementation branch (`claude/dev-<FR>` if it
                # exists, else `claude/mnt-<FR>`; DEC-0012 item 3).
                impl_found = _implementation_branch_for_fr(fr_id)
                impl_branch = impl_found[0] if impl_found is not None else f"claude/dev-{fr_id}"
                # @implements FR-0024:AC-3
                ev_rel = _repo_path(_gate_evidence_path(fr_id, gate["id"]))
                ev_ok, ev_text = _git_capture(
                    ["show", f"{impl_branch}:{ev_rel}"],
                    REPO_ROOT,
                )
                ev_sha = "?"
                if ev_ok:
                    mm = FRONTMATTER_PATTERN.match(ev_text)
                    if mm:
                        try:
                            ev_meta = yaml.safe_load(mm.group(1)) or {}
                            ev_sha = str(ev_meta.get("head_sha") or "?")
                        except yaml.YAMLError:
                            pass
                dev_sha = _branch_head_sha(impl_branch) or "?"
                print(
                    f"  {fr_id}  GATE-STALE   {gate['id']} — evidence head_sha "
                    f"{ev_sha[:7]} vs current dev tip {dev_sha[:7]}",
                    flush=True,
                )
                r.gate_result = "stale"
                r.gate_note = (
                    f"{gate['id']} — evidence {ev_sha[:7]} vs dev tip {dev_sha[:7]}"
                )
                continue
            # changes-requested
            print(f"  {fr_id}  GATE-BLOCKED {gate['id']} by architect", flush=True)
            r.gate_result = "blocked"
            r.gate_note = (
                f"{gate['id']} by architect — see specs/_gates/{fr_id}-{gate['id']}.md"
            )

        # ------------------------------------------------------------------
        # Phase 4: Rev Tick
        # ------------------------------------------------------------------
        print()
        current_phase = "rev-tick"
        print("--- Phase 4: Rev Tick ---", flush=True)

        frs = load_frs()
        rev_runnable = runnable_review_frs(frs)
        rev_eligible = [fr for fr in rev_runnable if fr["id"] in dev_finalized]

        if not rev_eligible:
            print("No FRs eligible for Reviewer (dev branches may need status flip).")
            print()
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
            # @implements FR-0008:AC-5, FR-0008:AC-7 — this early return is
            # exactly the scenario those ACs describe (every dev-finalized FR
            # is gated, so rev_eligible is empty); the exit code must still
            # reflect a gate outcome, not the wave's usual "nothing to do" 0.
            return _wave_exit_code(results, any(r.dropped_at for r in results))

        print(f"Eligible FRs for Reviewer: {[fr['id'] for fr in rev_eligible]}")

        rev_spawned: list[tuple[str, str]] = []
        for fr in rev_eligible:
            fr_id = fr["id"]
            state, lock = lock_state(fr_id, "rev")
            if state == "held":
                print(f"  {fr_id}  SKIP — Reviewer lock held", flush=True)
                continue
            if state in ("stale", "dead", "corrupt"):
                print(f"  {fr_id}  SKIP — rev lock state={state}", flush=True)
                continue

            # @implements FR-0010:AC-5
            if _owns_preflight_for(fr_id, "rev") is None:
                continue
            # @implements FR-0010:AC-7
            _print_stack_report(fr_id, "rev", _stack_preflight(fr_id, "rev"))

            result, pid, wt_path = spawn_role(
                fr_id,
                "rev",
                apply=True,
                adapter=adapter,
                **_spawn_extra_kwargs(preflight_segment),
            )
            if result == "spawned":
                log_file = DISPATCH_DIR / f"{fr_id}.rev.log"
                print(f"  {fr_id}  SPAWNED      pid={pid}, worktree={wt_path}, log={log_file}", flush=True)
                rev_spawned.append((fr_id, "rev"))
            else:
                print(f"  {fr_id}  ERROR — {result}", flush=True)

        if not rev_spawned:
            print("No Reviewer agents spawned.")
            print()
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
            # @implements FR-0008:AC-5, FR-0008:AC-7 — same as the
            # rev_eligible early return above: a gate outcome must survive
            # this early exit too.
            return _wave_exit_code(results, any(r.dropped_at for r in results))

        # ------------------------------------------------------------------
        # Phase 5: Rev Monitor
        # ------------------------------------------------------------------
        print()
        remaining_timeout = timeout - (time.monotonic() - wave_start)
        effective_phase_timeout = min(phase_timeout, max(remaining_timeout, 0))
        print(f"--- Phase 5: Rev Monitor ({len(rev_spawned)} agent(s), "
              f"timeout={_fmt_secs(effective_phase_timeout)}) ---", flush=True)

        current_phase = "rev-monitor"
        rev_poll_results = _wait_for_phase(rev_spawned, poll_interval, effective_phase_timeout)

        # ------------------------------------------------------------------
        # Phase 6: Rev Evaluate + Finalize
        # ------------------------------------------------------------------
        print()
        print("--- Phase 6: Rev Evaluate + Finalize ---", flush=True)

        for fr_id, poll_status in rev_poll_results.items():
            r = results_by_id.get(fr_id)
            if r is None:
                continue

            if poll_status == "timeout":
                r.dropped_at = "rev-monitor"
                r.drop_reason = "phase timeout (agent killed)"
                print(f"  {fr_id}  DROPPED — timeout", flush=True)
                _emit_dispatch_run(fr_id, "rev", "timeout", None)
                continue

            current_phase = "rev-evaluate"
            outcome = _evaluate_agent_outcome(fr_id, "rev", adapter)
            r.rev_outcome = outcome

            if outcome.status != "success":
                r.dropped_at = "rev-evaluate"
                r.drop_reason = outcome.summary
                print(f"  {fr_id}  DROPPED — {outcome.summary}", flush=True)
                continue

            current_phase = "rev-finalize"
            # @implements FR-0014:AC-1
            rc = cmd_finalize(fr_id, "rev", apply=True, draft=draft, adapter=adapter)
            if rc != 0:
                r.dropped_at = "rev-finalize"
                r.drop_reason = "finalize failed (see output above)"
                print(f"  {fr_id}  DROPPED — rev finalize failed", flush=True)
                continue

            r.rev_finalize_ok = True
            r.rev_verdict = outcome.verdict
            r.round_verdicts.append(outcome.verdict)
            print(f"  {fr_id}  REVIEW-POSTED  verdict={outcome.verdict}", flush=True)

        # ------------------------------------------------------------------
        # Rework rounds: re-dispatch Dev->Reviewer on request-changes
        # ------------------------------------------------------------------
        if rounds > 1:
            print()
            current_phase = "rework"
            print(f"--- Rework rounds (budget={rounds}) ---", flush=True)
            # Resolve each round-1 verdict from the Reviewer's own artifacts
            # (AC-3/AC-4) before deciding whether to loop, so a request-changes
            # that had to degrade to the own-PR comment fallback still re-drives.
            for fr_id, r in results_by_id.items():
                if not r.rev_finalize_ok or r.dropped_at:
                    continue
                resolved = _resolve_rework_verdict(fr_id, r.rev_verdict)
                if resolved != r.rev_verdict:
                    r.rev_verdict = resolved
                    if r.round_verdicts:
                        r.round_verdicts[-1] = resolved
            _run_rework_rounds(
                results_by_id,
                rounds,
                draft,
                adapter,
                phase_timeout,
                poll_interval,
                preflight_segment=preflight_segment,
            )

        # ------------------------------------------------------------------
        # Synthesis
        # ------------------------------------------------------------------
        current_phase = "synthesis"
        _write_wave_synthesis(
            results,
            started_at,
            time.monotonic() - wave_start,
            emit_record=True,
            extra_drop_reasons=preflight_drop_note,
        )
        if park_findings:
            _park_findings(_collect_findings(results), started_at)

        any_dropped = any(r.dropped_at for r in results)
        # @implements FR-0008:AC-5, FR-0008:AC-7 — see _wave_exit_code; this
        # is the normal end-of-wave exit point, kept in sync with the two
        # Phase 4 early returns above by going through the same helper.
        return _wave_exit_code(results, any_dropped)

    except Exception as exc:  # noqa: BLE001 — AC-3 requires catching any wave-phase crash
        # @implements FR-0014:AC-3, FR-0014:AC-4
        tb = traceback.format_exc()
        phase_name = _WAVE_PHASE_NAMES.get(current_phase, current_phase)
        print(f"CRASHED — {phase_name}: {type(exc).__name__}: {exc}", flush=True)
        print(tb, flush=True)
        print(tb, file=sys.stderr)
        if apply:
            crash_reason = f"{type(exc).__name__}: {exc}"
            crash_phase = f"{current_phase}-crash"
            for r in results_by_id.values():
                if not r.completed_e2e and not r.dropped_at:
                    r.dropped_at = crash_phase
                    r.drop_reason = crash_reason
            _write_wave_synthesis(
                results,
                started_at,
                time.monotonic() - wave_start,
                emit_record=True,
                extra_drop_reasons=preflight_drop_note,
            )
        return 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-dispatch Developer waves on FR readiness"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_harness(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--harness",
            choices=sorted(_ADAPTERS),
            default=DEFAULT_HARNESS,
            help=f"agent harness to use (default: {DEFAULT_HARNESS}; env: DISPATCH_HARNESS)",
        )

    def add_fr_selector(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--fr",
            action="append",
            metavar="FR-XXXX[,FR-YYYY]",
            help=(
                "Restrict dispatch to these FR ids. Repeatable and/or "
                "comma-separated. Omit for every runnable FR. A named FR that "
                "cannot run is an error, never a silent skip."
            ),
        )

    p_tick = sub.add_parser(
        "tick", help="Fire next Developer or Reviewer wave (dry-run unless --apply)"
    )
    p_tick.add_argument(
        "--apply", action="store_true", help="Actually spawn agent sessions"
    )
    p_tick.add_argument(
        "--role",
        choices=("dev", "rev", "gat"),
        default="dev",
        help=(
            "dev: spawn Developers for ready FRs (default). rev: spawn "
            "Reviewers for FRs whose dev branch exists and dev is finished. "
            "gat: spawn a one-shot Architect gate-review session for the "
            "named FR's (`--fr`, required) first unsatisfied `after: dev` "
            "architect gate (FR-0008)."
        ),
    )
    p_tick.add_argument(
        "--skip-env-preflight",
        action="store_true",
        help=(
            "Skip FR-0011's stack-aware environment pre-flight (Docker daemon "
            "reachability, PATH tools, Windows app-control policy, host port "
            f"collisions). Never skips gh's own preflight. Also settable via "
            f"{ENV_SKIP_PREFLIGHT_VAR}=1."
        ),
    )
    add_fr_selector(p_tick)
    add_harness(p_tick)

    sub.add_parser("status", help="Show liveness/idle/dead per lock")
    sub.add_parser("prune", help="Remove locks whose process is no longer alive")

    p_kill = sub.add_parser(
        "kill", help="Force-terminate a running role + remove its lock"
    )
    p_kill.add_argument("fr_id", help="FR id (e.g., FR-0002)")
    p_kill.add_argument(
        "--role",
        choices=("dev", "rev", "bkf", "mnt", "gat"),
        default="dev",
        help="role label (default: dev)",
    )

    p_sum = sub.add_parser(
        "summary",
        help="Pretty-print the result + tool counts + final message from a log",
    )
    p_sum.add_argument("fr_id", help="FR id (e.g., FR-0002)")
    p_sum.add_argument(
        "--role",
        choices=("dev", "rev", "bkf", "mnt", "gat"),
        default="dev",
        help="role label (default: dev)",
    )
    p_sum.add_argument(
        "--harness",
        choices=sorted(_ADAPTERS),
        default=None,
        help="override harness for log parsing (default: read from lockfile, fallback claude-code)",
    )

    p_fin = sub.add_parser(
        "finalize",
        help="Push the role branch and post the PR (dev) or review (rev). Idempotent.",
    )
    p_fin.add_argument("fr_id", help="FR id (e.g., FR-XXXX)")
    p_fin.add_argument(
        "--role",
        choices=("dev", "rev", "bkf", "mnt", "gat"),
        default="dev",
        help=(
            "dev: push + open draft PR. rev: push + post gh pr review against "
            "parent. bkf: push + open backfill PR (`test(FR-XXXX): backfill AC "
            "coverage`). mnt: push + open maintainer PR (`chore(FR-XXXX): <title>`)."
        ),
    )
    p_fin.add_argument(
        "--apply",
        action="store_true",
        help="Actually push and call gh (dry-run by default)",
    )
    p_fin.add_argument(
        "--ready",
        action="store_true",
        help="(dev only) Open the PR as ready-for-review instead of --draft",
    )
    p_fin.add_argument(
        "--verdict-file",
        type=Path,
        default=None,
        help=(
            "(rev only) Read the Reviewer's final text from this file instead of "
            "`_dispatch/<FR>.rev.log` — makes a subagent-run Reviewer (no "
            "dispatch log) finalizable. Takes precedence over the log when both "
            "are present. A missing or empty file is an error."
        ),
    )
    p_fin.add_argument(
        "--review-round",
        metavar="N",
        default=None,
        help=(
            "(rev only) The review round N (an integer >= 1) for the library "
            "path specs/_reviews/<FR>-r<N>.md and the filing commit's subject. "
            "Overrides the run-context round; use it for a hand-run Reviewer "
            "whose later round has no lock."
        ),
    )
    p_fin.add_argument(
        "--allow-crossing",
        action="append",
        metavar="GLOB",
        default=None,
        help=(
            "(mnt only) Repeatable. Exempt this glob from the maintainer "
            "footprint check, but only when the dispatcher can verify the diff "
            "on it is content-free (line-ending/whitespace only); a glob "
            "carrying real content is refused, not exempted."
        ),
    )
    p_fin.add_argument(
        "--revalidate",
        action="store_true",
        help=(
            "(dev/mnt/bkf) When origin/main carries commits the branch lacks, "
            "merge origin/main into the role worktree and re-run the deploy "
            "gate before pushing, instead of only warning."
        ),
    )

    p_bkf = sub.add_parser(
        "backfill",
        help=(
            "One-shot Reviewer-in-backfill-mode spawn. Branches off `main` "
            "and writes the AC tests an already-merged FR was missing. "
            "Opens a follow-up PR titled `test(FR-XXXX): backfill AC coverage`."
        ),
    )
    p_bkf.add_argument("fr_id", help="FR id (e.g., FR-XXXX)")
    p_bkf.add_argument(
        "--apply",
        action="store_true",
        help="Actually spawn the agent (dry-run by default)",
    )
    add_harness(p_bkf)

    p_mnt = sub.add_parser(
        "maintain",
        help=(
            "One-shot Developer-in-maintainer-mode spawn for an FR whose "
            "`owns:` footprint intersects the control-plane paths every other "
            "role denies. Writable footprint is derived from that FR's `owns:` "
            "and nothing else. Opens `chore(FR-XXXX): <title>`."
        ),
    )
    p_mnt.add_argument("fr_id", help="FR id (e.g., FR-XXXX)")
    p_mnt.add_argument(
        "--apply",
        action="store_true",
        help="Actually spawn the agent (dry-run by default)",
    )
    p_mnt.add_argument(
        "--skip-env-preflight",
        action="store_true",
        help=(
            "Skip FR-0011's stack-aware environment pre-flight. Also settable "
            f"via {ENV_SKIP_PREFLIGHT_VAR}=1."
        ),
    )
    add_harness(p_mnt)

    p_recon = sub.add_parser(
        "reconcile-merged",
        help=(
            "Project merged PR state from origin back into local state: "
            "flip FR frontmatter status to `merged` (commit per-FR) and "
            "remove the corresponding worktrees/branches/locks. Idempotent."
        ),
    )
    p_recon.add_argument(
        "--apply",
        action="store_true",
        help="Actually edit specs, commit, and clean working state (default: dry-run)",
    )

    p_gate = sub.add_parser(
        "gate",
        help=(
            "Inspect or satisfy an FR's declared gates (FR-0008). "
            "`gate list <FR>`, `gate pass <FR> <gate-id> --by <who> --apply`, "
            "`gate block <FR> <gate-id> --by <who> --note <text> --apply`."
        ),
    )
    gate_sub = p_gate.add_subparsers(dest="gate_cmd", required=True)
    p_gate_list = gate_sub.add_parser(
        "list", help="Print each declared gate's current status for an FR."
    )
    p_gate_list.add_argument("fr_id", help="FR id (e.g., FR-XXXX)")
    p_gate_pass = gate_sub.add_parser(
        "pass", help="Record a passing verdict for a human gate."
    )
    p_gate_pass.add_argument("fr_id", help="FR id (e.g., FR-XXXX)")
    p_gate_pass.add_argument("gate_id", help="the gate's declared id")
    p_gate_pass.add_argument("--by", required=True, help="who is passing this gate")
    p_gate_pass.add_argument("--note", default=None, help="optional rationale")
    p_gate_pass.add_argument(
        "--apply", action="store_true", help="Actually write + commit (dry-run by default)"
    )
    p_gate_block = gate_sub.add_parser(
        "block", help="Record a changes-requested verdict for a human gate."
    )
    p_gate_block.add_argument("fr_id", help="FR id (e.g., FR-XXXX)")
    p_gate_block.add_argument("gate_id", help="the gate's declared id")
    p_gate_block.add_argument("--by", required=True, help="who is blocking this gate")
    p_gate_block.add_argument(
        "--note", default=None, required=True, help="required rationale"
    )
    p_gate_block.add_argument(
        "--apply", action="store_true", help="Actually write + commit (dry-run by default)"
    )

    p_finall = sub.add_parser(
        "finalize-all",
        help="Finalize every FR whose role branch exists and lock is free. Idempotent.",
    )
    p_finall.add_argument(
        "--role",
        choices=("dev", "rev", "bkf", "mnt", "gat"),
        default="dev",
        help="dev (default), rev, bkf, or mnt",
    )
    p_finall.add_argument(
        "--apply",
        action="store_true",
        help="Actually push and call gh (dry-run by default)",
    )
    p_finall.add_argument(
        "--ready",
        action="store_true",
        help="(dev only) Open PRs as ready-for-review instead of --draft",
    )

    p_wave = sub.add_parser(
        "wave",
        help=(
            "Autonomous dispatch-to-PR pipeline. Chains: pre-flight -> "
            "dev tick -> dev monitor -> dev finalize -> rev tick -> rev monitor -> "
            "rev finalize -> synthesis. Single command, no human intervention in "
            "the happy path. PRs open as --draft; human reviews and merges."
        ),
    )
    p_wave.add_argument(
        "--apply",
        action="store_true",
        help="Actually spawn agents, push branches, and open PRs (dry-run by default)",
    )
    p_wave.add_argument(
        "--ready",
        action="store_true",
        help="Open PRs as ready-for-review instead of --draft",
    )
    p_wave.add_argument(
        "--timeout",
        type=float,
        default=7200,
        help="Total wave timeout in seconds (default: 7200 = 2h)",
    )
    p_wave.add_argument(
        "--phase-timeout",
        type=float,
        default=3600,
        help="Max time per phase (dev wave or rev wave) in seconds (default: 3600 = 1h)",
    )
    p_wave.add_argument(
        "--poll-interval",
        type=float,
        default=30,
        help="Seconds between lock-state polls (default: 30)",
    )
    p_wave.add_argument(
        "--rounds",
        type=int,
        default=2,
        help=(
            "Max Dev<->Reviewer cycles per FR (default: 2 — one automatic rework "
            "round on a request-changes verdict; --rounds 1 reproduces the "
            f"original single-pass behaviour exactly). Capped at the "
            f"{REVIEW_CYCLE_BUDGET}-cycle budget from CLAUDE.md; a higher value "
            "exits non-zero. When the reviewer requests changes and rounds "
            "remain, the Developer is re-dispatched with a generated rework "
            "brief."
        ),
    )
    p_wave.add_argument(
        "--park-findings",
        action="store_true",
        help=(
            "After synthesis, append each agent ## FINDINGS item to the hub "
            "parking lot via scripts/parking.py (serial). Findings always appear "
            "in the wave synthesis regardless; this also captures them as IDEAs. "
            "Set DISPATCH_HUB_ROOT if the project is not nested under the hub."
        ),
    )
    p_wave.add_argument(
        "--skip-env-preflight",
        action="store_true",
        help=(
            "Skip FR-0011's stack-aware environment pre-flight (Docker daemon "
            "reachability, PATH tools, Windows app-control policy, host port "
            f"collisions). Never skips `_gh_preflight`. Also settable via "
            f"{ENV_SKIP_PREFLIGHT_VAR}=1."
        ),
    )
    add_fr_selector(p_wave)
    add_harness(p_wave)

    args = parser.parse_args()
    if args.cmd == "tick":
        adapter = get_adapter(args.harness)
        return cmd_tick(
            apply=args.apply,
            adapter=adapter,
            role=args.role,
            fr_filter=parse_fr_selector(args.fr),
            skip_env_preflight=args.skip_env_preflight,
        )
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "prune":
        return cmd_prune()
    if args.cmd == "kill":
        return cmd_kill(args.fr_id, args.role)
    if args.cmd == "summary":
        return cmd_summary(args.fr_id, args.role, args.harness)
    if args.cmd == "finalize":
        return cmd_finalize(
            args.fr_id,
            args.role,
            apply=args.apply,
            draft=not args.ready,
            verdict_file=args.verdict_file,
            allow_crossing=args.allow_crossing,
            revalidate=args.revalidate,
            review_round=args.review_round,
        )
    if args.cmd == "finalize-all":
        return cmd_finalize_all(args.role, apply=args.apply, draft=not args.ready)
    if args.cmd == "gate":
        # @implements FR-0008:AC-3
        if args.gate_cmd == "list":
            return cmd_gate_list(args.fr_id)
        if args.gate_cmd == "pass":
            return cmd_gate_verdict(
                args.fr_id,
                args.gate_id,
                "pass",
                by=args.by,
                note=args.note,
                apply=args.apply,
            )
        if args.gate_cmd == "block":
            return cmd_gate_verdict(
                args.fr_id,
                args.gate_id,
                "changes-requested",
                by=args.by,
                note=args.note,
                apply=args.apply,
            )
        parser.print_help()
        return 1
    if args.cmd == "reconcile-merged":
        return cmd_reconcile_merged(apply=args.apply)
    if args.cmd == "backfill":
        adapter = get_adapter(args.harness)
        return cmd_oneshot(args.fr_id, "bkf", apply=args.apply, adapter=adapter)
    if args.cmd == "maintain":
        adapter = get_adapter(args.harness)
        return cmd_oneshot(
            args.fr_id,
            "mnt",
            apply=args.apply,
            adapter=adapter,
            skip_env_preflight=args.skip_env_preflight,
        )
    if args.cmd == "wave":
        adapter = get_adapter(args.harness)
        return cmd_wave(
            apply=args.apply,
            adapter=adapter,
            draft=not args.ready,
            timeout=args.timeout,
            phase_timeout=args.phase_timeout,
            poll_interval=args.poll_interval,
            fr_filter=parse_fr_selector(args.fr),
            rounds=args.rounds,
            park_findings=args.park_findings,
            skip_env_preflight=args.skip_env_preflight,
        )
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
