"""Indexer tests for hub-tooling FR-0026: an `ac_state` entry in `deferred`,
`withdrawn` or `superseded`, with a `moved_to` pointer, is an exemption entry.

`index-specs.py` validates the entry's shape (AC-1) and resolves local
pointers (AC-2), warn-only; checks IDEA pointers against the hub parking lot
on stderr when a hub is found (AC-3); does not opt an FR into ratification
tracking for an exemption alone (AC-4); parses `## Withdrawn acceptance
criteria` and warns where it disagrees with `ac_state` (AC-5); lists every
open deferral in `INDEX.md` (AC-13); leaves unmanaged trees byte-identical to
the base ref (AC-14); and the FR template and `specs/README.md` document the
rule (AC-15). The gate's side lives in `test_deploy_gate_ac_exemptions.py`.

Pure checks drive the loaded module (`_ac_state_warnings`, the in-memory `FR`
double). CLI behaviour runs subprocess copies of the scripts in `tmp_path`.
The hub lookup is isolated by pointing `DISPATCH_HUB_ROOT` at a synthetic hub
under `tmp_path`, or by removing it from the environment. The AC-14 base-ref
comparison loads `_BASE_REF`'s scripts with `git show` and skips where hub
history is unreachable (a bootstrapped project has none).

Coverage annotations use the ride-along form `# covers hub-tooling
FR-0026:AC-N`: this file travels into every bootstrapped project, where no
FR-0026 exists. Every fixture is synthetic (`tests/fixtures/ac-exemptions/`).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
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
_NOT_HONOURED = "; not honoured, AC-{n} still requires coverage"


# ---------------------------------------------------------------------------
# Module under test
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


idx = _load(_SCRIPTS_DIR / "index-specs.py", "fr0026_index_specs")


def _make_fr(
    fr_id: str,
    acs: dict[int, str],
    ac_state: dict,
    withdrawn_acs: dict[int, str] | None = None,
):  # type: ignore[no-untyped-def]
    """An in-memory `FR`, like `test_index_specs.py`'s `_make_fr` double."""
    kwargs = {} if withdrawn_acs is None else {"withdrawn_acs": withdrawn_acs}
    return idx.FR(
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
        acs=acs,
        ac_state=ac_state,
        **kwargs,
    )


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


def _dec(dec_id: str) -> str:
    return (
        "---\n"
        f"id: {dec_id}\n"
        f"title: Synthetic {dec_id}\n"
        "tier: agent\n"
        "status: ratified\n"
        "revises: null\n"
        f"rationale: Synthetic decision {dec_id}.\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n"
        f"# {dec_id}: Synthetic\n"
    )


def _adr(adr_id: str) -> str:
    return (
        "---\n"
        f"id: {adr_id}\n"
        f"title: Synthetic {adr_id}\n"
        "status: accepted\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n"
        f"# {adr_id}: Synthetic\n\n"
        "## When you may deviate\n\nx\n\n"
        "## What you must record when you deviate\n\nx\n"
    )


def _build_repo(
    base: Path,
    specs: dict[str, str],
    *,
    tests: dict[str, str] | None = None,
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
    for folder, files in (("specs", specs), ("tests", tests or {}), (".", extra or {})):
        (repo / folder).mkdir(exist_ok=True)
        for rel, content in files.items():
            target = repo / folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
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


def _index(repo: Path) -> str:
    return (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> list[str]:
    """The `- ` lines of one `## <heading>` section of INDEX.md."""
    if f"\n## {heading}\n" not in text:
        return []
    body = text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return [ln[2:] for ln in body.splitlines() if ln.startswith("- ")]


def _stderr_block(stderr: str, label: str) -> list[str]:
    """The `  - ` lines under `<label> (<n>):` on stderr."""
    lines = stderr.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(f"{label} ("):
            out = []
            for nxt in lines[i + 1 :]:
                if not nxt.startswith("  - "):
                    break
                out.append(nxt[4:])
            assert len(out) == int(ln[len(label) + 2 : ln.index(")")]), ln
            return out
    return []


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
# AC-1: two new states and one entry shape
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-1
def test_ac_states_gain_deferred_and_withdrawn():
    assert idx.AC_STATES == {
        "proposed",
        "refined",
        "client-review",
        "ratified",
        "superseded",
        "deferred",
        "withdrawn",
    }


_SHAPE_FAILURES = [
    ("moved-to-absent", {"state": "deferred"}, "needs moved_to"),
    ("moved-to-absent-superseded", {"state": "superseded"}, "needs moved_to"),
    ("moved-to-int", {"state": "deferred", "moved_to": 49}, "moved_to '49' is not"),
    (
        "moved-to-short",
        {"state": "withdrawn", "moved_to": "IDEA-49"},
        "moved_to 'IDEA-49' is not",
    ),
    (
        "moved-to-lowercase",
        {"state": "deferred", "moved_to": "idea-0049"},
        "'idea-0049'",
    ),
    (
        "moved-to-other-kind",
        {"state": "superseded", "moved_to": "TR-0001"},
        "'TR-0001'",
    ),
    (
        "moved-to-trailing-newline",
        {"state": "deferred", "moved_to": "IDEA-0049\n"},
        "is not",
    ),
    (
        "moved-to-unicode-digits",
        {"state": "deferred", "moved_to": "IDEA-١٢٣٤"},
        "is not",
    ),
    ("moved-to-list", {"state": "deferred", "moved_to": ["IDEA-0049"]}, "is not"),
    ("null-no-reason", {"state": "deferred", "moved_to": None}, "no reason"),
    (
        "null-blank-reason",
        {"state": "withdrawn", "moved_to": None, "reason": "  \n"},
        "no reason",
    ),
    (
        "null-non-string-reason",
        {"state": "withdrawn", "moved_to": None, "reason": 7},
        "no reason",
    ),
    (
        "superseded-null",
        {"state": "superseded", "moved_to": None, "reason": "Replaced"},
        "superseded needs a non-null moved_to",
    ),
]


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize(
    "entry, needle",
    [c[1:] for c in _SHAPE_FAILURES],
    ids=[c[0] for c in _SHAPE_FAILURES],
)
def test_each_malformed_exemption_entry_warns_and_is_not_honoured(entry, needle):
    fr = _make_fr("FR-0100", {1: "a", 2: "b"}, {1: entry})
    warnings = idx._ac_state_warnings([fr])
    assert len(warnings) == 1, warnings
    [w] = warnings
    assert w.startswith("FR-0100 AC-1: ") and w.endswith(_NOT_HONOURED.format(n=1)), w
    assert needle in w, w
    assert idx.coverage_exemptions([fr]) == {
        "FR-0100": idx.CoverageExemptions(exempt=frozenset(), invalid=(w,))
    }


_HONOURED = [
    ("deferred-idea", {"state": "deferred", "moved_to": "IDEA-0049"}),
    ("deferred-own-fr", {"state": "deferred", "moved_to": "FR-0100"}),
    (
        "deferred-null-reason",
        {"state": "deferred", "moved_to": None, "reason": "Pilot first"},
    ),
    (
        "withdrawn-null-reason",
        {"state": "withdrawn", "moved_to": None, "reason": "Not needed"},
    ),
    (
        "extra-keys-ignored",
        {
            "state": "deferred",
            "moved_to": "IDEA-0049",
            "source": "x",
            "ratified": None,
            "hash": None,
            "colour": "blue",
        },
    ),
]


# covers hub-tooling FR-0026:AC-1
# covers hub-tooling FR-0026:AC-2
@pytest.mark.parametrize(
    "entry", [c[1] for c in _HONOURED], ids=[c[0] for c in _HONOURED]
)
def test_well_formed_exemption_entries_are_honoured_without_a_warning(entry):
    if entry["state"] == "deferred":
        fr = _make_fr("FR-0100", {1: "a", 2: "b"}, {1: entry})
    else:  # its text sits under the Withdrawn section (AC-5)
        fr = _make_fr("FR-0100", {2: "b"}, {1: entry}, withdrawn_acs={1: "a"})
    assert idx._ac_state_warnings([fr]) == []
    assert idx.coverage_exemptions([fr])["FR-0100"].exempt == frozenset({1})


# covers hub-tooling FR-0026:AC-1
@pytest.mark.parametrize("state", ["proposed", "ratified", "refined"])
def test_moved_to_on_a_non_exemption_state_is_ignored_with_a_warning(state):
    entry = {"state": state, "moved_to": "IDEA-0049"}
    if state == "ratified":
        entry["hash"] = idx.ac_hash("a")
    fr = _make_fr("FR-0100", {1: "a"}, {1: entry})
    assert idx._ac_state_warnings([fr]) == [
        "FR-0100 AC-1: moved_to applies only to deferred, withdrawn or superseded; ignored"
    ]
    assert idx.coverage_exemptions([fr])["FR-0100"].exempt == frozenset()


# covers hub-tooling FR-0026:AC-1
def test_malformed_entries_warn_in_index_md_and_on_stderr_in_both_modes_and_exit_0(
    tmp_path,
):
    state = {
        1: "{state: deferred}",
        2: "{state: withdrawn, moved_to: 42}",
        3: "{state: deferred, moved_to: null}",
        4: "{state: superseded, moved_to: null, reason: gone}",
        5: "{state: proposed, moved_to: IDEA-0001}",
    }
    repo = _build_repo(
        tmp_path, {"FR-0100-a.md": _fr("FR-0100", _plain_body(5), ac_state=state)}
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    index_lines = _section(_index(repo), "AC ratification warnings")
    on_stderr = _stderr_block(proc.stderr, "AC ratification warnings")
    assert index_lines == on_stderr
    for n in (1, 2, 3, 4):
        [w] = [w for w in index_lines if w.startswith(f"FR-0100 AC-{n}: ")]
        assert w.endswith(_NOT_HONOURED.format(n=n)), w
    assert "FR-0100 AC-2: moved_to '42' is not" in "\n".join(index_lines)
    assert (
        "FR-0100 AC-5: moved_to applies only to deferred, withdrawn or superseded; ignored"
        in index_lines
    )
    validate = _run(repo, "index-specs.py", "--validate")
    assert validate.returncode == 0, validate.stderr
    assert _stderr_block(validate.stderr, "AC ratification warnings") == [
        w for w in index_lines if "no ac_state entry" not in w
    ]


# ---------------------------------------------------------------------------
# AC-2: local pointers must resolve; IDEA pointers are shape-checked only
# ---------------------------------------------------------------------------


def _dangling_tree() -> dict[str, str]:
    state = {
        1: "{state: superseded, moved_to: FR-0999}",
        2: "{state: withdrawn, moved_to: DEC-0999}",
        3: "{state: superseded, moved_to: ADR-0999}",
        4: "{state: deferred, moved_to: IDEA-0999}",
    }
    return {
        "FR-0100-a.md": _fr("FR-0100", _plain_body(4), status="merged", ac_state=state)
    }


# covers hub-tooling FR-0026:AC-2
def test_dangling_local_pointers_warn_and_an_idea_pointer_is_honoured_on_shape(
    tmp_path,
):
    repo = _build_repo(tmp_path, _dangling_tree())
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    warnings = _section(_index(repo), "AC ratification warnings")
    for n, ref in ((1, "FR-0999"), (2, "DEC-0999"), (3, "ADR-0999")):
        assert (
            f"FR-0100 AC-{n}: moved_to {ref} does not resolve in this project"
            + _NOT_HONOURED.format(n=n)
        ) in warnings
    assert not [w for w in warnings if w.startswith("FR-0100 AC-4:")]
    # Only the IDEA entry is honoured, so only it is listed as open.
    assert "| [FR-0100](FR-0100-a.md) | AC-4 | `merged` | IDEA-0999 | — |" in _index(
        repo
    )
    assert "AC-1 |" not in _index(repo).split("## Open deferrals", 1)[1]


# covers hub-tooling FR-0026:AC-2
def test_resolving_local_pointers_are_honoured(tmp_path):
    state = {
        1: "{state: superseded, moved_to: FR-0101}",
        2: "{state: withdrawn, moved_to: DEC-0001}",
        3: "{state: superseded, moved_to: ADR-0001}",
    }
    withdrawn = [f"- **AC-{n}:** Moved synthetic thing {n}." for n in (1, 2, 3)]
    specs = {
        "FR-0100-a.md": _fr("FR-0100", _plain_body(0, withdrawn), ac_state=state),
        "FR-0101-b.md": _fr("FR-0101"),
        "decisions/DEC-0001-d.md": _dec("DEC-0001"),
        "decisions/ADR-0001-r.md": _adr("ADR-0001"),
    }
    repo = _build_repo(tmp_path, specs)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _section(_index(repo), "AC ratification warnings") == []
    assert "## Open deferrals" not in _index(repo)


# covers hub-tooling FR-0026:AC-2
def test_pointer_resolver_reads_decs_and_adrs_only_when_named(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(idx, "collect_decs", lambda: (calls.append("dec"), ([], []))[1])
    monkeypatch.setattr(idx, "collect_adrs", lambda: (calls.append("adr"), [])[1])
    fr = _make_fr(
        "FR-0100", {1: "a"}, {1: {"state": "deferred", "moved_to": "IDEA-0001"}}
    )
    assert idx.coverage_exemptions([fr])["FR-0100"].exempt == {1}
    assert calls == []
    fr = _make_fr(
        "FR-0100", {1: "a"}, {1: {"state": "withdrawn", "moved_to": "DEC-0001"}}
    )
    assert idx.coverage_exemptions([fr])["FR-0100"].exempt == frozenset()
    assert calls == ["dec"]


# ---------------------------------------------------------------------------
# AC-3: IDEA pointers checked against the hub when reachable, stderr only
# ---------------------------------------------------------------------------


def _synthetic_hub(base: Path) -> Path:
    hub = base / "hub"
    (hub / "scripts").mkdir(parents=True)
    (hub / "scripts" / "parking.py").write_text("# synthetic\n", encoding="utf-8")
    lot = hub / "parking-lot"
    lot.mkdir()
    (lot / "IDEA-0001-present.md").write_text(
        "---\nid: IDEA-0001\nstatus: parked\n---\n\nSynthetic.\n", encoding="utf-8"
    )
    (lot / "IDEA-0002-old.md").write_text(
        "---\nid: IDEA-0002\nstatus: archived\n---\n\nSynthetic.\n", encoding="utf-8"
    )
    return hub


def _idea_tree() -> dict[str, str]:
    state = {
        1: "{state: deferred, moved_to: IDEA-0001}",
        2: "{state: deferred, moved_to: IDEA-0002}",
        3: "{state: withdrawn, moved_to: IDEA-0003}",
        4: "{state: deferred}",  # not honoured: never checked against the hub
    }
    retired_state = {1: "{state: deferred, moved_to: IDEA-0003}"}
    return {
        "FR-0100-a.md": _fr("FR-0100", _plain_body(4), ac_state=state),
        # Outside the default view: its IDEA pointer is not checked.
        "FR-0101-old.md": _fr(
            "FR-0101",
            ac_state=retired_state,
            extra="lifecycle: superseded\nsuperseded_by: FR-0102\n",
        ),
        "FR-0102-new.md": _fr("FR-0102", extra="supersedes: FR-0101\n"),
    }


_POINTER_WARNINGS = [
    "FR-0100 AC-2: moved_to IDEA-0002 is archived; the work has no live home",
    "FR-0100 AC-3: moved_to IDEA-0003 not found in the hub parking lot",
]


# covers hub-tooling FR-0026:AC-3
@pytest.mark.parametrize("mode", [(), ("--validate",)], ids=["write", "validate"])
def test_idea_pointers_are_checked_against_a_reachable_hub_on_stderr_only(
    tmp_path, mode
):
    hub = _synthetic_hub(tmp_path)
    repo = _build_repo(tmp_path / "repo", _idea_tree())
    with_hub = _run(repo, "index-specs.py", *mode, env=_env(DISPATCH_HUB_ROOT=str(hub)))
    assert with_hub.returncode == 0, with_hub.stderr
    assert (
        _stderr_block(with_hub.stderr, "Deferral pointer warnings") == _POINTER_WARNINGS
    )
    without = _run(repo, "index-specs.py", *mode)
    assert without.returncode == 0, without.stderr
    assert "Deferral pointer warnings" not in without.stderr
    # The hub check is the only difference.
    assert with_hub.stdout == without.stdout
    removed = with_hub.stderr.replace(
        f"Deferral pointer warnings ({len(_POINTER_WARNINGS)}):\n"
        + "".join(f"  - {w}\n" for w in _POINTER_WARNINGS),
        "",
    )
    assert removed == without.stderr


# covers hub-tooling FR-0026:AC-3
def test_index_md_is_byte_identical_with_and_without_the_hub(tmp_path):
    hub = _synthetic_hub(tmp_path)
    repo = _build_repo(tmp_path / "repo", _idea_tree())
    assert (
        _run(repo, "index-specs.py", env=_env(DISPATCH_HUB_ROOT=str(hub))).returncode
        == 0
    )
    with_hub = (repo / "specs" / "INDEX.md").read_bytes()
    (repo / "specs" / "INDEX.md").unlink()
    assert _run(repo, "index-specs.py").returncode == 0
    assert (repo / "specs" / "INDEX.md").read_bytes() == with_hub
    text = with_hub.decode("utf-8")
    assert "parking lot" not in text and "archived" not in text
    # Hub findings never make an entry not honoured: all three stay open.
    assert (
        "| AC-1 | `ready` | IDEA-0001 |" in text
        and "| AC-2 | `ready` | IDEA-0002 |" in text
    )


# covers hub-tooling FR-0026:AC-3
def test_hub_found_by_walking_up_from_a_nested_project(tmp_path):
    hub = _synthetic_hub(tmp_path)
    repo = _build_repo(hub / "projects" / "demo", _idea_tree())
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert _stderr_block(proc.stderr, "Deferral pointer warnings") == _POINTER_WARNINGS


# covers hub-tooling FR-0026:AC-3
def test_deploy_gate_never_runs_the_hub_check(tmp_path):
    hub = _synthetic_hub(tmp_path)
    repo = _build_repo(tmp_path / "repo", _idea_tree())
    proc = _run(
        repo,
        "deploy-gate.py",
        "--stage",
        "full",
        env=_env(DISPATCH_HUB_ROOT=str(hub), METRICS_LOG_DISABLED="1"),
    )
    assert proc.returncode == 0, proc.stderr
    assert "parking lot" not in proc.stderr and "archived" not in proc.stderr


# covers hub-tooling FR-0026:AC-3
def test_hub_root_finder_follows_the_dispatcher_rule(tmp_path, monkeypatch):
    hub = _synthetic_hub(tmp_path)
    project = hub / "projects" / "demo"
    project.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere" / "proj"
    elsewhere.mkdir(parents=True)
    monkeypatch.delenv("DISPATCH_HUB_ROOT", raising=False)
    assert idx._find_hub_root(project) == hub
    assert idx._find_hub_root(elsewhere) is None
    # The variable wins when it names a directory holding scripts/parking.py,
    # even with no parking-lot/ there.
    bare = tmp_path / "bare"
    (bare / "scripts").mkdir(parents=True)
    (bare / "scripts" / "parking.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("DISPATCH_HUB_ROOT", str(bare))
    assert idx._find_hub_root(project) == bare
    assert idx._find_hub_root(elsewhere) == bare
    # A variable that names no hub falls back to the walk.
    monkeypatch.setenv("DISPATCH_HUB_ROOT", str(tmp_path / "nowhere"))
    assert idx._find_hub_root(project) == hub
    assert idx._find_hub_root(elsewhere) is None
    # The walk needs both scripts/parking.py and parking-lot/.
    shutil.rmtree(hub / "parking-lot")
    assert idx._find_hub_root(project) is None


# covers hub-tooling FR-0026:AC-3
def test_dispatcher_hub_rule_is_the_one_mirrored():
    """`dispatch.py` still uses the rule the indexer re-implements."""
    source = (_SCRIPTS_DIR / "dispatch.py").read_text(encoding="utf-8")
    body = source.split("def _find_hub_root(", 1)[1].split("\ndef ", 1)[0]
    for needle in (
        'os.environ.get("DISPATCH_HUB_ROOT")',
        '(p / "scripts" / "parking.py").exists()',
        '(parent / "scripts" / "parking.py").exists() and (parent / "parking-lot").is_dir()',
    ):
        assert needle in body, needle
    indexer = (_SCRIPTS_DIR / "index-specs.py").read_text(encoding="utf-8")
    assert "import dispatch" not in indexer and '"dispatch.py"' not in indexer


# ---------------------------------------------------------------------------
# AC-4: an exemption does not opt an FR into ratification tracking
# ---------------------------------------------------------------------------


_FIVE = {n: f"text {n}" for n in range(1, 6)}


# covers hub-tooling FR-0026:AC-4
def test_a_single_deferred_entry_does_not_opt_in():
    fr = _make_fr("FR-0100", _FIVE, {2: {"state": "deferred", "moved_to": "IDEA-0001"}})
    assert idx._ac_state_warnings([fr]) == []


# covers hub-tooling FR-0026:AC-4
def test_a_ratified_entry_beside_a_deferral_opts_in_without_naming_either():
    state = {
        2: {"state": "deferred", "moved_to": "IDEA-0001"},
        4: {"state": "ratified", "hash": idx.ac_hash(_FIVE[4])},
    }
    fr = _make_fr("FR-0100", _FIVE, state)
    assert idx._ac_state_warnings([fr]) == [
        "FR-0100: no ac_state entry for AC-1, AC-3, AC-5"
    ]


# covers hub-tooling FR-0026:AC-4
def test_only_withdrawn_and_superseded_entries_do_not_opt_in():
    state = {
        1: {"state": "withdrawn", "moved_to": None, "reason": "Not needed"},
        2: {"state": "superseded", "moved_to": "FR-0100"},
    }
    fr = _make_fr("FR-0100", _FIVE, state, withdrawn_acs={})
    warnings = idx._ac_state_warnings([fr])
    assert not [w for w in warnings if "no ac_state entry" in w], warnings


# covers hub-tooling FR-0026:AC-4
def test_an_unhonoured_exemption_entry_does_not_opt_in_either():
    fr = _make_fr("FR-0100", _FIVE, {1: {"state": "deferred"}})
    warnings = idx._ac_state_warnings([fr])
    assert len(warnings) == 1 and "needs moved_to" in warnings[0], warnings


# ---------------------------------------------------------------------------
# AC-5: the Withdrawn section is parsed; ac_state wins
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-5
def test_withdrawn_section_parses_plain_and_labelled_bullets_apart_from_acs():
    body = _body("migrated")
    assert idx.parse_acs(body) == {
        1: "Does the first synthetic thing.",
        2: "Does the second synthetic thing.",
    }
    assert idx.parse_withdrawn_acs(body) == {
        3: "Does a withdrawn synthetic thing.\n  Its text continues here.",
        # The legacy line matches neither pattern: continuation text, never an AC.
        4: "(moved) Does a superseded synthetic thing.\n"
        "- **[DEPRECATED] AC-5** (left in the legacy form) Does an older synthetic thing.",
    }


# covers hub-tooling FR-0026:AC-5
def test_withdrawn_heading_is_matched_case_insensitively_and_bullets_need_column_0():
    body = (
        "## Acceptance criteria\n\n- **AC-1:** a\n\n"
        "## WITHDRAWN Acceptance Criteria  \n\n- **AC-2:** b\n  - **AC-3:** indented\n"
        "## Notes\n\n- **AC-4:** not in the section\n"
    )
    assert idx.parse_withdrawn_acs(body) == {2: "b\n  - **AC-3:** indented"}


# covers hub-tooling FR-0026:AC-5
def test_withdrawn_field_defaults_and_is_kept_out_of_hashes_and_slice_json(tmp_path):
    fr = _make_fr("FR-0100", {1: "a"}, {})
    assert fr.withdrawn_acs == {}
    specs = {"FR-0100-a.md": _fr("FR-0100", _body("migrated"))}
    repo = _build_repo(tmp_path, specs)
    hashes = _run(repo, "index-specs.py", "--ac-hashes")
    assert hashes.returncode == 0, hashes.stderr
    assert [ln.split(":")[0] for ln in hashes.stdout.splitlines()] == [
        "FR-0100 AC-1",
        "FR-0100 AC-2",
    ]
    sliced = _run(repo, "index-specs.py", "--slice", "FR-0100", "--json")
    assert sliced.returncode == 0, sliced.stderr
    assert (
        "withdrawn_acs" not in sliced.stdout
        and "withdrawn synthetic" not in sliced.stdout
    )
    parsed, errors = idx.parse_fr(repo / "specs" / "FR-0100-a.md")
    assert errors == [] and sorted(parsed.withdrawn_acs) == [3, 4]


def _w(fr_id: str, n: int, rest: str) -> str:
    return f"{fr_id} AC-{n}: {rest}"


_HONOURED_W = "{state: withdrawn, moved_to: null, reason: Not needed}"
_HONOURED_S = "{state: superseded, moved_to: FR-0101}"
_HONOURED_D = "{state: deferred, moved_to: IDEA-0001}"

# (id, body, ac_state, expected new warnings for FR-0100)
_DISAGREEMENTS = [
    (
        "a-no-entry",
        _plain_body(2, ["- **AC-3:** Withdrawn by hand."]),
        {},
        [
            _w(
                "FR-0100",
                3,
                "listed under Withdrawn acceptance criteria but ac_state is absent; it is live for coverage",
            )
        ],
    ),
    (
        "a-not-honoured",
        _plain_body(2, ["- **AC-3:** Withdrawn by hand."]),
        {3: "{state: withdrawn}"},
        [
            _w(
                "FR-0100",
                3,
                "withdrawn needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, DEC-NNNN, or null with a reason)",
            )
            + _NOT_HONOURED.format(n=3),
            _w(
                "FR-0100",
                3,
                "listed under Withdrawn acceptance criteria but ac_state is withdrawn; it is live for coverage",
            ),
        ],
    ),
    (
        "a-wrong-state",
        _plain_body(2, ["- **AC-3:** Withdrawn by hand."]),
        {3: "{state: proposed}"},
        [
            _w(
                "FR-0100",
                3,
                "listed under Withdrawn acceptance criteria but ac_state is proposed; it is live for coverage",
            )
        ],
    ),
    (
        "b-withdrawn-still-live-section",
        _plain_body(3),
        {3: _HONOURED_W},
        [
            _w(
                "FR-0100",
                3,
                "withdrawn but still under Acceptance criteria; move it under ## Withdrawn acceptance criteria",
            )
        ],
    ),
    (
        "b-superseded-still-live-section",
        _plain_body(3),
        {3: _HONOURED_S},
        [
            _w(
                "FR-0100",
                3,
                "superseded but still under Acceptance criteria; move it under ## Withdrawn acceptance criteria",
            )
        ],
    ),
    (
        "c-deferred-under-withdrawn",
        _plain_body(2, ["- **AC-3:** Deferred, misfiled."]),
        {3: _HONOURED_D},
        [_w("FR-0100", 3, "deferred ACs stay under Acceptance criteria")],
    ),
    (
        "d-both-sections",
        _plain_body(3, ["- **AC-3:** Also here."]),
        {3: _HONOURED_W},
        [
            _w(
                "FR-0100",
                3,
                "withdrawn but still under Acceptance criteria; move it under ## Withdrawn acceptance criteria",
            ),
            _w(
                "FR-0100",
                3,
                "appears under both Acceptance criteria and Withdrawn acceptance criteria",
            ),
        ],
    ),
    (
        "no-text",
        _plain_body(2),
        {9: _HONOURED_S},
        [
            _w(
                "FR-0100",
                9,
                "superseded but has no text in this FR; keep its original text under ## Withdrawn acceptance criteria",
            )
        ],
    ),
    (
        "legacy-line-ignored",
        _plain_body(2, ["- **[DEPRECATED] AC-3** (withdrawn) Old text."]),
        {},
        [],
    ),
    (
        "labelled-withdrawn",
        _plain_body(2, ["- **AC-3 (moved):** Withdrawn, labelled."]),
        {3: _HONOURED_W},
        [],
    ),
    (
        "honoured-in-withdrawn",
        _plain_body(2, ["- **AC-3:** Withdrawn, migrated."]),
        {3: _HONOURED_W},
        [],
    ),
]


def _disagreement_specs(body: str, state: dict[int, str]) -> dict[str, str]:
    return {
        "FR-0100-a.md": _fr("FR-0100", body, status="merged", ac_state=state),
        "FR-0101-b.md": _fr("FR-0101"),
    }


# covers hub-tooling FR-0026:AC-5
@pytest.mark.parametrize(
    "body, state, expected",
    [c[1:] for c in _DISAGREEMENTS],
    ids=[c[0] for c in _DISAGREEMENTS],
)
def test_section_and_ac_state_disagreements_warn_through_the_indexer(
    tmp_path, body, state, expected
):
    repo = _build_repo(tmp_path, _disagreement_specs(body, state))
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    warnings = _section(_index(repo), "AC ratification warnings")
    assert [w for w in warnings if "no ac_state entry" not in w] == expected
    assert not [w for w in warnings if "has no matching acceptance criterion" in w]
    validate = _run(repo, "index-specs.py", "--validate")
    assert _stderr_block(validate.stderr, "AC ratification warnings") == expected


# covers hub-tooling FR-0026:AC-5
def test_an_entry_for_an_ac_in_neither_section_keeps_its_old_warning_when_not_honoured():
    fr = _make_fr("FR-0100", {1: "a"}, {9: {"state": "superseded"}})
    assert idx._ac_state_warnings([fr]) == [
        "FR-0100: ac_state references AC-9, which has no matching acceptance criterion",
        _w(
            "FR-0100",
            9,
            "superseded needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, DEC-NNNN, or null with a reason)",
        )
        + _NOT_HONOURED.format(n=9),
    ]


# ---------------------------------------------------------------------------
# AC-13: INDEX.md lists every open deferral
# ---------------------------------------------------------------------------


def _deferral_tree() -> dict[str, str]:
    return {
        "FR-0102-a.md": _fr(
            "FR-0102",
            _plain_body(2),
            status="merged",
            ac_state={2: "{state: deferred, moved_to: IDEA-0049}"},
        ),
        "FR-0103-b.md": _fr(
            "FR-0103",
            _plain_body(2),
            status="in-review",
            ac_state={
                1: '{state: deferred, moved_to: null, reason: "Pilot | feedback\\nfirst"}',
                2: "{state: deferred, moved_to: FR-0103, reason: Later in this FR}",
            },
            extra="lifecycle: superseded\nsuperseded_by: FR-0104\n",
        ),
        "FR-0104-c.md": _fr(
            "FR-0104",
            _plain_body(1, ["- **AC-2:** Withdrawn.", "- **AC-3:** Not honoured."]),
            ac_state={
                2: "{state: withdrawn, moved_to: null, reason: Not needed}",
                3: "{state: deferred}",
            },
            extra="supersedes: FR-0103\n",
        ),
    }


_OPEN_DEFERRALS = """
## Open deferrals

_ACs deliberately not delivered yet, from `ac_state`. Each names where the work went._

| FR | AC | FR status | Moved to | Reason |
|----|----|-----------|----------|--------|
| [FR-0102](FR-0102-a.md) | AC-2 | `merged` | IDEA-0049 | — |
| [FR-0103](FR-0103-b.md) | AC-1 | `in-review` | none | Pilot \\| feedback first |
| [FR-0103](FR-0103-b.md) | AC-2 | `in-review` | FR-0103 | Later in this FR |
"""


# covers hub-tooling FR-0026:AC-13
def test_open_deferrals_lists_every_honoured_deferral_and_nothing_else(tmp_path):
    repo = _build_repo(tmp_path, _deferral_tree())
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    text = _index(repo)
    assert _OPEN_DEFERRALS in text
    section = text.split("## Open deferrals", 1)[1].split("\n## ", 1)[0]
    assert "FR-0104" not in section
    lines = text.splitlines()
    order = [
        lines.index("## AC ratification warnings"),
        lines.index("## Open deferrals"),
        lines.index("## Retired objects"),
    ]
    assert order == sorted(order)
    # The gate writes the same bytes through its two-argument render_index.
    from_indexer = (repo / "specs" / "INDEX.md").read_bytes()
    (repo / "specs" / "INDEX.md").unlink()
    gate = _run(
        repo, "deploy-gate.py", "--stage", "dev", env=_env(METRICS_LOG_DISABLED="1")
    )
    assert gate.returncode == 0, gate.stderr
    assert (repo / "specs" / "INDEX.md").read_bytes() == from_indexer


# covers hub-tooling FR-0026:AC-13
def test_open_deferrals_is_omitted_without_a_honoured_deferral(tmp_path):
    specs = _deferral_tree()
    del specs["FR-0102-a.md"], specs["FR-0103-b.md"]
    specs["FR-0104-c.md"] = specs["FR-0104-c.md"].replace("supersedes: FR-0103\n", "")
    repo = _build_repo(tmp_path, specs)
    assert _run(repo, "index-specs.py").returncode == 0
    assert "## Open deferrals" not in _index(repo)


# covers hub-tooling FR-0026:AC-13
def test_open_deferrals_sits_between_ac_and_versioning_warnings_with_every_table(
    tmp_path,
):
    specs = {
        **_deferral_tree(),
        "FR-0105-v.md": _fr("FR-0105", extra="version: 5\n"),  # a versioning warning
        "FR-0106-u.md": _fr("FR-0106").replace(
            "owns: []\n", ""
        ),  # undeclared footprint
        "TR-0001-t.md": (
            "---\nid: TR-0001\ntitle: Synthetic TR\noperationalises: [FR-0102]\n"
            "created: 2026-01-01\nupdated: 2026-01-01\n---\n\n# TR-0001\n"
        ),
        "decisions/DEC-0001-d.md": _dec("DEC-0001"),
        "decisions/ADR-0001-r.md": _adr("ADR-0001"),
    }
    repo = _build_repo(tmp_path, specs)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    lines = _index(repo).splitlines()
    order = [
        lines.index("## AC ratification warnings"),
        lines.index("## Open deferrals"),
        lines.index("## Versioning warnings"),
        lines.index("## Technical requirements"),
        lines.index("## Decisions"),
        lines.index("## Architecture decision records"),
    ]
    assert order == sorted(order), order
    assert lines[order[1] - 1] == "" and lines[order[0] + 2].startswith("- ")


# covers hub-tooling FR-0026:AC-13
def test_open_deferrals_without_ac_warnings_still_precedes_versioning_warnings(
    tmp_path,
):
    specs = {
        "FR-0100-a.md": _fr("FR-0100", ac_state={2: _HONOURED_D}, extra="version: 3\n"),
    }
    repo = _build_repo(tmp_path, specs)
    assert _run(repo, "index-specs.py").returncode == 0
    text = _index(repo)
    assert "## AC ratification warnings" not in text
    lines = text.splitlines()
    assert lines.index("## Open deferrals") < lines.index("## Versioning warnings")


# ---------------------------------------------------------------------------
# AC-14: unmanaged FRs behave exactly as at the base ref (indexer)
# ---------------------------------------------------------------------------


def _unmanaged_tree() -> dict[str, str]:
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


_LAYOUT = "project_name: demo\ngate:\n  test_dirs: [lib_tests]\n"


# covers hub-tooling FR-0026:AC-14
@pytest.mark.parametrize("layout", [False, True], ids=["no-layout", "layout"])
@pytest.mark.parametrize("args", [(), ("--validate",)], ids=["write", "validate"])
def test_unmanaged_tree_indexes_byte_identically_to_the_base_ref(
    tmp_path, args, layout
):
    extra = {".agent-team/layout.yaml": _LAYOUT} if layout else None
    old = _build_repo(
        tmp_path / "old", _unmanaged_tree(), scripts=_base_scripts(), extra=extra
    )
    new = _build_repo(tmp_path / "new", _unmanaged_tree(), extra=extra)
    p_old, p_new = (
        _run(old, "index-specs.py", *args),
        _run(new, "index-specs.py", *args),
    )
    assert p_new.returncode == p_old.returncode == 0, p_new.stderr
    assert p_new.stdout == p_old.stdout
    assert p_new.stderr == p_old.stderr
    if not args:
        assert (new / "specs" / "INDEX.md").read_bytes() == (
            old / "specs" / "INDEX.md"
        ).read_bytes()


# covers hub-tooling FR-0026:AC-14
def test_half_migrated_and_legacy_superseded_frs_gain_only_their_named_warnings(
    tmp_path,
):
    specs = {
        "FR-0011-successor.md": _fr("FR-0011"),
        # A legacy `{state: superseded}` with no moved_to: gains AC-1's warning.
        "FR-0100-legacy.md": _fr(
            "FR-0100",
            _body("legacy-withdrawn"),
            status="merged",
            ac_state={3: "{state: superseded}"},
        ),
        # ac_state: {} with a bullet under the Withdrawn section: gains AC-5(a).
        "FR-0101-half.md": _fr(
            "FR-0101", _plain_body(1, ["- **AC-2:** Moved by hand."])
        ),
    }
    old = _build_repo(tmp_path / "old", specs, scripts=_base_scripts())
    new = _build_repo(tmp_path / "new", specs)
    assert _run(old, "index-specs.py").returncode == 0
    assert _run(new, "index-specs.py").returncode == 0
    old_w = _section(_index(old), "AC ratification warnings")
    new_w = _section(_index(new), "AC ratification warnings")
    gained = [w for w in new_w if w not in old_w]
    assert gained == [
        _w(
            "FR-0100",
            3,
            "superseded needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, DEC-NNNN, or null with a reason)",
        )
        + _NOT_HONOURED.format(n=3),
        _w(
            "FR-0101",
            2,
            "listed under Withdrawn acceptance criteria but ac_state is absent; it is live for coverage",
        ),
    ]
    # Only-superseded entries no longer opt the FR in (AC-4).
    assert [w for w in old_w if w not in new_w] == [
        "FR-0100: no ac_state entry for AC-1, AC-2"
    ]


# ---------------------------------------------------------------------------
# AC-15: the FR template and specs/README.md document the rule
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-15
def test_fr_template_ac_state_comment_documents_the_exemption_states():
    text = (_TEMPLATE_DIR / "specs" / "_template" / "FR-XXXX-template.md").read_text(
        encoding="utf-8"
    )
    [line] = [ln for ln in text.splitlines() if ln.startswith("ac_state:")]
    assert line.startswith("ac_state: {}  # ")
    assert (
        "proposed | refined | client-review | ratified | superseded | deferred | withdrawn"
        in line
    )
    assert "moved_to" in line
    assert (
        "FR-NNNN | IDEA-NNNN | ADR-NNNN | DEC-NNNN | null" in line and "reason" in line
    )
    assert (
        "coverage gate" in line
        and "do not opt the FR into ratification tracking" in line
    )
    frontmatter = text.split("---", 2)[1]
    example = [
        ln
        for ln in frontmatter.splitlines()
        if ln.strip().startswith("# ") and "state: deferred" in ln
    ]
    assert len(example) == 1 and "moved_to: IDEA-NNNN" in example[0]


# covers hub-tooling FR-0026:AC-15
def test_specs_readme_documents_exemptions_and_the_migration():
    text = (_TEMPLATE_DIR / "specs" / "README.md").read_text(encoding="utf-8")
    section = text.split("## Deferred, withdrawn and superseded ACs", 1)[1].split(
        "\n## ", 1
    )[0]
    for needle in (
        "`deferred`",
        "`withdrawn`",
        "`superseded`",
        "moved_to",
        "IDEA-NNNN",
        "does not resolve",
        "parking lot",
        "DISPATCH_HUB_ROOT",
        "ac-all-exempt",
        "ac-exemption-invalid",
        "## Withdrawn acceptance criteria",
        "`ac_state` wins",
        "## Open deferrals",
        "Choosing the state",
    ):
        assert needle in section, needle
    assert "check 2" in section.lower() and "check 3" in section.lower()
    steps = [
        ln
        for ln in section.splitlines()
        if ln[:3] in {"1. ", "2. ", "3. ", "4. ", "5. "}
    ]
    assert [s[:2] for s in steps] == ["1.", "2.", "3.", "4.", "5."]
    alloc = text.split("## ID allocation", 1)[1].split("\n## ", 1)[0]
    assert "sequentially" in alloc and "never reused" in alloc
    assert "Deferred, withdrawn and superseded ACs" in alloc
    consumers = text.split("## Consumers of the default view", 1)[1].split("\n## ", 1)[
        0
    ]
    [row] = [
        ln
        for ln in consumers.splitlines()
        if ln.startswith("| `scripts/deploy-gate.py`")
    ]
    assert "exempt" in row


# ---------------------------------------------------------------------------
# Round 2: B-1, DEC-0029 item 6 (E-1 and the self-pointer)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0026:AC-1
def test_stray_moved_to_on_an_ac_with_no_text_warns_in_both_modes(tmp_path):
    fr = _make_fr(
        "FR-0100", {1: "a"}, {9: {"state": "proposed", "moved_to": "IDEA-0001"}}
    )
    stray = "FR-0100 AC-9: moved_to applies only to deferred, withdrawn or superseded; ignored"
    assert idx._ac_state_warnings([fr]) == [
        "FR-0100: ac_state references AC-9, which has no matching acceptance criterion",
        stray,
        "FR-0100: no ac_state entry for AC-1",
    ]
    assert idx._ac_exemption_warnings([fr]) == [stray]
    state = {9: "{state: proposed, moved_to: IDEA-0001}"}
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr("FR-0100", ac_state=state)})
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert _stderr_block(proc.stderr, "AC ratification warnings") == [stray]


# covers hub-tooling FR-0026:AC-5
@pytest.mark.parametrize(
    "line",
    ["- **AC-3:** Deferred, misfiled.", "- **AC-3 (later):** Deferred, misfiled."],
    ids=["plain", "labelled"],
)
def test_a_honoured_deferral_under_the_withdrawn_section_gets_c_and_never_a(
    tmp_path, line
):
    """DEC-0029 item 6 (E-1): (a) fires only for no entry or an unhonoured one."""
    specs = {
        "FR-0100-a.md": _fr(
            "FR-0100", _plain_body(2, [line]), ac_state={3: _HONOURED_D}
        )
    }
    repo = _build_repo(tmp_path, specs)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _section(_index(repo), "AC ratification warnings") == [
        "FR-0100 AC-3: deferred ACs stay under Acceptance criteria"
    ]
    assert "| [FR-0100](FR-0100-a.md) | AC-3 | `ready` | IDEA-0001 | — |" in _index(
        repo
    )


# covers hub-tooling FR-0026:AC-2
@pytest.mark.parametrize(
    "entry",
    [
        "{state: superseded, moved_to: FR-0100, reason: AC-1 replaced it}",
        "{state: withdrawn, moved_to: FR-0100}",
    ],
    ids=["superseded", "withdrawn"],
)
def test_a_self_pointer_is_honoured_in_every_exemption_state(tmp_path, entry):
    """DEC-0029 item 6 (N-2): `moved_to` may name the FR's own ID."""
    body = _plain_body(2, ["- **AC-3:** Moved within this FR."])
    specs = {"FR-0100-a.md": _fr("FR-0100", body, ac_state={3: entry})}
    repo = _build_repo(tmp_path, specs)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert _section(_index(repo), "AC ratification warnings") == []
    parsed, errors = idx.parse_fr(repo / "specs" / "FR-0100-a.md")
    assert errors == []
    assert idx.coverage_exemptions([parsed])["FR-0100"].exempt == {3}


# covers hub-tooling FR-0026:AC-15
def test_specs_readme_carries_dec_0029_item_6_wording():
    text = (_TEMPLATE_DIR / "specs" / "README.md").read_text(encoding="utf-8")
    section = text.split("## Deferred, withdrawn and superseded ACs", 1)[1].split(
        "\n## ", 1
    )[0]
    assert (
        "an AC under the section with no entry, or an entry that is not honoured, is live "
        "for coverage (a honoured `deferred` AC there stays exempt, and gets the next "
        "warning instead)"
    ) in section
    assert (
        "no honoured `withdrawn` or `superseded` entry is live for coverage"
        not in section
    )
    assert (
        "`moved_to` may name the FR's own ID in any exemption state; for `superseded` it "
        "means another AC of the same FR replaced it."
    ) in section
