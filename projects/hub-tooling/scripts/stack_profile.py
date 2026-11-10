"""
stack_profile.py — Pure, read-only detection of a project's declared stack,
and the closed table that turns a detected tool into a Bash grant (FR-0010).

`detect_stack(repo_root)` is the sole authority for "what does this project
declare it runs". It never executes, resolves, downloads, or installs
anything to answer that question — it only reads marker files at the repo
root and ADR frontmatter under `specs/decisions/`, plus one environment
variable. `stack_bash_grants(tools)` is the closed tool-id -> Bash-pattern
table; a tool id the table does not know never produces a grant, however it
reached the function (FR-0010:AC-3's "nothing else can widen the allow-list").

Both functions are consumed by `dispatch.py`'s permission derivation
(`ROLE_PERMISSIONS`-adjacent `dev_permissions` / `mnt_permissions` / the
`rev`/`bkf` equivalent) and by its spawn-report printing. Deliberately
dependency-free of `dispatch.py` itself so it can be imported and unit
tested standalone.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# AC-1 / AC-2: detection
# ---------------------------------------------------------------------------

# The closed vocabulary of tool ids `detect_stack` ever returns. An entry
# discovered anywhere (ADR frontmatter, the env override) that is not in this
# set is dropped and reported via one WARN-worthy string in `warnings`.
TOOL_VOCABULARY = frozenset(
    {"python", "uv", "pip", "node", "npm", "npx", "pnpm", "yarn", "docker", "alembic"}
)

# The operator escape hatch (FR-0010 Open question 1): a comma-separated list
# of tool ids a project declares that the marker files and ADRs cannot.
ENV_STACK_TOOLS = "DISPATCH_STACK_TOOLS"

# FR-0017 AC-1 / DEC-0020 Decision 1: the only markers read one directory
# below the root, each implying the same tools the root rule does. Every
# other marker (`pyproject.toml`, `uv.lock`, `requirements.txt`,
# `alembic.ini`, the compose files) stays root-only (DEC-0020 Decision 2).
_NESTED_NODE_MARKERS: dict[str, frozenset[str]] = {
    "package.json": frozenset({"node", "npm", "npx"}),
    "pnpm-lock.yaml": frozenset({"pnpm"}),
    "yarn.lock": frozenset({"yarn"}),
}

_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_COMPOSE_FILE_RE = re.compile(
    r"^(docker-compose.*\.ya?ml|compose\.ya?ml)$", re.IGNORECASE
)


@dataclass(frozen=True)
class StackDetection:
    """Result of `detect_stack`: the sorted, de-duplicated tool ids, and any
    warnings about entries that did not make it in (unrecognised ADR/env
    entries, or a malformed `stack_tools:` shape). Callers decide whether and
    how to print `warnings`; this module never prints anything itself."""

    tools: tuple[str, ...]
    warnings: tuple[str, ...]


def _marker_tools(repo_root: Path) -> set[str]:
    """AC-1: tool ids implied by marker files at the repo root. Presence-only
    — no marker file is ever parsed for its content, so an unparseable
    `pyproject.toml` still yields `python` with no error."""
    tools: set[str] = set()
    if (repo_root / "pyproject.toml").is_file():
        tools.add("python")
    has_uv_lock = (repo_root / "uv.lock").is_file()
    if has_uv_lock:
        tools.add("uv")
    if not has_uv_lock and (repo_root / "requirements.txt").is_file():
        tools.add("pip")
    if (repo_root / "package.json").is_file():
        tools.update({"node", "npm", "npx"})
    if (repo_root / "pnpm-lock.yaml").is_file():
        tools.add("pnpm")
    if (repo_root / "yarn.lock").is_file():
        tools.add("yarn")
    if (repo_root / "alembic.ini").is_file():
        tools.add("alembic")
    try:
        entries = list(repo_root.glob("*"))
    except OSError:
        entries = []
    if any(p.is_file() and _COMPOSE_FILE_RE.match(p.name) for p in entries):
        tools.add("docker")
    tools |= _nested_node_tools(repo_root)
    return tools


def _nested_node_tools(repo_root: Path) -> set[str]:
    """FR-0017 AC-1: node markers one directory below `repo_root`. A
    subdirectory `<root>/<d>/` qualifies only when it is a real directory
    (not a symlink — checked before any `is_dir()`, which would otherwise
    follow it), its name does not start with `.`, and it is not
    `node_modules` (DEC-0020 Decision 1). Presence-only, like the root
    rule: only `_NESTED_NODE_MARKERS`' three names are ever read one level
    down, and only for existence — no nested file's content is read, and a
    directory sharing a marker's name (e.g. `frontend/package.json/`) is
    not a marker.

    @implements FR-0017:AC-1
    @implements FR-0017:AC-2
    """
    tools: set[str] = set()
    try:
        entries = list(repo_root.iterdir())
    except OSError:
        return tools
    for entry in entries:
        if entry.is_symlink():
            continue
        name = entry.name
        if name.startswith(".") or name == "node_modules":
            continue
        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue
        for marker, marker_tools in _NESTED_NODE_MARKERS.items():
            try:
                if (entry / marker).is_file():
                    tools |= marker_tools
            except OSError:
                continue
    return tools


def _read_frontmatter(path: Path) -> dict | None:
    """Parsed YAML frontmatter of a spec-shaped markdown file, or None when
    the file is unreadable, has no frontmatter fence, or the fence doesn't
    parse as YAML. Read-only; never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_PATTERN.match(text)
    if m is None:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None


def _adr_tools(repo_root: Path, warnings: list[str]) -> set[str]:
    """AC-2: `stack_tools:` from every accepted ADR's frontmatter."""
    tools: set[str] = set()
    adr_dir = repo_root / "specs" / "decisions"
    if not adr_dir.is_dir():
        return tools
    for path in sorted(adr_dir.glob("ADR-*.md")):
        meta = _read_frontmatter(path)
        if not meta or meta.get("status") != "accepted":
            continue
        raw = meta.get("stack_tools")
        if raw is None:
            continue
        adr_id = str(meta.get("id") or path.stem)
        if not isinstance(raw, list) or not all(isinstance(e, str) for e in raw):
            warnings.append(
                f"{adr_id}: stack_tools must be a YAML list of strings, "
                f"got {type(raw).__name__}: {raw!r}; ignored"
            )
            continue
        for entry in raw:
            name = entry.strip()
            if not name:
                continue
            if name in TOOL_VOCABULARY:
                tools.add(name)
            else:
                warnings.append(
                    f"unrecognised stack tool {name!r} declared by {adr_id}"
                )
    return tools


def _env_tools(warnings: list[str]) -> set[str]:
    """AC-2: `DISPATCH_STACK_TOOLS`, a comma-separated operator override."""
    tools: set[str] = set()
    raw = os.environ.get(ENV_STACK_TOOLS, "")
    for entry in raw.split(","):
        name = entry.strip()
        if not name:
            continue
        if name in TOOL_VOCABULARY:
            tools.add(name)
        else:
            warnings.append(
                f"unrecognised stack tool {name!r} declared by {ENV_STACK_TOOLS}"
            )
    return tools


def detect_stack(repo_root: Path) -> StackDetection:
    """The project's declared stack: a sorted, de-duplicated list of tool ids
    drawn from `TOOL_VOCABULARY`, plus any warnings about entries that were
    dropped. Read-only: reads marker files and ADR frontmatter under
    `repo_root`, plus the `DISPATCH_STACK_TOOLS` environment variable.
    Executes nothing, spawns no subprocess, opens no socket, never writes.

    @implements FR-0010:AC-1
    @implements FR-0010:AC-2
    """
    warnings: list[str] = []
    tools = _marker_tools(repo_root)
    tools |= _adr_tools(repo_root, warnings)
    tools |= _env_tools(warnings)
    return StackDetection(tools=tuple(sorted(tools)), warnings=tuple(warnings))


# ---------------------------------------------------------------------------
# AC-3: tool id -> Bash grant, a closed table
# ---------------------------------------------------------------------------

# Deliberately closed and small. A tool id absent from this table produces no
# grant even though it may be a recognised vocabulary entry (e.g. `python`
# and `pip` are already covered by every role's static grants; `pnpm`/`yarn`
# are detected and reported but not yet mapped to a grant — see FR-0010
# Decisions). No entry here is a path grant, and none contains a shell
# metacharacter beyond the trailing ` *`.
STACK_BASH_GRANTS: dict[str, tuple[str, ...]] = {
    "uv": ("Bash(uv *)",),
    "node": ("Bash(node *)",),
    "npm": ("Bash(npm *)",),
    "npx": ("Bash(npx *)",),
    "docker": ("Bash(docker *)",),
    "alembic": ("Bash(alembic *)",),
}


def stack_bash_grants(tools: list[str] | tuple[str, ...]) -> list[str]:
    """The union of AC-3 Bash grants for a set of detected tool ids, sorted
    and de-duplicated. `[]` for `[]`. A tool id the table does not know
    (whatever its source) yields no grant.

    @implements FR-0010:AC-3
    """
    out: set[str] = set()
    for tool in tools:
        out.update(STACK_BASH_GRANTS.get(tool, ()))
    return sorted(out)


# ---------------------------------------------------------------------------
# AC-8: venv provisioning marker files (shared with `dispatch.ensure_dev_venv`
# so the "what does this worktree declare" question has one answer)
# ---------------------------------------------------------------------------


def find_lock_file(repo_root: Path) -> Path | None:
    """The project's `uv.lock`, if present."""
    p = repo_root / "uv.lock"
    return p if p.is_file() else None


def find_requirements_file(repo_root: Path) -> Path | None:
    """The project's `requirements.txt`, or the lexicographically-first
    `requirements*.lock` file, if present. Only consulted by callers that
    have already established there is no `uv.lock` (AC-8's `pip` branch)."""
    direct = repo_root / "requirements.txt"
    if direct.is_file():
        return direct
    candidates = sorted(p for p in repo_root.glob("requirements*.lock") if p.is_file())
    return candidates[0] if candidates else None
