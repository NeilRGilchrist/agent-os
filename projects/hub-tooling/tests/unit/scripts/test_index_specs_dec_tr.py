"""Reviewer tests for FR-0004 — DEC and TR object types.

Covers the two new templates, discovery / identity / shape / enum validation
for `specs/TR-*.md` and `specs/decisions/DEC-*.md`, hard cross-object
resolution (including the FR / TR `revisions` -> DEC resolution FR-0003
deferred), the warn-only reciprocity / breaking-marker / migration-window /
DEC-symmetry checks, the `## Technical requirements` and `## Decisions`
tables, backward compatibility for trees with no TR / DEC files, CLI
behaviour, the Python API (`DEC`, `TR`, `collect_*`, `collect_graph`,
`is_live_dec`) and the documentation ACs.

Same harness as `test_index_specs_versioning.py`: the hyphenated module is
loaded by path for the pure checks, and the CLI surfaces are driven through
`subprocess` against a self-contained temporary repo. Every fixture here is
synthetic.

Coverage annotations are written `# covers hub-tooling FR-0004:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0004 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (see test_index_specs_versioning.py).
"""

# Convention: backward-compat baselines pin a commit, never a branch name.
# `main:` only means "the code before this FR" while the FR lives on a feature
# branch; once merged, `main:` IS the code under test and every "identical to
# baseline" assertion turns into a tautology (and the "differs only by the
# default view" check fails with zero differences). Pinning a commit keeps the
# comparison meaningful forever. Outside the hub checkout (bootstrapped
# projects, shallow clones) the commit is unreachable and the tests skip.

from __future__ import annotations

import dataclasses
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# once bootstrapped).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_SPECS_DIR = _TEMPLATE_DIR / "specs"
_FR_TEMPLATE = _SPECS_DIR / "_template" / "FR-XXXX-template.md"
_TR_TEMPLATE = _SPECS_DIR / "_template" / "TR-XXXX-template.md"
_DEC_TEMPLATE = _SPECS_DIR / "_template" / "DEC-XXXX-template.md"
_COPY_SCRIPTS = ("index-specs.py", "deploy-gate.py", "spec_footprint.py", "spec_query.py")

# Field tables from FR-0004 "What" — attribute names equal frontmatter keys.
DEC_FIELDS = (
    "id",
    "title",
    "tier",
    "status",
    "satisfies",
    "constrained_by",
    "revises",
    "breaking",
    "authorised_by",
    "invokes_exception",
    "alternatives",
    "reversibility",
    "provisional_until",
    "client_visible",
    "supersedes",
    "superseded_by",
    "rationale",
    "created",
    "updated",
)
TR_FIELDS = (
    "id",
    "title",
    "operationalises",
    "version",
    "lifecycle",
    "revisions",
    "last_breaking_revision",
    "supersedes",
    "superseded_by",
    "implemented_by",
    "success_criteria",
    "tests",
    "created",
    "updated",
)
DEC_DEFAULTS = {
    "satisfies": [],
    "constrained_by": [],
    "revises": None,
    "breaking": False,
    "authorised_by": [],
    "invokes_exception": None,
    "alternatives": [],
    "reversibility": None,
    "provisional_until": None,
    "client_visible": False,
    "supersedes": None,
    "superseded_by": None,
}
TR_DEFAULTS = {
    "version": 1,
    "lifecycle": "live",
    "revisions": [],
    "last_breaking_revision": None,
    "supersedes": None,
    "superseded_by": None,
    "implemented_by": [],
    "success_criteria": [],
    "tests": [],
}
# Template pre-fill for every optional field (AC-1): the default, as YAML.
DEC_TEMPLATE_PREFILL = {
    "status": "status: proposed",
    "satisfies": "satisfies: []",
    "constrained_by": "constrained_by: []",
    "revises": "revises: null",
    "breaking": "breaking: false",
    "authorised_by": "authorised_by: []",
    "invokes_exception": "invokes_exception: null",
    "alternatives": "alternatives: []",
    "reversibility": "reversibility: null",
    "provisional_until": "provisional_until: null",
    "client_visible": "client_visible: false",
    "supersedes": "supersedes: null",
    "superseded_by": "superseded_by: null",
}
TR_TEMPLATE_PREFILL = {
    "version": "version: 1",
    "lifecycle": "lifecycle: draft",
    "revisions": "revisions: []",
    "last_breaking_revision": "last_breaking_revision: null",
    "supersedes": "supersedes: null",
    "superseded_by": "superseded_by: null",
    "implemented_by": "implemented_by: []",
    "success_criteria": "success_criteria: []",
    "tests": "tests: []",
}

TR_HEADER = "| ID | Title | Operationalises | Ver | Lifecycle | Last breaking | Implemented by | Updated |"
TR_SEPARATOR = "|----|-------|-----------------|-----|-----------|---------------|----------------|---------|"
DEC_HEADER = "| ID | Title | Tier | Status | Revises | Breaking | Authorised by | Updated |"
DEC_SEPARATOR = "|----|-------|------|--------|---------|----------|---------------|---------|"
FR_HEADER = "| ID | Title | Status | Ver | Lifecycle | Owner | Tags | Owns | Reads | Depends on | Derived from | Updated | Gates |"

OMIT = object()  # sentinel: drop this key from a fixture's frontmatter


def _load_index_specs():
    spec = importlib.util.spec_from_file_location(
        "index_specs_dec_tr_under_test", _SCRIPTS_DIR / "index-specs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


index_specs = _load_index_specs()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _frontmatter(fields: dict[str, object]) -> str:
    """Render top-level YAML lines. Values are spliced verbatim (already YAML);
    `OMIT` drops the key."""
    lines = [f"{k}: {v}" for k, v in fields.items() if v is not OMIT]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _fr_markdown(fr_id: str, *, extra_frontmatter: str = "", status: str = "ready") -> str:
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

Synthetic FR for FR-0004 fixtures.

## Acceptance criteria

- **AC-1:** does the first thing
"""


def _tr_markdown(tr_id: str, *, operationalises: object = "[FR-0100]", **overrides: object) -> str:
    """Synthetic TR. Keyword overrides are spliced as YAML; `OMIT` drops a key."""
    fields: dict[str, object] = {
        "id": tr_id,
        "title": f"Synthetic {tr_id}",
        "operationalises": operationalises,
    }
    fields.update(overrides)
    fields.setdefault("created", "2026-01-01")
    fields.setdefault("updated", "2026-01-02")
    return _frontmatter(fields) + f"\n# {tr_id}: Synthetic\n\n## Approach\n\nSynthetic.\n"


def _dec_markdown(
    dec_id: str,
    *,
    status: str = "ratified",
    revises: object = "null",
    breaking: object = None,
    **overrides: object,
) -> str:
    """Synthetic DEC. `breaking` defaults to `false` when `revises` is set and
    is omitted otherwise (the template's creating-DEC shape); pass `OMIT` or a
    YAML literal to control it. Other keyword overrides are spliced as YAML."""
    fields: dict[str, object] = {
        "id": dec_id,
        "title": f"Synthetic {dec_id}",
        "tier": "agent",
        "status": status,
        "revises": revises,
    }
    if breaking is None:
        breaking = "false" if revises not in ("null", OMIT) else OMIT
    fields["breaking"] = breaking
    fields.update(overrides)
    fields.setdefault("rationale", f"Synthetic decision {dec_id}.")
    fields.setdefault("created", "2026-01-01")
    fields.setdefault("updated", "2026-01-03")
    return _frontmatter(fields) + f"\n# {dec_id}: Synthetic\n\n## Context\n\nSynthetic.\n"


def _adr_markdown(adr_id: str) -> str:
    return f"""---
id: {adr_id}
title: Synthetic {adr_id}
status: accepted
owner: architect
supersedes: null
superseded_by: null
created: 2026-01-01
updated: 2026-01-02
---

# {adr_id}: Synthetic

## Context

x

## Decision

x

## When you may deviate

x

## What you must record when you deviate

x

## Consequences

x

## Alternatives considered

x

## Changelog

x
"""


def _build_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    for name in _COPY_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / name, tmp_path / "scripts" / name)
    specs = tmp_path / "specs"
    specs.mkdir(exist_ok=True)
    for rel, content in files.items():
        target = specs / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script), *args],
        capture_output=True,
        text=True,
    )


def _lint_stderr(proc: subprocess.CompletedProcess) -> str:
    keep = [
        l
        for l in proc.stderr.splitlines()
        if not l.startswith("WARN: spec_footprint:") and not l.startswith("INFO:")
    ]
    return "\n".join(keep)


def _warning_lines(proc: subprocess.CompletedProcess) -> list[str]:
    return [l for l in proc.stderr.splitlines() if l.startswith("  - ")]


def _index_text(repo: Path) -> str:
    return (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")


def _section_lines(index_text: str, heading: str) -> list[str]:
    lines = index_text.splitlines()
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return []
    out: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            out.append(line)
    return out


def _point_module_at(monkeypatch, repo: Path) -> None:
    """Make the in-process module's `collect_*()` discover `repo/specs`."""
    monkeypatch.setattr(index_specs, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(index_specs, "DECISIONS_DIR", repo / "specs" / "decisions")


# The canonical happy-path tree from FR-0004 Notes: one FR, one TR
# operationalising it, two DECs revising the TR (the second breaking), one
# ADR authorising them. Fully consistent — zero warnings expected.
def _happy_tree() -> dict[str, str]:
    return {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "TR-0001-approach.md": _tr_markdown(
            "TR-0001",
            version=3,
            lifecycle="live",
            revisions="[DEC-0001, DEC-0002]",
            last_breaking_revision=3,
            implemented_by='["src/api/x.py", "src/svc/*"]',
            success_criteria="[SC-100-1]",
            tests='["tests/unit/test_x.py"]',
        ),
        "decisions/DEC-0001-first.md": _dec_markdown(
            "DEC-0001", revises="TR-0001", authorised_by="[ADR-0001]"
        ),
        "decisions/DEC-0002-second.md": _dec_markdown(
            "DEC-0002",
            revises="TR-0001",
            breaking="true",
            authorised_by="[ADR-0001]",
            reversibility="low",
            client_visible="true",
            alternatives='["keep the old shape"]',
        ),
        "decisions/ADR-0001-rule.md": _adr_markdown("ADR-0001"),
    }


def _assert_hard_error(repo: Path, filename: str, field_name: str, *needles: str) -> None:
    """`--validate` exits 1, names the file and field on stderr, writes nothing."""
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1, proc.stderr
    assert "Spec validation FAILED" in proc.stderr
    assert filename in proc.stderr and field_name in proc.stderr, proc.stderr
    for needle in needles:
        assert needle in proc.stderr, proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()


# ---------------------------------------------------------------------------
# AC-10: dataclasses, collect_*, collect_graph, liveness predicates
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0004:AC-10
def test_dec_and_tr_dataclasses_expose_exactly_the_frontmatter_keys_plus_path():
    dec_names = {f.name for f in dataclasses.fields(index_specs.DEC)}
    tr_names = {f.name for f in dataclasses.fields(index_specs.TR)}
    assert dec_names == set(DEC_FIELDS) | {"path"}
    assert tr_names == set(TR_FIELDS) | {"path"}


# covers hub-tooling FR-0004:AC-10
def test_dec_and_tr_defaults_match_field_tables_and_are_not_shared():
    def dec(dec_id: str):
        return index_specs.DEC(
            path=Path(f"{dec_id}-x.md"), id=dec_id, title="t", tier="agent",
            status="proposed", rationale="r", created="2026-01-01", updated="2026-01-01",
        )

    def tr(tr_id: str):
        return index_specs.TR(
            path=Path(f"{tr_id}-x.md"), id=tr_id, title="t", operationalises=["FR-0100"],
            created="2026-01-01", updated="2026-01-01",
        )

    d = dec("DEC-0001")
    for name, expected in DEC_DEFAULTS.items():
        assert getattr(d, name) == expected, name
    t = tr("TR-0001")
    for name, expected in TR_DEFAULTS.items():
        assert getattr(t, name) == expected, name
    d.authorised_by.append("ADR-0001")
    t.revisions.append("DEC-0001")
    assert dec("DEC-0002").authorised_by == [] and tr("TR-0002").revisions == []


# covers hub-tooling FR-0004:AC-10
@pytest.mark.parametrize(
    "status,expected",
    [("proposed", True), ("ratified", True), ("rejected", False), ("superseded", False)],
)
def test_is_live_dec_liveness_table_on_parsed_fixtures(tmp_path, status, expected):
    """FR-0004 liveness table (normative for FR-0005): DEC live iff status in
    {proposed, ratified}. Checked on a parsed DEC, not a hand-built one."""
    extra: dict[str, object] = {}
    if status == "superseded":
        extra["superseded_by"] = "DEC-0002"
    repo = _build_repo(
        tmp_path, {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status=status, **extra)}
    )
    dec, errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-a.md")
    assert errors == [] and dec.status == status
    assert index_specs.is_live_dec(dec) is expected
    assert index_specs.is_live_dec(SimpleNamespace(status=status)) is expected  # duck-typed


# covers hub-tooling FR-0004:AC-10
@pytest.mark.parametrize(
    "lifecycle,expected", [("draft", False), ("live", True), ("superseded", False)]
)
def test_is_live_applies_to_parsed_trs(tmp_path, lifecycle, expected):
    """The other half of the liveness table: FR/TR live iff lifecycle == live
    (FR-0003's `is_live`, now exercised on a TR)."""
    repo = _build_repo(tmp_path, {"TR-0001-a.md": _tr_markdown("TR-0001", lifecycle=lifecycle)})
    tr, errors = index_specs.parse_tr(repo / "specs" / "TR-0001-a.md")
    assert errors == [] and tr.lifecycle == lifecycle
    assert index_specs.is_live(tr) is expected


# covers hub-tooling FR-0004:AC-10
def test_is_live_dec_is_strict_about_case_and_unknown_values():
    assert index_specs.is_live_dec(SimpleNamespace(status="Ratified")) is False
    assert index_specs.is_live_dec(SimpleNamespace(status="accepted")) is False
    assert index_specs.is_live_dec(SimpleNamespace(status=None)) is False


# covers hub-tooling FR-0004:AC-10
def test_collect_functions_mirror_collect_frs_and_collect_graph_merges_everything(
    tmp_path, monkeypatch
):
    repo = _build_repo(tmp_path, _happy_tree())
    _point_module_at(monkeypatch, repo)

    trs, tr_errors = index_specs.collect_trs()
    decs, dec_errors = index_specs.collect_decs()
    assert tr_errors == [] and dec_errors == []
    assert [t.id for t in trs] == ["TR-0001"]
    assert [d.id for d in decs] == ["DEC-0001", "DEC-0002"]
    assert all(isinstance(t, index_specs.TR) for t in trs)
    assert all(isinstance(d, index_specs.DEC) for d in decs)
    assert trs[0].path == repo / "specs" / "TR-0001-approach.md"
    assert decs[1].path == repo / "specs" / "decisions" / "DEC-0002-second.md"

    graph = index_specs.collect_graph()
    for attr in ("frs", "trs", "decs", "adrs", "errors"):
        assert hasattr(graph, attr), attr
    assert [f.id for f in graph.frs] == ["FR-0100"]
    assert [t.id for t in graph.trs] == ["TR-0001"]
    assert [d.id for d in graph.decs] == ["DEC-0001", "DEC-0002"]
    assert [a.id for a in graph.adrs] == ["ADR-0001"]
    assert graph.errors == []

    # Parsed values round-trip under their frontmatter names.
    tr = graph.trs[0]
    assert (tr.version, tr.lifecycle, tr.revisions, tr.last_breaking_revision) == (
        3, "live", ["DEC-0001", "DEC-0002"], 3
    )
    assert tr.implemented_by == ["src/api/x.py", "src/svc/*"]
    assert tr.success_criteria == ["SC-100-1"] and tr.tests == ["tests/unit/test_x.py"]
    d2 = graph.decs[1]
    assert (d2.tier, d2.status, d2.revises, d2.breaking) == ("agent", "ratified", "TR-0001", True)
    assert d2.authorised_by == ["ADR-0001"] and d2.reversibility == "low"
    assert d2.client_visible is True and d2.alternatives == ["keep the old shape"]
    assert d2.rationale == "Synthetic decision DEC-0002."
    assert (d2.created, d2.updated) == ("2026-01-01", "2026-01-03")


# covers hub-tooling FR-0004:AC-10
def test_collect_graph_errors_merge_parse_graph_and_reference_errors(tmp_path, monkeypatch):
    """One FR parse error, one FR graph error, one TR shape error and one DEC
    resolution error must all land in `graph.errors`."""
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100").replace("depends_on: []", "depends_on: [FR-9999]"),
        "FR-0101-b.md": _fr_markdown("FR-0101", status="bogus"),
        "TR-0001-a.md": _tr_markdown("TR-0001", version=0),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", constrained_by="[FR-9998]"),
    }
    repo = _build_repo(tmp_path, files)
    _point_module_at(monkeypatch, repo)
    graph = index_specs.collect_graph()
    joined = "\n".join(graph.errors)
    assert "FR-0101-b.md: status 'bogus'" in joined
    assert "FR-0100-a.md: depends_on references unknown FR 'FR-9999'" in joined
    assert "TR-0001-a.md: version must be an integer >= 1" in joined
    assert "DEC-0001-a.md: constrained_by references unknown FR 'FR-9998'" in joined
    assert graph.frs and graph.decs and graph.trs == []  # the malformed TR is dropped


# covers hub-tooling FR-0004:AC-10
def test_collect_trs_and_decs_return_empty_tuples_when_dirs_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(index_specs, "SPECS_DIR", tmp_path / "nope")
    monkeypatch.setattr(index_specs, "DECISIONS_DIR", tmp_path / "nope" / "decisions")
    assert index_specs.collect_trs() == ([], [])
    assert index_specs.collect_decs() == ([], [])


# ---------------------------------------------------------------------------
# AC-1: templates
# ---------------------------------------------------------------------------


def _top_level_line(frontmatter: str, key: str) -> str:
    hits = [l for l in frontmatter.splitlines() if l.startswith(f"{key}:")]
    assert len(hits) == 1, f"{key} must appear exactly once at top level"
    return hits[0]


# covers hub-tooling FR-0004:AC-1
def test_dec_template_lists_every_field_with_type_values_default_comment():
    assert _DEC_TEMPLATE.is_file()
    text = _DEC_TEMPLATE.read_text(encoding="utf-8")
    frontmatter = index_specs.FRONTMATTER_PATTERN.match(text).group(1)
    for key in DEC_FIELDS:
        line = _top_level_line(frontmatter, key)
        assert "#" in line, f"{key} needs an inline comment"
        comment = line.split("#", 1)[1].lower()
        assert "default" in comment or "required" in comment, f"{key}: comment must state default or required"
    for key, prefix in DEC_TEMPLATE_PREFILL.items():
        assert _top_level_line(frontmatter, key).startswith(prefix), key
    # Allowed values are named in the comments.
    assert "proposed | ratified | rejected | superseded" in _top_level_line(frontmatter, "status")
    assert "high | medium | low" in _top_level_line(frontmatter, "reversibility")
    assert "GOAL-" in _top_level_line(frontmatter, "satisfies")
    assert "ADR-NNNN" in _top_level_line(frontmatter, "authorised_by")
    assert "@" in _top_level_line(frontmatter, "revises")  # the no-version-citation rule
    # Required fields carry placeholders, not values.
    assert _top_level_line(frontmatter, "id").startswith("id: DEC-XXXX")
    assert "YYYY-MM-DD" in _top_level_line(frontmatter, "created")
    assert "YYYY-MM-DD" in _top_level_line(frontmatter, "updated")
    for heading in ("## Context", "## Alternatives considered", "## Cascade", "## Changelog"):
        assert heading in text, heading


# covers hub-tooling FR-0004:AC-1
def test_tr_template_lists_every_field_and_prefills_lifecycle_draft():
    assert _TR_TEMPLATE.is_file()
    text = _TR_TEMPLATE.read_text(encoding="utf-8")
    frontmatter = index_specs.FRONTMATTER_PATTERN.match(text).group(1)
    for key in TR_FIELDS:
        line = _top_level_line(frontmatter, key)
        assert "#" in line, f"{key} needs an inline comment"
        comment = line.split("#", 1)[1].lower()
        assert "default" in comment or "required" in comment, f"{key}: comment must state default or required"
    for key, prefix in TR_TEMPLATE_PREFILL.items():
        assert _top_level_line(frontmatter, key).startswith(prefix), key
    assert _top_level_line(frontmatter, "lifecycle").startswith("lifecycle: draft")
    assert "draft | live | superseded" in _top_level_line(frontmatter, "lifecycle")
    assert "DEC-NNNN" in _top_level_line(frontmatter, "revisions")
    assert "@" in _top_level_line(frontmatter, "implemented_by")
    assert _top_level_line(frontmatter, "id").startswith("id: TR-XXXX")
    assert "FR-XXXX" in _top_level_line(frontmatter, "operationalises")
    for heading in ("## Approach", "## Decisions", "## Components", "## Open questions", "## Changelog"):
        assert heading in text, heading


def _filled_templates() -> dict[str, str]:
    """Both templates with placeholders replaced by valid values: the TR points
    at FR-0100 and lists DEC-0001 (so `version` is bumped to 2); the DEC
    revises TR-0001, non-breaking."""
    dec = (
        _DEC_TEMPLATE.read_text(encoding="utf-8")
        .replace("DEC-XXXX", "DEC-0001")
        .replace("YYYY-MM-DD", "2026-01-01")
        .replace("<one-line title — the choice made, not the topic>", "Use the platform queue")
        .replace("tier: <tier>", "tier: agent")
        .replace("revises: null", "revises: TR-0001")
        .replace(
            "  <why this choice, in prose that stands on its own>",
            "  The platform queue already meets the latency budget; a custom one would not.",
        )
    )
    tr = (
        _TR_TEMPLATE.read_text(encoding="utf-8")
        .replace("TR-XXXX", "TR-0001")
        .replace("FR-XXXX", "FR-0100")
        .replace("YYYY-MM-DD", "2026-01-01")
        .replace("<one-line title — the approach, not the need>", "Queue-backed ingestion")
        .replace("version: 1", "version: 2")
        .replace("revisions: []", "revisions: [DEC-0001]")
    )
    fr = (
        _FR_TEMPLATE.read_text(encoding="utf-8")
        .replace("FR-XXXX", "FR-0100")
        .replace("YYYY-MM-DD", "2026-01-01")
    )
    return {
        "FR-0100-filled.md": fr,
        "TR-0001-filled.md": tr,
        "decisions/DEC-0001-filled.md": dec,
    }


# covers hub-tooling FR-0004:AC-1
def test_filled_templates_validate_with_exit_0_and_no_warnings(tmp_path):
    repo = _build_repo(tmp_path, _filled_templates())

    tr, tr_errors = index_specs.parse_tr(repo / "specs" / "TR-0001-filled.md")
    assert tr_errors == []
    assert tr.lifecycle == "draft" and tr.version == 2 and tr.revisions == ["DEC-0001"]
    assert tr.operationalises == ["FR-0100"]
    for name in ("last_breaking_revision", "supersedes", "superseded_by"):
        assert getattr(tr, name) is None, name
    for name in ("implemented_by", "success_criteria", "tests"):
        assert getattr(tr, name) == [], name

    dec, dec_errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-filled.md")
    assert dec_errors == []
    assert dec.status == "proposed" and dec.tier == "agent" and dec.revises == "TR-0001"
    assert dec.breaking is False and dec.client_visible is False
    assert dec.rationale.startswith("The platform queue")
    for name in ("satisfies", "constrained_by", "authorised_by", "alternatives"):
        assert getattr(dec, name) == [], name
    for name in ("invokes_exception", "reversibility", "provisional_until", "supersedes", "superseded_by"):
        assert getattr(dec, name) is None, name

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "Spec graph OK (1 FRs, 1 TRs, 1 DECs)" in proc.stdout

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    text = _index_text(repo)
    assert "## Versioning warnings" not in text
    assert "## Technical requirements" in text and "## Decisions" in text


# covers hub-tooling FR-0004:AC-1
def test_unfilled_templates_are_rejected_not_silently_indexed(tmp_path):
    """Adversarial: copying a template without editing it must fail (placeholder
    id, placeholder dates), never validate."""
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown("FR-0100"),
            "TR-0001-raw.md": _TR_TEMPLATE.read_text(encoding="utf-8"),
            "decisions/DEC-0001-raw.md": _DEC_TEMPLATE.read_text(encoding="utf-8"),
        },
    )
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert "TR-0001-raw.md: id 'TR-XXXX'" in proc.stderr
    assert "DEC-0001-raw.md: id 'DEC-XXXX'" in proc.stderr


# ---------------------------------------------------------------------------
# AC-2: discovery and identity
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0004:AC-2
def test_discovery_paths_adrs_not_decs_frs_not_trs_readmes_ignored(tmp_path, monkeypatch):
    files = {
        **_happy_tree(),
        "README.md": "# Specs\n",
        "decisions/README.md": "# Decisions\n",
        "_template/TR-XXXX-template.md": _TR_TEMPLATE.read_text(encoding="utf-8"),
        "_template/DEC-XXXX-template.md": _DEC_TEMPLATE.read_text(encoding="utf-8"),
    }
    repo = _build_repo(tmp_path, files)
    _point_module_at(monkeypatch, repo)
    graph = index_specs.collect_graph()
    assert graph.errors == []
    assert [d.id for d in graph.decs] == ["DEC-0001", "DEC-0002"]  # ADR-0001 not a DEC
    assert [t.id for t in graph.trs] == ["TR-0001"]  # FR-0100 not a TR; templates ignored
    assert [a.id for a in graph.adrs] == ["ADR-0001"]  # DECs not ADRs
    assert [f.id for f in graph.frs] == ["FR-0100"]


# covers hub-tooling FR-0004:AC-2
@pytest.mark.parametrize(
    "filename,content,needle",
    [
        pytest.param("TR-1-a.md", _tr_markdown("TR-0001"), "TR-1-a.md: filename does not match TR-XXXX-<slug>.md", id="tr-short-number"),
        pytest.param("TR-0001.md", _tr_markdown("TR-0001"), "TR-0001.md: filename does not match TR-XXXX-<slug>.md", id="tr-no-slug"),
        pytest.param("decisions/DEC-01-a.md", _dec_markdown("DEC-0001"), "DEC-01-a.md: filename does not match DEC-XXXX-<slug>.md", id="dec-short-number"),
        pytest.param("decisions/DEC-0001.md", _dec_markdown("DEC-0001"), "DEC-0001.md: filename does not match DEC-XXXX-<slug>.md", id="dec-no-slug"),
        pytest.param("TR-0001-a.md", _tr_markdown("TR-0002"), "TR-0001-a.md: id 'TR-0002' does not match filename prefix 'TR-0001'", id="tr-id-prefix-mismatch"),
        pytest.param("decisions/DEC-0001-a.md", _dec_markdown("DEC-0002"), "DEC-0001-a.md: id 'DEC-0002' does not match filename prefix 'DEC-0001'", id="dec-id-prefix-mismatch"),
        pytest.param("TR-0001-a.md", _tr_markdown("TR-01"), "TR-0001-a.md: id 'TR-01' must match TR-XXXX", id="tr-id-malformed"),
        pytest.param("decisions/DEC-0001-a.md", _dec_markdown("FR-0001"), "DEC-0001-a.md: id 'FR-0001' must match DEC-XXXX", id="dec-id-wrong-kind"),
    ],
)
def test_filename_and_id_identity_errors(tmp_path, filename, content, needle):
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100"), filename: content})
    _assert_hard_error(repo, Path(filename).name, "id" if "id" in needle else "filename", needle)


# covers hub-tooling FR-0004:AC-2
def test_duplicate_tr_and_dec_ids_across_files_are_errors_naming_both_files(tmp_path):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "TR-0001-a.md": _tr_markdown("TR-0001"),
        "TR-0001-b.md": _tr_markdown("TR-0001"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001"),
        "decisions/DEC-0001-b.md": _dec_markdown("DEC-0001"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert "duplicate TR id TR-0001 in TR-0001-b.md and TR-0001-a.md" in proc.stderr
    assert "duplicate DEC id DEC-0001 in DEC-0001-b.md and DEC-0001-a.md" in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0004:AC-2
@pytest.mark.parametrize("field_name", ["id", "title", "tier", "status", "rationale", "created", "updated"])
def test_dec_missing_required_field_is_error_naming_file_and_field(tmp_path, field_name):
    content = _dec_markdown("DEC-0001", **{field_name: OMIT})
    repo = _build_repo(tmp_path, {"decisions/DEC-0001-a.md": content})
    dec, errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-a.md")
    assert dec is None
    assert any("DEC-0001-a.md" in e and field_name in e for e in errors), errors
    _assert_hard_error(repo, "DEC-0001-a.md", field_name)


# covers hub-tooling FR-0004:AC-2
@pytest.mark.parametrize("field_name", ["id", "title", "operationalises", "created", "updated"])
def test_tr_missing_required_field_is_error_naming_file_and_field(tmp_path, field_name):
    content = _tr_markdown("TR-0001", **{field_name: OMIT})
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100"), "TR-0001-a.md": content})
    tr, errors = index_specs.parse_tr(repo / "specs" / "TR-0001-a.md")
    assert tr is None
    assert any("TR-0001-a.md" in e and field_name in e for e in errors), errors
    _assert_hard_error(repo, "TR-0001-a.md", field_name)


# covers hub-tooling FR-0004:AC-2
@pytest.mark.parametrize(
    "filename,content,needle",
    [
        pytest.param("TR-0001-a.md", "# no frontmatter\n", "TR-0001-a.md: missing YAML frontmatter", id="tr-no-frontmatter"),
        pytest.param("decisions/DEC-0001-a.md", "---\nid: [unclosed\n---\n", "DEC-0001-a.md: invalid YAML frontmatter", id="dec-bad-yaml"),
    ],
)
def test_missing_or_invalid_frontmatter_is_a_hard_error_for_trs_and_decs(tmp_path, filename, content, needle):
    """Unlike ADRs (warn-only), TRs and DECs are validated hard."""
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100"), filename: content})
    _assert_hard_error(repo, Path(filename).name, "frontmatter", needle)


# ---------------------------------------------------------------------------
# AC-3: shape and enum validation
# ---------------------------------------------------------------------------


DEC_SHAPE_CASES = [
    # (overrides, field named in the error)
    pytest.param({"status": "accepted"}, "status", id="status-enum"),
    pytest.param({"revises": "TR-0001", "breaking": '"no"'}, "breaking", id="breaking-string"),
    pytest.param({"revises": "TR-0001", "breaking": '"true"'}, "breaking", id="breaking-string-truthy"),
    pytest.param({"revises": "TR-0001", "breaking": OMIT}, "breaking", id="breaking-absent-with-revises"),
    pytest.param({"revises": "TR-0001", "breaking": "null"}, "breaking", id="breaking-null-with-revises"),
    pytest.param({"revises": "TR-0001", "breaking": "1"}, "breaking", id="breaking-int"),
    pytest.param({"client_visible": "1"}, "client_visible", id="client-visible-int"),
    pytest.param({"client_visible": '"yes"'}, "client_visible", id="client-visible-string"),
    pytest.param({"reversibility": "partial"}, "reversibility", id="reversibility-enum"),
    pytest.param({"revises": "TR-0001@v2"}, "revises", id="revises-tr-version-citation"),
    pytest.param({"revises": "FR-0100@v3"}, "revises", id="revises-fr-version-citation"),
    pytest.param({"revises": "DEC-0002"}, "revises", id="revises-dec-id"),
    pytest.param({"revises": "[TR-0001]"}, "revises", id="revises-list"),
    pytest.param({"revises": '""'}, "revises", id="revises-empty"),
    pytest.param({"authorised_by": "[ADR-1]"}, "authorised_by", id="authorised-by-short-id"),
    pytest.param({"authorised_by": "ADR-0001"}, "authorised_by", id="authorised-by-not-list"),
    pytest.param({"satisfies": "[G-3]"}, "satisfies", id="satisfies-pattern"),
    pytest.param({"rationale": '""'}, "rationale", id="rationale-empty"),
    pytest.param({"rationale": '"   "'}, "rationale", id="rationale-whitespace"),
    pytest.param({"rationale": "null"}, "rationale", id="rationale-null"),
    pytest.param({"tier": '""'}, "tier", id="tier-empty"),
    pytest.param({"tier": "3"}, "tier", id="tier-int"),
    pytest.param({"title": '""'}, "title", id="title-empty"),
    pytest.param({"constrained_by": "FR-0100"}, "constrained_by", id="constrained-by-not-list"),
    pytest.param({"constrained_by": "[TR-0001]"}, "constrained_by", id="constrained-by-wrong-kind"),
    pytest.param({"supersedes": "TR-0001"}, "supersedes", id="supersedes-wrong-kind"),
    pytest.param({"superseded_by": '""'}, "superseded_by", id="superseded-by-empty"),
    pytest.param({"alternatives": '[""]'}, "alternatives", id="alternatives-empty-string"),
    pytest.param({"alternatives": "x"}, "alternatives", id="alternatives-not-list"),
    pytest.param({"invokes_exception": "3"}, "invokes_exception", id="invokes-exception-int"),
    pytest.param({"provisional_until": "[]"}, "provisional_until", id="provisional-until-list"),
    pytest.param({"created": "null"}, "created", id="created-null"),
]


# covers hub-tooling FR-0004:AC-3
@pytest.mark.parametrize("overrides,field_name", DEC_SHAPE_CASES)
def test_dec_shape_error_names_file_and_field(tmp_path, overrides, field_name):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "TR-0001-a.md": _tr_markdown("TR-0001"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", **overrides),
    }
    repo = _build_repo(tmp_path, files)
    dec, errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-a.md")
    assert dec is None, "shape errors must yield no DEC object"
    assert any("DEC-0001-a.md" in e and field_name in e for e in errors), errors
    _assert_hard_error(repo, "DEC-0001-a.md", field_name)


# covers hub-tooling FR-0004:AC-3
@pytest.mark.parametrize(
    "revises_value",
    ["TR-0001@v2", "FR-0100@v3", "TR-0001@2", "TR-0001@"],
)
def test_revises_rejects_every_at_sign_form_with_stable_id_hint(tmp_path, revises_value):
    repo = _build_repo(
        tmp_path,
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises=revises_value)},
    )
    _, errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-a.md")
    assert any("revises" in e and "@" in e and "stable ID" in e for e in errors), errors


TR_SHAPE_CASES = [
    pytest.param({"operationalises": "[]"}, "operationalises", id="operationalises-empty"),
    pytest.param({"operationalises": "FR-0100"}, "operationalises", id="operationalises-not-list"),
    pytest.param({"operationalises": "[FR-1]"}, "operationalises", id="operationalises-short-id"),
    pytest.param({"operationalises": "[FR-0100@v1]"}, "operationalises", id="operationalises-version-citation"),
    pytest.param({"operationalises": "null"}, "operationalises", id="operationalises-null"),
    pytest.param({"implemented_by": '["src/x.py@2"]'}, "implemented_by", id="implemented-by-version-citation"),
    pytest.param({"implemented_by": "src/x.py"}, "implemented_by", id="implemented-by-not-list"),
    pytest.param({"implemented_by": '[""]'}, "implemented_by", id="implemented-by-empty-string"),
    pytest.param({"tests": '[""]'}, "tests", id="tests-empty-string"),
    pytest.param({"tests": '["tests/x.py@3"]'}, "tests", id="tests-version-citation"),
    pytest.param({"success_criteria": '[""]'}, "success_criteria", id="sc-empty-string"),
    pytest.param({"title": '""'}, "title", id="title-empty"),
    pytest.param({"created": "null"}, "created", id="created-null"),
    # Every shared-block case from FR-0003:AC-3, applied to a TR.
    pytest.param({"version": "0"}, "version", id="version-zero"),
    pytest.param({"version": '"2"'}, "version", id="version-string"),
    pytest.param({"version": "1.5"}, "version", id="version-float"),
    pytest.param({"version": "true"}, "version", id="version-bool"),
    pytest.param({"lifecycle": "retired"}, "lifecycle", id="lifecycle-enum"),
    pytest.param({"revisions": "DEC-0001"}, "revisions", id="revisions-not-list"),
    pytest.param({"revisions": "[DEC-1]"}, "revisions", id="revisions-short-id"),
    pytest.param({"revisions": "[FR-0100]"}, "revisions", id="revisions-fr-id"),
    pytest.param({"last_breaking_revision": "0"}, "last_breaking_revision", id="lbr-zero"),
    pytest.param({"last_breaking_revision": '"1"'}, "last_breaking_revision", id="lbr-string"),
    pytest.param({"supersedes": "42"}, "supersedes", id="supersedes-int"),
    pytest.param({"superseded_by": '""'}, "superseded_by", id="superseded-by-empty"),
]


# covers hub-tooling FR-0004:AC-3
@pytest.mark.parametrize("overrides,field_name", TR_SHAPE_CASES)
def test_tr_shape_error_names_file_and_field(tmp_path, overrides, field_name):
    files = {"FR-0100-a.md": _fr_markdown("FR-0100"), "TR-0001-a.md": _tr_markdown("TR-0001", **overrides)}
    repo = _build_repo(tmp_path, files)
    tr, errors = index_specs.parse_tr(repo / "specs" / "TR-0001-a.md")
    assert tr is None, "shape errors must yield no TR object"
    assert any("TR-0001-a.md" in e and field_name in e for e in errors), errors
    _assert_hard_error(repo, "TR-0001-a.md", field_name)


# covers hub-tooling FR-0004:AC-3
def test_dec_breaking_explicit_null_is_absent_when_revises_is_null(tmp_path):
    """`breaking: null` on a creating DEC (`revises: null`) is the template's
    pre-filled shape and must parse cleanly to `breaking == False`. The
    `revises`-set guard treats an explicit null as absent (see the
    `breaking-null-with-revises` shape case); this pins the other half so the
    guard cannot regress into rejecting every pre-filled creating DEC."""
    content = _dec_markdown("DEC-0001", revises="null", breaking="null")
    repo = _build_repo(tmp_path, {"decisions/DEC-0001-a.md": content})
    dec, errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-a.md")
    assert errors == []
    assert dec is not None and dec.revises is None and dec.breaking is False
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "breaking" not in proc.stderr


# covers hub-tooling FR-0004:AC-3
def test_dec_optional_fields_accept_explicit_null_and_yaml_dates(tmp_path):
    """Explicit `null` on every optional DEC field behaves as absent (the
    template pre-fills null); `breaking` may be absent when `revises` is null;
    a bare YAML date in `provisional_until` is stringified, not rejected."""
    content = _dec_markdown(
        "DEC-0001",
        revises="null",
        breaking=OMIT,
        satisfies="null",
        constrained_by="null",
        authorised_by="null",
        invokes_exception="null",
        alternatives="null",
        reversibility="null",
        provisional_until="2026-10-01",
        client_visible="null",
        supersedes="null",
        superseded_by="null",
    )
    repo = _build_repo(tmp_path, {"decisions/DEC-0001-a.md": content})
    dec, errors = index_specs.parse_dec(repo / "specs" / "decisions" / "DEC-0001-a.md")
    assert errors == []
    for name, expected in DEC_DEFAULTS.items():
        if name == "provisional_until":
            continue
        assert getattr(dec, name) == expected, name
    assert dec.provisional_until == "2026-10-01"
    assert dec.created == "2026-01-01" and dec.updated == "2026-01-03"


# covers hub-tooling FR-0004:AC-3
def test_tr_optional_fields_accept_explicit_null(tmp_path):
    content = _tr_markdown(
        "TR-0001",
        **{k: "null" for k in TR_DEFAULTS},
    )
    repo = _build_repo(tmp_path, {"TR-0001-a.md": content})
    tr, errors = index_specs.parse_tr(repo / "specs" / "TR-0001-a.md")
    assert errors == []
    for name, expected in TR_DEFAULTS.items():
        assert getattr(tr, name) == expected, name


# ---------------------------------------------------------------------------
# AC-4: reference resolution
# ---------------------------------------------------------------------------


RESOLUTION_CASES = [
    # (extra files, file named, expected error line)
    pytest.param(
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", constrained_by="[FR-0100, FR-9999]")},
        "DEC-0001-a.md: constrained_by references unknown FR 'FR-9999'",
        id="dec-constrained-by",
    ),
    pytest.param(
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="FR-9999")},
        "DEC-0001-a.md: revises references unknown FR 'FR-9999'",
        id="dec-revises-fr",
    ),
    pytest.param(
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="TR-9999")},
        "DEC-0001-a.md: revises references unknown TR 'TR-9999'",
        id="dec-revises-tr",
    ),
    pytest.param(
        # Adversarial: FR-0100 exists, TR-0100 does not — kinds are not conflated.
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="TR-0100")},
        "DEC-0001-a.md: revises references unknown TR 'TR-0100'",
        id="dec-revises-kind-confusion",
    ),
    pytest.param(
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", supersedes="DEC-9999")},
        "DEC-0001-a.md: supersedes references unknown DEC 'DEC-9999'",
        id="dec-supersedes",
    ),
    pytest.param(
        {"decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="superseded", superseded_by="DEC-9999")},
        "DEC-0001-a.md: superseded_by references unknown DEC 'DEC-9999'",
        id="dec-superseded-by",
    ),
    pytest.param(
        {"TR-0002-b.md": _tr_markdown("TR-0002", operationalises="[FR-0100, FR-9999]")},
        "TR-0002-b.md: operationalises references unknown FR 'FR-9999'",
        id="tr-operationalises",
    ),
    pytest.param(
        {"TR-0002-b.md": _tr_markdown("TR-0002", supersedes="TR-9999")},
        "TR-0002-b.md: supersedes references unknown TR 'TR-9999'",
        id="tr-supersedes",
    ),
    pytest.param(
        {"TR-0002-b.md": _tr_markdown("TR-0002", lifecycle="superseded", superseded_by="TR-9999")},
        "TR-0002-b.md: superseded_by references unknown TR 'TR-9999'",
        id="tr-superseded-by",
    ),
    pytest.param(
        # Adversarial: an FR ID in a TR-typed link is unresolvable, not coerced.
        {"TR-0002-b.md": _tr_markdown("TR-0002", supersedes="FR-0100")},
        "TR-0002-b.md: supersedes references unknown TR 'FR-0100'",
        id="tr-supersedes-kind-confusion",
    ),
    pytest.param(
        {"TR-0002-b.md": _tr_markdown("TR-0002", version=2, revisions="[DEC-0042]")},
        "TR-0002-b.md: revisions references unknown DEC 'DEC-0042'",
        id="tr-revisions-deferred-case",
    ),
    pytest.param(
        {"FR-0101-b.md": _fr_markdown("FR-0101", extra_frontmatter="version: 2\nrevisions: [DEC-0042]")},
        "FR-0101-b.md: revisions references unknown DEC 'DEC-0042'",
        id="fr-revisions-deferred-case",
    ),
]


# covers hub-tooling FR-0004:AC-4
@pytest.mark.parametrize("extra_files,expected_line", RESOLUTION_CASES)
def test_unresolvable_reference_is_error_naming_field_and_id(tmp_path, extra_files, expected_line):
    files = {"FR-0100-a.md": _fr_markdown("FR-0100"), "TR-0001-a.md": _tr_markdown("TR-0001"), **extra_files}
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1, proc.stderr
    assert expected_line in proc.stderr, proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()
    # Plain mode fails the same way and writes nothing either.
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 1
    assert expected_line in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0004:AC-4
def test_revises_resolves_fr_against_frs_and_tr_against_trs(tmp_path):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter="version: 2\nrevisions: [DEC-0001]"),
        "TR-0001-a.md": _tr_markdown("TR-0001", version=2, revisions="[DEC-0002]"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="FR-0100"),
        "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", revises="TR-0001"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


# covers hub-tooling FR-0004:AC-4
def test_validate_references_reports_only_the_unknown_entries():
    """Pure API check: mixed resolved / unknown lists report the unknown only,
    and resolution is scoped to the objects passed in."""
    fr = index_specs.FR(
        path=Path("FR-0100-a.md"), id="FR-0100", title="t", status="ready", owner="a",
        depends_on=[], tags=[], derived_from=None, pattern=None, created="d", updated="d",
        owns=(), reads=(), revisions=["DEC-0001", "DEC-0009"], version=3,
    )
    tr = index_specs.TR(
        path=Path("TR-0001-a.md"), id="TR-0001", title="t", operationalises=["FR-0100", "FR-0200"],
        created="d", updated="d",
    )
    dec = index_specs.DEC(
        path=Path("DEC-0001-a.md"), id="DEC-0001", title="t", tier="agent", status="ratified",
        rationale="r", created="d", updated="d", revises="FR-0100", constrained_by=["FR-0100", "FR-0300"],
    )
    errors = index_specs.validate_references([fr], [tr], [dec])
    assert errors == [
        "TR-0001-a.md: operationalises references unknown FR 'FR-0200'",
        "DEC-0001-a.md: constrained_by references unknown FR 'FR-0300'",
        "FR-0100-a.md: revisions references unknown DEC 'DEC-0009'",
    ]


# covers hub-tooling FR-0004:AC-4
def test_authorised_by_unknown_adr_is_a_warning_not_an_error(tmp_path):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", authorised_by="[ADR-0099]"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "Spec graph OK" in proc.stdout
    lines = _warning_lines(proc)
    assert lines == ["  - DEC-0001: authorised_by references unknown ADR 'ADR-0099'"], proc.stderr
    assert "Versioning warnings (1):" in proc.stderr

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0
    bullets = _section_lines(_index_text(repo), "Versioning warnings")
    assert bullets == ["- DEC-0001: authorised_by references unknown ADR 'ADR-0099'"]


# covers hub-tooling FR-0004:AC-4
def test_authorised_by_resolves_against_discovered_adr_files(tmp_path):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "decisions/ADR-0099-x.md": _adr_markdown("ADR-0099"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", authorised_by="[ADR-0099]"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


# ---------------------------------------------------------------------------
# AC-5: warn-only cross-checks
# ---------------------------------------------------------------------------


def _warn_cases():
    base = {"FR-0100-a.md": _fr_markdown("FR-0100")}
    return [
        pytest.param(
            {
                **base,
                # (i) TR-0001 claims DEC-0001, but DEC-0001 revised TR-0002
                # (which lists it correctly, so the forward check is silent).
                "TR-0001-a.md": _tr_markdown("TR-0001", version=2, revisions="[DEC-0001]"),
                "TR-0002-b.md": _tr_markdown("TR-0002", version=2, revisions="[DEC-0001]"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="TR-0002"),
            },
            "TR-0001",
            "revisions lists DEC-0001 but DEC-0001.revises is 'TR-0002'",
            id="i-backward-reciprocity",
        ),
        pytest.param(
            {
                **base,
                "TR-0001-a.md": _tr_markdown("TR-0001"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="proposed", revises="TR-0001"),
            },
            "DEC-0001",
            "revises TR-0001 (status 'proposed') but TR-0001.revisions does not list DEC-0001",
            id="ii-forward-reciprocity-proposed",
        ),
        pytest.param(
            {
                **base,
                "TR-0001-a.md": _tr_markdown("TR-0001", version=3, revisions="[DEC-0001, DEC-0002]", last_breaking_revision="null"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="TR-0001"),
                "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", revises="TR-0001", breaking="true"),
            },
            "TR-0001",
            "last_breaking_revision is None but the newest breaking DEC (DEC-0002, position 2) produced version 3",
            id="iii-breaking-marker-missing",
        ),
        pytest.param(
            {
                **base,
                "TR-0001-a.md": _tr_markdown("TR-0001", version=2, revisions="[DEC-0001]", last_breaking_revision=2),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="TR-0001"),
            },
            "TR-0001",
            "last_breaking_revision is 2 but no DEC in revisions has breaking: true (expected null)",
            id="iv-breaking-marker-spurious",
        ),
        pytest.param(
            {
                **base,
                "TR-0001-a.md": _tr_markdown("TR-0001", lifecycle="superseded", superseded_by="TR-0002", implemented_by="[api/x]"),
                "TR-0002-b.md": _tr_markdown("TR-0002", supersedes="TR-0001"),
            },
            "TR-0001",
            "lifecycle is 'superseded' but implemented_by is non-empty (api/x)",
            id="v-superseded-with-implementers",
        ),
        pytest.param(
            {
                **base,
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001"),
                "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", supersedes="DEC-0001"),
            },
            "DEC-0002",
            "supersedes DEC-0001 but DEC-0001.superseded_by is None",
            id="vi-dec-supersession-asymmetry",
        ),
    ]


# covers hub-tooling FR-0004:AC-5
@pytest.mark.parametrize("files,obj_id,condition", _warn_cases())
def test_each_cross_check_case_yields_exactly_one_warning_and_exits_zero(tmp_path, files, obj_id, condition):
    repo = _build_repo(tmp_path, files)

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "Spec graph OK" in proc.stdout
    lines = _warning_lines(proc)
    assert len(lines) == 1, proc.stderr
    assert lines[0].startswith(f"  - {obj_id}:") and condition in lines[0], lines[0]
    assert "Versioning warnings (1):" in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    bullets = _section_lines(_index_text(repo), "Versioning warnings")
    assert len(bullets) == 1, bullets
    assert bullets[0].startswith(f"- {obj_id}:") and condition in bullets[0]


# covers hub-tooling FR-0004:AC-5
@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            {
                # (vii) rejected DEC revising TR-0001, unlisted.
                "FR-0100-a.md": _fr_markdown("FR-0100"),
                "TR-0001-a.md": _tr_markdown("TR-0001"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="rejected", revises="TR-0001"),
            },
            id="vii-rejected-exempt",
        ),
        pytest.param(
            {
                # (viii) superseded DEC-0001 (symmetric with DEC-0002) revising
                # TR-0001, unlisted; its live successor was applied and listed.
                "FR-0100-a.md": _fr_markdown("FR-0100"),
                "TR-0001-a.md": _tr_markdown("TR-0001", version=2, revisions="[DEC-0002]"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="superseded", revises="TR-0001", superseded_by="DEC-0002"),
                "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", revises="TR-0001", supersedes="DEC-0001"),
            },
            id="viii-superseded-exempt",
        ),
        pytest.param(
            {
                # Rejected DEC that revises an FR (not only TRs) — likewise exempt.
                "FR-0100-a.md": _fr_markdown("FR-0100"),
                "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="rejected", revises="FR-0100", breaking="true"),
            },
            id="vii-rejected-revising-fr",
        ),
    ],
)
def test_rejected_and_superseded_decs_produce_no_reciprocity_warning(tmp_path, files):
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == "", proc.stderr
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0
    assert _lint_stderr(proc) == ""
    assert "## Versioning warnings" not in _index_text(repo)


# covers hub-tooling FR-0004:AC-5
def test_consistent_tree_with_breaking_dec_in_position_2_produces_no_warnings(tmp_path):
    """Breaking DEC at 1-based position 2 -> last_breaking_revision 3, version 3."""
    repo = _build_repo(tmp_path, _happy_tree())
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0
    assert _lint_stderr(proc) == ""
    assert "## Versioning warnings" not in _index_text(repo)


# covers hub-tooling FR-0004:AC-5
def test_all_eight_cases_in_one_tree_yield_exactly_six_lines(tmp_path):
    """The AC's literal shape: one tree containing (i)-(viii). Exactly six
    lines, one per warning case, none naming the exempt DECs."""
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        # (i)
        "TR-0001-a.md": _tr_markdown("TR-0001", version=2, revisions="[DEC-0001]"),
        "TR-0002-b.md": _tr_markdown("TR-0002", version=2, revisions="[DEC-0001]"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="TR-0002"),
        # (ii), (vii), (viii) all target TR-0003
        "TR-0003-c.md": _tr_markdown("TR-0003"),
        "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", status="proposed", revises="TR-0003"),
        "decisions/DEC-0008-h.md": _dec_markdown("DEC-0008", status="rejected", revises="TR-0003"),
        "decisions/DEC-0009-i.md": _dec_markdown("DEC-0009", status="superseded", revises="TR-0003", superseded_by="DEC-0010"),
        "decisions/DEC-0010-j.md": _dec_markdown("DEC-0010", supersedes="DEC-0009"),
        # (iii)
        "TR-0004-d.md": _tr_markdown("TR-0004", version=3, revisions="[DEC-0003, DEC-0004]"),
        "decisions/DEC-0003-c.md": _dec_markdown("DEC-0003", revises="TR-0004"),
        "decisions/DEC-0004-d.md": _dec_markdown("DEC-0004", revises="TR-0004", breaking="true"),
        # (iv)
        "TR-0005-e.md": _tr_markdown("TR-0005", version=2, revisions="[DEC-0005]", last_breaking_revision=2),
        "decisions/DEC-0005-e.md": _dec_markdown("DEC-0005", revises="TR-0005"),
        # (v)
        "TR-0006-f.md": _tr_markdown("TR-0006", lifecycle="superseded", superseded_by="TR-0007", implemented_by="[api/x]"),
        "TR-0007-g.md": _tr_markdown("TR-0007", supersedes="TR-0006"),
        # (vi)
        "decisions/DEC-0006-f.md": _dec_markdown("DEC-0006"),
        "decisions/DEC-0007-g.md": _dec_markdown("DEC-0007", supersedes="DEC-0006"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    lines = _warning_lines(proc)
    assert len(lines) == 6, proc.stderr
    assert [l.split(":")[0].strip("- ") for l in lines] == [
        "TR-0001", "TR-0004", "TR-0005", "TR-0006", "DEC-0002", "DEC-0007",
    ]
    assert "DEC-0008" not in proc.stderr and "DEC-0009" not in proc.stderr and "DEC-0010" not in proc.stderr
    assert "Versioning warnings (6):" in proc.stderr


# covers hub-tooling FR-0004:AC-5
def test_dec_in_revisions_with_revises_null_is_a_reciprocity_warning():
    """Pure API: a creating DEC (`revises: null`) listed in a TR's `revisions`
    fails the backward check, naming both objects."""
    tr = index_specs.TR(
        path=Path("TR-0001-a.md"), id="TR-0001", title="t", operationalises=["FR-0100"],
        created="d", updated="d", version=2, revisions=["DEC-0001"],
    )
    dec = index_specs.DEC(
        path=Path("DEC-0001-a.md"), id="DEC-0001", title="t", tier="agent", status="ratified",
        rationale="r", created="d", updated="d",
    )
    warnings = index_specs._cross_object_warnings([], [tr], [dec], [])
    assert warnings == ["TR-0001: revisions lists DEC-0001 but DEC-0001.revises is None (expected 'TR-0001')"]


# covers hub-tooling FR-0004:AC-5
@pytest.mark.parametrize(
    "revisions,breaking_flags,lbr,expected_line",
    [
        # newest breaking at position 1 of 3 -> version 2
        (["DEC-0001", "DEC-0002", "DEC-0003"], [True, False, False], 2, None),
        # newest breaking at position 3 -> version 4
        (["DEC-0001", "DEC-0002", "DEC-0003"], [True, False, True], 4, None),
        (["DEC-0001", "DEC-0002", "DEC-0003"], [True, False, True], 2,
         "TR-0001: last_breaking_revision is 2 but the newest breaking DEC (DEC-0003, position 3) produced version 4 (expected 4)"),
        # Off-by-one in the naive direction (position, not position + 1).
        (["DEC-0001", "DEC-0002"], [False, True], 2,
         "TR-0001: last_breaking_revision is 2 but the newest breaking DEC (DEC-0002, position 2) produced version 3 (expected 3)"),
    ],
)
def test_breaking_marker_arithmetic_is_position_plus_one(revisions, breaking_flags, lbr, expected_line):
    tr = index_specs.TR(
        path=Path("TR-0001-a.md"), id="TR-0001", title="t", operationalises=["FR-0100"],
        created="d", updated="d", version=len(revisions) + 1, revisions=list(revisions),
        last_breaking_revision=lbr,
    )
    decs = [
        index_specs.DEC(
            path=Path(f"{d}-x.md"), id=d, title="t", tier="agent", status="ratified", rationale="r",
            created="d", updated="d", revises="TR-0001", breaking=b,
        )
        for d, b in zip(revisions, breaking_flags)
    ]
    warnings = index_specs._cross_object_warnings([], [tr], decs, [])
    assert warnings == ([] if expected_line is None else [expected_line])


# covers hub-tooling FR-0004:AC-5
def test_fr_0003_literal_breaking_gt_version_fixture_now_also_trips_fr_0004_marker_check(tmp_path):
    """Documents the FR-0003:AC-5 / FR-0004 (b) interaction: `version: 2,
    revisions: [DEC-0001], last_breaking_revision: 3` with a breaking DEC file
    yields FR-0003's `> version` line *and* FR-0004's marker line — the same
    inconsistency seen from both rules. Exit is still 0."""
    files = {
        "FR-0100-a.md": _fr_markdown(
            "FR-0100", extra_frontmatter="version: 2\nrevisions: [DEC-0001]\nlast_breaking_revision: 3"
        ),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", revises="FR-0100", breaking="true"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0
    lines = _warning_lines(proc)
    assert len(lines) == 2, proc.stderr
    assert "last_breaking_revision 3 is greater than version 2" in lines[0]
    assert "produced version 2 (expected 2)" in lines[1]


# covers hub-tooling FR-0004:AC-5
def test_dec_symmetry_and_status_checks_mirror_fr_0003(tmp_path):
    """(d) DEC supersession symmetry from both sides plus `superseded_by` set
    while status is not `superseded` — each exactly one line."""
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        # old side fully marked, successor does not point back
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="superseded", superseded_by="DEC-0002"),
        "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002"),
        # superseded_by set but status ratified
        "decisions/DEC-0003-c.md": _dec_markdown("DEC-0003", superseded_by="DEC-0002"),
        # status superseded with no successor recorded
        "decisions/DEC-0004-d.md": _dec_markdown("DEC-0004", status="superseded"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    lines = _warning_lines(proc)
    assert lines == [
        "  - DEC-0001: superseded_by DEC-0002 but DEC-0002.supersedes is None (expected 'DEC-0001')",
        "  - DEC-0003: superseded_by is 'DEC-0002' but status is 'ratified' (expected 'superseded')",
        "  - DEC-0004: status is 'superseded' but superseded_by is null",
    ], proc.stderr


# covers hub-tooling FR-0004:AC-5
def test_fr_0003_block_lint_runs_over_trs_too(tmp_path):
    """The shared block's arithmetic / symmetry lint (FR-0003) applies to TRs."""
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "TR-0001-a.md": _tr_markdown("TR-0001", version=3),
        "TR-0002-b.md": _tr_markdown("TR-0002", lifecycle="superseded"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert _warning_lines(proc) == [
        "  - TR-0001: version 3 does not equal len(revisions) + 1 = 1",
        "  - TR-0002: lifecycle is 'superseded' but superseded_by is null",
    ]


# ---------------------------------------------------------------------------
# AC-6: INDEX.md tables
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0004:AC-6
def test_tr_and_dec_tables_have_exact_columns_rows_and_sorting(tmp_path):
    files = {
        **_happy_tree(),
        # Written out of order; a second TR with every list cell empty.
        "TR-0010-later.md": _tr_markdown("TR-0010", lifecycle="draft"),
        "TR-0002-mid.md": _tr_markdown("TR-0002", implemented_by="[api/y]"),
        "decisions/DEC-0003-creating.md": _dec_markdown("DEC-0003", status="proposed", tier="neil"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    lines = _index_text(repo).splitlines()

    i = lines.index("## Technical requirements")
    assert lines[i + 1] == ""
    assert lines[i + 2] == TR_HEADER
    assert lines[i + 3] == TR_SEPARATOR
    assert lines[i + 4] == (
        "| [TR-0001](TR-0001-approach.md) | Synthetic TR-0001 | FR-0100 | 3 | `live` | 3 | "
        "`src/api/x.py`, `src/svc/*` | 2026-01-02 |"
    )
    assert lines[i + 5] == "| [TR-0002](TR-0002-mid.md) | Synthetic TR-0002 | FR-0100 | 1 | `live` | — | `api/y` | 2026-01-02 |"
    assert lines[i + 6] == "| [TR-0010](TR-0010-later.md) | Synthetic TR-0010 | FR-0100 | 1 | `draft` | — | — | 2026-01-02 |"
    assert lines[i + 7] == ""

    # The Decisions table is the default view (FR-0005): DEC-0001 sits before
    # TR-0001's breaking revision (position 1 -> v2 < last_breaking_revision 3)
    # and is listed under `## Retired objects` instead. Column set, cell
    # formatting and ID sort are FR-0004's and unchanged for every row shown.
    j = lines.index("## Decisions")
    assert lines[j + 1] == ""
    assert lines[j + 2] == DEC_HEADER
    assert lines[j + 3] == DEC_SEPARATOR
    assert lines[j + 4] == "| [DEC-0002](decisions/DEC-0002-second.md) | Synthetic DEC-0002 | agent | `ratified` | TR-0001 | yes | ADR-0001 | 2026-01-03 |"
    assert lines[j + 5] == "| [DEC-0003](decisions/DEC-0003-creating.md) | Synthetic DEC-0003 | neil | `proposed` | — | no | — | 2026-01-03 |"
    assert lines[j + 6] == ""
    assert i < j
    assert not any(l.startswith("| [DEC-0001]") for l in lines[j : lines.index("## Retired objects")])
    assert (
        "| [DEC-0001](decisions/DEC-0001-first.md) | DEC | Synthetic DEC-0001 | pre-breaking (TR-0001 v2 < v3) | 2026-01-03 |"
        in lines[lines.index("## Retired objects") :]
    )


# covers hub-tooling FR-0004:AC-6
def test_tables_sit_after_fr_warning_sections_and_before_adr_table(tmp_path):
    files = {
        **_happy_tree(),
        # Force every FR-side section: undeclared footprint (empty owns:, ready),
        # AC ratification warnings, versioning warnings.
        "FR-0101-b.md": _fr_markdown("FR-0101", extra_frontmatter="version: 5\nac_state: {1: {state: ratified}}").replace(
            "ac_state: {}\n", ""
        ),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    lines = _index_text(repo).splitlines()
    order = [
        lines.index(FR_HEADER),
        lines.index("## FRs with undeclared footprint"),
        lines.index("## AC ratification warnings"),
        lines.index("## Versioning warnings"),
        lines.index("## Technical requirements"),
        lines.index("## Decisions"),
        lines.index("## Architecture decision records"),
        # FR-0005 appends `## Retired objects` after the ADR table (the happy
        # tree's DEC-0001 is pre-breaking); the TR / DEC tables still sit
        # after every FR-side section and before the ADR table.
        lines.index("## Retired objects"),
    ]
    assert order == sorted(order), order
    adr_rows = [l for l in lines[order[-2] : order[-1]] if l.startswith("| [")]
    assert adr_rows == [l for l in lines if l.startswith("| [ADR-0001]")]  # ADR table intact, directly before Retired
    assert lines[-1].startswith("| [DEC-0001]") and _index_text(repo).endswith("|\n")


# covers hub-tooling FR-0004:AC-6
@pytest.mark.parametrize(
    "files,expect_tr,expect_dec",
    [
        pytest.param({"FR-0100-a.md": _fr_markdown("FR-0100")}, False, False, id="neither"),
        pytest.param({"FR-0100-a.md": _fr_markdown("FR-0100"), "TR-0001-a.md": _tr_markdown("TR-0001")}, True, False, id="tr-only"),
        pytest.param({"FR-0100-a.md": _fr_markdown("FR-0100"), "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001")}, False, True, id="dec-only"),
        pytest.param(
            {"FR-0100-a.md": _fr_markdown("FR-0100"), "decisions/ADR-0001-a.md": _adr_markdown("ADR-0001"), "decisions/README.md": "# x\n"},
            False, False, id="adr-and-readme-only",
        ),
    ],
)
def test_tables_omitted_when_no_objects_of_that_type(tmp_path, files, expect_tr, expect_dec):
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    text = _index_text(repo)
    assert ("## Technical requirements" in text) is expect_tr
    assert ("## Decisions" in text) is expect_dec


# covers hub-tooling FR-0004:AC-6
def test_index_is_byte_identical_across_two_runs(tmp_path):
    repo = _build_repo(tmp_path, {**_happy_tree(), "decisions/DEC-0003-c.md": _dec_markdown("DEC-0003", authorised_by="[ADR-0099]")})
    assert _run(repo, "index-specs.py").returncode == 0
    first = (repo / "specs" / "INDEX.md").read_bytes()
    assert _run(repo, "index-specs.py").returncode == 0
    assert first == (repo / "specs" / "INDEX.md").read_bytes()
    assert b"## Versioning warnings" in first  # the run had something to lint


# ---------------------------------------------------------------------------
# AC-7: backward compatibility
# ---------------------------------------------------------------------------


# Hub `main` immediately before FR-0004 merged (FR-0003's versioned indexer,
# no DEC / TR support). AC-7 says a tree without TR / DEC files must index
# exactly as it did before this FR, so *this* is the indexer to compare with.
_BASELINE_REF = "79b23da"


def _git_show_baseline(rel: str) -> bytes | None:
    """`<hub>/<_BASELINE_REF>:<rel>` as bytes, or None when the pinned commit is
    not reachable (bootstrapped projects and shallow clones have no hub
    history)."""
    hub = _TEMPLATE_DIR.parent
    probe = subprocess.run(
        ["git", "-C", str(hub), "cat-file", "-e", f"{_BASELINE_REF}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode != 0:
        return None
    # Bytes, not text: a text-mode capture decodes with the console codepage on
    # Windows and corrupts the em-dash literals the renderer emits.
    proc = subprocess.run(["git", "-C", str(hub), "show", f"{_BASELINE_REF}:{rel}"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _baseline_indexer(tmp_path: Path) -> Path | None:
    """`template/scripts/index-specs.py` as of `_BASELINE_REF`, saved to a temp
    file; None when the pinned commit is unavailable."""
    data = _git_show_baseline("template/scripts/index-specs.py")
    if data is None or b"def collect_frs" not in data:
        return None
    target = tmp_path / "baseline" / "index-specs.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


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
    (DEC-0012 item 2(b)). Only the FR table is touched: the TR, DEC, ADR,
    Provisional and Retired tables have no such column and must come back
    byte-identical. Exactly one cell is removed per FR-table line, asserted
    here so a future column cannot slip through this normalisation silently.
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


def _fr_only_tree() -> dict[str, str]:
    """Versioned FRs with lint findings, ADRs with warnings, empty `revisions`
    everywhere — the richest tree FR-0003's indexer accepts."""
    return {
        "FR-0001-old.md": _fr_markdown(
            "FR-0001",
            status="merged",
            extra_frontmatter="lifecycle: superseded\nsuperseded_by: FR-0100\nversion: 1\nlast_breaking_revision: 2",
        ),
        "FR-0100-new.md": _fr_markdown(
            "FR-0100",
            extra_frontmatter="supersedes: FR-0001\nversion: 3\nextends: [FR-0001]\nsolution_space:\n  open: [x]\n  fixed: [y]",
        ),
        "FR-0101-c.md": _fr_markdown("FR-0101", status="draft"),
        "decisions/ADR-0001-a.md": _adr_markdown("ADR-0001"),
        "decisions/ADR-0002-b.md": _adr_markdown("ADR-0002").replace("## When you may deviate\n\nx\n\n", ""),
        "decisions/README.md": "# Decisions\n",
    }


def _run_both(tmp_path: Path, files: dict[str, str], *args: str):
    baseline = _baseline_indexer(tmp_path)
    if baseline is None:
        pytest.skip(f"baseline commit {_BASELINE_REF} not reachable (not running inside the hub checkout)")
    new = _build_repo(tmp_path / "new", files)
    old = _build_repo(tmp_path / "old", files)
    shutil.copy(baseline, old / "scripts" / "index-specs.py")
    return _run(old, "index-specs.py", *args), _run(new, "index-specs.py", *args), old, new


def _fr_only_tree_without_supersession() -> dict[str, str]:
    """`_fr_only_tree` with every object in the default view: the same lint
    findings (arithmetic, breaking > version, ADR sections) but no superseded
    FR, so FR-0005's `## Retired objects` has nothing to list and the file
    must be byte-identical to the pre-FR-0004 baseline."""
    files = _fr_only_tree()
    files["FR-0001-old.md"] = _fr_markdown(
        "FR-0001", status="merged", extra_frontmatter="version: 1\nlast_breaking_revision: 2"
    )
    files["FR-0100-new.md"] = _fr_markdown(
        "FR-0100", extra_frontmatter="version: 3\nextends: [FR-0001]\nsolution_space:\n  open: [x]\n  fixed: [y]"
    )
    return files


# covers hub-tooling FR-0004:AC-7
def test_fr_only_tree_gives_identical_exit_stderr_stdout_and_index_vs_pinned_baseline(tmp_path):
    old_proc, new_proc, old, new = _run_both(tmp_path, _fr_only_tree_without_supersession())
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode, new_proc.stdout, new_proc.stderr
    )
    assert old_proc.returncode == 0
    assert _lf(old / "specs" / "INDEX.md") == _strip_gates_column(
        (new / "specs" / "INDEX.md").read_bytes()
    )
    assert "## Versioning warnings" in _index_text(new)  # the tree exercised the lint
    assert "## Retired objects" not in _index_text(new)


# covers hub-tooling FR-0004:AC-7
def test_fr_only_tree_with_superseded_fr_differs_from_baseline_only_by_the_default_view(tmp_path):
    """The original `_fr_only_tree` carries a superseded FR. FR-0005 moves it
    from the FR table to `## Retired objects`; exit code, stdout and stderr are
    still identical to the baseline and every other line of INDEX.md is too."""
    old_proc, new_proc, old, new = _run_both(tmp_path, _fr_only_tree())
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode, new_proc.stdout, new_proc.stderr
    )
    assert old_proc.returncode == 0
    old_lines = _index_text(old).splitlines()
    new_lines = (
        _strip_gates_column((new / "specs" / "INDEX.md").read_bytes())
        .decode("utf-8")
        .splitlines()
    )
    removed = [l for l in old_lines if l not in new_lines]
    added = [l for l in new_lines if l not in old_lines]
    assert len(removed) == 1 and removed[0].startswith("| [FR-0001](FR-0001-old.md) |") and "`superseded`" in removed[0]
    retired_start = new_lines.index("## Retired objects")
    prefix = new_lines[:retired_start]
    assert prefix[-1] == ""  # the blank line that precedes every section heading
    assert prefix[:-1] == [l for l in old_lines if l != removed[0]]
    assert added == [
        "## Retired objects",
        "| ID | Type | Title | Why | Updated |",
        "|----|------|-------|-----|---------|",
        "| [FR-0001](FR-0001-old.md) | FR | Synthetic FR-0001 | superseded by FR-0100 | 2026-01-01 |",
    ]
    assert "## Versioning warnings" in _index_text(new)


# covers hub-tooling FR-0004:AC-7
def test_fr_only_tree_validate_mode_identical_vs_pinned_baseline(tmp_path):
    old_proc, new_proc, _, _ = _run_both(tmp_path, _fr_only_tree(), "--validate")
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode, new_proc.stdout, new_proc.stderr
    )


# covers hub-tooling FR-0004:AC-7
def test_fr_only_error_tree_identical_vs_pinned_baseline(tmp_path):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter="extends: [FR-9999]\nversion: 0"),
        "FR-0101-b.md": _fr_markdown("FR-0101", status="bogus"),
    }
    old_proc, new_proc, _, _ = _run_both(tmp_path, files, "--validate")
    assert old_proc.returncode == 1
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode, new_proc.stdout, new_proc.stderr
    )


# covers hub-tooling FR-0004:AC-7
def test_template_specs_dir_identical_vs_pinned_baseline(tmp_path):
    """`template/` itself (or the bootstrapped project's specs/) is one of the
    trees AC-7 names explicitly."""
    files: dict[str, str] = {}
    for p in sorted(_SPECS_DIR.glob("*.md")):
        files[p.name] = p.read_text(encoding="utf-8")
    for p in sorted((_SPECS_DIR / "decisions").glob("*.md")) if (_SPECS_DIR / "decisions").is_dir() else []:
        files[f"decisions/{p.name}"] = p.read_text(encoding="utf-8")
    files.pop("INDEX.md", None)
    assert not any(n.startswith("TR-") for n in files) and not any(n.startswith("decisions/DEC-") for n in files)
    old_proc, new_proc, old, new = _run_both(tmp_path, files)
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode, new_proc.stdout, new_proc.stderr
    )
    if old_proc.returncode == 0:
        assert _lf(old / "specs" / "INDEX.md") == _strip_gates_column(
            (new / "specs" / "INDEX.md").read_bytes()
        )


# covers hub-tooling FR-0004:AC-7
def test_no_tr_dec_tree_adds_no_sections_no_counts_and_no_warning_lines(tmp_path, monkeypatch):
    """Independent of the git baseline: with no TR / DEC files the combined
    warning list is exactly FR-0003's, stdout carries no TR/DEC counts, and
    INDEX.md has neither new heading."""
    repo = _build_repo(tmp_path, _fr_only_tree())
    _point_module_at(monkeypatch, repo)
    graph = index_specs.collect_graph()
    assert graph.trs == [] and graph.decs == [] and graph.errors == []
    assert index_specs._all_versioning_warnings(graph.frs, [], [], graph.adrs) == index_specs._versioning_warnings(graph.frs)
    assert index_specs._cross_object_warnings(graph.frs, [], [], graph.adrs) == []

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0
    assert "Spec graph OK (3 FRs). Wrote nothing (--validate)." in proc.stdout
    proc = _run(repo, "index-specs.py")
    assert "Wrote specs" in proc.stdout and "TRs" not in proc.stdout and "DECs" not in proc.stdout
    text = _index_text(repo)
    assert "## Technical requirements" not in text and "## Decisions" not in text


# ---------------------------------------------------------------------------
# AC-8: CLI
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0004:AC-8
def test_validate_includes_dec_tr_parse_and_resolution_errors_and_writes_nothing(tmp_path):
    files = {
        "FR-0100-a.md": _fr_markdown("FR-0100"),
        "TR-0001-a.md": _tr_markdown("TR-0001", operationalises="[FR-9999]"),
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", status="accepted"),
        "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", revises="TR-0001", supersedes="DEC-9999"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Spec validation FAILED:" in proc.stderr
    assert "TR-0001-a.md: operationalises references unknown FR 'FR-9999'" in proc.stderr
    assert "DEC-0001-a.md: status 'accepted' not in" in proc.stderr
    assert "DEC-0002-b.md: supersedes references unknown DEC 'DEC-9999'" in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()
    assert not (repo / "CODEOWNERS").exists()


# covers hub-tooling FR-0004:AC-8
def test_validate_reports_counts_and_writes_nothing_on_valid_tree(tmp_path):
    repo = _build_repo(tmp_path, _happy_tree())
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "Spec graph OK (1 FRs, 1 TRs, 2 DECs). Wrote nothing (--validate)."
    assert not (repo / "specs" / "INDEX.md").exists()
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0
    assert "Wrote specs" in proc.stdout and "(1 FRs, 1 TRs, 2 DECs)" in proc.stdout
    assert (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0004:AC-8
def test_ac_hashes_output_unchanged_by_presence_of_dec_tr_files(tmp_path):
    fr_only = _build_repo(tmp_path / "a", {"FR-0100-a.md": _fr_markdown("FR-0100")})
    with_objects = _build_repo(
        tmp_path / "b",
        {
            **_happy_tree(),
            # Even a malformed DEC and an unresolvable TR must not perturb it.
            "decisions/DEC-0009-bad.md": _dec_markdown("DEC-0009", status="accepted"),
            "TR-0009-bad.md": _tr_markdown("TR-0009", operationalises="[FR-9999]"),
        },
    )
    a = _run(fr_only, "index-specs.py", "--ac-hashes")
    b = _run(with_objects, "index-specs.py", "--ac-hashes")
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout and a.stdout.startswith("FR-0100 AC-1: ")
    assert a.stderr == b.stderr == ""
    c = _run(with_objects, "index-specs.py", "--ac-hashes", "FR-0100")
    assert c.stdout == a.stdout


# ---------------------------------------------------------------------------
# AC-9: deploy-gate.py untouched and byte-identical
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0004:AC-9
def test_deploy_gate_source_has_no_dec_tr_awareness_and_imports_resolve():
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    for token in ("collect_trs", "collect_decs", "collect_graph", "DEC(", "TR(", "is_live_dec"):
        assert token not in source, token
    assert "render_index(parsed_frs, repo_files)" in source  # still two positional args

    spec = importlib.util.spec_from_file_location("deploy_gate_under_test_fr0004", _SCRIPTS_DIR / "deploy-gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for name in ("collect_frs", "validate_graph", "render_index", "FR", "INDEX_PATH"):
        assert hasattr(mod, name), name
    assert mod.FR is mod._index_specs.FR
    # The FR-0003 signatures are intact.
    import inspect

    assert list(inspect.signature(index_specs.collect_frs).parameters) == []
    assert list(inspect.signature(index_specs.validate_graph).parameters) == ["frs"]
    params = inspect.signature(index_specs.render_index).parameters
    assert list(params)[:2] == ["frs", "repo_files"]
    assert all(params[p].default is None for p in list(params)[2:])


# covers hub-tooling FR-0004:AC-9
def test_deploy_gate_stage_full_passes_and_writes_byte_identical_index(tmp_path):
    files = {
        **_happy_tree(),
        "decisions/DEC-0003-c.md": _dec_markdown("DEC-0003", status="proposed", revises="FR-0100"),  # one warning
    }
    repo = _build_repo(tmp_path, files)
    index = repo / "specs" / "INDEX.md"

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    from_indexer = index.read_bytes()
    index.unlink()

    proc = _run(repo, "deploy-gate.py", "--stage", "full")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    from_gate = index.read_bytes()
    assert from_indexer == from_gate
    text = from_gate.decode("utf-8")
    assert "## Technical requirements" in text and "## Decisions" in text
    assert "## Versioning warnings" in text and "DEC-0003: revises FR-0100" in text
    assert "## Architecture decision records" in text


# covers hub-tooling FR-0004:AC-9
def test_render_index_two_positional_args_discovers_trs_and_decs(tmp_path, monkeypatch):
    repo = _build_repo(tmp_path, _happy_tree())
    _point_module_at(monkeypatch, repo)
    graph = index_specs.collect_graph()
    assert graph.errors == []
    two_arg = index_specs.render_index(graph.frs, [])
    five_arg = index_specs.render_index(graph.frs, [], graph.adrs, graph.trs, graph.decs)
    assert two_arg == five_arg
    assert "| [TR-0001](TR-0001-approach.md) |" in two_arg
    assert "| [DEC-0002](decisions/DEC-0002-second.md) |" in two_arg
    # Explicit empty lists suppress discovery (so callers can render a subset).
    none_given = index_specs.render_index(graph.frs, [], graph.adrs, [], [])
    assert "## Technical requirements" not in none_given and "## Decisions" not in none_given


# ---------------------------------------------------------------------------
# AC-11: documentation
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0004:AC-11
def test_specs_readme_layout_lists_templates_locations_and_id_rule():
    text = (_SPECS_DIR / "README.md").read_text(encoding="utf-8")
    layout = text.split("```", 2)[1]
    assert "DEC-XXXX-template.md" in layout
    assert "TR-XXXX-template.md" in layout
    assert "FR-XXXX-template.md" in layout and "ADR-XXXX-template.md" in layout
    assert "TR-NNNN-<slug>.md" in layout
    assert "DEC-NNNN-<slug>.md" in layout
    assert "specs/TR-NNNN-<slug>.md" in text
    assert "specs/decisions/DEC-NNNN-<slug>.md" in text
    alloc = text.split("## ID allocation", 1)[1].split("## ", 1)[0]
    assert "TR IDs" in alloc and "DEC IDs" in alloc
    assert "sequentially" in alloc and "never reused" in alloc


# covers hub-tooling FR-0004:AC-11
def test_decisions_readme_describes_adrs_and_decs_and_links_dec_template():
    text = (_SPECS_DIR / "decisions" / "README.md").read_text(encoding="utf-8")
    assert "ADR" in text and "DEC" in text
    assert "principle" in text.lower()
    assert "tier" in text
    assert "_template/DEC-XXXX-template.md" in text
    # Both kinds live here, told apart by prefix.
    assert "ADR-NNNN-<slug>.md" in text and "DEC-NNNN-<slug>.md" in text
    # The reciprocity exemption for rejected / superseded DECs is documented.
    assert "rejected" in text and "superseded" in text and "revisions" in text
