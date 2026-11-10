"""Reviewer's adversarial tests for hub-tooling FR-0026 (round 1).

The Developer's tests live in `test_index_specs_ac_exemptions.py` and
`test_deploy_gate_ac_exemptions.py`. These aim at what a naive implementation
gets wrong:

- `moved_to` shapes that a `.match` or `\\d` implementation accepts: surrounding
  whitespace, a trailing newline, Unicode digits, lowercase prefixes, prefixes
  outside the four kinds, non-string YAML values;
- `reason` values that are present but unusable;
- FR-0027's labelled ACs in each exemption state, and an indented labelled
  bullet the indexer does not parse but the gate still detects;
- FR-0023's layout-qualified annotations on exempt, unhonoured and live ACs;
- the stage differences (`dev`, `review`, `full`, `--status-only`);
- the `gate.run` record's warning classes, validated by `metrics_log`, with
  a bite against the base ref's enum;
- `## Open deferrals` cell escaping and ordering;
- the AC-14 harness's sensitivity, and `--list`/`--slice --json`/`--ac-hashes`
  output for existing `ac_state` shapes against the base ref.

Annotations use the ride-along form `# covers hub-tooling FR-0026:AC-N`: this
file travels into every bootstrapped project, where no FR-0026 exists. Fixture
annotations are assembled at run time from `_COVERS`, so no gate scanning this
file reads them. Every fixture is synthetic.
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_COPY_SCRIPTS = (
    "index-specs.py",
    "deploy-gate.py",
    "spec_footprint.py",
    "spec_query.py",
    "project_layout.py",
    "metrics_log.py",
)
_SIBLING_MODULES = (
    "index_specs",
    "spec_footprint",
    "spec_query",
    "project_layout",
    "metrics_log",
    "dispatch",
)
_DROP_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
    "DISPATCH_HUB_ROOT",
)
# `main` at the commit FR-0026 was branched from (FR-0023 and FR-0027 merged).
_BASE_REF = "ddbe9e5"
# Split so a gate scanning this file never reads fixture strings as annotations.
_COVERS = "@" + "covers"
_IMPLEMENTS = "@" + "implements"
_TAIL = "; not honoured, AC-{n} still requires coverage"
_LAYOUT = "project_name: demo\ngate:\n  test_dirs: [lib_tests]\n"


# ---------------------------------------------------------------------------
# Module under test (in-process) and the subprocess harness
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _isolated_imports(scripts_dir: Path) -> Iterator[None]:
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


idx = _load(_SCRIPTS_DIR / "index-specs.py", "fr0026_adv_index_specs")


def _make_fr(
    acs: dict[int, str],
    ac_state: dict,
    withdrawn_acs: dict[int, str] | None = None,
    fr_id: str = "FR-0100",
):  # type: ignore[no-untyped-def]
    kwargs = {} if withdrawn_acs is None else {"withdrawn_acs": withdrawn_acs}
    return idx.FR(
        path=Path(f"{fr_id}-x.md"),
        id=fr_id,
        title="t",
        status="merged",
        owner="architect",
        depends_on=[],
        tags=[],
        derived_from=None,
        pattern=None,
        created="2026-01-01",
        updated="2026-01-01",
        owns=(),
        reads=(),
        acs=acs,
        ac_state=ac_state,
        **kwargs,
    )


_TWO = {1: "Does one.", 2: "Does two."}


def _exempt(fr) -> frozenset[int]:  # type: ignore[no-untyped-def]
    return idx.coverage_exemptions([fr])[fr.id].exempt


def _invalid(fr) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    return idx.coverage_exemptions([fr])[fr.id].invalid


def _body(acs: list[str], withdrawn: list[str] | None = None) -> str:
    lines = ["", "# Synthetic FR", "", "## Acceptance criteria", "", *acs]
    if withdrawn is not None:
        lines += ["", "## Withdrawn acceptance criteria", "", "Kept for history.", ""]
        lines += withdrawn
    return "\n".join(lines) + "\n"


def _plain(n: int) -> list[str]:
    return [f"- **AC-{k}:** Does synthetic thing {k}." for k in range(1, n + 1)]


def _fr(
    fr_id: str,
    body: str,
    *,
    status: str = "ready",
    ac_state: dict[int, str] | None = None,
    extra: str = "",
) -> str:
    if ac_state:
        block = "ac_state:\n" + "".join(
            f"  {n}: {v}\n" for n, v in sorted(ac_state.items())
        )
    else:
        block = "ac_state: {}\n"
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
        f"{block}"
        f"{extra}"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n"
        f"{body}"
    )


def _covers(*refs: str) -> str:
    return "".join(f"# {_COVERS} {r}\n" for r in refs)


def _qualified(project: str, *refs: str) -> str:
    return "".join(f"# covers {project} {r}\n" for r in refs)


def _implements(*fr_ids: str) -> dict[str, str]:
    return {"src/impl.py": "".join(f"# {_IMPLEMENTS} {f}\n" for f in fr_ids)}


def _build_repo(
    base: Path,
    specs: dict[str, str],
    *,
    files: dict[str, str] | None = None,
    scripts: dict[str, bytes] | None = None,
) -> Path:
    (base / "scripts").mkdir(parents=True)
    for name in _COPY_SCRIPTS:
        if scripts is not None:
            (base / "scripts" / name).write_bytes(scripts[name])
        else:
            shutil.copy(_SCRIPTS_DIR / name, base / "scripts" / name)
    (base / "specs").mkdir()
    all_files = {f"specs/{k}": v for k, v in specs.items()}
    all_files.update(files or {})
    for rel, content in all_files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return base


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _run(repo: Path, script: str, *args: str, env: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env if env is not None else _env(),
    )


def _gate(repo: Path, *args: str):  # type: ignore[no-untyped-def]
    return _run(repo, "deploy-gate.py", *(args or ("--stage", "full")))


def _block(stderr: str, header: str) -> list[str]:
    lines = stderr.splitlines()
    if header not in lines:
        return []
    out = []
    for ln in lines[lines.index(header) + 1 :]:
        if not ln.startswith("  - "):
            break
        out.append(ln[4:])
    return out


def _labelled_block(stderr: str, label: str) -> list[str]:
    for i, ln in enumerate(stderr.splitlines()):
        if ln.startswith(f"{label} ("):
            return _block("\n".join(stderr.splitlines()[i:]), ln)
    return []


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
    return [r for r in out if r.get("kind") == "gate.run"]


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
    out: dict[str, bytes] = {}
    for name in _COPY_SCRIPTS:
        data = _git_show(_BASE_REF, f"template/scripts/{name}")
        if data is None:
            pytest.skip(f"hub history for {_BASE_REF} is not reachable")
        out[name] = data
    return out


# ---------------------------------------------------------------------------
# AC-1: pointer and reason shapes a naive validator accepts
# ---------------------------------------------------------------------------


_BAD_POINTERS = [
    ("leading-space", " IDEA-0049"),
    ("trailing-space", "IDEA-0049 "),
    ("trailing-newline", "IDEA-0049\n"),
    ("leading-newline", "\nIDEA-0049"),
    ("lowercase", "idea-0049"),
    ("mixed-case", "Fr-0011"),
    ("arabic-indic-digits", "IDEA-٠٠٤٩"),
    ("fullwidth-digits", "IDEA-００４９"),
    ("devanagari-digits", "FR-००११"),
    ("five-digits", "FR-00110"),
    ("three-digits", "FR-011"),
    ("underscore", "IDEA_0049"),
    ("no-dash", "IDEA0049"),
    ("tr-kind", "TR-0001"),
    ("pattern-kind", "PATTERN-0001"),
    ("two-ids", "FR-0011 FR-0012"),
    ("suffix", "FR-0011-x"),
    ("empty", ""),
]


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize(
    "value", [v for _, v in _BAD_POINTERS], ids=[i for i, _ in _BAD_POINTERS]
)
@pytest.mark.parametrize("state", ["deferred", "withdrawn", "superseded"])
def test_near_miss_pointer_strings_are_not_honoured(state, value):
    fr = _make_fr(_TWO, {2: {"state": state, "moved_to": value, "reason": "r"}})
    assert _exempt(fr) == frozenset()
    (msg,) = _invalid(fr)
    assert msg == (
        f"FR-0100 AC-2: moved_to '{value}' is not FR-NNNN, IDEA-NNNN, ADR-NNNN, "
        "DEC-NNNN or null" + _TAIL.format(n=2)
    )
    assert msg in idx._ac_state_warnings([fr])


_NON_STRING_POINTERS = [
    ("int", 49),
    ("float", 49.0),
    ("bool", True),
    ("list", ["IDEA-0049"]),
    ("mapping", {"id": "IDEA-0049"}),
    ("date", datetime.date(2026, 1, 1)),
]


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize(
    "value",
    [v for _, v in _NON_STRING_POINTERS],
    ids=[i for i, _ in _NON_STRING_POINTERS],
)
def test_non_string_pointers_are_not_honoured_and_the_value_is_quoted(value):
    fr = _make_fr(_TWO, {2: {"state": "deferred", "moved_to": value}})
    assert _exempt(fr) == frozenset()
    (msg,) = _invalid(fr)
    assert msg.startswith(f"FR-0100 AC-2: moved_to '{value}' is not ")
    assert msg.endswith(_TAIL.format(n=2))


_UNUSABLE_REASONS = [
    ("absent", None),
    ("empty", ""),
    ("spaces", "   "),
    ("whitespace-mix", " \t\n "),
    ("int", 0),
    ("list", ["why"]),
    ("null", "NULL-SENTINEL"),
]


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize(
    "reason", [v for _, v in _UNUSABLE_REASONS], ids=[i for i, _ in _UNUSABLE_REASONS]
)
@pytest.mark.parametrize("state", ["deferred", "withdrawn"])
def test_null_pointer_needs_a_usable_reason(state, reason):
    entry: dict = {"state": state, "moved_to": None}
    if reason == "NULL-SENTINEL":
        entry["reason"] = None
    elif reason is not None:
        entry["reason"] = reason
    fr = _make_fr(_TWO, {2: entry})
    assert _exempt(fr) == frozenset()
    assert _invalid(fr) == (
        "FR-0100 AC-2: moved_to is null but no reason is given" + _TAIL.format(n=2),
    )


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize("reason", ["x", " padded ", "multi\nline"])
def test_null_pointer_with_any_non_blank_reason_is_honoured(reason):
    fr = _make_fr(_TWO, {2: {"state": "deferred", "moved_to": None, "reason": reason}})
    assert _exempt(fr) == {2}
    assert _invalid(fr) == ()


# covers hub-tooling FR-0026:AC-1
def test_superseded_null_is_refused_even_with_a_reason_and_idea_is_accepted():
    refused = _make_fr(
        _TWO, {2: {"state": "superseded", "moved_to": None, "reason": "gone"}}
    )
    assert _exempt(refused) == frozenset()
    assert _invalid(refused) == (
        "FR-0100 AC-2: superseded needs a non-null moved_to naming its successor"
        + _TAIL.format(n=2),
    )
    accepted = _make_fr(_TWO, {2: {"state": "superseded", "moved_to": "IDEA-0001"}})
    assert _exempt(accepted) == {2}


# covers hub-tooling FR-0026:AC-1
def test_keys_beyond_the_five_are_ignored_and_the_optional_four_are_allowed():
    entry = {
        "state": "deferred",
        "moved_to": "IDEA-0001",
        "reason": "later",
        "source": "fathom:rec_1#seg2",
        "ratified": None,
        "hash": "0" * 64,
        "owner": "someone",
        "priority": 2,
    }
    fr = _make_fr(_TWO, {2: entry})
    assert _exempt(fr) == {2}
    assert idx._ac_state_warnings([fr]) == []


# covers hub-tooling FR-0026:AC-1
def test_moved_to_on_a_non_exemption_state_warns_even_when_the_ac_has_no_text():
    """AC-1: "A `moved_to` on a non-exemption state produces the warning ...".
    The sentence has no condition on the AC having text. r1's B-1: the indexer
    used to `continue` past this check for an AC in neither section."""
    fr = _make_fr(_TWO, {9: {"state": "proposed", "moved_to": "IDEA-0001"}})
    warnings = idx._ac_state_warnings([fr])
    assert (
        "FR-0100 AC-9: moved_to applies only to deferred, withdrawn or superseded; "
        "ignored"
    ) in warnings
    assert _exempt(fr) == frozenset()


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize("state", ["Deferred", "WITHDRAWN", " superseded", None])
def test_a_state_that_is_not_exactly_an_exemption_state_never_exempts(state):
    fr = _make_fr(_TWO, {2: {"state": state, "moved_to": "IDEA-0001"}})
    assert _exempt(fr) == frozenset()
    assert _invalid(fr) == ()  # not an exemption entry, so not "not honoured"
    assert (
        "FR-0100 AC-2: moved_to applies only to deferred, withdrawn or superseded; "
        "ignored"
    ) in idx._ac_state_warnings([fr])


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize("entry", ["deferred", ["deferred", "IDEA-0001"], None])
def test_a_non_mapping_entry_never_exempts(entry):
    fr = _make_fr(_TWO, {2: entry})
    assert _exempt(fr) == frozenset()
    assert _invalid(fr) == ()


# ---------------------------------------------------------------------------
# AC-2: local resolution edge cases
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-2
def test_a_deferral_to_its_own_fr_resolves_and_a_pointer_to_another_fr_needs_it():
    own = _make_fr(_TWO, {2: {"state": "deferred", "moved_to": "FR-0100"}})
    assert _exempt(own) == {2}
    other = _make_fr(_TWO, {2: {"state": "superseded", "moved_to": "FR-0101"}})
    succ = _make_fr(_TWO, {}, fr_id="FR-0101")
    assert idx.coverage_exemptions([other])["FR-0100"].exempt == frozenset()
    assert idx.coverage_exemptions([other, succ])["FR-0100"].exempt == {2}


# covers hub-tooling FR-0026:AC-2
def test_dec_and_adr_resolve_by_id_and_by_filename_prefix_only(tmp_path):
    """A DEC resolves by a parsed DEC's id; an ADR by an `ADR-NNNN-*.md` file.
    `ADR-0001.md` (no slug) and `ADR-00010-x.md` (a longer number with the
    same prefix) must not resolve `ADR-0001`."""
    dec = type("D", (), {"id": "DEC-0007"})()
    adr_ok = type("A", (), {"path": tmp_path / "ADR-0002-ok.md"})()
    adr_noslug = type("A", (), {"path": tmp_path / "ADR-0001.md"})()
    adr_long = type("A", (), {"path": tmp_path / "ADR-00010-x.md"})()
    resolver = idx._PointerResolver([], [dec], [adr_ok, adr_noslug, adr_long])
    assert resolver.resolves("DEC-0007")
    assert not resolver.resolves("DEC-0008")
    assert resolver.resolves("ADR-0002")
    assert not resolver.resolves("ADR-0001")
    assert resolver.resolves("IDEA-9999")


# ---------------------------------------------------------------------------
# AC-5: the Withdrawn section with labelled ACs (FR-0027), and heading variants
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-5
@pytest.mark.parametrize(
    "heading, parsed",
    [
        ("## WITHDRAWN ACCEPTANCE CRITERIA", True),
        ("##   Withdrawn acceptance criteria   ", True),
        ("### Withdrawn acceptance criteria", False),
        ("## Withdrawn acceptance criteria:", False),
        ("## Withdrawn acceptance criteria (history)", False),
        ("##Withdrawn acceptance criteria", False),
    ],
)
def test_withdrawn_heading_variants(heading, parsed):
    text = (
        "## Acceptance criteria\n\n- **AC-1:** One.\n\n"
        f"{heading}\n\n- **AC-2 (old):** Two.\n"
    )
    assert (idx.parse_withdrawn_acs(text) == {2: "(old) Two."}) is parsed
    # An H3 is not a section break, so its bullet stays in the AC section.
    if heading.startswith("### "):
        assert 2 in idx.parse_acs(text)


# covers hub-tooling FR-0026:AC-5
def test_labelled_acs_in_each_state_under_the_withdrawn_section():
    withdrawn = {
        3: "(L) Withdrawn.",
        4: "(L) Superseded.",
        5: "(L) Deferred in the wrong place.",
        6: "(L) Unhonoured.",
        7: "(L) No entry.",
    }
    fr = _make_fr(
        {1: "(L) Live.", 2: "(L) Deferred."},
        {
            2: {"state": "deferred", "moved_to": "IDEA-0001"},
            3: {"state": "withdrawn", "moved_to": None, "reason": "gone"},
            4: {"state": "superseded", "moved_to": "IDEA-0002"},
            5: {"state": "deferred", "moved_to": "IDEA-0003"},
            6: {"state": "withdrawn"},
        },
        withdrawn,
    )
    assert _exempt(fr) == {2, 3, 4, 5}
    # Whether AC-5(a) also fires for the honoured deferral under the section
    # (AC-5) is escalated in the r1 review; this test does not pin it.
    warnings = [
        w
        for w in idx._ac_state_warnings([fr])
        if not w.startswith("FR-0100 AC-5: listed under")
    ]
    assert warnings == [
        "FR-0100 AC-6: withdrawn needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, "
        "DEC-NNNN, or null with a reason)" + _TAIL.format(n=6),
        "FR-0100 AC-5: deferred ACs stay under Acceptance criteria",
        "FR-0100 AC-6: listed under Withdrawn acceptance criteria but ac_state is "
        "withdrawn; it is live for coverage",
        "FR-0100 AC-7: listed under Withdrawn acceptance criteria but ac_state is "
        "absent; it is live for coverage",
    ]
    assert not any("has no matching" in w for w in warnings)


# covers hub-tooling FR-0026:AC-5
def test_ratified_text_under_the_withdrawn_section_is_hashed_from_that_text():
    text = "(L) Kept."
    fr = _make_fr(
        _TWO,
        {
            1: {"state": "ratified", "hash": idx.ac_hash("Does one.")},
            2: {"state": "ratified", "hash": idx.ac_hash("Does two.")},
            3: {"state": "ratified", "hash": idx.ac_hash(text)},
        },
        {3: text},
    )
    warnings = idx._ac_state_warnings([fr])
    assert warnings == [
        "FR-0100 AC-3: listed under Withdrawn acceptance criteria but ac_state is "
        "ratified; it is live for coverage"
    ]


# covers hub-tooling FR-0026:AC-5
# covers hub-tooling FR-0026:AC-7
def test_an_indented_labelled_bullet_is_not_parsed_but_the_gate_still_detects_it(
    tmp_path,
):
    """Column 0 is the indexer's rule; the gate's `AC_LABELLED_PATTERN` allows
    leading whitespace. A honoured entry for such an AC keeps working, with
    only the "no text in this FR" warning."""
    body = _body(_plain(2), ["  - **AC-3 (old):** Indented withdrawn text."])
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100",
            body,
            status="merged",
            ac_state={3: "{state: withdrawn, moved_to: null, reason: gone}"},
        )
    }
    repo = _build_repo(
        tmp_path,
        specs,
        files={
            "tests/test_x.py": _covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-3"),
            **_implements("FR-0100"),
        },
    )
    idx_proc = _run(repo, "index-specs.py", "--validate")
    assert idx_proc.returncode == 0, idx_proc.stderr
    assert _labelled_block(idx_proc.stderr, "AC ratification warnings") == [
        "FR-0100 AC-3: withdrawn but has no text in this FR; keep its original text "
        "under ## Withdrawn acceptance criteria"
    ]
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr
    assert "not in the FR" not in proc.stderr


# ---------------------------------------------------------------------------
# AC-7 / AC-8 / AC-9: labelled ACs and layout-qualified annotations in the gate
# ---------------------------------------------------------------------------


def _labelled_fr(status: str = "merged") -> dict[str, str]:
    body = _body(
        ["- **AC-1 (live):** Live.", "- **AC-2 (later):** Deferred."],
        [
            "- **AC-3 (gone):** Withdrawn.",
            "- **AC-4 (moved):** Superseded.",
            "- **AC-5 (broken):** Unhonoured withdrawn.",
        ],
    )
    state = {
        2: "{state: deferred, moved_to: IDEA-0001}",
        3: "{state: withdrawn, moved_to: null, reason: gone}",
        4: "{state: superseded, moved_to: FR-0101}",
        5: "{state: withdrawn}",
    }
    return {
        "FR-0100-l.md": _fr("FR-0100", body, status=status, ac_state=state),
        "FR-0101-s.md": _fr("FR-0101", _body(_plain(1))),
    }


# covers hub-tooling FR-0026:AC-7
# covers hub-tooling FR-0026:AC-8
# covers hub-tooling FR-0026:AC-10
def test_labelled_acs_in_each_state_through_the_gate(tmp_path):
    repo = _build_repo(
        tmp_path,
        _labelled_fr(),
        files={
            "tests/test_x.py": _covers("FR-0100:AC-1", "FR-0100:AC-3", "FR-0100:AC-4"),
            **_implements("FR-0100"),
        },
    )
    proc = _gate(repo)
    assert proc.returncode == 1
    assert _block(proc.stderr, "Deploy gate FAILED:") == [
        "FR-0100 (merged): no " + _COVERS + " test for AC-5"
    ]
    assert (
        "FR-0100 AC-5: withdrawn needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, "
        "DEC-NNNN, or null with a reason)" + _TAIL.format(n=5)
    ) in _block(proc.stderr, "Deploy gate WARNINGS:")
    rec = _records(repo)[-1]
    assert rec["failure_classes"] == ["coverage-missing"]
    assert "ac-exemption-invalid" in rec["warning_classes"]
    assert "ac-all-exempt" not in rec["warning_classes"]

    # Covering AC-5 turns it green; a cover on the honoured deferral is fine.
    (repo / "tests" / "test_y.py").write_text(
        _covers("FR-0100:AC-5", "FR-0100:AC-2"), encoding="utf-8"
    )
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr


# covers hub-tooling FR-0026:AC-7
# covers hub-tooling FR-0026:AC-8
def test_layout_qualified_annotations_follow_the_project_name_and_test_dirs(tmp_path):
    """Under `project_name: demo` and `gate.test_dirs: [lib_tests]`:
    a qualified annotation for another project is not counted, a plain one in
    `tests/` is outside the test dirs, a qualified one on an AC whose entry is
    not honoured fails `covers-unknown-ac`, and a qualified one on a honoured
    legacy-form AC passes check 2. A legacy-form AC is not detected, so its
    unhonoured entry adds no coverage demand either."""
    body = _body(
        _plain(2),
        [
            "- **[DEPRECATED] AC-3** (superseded) Legacy text.",
            "- **[DEPRECATED] AC-4** (withdrawn) Legacy text.",
        ],
    )
    state = {
        3: "{state: superseded, moved_to: FR-0101}",
        4: "{state: withdrawn}",
    }
    specs = {
        "FR-0100-q.md": _fr("FR-0100", body, status="merged", ac_state=state),
        "FR-0101-s.md": _fr("FR-0101", _body(_plain(1))),
    }
    files = {
        ".agent-team/layout.yaml": _LAYOUT,
        "lib_tests/test_lib.py": _qualified("demo", "FR-0100:AC-1", "FR-0100:AC-3")
        + _qualified("other", "FR-0100:AC-2"),
        "tests/test_outside.py": _covers("FR-0100:AC-2"),
        **_implements("FR-0100"),
    }
    repo = _build_repo(tmp_path, specs, files=files)
    proc = _gate(repo)
    assert proc.returncode == 1
    assert sorted(_block(proc.stderr, "Deploy gate FAILED:")) == [
        "FR-0100 (merged): no " + _COVERS + " test for AC-2",
    ]
    # Now qualify a cover on the unhonoured AC-4: it is unknown to check 2.
    (repo / "lib_tests" / "test_more.py").write_text(
        _qualified("demo", "FR-0100:AC-4"), encoding="utf-8"
    )
    proc = _gate(repo, "--stage", "dev")
    assert proc.returncode == 1
    assert _block(proc.stderr, "Deploy gate FAILED:") == [
        _COVERS + " references FR-0100:AC-4 but that AC is not in the FR"
    ]
    assert _records(repo)[-1]["failure_classes"] == ["covers-unknown-ac"]


# covers hub-tooling FR-0026:AC-9
def test_a_labelled_deferred_target_never_masks_a_live_gap(tmp_path):
    body = _body(
        [
            "- **AC-1 (a):** Live and uncovered.",
            "- **AC-2 (b):** Deferred and covered.",
            "- **AC-3 (c):** Live and covered.",
        ]
    )
    specs = {
        "FR-0100-adv.md": _fr(
            "FR-0100",
            body,
            status="in-review",
            ac_state={2: "{state: deferred, moved_to: IDEA-0001}"},
        )
    }
    repo = _build_repo(
        tmp_path,
        specs,
        files={
            "tests/test_x.py": _covers("FR-0100:AC-2", "FR-0100:AC-3"),
            **_implements("FR-0100"),
        },
    )
    proc = _gate(repo)
    assert proc.returncode == 1
    assert _block(proc.stderr, "Deploy gate FAILED:") == [
        "FR-0100 (in-review): no " + _COVERS + " test for AC-1"
    ]
    rec = _records(repo)[-1]
    assert rec["failure_classes"] == ["coverage-missing"]
    assert rec["object_ids"] == ["FR-0100"]


# ---------------------------------------------------------------------------
# AC-10 / AC-11 / AC-12: stages and the gate.run record's classes
# ---------------------------------------------------------------------------


def _stage_tree() -> dict[str, str]:
    """FR-0100 (merged): AC-2's entry is not honoured and AC-2 is uncovered.
    FR-0101 (merged): every AC deferred. FR-0102: a legacy `ac-format` line."""
    return {
        "FR-0100-a.md": _fr(
            "FR-0100",
            _body(_plain(2)),
            status="merged",
            ac_state={2: "{state: deferred, moved_to: IDEA-49}"},
        ),
        "FR-0101-b.md": _fr(
            "FR-0101",
            _body(_plain(2)),
            status="merged",
            ac_state={
                1: "{state: deferred, moved_to: IDEA-0001}",
                2: "{state: deferred, moved_to: null, reason: later}",
            },
        ),
        "FR-0102-c.md": _fr(
            "FR-0102",
            _body(_plain(1), ["- **[DEPRECATED] AC-2** (withdrawn) Old."]),
        ),
    }


_INVALID_LINE = (
    "FR-0100 AC-2: moved_to 'IDEA-49' is not FR-NNNN, IDEA-NNNN, ADR-NNNN, "
    "DEC-NNNN or null" + _TAIL.format(n=2)
)
_ALL_EXEMPT_LINE = (
    "FR-0101 (merged): every AC is deferred, withdrawn or superseded; nothing in "
    "this FR is delivered"
)


# covers hub-tooling FR-0026:AC-10
# covers hub-tooling FR-0026:AC-11
# covers hub-tooling FR-0026:AC-12
@pytest.mark.parametrize(
    "args, rc, failures, warning_classes, all_exempt",
    [
        (("--stage", "dev"), 0, [], ["ac-format", "ac-exemption-invalid"], False),
        (
            ("--stage", "review"),
            1,
            ["coverage-missing"],
            ["ac-format", "ac-exemption-invalid", "ac-all-exempt"],
            True,
        ),
        (
            ("--stage", "full"),
            1,
            ["coverage-missing"],
            ["ac-format", "ac-exemption-invalid", "ac-all-exempt"],
            True,
        ),
    ],
    ids=["dev", "review", "full"],
)
def test_stage_differences_and_the_record_classes(
    tmp_path, args, rc, failures, warning_classes, all_exempt
):
    repo = _build_repo(
        tmp_path,
        _stage_tree(),
        files={
            "tests/test_x.py": _covers("FR-0100:AC-1"),
            **_implements("FR-0100", "FR-0101"),
        },
    )
    proc = _gate(repo, *args)
    assert proc.returncode == rc, proc.stderr
    warnings = _block(proc.stderr, "Deploy gate WARNINGS:")
    assert warnings.count(_INVALID_LINE) == 1
    assert (_ALL_EXEMPT_LINE in warnings) is all_exempt
    (rec,) = _records(repo)
    assert rec["failure_classes"] == failures
    assert sorted(rec["warning_classes"]) == sorted(warning_classes)
    assert len(rec["warning_classes"]) == len(set(rec["warning_classes"]))
    # The record validates against this branch's metrics schema.
    metrics_log = _load(repo / "scripts" / "metrics_log.py", "fr0026_adv_metrics")
    metrics_log.validate(rec)


# covers hub-tooling FR-0026:AC-10
def test_status_only_prints_the_warning_and_writes_no_record(tmp_path):
    repo = _build_repo(
        tmp_path,
        _stage_tree(),
        files={"tests/test_x.py": _covers("FR-0100:AC-1")},
    )
    proc = _gate(repo, "--stage", "dev", "--status-only")
    assert proc.returncode == 0, proc.stderr
    assert _INVALID_LINE in _block(proc.stderr, "Deploy gate WARNINGS:")
    assert _records(repo) == []
    assert not (repo / "specs" / "INDEX.md").exists()


# covers hub-tooling FR-0026:AC-12
def test_the_base_refs_metrics_schema_rejects_the_new_classes(tmp_path):
    """Bite for AC-12: the enum edit is load-bearing. A real `gate.run` record
    carrying both new classes validates against this branch's `metrics_log`,
    and the base ref's refuses it, naming `warning_classes`."""
    base = _git_show(_BASE_REF, "template/scripts/metrics_log.py")
    if base is None:
        pytest.skip(f"hub history for {_BASE_REF} is not reachable")
    repo = _build_repo(
        tmp_path / "repo",
        _stage_tree(),
        files={"tests/test_x.py": _covers("FR-0100:AC-1")},
    )
    _gate(repo)
    (rec,) = _records(repo)
    assert {"ac-exemption-invalid", "ac-all-exempt"} <= set(rec["warning_classes"])
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "metrics_log.py").write_bytes(base)
    old = _load(tmp_path / "base" / "metrics_log.py", "fr0026_adv_metrics_base")
    new = _load(_SCRIPTS_DIR / "metrics_log.py", "fr0026_adv_metrics_new")
    assert new.validation_errors(rec) == []
    errors = old.validation_errors(rec)
    assert len(errors) == 1 and errors[0].startswith("warning_classes")


# ---------------------------------------------------------------------------
# AC-13: Open deferrals cells
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-13
def test_open_deferrals_rows_escape_sort_and_skip_correctly():
    frs = [
        _make_fr(
            {n: f"t{n}" for n in range(1, 12)},
            {
                10: {"state": "deferred", "moved_to": "IDEA-0001", "reason": "a | b"},
                2: {"state": "deferred", "moved_to": None, "reason": "line1\r\nline2"},
                3: {"state": "deferred", "moved_to": "FR-0100", "reason": "   "},
                4: {"state": "deferred", "moved_to": "IDEA-0002", "reason": 42},
                5: {"state": "deferred", "moved_to": "FR-0999"},  # dangling
                6: {"state": "withdrawn", "moved_to": None, "reason": "gone"},
                7: {"state": "superseded", "moved_to": "IDEA-0003"},
                8: {"state": "ratified", "moved_to": "IDEA-0004"},
            },
            fr_id="FR-0100",
        ),
        _make_fr(
            {1: "x"},
            {1: {"state": "deferred", "moved_to": "IDEA-0005"}},
            fr_id="FR-0099",
        ),
    ]
    lines = idx._render_open_deferrals(frs)
    rows = [ln for ln in lines if ln.startswith("| [")]
    assert rows == [
        "| [FR-0099](FR-0099-x.md) | AC-1 | `merged` | IDEA-0005 | — |",
        "| [FR-0100](FR-0100-x.md) | AC-2 | `merged` | none | line1 line2 |",
        "| [FR-0100](FR-0100-x.md) | AC-3 | `merged` | FR-0100 | — |",
        "| [FR-0100](FR-0100-x.md) | AC-4 | `merged` | IDEA-0002 | 42 |",
        "| [FR-0100](FR-0100-x.md) | AC-10 | `merged` | IDEA-0001 | a \\| b |",
    ]
    # One cell per column in every row.
    for row in rows:
        assert len(re.split(r"(?<!\\)\|", row)) == 7


# ---------------------------------------------------------------------------
# AC-14 and point 4: the base-ref comparisons are sensitive, and the query
# output for existing `ac_state` shapes is unchanged
# ---------------------------------------------------------------------------


def _existing_shapes_tree() -> dict[str, str]:
    return {
        "FR-0100-a.md": _fr(
            "FR-0100",
            _body(_plain(3)),
            status="merged",
            ac_state={
                1: '{state: ratified, source: "fathom:rec_1#seg1", ratified: 2026-01-02, '
                'hash: "' + idx.ac_hash("Does synthetic thing 1.") + '"}',
                2: "{state: proposed, source: null, ratified: null, hash: null}",
                3: "{state: superseded}",
            },
        ),
        "FR-0101-b.md": _fr(
            "FR-0101",
            _body(["- **AC-1 (L):** Labelled."], ["- **[DEPRECATED] AC-2** old"]),
        ),
    }


# covers hub-tooling FR-0026:AC-14
# covers hub-tooling FR-0026:AC-5
@pytest.mark.parametrize(
    "args",
    [
        ("--list", "fr", "--json"),
        ("--list", "all", "--json"),
        ("--slice", "FR-0100", "--json"),
        ("--slice", "FR-0101", "--json"),
        ("--ac-hashes",),
    ],
    ids=["list-fr", "list-all", "slice-ratified", "slice-labelled", "ac-hashes"],
)
def test_query_output_for_existing_ac_state_shapes_matches_the_base_ref(tmp_path, args):
    runs = {}
    for side, scripts in (("old", _base_scripts()), ("new", None)):
        repo = _build_repo(tmp_path / side, _existing_shapes_tree(), scripts=scripts)
        runs[side] = _run(repo, "index-specs.py", *args)
    assert runs["new"].returncode == runs["old"].returncode == 0, runs["new"].stderr
    assert runs["new"].stdout == runs["old"].stdout
    assert runs["new"].stdout.strip()


# covers hub-tooling FR-0026:AC-5
def test_slice_json_never_carries_the_withdrawn_text_and_keeps_ac_state_raw(tmp_path):
    body = _body(_plain(2), ["- **AC-3:** Secret-free withdrawn text."])
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100",
            body,
            ac_state={3: "{state: withdrawn, moved_to: null, reason: gone}"},
        )
    }
    repo = _build_repo(tmp_path, specs)
    proc = _run(repo, "index-specs.py", "--slice", "FR-0100", "--json")
    assert proc.returncode == 0, proc.stderr
    assert "withdrawn_acs" not in proc.stdout
    assert "Secret-free withdrawn text" not in proc.stdout
    data = json.loads(proc.stdout)
    found = []

    def walk(node):  # type: ignore[no-untyped-def]
        if isinstance(node, dict):
            if node.get("id") == "FR-0100" and "ac_state" in node:
                found.append(node["ac_state"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    assert found == [{"3": {"state": "withdrawn", "moved_to": None, "reason": "gone"}}]


# covers hub-tooling FR-0026:AC-14
# covers hub-tooling FR-0026:AC-13
def test_the_unmanaged_comparison_would_see_a_single_deferral(tmp_path):
    """Non-vacuity of AC-14's byte-identity harness: the same aitk-shaped tree
    with one honoured deferral differs from the base ref, and only by the
    `## Open deferrals` block (a lone deferral does not opt in)."""
    specs = _existing_shapes_tree()
    specs["FR-0102-d.md"] = _fr(
        "FR-0102",
        _body(_plain(2)),
        status="in-review",
        ac_state={2: "{state: deferred, moved_to: IDEA-0001}"},
    )
    runs = {}
    for side, scripts in (("old", _base_scripts()), ("new", None)):
        repo = _build_repo(tmp_path / side, specs, scripts=scripts)
        proc = _run(repo, "index-specs.py")
        assert proc.returncode == 0, proc.stderr
        runs[side] = (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")
    old, new = runs["old"], runs["new"]
    assert old != new
    block = re.search(r"\n## Open deferrals\n.*?(?=\n## |\Z)", new, flags=re.S)
    assert block is not None
    assert (
        "| [FR-0102](FR-0102-d.md) | AC-2 | `in-review` | IDEA-0001 | — |"
        in block.group(0)
    )
    # The legacy superseded AC-3 gains AC-1's warning. The base indexer treated
    # the lone deferral as an opt-in with an unknown state; this branch does
    # not (AC-4), so those two base lines go.
    old_rest = old
    new_rest = new.replace(block.group(0), "")
    gained = sorted(set(new_rest.splitlines()) - set(old_rest.splitlines()))
    lost = sorted(set(old_rest.splitlines()) - set(new_rest.splitlines()))
    assert gained == [
        "- FR-0100 AC-3: superseded needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, "
        "DEC-NNNN, or null with a reason)" + _TAIL.format(n=3)
    ]
    assert lost == [
        "- FR-0102 AC-2: state 'deferred' not in ['client-review', 'proposed', "
        "'ratified', 'refined', 'superseded']",
        "- FR-0102: no ac_state entry for AC-1",
    ]


# ---------------------------------------------------------------------------
# AC-3: hub lookup edge cases
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-3
def test_an_env_hub_without_parking_py_falls_back_to_the_walk_and_finds_none(tmp_path):
    fake = tmp_path / "not-a-hub"
    (fake / "parking-lot").mkdir(parents=True)
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100",
            _body(_plain(2)),
            ac_state={2: "{state: deferred, moved_to: IDEA-0001}"},
        )
    }
    repo = _build_repo(tmp_path / "repo", specs)
    proc = _run(
        repo, "index-specs.py", "--validate", env=_env(DISPATCH_HUB_ROOT=str(fake))
    )
    assert proc.returncode == 0, proc.stderr
    assert "Deferral pointer warnings" not in proc.stderr


# covers hub-tooling FR-0026:AC-3
def test_pointer_check_skips_retired_frs_and_reads_status_exactly(tmp_path):
    hub = tmp_path / "hub"
    (hub / "scripts").mkdir(parents=True)
    (hub / "scripts" / "parking.py").write_text("", encoding="utf-8")
    lot = hub / "parking-lot"
    lot.mkdir()
    (lot / "IDEA-0001-a.md").write_text(
        "---\nid: IDEA-0001\nstatus: Archived\n---\n", encoding="utf-8"
    )
    (lot / "IDEA-0002-b.md").mkdir()  # a directory, not an IDEA file
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100",
            _body(_plain(3)),
            ac_state={
                1: "{state: deferred, moved_to: IDEA-0001}",
                2: "{state: deferred, moved_to: IDEA-0002}",
            },
        ),
        "FR-0101-b.md": _fr(
            "FR-0101",
            _body(_plain(1)),
            ac_state={1: "{state: deferred, moved_to: IDEA-0404}"},
            extra="lifecycle: superseded\n",
        ),
    }
    repo = _build_repo(tmp_path / "repo", specs)
    proc = _run(
        repo, "index-specs.py", "--validate", env=_env(DISPATCH_HUB_ROOT=str(hub))
    )
    assert proc.returncode == 0, proc.stderr
    assert _labelled_block(proc.stderr, "Deferral pointer warnings") == [
        "FR-0100 AC-2: moved_to IDEA-0002 not found in the hub parking lot"
    ]


# ---------------------------------------------------------------------------
# AC-4, AC-6, AC-15: opt-in, the gate's single entry point, the documentation
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-4
@pytest.mark.parametrize(
    "ac_state, opted_in",
    [
        ({9: {"state": "withdrawn", "moved_to": None, "reason": "x"}}, False),
        ({2: {"state": "superseded"}}, False),
        ({2: {"state": "deferred", "moved_to": "nonsense"}}, False),
        ({2: {"state": "Deferred", "moved_to": "IDEA-0001"}}, True),
        ({2: "deferred"}, True),
    ],
    ids=["no-text", "legacy-superseded", "unhonoured", "wrong-case", "scalar"],
)
def test_only_an_exact_exemption_state_stays_out_of_ratification_tracking(
    ac_state, opted_in
):
    fr = _make_fr({1: "a", 2: "b", 3: "c"}, ac_state)
    noisy = any("no ac_state entry for" in w for w in idx._ac_state_warnings([fr]))
    assert noisy is opted_in


# covers hub-tooling FR-0026:AC-6
def test_the_gate_names_one_indexer_function_and_none_of_its_helpers():
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    for helper in (
        "parse_withdrawn_acs",
        "withdrawn_acs",
        "MOVED_TO_PATTERN",
        "AC_EXEMPT_STATES",
        "WITHDRAWN_ACS_HEADING",
        "_exemption_problem",
        "_ac_state_report",
        "_PointerResolver",
        "collect_decs",
        "collect_adrs",
        "[P2]",
        "DEPRECATED",
    ):
        assert helper not in source, helper
    assert source.count("_index_specs.coverage_exemptions") == 1
    # Every FR gets an answer, managed or not, so the gate never guesses.
    frs = [
        _make_fr(_TWO, {}),
        _make_fr(
            _TWO, {2: {"state": "deferred", "moved_to": "IDEA-0001"}}, fr_id="FR-0101"
        ),
    ]
    answer = idx.coverage_exemptions(frs)
    assert set(answer) == {"FR-0100", "FR-0101"}
    assert answer["FR-0100"] == idx.CoverageExemptions()
    assert answer["FR-0101"].exempt == {2}


# covers hub-tooling FR-0026:AC-15
def test_the_readme_example_is_honoured_and_its_migration_steps_are_numbered():
    readme = (_TEMPLATE_DIR / "specs" / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Deferred, withdrawn and superseded ACs", 1)[1]
    section = section.split("\n## ", 1)[0]
    example = re.search(r"```yaml\n(.*?)```", section, flags=re.S)
    assert example is not None
    import yaml

    ac_state = yaml.safe_load(example.group(1))["ac_state"]
    fr = _make_fr({n: f"t{n}" for n in (9, 11)}, ac_state, {12: "t12"})
    successor = _make_fr({1: "x"}, {}, fr_id="FR-0011")
    answer = idx.coverage_exemptions([fr, successor])["FR-0100"]
    assert answer == idx.CoverageExemptions(exempt=frozenset({9, 11, 12}))
    migration = section.split("**Migrating a hand-written convention.**", 1)[1]
    steps = re.findall(r"^(\d+)\. ", migration, flags=re.M)
    assert steps == ["1", "2", "3", "4", "5"]


# ---------------------------------------------------------------------------
# Round 2: DEC-0029 item 6 (AC-2's self-pointer in every state; AC-5(a))
# ---------------------------------------------------------------------------


_SELF_CASES = [
    # (state, under Withdrawn?, expected warnings beyond none)
    ("deferred", False, []),
    ("deferred", True, ["FR-0100 AC-3: deferred ACs stay under Acceptance criteria"]),
    (
        "withdrawn",
        False,
        [
            "FR-0100 AC-3: withdrawn but still under Acceptance criteria; move it "
            "under ## Withdrawn acceptance criteria"
        ],
    ),
    ("withdrawn", True, []),
    (
        "superseded",
        False,
        [
            "FR-0100 AC-3: superseded but still under Acceptance criteria; move it "
            "under ## Withdrawn acceptance criteria"
        ],
    ),
    ("superseded", True, []),
]


# covers hub-tooling FR-0026:AC-2
# covers hub-tooling FR-0026:AC-5
@pytest.mark.parametrize(
    "state, withdrawn, expected",
    _SELF_CASES,
    ids=[f"{s}-{'withdrawn' if w else 'acs'}" for s, w, _ in _SELF_CASES],
)
def test_a_self_pointer_is_honoured_in_every_state_and_placement(
    state, withdrawn, expected
):
    """DEC-0029 item 6: a self-pointer is honoured in all three states, with no
    `reason` required when it is non-null. Placement warnings are the only
    ones, and a honoured deferral under the Withdrawn section gets (c), never
    (a)."""
    acs = {1: "Does one.", 2: "Does two."}
    wd = None
    if withdrawn:
        wd = {3: "Moved within this FR."}
    else:
        acs[3] = "Moved within this FR."
    fr = _make_fr(acs, {3: {"state": state, "moved_to": "FR-0100"}}, wd)
    assert _exempt(fr) == {3}
    assert _invalid(fr) == ()
    warnings = idx._ac_state_warnings([fr])
    assert warnings == expected
    assert not any("listed under Withdrawn" in w for w in warnings)


# covers hub-tooling FR-0026:AC-2
@pytest.mark.parametrize("value", ["fr-0100", "FR-0100 ", "FR-100", "FR-01000"])
def test_a_near_miss_self_pointer_is_not_honoured(value):
    fr = _make_fr(_TWO, {2: {"state": "superseded", "moved_to": value}})
    assert _exempt(fr) == frozenset()
    (msg,) = _invalid(fr)
    assert msg.startswith(f"FR-0100 AC-2: moved_to '{value}' is not ")


# covers hub-tooling FR-0026:AC-2
# covers hub-tooling FR-0026:AC-7
# covers hub-tooling FR-0026:AC-8
# covers hub-tooling FR-0026:AC-11
# covers hub-tooling FR-0026:AC-13
def test_self_pointers_through_the_gate_and_open_deferrals(tmp_path):
    """FR-0100 (merged): AC-1 covered; AC-2 superseded by another AC of this FR
    and still under Acceptance criteria; AC-3 withdrawn in the FR's own record,
    left in the legacy form and still covered by a test; AC-4 deferred to later
    in this FR and uncovered. FR-0101 (merged): its only AC self-superseded."""
    body = _body(
        [*_plain(2), "- **AC-4:** Later in this FR."],
        ["- **[DEPRECATED] AC-3** (withdrawn, see Changelog) Old text."],
    )
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100",
            body,
            status="merged",
            ac_state={
                2: "{state: superseded, moved_to: FR-0100, reason: AC-1 replaced it}",
                3: "{state: withdrawn, moved_to: FR-0100}",
                4: "{state: deferred, moved_to: FR-0100}",
            },
        ),
        "FR-0101-b.md": _fr(
            "FR-0101",
            _body(_plain(1)),
            status="merged",
            ac_state={1: "{state: superseded, moved_to: FR-0101}"},
        ),
    }
    repo = _build_repo(
        tmp_path,
        specs,
        files={
            "tests/test_x.py": _covers("FR-0100:AC-1", "FR-0100:AC-3"),
            **_implements("FR-0100", "FR-0101"),
        },
    )
    validate = _run(repo, "index-specs.py", "--validate")
    assert validate.returncode == 0, validate.stderr
    assert _labelled_block(validate.stderr, "AC ratification warnings") == [
        "FR-0100 AC-3: withdrawn but has no text in this FR; keep its original text "
        "under ## Withdrawn acceptance criteria",
        "FR-0100 AC-2: superseded but still under Acceptance criteria; move it "
        "under ## Withdrawn acceptance criteria",
        "FR-0101 AC-1: superseded but still under Acceptance criteria; move it "
        "under ## Withdrawn acceptance criteria",
    ]
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr
    assert "not in the FR" not in proc.stderr
    assert _block(proc.stderr, "Deploy gate WARNINGS:") == [
        "FR-0101 (merged): every AC is deferred, withdrawn or superseded; nothing "
        "in this FR is delivered"
    ]
    (rec,) = _records(repo)
    assert rec["outcome"] == "pass"
    assert rec["warning_classes"] == ["ac-format", "ac-all-exempt"]
    index = (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")
    rows = [
        ln
        for ln in index.split("## Open deferrals", 1)[1].splitlines()
        if ln.startswith("| [")
    ]
    assert rows == ["| [FR-0100](FR-0100-a.md) | AC-4 | `merged` | FR-0100 | — |"]
