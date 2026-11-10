#!/usr/bin/env python3
"""bootstrap.py — Stand up or upgrade an agent-team project from this hub.

Usage:
  python scripts/bootstrap.py <name-or-path> "<description>" [flags]
  python scripts/bootstrap.py --upgrade <project-path> [flags]

If <name-or-path> contains no path separator, the project lands under
projects/<name> (a sibling of the hub layout). Pass an explicit path to put it
elsewhere — the project still gets registered in hub/projects.yaml.

Flags (create mode):
  --stack python|node|none   Inject stack-specific conventions and CI (default: none)
  --profile <name>           Activate a compliance profile (can be repeated; validated against profiles/)
  --private                  Mark project as private (excluded from cross-project pattern detection)
  --keep-example             Keep specs/FR-0001-example.md (default: delete it)
  --no-git                   Skip git init (default: init and make initial commit)
  --no-register              Don't append to hub/projects.yaml

Flags (upgrade mode):
  --upgrade <project-path>   Propagate template changes to an existing project
  --yes                      Apply all upgrades without interactive confirmation
  --profile <name>           Backfill the project's profile record (repeatable), then
                             upgrade using that set. For projects created before the
                             record existed.

Common flags:
  -h, --help                 Show this help

Profiles and --upgrade (FR-0001): the profiles applied at creation are recorded
in the project (.agent-team/profiles.yaml) and on its hub/projects.yaml entry.
--upgrade reads that record and syncs profile-owned files (e.g. phipa's
.agent-team/hooks/phi_regex_check.py) from profiles/<name>/, never from the
template; the profile's settings overlay and AGENTS.md block are verified and
reported but never edited.
"""

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

# _console is a sibling module providing encoding-safe console output. Windows
# consoles cannot represent the arrows and dashes in this script's progress
# messages, and an unhandled UnicodeEncodeError here aborts bootstrap partway
# through, leaving a half-created project directory behind.
from _console import configure_stdio, safe_print

SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

HUB_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = HUB_ROOT / "template"
PROFILES_ROOT = HUB_ROOT / "profiles"

# Infrastructure paths that --upgrade will sync from the template.
# Note: `.claude` (not just `.claude/commands`) so settings.json — which wires
# the PHI/spec hooks — propagates on upgrade. `.claude/worktrees/` is created
# per-project at bootstrap time and does not exist in the template, so it is
# safe to include the full `.claude` subtree.
INFRA_DIRS = [
    ".agent-team",
    "scripts",
    ".github/workflows",
    ".claude",
    ".cursor/commands",
    ".cursor/rules",
]

# Root-level infrastructure files that --upgrade syncs. INFRA_DIRS only walks
# subdirectories, so root files need naming here explicitly. This is an
# allowlist rather than "every root file not in UPGRADE_EXCLUDE" on purpose:
# requirements.txt is project-owned (projects append their own dependencies to
# it) and an upgrade must not clobber it.
INFRA_ROOT_FILES = [
    "pytest.ini",
    ".gitattributes",
]

# Files/dirs that --upgrade must never touch.
UPGRADE_EXCLUDE = {
    "specs",
    "src",
    "tests",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    ".gitignore",
    "AGENTS.override.md.example",
}

# Files --upgrade seeds when absent but never overwrites when present and
# different: present-and-different is reported as drift instead, listed under
# the summary's Drift: block. Each carries content a project appends to or
# edits itself:
#   - .claude/settings.json: project-local hook/permission additions (FR-0001).
#   - pytest.ini: a project's own appended `testpaths`/marker section (FR-0020 AC-1).
# run_upgrade also adds this run's unresolved stack-injected paths (AC-2) and a
# `.gitattributes` with a damaged managed-block (AC-5) to a per-run copy of
# this set; SEED_ONLY_FILES itself never changes.
# @implements FR-0020:AC-1
SEED_ONLY_FILES = {".claude/settings.json", "pytest.ini"}

# Stack-injected files whose content depends on the project's registered
# stack (FR-0020 AC-2). `--upgrade` applies the same transforms create does
# (`enable_cursor_rule` / `uncomment_ci_job`) to the template's current text in
# memory before comparing, so a resolved-stack project keeps its rule enabled
# and its CI job uncommented while still receiving template changes to them.
STACK_RULE_REL = {
    "python": ".cursor/rules/20-python.mdc",
    "node": ".cursor/rules/20-node.mdc",
}
CI_WORKFLOW_REL = ".github/workflows/agent-gates.yml"

# When a project's stack cannot be resolved, both cursor-rule stack variants
# (either could be the one an earlier --stack bootstrap enabled) and the CI
# workflow join SEED_ONLY_FILES for that run, rather than being compared
# against the raw template and risking a silent revert of stack injection.
STACK_FILES_UNRESOLVED = (
    STACK_RULE_REL["python"],
    STACK_RULE_REL["node"],
    CI_WORKFLOW_REL,
)

# `.gitattributes`'s managed block (FR-0020 AC-4/AC-5): the two marker lines
# that delimit the block bootstrap.py --upgrade owns. Every other line in a
# project's `.gitattributes` is the project's own and is never touched.
GITATTRIBUTES_REL = ".gitattributes"
GITATTRIBUTES_BLOCK_BEGIN = "# BEGIN bootstrap.py --upgrade managed block -- do not edit lines between BEGIN/END\n"
GITATTRIBUTES_BLOCK_END = "# END bootstrap.py --upgrade managed block\n"

# Project-relative path of the provenance register (Project A FR-0015): when a
# project keeps one, --upgrade reminds the human that every added file needs
# a row in it (FR-0020 AC-3).
PROVENANCE_REGISTER_REL = "specs/knowledge/provenance-register.md"

# Project-local record of the compliance profiles applied to a project. Written
# in create mode (and by `--upgrade --profile` backfill), read by --upgrade so it
# can tell profile-owned files from template files without consulting the hub
# registry. It is project state, not template content: run_upgrade removes it
# from the template sync walk unconditionally, so it can never be offered,
# overwritten, or "added" from the template.
# @implements FR-0001:AC-1
PROFILE_RECORD_REL = ".agent-team/profiles.yaml"

# Per-profile set of project-relative paths the profile installs, mapped to the
# source file inside profiles/<name>/. --upgrade compares and syncs these
# against the profile source and never against the template base copy. Declared
# in code alongside apply_profiles()'s install steps (FR-0001 Notes); a
# profiles/<name>/manifest.yaml is a possible later refactor.
# @implements FR-0001:AC-3
PROFILE_OWNED_FILES: dict[str, dict[str, str]] = {
    "phipa": {
        ".agent-team/hooks/phi_regex_check.py": "phi_regex_check.py",
    },
}

# Per-profile verification-only assets. --upgrade checks these and reports, but
# never writes .claude/settings.json or AGENTS.md (AC-5, AC-6; interim policy
# until IDEA-0034's core/overlay split lands).
PROFILE_SETTINGS_OVERLAY = "settings_overlay.json"
PROFILE_AGENTS_BLOCK: dict[str, str] = {
    "phipa": "phi_hygiene_block.md",
}

# Header written only when hub/projects.yaml does not exist yet. An existing
# registry is never rewritten (AC-10): entries are appended after its last byte.
REGISTRY_HEADER = (
    "# Project registry — maintained by scripts/bootstrap.py\n"
    "#\n"
    "# Each entry records a project bootstrapped from this hub. The hub indexer\n"
    "# (scripts/hub-index.py) walks this list to build hub/FR-INDEX.json.\n"
    "#\n"
    "# Schema:\n"
    "#   - name: <slug>\n"
    "#     path: <absolute or relative-to-hub-root path>\n"
    "#     created: YYYY-MM-DD\n"
    "#     stack: python | node | none\n"
    "#     private: false  # if true, excluded from cross-project pattern detection\n"
    "#     profiles: []    # compliance profiles applied at bootstrap (see profiles/)\n\n"
)

# Command frontmatter: each canonical source under .agent-team/commands/ now
# declares its own metadata block (FR-0019 AC-2), so the dict this used to be
# (`COMMAND_META`) is retired -- these are only the keys it knew about and the
# rendering order/quoting `generate_commands` has always used for them.
# @implements FR-0019:AC-3
_COMMAND_META_KEYS = (
    "description",
    "argument-hint",
    "model",
    "effort",
    "allowed-tools",
)
_COMMAND_META_QUOTED_KEYS = ("description", "argument-hint")


class _MalformedCommandFrontmatter(Exception):
    """One of FR-0019 AC-5's malformed conditions. `cause` is the short reason
    named alongside the file in generate_commands' warn line."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


def _split_command_source(text: str) -> tuple[str, str] | None:
    """Split a canonical command source at its leading frontmatter fences.

    Returns `(block_text, body)`, or `None` when the source does not open
    with `---` -- today's unknown-name fallback then applies (FR-0019 AC-3).
    `block_text` is the raw `key: value` lines between the fences, newline
    joined. `body` is everything after the one blank line that follows the
    closing fence: the whole base file, byte-for-byte (FR-0019 AC-2).
    Raises `_MalformedCommandFrontmatter` when the source opens with `---`
    but no closing fence exists (AC-5).
    @implements FR-0019:AC-2
    @implements FR-0019:AC-3
    """
    if not text.startswith("---\n"):
        return None
    try:
        close = text.index("\n---\n", 4)
    except ValueError:
        raise _MalformedCommandFrontmatter("no closing '---' found") from None
    block_text = text[4:close]
    after = text[close + 5 :]
    body = after.removeprefix("\n")
    return block_text, body


def _parse_command_meta(block_text: str, label: str) -> dict[str, str]:
    """Parse a source's frontmatter block into `{key: value}` of known keys.

    An unknown key warns, naming `label` and the key, and is dropped -- not a
    malformed block (FR-0019 AC-5). Raises `_MalformedCommandFrontmatter` when
    the block is not a mapping, a value is not a single-line string, or a
    `description`/`argument-hint` value contains a literal `"` (AC-5).
    @implements FR-0019:AC-5
    """
    yaml_mod = _require_yaml()
    try:
        parsed = yaml_mod.safe_load(block_text)
    except yaml_mod.YAMLError as e:
        raise _MalformedCommandFrontmatter(f"invalid YAML ({e})") from None
    if not isinstance(parsed, dict):
        raise _MalformedCommandFrontmatter("frontmatter block is not a mapping")

    meta: dict[str, str] = {}
    for key in _COMMAND_META_KEYS:
        if key not in parsed:
            continue
        value = parsed[key]
        if not isinstance(value, str) or "\n" in value:
            raise _MalformedCommandFrontmatter(
                f"'{key}' value is not a single-line string"
            )
        if key in _COMMAND_META_QUOTED_KEYS and '"' in value:
            raise _MalformedCommandFrontmatter(f"'{key}' value contains a '\"'")
        meta[key] = value

    for key in parsed:
        if key not in _COMMAND_META_KEYS:
            warn(f"{label}: unknown frontmatter key '{key}' ignored")
    return meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def die(msg: str) -> None:
    safe_print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    safe_print(f"WARN: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    safe_print(f"-> {msg}")


def validate_slug(name: str) -> None:
    if not SLUG_RE.match(name):
        die(
            f"Invalid project name: '{name}'. "
            "Must match [a-z0-9]([a-z0-9-]*[a-z0-9])? "
            "(lowercase alphanumeric with optional hyphens, no leading/trailing hyphen)."
        )


def _probe_python(path: str) -> tuple[bool, bool]:
    """Return (is_python_311_plus, has_pyyaml) for the interpreter at `path`.

    The candidate is validated by running it rather than by trusting its name.
    On Windows `shutil.which("python3")` resolves to the Microsoft Store App
    Execution Alias stub under AppData/Local/Microsoft/WindowsApps, which is not
    an interpreter at all -- it prints an install advert and exits 49.
    """
    def ok(code: str) -> bool:
        try:
            completed = subprocess.run(
                [path, "-c", code], capture_output=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    if not ok("import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"):
        return (False, False)
    return (True, ok("import yaml"))


def find_python() -> str:
    """Return the path to a working Python 3.11+ interpreter, or die trying.

    `sys.executable` is preferred: the interpreter already running bootstrap has
    provably imported everything bootstrap needs. The PATH probe is only a
    fallback, and every candidate is validated so a stub can never win. An
    interpreter that has pyyaml beats one that does not, but a bare Python 3 is
    still returned so `check_pyyaml` can emit its actionable install hint
    instead of a misleading "python is required".
    """
    candidates: list[str] = []
    if sys.executable:
        candidates.append(sys.executable)
    for name in ("python3", "python"):
        path = shutil.which(name)
        if path and path not in candidates:
            candidates.append(path)

    fallback = ""
    for candidate in candidates:
        is_py3, has_yaml = _probe_python(candidate)
        if is_py3 and has_yaml:
            return candidate
        if is_py3 and not fallback:
            fallback = candidate

    if fallback:
        return fallback
    die("python 3.11+ is required (for the spec indexer)")
    return ""  # unreachable


def check_pyyaml(python: str) -> None:
    try:
        subprocess.run(
            [python, "-c", "import yaml"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        die("pyyaml is required. Install with: pip install pyyaml")


def copy_template(src: Path, dst: Path) -> None:
    """Copy the template directory tree, excluding .git and __pycache__."""
    for item in src.iterdir():
        if item.name in (".git", "__pycache__"):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc",
            ))
        else:
            shutil.copy2(item, target)


def substitute_description(agents_md: Path, description: str) -> None:
    """Replace the description marker in AGENTS.md."""
    text = agents_md.read_text(encoding="utf-8")
    marker = "<<REPLACE: ONE_PARAGRAPH_PROJECT_DESCRIPTION>>"
    if marker not in text:
        warn(f"Marker '{marker}' not found in AGENTS.md -- already filled?")
    else:
        text = text.replace(marker, description)

    text = "\n".join(
        line for line in text.splitlines()
        if not line.startswith("Example (replace, then delete this line):")
    )
    if not text.endswith("\n"):
        text += "\n"
    # @implements FR-0019:AC-1
    agents_md.write_text(text, encoding="utf-8", newline="\n")


def inject_stack(agents_md: Path, stack: str) -> None:
    """Inject stack-specific conventions into AGENTS.md."""
    conventions = {
        "python": textwrap.dedent("""\
            - Language: Python 3.11+, type hints required
            - Test runner: `pytest`
            - Lint/format: `ruff check .` and `ruff format --check .`
            - Commit style: Conventional Commits, scope = FR ID (e.g., `feat(FR-0013): add canonical visit mapper`)
            - PRs must reference all FR IDs they touch in the title"""),
        "node": textwrap.dedent("""\
            - Language: TypeScript (strict mode), Node 20+
            - Test runner: `vitest` (or `jest` — pick one and document)
            - Lint/format: `eslint .` and `prettier --check .`
            - Commit style: Conventional Commits, scope = FR ID (e.g., `feat(FR-0013): add canonical visit mapper`)
            - PRs must reference all FR IDs they touch in the title"""),
    }

    text = agents_md.read_text(encoding="utf-8")
    marker = "<<REPLACE: PROJECT_CONVENTIONS>>"
    if marker in text:
        text = text.replace(marker, conventions[stack])
        out_lines: list[str] = []
        skipping = False
        for line in text.splitlines():
            if line.startswith("Examples (replace with real values, then delete this block):"):
                skipping = True
                continue
            if skipping:
                if line.startswith("- "):
                    continue
                if line.strip() == "":
                    skipping = False
            out_lines.append(line)
        text = "\n".join(out_lines)

    if not text.endswith("\n"):
        text += "\n"
    # @implements FR-0019:AC-1
    agents_md.write_text(text, encoding="utf-8", newline="\n")


def _render_enabled_cursor_rule(text: str) -> str:
    """Pure transform: strip the DISABLED_BY_DEFAULT wrapper from a Cursor
    rule's text. The sole core of `enable_cursor_rule`, factored out so
    `--upgrade` can render a stack-injected rule from the template's current
    text in memory, the same way create renders it on disk (FR-0020 AC-2).
    """
    text = text.replace(
        "# DISABLED_BY_DEFAULT: bootstrap.sh enables this for --stack python\n", ""
    )
    text = text.replace(
        "# DISABLED_BY_DEFAULT: bootstrap.sh enables this for --stack node\n", ""
    )
    text = text.replace("<!--\n", "", 1)
    text = text.replace("\n-->", "", 1)
    return text


def enable_cursor_rule(rule_path: Path) -> None:
    """Remove the DISABLED_BY_DEFAULT wrapper from a Cursor rule file on disk."""
    if not rule_path.exists():
        warn(f"Cursor rule file not found: {rule_path}")
        return
    text = rule_path.read_text(encoding="utf-8")
    text = _render_enabled_cursor_rule(text)
    # @implements FR-0019:AC-1
    rule_path.write_text(text, encoding="utf-8", newline="\n")


_CI_JOB_MARKERS = {"python": "python-tests:", "node": "node-tests:"}


def _render_uncommented_ci_job(text: str, stack: str) -> tuple[str, bool]:
    """Pure transform: uncomment the matching CI job block. Returns
    `(rendered_text, found)`; the sole core of `uncomment_ci_job`, factored
    out so `--upgrade` can render agent-gates.yml from the template's current
    text in memory (FR-0020 AC-2).
    """
    marker = _CI_JOB_MARKERS[stack]

    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    found = False

    for line in lines:
        stripped = re.sub(r"^\s*#\s*", "", line)
        if not in_block and stripped.startswith(marker):
            in_block = True
            found = True
        if in_block:
            # A comment-only line ("#") separates the two job blocks, so it has
            # to terminate the block as well as a truly blank line -- otherwise
            # uncommenting python-tests bleeds straight into node-tests and the
            # project ships a job for a stack it does not have.
            if line.strip() in ("", "#"):
                in_block = False
                out.append(line)
                continue
            if line.lstrip().startswith("#"):
                out.append(re.sub(r"^(\s*)#\s?", r"\1", line, count=1))
            else:
                out.append(line)
        else:
            out.append(line)

    return "\n".join(out) + "\n", found


def uncomment_ci_job(workflow_path: Path, stack: str) -> None:
    """Uncomment the matching CI job block in agent-gates.yml, on disk."""
    text = workflow_path.read_text(encoding="utf-8")
    rendered, found = _render_uncommented_ci_job(text, stack)
    if not found:
        marker = _CI_JOB_MARKERS[stack]
        warn(f"'{marker}' block not found in agent-gates.yml -- skipping CI uncomment")

    # @implements FR-0019:AC-1
    workflow_path.write_text(rendered, encoding="utf-8", newline="\n")


def generate_commands(target: Path) -> int:
    """Generate self-contained .claude/commands/ and .cursor/commands/
    from the canonical .agent-team/commands/ sources.

    Each source may open with its own YAML frontmatter block holding the
    metadata `COMMAND_META` used to hold centrally (FR-0019 AC-2); this
    function parses it, strips it (with the one blank line that follows) from
    the body, and renders the wrapper frontmatter from its keys with the same
    key order and quoting the retired dict used (FR-0019 AC-3). A source that
    does not open with `---` falls back to today's unknown-name behaviour: no
    argument hint and a generic description.

    A malformed block (FR-0019 AC-5) prints one warn line naming the file and
    the cause, writes neither wrapper for that command, leaves any existing
    wrapper untouched, and does not count the command. An unknown key warns
    and is ignored; the wrappers are still generated.

    Returns the number of commands generated.
    """
    canonical_dir = target / ".agent-team" / "commands"
    claude_dir = target / ".claude" / "commands"
    cursor_dir = target / ".cursor" / "commands"
    claude_dir.mkdir(parents=True, exist_ok=True)
    cursor_dir.mkdir(parents=True, exist_ok=True)

    if not canonical_dir.exists():
        warn(f"{canonical_dir} not found; skipping command generation")
        return 0

    generated = 0
    for src in sorted(canonical_dir.glob("*.md")):
        name = src.stem
        text = src.read_text(encoding="utf-8")

        # @implements FR-0019:AC-3
        # @implements FR-0019:AC-5
        try:
            split = _split_command_source(text)
            if split is None:
                meta: dict[str, str] = {}
                body = text.strip()
            else:
                block_text, raw_body = split
                meta = _parse_command_meta(block_text, str(src))
                body = raw_body.strip()
        except _MalformedCommandFrontmatter as e:
            warn(f"{src}: malformed frontmatter block ({e.cause}) -- skipping")
            continue

        desc = meta.get("description", f"Run the {name} command.")
        hint = meta.get("argument-hint", "")

        # Shared keys (both harnesses).
        base_lines = ["---", f'description: "{desc}"']
        if hint:
            base_lines.append(f'argument-hint: "{hint}"')

        # Claude-only keys. Cursor selects models/tools through its own config,
        # so `model`/`effort`/`allowed-tools` are emitted into the .claude
        # variant only. `allowed-tools` is an additive pre-approval grant, not a
        # restriction (unlisted tools still follow the session's permission
        # rules), so it is convenience, not a security boundary.
        claude_lines = list(base_lines)
        if meta.get("model"):
            claude_lines.append(f"model: {meta['model']}")
        if meta.get("effort"):
            claude_lines.append(f"effort: {meta['effort']}")
        if meta.get("allowed-tools"):
            claude_lines.append(f"allowed-tools: {meta['allowed-tools']}")
        claude_lines.append("---")
        base_lines.append("---")

        claude_fm = "\n".join(claude_lines)
        cursor_fm = "\n".join(base_lines)

        # The `---` block must open on line 1 or the harness may fail to parse
        # the frontmatter (behaviour with leading content is undocumented), so
        # the "generated" notice follows the closing `---` rather than leading.
        gen_note = (
            f"<!-- Generated from .agent-team/commands/{src.name} — "
            f"do not edit by hand. -->"
        )

        claude_content = f"{claude_fm}\n{gen_note}\n\n{body}\n"
        # @implements FR-0019:AC-1
        (claude_dir / src.name).write_text(
            claude_content, encoding="utf-8", newline="\n"
        )

        cursor_body = body.replace("$ARGUMENTS", "{{args}}")
        cursor_content = f"{cursor_fm}\n{gen_note}\n\n{cursor_body}\n"
        # @implements FR-0019:AC-1
        (cursor_dir / src.name).write_text(
            cursor_content, encoding="utf-8", newline="\n"
        )
        generated += 1

    return generated


def validate_profiles(profile_names: list[str]) -> list[str]:
    """Validate that each profile name corresponds to a directory in profiles/."""
    valid = []
    for name in profile_names:
        profile_dir = PROFILES_ROOT / name
        if not profile_dir.is_dir():
            available = [
                d.name for d in PROFILES_ROOT.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ] if PROFILES_ROOT.is_dir() else []
            die(
                f"Unknown profile: '{name}'. "
                f"Available profiles: {', '.join(available) or '(none)'}"
            )
        valid.append(name)
    return valid


def apply_profiles(target: Path, profile_names: list[str]) -> None:
    """Overlay profile-specific files onto a bootstrapped project."""
    for name in profile_names:
        profile_dir = PROFILES_ROOT / name
        info(f"Applying profile: {name}")

        if name == "phipa":
            hook_src = profile_dir / "phi_regex_check.py"
            if hook_src.exists():
                hooks_dir = target / ".agent-team" / "hooks"
                hooks_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(hook_src, hooks_dir / "phi_regex_check.py")
                info("  Copied phi_regex_check.py → .agent-team/hooks/")

            hygiene_src = profile_dir / "phi_hygiene_block.md"
            if hygiene_src.exists():
                agents_md = target / "AGENTS.md"
                if agents_md.exists():
                    agents_text = agents_md.read_text(encoding="utf-8")
                    hygiene_block = hygiene_src.read_text(encoding="utf-8").strip()
                    marker = "## Universal rules"
                    if marker in agents_text:
                        agents_text = agents_text.replace(
                            marker,
                            hygiene_block + "\n\n" + marker,
                        )
                    else:
                        agents_text = agents_text.rstrip() + "\n\n" + hygiene_block + "\n"
                    # @implements FR-0019:AC-1
                    agents_md.write_text(agents_text, encoding="utf-8", newline="\n")
                    info("  Appended PHI hygiene block to AGENTS.md")

            overlay_src = profile_dir / "settings_overlay.json"
            if overlay_src.exists():
                settings_path = target / ".claude" / "settings.json"
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                if settings_path.exists():
                    base = json.loads(settings_path.read_text(encoding="utf-8"))
                else:
                    base = {}
                overlay = json.loads(overlay_src.read_text(encoding="utf-8"))
                base = _merge_json(base, overlay)
                # LF bytes: write_text would emit CRLF on Windows, so a fresh
                # profiled project's settings.json would never byte-equal the
                # template's even when the merge (AC-11) leaves it unchanged.
                settings_path.write_bytes(
                    (json.dumps(base, indent=2) + "\n").encode("utf-8")
                )
                info("  Merged settings_overlay.json → .claude/settings.json")
        else:
            readme = profile_dir / "README.md"
            if readme.exists():
                info(f"  Profile '{name}' recognized (see {readme})")
            else:
                warn(f"  Profile '{name}' has no apply logic yet — skipped")

    if profile_names:
        safe_print(f"\n  Profiles applied: {', '.join(profile_names)}")


def _merge_json(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base.

    Lists are merged idempotently: an overlay item that is already present in
    the base list (structural equality) is not appended again, so applying a
    profile whose hook entry the template already wires -- as
    template/.claude/settings.json does for phi_regex_check.py -- yields exactly
    one copy. Distinct items are still appended in overlay order.
    @implements FR-0001:AC-11
    """
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = _merge_json(base[key], value)
        elif key in base and isinstance(base[key], list) and isinstance(value, list):
            merged = list(base[key])
            for item in value:
                if item not in merged:
                    merged.append(item)
            base[key] = merged
        else:
            base[key] = value
    return base


# ---------------------------------------------------------------------------
# Profile records: project-local file + registry field
# ---------------------------------------------------------------------------

def _require_yaml():
    """Import pyyaml or die with the standard install hint."""
    try:
        import yaml  # noqa: F811
    except ImportError:
        die("pyyaml is required. Install with: pip install pyyaml")
    return yaml


def dedupe_profiles(profile_names) -> list[str]:
    """Order-preserving de-duplication of profile names (first occurrence wins)."""
    seen: set[str] = set()
    out: list[str] = []
    for name in profile_names:
        name = str(name)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _yaml_flow_list(items) -> str:
    """Render a list of plain scalars as a YAML flow sequence: `[a, b]` / `[]`."""
    return "[" + ", ".join(str(i) for i in items) + "]"


def write_profile_record(project: Path, profile_names) -> Path:
    """Write the project-local profile record, listing exactly `profile_names`.

    Always LF; comments explain the file's purpose and how to backfill it.
    @implements FR-0001:AC-1
    """
    record = project / PROFILE_RECORD_REL
    record.parent.mkdir(parents=True, exist_ok=True)
    names = dedupe_profiles(profile_names)
    text = (
        "# Compliance profiles applied to this project (written by scripts/bootstrap.py).\n"
        "# `bootstrap.py --upgrade` reads this file to sync profile-owned files from the\n"
        "# hub's profiles/<name>/ instead of the template. To backfill or change it:\n"
        "#   python scripts/bootstrap.py --upgrade <project-path> --profile <name>\n"
        f"profiles: {_yaml_flow_list(names)}\n"
    )
    record.write_bytes(text.encode("utf-8"))
    return record


def read_profile_record(project: Path) -> list[str] | None:
    """Return the profile list from the project-local record, or None if absent.

    A malformed record is fatal rather than ignored: silently treating a
    profiled project as unprofiled is exactly the downgrade this FR prevents.
    @implements FR-0001:AC-2
    """
    record = project / PROFILE_RECORD_REL
    if not record.is_file():
        return None
    yaml = _require_yaml()
    try:
        data = yaml.safe_load(record.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        die(f"{PROFILE_RECORD_REL} is malformed: {e}")
        return None
    if not isinstance(data, dict):
        die(f"{PROFILE_RECORD_REL} must be a mapping with a 'profiles' key")
        return None
    return _coerce_profile_list(data.get("profiles"), PROFILE_RECORD_REL)


def _coerce_profile_list(raw, where: str) -> list[str]:
    """Normalise a `profiles:` value (None, scalar, or list) to a deduped list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        die(f"{where}: 'profiles' must be a list of profile names")
        return []
    return dedupe_profiles(raw)


def load_registry_entries(hub_root: Path) -> list[dict]:
    """hub/projects.yaml overlaid by hub/projects.local.yaml, keyed by name.

    Same merge as scripts/hub-index.py: a local entry with a shared name
    replaces that entry. Read-only; malformed files are warned about and
    skipped so an upgrade can still proceed on the project-local record.
    """
    yaml = _require_yaml()
    merged: dict[str, dict] = {}
    for fname in ("projects.yaml", "projects.local.yaml"):
        path = hub_root / "hub" / fname
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            warn(f"hub/{fname} is malformed ({e}); ignoring it for profile lookup")
            continue
        for entry in (data.get("projects") or []) if isinstance(data, dict) else []:
            if isinstance(entry, dict) and "name" in entry:
                merged[str(entry["name"])] = entry
    return list(merged.values())


def find_registry_entry(hub_root: Path, project: Path) -> dict | None:
    """Locate the registry entry for `project`: by resolved path, else by name."""
    project = project.resolve()
    entries = load_registry_entries(hub_root)
    for entry in entries:
        raw = entry.get("path")
        if not raw:
            continue
        p = Path(str(raw))
        if not p.is_absolute():
            p = hub_root / p
        try:
            if p.resolve() == project:
                return entry
        except OSError:
            continue
    for entry in entries:
        if str(entry.get("name")) == project.name:
            return entry
    return None


def registry_profiles(entry: dict | None) -> list[str] | None:
    """The `profiles:` field of a registry entry; None when the key is absent."""
    if entry is None or "profiles" not in entry:
        return None
    return _coerce_profile_list(entry.get("profiles"), f"registry entry '{entry.get('name')}'")


def resolve_profiles(project: Path, hub_root: Path) -> tuple[list[str], list[str]]:
    """Determine a project's profile set for --upgrade.

    Precedence: project-local record, then the registry entry (shared registry
    overlaid by the local one). Returns (profiles, notices); notices are printed
    by the caller. Disagreement between the two sources is surfaced, never
    silently resolved. Unknown names die via the same path as --profile.
    @implements FR-0001:AC-2
    """
    local = read_profile_record(project)
    entry = find_registry_entry(hub_root, project)
    reg = registry_profiles(entry)
    notices: list[str] = []

    if local is None:
        if reg:
            resolved = reg
            notices.append(
                f"No {PROFILE_RECORD_REL} in project; profile set taken from the "
                f"registry entry '{entry['name']}' ({_yaml_flow_list(reg)}). "
                f"Persist it with: --upgrade <path> --profile {' --profile '.join(reg)}"
            )
        else:
            resolved = []
            notices.append(
                f"Profile state is unrecorded for this project (no {PROFILE_RECORD_REL} "
                "and no `profiles:` on its registry entry); treating it as unprofiled. "
                "If it was bootstrapped with a compliance profile, backfill with: "
                "python scripts/bootstrap.py --upgrade <project-path> --profile <name>"
            )
    else:
        resolved = local
        if reg is not None and sorted(reg) != sorted(local):
            notices.append(
                f"{PROFILE_RECORD_REL} lists {_yaml_flow_list(local)} but the registry "
                f"entry '{entry['name']}' lists {_yaml_flow_list(reg)}; using the "
                "project-local record. Reconcile with: --upgrade <path> --profile <name>"
            )

    if resolved:
        resolved = validate_profiles(resolved)
    return resolved, notices


def resolve_stack(project: Path, hub_root: Path) -> tuple[str | None, list[str]]:
    """Resolve a project's stack for --upgrade's stack-injected file rendering.

    Reads the project's registry entry (`find_registry_entry`: resolved path,
    then name, `hub/projects.local.yaml` overlaid) and its `stack:` value.
    Returns `(None, [notice])` when the entry is absent (including an
    unreadable registry, which `load_registry_entries` already warns about and
    treats as "no entries") or its `stack:` is outside `python | node | none`
    -- the caller then treats the stack-injected paths as seed-only for this
    run rather than guessing which stack applies.
    @implements FR-0020:AC-2
    """
    entry = find_registry_entry(hub_root, project)
    if entry is None:
        notice = (
            "Project stack is unknown (no hub registry entry found for this "
            f"project); .cursor/rules/20-<stack>.mdc and {CI_WORKFLOW_REL} are "
            "left unchanged this run and reported as drift if they differ, "
            "not rendered for a stack. Register the project, or set its "
            "`stack:` field, to enable stack-aware upgrade."
        )
        return None, [notice]
    stack = entry.get("stack")
    if stack not in ("python", "node", "none"):
        notice = (
            f"Project stack is unknown (registry entry '{entry.get('name')}' "
            f"has stack: {stack!r}, not one of python|node|none); "
            f".cursor/rules/20-<stack>.mdc and {CI_WORKFLOW_REL} are left "
            "unchanged this run and reported as drift if they differ. Fix "
            "its `stack:` field to enable stack-aware upgrade."
        )
        return None, [notice]
    return stack, []


def profile_owned_files(profile_names, profiles_root: Path | None = None) -> dict[str, tuple[str, Path]]:
    """Return {project-relative POSIX path: (profile name, source file)} for the
    files the given profiles install. Later profiles win on a path collision.
    @implements FR-0001:AC-3
    """
    root = PROFILES_ROOT if profiles_root is None else profiles_root
    owned: dict[str, tuple[str, Path]] = {}
    for name in profile_names:
        for rel_path, src_rel in PROFILE_OWNED_FILES.get(name, {}).items():
            src = root / name / src_rel
            if not src.is_file():
                warn(f"Profile '{name}' source missing: {src} -- cannot sync {rel_path}")
                continue
            owned[Path(rel_path).as_posix()] = (name, src)
    return owned


def missing_profile_sources(profile_names, profiles_root: Path | None = None) -> list[tuple[str, str, Path]]:
    """Return [(project-relative POSIX path, profile name, absent source)] for
    every profile-owned path whose source file is missing under profiles/<name>/.

    Such a path is still profile-owned: it must be dropped from the sync plan
    (never compared against or synced from the template base copy) and
    reported as skipped.
    @implements FR-0001:AC-3
    """
    root = PROFILES_ROOT if profiles_root is None else profiles_root
    missing: list[tuple[str, str, Path]] = []
    for name in profile_names:
        for rel_path, src_rel in PROFILE_OWNED_FILES.get(name, {}).items():
            src = root / name / src_rel
            if not src.is_file():
                missing.append((Path(rel_path).as_posix(), name, src))
    return missing


def _yaml_scalar(value: str) -> str:
    """Render a string as a plain YAML scalar when unambiguous, else single-quoted."""
    plain = re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./:@+~-]*", value) is not None
    reserved = value.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
    numeric = re.fullmatch(r"[0-9.+-]+", value) is not None
    if plain and not reserved and not numeric:
        return value
    return "'" + value.replace("'", "''") + "'"


def format_registry_entry(
    name: str, path: str, created: str, stack: str, private: bool, profiles,
) -> str:
    """One `projects:` list item, keys in registry order, LF line endings.
    @implements FR-0001:AC-10
    """
    return (
        f"- name: {_yaml_scalar(name)}\n"
        f"  path: {_yaml_scalar(path)}\n"
        f"  created: '{created}'\n"
        f"  stack: {stack}\n"
        f"  private: {'true' if private else 'false'}\n"
        f"  profiles: {_yaml_flow_list(dedupe_profiles(profiles))}\n"
    )


def _count_registry_projects(text: str, yaml_path: Path) -> int:
    """Number of entries under `projects:` in registry text; die if unparsable."""
    yaml = _require_yaml()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        die(f"{yaml_path} is malformed: {e}")
    if data is None:
        return 0
    if not isinstance(data, dict):
        die(f"{yaml_path} is malformed: top level is not a mapping")
    projects = data.get("projects")
    if projects is None:
        return 0
    if not isinstance(projects, list):
        die(f"{yaml_path} is malformed: `projects:` is not a list")
    return len(projects)


def _write_registry_checked(yaml_path: Path, original: bytes | None, new_text: str, expected: int) -> None:
    """Write the registry, re-parse it, and die (restoring the original bytes)
    unless it now yields exactly `expected` projects. An edit that shadows or
    drops existing entries -- e.g. a second `projects:` key -- must never be
    left on disk, because scripts/hub-index.py would then see fewer projects.
    @implements FR-0001:AC-10
    """
    yaml = _require_yaml()
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_bytes(new_text.encode("utf-8"))
    problem = None
    try:
        data = yaml.safe_load(yaml_path.read_bytes().decode("utf-8"))
        projects = data.get("projects") if isinstance(data, dict) else None
        if not isinstance(projects, list):
            problem = "`projects:` is missing or not a list"
        elif len(projects) != expected:
            problem = f"expected {expected} project(s) after the edit, parsed {len(projects)}"
    except yaml.YAMLError as e:
        problem = f"result is malformed: {e}"
    if problem is not None:
        if original is None:
            yaml_path.unlink(missing_ok=True)
        else:
            yaml_path.write_bytes(original)
        die(f"Refusing to edit {yaml_path}: {problem}; original bytes restored")


# The `projects:` key line, optionally a literal `[]` and/or a trailing
# comment. `\r?` before `$` so the key is also found in a CRLF file (re.M `$`
# only matches before `\n`); the CR, if any, is captured and put back.
_PROJECTS_KEY_RE = re.compile(r"^projects:[ \t]*(\[[ \t]*\])?[ \t]*(#[^\r\n]*)?(\r?)$", re.M)


def append_registry_entry(yaml_path: Path, entry_text: str) -> None:
    """Append one list item under `projects:` after the file's last byte.

    Existing bytes -- comments, ordering, line endings (LF or CRLF) -- are left
    untouched; the only edits are a trailing newline if the file lacks one,
    opening up a literal `projects: []` so it can take a block item, or adding
    `projects:` when the key is absent. The appended entry is always LF.
    Binary I/O so no platform ever injects CRLF. After writing, the file is
    re-parsed and must yield exactly one more project than before.
    @implements FR-0001:AC-10
    """
    original: bytes | None = None
    if yaml_path.is_file():
        original = yaml_path.read_bytes()
        text = original.decode("utf-8")
    else:
        text = REGISTRY_HEADER + "projects:\n"
    before = _count_registry_projects(text, yaml_path)
    if text and not text.endswith("\n"):
        text += "\n"
    m = _PROJECTS_KEY_RE.search(text)
    if m is None:
        text += "projects:\n"
    elif m.group(1):
        comment = f"  {m.group(2)}" if m.group(2) else ""
        text = text[: m.start()] + "projects:" + comment + m.group(3) + text[m.end():]
    _write_registry_checked(yaml_path, original, text + entry_text, before + 1)


def set_registry_profiles(yaml_path: Path, project_name: str, profiles) -> bool:
    """Set `profiles:` on one existing entry by editing a single line.

    Locates the entry as a unique column-0 `- name: <project_name>` item, then
    replaces its `profiles:` line if present, else inserts one after `private:`
    (else after the entry's last non-blank line). Every other byte is preserved.
    Returns False -- and writes nothing -- when the entry is absent or ambiguous.
    @implements FR-0001:AC-7
    """
    if not yaml_path.is_file():
        return False
    original = yaml_path.read_bytes()
    text = original.decode("utf-8")
    before = _count_registry_projects(text, yaml_path)
    # Split on LF only; a CRLF file leaves a trailing CR on every line. Match
    # against the CR-stripped line and put the CR back on any line we rewrite,
    # so existing bytes survive exactly. An inserted line is LF-only (AC-10).
    lines = text.split("\n")

    def core(ln: str) -> str:
        return ln[:-1] if ln.endswith("\r") else ln

    def ending(ln: str) -> str:
        return "\r" if ln.endswith("\r") else ""

    name_re = re.compile(
        rf"^- name:[ \t]+(['\"]?){re.escape(project_name)}\1[ \t]*(#.*)?$"
    )
    starts = [i for i, ln in enumerate(lines) if name_re.match(core(ln))]
    if len(starts) != 1:
        return False
    start = starts[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = core(lines[j])
        if ln.strip() == "":
            continue
        if not ln[0].isspace():
            end = j
            break

    new_line = f"  profiles: {_yaml_flow_list(dedupe_profiles(profiles))}"
    key_re = re.compile(r"^([ \t]+profiles:)[^#]*(#.*)?$")
    private_re = re.compile(r"^[ \t]+private:")
    for j in range(start + 1, end):
        m = key_re.match(core(lines[j]))
        if m:
            replacement = new_line + (f"  {m.group(2)}" if m.group(2) else "") + ending(lines[j])
            if lines[j] == replacement:
                return True
            lines[j] = replacement
            break
    else:
        insert_at = None
        for j in range(start + 1, end):
            if private_re.match(core(lines[j])):
                insert_at = j + 1
                break
        if insert_at is None:
            insert_at = start + 1
            for j in range(start + 1, end):
                if core(lines[j]).strip() != "":
                    insert_at = j + 1
        lines.insert(insert_at, new_line)

    _write_registry_checked(yaml_path, original, "\n".join(lines), before)
    return True


def backfill_registry(hub_root: Path, project: Path, profiles) -> None:
    """Update the project's registry entry with `profiles:`, or print the line.
    @implements FR-0001:AC-7
    """
    entry = find_registry_entry(hub_root, project)
    line = f"  profiles: {_yaml_flow_list(dedupe_profiles(profiles))}"
    if entry is None:
        safe_print(
            "  ! No hub registry entry found for this project (not registered, or\n"
            "    --no-register). If it should carry the profile set there, add to its\n"
            f"    entry in hub/projects.yaml:\n      {line}"
        )
        return
    name = str(entry["name"])
    touched = False
    for fname in ("projects.yaml", "projects.local.yaml"):
        yaml_path = hub_root / "hub" / fname
        if yaml_path.is_file() and set_registry_profiles(yaml_path, name, profiles):
            info(f"Registry hub/{fname} entry '{name}': {line.strip()}")
            touched = True
    if not touched:
        safe_print(
            f"  ! Could not locate a unique '- name: {name}' entry in hub/projects.yaml;\n"
            f"    add this line to it by hand:\n      {line}"
        )


def overlay_missing_entries(settings: dict, overlay: dict) -> list[str]:
    """Describe the parts of a profile settings overlay absent from `settings`.

    Structural containment, not byte equality: a hook entry counts as present
    when some entry under the same event contains all of its keys/values (the
    project may have added e.g. a timeout). Empty list means fully present.
    @implements FR-0001:AC-5
    """
    missing: list[str] = []
    for key, value in overlay.items():
        if key == "hooks" and isinstance(value, dict):
            have = settings.get("hooks")
            have = have if isinstance(have, dict) else {}
            for event, entries in value.items():
                present = have.get(event)
                present = present if isinstance(present, list) else []
                for entry in entries if isinstance(entries, list) else [entries]:
                    if not any(_json_contains(p, entry) for p in present):
                        missing.append(f"hooks.{event}: {_describe_hook_entry(entry)}")
        elif not _json_contains(settings.get(key), value):
            missing.append(f"{key}: {json.dumps(value, sort_keys=True)}")
    return missing


def _json_contains(container, part) -> bool:
    """True when every key/value (dict) or item (list) of `part` is in `container`."""
    if isinstance(part, dict):
        return isinstance(container, dict) and all(
            k in container and _json_contains(container[k], v) for k, v in part.items()
        )
    if isinstance(part, list):
        return isinstance(container, list) and all(
            any(_json_contains(c, p) for c in container) for p in part
        )
    return container == part


def _describe_hook_entry(entry) -> str:
    if isinstance(entry, dict):
        matcher = entry.get("matcher", "*")
        hooks = entry.get("hooks") if isinstance(entry.get("hooks"), list) else []
        commands = [h.get("command", "?") for h in hooks if isinstance(h, dict)]
        return f"matcher={matcher!r} command(s)={commands}"
    return json.dumps(entry, sort_keys=True)


def agents_block_state(agents_text: str, block_text: str) -> tuple[str, str]:
    """Classify a profile's AGENTS.md block: 'present' | 'differs' | 'missing'.

    Returns (state, project_section) where project_section is the text of the
    project's own section under the block's heading (for the 'differs' diff).
    @implements FR-0001:AC-6
    """
    block = block_text.replace("\r\n", "\n").strip()
    text = agents_text.replace("\r\n", "\n")
    if block in text:
        return "present", block
    heading = block.splitlines()[0].strip() if block else ""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if heading and ln.strip() == heading:
            section = [ln]
            for nxt in lines[i + 1:]:
                if nxt.startswith("## "):
                    break
                section.append(nxt)
            return "differs", "\n".join(section).strip()
    return "missing", ""


def register_project(
    hub_root: Path,
    project_name: str,
    target: Path,
    stack: str,
    private: bool,
    python: str,
    profiles=(),
) -> None:
    """Append a project entry to hub/projects.yaml.

    Append-only: the registry is hand-annotated (inline comments explain why
    entries are private or submodules), so it is never round-tripped through
    yaml.safe_dump, which would drop every comment and, on Windows, emit CRLF.
    The existing file is used only to detect a duplicate name.
    @implements FR-0001:AC-10
    """
    yaml = _require_yaml()
    yaml_path = hub_root / "hub" / "projects.yaml"
    projects: list = []
    if yaml_path.is_file():
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            die(f"hub/projects.yaml is malformed: {e}")
            return
        projects = list(data.get("projects") or []) if isinstance(data, dict) else []

    for p in projects:
        if isinstance(p, dict) and p.get("name") == project_name:
            warn(
                f"Project '{project_name}' already registered at {p.get('path')}; "
                "leaving entry unchanged."
            )
            return

    try:
        rel = target.resolve().relative_to(hub_root.resolve())
        # The registry is read on every platform, so always emit POSIX
        # separators. str() on a Windows Path yields `projects\foo`, which
        # contradicts every pre-existing entry and cannot be resolved from a
        # POSIX checkout of the same repo.
        path_field = rel.as_posix()
    except ValueError:
        path_field = target.resolve().as_posix()

    entry = format_registry_entry(
        name=project_name,
        path=path_field,
        created=datetime.date.today().isoformat(),
        stack=stack,
        private=private,
        profiles=profiles,
    )
    append_registry_entry(yaml_path, entry)


def git_init(target: Path) -> None:
    """Initialize a git repo with an initial commit."""
    if not shutil.which("git"):
        warn("git not found; skipping git init")
        return

    info("Initializing git repo")
    try:
        subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            cwd=target, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "init", "-q"],
            cwd=target, check=True, capture_output=True,
        )

    subprocess.run(["git", "add", "-A"], cwd=target, check=True, capture_output=True)

    try:
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-q",
             "-m", "Initial commit from agent-team-template"],
            cwd=target, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        warn(
            "Initial commit skipped -- configure git user.name/user.email "
            "and commit manually."
        )


# ---------------------------------------------------------------------------
# Upgrade mode
# ---------------------------------------------------------------------------

def files_in_dir(base: Path, rel_dir: str) -> dict[str, Path]:
    """Return {relative-path: absolute-path} for all files under base/rel_dir.

    Skips Python bytecode caches, mirroring the ignore list in `copy_template`.
    They are not template content and they are not UTF-8, so running the
    template's own test suite in place would otherwise leave `.pyc` files that
    crash `--upgrade` when it reads every candidate as text.
    """
    root = base / rel_dir
    if not root.exists():
        return {}
    result: dict[str, Path] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix == ".pyc" or "__pycache__" in p.parts:
            continue
        result[str(p.relative_to(base))] = p
    return result


def diff_content(
    old_content: str, new_content: str, label: str, tofile_prefix: str = "template",
) -> str:
    """Return a unified-diff-style summary of changes (project -> source)."""
    import difflib
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines, fromfile=f"project/{label}", tofile=f"{tofile_prefix}/{label}"
    )
    return "".join(diff)


def _copy_bytes(source_bytes: bytes, project_file: Path) -> None:
    """Write already-resolved sync content into the project byte-for-byte.

    `write_text` would translate LF to CRLF on Windows, so a synced file would
    never byte-equal its source there (AC-8 requires that it does) and would
    show as a whole-file diff to git with core.autocrlf=false. The caller
    already holds the bytes -- read from disk, or rendered in memory for a
    stack-injected file or a `.gitattributes` merge (FR-0020 AC-2, AC-5) --
    so there is nothing to read here.
    """
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_bytes(source_bytes)


def build_sync_plan(profiles) -> dict[str, tuple[Path, str | None]]:
    """Return {project-relative POSIX path: (source file, owning profile or None)}.

    Template infrastructure files first; then each resolved profile's owned
    files override the template entry for the same path (or add a path the
    template lacks), so a profile-owned file is only ever compared against and
    synced from profiles/<name>/. The project-local profile record is removed
    from the plan unconditionally: it is project state, so even if a future
    template shipped one it must never be offered or overwritten.
    @implements FR-0001:AC-3
    @implements FR-0001:AC-9
    """
    template_files: dict[str, Path] = {}
    for infra_dir in INFRA_DIRS:
        template_files.update(files_in_dir(TEMPLATE_ROOT, infra_dir))

    # Root-level infrastructure files (INFRA_DIRS only walks subdirectories).
    for rel_name in INFRA_ROOT_FILES:
        candidate = TEMPLATE_ROOT / rel_name
        if candidate.is_file():
            template_files[rel_name] = candidate

    # Also include specs/_template/
    template_files.update(files_in_dir(TEMPLATE_ROOT, "specs/_template"))

    plan: dict[str, tuple[Path, str | None]] = {
        Path(rel).as_posix(): (src, None) for rel, src in template_files.items()
    }
    plan.pop(PROFILE_RECORD_REL, None)
    for rel_posix, (profile_name, src) in profile_owned_files(profiles).items():
        plan[rel_posix] = (src, profile_name)
    # A profile-owned path whose profile source is absent is dropped outright:
    # the template entry for that path must never survive into a profiled
    # project's plan, in any mode. run_upgrade reports it as skipped.
    for rel_posix, _profile_name, _src in missing_profile_sources(profiles):
        plan.pop(rel_posix, None)
    return plan


def _gitattributes_merge(
    project_text: str, template_block: str
) -> tuple[str | None, str]:
    """Compute a project's `.gitattributes` content after syncing the managed
    block, given its current text and the template's current block (its
    whole `template/.gitattributes` file, BEGIN..END, FR-0020 AC-4).

    Returns `(new_text, state)`. `state` is one of:
      "inserted" -- no BEGIN and no END line found anywhere; the template's
                    block is inserted at the top, followed by one blank line,
                    then every existing line unchanged and in order.
      "replaced" -- exactly one BEGIN line and exactly one END line, BEGIN
                    before END; the span from BEGIN through END is replaced
                    by the template's block, byte-for-byte outside it.
                    `new_text == project_text` is a legal result (the block is
                    already current); the caller does not report that as a
                    change. A well-formed block whose line terminator is
                    `\r\n` (a CRLF checkout) matches here too and is replaced
                    in place with the template's LF block; it is never
                    treated as absent.
      "damaged"  -- anything else: exactly one marker present, BEGIN and END
                    reversed, or either marker duplicated. `new_text` is
                    `None`: nothing is computed, and the caller reports drift
                    instead of touching the file.

    Detection is line-wise and terminator-tolerant: each line is compared
    with a trailing `\r\n` or `\n` stripped against the BEGIN/END marker
    text (which is itself stripped the same way), so a marker line survives
    regardless of the file's line ending.
    @implements FR-0020:AC-5
    """
    begin_line = GITATTRIBUTES_BLOCK_BEGIN.rstrip("\r\n")
    end_line = GITATTRIBUTES_BLOCK_END.rstrip("\r\n")
    lines = project_text.splitlines(keepends=True)
    begin_positions = [
        i for i, ln in enumerate(lines) if ln.rstrip("\r\n") == begin_line
    ]
    end_positions = [
        i for i, ln in enumerate(lines) if ln.rstrip("\r\n") == end_line
    ]
    if not begin_positions and not end_positions:
        return template_block + "\n" + project_text, "inserted"
    if (
        len(begin_positions) == 1
        and len(end_positions) == 1
        and begin_positions[0] < end_positions[0]
    ):
        begin_i, end_i = begin_positions[0], end_positions[0]
        new_text = (
            "".join(lines[:begin_i])
            + template_block
            + "".join(lines[end_i + 1 :])
        )
        return new_text, "replaced"
    return None, "damaged"


def _gitattributes_duplicate_lines(text: str) -> list[str]:
    """Lines outside `text`'s managed block that are byte-identical to a line
    inside it (FR-0020 AC-5's duplicate note). `text` must already contain a
    well-formed block (the caller only calls this for "inserted"/"replaced").
    """
    begin_idx = text.find(GITATTRIBUTES_BLOCK_BEGIN)
    end_idx = text.find(GITATTRIBUTES_BLOCK_END)
    if begin_idx == -1 or end_idx == -1:
        return []
    block_lines = {
        ln
        for ln in text[begin_idx : end_idx + len(GITATTRIBUTES_BLOCK_END)].splitlines()
        if ln.strip()
    }
    outside = (
        text[:begin_idx].splitlines()
        + text[end_idx + len(GITATTRIBUTES_BLOCK_END) :].splitlines()
    )
    found: list[str] = []
    for ln in outside:
        if ln.strip() and ln in block_lines and ln not in found:
            found.append(ln)
    return found


def verify_profile_assets(project: Path, profiles, auto_yes: bool) -> tuple[list[str], list[str], list[str]]:
    """Check each profile's settings overlay and AGENTS.md block; report only.

    Returns (overlay_missing, block_missing, block_differs) as printable lines.
    Neither .claude/settings.json nor AGENTS.md is written here or anywhere in
    --upgrade (AGENTS.md stays in UPGRADE_EXCLUDE; settings.json is drift-warn
    only). In interactive mode a differing block is shown as a diff.
    @implements FR-0001:AC-5
    @implements FR-0001:AC-6
    """
    overlay_missing: list[str] = []
    block_missing: list[str] = []
    block_differs: list[str] = []

    settings_path = project / ".claude" / "settings.json"
    settings: dict = {}
    settings_ok = True
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            settings = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError as e:
            warn(f".claude/settings.json is not valid JSON ({e}); overlay check skipped")
            settings_ok = False

    agents_md = project / "AGENTS.md"
    agents_text = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""

    for name in profiles:
        profile_dir = PROFILES_ROOT / name

        overlay_src = profile_dir / PROFILE_SETTINGS_OVERLAY
        if overlay_src.is_file() and settings_ok:
            overlay = json.loads(overlay_src.read_text(encoding="utf-8"))
            for missing in overlay_missing_entries(settings, overlay):
                overlay_missing.append(f"{name}: {missing}")

        block_rel = PROFILE_AGENTS_BLOCK.get(name)
        block_src = profile_dir / block_rel if block_rel else None
        if block_src is not None and block_src.is_file():
            block_text = block_src.read_text(encoding="utf-8")
            state, section = agents_block_state(agents_text, block_text)
            if state == "missing":
                block_missing.append(f"{name}: {block_rel} (AGENTS.md)")
            elif state == "differs":
                block_differs.append(f"{name}: {block_rel} (AGENTS.md)")
                if not auto_yes:
                    safe_print(f"\n  PROFILE BLOCK DIFFERS: AGENTS.md ({name}) -- NOT changed")
                    safe_print("  " + "-" * 60)
                    diff_text = diff_content(
                        section + "\n", block_text.strip() + "\n", "AGENTS.md",
                        tofile_prefix=f"profile:{name}",
                    )
                    for line in diff_text.splitlines():
                        safe_print(f"  {line}")
                    safe_print("  " + "-" * 60)

    for line in overlay_missing:
        safe_print(f"  ! Profile overlay missing in .claude/settings.json -- NOT changed: {line}")
    for line in block_missing:
        safe_print(f"  ! Profile block missing in AGENTS.md -- NOT changed: {line}")
    if auto_yes:
        for line in block_differs:
            safe_print(f"  ! Profile block differs in AGENTS.md -- NOT changed: {line}")
    return overlay_missing, block_missing, block_differs


def run_upgrade(
    project_path: Path, auto_yes: bool, backfill_profiles: list[str] | None = None,
) -> None:
    """Propagate template (and profile) infrastructure changes to a project."""
    project = project_path.resolve()
    if not project.is_dir():
        die(f"Project path does not exist: {project}")
    if not (project / "AGENTS.md").exists():
        die(f"'{project}' does not look like an agent-team project (no AGENTS.md)")

    info(f"Upgrading project at: {project}")

    # Resolve the profile set: an explicit --profile backfills the record and
    # wins outright; otherwise read the project-local record with registry
    # fallback (AC-2).
    if backfill_profiles is not None:
        # @implements FR-0001:AC-7
        profiles = dedupe_profiles(validate_profiles(list(backfill_profiles)))
        write_profile_record(project, profiles)
        info(f"Recorded profile set in {PROFILE_RECORD_REL}: {_yaml_flow_list(profiles)}")
        backfill_registry(HUB_ROOT, project, profiles)
        notices: list[str] = []
    else:
        profiles, notices = resolve_profiles(project, HUB_ROOT)

    # Resolve the project's stack for AC-2's stack-injected file rendering.
    # @implements FR-0020:AC-2
    stack, stack_notices = resolve_stack(project, HUB_ROOT)
    notices = notices + stack_notices

    # @implements FR-0001:AC-8
    safe_print(f"Profiles: {', '.join(profiles) if profiles else '(none)'}")
    for notice in notices:
        safe_print(f"  ! {notice}")

    updated: list[str] = []
    added: list[str] = []
    skipped: list[str] = []
    drifted: list[str] = []

    plan = build_sync_plan(profiles)

    # Seed-only paths for this run: never overwritten when present and
    # different, reported as drift instead (AC-1). Grows with this run's
    # unresolved stack-injected paths (AC-2); a damaged `.gitattributes`
    # block joins it below (AC-5). SEED_ONLY_FILES itself is never mutated.
    seed_only = set(SEED_ONLY_FILES)
    if stack is None:
        seed_only |= set(STACK_FILES_UNRESOLVED)

    # Pre-rendered sync sources for this run, keyed by project-relative path:
    # a stack-injected file's rendered text (AC-2) or a `.gitattributes`
    # merge result (AC-5). When a path is present here its bytes are used for
    # both comparison and writing, instead of reading the plan's source file.
    rendered_sources: dict[str, bytes] = {}

    # @implements FR-0020:AC-2
    if stack in ("python", "node"):
        rule_rel = STACK_RULE_REL[stack]
        if rule_rel in plan:
            src_path, _owner = plan[rule_rel]
            rendered_sources[rule_rel] = _render_enabled_cursor_rule(
                src_path.read_bytes().decode("utf-8")
            ).encode("utf-8")
        if CI_WORKFLOW_REL in plan:
            src_path, _owner = plan[CI_WORKFLOW_REL]
            rendered_text, _found = _render_uncommented_ci_job(
                src_path.read_bytes().decode("utf-8"), stack
            )
            rendered_sources[CI_WORKFLOW_REL] = rendered_text.encode("utf-8")

    # @implements FR-0020:AC-5
    gitattributes_notes: list[str] = []
    if GITATTRIBUTES_REL in plan:
        project_gitattributes = project / GITATTRIBUTES_REL
        if project_gitattributes.is_file():
            src_path, _owner = plan[GITATTRIBUTES_REL]
            template_block = src_path.read_bytes().decode("utf-8")
            project_text = project_gitattributes.read_bytes().decode("utf-8")
            new_text, state = _gitattributes_merge(project_text, template_block)
            if state == "damaged":
                seed_only.add(GITATTRIBUTES_REL)
            else:
                rendered_sources[GITATTRIBUTES_REL] = new_text.encode("utf-8")
                gitattributes_notes = _gitattributes_duplicate_lines(new_text)

    # @implements FR-0001:AC-3
    source_missing: list[str] = []
    for rel_path, profile_name, src in missing_profile_sources(profiles):
        source_missing.append(f"{rel_path} (from profile: {profile_name}; expected {src})")
        safe_print(
            f"  ! {rel_path}: profile source missing -- skipped "
            f"(profile: {profile_name}; NOT compared against the template copy)"
        )

    for rel_path, (source_file, source_profile) in sorted(plan.items()):
        project_file = project / rel_path
        # Compare bytes, not decoded text: read_text's newline translation
        # would hide a line-ending-only difference (e.g. a CRLF hook) and the
        # file would never re-sync. A rendered source (AC-2's stack files,
        # AC-5's `.gitattributes` merge) is used in place of the plan's raw
        # source file when this run computed one.
        if rel_path in rendered_sources:
            source_bytes = rendered_sources[rel_path]
        else:
            source_bytes = source_file.read_bytes()
        source_content = source_bytes.decode("utf-8")
        # Profile-sourced changes are annotated so the summary distinguishes
        # them from template-sourced ones (AC-4).
        origin = f"profile:{source_profile}" if source_profile else "template"
        tag = f" (from profile: {source_profile})" if source_profile else ""
        summary_label = f"{rel_path}{tag}"

        if not project_file.exists():
            # @implements FR-0001:AC-4
            if auto_yes:
                _copy_bytes(source_bytes, project_file)
                added.append(summary_label)
                safe_print(f"  + {rel_path} (new file{tag})")
            else:
                safe_print(f"\n  NEW: {rel_path}{tag}")
                safe_print(f"  This file exists in the {origin} but not in your project.")
                answer = input("  Add it? [y/N] ").strip().lower()
                if answer == "y":
                    _copy_bytes(source_bytes, project_file)
                    added.append(summary_label)
                else:
                    skipped.append(summary_label)
            continue

        project_bytes = project_file.read_bytes()
        if project_bytes == source_bytes:
            continue

        project_content = project_bytes.decode("utf-8")
        diff_text = diff_content(project_content, source_content, rel_path, tofile_prefix=origin)
        if not diff_text:
            diff_text = f"(bytes differ from {origin}; no printable line diff)\n"

        # Seed-only paths (AC-1: `.claude/settings.json`, `pytest.ini`; AC-2's
        # unresolved-stack paths for this run; AC-5's damaged `.gitattributes`)
        # carry project-local content an --upgrade must NEVER overwrite. A
        # whole-file replace would silently clobber it. Instead, report the
        # drift so it can be reconciled by hand. This holds in --yes too
        # (drift is exactly the thing an unattended run must not clobber).
        # Interim policy until the core/overlay split lands; see hub
        # CLAUDE.md / IDEA-0034.
        # @implements FR-0020:AC-1
        # @implements FR-0020:AC-6
        if rel_path in seed_only:
            drifted.append(rel_path)
            safe_print(f"  ! {rel_path} differs from {origin} — NOT changed (drift; reconcile by hand)")
            if not auto_yes:
                safe_print("  " + "-" * 60)
                for line in diff_text.splitlines():
                    safe_print(f"  {line}")
                safe_print("  " + "-" * 60)
            continue

        # @implements FR-0001:AC-4
        if auto_yes:
            _copy_bytes(source_bytes, project_file)
            updated.append(summary_label)
            safe_print(f"  ~ {rel_path} (updated{tag})")
        else:
            safe_print(f"\n  CHANGED: {rel_path}{tag}")
            safe_print("  " + "-" * 60)
            for line in diff_text.splitlines():
                safe_print(f"  {line}")
            safe_print("  " + "-" * 60)
            answer = input("  Apply this change? [y/N] ").strip().lower()
            if answer == "y":
                _copy_bytes(source_bytes, project_file)
                updated.append(summary_label)
            else:
                skipped.append(summary_label)

    # Verify (never edit) the profile's settings overlay and AGENTS.md block.
    overlay_missing, block_missing, block_differs = verify_profile_assets(
        project, profiles, auto_yes
    )

    # Regenerate commands from .agent-team/commands/ sources
    info("Regenerating commands from .agent-team/commands/ sources")
    cmd_count = generate_commands(project)
    safe_print(f"  Generated {cmd_count} command(s) for .claude/ and .cursor/")

    # Summary
    safe_print("\n" + "=" * 60)
    safe_print("Upgrade summary:")
    if updated:
        safe_print(f"  Updated:  {len(updated)} file(s)")
        for f in updated:
            safe_print(f"    ~ {f}")
    if added:
        safe_print(f"  Added:    {len(added)} file(s)")
        for f in added:
            safe_print(f"    + {f}")
        # @implements FR-0020:AC-3
        if (project / PROVENANCE_REGISTER_REL).is_file():
            safe_print(
                f"  Provenance: {len(added)} added file(s) need a row in "
                f"{PROVENANCE_REGISTER_REL} before commit:"
            )
            for f in added:
                safe_print(f"    + {f}")
    if skipped:
        safe_print(f"  Skipped:  {len(skipped)} file(s)")
        for f in skipped:
            safe_print(f"    - {f}")
    if drifted:
        safe_print(f"  Drift:    {len(drifted)} file(s) differ but were NOT changed")
        for f in drifted:
            safe_print(f"    ! {f}  (reconcile by hand — never auto-overwritten)")
    if overlay_missing:
        safe_print(
            f"  Profile overlay missing: {len(overlay_missing)} entry(ies) absent from "
            ".claude/settings.json (NOT changed; reconcile by hand)"
        )
        for f in overlay_missing:
            safe_print(f"    ! {f}")
    if block_missing:
        safe_print(
            f"  Profile block missing: {len(block_missing)} block(s) absent from "
            "AGENTS.md (NOT changed; reconcile by hand)"
        )
        for f in block_missing:
            safe_print(f"    ! {f}")
    if block_differs:
        safe_print(
            f"  Profile block differs: {len(block_differs)} block(s) in AGENTS.md "
            "differ from the profile text (NOT changed; reconcile by hand)"
        )
        for f in block_differs:
            safe_print(f"    ! {f}")
    if source_missing:
        safe_print(
            f"  Profile source missing: {len(source_missing)} path(s) skipped "
            "(NOT synced from the template copy)"
        )
        for f in source_missing:
            safe_print(f"    ! {f}")
    if not updated and not added:
        safe_print("  Everything is already up to date.")
    if cmd_count:
        safe_print(f"  Commands: {cmd_count} regenerated")
    # @implements FR-0020:AC-5
    if GITATTRIBUTES_REL in added or GITATTRIBUTES_REL in updated:
        safe_print(
            "  Reminder: .gitattributes' managed block changed -- run "
            "'git add --renormalize .' in the project and commit the result."
        )
    if gitattributes_notes:
        safe_print(
            "  NOTE: .gitattributes has line(s) outside the managed block "
            "identical to line(s) inside it: " + "; ".join(gitattributes_notes)
        )
    safe_print("=" * 60)


# ---------------------------------------------------------------------------
# Create mode (main bootstrap)
# ---------------------------------------------------------------------------

def run_create(args: argparse.Namespace) -> None:
    """Bootstrap a new project from the template."""
    name_or_path: str = args.name
    description: str = args.description
    stack: str = args.stack
    profiles: list[str] = args.profile
    keep_example: bool = args.keep_example
    do_git: bool = not args.no_git
    private: bool = args.private
    register: bool = not args.no_register

    # Validate, then de-duplicate preserving the order given (AC-1).
    profiles = dedupe_profiles(validate_profiles(profiles)) if profiles else []

    # Determine target path and project name
    if os.sep not in name_or_path and "/" not in name_or_path and not name_or_path.startswith("."):
        project_name = name_or_path
        target = HUB_ROOT / "projects" / name_or_path
    else:
        target = Path(name_or_path)
        project_name = target.name

    validate_slug(project_name)

    if target.exists() and any(target.iterdir()):
        die(f"Target '{target}' exists and is not empty")

    # Pre-flight
    python = find_python()
    check_pyyaml(python)

    # Copy template
    target.mkdir(parents=True, exist_ok=True)
    target = target.resolve()
    info(f"Copying template into {target}")
    copy_template(TEMPLATE_ROOT, target)

    # Substitute project description
    info("Filling project description in AGENTS.md")
    agents_md = target / "AGENTS.md"
    substitute_description(agents_md, description)

    # Stack-specific injection
    if stack != "none":
        info(f"Injecting {stack} conventions")
        inject_stack(agents_md, stack)
        enable_cursor_rule(target / ".cursor" / "rules" / f"20-{stack}.mdc")
        uncomment_ci_job(target / ".github" / "workflows" / "agent-gates.yml", stack)

    # Apply compliance profiles
    if profiles:
        apply_profiles(target, profiles)

    # Record the profile set in the project itself (empty list when unprofiled)
    # so --upgrade can resolve it without the hub registry.
    # @implements FR-0001:AC-1
    info(f"Recording profile set in {PROFILE_RECORD_REL}")
    write_profile_record(target, profiles)

    # Generate commands
    info("Generating .claude/commands/ and .cursor/commands/ from .agent-team/commands/")
    cmd_count = generate_commands(target)
    safe_print(f"  Generated {cmd_count} command(s) for .claude/ and .cursor/", file=sys.stderr)

    # Create dispatch directory
    info("Creating _dispatch/ directory")
    dispatch_dir = target / "_dispatch"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    (dispatch_dir / ".gitkeep").touch()

    # Create worktrees directory
    worktrees_dir = target / ".claude" / "worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    # Delete example FR
    example_fr = target / "specs" / "FR-0001-example.md"
    if not keep_example and example_fr.exists():
        info("Removing example FR-0001")
        example_fr.unlink()

    # Regenerate spec index
    info("Regenerating specs/INDEX.md")
    subprocess.run([python, "scripts/index-specs.py"], cwd=target, check=True)

    # Register in hub
    if register:
        info("Registering project in hub/projects.yaml")
        register_project(
            HUB_ROOT, project_name, target, stack, private, python, profiles=profiles
        )

        info("Refreshing hub/FR-INDEX.json")
        subprocess.run(
            [python, "scripts/hub-index.py"], cwd=HUB_ROOT, check=True
        )

    # Git init
    if do_git:
        git_init(target)

    # Done
    conventions_note = ""
    if stack == "none":
        conventions_note = "\n       - <<REPLACE: PROJECT_CONVENTIONS>>"
    safe_print(f"""
\u2705 Project ready at: {target}

Next steps:
  1. cd "{target}"
  2. Open AGENTS.md and fill in:
       - <<REPLACE: PROJECT_GLOSSARY>>{conventions_note}
  3. Open the project in Claude Code or Cursor, then run:
       /architect <one-line description of your first FR>
  4. Verify the gate: python scripts/deploy-gate.py

Roles available via slash commands:
  /architect [FR-XXXX | description]
  /developer FR-XXXX
  /reviewer FR-XXXX
  /reviewer-backfill FR-XXXX
  /maintainer FR-XXXX
  /orchestrator [FR-XXXX ... | description]
  /docs [doc-id]
  /gate [--stage dev|full]
  /status [FR-XXXX]
  /escalate <reason>""")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Stand up or upgrade an agent-team project from the hub template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              # Create a new project
              python scripts/bootstrap.py helena-emr-mapper \\
                "Bidirectional EMR transformation layer for Helena." --stack python

              # Create a project at a custom path
              python scripts/bootstrap.py ~/code/some-other-project \\
                "External project, lives outside the hub." --stack node

              # Upgrade an existing project with template changes
              python scripts/bootstrap.py --upgrade projects/my-project

              # Upgrade non-interactively (e.g. in CI)
              python scripts/bootstrap.py --upgrade projects/my-project --yes

              # Backfill the profile record on a project created before FR-0001,
              # then upgrade it profile-aware
              python scripts/bootstrap.py --upgrade projects/my-project --profile phipa
        """),
    )

    parser.add_argument(
        "--upgrade",
        metavar="PROJECT_PATH",
        help="Propagate template infrastructure changes to an existing project. "
             "Diffs .agent-team/, scripts/, .github/workflows/, .claude/, "
             ".cursor/commands/, .cursor/rules/, and specs/_template/ against the "
             "template and offers to update divergent files. Files owned by the "
             "project's recorded compliance profiles (.agent-team/profiles.yaml) "
             "are diffed and synced against profiles/<name>/ instead.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply all upgrades without interactive confirmation (for --upgrade mode).",
    )

    parser.add_argument(
        "name",
        nargs="?",
        help="Project name (slug) or path. If no slash, lands under projects/<name>.",
    )
    parser.add_argument(
        "description",
        nargs="?",
        help="One-paragraph project description (injected into AGENTS.md).",
    )
    parser.add_argument(
        "--stack",
        choices=["python", "node", "none"],
        default="none",
        help="Inject stack-specific conventions and CI (default: none).",
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        metavar="NAME",
        help="Activate a compliance profile (can be repeated). "
             "Validated against directories in profiles/. With --upgrade: backfill "
             "the project's profile record to exactly the given set, then upgrade.",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Mark project as private (excluded from cross-project pattern detection).",
    )
    parser.add_argument(
        "--keep-example",
        action="store_true",
        help="Keep specs/FR-0001-example.md (default: delete it).",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git init and initial commit.",
    )
    parser.add_argument(
        "--no-register",
        action="store_true",
        help="Don't append to hub/projects.yaml.",
    )

    return parser


def main() -> None:
    configure_stdio()

    parser = build_parser()
    args = parser.parse_args()

    if args.upgrade:
        project_path = Path(args.upgrade)
        if not project_path.is_absolute():
            project_path = HUB_ROOT / project_path
        run_upgrade(
            project_path,
            auto_yes=args.yes,
            backfill_profiles=list(args.profile) if args.profile else None,
        )
    elif args.name and args.description:
        run_create(args)
    elif args.name and not args.description:
        die(
            "Description is required.\n"
            f'Usage: python scripts/bootstrap.py {args.name} "Your project description"'
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
