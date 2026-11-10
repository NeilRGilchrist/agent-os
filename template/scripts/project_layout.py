"""
project_layout.py — the one reader of a project's `.agent-team/layout.yaml`.

A project may declare where it sits and what its gate scans:

    project_name: hub-tooling      # enables `# covers <project_name> FR-NNNN:AC-N`
    footprint_root: repo           # `project` (default) or `repo`
    gate:
      source_dirs: [template/scripts, scripts]   # default [src]
      test_dirs: [template/tests, tests]         # default [tests]

`footprint_root` is the directory that `owns:` / `reads:` entries and the
gate's directories resolve against: the project root itself, or the top of
the git repository the project lives in (for a project in a subdirectory of
a larger repository whose FRs change files outside it).

With no layout file, `load()` returns the default layout — the project root,
`src/` and `tests/`, no project name — without running a subprocess or
printing anything, so every script behaves exactly as it did before the file
existed. A present file is validated strictly: any unknown key, wrong type or
invalid value raises `LayoutInvalid`, whose message names
`.agent-team/layout.yaml` and the offending key. `git rev-parse` runs once per
`load()`, and only when `footprint_root` is `repo`.

The template ships `.agent-team/layout.yaml.example`, never `layout.yaml`, so
`bootstrap.py --upgrade` never creates or overwrites a project's layout.

@implements FR-0023:AC-1
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from spec_footprint import FootprintInvalid, _validate_glob

LAYOUT_RELPATH = ".agent-team/layout.yaml"

FOOTPRINT_ROOTS = ("project", "repo")
DEFAULT_SOURCE_DIRS: tuple[str, ...] = ("src",)
DEFAULT_TEST_DIRS: tuple[str, ...] = ("tests",)

_PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOP_LEVEL_KEYS = ("project_name", "footprint_root", "gate")
_GATE_KEYS = ("source_dirs", "test_dirs")


class LayoutInvalid(ValueError):
    """Raised when `.agent-team/layout.yaml` is malformed or cannot be resolved."""


@dataclass(frozen=True)
class ProjectLayout:
    project_root: Path
    project_name: str | None
    footprint_root: str
    # The directory footprints and gate directories resolve against: equal to
    # `project_root` under `project`, the git toplevel under `repo`.
    root: Path
    source_dirs: tuple[str, ...]
    test_dirs: tuple[str, ...]

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / d for d in self.source_dirs)

    @property
    def test_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / d for d in self.test_dirs)


def default(project_root: Path) -> ProjectLayout:
    """The layout of a project with no `layout.yaml`: today's behaviour."""
    return ProjectLayout(
        project_root=project_root,
        project_name=None,
        footprint_root="project",
        root=project_root,
        source_dirs=DEFAULT_SOURCE_DIRS,
        test_dirs=DEFAULT_TEST_DIRS,
    )


def load(project_root: Path) -> ProjectLayout:
    """Read and validate `<project_root>/.agent-team/layout.yaml`.

    Returns `default(project_root)` when the file is absent. Raises
    `LayoutInvalid` when it is present but malformed, or when
    `footprint_root: repo` cannot be resolved to a git toplevel.
    """
    path = project_root / LAYOUT_RELPATH
    if not path.is_file():
        return default(project_root)

    # Imported here so a project with no layout never needs pyyaml for it.
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise LayoutInvalid(f"{LAYOUT_RELPATH}: cannot be read as YAML: {e}") from e
    if not isinstance(raw, dict):
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: must be a YAML mapping of "
            f"{', '.join(_TOP_LEVEL_KEYS)}, got {type(raw).__name__}"
        )
    for key in raw:
        if key not in _TOP_LEVEL_KEYS:
            raise LayoutInvalid(
                f"{LAYOUT_RELPATH}: unknown key {key!r} "
                f"(allowed: {', '.join(_TOP_LEVEL_KEYS)})"
            )

    project_name = _project_name(raw)
    footprint_root = _footprint_root(raw)
    source_dirs, test_dirs = _gate_dirs(raw)

    root = project_root
    if footprint_root == "repo":
        root = _git_toplevel(project_root)

    return ProjectLayout(
        project_root=project_root,
        project_name=project_name,
        footprint_root=footprint_root,
        root=root,
        source_dirs=source_dirs,
        test_dirs=test_dirs,
    )


def _project_name(raw: dict) -> str | None:
    if "project_name" not in raw:
        return None
    value = raw["project_name"]
    if not isinstance(value, str) or not _PROJECT_NAME_PATTERN.fullmatch(value):
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: project_name must be a string matching "
            f"{_PROJECT_NAME_PATTERN.pattern}, got {value!r}"
        )
    return value


def _footprint_root(raw: dict) -> str:
    if "footprint_root" not in raw:
        return "project"
    value = raw["footprint_root"]
    if not isinstance(value, str) or value not in FOOTPRINT_ROOTS:
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: footprint_root must be one of "
            f"{', '.join(FOOTPRINT_ROOTS)}, got {value!r}"
        )
    return value


def _gate_dirs(raw: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if "gate" not in raw:
        return DEFAULT_SOURCE_DIRS, DEFAULT_TEST_DIRS
    gate = raw["gate"]
    if not isinstance(gate, dict) or not gate:
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: gate must be a mapping with "
            f"{' and/or '.join(_GATE_KEYS)}, got {gate!r}"
        )
    for key in gate:
        if key not in _GATE_KEYS:
            raise LayoutInvalid(
                f"{LAYOUT_RELPATH}: unknown key 'gate.{key}' "
                f"(allowed: {', '.join(_GATE_KEYS)})"
            )
    source_dirs = _dir_list(gate, "source_dirs", DEFAULT_SOURCE_DIRS)
    test_dirs = _dir_list(gate, "test_dirs", DEFAULT_TEST_DIRS)
    return source_dirs, test_dirs


def _dir_list(gate: dict, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if key not in gate:
        return fallback
    value = gate[key]
    field_name = f"gate.{key}"
    if not isinstance(value, list) or not value:
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: {field_name} must be a non-empty list of "
            f"directory paths, got {value!r}"
        )
    # Same entry rules as `owns:` (no absolute path, no `..`, no backslash):
    # only the root they resolve against can move, never the entry syntax.
    try:
        entries = tuple(_validate_glob(LAYOUT_RELPATH, field_name, v) for v in value)
    except FootprintInvalid as e:
        raise LayoutInvalid(str(e)) from e
    # Plus, for the layout only: no Windows drive or UNC root, on every
    # platform. `root / "C:/x"` discards the root, so such an entry would be
    # scanned outside the footprint root. @implements FR-0023:AC-1, FR-0023:AC-3
    for entry in entries:
        if PureWindowsPath(entry).drive:
            raise LayoutInvalid(
                f"{LAYOUT_RELPATH}: {field_name} entry {entry!r} has a drive or "
                "UNC root; directories must be relative to the footprint root"
            )
    return entries


def _git_toplevel(project_root: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: footprint_root is 'repo' but "
            f"`git rev-parse --show-toplevel` failed in {project_root}: "
            f"{detail.strip()}"
        ) from e
    toplevel = result.stdout.strip()
    if not toplevel:
        raise LayoutInvalid(
            f"{LAYOUT_RELPATH}: footprint_root is 'repo' but "
            f"`git rev-parse --show-toplevel` printed nothing in {project_root}"
        )
    return Path(toplevel).resolve()
