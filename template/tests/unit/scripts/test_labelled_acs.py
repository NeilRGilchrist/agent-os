"""Tests for hub-tooling FR-0027: a labelled AC bullet `- **AC-N (L):** R` is an
AC to the indexer (`parse_acs`, AC-1) and hashes as `(L) R` (AC-2), and to the
deploy gate's checks 2 and 3 and its `ac-format` warning (AC-3). A tree with no
labelled bullet behaves byte-for-byte as at the base ref (AC-4), the pinned
patterns and existing pins hold (AC-5), and the hub's own FR-0001 is fully
gate-visible (AC-6).

Gate and indexer behaviour is driven through subprocess copies of the team
scripts in a temporary repo, as `test_deploy_gate_scope.py` does. The base ref
(`_BASE_REF`, `main` when FR-0027 was dispatched) is loaded with `git show` for
the AC-4 comparison, the AC-5 pattern pins and the bite checks; those skip where
hub history is unreachable (a bootstrapped project has none). The AC-6 tests
read the hub's real FR-0001 and hub tests, read-only, and skip outside the hub.

Coverage annotations use the ride-along form `# covers hub-tooling FR-0027:AC-N`:
this file travels into every bootstrapped project, where no FR-0027 exists.
Every fixture is synthetic (see `tests/fixtures/labelled-acs/README.md`).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# in a bootstrapped project).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_BODIES = _TEMPLATE_DIR / "tests" / "fixtures" / "labelled-acs" / "bodies"
_COPY_SCRIPTS = (
    "deploy-gate.py",
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
)
_SIBLING_MODULES = (
    "index_specs",
    "spec_footprint",
    "spec_query",
    "metrics_log",
    "dispatch",
)
_METRICS_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
)
# `main` at the commit FR-0027 was dispatched from: the scripts before FR-0027.
_BASE_REF = "b803216"
# Split so a bootstrapped project's gate, which regex-scans tests/, never reads
# these fixture strings as real annotations.
_COVERS = "@" + "covers"

# The hub's own files that AC-6 reads (hub-relative).
_HUB_FR0001 = "projects/hub-tooling/specs/FR-0001-profile-aware-upgrade.md"
_HUB_TESTS = "tests"


# ---------------------------------------------------------------------------
# Synthetic FRs
# ---------------------------------------------------------------------------


def _body(name: str) -> str:
    return (_BODIES / f"{name}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def _fr(
    fr_id: str,
    body: str,
    *,
    status: str = "ready",
    ac_state: dict[int, tuple[str, str | None]] | None = None,
    owns: str = "[]",
) -> str:
    if ac_state:
        lines = ["ac_state:"]
        for n, (state, digest) in sorted(ac_state.items()):
            entry = f"state: {state}" + (f", hash: {digest}" if digest else "")
            lines.append(f"  {n}: {{{entry}}}")
        ac_state_block = "\n".join(lines)
    else:
        ac_state_block = "ac_state: {}"
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
        f"{ac_state_block}\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n"
        f"{body}"
    )


def _covers(*refs: str) -> dict[str, str]:
    return {"test_synthetic.py": "".join(f"# {_COVERS} {r}\n" for r in refs)}


# The three ACs of `all-labelled.md`, as `parse_acs` must return them (AC-2).
_ALL_LABELLED_ACS = {
    1: "(first label) Does thing one.",
    2: (
        "(`--flag` is set, with commas - and (nested) parens) Does thing two.\n"
        "  It continues on this line.\n"
        "\n"
        "  And on this one, after a blank line."
    ),
    3: "(empty rest)",
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _git_show(ref: str, rel: str) -> bytes | None:
    hub = _TEMPLATE_DIR.parent
    probe = subprocess.run(
        ["git", "-C", str(hub), "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    proc = subprocess.run(
        ["git", "-C", str(hub), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _base_scripts() -> dict[str, bytes]:
    """The base ref's copies of every script a temp repo carries."""
    out: dict[str, bytes] = {}
    for name in _COPY_SCRIPTS:
        data = _git_show(_BASE_REF, f"template/scripts/{name}")
        if data is None:
            pytest.skip(f"hub history for {_BASE_REF} is not reachable")
        out[name] = data
    return out


def _build_repo(
    base: Path,
    specs: dict[str, str],
    *,
    tests: dict[str, str] | None = None,
    scripts: dict[str, bytes] | None = None,
    codeowners: bool = False,
) -> Path:
    repo = base
    (repo / "scripts").mkdir(parents=True)
    for name in _COPY_SCRIPTS:
        if scripts is not None:
            (repo / "scripts" / name).write_bytes(scripts[name])
        else:
            shutil.copy(_SCRIPTS_DIR / name, repo / "scripts" / name)
    for folder, files in (("specs", specs), ("tests", tests or {})):
        (repo / folder).mkdir(exist_ok=True)
        for rel, content in files.items():
            target = repo / folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
    if codeowners:
        (repo / ".agent-team").mkdir()
        (repo / ".agent-team" / "codeowners-config.yaml").write_bytes(
            b'owner_handle: "@synthetic-team"\n'
        )
    return repo


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=_env(),
    )


def _gate(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(repo, "deploy-gate.py", *args)


def _ac_hashes(repo: Path, target: str = "*") -> list[str]:
    proc = _run(repo, "index-specs.py", "--ac-hashes", target)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


def _records(repo: Path) -> list[dict]:
    d = repo / "specs" / "_metrics"
    if not d.exists():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.ndjson")):
        out.extend(
            json.loads(ln)
            for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        )
    return out


def _snapshot(repo: Path) -> dict[str, str]:
    """sha256 of every file except scripts, the metrics log and bytecode."""
    out: dict[str, str] = {}
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo).as_posix()
        if (
            rel.startswith("scripts/")
            or rel.startswith("specs/_metrics/")
            or "__pycache__" in rel
        ):
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@contextlib.contextmanager
def _isolated_imports(scripts_dir: Path) -> Iterator[None]:
    """Let a script and its siblings be imported from `scripts_dir` without
    leaving them in `sys.modules` / `sys.path` for the rest of the session."""
    saved_modules = dict(sys.modules)
    saved_path = list(sys.path)
    for name in _SIBLING_MODULES:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path


def _load(path: Path, module_name: str):  # type: ignore[no-untyped-def]
    with _isolated_imports(path.parent):
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_CURRENT: dict[str, object] = {}


def _current(script: str):  # type: ignore[no-untyped-def]
    if script not in _CURRENT:
        name = "fr0027_current_" + script.replace("-", "_").removesuffix(".py")
        _CURRENT[script] = _load(_SCRIPTS_DIR / script, name)
    return _CURRENT[script]


def _base(script: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    scripts = _base_scripts()
    d = tmp_path / "base-scripts"
    if not d.exists():
        d.mkdir()
        for name, data in scripts.items():
            (d / name).write_bytes(data)
    name = "fr0027_base_" + script.replace("-", "_").removesuffix(".py")
    return _load(d / script, name)


def _parse_acs(idx, text: str) -> dict[int, str]:  # type: ignore[no-untyped-def]
    match = idx.FRONTMATTER_PATTERN.match(text)
    return idx.parse_acs(text[match.end() :] if match else text)


def _gate_acs(gate, path: Path) -> set[int]:  # type: ignore[no-untyped-def]
    """The gate's detected AC set for one FR file, through `_load_fr_summaries`."""
    fr = SimpleNamespace(id="FR-0000", status="ready", path=path)
    return gate._load_fr_summaries([fr])["FR-0000"].acs


def _near_miss_lines() -> list[str]:
    return [ln for ln in _body("near-misses").splitlines() if ln.startswith("- ")]


# ---------------------------------------------------------------------------
# AC-1: the indexer parses a labelled bullet as an AC
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0027:AC-1
def test_all_labelled_body_parses_every_ac_with_continuations():
    idx = _current("index-specs.py")
    assert idx.parse_acs(_body("all-labelled")) == _ALL_LABELLED_ACS


# covers hub-tooling FR-0027:AC-1
def test_mixed_body_parses_both_forms_with_continuations():
    idx = _current("index-specs.py")
    assert idx.parse_acs(_body("mixed")) == {
        1: "Plain one.",
        2: "(labelled two) Labelled two.\n  Continuation of two.",
        3: "Plain three.",
    }


# covers hub-tooling FR-0027:AC-1
def test_labelled_bullet_outside_the_section_is_ignored():
    idx = _current("index-specs.py")
    assert idx.parse_acs(_body("outside-section")) == {1: "(inside) The only AC."}


# covers hub-tooling FR-0027:AC-1
def test_indented_labelled_bullet_is_a_continuation_line_to_the_indexer():
    idx = _current("index-specs.py")
    assert idx.parse_acs(_body("indented")) == {
        1: "Plain one.\n  - **AC-2 (indented label):** Indented labelled two."
    }


# covers hub-tooling FR-0027:AC-1
def test_label_with_backticks_and_nested_parens_ends_at_first_close_colon_bold():
    idx = _current("index-specs.py")
    section = "## Acceptance criteria\n\n- **AC-4 (`a` (b), c - d):** e):** f\n"
    assert idx.parse_acs(section) == {4: "(`a` (b), c - d) e):** f"}
    # A tab between the number and the label is accepted too.
    assert idx.parse_acs("## Acceptance criteria\n\n- **AC-5\t(t):** u\n") == {
        5: "(t) u"
    }


# covers hub-tooling FR-0027:AC-1
@pytest.mark.parametrize(
    "line", _near_miss_lines(), ids=[f"shape{i}" for i in range(1, 7)]
)
def test_each_not_labelled_shape_keeps_todays_treatment(line):
    idx = _current("index-specs.py")
    section = f"## Acceptance criteria\n\n{line}\n"
    expected = (
        {1: "(looks like a label) but is a plain bullet."} if "AC-1:" in line else {}
    )
    assert idx.parse_acs(section) == expected
    assert not idx.AC_LABELLED_LINE_PATTERN.match(line)


# covers hub-tooling FR-0027:AC-1
def test_duplicate_numbers_across_forms_behave_as_duplicate_plain_bullets():
    idx = _current("index-specs.py")
    labelled = "## Acceptance criteria\n\n- **AC-1 (x):** first\n- **AC-1:** second\n"
    plain = "## Acceptance criteria\n\n- **AC-1:** first\n- **AC-1:** second\n"
    assert idx.parse_acs(labelled) == idx.parse_acs(plain) == {1: "second"}
    # The later labelled duplicate wins, as a later plain `(x) second` would.
    labelled = "## Acceptance criteria\n\n- **AC-1:** first\n- **AC-1 (x):** second\n"
    plain = "## Acceptance criteria\n\n- **AC-1:** first\n- **AC-1:** (x) second\n"
    assert idx.parse_acs(labelled) == idx.parse_acs(plain) == {1: "(x) second"}


# covers hub-tooling FR-0027:AC-1
def test_plain_and_not_labelled_bodies_parse_as_at_the_base_ref(tmp_path):
    idx = _current("index-specs.py")
    base = _base("index-specs.py", tmp_path)
    for name in ("plain", "near-misses"):
        assert idx.parse_acs(_body(name)) == base.parse_acs(_body(name)), name
    for line in _near_miss_lines():
        section = f"## Acceptance criteria\n\n{line}\n"
        assert idx.parse_acs(section) == base.parse_acs(section), line


# covers hub-tooling FR-0027:AC-1
def test_bite_the_base_indexer_parses_no_labelled_ac(tmp_path):
    base = _base("index-specs.py", tmp_path)
    assert base.parse_acs(_body("all-labelled")) == {}
    assert base.parse_acs(_body("mixed")) != _current("index-specs.py").parse_acs(
        _body("mixed")
    )


# ---------------------------------------------------------------------------
# AC-2: a labelled AC hashes as `(L) R`
# ---------------------------------------------------------------------------


def _hash_lines_for(tmp_path: Path, name: str, body: str) -> list[str]:
    repo = _build_repo(tmp_path / name, {"FR-0100-a.md": _fr("FR-0100", body)})
    return _ac_hashes(repo, "FR-0100")


# covers hub-tooling FR-0027:AC-2
def test_labelled_and_plain_rewrite_print_equal_ac_hash_lines(tmp_path):
    labelled = (
        "\n## Acceptance criteria\n\n- **AC-1 (the label):** The rest.\n  More.\n"
    )
    plain = "\n## Acceptance criteria\n\n- **AC-1:** (the label) The rest.\n  More.\n"
    a = _hash_lines_for(tmp_path, "labelled", labelled)
    b = _hash_lines_for(tmp_path, "plain", plain)
    assert len(a) == 1 and a == b
    idx = _current("index-specs.py")
    assert a == [f"FR-0100 AC-1: {idx.ac_hash('(the label) The rest. More.')}"]


# covers hub-tooling FR-0027:AC-2
def test_empty_rest_hashes_as_the_label_alone(tmp_path):
    idx = _current("index-specs.py")
    lines = _hash_lines_for(tmp_path, "all", _body("all-labelled"))
    assert lines[2] == f"FR-0100 AC-3: {idx.ac_hash('(empty rest)')}"


# covers hub-tooling FR-0027:AC-2
def test_relabelling_changes_the_hash(tmp_path):
    a = _hash_lines_for(
        tmp_path, "one", "\n## Acceptance criteria\n\n- **AC-1 (one):** Same rest.\n"
    )
    b = _hash_lines_for(
        tmp_path, "two", "\n## Acceptance criteria\n\n- **AC-1 (two):** Same rest.\n"
    )
    assert len(a) == len(b) == 1 and a != b


# covers hub-tooling FR-0027:AC-2
def test_ac_hashes_prints_labelled_acs_in_number_order_with_plain_ones(tmp_path):
    idx = _current("index-specs.py")
    lines = _hash_lines_for(tmp_path, "mixed", _body("mixed"))
    expected = idx.parse_acs(_body("mixed"))
    assert lines == [
        f"FR-0100 AC-{n}: {idx.ac_hash(expected[n])}" for n in sorted(expected)
    ]
    assert len(lines) == 3


# covers hub-tooling FR-0027:AC-2
def test_ratified_labelled_ac_raises_no_ratification_warning(tmp_path):
    body = _body("mixed")
    repo = _build_repo(tmp_path / "r", {"FR-0100-a.md": _fr("FR-0100", body)})
    hashes = {
        int(m.group(1)): m.group(2)
        for m in (re.match(r"FR-0100 AC-(\d+): (\w+)$", ln) for ln in _ac_hashes(repo))
        if m
    }
    assert sorted(hashes) == [1, 2, 3]
    ratified = {n: ("ratified", h) for n, h in hashes.items()}
    (repo / "specs" / "FR-0100-a.md").write_bytes(
        _fr("FR-0100", body, ac_state=ratified).encode("utf-8")
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert "AC ratification warnings" not in proc.stdout + proc.stderr
    assert "no matching" not in proc.stdout + proc.stderr
    index = (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "## AC ratification warnings" not in index

    # Changing only the label is drift on a ratified AC.
    relabelled = body.replace("(labelled two)", "(relabelled two)")
    (repo / "specs" / "FR-0100-a.md").write_bytes(
        _fr("FR-0100", relabelled, ac_state=ratified).encode("utf-8")
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert "FR-0100 AC-2: ratified text changed since sign-off" in proc.stderr
    assert "FR-0100 AC-1:" not in proc.stderr and "FR-0100 AC-3:" not in proc.stderr


# covers hub-tooling FR-0027:AC-2
def test_ac_state_keyed_on_a_labelled_ac_has_a_matching_ac(tmp_path):
    body = "\n## Acceptance criteria\n\n- **AC-1 (only):** One.\n"
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", body, ac_state={1: ("proposed", None)})},
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert "no matching acceptance criterion" not in proc.stderr
    assert "AC ratification warnings" not in proc.stderr


# covers hub-tooling FR-0027:AC-2
def test_bite_the_base_indexer_prints_no_hash_for_a_labelled_ac(tmp_path):
    scripts = _base_scripts()
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", _body("all-labelled"))},
        scripts=scripts,
    )
    assert _ac_hashes(repo) == []


# ---------------------------------------------------------------------------
# AC-3: the gate detects a labelled bullet as an AC
# ---------------------------------------------------------------------------

_UNEXPECTED = "contains AC references in unexpected format"


# covers hub-tooling FR-0027:AC-3
@pytest.mark.parametrize(
    "name, expected",
    [("all-labelled", {1, 2, 3}), ("mixed", {1, 2, 3}), ("indented", {1, 2})],
)
def test_gate_detects_labelled_bullets_including_indented(tmp_path, name, expected):
    gate = _current("deploy-gate.py")
    path = tmp_path / "FR-0000-x.md"
    path.write_bytes(_fr("FR-0000", _body(name)).encode("utf-8"))
    assert _gate_acs(gate, path) == expected


# covers hub-tooling FR-0027:AC-3
def test_gate_detection_of_not_labelled_shapes_is_unchanged(tmp_path):
    gate = _current("deploy-gate.py")
    path = tmp_path / "FR-0000-x.md"
    path.write_bytes(_fr("FR-0000", _body("near-misses")).encode("utf-8"))
    assert _gate_acs(gate, path) == {1}
    for line in _near_miss_lines():
        assert not gate.AC_LABELLED_PATTERN.search(line), line


# covers hub-tooling FR-0027:AC-3
@pytest.mark.parametrize("name", ["all-labelled", "mixed", "indented"])
@pytest.mark.parametrize("stage", ["dev", "full"])
def test_check2_covers_on_labelled_acs_pass(tmp_path, name, stage):
    acs = {"all-labelled": 3, "mixed": 3, "indented": 2}[name]
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", _body(name), status="merged")},
        tests=_covers(*(f"FR-0100:AC-{n}" for n in range(1, acs + 1))),
    )
    proc = _gate(repo, "--stage", stage)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"{acs} @covers annotations" in proc.stdout
    assert _UNEXPECTED not in proc.stderr


# covers hub-tooling FR-0027:AC-3
@pytest.mark.parametrize("stage", ["dev", "full"])
def test_check2_unknown_ac_still_fails_with_todays_message(tmp_path, stage):
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", _body("mixed"))},
        tests=_covers("FR-0100:AC-2", "FR-0100:AC-9"),
    )
    proc = _gate(repo, "--stage", stage)
    assert proc.returncode == 1
    lines = proc.stderr.splitlines()
    assert "  - @covers references FR-0100:AC-9 but that AC is not in the FR" in lines
    assert not any("FR-0100:AC-2 but" in ln for ln in lines)
    (rec,) = _records(repo)
    assert rec["failure_classes"] == ["covers-unknown-ac"]


# covers hub-tooling FR-0027:AC-3
@pytest.mark.parametrize("status", ["in-review", "merged"])
@pytest.mark.parametrize("stage", ["dev", "review", "full"])
def test_check3_uncovered_labelled_ac_fails_coverage_missing(tmp_path, status, stage):
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", _body("mixed"), status=status)},
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-3"),
    )
    proc = _gate(repo, "--stage", stage)
    (rec,) = _records(repo)
    if stage == "dev":
        assert proc.returncode == 0, proc.stderr
        assert rec["failure_classes"] == []
        return
    assert proc.returncode == 1
    assert (
        f"  - FR-0100 ({status}): no @covers test for AC-2" in proc.stderr.splitlines()
    )
    assert rec["failure_classes"] == ["coverage-missing"]


# covers hub-tooling FR-0027:AC-3
@pytest.mark.parametrize("stage", ["review", "full"])
def test_check3_covered_labelled_ac_passes(tmp_path, stage):
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", _body("all-labelled"), status="merged")},
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-3"),
    )
    proc = _gate(repo, "--stage", stage)
    assert proc.returncode == 0, proc.stderr


# covers hub-tooling FR-0027:AC-3
def test_ac_format_not_raised_for_labelled_mentions_but_still_for_undetected(tmp_path):
    clean = _build_repo(
        tmp_path / "clean", {"FR-0100-a.md": _fr("FR-0100", _body("all-labelled"))}
    )
    proc = _gate(clean, "--stage", "dev")
    assert proc.returncode == 0, proc.stderr
    assert _UNEXPECTED not in proc.stderr
    (rec,) = _records(clean)
    assert "ac-format" not in rec["warning_classes"]

    body = _body("all-labelled").replace("Synthetic notes.", "See AC-7 and AC-2.")
    noisy = _build_repo(tmp_path / "noisy", {"FR-0100-a.md": _fr("FR-0100", body)})
    proc = _gate(noisy, "--stage", "dev")
    assert proc.returncode == 0, proc.stderr
    assert (
        "WARN: FR-0100-a.md contains AC references in unexpected format: AC-7 "
        "— consider using '**AC-N:**' format"
    ) in proc.stderr.splitlines()
    (rec,) = _records(noisy)
    assert rec["warning_classes"] == ["ac-format"]


# covers hub-tooling FR-0027:AC-3
def test_bite_the_base_gate_rejects_covers_on_labelled_acs(tmp_path):
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", _body("all-labelled"), status="merged")},
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-3"),
        scripts=_base_scripts(),
    )
    proc = _gate(repo, "--stage", "dev")
    assert proc.returncode == 1
    assert "@covers references FR-0100:AC-1 but that AC is not in the FR" in proc.stderr
    assert _UNEXPECTED in proc.stderr


# ---------------------------------------------------------------------------
# AC-4: no labelled bullet, no change
# ---------------------------------------------------------------------------


def _no_labelled_tree() -> tuple[dict[str, str], dict[str, str]]:
    """Every AC-4 path: plain ACs; every not-labelled shape (also an
    `ac-format` trigger); covered ACs; an uncovered AC on a merged FR; an
    unknown-AC `@covers`; and a ratified `ac_state` entry."""
    idx = _current("index-specs.py")
    plain = _body("plain")
    ratified = {
        1: ("ratified", idx.ac_hash(idx.parse_acs(plain)[1])),
        2: ("proposed", None),
    }
    specs = {
        "FR-0100-plain.md": _fr(
            "FR-0100", plain, status="merged", ac_state=ratified, owns="[src/a/**]"
        ),
        "FR-0101-near-misses.md": _fr(
            "FR-0101", _body("near-misses"), owns="[src/b/**]"
        ),
    }
    tests = _covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-9", "FR-0101:AC-1")
    return specs, tests


def _normalise(text: str, repo: Path) -> str:
    return text.replace(str(repo), "<repo>").replace(repo.as_posix(), "<repo>")


def _strip_volatile(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in ("ts", "record_id")}


def _old_and_new(tmp_path: Path, label: str) -> tuple[Path, Path]:
    specs, tests = _no_labelled_tree()
    old = _build_repo(
        tmp_path / f"old-{label}",
        specs,
        tests=tests,
        scripts=_base_scripts(),
        codeowners=True,
    )
    new = _build_repo(tmp_path / f"new-{label}", specs, tests=tests, codeowners=True)
    return old, new


def _assert_same_run(
    old: Path, new: Path, script: str, args: tuple[str, ...]
) -> subprocess.CompletedProcess:
    p_old = _run(old, script, *args)
    p_new = _run(new, script, *args)
    assert p_new.returncode == p_old.returncode
    assert _normalise(p_new.stdout, new) == _normalise(p_old.stdout, old)
    assert _normalise(p_new.stderr, new) == _normalise(p_old.stderr, old)
    assert _snapshot(new) == _snapshot(old)
    assert [_strip_volatile(r) for r in _records(new)] == [
        _strip_volatile(r) for r in _records(old)
    ]
    return p_new


_INDEXER_RUNS: list[tuple[str, ...]] = [
    (),
    ("--validate",),
    ("--ac-hashes", "*"),
    ("--list", "all", "--json"),
    ("--slice", "FR-0100", "--json"),
]
_GATE_RUNS: list[tuple[str, ...]] = [
    ("--stage", "dev"),
    ("--stage", "review"),
    ("--stage", "full"),
    ("--status-only",),
]


# covers hub-tooling FR-0027:AC-4
@pytest.mark.parametrize(
    "args", _INDEXER_RUNS, ids=["plain", "validate", "ac-hashes", "list", "slice"]
)
def test_indexer_is_byte_identical_to_the_base_ref_without_labelled_acs(tmp_path, args):
    old, new = _old_and_new(tmp_path, "idx")
    proc = _assert_same_run(old, new, "index-specs.py", args)
    if args == ():
        assert (new / "specs" / "INDEX.md").exists()
        assert (new / "CODEOWNERS").exists()
        assert "## AC ratification warnings" in (new / "specs" / "INDEX.md").read_text(
            encoding="utf-8"
        )
    if args == ("--ac-hashes", "*"):
        assert [ln.split(":")[0] for ln in proc.stdout.splitlines()] == [
            "FR-0100 AC-1",
            "FR-0100 AC-2",
            "FR-0100 AC-3",
            "FR-0101 AC-1",
        ]


# covers hub-tooling FR-0027:AC-4
@pytest.mark.parametrize(
    "args", _GATE_RUNS, ids=["dev", "review", "full", "status-only"]
)
def test_gate_is_byte_identical_to_the_base_ref_without_labelled_acs(tmp_path, args):
    old, new = _old_and_new(tmp_path, "gate")
    proc = _assert_same_run(old, new, "deploy-gate.py", args)
    # The tree really exercises the paths it claims to.
    assert proc.returncode == 1
    assert "@covers references FR-0100:AC-9 but that AC is not in the FR" in proc.stderr
    assert "FR-0101-near-misses.md " + _UNEXPECTED in proc.stderr
    if args != ("--stage", "dev"):
        assert "FR-0100 (merged): no @covers test for AC-3" in proc.stderr
    records = _records(new)
    assert len(records) == (0 if "--status-only" in args else 1)


# covers hub-tooling FR-0027:AC-4
def test_labelled_tree_index_differs_only_in_ac_ratification_warnings(tmp_path):
    body = _body("mixed")
    specs = {
        "FR-0100-a.md": _fr("FR-0100", body, ac_state={1: ("proposed", None)}),
        "FR-0101-b.md": _fr("FR-0101", _body("all-labelled")),
    }
    old = _build_repo(tmp_path / "old", specs, scripts=_base_scripts())
    new = _build_repo(tmp_path / "new", specs)
    assert _run(old, "index-specs.py").returncode == 0
    assert _run(new, "index-specs.py").returncode == 0
    old_index = (old / "specs" / "INDEX.md").read_text(encoding="utf-8")
    new_index = (new / "specs" / "INDEX.md").read_text(encoding="utf-8")

    def _without_ac_warnings(text: str) -> str:
        return re.sub(
            r"\n## AC ratification warnings\n.*?(?=\n## |\Z)", "", text, flags=re.S
        )

    assert old_index != new_index
    assert _without_ac_warnings(old_index) == _without_ac_warnings(new_index)
    # Only FR-0100 (non-empty ac_state) differs; FR-0101 (labelled, unmanaged)
    # appears in neither warnings section.
    for index in (old_index, new_index):
        section = index.split("## AC ratification warnings", 1)[1]
        assert "FR-0101" not in section.split("\n## ", 1)[0]
    assert "FR-0100: no ac_state entry for AC-2, AC-3" in new_index


# ---------------------------------------------------------------------------
# AC-5: pinned patterns hold
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0027:AC-5
def test_existing_ac_patterns_equal_their_base_ref_values(tmp_path):
    idx_base = _base("index-specs.py", tmp_path)
    gate_base = _base("deploy-gate.py", tmp_path)
    idx = _current("index-specs.py")
    gate = _current("deploy-gate.py")
    for new, old in (
        (idx.AC_LINE_PATTERN, idx_base.AC_LINE_PATTERN),
        (gate.AC_HEADING_PATTERN, gate_base.AC_HEADING_PATTERN),
        (gate.AC_LOOSE_PATTERN, gate_base.AC_LOOSE_PATTERN),
    ):
        assert (new.pattern, new.flags) == (old.pattern, old.flags)
    # The labelled form is an additional pattern, not a loosened existing one.
    line = "- **AC-1 (L):** R"
    assert not idx.AC_LINE_PATTERN.match(line)
    assert idx.AC_LABELLED_LINE_PATTERN.match(line)
    assert not gate.AC_HEADING_PATTERN.search(line)
    assert gate.AC_LABELLED_PATTERN.search(line)


# covers hub-tooling FR-0027:AC-5
def test_gate_keeps_its_own_detection_and_adds_no_new_vocabulary():
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    assert "parse_acs" not in source
    for token in ("collect_trs", "collect_decs", "collect_graph", "DEC(", "TR("):
        assert token not in source, token
    assert "spec_query" not in source and "retired" not in source.lower()


# ---------------------------------------------------------------------------
# AC-6: the hub's FR-0001 is gate-visible and fully annotated
# ---------------------------------------------------------------------------


def _hub_root() -> Path:
    hub = _TEMPLATE_DIR.parent
    if not (hub / _HUB_FR0001).is_file() or not (hub / _HUB_TESTS).is_dir():
        pytest.skip("not running inside the hub (no hub FR-0001 / tests/)")
    return hub


def _hub_fr0001_covers(gate, hub: Path) -> list[int]:  # type: ignore[no-untyped-def]
    nums: list[int] = []
    for path in sorted((hub / _HUB_TESTS).rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in gate.COVERS_PATTERN.finditer(text):
            if m.group(1) == "FR-0001":
                nums.append(int(m.group(2).removeprefix("AC-")))
    return nums


# covers hub-tooling FR-0027:AC-6
def test_hub_fr0001_gate_detects_exactly_ac1_to_ac12():
    hub = _hub_root()
    gate = _current("deploy-gate.py")
    assert _gate_acs(gate, hub / _HUB_FR0001) == set(range(1, 13))


# covers hub-tooling FR-0027:AC-6
def test_hub_fr0001_parse_acs_yields_twelve_acs_each_led_by_its_label():
    hub = _hub_root()
    idx = _current("index-specs.py")
    text = (hub / _HUB_FR0001).read_text(encoding="utf-8")
    acs = _parse_acs(idx, text)
    assert sorted(acs) == list(range(1, 13))
    for n, ac_text in acs.items():
        m = re.search(rf"^- \*\*AC-{n} \((.+?)\):\*\*", text, re.M)
        assert m and ac_text.startswith(f"({m.group(1)}) "), n


# covers hub-tooling FR-0027:AC-6
def test_hub_fr0001_every_covers_names_a_detected_ac():
    hub = _hub_root()
    gate = _current("deploy-gate.py")
    detected = _gate_acs(gate, hub / _HUB_FR0001)
    nums = _hub_fr0001_covers(gate, hub)
    assert nums, "the hub's tests/ carry no FR-0001 annotations"
    assert set(nums) <= detected


# covers hub-tooling FR-0027:AC-6
def test_hub_fr0001_has_no_check3_failure_under_fr0023_layout():
    """Every detected AC is covered by the hub's tests/, AC-12 included. The
    AC-12 annotation is the Reviewer's one-line addition to
    `tests/unit/scripts/test_bootstrap_profiles.py`."""
    hub = _hub_root()
    gate = _current("deploy-gate.py")
    detected = _gate_acs(gate, hub / _HUB_FR0001)
    covered = set(_hub_fr0001_covers(gate, hub))
    assert 12 in covered, f"no {_COVERS} FR-0001:AC-12 in the hub's tests/"
    assert sorted(detected - covered) == []


# covers hub-tooling FR-0027:AC-6
def test_bite_the_base_gate_and_indexer_detect_nothing_in_hub_fr0001(tmp_path):
    hub = _hub_root()
    gate_base = _base("deploy-gate.py", tmp_path)
    idx_base = _base("index-specs.py", tmp_path)
    assert _gate_acs(gate_base, hub / _HUB_FR0001) == set()
    text = (hub / _HUB_FR0001).read_text(encoding="utf-8")
    assert _parse_acs(idx_base, text) == {}
