"""Tests for hub-tooling FR-0024 — the dispatcher works for a project that
lives in a subdirectory of its repository.

Every fixture here puts the project in `projects/demo/` of a real temporary
git repository (with a real bare `origin`), which no other dispatcher test
does: the prefix is `projects/demo/` (AC-1). The repository top carries
decoys — a `REVIEW.md`, a `PR_BODY.md`, a library review under
`specs/_reviews/`, a `specs/INDEX.md`, `scripts/` — that a prefix-blind
dispatcher reads instead of the project's (AC-2, AC-3, AC-4). Absolute grants
for a repo-rooted footprint (AC-5), the early refusal on a malformed layout
(AC-6) and hub-tooling's `.gitignore` (AC-7) are checked here too; AC-1's and
AC-8's byte-identity at prefix "" is the rest of the dispatcher suite, run
unedited.

Harness: `dispatch.py` loaded by path; `REPO_ROOT` re-pointed at the project
directory; only `gh` argv is intercepted (never invoked for real);
`_gh_preflight` / `_repo_nwo` stubbed. The pre-FR dispatcher for the bite
checks is `git show <pre-FR ref>:template/scripts/dispatch.py` and skips
inside a bootstrapped project.

Coverage annotations are written `# covers hub-tooling FR-0024:AC-N` rather
than the gate's own form on purpose: this file rides along into every
bootstrapped project, where no FR-0024 exists and `deploy-gate.py` would fail
with "references unknown FR".

Every fixture is synthetic (see tests/fixtures/README.md and
tests/fixtures/dispatch-subdirectory/README.md).
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
_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "dispatch-subdirectory"
_PRE_FR_REF = "d866207"  # main before FR-0024
_FR = "FR-0001"
_PREFIX = "projects/demo/"
# The gate's coverage tag, spelled so this file never carries it literally.
_COVERS_TAG = "@" + "covers"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log  # noqa: E402  (sibling module, importable by name)

_REAL_RUN = subprocess.run

# Scripts a bootstrapped project's gate and indexer need (FR-0018's lists).
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
_METRICS_DIR_ENV = "DISPATCH_METRICS_DIR"
_WORKTREE_ENV = "DISPATCH_WORKTREE"
_SCRUBBED_ENV = (
    _METRICS_DIR_ENV,
    _WORKTREE_ENV,
    "DISPATCH_RUN_ID",
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
)


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0024")


@functools.lru_cache(maxsize=1)
def _pre_fr_source() -> bytes | None:
    proc = _REAL_RUN(
        [
            "git",
            "-C",
            str(_TEMPLATE_DIR.parent),
            "show",
            f"{_PRE_FR_REF}:template/scripts/dispatch.py",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


@pytest.fixture(scope="session")
def pre_fr_dispatch(tmp_path_factory):
    src = _pre_fr_source()
    if src is None:
        pytest.skip(f"pre-FR dispatch.py ({_PRE_FR_REF}) not reachable")
    d = tmp_path_factory.mktemp("pre_fr0024_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0024")


@pytest.fixture(autouse=True)
def _no_inherited_redirect(monkeypatch):
    for key in (_METRICS_DIR_ENV, _WORKTREE_ENV, "DISPATCH_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Real-git fixture: the project in projects/demo/, decoys at the top
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = _REAL_RUN(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check:
        assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr or proc.stdout}"
    return (proc.stdout or "").strip()


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    path.write_bytes(data)


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _fr_md(fr_id: str = _FR, status: str = "ready", owns=("src/**",)) -> str:
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
owns: {json.dumps(list(owns))}
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


def _make_repo(
    tmp_path: Path,
    *,
    owns=("src/**",),
    layout: str | None = None,
    top_files: dict[str, str | bytes] | None = None,
    project_files: dict[str, str | bytes] | None = None,
) -> SimpleNamespace:
    """A repository whose project is `projects/demo/`, with decoys at the
    top, committed on `main` and pushed to a bare `origin`."""
    top = tmp_path / "top"
    _init_repo(top)
    proj = top / "projects" / "demo"
    files_top: dict[str, str | bytes] = {
        "REVIEW.md": _fixture("decoy-REVIEW.md"),
        "PR_BODY.md": _fixture("decoy-PR_BODY.md"),
        f"specs/_reviews/{_FR}-r1.md": _fixture("decoy-library-review.md"),
        "specs/INDEX.md": "# Decoy repository-top index\n",
        "scripts/deploy-gate.py": "import sys\nsys.exit(3)\n",
        "other/b.py": "b = 1\n",
        "lib/x.py": "x = 1\n",
        ".gitignore": (
            "**/.claude/worktrees/\n**/.claude/settings.local.json\n"
            f"{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\n"
        ),
    }
    files_top.update(top_files or {})
    for rel, content in files_top.items():
        _write(top / rel, content)
    files_proj: dict[str, str | bytes] = {
        f"specs/{_FR}-synthetic.md": _fr_md(owns=owns),
        "specs/INDEX.md": "# Spec index\n\nbase\n",
        "src/a.py": "a = 1\n",
        "scripts/dispatch.py": "# synthetic copy of the project's dispatcher\n",
    }
    if layout is not None:
        files_proj[".agent-team/layout.yaml"] = layout
    files_proj.update(project_files or {})
    for rel, content in files_proj.items():
        _write(proj / rel, content)
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(top, "remote", "add", "origin", str(bare))
    _git(top, "push", "-q", "-u", "origin", "main")
    return SimpleNamespace(top=top, proj=proj, bare=bare, gh=[], tmp=tmp_path)


def _point(monkeypatch, mod, env: SimpleNamespace) -> None:
    """Point `mod` at the project directory and route `gh` to a double."""
    proj = env.proj
    monkeypatch.setattr(mod, "REPO_ROOT", proj)
    monkeypatch.setattr(mod, "SPECS_DIR", proj / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", proj / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", proj / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", proj / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_PROJECT_PREFIX_CACHE", {}, raising=False)
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(mod, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(mod, "_find_uv", lambda: None)
    if getattr(mod, "_metrics", None) is not None:
        monkeypatch.setattr(mod._metrics, "METRICS_DIR", env.tmp / "metrics")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", env.tmp / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    (proj / "_dispatch").mkdir(exist_ok=True)

    def routed(cmd, *a, **k):
        if cmd and cmd[0] == "gh":
            env.gh.append([str(c) for c in cmd])
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


def _worktree(env: SimpleNamespace, role: str, base: str = "main") -> Path:
    wt = env.proj / ".claude" / "worktrees" / f"{role}-{_FR}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(env.top, "worktree", "add", "-q", "-b", f"claude/{role}-{_FR}", str(wt), base)
    return wt


def _commit(cwd: Path, files: dict[str, str | bytes], msg: str) -> str:
    for rel, content in files.items():
        _write(cwd / rel, content)
        _git(cwd, "add", "--", rel)
    _git(cwd, "commit", "-q", "-m", msg)
    return _git(cwd, "rev-parse", "HEAD")


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


# ---------------------------------------------------------------------------
# AC-1: the prefix is computed at call time and cached per REPO_ROOT
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0024:AC-1
def test_the_prefix_is_the_projects_posix_path_and_empty_at_the_top_or_outside_git(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    monkeypatch.setattr(dispatch, "_PROJECT_PREFIX_CACHE", {})
    monkeypatch.setattr(dispatch, "REPO_ROOT", env.proj)
    assert dispatch._project_prefix() == _PREFIX
    monkeypatch.setattr(dispatch, "REPO_ROOT", env.top)
    assert dispatch._project_prefix() == ""
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    monkeypatch.setattr(dispatch, "REPO_ROOT", outside)
    assert dispatch._project_prefix() == ""
    # A role worktree's own project directory has the same prefix.
    wt = _worktree(env, "dev")
    monkeypatch.setattr(dispatch, "REPO_ROOT", wt / "projects" / "demo")
    assert dispatch._project_prefix() == _PREFIX
    assert dispatch._worktree_project_root(wt) == wt / "projects" / "demo"
    assert dispatch._repo_path("PR_BODY.md") == "projects/demo/PR_BODY.md"


# covers hub-tooling FR-0024:AC-1
def test_the_prefix_is_cached_per_repo_root_and_never_computed_at_import(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    seen: list[list[str]] = []

    def spy(cmd, *a, **k):
        seen.append([str(c) for c in cmd])
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    fresh = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_fr0024_import_probe")
    assert not any("--show-prefix" in c for c in seen), seen
    assert fresh._PROJECT_PREFIX_CACHE == {}
    monkeypatch.setattr(fresh, "REPO_ROOT", env.proj)
    assert fresh._project_prefix() == _PREFIX
    first = [c for c in seen if "--show-prefix" in c]
    assert len(first) == 1 and first[0][2] == str(env.proj)
    assert fresh._project_prefix() == _PREFIX
    assert len([c for c in seen if "--show-prefix" in c]) == 1  # cached
    # Re-pointed REPO_ROOT: worked out afresh, never the stale answer.
    monkeypatch.setattr(fresh, "REPO_ROOT", env.top)
    assert fresh._project_prefix() == ""
    monkeypatch.setattr(fresh, "REPO_ROOT", env.proj)
    assert fresh._project_prefix() == _PREFIX
    assert len([c for c in seen if "--show-prefix" in c]) == 1


# covers hub-tooling FR-0024:AC-1
def test_ensure_dev_venv_never_computes_the_prefix_and_its_reuse_path_runs_nothing(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    project_in_wt = tmp_path / "wt" / "projects" / "demo"
    py = dispatch._venv_python_exe(project_in_wt / dispatch.VENV_DIRNAME)
    _write(py, b"")
    calls: list = []
    monkeypatch.setattr(
        dispatch.subprocess, "run", lambda *a, **k: calls.append(a) or None
    )
    assert dispatch.ensure_dev_venv(project_in_wt) == (True, "venv-reused")
    assert calls == []
    assert dispatch._PROJECT_PREFIX_CACHE == {}


# covers hub-tooling FR-0024:AC-1
def test_a_malformed_layout_at_prefix_empty_is_not_read(tmp_path, monkeypatch):
    """At prefix "" nothing reads the layout, so nothing changes byte for
    byte (the fixed clause; FR-0018's bad-layout finalize test pins it)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / ".agent-team" / "layout.yaml", _fixture("layout-malformed.yaml"))
    monkeypatch.setattr(dispatch, "_PROJECT_PREFIX_CACHE", {})
    monkeypatch.setattr(dispatch, "REPO_ROOT", repo)
    assert dispatch._project_prefix() == ""
    assert dispatch._layout_refusal() is None


# ---------------------------------------------------------------------------
# AC-2: agents and worktree files use the project directory in the worktree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_name", ["claude-code", "cursor"])
# covers hub-tooling FR-0024:AC-2
def test_the_spawn_preview_runs_the_agent_in_the_project_directory(
    tmp_path, monkeypatch, adapter_name
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    adapter = dispatch.get_adapter(adapter_name)
    wt = env.proj / ".claude" / "worktrees" / f"dev-{_FR}"
    preview = adapter.dry_run_preview(_FR, "dev", wt)
    assert f"cwd={wt / 'projects' / 'demo'};" in preview, preview


# covers hub-tooling FR-0024:AC-2
def test_a_dry_run_tick_plans_the_developer_in_the_project_directory(
    tmp_path, monkeypatch, capsys
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (False, "offline"))
    rc = dispatch.cmd_tick(
        False, dispatch.ClaudeCodeAdapter(), role="dev", fr_filter=[_FR],
        skip_env_preflight=True,
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    wt = env.proj / ".claude" / "worktrees" / f"dev-{_FR}"
    [line] = _lines(out, "WOULD-SPAWN")
    assert f"cwd={wt / 'projects' / 'demo'};" in line, out
    assert not wt.exists()


@pytest.mark.parametrize(
    ("adapter_name", "rel"),
    [("claude-code", ".claude/settings.local.json"), ("cursor", ".cursor/cli.json")],
)
# covers hub-tooling FR-0024:AC-2
def test_the_permission_file_is_written_in_the_project_inside_the_worktree(
    tmp_path, monkeypatch, adapter_name, rel
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    dispatch.get_adapter(adapter_name).write_worktree_settings(wt, "dev", _FR)
    assert (wt / "projects" / "demo" / rel).is_file()
    assert not (wt / rel).exists()
    record = json.loads(
        (env.proj / "_dispatch" / f"{_FR}.dev.settings.sha256").read_text(encoding="utf-8")
    )
    assert Path(record["path"]) == wt / "projects" / "demo" / rel


class _SamplingClaude(dispatch.ClaudeCodeAdapter):
    """The real Claude adapter's settings, with `spawn` sampling the
    environment instead of launching `claude`."""

    def __init__(self) -> None:
        self.seen: dict[str, str] | None = None
        self.wt: Path | None = None

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None, gate_id=None):
        self.seen = dict(os.environ)
        self.wt = wt_path
        return ("spawned", 4242)


# covers hub-tooling FR-0024:AC-2
def test_a_real_spawn_creates_the_worktree_at_its_root_and_points_the_agent_at_the_project(
    tmp_path, monkeypatch, capsys
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    venv_args: list[Path] = []
    real_venv = dispatch.ensure_dev_venv

    def venv_spy(path):
        venv_args.append(path)
        return real_venv(path)

    monkeypatch.setattr(dispatch, "ensure_dev_venv", venv_spy)
    adapter = _SamplingClaude()
    result, pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert (result, pid) == ("spawned", 4242), capsys.readouterr().out
    root = env.proj / ".claude" / "worktrees" / f"dev-{_FR}"
    project = root / "projects" / "demo"
    assert wt == root and adapter.wt == root
    assert (root / ".git").is_file()  # created at the worktree root
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD") == f"claude/dev-{_FR}"
    assert (project / ".claude" / "settings.local.json").is_file()
    assert not (root / ".claude" / "settings.local.json").exists()
    assert venv_args == [project]
    # DEC-0031 item 1: the one project-root helper names the project.
    assert adapter.seen[_WORKTREE_ENV] == os.path.abspath(project)
    assert adapter.seen[_METRICS_DIR_ENV] == os.path.abspath(env.proj / "specs" / "_metrics")
    lock = json.loads((env.proj / "_dispatch" / f"{_FR}.dev.lock").read_text(encoding="utf-8"))
    assert lock["worktree"] == str(root)


# covers hub-tooling FR-0024:AC-2
def test_the_claude_harness_is_launched_with_the_project_as_its_cwd(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    wt = env.proj / ".claude" / "worktrees" / f"dev-{_FR}"
    assert dispatch._project_prefix() == _PREFIX  # warm before Popen is faked
    seen: dict = {}

    class _Proc:
        pid = 4343

    def fake_popen(cmd, **kw):
        seen.update(kw)
        return _Proc()

    monkeypatch.setattr(dispatch.shutil, "which", lambda name: "claude-synthetic")
    monkeypatch.setattr(dispatch.subprocess, "Popen", fake_popen)
    log = tmp_path / "agent.log"
    try:
        assert dispatch.ClaudeCodeAdapter().spawn(_FR, "dev", wt, log) == ("spawned", 4343)
    finally:
        seen.get("stdout") and seen["stdout"].close()
    assert Path(seen["cwd"]) == wt / "projects" / "demo"


# covers hub-tooling FR-0024:AC-2
def test_metrics_follow_the_redirect_only_from_the_project_inside_the_worktree(
    tmp_path, monkeypatch
):
    """DEC-0031 item 1, with the variables a real `spawn_role` exports: the
    project's gate inside the worktree appends to the primary checkout's
    log; copies at the worktree root and in a sibling project keep theirs."""
    scripts = {f"scripts/{n}": (_SCRIPTS_DIR / n).read_bytes() for n in _PROJECT_SCRIPTS}
    fr100 = {"specs/FR-0100-synthetic.md": _fr_md("FR-0100")}
    env = _make_repo(
        tmp_path,
        top_files={**scripts, **fr100},
        project_files={
            **scripts,
            **fr100,
            # The sibling project, another copy of the same scripts.
        },
    )
    other = env.top / "projects" / "other"
    for rel, content in {**scripts, **fr100}.items():
        _write(other / rel, content)
    _git(env.top, "add", "-A")
    _git(env.top, "commit", "-q", "-m", "sibling project")
    _point(monkeypatch, dispatch, env)
    adapter = _SamplingClaude()
    assert dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)[0] == "spawned"
    root = adapter.wt
    child = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
    child.update(
        {
            "METRICS_PROJECT": "synthetic-project",
            "PYTHONIOENCODING": "utf-8",
            "DISPATCH_RUN_ID": adapter.seen["DISPATCH_RUN_ID"],
            _METRICS_DIR_ENV: adapter.seen[_METRICS_DIR_ENV],
            _WORKTREE_ENV: adapter.seen[_WORKTREE_ENV],
        }
    )

    def run_gate(where: Path) -> subprocess.CompletedProcess:
        return _REAL_RUN(
            [sys.executable, str(where / "scripts" / "deploy-gate.py"), "--stage", "dev"],
            cwd=str(where),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=child,
        )

    def records(where: Path) -> list[dict]:
        d = where / "specs" / "_metrics"
        if not d.exists():
            return []
        return [
            json.loads(ln)
            for f in sorted(d.glob("*.ndjson"))
            for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]

    project = root / "projects" / "demo"
    proc = run_gate(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    primary = records(env.proj)
    assert [r["kind"] for r in primary] == ["gate.run"], primary
    assert primary[0]["run_id"] == adapter.seen["DISPATCH_RUN_ID"]
    assert not (project / "specs" / "_metrics").exists()
    for elsewhere in (root, root / "projects" / "other"):
        run_gate(elsewhere)
        assert "gate.run" in [r["kind"] for r in records(elsewhere)], elsewhere
    assert len(records(env.proj)) == 1


# covers hub-tooling FR-0024:AC-2
def test_finalize_reads_the_projects_pr_body_not_a_decoy_at_the_worktree_root(
    tmp_path, monkeypatch, capsys
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    _commit(wt, {"projects/demo/src/a.py": "a = 2\n"}, "feat: synthetic change")
    body = wt / "projects" / "demo" / "PR_BODY.md"
    _write(body, _fixture("project-PR_BODY.md"))
    assert (wt / "PR_BODY.md").read_bytes() == _fixture("decoy-PR_BODY.md")
    rc = dispatch.cmd_finalize(_FR, "dev", apply=True, draft=True, adapter=None)
    out = capsys.readouterr().out
    assert rc == 0, out
    [create] = [c for c in env.gh if c[1:3] == ["pr", "create"]]
    assert Path(create[create.index("--body-file") + 1]) == body


# covers hub-tooling FR-0024:AC-3
def test_the_pr_body_fallback_reads_the_projects_file_on_the_branch(
    tmp_path, monkeypatch, capsys
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    _commit(
        wt,
        {
            "projects/demo/src/a.py": "a = 2\n",
            "projects/demo/PR_BODY.md": _fixture("project-PR_BODY.md"),
        },
        "feat: synthetic change with a committed body",
    )
    (wt / "projects" / "demo" / "PR_BODY.md").unlink()  # pruned, still on the branch
    rc = dispatch._finalize_dev(_FR, f"claude/dev-{_FR}", None, "synthetic/repo", True)
    out = capsys.readouterr().out
    assert rc == 0, out
    materialised = env.proj / "_dispatch" / f"{_FR}.dev.pr_body.md"
    assert materialised.read_bytes().replace(b"\r\n", b"\n") == _fixture("project-PR_BODY.md")


# ---------------------------------------------------------------------------
# AC-3: branch reads and pathspecs are prefix-correct
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0024:AC-3
def test_the_status_is_read_from_the_role_branch_not_mains(tmp_path, monkeypatch):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    _commit(
        wt,
        {f"projects/demo/specs/{_FR}-synthetic.md": _fr_md(status="in-progress")},
        "chore: start",
    )
    branch = f"claude/dev-{_FR}"
    assert dispatch._fr_status_on_branch(_FR, branch) == "in-progress"
    assert dispatch._handed_off_reason(_FR, "dev") is not None
    frs = dispatch.load_frs()
    assert [fr["id"] for fr in dispatch.runnable_review_frs(frs)] == [_FR]


# covers hub-tooling FR-0024:AC-3
def test_the_review_read_returns_the_projects_library_file_not_the_decoy(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    rev = _worktree(env, "rev")
    own = b"## Request changes\n\nThe project's own filed review (synthetic).\n"
    _commit(rev, {f"projects/demo/specs/_reviews/{_FR}-r1.md": own}, "review: r1")
    assert dispatch._newest_review_on_branch(_FR)[1] == f"specs/_reviews/{_FR}-r1.md"
    assert dispatch._read_review_md_on_branch(_FR) == own.decode("utf-8")
    assert dispatch._resolve_rework_verdict(_FR, None) == "request-changes"


# covers hub-tooling FR-0024:AC-3
def test_gate_status_reads_the_projects_evidence(tmp_path, monkeypatch):
    def evidence(verdict: str) -> str:
        return f"---\nfr: {_FR}\ngate: arch\nverdict: {verdict}\nby: architect\n---\n"

    env = _make_repo(
        tmp_path, top_files={f"specs/_gates/{_FR}-arch.md": evidence("changes-requested")}
    )
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    _commit(wt, {f"projects/demo/specs/_gates/{_FR}-arch.md": evidence("pass")}, "gate")
    assert dispatch.gate_status(_FR, "arch") == "pass"
    assert dispatch.gate_status(_FR, "arch", ref="main") == "missing"


def _rev_scenario(tmp_path, monkeypatch, *, legacy: bool = False, own: bool = True):
    env = _make_repo(
        tmp_path,
        project_files={"REVIEW.md": _fixture("legacy-REVIEW.md")} if legacy else None,
    )
    _point(monkeypatch, dispatch, env)
    dev = _worktree(env, "dev")
    _commit(dev, {"projects/demo/src/a.py": "a = 2\n"}, "feat: synthetic change")
    _git(env.top, "push", "-q", "origin", f"claude/dev-{_FR}")
    rev = env.proj / ".claude" / "worktrees" / f"rev-{_FR}"
    _git(env.top, "worktree", "add", "-q", "-b", f"claude/rev-{_FR}", str(rev), f"claude/dev-{_FR}")
    if own:
        _commit(
            rev,
            {"projects/demo/REVIEW.md": _fixture("reviewer-REVIEW.md")},
            "test: reviewer handoff",
        )
    verdict = tmp_path / "verdict.md"
    _write(verdict, _fixture("reviewer-REVIEW.md"))
    dispatch._save_pr_record(_FR, "dev", {"pr_number": 7})
    return env, rev, verdict


# covers hub-tooling FR-0024:AC-3
def test_a_reviewer_finalize_files_in_the_project_and_leaves_the_top_decoys(
    tmp_path, monkeypatch, capsys
):
    env, rev, verdict = _rev_scenario(tmp_path, monkeypatch)
    rc = dispatch.cmd_finalize(
        _FR, "rev", apply=True, draft=True, adapter=None, verdict_file=verdict
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    branch = f"claude/rev-{_FR}"
    lib = f"projects/demo/specs/_reviews/{_FR}-r1.md"
    assert _git(env.top, "show", f"{branch}:{lib}") + "\n" == _fixture(
        "reviewer-REVIEW.md"
    ).decode("utf-8")
    assert _git(env.top, "ls-tree", branch, "--", "projects/demo/REVIEW.md") == ""
    for rel, name in (
        ("REVIEW.md", "decoy-REVIEW.md"),
        (f"specs/_reviews/{_FR}-r1.md", "decoy-library-review.md"),
    ):
        assert _git(env.top, "rev-parse", f"{branch}:{rel}") == _git(
            env.top, "rev-parse", f"main:{rel}"
        )
        assert (rev / rel).read_bytes() == _fixture(name)
    assert not (rev / "projects" / "demo" / "REVIEW.md").exists()
    assert (rev / lib).read_bytes() == _fixture("reviewer-REVIEW.md")
    [kept] = _lines(out, "REVIEW-KEPT")
    assert f"specs/_reviews/{_FR}-r1.md" in kept and "Reviewer's own" in kept
    assert any(c[1:3] == ["pr", "review"] for c in env.gh)


# covers hub-tooling FR-0024:AC-3
def test_with_no_project_review_the_decoy_is_never_kept_or_filed(
    tmp_path, monkeypatch, capsys
):
    env, rev, verdict = _rev_scenario(tmp_path, monkeypatch, own=False)
    ok, parsed = dispatch._materialise_review_md(
        _FR, f"claude/rev-{_FR}", None, True, verdict_file=verdict
    )
    out = capsys.readouterr().out
    assert ok and parsed[0] == "request-changes", out
    assert "REVIEW-KEPT" not in out and len(_lines(out, "REVIEW-WRITTEN")) == 1
    branch = f"claude/rev-{_FR}"
    filed = _git(env.top, "show", f"{branch}:projects/demo/specs/_reviews/{_FR}-r1.md")
    assert "Decoy" not in filed and "FR-0001:AC-1" in filed
    assert _git(env.top, "rev-parse", f"{branch}:REVIEW.md") == _git(
        env.top, "rev-parse", "main:REVIEW.md"
    )


# covers hub-tooling FR-0024:AC-3
def test_a_legacy_project_review_on_the_merge_base_is_restored_not_removed(
    tmp_path, monkeypatch, capsys
):
    env, rev, verdict = _rev_scenario(tmp_path, monkeypatch, legacy=True)
    ok, _parsed = dispatch._materialise_review_md(
        _FR, f"claude/rev-{_FR}", None, True, verdict_file=verdict
    )
    out = capsys.readouterr().out
    assert ok, out
    branch = f"claude/rev-{_FR}"
    assert _git(env.top, "rev-parse", f"{branch}:projects/demo/REVIEW.md") == _git(
        env.top, "rev-parse", "main:projects/demo/REVIEW.md"
    )
    assert (rev / "projects" / "demo" / "REVIEW.md").read_bytes() == _fixture(
        "legacy-REVIEW.md"
    )
    assert _git(env.top, "show", f"{branch}:projects/demo/specs/_reviews/{_FR}-r1.md")
    assert _git(rev, "status", "--porcelain", "--untracked-files=no") == ""


# covers hub-tooling FR-0024:AC-3
def test_the_provenance_log_is_top_anchored_for_a_path_outside_the_project(
    tmp_path, monkeypatch, capsys
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    mnt = _worktree(env, "mnt")
    sha = _commit(mnt, {"other/b.py": "b = 2\n"}, "feat: from the reviewer")
    dispatch._save_pr_record(_FR, "mnt", {"ff_commits": [sha]})
    exempt = dispatch._mnt_provenance_exemptions(
        _FR, f"claude/mnt-{_FR}", "main", ["other/b.py"]
    )
    assert exempt == {"other/b.py"}, capsys.readouterr().out


# ---------------------------------------------------------------------------
# AC-4: git-returned paths are compared in footprint coordinates
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0024:AC-4
def test_a_project_rooted_mnt_reports_exactly_the_path_outside_the_project(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path, owns=("src/**",))
    _point(monkeypatch, dispatch, env)
    mnt = _worktree(env, "mnt")
    _commit(mnt, {"projects/demo/src/a.py": "a = 2\n", "other/b.py": "b = 2\n"}, "work")
    violations, err = dispatch.mnt_footprint_violations(_FR, f"claude/mnt-{_FR}")
    assert err is None and violations == ["other/b.py"]


# covers hub-tooling FR-0024:AC-4
def test_a_repo_rooted_mnt_compares_repo_relative_paths_with_owns(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path, owns=("lib/**",), layout=_fixture("layout-repo.yaml"))
    _point(monkeypatch, dispatch, env)
    mnt = _worktree(env, "mnt")
    _commit(mnt, {"lib/x.py": "x = 2\n"}, "work")
    assert dispatch.mnt_footprint_violations(_FR, f"claude/mnt-{_FR}") == ([], None)
    _commit(mnt, {"projects/demo/src/a.py": "a = 2\n"}, "more")
    assert dispatch.mnt_footprint_violations(_FR, f"claude/mnt-{_FR}") == (
        ["projects/demo/src/a.py"],
        None,
    )


# covers hub-tooling FR-0024:AC-4
def test_a_repo_rooted_allow_crossing_glob_is_top_anchored(tmp_path, monkeypatch, capsys):
    env = _make_repo(tmp_path, owns=("lib/**",), layout=_fixture("layout-repo.yaml"))
    _point(monkeypatch, dispatch, env)
    mnt = _worktree(env, "mnt")
    _commit(mnt, {"other/b.py": "b = 1\r\n"}, "line endings only")
    exempt, ok = dispatch._resolve_allow_crossing(
        _FR, f"claude/mnt-{_FR}", "main", ["other/**"], apply=True
    )
    assert ok and exempt == {"other/b.py"}, capsys.readouterr().out


# covers hub-tooling FR-0024:AC-4
def test_the_projects_own_control_plane_is_refused_and_the_repositorys_is_not(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    dev = _worktree(env, "dev")
    _commit(dev, {"projects/demo/scripts/deploy-gate.py": "# changed\n"}, "own gate")
    paths, err = dispatch._control_plane_branch_paths(_FR, "dev", f"claude/dev-{_FR}", True)
    assert err is None and paths == ["projects/demo/scripts/deploy-gate.py"]
    _git(dev, "reset", "-q", "--hard", "main")
    _commit(dev, {"scripts/deploy-gate.py": "# changed\n"}, "repository gate")
    assert dispatch._control_plane_branch_paths(_FR, "dev", f"claude/dev-{_FR}", True) == (
        [],
        None,
    )
    # Outside `owns:`, it is still an unowned path for `mnt`.
    mnt = _worktree(env, "mnt")
    _commit(mnt, {"scripts/deploy-gate.py": "# changed\n"}, "repository gate")
    assert dispatch.mnt_footprint_violations(_FR, f"claude/mnt-{_FR}") == (
        ["scripts/deploy-gate.py"],
        None,
    )


# covers hub-tooling FR-0024:AC-4
def test_an_uncommitted_change_to_the_projects_control_plane_is_refused(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    dev = _worktree(env, "dev")
    _write(dev / "scripts" / "deploy-gate.py", "# repository gate, edited\n")
    assert dispatch._uncommitted_control_plane_paths(_FR, "dev") == ([], None)
    _write(dev / "projects" / "demo" / "scripts" / "dispatch.py", "# edited\n")
    assert dispatch._uncommitted_control_plane_paths(_FR, "dev") == (
        ["projects/demo/scripts/dispatch.py"],
        None,
    )


# covers hub-tooling FR-0024:AC-4
def test_the_pr_change_size_counts_only_the_projects_tests(tmp_path, monkeypatch):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    dev = _worktree(env, "dev")
    covers = f"# {_COVERS_TAG} {_FR}:AC-1\n"
    # Reviewer r1: two project test files against one at the repository top,
    # so a prefix-blind count (1, the top's) differs from the project's (2).
    _commit(
        dev,
        {
            "projects/demo/tests/test_a.py": covers,
            "projects/demo/tests/test_b.py": covers,
            "tests/test_top.py": covers,
            "projects/demo/src/a.py": "a = 2\n",
        },
        "work",
    )
    size = dispatch._pr_change_size(f"claude/dev-{_FR}")
    assert size["files_touched"] == 4
    assert size["tests_changed"] == 2 and size["covers_delta"] == 2


_CODEOWNERS_CONFIG = 'owner_handle: "@synthetic-owner"\n'
_CODEOWNERS_BASE = "# synthetic owners\n\n# body\n\n# footer\n"
_CODEOWNERS_DEV = "# synthetic owners\n\n# body\n\n# footer\n# dev line\n"
_CODEOWNERS_MAIN = "# main line\n# synthetic owners\n\n# body\n\n# footer\n"
_CODEOWNERS_MERGED = "# main line\n# synthetic owners\n\n# body\n\n# footer\n# dev line\n"


def _index_scenario(tmp_path, monkeypatch, *, where: str):
    """`claude/dev-FR-0001` and `main` both rewrite an INDEX.md — the
    project's (`where="project"`) or the repository top's (`"top"`) — so
    merging `origin/main` conflicts on exactly that one path. The project
    carries its real indexer and a gate that passes; the top a gate that
    fails."""
    project_files: dict[str, str | bytes] = {
        f"scripts/{n}": (_SCRIPTS_DIR / n).read_bytes() for n in _INDEXER_SCRIPTS
    }
    project_files["scripts/deploy-gate.py"] = "import sys\nsys.exit(0)\n"
    project_files[".agent-team/codeowners-config.yaml"] = _CODEOWNERS_CONFIG
    project_files["CODEOWNERS"] = _CODEOWNERS_BASE
    project_files[f"specs/{_FR}-synthetic.md"] = _fr_md()
    project_files["specs/FR-0002-synthetic.md"] = _fr_md("FR-0002")
    env = _make_repo(tmp_path, project_files=project_files)
    _point(monkeypatch, dispatch, env)
    index = "projects/demo/specs/INDEX.md" if where == "project" else "specs/INDEX.md"
    dev = _worktree(env, "dev")
    own = _commit(
        dev,
        {
            "projects/demo/src/thing.py": "thing\n",
            index: "# Spec index\n\ndev's index\n",
            "projects/demo/CODEOWNERS": _CODEOWNERS_DEV,
        },
        "dev: work",
    )
    _write(dev / "projects" / "demo" / "PR_BODY.md", _fixture("project-PR_BODY.md"))
    landed = _commit(
        env.top,
        {
            "projects/demo/specs/FR-0002-synthetic.md": _fr_md("FR-0002", status="merged"),
            index: "# Spec index\n\nmain's index\n",
            "projects/demo/CODEOWNERS": _CODEOWNERS_MAIN,
        },
        "feat: landed on main",
    )
    _git(env.top, "push", "-q", "origin", "main")
    return env, dev, own, landed


# covers hub-tooling FR-0024:AC-4
# covers hub-tooling FR-0024:AC-2
def test_a_revalidate_conflict_on_the_projects_index_is_resolved_by_the_projects_indexer(
    tmp_path, monkeypatch, capsys
):
    env, dev, own, landed = _index_scenario(tmp_path, monkeypatch, where="project")
    routed = dispatch.subprocess.run
    seen: list[tuple[list[str], str | None]] = []

    def recording(cmd, *a, **k):
        seen.append(([str(c) for c in cmd], str(k.get("cwd")) if k.get("cwd") else None))
        return routed(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", recording)
    rc = dispatch.cmd_finalize(
        _FR, "dev", apply=True, draft=True, adapter=None, revalidate=True
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    [resolved] = _lines(out, "MERGE-RESOLVED")
    assert "specs/INDEX.md" in resolved and _lines(out, "ERROR") == []
    [revalidated] = _lines(out, "REVALIDATE  ")
    assert "gate=pass" in revalidated
    project = dev / "projects" / "demo"
    scripts_run = [
        (Path(argv[1]), cwd)
        for argv, cwd in seen
        if argv[0] == sys.executable and argv[1].endswith(".py")
    ]
    indexer = [p for p in scripts_run if p[0].name == "index-specs.py"]
    gates = [p for p in scripts_run if p[0].name == "deploy-gate.py"]
    assert indexer == [(project / "scripts" / "index-specs.py", str(project))]
    assert gates and all(
        p == (project / "scripts" / "deploy-gate.py", str(project)) for p in gates
    )
    adds = [argv for argv, _ in seen if argv[:1] == ["git"] and "add" in argv]
    assert [a[a.index("add"):] for a in adds] == [["add", "--", "projects/demo/specs/INDEX.md"]]
    branch = f"claude/dev-{_FR}"
    assert _git(env.top, "log", "-1", "--format=%P", branch).split() == [own, landed]
    assert (project / "CODEOWNERS").read_text(encoding="utf-8") == _CODEOWNERS_MERGED
    assert _git(dev, "status", "--porcelain", "--untracked-files=no") == ""
    committed = _git(dev, "show", f"{branch}:projects/demo/specs/INDEX.md")
    assert "<<<<<<<" not in committed and "FR-0002" in committed


# covers hub-tooling FR-0024:AC-4
def test_a_conflict_confined_to_the_repository_top_index_is_todays_error(
    tmp_path, monkeypatch, capsys
):
    env, dev, own, _landed = _index_scenario(tmp_path, monkeypatch, where="top")
    rc = dispatch.cmd_finalize(
        _FR, "dev", apply=True, draft=True, adapter=None, revalidate=True
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    [error] = _lines(out, "ERROR")
    assert "origin/main" in error and "failed" in error and "left for a human" in error
    assert "MERGE-RESOLVED" not in out
    assert "UU specs/INDEX.md" in _git(dev, "status", "--porcelain")
    assert _git(env.top, "rev-parse", f"claude/dev-{_FR}") == own and env.gh == []


# ---------------------------------------------------------------------------
# AC-5: a repo-rooted footprint becomes absolute grants
# ---------------------------------------------------------------------------


def _settings(wt: Path) -> dict:
    return json.loads(
        (wt / "projects" / "demo" / ".claude" / "settings.local.json").read_text(
            encoding="utf-8"
        )
    )


# covers hub-tooling FR-0024:AC-5
def test_the_absolute_rule_root_is_double_slash_and_the_posix_path():
    root = dispatch._claude_absolute_rule_root(Path(os.getcwd()))
    assert root.startswith("//") and root.endswith("/") and "\\" not in root
    if sys.platform == "win32":
        drive = os.path.realpath(os.getcwd())[0].lower()
        assert root.startswith(f"//{drive}/")


@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
# covers hub-tooling FR-0024:AC-5
def test_a_repo_rooted_footprint_gets_absolute_owns_grants_and_the_worktree_root(
    tmp_path, monkeypatch, role
):
    env = _make_repo(tmp_path, owns=("lib/**",), layout=_fixture("layout-repo.yaml"))
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, role)
    adapter = dispatch.ClaudeCodeAdapter()
    adapter.write_worktree_settings(wt, role, _FR)
    perms = _settings(wt)["permissions"]
    anchor = dispatch._claude_absolute_rule_root(wt)
    assert anchor.startswith("//")
    assert f"Edit({anchor}lib/**)" in perms["allow"]
    assert f"Write({anchor}lib/**)" in perms["allow"]
    assert "Edit(lib/**)" not in perms["allow"] and "Write(lib/**)" not in perms["allow"]
    assert perms["additionalDirectories"] == [Path(os.path.realpath(wt)).as_posix()]
    # Denies and the static role permissions stay relative to the agent's cwd.
    assert not any(d.startswith(("Edit(/", "Write(/")) for d in perms["deny"])
    absolute = [a for a in perms["allow"] if a.startswith(("Edit(/", "Write(/"))]
    assert sorted(absolute) == sorted([f"Edit({anchor}lib/**)", f"Write({anchor}lib/**)"])
    relative = getattr(adapter, f"{role}_permissions", None)
    if role in ("dev", "mnt"):
        expected = relative(_FR)
        assert perms["deny"] == expected["deny"]
        assert [a for a in perms["allow"] if a not in absolute] == [
            a for a in expected["allow"] if a not in ("Edit(lib/**)", "Write(lib/**)")
        ]


# covers hub-tooling FR-0024:AC-5
def test_the_gate_review_grant_stays_relative_with_no_additional_directory(
    tmp_path, monkeypatch
):
    env = _make_repo(tmp_path, owns=("lib/**",), layout=_fixture("layout-repo.yaml"))
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "gat")
    dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, "gat", _FR, gate_id="arch")
    perms = _settings(wt)["permissions"]
    assert "additionalDirectories" not in perms
    assert f"Edit(specs/_gates/{_FR}-arch.md)" in perms["allow"]


# covers hub-tooling FR-0024:AC-5
def test_cursor_keeps_relative_owns_grants(tmp_path, monkeypatch):
    env = _make_repo(tmp_path, owns=("lib/**",), layout=_fixture("layout-repo.yaml"))
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    dispatch.CursorAdapter().write_worktree_settings(wt, "dev", _FR)
    perms = json.loads(
        (wt / "projects" / "demo" / ".cursor" / "cli.json").read_text(encoding="utf-8")
    )["permissions"]
    assert "Write(lib/**)" in perms["allow"] and "additionalDirectories" not in perms


@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt", "gat"])
# covers hub-tooling FR-0024:AC-5
def test_a_project_rooted_subdirectory_permission_file_is_byte_identical_to_todays(
    tmp_path, monkeypatch, pre_fr_dispatch, role
):
    env = _make_repo(tmp_path, owns=("src/**", "lib/**"))
    _point(monkeypatch, dispatch, env)
    _point(monkeypatch, pre_fr_dispatch, env)
    wt = _worktree(env, role)
    kw = {"gate_id": "arch"} if role == "gat" else {}
    dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, role, _FR, **kw)
    pre_fr_dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, role, _FR, **kw)
    ours = (wt / "projects" / "demo" / ".claude" / "settings.local.json").read_bytes()
    todays = (wt / ".claude" / "settings.local.json").read_bytes()
    assert ours == todays


# ---------------------------------------------------------------------------
# AC-6: a malformed layout refuses early
# ---------------------------------------------------------------------------


def _malformed(tmp_path, monkeypatch) -> tuple[SimpleNamespace, list[list[str]]]:
    env = _make_repo(tmp_path, layout=_fixture("layout-malformed.yaml"))
    _point(monkeypatch, dispatch, env)
    routed = dispatch.subprocess.run
    seen: list[list[str]] = []

    def recording(cmd, *a, **k):
        seen.append([str(c) for c in cmd])
        return routed(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", recording)
    return env, seen


def _entry(name: str, apply: bool):
    adapter = dispatch.ClaudeCodeAdapter()
    if name == "tick":
        return lambda: dispatch.cmd_tick(apply, adapter, role="dev")
    if name == "wave":
        return lambda: dispatch.cmd_wave(apply, adapter, poll_interval=0.01)
    if name == "finalize":
        return lambda: dispatch.cmd_finalize(_FR, "dev", apply=apply, draft=True, adapter=adapter)
    return lambda: dispatch.spawn_role(_FR, "dev", apply=apply, adapter=adapter)


@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
@pytest.mark.parametrize("entry", ["tick", "wave", "finalize", "spawn_role"])
# covers hub-tooling FR-0024:AC-6
def test_a_malformed_layout_refuses_every_entry_point_before_anything_happens(
    tmp_path, monkeypatch, capsys, entry, apply
):
    env, seen = _malformed(tmp_path, monkeypatch)
    before = sorted(p.relative_to(env.top).as_posix() for p in env.top.rglob("*"))
    result = _entry(entry, apply)()
    out = capsys.readouterr().out
    if entry == "spawn_role":
        status, pid, wt = result
        assert status.startswith("error:") and pid is None and wt is None
        message = status
    else:
        assert result != 0, out
        [message] = _lines(out, "ERROR")
    assert ".agent-team/layout.yaml" in message and "footprint_root" in message
    assert all(c[-2:] == ["rev-parse", "--show-prefix"] for c in seen), seen
    assert env.gh == []
    assert not (env.proj / ".claude" / "worktrees").exists()
    after = sorted(p.relative_to(env.top).as_posix() for p in env.top.rglob("*"))
    added = [p for p in after if p not in before]
    if entry == "wave":
        # FR-0014: the wave still writes its synthesis, and nothing else.
        assert added and all(p.startswith("projects/demo/_dispatch") for p in added)
        assert any(p.endswith(".md") and "wave-" in p for p in added), added
    else:
        assert added == []


# ---------------------------------------------------------------------------
# AC-7: hub-tooling's .gitignore covers the dispatch artifacts
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0024:AC-7
def test_hub_toolings_gitignore_covers_the_permission_file_and_the_venv():
    gitignore = _TEMPLATE_DIR.parent / "projects" / "hub-tooling" / ".gitignore"
    if not gitignore.is_file():
        pytest.skip("not inside the hub (no projects/hub-tooling/.gitignore)")
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    assert ".claude/settings.local.json" in lines
    assert f"{dispatch.VENV_DIRNAME}/" in lines


# ---------------------------------------------------------------------------
# Bite checks: the pre-FR dispatcher gets each subdirectory case wrong
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0024:AC-2
def test_bite_pre_fr_runs_the_agent_and_writes_its_permission_file_at_the_worktree_root(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, pre_fr_dispatch, env)
    wt = _worktree(env, "dev")
    preview = pre_fr_dispatch.ClaudeCodeAdapter().dry_run_preview(_FR, "dev", wt)
    assert f"cwd={wt};" in preview
    pre_fr_dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, "dev", _FR)
    assert (wt / ".claude" / "settings.local.json").is_file()
    assert not (wt / "projects" / "demo" / ".claude").exists()


# covers hub-tooling FR-0024:AC-3
def test_bite_pre_fr_misses_the_branch_status_and_reads_the_decoy_review(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    env = _make_repo(tmp_path)
    _point(monkeypatch, pre_fr_dispatch, env)
    dev = _worktree(env, "dev")
    _commit(
        dev,
        {f"projects/demo/specs/{_FR}-synthetic.md": _fr_md(status="in-progress")},
        "chore: start",
    )
    assert pre_fr_dispatch._fr_status_on_branch(_FR, f"claude/dev-{_FR}") is None
    rev = _worktree(env, "rev")
    own = "## Request changes\n\nThe project's own filed review (synthetic).\n"
    _commit(rev, {f"projects/demo/specs/_reviews/{_FR}-r1.md": own}, "review: r1")
    assert pre_fr_dispatch._read_review_md_on_branch(_FR) == _fixture(
        "decoy-library-review.md"
    ).decode("utf-8")


# covers hub-tooling FR-0024:AC-4
def test_bite_pre_fr_compares_repo_relative_paths_as_project_relative(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    env = _make_repo(tmp_path, owns=("src/**",))
    _point(monkeypatch, pre_fr_dispatch, env)
    mnt = _worktree(env, "mnt")
    _commit(mnt, {"projects/demo/src/a.py": "a = 2\n", "other/b.py": "b = 2\n"}, "work")
    violations, _err = pre_fr_dispatch.mnt_footprint_violations(_FR, f"claude/mnt-{_FR}")
    assert violations == ["other/b.py", "projects/demo/src/a.py"]
    dev = _worktree(env, "dev")
    _commit(dev, {"projects/demo/scripts/deploy-gate.py": "# changed\n"}, "own gate")
    assert pre_fr_dispatch._control_plane_branch_paths(
        _FR, "dev", f"claude/dev-{_FR}", True
    ) == ([], None)


# ---------------------------------------------------------------------------
# Reviewer additions (round 1)
# ---------------------------------------------------------------------------


def _show_prefix_calls(seen: list[list[str]]) -> list[list[str]]:
    return [c for c in seen if c[-2:] == ["rev-parse", "--show-prefix"]]


# covers hub-tooling FR-0024:AC-1
def test_a_nested_repository_a_gitfile_repository_and_a_worktree_each_give_their_own_prefix(
    tmp_path, monkeypatch
):
    """The `.git`-exists shortcut must agree with `rev-parse --show-prefix`
    wherever `.git` is a directory (a nested repository) or a file (a linked
    worktree; a `--separate-git-dir` repository, the shape a submodule has),
    and a project below any of those tops is prefixed relative to the
    innermost repository, never the outer one."""
    env = _make_repo(tmp_path)
    # A nested repository with its own `.git` directory inside the outer one.
    inner = env.top / "projects" / "sub"
    _init_repo(inner)
    _write(inner / "app" / "README.md", "synthetic\n")
    _git(inner, "add", "-A")
    _git(inner, "commit", "-q", "-m", "inner")
    # A repository whose `.git` is a file, as a submodule's is.
    gitfile = tmp_path / "gitfile-repo"
    _git(
        tmp_path,
        "init",
        "-q",
        "--separate-git-dir",
        str(tmp_path / "gitfile.git"),
        str(gitfile),
    )
    _write(gitfile / "pkg" / "app" / "README.md", "synthetic\n")
    assert (gitfile / ".git").is_file()
    wt = _worktree(env, "dev")
    assert (wt / ".git").is_file()

    seen: list[list[str]] = []

    def spy(cmd, *a, **k):
        seen.append([str(c) for c in cmd])
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", spy)
    cases = [
        (inner, ""),
        (inner / "app", "app/"),
        (gitfile, ""),
        (gitfile / "pkg" / "app", "pkg/app/"),
        (wt, ""),
        (wt / "projects" / "demo", _PREFIX),
    ]
    for root, expected in cases:
        monkeypatch.setattr(dispatch, "_PROJECT_PREFIX_CACHE", {})
        monkeypatch.setattr(dispatch, "REPO_ROOT", root)
        before = len(_show_prefix_calls(seen))
        assert dispatch._project_prefix() == expected, root
        ran = len(_show_prefix_calls(seen)) - before
        # A working-tree top level answers "" without spawning git.
        assert ran == (0 if (root / ".git").exists() else 1), (root, ran)
        # ...and git itself agrees with the answer.
        assert _git(root, "rev-parse", "--show-prefix") == expected, root


def _make_top_level_repo(tmp_path: Path, *, owns, layout: str | None) -> SimpleNamespace:
    """A project that is its own repository (prefix "")."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    files: dict[str, str | bytes] = {
        f"specs/{_FR}-synthetic.md": _fr_md(owns=owns),
        "src/a.py": "a = 1\n",
        "lib/x.py": "x = 1\n",
        ".gitignore": "**/.claude/worktrees/\n**/.claude/settings.local.json\n",
    }
    if layout is not None:
        files[".agent-team/layout.yaml"] = layout
    for rel, content in files.items():
        _write(repo / rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return SimpleNamespace(top=repo, proj=repo, bare=bare, gh=[], tmp=tmp_path)


@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
# covers hub-tooling FR-0024:AC-5
def test_a_repo_rooted_layout_in_a_project_that_is_its_own_repository_writes_todays_file(
    tmp_path, monkeypatch, pre_fr_dispatch, role
):
    """AC-5 "Otherwise": `footprint_root: repo` alone is not enough. At
    prefix "" the file is byte-identical to the pre-FR dispatcher's, with no
    absolute rule and no `additionalDirectories` (AC-1's fixed clause)."""
    env = _make_top_level_repo(
        tmp_path, owns=("lib/**", "src/**"), layout=_fixture("layout-repo.yaml")
    )
    _point(monkeypatch, dispatch, env)
    _point(monkeypatch, pre_fr_dispatch, env)
    assert dispatch._project_prefix() == ""
    wt = _worktree(env, role)
    path = wt / ".claude" / "settings.local.json"
    pre_fr_dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, role, _FR)
    todays = path.read_bytes()
    dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, role, _FR)
    assert path.read_bytes() == todays
    perms = json.loads(todays)["permissions"]
    assert "additionalDirectories" not in perms
    assert not any(a.startswith(("Edit(/", "Write(/")) for a in perms["allow"])


# covers hub-tooling FR-0024:AC-5
def test_the_absolute_anchor_and_the_additional_directory_name_the_same_directory(
    tmp_path, monkeypatch
):
    """The rule root `//<drive>/<rest>/` and `additionalDirectories`'
    `<DRIVE>:/<rest>` are two spellings of one directory: the worktree root,
    resolved (no 8.3 short name, no backslash), never the project inside
    it. `//<DRIVE>:/` is not a spelling Claude Code reads as a drive."""
    env = _make_repo(tmp_path, owns=("lib/**",), layout=_fixture("layout-repo.yaml"))
    _point(monkeypatch, dispatch, env)
    wt = _worktree(env, "dev")
    dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, "dev", _FR)
    perms = _settings(wt)["permissions"]
    [extra] = perms["additionalDirectories"]
    [grant] = [a for a in perms["allow"] if a.startswith("Edit(//")]
    anchor = grant[len("Edit(") : -len("lib/**)")]
    assert anchor.startswith("//") and anchor.endswith("/") and "\\" not in anchor
    resolved = Path(os.path.realpath(wt)).as_posix()
    assert extra == resolved and "~" not in extra
    if sys.platform == "win32":
        drive, rest = resolved.split(":", 1)
        assert anchor == f"//{drive.lower()}{rest}/"
        assert ":" not in anchor
    else:
        assert anchor == f"/{resolved}/"
    assert not resolved.endswith("projects/demo")


# covers hub-tooling FR-0024:AC-6
@pytest.mark.parametrize("entry", ["tick", "finalize"])
def test_a_drive_letter_gate_directory_refuses_like_any_malformed_layout(
    tmp_path, monkeypatch, capsys, entry
):
    """DEC-0027's drive-letter rejection is one of the loader's errors, so it
    refuses early too, naming the file, not only an invalid
    `footprint_root`."""
    env = _make_repo(
        tmp_path,
        layout='footprint_root: repo\ngate:\n  source_dirs: ["C:synthetic"]\n',
    )
    _point(monkeypatch, dispatch, env)
    result = _entry(entry, True)()
    out = capsys.readouterr().out
    assert result != 0, out
    [message] = _lines(out, "ERROR")
    assert ".agent-team/layout.yaml" in message and "source_dirs" in message
    assert env.gh == [] and not (env.proj / ".claude" / "worktrees").exists()


def _rework_scenario(tmp_path, monkeypatch, *, tests_in_project: bool):
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    dev = _worktree(env, "dev")
    _commit(dev, {"projects/demo/src/a.py": "a = 2\n"}, "feat: synthetic change")
    rev = env.proj / ".claude" / "worktrees" / f"rev-{_FR}"
    _git(
        env.top, "worktree", "add", "-q", "-b", f"claude/rev-{_FR}", str(rev),
        f"claude/dev-{_FR}",
    )
    test_path = (
        "projects/demo/tests/test_rework.py" if tests_in_project else "tests/test_rework.py"
    )
    _commit(
        rev,
        {
            f"projects/demo/specs/_reviews/{_FR}-r1.md": (
                "## Request changes\n\nSynthetic review.\n"
            ),
            test_path: f"# {_COVERS_TAG} {_FR}:AC-1\ndef test_x():\n    assert False\n",
        },
        "test: reviewer round 1",
    )
    return env, dev


# covers hub-tooling FR-0024:AC-2
def test_the_rework_precondition_reads_the_projects_review_and_tests(
    tmp_path, monkeypatch
):
    _env, dev = _rework_scenario(tmp_path, monkeypatch, tests_in_project=True)
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert f"specs/_reviews/{_FR}-r1.md" in note
    assert (dev / "projects" / "demo" / "specs" / "_reviews" / f"{_FR}-r1.md").is_file()


# covers hub-tooling FR-0024:AC-2
def test_the_rework_precondition_ignores_coverage_tests_at_the_repository_top(
    tmp_path, monkeypatch
):
    """A tagged test in the repository's own `tests/`, outside the project,
    is not the project's `tests/`: the precondition fails."""
    _rework_scenario(tmp_path, monkeypatch, tests_in_project=False)
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert not ok and f"no {_COVERS_TAG} test files" in note, note


# covers hub-tooling FR-0024:AC-2
def test_a_rework_round_runs_pytest_and_writes_its_brief_in_the_project(
    tmp_path, monkeypatch
):
    _env, dev = _rework_scenario(tmp_path, monkeypatch, tests_in_project=True)
    routed = dispatch.subprocess.run
    pytest_cwds: list[str] = []

    def recording(cmd, *a, **k):
        argv = [str(c) for c in cmd]
        if argv[1:3] == ["-m", "pytest"]:
            pytest_cwds.append(str(k.get("cwd")))
            return SimpleNamespace(
                returncode=1, stdout="FAILED tests/test_rework.py::test_x\n", stderr=""
            )
        return routed(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", recording)
    spawned: list[tuple] = []

    def no_spawn(fr_id, role, **kw):
        spawned.append((fr_id, role, kw.get("extra_prompt")))
        return ("binary-not-found", None, None)

    monkeypatch.setattr(dispatch, "spawn_role", no_spawn)
    verdict, note = dispatch._run_one_rework_round(
        _FR, 2, 2, "## Request changes\n", True, dispatch.ClaudeCodeAdapter(), 1.0, 0.01
    )
    assert verdict is None and "re-dispatch failed" in note, note
    project = dev / "projects" / "demo"
    assert pytest_cwds == [str(project)]
    brief = project / "_dispatch" / f"round2-{_FR}-dev.md"
    assert brief.is_file()
    assert "tests/test_rework.py::test_x" in brief.read_text(encoding="utf-8")
    assert not (dev / "_dispatch").exists()
    [(_fr, role, prompt)] = spawned
    assert role == "dev" and f"_dispatch/round2-{_FR}-dev.md" in prompt


# covers hub-tooling FR-0024:AC-3
def test_a_dry_run_reviewer_finalize_reads_the_projects_staged_review_not_the_tops(
    tmp_path, monkeypatch
):
    """The index form `:<prefix>REVIEW.md`: a staged project review is
    pending; a staged edit to the repository-top decoy alone is not."""
    env = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, env)
    dev = _worktree(env, "dev")
    _commit(dev, {"projects/demo/src/a.py": "a = 2\n"}, "feat: synthetic change")
    rev = env.proj / ".claude" / "worktrees" / f"rev-{_FR}"
    _git(
        env.top, "worktree", "add", "-q", "-b", f"claude/rev-{_FR}", str(rev),
        f"claude/dev-{_FR}",
    )
    _write(rev / "REVIEW.md", "## Approve\n\nA staged edit to the repository-top decoy.\n")
    _git(rev, "add", "--", "REVIEW.md")
    assert dispatch._existing_review_md_source(_FR, rev, apply=False) is None
    _write(rev / "projects" / "demo" / "REVIEW.md", _fixture("reviewer-REVIEW.md"))
    _git(rev, "add", "--", "projects/demo/REVIEW.md")
    found = dispatch._existing_review_md_source(_FR, rev, apply=False)
    assert found is not None and found["source"] == "staged"
    assert found["blob"] == _git(rev, "rev-parse", ":projects/demo/REVIEW.md")


# covers hub-tooling FR-0024:AC-4
def test_mnt_narrowing_of_the_projects_control_plane_works_at_a_prefix(
    tmp_path, monkeypatch
):
    """`footprint_root: project`: an owned control-plane file inside the
    project is writable for `mnt`, its unowned sibling is off limits, and a
    same-named path at the repository top is not the project's control plane
    at all."""
    env = _make_repo(
        tmp_path,
        owns=(".agent-team/roles/x.md",),
        project_files={
            ".agent-team/roles/x.md": "x\n",
            ".agent-team/roles/y.md": "y\n",
        },
        top_files={".agent-team/roles/z.md": "z\n"},
    )
    _point(monkeypatch, dispatch, env)
    paths = {
        "projects/demo/.agent-team/roles/x.md",
        "projects/demo/.agent-team/roles/y.md",
        ".agent-team/roles/z.md",
    }
    assert dispatch._off_limits_worktree_paths(_FR, "mnt", paths) == [
        "projects/demo/.agent-team/roles/y.md"
    ]
    assert sorted(dispatch._off_limits_worktree_paths(_FR, "dev", paths)) == [
        "projects/demo/.agent-team/roles/x.md",
        "projects/demo/.agent-team/roles/y.md",
    ]


# covers hub-tooling FR-0024:AC-4
# covers hub-tooling FR-0024:AC-5
def test_a_repo_rooted_footprint_naming_the_projects_control_plane_fails_closed(
    tmp_path, monkeypatch
):
    """Developer finding 4: under `footprint_root: repo` the `owns:`-side
    protected-path derivation is not converted, so an FR naming the
    project's own control plane in repository coordinates gets no narrowing
    (FR-0024 Out of scope, "Known limitations").

    What holds: every role's permission file keeps the relative deny that
    covers the path from the agent's cwd; an uncommitted change refuses
    finalize for `mnt` (FR-0015 AC-3); a committed change refuses finalize
    for `dev` (FR-0015 AC-2). What does not (r2): FR-0015 AC-2 does not
    apply to `mnt`, so a change to the owned path that is already committed
    on `claude/mnt-<FR>` passes `mnt`'s footprint check as owned, as it would
    for a narrowed grant under `footprint_root: project`."""
    owned = "projects/demo/.agent-team/roles/x.md"
    env = _make_repo(
        tmp_path,
        owns=(owned,),
        layout=_fixture("layout-repo.yaml"),
        project_files={".agent-team/roles/x.md": "x\n"},
    )
    _point(monkeypatch, dispatch, env)
    assert dispatch._off_limits_worktree_paths(_FR, "mnt", {owned}) == [owned]
    for role in ("mnt", "dev"):
        wt = _worktree(env, role)
        dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, role, _FR)
        perms = _settings(wt)["permissions"]
        assert "Edit(.agent-team/**)" in perms["deny"], role
        assert "Write(.agent-team/**)" in perms["deny"], role
    mnt = env.proj / ".claude" / "worktrees" / f"mnt-{_FR}"
    dev = env.proj / ".claude" / "worktrees" / f"dev-{_FR}"
    _commit(mnt, {owned: "x, committed by mnt\n"}, "mnt: owned control-plane file")
    assert dispatch.mnt_footprint_violations(_FR, f"claude/mnt-{_FR}") == ([], None)
    _write(mnt / owned, "x, edited again and not committed\n")
    assert dispatch._uncommitted_control_plane_paths(_FR, "mnt") == ([owned], None)
    _commit(dev, {owned: "x, committed by dev\n"}, "dev: owned control-plane file")
    assert dispatch._control_plane_branch_paths(
        _FR, "dev", f"claude/dev-{_FR}", True
    ) == ([owned], None)


# ---------------------------------------------------------------------------
# Reviewer additions (round 2): AC-8, nothing else changes
# ---------------------------------------------------------------------------

# FR-0024's implementation commit and its Developer test commit. Fixed refs,
# so this check stays scoped to what this FR changed after later FRs move
# `dispatch.py` on; it skips where the refs are not reachable (a
# bootstrapped project, a squash-merged history).
_FR_IMPL_REF = "18c6845"
_FR_TESTS_REF = "ebedce7"
_EMIT_CALLS = {"_metrics_emit", "_emit_pr_event", "_emit_dispatch_run", "emit"}


def _hub_git(*args: str) -> subprocess.CompletedProcess:
    return _REAL_RUN(
        ["git", "-C", str(_TEMPLATE_DIR.parent), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _dispatch_ast_at(ref: str):
    import ast

    proc = _hub_git("show", f"{ref}:template/scripts/dispatch.py")
    if proc.returncode != 0 or not proc.stdout:
        pytest.skip(f"{ref}:template/scripts/dispatch.py not reachable")
    return ast.parse(proc.stdout)


def _ac8_shape(tree) -> dict:
    """The surfaces AC-8 freezes: every `gh` argv list literal, every
    metrics record kind and keyword field the dispatcher emits, and the PR
    record's change-size fields."""
    import ast

    gh = []
    kinds: set[str] = set()
    fields: set[str] = set()
    size_keys: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.List)
            and node.elts
            and isinstance(node.elts[0], ast.Constant)
            and node.elts[0].value == "gh"
        ):
            gh.append(
                tuple(e.value if isinstance(e, ast.Constant) else "<expr>" for e in node.elts)
            )
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in _EMIT_CALLS:
                if node.args and isinstance(node.args[0], ast.Constant):
                    kinds.add(node.args[0].value)
                fields |= {k.arg for k in node.keywords if k.arg}
        elif isinstance(node, ast.FunctionDef) and node.name == "_pr_change_size":
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict):
                    size_keys = sorted(k.value for k in ret.value.keys)
    return {"gh": sorted(gh), "kinds": kinds, "fields": fields, "size_keys": size_keys}


# covers hub-tooling FR-0024:AC-8
def test_the_fr_adds_no_metrics_kind_or_field_and_leaves_every_gh_call_as_it_was():
    before = _ac8_shape(_dispatch_ast_at(f"{_FR_IMPL_REF}^"))
    after = _ac8_shape(_dispatch_ast_at(_FR_IMPL_REF))
    # Sentinels: the extraction found the real surfaces, not empty sets.
    assert len(before["gh"]) >= 5 and {"pr.opened", "dispatch.run"} <= before["kinds"]
    assert {"tests_changed", "covers_delta"} <= set(before["size_keys"])
    assert after == before
    # Every `gh pr` argv still names the repository explicitly.
    assert all("--repo" in argv for argv in after["gh"] if argv[1:2] == ("pr",))


# covers hub-tooling FR-0024:AC-8
def test_the_frs_template_changes_are_the_dispatcher_and_its_own_tests_only():
    """No other template script, and neither `metrics_log.py` nor the
    metrics schema, changes in FR-0024's commits."""
    proc = _hub_git("diff", "--name-only", f"{_FR_IMPL_REF}^", _FR_TESTS_REF, "--", "template")
    if proc.returncode != 0:
        pytest.skip(f"{_FR_IMPL_REF}..{_FR_TESTS_REF} not reachable")
    changed = proc.stdout.split()
    assert "template/scripts/dispatch.py" in changed
    allowed = (
        "template/scripts/dispatch.py",
        "template/tests/unit/scripts/test_dispatch_subdirectory.py",
        "template/tests/fixtures/dispatch-subdirectory/",
    )
    assert [p for p in changed if not p.startswith(allowed)] == []
