"""Reviewer tests for hub-tooling FR-0021: the deploy gate fails, before writing
anything, on every spec-graph error the indexer refuses (AC-1), by delegating to
one exported indexer function (AC-2); valid graphs behave exactly as before
(AC-3); the PASSED line states the gate's scope (AC-4); and two role files
describe the gate correctly (AC-5).

Every behavioural test drives the real `deploy-gate.py` as a subprocess in a
self-contained temporary repo (the team scripts are copied in), once with no
arguments at all and once per `--stage` / `--status-only`. "Wrote nothing" is
asserted as byte-identity of the whole tree, not by reading a message.

Bite checks load the pre-FR-0021 gate (`_BASELINE_REF`) from hub history and
show the AC-1 and AC-4 assertions fail against it; they skip where that commit
is unreachable (bootstrapped projects have no hub history).

Coverage annotations use the ride-along form `# covers hub-tooling FR-0021:AC-N`
rather than the gate's own annotation: this file travels into every
bootstrapped project, where no FR-0021 exists. Every fixture is synthetic.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# in a bootstrapped project).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_ROLES_DIR = _TEMPLATE_DIR / ".agent-team" / "roles"
_COMMANDS_DIR = _TEMPLATE_DIR / ".agent-team" / "commands"
_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "deploy-gate-scope"
_COPY_SCRIPTS = (
    "deploy-gate.py",
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
)
_METRICS_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
)
# The gate as it was before FR-0021 (identical to hub main @ 82670a5).
_BASELINE_REF = "a8889df"
# The FR-0021 implementation commit and its parent, for the AC-5 one-line diff.
_IMPL_REF = "e37dda9"
_IMPL_PARENT_REF = "82670a5"
# Split so a bootstrapped project's gate, which regex-scans tests/, never reads
# these fixture strings as real annotations.
_COVERS = "@" + "covers"
_IMPLEMENTS = "@" + "implements"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_FAIL_HEADER = "Spec index validation failed:"
_DEV_CLAUSE = "; scope: spec graph, annotations; tests not run"
_FULL_CLAUSE = (
    "; scope: spec graph, annotations, AC coverage, gate evidence; tests not run"
)
_CLAUSE = {"dev": _DEV_CLAUSE, "review": _FULL_CLAUSE, "full": _FULL_CLAUSE}

# Every invocation shape the gate accepts: no arguments at all, each stage, and
# each of those under --status-only.
_INVOCATIONS: list[tuple[str, ...]] = [
    (),
    ("--stage", "dev"),
    ("--stage", "review"),
    ("--stage", "full"),
    ("--status-only",),
    ("--stage", "dev", "--status-only"),
    ("--stage", "review", "--status-only"),
    ("--stage", "full", "--status-only"),
]
_INVOCATION_IDS = ["-".join(a).replace("--", "") or "no-args" for a in _INVOCATIONS]


def _stage_of(args: tuple[str, ...]) -> str:
    return args[args.index("--stage") + 1] if "--stage" in args else "full"


# ---------------------------------------------------------------------------
# Synthetic spec fixtures
# ---------------------------------------------------------------------------


def _fr(fr_id: str, *, status: str = "ready", extra: str = "", acs: int = 2) -> str:
    extra_block = f"{extra.rstrip()}\n" if extra.strip() else ""
    ac_lines = "\n".join(f"- **AC-{n}:** does thing {n}" for n in range(1, acs + 1))
    return (
        "---\n"
        f"id: {fr_id}\n"
        f"title: Synthetic {fr_id}\n"
        f"status: {status}\n"
        "owner: architect\n"
        "depends_on: []\n"
        "tags: []\n"
        "owns: []\n"
        "reads: []\n"
        "derived_from: null\n"
        "pattern: null\n"
        "ac_state: {}\n"
        f"{extra_block}"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n"
        f"# {fr_id}: Synthetic\n\n"
        "## Acceptance criteria\n\n"
        f"{ac_lines}\n"
    )


def _frontmatter(fields: dict[str, str]) -> str:
    return "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n"


def _tr(tr_id: str, **overrides: str) -> str:
    fields = {
        "id": tr_id,
        "title": f"Synthetic {tr_id}",
        "operationalises": "[FR-0100]",
    }
    fields.update(overrides)
    fields.setdefault("created", "2026-01-01")
    fields.setdefault("updated", "2026-01-02")
    return (
        _frontmatter(fields) + f"\n# {tr_id}: Synthetic\n\n## Approach\n\nSynthetic.\n"
    )


def _dec(dec_id: str, **overrides: str) -> str:
    fields = {
        "id": dec_id,
        "title": f"Synthetic {dec_id}",
        "tier": "agent",
        "status": "ratified",
        "revises": "null",
    }
    fields.update(overrides)
    if fields["revises"] != "null":
        fields.setdefault("breaking", "false")
    fields.setdefault("rationale", f"Synthetic decision {dec_id}.")
    fields.setdefault("created", "2026-01-01")
    fields.setdefault("updated", "2026-01-03")
    return (
        _frontmatter(fields) + f"\n# {dec_id}: Synthetic\n\n## Context\n\nSynthetic.\n"
    )


def _dec_accepted_tree() -> dict[str, str]:
    """The DEC-0001 shape, read from the committed fixture."""
    root = _FIXTURES / "dec-accepted" / "specs"
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.md"))
    }


# Broken trees: each is refused by `index-specs.py --validate`. The needles are
# substrings the indexer's own wording must contain, so a tree that silently
# became valid (or broke differently) is caught.
_BROKEN: dict[str, tuple[dict[str, str], tuple[str, ...]]] = {
    "dec-accepted": (
        _dec_accepted_tree(),
        (
            "DEC-0001-accepted-token.md: status 'accepted' not in",
            "FR-0100-dec-shape.md: revisions references unknown DEC 'DEC-0001'",
        ),
    ),
    "tr-parse-error": (
        {
            "FR-0100-a.md": _fr("FR-0100"),
            "TR-0001-bad.md": _tr("TR-0001", operationalises="FR-0100"),
        },
        ("TR-0001-bad.md: operationalises must be a non-empty list",),
    ),
    "dec-supersedes-unresolved": (
        {
            "FR-0100-a.md": _fr("FR-0100"),
            "decisions/DEC-0002-b.md": _dec("DEC-0002", supersedes="DEC-0999"),
        },
        ("DEC-0002-b.md: supersedes references unknown DEC 'DEC-0999'",),
    ),
    "tr-supersedes-unresolved": (
        {
            "FR-0100-a.md": _fr("FR-0100"),
            "TR-0001-a.md": _tr("TR-0001", supersedes="TR-0999"),
        },
        ("TR-0001-a.md: supersedes references unknown TR 'TR-0999'",),
    ),
    "fr-supersedes-unresolved": (
        {"FR-0100-a.md": _fr("FR-0100", extra="supersedes: FR-0999")},
        ("FR-0100-a.md: supersedes references unknown FR 'FR-0999'",),
    ),
    "fr-depends-unknown": (
        {
            "FR-0100-a.md": _fr("FR-0100").replace(
                "depends_on: []", "depends_on: [FR-0999]"
            )
        },
        ("FR-0100-a.md: depends_on references unknown FR 'FR-0999'",),
    ),
    "mixed-with-duplicate": (
        {
            "FR-0100-a.md": _fr("FR-0100", extra="revisions: [DEC-0007]"),
            "FR-0101-b.md": _fr("FR-0101", status="not-a-status"),
            "TR-0001-a.md": _tr("TR-0001", title='""'),
            "decisions/DEC-0003-c.md": _dec(
                "DEC-0003", constrained_by="[FR-0998, FR-0998]"
            ),
        },
        (
            "FR-0101-b.md: status 'not-a-status'",
            "TR-0001-a.md: title must be a non-empty string",
            "FR-0100-a.md: revisions references unknown DEC 'DEC-0007'",
            "DEC-0003-c.md: constrained_by references unknown FR 'FR-0998'",
        ),
    ),
}


def _happy_tree() -> dict[str, str]:
    """Valid: FR, TR, DECs, plus one warn-only versioning lint (a proposed DEC
    revising the FR) so warnings are known not to count as errors."""
    return {
        "FR-0100-a.md": _fr("FR-0100"),
        "TR-0001-approach.md": _tr("TR-0001", revisions="[DEC-0001]"),
        "decisions/DEC-0001-first.md": _dec("DEC-0001", revises="TR-0001"),
        "decisions/DEC-0002-proposed.md": _dec(
            "DEC-0002", status="proposed", revises="FR-0100"
        ),
    }


def _fr_only_tree() -> dict[str, str]:
    return {"FR-0100-a.md": _fr("FR-0100"), "FR-0101-b.md": _fr("FR-0101", acs=3)}


def _annotated_tree() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Passes every stage with non-zero covers/implements counts: FR-0100 is
    in-review with every AC covered and implemented."""
    specs = {
        "FR-0100-a.md": _fr("FR-0100", status="in-review"),
        "FR-0101-b.md": _fr("FR-0101"),
    }
    tests = {"test_a.py": f"# {_COVERS} FR-0100:AC-1\n# {_COVERS} FR-0100:AC-2\n"}
    src = {"a.py": f"# {_IMPLEMENTS} FR-0100\n"}
    return specs, tests, src


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _build_repo(
    base: Path,
    specs: dict[str, str],
    *,
    tests: dict[str, str] | None = None,
    src: dict[str, str] | None = None,
    gate_source: bytes | None = None,
) -> Path:
    repo = base
    (repo / "scripts").mkdir(parents=True)
    for name in _COPY_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / name, repo / "scripts" / name)
    if gate_source is not None:
        (repo / "scripts" / "deploy-gate.py").write_bytes(gate_source)
    for folder, files in (("specs", specs), ("tests", tests or {}), ("src", src or {})):
        (repo / folder).mkdir(exist_ok=True)
        for rel, content in files.items():
            target = repo / folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
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


def _snapshot(repo: Path) -> dict[str, str]:
    """sha256 of every file except the metrics log and bytecode caches."""
    out: dict[str, str] = {}
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo).as_posix()
        if rel.startswith("specs/_metrics/") or "__pycache__" in rel:
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _lint_lines(stderr: str) -> list[str]:
    return [
        ln
        for ln in stderr.splitlines()
        if not ln.startswith("WARN: spec_footprint:") and not ln.startswith("INFO:")
    ]


def _indexer_errors(repo: Path) -> list[str]:
    """The errors `index-specs.py --validate` reports, in order, duplicates kept."""
    proc = _run(repo, "index-specs.py", "--validate")
    lines = _lint_lines(proc.stderr)
    if proc.returncode == 0:
        return []
    assert proc.returncode == 1, proc.stderr
    start = lines.index("Spec validation FAILED:")
    return [ln[len("  - ") :] for ln in lines[start + 1 :] if ln.startswith("  - ")]


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


def _baseline_gate() -> bytes:
    data = _git_show(_BASELINE_REF, "template/scripts/deploy-gate.py")
    if data is None or b"def _run_checks" not in data:
        pytest.skip(f"hub history for {_BASELINE_REF} is not reachable")
    return data


# ---------------------------------------------------------------------------
# Shared assertions (reused verbatim by the bite checks)
# ---------------------------------------------------------------------------

_SENTINEL_INDEX = b"# sentinel INDEX\r\nnot what the indexer would render\r\n"


def _assert_refuses_and_writes_nothing(
    repo: Path, args: tuple[str, ...], expected: list[str]
) -> subprocess.CompletedProcess:
    """AC-1 in full for one invocation: rc 1, the header plus one line per
    distinct indexer error in the indexer's wording, nothing on stdout, and no
    file created, changed or removed (the metrics log aside)."""
    before = _snapshot(repo)
    proc = _gate(repo, *args)
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    distinct = list(dict.fromkeys(expected))
    assert _lint_lines(proc.stderr) == [_FAIL_HEADER] + [f"  {e}" for e in distinct], (
        proc.stderr
    )
    assert proc.stdout == "", proc.stdout
    assert _snapshot(repo) == before
    return proc


def _passed_line_re(stage: str) -> re.Pattern[str]:
    return re.compile(
        rf"Deploy gate PASSED \(stage={stage}\): \d+ FRs, \d+ @covers annotations, "
        rf"\d+ @implements annotations{re.escape(_CLAUSE[stage])}"
    )


def _assert_passed_line(stdout: str, stage: str) -> None:
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout
    assert stdout.isascii(), stdout
    assert _passed_line_re(stage).fullmatch(lines[0]), lines[0]


# ---------------------------------------------------------------------------
# AC-1: every indexer error fails the gate before anything is written
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0021:AC-1
@pytest.mark.parametrize("args", _INVOCATIONS, ids=_INVOCATION_IDS)
@pytest.mark.parametrize("tree", sorted(_BROKEN))
def test_every_indexer_error_fails_the_gate_and_an_existing_index_is_untouched(
    tmp_path, tree, args
):
    specs, needles = _BROKEN[tree]
    repo = _build_repo(tmp_path / "r", specs)
    (repo / "specs" / "INDEX.md").write_bytes(_SENTINEL_INDEX)

    expected = _indexer_errors(repo)
    assert expected, f"{tree} must be refused by the indexer"
    for needle in needles:
        assert any(needle in e for e in expected), (needle, expected)

    _assert_refuses_and_writes_nothing(repo, args, expected)
    assert (repo / "specs" / "INDEX.md").read_bytes() == _SENTINEL_INDEX


# covers hub-tooling FR-0021:AC-1
@pytest.mark.parametrize("args", _INVOCATIONS, ids=_INVOCATION_IDS)
def test_dec_accepted_shape_creates_no_index_when_none_existed(tmp_path, args):
    specs, _ = _BROKEN["dec-accepted"]
    repo = _build_repo(tmp_path / "r", specs)
    expected = _indexer_errors(repo)
    assert len(expected) == 2, expected
    _assert_refuses_and_writes_nothing(repo, args, expected)
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0021:AC-1
def test_each_distinct_error_is_printed_once(tmp_path):
    # An FR-graph error is seen by both the FR-only validator and the full
    # graph; it must still appear once. A DEC naming the same unknown FR twice
    # makes the indexer itself report a duplicate, which the gate collapses.
    specs, _ = _BROKEN["mixed-with-duplicate"]
    specs = {
        **specs,
        "FR-0102-c.md": _fr("FR-0102").replace(
            "depends_on: []", "depends_on: [FR-0999]"
        ),
    }
    repo = _build_repo(tmp_path / "r", specs)
    expected = _indexer_errors(repo)
    dup = "DEC-0003-c.md: constrained_by references unknown FR 'FR-0998'"
    assert expected.count(dup) == 2, expected  # the indexer repeats it

    proc = _gate(repo)
    assert proc.returncode == 1
    lines = _lint_lines(proc.stderr)
    assert lines.count(f"  {dup}") == 1, lines
    depends = "  FR-0102-c.md: depends_on references unknown FR 'FR-0999'"
    assert lines.count(depends) == 1, lines
    assert len(lines) == len(set(lines)), lines
    assert lines == [_FAIL_HEADER] + [f"  {e}" for e in dict.fromkeys(expected)]


# covers hub-tooling FR-0021:AC-1
@pytest.mark.parametrize("stage", ["dev", "review", "full", None])
@pytest.mark.parametrize(
    "tree", ["dec-accepted", "tr-parse-error", "dec-supersedes-unresolved"]
)
def test_failure_emits_one_valid_spec_validation_record(tmp_path, tree, stage):
    repo = _build_repo(tmp_path / "r", _BROKEN[tree][0])
    args = ("--stage", stage) if stage else ()
    proc = _gate(repo, *args)
    assert proc.returncode == 1, proc.stderr
    recs = _records(repo)
    assert len(recs) == 1, recs
    rec = recs[0]
    assert metrics_log.validation_errors(rec) == [], rec
    assert rec["kind"] == "gate.run" and rec["source"] == "gate"
    assert rec["stage"] == (stage or "full")
    assert rec["outcome"] == "fail"
    assert rec["failure_classes"] == ["spec-validation"]
    assert rec["warning_classes"] == []
    assert set(rec["counts"]) == {"frs", "covers", "implements"}


# covers hub-tooling FR-0021:AC-1
@pytest.mark.parametrize("stage", ["dev", "review", "full"])
def test_status_only_failure_writes_no_record(tmp_path, stage):
    repo = _build_repo(tmp_path / "r", _BROKEN["dec-accepted"][0])
    proc = _gate(repo, "--stage", stage, "--status-only")
    assert proc.returncode == 1
    assert not (repo / "specs" / "_metrics").exists()


# ---------------------------------------------------------------------------
# AC-2: one validator, delegated
# ---------------------------------------------------------------------------


def _fresh_index_specs(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / "index-specs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_index_specs = _fresh_index_specs("index_specs_fr0021_under_test")


def _point_at(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(_index_specs, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(_index_specs, "DECISIONS_DIR", repo / "specs" / "decisions")
    monkeypatch.setattr(_index_specs, "INDEX_PATH", repo / "specs" / "INDEX.md")


_AC2_TREES = {
    **{k: v[0] for k, v in _BROKEN.items()},
    "happy": _happy_tree(),
    "fr-only": _fr_only_tree(),
}


# covers hub-tooling FR-0021:AC-2
@pytest.mark.parametrize("tree", sorted(_AC2_TREES))
def test_exported_validator_returns_exactly_what_validate_reports(
    tmp_path, monkeypatch, tree
):
    repo = _build_repo(tmp_path / "r", _AC2_TREES[tree])
    from_cli = _indexer_errors(repo)
    _point_at(monkeypatch, repo)
    got = _index_specs.validate_spec_graph()
    assert isinstance(got, list) and all(isinstance(e, str) for e in got)
    assert got == from_cli  # same order, duplicates included, nothing else
    if tree in ("happy", "fr-only"):
        assert got == []
        assert _run(repo, "index-specs.py", "--validate").returncode == 0
    assert not (repo / "specs" / "INDEX.md").exists()  # the validator writes nothing


# covers hub-tooling FR-0021:AC-2
def test_exported_validator_sees_what_the_fr_only_path_misses(tmp_path, monkeypatch):
    repo = _build_repo(tmp_path / "r", _BROKEN["dec-supersedes-unresolved"][0])
    _point_at(monkeypatch, repo)
    frs, parse_errors = _index_specs.collect_frs()
    assert parse_errors + _index_specs.validate_graph(frs) == []  # the old gate's view
    assert _index_specs.validate_spec_graph() != []


# covers hub-tooling FR-0021:AC-2
def test_exported_validator_signature_and_name():
    fn = _index_specs.validate_spec_graph
    assert list(inspect.signature(fn).parameters) == []
    forbidden = (
        "collect_trs",
        "collect_decs",
        "collect_graph",
        "DEC(",
        "TR(",
        "is_live_dec",
    )
    for token in forbidden:
        assert token not in fn.__name__
    for token in ("spec_query", "in_default_view", "retired"):
        assert token not in fn.__name__.lower()


# covers hub-tooling FR-0021:AC-2
def test_gate_delegates_to_the_indexer_function_and_has_no_dec_tr_vocabulary():
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    for token in (
        "collect_trs",
        "collect_decs",
        "collect_graph",
        "DEC(",
        "TR(",
        "is_live_dec",
    ):
        assert token not in source, token
    for token in ("spec_query", "in_default_view", "retired"):
        assert token not in source.lower(), token
    assert "render_index(parsed_frs, repo_files)" in source

    # No identifier in the gate's code (comments aside) names a DEC, TR,
    # decisions directory, revision or supersession concept.
    vocab = re.compile(
        r"(?i)(^|_)(decs?|trs?|decisions?)(_|$)|supersed|revision|lifecycle"
    )
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    assert not sorted(n for n in names if vocab.search(n))

    spec = importlib.util.spec_from_file_location(
        "deploy_gate_fr0021_under_test", _SCRIPTS_DIR / "deploy-gate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    assert mod.validate_spec_graph is mod._index_specs.validate_spec_graph
    # The gate's step 1 calls the delegated validator, not the FR-only pair.
    step1 = inspect.getsource(mod._run_checks).split("INDEX_PATH.write_text", 1)[0]
    assert "validate_spec_graph()" in step1
    assert "validate_graph(" not in step1.replace("validate_spec_graph(", "")


# ---------------------------------------------------------------------------
# AC-3: valid graphs behave exactly as before
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0021:AC-3
@pytest.mark.parametrize(
    "args",
    [a for a in _INVOCATIONS if "--status-only" not in a],
    ids=[i for a, i in zip(_INVOCATIONS, _INVOCATION_IDS) if "--status-only" not in a],
)
@pytest.mark.parametrize("tree", ["happy", "fr-only"])
def test_valid_tree_index_is_byte_identical_to_the_indexers(tmp_path, tree, args):
    specs = _happy_tree() if tree == "happy" else _fr_only_tree()
    repo = _build_repo(tmp_path / "r", specs)
    index = repo / "specs" / "INDEX.md"
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    from_indexer = index.read_bytes()
    index.unlink()

    proc = _gate(repo, *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert index.read_bytes() == from_indexer
    if tree == "happy":
        assert (
            b"## Decisions" in from_indexer
            and b"## Technical requirements" in from_indexer
        )


# covers hub-tooling FR-0021:AC-3
@pytest.mark.parametrize("stage", ["dev", "review", "full"])
def test_valid_tree_status_only_still_writes_nothing(tmp_path, stage):
    repo = _build_repo(tmp_path / "r", _happy_tree())
    before = _snapshot(repo)
    proc = _gate(repo, "--stage", stage, "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _snapshot(repo) == before
    assert not (repo / "specs" / "_metrics").exists()


def _record_shape(rec: dict) -> dict:
    return {
        "keys": sorted(rec),
        "counts": rec["counts"],
        "stage": rec["stage"],
        "outcome": rec["outcome"],
        "failure_classes": rec["failure_classes"],
        "warning_classes": rec["warning_classes"],
        "object_ids": rec["object_ids"],
        "invoked_by": rec["invoked_by"],
    }


# covers hub-tooling FR-0021:AC-3
@pytest.mark.parametrize("stage", ["dev", "review", "full"])
def test_pass_record_matches_the_pre_fr0021_gate(tmp_path, stage):
    old_src = _baseline_gate()
    specs, tests, src = _annotated_tree()
    new = _build_repo(tmp_path / "new", specs, tests=tests, src=src)
    old = _build_repo(
        tmp_path / "old", specs, tests=tests, src=src, gate_source=old_src
    )
    assert _gate(new, "--stage", stage).returncode == 0
    assert _gate(old, "--stage", stage).returncode == 0
    (rec_new,), (rec_old,) = _records(new), _records(old)
    assert _record_shape(rec_new) == _record_shape(rec_old)
    assert rec_new["counts"] == {"frs": 2, "covers": 2, "implements": 1}
    assert (new / "specs" / "INDEX.md").read_bytes() == (
        old / "specs" / "INDEX.md"
    ).read_bytes()


# covers hub-tooling FR-0021:AC-3
def test_fr_graph_failure_record_keys_match_the_pre_fr0021_gate(tmp_path):
    # Key set, stage, outcome and class are unchanged on the failure branch too.
    # counts.frs is deliberately not compared: see REVIEW.md FINDINGS.
    old_src = _baseline_gate()
    specs = _BROKEN["fr-depends-unknown"][0]
    new = _build_repo(tmp_path / "new", specs)
    old = _build_repo(tmp_path / "old", specs, gate_source=old_src)
    assert _gate(new).returncode == 1 and _gate(old).returncode == 1
    (rec_new,), (rec_old,) = _records(new), _records(old)
    for key in ("stage", "outcome", "failure_classes", "warning_classes", "object_ids"):
        assert rec_new[key] == rec_old[key], key
    assert sorted(rec_new) == sorted(rec_old)
    assert sorted(rec_new["counts"]) == sorted(rec_old["counts"])


# ---------------------------------------------------------------------------
# AC-4: the PASSED line states the gate's scope
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0021:AC-4
@pytest.mark.parametrize("args", _INVOCATIONS, ids=_INVOCATION_IDS)
def test_passed_line_carries_the_exact_scope_clause_and_is_deterministic(
    tmp_path, args
):
    specs, tests, src = _annotated_tree()
    repo = _build_repo(tmp_path / "r", specs, tests=tests, src=src)
    first = _gate(repo, *args)
    second = _gate(repo, *args)
    assert first.returncode == 0 and second.returncode == 0, first.stderr
    stage = _stage_of(args)
    _assert_passed_line(first.stdout, stage)
    assert first.stdout.rstrip("\n").endswith(_CLAUSE[stage])
    assert first.stdout == second.stdout
    assert first.stdout.startswith(
        f"Deploy gate PASSED (stage={stage}): 2 FRs, 2 @covers annotations, 1 @implements annotations;"
    )
    if stage == "dev":
        assert "AC coverage" not in first.stdout and "gate evidence" not in first.stdout


# covers hub-tooling FR-0021:AC-4
@pytest.mark.parametrize("args", _INVOCATIONS, ids=_INVOCATION_IDS)
def test_passed_line_is_the_old_line_plus_the_clause(tmp_path, args):
    old_src = _baseline_gate()
    specs, tests, src = _annotated_tree()
    new = _build_repo(tmp_path / "new", specs, tests=tests, src=src)
    old = _build_repo(
        tmp_path / "old", specs, tests=tests, src=src, gate_source=old_src
    )
    p_new, p_old = _gate(new, *args), _gate(old, *args)
    assert p_old.returncode == p_new.returncode == 0
    assert p_new.stdout == p_old.stdout.rstrip("\n") + _CLAUSE[_stage_of(args)] + "\n"
    assert _lint_lines(p_new.stderr) == _lint_lines(p_old.stderr)


def _coverage_gap_tree() -> dict[str, str]:
    return {"FR-0100-a.md": _fr("FR-0100", status="in-review")}


def _warning_tree() -> dict[str, str]:
    return {"FR-0100-a.md": _fr("FR-0100", status="in-progress")}


# covers hub-tooling FR-0021:AC-4
@pytest.mark.parametrize("stage", ["review", "full"])
def test_failed_format_is_unchanged_and_carries_no_clause(tmp_path, stage):
    repo = _build_repo(tmp_path / "r", _coverage_gap_tree())
    proc = _gate(repo, "--stage", stage)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert _lint_lines(proc.stderr) == [
        "Deploy gate WARNINGS:",
        "  - FR-0100 (in-review): no @implements tag found in src/",
        "Deploy gate FAILED:",
        "  - FR-0100 (in-review): no @covers test for AC-1, AC-2",
    ]
    assert "scope:" not in proc.stderr


# covers hub-tooling FR-0021:AC-4
def test_warnings_format_is_unchanged_and_pass_still_states_scope(tmp_path):
    repo = _build_repo(tmp_path / "r", _warning_tree())
    proc = _gate(repo, "--stage", "dev")
    assert proc.returncode == 0, proc.stderr
    assert _lint_lines(proc.stderr) == [
        "Deploy gate WARNINGS:",
        "  - FR-0100 (in-progress): no @implements tag found in src/",
    ]
    _assert_passed_line(proc.stdout, "dev")


# covers hub-tooling FR-0021:AC-4
@pytest.mark.parametrize("tree", ["coverage-gap", "warning"])
def test_failed_and_warnings_stderr_byte_identical_to_the_pre_fr0021_gate(
    tmp_path, tree
):
    old_src = _baseline_gate()
    specs = _coverage_gap_tree() if tree == "coverage-gap" else _warning_tree()
    new = _build_repo(tmp_path / "new", specs)
    old = _build_repo(tmp_path / "old", specs, gate_source=old_src)
    p_new, p_old = _gate(new), _gate(old)
    assert p_new.returncode == p_old.returncode
    assert _lint_lines(p_new.stderr) == _lint_lines(p_old.stderr)


# ---------------------------------------------------------------------------
# Bite checks: the assertions above fail against the pre-FR-0021 gate
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0021:AC-1
@pytest.mark.parametrize("args", _INVOCATIONS, ids=_INVOCATION_IDS)
def test_bite_the_old_gate_passes_the_dec_accepted_shape(tmp_path, args):
    old_src = _baseline_gate()
    repo = _build_repo(
        tmp_path / "old", _BROKEN["dec-accepted"][0], gate_source=old_src
    )
    expected = _indexer_errors(repo)
    with pytest.raises(AssertionError):
        _assert_refuses_and_writes_nothing(repo, args, expected)
    # Concretely: it passes, and without --status-only writes a partial INDEX.
    repo2 = _build_repo(
        tmp_path / "old2", _BROKEN["dec-accepted"][0], gate_source=old_src
    )
    proc = _gate(repo2, *args)
    assert proc.returncode == 0 and "Deploy gate PASSED" in proc.stdout
    index = repo2 / "specs" / "INDEX.md"
    if "--status-only" in args:
        assert not index.exists()
    else:
        assert "## Decisions" not in index.read_text(encoding="utf-8")


# covers hub-tooling FR-0021:AC-4
@pytest.mark.parametrize("stage", ["dev", "review", "full"])
def test_bite_the_old_gate_has_no_scope_clause(tmp_path, stage):
    old_src = _baseline_gate()
    specs, tests, src = _annotated_tree()
    repo = _build_repo(
        tmp_path / "old", specs, tests=tests, src=src, gate_source=old_src
    )
    proc = _gate(repo, "--stage", stage)
    assert proc.returncode == 0
    with pytest.raises(AssertionError):
        _assert_passed_line(proc.stdout, stage)


# ---------------------------------------------------------------------------
# AC-5: the role files describe the gate correctly
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0021:AC-5
def test_orchestrator_after_architect_step_runs_the_indexer_validation():
    text = (_ROLES_DIR / "orchestrator.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert (
        "   - After Architect phase: `python scripts/index-specs.py --validate`"
        in lines
    )
    assert "--stage spec" not in text
    # Every gate invocation the role file names uses a stage argparse accepts.
    stages = set(re.findall(r"deploy-gate\.py --stage (\S+?)`", text))
    assert stages and stages <= {"dev", "review", "full"}, stages
    # The two neighbouring lines of the step are intact.
    i = lines.index(
        "   - After Architect phase: `python scripts/index-specs.py --validate`"
    )
    assert lines[i - 1] == "2. **Run `deploy-gate.py`** at the appropriate stage:"
    assert (
        lines[i + 1]
        == "   - After Developer phase: `python scripts/deploy-gate.py --stage dev`"
    )


# covers hub-tooling FR-0021:AC-5
def test_the_old_orchestrator_invocation_really_was_invalid(tmp_path):
    repo = _build_repo(tmp_path / "r", _fr_only_tree())
    proc = _gate(repo, "--stage", "spec")
    assert proc.returncode == 2
    assert "invalid choice" in proc.stderr


# covers hub-tooling FR-0021:AC-5
def test_reviewer_rejection_step_names_the_dispatcher_verdict_heading():
    text = (_ROLES_DIR / "reviewer.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    expected = (
        "1. Use `Request changes` on the PR (not just a comment — the dispatcher reads the "
        "verdict from the Reviewer's final message heading; see the reviewer command)"
    )
    assert expected in lines
    assert "review state" not in text
    i = lines.index(expected)
    assert lines[i - 2] == "On rejection:"
    assert lines[i + 1].startswith("2. List each issue with:")
    # The claim is true of the reviewer command it points at.
    command = (_COMMANDS_DIR / "reviewer.md").read_text(encoding="utf-8")
    assert "that heading is what the dispatcher reads as the verdict" in command
    # And the deploy gate indeed reads no review state.
    gate = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    assert "gh" not in re.findall(r"\b\w+\b", gate)
    assert "reviewDecision" not in gate and "REVIEW.md" not in gate


# covers hub-tooling FR-0021:AC-5
@pytest.mark.parametrize("role", ["orchestrator.md", "reviewer.md"])
def test_the_fr0021_commit_changed_one_line_of_each_role_file(role):
    rel = f"template/.agent-team/roles/{role}"
    before, after = _git_show(_IMPL_PARENT_REF, rel), _git_show(_IMPL_REF, rel)
    if before is None or after is None:
        pytest.skip(f"hub history for {_IMPL_REF} is not reachable")
    old_lines = before.decode("utf-8").splitlines()
    new_lines = after.decode("utf-8").splitlines()
    assert len(old_lines) == len(new_lines)
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(changed) == 1, changed
