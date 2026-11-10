"""Reviewer tests for FR-0007 — generated spec artifacts are written with LF
line endings on every platform.

`Path.write_text` without `newline=` applies platform newline translation, so
on Windows the regenerable artifacts (`specs/INDEX.md`, `CODEOWNERS`,
`.agent-team/escalation-log.md`, `docs/client/*.md`, `docs/_render.json`,
`docs/_gaps.md`) came out CRLF while CI regenerated them LF on Linux, and the
"spec index is up to date" check failed on every Windows push.

Harness: the team scripts are copied into a self-contained temporary repo and
driven through `subprocess`, as in `test_deploy_gate_metrics.py`. Two regimes
are exercised for every writer:

* **native** — the script runs as-is on whatever platform the tests run on;
* **simulated Windows** — the script runs under a tiny bootstrap that wraps
  `Path.write_text` so a call *without* `newline=` gets CRLF translation, the
  way CPython hard-codes it on Windows. CPython does not consult `os.linesep`
  at runtime, so this wrapper is the only way to make a naive writer fail on
  Linux CI too — without it the AC-4 guard would be a tautology there.

Coverage annotations are written `# covers hub-tooling FR-0007:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0007 exists and `deploy-gate.py` would fail
with "@covers references unknown FR".

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

# template/tests/unit/scripts/ -> parents[3] == template/
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_MATRIX = _TEMPLATE_DIR / ".agent-team" / "escalation-matrix.md"
_WORKFLOW = _TEMPLATE_DIR / ".github" / "workflows" / "agent-gates.yml"

# deploy-gate imports index-specs (which imports spec_footprint, spec_query and
# metrics_log); escalation-log imports metrics_log; render-docs is standalone.
_COPY_SCRIPTS = (
    "index-specs.py",
    "deploy-gate.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
    "escalation-log.py",
    "render-docs.py",
)
_METRICS_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
)

# Bootstrap that makes *this* interpreter behave like Windows for every
# `Path.write_text` call that omits `newline=`: translate "\n" -> "\r\n" and
# write with translation disabled. A call that passes `newline=` is forwarded
# untouched, which is exactly the contract FR-0007 relies on.
_WINDOWS_SHIM = textwrap.dedent(
    """
    import pathlib, runpy, sys
    _orig = pathlib.Path.write_text
    def _crlf_write_text(self, data, encoding=None, errors=None, newline=None):
        if newline is None:
            return _orig(self, data.replace("\\n", "\\r\\n"), encoding=encoding, errors=errors, newline="")
        return _orig(self, data, encoding=encoding, errors=errors, newline=newline)
    pathlib.Path.write_text = _crlf_write_text
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    # Direct invocation puts the script's own directory at sys.path[0]; runpy
    # does not, and the team scripts import their siblings by bare name.
    sys.path.insert(0, str(pathlib.Path(script).resolve().parent))
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        code = e.code
        sys.exit(0 if code is None else (code if isinstance(code, int) else 1))
    """
)

_FR_0001 = textwrap.dedent(
    """\
    ---
    id: FR-0001
    title: Synthetic FR-0001
    status: ready
    owner: architect
    depends_on: []
    tags: []
    owns: []
    reads: []
    derived_from: null
    pattern: null
    ac_state: {}
    created: 2026-01-01
    updated: 2026-01-01
    ---

    # FR-0001: Synthetic FR-0001

    ## Why

    Synthetic.

    ## What

    Synthetic.

    ## Acceptance criteria

    - **AC-1:** does the first thing
    - **AC-2:** does the second thing

    ## Out of scope

    - nothing

    ## Open questions

    - **Q:** none
      - **Default:** none
    """
)

_DOC_SPEC = textwrap.dedent(
    """\
    doc: overview
    title: "Synthetic overview"
    frs:
      - FR-0001
    adrs: []
    """
)


def _build_repo(
    tmp_path: Path, name: str = "repo", *, codeowners: bool = False
) -> Path:
    repo = tmp_path / name
    (repo / "scripts").mkdir(parents=True)
    for script in _COPY_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / script, repo / "scripts" / script)
    (repo / "specs").mkdir()
    (repo / "specs" / "FR-0001-synthetic.md").write_text(
        _FR_0001, encoding="utf-8", newline="\n"
    )
    (repo / ".agent-team").mkdir()
    shutil.copy(_MATRIX, repo / ".agent-team" / "escalation-matrix.md")
    if codeowners:
        (repo / ".agent-team" / "codeowners-config.yaml").write_text(
            'owner_handle: "@synthetic-owner"\n', encoding="utf-8", newline="\n"
        )
    (repo / "docs" / "_spec").mkdir(parents=True)
    (repo / "docs" / "_spec" / "overview.yaml").write_text(
        _DOC_SPEC, encoding="utf-8", newline="\n"
    )
    (repo / "shim.py").write_text(_WINDOWS_SHIM, encoding="utf-8", newline="\n")
    return repo


def _run(
    repo: Path, script: str, *args: str, windows: bool = False
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    env["METRICS_LOG_DISABLED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    target = str(repo / "scripts" / script)
    argv = (
        [sys.executable, str(repo / "shim.py"), target, *args]
        if windows
        else [sys.executable, target, *args]
    )
    return subprocess.run(
        argv,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=repo,
    )


def _bytes(repo: Path, rel: str) -> bytes:
    return (repo / rel).read_bytes()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


def _git_repo(repo: Path) -> None:
    for args in (
        ("init", "-q"),
        ("config", "user.email", "synthetic@example.invalid"),
        ("config", "user.name", "Synthetic"),
        ("config", "core.autocrlf", "false"),
    ):
        proc = _git(repo, *args)
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# AC-4 first: prove the harness can see a regression. If the shim did not
# force CRLF for a naive `write_text`, every other test here would pass on
# Linux regardless of the fix and AC-4 ("fails on regression") would be hollow.
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0007:AC-4
def test_simulated_windows_regime_makes_a_naive_writer_emit_crlf(tmp_path):
    repo = _build_repo(tmp_path)
    naive = repo / "scripts" / "naive.py"
    naive.write_text(
        'from pathlib import Path\nPath("naive.txt").write_text("a\\nb\\n", encoding="utf-8")\n',
        encoding="utf-8",
        newline="\n",
    )
    proc = _run(repo, "naive.py", windows=True)
    assert proc.returncode == 0, proc.stderr
    assert _bytes(repo, "naive.txt") == b"a\r\nb\r\n"


# covers hub-tooling FR-0007:AC-4
def test_simulated_windows_regime_leaves_an_explicit_lf_writer_alone(tmp_path):
    """The shim must not mask a correct writer either: `newline="\\n"` is
    forwarded, so a fixed script produces LF under the shim exactly as it
    would on real Windows."""
    repo = _build_repo(tmp_path)
    fixed = repo / "scripts" / "fixed.py"
    fixed.write_text(
        'from pathlib import Path\nPath("fixed.txt").write_text("a\\nb\\n", encoding="utf-8", newline="\\n")\n',
        encoding="utf-8",
        newline="\n",
    )
    proc = _run(repo, "fixed.py", windows=True)
    assert proc.returncode == 0, proc.stderr
    assert _bytes(repo, "fixed.txt") == b"a\nb\n"


# covers hub-tooling FR-0007:AC-4
def test_guard_is_not_platform_gated():
    """AC-4: the guard runs on every platform. No test in this module carries
    a skip / skipif / xfail marker, so nothing here is gated on the OS."""
    tests = [
        obj
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    assert len(tests) >= 15
    for fn in tests:
        assert not getattr(fn, "pytestmark", []), fn.__name__


# ---------------------------------------------------------------------------
# AC-1: index-specs.py — specs/INDEX.md and CODEOWNERS
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0007:AC-1
def test_index_specs_writes_lf_index_natively(tmp_path):
    repo = _build_repo(tmp_path)
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    data = _bytes(repo, "specs/INDEX.md")
    assert b"\r" not in data
    assert data.endswith(b"\n") and data.count(b"\n") > 10


# covers hub-tooling FR-0007:AC-1
def test_index_specs_writes_lf_index_under_simulated_windows(tmp_path):
    repo = _build_repo(tmp_path)
    proc = _run(repo, "index-specs.py", windows=True)
    assert proc.returncode == 0, proc.stderr
    assert b"\r" not in _bytes(repo, "specs/INDEX.md")


# covers hub-tooling FR-0007:AC-1
def test_index_specs_writes_lf_codeowners_under_simulated_windows(tmp_path):
    repo = _build_repo(tmp_path, codeowners=True)
    proc = _run(repo, "index-specs.py", windows=True)
    assert proc.returncode == 0, proc.stderr
    assert "Wrote CODEOWNERS" in proc.stdout
    data = _bytes(repo, "CODEOWNERS")
    assert b"\r" not in data
    # The fixture FR declares no `owns:` globs, so the file is the generated
    # header only — still four LF-terminated lines the old writer would have
    # emitted as CRLF.
    assert data.startswith(b"# Auto-generated by scripts/index-specs.py")
    assert data.count(b"\n") >= 4 and data.endswith(b"\n")


# covers hub-tooling FR-0007:AC-1
def test_index_specs_output_is_byte_identical_across_platform_regimes(tmp_path):
    """The AC's cross-platform clause, made concrete: the same spec tree
    regenerated natively and under the CRLF regime yields identical bytes for
    both artifacts — not merely "no CR"."""
    native = _build_repo(tmp_path, "native", codeowners=True)
    windows = _build_repo(tmp_path, "windows", codeowners=True)
    p_native = _run(native, "index-specs.py")
    p_windows = _run(windows, "index-specs.py", windows=True)
    assert p_native.returncode == 0 and p_windows.returncode == 0, (
        p_native.stderr,
        p_windows.stderr,
    )
    assert _bytes(native, "specs/INDEX.md") == _bytes(windows, "specs/INDEX.md")
    assert _bytes(native, "CODEOWNERS") == _bytes(windows, "CODEOWNERS")


# covers hub-tooling FR-0007:AC-1
def test_index_specs_validate_writes_nothing_in_either_regime(tmp_path):
    """`--validate` is the read-only surface; the fix must not have turned it
    into a writer."""
    repo = _build_repo(tmp_path, codeowners=True)
    for windows in (False, True):
        proc = _run(repo, "index-specs.py", "--validate", windows=windows)
        assert proc.returncode == 0, proc.stderr
        assert not (repo / "specs" / "INDEX.md").exists()
        assert not (repo / "CODEOWNERS").exists()


# ---------------------------------------------------------------------------
# AC-2: deploy-gate.py — the INDEX rewrite matches index-specs.py
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0007:AC-2
def test_deploy_gate_index_bytes_equal_index_specs_bytes_natively(tmp_path):
    via_indexer = _build_repo(tmp_path, "indexer")
    via_gate = _build_repo(tmp_path, "gate")
    assert _run(via_indexer, "index-specs.py").returncode == 0
    gate = _run(via_gate, "deploy-gate.py")
    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert _bytes(via_gate, "specs/INDEX.md") == _bytes(via_indexer, "specs/INDEX.md")
    assert b"\r" not in _bytes(via_gate, "specs/INDEX.md")


# covers hub-tooling FR-0007:AC-2
def test_deploy_gate_index_bytes_equal_index_specs_bytes_under_simulated_windows(
    tmp_path,
):
    """Adversarial: the gate's writer is a *separate* call site from the
    indexer's. Fixing one and not the other passes the native test above on
    Linux; it does not pass this one."""
    via_indexer = _build_repo(tmp_path, "indexer")
    via_gate = _build_repo(tmp_path, "gate")
    assert _run(via_indexer, "index-specs.py").returncode == 0
    gate = _run(via_gate, "deploy-gate.py", windows=True)
    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert b"\r" not in _bytes(via_gate, "specs/INDEX.md")
    assert _bytes(via_gate, "specs/INDEX.md") == _bytes(via_indexer, "specs/INDEX.md")


# covers hub-tooling FR-0007:AC-2
def test_deploy_gate_status_only_still_writes_nothing(tmp_path):
    """The read-only contract of `--status-only` is explicitly carried over
    by the AC; a change to the write call must not have moved it out from
    under the guard."""
    repo = _build_repo(tmp_path)
    for windows in (False, True):
        proc = _run(repo, "deploy-gate.py", "--status-only", windows=windows)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert not (repo / "specs" / "INDEX.md").exists()


# ---------------------------------------------------------------------------
# AC-3: escalation-log.py and render-docs.py
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0007:AC-3
def test_escalation_log_header_and_append_are_lf_under_simulated_windows(tmp_path):
    """The header-creation path (log absent) and the append path in one run."""
    repo = _build_repo(tmp_path)
    log = repo / ".agent-team" / "escalation-log.md"
    assert not log.exists()
    proc = _run(
        repo,
        "escalation-log.py",
        "append",
        "--fr",
        "FR-0001",
        "--role",
        "Developer",
        "--trigger",
        "Spec is ambiguous",
        windows=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = log.read_bytes()
    assert b"\r" not in data
    assert b"| FR-0001 | Developer | Spec is ambiguous | (pending) |" in data
    assert data.endswith(b"\n")


# covers hub-tooling FR-0007:AC-3
def test_escalation_log_resolve_is_lf_under_simulated_windows(tmp_path):
    repo = _build_repo(tmp_path)
    assert (
        _run(
            repo,
            "escalation-log.py",
            "append",
            "--fr",
            "FR-0001",
            "--role",
            "Developer",
            "--trigger",
            "Spec is ambiguous",
            windows=True,
        ).returncode
        == 0
    )
    proc = _run(
        repo,
        "escalation-log.py",
        "resolve",
        "--fr",
        "FR-0001",
        "--resolution",
        "clarified AC-1",
        windows=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = (repo / ".agent-team" / "escalation-log.md").read_bytes()
    assert b"\r" not in data
    assert b"| clarified AC-1 |" in data and b"(pending)" not in data


# covers hub-tooling FR-0007:AC-3
def test_escalation_log_append_normalises_a_legacy_crlf_log(tmp_path):
    """Adversarial: a log written by the pre-fix script on Windows is CRLF
    throughout. Appending to it must not leave a mixed-ending file; the
    read-modify-write path reads with universal newlines and writes LF, so the
    whole file comes out LF with every prior row intact."""
    repo = _build_repo(tmp_path)
    log = repo / ".agent-team" / "escalation-log.md"
    legacy = (
        "# Escalation Log\r\n\r\n| Date | FR | Role | Trigger | Resolution |\r\n"
        "|------|----|------|---------|------------|\r\n"
        "| 2026-01-01 | FR-0001 | Reviewer | Test reveals spec gap | resolved |\r\n"
    )
    log.write_bytes(legacy.encode("utf-8"))
    proc = _run(
        repo,
        "escalation-log.py",
        "append",
        "--fr",
        "FR-0001",
        "--role",
        "Developer",
        "--trigger",
        "Spec is ambiguous",
        windows=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = log.read_bytes()
    assert b"\r" not in data
    assert (
        b"| 2026-01-01 | FR-0001 | Reviewer | Test reveals spec gap | resolved |\n"
        in data
    )
    assert data.endswith(b"| FR-0001 | Developer | Spec is ambiguous | (pending) |\n")


# covers hub-tooling FR-0007:AC-3
def test_render_docs_writes_all_three_artifacts_lf_under_simulated_windows(tmp_path):
    repo = _build_repo(tmp_path)
    proc = _run(repo, "render-docs.py", windows=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for rel in ("docs/client/overview.md", "docs/_render.json", "docs/_gaps.md"):
        data = _bytes(repo, rel)
        assert b"\r" not in data, rel
        assert data.endswith(b"\n"), rel


# covers hub-tooling FR-0007:AC-3
def test_render_docs_content_is_unchanged_between_regimes(tmp_path):
    """Adversarial for the "content otherwise byte-identical" clause: the
    rendered doc and the gaps file must match across regimes exactly. The
    render stamp carries a timestamp, so it is compared after masking the
    `rendered_at` values only."""
    native = _build_repo(tmp_path, "native")
    windows = _build_repo(tmp_path, "windows")
    assert _run(native, "render-docs.py").returncode == 0
    assert _run(windows, "render-docs.py", windows=True).returncode == 0
    for rel in ("docs/client/overview.md", "docs/_gaps.md"):
        assert _bytes(native, rel) == _bytes(windows, rel), rel
    import json

    n = json.loads(_bytes(native, "docs/_render.json"))
    w = json.loads(_bytes(windows, "docs/_render.json"))
    for stamp in (n, w):
        for entry in stamp.values():
            entry.pop("rendered_at", None)
    assert n == w


# ---------------------------------------------------------------------------
# AC-5: regeneration is idempotent from git's point of view, across regimes
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0007:AC-5
def test_second_regeneration_leaves_git_status_clean(tmp_path):
    repo = _build_repo(tmp_path)
    _git_repo(repo)
    assert _run(repo, "index-specs.py").returncode == 0
    assert _git(repo, "add", "specs/INDEX.md").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "index").returncode == 0
    assert _run(repo, "index-specs.py").returncode == 0
    status = _git(repo, "status", "--porcelain", "specs/INDEX.md")
    assert status.returncode == 0 and status.stdout == ""


# covers hub-tooling FR-0007:AC-5
def test_index_committed_from_windows_regime_is_clean_after_linux_regeneration(
    tmp_path,
):
    """The exact CI scenario that motivated the FR: a Windows contributor
    commits the regenerated index; CI on Linux regenerates it and runs
    `git status --porcelain specs/INDEX.md`. With `core.autocrlf=false` on
    both sides nothing normalises the bytes but the writer itself."""
    repo = _build_repo(tmp_path)
    _git_repo(repo)
    assert _run(repo, "index-specs.py", windows=True).returncode == 0
    assert _git(repo, "add", "specs/INDEX.md").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "index from windows").returncode == 0
    assert _run(repo, "index-specs.py").returncode == 0
    status = _git(repo, "status", "--porcelain", "specs/INDEX.md")
    assert status.returncode == 0 and status.stdout == "", status.stdout
    # And the other direction: Linux commit, Windows regeneration.
    assert _run(repo, "index-specs.py", windows=True).returncode == 0
    status = _git(repo, "status", "--porcelain", "specs/INDEX.md")
    assert status.returncode == 0 and status.stdout == "", status.stdout


# covers hub-tooling FR-0007:AC-5
def test_ci_up_to_date_check_is_unchanged():
    """The workflow step this FR exists to satisfy is still there and still
    keyed on `git status --porcelain specs/INDEX.md`; the fix landed in the
    writers, not by loosening the check."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/index-specs.py" in text
    assert "git status --porcelain specs/INDEX.md" in text
    assert "specs/INDEX.md is out of date" in text
