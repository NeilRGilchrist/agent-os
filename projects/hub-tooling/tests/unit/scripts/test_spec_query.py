"""Reviewer tests for FR-0005 — supersession-aware indexer.

Covers the pure query module `scripts/spec_query.py` (visibility classes, the
default-view selector and its opt-ins, the revision window, the reachable
subgraph `slice`, the provisional report), the read-only CLI query modes the
indexer gained (`--list`, `--slice`, `--provisional`, each with `--json`), the
default-view `INDEX.md` with its `## Provisional decisions` and
`## Retired objects` sections, `deploy-gate.py` byte-identity, backward
compatibility against the pinned pre-FR-0005 baseline, the AC-12 fixture tree
and the documentation ACs.

Same harness as `test_index_specs_dec_tr.py`: `spec_query` is imported by
name (pytest.ini puts `scripts/` on `sys.path`) and the hyphenated indexer is
loaded by path; CLI surfaces run through `subprocess` against a copy of the
fixture tree under `tests/fixtures/spec_query/specs/` so "writes nothing" is
provable with a before/after snapshot of every file in the temp repo.

Coverage annotations are written `# covers hub-tooling FR-0005:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0005 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (see test_index_specs_versioning.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

# Convention: backward-compat baselines pin a commit, never a branch name.
# `main:` only means "the code before this FR" while the FR lives on a feature
# branch; once merged, `main:` IS the code under test and every "identical to
# baseline" assertion turns into a tautology (and the "differs only by the
# default view" check fails with zero differences). Pinning a commit keeps the
# comparison meaningful forever. Outside the hub checkout (bootstrapped
# projects, shallow clones) the commit is unreachable and the tests skip.

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# once bootstrapped).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_SPECS_DIR = _TEMPLATE_DIR / "specs"
_FIXTURE_SPECS = _TEMPLATE_DIR / "tests" / "fixtures" / "spec_query" / "specs"
_COPY_SCRIPTS = ("index-specs.py", "deploy-gate.py", "spec_footprint.py", "spec_query.py")
_CONSUMER_SCRIPTS = ("deploy-gate.py", "dispatch.py", "render-docs.py", "agent-status.py")

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import spec_query  # noqa: E402  (sibling module, importable by name)


def _load_index_specs():
    spec = importlib.util.spec_from_file_location(
        "index_specs_spec_query_under_test", _SCRIPTS_DIR / "index-specs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


index_specs = _load_index_specs()

# ---------------------------------------------------------------------------
# The AC-12 fixture tree, by role (IDs are the contract the assertions use)
# ---------------------------------------------------------------------------
#
# FR-0100 live successor (v3, revisions [DEC-0004, DEC-0005], lbr 3,
#         supersedes FR-0101, depends_on FR-0102, extends FR-0103)
# FR-0101 superseded predecessor (superseded_by FR-0100, status merged)
# FR-0102 live dependency
# FR-0103 draft (extends the superseded FR-0101)
# TR-0000 superseded (v3, revisions [DEC-0006, DEC-0007], lbr 3 -> current
#         window is exactly the migration DEC-0007; superseded_by TR-0001)
# TR-0001 live successor at version 1 (supersedes TR-0000)
# TR-0002 live, revisions [DEC-0001, DEC-0002, DEC-0003], DEC-0002 breaking,
#         lbr 3 (DEC-0001 pre-breaking)
# TR-0003 draft
# DEC-0001 ratified, pre-breaking (TR-0002)          DEC-0007 migration-window DEC
# DEC-0002 ratified, breaking, cites ADR-0001+0003   DEC-0008 proposed, revises null,
# DEC-0003 ratified, provisional 2026-12-31,                  provisional 2026-09-07
#          invokes_exception ADR-0002                DEC-0009 rejected (revises TR-0002)
# DEC-0004 ratified, pre-breaking (FR-0100),         DEC-0010 superseded by DEC-0011
#          provisional 2026-01-01                    DEC-0011 ratified, supersedes DEC-0010
# DEC-0005 ratified, breaking, event trigger,
#          constrained_by [FR-0102, FR-0101]
# DEC-0006 ratified, pre-breaking (TR-0000)
# ADR-0001 accepted, ADR-0002 proposed, ADR-0003 superseded

AS_OF = date(2026, 9, 7)

ALL_IDS = [
    "ADR-0001", "ADR-0002", "ADR-0003",
    "DEC-0001", "DEC-0002", "DEC-0003", "DEC-0004", "DEC-0005", "DEC-0006",
    "DEC-0007", "DEC-0008", "DEC-0009", "DEC-0010", "DEC-0011",
    "FR-0100", "FR-0101", "FR-0102", "FR-0103",
    "TR-0000", "TR-0001", "TR-0002", "TR-0003",
]
DEFAULT_IDS = [
    "ADR-0001", "ADR-0002",
    "DEC-0002", "DEC-0003", "DEC-0005", "DEC-0007", "DEC-0008", "DEC-0011",
    "FR-0100", "FR-0102", "FR-0103",
    "TR-0001", "TR-0002", "TR-0003",
]
SUPERSEDED_IDS = ["ADR-0003", "DEC-0010", "FR-0101", "TR-0000"]
REJECTED_IDS = ["DEC-0009"]
HISTORY_IDS = ["DEC-0001", "DEC-0004", "DEC-0006"]

FR_HEADER = "| ID | Title | Status | Ver | Lifecycle | Owner | Tags | Owns | Reads | Depends on | Derived from | Updated | Gates |"
PROVISIONAL_HEADER = "| ID | Title | Trigger | Revises | Updated |"
PROVISIONAL_SEPARATOR = "|----|-------|---------|---------|---------|"
RETIRED_HEADER = "| ID | Type | Title | Why | Updated |"
RETIRED_SEPARATOR = "|----|------|-------|-----|---------|"

EXPECTED_RETIRED_ROWS = [
    "| [DEC-0001](decisions/DEC-0001-b-first.md) | DEC | B - first refinement (pre-breaking) | pre-breaking (TR-0002 v2 < v3) | 2026-01-03 |",
    "| [DEC-0004](decisions/DEC-0004-a-first.md) | DEC | A - first refinement (pre-breaking, provisional) | pre-breaking (FR-0100 v2 < v3) | 2026-01-03 |",
    "| [DEC-0006](decisions/DEC-0006-a-old-first.md) | DEC | Old A - first refinement (pre-breaking) | pre-breaking (TR-0000 v2 < v3) | 2026-01-03 |",
    "| [DEC-0009](decisions/DEC-0009-b-rejected.md) | DEC | B - rejected proposal | rejected | 2026-01-03 |",
    "| [DEC-0010](decisions/DEC-0010-b-superseded.md) | DEC | B - superseded choice | superseded by DEC-0011 | 2026-01-03 |",
    "| [FR-0101](FR-0101-need-a-old.md) | FR | Need A (superseded predecessor) | superseded by FR-0100 | 2026-01-01 |",
    "| [TR-0000](TR-0000-approach-old.md) | TR | Approach A (superseded, migration window) | superseded by TR-0001 | 2026-01-02 |",
]
EXPECTED_PROVISIONAL_ROWS = [
    "| [DEC-0003](decisions/DEC-0003-b-third.md) | B - third refinement (provisional, future date) | 2026-12-31 | TR-0002 | 2026-01-03 |",
    "| [DEC-0005](decisions/DEC-0005-a-breaking.md) | A - breaking change (event trigger) | after Project A pilot tenant 2 onboards | FR-0100 | 2026-01-03 |",
    "| [DEC-0007](decisions/DEC-0007-a-old-migration.md) | Old A - supersede for migration window | 2026-06-30 | TR-0000 | 2026-01-03 |",
    "| [DEC-0008](decisions/DEC-0008-creating-proposed.md) | Creating decision (proposed, boundary date) | 2026-09-07 | — | 2026-01-03 |",
]


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _fr_markdown(fr_id: str, *, status: str = "ready", extra_frontmatter: str = "") -> str:
    extra = f"{extra_frontmatter.rstrip()}\n" if extra_frontmatter.strip() else ""
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
owns: []
reads: []
derived_from: null
pattern: null
ac_state: {{}}
{extra}created: 2026-01-01
updated: 2026-01-01
---

# {fr_id}: Synthetic

## Why

Synthetic FR for FR-0005 fixtures.

## Acceptance criteria

- **AC-1:** does the first thing
"""


def _tr_markdown(tr_id: str, *, extra_frontmatter: str = "") -> str:
    extra = f"{extra_frontmatter.rstrip()}\n" if extra_frontmatter.strip() else ""
    return f"""---
id: {tr_id}
title: Synthetic {tr_id}
operationalises: [FR-0100]
{extra}created: 2026-01-01
updated: 2026-01-02
---

# {tr_id}: Synthetic
"""


def _dec_markdown(dec_id: str, *, status: str = "ratified", extra_frontmatter: str = "") -> str:
    extra = f"{extra_frontmatter.rstrip()}\n" if extra_frontmatter.strip() else ""
    return f"""---
id: {dec_id}
title: Synthetic {dec_id}
tier: agent
status: {status}
{extra}rationale: Synthetic decision {dec_id}.
created: 2026-01-01
updated: 2026-01-03
---

# {dec_id}: Synthetic
"""


def _adr_markdown(adr_id: str, *, status: str = "accepted") -> str:
    body = "\n\n".join(
        f"{h}\n\nx"
        for h in (
            "## Context",
            "## Decision",
            "## When you may deviate",
            "## What you must record when you deviate",
            "## Consequences",
            "## Alternatives considered",
            "## Changelog",
        )
    )
    return f"""---
id: {adr_id}
title: Synthetic {adr_id}
status: {status}
owner: architect
supersedes: null
superseded_by: null
created: 2026-01-01
updated: 2026-01-02
---

# {adr_id}: Synthetic

{body}
"""


def _copy_scripts(repo: Path) -> None:
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    for name in _COPY_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / name, repo / "scripts" / name)


def _build_fixture_repo(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    """Copy the team scripts and the AC-12 fixture tree into a temp repo;
    `extra` writes/overwrites files under `specs/` (relative names)."""
    repo = tmp_path / "repo"
    _copy_scripts(repo)
    shutil.copytree(_FIXTURE_SPECS, repo / "specs")
    for rel, content in (extra or {}).items():
        target = repo / "specs" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return repo


def _build_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Temp repo from an inline dict of `specs/`-relative files."""
    _copy_scripts(tmp_path)
    for rel, content in files.items():
        target = tmp_path / "specs" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _lint_stderr(proc: subprocess.CompletedProcess) -> list[str]:
    """stderr minus the environment-dependent lines every plain run emits in a
    temp dir (`git ls-files` unavailable; no CODEOWNERS config)."""
    return [
        l
        for l in proc.stderr.splitlines()
        if not l.startswith("WARN: spec_footprint:") and not l.startswith("INFO:")
    ]


def _snapshot(repo: Path) -> dict[str, bytes]:
    return {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _index_text(repo: Path) -> str:
    return (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")


def _table_rows(lines: list[str], heading: str) -> list[str]:
    """The `| ... |` body rows of the table under `## <heading>`."""
    start = lines.index(f"## {heading}")
    rows: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("| [") :
            rows.append(line)
    return rows


def _row_ids(rows: list[str]) -> list[str]:
    return [re.match(r"\| \[([A-Z]+-\d{4})\]", r).group(1) for r in rows]


def _point_module_at(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(index_specs, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(index_specs, "DECISIONS_DIR", repo / "specs" / "decisions")


@pytest.fixture
def graph(tmp_path, monkeypatch):
    """The parsed AC-12 fixture tree as the indexer's `SpecGraph`."""
    repo = _build_fixture_repo(tmp_path)
    _point_module_at(monkeypatch, repo)
    g = index_specs.collect_graph()
    assert g.errors == [], g.errors
    return g


def _by_id(graph):
    return {o.id: o for o in [*graph.frs, *graph.trs, *graph.decs, *graph.adrs]}


def _objs_by_id(graph):
    return {o.id: o for o in [*graph.frs, *graph.trs]}


# Hub `main` immediately before FR-0005 merged (FR-0004's DEC / TR indexer, no
# spec_query / default view). AC-10, AC-11 and AC-13 all say "unchanged versus
# before this FR", so *this* is the code to compare with.
_BASELINE_REF = "d5eec69"
# The FR-0005 merge commit itself. AC-10 / AC-13's "the implementing PR's diff
# is empty for <consumer>" is a claim about *FR-0005's* diff, not a permanent
# freeze on those scripts (FR-0002 legitimately instruments deploy-gate.py and
# dispatch.py), so the consumer checks compare these two historical refs and
# leave the live-invariant half ("still no spec_query import") to its own test.
_FR0005_MERGE_REF = "8160ba2"


def _git_show_baseline(rel: str, ref: str = _BASELINE_REF) -> bytes | None:
    """`<hub>/<ref>:<rel>` as bytes, or None when the pinned commit is not
    reachable (bootstrapped projects and shallow clones have no hub history)."""
    hub = _TEMPLATE_DIR.parent
    probe = subprocess.run(
        ["git", "-C", str(hub), "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode != 0:
        return None
    proc = subprocess.run(["git", "-C", str(hub), "show", f"{ref}:{rel}"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _baseline_indexer(tmp_path: Path) -> Path | None:
    data = _git_show_baseline("template/scripts/index-specs.py")
    if data is None or b"def collect_frs" not in data:
        return None
    target = tmp_path / "baseline" / "index-specs.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


# ---------------------------------------------------------------------------
# AC-1: visibility classes
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-1
@pytest.mark.parametrize("prefix", ["FR", "TR"])
@pytest.mark.parametrize(
    "lifecycle,expected",
    [("live", "live"), ("draft", "draft"), ("superseded", "superseded"), (None, "live")],
)
def test_visibility_table_for_fr_and_tr_lifecycles(prefix, lifecycle, expected):
    obj = SimpleNamespace(id=f"{prefix}-0001")
    if lifecycle is not None:
        obj.lifecycle = lifecycle
    assert spec_query.visibility(obj) == expected
    assert spec_query.visibility(obj) in spec_query.VISIBILITY_CLASSES


# covers hub-tooling FR-0005:AC-1
@pytest.mark.parametrize(
    "status,expected",
    [("proposed", "live"), ("ratified", "live"), ("superseded", "superseded"), ("rejected", "rejected")],
)
def test_visibility_table_for_dec_statuses(status, expected):
    assert spec_query.visibility(SimpleNamespace(id="DEC-0001", status=status)) == expected


# covers hub-tooling FR-0005:AC-1
@pytest.mark.parametrize(
    "status,expected",
    [
        ("proposed", "live"),
        ("accepted", "live"),
        (None, "live"),
        ("bogus", "live"),
        ("", "live"),
        ("superseded", "superseded"),
        ("deprecated", "superseded"),
        ("rejected", "rejected"),
    ],
)
def test_visibility_table_for_adr_statuses_including_absent_and_unknown(status, expected):
    assert spec_query.visibility(SimpleNamespace(id="ADR-0001", status=status)) == expected


# covers hub-tooling FR-0005:AC-1
def test_visibility_never_hides_a_malformed_object():
    """Out-of-enum values (which the indexer would already have rejected for
    FR/TR/DEC) fall to the default view, never to a hidden class."""
    for obj in (
        SimpleNamespace(id="FR-0001", lifecycle="retired"),
        SimpleNamespace(id="TR-0001", lifecycle=""),
        SimpleNamespace(id="DEC-0001", status="accepted"),
        SimpleNamespace(id="ADR-0001", status="withdrawn"),
        SimpleNamespace(id="ADR-0001"),  # no status attribute at all
    ):
        cls = spec_query.visibility(obj)
        assert cls in spec_query.VISIBILITY_CLASSES
        assert cls in spec_query.DEFAULT_VIEW, obj


# covers hub-tooling FR-0005:AC-1
def test_visibility_agrees_with_is_live_and_is_live_dec_on_every_parsed_fixture(graph):
    seen_lifecycles = {o.lifecycle for o in [*graph.frs, *graph.trs]}
    seen_statuses = {d.status for d in graph.decs}
    assert seen_lifecycles == {"live", "draft", "superseded"}
    assert seen_statuses == {"proposed", "ratified", "rejected", "superseded"}
    for obj in [*graph.frs, *graph.trs]:
        assert (spec_query.visibility(obj) == "live") is index_specs.is_live(obj), obj.id
    for dec in graph.decs:
        assert (spec_query.visibility(dec) == "live") is index_specs.is_live_dec(dec), dec.id
    assert {spec_query.visibility(a) for a in graph.adrs} == {"live", "superseded"}


# covers hub-tooling FR-0005:AC-1
def test_module_is_pure_stdlib_only_and_does_not_import_the_indexer():
    source = (_SCRIPTS_DIR / "spec_query.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", ""))
    assert imported <= {"__future__", "re", "dataclasses", "datetime", "typing"}, imported
    for forbidden in ("os", "sys", "subprocess", "pathlib", "yaml", "json", "importlib", "index_specs"):
        assert forbidden not in imported
    for io_call in ("open", "print", "run", "Popen", "read_text", "write_text", "import_module"):
        assert io_call not in called, io_call
    assert "spec_from_file_location" not in source
    # Importing it in a clean interpreter pulls in neither yaml nor the indexer.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import spec_query; "
            "print(sorted(m for m in sys.modules if m in ('yaml', 'subprocess', 'index_specs') or 'index' in m.lower()))",
            str(_SCRIPTS_DIR),
        ],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "[]", probe.stdout


# ---------------------------------------------------------------------------
# AC-2: select() and the opt-ins
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-2
def test_select_default_view_is_live_plus_draft_minus_pre_breaking_in_id_order(graph):
    objs = [*graph.adrs, *graph.decs, *graph.trs, *graph.frs]  # deliberately unsorted
    chosen = spec_query.select(objs)
    assert [o.id for o in chosen] == DEFAULT_IDS
    assert [o.id for o in spec_query.select(objs, frozenset())] == DEFAULT_IDS
    assert [o.id for o in spec_query.select(objs, None)] == DEFAULT_IDS
    # Nothing superseded / rejected / pre-breaking leaks in.
    assert not set(SUPERSEDED_IDS + REJECTED_IDS + HISTORY_IDS) & set(DEFAULT_IDS)


# covers hub-tooling FR-0005:AC-2
def test_select_opt_ins_add_exactly_their_class_and_compose(graph):
    objs = [*graph.frs, *graph.trs, *graph.decs, *graph.adrs]
    ids = lambda include: [o.id for o in spec_query.select(objs, include)]  # noqa: E731
    assert ids({"superseded"}) == sorted(DEFAULT_IDS + SUPERSEDED_IDS)
    assert ids({"rejected"}) == sorted(DEFAULT_IDS + REJECTED_IDS)
    assert ids({"history"}) == sorted(DEFAULT_IDS + HISTORY_IDS)
    assert ids({"superseded", "rejected"}) == sorted(DEFAULT_IDS + SUPERSEDED_IDS + REJECTED_IDS)
    assert ids({"superseded", "rejected", "history"}) == ALL_IDS
    assert ids({"all"}) == ALL_IDS
    assert ids({"all", "rejected"}) == ALL_IDS
    assert ids(["history", "history"]) == sorted(DEFAULT_IDS + HISTORY_IDS)  # any iterable


# covers hub-tooling FR-0005:AC-2
@pytest.mark.parametrize("bad", ["bogus", "draft", "live", "SUPERSEDED", "pre-breaking", ""])
def test_select_rejects_unknown_include_values_naming_them(graph, bad):
    with pytest.raises(ValueError) as exc:
        spec_query.select(graph.decs, {bad, "superseded"})
    assert repr(bad) in str(exc.value) or f"'{bad}'" in str(exc.value)
    with pytest.raises(ValueError):
        spec_query.normalise_include([bad])


# covers hub-tooling FR-0005:AC-2
# covers hub-tooling FR-0005:AC-3
def test_select_class_wins_over_window_for_current_window_rejected_or_superseded_decs():
    tr = SimpleNamespace(
        id="TR-0001", lifecycle="live", revisions=["DEC-0001", "DEC-0002", "DEC-0003"], last_breaking_revision=None
    )
    rejected = SimpleNamespace(id="DEC-0001", status="rejected", revises="TR-0001")
    superseded = SimpleNamespace(id="DEC-0002", status="superseded", revises="TR-0001")
    live = SimpleNamespace(id="DEC-0003", status="ratified", revises="TR-0001")
    objs = [tr, rejected, superseded, live]
    # All three are in the current window (null marker) ...
    assert spec_query.revision_window(tr) == (["DEC-0001", "DEC-0002", "DEC-0003"], [])
    # ... but only the live one is visible by default; `history` does not help.
    assert [o.id for o in spec_query.select(objs)] == ["DEC-0003", "TR-0001"]
    assert [o.id for o in spec_query.select(objs, {"history"})] == ["DEC-0003", "TR-0001"]
    assert [o.id for o in spec_query.select(objs, {"rejected"})] == ["DEC-0001", "DEC-0003", "TR-0001"]
    assert [o.id for o in spec_query.select(objs, {"superseded"})] == ["DEC-0002", "DEC-0003", "TR-0001"]


# covers hub-tooling FR-0005:AC-2
def test_select_places_decs_by_window_when_objs_by_id_is_passed_or_derived(graph):
    """Passing the FR/TR map explicitly and letting `select` derive it from
    the objects give the same answer; passing DECs alone (no targets) cannot
    place them and shows every live one (the conservative reading)."""
    decs = list(graph.decs)
    derived = [o.id for o in spec_query.select([*graph.frs, *graph.trs, *decs])]
    explicit = [o.id for o in spec_query.select(decs, objs_by_id=_objs_by_id(graph))]
    assert [i for i in derived if i.startswith("DEC-")] == explicit
    alone = [o.id for o in spec_query.select(decs)]
    assert set(alone) == set(explicit) | set(HISTORY_IDS)


# ---------------------------------------------------------------------------
# AC-3: revision window
# ---------------------------------------------------------------------------


def _tr(revisions, lbr):
    return SimpleNamespace(id="TR-0002", lifecycle="live", revisions=list(revisions), last_breaking_revision=lbr)


# covers hub-tooling FR-0005:AC-3
def test_revision_window_on_fixture_tr_breaking_dec_counted_current(graph):
    tr = _by_id(graph)["TR-0002"]
    assert tr.last_breaking_revision == 3
    current, history = spec_query.revision_window(tr, {d.id: d for d in graph.decs})
    assert current == ["DEC-0002", "DEC-0003"]
    assert history == ["DEC-0001"]


# covers hub-tooling FR-0005:AC-3
@pytest.mark.parametrize(
    "lbr,expected_current,expected_history",
    [
        (None, ["DEC-0001", "DEC-0002", "DEC-0003"], []),
        (1, ["DEC-0001", "DEC-0002", "DEC-0003"], []),  # version 1 predates every DEC
        (2, ["DEC-0001", "DEC-0002", "DEC-0003"], []),  # position 1 produced v2
        (3, ["DEC-0002", "DEC-0003"], ["DEC-0001"]),
        (4, ["DEC-0003"], ["DEC-0001", "DEC-0002"]),
        (5, [], ["DEC-0001", "DEC-0002", "DEC-0003"]),  # marker beyond version: FR-0003 warns, window obeys
    ],
)
def test_revision_window_arithmetic_uses_the_recorded_marker(lbr, expected_current, expected_history):
    current, history = spec_query.revision_window(_tr(["DEC-0001", "DEC-0002", "DEC-0003"], lbr))
    assert (current, history) == (expected_current, expected_history)
    assert spec_query.revision_window(_tr([], lbr)) == ([], [])


# covers hub-tooling FR-0005:AC-3
def test_revision_window_ignores_breaking_flags_when_they_disagree_with_the_marker():
    """The FR-0004 warn case: DEC-0001 says breaking but the recorded marker
    says version 4. The split follows the marker, not a recomputation."""
    tr = _tr(["DEC-0001", "DEC-0002", "DEC-0003"], 4)
    decs = {
        "DEC-0001": SimpleNamespace(id="DEC-0001", status="ratified", revises="TR-0002", breaking=True),
        "DEC-0002": SimpleNamespace(id="DEC-0002", status="ratified", revises="TR-0002", breaking=False),
        "DEC-0003": SimpleNamespace(id="DEC-0003", status="ratified", revises="TR-0002", breaking=False),
    }
    assert spec_query.revision_window(tr, decs) == (["DEC-0003"], ["DEC-0001", "DEC-0002"])
    assert spec_query.dec_window_class(decs["DEC-0001"], {"TR-0002": tr}) == ("history", None)
    assert spec_query.dec_window_class(decs["DEC-0003"], {"TR-0002": tr}) == ("current", None)


# covers hub-tooling FR-0005:AC-3
def test_dec_window_class_treats_unplaceable_decs_as_current_with_a_note():
    tr = _tr(["DEC-0001"], None)
    objs = {"TR-0002": tr}
    creating = SimpleNamespace(id="DEC-0010", status="ratified", revises=None)
    unlisted = SimpleNamespace(id="DEC-0011", status="ratified", revises="TR-0002")
    dangling = SimpleNamespace(id="DEC-0012", status="ratified", revises="TR-0099")
    for dec in (creating, unlisted, dangling):
        window, note = spec_query.dec_window_class(dec, objs)
        assert window == "current"
        assert note is not None and dec.id in note, (dec.id, note)
    assert "TR-0002" in spec_query.dec_window_class(unlisted, objs)[1]
    assert "TR-0099" in spec_query.dec_window_class(dangling, objs)[1]
    placed = SimpleNamespace(id="DEC-0001", status="ratified", revises="TR-0002")
    assert spec_query.dec_window_class(placed, objs) == ("current", None)


# covers hub-tooling FR-0005:AC-3
def test_pre_breaking_reason_wording_and_none_for_current(graph):
    objs = _objs_by_id(graph)
    by_id = _by_id(graph)
    assert spec_query.pre_breaking_reason(by_id["DEC-0001"], objs) == "pre-breaking (TR-0002 v2 < v3)"
    assert spec_query.pre_breaking_reason(by_id["DEC-0004"], objs) == "pre-breaking (FR-0100 v2 < v3)"
    assert spec_query.pre_breaking_reason(by_id["DEC-0006"], objs) == "pre-breaking (TR-0000 v2 < v3)"
    for current in ("DEC-0002", "DEC-0003", "DEC-0005", "DEC-0007", "DEC-0008", "DEC-0011"):
        assert spec_query.pre_breaking_reason(by_id[current], objs) is None, current


# ---------------------------------------------------------------------------
# AC-4: slice, current mode
# ---------------------------------------------------------------------------


def _ids(result):
    return [o.id for o in result.objects]


def _via(result):
    return {o.id: o.via for o in result.objects}


def _excluded(result):
    return {(e.id, e.visibility, e.via) for e in result.excluded}


# covers hub-tooling FR-0005:AC-4
def test_slice_current_rooted_at_live_successor_tr(graph):
    result = spec_query.slice(graph, "TR-0001")
    assert result.root == "TR-0001" and result.mode == "current"
    assert _ids(result) == ["FR-0100", "FR-0102", "TR-0001", "DEC-0005", "ADR-0001"]
    via = _via(result)
    assert via["TR-0001"] == "root" and via["FR-0100"] == "operationalises"
    assert via["DEC-0005"] == "revisions of FR-0100"
    assert via["FR-0102"] == "constrained_by of DEC-0005"
    assert via["ADR-0001"] == "authorised_by of DEC-0005"
    assert {o.visibility for o in result.objects} == {"live"}
    assert _excluded(result) == {
        ("FR-0101", "superseded", "constrained_by of DEC-0005"),
        ("DEC-0004", "live", "revisions of FR-0100 (pre-breaking)"),
    }
    assert result.notes == []
    # Every Excluded compares equal to its plain 3-tuple (the JSON contract).
    assert ("FR-0101", "superseded", "constrained_by of DEC-0005") in result.excluded
    # One hop only: FR-0100's own extends / depends_on are not followed from a TR root.
    assert "FR-0103" not in result and "TR-0002" not in result
    assert spec_query.slice(graph, "TR-0001") == result


# covers hub-tooling FR-0005:AC-4
def test_slice_current_rooted_at_three_revision_tr_follows_both_adr_edges_and_hides_history(graph):
    result = spec_query.slice(graph, "TR-0002")
    assert _ids(result) == [
        "FR-0100", "FR-0102", "TR-0002", "DEC-0002", "DEC-0003", "DEC-0005", "ADR-0001", "ADR-0002",
    ]
    via = _via(result)
    assert via["DEC-0002"] == "revisions of TR-0002" and via["DEC-0003"] == "revisions of TR-0002"
    assert via["ADR-0001"] == "authorised_by of DEC-0002"
    assert via["ADR-0002"] == "invokes_exception of DEC-0003"  # reached only via the ADR-nnnn prefix
    assert _excluded(result) == {
        ("FR-0101", "superseded", "constrained_by of DEC-0005"),
        ("DEC-0001", "live", "revisions of TR-0002 (pre-breaking)"),
        ("DEC-0004", "live", "revisions of FR-0100 (pre-breaking)"),
        ("DEC-0009", "rejected", "revises TR-0002 (unlisted)"),
        ("DEC-0010", "superseded", "revises TR-0002 (unlisted)"),
        ("ADR-0003", "superseded", "authorised_by of DEC-0002"),
    }
    for obj in result.objects:
        assert obj.visibility not in ("superseded", "rejected")
        if obj.type == "DEC":
            assert spec_query.dec_window_class(obj.obj, _objs_by_id(graph))[0] == "current"
    # Order: by type FR, TR, DEC, ADR then ID.
    kinds = [o.type for o in result.objects]
    assert kinds == sorted(kinds, key=spec_query.OBJECT_TYPES.index)
    assert spec_query.slice(graph, "TR-0002") == result
    assert result.notes == []


# covers hub-tooling FR-0005:AC-4
def test_slice_current_does_not_follow_supersession_or_non_object_edges():
    """Adversarial: a naive walker that follows every ID-shaped field would
    pull in the predecessor (supersedes), the second-hop FR, and the paths in
    implemented_by / tests. None of those may appear — not even in `excluded`."""
    graph = SimpleNamespace(
        frs=[
            SimpleNamespace(id="FR-0001", lifecycle="live", extends=[], depends_on=["FR-0002"], revisions=[], last_breaking_revision=None),
            SimpleNamespace(id="FR-0002", lifecycle="live", extends=[], depends_on=[], revisions=[], last_breaking_revision=None),
        ],
        trs=[
            SimpleNamespace(id="TR-0001", lifecycle="live", operationalises=["FR-0001"], supersedes="TR-0000", superseded_by=None,
                            revisions=[], last_breaking_revision=None, implemented_by=["src/TR-0000.py"], tests=["tests/FR-0002.py"]),
            SimpleNamespace(id="TR-0000", lifecycle="superseded", operationalises=["FR-0001"], supersedes=None, superseded_by="TR-0001",
                            revisions=["DEC-0001"], last_breaking_revision=None),
        ],
        decs=[SimpleNamespace(id="DEC-0001", status="ratified", revises="TR-0000", constrained_by=[], authorised_by=["ADR-0001"])],
        adrs=[SimpleNamespace(id="ADR-0001", status="accepted")],
    )
    result = spec_query.slice(graph, "TR-0001")
    assert _ids(result) == ["FR-0001", "TR-0001"]
    assert result.excluded == [] and result.notes == []
    assert "FR-0002" not in result and "TR-0000" not in result and "DEC-0001" not in result


# covers hub-tooling FR-0005:AC-4
def test_slice_unresolved_adr_is_a_note_never_an_error():
    graph = SimpleNamespace(
        frs=[SimpleNamespace(id="FR-0001", lifecycle="live", extends=[], depends_on=[], revisions=["DEC-0001"], last_breaking_revision=None)],
        trs=[],
        decs=[SimpleNamespace(id="DEC-0001", status="ratified", revises="FR-0001", constrained_by=[],
                              authorised_by=["ADR-0099"], invokes_exception="ADR-0098§when-you-may-deviate")],
        adrs=[],
    )
    result = spec_query.slice(graph, "FR-0001")
    assert _ids(result) == ["FR-0001", "DEC-0001"]
    assert result.excluded == []
    assert any("ADR-0099" in n for n in result.notes) and any("ADR-0098" in n for n in result.notes)


# ---------------------------------------------------------------------------
# AC-5: slice, migration mode
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-5
def test_slice_migration_adds_predecessor_and_its_current_window_and_nothing_older(graph):
    current = spec_query.slice(graph, "TR-0001")
    migration = spec_query.slice(graph, "TR-0001", mode="migration")
    assert migration.mode == "migration"
    assert set(_ids(migration)) - set(_ids(current)) == {"TR-0000", "DEC-0007"}
    assert set(_ids(current)) <= set(_ids(migration))
    assert _ids(migration) == ["FR-0100", "FR-0102", "TR-0000", "TR-0001", "DEC-0005", "DEC-0007", "ADR-0001"]
    pred = migration.get("TR-0000")
    assert pred.visibility == "superseded" and pred.via == "supersedes"
    mig = migration.get("DEC-0007")
    assert mig.via == "revisions of TR-0000"
    assert mig.obj.breaking is True
    assert mig.obj.provisional_until == "2026-06-30"
    assert mig.obj.invokes_exception == "ADR-0001§when-you-may-deviate"
    assert mig.obj.authorised_by == ["ADR-0001"]
    # The predecessor's pre-breaking DEC is the only new exclusion.
    assert _excluded(migration) - _excluded(current) == {("DEC-0006", "live", "revisions of TR-0000 (pre-breaking)")}
    assert migration.notes == []
    assert spec_query.slice(graph, "TR-0001", mode="migration") == migration


# covers hub-tooling FR-0005:AC-5
def test_slice_migration_without_supersession_equals_current_plus_one_note(graph):
    current = spec_query.slice(graph, "TR-0002")
    migration = spec_query.slice(graph, "TR-0002", mode="migration")
    assert _ids(migration) == _ids(current)
    assert _excluded(migration) == _excluded(current)
    assert [o.via for o in migration.objects] == [o.via for o in current.objects]
    assert len(migration.notes) == 1 and "TR-0002" in migration.notes[0]
    assert "supersedes" in migration.notes[0] and "superseded_by" in migration.notes[0]
    assert current.notes == []


# covers hub-tooling FR-0005:AC-5
def test_slice_migration_follows_superseded_by_from_a_superseded_root(graph):
    result = spec_query.slice(graph, "FR-0101", mode="migration")
    assert _ids(result) == ["FR-0100", "FR-0101", "FR-0102", "DEC-0005", "ADR-0001"]
    assert result.get("FR-0101").visibility == "superseded" and result.get("FR-0101").via == "root"
    assert result.get("FR-0100").via == "superseded_by"
    assert result.notes == []
    assert _ids(spec_query.slice(graph, "FR-0101")) == ["FR-0101"]  # current mode: root only


# covers hub-tooling FR-0005:AC-5
def test_slice_migration_stops_at_one_generation_and_does_not_hop_from_the_neighbour():
    """Adversarial: A supersedes B supersedes C. Migration from A adds B (and
    B's window) but neither C nor the FR only B operationalises."""
    graph = SimpleNamespace(
        frs=[
            SimpleNamespace(id="FR-0001", lifecycle="live", extends=[], depends_on=[], revisions=[], last_breaking_revision=None),
            SimpleNamespace(id="FR-0002", lifecycle="live", extends=[], depends_on=[], revisions=[], last_breaking_revision=None),
        ],
        trs=[
            SimpleNamespace(id="TR-0003", lifecycle="live", operationalises=["FR-0001"], supersedes="TR-0002", superseded_by=None, revisions=[], last_breaking_revision=None),
            SimpleNamespace(id="TR-0002", lifecycle="superseded", operationalises=["FR-0002"], supersedes="TR-0001", superseded_by="TR-0003", revisions=["DEC-0002"], last_breaking_revision=2),
            SimpleNamespace(id="TR-0001", lifecycle="superseded", operationalises=["FR-0002"], supersedes=None, superseded_by="TR-0002", revisions=["DEC-0001"], last_breaking_revision=2),
        ],
        decs=[
            SimpleNamespace(id="DEC-0001", status="ratified", revises="TR-0001", breaking=True, constrained_by=[], authorised_by=[]),
            SimpleNamespace(id="DEC-0002", status="ratified", revises="TR-0002", breaking=True, constrained_by=[], authorised_by=[]),
        ],
        adrs=[],
    )
    result = spec_query.slice(graph, "TR-0003", mode="migration")
    assert _ids(result) == ["FR-0001", "TR-0002", "TR-0003", "DEC-0002"]
    assert "TR-0001" not in result and "DEC-0001" not in result and "FR-0002" not in result
    assert result.excluded == []


# covers hub-tooling FR-0005:AC-5
@pytest.mark.parametrize("mode", ["history", "all", "", "Current", "MIGRATION", None])
def test_slice_mode_outside_enum_raises_value_error(graph, mode):
    with pytest.raises(ValueError) as exc:
        spec_query.slice(graph, "TR-0001", mode=mode)
    assert repr(mode) in str(exc.value)


# ---------------------------------------------------------------------------
# AC-6: root rules
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-6
def test_slice_accepts_a_superseded_root_and_returns_it_with_its_class(graph):
    result = spec_query.slice(graph, "FR-0101")
    assert result.root == "FR-0101"
    root = result.get("FR-0101")
    assert root.visibility == "superseded" and root.via == "root" and root.type == "FR"
    assert _ids(result) == ["FR-0101"]
    tr_result = spec_query.slice(graph, "TR-0000")
    assert tr_result.get("TR-0000").visibility == "superseded"
    assert _ids(tr_result) == ["FR-0100", "FR-0102", "TR-0000", "DEC-0005", "DEC-0007", "ADR-0001"]


# covers hub-tooling FR-0005:AC-6
def test_slice_fr_root_includes_default_view_trs_extends_and_depends_on(graph):
    result = spec_query.slice(graph, "FR-0100")
    assert _ids(result) == [
        "FR-0100", "FR-0102", "FR-0103",
        "TR-0001", "TR-0002", "TR-0003",
        "DEC-0002", "DEC-0003", "DEC-0005",
        "ADR-0001", "ADR-0002",
    ]
    via = _via(result)
    assert via["FR-0102"] == "depends_on" and via["FR-0103"] == "extends"
    assert result.get("FR-0103").visibility == "draft" and result.get("TR-0003").visibility == "draft"
    assert {via[t] for t in ("TR-0001", "TR-0002", "TR-0003")} == {"reverse operationalises"}
    assert ("TR-0000", "superseded", "reverse operationalises") in _excluded(result)
    # extends / depends_on are root-only: FR-0103's own extends (FR-0101) is not followed.
    assert ("FR-0101", "superseded", "extends") not in _excluded(result)


# covers hub-tooling FR-0005:AC-6
def test_slice_draft_root_excludes_its_superseded_extends_target(graph):
    result = spec_query.slice(graph, "FR-0103")
    assert _ids(result) == ["FR-0103"]
    assert result.get("FR-0103").visibility == "draft"
    assert _excluded(result) == {("FR-0101", "superseded", "extends")}


# covers hub-tooling FR-0005:AC-6
@pytest.mark.parametrize(
    "root_id,exc_type",
    [("DEC-0001", ValueError), ("ADR-0001", ValueError), ("FR-9999", KeyError), ("TR-9999", KeyError), ("", KeyError), ("fr-0100", KeyError)],
)
def test_slice_rejects_dec_adr_and_unknown_roots_naming_the_id(graph, root_id, exc_type):
    with pytest.raises(exc_type) as exc:
        spec_query.slice(graph, root_id)
    assert root_id in str(exc.value)
    with pytest.raises((KeyError, ValueError)):
        spec_query.slice(graph, root_id, mode="migration")


# covers hub-tooling FR-0005:AC-6
@pytest.mark.parametrize("root_id", ["DEC-0001", "ADR-0001", "FR-9999"])
def test_cli_slice_bad_root_is_stderr_naming_the_id_exit_1_and_writes_nothing(tmp_path, root_id):
    repo = _build_fixture_repo(tmp_path)
    before = _snapshot(repo)
    for extra in ((), ("--json",), ("--mode", "migration")):
        proc = _run(repo, "index-specs.py", "--slice", root_id, *extra)
        assert proc.returncode == 1
        assert root_id in proc.stderr and "--slice" in proc.stderr
        assert proc.stdout == ""
    assert _snapshot(repo) == before


# ---------------------------------------------------------------------------
# AC-7: provisional report
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-7
def test_provisional_classifies_past_pending_event_and_skips_non_default_view(graph):
    report = spec_query.provisional(graph.decs, AS_OF, _objs_by_id(graph))
    assert report.as_of == AS_OF
    assert [d.id for d in report.past] == ["DEC-0007", "DEC-0008"]  # 2026-06-30; 2026-09-07 == as_of
    assert [d.id for d in report.pending] == ["DEC-0003"]  # 2026-12-31
    assert [d.id for d in report.event] == ["DEC-0005"]  # "after Project A pilot tenant 2 onboards"
    reported = {d.id for group in (report.past, report.pending, report.event) for d in group}
    assert "DEC-0009" not in reported  # rejected, past date
    assert "DEC-0010" not in reported  # superseded, past date
    assert "DEC-0004" not in reported  # pre-breaking, past date
    assert not reported & {d.id for d in graph.decs if d.provisional_until is None}
    again = spec_query.provisional(list(reversed(graph.decs)), AS_OF, _objs_by_id(graph))
    assert ([d.id for d in again.past], [d.id for d in again.pending], [d.id for d in again.event]) == (
        ["DEC-0007", "DEC-0008"], ["DEC-0003"], ["DEC-0005"]
    )


# covers hub-tooling FR-0005:AC-7
def test_provisional_as_of_moves_the_boundary(graph):
    early = spec_query.provisional(graph.decs, date(2026, 1, 1), _objs_by_id(graph))
    assert [d.id for d in early.past] == []
    assert [d.id for d in early.pending] == ["DEC-0003", "DEC-0007", "DEC-0008"]
    late = spec_query.provisional(graph.decs, date(2027, 1, 1), _objs_by_id(graph))
    assert [d.id for d in late.past] == ["DEC-0003", "DEC-0007", "DEC-0008"]
    assert [d.id for d in late.pending] == []
    assert [d.id for d in late.event] == ["DEC-0005"]  # events never become past by date


# covers hub-tooling FR-0005:AC-7
@pytest.mark.parametrize(
    "trigger,expected",
    [
        ("2026-06-30", "past"),
        ("2026-09-07", "past"),  # equal to as_of is past (<=)
        ("2026-09-08", "pending"),
        ("2026-12-31", "pending"),
        ("after Project A pilot tenant 2 onboards", "event"),
        ("2026-13-01", "event"),  # ISO-shaped but not a date
        ("2026-6-30", "event"),  # not YYYY-MM-DD
        ("30/06/2026", "event"),
        ("2026-06-30T00:00", "event"),
    ],
)
def test_classify_trigger_boundaries_and_malformed_dates(trigger, expected):
    assert spec_query.classify_trigger(trigger, AS_OF) == expected


# covers hub-tooling FR-0005:AC-7
def test_provisional_rejected_and_superseded_with_past_dates_are_never_reported_even_without_targets():
    decs = [
        SimpleNamespace(id="DEC-0001", status="rejected", revises="TR-0001", provisional_until="2020-01-01"),
        SimpleNamespace(id="DEC-0002", status="superseded", revises="TR-0001", provisional_until="2020-01-01"),
        SimpleNamespace(id="DEC-0003", status="proposed", revises=None, provisional_until="2020-01-01"),
        SimpleNamespace(id="DEC-0004", status="ratified", revises=None, provisional_until=None),
    ]
    report = spec_query.provisional(decs, AS_OF)
    assert [d.id for d in report.past] == ["DEC-0003"]
    assert report.pending == [] and report.event == []


# ---------------------------------------------------------------------------
# AC-8: CLI query modes
# ---------------------------------------------------------------------------

QUERY_ARGS = [
    ("--list", "fr"),
    ("--list", "all", "--include", "all", "--json"),
    ("--list", "dec", "--include", "superseded,rejected,history"),
    ("--slice", "TR-0001"),
    ("--slice", "TR-0001", "--mode", "migration", "--json"),
    ("--provisional",),
    ("--provisional", "--as-of", "2026-09-07", "--json"),
]


# covers hub-tooling FR-0005:AC-8
@pytest.mark.parametrize("args", QUERY_ARGS, ids=lambda a: " ".join(a))
def test_cli_query_modes_write_nothing_and_exit_0_on_valid_tree(tmp_path, args):
    repo = _build_fixture_repo(tmp_path)
    (repo / ".agent-team").mkdir()
    (repo / ".agent-team" / "codeowners-config.yaml").write_text('owner_handle: "@team"\n', encoding="utf-8")
    before = _snapshot(repo)
    proc = _run(repo, "index-specs.py", *args)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()
    assert not (repo / "specs" / "INDEX.md").exists()
    assert not (repo / "CODEOWNERS").exists()
    assert _snapshot(repo) == before
    assert _lint_stderr(proc) == []  # no warnings, no past-trigger lines from a query
    # Anchor: the plain run does write, so the assertion above is a real distinction.
    assert _run(repo, "index-specs.py").returncode == 0
    assert (repo / "specs" / "INDEX.md").exists() and (repo / "CODEOWNERS").exists()


# covers hub-tooling FR-0005:AC-8
@pytest.mark.parametrize("args", QUERY_ARGS, ids=lambda a: " ".join(a))
def test_cli_query_modes_on_broken_tree_print_validate_listing_and_exit_1(tmp_path, args):
    repo = _build_fixture_repo(
        tmp_path,
        {
            "TR-0009-broken.md": _tr_markdown("TR-0009").replace("[FR-0100]", "[FR-9999]"),
            "decisions/DEC-0099-broken.md": _dec_markdown("DEC-0099", status="accepted"),
        },
    )
    before = _snapshot(repo)
    validate = _run(repo, "index-specs.py", "--validate")
    assert validate.returncode == 1 and "Spec validation FAILED" in validate.stderr
    assert "TR-0009-broken.md: operationalises references unknown FR 'FR-9999'" in validate.stderr
    assert "DEC-0099-broken.md: status 'accepted' not in" in validate.stderr
    proc = _run(repo, "index-specs.py", *args)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr == validate.stderr
    assert _snapshot(repo) == before


# covers hub-tooling FR-0005:AC-8
def test_cli_include_accepts_subsets_and_rejects_anything_else(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    before = _snapshot(repo)
    ok = _run(repo, "index-specs.py", "--list", "all", "--include", "superseded,rejected")
    assert ok.returncode == 0
    assert ok.stdout.split() == sorted(DEFAULT_IDS + SUPERSEDED_IDS + REJECTED_IDS)
    ok = _run(repo, "index-specs.py", "--list", "dec", "--include", "history")
    assert ok.stdout.split() == [i for i in sorted(DEFAULT_IDS + HISTORY_IDS) if i.startswith("DEC-")]
    ok = _run(repo, "index-specs.py", "--list", "all", "--include", "all,history")
    assert ok.stdout.split() == ALL_IDS
    ok = _run(repo, "index-specs.py", "--list", "all", "--include", "")
    assert ok.stdout.split() == DEFAULT_IDS
    for bad in ("bogus", "superseded,draft", "ALL", "superseded rejected"):
        proc = _run(repo, "index-specs.py", "--list", "all", "--include", bad)
        assert proc.returncode == 1, bad
        assert "--include" in proc.stderr and bad.split(",")[-1].split()[-1] in proc.stderr
        assert proc.stdout == ""
    assert _snapshot(repo) == before


# covers hub-tooling FR-0005:AC-8
def test_cli_list_plain_output_is_default_view_ids_one_per_line(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    expect = {
        "fr": ["FR-0100", "FR-0102", "FR-0103"],
        "tr": ["TR-0001", "TR-0002", "TR-0003"],
        "dec": ["DEC-0002", "DEC-0003", "DEC-0005", "DEC-0007", "DEC-0008", "DEC-0011"],
        "adr": ["ADR-0001", "ADR-0002"],
        "all": DEFAULT_IDS,
    }
    for kind, ids in expect.items():
        proc = _run(repo, "index-specs.py", "--list", kind)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.splitlines() == ids, kind
    bad = _run(repo, "index-specs.py", "--list", "frs")
    assert bad.returncode != 0 and bad.stdout == ""


# covers hub-tooling FR-0005:AC-8
def test_cli_list_json_shape_and_repo_relative_posix_paths(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    proc = _run(repo, "index-specs.py", "--list", "all", "--include", "all", "--json")
    assert proc.returncode == 0, proc.stderr
    objects = json.loads(proc.stdout)
    assert isinstance(objects, list) and [o["id"] for o in objects] == ALL_IDS
    for o in objects:
        for key in ("id", "type", "title", "visibility", "path"):
            assert key in o, (o["id"], key)
        assert o["type"] == o["id"].split("-")[0]
        assert o["visibility"] in spec_query.VISIBILITY_CLASSES
        assert o["path"].startswith("specs/") and "\\" not in o["path"] and not Path(o["path"]).is_absolute()
        assert (repo / o["path"]).is_file()
        if o["type"] in ("FR", "TR"):
            assert isinstance(o["version"], int) and o["lifecycle"] in ("live", "draft", "superseded")
            assert "status" not in o or o["type"] == "FR"  # FR carries workflow status too
        else:
            assert "status" in o and "lifecycle" not in o
    by_id = {o["id"]: o for o in objects}
    assert by_id["FR-0101"]["visibility"] == "superseded" and by_id["FR-0101"]["lifecycle"] == "superseded"
    assert by_id["DEC-0009"]["visibility"] == "rejected" and by_id["DEC-0009"]["status"] == "rejected"
    assert by_id["ADR-0003"]["visibility"] == "superseded" and by_id["ADR-0003"]["status"] == "superseded"
    assert by_id["DEC-0001"]["window"] == "history" and by_id["DEC-0002"]["window"] == "current"
    assert by_id["DEC-0002"]["path"] == "specs/decisions/DEC-0002-b-breaking.md"
    assert by_id["TR-0001"]["path"] == "specs/TR-0001-approach-new.md"
    # Default JSON list carries the default view only.
    default = json.loads(_run(repo, "index-specs.py", "--list", "dec", "--json").stdout)
    assert [o["id"] for o in default] == ["DEC-0002", "DEC-0003", "DEC-0005", "DEC-0007", "DEC-0008", "DEC-0011"]


# covers hub-tooling FR-0005:AC-8
def test_cli_slice_json_shape(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    proc = _run(repo, "index-specs.py", "--slice", "TR-0001", "--mode", "migration", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload) >= {"root", "mode", "objects", "excluded", "notes"}
    assert payload["root"] == "TR-0001" and payload["mode"] == "migration"
    assert [o["id"] for o in payload["objects"]] == [
        "FR-0100", "FR-0102", "TR-0000", "TR-0001", "DEC-0005", "DEC-0007", "ADR-0001",
    ]
    for o in payload["objects"]:
        for key in ("id", "type", "title", "visibility", "path", "via"):
            assert key in o, (o["id"], key)
        assert o["path"].startswith("specs/") and "\\" not in o["path"]
        assert all(v is not None for v in o.values()), o["id"]  # non-null frontmatter fields only
    dec7 = next(o for o in payload["objects"] if o["id"] == "DEC-0007")
    assert dec7["breaking"] is True and dec7["provisional_until"] == "2026-06-30"
    assert dec7["invokes_exception"] == "ADR-0001§when-you-may-deviate" and dec7["revises"] == "TR-0000"
    tr0 = next(o for o in payload["objects"] if o["id"] == "TR-0000")
    assert tr0["visibility"] == "superseded" and tr0["via"] == "supersedes" and tr0["lifecycle"] == "superseded"
    assert {(e["id"], e["class"], e["via"]) for e in payload["excluded"]} == {
        ("FR-0101", "superseded", "constrained_by of DEC-0005"),
        ("DEC-0004", "live", "revisions of FR-0100 (pre-breaking)"),
        ("DEC-0006", "live", "revisions of TR-0000 (pre-breaking)"),
    }
    assert payload["notes"] == []
    current = json.loads(_run(repo, "index-specs.py", "--slice", "TR-0002", "--mode", "migration", "--json").stdout)
    assert len(current["notes"]) == 1 and "TR-0002" in current["notes"][0]
    human = _run(repo, "index-specs.py", "--slice", "TR-0001")
    assert human.returncode == 0 and "TR-0001" in human.stdout and "FR-0101" in human.stdout


# covers hub-tooling FR-0005:AC-8
def test_cli_provisional_as_of_override_matches_ac7_and_groups_past_first(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    proc = _run(repo, "index-specs.py", "--provisional", "--as-of", "2026-09-07", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload) >= {"past", "pending", "event"}
    assert payload["as_of"] == "2026-09-07"
    assert [d["id"] for d in payload["past"]] == ["DEC-0007", "DEC-0008"]
    assert [d["id"] for d in payload["pending"]] == ["DEC-0003"]
    assert [d["id"] for d in payload["event"]] == ["DEC-0005"]
    for entry in payload["past"] + payload["pending"] + payload["event"]:
        assert {"id", "title", "trigger", "revises", "path"} <= set(entry)
        assert entry["path"].startswith("specs/decisions/") and "\\" not in entry["path"]
    assert payload["event"][0]["trigger"] == "after Project A pilot tenant 2 onboards"
    human = _run(repo, "index-specs.py", "--provisional", "--as-of", "2026-09-07")
    assert human.returncode == 0
    text = human.stdout
    assert text.index("past") < text.index("pending") < text.index("event")
    assert text.index("DEC-0007") < text.index("DEC-0008") < text.index("DEC-0003") < text.index("DEC-0005")
    for hidden in ("DEC-0004", "DEC-0009", "DEC-0010"):
        assert hidden not in text and hidden not in proc.stdout
    early = json.loads(_run(repo, "index-specs.py", "--provisional", "--as-of", "2026-01-01", "--json").stdout)
    assert early["past"] == [] and [d["id"] for d in early["pending"]] == ["DEC-0003", "DEC-0007", "DEC-0008"]
    # Default as_of is today: DEC-0007 (2026-06-30) is past for any run from now on.
    today = json.loads(_run(repo, "index-specs.py", "--provisional", "--json").stdout)
    assert today["as_of"] == date.today().isoformat()
    assert "DEC-0007" in [d["id"] for d in today["past"]]
    bad = _run(repo, "index-specs.py", "--provisional", "--as-of", "2026-13-01")
    assert bad.returncode == 1 and "--as-of" in bad.stderr and "2026-13-01" in bad.stderr


# ---------------------------------------------------------------------------
# AC-9: INDEX.md default view, Retired / Provisional sections, no date math
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-9
def test_index_fr_tr_dec_tables_contain_only_default_view_objects(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    lines = _index_text(repo).splitlines()
    assert lines[4] == FR_HEADER
    fr_rows = [l for l in lines[6:] if l.startswith("| [FR-")]
    fr_rows = fr_rows[: next(i for i, l in enumerate(lines[6:]) if not l.startswith("| ["))]
    assert _row_ids(fr_rows) == ["FR-0100", "FR-0102", "FR-0103"]
    assert _row_ids(_table_rows(lines, "Technical requirements")) == ["TR-0001", "TR-0002", "TR-0003"]
    assert _row_ids(_table_rows(lines, "Decisions")) == ["DEC-0002", "DEC-0003", "DEC-0005", "DEC-0007", "DEC-0008", "DEC-0011"]
    assert _row_ids(_table_rows(lines, "Architecture decision records")) == ["ADR-0001", "ADR-0002", "ADR-0003"]
    # The draft FR keeps its effective Ver / Lifecycle columns (FR-0003:AC-6 still holds).
    assert "| `draft` | 1 | `draft` | architect |" in fr_rows[2]


# covers hub-tooling FR-0005:AC-9
def test_index_retired_section_is_last_after_adr_table_with_exact_rows(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    assert _run(repo, "index-specs.py").returncode == 0
    text = _index_text(repo)
    lines = text.splitlines()
    i = lines.index("## Retired objects")
    assert lines[i + 1] == ""
    assert lines[i + 2] == RETIRED_HEADER
    assert lines[i + 3] == RETIRED_SEPARATOR
    assert lines[i + 4 : i + 4 + len(EXPECTED_RETIRED_ROWS)] == EXPECTED_RETIRED_ROWS
    assert lines[-1] == EXPECTED_RETIRED_ROWS[-1] and text.endswith("|\n")
    assert lines.index("## Architecture decision records") < i
    assert not any(l.startswith("## ") for l in lines[i + 1 :])
    # Every non-default-view FR/TR/DEC and nothing else (ADRs stay in their own table).
    assert _row_ids(_table_rows(lines, "Retired objects")) == sorted(SUPERSEDED_IDS + REJECTED_IDS + HISTORY_IDS)[1:]
    assert "ADR-0003" not in text.split("## Retired objects")[1]


# covers hub-tooling FR-0005:AC-9
def test_index_provisional_section_sits_immediately_before_retired_with_exact_rows(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    assert _run(repo, "index-specs.py").returncode == 0
    lines = _index_text(repo).splitlines()
    p = lines.index("## Provisional decisions")
    r = lines.index("## Retired objects")
    assert lines.index("## Architecture decision records") < p < r
    assert not any(l.startswith("## ") for l in lines[p + 1 : r])
    assert lines[p + 1] == ""
    assert lines[p + 2] == PROVISIONAL_HEADER
    assert lines[p + 3] == PROVISIONAL_SEPARATOR
    assert lines[p + 4 : p + 4 + len(EXPECTED_PROVISIONAL_ROWS)] == EXPECTED_PROVISIONAL_ROWS
    assert lines[p + 4 + len(EXPECTED_PROVISIONAL_ROWS)] == ""
    # Default-view DECs with a trigger only: the pre-breaking, rejected and
    # superseded DECs all carry a past date and none is listed.
    listed = _row_ids(_table_rows(lines, "Provisional decisions"))
    assert listed == ["DEC-0003", "DEC-0005", "DEC-0007", "DEC-0008"]


# covers hub-tooling FR-0005:AC-9
@pytest.mark.parametrize(
    "files,expect_provisional,expect_retired",
    [
        pytest.param({"FR-0100-a.md": _fr_markdown("FR-0100")}, False, False, id="plain"),
        pytest.param(
            {
                "FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter="supersedes: FR-0001"),
                "FR-0001-old.md": _fr_markdown("FR-0001", extra_frontmatter="lifecycle: superseded\nsuperseded_by: FR-0100"),
            },
            False, True, id="retired-only",
        ),
        pytest.param(
            {
                "FR-0100-a.md": _fr_markdown("FR-0100"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="proposed", extra_frontmatter="provisional_until: 2099-01-01"),
            },
            True, False, id="provisional-only",
        ),
        pytest.param(
            {
                "FR-0100-a.md": _fr_markdown("FR-0100"),
                # A rejected DEC with a trigger is retired, not provisional.
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="rejected", extra_frontmatter="provisional_until: 2000-01-01"),
            },
            False, True, id="rejected-with-trigger",
        ),
    ],
)
def test_index_sections_omitted_when_empty(tmp_path, files, expect_provisional, expect_retired):
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    text = _index_text(repo)
    assert ("## Provisional decisions" in text) is expect_provisional
    assert ("## Retired objects" in text) is expect_retired
    if expect_retired and not expect_provisional:
        assert text.rstrip().splitlines()[-1].startswith("| [")
    assert not any(l.startswith("Provisional past trigger") for l in proc.stderr.splitlines()) or expect_retired is False


# covers hub-tooling FR-0005:AC-9
def test_index_never_evaluates_dates_and_is_byte_identical_across_runs_and_system_dates(tmp_path, graph, monkeypatch):
    repo = _build_fixture_repo(tmp_path / "cli")
    assert _run(repo, "index-specs.py").returncode == 0
    first = (repo / "specs" / "INDEX.md").read_bytes()
    assert _run(repo, "index-specs.py").returncode == 0
    assert (repo / "specs" / "INDEX.md").read_bytes() == first
    text = first.decode("utf-8")
    assert not re.search(r"\b(past|pending)\b", text, re.IGNORECASE)
    assert "2026-06-30" in text and "2026-09-07" in text  # triggers are listed verbatim ...
    # ... but never classified: render_index cannot reach the clock at all.

    class NoClock:
        @staticmethod
        def today():
            raise AssertionError("render_index evaluated the system date")

        fromisoformat = staticmethod(date.fromisoformat)

    monkeypatch.setattr(index_specs, "date", NoClock)
    monkeypatch.setattr(spec_query, "date", NoClock)
    rendered = index_specs.render_index(graph.frs, [], graph.adrs, graph.trs, graph.decs)
    assert "## Provisional decisions" in rendered and "## Retired objects" in rendered
    for fn in (index_specs.render_index, index_specs._render_provisional_table, index_specs._render_retired_table):
        src = inspect.getsource(fn)
        assert "today" not in src and "provisional(" not in src and "classify_trigger" not in src, fn.__name__


# covers hub-tooling FR-0005:AC-9
def test_past_trigger_lines_go_to_stderr_only_at_index_time_and_exit_0(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    past_lines = [l for l in proc.stderr.splitlines() if l.startswith("Provisional past trigger:")]
    assert "Provisional past trigger: DEC-0007 (2026-06-30)" in past_lines
    for line in past_lines:
        assert re.fullmatch(r"Provisional past trigger: DEC-\d{4} \(.+\)", line), line
    # Hidden DECs with past dates never surface; pending / event triggers never surface.
    for hidden in ("DEC-0004", "DEC-0009", "DEC-0010", "DEC-0003", "DEC-0005"):
        assert not any(hidden in l for l in past_lines), hidden
    assert "Provisional past trigger" not in proc.stdout
    assert "Provisional past trigger" not in _index_text(repo)
    # --validate is not index time: no past-trigger lines there (AC-11 keeps its stderr to FR-0003/FR-0004).
    validate = _run(repo, "index-specs.py", "--validate")
    assert validate.returncode == 0 and "Provisional past trigger" not in validate.stderr


# ---------------------------------------------------------------------------
# AC-10: deploy-gate.py unchanged, byte-identical INDEX.md
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-10
def test_deploy_gate_source_unchanged_and_imports_intact():
    # Historical half: FR-0005's own diff left deploy-gate.py byte-identical
    # (file at the FR-0005 merge commit == file just before it).
    baseline = _git_show_baseline("template/scripts/deploy-gate.py")
    at_merge = _git_show_baseline("template/scripts/deploy-gate.py", _FR0005_MERGE_REF)
    if baseline is not None and at_merge is not None:
        assert at_merge.replace(b"\r\n", b"\n") == baseline.replace(b"\r\n", b"\n")
    # Live half: whatever later FRs add (FR-0002 instruments the gate), it still
    # consumes the indexer through the two-argument `render_index` and never
    # the default view.
    current = (_SCRIPTS_DIR / "deploy-gate.py").read_bytes()
    source = current.decode("utf-8")
    assert "spec_query" not in source and "in_default_view" not in source and "retired" not in source.lower()
    assert "render_index(parsed_frs, repo_files)" in source
    spec = importlib.util.spec_from_file_location("deploy_gate_under_test_fr0005", _SCRIPTS_DIR / "deploy-gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for name in ("collect_frs", "validate_graph", "render_index", "FR", "INDEX_PATH"):
        assert hasattr(mod, name), name
    params = inspect.signature(index_specs.render_index).parameters
    assert list(params)[:2] == ["frs", "repo_files"]
    assert all(params[p].default is None for p in list(params)[2:])


# covers hub-tooling FR-0005:AC-10
def test_deploy_gate_stage_full_passes_and_writes_byte_identical_index_with_new_sections(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    # FR-0101 is `merged`, so the full stage requires its one AC to be covered.
    (repo / "tests").mkdir()
    # Assembled so the gate scanning THIS file (it rides into bootstrapped
    # projects) does not see a literal annotation for an FR that is not there.
    annotation = "# @" + "covers " + "FR-0101:AC-1"
    (repo / "tests" / "test_cov.py").write_text(f"{annotation}\ndef test_x():\n    pass\n", encoding="utf-8")
    index = repo / "specs" / "INDEX.md"

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    from_indexer = index.read_bytes()
    index.unlink()

    proc = _run(repo, "deploy-gate.py", "--stage", "full")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    from_gate = index.read_bytes()
    assert from_gate == from_indexer
    text = from_gate.decode("utf-8")
    assert "## Retired objects" in text and "## Provisional decisions" in text
    assert "| [FR-0101](FR-0101-need-a-old.md) | FR |" in text
    assert not re.search(r"\b(past|pending)\b", text, re.IGNORECASE)
    # And the gate's read-only mode still writes nothing.
    index.unlink()
    proc = _run(repo, "deploy-gate.py", "--status-only")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not index.exists()


# covers hub-tooling FR-0005:AC-10
def test_render_index_two_positional_args_reaches_both_new_sections(tmp_path, graph):
    two_arg = index_specs.render_index(graph.frs, [])
    five_arg = index_specs.render_index(graph.frs, [], graph.adrs, graph.trs, graph.decs)
    assert two_arg == five_arg
    assert "## Retired objects" in two_arg and "## Provisional decisions" in two_arg
    # Explicit empty TR/DEC lists: the FR-side retired row still renders, the DEC rows do not.
    frs_only = index_specs.render_index(graph.frs, [], graph.adrs, [], [])
    assert "## Provisional decisions" not in frs_only
    assert "| [FR-0101](FR-0101-need-a-old.md) | FR |" in frs_only and "DEC-0001" not in frs_only


# ---------------------------------------------------------------------------
# AC-11: backward compatibility
# ---------------------------------------------------------------------------


def _unversioned_tree() -> dict[str, str]:
    """No versioning fields, no TR / DEC files: the shape every pre-FR-0003
    project has. Includes an ADR so the ADR table is exercised too."""
    return {
        "FR-0001-a.md": _fr_markdown("FR-0001", status="merged"),
        "FR-0002-b.md": _fr_markdown("FR-0002").replace("depends_on: []", "depends_on: [FR-0001]"),
        "FR-0003-c.md": _fr_markdown("FR-0003", status="draft"),
        "decisions/ADR-0001-a.md": _adr_markdown("ADR-0001"),
        "decisions/README.md": "# Decisions\n",
    }


def _run_old_and_new(tmp_path: Path, files: dict[str, str], *args: str):
    baseline = _baseline_indexer(tmp_path)
    if baseline is None:
        pytest.skip(f"baseline commit {_BASELINE_REF} not reachable (not running inside the hub checkout)")
    new = _build_repo(tmp_path / "new", files)
    old = _build_repo(tmp_path / "old", files)
    shutil.copy(baseline, old / "scripts" / "index-specs.py")
    return _run(old, "index-specs.py", *args), _run(new, "index-specs.py", *args), old, new


def _lf(path: Path) -> bytes:
    """Bytes of a file the *pinned baseline* indexer wrote, CRLF-normalised.

    The baseline predates FR-0007 and still applies platform newline
    translation, so on Windows it writes CRLF where the current indexer writes
    LF by contract. Normalising the baseline side only keeps these
    backward-compat assertions about content, not about the line terminator.
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


def _strip_gates_column(data: bytes) -> bytes:
    """An INDEX.md's bytes with the FR table's trailing `Gates` cell removed.

    FR-0008 AC-1 added a `Gates` column to the FR table *after* the baselines
    below were pinned, so the new side carries one cell the baseline cannot
    (DEC-0012 item 2(c)). Only the FR table is touched: the TR, DEC, ADR,
    Provisional and Retired tables have no such column and must come back
    byte-identical. Exactly one cell is removed per FR-table line, asserted
    here so a future column cannot slip through this normalisation silently.
    A local copy of `test_index_specs_dec_tr.py`'s helper: these files ride
    independently into every bootstrapped project and share no support module.
    """
    lines = data.split(b"\n")
    header = FR_HEADER.encode("utf-8")
    if header not in lines:
        return data
    i = lines.index(header)
    while i < len(lines) and lines[i].startswith(b"|"):
        cells = lines[i].split(b"|")
        assert len(cells) >= 3 and cells[-1] == b"", lines[i]
        before = len(cells)
        del cells[-2]
        assert len(cells) == before - 1, lines[i]
        lines[i] = b"|".join(cells)
        i += 1
    return b"\n".join(lines)


# covers hub-tooling FR-0005:AC-11
def test_unversioned_tree_identical_to_pinned_baseline_in_exit_stderr_and_index(tmp_path):
    old_proc, new_proc, old, new = _run_old_and_new(tmp_path, _unversioned_tree())
    assert old_proc.returncode == 0
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (new_proc.returncode, new_proc.stdout, new_proc.stderr)
    assert _lf(old / "specs" / "INDEX.md") == _strip_gates_column(
        (new / "specs" / "INDEX.md").read_bytes()
    )
    text = _index_text(new)
    assert "## Retired objects" not in text and "## Provisional decisions" not in text
    assert "## Architecture decision records" in text
    assert "Provisional past trigger" not in new_proc.stderr
    old_v, new_v, _, _ = _run_old_and_new(tmp_path / "v", _unversioned_tree(), "--validate")
    assert (old_v.returncode, old_v.stdout, old_v.stderr) == (new_v.returncode, new_v.stdout, new_v.stderr)


# covers hub-tooling FR-0005:AC-11
def test_unversioned_tree_adds_no_sections_and_no_stderr_lines_without_git_baseline(tmp_path):
    """Independent of the git baseline: every FR live by default, no TR / DEC
    files -> no new headings, no new stderr lines, same counts."""
    repo = _build_repo(tmp_path, _unversioned_tree())
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == []
    assert "Wrote specs" in proc.stdout and "TRs" not in proc.stdout
    text = _index_text(repo)
    for heading in ("## Retired objects", "## Provisional decisions", "## Technical requirements", "## Decisions"):
        assert heading not in text
    validate = _run(repo, "index-specs.py", "--validate")
    assert validate.stdout.strip() == "Spec graph OK (3 FRs). Wrote nothing (--validate)."
    assert _lint_stderr(validate) == []


# covers hub-tooling FR-0005:AC-11
def test_validate_on_fixture_tree_exits_0_with_ok_and_exactly_the_fr0003_fr0004_warnings(tmp_path, graph):
    repo = _build_fixture_repo(tmp_path / "cli")
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "Spec graph OK (4 FRs, 4 TRs, 11 DECs). Wrote nothing (--validate)."
    expected = [
        *index_specs._all_versioning_warnings(graph.frs, graph.trs, graph.decs, graph.adrs),
        *index_specs._adr_warnings(graph.adrs),
    ]
    # The fixture is consistent by construction: FR-0003/FR-0004 define no
    # warning line for it, and this FR adds none.
    assert expected == []
    assert _lint_stderr(proc) == []
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0005:AC-11
def test_plain_run_on_fixture_tree_adds_only_past_trigger_lines_to_stderr(tmp_path):
    repo = _build_fixture_repo(tmp_path)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    extra = _lint_stderr(proc)
    assert extra and all(l.startswith("Provisional past trigger: ") for l in extra), extra
    # Drop the two provisional DECs whose dates are past -> stderr is exactly FR-0003/FR-0004's (empty).
    for name in ("decisions/DEC-0007-a-old-migration.md", "decisions/DEC-0008-creating-proposed.md"):
        path = repo / "specs" / name
        path.write_text(
            re.sub(r"^provisional_until: .*\n", "", path.read_text(encoding="utf-8"), flags=re.M),
            encoding="utf-8",
        )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0 and _lint_stderr(proc) == [], proc.stderr


# covers hub-tooling FR-0005:AC-11
def test_template_specs_dir_identical_vs_pinned_baseline(tmp_path):
    """`template/` itself (or the bootstrapped project's own specs/) is one of
    the trees AC-11 names explicitly."""
    files: dict[str, str] = {}
    for p in sorted(_SPECS_DIR.glob("*.md")):
        files[p.name] = p.read_text(encoding="utf-8")
    decisions = _SPECS_DIR / "decisions"
    for p in sorted(decisions.glob("*.md")) if decisions.is_dir() else []:
        files[f"decisions/{p.name}"] = p.read_text(encoding="utf-8")
    files.pop("INDEX.md", None)
    old_proc, new_proc, old, new = _run_old_and_new(tmp_path, files)
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (new_proc.returncode, new_proc.stdout, new_proc.stderr)
    if old_proc.returncode == 0:
        assert _lf(old / "specs" / "INDEX.md") == _strip_gates_column(
            (new / "specs" / "INDEX.md").read_bytes()
        )


# ---------------------------------------------------------------------------
# AC-12: the fixture tree
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-12
def test_fixture_tree_contains_every_object_ac12_names_and_validates(tmp_path, graph):
    by_id = _by_id(graph)
    assert sorted(by_id) == ALL_IDS
    # Superseded FR and its live successor.
    assert by_id["FR-0101"].lifecycle == "superseded" and by_id["FR-0101"].superseded_by == "FR-0100"
    assert by_id["FR-0100"].lifecycle == "live" and by_id["FR-0100"].supersedes == "FR-0101"
    # Superseded TR whose current window is exactly the migration DEC; successor at version 1.
    old = by_id["TR-0000"]
    assert old.lifecycle == "superseded" and old.superseded_by == "TR-0001"
    assert spec_query.revision_window(old) == (["DEC-0007"], ["DEC-0006"])
    mig = by_id["DEC-0007"]
    assert mig.revises == "TR-0000" and mig.breaking is True
    assert mig.provisional_until == "2026-06-30" and date.fromisoformat(mig.provisional_until) < AS_OF
    assert mig.invokes_exception == "ADR-0001§when-you-may-deviate" and mig.authorised_by == ["ADR-0001"]
    new = by_id["TR-0001"]
    assert new.lifecycle == "live" and new.version == 1 and new.revisions == [] and new.supersedes == "TR-0000"
    # Live TR with three revisions, the second breaking, lbr 3.
    tr = by_id["TR-0002"]
    assert tr.lifecycle == "live" and tr.revisions == ["DEC-0001", "DEC-0002", "DEC-0003"]
    assert [by_id[d].breaking for d in tr.revisions] == [False, True, False] and tr.last_breaking_revision == 3
    # Rejected DEC revising a live TR.
    assert by_id["DEC-0009"].status == "rejected" and by_id["DEC-0009"].revises == "TR-0002"
    # Live DECs with a future date and with an event string.
    assert by_id["DEC-0003"].status == "ratified" and date.fromisoformat(by_id["DEC-0003"].provisional_until) > AS_OF
    assert by_id["DEC-0005"].status == "ratified" and spec_query.classify_trigger(by_id["DEC-0005"].provisional_until, AS_OF) == "event"
    # One ADR of each named status.
    assert {a.id: a.status for a in graph.adrs} == {"ADR-0001": "accepted", "ADR-0002": "proposed", "ADR-0003": "superseded"}
    assert all(a.warnings == [] for a in graph.adrs)
    # The tree passes --validate.
    repo = _build_fixture_repo(tmp_path / "cli")
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0 and "Spec graph OK" in proc.stdout, proc.stderr


# covers hub-tooling FR-0005:AC-12
def test_fixture_tree_is_synthetic_and_self_contained():
    files = sorted(p.relative_to(_FIXTURE_SPECS).as_posix() for p in _FIXTURE_SPECS.rglob("*.md"))
    assert len(files) == 22
    assert not any(name == "INDEX.md" for name in files)
    for p in _FIXTURE_SPECS.rglob("*.md"):
        text = p.read_text(encoding="utf-8")
        assert "Synthetic" in text or "synthetic" in text, p.name
        assert "@" not in text.split("---", 2)[1].replace("§", "")  # no emails / @version citations


# ---------------------------------------------------------------------------
# AC-13: documentation and the untouched consumers
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0005:AC-13
def test_specs_readme_documents_visibility_default_view_query_modes_and_consumers():
    text = (_SPECS_DIR / "README.md").read_text(encoding="utf-8")
    # Visibility table.
    assert "| `live` |" in text and "| `draft` |" in text and "| `superseded` |" in text and "| `rejected` |" in text
    assert "`proposed`, `ratified`" in text and "`superseded`, `deprecated`" in text
    # Default-view rule and opt-ins.
    assert "Default view" in text and "last_breaking_revision" in text
    for opt in ("`superseded`", "`rejected`", "`history`", "`all`"):
        assert opt in text
    # Three CLI query modes with flags.
    for flag in ("--list", "--slice", "--provisional", "--include", "--mode", "--as-of", "--json"):
        assert flag in text, flag
    assert "migration" in text and "current" in text
    # JSON keys.
    for key in ("`id`", "`type`", "`title`", "`visibility`", "`path`", "`root`", "`mode`", "`objects`", "`excluded`", "`notes`", "`past`", "`pending`", "`event`"):
        assert key in text, key
    # Consumer table.
    consumers = text.split("## Consumers", 1)[1]
    for name in ("index-specs.py", "deploy-gate.py", "dispatch.py", "render-docs.py", "agent-status.py", "hub-index.py"):
        assert name in consumers, name
    assert "## Retired objects" in text and "## Provisional decisions" in text


# covers hub-tooling FR-0005:AC-13
@pytest.mark.parametrize("script", _CONSUMER_SCRIPTS)
def test_consumer_scripts_have_an_empty_diff_across_the_fr0005_merge(script):
    """FR-0005's diff for each consumer is empty: the file at the FR-0005 merge
    commit is byte-identical to the file just before it. Later FRs may touch
    these scripts (FR-0002 instruments deploy-gate.py and dispatch.py); the
    live invariant FR-0005 cares about is the next test."""
    baseline = _git_show_baseline(f"template/scripts/{script}")
    at_merge = _git_show_baseline(f"template/scripts/{script}", _FR0005_MERGE_REF)
    if baseline is None or at_merge is None:
        pytest.skip(f"{_BASELINE_REF} / {_FR0005_MERGE_REF} not reachable (not running inside the hub checkout)")
    assert at_merge.replace(b"\r\n", b"\n") == baseline.replace(b"\r\n", b"\n"), script


# covers hub-tooling FR-0005:AC-13
def test_consumer_scripts_do_not_import_spec_query():
    for script in _CONSUMER_SCRIPTS:
        source = (_SCRIPTS_DIR / script).read_text(encoding="utf-8")
        assert "spec_query" not in source, script
