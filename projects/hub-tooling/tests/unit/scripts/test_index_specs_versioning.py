"""Reviewer tests for FR-0003 — versioned spec objects.

Covers the shared versioning block and FR-only solution-space fields parsed by
`scripts/index-specs.py`, the warn-only versioning / supersession lint, the
`Ver` / `Lifecycle` INDEX.md columns, ADR discovery and lint, the new
`ADR-XXXX-template.md`, and the documentation ACs.

Same harness as `test_index_specs.py`: the hyphenated module is loaded by path
for the pure checks, and the CLI surfaces are driven through `subprocess`
against a self-contained temporary repo (scripts copied in, synthetic FRs and
ADRs written under `specs/`). Every fixture here is synthetic.

Coverage annotations are written `# covers hub-tooling FR-0003:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0003 exists and `deploy-gate.py` would fail
with "@covers references unknown FR". The template's other script tests carry
no `@covers` for the same reason; the hub-tooling Reviewer states coverage per
AC in the review instead (IDEA-0061).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_SPECS_DIR = _TEMPLATE_DIR / "specs"
_FR_TEMPLATE = _SPECS_DIR / "_template" / "FR-XXXX-template.md"
_ADR_TEMPLATE = _SPECS_DIR / "_template" / "ADR-XXXX-template.md"
_EXAMPLE_FR = _SPECS_DIR / "FR-0001-example.md"
_COPY_SCRIPTS = ("index-specs.py", "deploy-gate.py", "spec_footprint.py", "spec_query.py")

VERSIONING_FIELDS = (
    "version",
    "lifecycle",
    "revisions",
    "last_breaking_revision",
    "supersedes",
    "superseded_by",
)
SOLUTION_SPACE_FIELDS = (
    "extends",
    "serves_roles",
    "solution_space",
    "goal",
    "success_criteria",
    "asserted_by",
    "variability",
)
NEW_FIELDS = VERSIONING_FIELDS + SOLUTION_SPACE_FIELDS

DEFAULTS = {
    "version": 1,
    "lifecycle": "live",
    "revisions": [],
    "last_breaking_revision": None,
    "supersedes": None,
    "superseded_by": None,
    "extends": [],
    "serves_roles": [],
    "solution_space": {"open": [], "fixed": []},
    "goal": None,
    "success_criteria": [],
    "asserted_by": [],
    "variability": None,
}

ADR_SECTIONS_IN_ORDER = (
    "## Context",
    "## Decision",
    "## When you may deviate",
    "## What you must record when you deviate",
    "## Consequences",
    "## Alternatives considered",
    "## Changelog",
)

OLD_HEADER = "| ID | Title | Status | Owner | Tags | Owns | Reads | Depends on | Derived from | Updated |"
NEW_HEADER = "| ID | Title | Status | Ver | Lifecycle | Owner | Tags | Owns | Reads | Depends on | Derived from | Updated | Gates |"
NEW_SEPARATOR = "|----|-------|--------|-----|-----------|-------|------|------|-------|------------|--------------|---------|-------|"


def _load_index_specs():
    spec = importlib.util.spec_from_file_location(
        "index_specs_versioning_under_test", _SCRIPTS_DIR / "index-specs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


index_specs = _load_index_specs()


# `bootstrap.py` deletes the example FR unless `--keep-example`; in a
# bootstrapped project these verbatim-fixture tests have nothing to read.
_needs_example_fr = pytest.mark.skipif(
    not _EXAMPLE_FR.is_file(), reason="specs/FR-0001-example.md not present (bootstrap deletes it)"
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fr_markdown(
    fr_id: str,
    *,
    status: str = "ready",
    depends_on: str = "[]",
    extra_frontmatter: str = "",
) -> str:
    """Synthetic FR. `extra_frontmatter` is spliced verbatim (top-level keys)."""
    extra = f"{extra_frontmatter.rstrip()}\n" if extra_frontmatter.strip() else ""
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: {depends_on}
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

Synthetic FR for exercising the FR-0003 versioning fields.

## Acceptance criteria

- **AC-1:** does the first thing
- **AC-2:** does the second thing
"""


def _adr_markdown(
    adr_id: str,
    *,
    status: str = "accepted",
    frontmatter_id: str | None = None,
    omit_sections: tuple[str, ...] = (),
    raw_frontmatter: str | None = None,
) -> str:
    """Synthetic ADR. `omit_sections` drops named `## ` headings from the body;
    `raw_frontmatter` replaces the whole frontmatter block (for malformed cases)."""
    fm_id = frontmatter_id or adr_id
    if raw_frontmatter is None:
        frontmatter = f"""---
id: {fm_id}
title: Synthetic {adr_id}
status: {status}
owner: architect
supersedes: null
superseded_by: null
created: 2026-01-01
updated: 2026-01-02
---
"""
    else:
        frontmatter = raw_frontmatter
    body_parts = [f"# {adr_id}: Synthetic\n"]
    for heading in ADR_SECTIONS_IN_ORDER:
        if heading in omit_sections:
            continue
        body_parts.append(f"{heading}\n\nSynthetic text for {heading[3:]}.\n")
    return frontmatter + "\n" + "\n".join(body_parts)


def _dec_markdown(dec_id: str, revises: str, *, breaking: bool = False) -> str:
    """Minimal synthetic DEC whose `revises` points back at the object that
    lists it. FR-0004 (AC-4) made an unresolvable `revisions` entry a hard
    error — the resolution FR-0003:AC-4 explicitly deferred — so every FR-0003
    fixture that lists a DEC now ships the DEC file too. `breaking` is set only
    where the fixture's `last_breaking_revision` says a breaking DEC exists,
    so FR-0004's breaking-marker lint stays silent and the assertions below
    still see exactly the FR-0003 lines."""
    return f"""---
id: {dec_id}
title: Synthetic {dec_id}
tier: agent
status: ratified
revises: {revises}
breaking: {'true' if breaking else 'false'}
rationale: Synthetic decision revising {revises}.
created: 2026-01-01
updated: 2026-01-01
---

# {dec_id}: Synthetic
"""


def _build_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Copy the team scripts to `<tmp>/scripts/` and write each file under
    `<tmp>/specs/<relative name>` (creating `decisions/` etc. as needed)."""
    (tmp_path / "scripts").mkdir(exist_ok=True)
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
    """stderr minus the pre-existing, environment-dependent lines a plain run
    emits in a temp dir (`git ls-files` unavailable; no CODEOWNERS config).
    Everything FR-0003 adds — `Versioning warnings`, `ADR warnings` — stays."""
    keep = [
        l
        for l in proc.stderr.splitlines()
        if not l.startswith("WARN: spec_footprint:") and not l.startswith("INFO:")
    ]
    return "\n".join(keep)


def _index_text(repo: Path) -> str:
    return (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")


def _section_lines(index_text: str, heading: str) -> list[str]:
    """Return the bullet lines under `## <heading>` (empty if absent)."""
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


def _parse_in_repo(repo: Path, filename: str):
    """Parse one FR via the loaded module's `parse_fr` (path-independent)."""
    fr, errors = index_specs.parse_fr(repo / "specs" / filename)
    return fr, errors


# ---------------------------------------------------------------------------
# AC-10: dataclass field names and is_live()
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-10
def test_fr_dataclass_exposes_fields_under_frontmatter_names():
    names = {f.name for f in dataclasses.fields(index_specs.FR)}
    for name in NEW_FIELDS:
        assert name in names, f"FR dataclass is missing field {name!r}"


# covers hub-tooling FR-0003:AC-10
# covers hub-tooling FR-0003:AC-2
def test_fr_dataclass_defaults_match_spec():
    fr = index_specs.FR(
        path=Path("FR-0100.md"),
        id="FR-0100",
        title="t",
        status="ready",
        owner="architect",
        depends_on=[],
        tags=[],
        derived_from=None,
        pattern=None,
        created="2026-01-01",
        updated="2026-01-01",
        owns=(),
        reads=(),
    )
    for name, expected in DEFAULTS.items():
        assert getattr(fr, name) == expected, name
    # Mutable defaults must not be shared between instances.
    fr.revisions.append("DEC-0001")
    fr.solution_space["open"].append("x")
    fresh = _fr_obj("FR-0101")
    assert fresh.revisions == [] and fresh.solution_space == {"open": [], "fixed": []}


# covers hub-tooling FR-0003:AC-10
def test_is_live_is_pure_and_duck_typed():
    assert index_specs.is_live(SimpleNamespace(lifecycle="live")) is True
    assert index_specs.is_live(SimpleNamespace(lifecycle="draft")) is False
    assert index_specs.is_live(SimpleNamespace(lifecycle="superseded")) is False
    # Any object with a `lifecycle` attribute — not only FR — qualifies.
    assert index_specs.is_live(SimpleNamespace(lifecycle="LIVE")) is False


# ---------------------------------------------------------------------------
# AC-2: backward compatibility for unversioned FRs
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-2
@_needs_example_fr
def test_example_fr_verbatim_validates_with_no_new_errors_or_warnings(tmp_path):
    repo = _build_repo(
        tmp_path, {"FR-0001-example.md": _EXAMPLE_FR.read_text(encoding="utf-8")}
    )
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "Spec graph OK (1 FRs)" in proc.stdout


# covers hub-tooling FR-0003:AC-2
@_needs_example_fr
def test_example_fr_verbatim_parses_to_defaults():
    fr, errors = index_specs.parse_fr(_EXAMPLE_FR)
    assert errors == []
    assert fr is not None
    for name, expected in DEFAULTS.items():
        assert getattr(fr, name) == expected, name


# covers hub-tooling FR-0003:AC-2
# covers hub-tooling FR-0003:AC-6
@_needs_example_fr
def test_unversioned_index_minus_new_columns_is_unchanged(tmp_path):
    """Run the indexer on the example FR; strip the new cells from every
    table row and compare with the pre-FR-0003 rendering built from the same
    parsed object. No new sections may appear for an unversioned tree."""
    repo = _build_repo(
        tmp_path, {"FR-0001-example.md": _EXAMPLE_FR.read_text(encoding="utf-8")}
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    text = _index_text(repo)

    fr, _ = index_specs.parse_fr(repo / "specs" / "FR-0001-example.md")
    deps = "—"
    derived = "—"
    tags = ", ".join(fr.tags)
    old_row = (
        f"| [{fr.id}]({fr.path.name}) | {fr.title} | `{fr.status}` | {fr.owner} | "
        f"{tags} | — | — | {deps} | {derived} | {fr.updated} |"
    )
    # The pre-FR-0003 renderer also emitted the "undeclared footprint" nudge
    # for an active FR with empty `owns:` — the example FR is one — so the
    # unchanged rendering carries that section and nothing else.
    old_expected = "\n".join(
        [
            "# Spec Index",
            "",
            "_Auto-generated by `scripts/index-specs.py`. Do not edit by hand._",
            "",
            OLD_HEADER,
            "|----|-------|--------|-------|------|------|-------|------------|--------------|---------|",
            old_row,
            "",
            "## FRs with undeclared footprint",
            "",
            "_These FRs have empty `owns:` and will not appear in `CODEOWNERS`._",
            "",
            "- FR-0001",
            "",
        ]
    )

    def strip_new_cells(line: str) -> str:
        if not line.startswith("|"):
            return line
        cells = line.split("|")
        # cells[0] == "" and cells[-1] == ""; Status is cells[3]; Ver, Lifecycle
        # are cells[4], cells[5]; the trailing Gates cell (FR-0008 AC-1, added
        # after this baseline was pinned - DEC-0012 item 2(a)) is cells[-2].
        del cells[-2]
        del cells[4:6]
        return "|".join(cells)

    stripped = "\n".join(strip_new_cells(l) for l in text.splitlines()) + "\n"
    assert stripped == old_expected
    assert "## Versioning warnings" not in text
    assert "## Architecture decision records" not in text
    assert "## ADR warnings" not in text


# covers hub-tooling FR-0003:AC-2
def test_explicit_nulls_behave_as_absent(tmp_path):
    """Adversarial: the FR template pre-fills `null` for the scalar fields; an
    FR that writes every new key as null must parse to the defaults with no
    error and no warning."""
    extra = "\n".join(f"{name}: null" for name in NEW_FIELDS)
    repo = _build_repo(
        tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter=extra)}
    )
    fr, errors = _parse_in_repo(repo, "FR-0100-a.md")
    assert errors == []
    for name, expected in DEFAULTS.items():
        assert getattr(fr, name) == expected, name
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


# covers hub-tooling FR-0003:AC-2
def test_existing_fr_path_unchanged_status_enum_and_exit_code(tmp_path):
    """Pre-existing behaviour must not shift: an invalid workflow status is
    still an error naming the file, exit 1, and no versioning noise appears."""
    repo = _build_repo(
        tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100", status="retired")}
    )
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert "FR-0100-a.md: status 'retired' not in" in proc.stderr
    assert "lifecycle" not in proc.stderr
    assert "Versioning warnings" not in proc.stderr


# ---------------------------------------------------------------------------
# AC-3: shape validation
# ---------------------------------------------------------------------------


SHAPE_CASES = [
    pytest.param("version: 0", "version", id="version-zero"),
    pytest.param('version: "2"', "version", id="version-string"),
    pytest.param("version: 1.5", "version", id="version-float"),
    pytest.param("lifecycle: retired", "lifecycle", id="lifecycle-enum"),
    pytest.param("revisions: DEC-0001", "revisions", id="revisions-not-list"),
    pytest.param("revisions: [DEC-1]", "revisions", id="revisions-short-id"),
    pytest.param("revisions: [FR-0001]", "revisions", id="revisions-fr-id"),
    pytest.param("last_breaking_revision: 0", "last_breaking_revision", id="lbr-zero"),
    pytest.param('last_breaking_revision: "1"', "last_breaking_revision", id="lbr-string"),
    pytest.param("solution_space: []", "solution_space", id="ss-list"),
    pytest.param("solution_space: {open: []}", "solution_space", id="ss-missing-fixed"),
    pytest.param(
        "solution_space: {open: [], fixed: [], other: []}", "solution_space", id="ss-unknown-key"
    ),
    pytest.param('solution_space: {open: "x", fixed: []}', "solution_space", id="ss-open-string"),
    pytest.param("variability: shared", "variability", id="variability-enum"),
    pytest.param("goal: 3", "goal", id="goal-int"),
    pytest.param("serves_roles: quality", "serves_roles", id="serves-roles-not-list"),
    pytest.param('success_criteria: [""]', "success_criteria", id="sc-empty-string"),
]


# covers hub-tooling FR-0003:AC-3
@pytest.mark.parametrize("snippet,field_name", SHAPE_CASES)
def test_shape_error_names_file_and_field(tmp_path, snippet, field_name):
    repo = _build_repo(
        tmp_path,
        {"FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter=snippet)},
    )
    fr, errors = _parse_in_repo(repo, "FR-0100-a.md")
    assert fr is None
    assert len(errors) >= 1
    assert any("FR-0100-a.md" in e and field_name in e for e in errors), errors

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert "Spec validation FAILED" in proc.stderr
    assert "FR-0100-a.md" in proc.stderr and field_name in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0003:AC-3
@pytest.mark.parametrize(
    "snippet,field_name",
    [
        pytest.param("version: true", "version", id="version-bool"),
        pytest.param("last_breaking_revision: false", "last_breaking_revision", id="lbr-bool"),
        pytest.param("supersedes: 42", "supersedes", id="supersedes-int"),
        pytest.param('superseded_by: ""', "superseded_by", id="superseded-by-empty"),
        pytest.param("extends: FR-0100", "extends", id="extends-not-list"),
        pytest.param("asserted_by: [1]", "asserted_by", id="asserted-by-int"),
        pytest.param("solution_space: {open: [], fixed: [3]}", "solution_space.fixed", id="ss-fixed-int"),
        pytest.param('goal: "goal-x"', "goal", id="goal-bad-prefix"),
    ],
)
def test_shape_error_adversarial_cases(tmp_path, snippet, field_name):
    """Boundary cases beyond the AC-3 list: bools are ints in Python and must
    not pass as versions; empty strings are not IDs; nested list entries are
    named by their dotted path."""
    repo = _build_repo(
        tmp_path,
        {"FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter=snippet)},
    )
    fr, errors = _parse_in_repo(repo, "FR-0100-a.md")
    assert fr is None
    assert any("FR-0100-a.md" in e and field_name in e for e in errors), errors


# covers hub-tooling FR-0003:AC-3
def test_well_formed_versioned_fr_parses_every_field(tmp_path):
    extra = """version: 3
lifecycle: draft
revisions: [DEC-0001, DEC-0002]
last_breaking_revision: 2
supersedes: FR-0090
superseded_by: null
extends: [FR-0090]
serves_roles: [quality_risk_lead]
solution_space:
  open: [transport]
  fixed: [schema]
goal: GOAL-fewer-halts
success_criteria: [SC-003-1]
asserted_by: ["fathom:rec_1#seg2"]
variability: configurable"""
    repo = _build_repo(
        tmp_path,
        {
            "FR-0090-old.md": _fr_markdown("FR-0090"),
            "FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter=extra),
        },
    )
    fr, errors = _parse_in_repo(repo, "FR-0100-a.md")
    assert errors == []
    assert fr.version == 3
    assert fr.lifecycle == "draft"
    assert fr.revisions == ["DEC-0001", "DEC-0002"]
    assert fr.last_breaking_revision == 2
    assert fr.supersedes == "FR-0090"
    assert fr.superseded_by is None
    assert fr.extends == ["FR-0090"]
    assert fr.serves_roles == ["quality_risk_lead"]
    assert fr.solution_space == {"open": ["transport"], "fixed": ["schema"]}
    assert fr.goal == "GOAL-fewer-halts"
    assert fr.success_criteria == ["SC-003-1"]
    assert fr.asserted_by == ["fathom:rec_1#seg2"]
    assert fr.variability == "configurable"


# covers hub-tooling FR-0003:AC-3
def test_lifecycle_and_status_are_independent(tmp_path):
    """`lifecycle` is never cross-checked against workflow `status`."""
    files = {
        "FR-0100-a.md": _fr_markdown(
            "FR-0100", status="deprecated", extra_frontmatter="lifecycle: live"
        ),
        "FR-0101-b.md": _fr_markdown(
            "FR-0101",
            status="draft",
            extra_frontmatter="lifecycle: superseded\nsuperseded_by: FR-0102",
        ),
        "FR-0102-c.md": _fr_markdown(
            "FR-0102", status="merged", extra_frontmatter="supersedes: FR-0101"
        ),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


# ---------------------------------------------------------------------------
# AC-4: reference resolution
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-4
@pytest.mark.parametrize(
    "snippet,field_name",
    [
        pytest.param("extends: [FR-9999]", "extends", id="extends"),
        pytest.param("supersedes: FR-9999", "supersedes", id="supersedes"),
        pytest.param(
            "lifecycle: superseded\nsuperseded_by: FR-9999", "superseded_by", id="superseded_by"
        ),
    ],
)
def test_unknown_fr_reference_is_error_with_depends_on_wording(tmp_path, snippet, field_name):
    repo = _build_repo(
        tmp_path,
        {"FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter=snippet)},
    )
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert f"FR-0100-a.md: {field_name} references unknown FR 'FR-9999'" in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0003:AC-4
def test_extends_mixed_resolved_and_unknown_reports_only_the_unknown(tmp_path):
    repo = _build_repo(
        tmp_path,
        {
            "FR-0090-old.md": _fr_markdown("FR-0090"),
            "FR-0100-a.md": _fr_markdown(
                "FR-0100", extra_frontmatter="extends: [FR-0090, FR-9999]"
            ),
        },
    )
    frs, parse_errors = [], []
    for name in ("FR-0090-old.md", "FR-0100-a.md"):
        fr, errs = _parse_in_repo(repo, name)
        parse_errors += errs
        frs.append(fr)
    assert parse_errors == []
    graph_errors = index_specs.validate_graph(frs)
    assert graph_errors == ["FR-0100-a.md: extends references unknown FR 'FR-9999'"]


# covers hub-tooling FR-0004:AC-4
def test_revisions_entry_with_no_dec_file_is_an_error_since_fr_0004(tmp_path):
    """FR-0003:AC-4 said `revisions: [DEC-0042]` with no DEC file is *not* an
    error "in this FR (pattern-valid, resolution deferred to FR-0004)".
    FR-0004:AC-4 completes that deferral: the same fixture is now a hard error
    naming the file, the field and the unknown ID, in `depends_on` wording.
    The pattern-validity half of FR-0003:AC-4 is unchanged — a well-formed ID
    reaches resolution (and fails there) rather than failing shape."""
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown(
                "FR-0100", extra_frontmatter="version: 2\nrevisions: [DEC-0042]"
            )
        },
    )
    fr, parse_errors = _parse_in_repo(repo, "FR-0100-a.md")
    assert parse_errors == [] and fr.revisions == ["DEC-0042"]  # shape still passes
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1
    assert "Spec validation FAILED" in proc.stderr
    assert "FR-0100-a.md: revisions references unknown DEC 'DEC-0042'" in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()


# ---------------------------------------------------------------------------
# AC-5: warn-only versioning lint
# ---------------------------------------------------------------------------


def _warning_cases():
    other = {"FR-0001-old.md": _fr_markdown("FR-0001")}
    other_new = {"FR-0009-new.md": _fr_markdown("FR-0009")}
    return [
        pytest.param(
            {
                # DEC file present and pointing back (FR-0004:AC-4 resolution);
                # non-breaking, so only FR-0003's arithmetic line fires.
                "FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter="version: 3\nrevisions: [DEC-0001]"),
                "decisions/DEC-0001-x.md": _dec_markdown("DEC-0001", "FR-0100"),
            },
            "FR-0100",
            "version 3",
            id="arithmetic-mismatch",
        ),
        pytest.param(
            # FR-0003:AC-5's condition is "breaking > version". The AC's literal
            # values (`version: 2, last_breaking_revision: 3` with one DEC) now
            # also trip FR-0004's breaking-marker check — any lbr above
            # `version` disagrees with the newest breaking DEC's position too —
            # so the condition is isolated at its minimal consistent values:
            # `version: 1`, no revisions, `last_breaking_revision: 2`. The
            # literal-values interaction is asserted in test_index_specs_dec_tr.py.
            {
                "FR-0100-a.md": _fr_markdown(
                    "FR-0100", extra_frontmatter="version: 1\nlast_breaking_revision: 2"
                )
            },
            "FR-0100",
            "last_breaking_revision 2",
            id="breaking-gt-version",
        ),
        pytest.param(
            {"FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter="lifecycle: superseded")},
            "FR-0100",
            "superseded_by is null",
            id="superseded-without-successor",
        ),
        pytest.param(
            {
                **other_new,
                "FR-0100-a.md": _fr_markdown(
                    "FR-0100", extra_frontmatter="lifecycle: live\nsuperseded_by: FR-0009"
                ),
            },
            "FR-0100",
            "lifecycle is 'live'",
            id="live-with-superseded-by",
        ),
        pytest.param(
            {**other, "FR-0100-a.md": _fr_markdown("FR-0100", extra_frontmatter="supersedes: FR-0001")},
            "FR-0100",
            "FR-0001.superseded_by is None",
            id="asymmetric-supersedes",
        ),
    ]


# covers hub-tooling FR-0003:AC-5
@pytest.mark.parametrize("files,fr_id,condition", _warning_cases())
def test_versioning_lint_yields_exactly_one_warning_and_exits_zero(tmp_path, files, fr_id, condition):
    repo = _build_repo(tmp_path, files)

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "Spec graph OK" in proc.stdout
    stderr_lines = [l for l in proc.stderr.splitlines() if l.startswith("  - ")]
    assert len(stderr_lines) == 1, proc.stderr
    assert fr_id in stderr_lines[0] and condition in stderr_lines[0]
    assert "Versioning warnings (1):" in proc.stderr
    assert not (repo / "specs" / "INDEX.md").exists()

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert "Versioning warnings (1):" in proc.stderr
    bullets = _section_lines(_index_text(repo), "Versioning warnings")
    assert len(bullets) == 1, bullets
    assert fr_id in bullets[0] and condition in bullets[0]


# covers hub-tooling FR-0003:AC-5
def test_versioning_section_omitted_when_consistent(tmp_path):
    """Adversarial for a naive 'always render the heading' implementation: a
    fully consistent supersession pair plus a correctly-revised FR must yield
    no section and an empty stderr."""
    files = {
        "FR-0001-old.md": _fr_markdown(
            "FR-0001",
            status="merged",
            extra_frontmatter="lifecycle: superseded\nsuperseded_by: FR-0100\nversion: 2\nrevisions: [DEC-0001]\nlast_breaking_revision: 2",
        ),
        "FR-0100-new.md": _fr_markdown("FR-0100", extra_frontmatter="supersedes: FR-0001"),
        # `last_breaking_revision: 2` says the DEC in position 1 was breaking;
        # the DEC file (required since FR-0004:AC-4) says so too.
        "decisions/DEC-0001-x.md": _dec_markdown("DEC-0001", "FR-0001", breaking=True),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    assert "## Versioning warnings" not in _index_text(repo)


# covers hub-tooling FR-0003:AC-5
def test_versioning_lint_reports_from_superseded_side_too():
    """The old object is fully marked superseded but the successor does not
    point back: one warning naming the old object and the condition."""
    frs = [
        _fr_obj("FR-0001", lifecycle="superseded", superseded_by="FR-0100"),
        _fr_obj("FR-0100"),
    ]
    warnings = index_specs._versioning_warnings(frs)
    assert len(warnings) == 1
    assert warnings[0].startswith("FR-0001:")
    assert "FR-0100.supersedes is None" in warnings[0]


def _fr_obj(fr_id: str, **overrides):
    base = dict(
        path=Path(f"{fr_id}.md"),
        id=fr_id,
        title="t",
        status="ready",
        owner="architect",
        depends_on=[],
        tags=[],
        derived_from=None,
        pattern=None,
        created="2026-01-01",
        updated="2026-01-01",
        owns=(),
        reads=(),
    )
    return index_specs.FR(**base, **overrides)


# covers hub-tooling FR-0003:AC-5
def test_versioning_lint_multiple_frs_sorted_by_id():
    frs = [
        _fr_obj("FR-0200", version=5),
        _fr_obj("FR-0100", version=2),
    ]
    warnings = index_specs._versioning_warnings(frs)
    assert [w.split(":")[0] for w in warnings] == ["FR-0100", "FR-0200"]


# ---------------------------------------------------------------------------
# AC-6: Ver / Lifecycle columns, determinism
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-6
def test_index_columns_inserted_after_status_with_defaults(tmp_path):
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100")})
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    lines = _index_text(repo).splitlines()
    assert lines[4] == NEW_HEADER
    assert lines[5] == NEW_SEPARATOR
    row = lines[6]
    assert row.startswith("| [FR-0100](FR-0100-a.md) | Synthetic FR-0100 | `ready` | 1 | `live` | architect |")


# covers hub-tooling FR-0003:AC-6
def test_index_columns_show_explicit_versioned_values(tmp_path):
    """Explicit `version` / `lifecycle` values render in the two columns. Since
    FR-0005 the FR table is the default view (live + draft), so the explicit
    values sit on default-view FRs here and the superseded FR is asserted
    where FR-0005 moves it: `## Retired objects`, with its lifecycle as the
    `Why`. FR-0003's column claim is unchanged for every row the table shows."""
    files = {
        "FR-0001-old.md": _fr_markdown(
            "FR-0001",
            extra_frontmatter="version: 4\nrevisions: [DEC-0001, DEC-0002, DEC-0003]\nlifecycle: live",
        ),
        "FR-0002-gone.md": _fr_markdown(
            "FR-0002", extra_frontmatter="version: 2\nrevisions: [DEC-0004]\nlifecycle: superseded\nsuperseded_by: FR-0100"
        ),
        "FR-0100-new.md": _fr_markdown("FR-0100", extra_frontmatter="supersedes: FR-0002\nlifecycle: draft"),
        # One DEC file per `revisions` entry (FR-0004:AC-4 resolution).
        "decisions/DEC-0001-a.md": _dec_markdown("DEC-0001", "FR-0001"),
        "decisions/DEC-0002-b.md": _dec_markdown("DEC-0002", "FR-0001"),
        "decisions/DEC-0003-c.md": _dec_markdown("DEC-0003", "FR-0001"),
        "decisions/DEC-0004-d.md": _dec_markdown("DEC-0004", "FR-0002"),
    }
    repo = _build_repo(tmp_path, files)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    lines = _index_text(repo).splitlines()
    assert lines[6].startswith("| [FR-0001](FR-0001-old.md) |")
    assert "| `ready` | 4 | `live` | architect |" in lines[6]
    assert lines[7].startswith("| [FR-0100](FR-0100-new.md) |")
    assert "| `ready` | 1 | `draft` | architect |" in lines[7]
    assert lines[8] == ""  # the superseded FR is not a third FR-table row ...
    retired = lines[lines.index("## Retired objects") :]
    assert any(l.startswith("| [FR-0002](FR-0002-gone.md) | FR |") and "| superseded by FR-0100 |" in l for l in retired)


# covers hub-tooling FR-0003:AC-6
def test_index_is_byte_deterministic_across_runs(tmp_path):
    files = {
        "FR-0001-old.md": _fr_markdown("FR-0001", extra_frontmatter="version: 9"),
        "FR-0100-new.md": _fr_markdown("FR-0100", extra_frontmatter="supersedes: FR-0001"),
        "decisions/ADR-0001-x.md": _adr_markdown("ADR-0001", omit_sections=("## Consequences",)),
        "decisions/ADR-0002-y.md": _adr_markdown("ADR-0002", status="bogus"),
    }
    repo = _build_repo(tmp_path, files)
    assert _run(repo, "index-specs.py").returncode == 0
    first = (repo / "specs" / "INDEX.md").read_bytes()
    assert _run(repo, "index-specs.py").returncode == 0
    second = (repo / "specs" / "INDEX.md").read_bytes()
    assert first == second


# ---------------------------------------------------------------------------
# AC-7: ADR template, discovery, table, warnings
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-7
def test_adr_template_has_frontmatter_fields_and_sections_in_order():
    text = _ADR_TEMPLATE.read_text(encoding="utf-8")
    match = index_specs.FRONTMATTER_PATTERN.match(text)
    assert match, "ADR template has no frontmatter"
    frontmatter = match.group(1)
    for key in ("id", "title", "status", "owner", "supersedes", "superseded_by", "created", "updated"):
        assert f"\n{key}:" in f"\n{frontmatter}", key
    assert "proposed | accepted | superseded | rejected | deprecated" in frontmatter
    headings = [l for l in text.splitlines() if l.startswith("## ")]
    assert headings == list(ADR_SECTIONS_IN_ORDER)


# covers hub-tooling FR-0003:AC-7
# covers hub-tooling FR-0003:AC-9
def test_filled_adr_template_parses_with_no_warnings(tmp_path):
    filled = (
        _ADR_TEMPLATE.read_text(encoding="utf-8")
        .replace("ADR-XXXX", "ADR-0001")
        .replace("YYYY-MM-DD", "2026-01-01")
    )
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown("FR-0100"),
            "decisions/ADR-0001-filled.md": filled,
        },
    )
    adr = index_specs.parse_adr(repo / "specs" / "decisions" / "ADR-0001-filled.md")
    assert adr.warnings == []
    assert adr.id == "ADR-0001"
    assert adr.status == "proposed"
    assert adr.has_deviation_sections is True

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    text = _index_text(repo)
    assert "## Architecture decision records" in text
    assert "## ADR warnings" not in text
    rows = [l for l in text.splitlines() if l.startswith("| [ADR-0001]")]
    assert len(rows) == 1
    assert rows[0].startswith("| [ADR-0001](decisions/ADR-0001-filled.md) |")
    assert "| `proposed` | yes | 2026-01-01 |" in rows[0]


# covers hub-tooling FR-0003:AC-7
def test_adr_table_columns_and_link_form(tmp_path):
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown("FR-0100"),
            "decisions/ADR-0003-z.md": _adr_markdown("ADR-0003"),
        },
    )
    assert _run(repo, "index-specs.py").returncode == 0
    lines = _index_text(repo).splitlines()
    i = lines.index("## Architecture decision records")
    assert lines[i + 2] == "| ID | Title | Status | Deviation sections | Updated |"
    assert lines[i + 3] == "|----|-------|--------|--------------------|---------|"
    assert lines[i + 4] == "| [ADR-0003](decisions/ADR-0003-z.md) | Synthetic ADR-0003 | `accepted` | yes | 2026-01-02 |"


# covers hub-tooling FR-0003:AC-7
@pytest.mark.parametrize(
    "filename,content,expect_deviation,condition",
    [
        pytest.param(
            "ADR-0001-a.md",
            _adr_markdown("ADR-0001", omit_sections=("## When you may deviate",)),
            "no",
            "missing mandatory section(s) `## When you may deviate`",
            id="missing-when-section",
        ),
        pytest.param(
            "ADR-0001-a.md",
            _adr_markdown("ADR-0001", omit_sections=("## What you must record when you deviate",)),
            "no",
            "missing mandatory section(s) `## What you must record when you deviate`",
            id="missing-record-section",
        ),
        pytest.param(
            "ADR-0001-a.md",
            _adr_markdown("ADR-0001", status="approved"),
            "yes",
            "status 'approved' not in",
            id="status-outside-enum",
        ),
        pytest.param(
            "ADR-0001-a.md",
            _adr_markdown("ADR-0001", frontmatter_id="ADR-0002"),
            "yes",
            "id 'ADR-0002' does not match filename prefix 'ADR-0001'",
            id="id-filename-mismatch",
        ),
        pytest.param(
            "ADR-0001-a.md",
            _adr_markdown("ADR-0001", raw_frontmatter="---\nid: [unclosed\ntitle: x\n---\n"),
            "no",
            "invalid YAML frontmatter",
            id="malformed-frontmatter",
        ),
        pytest.param(
            "ADR-0001-a.md",
            _adr_markdown("ADR-0001", raw_frontmatter=""),
            "no",
            "missing YAML frontmatter",
            id="no-frontmatter",
        ),
    ],
)
def test_adr_problem_is_exactly_one_warning_never_an_error(
    tmp_path, filename, content, expect_deviation, condition
):
    repo = _build_repo(
        tmp_path,
        {"FR-0100-a.md": _fr_markdown("FR-0100"), f"decisions/{filename}": content},
    )
    adr = index_specs.parse_adr(repo / "specs" / "decisions" / filename)
    assert len(adr.warnings) == 1, adr.warnings
    assert filename in adr.warnings[0] and condition in adr.warnings[0]

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "Spec graph OK" in proc.stdout
    assert "ADR warnings (1):" in proc.stderr
    assert condition in proc.stderr

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    text = _index_text(repo)
    bullets = _section_lines(text, "ADR warnings")
    assert len(bullets) == 1 and condition in bullets[0]
    rows = [l for l in text.splitlines() if f"](decisions/{filename})" in l]
    assert len(rows) == 1, "a malformed ADR must still get a row"
    assert f"| {expect_deviation} |" in rows[0]


# covers hub-tooling FR-0003:AC-7
def test_adr_missing_both_sections_is_one_warning_and_no(tmp_path):
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown("FR-0100"),
            "decisions/ADR-0001-legacy.md": _adr_markdown(
                "ADR-0001", omit_sections=ADR_SECTIONS_IN_ORDER[2:4]
            ),
        },
    )
    adr = index_specs.parse_adr(repo / "specs" / "decisions" / "ADR-0001-legacy.md")
    assert len(adr.warnings) == 1
    assert "`## When you may deviate`" in adr.warnings[0]
    assert "`## What you must record when you deviate`" in adr.warnings[0]
    assert adr.has_deviation_sections is False


# covers hub-tooling FR-0003:AC-7
def test_no_decisions_dir_renders_neither_adr_section(tmp_path):
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100")})
    assert not (repo / "specs" / "decisions").exists()
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    text = _index_text(repo)
    assert "## Architecture decision records" not in text
    assert "## ADR warnings" not in text


# covers hub-tooling FR-0003:AC-7
def test_decisions_dir_with_only_readme_renders_neither_adr_section(tmp_path):
    """Adversarial: `specs/decisions/README.md` exists in every bootstrapped
    project; it must not be mistaken for an ADR."""
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown("FR-0100"),
            "decisions/README.md": "# Decisions\n",
        },
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    text = _index_text(repo)
    assert "## Architecture decision records" not in text
    assert "## ADR warnings" not in text


# covers hub-tooling FR-0003:AC-7
def test_adr_rows_sorted_by_filename_and_warnings_follow(tmp_path):
    repo = _build_repo(
        tmp_path,
        {
            "FR-0100-a.md": _fr_markdown("FR-0100"),
            "decisions/ADR-0002-b.md": _adr_markdown("ADR-0002", status="bogus"),
            "decisions/ADR-0001-a.md": _adr_markdown("ADR-0001"),
        },
    )
    assert _run(repo, "index-specs.py").returncode == 0
    lines = _index_text(repo).splitlines()
    rows = [l for l in lines if l.startswith("| [ADR-")]
    assert [r.split("]")[0] for r in rows] == ["| [ADR-0001", "| [ADR-0002"]
    assert lines.index("## Architecture decision records") < lines.index("## ADR warnings")
    assert _section_lines(_index_text(repo), "ADR warnings") == [
        "- ADR-0002-b.md: status 'bogus' not in ['accepted', 'deprecated', 'proposed', 'rejected', 'superseded']"
    ]


# ---------------------------------------------------------------------------
# AC-8: deploy-gate.py compatibility and byte-identical INDEX.md
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-8
def test_deploy_gate_imports_still_resolve():
    spec = importlib.util.spec_from_file_location(
        "deploy_gate_under_test_fr0003", _SCRIPTS_DIR / "deploy-gate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for name in ("collect_frs", "validate_graph", "render_index", "FR", "INDEX_PATH"):
        assert hasattr(mod, name), name
    assert mod.FR is mod._index_specs.FR


# covers hub-tooling FR-0003:AC-8
def test_deploy_gate_and_indexer_write_byte_identical_index(tmp_path):
    """Versioned FRs, lint warnings, ADR table and ADR warnings all present:
    the two writers must not flip-flop INDEX.md."""
    files = {
        "FR-0001-old.md": _fr_markdown(
            "FR-0001",
            status="ready",
            extra_frontmatter="version: 2\nrevisions: [DEC-0001]\nlifecycle: superseded\nsuperseded_by: FR-0100",
        ),
        "FR-0100-new.md": _fr_markdown("FR-0100", extra_frontmatter="supersedes: FR-0001\nversion: 3"),
        "decisions/ADR-0001-a.md": _adr_markdown("ADR-0001"),
        "decisions/ADR-0002-b.md": _adr_markdown("ADR-0002", omit_sections=("## When you may deviate",)),
        # FR-0001's `revisions` entry must resolve to a DEC file (FR-0004:AC-4).
        "decisions/DEC-0001-x.md": _dec_markdown("DEC-0001", "FR-0001"),
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
    assert "| Ver | Lifecycle |" in text
    assert "## Versioning warnings" in text
    assert "## Architecture decision records" in text
    assert "## ADR warnings" in text


# covers hub-tooling FR-0003:AC-8
def test_render_index_two_positional_args_discovers_adrs_from_specs_dir(tmp_path, monkeypatch):
    """`render_index(frs, repo_files)` — the exact call deploy-gate.py makes —
    must fall back to `collect_adrs()` rather than silently rendering no ADRs."""
    decisions = tmp_path / "specs" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "ADR-0007-q.md").write_text(_adr_markdown("ADR-0007"), encoding="utf-8")
    monkeypatch.setattr(index_specs, "DECISIONS_DIR", decisions)
    out = index_specs.render_index([_fr_obj("FR-0100")], [])
    assert "| [ADR-0007](decisions/ADR-0007-q.md) |" in out
    assert out == index_specs.render_index([_fr_obj("FR-0100")], [], index_specs.collect_adrs())


# ---------------------------------------------------------------------------
# AC-1 / AC-9: templates and documentation
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0003:AC-1
def test_fr_template_lists_every_new_field_with_default_and_comment():
    text = _FR_TEMPLATE.read_text(encoding="utf-8")
    frontmatter = index_specs.FRONTMATTER_PATTERN.match(text).group(1)
    lines = frontmatter.splitlines()

    def line_for(key: str) -> str:
        hits = [l for l in lines if l.startswith(f"{key}:")]
        assert len(hits) == 1, f"{key} must appear exactly once at top level"
        return hits[0]

    expected_prefill = {
        "version": "version: 1",
        "lifecycle": "lifecycle: live",
        "revisions": "revisions: []",
        "last_breaking_revision": "last_breaking_revision: null",
        "supersedes": "supersedes: null",
        "superseded_by": "superseded_by: null",
        "extends": "extends: []",
        "serves_roles": "serves_roles: []",
        "goal": "goal: null",
        "success_criteria": "success_criteria: []",
        "asserted_by": "asserted_by: []",
        "variability": "variability: null",
    }
    for key, prefix in expected_prefill.items():
        line = line_for(key)
        assert line.startswith(prefix), line
        assert "#" in line and "default" in line.lower(), f"{key} needs an inline comment with its default"
    ss = line_for("solution_space")
    assert "#" in ss and "open" in ss and "fixed" in ss
    assert "  open: []" in lines and "  fixed: []" in lines
    # Allowed values / types are named in the comments.
    assert "draft | live | superseded" in line_for("lifecycle")
    assert "core | configurable | tenant_specific" in line_for("variability")
    assert "DEC-NNNN" in line_for("revisions")

    assert "## Success criteria" in text
    assert "v<N> — DEC-NNNN (breaking: <bool>)" in text


# covers hub-tooling FR-0003:AC-1
def test_filled_fr_template_validates_with_no_warnings(tmp_path):
    filled = (
        _FR_TEMPLATE.read_text(encoding="utf-8")
        .replace("FR-XXXX", "FR-0100")
        .replace("YYYY-MM-DD", "2026-01-01")
    )
    repo = _build_repo(tmp_path, {"FR-0100-filled.md": filled})
    fr, errors = _parse_in_repo(repo, "FR-0100-filled.md")
    assert errors == []
    for name, expected in DEFAULTS.items():
        assert getattr(fr, name) == expected, name

    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "Spec graph OK (1 FRs)" in proc.stdout

    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _lint_stderr(proc) == ""
    assert "## Versioning warnings" not in _index_text(repo)


# covers hub-tooling FR-0003:AC-9
def test_decisions_readme_states_revision_vs_supersession_rule():
    text = (_SPECS_DIR / "decisions" / "README.md").read_text(encoding="utf-8")
    assert "## Revision vs supersession" in text
    rule = text.split("## Revision vs supersession", 1)[1]
    assert "identity" in rule and "versioned under it" in rule
    assert "Revise in place" in rule and "`version`" in rule and "DEC" in rule
    assert "breaking: true" in rule and "last_breaking_revision" in rule
    assert "`supersedes" in rule and "superseded_by" in rule and "lifecycle: superseded" in rule
    assert "migration window" in rule
    assert "History stays with the object" in rule

    assert "## Mandatory sections" in text
    note = text.split("## Mandatory sections", 1)[1].split("## Revision vs supersession", 1)[0]
    assert "## When you may deviate" in note
    assert "## What you must record when you deviate" in note
    assert "_template/ADR-XXXX-template.md" in note


# covers hub-tooling FR-0003:AC-9
def test_specs_readme_lists_adr_template_in_layout():
    text = (_SPECS_DIR / "README.md").read_text(encoding="utf-8")
    layout = text.split("```", 2)[1]
    assert "ADR-XXXX-template.md" in layout
    assert "FR-XXXX-template.md" in layout


# covers hub-tooling FR-0003:AC-9
# covers hub-tooling FR-0003:AC-7
def test_adr_template_file_exists_next_to_fr_template():
    assert _ADR_TEMPLATE.is_file()
    assert _FR_TEMPLATE.is_file()
