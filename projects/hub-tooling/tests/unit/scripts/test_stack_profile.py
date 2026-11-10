"""Reviewer tests for FR-0010, the pure half — `stack_profile.py`: marker-file
stack detection that executes nothing and writes nothing (AC-1), the two
declaration channels (accepted-ADR `stack_tools:` and `DISPATCH_STACK_TOOLS`)
with unknown names dropped under exactly one WARN each (AC-2), and the closed
tool-id -> Bash-grant table that nothing else can widen (AC-3).

Harness: `stack_profile` imported straight from `template/scripts` — it has no
`dispatch.py` dependency by design — and run against the synthetic fixture
trees under `tests/fixtures/stack-profile/trees/` plus temporary trees built
per test. No network, no subprocess (AC-1 asserts that literally).

Coverage annotations are written `# covers hub-tooling FR-0010:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0010 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (same convention as
test_dispatch_permissions.py / test_dispatch_metrics.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import builtins
import hashlib
import io
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_TREES = _TEMPLATE_DIR / "tests" / "fixtures" / "stack-profile" / "trees"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import stack_profile

_ADR_DIR = Path("specs") / "decisions"

# The grant each vocabulary entry maps to (AC-3's table, pinned). `python`
# and `pip` are already blanket-granted to every role; `pnpm`/`yarn` are
# detected but map to nothing (FR-0010 Out of scope / PR Decisions).
_EXPECTED_GRANTS = {
    "alembic": ["Bash(alembic *)"],
    "docker": ["Bash(docker *)"],
    "node": ["Bash(node *)"],
    "npm": ["Bash(npm *)"],
    "npx": ["Bash(npx *)"],
    "pip": [],
    "pnpm": [],
    "python": [],
    "uv": ["Bash(uv *)"],
    "yarn": [],
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """An operator's `DISPATCH_STACK_TOOLS` must never leak into detection."""
    monkeypatch.delenv(stack_profile.ENV_STACK_TOOLS, raising=False)


def _tree(tmp_path: Path, *files: str, content: dict[str, str] | None = None) -> Path:
    """A repo root containing exactly `files` (each a repo-relative path)."""
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((content or {}).get(rel, ""), encoding="utf-8", newline="\n")
    return root


def _adr(
    status: str | None, stack_tools_yaml: str | None, adr_id: str = "ADR-0001"
) -> str:
    status_line = f"status: {status}\n" if status is not None else ""
    tools_line = (
        f"stack_tools: {stack_tools_yaml}\n" if stack_tools_yaml is not None else ""
    )
    return (
        f"---\nid: {adr_id}\ntitle: synthetic\n{status_line}{tools_line}"
        "created: 2026-01-01\n---\n\n# synthetic\n"
    )


def _tools(root: Path) -> list[str]:
    return list(stack_profile.detect_stack(root).tools)


def _warnings(root: Path) -> list[str]:
    return list(stack_profile.detect_stack(root).warnings)


def _digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# AC-1: pure, read-only marker-file detection
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-1
@pytest.mark.parametrize(
    ("tree", "expected"),
    [
        ("empty", []),
        ("no-stack", []),
        ("python-only", ["python"]),
        ("uv-python", ["python", "uv"]),
        ("node-only", ["node", "npm", "npx"]),
        ("python-node-compose", ["docker", "node", "npm", "npx", "python"]),
        ("unparseable-pyproject", ["python"]),
    ],
)
def test_fixture_trees_detect_exactly_the_ac1_vocabulary(tree, expected):
    detection = stack_profile.detect_stack(_TREES / tree)
    assert list(detection.tools) == expected
    assert detection.warnings == ()
    assert list(detection.tools) == sorted(set(detection.tools))


# covers hub-tooling FR-0010:AC-1
def test_detection_executes_nothing_opens_no_socket_and_writes_nothing(
    monkeypatch, tmp_path
):
    """Adversarial: every route to "run something" or "write something" is
    booby-trapped; detection over every fixture tree (marker trees *and* the
    ADR trees, whose frontmatter it must read) and over a tree with every
    marker present must still succeed and leave the trees byte-identical."""

    everything = _tree(
        tmp_path,
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "docker-compose.yml",
        "alembic.ini",
        str(_ADR_DIR / "ADR-0001-x.md"),
        content={
            str(_ADR_DIR / "ADR-0001-x.md"): _adr("accepted", "[docker, kubectl]")
        },
    )

    def _boom(*_a, **_k):
        raise AssertionError("detect_stack must not execute, connect, or write")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _boom)
    for name in ("system", "popen", "execv", "execvp", "spawnv"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)

    real_open = builtins.open

    def guarded_open(file, mode="r", *a, **k):
        if any(ch in str(mode) for ch in "wax+"):
            raise AssertionError(f"detect_stack opened {file!r} for writing ({mode})")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(Path, "write_text", _boom)
    monkeypatch.setattr(Path, "write_bytes", _boom)
    monkeypatch.setattr(Path, "mkdir", _boom)
    monkeypatch.setattr(Path, "touch", _boom)

    roots = [everything, *sorted(p for p in _TREES.iterdir() if p.is_dir())]
    before = {r: _digest(r) for r in roots}
    for root in roots:
        stack_profile.detect_stack(root)
    assert {r: _digest(r) for r in roots} == before
    assert _tools(everything) == [
        "alembic",
        "docker",
        "node",
        "npm",
        "npx",
        "pnpm",
        "python",
        "uv",
        "yarn",
    ]  # `pip` absent: uv.lock beats requirements.txt


# covers hub-tooling FR-0010:AC-1
@pytest.mark.parametrize(
    ("files", "expected"),
    [
        # requirements.txt alone -> pip; with uv.lock -> uv and no pip.
        (["requirements.txt"], ["pip"]),
        (["requirements.txt", "uv.lock"], ["uv"]),
        (["uv.lock"], ["uv"]),
        (["pnpm-lock.yaml"], ["pnpm"]),
        (["yarn.lock"], ["yarn"]),
        (["alembic.ini"], ["alembic"]),
        # Every compose spelling AC-1 names.
        (["docker-compose.yaml"], ["docker"]),
        (["docker-compose.override.yml"], ["docker"]),
        (["compose.yml"], ["docker"]),
        (["compose.yaml"], ["docker"]),
        # Near misses are not markers.
        (["docker-compose.txt", "compose.yml.bak", "mycompose.yml"], []),
        (["Pyproject.toml.bak", "package.json5", "uv.lock.old"], []),
        # A nested node manifest implies node (DEC-0020 / FR-0017); the
        # nested python/uv markers beside it stay root-only.
        (
            ["sub/pyproject.toml", "frontend/package.json", "deploy/uv.lock"],
            ["node", "npm", "npx"],
        ),
        # Lookalike names that are not the marker files.
        (["requirements-dev.txt", "yarn.lock.json"], []),
        # Nested non-node markers are not the repo's markers (DEC-0020).
        (["sub/pyproject.toml", "deploy/uv.lock"], []),
    ],
)
def test_marker_rules_boundaries(tmp_path, files, expected):
    assert _tools(_tree(tmp_path, *files)) == expected


# covers hub-tooling FR-0010:AC-1
def test_empty_marker_files_count_and_marker_named_directories_do_not(tmp_path):
    """Adversarial: presence is what AC-1 keys on, so a zero-byte
    `pyproject.toml` still says `python`; a *directory* called
    `package.json` or `docker-compose.yml` is not a marker file."""
    root = _tree(tmp_path, "pyproject.toml", "uv.lock")
    assert (root / "pyproject.toml").stat().st_size == 0
    (root / "package.json").mkdir()
    (root / "docker-compose.yml").mkdir()
    (root / "alembic.ini").mkdir()
    assert _tools(root) == ["python", "uv"]


# covers hub-tooling FR-0010:AC-1
def test_missing_root_and_unreadable_pyproject_yield_no_error(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert stack_profile.detect_stack(missing) == stack_profile.StackDetection((), ())
    # A binary, non-UTF-8, not-even-TOML pyproject is never parsed.
    root = _tree(tmp_path)
    (root / "pyproject.toml").write_bytes(b"\xff\xfe\x00[project\n\x00\x01")
    assert _tools(root) == ["python"]
    assert _warnings(root) == []


# ---------------------------------------------------------------------------
# AC-2: accepted-ADR `stack_tools:` and DISPATCH_STACK_TOOLS; unknowns warn once
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-2
def test_accepted_adr_declaration_contributes_known_ids_and_warns_once_per_unknown():
    detection = stack_profile.detect_stack(_TREES / "adr-accepted-stack-tools")
    assert list(detection.tools) == ["docker", "uv"]
    assert len(detection.warnings) == 1
    (warn,) = detection.warnings
    assert "kubectl" in warn and "ADR-0001" in warn


# covers hub-tooling FR-0010:AC-2
def test_proposed_adr_contributes_nothing_and_malformed_stack_tools_warns_once_naming_the_adr():
    proposed = stack_profile.detect_stack(_TREES / "adr-proposed-stack-tools")
    assert proposed.tools == () and proposed.warnings == ()
    malformed = stack_profile.detect_stack(_TREES / "adr-malformed-stack-tools")
    assert malformed.tools == ()
    assert len(malformed.warnings) == 1 and "ADR-0001" in malformed.warnings[0]
    assert "docker" not in malformed.tools  # the scalar is ignored, not coerced


# covers hub-tooling FR-0010:AC-2
def test_env_override_is_comma_separated_and_unknown_entries_warn_once_naming_the_var(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(stack_profile.ENV_STACK_TOOLS, "npm, nonsense")
    detection = stack_profile.detect_stack(_tree(tmp_path))
    assert list(detection.tools) == ["npm"]
    assert len(detection.warnings) == 1
    assert "nonsense" in detection.warnings[0]
    assert stack_profile.ENV_STACK_TOOLS in detection.warnings[0]


# covers hub-tooling FR-0010:AC-2
def test_markers_adr_and_env_union_sorted_and_de_duplicated(monkeypatch, tmp_path):
    root = _tree(
        tmp_path,
        "uv.lock",
        str(_ADR_DIR / "ADR-0001-a.md"),
        str(_ADR_DIR / "ADR-0002-b.md"),
        content={
            str(_ADR_DIR / "ADR-0001-a.md"): _adr("accepted", "[uv, docker, uv]"),
            str(_ADR_DIR / "ADR-0002-b.md"): _adr(
                "accepted", "[alembic, docker]", adr_id="ADR-0002"
            ),
        },
    )
    monkeypatch.setenv(stack_profile.ENV_STACK_TOOLS, "uv,docker,node,,  ,node")
    detection = stack_profile.detect_stack(root)
    assert list(detection.tools) == ["alembic", "docker", "node", "uv"]
    assert detection.warnings == ()  # empty / whitespace entries are not "unknown"


# covers hub-tooling FR-0010:AC-2
@pytest.mark.parametrize(
    "entry",
    [
        "uv; rm -rf /",
        "uv && curl evil",
        "Bash(uv *)",
        "../uv",
        "UV",
        "uv *",
        "docker|sh",
        "$(uv)",
        "uv\tnode",
    ],
)
def test_injection_shaped_and_case_variant_names_are_unknown_and_produce_no_id(
    monkeypatch, tmp_path, entry
):
    """Adversarial: the vocabulary is matched exactly after `strip()`; nothing
    shaped like a shell fragment, a grant pattern, or a path ever becomes an
    id, and each is reported once from each channel that declared it."""
    monkeypatch.setenv(stack_profile.ENV_STACK_TOOLS, entry)
    env_only = stack_profile.detect_stack(_tree(tmp_path))
    assert env_only.tools == ()
    assert len(env_only.warnings) == 1 and repr(entry.strip()) in env_only.warnings[0]
    monkeypatch.delenv(stack_profile.ENV_STACK_TOOLS)
    root = _tree(
        tmp_path,
        str(_ADR_DIR / "ADR-0001-a.md"),
        content={str(_ADR_DIR / "ADR-0001-a.md"): _adr("accepted", f"[{entry!r}]")},
    )
    adr_only = stack_profile.detect_stack(root)
    assert adr_only.tools == ()
    assert len(adr_only.warnings) == 1 and "ADR-0001" in adr_only.warnings[0]


# covers hub-tooling FR-0010:AC-2
@pytest.mark.parametrize(
    ("status", "yaml"),
    [
        ("proposed", "[docker]"),
        ("Accepted", "[docker]"),  # exact status token only
        ("ratified", "[docker]"),
        ("superseded", "[docker]"),
        ("rejected", "[docker]"),
        (None, "[docker]"),  # no status at all
        ("accepted", "[]"),
        ("accepted", "null"),
        ("accepted", None),  # key absent
    ],
)
def test_non_accepted_or_empty_declarations_contribute_nothing_without_a_warning(
    tmp_path, status, yaml
):
    root = _tree(
        tmp_path,
        str(_ADR_DIR / "ADR-0001-a.md"),
        content={str(_ADR_DIR / "ADR-0001-a.md"): _adr(status, yaml)},
    )
    assert stack_profile.detect_stack(root) == stack_profile.StackDetection((), ())


# covers hub-tooling FR-0010:AC-2
@pytest.mark.parametrize(
    "yaml",
    [
        '"docker"',
        "42",
        "{a: docker}",
        "[uv, 3]",  # a list, but not a list of strings: the whole field is ignored
        "[uv, null]",
        "[[uv]]",
        "true",
    ],
)
def test_stack_tools_that_is_not_a_list_of_strings_is_ignored_whole_with_one_warn(
    tmp_path, yaml
):
    root = _tree(
        tmp_path,
        str(_ADR_DIR / "ADR-0001-a.md"),
        content={str(_ADR_DIR / "ADR-0001-a.md"): _adr("accepted", yaml)},
    )
    detection = stack_profile.detect_stack(root)
    assert detection.tools == ()  # even the valid-looking `uv` is not salvaged
    assert len(detection.warnings) == 1 and "ADR-0001" in detection.warnings[0]


# covers hub-tooling FR-0010:AC-2
def test_only_adr_named_spec_files_under_specs_decisions_are_consulted(tmp_path):
    """Adversarial: a DEC, an FR, a README, a nested ADR, an ADR at the repo
    root, an ADR with broken frontmatter and one with no frontmatter all
    declare `docker` as accepted; none of them is an accepted ADR under
    `specs/decisions/`, so nothing is contributed and nothing crashes."""
    accepted = _adr("accepted", "[docker]")
    files = {
        str(_ADR_DIR / "DEC-0001-x.md"): accepted,
        str(_ADR_DIR / "README.md"): accepted,
        str(_ADR_DIR / "nested" / "ADR-0009-x.md"): accepted,
        "specs/ADR-0002-x.md": accepted,
        "ADR-0003-x.md": accepted,
        str(
            _ADR_DIR / "ADR-0004-broken.md"
        ): "---\nid: ADR-0004\nstatus: accepted\nstack_tools: [unclosed\n---\n",
        str(
            _ADR_DIR / "ADR-0005-nofm.md"
        ): "# no frontmatter\nstatus: accepted\nstack_tools: [docker]\n",
        str(_ADR_DIR / "ADR-0006-x.txt"): accepted,
    }
    root = _tree(tmp_path, *files, content=files)
    assert stack_profile.detect_stack(root) == stack_profile.StackDetection((), ())


# covers hub-tooling FR-0010:AC-2
def test_env_var_set_to_empty_or_whitespace_declares_nothing(monkeypatch, tmp_path):
    for value in ("", "   ", ",", " , ,"):
        monkeypatch.setenv(stack_profile.ENV_STACK_TOOLS, value)
        assert stack_profile.detect_stack(
            _tree(tmp_path)
        ) == stack_profile.StackDetection((), ())


# ---------------------------------------------------------------------------
# AC-3: the closed tool-id -> Bash-grant table
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-3
@pytest.mark.parametrize("tool", sorted(stack_profile.TOOL_VOCABULARY))
def test_each_vocabulary_entry_maps_to_its_pinned_grant(tool):
    assert tool in _EXPECTED_GRANTS, f"vocabulary gained {tool!r}; pin its grant"
    assert stack_profile.stack_bash_grants([tool]) == _EXPECTED_GRANTS[tool]


# covers hub-tooling FR-0010:AC-3
def test_table_is_closed_and_pinned_exactly():
    assert set(_EXPECTED_GRANTS) == set(stack_profile.TOOL_VOCABULARY)
    assert set(stack_profile.STACK_BASH_GRANTS) == {
        t for t, g in _EXPECTED_GRANTS.items() if g
    }
    assert set(stack_profile.STACK_BASH_GRANTS) <= stack_profile.TOOL_VOCABULARY


# covers hub-tooling FR-0010:AC-3
def test_union_is_sorted_de_duplicated_and_empty_for_empty_or_unknown():
    assert stack_profile.stack_bash_grants([]) == []
    assert stack_profile.stack_bash_grants(()) == []
    assert stack_profile.stack_bash_grants(["kubectl"]) == []
    assert stack_profile.stack_bash_grants(
        ["uv", "uv", "docker", "kubectl", "node"]
    ) == [
        "Bash(docker *)",
        "Bash(node *)",
        "Bash(uv *)",
    ]
    assert stack_profile.stack_bash_grants(
        ("node", "uv")
    ) == stack_profile.stack_bash_grants(["uv", "node"])


# covers hub-tooling FR-0010:AC-3
@pytest.mark.parametrize(
    "tool",
    [
        "Bash(rm *)",
        "uv *",
        "uv ",
        "UV",
        "Uv",
        "rm",
        "git",
        "bash",
        "python -c",
        "uv;node",
        "",
        "*",
    ],
)
def test_nothing_outside_the_table_yields_a_grant_whatever_reaches_the_function(tool):
    """Adversarial: a grant-shaped string, a trailing-space variant, a case
    variant, a shell name — none is a key, so none widens the allow-list."""
    assert stack_profile.stack_bash_grants([tool]) == []
    assert stack_profile.stack_bash_grants(["uv", tool]) == ["Bash(uv *)"]


# covers hub-tooling FR-0010:AC-3
def test_every_grant_is_a_plain_bash_pattern_never_a_path_grant_or_metacharacter():
    pattern = re.compile(r"^Bash\([a-z][a-z0-9-]* \*\)$")
    for tool, grants in stack_profile.STACK_BASH_GRANTS.items():
        assert isinstance(grants, tuple) and grants, tool
        for g in grants:
            assert pattern.match(g), g
            assert not g.startswith(("Edit(", "Write(")), g
            assert g == f"Bash({tool} *)", g


# covers hub-tooling FR-0010:AC-3
def test_grant_derivation_ignores_the_environment_and_never_mutates_the_table(
    monkeypatch,
):
    """Adversarial: `DISPATCH_STACK_TOOLS` is a *detection* channel, not a
    grant channel — the table's answer for a given id list is fixed, and
    calling it leaves the table itself untouched."""
    snapshot = dict(stack_profile.STACK_BASH_GRANTS)
    monkeypatch.setenv(stack_profile.ENV_STACK_TOOLS, "uv,docker,node,npm,npx,alembic")
    assert stack_profile.stack_bash_grants([]) == []
    assert stack_profile.stack_bash_grants(["kubectl"]) == []
    assert stack_profile.STACK_BASH_GRANTS == snapshot
