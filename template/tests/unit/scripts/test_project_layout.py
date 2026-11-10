"""Tests for hub-tooling FR-0023: a project declares its layout in
`.agent-team/layout.yaml`, read through `scripts/project_layout.py` (AC-1);
footprints resolve against the declared root (AC-2); the gate scans the
declared directories (AC-3) and counts `# covers <project_name>` for its own
project (AC-4); hub CI runs the hub and template suites (AC-5); hub-tooling
declares its layout (AC-6); and a project with no layout is untouched (AC-7).

Behavioural tests drive the real scripts as subprocesses in self-contained
temporary repositories (the team scripts are copied in). The subdirectory
fixture is a git repository holding a project at `proj/` whose FRs own
`lib/x.py`, outside the project.

AC-5 and AC-6 read hub files and skip outside the hub. AC-7's byte-identity
check runs the gate and indexer from FR-0023's base (`_baseline_ref()`: the
parent of the commit that added `project_layout.py`) beside the current ones,
and skips where that history is unreachable (bootstrapped projects have no hub
history).

Coverage annotations use the ride-along form `# covers hub-tooling FR-0023:AC-N`
rather than the gate's own annotation: this file travels into every
bootstrapped project, where no FR-0023 exists. Annotation strings inside
fixtures are split so no gate scanning this file reads them. Every fixture is
synthetic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest
import yaml

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# in a bootstrapped project).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_HUB_DIR = _TEMPLATE_DIR.parent
_IS_HUB = (
    _TEMPLATE_DIR.name == "template"
    and (_HUB_DIR / "scripts" / "hub-index.py").is_file()
)
_COPY_SCRIPTS = (
    "deploy-gate.py",
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
    "project_layout.py",
)
_METRICS_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
)
# Split so a gate regex-scanning tests never reads fixture strings as real
# annotations.
_COVERS = "@" + "covers"
_IMPLEMENTS = "@" + "implements"
_QUALIFIED = "# " + "covers"
_LAYOUT = ".agent-team/layout.yaml"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import project_layout  # noqa: E402
import spec_footprint  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic fixtures and harness
# ---------------------------------------------------------------------------


def _fr(fr_id: str, *, status: str = "ready", owns: str = "[]", acs: int = 1) -> str:
    ac_lines = "\n".join(f"- **AC-{n}:** does thing {n}" for n in range(1, acs + 1))
    return (
        "---\n"
        f"id: {fr_id}\n"
        f"title: Synthetic {fr_id}\n"
        f"status: {status}\n"
        "owner: architect\n"
        "depends_on: []\n"
        "tags: []\n"
        f"owns: {owns}\n"
        "reads: []\n"
        "derived_from: null\n"
        "pattern: null\n"
        "ac_state: {}\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n"
        f"# {fr_id}: Synthetic\n\n"
        "## Acceptance criteria\n\n"
        f"{ac_lines}\n"
    )


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))


def _install_scripts(project: Path, scripts: tuple[str, ...] = _COPY_SCRIPTS) -> None:
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    for name in scripts:
        shutil.copy(_SCRIPTS_DIR / name, project / "scripts" / name)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        env=_env(),
    )


def _git_init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _run(
    project: Path, script: str, *args: str, **env: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(project / "scripts" / script), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=_env(**env),
    )


def _gate(project: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(project, "deploy-gate.py", *args, METRICS_LOG_DISABLED="1")


def _set_layout(project: Path, text: str | None) -> None:
    path = project / _LAYOUT
    if text is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts
    }


def _records(project: Path) -> list[dict]:
    d = project / "specs" / "_metrics"
    if not d.exists():
        return []
    return [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


_PASSED_COUNTS = re.compile(
    r"Deploy gate PASSED \(stage=\w+\): (\d+) FRs, (\d+) @covers annotations, "
    r"(\d+) @implements annotations"
)


def _counts(proc: subprocess.CompletedProcess) -> tuple[int, int]:
    """(covers, implements) from a PASSED line."""
    m = _PASSED_COUNTS.search(proc.stdout)
    assert m, (proc.returncode, proc.stdout, proc.stderr)
    return int(m.group(2)), int(m.group(3))


def _subdir_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A git repository with a project at `proj/` and two `ready` FRs that both
    own `lib/x.py`, a tracked file outside the project. Returns (repo, project)."""
    repo = tmp_path / "repo"
    _git_init(repo)
    project = repo / "proj"
    _install_scripts(project)
    _write(
        project / "specs",
        {
            "FR-0001-a.md": _fr("FR-0001", owns="[lib/x.py]"),
            "FR-0002-b.md": _fr("FR-0002", owns="[lib/x.py]"),
        },
    )
    _write(repo, {"lib/x.py": "X = 1\n", "README.md": "synthetic\n"})
    _git(repo, "add", "-A")
    return repo, project


_REPO_LAYOUT = "footprint_root: repo\n"


# ---------------------------------------------------------------------------
# AC-1: an optional, validated layout file read through one module
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-1
def test_absent_layout_is_the_default_and_runs_nothing(tmp_path, monkeypatch, capsys):
    def _no_subprocess(*a, **k):  # pragma: no cover - failing path only
        raise AssertionError("load() ran a subprocess with no layout file")

    monkeypatch.setattr(project_layout.subprocess, "run", _no_subprocess)
    layout = project_layout.load(tmp_path)
    assert layout.project_name is None
    assert layout.footprint_root == "project"
    assert layout.root == tmp_path
    assert layout.source_dirs == ("src",)
    assert layout.test_dirs == ("tests",)
    assert layout.source_paths == (tmp_path / "src",)
    assert layout.test_paths == (tmp_path / "tests",)
    assert layout == project_layout.default(tmp_path)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


@pytest.mark.parametrize(
    ("text", "name", "source_dirs", "test_dirs"),
    [
        ("project_name: demo\n", "demo", ("src",), ("tests",)),
        ("project_name: a-1\nfootprint_root: project\n", "a-1", ("src",), ("tests",)),
        ("footprint_root: project\n", None, ("src",), ("tests",)),
        ("gate:\n  source_dirs: [lib]\n", None, ("lib",), ("tests",)),
        (
            "gate:\n  test_dirs: [lib_tests, more/tests]\n",
            None,
            ("src",),
            ("lib_tests", "more/tests"),
        ),
        (
            "project_name: demo\ngate:\n  source_dirs: [a, b]\n  test_dirs: [c]\n",
            "demo",
            ("a", "b"),
            ("c",),
        ),
    ],
    ids=["name", "name-project", "project", "source-only", "tests-only", "all-keys"],
)
# covers hub-tooling FR-0023:AC-1
def test_valid_project_rooted_layouts(
    tmp_path, monkeypatch, text, name, source_dirs, test_dirs
):
    def _no_subprocess(*a, **k):  # pragma: no cover - failing path only
        raise AssertionError("git ran although footprint_root is not repo")

    monkeypatch.setattr(project_layout.subprocess, "run", _no_subprocess)
    _set_layout(tmp_path, text)
    layout = project_layout.load(tmp_path)
    assert layout.project_name == name
    assert layout.footprint_root == "project"
    assert layout.root == tmp_path
    assert layout.source_dirs == source_dirs
    assert layout.test_dirs == test_dirs
    assert layout.test_paths == tuple(tmp_path / d for d in test_dirs)


# covers hub-tooling FR-0023:AC-1
def test_repo_rooted_layout_resolves_to_the_git_toplevel_with_one_git_call(
    tmp_path, monkeypatch
):
    repo, project = _subdir_repo(tmp_path)
    _set_layout(
        project,
        "project_name: demo\nfootprint_root: repo\ngate:\n  test_dirs: [lib_tests]\n",
    )
    calls: list[list[str]] = []
    real_run = subprocess.run

    def _counting_run(cmd, *a, **k):
        calls.append(list(cmd))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(project_layout.subprocess, "run", _counting_run)
    layout = project_layout.load(project)
    assert calls == [["git", "rev-parse", "--show-toplevel"]]
    assert layout.footprint_root == "repo"
    assert layout.root == repo.resolve()
    assert layout.project_root == project
    assert layout.test_paths == (repo.resolve() / "lib_tests",)
    assert layout.source_paths == (repo.resolve() / "src",)


# covers hub-tooling FR-0023:AC-1
def test_repo_rooted_layout_outside_any_git_repository_is_a_layout_error(
    tmp_path, monkeypatch
):
    project = tmp_path / "proj"
    project.mkdir()
    # Stop git's upward search at tmp_path so an enclosing checkout is never found.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    _set_layout(project, _REPO_LAYOUT)
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(project)
    msg = str(exc.value)
    assert _LAYOUT in msg and "footprint_root" in msg


_MALFORMED: list[tuple[str, str, str]] = [
    ("unknown-top-key", "project_nme: demo\n", "project_nme"),
    ("top-level-list", "- project_name\n", "mapping"),
    ("empty-file", "", "mapping"),
    ("comments-only", "# nothing declared\n", "mapping"),
    ("null", "null\n", "mapping"),
    ("bad-yaml", "project_name: [demo\n", "YAML"),
    ("name-uppercase", "project_name: Demo\n", "project_name"),
    ("name-leading-dash", "project_name: -demo\n", "project_name"),
    ("name-underscore", "project_name: my_proj\n", "project_name"),
    ("name-int", "project_name: 7\n", "project_name"),
    ("name-null", "project_name: null\n", "project_name"),
    ("name-trailing-newline", 'project_name: "demo\\n"\n', "project_name"),
    ("name-literal-block", "project_name: |\n  demo\n", "project_name"),
    ("root-unknown", "footprint_root: tree\n", "footprint_root"),
    ("root-list", "footprint_root: [repo]\n", "footprint_root"),
    ("gate-list", "gate: [src]\n", "gate"),
    ("gate-empty", "gate: {}\n", "gate"),
    ("gate-null", "gate: null\n", "gate"),
    ("gate-null-in-flow", "{gate: null}\n", "gate"),
    ("gate-unknown-key", "gate:\n  docs_dirs: [docs]\n", "gate.docs_dirs"),
    ("source-empty", "gate:\n  source_dirs: []\n", "gate.source_dirs"),
    ("source-string", "gate:\n  source_dirs: src\n", "gate.source_dirs"),
    ("source-non-string", "gate:\n  source_dirs: [3]\n", "gate.source_dirs"),
    ("source-empty-entry", "gate:\n  source_dirs: ['']\n", "gate.source_dirs"),
    ("tests-absolute", "gate:\n  test_dirs: [/abs/tests]\n", "gate.test_dirs"),
    ("tests-dotdot", "gate:\n  test_dirs: [../tests]\n", "gate.test_dirs"),
    ("tests-dotdot-middle", "gate:\n  test_dirs: [a/../b]\n", "gate.test_dirs"),
    ("tests-backslash", "gate:\n  test_dirs: ['a\\b']\n", "gate.test_dirs"),
    # DEC-0027 item 6: a Windows drive or UNC root, refused on every platform.
    ("source-drive", "gate:\n  source_dirs: ['C:/x']\n", "gate.source_dirs"),
    ("source-drive-relative", "gate:\n  source_dirs: ['c:x']\n", "gate.source_dirs"),
    ("source-unc", "gate:\n  source_dirs: ['//server/share/x']\n", "gate.source_dirs"),
    ("tests-drive", "gate:\n  test_dirs: ['C:/x']\n", "gate.test_dirs"),
    ("tests-drive-relative", "gate:\n  test_dirs: ['c:x']\n", "gate.test_dirs"),
    ("tests-unc", "gate:\n  test_dirs: ['//server/share/x']\n", "gate.test_dirs"),
]


@pytest.mark.parametrize(
    ("text", "key"),
    [(t, k) for _, t, k in _MALFORMED],
    ids=[i for i, _, _ in _MALFORMED],
)
# covers hub-tooling FR-0023:AC-1
def test_malformed_layout_raises_one_error_naming_the_file_and_key(tmp_path, text, key):
    _set_layout(tmp_path, text)
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(tmp_path)
    msg = str(exc.value)
    assert msg.startswith(f"{_LAYOUT}:"), msg
    assert key in msg, msg


# covers hub-tooling FR-0023:AC-1
def test_top_level_empty_mapping_is_the_default_layout(tmp_path, monkeypatch):
    def _no_subprocess(*a, **k):  # pragma: no cover - failing path only
        raise AssertionError("load() ran a subprocess for an empty layout")

    monkeypatch.setattr(project_layout.subprocess, "run", _no_subprocess)
    _set_layout(tmp_path, "{}\n")
    assert project_layout.load(tmp_path) == project_layout.default(tmp_path)


# covers hub-tooling FR-0023:AC-1
def test_gate_dir_entries_use_the_owns_entry_validator():
    # The same rules, by construction: the layout reuses spec_footprint's
    # validator rather than a copy of it.
    for entry in ("/abs", "a/../b", "a\\b"):
        with pytest.raises(spec_footprint.FootprintInvalid):
            spec_footprint._validate_glob(_LAYOUT, "gate.test_dirs", entry)
    assert project_layout._validate_glob is spec_footprint._validate_glob


@pytest.mark.parametrize("args", [(), ("--status-only",), ("--stage", "dev")])
# covers hub-tooling FR-0023:AC-1
def test_gate_fails_spec_validation_on_a_malformed_layout_before_writing(
    tmp_path, args
):
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(project / "specs", {"FR-0001-a.md": _fr("FR-0001")})
    _set_layout(project, "footprint_root: tree\n")
    before = _snapshot(project)
    proc = _gate(project, *args)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    lines = [ln for ln in proc.stderr.splitlines() if not ln.startswith("WARN: ")]
    assert lines[0] == "Spec index validation failed:"
    assert len(lines) == 2 and _LAYOUT in lines[1] and "footprint_root" in lines[1]
    assert _snapshot(project) == before


@pytest.mark.parametrize("key", ["source_dirs", "test_dirs"])
# covers hub-tooling FR-0023:AC-1
# covers hub-tooling FR-0023:AC-3
def test_gate_refuses_a_drive_letter_dir_as_spec_validation_not_script_error(
    tmp_path, key
):
    # A real absolute directory outside the project, holding a scannable file:
    # without the refusal the gate would reach `relative_to` with it and crash.
    outside = tmp_path / "outside"
    _write(outside, {"m.py": f"# {_IMPLEMENTS} FR-0001\n# {_COVERS} FR-0001:AC-1\n"})
    drive_entry = outside.as_posix() if PureWindowsPath(str(outside)).drive else "C:/x"
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(project / "specs", {"FR-0001-a.md": _fr("FR-0001", status="in-progress")})
    _set_layout(project, f"gate:\n  {key}: ['{drive_entry}']\n")
    before = _snapshot(project)
    proc = _run(project, "deploy-gate.py", "--stage", "dev")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr and "ValueError" not in proc.stderr
    lines = proc.stderr.splitlines()
    assert lines[0] == "Spec index validation failed:"
    assert lines[1].startswith(f"  {_LAYOUT}: gate.{key} entry "), lines
    assert len(lines) == 2, lines
    [record] = _records(project)
    assert record["outcome"] == "fail"
    assert record["failure_classes"] == ["spec-validation"]
    after = _snapshot(project)
    after.pop(next(k for k in after if k.startswith("specs/_metrics/")))
    assert after == before


# covers hub-tooling FR-0023:AC-1
def test_gate_records_a_malformed_layout_under_spec_validation(tmp_path):
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(project / "specs", {"FR-0001-a.md": _fr("FR-0001")})
    _set_layout(project, "unknown: 1\n")
    proc = _run(project, "deploy-gate.py")
    assert proc.returncode == 1
    assert not (project / "specs" / "INDEX.md").exists()
    [record] = _records(project)
    assert record["outcome"] == "fail"
    assert record["failure_classes"] == ["spec-validation"]


_BAD_LAYOUT = "footprint_root: tree\n"
_LAYOUT_ERROR = f"{_LAYOUT}: footprint_root must be one of project, repo, got 'tree'"


def _malformed_layout_project(tmp_path: Path) -> Path:
    """One malformed layout plus one FR error in the same tree, with a
    CODEOWNERS config so a successful plain run would write CODEOWNERS."""
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(
        project / "specs",
        {
            "FR-0001-a.md": _fr("FR-0001"),
            "FR-0002-b.md": _fr("FR-0002", status="not-a-status"),
        },
    )
    _write(
        project, {".agent-team/codeowners-config.yaml": 'owner_handle: "@synthetic"\n'}
    )
    _set_layout(project, _BAD_LAYOUT)
    return project


_INDEXER_MODES: list[tuple[str, ...]] = [
    (),
    ("--validate",),
    ("--list", "fr"),
    ("--slice", "FR-0001"),
    ("--provisional",),
]


@pytest.mark.parametrize(
    "args", _INDEXER_MODES, ids=["plain", "validate", "list", "slice", "provisional"]
)
# covers hub-tooling FR-0023:AC-1
def test_indexer_reports_a_malformed_layout_first_in_every_graph_mode(tmp_path, args):
    project = _malformed_layout_project(tmp_path)
    before = _snapshot(project)
    proc = _run(project, "index-specs.py", *args)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    lines = proc.stderr.splitlines()
    assert lines[0] == "Spec validation FAILED:"
    assert lines[1] == f"  - {_LAYOUT_ERROR}"
    assert lines[2].startswith("  - FR-0002-b.md: status 'not-a-status'"), lines
    assert sum(_LAYOUT in ln for ln in lines) == 1
    assert not (project / "specs" / "INDEX.md").exists()
    assert not (project / "CODEOWNERS").exists()
    assert _snapshot(project) == before


# covers hub-tooling FR-0023:AC-1
def test_indexer_validate_spec_graph_puts_the_layout_error_first(tmp_path):
    project = _malformed_layout_project(tmp_path)
    probe = (
        "import importlib.util, json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "spec = importlib.util.spec_from_file_location("
        "'ix', sys.argv[1] + '/index-specs.py')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['ix'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "print(json.dumps(mod.validate_spec_graph()))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe, str(project / "scripts")],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        env=_env(),
    )
    errors = json.loads(proc.stdout)
    assert errors[0] == _LAYOUT_ERROR
    assert errors[1].startswith("FR-0002-b.md: status 'not-a-status'")


# covers hub-tooling FR-0023:AC-1
def test_indexer_ac_hashes_is_unaffected_by_a_malformed_layout(tmp_path):
    project = _malformed_layout_project(tmp_path)
    proc = _run(project, "index-specs.py", "--ac-hashes")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("FR-0001 AC-1: ")
    assert _LAYOUT not in proc.stdout + proc.stderr


# covers hub-tooling FR-0023:AC-1
def test_gate_shows_the_layout_error_once_and_first(tmp_path):
    project = _malformed_layout_project(tmp_path)
    before = _snapshot(project)
    proc = _gate(project)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    lines = proc.stderr.splitlines()
    assert lines[0] == "Spec index validation failed:"
    assert lines[1] == f"  {_LAYOUT_ERROR}"
    assert lines[2].startswith("  FR-0002-b.md: status 'not-a-status'"), lines
    assert sum(_LAYOUT in ln for ln in lines) == 1
    assert _snapshot(project) == before


# covers hub-tooling FR-0023:AC-1
def test_indexer_without_a_sibling_project_layout_ignores_the_layout(tmp_path):
    project = _malformed_layout_project(tmp_path)
    (project / "scripts" / "project_layout.py").unlink()
    proc = _run(project, "index-specs.py", "--validate")
    assert proc.returncode == 1
    lines = proc.stderr.splitlines()
    assert lines[0] == "Spec validation FAILED:"
    assert lines[1].startswith("  - FR-0002-b.md: status 'not-a-status'"), lines
    assert _LAYOUT not in proc.stderr


# covers hub-tooling FR-0023:AC-1
def test_template_ships_the_example_documenting_every_key_and_never_the_layout():
    example = _TEMPLATE_DIR / ".agent-team" / "layout.yaml.example"
    text = example.read_text(encoding="utf-8")
    for needle in (
        "project_name",
        "footprint_root",
        "Default: project",
        "source_dirs",
        "Default: [src]",
        "test_dirs",
        "Default: [tests]",
    ):
        assert needle in text, needle
    # Every key is commented out: the example as shipped is an empty layout.
    assert yaml.safe_load(text) is None
    if not _IS_HUB:
        pytest.skip("a bootstrapped project may carry its own layout.yaml")
    assert not (_TEMPLATE_DIR / _LAYOUT).exists()


# ---------------------------------------------------------------------------
# AC-2: footprints resolve against the declared root
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-2
def test_git_ls_files_lists_repo_relative_paths_under_footprint_root_repo(tmp_path):
    repo, project = _subdir_repo(tmp_path)
    _set_layout(project, _REPO_LAYOUT)
    layout = project_layout.load(project)
    files = spec_footprint._git_ls_files(layout)
    assert "lib/x.py" in files
    assert "proj/specs/FR-0001-a.md" in files
    assert spec_footprint._git_ls_files(project_layout.default(project)) == (
        spec_footprint._git_ls_files()
    )


# covers hub-tooling FR-0023:AC-2
def test_repo_rooted_footprints_report_an_overlap_outside_the_project(tmp_path):
    _, project = _subdir_repo(tmp_path)
    _set_layout(project, _REPO_LAYOUT)
    proc = _run(project, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    index = (project / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "## Footprint warnings" in index
    assert "**FR-0001 ↔ FR-0002**: shared files: `lib/x.py`" in index


# covers hub-tooling FR-0023:AC-2
def test_without_a_layout_the_file_outside_the_project_is_not_seen(tmp_path):
    _, project = _subdir_repo(tmp_path)
    proc = _run(project, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    index = (project / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "## Footprint warnings" not in index
    assert "lib/x.py" in index  # the owns: column still renders it


# covers hub-tooling FR-0023:AC-2
def test_project_at_repo_top_gives_identical_output_for_both_roots(tmp_path):
    repo = tmp_path / "repo"
    _git_init(repo)
    _install_scripts(repo)
    _write(
        repo / "specs",
        {
            "FR-0001-a.md": _fr("FR-0001", owns="[lib/x.py]"),
            "FR-0002-b.md": _fr("FR-0002", owns="[lib/x.py]"),
        },
    )
    _write(repo, {"lib/x.py": "X = 1\n"})
    _git(repo, "add", "-A")
    outputs = []
    for root in ("project", "repo"):
        _set_layout(repo, f"footprint_root: {root}\n")
        proc = _run(repo, "index-specs.py")
        assert proc.returncode == 0, proc.stderr
        index = (repo / "specs" / "INDEX.md").read_bytes()
        outputs.append((proc.stdout, proc.stderr, index))
    assert outputs[0] == outputs[1]
    assert b"## Footprint warnings" in outputs[0][2]


# ---------------------------------------------------------------------------
# AC-3: the gate scans the declared directories
# ---------------------------------------------------------------------------


def _annotated_subdir_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo, project = _subdir_repo(tmp_path)
    _write(
        repo,
        {
            "lib_tests/test_x.py": f"# {_COVERS} FR-0001:AC-1\n",
            "lib/x.py": f"# {_IMPLEMENTS} FR-0001\nX = 1\n",
            "lib/y.py": f"# {_IMPLEMENTS} FR-0042\n",
        },
    )
    return repo, project


# covers hub-tooling FR-0023:AC-3
def test_gate_counts_annotations_in_declared_dirs_outside_the_project(tmp_path):
    _, project = _annotated_subdir_repo(tmp_path)
    _set_layout(
        project,
        "footprint_root: repo\ngate:\n  source_dirs: [lib]\n  test_dirs: [lib_tests]\n",
    )
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (1, 2)
    # Reported relative to the footprint root, not the project root (which
    # would have raised ValueError from relative_to).
    assert f"@implements references unknown FR FR-0042 in: {Path('lib', 'y.py')}" in (
        proc.stderr
    )


# covers hub-tooling FR-0023:AC-3
def test_without_a_layout_the_gate_counts_neither(tmp_path):
    _, project = _annotated_subdir_repo(tmp_path)
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (0, 0)


# covers hub-tooling FR-0023:AC-3
def test_missing_declared_dirs_are_skipped_silently(tmp_path):
    _, project = _annotated_subdir_repo(tmp_path)
    _set_layout(
        project,
        "footprint_root: repo\ngate:\n  source_dirs: [nope, lib]\n  test_dirs: [absent]\n",
    )
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (0, 2)


# covers hub-tooling FR-0023:AC-3
def test_default_dirs_scan_src_and_tests_under_the_project(tmp_path):
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(project / "specs", {"FR-0001-a.md": _fr("FR-0001")})
    _write(
        project,
        {
            "tests/test_a.py": f"# {_COVERS} FR-0001:AC-1\n",
            "src/a.py": f"# {_IMPLEMENTS} FR-0001\n",
            "lib/b.py": f"# {_IMPLEMENTS} FR-0001\n",
        },
    )
    for text in (None, "footprint_root: project\n", "gate:\n  source_dirs: [src]\n"):
        _set_layout(project, text)
        proc = _gate(project, "--stage", "dev", "--status-only")
        assert proc.returncode == 0, proc.stderr
        assert _counts(proc) == (1, 1), text


# ---------------------------------------------------------------------------
# AC-4: `# covers <project_name>` counts for its own project
# ---------------------------------------------------------------------------


def _qualified_project(tmp_path: Path, test_text: str) -> Path:
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(project / "specs", {"FR-0001-a.md": _fr("FR-0001", status="in-review")})
    _write(project, {"tests/test_a.py": test_text})
    return project


# covers hub-tooling FR-0023:AC-4
def test_qualified_annotation_covers_for_its_own_project(tmp_path):
    project = _qualified_project(tmp_path, f"{_QUALIFIED} demo FR-0001:AC-1\n")
    _set_layout(project, "project_name: demo\n")
    proc = _gate(project, "--stage", "full", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (1, 0)


@pytest.mark.parametrize(
    "layout", ["project_name: other\n", None], ids=["other", "no-layout"]
)
# covers hub-tooling FR-0023:AC-4
def test_qualified_annotation_is_ignored_for_another_or_no_project(tmp_path, layout):
    project = _qualified_project(tmp_path, f"{_QUALIFIED} demo FR-0001:AC-1\n")
    _set_layout(project, layout)
    proc = _gate(project, "--stage", "full", "--status-only")
    assert proc.returncode == 1
    assert "FR-0001 (in-review): no @covers test for AC-1" in proc.stderr
    assert _counts(_gate(project, "--stage", "dev", "--status-only")) == (0, 0)


@pytest.mark.parametrize(
    ("layout", "fails"),
    [("project_name: demo\n", True), ("project_name: other\n", False), (None, False)],
    ids=["demo", "other", "no-layout"],
)
# covers hub-tooling FR-0023:AC-4
def test_qualified_annotation_for_an_unknown_fr_fails_only_its_project(
    tmp_path, layout, fails
):
    project = _qualified_project(tmp_path, f"{_QUALIFIED} demo FR-0099:AC-1\n")
    (project / "specs" / "FR-0001-a.md").write_text(_fr("FR-0001"), encoding="utf-8")
    _set_layout(project, layout)
    proc = _run(project, "deploy-gate.py", "--stage", "dev")
    assert (proc.returncode == 1) is fails, (proc.stdout, proc.stderr)
    assert ("@covers references unknown FR FR-0099" in proc.stderr) is fails
    [record] = _records(project)
    assert ("covers-unknown-fr" in record["failure_classes"]) is fails


# covers hub-tooling FR-0023:AC-4
def test_qualified_unknown_ac_fails_covers_unknown_ac(tmp_path):
    project = _qualified_project(tmp_path, f"{_QUALIFIED} demo FR-0001:AC-7\n")
    _set_layout(project, "project_name: demo\n")
    proc = _run(project, "deploy-gate.py", "--stage", "dev")
    assert proc.returncode == 1
    assert "@covers references FR-0001:AC-7 but that AC is not in the FR" in proc.stderr
    [record] = _records(project)
    assert record["failure_classes"] == ["covers-unknown-ac"]


@pytest.mark.parametrize(
    "line",
    [
        f"{_QUALIFIED} demo FR-00NN:AC-N",
        f"{_QUALIFIED} demo-x FR-0001:AC-1",
        f"{_QUALIFIED} xdemo FR-0001:AC-1",
        f"{_QUALIFIED} demoFR-0001:AC-1",
        "# cover demo FR-0001:AC-1",
    ],
    ids=["placeholder", "suffixed-name", "prefixed-name", "no-space", "cover"],
)
# covers hub-tooling FR-0023:AC-4
def test_placeholders_and_other_names_do_not_match(tmp_path, line):
    project = _qualified_project(tmp_path, line + "\n")
    (project / "specs" / "FR-0001-a.md").write_text(_fr("FR-0001"), encoding="utf-8")
    _set_layout(project, "project_name: demo\n")
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (0, 0)


# covers hub-tooling FR-0023:AC-4
def test_qualified_and_plain_annotations_count_as_one_set(tmp_path):
    project = _qualified_project(
        tmp_path,
        f"{_QUALIFIED} demo FR-0001:AC-1\n# {_COVERS} FR-0001:AC-1\n"
        f"#covers  demo  FR-0001:AC-2\n",
    )
    (project / "specs" / "FR-0001-a.md").write_text(
        _fr("FR-0001", status="in-review", acs=2), encoding="utf-8"
    )
    _set_layout(project, "project_name: demo\n")
    proc = _run(project, "deploy-gate.py", "--stage", "full")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (2, 0)
    [record] = _records(project)
    assert record["counts"]["covers"] == 2


# ---------------------------------------------------------------------------
# AC-5: hub CI runs the hub and template suites
# ---------------------------------------------------------------------------


def _hub_workflow() -> dict:
    if not _IS_HUB:
        pytest.skip("hub CI workflow exists only in the hub")
    return yaml.safe_load(
        (_HUB_DIR / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
    )


# covers hub-tooling FR-0023:AC-5
def test_hub_ci_runs_both_suites_separately_and_non_blocking():
    steps = _hub_workflow()["jobs"]["validate"]["steps"]
    checkout = next(
        s for s in steps if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 0
    runs = [s.get("run") for s in steps]
    assert "pip install pyyaml pytest" in runs
    hub = next(s for s in steps if s.get("run") == "python -m pytest tests -q")
    template = next(
        s for s in steps if s.get("run") == "python -m pytest template/tests -q"
    )
    assert hub["continue-on-error"] is True
    assert template["continue-on-error"] is True
    # The three existing steps are unchanged, in order, ahead of the suites.
    existing = [
        "python scripts/hub-index.py --check --allow-shrink",
        "python scripts/parking.py reindex",
        "python scripts/patterns.py reindex",
    ]
    assert [r for r in runs if r in existing] == existing
    for s in steps:
        if s.get("run") in existing:
            assert set(s) == {"run"}, s
    assert runs.index(existing[-1]) < runs.index("python -m pytest tests -q")


# ---------------------------------------------------------------------------
# AC-6: hub-tooling declares its layout
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-6
def test_hub_tooling_declares_its_layout():
    if not _IS_HUB:
        pytest.skip("hub-tooling exists only in the hub")
    project = _HUB_DIR / "projects" / "hub-tooling"
    raw = yaml.safe_load((project / _LAYOUT).read_text(encoding="utf-8"))
    assert raw == {
        "project_name": "hub-tooling",
        "footprint_root": "repo",
        "gate": {
            "source_dirs": ["template/scripts", "scripts"],
            "test_dirs": ["template/tests", "tests"],
        },
    }
    layout = project_layout.load(project)
    assert layout.root == _HUB_DIR.resolve()
    assert layout.test_paths == (
        _HUB_DIR.resolve() / "template/tests",
        _HUB_DIR.resolve() / "tests",
    )


# ---------------------------------------------------------------------------
# AC-7: nothing else changes
# ---------------------------------------------------------------------------


_BASELINE_CACHE: dict[str, str | None] = {}


def _baseline_ref() -> str | None:
    """The commit FR-0023 sits on: the parent of the commit that added
    `template/scripts/project_layout.py`. Its scripts are what a project with
    no layout must match ("today's"), whatever FR merged below FR-0023.
    Derived rather than pinned so it survives a rebase. None outside the hub
    or where that history is unreachable."""
    if "base" in _BASELINE_CACHE:
        return _BASELINE_CACHE["base"]
    base = None
    if _IS_HUB:
        adds = subprocess.run(
            [
                "git",
                "-C",
                str(_HUB_DIR),
                "log",
                "--format=%H",
                "--diff-filter=A",
                "--",
                "template/scripts/project_layout.py",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        commits = adds.stdout.split()
        if adds.returncode == 0 and commits:
            parent = subprocess.run(
                [
                    "git",
                    "-C",
                    str(_HUB_DIR),
                    "rev-parse",
                    "--verify",
                    "-q",
                    f"{commits[-1]}^",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if parent.returncode == 0:
                base = parent.stdout.strip()
    _BASELINE_CACHE["base"] = base
    return base


def _git_show(ref: str | None, rel: str) -> bytes | None:
    if ref is None:
        return None
    probe = subprocess.run(
        ["git", "-C", str(_HUB_DIR), "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    proc = subprocess.run(
        ["git", "-C", str(_HUB_DIR), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _baseline_scripts(dest: Path) -> None:
    """Install FR-0023's base scripts (which have no project_layout.py)."""
    (dest / "scripts").mkdir(parents=True)
    for name in _COPY_SCRIPTS:
        if name == "project_layout.py":
            continue
        data = _git_show(_baseline_ref(), f"template/scripts/{name}")
        if data is None:
            pytest.skip("hub history for FR-0023's base commit is not reachable")
        (dest / "scripts" / name).write_bytes(data)


def _no_layout_tree(root: Path) -> None:
    """A tree exercising every gate path a layout could touch: overlaps,
    coverage, unknown FR/AC, implements warnings."""
    _write(
        root / "specs",
        {
            "FR-0001-a.md": _fr(
                "FR-0001", status="in-review", owns="[src/a.py]", acs=2
            ),
            "FR-0002-b.md": _fr("FR-0002", owns="[src/a.py]"),
            "FR-0003-c.md": _fr("FR-0003", status="in-progress"),
        },
    )
    _write(
        root,
        {
            "tests/test_a.py": (
                f"# {_COVERS} FR-0001:AC-1\n"
                f"{_QUALIFIED} synthetic FR-0001:AC-2\n"
                f"# {_COVERS} FR-0099:AC-1\n"
            ),
            "src/a.py": f"# {_IMPLEMENTS} FR-0001\n# {_IMPLEMENTS} FR-0077\n",
            "lib/b.py": f"# {_IMPLEMENTS} FR-0003\n",
        },
    )


_VOLATILE = {"ts", "record_id", "run_id", "duration_ms"}


def _observe(project: Path) -> list:
    out: list = []
    invocations = [
        ("index-specs.py", "--validate"),
        ("index-specs.py", "--list", "fr"),
        ("index-specs.py", "--slice", "FR-0001"),
        ("index-specs.py", "--provisional", "--as-of", "2026-01-01"),
        ("index-specs.py", "--ac-hashes"),
        ("index-specs.py",),
        ("deploy-gate.py", "--stage", "dev"),
        ("deploy-gate.py", "--stage", "review"),
        ("deploy-gate.py",),
        ("deploy-gate.py", "--status-only"),
    ]
    for inv in invocations:
        index = project / "specs" / "INDEX.md"
        if index.exists():
            index.unlink()
        proc = _run(project, *inv)
        written = index.read_bytes() if index.exists() else None
        out.append((inv, proc.returncode, proc.stdout, proc.stderr, written))
    records = [
        {k: v for k, v in r.items() if k not in _VOLATILE} for r in _records(project)
    ]
    out.append(records)
    return out


@pytest.mark.parametrize("in_git", [True, False], ids=["git", "no-git"])
# covers hub-tooling FR-0023:AC-7
def test_no_layout_is_byte_identical_to_the_baseline(tmp_path, monkeypatch, in_git):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    observed = []
    for label, install in (
        ("baseline", _baseline_scripts),
        ("current", _install_scripts),
    ):
        project = tmp_path / label / "proj"
        project.mkdir(parents=True)
        install(project)
        _no_layout_tree(project)
        if in_git:
            _git_init(project)
            _git(project, "add", "-A")
        observed.append(_observe(project))
    assert observed[0] == observed[1]
    # The tree was not trivially green: the comparison covered failures too.
    assert any(rc == 1 for _, rc, *_ in observed[1][:-1])


# FR-0023's merge commit on hub `main` (PR #26). The class and metrics_log
# pins below check FR-0023's own diff only (the file at this commit against
# its first parent), as FR-0005's `test_spec_query.py` pins do, so a later FR
# that legitimately adds a class or edits metrics_log.py (FR-0026, FR-0018)
# does not turn them red.
_FR0023_MERGE_REF = "ddbe9e5"


def _fr0023_diff_sides(rel: str) -> tuple[bytes, bytes]:
    """(file at FR-0023's first parent, file at FR-0023's merge commit).
    Skips where that history is unreachable (outside the hub, shallow clone)."""
    before = _git_show(f"{_FR0023_MERGE_REF}^1", rel)
    after = _git_show(_FR0023_MERGE_REF, rel)
    if before is None or after is None:
        pytest.skip(
            f"hub history for FR-0023's merge {_FR0023_MERGE_REF} is not reachable"
        )
    return before, after


# covers hub-tooling FR-0023:AC-7
def test_gate_failure_and_warning_class_literals_are_unchanged():
    pattern = re.compile(r"""report\.(?:fail|warn)\(\s*["']([a-z-]+)["']""")
    before, after = _fr0023_diff_sides("template/scripts/deploy-gate.py")
    classes = set(pattern.findall(after.decode("utf-8")))
    assert classes  # the scrape is not vacuous
    assert classes == set(pattern.findall(before.decode("utf-8")))
    ml_before, ml_after = _fr0023_diff_sides("template/scripts/metrics_log.py")
    assert ml_after.replace(b"\r\n", b"\n") == ml_before.replace(b"\r\n", b"\n")


# covers hub-tooling FR-0023:AC-7
def test_scripts_without_a_sibling_project_layout_still_gate(tmp_path):
    project = tmp_path / "proj"
    _install_scripts(
        project, tuple(n for n in _COPY_SCRIPTS if n != "project_layout.py")
    )
    _no_layout_tree(project)
    _set_layout(project, "project_name: synthetic\n")  # inert without the module
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 1 and "Traceback" not in proc.stderr, proc.stderr
    assert proc.stderr.endswith(
        "Deploy gate FAILED:\n"
        "  - @covers references unknown FR FR-0099 (FR may have been deleted)\n"
    )
    idx = _run(project, "index-specs.py")
    assert idx.returncode == 0, idx.stderr
