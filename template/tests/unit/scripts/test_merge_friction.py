"""Tests for FR-0018 — merge friction removed at the source.

- AC-1: `spawn_role` exports `DISPATCH_METRICS_DIR` and `DISPATCH_WORKTREE`
  to the agent it spawns, and restores `os.environ` exactly afterwards.
- AC-2: `metrics_log` follows `DISPATCH_METRICS_DIR` only from the project
  root `DISPATCH_WORKTREE` names. Driven in-process (the module loaded by path
  from a copy) and for real: a primary repository with a linked worktree
  (`git worktree add`), running the worktree's own `deploy-gate.py`,
  `escalation-log.py` and `metrics_log.py` as subprocesses.
- AC-4: `finalize --revalidate` resolves a merge conflict confined to
  `specs/INDEX.md` by regenerating it with the worktree's indexer and
  concluding the merge with `git commit --no-edit`; every other conflict is
  still today's ERROR. Driven against a real repository with a real bare
  `origin`, in the manner of `test_dispatch_postapprove.py`: only `gh` is
  intercepted, and the deploy gate is a scripted double.
- AC-6: the metrics README says where rows go.

Bite checks load the base commit's `dispatch.py` and `metrics_log.py`
(`_BASE_REF`, the `main` commit FR-0018 branched from) as second modules and
show the AC-2 and AC-4 tests fail on them. Outside the hub checkout that
commit is unreachable and the bite checks skip.

AC-3 (the whole suite run from inside a linked worktree with the variables
set) is the Reviewer's real run; AC-5 is withdrawn (DEC-0025); AC-7 is the
pinned tests elsewhere passing unedited.

Coverage annotations are written `# covers hub-tooling FR-0018:AC-N` rather
than the gate's own form on purpose: this file rides along into every
bootstrapped project, where no FR-0018 exists.

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import functools
import importlib.util
import json
import os

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
# The hub `main` commit FR-0018 branched from (FR-0023's merge, PR #26).
_BASE_REF = "ddbe9e5"
_FR = "FR-0001"
_METRICS_DIR_ENV = "DISPATCH_METRICS_DIR"
_WORKTREE_ENV = "DISPATCH_WORKTREE"
# Variables a subprocess must not inherit from whoever runs this suite.
_SCRUBBED_ENV = (
    _METRICS_DIR_ENV,
    _WORKTREE_ENV,
    "DISPATCH_RUN_ID",
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
)
# The scripts a bootstrapped project's gate, indexer and escalation log need.
_PROJECT_SCRIPTS = (
    "deploy-gate.py",
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
    "project_layout.py",
    "escalation-log.py",
)
_INDEXER_SCRIPTS = (
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
    "project_layout.py",
)

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log  # noqa: E402

_REAL_RUN = subprocess.run  # captured before any test patches `subprocess.run`


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_module(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0018")


@functools.lru_cache(maxsize=None)
def _base_source(rel: str) -> bytes | None:
    proc = _REAL_RUN(
        ["git", "-C", str(_TEMPLATE_DIR.parent), "show", f"{_BASE_REF}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _require_base(rel: str) -> bytes:
    src = _base_source(rel)
    if src is None:
        pytest.skip(f"base {rel} ({_BASE_REF}) not reachable")
    return src


@pytest.fixture(autouse=True)
def _no_inherited_redirect(monkeypatch):
    """Whatever environment runs the suite (AC-3 runs it with both variables
    set), each test starts with neither."""
    for key in (_METRICS_DIR_ENV, _WORKTREE_ENV):
        monkeypatch.delenv(key, raising=False)


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = _REAL_RUN(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check:
        assert proc.returncode == 0, (
            f"git {' '.join(args)}: {proc.stderr or proc.stdout}"
        )
    return (proc.stdout or "").strip()


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    path.write_bytes(data)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)


def _fr_md(fr_id: str, status: str = "ready") -> str:
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
owns: ["src/**"]
reads: []
derived_from: null
pattern: null
ac_state: {{}}
created: 2026-01-01
updated: 2026-01-01
---

# {fr_id}: Synthetic

## Acceptance criteria

- **AC-1:** does the first thing
"""


def _month_records(metrics_dir: Path) -> list[dict]:
    if not metrics_dir.exists():
        return []
    return [
        json.loads(ln)
        for f in sorted(metrics_dir.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


# ---------------------------------------------------------------------------
# AC-1: the dispatcher tells a spawned agent where the metrics log lives
# ---------------------------------------------------------------------------


class _SamplingAdapter:
    """Fake harness adapter: samples the whole `os.environ` inside `spawn`."""

    name = "fake"

    def __init__(self, raise_in_spawn: bool = False) -> None:
        self.seen: dict[str, str] | None = None
        self.raise_in_spawn = raise_in_spawn

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.seen = dict(os.environ)
        if self.raise_in_spawn:
            raise RuntimeError("synthetic harness crash")
        return ("spawned", 4242)

    def write_worktree_settings(self, wt_path, role, fr_id):
        pass


@pytest.fixture
def spawn_env(monkeypatch, tmp_path):
    repo = tmp_path / "primary"
    (repo / "specs").mkdir(parents=True)
    (repo / "_dispatch").mkdir()
    wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    wt.mkdir(parents=True)
    monkeypatch.setattr(dispatch, "REPO_ROOT", repo)
    monkeypatch.setattr(dispatch, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", repo / "_dispatch")
    monkeypatch.setattr(dispatch, "_RUN_REGISTRY", {})
    monkeypatch.setattr(
        dispatch, "ensure_role_worktree", lambda fr, role, adapter: (wt, "created")
    )
    monkeypatch.setattr(dispatch, "_base_branch_for_role", lambda fr, role: "main")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    return SimpleNamespace(repo=repo, wt=wt)


# covers hub-tooling FR-0018:AC-1
def test_spawn_exports_both_variables_and_leaves_them_absent_after(spawn_env):
    adapter = _SamplingAdapter()
    before = dict(os.environ)
    assert _METRICS_DIR_ENV not in before and _WORKTREE_ENV not in before
    result, pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert (result, pid, wt) == ("spawned", 4242, spawn_env.wt)
    seen = adapter.seen
    assert seen is not None
    assert seen[_METRICS_DIR_ENV] == os.path.abspath(
        spawn_env.repo / "specs" / "_metrics"
    )
    assert seen[_WORKTREE_ENV] == os.path.abspath(spawn_env.wt)
    assert (
        Path(seen[_METRICS_DIR_ENV]).is_absolute()
        and Path(seen[_WORKTREE_ENV]).is_absolute()
    )
    assert seen["DISPATCH_RUN_ID"]  # set beside the existing variable
    assert dict(os.environ) == before
    assert _METRICS_DIR_ENV not in os.environ and _WORKTREE_ENV not in os.environ


# covers hub-tooling FR-0018:AC-1
def test_spawn_overrides_preset_values_inside_and_restores_them_after(
    spawn_env, monkeypatch
):
    monkeypatch.setenv(_METRICS_DIR_ENV, "/synthetic/elsewhere/specs/_metrics")
    monkeypatch.setenv(_WORKTREE_ENV, "/synthetic/elsewhere")
    adapter = _SamplingAdapter()
    before = dict(os.environ)
    assert dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)[0] == "spawned"
    assert adapter.seen[_METRICS_DIR_ENV] == os.path.abspath(
        spawn_env.repo / "specs" / "_metrics"
    )
    assert adapter.seen[_WORKTREE_ENV] == os.path.abspath(spawn_env.wt)
    assert dict(os.environ) == before
    assert os.environ[_METRICS_DIR_ENV] == "/synthetic/elsewhere/specs/_metrics"
    assert os.environ[_WORKTREE_ENV] == "/synthetic/elsewhere"


# covers hub-tooling FR-0018:AC-1
def test_spawn_restores_the_environment_even_when_the_harness_raises(spawn_env):
    adapter = _SamplingAdapter(raise_in_spawn=True)
    before = dict(os.environ)
    with pytest.raises(RuntimeError):
        dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert adapter.seen[_WORKTREE_ENV] == os.path.abspath(spawn_env.wt)
    assert dict(os.environ) == before


# covers hub-tooling FR-0018:AC-1
def test_dry_run_spawn_sets_nothing_and_the_project_root_today_is_the_worktree(
    spawn_env,
):
    before = dict(os.environ)
    adapter = _SamplingAdapter()
    assert dispatch.spawn_role(_FR, "dev", apply=False, adapter=adapter) == (
        "dry-run",
        None,
        None,
    )
    assert adapter.seen is None and dict(os.environ) == before
    # The one value FR-0024 changes (DEC-0030): today it is the worktree path.
    assert dispatch._worktree_project_root(spawn_env.wt) == spawn_env.wt


# ---------------------------------------------------------------------------
# AC-2 (in-process): metrics_log follows the redirect only from that worktree
# ---------------------------------------------------------------------------

_LOAD_COUNTER = [0]


def _copy_metrics_log(root: Path, source: bytes | None = None) -> Path:
    path = root / "scripts" / "metrics_log.py"
    _write(
        path,
        source
        if source is not None
        else (_SCRIPTS_DIR / "metrics_log.py").read_bytes(),
    )
    return path


def _import_copy(path: Path):
    _LOAD_COUNTER[0] += 1
    name = f"metrics_log_fr0018_copy_{_LOAD_COUNTER[0]}"
    try:
        return _load_module(path, name)
    finally:
        sys.modules.pop(name, None)


# covers hub-tooling FR-0018:AC-2
def test_redirect_is_followed_when_both_variables_name_this_copys_project_root(
    tmp_path, monkeypatch
):
    project = tmp_path / "wt"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    path = _copy_metrics_log(project)
    monkeypatch.setenv(_METRICS_DIR_ENV, str(redirect))
    monkeypatch.setenv(_WORKTREE_ENV, str(project))
    mod = _import_copy(path)
    assert mod.METRICS_DIR == redirect
    # A non-normalised spelling of the same directory still matches.
    monkeypatch.setenv(_WORKTREE_ENV, str(project / "scripts" / ".."))
    assert _import_copy(path).METRICS_DIR == redirect
    monkeypatch.setenv(_WORKTREE_ENV, str(project) + os.sep)
    assert _import_copy(path).METRICS_DIR == redirect


# covers hub-tooling FR-0018:AC-2
@pytest.mark.skipif(
    sys.platform != "win32", reason="case-insensitive paths are a Windows rule"
)
def test_redirect_comparison_ignores_case_on_windows(tmp_path, monkeypatch):
    project = tmp_path / "Wt-Case"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    path = _copy_metrics_log(project)
    monkeypatch.setenv(_METRICS_DIR_ENV, str(redirect))
    monkeypatch.setenv(_WORKTREE_ENV, str(project).swapcase())
    assert _import_copy(path).METRICS_DIR == redirect


# covers hub-tooling FR-0018:AC-2
@pytest.mark.parametrize(
    "case",
    [
        "worktree-elsewhere",
        "only-metrics-dir",
        "only-worktree",
        "neither",
        "empty-values",
    ],
)
def test_every_other_case_keeps_the_copys_own_log(tmp_path, monkeypatch, case):
    project = tmp_path / "copy"
    other = tmp_path / "wt"
    other.mkdir()
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    path = _copy_metrics_log(project)
    values = {
        "worktree-elsewhere": (str(redirect), str(other)),
        "only-metrics-dir": (str(redirect), None),
        "only-worktree": (None, str(project)),
        "neither": (None, None),
        "empty-values": ("", str(project)),
    }[case]
    for key, value in zip((_METRICS_DIR_ENV, _WORKTREE_ENV), values):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    mod = _import_copy(path)
    assert mod.METRICS_DIR == project.resolve() / "specs" / "_metrics"


# covers hub-tooling FR-0018:AC-2
def test_explicit_dir_cli_flag_and_monkeypatch_still_take_precedence(
    tmp_path, monkeypatch
):
    project = tmp_path / "wt"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    path = _copy_metrics_log(project)
    monkeypatch.setenv(_METRICS_DIR_ENV, str(redirect))
    monkeypatch.setenv(_WORKTREE_ENV, str(project))
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    mod = _import_copy(path)
    assert mod.METRICS_DIR == redirect
    monkeypatch.setattr(mod, "PHI_HOOK_PATH", tmp_path / "no-such-hook.py")
    explicit = tmp_path / "explicit"
    rec = mod.emit("gate.run", source="manual", metrics_dir=explicit, **_gate_fields())
    assert rec is not None and len(_month_records(explicit)) == 1
    flag = tmp_path / "flag"
    rc = mod.main(
        [
            "--metrics-dir",
            str(flag),
            "emit",
            "--kind",
            "gate.run",
            "--json",
            json.dumps(_gate_fields()),
        ]
    )
    assert rc == 0 and len(_month_records(flag)) == 1
    patched = tmp_path / "patched"
    monkeypatch.setattr(mod, "METRICS_DIR", patched)
    assert mod.emit("gate.run", source="manual", **_gate_fields()) is not None
    assert len(_month_records(patched)) == 1
    assert _month_records(redirect) == []


def _gate_fields() -> dict:
    return {
        "stage": "dev",
        "outcome": "pass",
        "failure_classes": [],
        "warning_classes": [],
        "counts": {},
        "invoked_by": "manual",
    }


# covers hub-tooling FR-0018:AC-2
def test_help_text_does_not_raise_when_the_log_lies_outside_the_project(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "wt"
    redirect = tmp_path / "primary 100%" / "specs" / "_metrics"
    path = _copy_metrics_log(project)
    monkeypatch.setenv(_METRICS_DIR_ENV, str(redirect))
    monkeypatch.setenv(_WORKTREE_ENV, str(project))
    mod = _import_copy(path)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "100%" in out and "_metrics" in out
    # Without the redirect the help is unchanged: repo-relative.
    monkeypatch.delenv(_WORKTREE_ENV)
    plain = _import_copy(path)
    with pytest.raises(SystemExit):
        plain.main(["--help"])
    assert "(default: specs/_metrics)" in " ".join(capsys.readouterr().out.split())


# covers hub-tooling FR-0018:AC-2
def test_bite_base_metrics_log_ignores_the_redirect(tmp_path, monkeypatch):
    src = _require_base("template/scripts/metrics_log.py")
    project = tmp_path / "wt"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    path = _copy_metrics_log(project, src)
    monkeypatch.setenv(_METRICS_DIR_ENV, str(redirect))
    monkeypatch.setenv(_WORKTREE_ENV, str(project))
    base = _import_copy(path)
    assert base.METRICS_DIR != redirect
    assert base.METRICS_DIR == project.resolve() / "specs" / "_metrics"


# ---------------------------------------------------------------------------
# AC-2 (real worktree): the worktree's own scripts append to the primary log
# ---------------------------------------------------------------------------


def _install_project(repo: Path, scripts: tuple[str, ...] = _PROJECT_SCRIPTS) -> None:
    for name in scripts:
        _write(repo / "scripts" / name, (_SCRIPTS_DIR / name).read_bytes())


@pytest.fixture
def linked(tmp_path) -> SimpleNamespace:
    """A primary checkout with the project scripts committed, and a linked
    role worktree where `dispatch.py` puts one."""
    repo = tmp_path / "primary"
    _init_repo(repo)
    _install_project(repo)
    _write(repo / "specs" / "FR-0100-synthetic.md", _fr_md("FR-0100"))
    _write(repo / ".gitignore", ".claude/worktrees/\n__pycache__/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    wt = repo / ".claude" / "worktrees" / "dev-FR-0100"
    _git(repo, "worktree", "add", "-q", "-b", "claude/dev-FR-0100", str(wt), "main")
    run_id = "f0" * 16
    env = _clean_env(
        DISPATCH_RUN_ID=run_id,
        **{
            _METRICS_DIR_ENV: os.path.abspath(repo / "specs" / "_metrics"),
            _WORKTREE_ENV: os.path.abspath(wt),
        },
    )
    return SimpleNamespace(repo=repo, wt=wt, run_id=run_id, env=env, tmp=tmp_path)


def _run_script(
    root: Path, script: str, *args: str, env: dict[str, str]
) -> subprocess.CompletedProcess:
    return _REAL_RUN(
        [sys.executable, str(root / "scripts" / script), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


def _assert_worktree_log_untouched(wt: Path) -> None:
    assert (
        _git(
            wt, "status", "--porcelain", "--untracked-files=all", "--", "specs/_metrics"
        )
        == ""
    )
    assert not (wt / "specs" / "_metrics").exists()


# covers hub-tooling FR-0018:AC-2
def test_worktree_gate_appends_its_gate_run_to_the_primary_log(linked):
    proc = _run_script(linked.wt, "deploy-gate.py", "--stage", "dev", env=linked.env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    recs = _month_records(linked.repo / "specs" / "_metrics")
    assert [r["kind"] for r in recs] == ["gate.run"], recs
    assert recs[0]["run_id"] == linked.run_id and recs[0]["source"] == "gate"
    assert metrics_log.validation_errors(recs[0]) == []
    _assert_worktree_log_untouched(linked.wt)


# covers hub-tooling FR-0018:AC-2
def test_worktree_escalation_log_appends_its_record_to_the_primary_log(linked):
    proc = _run_script(
        linked.wt,
        "escalation-log.py",
        "append",
        "--fr",
        "FR-0100",
        "--role",
        "Developer",
        "--trigger",
        "3 dev-reviewer cycles",
        env=linked.env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    recs = _month_records(linked.repo / "specs" / "_metrics")
    assert len(recs) == 1 and recs[0]["source"] == "escalation-log", recs
    assert recs[0]["run_id"] == linked.run_id and recs[0]["object_ids"] == ["FR-0100"]
    assert metrics_log.validation_errors(recs[0]) == []
    _assert_worktree_log_untouched(linked.wt)


# covers hub-tooling FR-0018:AC-2
def test_scripts_copied_elsewhere_keep_their_own_log_with_the_variables_set(linked):
    other = linked.tmp / "copied"
    _install_project(other)
    _write(other / "specs" / "FR-0100-synthetic.md", _fr_md("FR-0100"))
    proc = _run_script(other, "deploy-gate.py", "--stage", "dev", env=linked.env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _run_script(
        other,
        "escalation-log.py",
        "append",
        "--fr",
        "FR-0100",
        "--role",
        "Developer",
        "--trigger",
        "3 dev-reviewer cycles",
        env=linked.env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    kinds = sorted(r["kind"] for r in _month_records(other / "specs" / "_metrics"))
    assert len(kinds) == 2 and "gate.run" in kinds, kinds
    assert _month_records(linked.repo / "specs" / "_metrics") == []


# covers hub-tooling FR-0018:AC-2
def test_worktree_metrics_log_help_exits_zero_with_the_variables_set(linked):
    proc = _run_script(linked.wt, "metrics_log.py", "--help", env=linked.env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "--metrics-dir" in proc.stdout


# covers hub-tooling FR-0018:AC-2
def test_bite_base_metrics_log_in_the_worktree_writes_the_branch_log(linked):
    src = _require_base("template/scripts/metrics_log.py")
    _write(linked.wt / "scripts" / "metrics_log.py", src)
    proc = _run_script(linked.wt, "deploy-gate.py", "--stage", "dev", env=linked.env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _month_records(linked.repo / "specs" / "_metrics") == []
    assert [r["kind"] for r in _month_records(linked.wt / "specs" / "_metrics")] == [
        "gate.run"
    ]


# ---------------------------------------------------------------------------
# AC-4: revalidate resolves a conflict confined to specs/INDEX.md
# ---------------------------------------------------------------------------


class _Gate:
    """Scripted `_run_deploy_gate` double: green unless told otherwise."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(
        self, stage: str, env_extra: dict | None = None, **kw
    ) -> tuple[bool, str]:
        self.calls.append(stage)
        return (True, "")


class _Env:
    def __init__(self, repo: Path, bare: Path) -> None:
        self.repo = repo
        self.bare = bare
        self.gh: list[list[str]] = []
        self.gate = _Gate()

    def bare_sha(self, branch: str) -> str | None:
        out = _git(
            self.bare,
            "rev-parse",
            "--verify",
            "-q",
            f"refs/heads/{branch}",
            check=False,
        )
        return out or None

    def snapshot(self, wt: Path) -> str:
        parts = [
            _git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
            _git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)"),
            _git(wt, "rev-parse", "HEAD"),
            _git(wt, "status", "--porcelain", "--untracked-files=all"),
            _git(wt, "diff"),
            _git(wt, "diff", "--cached"),
        ]
        for p in sorted(wt.rglob("*")):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                parts.append(f"{p.relative_to(wt)}:{p.read_bytes().hex()}")
        md = metrics_log.METRICS_DIR
        parts.append(
            ",".join(sorted(p.name for p in md.iterdir())) if md.exists() else "-"
        )
        return "\n".join(parts)


def _point(monkeypatch, mod, env: _Env, tmp_path: Path) -> None:
    repo = env.repo
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    monkeypatch.setattr(mod, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", repo / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", repo / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", repo / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(mod, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(mod, "_run_deploy_gate", env.gate)
    if getattr(mod, "_metrics", None) is not None:
        monkeypatch.setattr(mod._metrics, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (repo / "_dispatch").mkdir(exist_ok=True)

    def routed(cmd, *a, **k):
        if cmd and cmd[0] == "gh":
            env.gh.append(list(cmd))
            if cmd[1:3] == ["pr", "create"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="https://github.com/synthetic/repo/pull/7\n",
                    stderr="",
                )
            if cmd[1:3] == ["pr", "list"]:
                return SimpleNamespace(returncode=0, stdout="[]", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(mod.subprocess, "run", routed)


def _commit(wt: Path, files: dict[str, str], msg: str) -> str:
    for rel, content in files.items():
        _write(wt / rel, content)
        _git(wt, "add", rel)
    _git(wt, "commit", "-q", "-m", msg)
    return _git(wt, "rev-parse", "HEAD")


# The conflict scenarios. Every one conflicts on specs/INDEX.md; the extras
# add a second conflicted path, a merged tree without a worktree indexer, a
# merged tree whose layout the indexer rejects, or (DEC-0030 item 6) a
# codeowners config, so the indexer also writes CODEOWNERS.
_CODEOWNERS_FAILING = {
    "codeowners-rewritten-then-fails": (
        '(root / "CODEOWNERS").write_text("synthetic garbage\\n", encoding="utf-8")'
    ),
    "codeowners-created-then-fails": (
        '(root / "CODEOWNERS").write_text("synthetic garbage\\n", encoding="utf-8")'
    ),
    "codeowners-deleted-then-fails": '(root / "CODEOWNERS").unlink()',
}
_SCENARIOS = (
    "index-only",
    "index-and-review",
    "index-and-readme",
    "no-indexer",
    "bad-layout",
    "codeowners-merged",
    "codeowners-absent",
    *_CODEOWNERS_FAILING,
)
_CODEOWNERS_CONFIG = 'owner_handle: "@synthetic-owner"\n'
# CODEOWNERS on each side of "codeowners-merged": hand-edited, never
# regenerated, and merging cleanly line by line.
_CODEOWNERS_BASE = "# synthetic owners\n\n# body\n\n# footer\n"
_CODEOWNERS_DEV = "# synthetic owners\n\n# body\n\n# footer\n# dev line\n"
_CODEOWNERS_MAIN = "# main line\n# synthetic owners\n\n# body\n\n# footer\n"
_CODEOWNERS_MERGED = (
    "# main line\n# synthetic owners\n\n# body\n\n# footer\n# dev line\n"
)
_FAILING_INDEXER = (
    "import sys\n"
    "from pathlib import Path\n"
    "root = Path(__file__).resolve().parent.parent\n"
    "{action}\n"
    "print('synthetic indexer failure', file=sys.stderr)\n"
    "sys.exit(3)\n"
)


def _scenario(tmp_path: Path, which: str) -> tuple[_Env, Path, str, str]:
    """A primary repo with a bare origin; `claude/dev-FR-0001` and `main` both
    rewrite specs/INDEX.md (plus whatever `which` adds), so merging
    `origin/main` into the dev worktree conflicts. Returns the env, the dev
    worktree, and the dev and main tips."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    if which != "no-indexer":
        _install_project(repo, _INDEXER_SCRIPTS)
    _write(repo / "specs" / f"{_FR}-synthetic.md", _fr_md(_FR))
    _write(repo / "specs" / "FR-0002-synthetic.md", _fr_md("FR-0002"))
    _write(repo / "specs" / "INDEX.md", "# Spec index\n\nbase\n")
    _write(repo / "README.md", "synthetic\n")
    if which == "index-and-review":
        # Inherited by both sides, then edited on both: a content conflict.
        _write(repo / "REVIEW.md", "## Approve\n\nbase\n")
    if which.startswith("codeowners-"):
        _write(repo / ".agent-team" / "codeowners-config.yaml", _CODEOWNERS_CONFIG)
    if which in ("codeowners-merged", *_CODEOWNERS_FAILING) and (
        which != "codeowners-created-then-fails"
    ):
        _write(repo / "CODEOWNERS", _CODEOWNERS_BASE)
    _write(
        repo / ".gitignore",
        f".claude/\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\nPR_BODY.md\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")

    wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/dev-{_FR}", str(wt), "main")
    dev_files = {
        "src/thing.py": "thing\n",
        "specs/INDEX.md": "# Spec index\n\ndev's index\n",
    }
    main_files = {
        "specs/FR-0002-synthetic.md": _fr_md("FR-0002", status="merged"),
        "specs/INDEX.md": "# Spec index\n\nmain's index\n",
    }
    if which == "index-and-review":
        dev_files["REVIEW.md"] = "## Approve\n\ndev side\n"
        main_files["REVIEW.md"] = "## Approve\n\nmain side\n"
    if which == "index-and-readme":
        dev_files["README.md"] = "dev's version\n"
        main_files["README.md"] = "main's version\n"
    if which == "bad-layout":
        main_files[".agent-team/layout.yaml"] = "no_such_key: true\n"
    if which == "codeowners-merged":
        dev_files["CODEOWNERS"] = _CODEOWNERS_DEV
        main_files["CODEOWNERS"] = _CODEOWNERS_MAIN
    if which in _CODEOWNERS_FAILING:
        # Landed on main, so the merged tree's indexer is the failing one.
        main_files["scripts/index-specs.py"] = _FAILING_INDEXER.format(
            action=_CODEOWNERS_FAILING[which]
        )
    own = _commit(wt, dev_files, "dev: work")
    _write(wt / "PR_BODY.md", "# body\n")
    landed = _commit(repo, main_files, "feat: landed on main")
    _git(repo, "push", "-q", "origin", "main")
    return _Env(repo, bare), wt, own, landed


def _finalize(mod, apply: bool = True) -> int:
    return mod.cmd_finalize(
        _FR, "dev", apply=apply, draft=True, adapter=None, revalidate=True
    )


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


def _regenerate(wt: Path) -> None:
    proc = _run_script(wt, "index-specs.py", env=_clean_env())
    assert proc.returncode == 0, proc.stdout + proc.stderr


# covers hub-tooling FR-0018:AC-4
def test_index_only_conflict_is_regenerated_and_concluded_with_two_parents(
    tmp_path, monkeypatch, capsys
):
    env, wt, own, landed = _scenario(tmp_path, "index-only")
    _point(monkeypatch, dispatch, env, tmp_path)
    branch = f"claude/dev-{_FR}"
    rc = _finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 0, out
    resolved = _lines(out, "MERGE-RESOLVED")
    assert len(resolved) == 1 and "specs/INDEX.md" in resolved[0], out
    assert "REVALIDATE" not in resolved[0] and "ERROR" not in resolved[0]
    assert _lines(out, "ERROR") == []
    revalidate = _lines(out, "REVALIDATE  ")
    tip = _git(env.repo, "rev-parse", branch)
    assert (
        len(revalidate) == 1
        and tip[:7] in revalidate[0]
        and "gate=pass" in revalidate[0]
    )
    assert out.index("MERGE-RESOLVED") < out.index("REVALIDATE  ")
    assert _git(env.repo, "log", "-1", "--format=%P", branch).split() == [own, landed]
    assert env.gate.calls == ["dev", "dev"]  # before the merge and after it, as today
    assert env.bare_sha(branch) == tip
    # Nothing left over: no merge in progress, nothing unstaged, and the
    # committed index is what a fresh regenerate of the merged tree writes.
    assert not _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(wt, "status", "--porcelain", "--untracked-files=no") == ""
    committed = _git(wt, "show", f"{tip}:specs/INDEX.md")
    assert "<<<<<<<" not in committed and "main's index" not in committed
    assert "FR-0002" in committed and "merged" in committed
    _regenerate(wt)
    assert _git(wt, "status", "--porcelain", "--untracked-files=no") == ""


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize(
    ("which", "other"),
    [("index-and-review", "REVIEW.md"), ("index-and-readme", "README.md")],
)
def test_index_plus_another_conflict_is_todays_error_with_both_left_in_place(
    tmp_path, monkeypatch, capsys, which, other
):
    env, wt, own, _landed = _scenario(tmp_path, which)
    _point(monkeypatch, dispatch, env, tmp_path)
    rc = _finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert (
        len(errors) == 1
        and "origin/main" in errors[0]
        and "left for a human" in errors[0]
    )
    assert "MERGE-RESOLVED" not in out and "REVALIDATE  " not in out
    status = _git(wt, "status", "--porcelain")
    assert f"UU {other}" in status and "UU specs/INDEX.md" in status
    assert "<<<<<<<" in (wt / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []
    assert env.gate.calls == ["dev"]  # baseline only


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize("which", ["no-indexer", "bad-layout"])
def test_index_conflict_without_a_working_indexer_is_one_error_and_left_in_place(
    tmp_path, monkeypatch, capsys, which
):
    env, wt, own, _landed = _scenario(tmp_path, which)
    _point(monkeypatch, dispatch, env, tmp_path)
    rc = _finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert (
        len(errors) == 1
        and "specs/INDEX.md" in errors[0]
        and "left for a human" in errors[0]
    )
    assert "index-specs.py" in errors[0]
    assert ("absent" in errors[0]) == (which == "no-indexer")
    assert "MERGE-RESOLVED" not in out and "REVALIDATE  " not in out
    assert (
        _git(wt, "status", "--porcelain", "--", "specs/INDEX.md") == "UU specs/INDEX.md"
    )
    conflicted_before = (wt / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "<<<<<<<" in conflicted_before and "main's index" in conflicted_before
    assert _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize("which", _SCENARIOS)
def test_dry_run_of_each_conflict_mutates_nothing(tmp_path, monkeypatch, capsys, which):
    env, wt, own, _landed = _scenario(tmp_path, which)
    _point(monkeypatch, dispatch, env, tmp_path)
    before = env.snapshot(wt)
    assert _finalize(dispatch, apply=False) == 0
    out = capsys.readouterr().out
    assert (
        "WOULD-REVALIDATE" in out and "MERGE-RESOLVED" not in out and "ERROR" not in out
    )
    assert env.snapshot(wt) == before
    assert not _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert env.gate.calls == [] and env.gh == []


# covers hub-tooling FR-0018:AC-4
def test_the_merge_is_concluded_by_commit_no_edit_and_never_by_a_new_merge():
    """Static: the resolution adds `commit --no-edit` and no `merge
    --continue`; no history-rewriting argv appears (the FR's fixed point)."""
    import ast

    tree = ast.parse((_SCRIPTS_DIR / "dispatch.py").read_text(encoding="utf-8"))
    lists = [
        [
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        for node in ast.walk(tree)
        if isinstance(node, ast.List)
    ]
    assert ["commit", "--no-edit"] in lists
    assert not any("merge" in ls and "--continue" in ls for ls in lists)
    assert not any("reset" in ls for ls in lists if "--hard" in ls)


# covers hub-tooling FR-0018:AC-4
def test_bite_base_dispatcher_leaves_an_index_only_conflict_for_a_human(
    tmp_path, monkeypatch, capsys
):
    src = _require_base("template/scripts/dispatch.py")
    d = tmp_path / "base_scripts"
    _write(d / "dispatch.py", src)
    base = _load_module(d / "dispatch.py", "dispatch_base_fr0018")
    env, wt, own, _landed = _scenario(tmp_path, "index-only")
    _point(monkeypatch, base, env, tmp_path)
    rc = _finalize(base)
    out = capsys.readouterr().out
    assert rc == 1 and "MERGE-RESOLVED" not in out and len(_lines(out, "ERROR")) == 1
    assert "UU specs/INDEX.md" in _git(wt, "status", "--porcelain")


# covers hub-tooling FR-0018:AC-4
def test_a_merged_codeowners_a_regenerate_would_change_is_kept_and_the_worktree_is_clean(
    tmp_path, monkeypatch, capsys
):
    """DEC-0030 item 6: the indexer rewrites CODEOWNERS, the resolution puts
    the textual merge back, so the tip carries the merge and nothing is left
    unstaged for FR-0013 AC-1's fast-forward to refuse."""
    env, wt, own, landed = _scenario(tmp_path, "codeowners-merged")
    _point(monkeypatch, dispatch, env, tmp_path)
    branch = f"claude/dev-{_FR}"
    rc = _finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert len(_lines(out, "MERGE-RESOLVED")) == 1 and _lines(out, "ERROR") == []
    tip = _git(env.repo, "rev-parse", branch)
    assert _git(env.repo, "log", "-1", "--format=%P", branch).split() == [own, landed]
    assert env.bare_sha(branch) == tip
    assert dispatch._rev_worktree_dirty_paths(wt) == []
    assert _git(wt, "status", "--porcelain", "--untracked-files=no") == ""
    assert (wt / "CODEOWNERS").read_text(encoding="utf-8") == _CODEOWNERS_MERGED
    assert _git(wt, "show", f"{tip}:CODEOWNERS") + "\n" == _CODEOWNERS_MERGED
    # The case is real: a regenerate does change CODEOWNERS, and leaves the
    # committed INDEX.md as it is.
    _regenerate(wt)
    assert _git(wt, "status", "--porcelain", "--untracked-files=no") == "M CODEOWNERS"


# covers hub-tooling FR-0018:AC-4
def test_an_absent_codeowners_a_regenerate_would_create_stays_absent(
    tmp_path, monkeypatch, capsys
):
    env, wt, _own, _landed = _scenario(tmp_path, "codeowners-absent")
    _point(monkeypatch, dispatch, env, tmp_path)
    rc = _finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 0 and len(_lines(out, "MERGE-RESOLVED")) == 1, out
    tip = _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    assert not (wt / "CODEOWNERS").exists()
    assert _git(wt, "ls-tree", "--name-only", tip, "--", "CODEOWNERS") == ""
    status = _git(
        wt, "status", "--porcelain", "--untracked-files=all", "--", "CODEOWNERS"
    )
    assert status == ""
    assert dispatch._rev_worktree_dirty_paths(wt) == []
    _regenerate(wt)  # the case is real: a regenerate creates it
    assert (wt / "CODEOWNERS").is_file()


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize("which", list(_CODEOWNERS_FAILING))
def test_an_indexer_that_touches_codeowners_and_fails_has_both_put_back(
    tmp_path, monkeypatch, capsys, which
):
    env, wt, own, _landed = _scenario(tmp_path, which)
    _point(monkeypatch, dispatch, env, tmp_path)
    before = (
        None
        if which == "codeowners-created-then-fails"
        else (wt / "CODEOWNERS").read_bytes()
    )
    rc = _finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "exited 3" in errors[0], out
    assert "left for a human" in errors[0] and "MERGE-RESOLVED" not in out
    if before is None:
        assert not (wt / "CODEOWNERS").exists()
    else:
        assert (wt / "CODEOWNERS").read_bytes() == before
    status = _git(
        wt, "status", "--porcelain", "--untracked-files=all", "--", "CODEOWNERS"
    )
    assert status == ""
    index_status = _git(wt, "status", "--porcelain", "--", "specs/INDEX.md")
    assert index_status == "UU specs/INDEX.md"
    text = (wt / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "<<<<<<<" in text and "dev's index" in text and "main's index" in text
    assert _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0018:AC-4
def test_side_write_restore_puts_back_bytes_absence_and_deletions(tmp_path):
    """The helper pair on its own: changed bytes, a created path, a deleted
    path (in a since-removed directory) and an untouched path."""
    root = tmp_path / "root"
    _write(root / "changed", b"before\r\n")
    _write(root / "gone" / "deleted", b"kept")
    _write(root / "same", b"same")
    rels = ("changed", "created", "gone/deleted", "same")
    snap = dispatch._snapshot_paths(root, rels)
    assert snap == {
        "changed": b"before\r\n",
        "created": None,
        "gone/deleted": b"kept",
        "same": b"same",
    }
    _write(root / "changed", b"after\n")
    _write(root / "created", b"new")
    (root / "gone" / "deleted").unlink()
    (root / "gone").rmdir()
    assert dispatch._restore_paths(root, snap) == []
    assert dispatch._snapshot_paths(root, rels) == snap
    assert not (root / "created").exists()
    assert dispatch._INDEXER_SIDE_WRITES == ("CODEOWNERS",)


# ---------------------------------------------------------------------------
# AC-6: the metrics README says where rows go
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0018:AC-6
def test_metrics_readme_says_rows_land_in_the_primary_log_and_commit_from_main():
    text = (_TEMPLATE_DIR / "specs" / "_metrics" / "README.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(text.split())
    assert "`DISPATCH_METRICS_DIR`" in flat and "`DISPATCH_WORKTREE`" in flat
    assert "primary checkout's log, uncommitted" in flat
    assert "from `main` only" in flat
    assert "merge=union" in flat and "local merge" in flat
    assert "FR-0020" in flat
    assert "add that line by hand" not in flat
