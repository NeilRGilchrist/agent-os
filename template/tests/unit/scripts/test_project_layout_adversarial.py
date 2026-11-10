"""Reviewer adversarial tests for hub-tooling FR-0023 (round 1).

The Developer's `test_project_layout.py` covers each AC's stated cases. This
file goes after what a naive implementation would get wrong:

- AC-1: values that only look valid (a trailing newline in `project_name`),
  Windows-authored files (BOM, CRLF), non-string keys, and the `repo` root
  failing through the real scripts, where the error must be first and single.
- AC-2: a bite check against the scripts FR-0023 was built on, and the rule
  that only the root moves (a project-relative `owns:` stops matching).
- AC-3: a declared directory that is a file, and explicit defaults behaving
  byte-for-byte like no layout.
- AC-4: the interaction with FR-0027's labelled ACs, near-miss annotation
  forms, and project names that are prefixes of each other.
- AC-5: the template suite, invoked from the hub root, really takes
  `template/` as its rootdir.
- AC-6: hub-tooling's real layout, re-checked in-process: no unknown FR or
  AC, FR-0001..FR-0014 covered, and the footprint overlaps equal to an
  independent computation with git's own `:(glob)` pathspecs.
- AC-7: byte-identity against the commit FR-0023 sits on (FR-0027 included),
  on a tree that holds a labelled AC.

The base ref is derived, not pinned: the parent of the commit that added
`template/scripts/project_layout.py`. Tests that need hub history skip
outside the hub. Annotation strings in fixtures are built at runtime so no
gate scanning this file reads them. Every fixture is synthetic.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path, PureWindowsPath

import pytest
import yaml

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_HUB_DIR = _TEMPLATE_DIR.parent
_IS_HUB = (
    _TEMPLATE_DIR.name == "template"
    and (_HUB_DIR / "scripts" / "hub-index.py").is_file()
)
_HUB_TOOLING = _HUB_DIR / "projects" / "hub-tooling"
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
_COVERS = "@" + "covers"
_IMPLEMENTS = "@" + "implements"
_QUALIFIED = "# " + "covers"
_LAYOUT = ".agent-team/layout.yaml"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import project_layout  # noqa: E402
import spec_footprint  # noqa: E402

# ---------------------------------------------------------------------------
# Harness (duplicated from the Developer's file on purpose: independent)
# ---------------------------------------------------------------------------


def _fr(fr_id: str, *, status: str = "ready", owns: str = "[]", body: str) -> str:
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
        f"{body}\n"
    )


def _plain_fr(fr_id: str, *, status: str = "ready", owns: str = "[]") -> str:
    return _fr(fr_id, status=status, owns=owns, body="- **AC-1:** does one thing")


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _install_scripts(project: Path, scripts: tuple[str, ...] = _COPY_SCRIPTS) -> None:
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    for name in scripts:
        shutil.copy(_SCRIPTS_DIR / name, project / "scripts" / name)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        env=_env(),
    ).stdout


def _run(project: Path, script: str, *args: str, **env: str):
    return subprocess.run(
        [sys.executable, str(project / "scripts" / script), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=_env(**env),
    )


def _gate(project: Path, *args: str, **env: str):
    return _run(project, "deploy-gate.py", *args, METRICS_LOG_DISABLED="1", **env)


def _set_layout(project: Path, text: str | None) -> None:
    path = project / _LAYOUT
    if text is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


_PASSED = re.compile(
    r"Deploy gate PASSED \(stage=\w+\): \d+ FRs, (\d+) @covers annotations, "
    r"(\d+) @implements annotations"
)


def _counts(proc) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    m = _PASSED.search(proc.stdout)
    assert m, (proc.returncode, proc.stdout, proc.stderr)
    return int(m.group(1)), int(m.group(2))


def _subdir_repo(tmp_path: Path, scripts: tuple[str, ...] = _COPY_SCRIPTS):
    """A git repository with a project at `proj/`; two `ready` FRs own
    `lib/x.py` outside it; `lib/` and `lib_tests/` carry annotations."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    project = repo / "proj"
    _install_scripts(project, scripts)
    _write(
        project / "specs",
        {
            "FR-0001-a.md": _plain_fr("FR-0001", owns="[lib/x.py]"),
            "FR-0002-b.md": _plain_fr("FR-0002", owns="[lib/x.py]"),
        },
    )
    _write(
        repo,
        {
            "lib/x.py": f"# {_IMPLEMENTS} FR-0001\nX = 1\n",
            "lib_tests/test_x.py": f"{_QUALIFIED} demo FR-0001:AC-1\n",
        },
    )
    _git(repo, "add", "-A")
    return repo, project


_SUBDIR_LAYOUT = (
    "project_name: demo\n"
    "footprint_root: repo\n"
    "gate:\n  source_dirs: [lib]\n  test_dirs: [lib_tests]\n"
)

# ---------------------------------------------------------------------------
# The base FR-0023 sits on: derived from history, never pinned
# ---------------------------------------------------------------------------

_BASE_CACHE: dict[str, str | None] = {}


def _fr0023_base() -> str | None:
    """The parent of the commit that added project_layout.py: the scripts a
    project with no layout must match ("today's"), FR-0027 included."""
    if "base" in _BASE_CACHE:
        return _BASE_CACHE["base"]
    base = None
    if _IS_HUB:
        proc = subprocess.run(
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
        adds = proc.stdout.split()
        if proc.returncode == 0 and adds:
            parent = subprocess.run(
                [
                    "git",
                    "-C",
                    str(_HUB_DIR),
                    "rev-parse",
                    "--verify",
                    "-q",
                    f"{adds[-1]}^",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if parent.returncode == 0:
                base = parent.stdout.strip()
    _BASE_CACHE["base"] = base
    return base


def _install_base_scripts(project: Path) -> None:
    base = _fr0023_base()
    if base is None:
        pytest.skip("hub history below FR-0023 is not reachable")
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    for name in _COPY_SCRIPTS:
        if name == "project_layout.py":
            continue
        proc = subprocess.run(
            ["git", "-C", str(_HUB_DIR), "show", f"{base}:template/scripts/{name}"],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            pytest.skip(f"{name} is not readable at {base}")
        (project / "scripts" / name).write_bytes(proc.stdout)
    assert not (project / "scripts" / "project_layout.py").exists()


# ---------------------------------------------------------------------------
# AC-1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        'project_name: "demo\\n"\n',
        "project_name: |\n  demo\n",
        "project_name: >\n  demo\n",
    ],
    ids=["escaped-newline", "literal-block", "folded-block"],
)
# covers hub-tooling FR-0023:AC-1
def test_project_name_with_a_trailing_newline_is_malformed(tmp_path, text):
    # `^[a-z0-9][a-z0-9-]*$` under `re.match` lets `$` match before a final
    # newline, so "demo\n" would pass a naive check. The name then never
    # matches a qualified annotation and the layout looked valid.
    _set_layout(tmp_path, text)
    assert yaml.safe_load(text)["project_name"] == "demo\n"
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(tmp_path)
    msg = str(exc.value)
    assert msg.startswith(f"{_LAYOUT}:") and "project_name" in msg, msg


@pytest.mark.parametrize(
    "text",
    [
        "footprint_root: Repo\n",
        "footprint_root: 'repo '\n",
        'footprint_root: "repo\\n"\n',
        "footprint_root: true\n",
        "gate: src\n",
        "gate: 3\n",
        "gate:\n  source_dirs: [src]\n  test_dirs: {a: b}\n",
        "project_name: ''\n",
    ],
    ids=[
        "root-case",
        "root-space",
        "root-newline",
        "root-bool",
        "gate-string",
        "gate-int",
        "tests-mapping",
        "name-empty",
    ],
)
# covers hub-tooling FR-0023:AC-1
def test_near_valid_values_are_malformed(tmp_path, text):
    _set_layout(tmp_path, text)
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(tmp_path)
    assert str(exc.value).startswith(f"{_LAYOUT}:")


@pytest.mark.parametrize(
    ("text", "shown"),
    [("1: x\n", "1"), ("true: x\n", "True"), ("null: x\n", "None")],
    ids=["int-key", "bool-key", "null-key"],
)
# covers hub-tooling FR-0023:AC-1
def test_non_string_top_level_keys_are_unknown_keys(tmp_path, text, shown):
    _set_layout(tmp_path, text)
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(tmp_path)
    msg = str(exc.value)
    assert msg.startswith(f"{_LAYOUT}: unknown key {shown}"), msg


@pytest.mark.parametrize(
    "prefix,newline",
    [("﻿", "\n"), ("", "\r\n"), ("﻿", "\r\n")],
    ids=["bom", "crlf", "bom-crlf"],
)
# covers hub-tooling FR-0023:AC-1
def test_windows_authored_layout_loads(tmp_path, prefix, newline):
    # PowerShell 5.1's Out-File writes a BOM; Windows editors write CRLF.
    lines = ["project_name: demo", "gate:", "  test_dirs: [t]"]
    _set_layout(tmp_path, prefix + newline.join(lines) + newline)
    layout = project_layout.load(tmp_path)
    assert layout.project_name == "demo"
    assert layout.test_dirs == ("t",)


# covers hub-tooling FR-0023:AC-1
def test_loaded_layout_is_immutable(tmp_path):
    layout = project_layout.load(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        layout.footprint_root = "repo"  # type: ignore[misc]


def _string_literals(path: Path) -> list[str]:
    toks = tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline)
    return [t.string for t in toks if t.type == tokenize.STRING]


@pytest.mark.parametrize(
    "script", ["deploy-gate.py", "index-specs.py", "spec_footprint.py"]
)
# covers hub-tooling FR-0023:AC-1
def test_no_script_reads_the_layout_file_except_through_project_layout(script):
    # "Read through one module": no other script names the file in code.
    for literal in _string_literals(_SCRIPTS_DIR / script):
        assert "layout.yaml" not in literal or literal.startswith(('"""', "'''")), (
            script,
            literal,
        )
    assert "yaml.safe_load" not in "".join(
        ln
        for ln in (_SCRIPTS_DIR / script).read_text("utf-8").splitlines(True)
        if "layout" in ln
    )


# covers hub-tooling FR-0023:AC-1
def test_unresolvable_repo_root_fails_both_tools_first_and_once(tmp_path):
    # Not a `footprint_root: tree` typo but the other error kind: `repo`
    # declared where `git rev-parse --show-toplevel` fails. One FR error too.
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(
        project / "specs",
        {
            "FR-0001-a.md": _plain_fr("FR-0001"),
            "FR-0002-b.md": _plain_fr("FR-0002", status="not-a-status"),
        },
    )
    _set_layout(project, "footprint_root: repo\n")
    ceiling = {"GIT_CEILING_DIRECTORIES": str(tmp_path)}

    gate = _gate(project, **ceiling)
    assert gate.returncode == 1, (gate.stdout, gate.stderr)
    lines = gate.stderr.splitlines()
    assert lines[0] == "Spec index validation failed:"
    assert lines[1].startswith(f"  {_LAYOUT}: footprint_root is 'repo'"), lines
    assert lines[2].startswith("  FR-0002-b.md:"), lines
    assert sum(_LAYOUT in ln for ln in lines) == 1

    idx = _run(project, "index-specs.py", **ceiling)
    assert idx.returncode == 1
    lines = idx.stderr.splitlines()
    assert lines[0] == "Spec validation FAILED:"
    assert lines[1].startswith(f"  - {_LAYOUT}: footprint_root is 'repo'"), lines
    assert sum(_LAYOUT in ln for ln in lines) == 1
    assert not (project / "specs" / "INDEX.md").exists()


# ---------------------------------------------------------------------------
# AC-2
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-2
def test_bite_the_base_indexer_reports_no_overlap_outside_the_project(tmp_path):
    # The same tree and layout; the base scripts ignore the layout.
    reports = {}
    for label, install in (("base", _install_base_scripts), ("current", None)):
        repo, project = _subdir_repo(tmp_path / label)
        if install is not None:
            shutil.rmtree(project / "scripts")
            install(project)
        _set_layout(project, _SUBDIR_LAYOUT)
        proc = _run(project, "index-specs.py")
        assert proc.returncode == 0, proc.stderr
        reports[label] = (project / "specs" / "INDEX.md").read_text("utf-8")
    assert "## Footprint warnings" not in reports["base"]
    assert "**FR-0001 ↔ FR-0002**: shared files: `lib/x.py`" in reports["current"]


# covers hub-tooling FR-0023:AC-2
def test_only_the_root_moves_project_relative_owns_stop_matching(tmp_path):
    repo, project = _subdir_repo(tmp_path)
    _write(project, {"src/a.py": "A = 1\n"})
    _git(repo, "add", "-A")
    _set_layout(project, "footprint_root: repo\n")
    files = spec_footprint._git_ls_files(project_layout.load(project))
    fp = spec_footprint.Footprint

    def overlaps(a: str, b: str) -> list:
        recs = [
            spec_footprint.FRRecord("FR-0001", "ready", fp(owns=(a,), reads=())),
            spec_footprint.FRRecord("FR-0002", "ready", fp(owns=(b,), reads=())),
        ]
        return spec_footprint.find_overlaps(recs, repo_files=files)

    assert overlaps("src/a.py", "src/**") == []  # project-relative: no file
    [o] = overlaps("proj/src/a.py", "proj/src/**")
    assert o.shared_files == frozenset({"proj/src/a.py"})


# ---------------------------------------------------------------------------
# AC-3
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-3
def test_declared_dir_that_is_a_file_is_skipped_without_error(tmp_path):
    repo, project = _subdir_repo(tmp_path)
    _write(repo, {"notadir.py": f"# {_COVERS} FR-0001:AC-1\n"})
    _set_layout(
        project,
        "project_name: demo\nfootprint_root: repo\n"
        "gate:\n  source_dirs: [notadir.py, lib]\n  test_dirs: [notadir.py, lib_tests]\n",
    )
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert _counts(proc) == (1, 1)


_EXPLICIT_DEFAULTS = (
    "footprint_root: project\ngate:\n  source_dirs: [src]\n  test_dirs: [tests]\n"
)


# covers hub-tooling FR-0023:AC-3
def test_explicit_defaults_and_empty_mapping_match_no_layout_byte_for_byte(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-q")
    _install_scripts(project)
    _write(
        project / "specs",
        {
            "FR-0001-a.md": _fr(
                "FR-0001",
                status="in-review",
                owns="[src/a.py]",
                body="- **AC-1:** one\n- **AC-2 (labelled):** two",
            ),
            "FR-0002-b.md": _plain_fr("FR-0002", owns="[src/**]"),
        },
    )
    _write(
        project,
        {
            "tests/test_a.py": f"# {_COVERS} FR-0001:AC-1\n",
            "src/a.py": f"# {_IMPLEMENTS} FR-0001\n# {_IMPLEMENTS} FR-0077\n",
            "lib/b.py": f"# {_IMPLEMENTS} FR-0002\n",
        },
    )
    _git(project, "add", "-A")
    seen = []
    for text in (None, "{}\n", _EXPLICIT_DEFAULTS):
        _set_layout(project, text)
        out = []
        for script, args in (
            ("index-specs.py", ()),
            ("deploy-gate.py", ("--stage", "dev", "--status-only")),
            ("deploy-gate.py", ("--stage", "full", "--status-only")),
        ):
            proc = _run(project, script, *args, METRICS_LOG_DISABLED="1")
            index = (project / "specs" / "INDEX.md").read_bytes()
            out.append((script, args, proc.returncode, proc.stdout, proc.stderr, index))
        seen.append(out)
    assert seen[0] == seen[1] == seen[2]
    # Not trivially green: full fails on the uncovered labelled AC-2.
    assert seen[0][2][2] == 1 and "no @covers test for AC-2" in seen[0][2][4]


# ---------------------------------------------------------------------------
# AC-4
# ---------------------------------------------------------------------------


def _labelled_project(tmp_path: Path, test_text: str) -> Path:
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(
        project / "specs",
        {
            "FR-0001-a.md": _fr(
                "FR-0001",
                status="in-review",
                body="- **AC-1 (with `code`):** labelled\n- **AC-2:** plain",
            )
        },
    )
    _write(project, {"tests/test_a.py": test_text})
    _set_layout(project, "project_name: demo\n")
    return project


# covers hub-tooling FR-0023:AC-4
def test_qualified_annotations_cover_fr0027_labelled_acs(tmp_path):
    project = _labelled_project(
        tmp_path,
        f"{_QUALIFIED} demo FR-0001:AC-1\n{_QUALIFIED} demo FR-0001:AC-2\n",
    )
    proc = _gate(project, "--stage", "full", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (2, 0)


# covers hub-tooling FR-0023:AC-4
def test_uncovered_labelled_ac_still_fails_with_only_qualified_coverage(tmp_path):
    project = _labelled_project(tmp_path, f"{_QUALIFIED} demo FR-0001:AC-2\n")
    proc = _gate(project, "--stage", "full", "--status-only")
    assert proc.returncode == 1
    assert "FR-0001 (in-review): no @covers test for AC-1" in proc.stderr


# covers hub-tooling FR-0023:AC-4
def test_qualified_annotation_on_an_ac_neither_form_defines_is_unknown(tmp_path):
    project = _labelled_project(tmp_path, f"{_QUALIFIED} demo FR-0001:AC-3\n")
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 1
    assert "@covers references FR-0001:AC-3 but that AC is not in the FR" in proc.stderr


@pytest.mark.parametrize(
    ("name", "annotated"),
    [("hub", "hub-tooling"), ("hub-tooling", "hub"), ("a", "a-a"), ("a-a", "a")],
    ids=["prefix-name", "suffix-name", "short", "long"],
)
# covers hub-tooling FR-0023:AC-4
def test_names_that_prefix_each_other_do_not_cross_count(tmp_path, name, annotated):
    project = _labelled_project(tmp_path, f"{_QUALIFIED} {annotated} FR-0001:AC-9\n")
    _set_layout(project, f"project_name: {name}\n")
    proc = _gate(project, "--stage", "dev", "--status-only")
    # AC-9 is unknown: counting it would fail covers-unknown-ac.
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (0, 0)


@pytest.mark.parametrize(
    "line",
    [
        "# Covers demo FR-0001:AC-9",
        "# covers DEMO FR-0001:AC-9",
        "# " + _COVERS + " demo FR-0001:AC-9",
        "// covers demo FR-0001:AC-9",
        "# covers demo fr-0001:AC-9",
        "# covers demo FR-001:AC-9",
    ],
    ids=["capital", "upper-name", "at-form", "slashes", "lower-fr", "short-fr"],
)
# covers hub-tooling FR-0023:AC-4
def test_near_miss_qualified_forms_are_not_counted(tmp_path, line):
    project = _labelled_project(tmp_path, line + "\n")
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (0, 0)


# covers hub-tooling FR-0023:AC-4
def test_two_qualified_annotations_on_one_line_both_count(tmp_path):
    project = _labelled_project(
        tmp_path,
        f"x = 1  {_QUALIFIED} demo FR-0001:AC-1 {_QUALIFIED} demo FR-0001:AC-2\n",
    )
    proc = _gate(project, "--stage", "full", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (2, 0)


# covers hub-tooling FR-0023:AC-4
def test_qualified_annotation_outside_a_source_extension_is_not_counted(tmp_path):
    project = _labelled_project(tmp_path, "")
    _write(project, {"tests/notes.md": f"{_QUALIFIED} demo FR-0001:AC-9\n"})
    proc = _gate(project, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _counts(proc) == (0, 0)


# ---------------------------------------------------------------------------
# AC-2/AC-3/AC-4 bite: the base gate ignores the layout entirely
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-3
# covers hub-tooling FR-0023:AC-4
def test_bite_the_base_gate_counts_nothing_the_layout_declares(tmp_path):
    counts = {}
    for label, install in (("base", _install_base_scripts), ("current", None)):
        _, project = _subdir_repo(tmp_path / label)
        if install is not None:
            shutil.rmtree(project / "scripts")
            install(project)
        _set_layout(project, _SUBDIR_LAYOUT)
        counts[label] = _counts(_gate(project, "--stage", "dev", "--status-only"))
    assert counts == {"base": (0, 0), "current": (1, 1)}


# ---------------------------------------------------------------------------
# AC-5
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0023:AC-5
def test_template_suite_from_the_hub_root_takes_template_as_rootdir():
    if not _IS_HUB:
        pytest.skip("hub CI exists only in the hub")
    steps = yaml.safe_load(
        (_HUB_DIR / ".github/workflows/validate.yml").read_text("utf-8")
    )["jobs"]["validate"]["steps"]
    suites = [s for s in steps if "-m pytest" in str(s.get("run", ""))]
    assert [s["run"] for s in suites] == [
        "python -m pytest tests -q",
        "python -m pytest template/tests -q",
    ]
    assert all("working-directory" not in s for s in suites)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "template/tests/unit/scripts/test_project_layout.py",
        ],
        cwd=_HUB_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=_env(),
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
    m = re.search(r"^rootdir: (.+)$", proc.stdout, re.MULTILINE)
    assert m and os.path.samefile(m.group(1).strip(), _TEMPLATE_DIR), proc.stdout[:500]
    assert "configfile: pytest.ini" in proc.stdout


# ---------------------------------------------------------------------------
# AC-6: hub-tooling's real layout, re-checked in-process (read-only)
# ---------------------------------------------------------------------------

_GATE_PROBE = r"""
import importlib.util, json, sys
from pathlib import Path
from types import SimpleNamespace
import yaml
scripts, project = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location("gate_probe", scripts / "deploy-gate.py")
gate = importlib.util.module_from_spec(spec)
sys.modules["gate_probe"] = gate
spec.loader.exec_module(gate)
import project_layout
layout = project_layout.load(project)
frs = []
for p in sorted((project / "specs").glob("FR-*.md")):
    fm = yaml.safe_load(p.read_text(encoding="utf-8").split("---", 2)[1])
    frs.append(SimpleNamespace(id=fm["id"], status=fm["status"], path=p))
summaries = gate._load_fr_summaries(frs)
covers = gate.collect_covers(layout)
print(json.dumps({
    "acs": {k: [v.status, sorted(v.acs)] for k, v in summaries.items()},
    "covers": {k: sorted(int(a[3:]) for a in v) for k, v in covers.items()},
}))
"""


def _hub_tooling_or_skip() -> Path:
    if not _IS_HUB or not (_HUB_TOOLING / _LAYOUT).is_file():
        pytest.skip("hub-tooling's layout exists only in the hub")
    return _HUB_TOOLING


# covers hub-tooling FR-0023:AC-6
def test_hub_tooling_annotations_all_resolve_and_fr0001_to_fr0014_are_covered():
    project = _hub_tooling_or_skip()
    proc = subprocess.run(
        [sys.executable, "-c", _GATE_PROBE, str(_SCRIPTS_DIR), str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=_env(),
    )
    data = json.loads(proc.stdout)
    acs = {k: (v[0], set(v[1])) for k, v in data["acs"].items()}
    covers = {k: set(v) for k, v in data["covers"].items()}
    assert sorted(set(covers) - set(acs)) == []  # no covers-unknown-fr
    unknown_ac = sorted((fr, n) for fr, ns in covers.items() for n in ns - acs[fr][1])
    assert unknown_ac == []  # no covers-unknown-ac
    for n in range(1, 15):
        fr = f"FR-{n:04d}"
        assert acs[fr][1], fr
        assert acs[fr][1] - covers.get(fr, set()) == set(), fr
    assert 12 in covers["FR-0001"]  # FR-0027's annotation, seen via tests/


# covers hub-tooling FR-0023:AC-6
def test_hub_tooling_overlaps_equal_an_independent_git_glob_computation():
    project = _hub_tooling_or_skip()
    layout = project_layout.load(project)
    records = []
    for p in sorted((project / "specs").glob("FR-*.md")):
        fm = yaml.safe_load(p.read_text(encoding="utf-8").split("---", 2)[1])
        records.append(
            spec_footprint.FRRecord(
                fm["id"], fm["status"], spec_footprint.parse_footprint(fm)
            )
        )
    observed = {
        (o.fr_a, o.fr_b): set(o.shared_files)
        for o in spec_footprint.find_overlaps(
            records, repo_files=spec_footprint._git_ls_files(layout)
        )
    }
    root = layout.root
    expanded = {}
    for r in records:
        if r.status not in ("ready", "in-progress", "in-review"):
            continue
        files: set[str] = set()
        for g in r.footprint.owns:
            files |= set(_git(root, "ls-files", "--", f":(glob){g}").split())
        expanded[r.id] = files
    expected = {}
    ids = sorted(expanded)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if expanded[a] & expanded[b]:
                expected[(a, b)] = expanded[a] & expanded[b]
    assert observed == expected
    if observed:
        shared = set().union(*observed.values())
        assert any(not f.startswith("projects/hub-tooling/") for f in shared)


# ---------------------------------------------------------------------------
# AC-7: byte-identity against the commit FR-0023 sits on, labelled AC included
# ---------------------------------------------------------------------------

_VOLATILE = {"ts", "record_id", "run_id", "duration_ms"}


def _labelled_tree(root: Path) -> None:
    _write(
        root / "specs",
        {
            "FR-0001-a.md": _fr(
                "FR-0001",
                status="in-review",
                owns="[src/a.py]",
                body="- **AC-1 (labelled `x`):** one\n- **AC-2:** two\n\nSee AC-1.",
            ),
            "FR-0002-b.md": _plain_fr("FR-0002", owns="[src/**]"),
        },
    )
    _write(
        root,
        {
            "tests/test_a.py": (
                f"# {_COVERS} FR-0001:AC-1\n{_QUALIFIED} synthetic FR-0001:AC-2\n"
            ),
            "src/a.py": f"# {_IMPLEMENTS} FR-0001\n",
        },
    )


# covers hub-tooling FR-0023:AC-7
def test_no_layout_is_byte_identical_to_fr0023s_own_base_with_labelled_acs(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    observed = []
    for label, install in (
        ("base", _install_base_scripts),
        ("current", _install_scripts),
    ):
        project = tmp_path / label / "proj"
        project.mkdir(parents=True)
        install(project)
        _labelled_tree(project)
        _git(project, "init", "-q")
        _git(project, "add", "-A")
        out = []
        for inv in (
            ("index-specs.py", "--validate"),
            ("index-specs.py", "--ac-hashes"),
            ("index-specs.py",),
            ("deploy-gate.py", "--stage", "dev"),
            ("deploy-gate.py", "--stage", "full"),
            ("deploy-gate.py", "--status-only"),
        ):
            index = project / "specs" / "INDEX.md"
            if index.exists():
                index.unlink()
            proc = _run(project, *inv)
            written = index.read_bytes() if index.exists() else None
            out.append((inv, proc.returncode, proc.stdout, proc.stderr, written))
        d = project / "specs" / "_metrics"
        out.append(
            [
                {k: v for k, v in json.loads(ln).items() if k not in _VOLATILE}
                for f in sorted(d.glob("*.ndjson"))
                for ln in f.read_text("utf-8").splitlines()
                if ln.strip()
            ]
            if d.exists()
            else []
        )
        observed.append(out)
    assert observed[0] == observed[1]
    # The labelled AC is live at the base (FR-0027 is below FR-0023): full
    # fails on AC-2 only, never on AC-1.
    full = observed[1][4]
    assert full[1] == 1 and "no @covers test for AC-2" in full[3]
    assert "AC-1" not in full[3].split("Deploy gate FAILED:")[-1]


# ---------------------------------------------------------------------------
# Round 2: DEC-0027 item 6, the layout-only drive-letter rejection
# ---------------------------------------------------------------------------

_KEYS = ("source_dirs", "test_dirs")


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize(
    "entry",
    ["C:", "z:/", "C:.", "c:/Mixed/Case"],
    ids=["bare-drive", "drive-root", "drive-dot", "mixed-case"],
)
# covers hub-tooling FR-0023:AC-1
def test_every_drive_form_is_refused_under_both_keys(tmp_path, entry, key):
    # Each passes `_validate_glob` (no leading `/`, no `..`, no backslash),
    # so only the drive rule can refuse it. Letter drives are drives on every
    # supported Python.
    assert spec_footprint._validate_glob("FR-0001", "owns", entry) == entry
    assert PureWindowsPath(entry).drive
    _set_layout(tmp_path, f"gate:\n  {key}: ['{entry}']\n")
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(tmp_path)
    msg = str(exc.value)
    assert msg.startswith(f"{_LAYOUT}: gate.{key} entry {entry!r}"), msg


@pytest.mark.parametrize("key", _KEYS)
# covers hub-tooling FR-0023:AC-1
def test_a_digit_drive_follows_pure_windows_path_on_this_python(tmp_path, key):
    # The rule is "`PureWindowsPath(entry).drive` is non-empty" (AC-1,
    # DEC-0027 item 6). Whether `1:x` has a drive depends on the Python:
    # 3.11's pathlib accepts only ASCII letters as drives (drive ''), 3.12+
    # accepts any character ('1:'). Either way the entry must be refused or
    # stay under the footprint root, never resolve outside it.
    entry = "1:x"
    _set_layout(tmp_path, f"gate:\n  {key}: ['{entry}']\n")
    if PureWindowsPath(entry).drive:
        with pytest.raises(project_layout.LayoutInvalid) as exc:
            project_layout.load(tmp_path)
        msg = str(exc.value)
        assert msg.startswith(f"{_LAYOUT}: gate.{key} entry {entry!r}"), msg
    else:
        layout = project_layout.load(tmp_path)
        assert getattr(layout, key) == (entry,)
        paths = layout.source_paths if key == "source_dirs" else layout.test_paths
        [path] = paths
        path.relative_to(layout.root)  # raises if the root were discarded


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize(
    "entry",
    [r"\\server\share", "//?/C:/x", "//server"],
    ids=["backslash-unc", "extended-path", "bare-unc"],
)
# covers hub-tooling FR-0023:AC-1
def test_unc_forms_are_refused_by_one_rule_or_the_other(tmp_path, entry, key):
    _set_layout(tmp_path, f"gate:\n  {key}: [{json.dumps(entry)}]\n")
    with pytest.raises(project_layout.LayoutInvalid) as exc:
        project_layout.load(tmp_path)
    msg = str(exc.value)
    assert msg.startswith(f"{_LAYOUT}:") and f"gate.{key}" in msg, msg


@pytest.mark.parametrize("entry", ["lib/C:/x", "ab:c", "a/b:c", ":x"])
# covers hub-tooling FR-0023:AC-1
# covers hub-tooling FR-0023:AC-3
def test_a_colon_outside_the_drive_position_is_allowed_and_stays_under_root(
    tmp_path, entry
):
    _set_layout(tmp_path, f"gate:\n  source_dirs: ['{entry}']\n  test_dirs: [t]\n")
    layout = project_layout.load(tmp_path)
    assert layout.source_dirs == (entry,)
    [path] = layout.source_paths
    path.relative_to(layout.root)  # raises if the root were discarded


# covers hub-tooling FR-0023:AC-1
def test_the_drive_rule_is_layout_only_and_owns_is_unchanged(tmp_path):
    # Same tree: an FR owns a drive-letter path (still valid `owns:` syntax,
    # solution_space.fixed line 2) while the layout uses one as a gate
    # directory. The indexer reports exactly one error, the layout's, first.
    project = tmp_path / "proj"
    _install_scripts(project)
    _write(project / "specs", {"FR-0001-a.md": _plain_fr("FR-0001", owns="['C:/x']")})
    _set_layout(project, "gate:\n  test_dirs: ['C:/x']\n")
    proc = _run(project, "index-specs.py", "--validate")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    errors = [ln for ln in proc.stderr.splitlines() if ln.startswith("  - ")]
    assert proc.stderr.splitlines()[0] == "Spec validation FAILED:"
    assert errors == [
        f"  - {_LAYOUT}: gate.test_dirs entry 'C:/x' has a drive or UNC root; "
        "directories must be relative to the footprint root"
    ]
    _set_layout(project, None)
    ok = _run(project, "index-specs.py", "--validate")
    assert ok.returncode == 0, ok.stderr


# covers hub-tooling FR-0023:AC-3
def test_template_scripts_implements_tags_never_fail_a_project_gate(tmp_path):
    # Template scripts carry hub-tooling `@implements` tags (FR-0023's among
    # them) into every bootstrapped project. Unlike r1's ride-along `@covers`
    # (FR-0027 K-1), they cannot fail a gate: scripts/ is not scanned by
    # default, and an unknown-FR `@implements` is a warning even when a
    # project lists scripts/ against the example's advice.
    tag = re.compile(r"@implements\s+FR-0023\b")
    assert any(tag.search(p.read_text("utf-8")) for p in _SCRIPTS_DIR.glob("*.py"))
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    for p in _SCRIPTS_DIR.glob("*.py"):
        shutil.copy(p, project / "scripts" / p.name)
    _write(project / "specs", {"FR-0001-a.md": _plain_fr("FR-0001", status="merged")})
    _write(project, {"tests/test_a.py": f"# {_COVERS} FR-0001:AC-1\n"})
    for layout, warned in ((None, False), ("gate:\n  source_dirs: [scripts]\n", True)):
        _set_layout(project, layout)
        proc = _gate(project, "--stage", "full", "--status-only")
        assert proc.returncode == 0, (layout, proc.stderr)
        assert ("@implements references unknown FR FR-0023" in proc.stderr) is warned
