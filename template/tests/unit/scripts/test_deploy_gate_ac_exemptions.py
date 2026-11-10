"""Gate tests for hub-tooling FR-0026: `deploy-gate.py` learns each FR's
honoured exemption entries from the indexer's `coverage_exemptions` (AC-6).
Check 2 accepts a covering annotation on an exempt AC (AC-7); check 3 skips
exempt ACs and nothing else (AC-8), so an exempt target never masks a live gap
(AC-9). An entry that is not honoured fails closed and is reported (AC-10); an
FR with no live AC is warned about (AC-11); both through two new warning
classes (AC-12). Unmanaged trees gate byte-identically to the base ref
(AC-14). The indexer's side lives in `test_index_specs_ac_exemptions.py`.

Gate behaviour runs through subprocess copies of the scripts in `tmp_path`;
one test loads a copy in-process to monkeypatch the exported function. The
base ref (`_BASE_REF`) is loaded with `git show` and those tests skip where hub
history is unreachable (a bootstrapped project has none).

Coverage annotations use the ride-along form `# covers hub-tooling
FR-0026:AC-N`: this file travels into every bootstrapped project, where no
FR-0026 exists. Fixture annotations are assembled at run time, so no gate
scanning this file reads them. Every fixture is synthetic
(`tests/fixtures/ac-exemptions/`).
"""

from __future__ import annotations

import contextlib
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
_BODIES = _TEMPLATE_DIR / "tests" / "fixtures" / "ac-exemptions" / "bodies"
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
# `main` at the commit FR-0026 was branched from: FR-0023 and FR-0027 merged.
_BASE_REF = "ddbe9e5"
# Split so a gate scanning this file never reads fixture strings as annotations.
_COVERS = "@" + "covers"
_IMPLEMENTS = "@" + "implements"
_LAYOUT = "project_name: demo\ngate:\n  test_dirs: [lib_tests]\n"
_NOT_HONOURED = "; not honoured, AC-{n} still requires coverage"


# ---------------------------------------------------------------------------
# Synthetic trees and subprocess harness
# ---------------------------------------------------------------------------


def _body(name: str) -> str:
    return (_BODIES / f"{name}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def _plain_body(n_acs: int = 3, withdrawn: list[str] | None = None) -> str:
    lines = ["", "# Synthetic FR", "", "## Acceptance criteria", ""]
    lines += [f"- **AC-{n}:** Does synthetic thing {n}." for n in range(1, n_acs + 1)]
    if withdrawn is not None:
        lines += ["", "## Withdrawn acceptance criteria", "", "Kept for history.", ""]
        lines += withdrawn
    return "\n".join(lines) + "\n"


def _fr(
    fr_id: str,
    body: str | None = None,
    *,
    status: str = "ready",
    ac_state: dict[int, str] | None = None,
    extra: str = "",
) -> str:
    """A synthetic FR file. `ac_state` maps AC number to a YAML flow mapping."""
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
        f"{body if body is not None else _plain_body()}"
    )


def _covers(*refs: str) -> str:
    return "".join(f"# {_COVERS} {r}\n" for r in refs)


def _qualified(project: str, *refs: str) -> str:
    return "".join(f"# covers {project} {r}\n" for r in refs)


def _implements(*fr_ids: str) -> dict[str, str]:
    """`src/` tags so `merged` FRs raise no `implements-missing` warning."""
    return {"src/impl.py": "".join(f"# {_IMPLEMENTS} {f}\n" for f in fr_ids)}


def _build_repo(
    base: Path,
    specs: dict[str, str],
    *,
    tests: str | None = None,
    scripts: dict[str, bytes] | None = None,
    extra: dict[str, str] | None = None,
) -> Path:
    repo = base
    (repo / "scripts").mkdir(parents=True)
    for name in _COPY_SCRIPTS:
        if scripts is not None:
            (repo / "scripts" / name).write_bytes(scripts[name])
        else:
            shutil.copy(_SCRIPTS_DIR / name, repo / "scripts" / name)
    files = {f"specs/{k}": v for k, v in specs.items()}
    if tests is not None:
        files["tests/test_synthetic.py"] = tests
    files.update(extra or {})
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    (repo / "specs").mkdir(exist_ok=True)
    return repo


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


def _gate(repo: Path, stage: str = "full"):  # type: ignore[no-untyped-def]
    return _run(repo, "deploy-gate.py", "--stage", stage)


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


def _last_record(repo: Path) -> dict:
    recs = [r for r in _records(repo) if r["kind"] == "gate.run"]
    assert recs, "no gate.run record"
    return recs[-1]


def _block(stderr: str, header: str) -> list[str]:
    """The `  - ` lines under a `Deploy gate WARNINGS:` / `FAILED:` header."""
    lines = stderr.splitlines()
    if header not in lines:
        return []
    out = []
    for ln in lines[lines.index(header) + 1 :]:
        if not ln.startswith("  - "):
            break
        out.append(ln[4:])
    return out


def _warnings(proc) -> list[str]:  # type: ignore[no-untyped-def]
    return _block(proc.stderr, "Deploy gate WARNINGS:")


def _failures(proc) -> list[str]:  # type: ignore[no-untyped-def]
    return _block(proc.stderr, "Deploy gate FAILED:")


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


_SUCCESSOR = {"FR-0101-successor.md": _fr("FR-0101")}


# ---------------------------------------------------------------------------
# AC-2 (gate side): only the IDEA pointer is honoured
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-2
def test_gate_honours_the_idea_pointer_and_not_the_dangling_local_ones(tmp_path):
    state = {
        1: "{state: superseded, moved_to: FR-0999}",
        2: "{state: withdrawn, moved_to: DEC-0999}",
        3: "{state: superseded, moved_to: ADR-0999}",
        4: "{state: deferred, moved_to: IDEA-0999}",
    }
    specs = {
        "FR-0100-a.md": _fr("FR-0100", _plain_body(4), status="merged", ac_state=state)
    }
    repo = _build_repo(tmp_path, specs, extra=_implements("FR-0100"))
    proc = _gate(repo)
    assert proc.returncode == 1
    assert _failures(proc) == ["FR-0100 (merged): no @covers test for AC-1, AC-2, AC-3"]
    assert [w for w in _warnings(proc)] == [
        f"FR-0100 AC-{n}: moved_to {ref} does not resolve in this project"
        + _NOT_HONOURED.format(n=n)
        for n, ref in ((1, "FR-0999"), (2, "DEC-0999"), (3, "ADR-0999"))
    ]


# ---------------------------------------------------------------------------
# AC-5 (gate side): each disagreement's coverage verdict follows ac_state
# ---------------------------------------------------------------------------


_W = "{state: withdrawn, moved_to: null, reason: Not needed}"
_D = "{state: deferred, moved_to: IDEA-0001}"

# (id, body, ac_state, missing ACs at --stage full; AC-1 and AC-2 are covered)
_SECTION_CASES = [
    ("a-no-entry", _plain_body(2, ["- **AC-3:** Withdrawn by hand."]), {}, [3]),
    (
        "a-not-honoured",
        _plain_body(2, ["- **AC-3:** Withdrawn by hand."]),
        {3: "{state: withdrawn}"},
        [3],
    ),
    ("b-still-under-acs", _plain_body(3), {3: _W}, []),
    (
        "c-deferred-under-withdrawn",
        _plain_body(2, ["- **AC-3:** Deferred."]),
        {3: _D},
        [],
    ),
    ("d-both-sections", _plain_body(3, ["- **AC-3:** Also here."]), {3: _W}, []),
    ("no-text", _plain_body(2), {3: _W}, []),
    (
        "legacy-line",
        _plain_body(2, ["- **[DEPRECATED] AC-3** (withdrawn) Old."]),
        {},
        [],
    ),
    (
        "labelled-withdrawn",
        _plain_body(2, ["- **AC-3 (moved):** Withdrawn."]),
        {3: _W},
        [],
    ),
]


# covers hub-tooling FR-0026:AC-5
@pytest.mark.parametrize(
    "body, state, missing",
    [c[1:] for c in _SECTION_CASES],
    ids=[c[0] for c in _SECTION_CASES],
)
def test_each_section_disagreement_gates_by_ac_state(tmp_path, body, state, missing):
    specs = {"FR-0100-a.md": _fr("FR-0100", body, status="merged", ac_state=state)}
    repo = _build_repo(
        tmp_path,
        specs,
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2"),
        extra=_implements("FR-0100"),
    )
    proc = _gate(repo)
    if missing:
        assert proc.returncode == 1
        listed = ", AC-".join(str(n) for n in missing)
        assert _failures(proc) == [f"FR-0100 (merged): no @covers test for AC-{listed}"]
    else:
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith("Deploy gate PASSED (stage=full)")


# covers hub-tooling FR-0026:AC-5
# covers hub-tooling FR-0026:AC-7
def test_labelled_withdrawn_bullet_is_parsed_without_warning_and_its_covers_pass(
    tmp_path,
):
    body = _plain_body(2, ["- **AC-3 (moved):** Withdrawn, labelled."])
    specs = {"FR-0100-a.md": _fr("FR-0100", body, status="merged", ac_state={3: _W})}
    repo = _build_repo(
        tmp_path,
        specs,
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-3"),
        extra=_implements("FR-0100"),
    )
    indexed = _run(repo, "index-specs.py")
    assert indexed.returncode == 0, indexed.stderr
    assert "## AC ratification warnings" not in (repo / "specs" / "INDEX.md").read_text(
        encoding="utf-8"
    )
    for stage in ("dev", "full"):
        proc = _gate(repo, stage)
        assert proc.returncode == 0, proc.stderr
        assert "covers-unknown-ac" not in proc.stderr and _warnings(proc) == []


# ---------------------------------------------------------------------------
# AC-6: the gate learns exemptions from the indexer, not from the body
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-6
def test_gate_binds_the_exported_function_and_adds_no_forbidden_token():
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    assert "coverage_exemptions = _index_specs.coverage_exemptions" in source
    for token in (
        "spec_query",
        "in_default_view",
        "collect_trs",
        "collect_decs",
        "collect_graph",
        "DEC(",
        "TR(",
        "is_live_dec",
        # It reads no `ac_state`, no section and no AC-text tag of its own.
        ".ac_state",
        '"moved_to"',
        "Withdrawn acceptance criteria",
        "[P2]",
        "[DEPRECATED]",
    ):
        assert token not in source, token
    assert "retired" not in source.lower()
    # The detection FR-0027 left is untouched.
    assert (
        "ac_nums |= {int(m.group(1)) for m in AC_LABELLED_PATTERN.finditer(body)}"
        in source
    )


# covers hub-tooling FR-0026:AC-6
def test_check_3_follows_the_exported_function_not_the_body(
    tmp_path, monkeypatch, capsys
):
    specs = {"FR-0100-a.md": _fr("FR-0100", _plain_body(2), status="merged")}
    repo = _build_repo(
        tmp_path, specs, tests=_covers("FR-0100:AC-1"), extra=_implements("FR-0100")
    )
    monkeypatch.setenv("METRICS_LOG_DISABLED", "1")
    monkeypatch.delenv("DISPATCH_HUB_ROOT", raising=False)
    gate = _load(repo / "scripts" / "deploy-gate.py", "fr0026_gate_under_test")
    monkeypatch.setattr(sys, "argv", ["deploy-gate.py", "--stage", "full"])
    assert gate.main() == 1
    assert "FR-0100 (merged): no @covers test for AC-2" in capsys.readouterr().err
    fixed = gate._index_specs.CoverageExemptions(exempt=frozenset({2}))
    monkeypatch.setattr(gate, "coverage_exemptions", lambda frs: {"FR-0100": fixed})
    assert gate.main() == 0
    captured = capsys.readouterr()
    assert "no @covers test" not in captured.err
    assert captured.out.startswith("Deploy gate PASSED (stage=full)")


# covers hub-tooling FR-0026:AC-6
def test_coverage_exemptions_ignores_body_tags_and_sections():
    idx = _load(_SCRIPTS_DIR / "index-specs.py", "fr0026_gate_side_index_specs")
    fr = idx.FR(
        path=Path("FR-0100.md"),
        id="FR-0100",
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
        acs={1: "[P2] later", 2: "[DEPRECATED] old"},
        ac_state={},
        withdrawn_acs={3: "withdrawn text"},
    )
    assert idx.coverage_exemptions([fr]) == {"FR-0100": idx.CoverageExemptions()}


# ---------------------------------------------------------------------------
# AC-7: check 2 accepts a covering annotation on an exempt AC
# ---------------------------------------------------------------------------


def _check2_tree(entry: str, withdrawn_line: str) -> dict[str, str]:
    body = _plain_body(2, [withdrawn_line])
    return {
        "FR-0100-a.md": _fr("FR-0100", body, status="merged", ac_state={9: entry}),
        **_SUCCESSOR,
    }


_LEGACY_9 = "- **[DEPRECATED] AC-9** (superseded by the successor) Old synthetic text."


# covers hub-tooling FR-0026:AC-7
@pytest.mark.parametrize("stage", ["dev", "full"])
@pytest.mark.parametrize(
    "entry, line",
    [
        (_W, "- **AC-9:** Withdrawn synthetic text."),
        ("{state: superseded, moved_to: FR-0101}", _LEGACY_9),
    ],
    ids=["withdrawn-plain-form", "superseded-legacy-form"],
)
def test_covers_on_a_honoured_exempt_ac_passes_check_2(tmp_path, stage, entry, line):
    repo = _build_repo(
        tmp_path,
        _check2_tree(entry, line),
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-9"),
        extra=_implements("FR-0100"),
    )
    proc = _gate(repo, stage)
    assert proc.returncode == 0, proc.stderr
    assert "not in the FR" not in proc.stderr and _warnings(proc) == []
    assert proc.stdout.startswith(
        f"Deploy gate PASSED (stage={stage}): 2 FRs, 3 @covers"
    )


# covers hub-tooling FR-0026:AC-7
@pytest.mark.parametrize("stage", ["dev", "full"])
def test_covers_on_an_unhonoured_legacy_ac_still_fails_covers_unknown_ac(
    tmp_path, stage
):
    repo = _build_repo(
        tmp_path,
        _check2_tree("{state: withdrawn}", _LEGACY_9),
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-9"),
        extra=_implements("FR-0100"),
    )
    proc = _gate(repo, stage)
    assert proc.returncode == 1
    assert "@covers references FR-0100:AC-9 but that AC is not in the FR" in _failures(
        proc
    )
    rec = _last_record(repo)
    assert "covers-unknown-ac" in rec["failure_classes"]


# covers hub-tooling FR-0026:AC-7
@pytest.mark.parametrize("stage", ["dev", "full"])
def test_qualified_annotation_in_layout_test_dirs_passes_check_2_on_an_exempt_ac(
    tmp_path, stage
):
    lib = _covers("FR-0100:AC-1") + _qualified("demo", "FR-0100:AC-2", "FR-0100:AC-9")
    repo = _build_repo(
        tmp_path,
        _check2_tree("{state: superseded, moved_to: FR-0101}", _LEGACY_9),
        extra={
            ".agent-team/layout.yaml": _LAYOUT,
            "lib_tests/test_lib.py": lib,
            **_implements("FR-0100"),
        },
    )
    proc = _gate(repo, stage)
    assert proc.returncode == 0, proc.stderr
    assert "not in the FR" not in proc.stderr


# ---------------------------------------------------------------------------
# AC-8: check 3 skips honoured exempt ACs and nothing else
# ---------------------------------------------------------------------------


_EXEMPT_ENTRIES = {
    "deferred": ("{state: deferred, moved_to: IDEA-0001}", None),
    "withdrawn": (_W, "- **AC-2:** Withdrawn synthetic thing."),
    "superseded": (
        "{state: superseded, moved_to: FR-0101}",
        "- **AC-2:** Superseded synthetic thing.",
    ),
}


def _check3_tree(state: str, status: str = "merged") -> dict[str, str]:
    entry, withdrawn_line = _EXEMPT_ENTRIES[state]
    if withdrawn_line is None:
        body = _plain_body(3)
    else:
        body = _plain_body(1, [withdrawn_line]).replace(
            "\n\n## Withdrawn", "\n- **AC-3:** Does synthetic thing 3.\n\n## Withdrawn"
        )
    return {
        "FR-0100-a.md": _fr("FR-0100", body, status=status, ac_state={2: entry}),
        **_SUCCESSOR,
    }


# covers hub-tooling FR-0026:AC-8
@pytest.mark.parametrize("stage", ["review", "full"])
@pytest.mark.parametrize("state", sorted(_EXEMPT_ENTRIES))
def test_check_3_skips_the_exempt_ac_and_lists_only_live_gaps(tmp_path, state, stage):
    covered = _build_repo(
        tmp_path / "covered",
        _check3_tree(state),
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-3"),
        extra=_implements("FR-0100"),
    )
    proc = _gate(covered, stage)
    assert proc.returncode == 0, proc.stderr
    gap = _build_repo(
        tmp_path / "gap",
        _check3_tree(state, status="in-review"),
        tests=_covers("FR-0100:AC-1"),
        extra=_implements("FR-0100"),
    )
    proc = _gate(gap, stage)
    assert proc.returncode == 1
    assert _failures(proc) == ["FR-0100 (in-review): no @covers test for AC-3"]


# covers hub-tooling FR-0026:AC-8
def test_dev_stage_still_skips_check_3(tmp_path):
    repo = _build_repo(tmp_path, _check3_tree("deferred"), extra=_implements("FR-0100"))
    proc = _gate(repo, "dev")
    assert proc.returncode == 0, proc.stderr


# covers hub-tooling FR-0026:AC-8
def test_merged_fr_passes_whatever_number_of_deferrals(tmp_path):
    state = {n: "{state: deferred, moved_to: IDEA-0001}" for n in (2, 3, 4, 5)}
    specs = {
        "FR-0100-a.md": _fr("FR-0100", _plain_body(5), status="merged", ac_state=state)
    }
    repo = _build_repo(
        tmp_path, specs, tests=_covers("FR-0100:AC-1"), extra=_implements("FR-0100")
    )
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr


# covers hub-tooling FR-0026:AC-8
def test_layout_qualified_covers_count_and_a_deferral_with_no_annotation_is_not_listed(
    tmp_path,
):
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100",
            _plain_body(3),
            status="merged",
            ac_state={3: "{state: deferred, moved_to: IDEA-0001}"},
        )
    }
    extra = {".agent-team/layout.yaml": _LAYOUT, **_implements("FR-0100")}
    # tests/ is not scanned under this layout: an annotation there counts for nothing.
    repo = _build_repo(
        tmp_path / "gap",
        specs,
        tests=_covers("FR-0100:AC-2"),
        extra={**extra, "lib_tests/test_lib.py": _covers("FR-0100:AC-1")},
    )
    proc = _gate(repo)
    assert proc.returncode == 1
    assert _failures(proc) == ["FR-0100 (merged): no @covers test for AC-2"]
    repo = _build_repo(
        tmp_path / "ok",
        specs,
        extra={
            **extra,
            "lib_tests/test_lib.py": _covers("FR-0100:AC-1")
            + _qualified("demo", "FR-0100:AC-2"),
        },
    )
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# AC-9: adversarial — an exempt target never masks a live gap
# ---------------------------------------------------------------------------


def _ac9_specs(status: str = "in-review", entry: bool = True) -> dict[str, str]:
    state = {2: "{state: deferred, moved_to: IDEA-0001}"} if entry else None
    return {
        "FR-0100-adv.md": _fr(
            "FR-0100", _body("adversarial"), status=status, ac_state=state
        )
    }


# covers hub-tooling FR-0026:AC-9
def test_adversarial_exempt_target_never_masks_a_live_gap(tmp_path):
    repo = _build_repo(
        tmp_path / "r",
        _ac9_specs(),
        tests=_covers("FR-0100:AC-2", "FR-0100:AC-3"),
        extra=_implements("FR-0100"),
    )
    proc = _gate(repo)
    assert proc.returncode == 1
    assert _failures(proc) == ["FR-0100 (in-review): no @covers test for AC-1"]
    assert "covers-unknown-ac" not in proc.stderr and "not in the FR" not in proc.stderr
    rec = _last_record(repo)
    assert rec["failure_classes"] == ["coverage-missing"]
    assert rec["object_ids"] == ["FR-0100"]

    # Cover AC-1 and merge: the gate passes.
    (repo / "tests" / "test_ac1.py").write_text(
        _covers("FR-0100:AC-1"), encoding="utf-8"
    )
    (repo / "specs" / "FR-0100-adv.md").write_text(
        _ac9_specs("merged")["FR-0100-adv.md"], encoding="utf-8"
    )
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("Deploy gate PASSED (stage=full): ")

    # Delete AC-2's entry: still green, because AC-2 is covered.
    (repo / "specs" / "FR-0100-adv.md").write_text(
        _ac9_specs("merged", entry=False)["FR-0100-adv.md"], encoding="utf-8"
    )
    proc = _gate(repo)
    assert proc.returncode == 0, proc.stderr


# covers hub-tooling FR-0026:AC-9
def test_bite_the_base_gate_differs_only_on_the_exempt_ac(tmp_path):
    base = _base_scripts()
    outcomes = {}
    for label, refs in (
        ("with-ac2-test", ("FR-0100:AC-2", "FR-0100:AC-3")),
        ("without", ("FR-0100:AC-3",)),
    ):
        for side, scripts in (("base", base), ("new", None)):
            repo = _build_repo(
                tmp_path / f"{label}-{side}",
                _ac9_specs(),
                tests=_covers(*refs),
                scripts=scripts,
                extra=_implements("FR-0100"),
            )
            proc = _gate(repo)
            outcomes[label, side] = (proc.returncode, _failures(proc))
    # With AC-2's test the exemption changes nothing.
    assert outcomes["with-ac2-test", "base"] == outcomes["with-ac2-test", "new"]
    # Without it, the base gate also wants AC-2; the new gate wants only AC-1.
    assert outcomes["without", "base"] == (
        1,
        ["FR-0100 (in-review): no @covers test for AC-1, AC-2"],
    )
    assert outcomes["without", "new"] == (
        1,
        ["FR-0100 (in-review): no @covers test for AC-1"],
    )


# ---------------------------------------------------------------------------
# AC-10: a not-honoured exemption entry fails closed and is reported
# ---------------------------------------------------------------------------


_UNHONOURED = [
    ("moved-to-absent", "{state: deferred}", "needs moved_to"),
    (
        "moved-to-malformed",
        "{state: deferred, moved_to: IDEA-49}",
        "moved_to 'IDEA-49' is not",
    ),
    ("null-no-reason", "{state: withdrawn, moved_to: null}", "no reason"),
    (
        "superseded-null",
        "{state: superseded, moved_to: null, reason: gone}",
        "superseded needs a non-null",
    ),
    (
        "dangling-fr",
        "{state: superseded, moved_to: FR-0999}",
        "FR-0999 does not resolve",
    ),
    (
        "dangling-dec",
        "{state: withdrawn, moved_to: DEC-0999}",
        "DEC-0999 does not resolve",
    ),
    (
        "dangling-adr",
        "{state: superseded, moved_to: ADR-0999}",
        "ADR-0999 does not resolve",
    ),
]


# covers hub-tooling FR-0026:AC-10
# covers hub-tooling FR-0026:AC-12
@pytest.mark.parametrize(
    "entry, needle", [c[1:] for c in _UNHONOURED], ids=[c[0] for c in _UNHONOURED]
)
def test_unhonoured_entry_fails_closed_with_a_warning_and_both_classes(
    tmp_path, entry, needle
):
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100", _plain_body(2), status="merged", ac_state={2: entry}
        )
    }
    repo = _build_repo(
        tmp_path, specs, tests=_covers("FR-0100:AC-1"), extra=_implements("FR-0100")
    )
    proc = _gate(repo)
    assert proc.returncode == 1
    assert _failures(proc) == ["FR-0100 (merged): no @covers test for AC-2"]
    [w] = _warnings(proc)
    assert (
        w.startswith("FR-0100 AC-2: ")
        and needle in w
        and w.endswith(_NOT_HONOURED.format(n=2))
    ), w
    rec = _last_record(repo)
    assert rec["failure_classes"] == ["coverage-missing"]
    assert rec["warning_classes"] == ["ac-exemption-invalid"]


# covers hub-tooling FR-0026:AC-10
@pytest.mark.parametrize("stage", ["dev", "review"])
def test_unhonoured_entry_is_reported_at_every_stage_once_per_run(tmp_path, stage):
    state = {1: "{state: deferred}", 2: "{state: withdrawn, moved_to: null}"}
    specs = {"FR-0100-a.md": _fr("FR-0100", _plain_body(2), ac_state=state)}
    repo = _build_repo(tmp_path, specs)
    proc = _gate(repo, stage)
    assert proc.returncode == 0, proc.stderr
    assert len([w for w in _warnings(proc) if "not honoured" in w]) == 2
    assert _last_record(repo)["warning_classes"] == ["ac-exemption-invalid"]


# ---------------------------------------------------------------------------
# AC-11: an FR with no live AC gets a warning, not a failure
# ---------------------------------------------------------------------------


_ALL_DEFERRED = {n: "{state: deferred, moved_to: IDEA-0001}" for n in (1, 2, 3)}


# covers hub-tooling FR-0026:AC-11
# covers hub-tooling FR-0026:AC-12
@pytest.mark.parametrize("stage", ["review", "full"])
def test_all_exempt_merged_fr_warns_and_passes(tmp_path, stage):
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100", _plain_body(3), status="merged", ac_state=_ALL_DEFERRED
        )
    }
    repo = _build_repo(tmp_path, specs, extra=_implements("FR-0100"))
    proc = _gate(repo, stage)
    assert proc.returncode == 0, proc.stderr
    assert _warnings(proc) == [
        "FR-0100 (merged): every AC is deferred, withdrawn or superseded; nothing in this FR is delivered"
    ]
    rec = _last_record(repo)
    assert rec["outcome"] == "pass" and rec["warning_classes"] == ["ac-all-exempt"]


# covers hub-tooling FR-0026:AC-11
def test_all_exempt_warning_is_not_raised_at_dev_or_for_an_fr_with_no_acs(tmp_path):
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100", _plain_body(3), status="merged", ac_state=_ALL_DEFERRED
        ),
        "FR-0102-empty.md": _fr("FR-0102", _plain_body(0), status="merged"),
    }
    repo = _build_repo(tmp_path, specs, extra=_implements("FR-0100", "FR-0102"))
    proc = _gate(repo, "dev")
    assert proc.returncode == 0, proc.stderr
    assert _warnings(proc) == [] and _last_record(repo)["warning_classes"] == []
    proc = _gate(repo, "full")
    assert proc.returncode == 0, proc.stderr
    assert [w for w in _warnings(proc) if "FR-0102" in w] == []


# ---------------------------------------------------------------------------
# AC-12: two new warning classes; nothing else in the schema moves
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-12
def test_two_warning_classes_join_the_enum_through_literal_warn_calls():
    metrics_log = _load(_SCRIPTS_DIR / "metrics_log.py", "fr0026_metrics_log")
    assert metrics_log.GATE_WARNING_CLASSES == {
        "implements-missing",
        "implements-unknown-fr",
        "ac-format",
        "ac-exemption-invalid",
        "ac-all-exempt",
    }
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    assert 'report.warn("ac-exemption-invalid")' in source
    assert 'report.warn("ac-all-exempt")' in source
    assert (
        set(re.findall(r'report\.warn\("([a-z-]+)"', source))
        == metrics_log.GATE_WARNING_CLASSES
    )
    readme = (_TEMPLATE_DIR / "specs" / "_metrics" / "README.md").read_text(
        encoding="utf-8"
    )
    [row] = [ln for ln in readme.splitlines() if ln.startswith("| `warning_classes` |")]
    for cls in ("ac-exemption-invalid", "ac-all-exempt"):
        assert f"`{cls}` (hub-tooling FR-0026" in row, cls


# covers hub-tooling FR-0026:AC-12
def test_failure_classes_kinds_and_counts_do_not_move(tmp_path):
    d = tmp_path / "base-scripts"
    d.mkdir()
    for name, data in _base_scripts().items():
        (d / name).write_bytes(data)
    old = _load(d / "metrics_log.py", "fr0026_metrics_log_base")
    new = _load(_SCRIPTS_DIR / "metrics_log.py", "fr0026_metrics_log_new")
    assert new.GATE_FAILURE_CLASSES == old.GATE_FAILURE_CLASSES
    assert new.KINDS == old.KINDS and new.KIND_REQUIRED == old.KIND_REQUIRED
    assert new.GATE_WARNING_CLASSES - old.GATE_WARNING_CLASSES == {
        "ac-exemption-invalid",
        "ac-all-exempt",
    }
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100", _plain_body(3), status="merged", ac_state=_ALL_DEFERRED
        )
    }
    repo = _build_repo(tmp_path / "r", specs, extra=_implements("FR-0100"))
    assert _gate(repo).returncode == 0
    assert set(_last_record(repo)["counts"]) == {"frs", "covers", "implements"}


# ---------------------------------------------------------------------------
# AC-14: unmanaged FRs gate exactly as at the base ref
# ---------------------------------------------------------------------------


def _unmanaged_specs() -> dict[str, str]:
    """aitk-shaped, all unmanaged: the legacy `[DEPRECATED]` section, a `[P2]`
    live AC, the three-AC supersession, and an FR with no `ac_state` key."""
    return {
        "FR-0011-successor.md": _fr("FR-0011"),
        "FR-0100-legacy.md": _fr("FR-0100", _body("legacy-withdrawn"), status="merged"),
        "FR-0101-p2.md": _fr("FR-0101", _body("p2-live"), status="in-review"),
        "FR-0102-moved.md": _fr(
            "FR-0102", _body("three-ac-supersession"), status="merged"
        ),
        "FR-0103-nokey.md": _fr("FR-0103").replace("ac_state: {}\n", ""),
    }


# AC-2 of FR-0100 is uncovered (check 3 fails), and a test still covers the
# legacy-form FR-0102 AC-3 (check 2 fails `covers-unknown-ac`, as today).
_UNMANAGED_COVERS = (
    "FR-0100:AC-1",
    "FR-0101:AC-1",
    "FR-0101:AC-2",
    "FR-0101:AC-3",
    "FR-0102:AC-1",
    "FR-0102:AC-2",
    "FR-0102:AC-3",
)


def _strip_volatile(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in ("ts", "record_id")}


# covers hub-tooling FR-0026:AC-14
@pytest.mark.parametrize("layout", [False, True], ids=["no-layout", "layout"])
@pytest.mark.parametrize("stage", ["dev", "review", "full"])
def test_unmanaged_tree_gates_byte_identically_to_the_base_ref(tmp_path, stage, layout):
    base = _base_scripts()
    runs = {}
    for side, scripts in (("old", base), ("new", None)):
        if layout:
            half = len(_UNMANAGED_COVERS) // 2
            lib = _covers(*_UNMANAGED_COVERS[:half]) + _qualified(
                "demo", *_UNMANAGED_COVERS[half:]
            )
            kw = {
                "extra": {
                    ".agent-team/layout.yaml": _LAYOUT,
                    "lib_tests/test_lib.py": lib,
                }
            }
        else:
            kw = {"tests": _covers(*_UNMANAGED_COVERS)}
        repo = _build_repo(tmp_path / side, _unmanaged_specs(), scripts=scripts, **kw)
        proc = _gate(repo, stage)
        runs[side] = (repo, proc)
    (old, p_old), (new, p_new) = runs["old"], runs["new"]
    assert p_new.returncode == p_old.returncode == 1
    assert p_new.stdout == p_old.stdout
    assert p_new.stderr.replace(str(new), "<repo>") == p_old.stderr.replace(
        str(old), "<repo>"
    )
    assert (
        "@covers references FR-0102:AC-3 but that AC is not in the FR" in p_new.stderr
    )
    assert [_strip_volatile(r) for r in _records(new)] == [
        _strip_volatile(r) for r in _records(old)
    ]
    assert (new / "specs" / "INDEX.md").read_bytes() == (
        old / "specs" / "INDEX.md"
    ).read_bytes()


# covers hub-tooling FR-0026:AC-14
@pytest.mark.parametrize("stage", ["dev", "full"])
def test_legacy_superseded_entry_keeps_its_verdict_and_gains_only_a_warning(
    tmp_path, stage
):
    specs = {
        "FR-0011-successor.md": _fr("FR-0011"),
        "FR-0100-legacy.md": _fr(
            "FR-0100",
            _body("three-ac-supersession"),
            status="merged",
            ac_state={3: "{state: superseded}"},
        ),
    }
    covers = _covers("FR-0100:AC-1", "FR-0100:AC-3")
    runs = {}
    for side, scripts in (("old", _base_scripts()), ("new", None)):
        repo = _build_repo(tmp_path / side, specs, tests=covers, scripts=scripts)
        runs[side] = _gate(repo, stage)
    p_old, p_new = runs["old"], runs["new"]
    assert p_new.returncode == p_old.returncode == 1
    assert _failures(p_new) == _failures(p_old)
    assert "@covers references FR-0100:AC-3 but that AC is not in the FR" in _failures(
        p_new
    )
    gained = [w for w in _warnings(p_new) if w not in _warnings(p_old)]
    assert gained == [
        "FR-0100 AC-3: superseded needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, DEC-NNNN, "
        "or null with a reason)" + _NOT_HONOURED.format(n=3)
    ]
