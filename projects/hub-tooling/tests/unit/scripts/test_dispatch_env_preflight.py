"""Reviewer tests for FR-0011, the dispatcher half — `wave`/`tick`/`maintain`
run the environment pre-flight before any side effect and a blocking finding
stops them (AC-6), the classification reaches the metrics log through the
fields `dispatch.spawn` / `dispatch.wave` already carry (AC-7), the
`--skip-env-preflight` / `DISPATCH_SKIP_ENV_PREFLIGHT` override is honoured
and recorded (AC-8), pre-flight is read-only and bounded in apply and dry-run
alike and reaches the host through exactly one seam (AC-9 v2), and a project
that declares no stack is byte-identical to the pre-FR-0011 dispatcher
(AC-10).

Harness: the FR-0010 pattern — `dispatch.py` loaded by path with its path
globals pointed at a real temporary git repository, a fake harness adapter
that records spawns, gh preflight / reconcile / prune stubbed, the venv
provisioner stubbed. Host contact for FR-0011's checks is contained in one
name, `env_preflight.run_preflight` (AC-9 v2), and every test here either
stubs it with crafted findings or wraps the real function with injected I/O;
`subprocess.run` is wrapped process-wide to record every argv so a test can
prove no `docker` / `powershell` probe ran, and the module's socket path is
trapped. The "pre-FR dispatcher" that AC-7/AC-10 compare against is loaded
from `git show <pre-FR ref>:template/scripts/dispatch.py` — the hub commit
FR-0011 branched from; inside a bootstrapped project that object does not
exist and those comparisons skip.

Coverage annotations are written `# covers hub-tooling FR-0011:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_permissions.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_LOCK_PROJECT = (
    _TEMPLATE_DIR
    / "tests"
    / "fixtures"
    / "stack-profile"
    / "venv-provision"
    / "lock-project"
)
# The hub commit FR-0011 branched from (`main` after FR-0010 merged).
_PRE_FR_REF = "bd46dd3"

_FR = "FR-0001"
_ENV_STACK = "DISPATCH_STACK_TOOLS"
_ENV_SKIP = "DISPATCH_SKIP_ENV_PREFLIGHT"
_FULL_STACK = ["docker", "node", "npm", "npx", "python", "uv"]
_FULL_STACK_SEG = "stack=docker+node+npm+npx+python+uv"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import env_preflight
import metrics_log

_REAL_RUN_PREFLIGHT = env_preflight.run_preflight
_REAL_SUBPROCESS_RUN = subprocess.run


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0011")
assert dispatch.env_preflight is env_preflight, (
    "the dispatcher must import the env_preflight these tests stub"
)
assert dispatch._metrics is metrics_log


@functools.lru_cache(maxsize=1)
def _pre_fr_source() -> bytes | None:
    hub_root = _TEMPLATE_DIR.parent
    proc = _REAL_SUBPROCESS_RUN(
        [
            "git",
            "-C",
            str(hub_root),
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
    d = tmp_path_factory.mktemp("pre_fr0011_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0011")


# ---------------------------------------------------------------------------
# Synthetic FR + repo fixtures (FR-0010 harness shape)
# ---------------------------------------------------------------------------


def _fr_md(fr_id: str, status: str = "ready") -> str:
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
owns: ["src/thing.py", "tests/**"]
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


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = _REAL_SUBPROCESS_RUN(
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


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def _commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)
    _write(repo, f"specs/{_FR}-synthetic.md", _fr_md(_FR))
    for rel in (
        ".agent-team/roles/developer.md",
        ".agent-team/roles/reviewer.md",
        "scripts/deploy-gate.py",
        "src/thing.py",
    ):
        _write(repo, rel, f"# {rel}\n")
    _write(
        repo,
        ".gitignore",
        f".claude/settings.local.json\n.cursor/cli.json\n{dispatch.VENV_DIRNAME}/\n"
        "__pycache__/\n_dispatch/\nmetrics/\n",
    )
    _commit_all(repo, "base")
    return repo


def _declare_full_stack(repo: Path, compose_text: str = "services: {}\n") -> None:
    shutil.copy(_LOCK_PROJECT / "pyproject.toml", repo / "pyproject.toml")
    shutil.copy(_LOCK_PROJECT / "uv.lock", repo / "uv.lock")
    _write(repo, "package.json", '{"name": "synthetic", "private": true}\n')
    _write(repo, "docker-compose.yml", compose_text)
    _commit_all(repo, "declare stack")


def _dev_branch_in_progress(repo: Path) -> Path:
    wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    if not wt.exists():
        wt.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", "-b", f"claude/dev-{_FR}", str(wt), "main")
    spec = wt / "specs" / f"{_FR}-synthetic.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "status: ready", "status: in-progress"
        ),
        encoding="utf-8",
        newline="\n",
    )
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "status -> in-progress")
    return wt


def _point(monkeypatch, mod, r: Path) -> None:
    monkeypatch.setattr(mod, "REPO_ROOT", r)
    monkeypatch.setattr(mod, "SPECS_DIR", r / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", r / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", r / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", r / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "ensure_dev_venv", lambda wt: (True, "venv-created"))
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(
        mod,
        "reconcile_merged_prs",
        lambda apply=False, verbose=False: mod.ReconcileSummary(
            flipped=[], cleaned=[], skipped=[]
        ),
    )
    monkeypatch.setattr(mod, "prune_dead_locks", lambda verbose=True: 0)
    monkeypatch.setattr(metrics_log, "METRICS_DIR", r / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (r / "_dispatch").mkdir(exist_ok=True)


class _FakeAdapter:
    name = "fake"
    binary_name = "fake"

    def __init__(self, real) -> None:
        self.real = real
        self.spawns: list[tuple[str, str, Path, str | None]] = []

    def write_worktree_settings(self, wt_path: Path, role: str, fr_id: str) -> None:
        self.real.write_worktree_settings(wt_path, role, fr_id)

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.spawns.append((fr_id, role, wt_path, extra_prompt))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type":"result","subtype":"success"}\n', encoding="utf-8")
        return ("spawned", 999_999)

    def parse_log(self, log_path: Path):
        return SimpleNamespace(last_text="", result_subtype="success", tool_calls=0)

    def dry_run_preview(self, fr_id: str, role: str, wt_preview: Path) -> str:
        return f"fake-preview {role} {fr_id}"


# ---------------------------------------------------------------------------
# Findings, seam stubs and booby traps
# ---------------------------------------------------------------------------


def _f(
    cls: str, resource: str, severity: str, remedy: str = "synthetic remedy"
) -> env_preflight.Finding:
    return env_preflight.Finding(
        cls=cls, resource=resource, severity=severity, remedy=remedy
    )


_BLOCK_DOCKER = _f("docker-not-installed", "docker", "block", "install Docker Desktop")
_BLOCK_UV = _f("tool-missing", "uv", "block", "install uv")
_WARN_PORT = _f("port-collision", "5432", "warn", "port 5432 is already bound")
_WARN_NODE = _f("tool-missing", "node", "warn", "install node")
_WARN_APP = _f(
    "app-control-enforced", "windows-app-control", "warn", "WDAC is enforcing"
)


def _inject(
    monkeypatch,
    *findings,
    checks_ran=("docker", "tool-presence", "ports"),
    unresolved=(),
):
    """Stub the seam with crafted findings; return the recorded call list."""
    calls: list[dict] = []

    def stub(repo_root, tools, **kwargs):
        calls.append({"repo_root": repo_root, "tools": list(tools), **kwargs})
        return env_preflight.PreflightResult(
            findings=tuple(findings),
            checks_ran=tuple(checks_ran),
            unresolved_ports=tuple(unresolved),
        )

    monkeypatch.setattr(env_preflight, "run_preflight", stub)
    return calls


def _inject_real_with_fakes(
    monkeypatch, *, which=None, run=None, port_busy=None, platform="linux", find_uv=None
):
    """Wrap the real `run_preflight` with injected I/O — the whole module runs
    (compose parsing included) without touching the host."""

    def wrapped(repo_root, tools, **kwargs):
        kwargs.pop("find_uv", None)
        return _REAL_RUN_PREFLIGHT(
            repo_root,
            tools,
            find_uv=find_uv or (lambda: "/fake/uv"),
            run=run
            or (lambda argv, **kw: SimpleNamespace(returncode=0, stdout="27.0\n")),
            which=which or (lambda t: f"/fake/{t}"),
            port_busy=port_busy or (lambda p: False),
            platform=platform,
        )

    monkeypatch.setattr(env_preflight, "run_preflight", wrapped)


def _trap_checks(monkeypatch) -> None:
    """Every check function and the module's own host-touching names explode."""

    def boom(name):
        def _b(*a, **k):
            raise AssertionError(f"{name} must not run")

        return _b

    for name in (
        "check_docker",
        "check_tool_presence",
        "check_app_control",
        "check_ports",
        "_port_busy",
        "_query_windows_app_control",
    ):
        monkeypatch.setattr(env_preflight, name, boom(name))
    monkeypatch.setattr(
        env_preflight,
        "subprocess",
        SimpleNamespace(
            run=boom("subprocess.run"), TimeoutExpired=subprocess.TimeoutExpired
        ),
    )
    monkeypatch.setattr(
        env_preflight, "socket", SimpleNamespace(socket=boom("socket.socket"))
    )
    monkeypatch.setattr(
        env_preflight, "shutil", SimpleNamespace(which=boom("shutil.which"))
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv(_ENV_STACK, raising=False)
    monkeypatch.delenv(_ENV_SKIP, raising=False)


@pytest.fixture
def argv_log(monkeypatch) -> list[list[str]]:
    """Process-wide `subprocess.run` wrapper: git still runs; every argv is
    recorded so a test can assert no `docker` / `powershell` probe happened."""
    seen: list[list[str]] = []

    def wrapped(argv, *a, **k):
        seen.append(
            [str(x) for x in (argv if isinstance(argv, (list, tuple)) else [argv])]
        )
        return _REAL_SUBPROCESS_RUN(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", wrapped)
    return seen


def _host_probes(argv_log: list[list[str]]) -> list[list[str]]:
    return [
        a
        for a in argv_log
        if a
        and Path(a[0]).name.lower().split(".")[0] in {"docker", "powershell", "pwsh"}
    ]


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    r = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, r)
    return r


@pytest.fixture
def stack_repo(repo) -> Path:
    _declare_full_stack(repo)
    assert dispatch.detected_stack_tools() == _FULL_STACK
    return repo


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter(dispatch.ClaudeCodeAdapter())


def _records() -> list[dict]:
    d = metrics_log.METRICS_DIR
    if not d.exists():
        return []
    recs = [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    for r in recs:
        assert metrics_log.validation_errors(r) == [], r
    return recs


def _kind(kind: str) -> list[dict]:
    return [r for r in _records() if r["kind"] == kind]


def _preflight_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if "PREFLIGHT" in ln or "WOULD-BLOCK" in ln]


def _tree_digest(root: Path, exclude: tuple[str, ...] = (".git",)) -> str:
    if not root.exists():
        return "absent"
    h = hashlib.sha256()
    for p in sorted(
        x for x in root.rglob("*") if x.is_file() and not set(exclude) & set(x.parts)
    ):
        if p.parent == root and p.name.startswith("wave-") and p.suffix == ".md":
            # The wave synthesis report: `_write_wave_synthesis` writes it in
            # dry-run too, on the pre-FR-0011 dispatcher as well (see the
            # REVIEW.md FINDINGS on AC-9's `_dispatch/` clause). Not this FR's.
            continue
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _snapshot(repo: Path) -> dict:
    return {
        "refs": _git(repo, "for-each-ref"),
        "status": _git(repo, "status", "--porcelain"),
        "worktrees": _git(repo, "worktree", "list", "--porcelain"),
        "dispatch": _tree_digest(repo / "_dispatch"),
        "metrics": _tree_digest(repo / "metrics"),
        "tree": _tree_digest(repo, (".git", "metrics", "_dispatch")),
    }


def _role_wt(repo: Path, role: str) -> Path:
    return repo / ".claude" / "worktrees" / f"{role}-{_FR}"


def _trap_side_effects(monkeypatch) -> None:
    for name in ("ensure_role_worktree", "ensure_dev_venv", "spawn_role"):
        monkeypatch.setattr(
            dispatch,
            name,
            lambda *a, _n=name, **k: pytest.fail(f"{_n} ran after a blocking finding"),
        )


# ---------------------------------------------------------------------------
# AC-6: pre-flight before any side effect; block stops; warn proceeds; OK
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-6
@pytest.mark.parametrize("cmd", ["tick", "maintain", "wave"])
def test_blocking_finding_stops_each_command_before_any_side_effect(
    cmd, stack_repo, adapter, capsys, monkeypatch
):
    _inject(monkeypatch, _BLOCK_DOCKER, _WARN_PORT, _BLOCK_UV)
    _trap_side_effects(monkeypatch)
    before = _snapshot(stack_repo)
    if cmd == "tick":
        rc = dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR])
    elif cmd == "maintain":
        rc = dispatch.cmd_oneshot(_FR, "mnt", apply=True, adapter=adapter)
    else:
        rc = dispatch.cmd_wave(
            apply=True, adapter=adapter, fr_filter=[_FR], poll_interval=0.01
        )
    assert rc != 0
    out = capsys.readouterr().out
    blocks = [ln for ln in out.splitlines() if "PREFLIGHT BLOCK" in ln]
    assert len(blocks) == 2
    for ln, f in zip(blocks, (_BLOCK_DOCKER, _BLOCK_UV)):
        assert (
            f.cls in ln
            and f"resource={f.resource}" in ln
            and f"remedy={f.remedy}" in ln
        )
    # The warn finding is still reported, on its own line, and nothing else
    # claims to be a spawn.
    assert sum("PREFLIGHT WARN" in ln for ln in out.splitlines()) == 1
    assert "SPAWNED" not in out and "WOULD-SPAWN" not in out
    # No worktree, branch, venv, lock, agent, or spawn record; tree untouched.
    after = _snapshot(stack_repo)
    assert after["refs"] == before["refs"] and after["worktrees"] == before["worktrees"]
    assert after["tree"] == before["tree"] and after["dispatch"] == before["dispatch"]
    assert adapter.spawns == [] and not (stack_repo / ".claude" / "worktrees").exists()
    assert list((stack_repo / "_dispatch").glob("*.lock")) == []
    assert _kind("dispatch.spawn") == [] and _kind("dispatch.run") == []


# covers hub-tooling FR-0011:AC-6
def test_wave_phase0_ordering_gh_preflight_then_env_preflight_then_nothing_else(
    stack_repo, adapter, capsys, monkeypatch
):
    """Adversarial ordering: the env pre-flight runs inside Phase 0 *after*
    `_gh_preflight`, and a gh failure means it never runs at all; a block
    means no `ensure_role_worktree` call follows."""
    order: list[str] = []
    monkeypatch.setattr(
        dispatch,
        "_gh_preflight",
        lambda verbose=False: order.append("gh") or (True, None),
    )
    calls = _inject(monkeypatch, _BLOCK_DOCKER)
    real_stub = env_preflight.run_preflight
    monkeypatch.setattr(
        env_preflight,
        "run_preflight",
        lambda *a, **k: order.append("env") or real_stub(*a, **k),
    )
    monkeypatch.setattr(
        dispatch,
        "ensure_role_worktree",
        lambda *a, **k: order.append("worktree") or (None, "error:x"),
    )
    assert dispatch.cmd_wave(apply=True, adapter=adapter, fr_filter=[_FR]) == 1
    assert order == ["gh", "env"]
    out = capsys.readouterr().out
    assert out.index("--- Phase 0: Pre-flight ---") < out.index("PREFLIGHT BLOCK")
    assert "--- Phase 1" not in out
    assert (
        len(calls) == 1
        and calls[0]["repo_root"] == stack_repo
        and calls[0]["tools"] == _FULL_STACK
    )
    assert calls[0]["find_uv"] is dispatch._find_uv
    # gh down -> no env pre-flight at all.
    order.clear()
    monkeypatch.setattr(
        dispatch,
        "_gh_preflight",
        lambda verbose=False: order.append("gh") or (False, "gh missing"),
    )
    assert dispatch.cmd_wave(apply=True, adapter=adapter, fr_filter=[_FR]) == 1
    assert order == ["gh"]


# covers hub-tooling FR-0011:AC-6
def test_tick_and_maintain_gate_runs_once_before_ensure_role_worktree(
    stack_repo, adapter, monkeypatch
):
    order: list[str] = []
    calls = _inject(monkeypatch, _WARN_PORT)
    real_stub = env_preflight.run_preflight
    monkeypatch.setattr(
        env_preflight,
        "run_preflight",
        lambda *a, **k: order.append("env") or real_stub(*a, **k),
    )
    real_wt = dispatch.ensure_role_worktree
    monkeypatch.setattr(
        dispatch,
        "ensure_role_worktree",
        lambda *a, **k: order.append("worktree") or real_wt(*a, **k),
    )
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    assert order == ["env", "worktree"] and len(calls) == 1
    dispatch.lock_path(_FR, "dev").unlink()
    order.clear()
    assert dispatch.cmd_oneshot(_FR, "mnt", apply=True, adapter=adapter) == 0
    assert order == ["env", "worktree"] and len(calls) == 2
    assert [s[1] for s in adapter.spawns] == ["dev", "mnt"]


# covers hub-tooling FR-0011:AC-6
def test_warn_only_prints_one_warn_line_per_finding_and_proceeds_unchanged(
    stack_repo, adapter, capsys, monkeypatch
):
    _inject(monkeypatch, _WARN_PORT, _WARN_NODE)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    warns = [ln for ln in out.splitlines() if "PREFLIGHT WARN" in ln]
    assert len(warns) == 2
    assert (
        "port-collision" in warns[0]
        and "resource=5432" in warns[0]
        and "remedy=port 5432 is already bound" in warns[0]
    )
    assert "tool-missing" in warns[1] and "resource=node" in warns[1]
    assert "PREFLIGHT BLOCK" not in out and "PREFLIGHT OK" not in out
    assert out.index("PREFLIGHT WARN") < out.index("SPAWNED")
    assert [s[1] for s in adapter.spawns] == ["dev"] and _role_wt(
        stack_repo, "dev"
    ).exists()


# covers hub-tooling FR-0011:AC-6
def test_no_findings_prints_exactly_one_ok_line_naming_the_checks_that_ran(
    stack_repo, adapter, capsys, monkeypatch
):
    _inject(monkeypatch, checks_ran=("docker", "tool-presence", "app-control", "ports"))
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    lines = _preflight_lines(out)
    assert len(lines) == 1 and "PREFLIGHT OK" in lines[0]
    for name in ("docker", "tool-presence", "app-control", "ports"):
        assert name in lines[0]
    assert "no stack declared" not in lines[0]


# covers hub-tooling FR-0011:AC-6
def test_backfill_runs_no_environment_gate(stack_repo, adapter, capsys, monkeypatch):
    """`backfill` is not one of the three commands; a seam that would block
    is never consulted and the spawn proceeds with no PREFLIGHT line."""
    monkeypatch.setattr(
        env_preflight,
        "run_preflight",
        lambda *a, **k: pytest.fail("bkf ran the env gate"),
    )
    _dev_branch_in_progress(stack_repo)
    assert dispatch.cmd_oneshot(_FR, "bkf", apply=False, adapter=adapter) == 0
    assert dispatch.cmd_oneshot(_FR, "bkf", apply=True, adapter=adapter) == 0
    out = capsys.readouterr().out
    assert (
        _preflight_lines(out) == []
        and out.count("WOULD-SPAWN") == 1
        and out.count("SPAWNED") == 1
    )


# covers hub-tooling FR-0011:AC-6
def test_rev_tick_is_gated_too(stack_repo, adapter, capsys, monkeypatch):
    _inject(monkeypatch, _BLOCK_UV)
    _dev_branch_in_progress(stack_repo)
    _trap_side_effects(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="rev", fr_filter=[_FR]) == 1
    )
    assert "PREFLIGHT BLOCK" in capsys.readouterr().out and adapter.spawns == []
    assert not _role_wt(stack_repo, "rev").exists()


# covers hub-tooling FR-0011:AC-6
def test_ok_line_on_a_declared_stack_never_claims_no_stack_declared(
    stack_repo, adapter, capsys, monkeypatch
):
    """Adversarial: a declared stack for which no check happened to run
    (`pip`-only on a non-Windows host, or the AC-9 seam stub) still has a
    stack. The `(no stack declared)` wording is AC-10's, reserved for
    `detect_stack == []`; here the one OK line must not assert a falsehood."""
    _inject(monkeypatch, checks_ran=())
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    lines = _preflight_lines(capsys.readouterr().out)
    assert len(lines) == 1 and "PREFLIGHT OK" in lines[0]
    assert "no stack declared" not in lines[0]


# covers hub-tooling FR-0011:AC-5
def test_unresolved_ports_are_surfaced_on_a_clean_run_too(
    stack_repo, adapter, capsys, monkeypatch
):
    """The Open-question default: an unresolvable `${VAR}` port is skipped,
    produces no finding, and is *included in the `PREFLIGHT OK`/`WARN` line's
    list of ports that could not be resolved*. A run with no findings is the
    case where that matters most — the operator otherwise reads "OK" for a
    port that was never checked."""
    _inject(monkeypatch, checks_ran=("docker", "ports"), unresolved=("db:${DB_PORT}",))
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    assert "db:${DB_PORT}" in out
    assert "PREFLIGHT OK" in out and "PREFLIGHT WARN" not in out
    dispatch.lock_path(_FR, "dev").unlink()
    shutil.rmtree(stack_repo / ".claude" / "worktrees")
    _git(stack_repo, "worktree", "prune")
    _git(stack_repo, "branch", "-D", f"claude/dev-{_FR}")
    # And with a warning present it is still listed (the implemented NOTE path).
    _inject(
        monkeypatch,
        _WARN_NODE,
        checks_ran=("docker", "ports"),
        unresolved=("db:${DB_PORT}",),
    )
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert "db:${DB_PORT}" in capsys.readouterr().out


# covers hub-tooling FR-0011:AC-5
@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "findings",
    [(), (_WARN_PORT, _WARN_NODE), (_BLOCK_DOCKER, _WARN_NODE)],
    ids=["clean", "warn-only", "blocking"],
)
def test_unresolved_ports_are_listed_exactly_once_on_every_path(
    apply, findings, stack_repo, adapter, capsys, monkeypatch
):
    """Round 2: the clean-run fix appends the list to the OK line while the
    findings path keeps its NOTE line. Whatever the findings and mode, the
    list appears exactly once, in full, on exactly one line — the OK line
    when there is nothing else to say, otherwise a NOTE line after the
    finding lines — and the OK line and the NOTE line never both appear."""
    unresolved = ("db:${DB_PORT}", "cache:${CACHE_PORT}")
    _inject(
        monkeypatch, *findings, checks_ran=("docker", "ports"), unresolved=unresolved
    )
    blocking = apply and any(f.severity == "block" for f in findings)
    if blocking:
        _trap_side_effects(monkeypatch)
    rc = dispatch.cmd_tick(apply=apply, adapter=adapter, role="dev", fr_filter=[_FR])
    assert rc == (1 if blocking else 0)
    out = capsys.readouterr().out
    lines = _preflight_lines(out)
    assert len(lines) == len(findings) + 1
    listed = [ln for ln in lines if "unresolved ports:" in ln]
    assert len(listed) == 1 and out.count("db:${DB_PORT}") == 1
    assert "unresolved ports: db:${DB_PORT}, cache:${CACHE_PORT}" in listed[0]
    if findings:
        assert listed[0] is lines[-1] and "PREFLIGHT NOTE" in listed[0]
        assert "PREFLIGHT OK" not in out
    else:
        assert listed[0] is lines[0] and "PREFLIGHT OK" in listed[0]
        assert "PREFLIGHT NOTE" not in out and "ran: docker, ports" in listed[0]


# covers hub-tooling FR-0011:AC-6
def test_ok_line_names_none_when_a_declared_stack_ran_no_check(
    repo, adapter, capsys, monkeypatch
):
    """Round 2: a `pip`-only project on a non-Windows host declares a stack
    (`detect_stack` -> ["pip"]) yet no check has a marker to run on. With
    the real module and every I/O booby-trapped, the OK line names the
    checks that ran — "(none)" — and never AC-10's reserved wording; the
    stubbed seam returning the empty result on the same repo reads the
    same."""
    _write(repo, "requirements.txt", "requests==2.32.0\n")
    _commit_all(repo, "pip only")
    assert dispatch.detected_stack_tools() == ["pip"]

    def boom(name):
        return lambda *a, **k: pytest.fail(f"{name} ran for a pip-only stack")

    _inject_real_with_fakes(
        monkeypatch,
        platform="linux",
        which=boom("which"),
        run=boom("run"),
        port_busy=boom("port_busy"),
    )
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert _preflight_lines(capsys.readouterr().out) == [
        "  PREFLIGHT OK        ran: (none)"
    ]

    _inject(monkeypatch, checks_ran=())
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert _preflight_lines(capsys.readouterr().out) == [
        "  PREFLIGHT OK        ran: (none)"
    ]


# ---------------------------------------------------------------------------
# AC-7: classification reaches the metrics log through existing fields
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-7
def test_warn_only_spawn_record_carries_preflight_segment_after_stack_and_venv(
    stack_repo, adapter, monkeypatch
):
    """DEC-0003 order `stack=`, `venv=`, `preflight=`; classes `+`-joined,
    sorted, de-duplicated; the lock file (a different record) is untouched."""
    _inject(
        monkeypatch,
        _WARN_PORT,
        _WARN_NODE,
        _WARN_APP,
        _f("tool-missing", "pnpm", "warn"),
        _f("port-collision", "6379", "warn"),
    )
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (False, "uv-not-found"))
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    [rec] = _kind("dispatch.spawn")
    assert rec["worktree_status"] == (
        f"created,{_FULL_STACK_SEG},venv=uv-not-found,preflight=app-control-enforced+port-collision+tool-missing"
    )
    lock = json.loads(
        (stack_repo / "_dispatch" / f"{_FR}.dev.lock").read_text(encoding="utf-8")
    )
    assert "preflight" not in lock["worktree_status"]
    # A second spawn in the same invocation (rev tick) carries the same segment.
    dispatch.lock_path(_FR, "dev").unlink()
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (True, "venv-created"))
    _dev_branch_in_progress(stack_repo)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="rev", fr_filter=[_FR]) == 0
    )
    assert _kind("dispatch.spawn")[-1]["worktree_status"] == (
        f"created,{_FULL_STACK_SEG},preflight=app-control-enforced+port-collision+tool-missing"
    )


# covers hub-tooling FR-0011:AC-7
def test_no_findings_means_no_preflight_segment_at_all(
    stack_repo, adapter, monkeypatch
):
    _inject(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    [rec] = _kind("dispatch.spawn")
    assert rec["worktree_status"] == f"created,{_FULL_STACK_SEG}"
    assert "preflight" not in rec["worktree_status"]


# covers hub-tooling FR-0011:AC-7
def test_segment_builder_sorts_dedupes_and_is_empty_for_no_findings():
    assert dispatch._preflight_metrics_segment([]) == ""
    assert (
        dispatch._preflight_metrics_segment([_WARN_NODE, _WARN_PORT, _WARN_NODE])
        == "preflight=port-collision+tool-missing"
    )
    assert dispatch._spawn_extra_kwargs("") == {}
    assert dispatch._spawn_extra_kwargs("preflight=skipped") == {
        "preflight_segment": "preflight=skipped"
    }


# covers hub-tooling FR-0011:AC-7
def test_blocking_wave_emits_its_wave_record_with_one_drop_reason_per_blocking_finding(
    stack_repo, adapter, monkeypatch
):
    _write(stack_repo, "specs/FR-0002-synthetic.md", _fr_md("FR-0002"))
    _commit_all(stack_repo, "second FR")
    _inject(monkeypatch, _BLOCK_DOCKER, _WARN_PORT, _BLOCK_UV)
    assert dispatch.cmd_wave(apply=True, adapter=adapter) == 1
    [rec] = _kind("dispatch.wave")
    assert rec["fr_count"] == 2 and rec["dropped"] == 2
    assert rec["completed"] == 0 and rec["dev_only"] == 0
    assert sorted(rec["object_ids"]) == ["FR-0001", "FR-0002"]
    assert rec["drop_reasons"] == [
        {
            "fr_id": None,
            "phase": "preflight-env",
            "class": "docker-not-installed",
            "resource": "docker",
        },
        {
            "fr_id": None,
            "phase": "preflight-env",
            "class": "tool-missing",
            "resource": "uv",
        },
    ]
    assert rec["rounds_ran"] == {} and rec["force_escalated"] == []
    assert _kind("dispatch.spawn") == [] and _kind("dispatch.run") == []
    # A dry-run block emits nothing.
    assert dispatch.cmd_wave(apply=False, adapter=adapter) == 0
    assert len(_kind("dispatch.wave")) == 1


# covers hub-tooling FR-0011:AC-7
def test_records_validate_against_the_unmodified_validator_and_add_no_kind_or_field(
    stack_repo, adapter, monkeypatch, pre_fr_dispatch, tmp_path
):
    """No new record kind, no new top-level field: the key sets of the
    FR-0011 records equal those of records the pre-FR-0011 dispatcher emits
    for the same commands, and `metrics_log` has no preflight kind."""
    assert not any("preflight" in k for k in metrics_log.KINDS)
    assert metrics_log.KIND_REQUIRED["dispatch.spawn"] == (
        "harness",
        "worktree_status",
        "base_branch",
        "model",
        "round",
    )
    assert (
        "class" not in metrics_log.STRING_FIELDS
        and "resource" not in metrics_log.STRING_FIELDS
    )
    # FR-0011 records.
    _inject(monkeypatch, _WARN_PORT)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    dispatch.lock_path(_FR, "dev").unlink()
    shutil.rmtree(stack_repo / ".claude" / "worktrees")
    _git(stack_repo, "worktree", "prune")
    _git(stack_repo, "branch", "-D", f"claude/dev-{_FR}")
    _inject(monkeypatch, _BLOCK_DOCKER)
    assert dispatch.cmd_wave(apply=True, adapter=adapter, fr_filter=[_FR]) == 1
    [spawn_new] = _kind("dispatch.spawn")
    [wave_new] = _kind("dispatch.wave")
    # Pre-FR records for the same commands, in a fresh repo.
    old_repo = _make_repo(tmp_path, "old")
    _declare_full_stack(old_repo)
    _point(monkeypatch, pre_fr_dispatch, old_repo)
    old_adapter = _FakeAdapter(pre_fr_dispatch.ClaudeCodeAdapter())
    assert (
        pre_fr_dispatch.cmd_tick(
            apply=True, adapter=old_adapter, role="dev", fr_filter=[_FR]
        )
        == 0
    )
    monkeypatch.setattr(
        pre_fr_dispatch,
        "_wait_for_phase",
        lambda agents, poll, timeout: {_FR: "timeout"},
    )
    pre_fr_dispatch.lock_path(_FR, "dev").unlink()
    pre_fr_dispatch.cmd_wave(
        apply=True,
        adapter=old_adapter,
        fr_filter=[_FR],
        timeout=5,
        phase_timeout=1,
        poll_interval=0.01,
    )
    spawn_old = _kind("dispatch.spawn")[0]
    [wave_old] = _kind("dispatch.wave")
    assert set(spawn_new) == set(spawn_old)
    assert set(wave_new) == set(wave_old)
    assert set(wave_old["drop_reasons"][0]) == {"fr_id", "phase"}
    assert set(wave_new["drop_reasons"][0]) == {"fr_id", "phase", "class", "resource"}


# covers hub-tooling FR-0011:AC-7
def test_wave_that_proceeds_on_warnings_stamps_every_spawn_and_no_preflight_drop_reason(
    stack_repo, adapter, monkeypatch
):
    _inject(monkeypatch, _WARN_APP)
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {_FR: "timeout"}
    )
    dispatch.cmd_wave(
        apply=True,
        adapter=adapter,
        fr_filter=[_FR],
        timeout=5,
        phase_timeout=1,
        poll_interval=0.01,
    )
    spawns = _kind("dispatch.spawn")
    assert len(spawns) == 1 and spawns[0]["worktree_status"].endswith(
        ",preflight=app-control-enforced"
    )
    [wave] = _kind("dispatch.wave")
    assert wave["drop_reasons"] == [{"fr_id": _FR, "phase": "dev-monitor"}]


# ---------------------------------------------------------------------------
# AC-8: the override, recorded
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-8
@pytest.mark.parametrize("via", ["flag", "env-1", "env-true"])
@pytest.mark.parametrize("cmd", ["tick", "maintain"])
def test_skip_bypasses_a_blocking_seam_prints_one_skipped_line_and_records_it(
    cmd, via, stack_repo, adapter, capsys, monkeypatch
):
    """The FR would have blocked; with the override it spawns, exactly one
    `PREFLIGHT SKIPPED` line is printed, no check runs, and the spawn record
    carries `preflight=skipped`."""
    monkeypatch.setattr(
        env_preflight,
        "run_preflight",
        lambda *a, **k: pytest.fail("a skipped pre-flight ran a check"),
    )
    _trap_checks(monkeypatch)
    flag = via == "flag"
    if via == "env-1":
        monkeypatch.setenv(_ENV_SKIP, "1")
    elif via == "env-true":
        monkeypatch.setenv(_ENV_SKIP, "true")
    gh_calls: list[int] = []
    monkeypatch.setattr(
        dispatch,
        "_gh_preflight",
        lambda verbose=False: gh_calls.append(1) or (True, None),
    )
    if cmd == "tick":
        rc = dispatch.cmd_tick(
            apply=True,
            adapter=adapter,
            role="dev",
            fr_filter=[_FR],
            skip_env_preflight=flag,
        )
    else:
        rc = dispatch.cmd_oneshot(
            _FR, "mnt", apply=True, adapter=adapter, skip_env_preflight=flag
        )
    assert rc == 0
    out = capsys.readouterr().out
    lines = _preflight_lines(out)
    assert len(lines) == 1 and "PREFLIGHT SKIPPED" in lines[0]
    assert len(adapter.spawns) == 1
    [rec] = _kind("dispatch.spawn")
    assert rec["worktree_status"] == f"created,{_FULL_STACK_SEG},preflight=skipped"
    if cmd == "tick":
        assert gh_calls == [1]  # never `_gh_preflight`


# covers hub-tooling FR-0011:AC-8
def test_skip_on_wave_records_the_override_in_drop_reasons_and_on_every_spawn(
    stack_repo, adapter, capsys, monkeypatch
):
    monkeypatch.setattr(
        env_preflight,
        "run_preflight",
        lambda *a, **k: pytest.fail("a skipped pre-flight ran a check"),
    )
    gh_calls: list[int] = []
    monkeypatch.setattr(
        dispatch,
        "_gh_preflight",
        lambda verbose=False: gh_calls.append(1) or (True, None),
    )
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {_FR: "timeout"}
    )
    dispatch.cmd_wave(
        apply=True,
        adapter=adapter,
        fr_filter=[_FR],
        timeout=5,
        phase_timeout=1,
        poll_interval=0.01,
        skip_env_preflight=True,
    )
    out = capsys.readouterr().out
    assert gh_calls == [1]
    assert len(_preflight_lines(out)) == 1 and "PREFLIGHT SKIPPED" in out
    [spawn] = _kind("dispatch.spawn")
    assert spawn["worktree_status"] == f"created,{_FULL_STACK_SEG},preflight=skipped"
    [wave] = _kind("dispatch.wave")
    # The per-FR drop entries come first; the override note is appended.
    assert wave["drop_reasons"] == [
        {"fr_id": _FR, "phase": "dev-monitor"},
        {"fr_id": None, "phase": "preflight-env", "class": "skipped"},
    ]
    # Dry-run + skip: one SKIPPED line, plan printed, nothing recorded.
    dispatch.lock_path(_FR, "dev").unlink()
    assert (
        dispatch.cmd_wave(
            apply=False, adapter=adapter, fr_filter=[_FR], skip_env_preflight=True
        )
        == 0
    )
    out = capsys.readouterr().out
    assert out.count("PREFLIGHT SKIPPED") == 1 and "WOULD-SPAWN" in out
    assert len(_kind("dispatch.wave")) == 1


# covers hub-tooling FR-0011:AC-8
@pytest.mark.parametrize("value", ["0", "", "false", "no", " ", "skip"])
def test_env_var_near_misses_do_not_skip(
    value, stack_repo, adapter, capsys, monkeypatch
):
    """Adversarial: only an affirmative value skips; anything else runs the
    gate (which here blocks)."""
    monkeypatch.setenv(_ENV_SKIP, value)
    _inject(monkeypatch, _BLOCK_UV)
    _trap_side_effects(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 1
    )
    out = capsys.readouterr().out
    assert "PREFLIGHT SKIPPED" not in out and "PREFLIGHT BLOCK" in out
    assert _kind("dispatch.spawn") == []


# covers hub-tooling FR-0011:AC-8
def test_cli_flag_is_wired_on_all_three_subcommands_and_only_those(
    monkeypatch, adapter
):
    captured: dict[str, dict] = {}
    monkeypatch.setattr(dispatch, "get_adapter", lambda name: adapter)
    monkeypatch.setattr(
        dispatch, "cmd_tick", lambda **k: captured.setdefault("tick", k) and 0
    )
    monkeypatch.setattr(
        dispatch, "cmd_wave", lambda **k: captured.setdefault("wave", k) and 0
    )
    monkeypatch.setattr(
        dispatch, "cmd_oneshot", lambda *a, **k: captured.setdefault(a[1], k) and 0
    )
    for argv, key in (
        (["tick", "--skip-env-preflight"], "tick"),
        (["wave", "--skip-env-preflight", "--fr", _FR], "wave"),
        (["maintain", _FR, "--skip-env-preflight"], "mnt"),
    ):
        captured.clear()
        monkeypatch.setattr(sys, "argv", ["dispatch.py", *argv])
        assert dispatch.main() == 0
        assert captured[key]["skip_env_preflight"] is True
    for argv, key in (
        (["tick"], "tick"),
        (["wave"], "wave"),
        (["maintain", _FR], "mnt"),
    ):
        captured.clear()
        monkeypatch.setattr(sys, "argv", ["dispatch.py", *argv])
        assert dispatch.main() == 0
        assert captured[key]["skip_env_preflight"] is False
    # backfill has no such flag and never passes one.
    captured.clear()
    monkeypatch.setattr(sys, "argv", ["dispatch.py", "backfill", _FR])
    assert dispatch.main() == 0
    assert "skip_env_preflight" not in captured["bkf"]
    monkeypatch.setattr(
        sys, "argv", ["dispatch.py", "backfill", _FR, "--skip-env-preflight"]
    )
    with pytest.raises(SystemExit):
        dispatch.main()


# ---------------------------------------------------------------------------
# AC-9 (v2): read-only, bounded, one seam; dry-run runs and reports
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-9
@pytest.mark.parametrize("cmd", ["tick", "maintain", "wave"])
def test_seam_stubbed_means_no_host_contact_no_preflight_segment_and_only_an_ok_line(
    cmd, stack_repo, adapter, capsys, monkeypatch, argv_log
):
    """The DEC-0005/DEC-0006 property FR-0010's harness relies on: with
    `env_preflight.run_preflight` replaced by a no-findings stub, every check
    function and host name is trapped, no `docker`/`powershell` subprocess
    runs, no socket is bound, the only PREFLIGHT line is `PREFLIGHT OK`, and
    the spawn record has no `preflight=` segment."""
    _trap_checks(monkeypatch)
    monkeypatch.setattr(
        env_preflight, "run_preflight", lambda *a, **k: env_preflight.PreflightResult()
    )
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {_FR: "timeout"}
    )
    if cmd == "tick":
        assert (
            dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR])
            == 0
        )
    elif cmd == "maintain":
        assert dispatch.cmd_oneshot(_FR, "mnt", apply=True, adapter=adapter) == 0
    else:
        dispatch.cmd_wave(
            apply=True,
            adapter=adapter,
            fr_filter=[_FR],
            timeout=5,
            phase_timeout=1,
            poll_interval=0.01,
        )
    out = capsys.readouterr().out
    lines = _preflight_lines(out)
    assert len(lines) == 1 and "PREFLIGHT OK" in lines[0]
    assert _host_probes(argv_log) == []
    assert len(adapter.spawns) == 1
    for rec in _kind("dispatch.spawn"):
        assert "preflight=" not in rec["worktree_status"]


# covers hub-tooling FR-0011:AC-9
def test_the_seam_is_resolved_at_call_time_as_a_module_attribute(
    stack_repo, adapter, capsys, monkeypatch
):
    """Adversarial: rebinding `env_preflight.run_preflight` *after* the
    dispatcher was imported must take effect — an import-time `from ... import`
    would silently put FR-0010's eight harness tests back on the host."""
    assert "run_preflight" not in vars(dispatch)
    seen: list[int] = []

    def late_stub(repo_root, tools, **kw):
        seen.append(1)
        return env_preflight.PreflightResult(findings=(_BLOCK_UV,))

    monkeypatch.setattr(env_preflight, "run_preflight", late_stub)
    _trap_side_effects(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 1
    )
    assert seen == [1] and "PREFLIGHT BLOCK" in capsys.readouterr().out


# covers hub-tooling FR-0011:AC-9
@pytest.mark.parametrize("cmd", ["tick", "maintain", "wave"])
def test_dry_run_runs_the_checks_reports_would_block_continues_and_mutates_nothing(
    cmd, stack_repo, adapter, capsys, monkeypatch, argv_log
):
    calls = _inject(monkeypatch, _BLOCK_DOCKER, _WARN_PORT, unresolved=("db:${X}",))
    monkeypatch.setattr(
        dispatch, "ensure_dev_venv", lambda wt: pytest.fail("dry-run provisioned")
    )
    before = _snapshot(stack_repo)
    if cmd == "tick":
        rc = dispatch.cmd_tick(
            apply=False, adapter=adapter, role="dev", fr_filter=[_FR]
        )
    elif cmd == "maintain":
        rc = dispatch.cmd_oneshot(_FR, "mnt", apply=False, adapter=adapter)
    else:
        rc = dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR])
    assert rc == 0  # a dry-run never exits non-zero on a block
    out = capsys.readouterr().out
    assert len(calls) == 1  # the checks still ran (read-only)
    would_block = [ln for ln in out.splitlines() if "WOULD-BLOCK" in ln]
    would_pf = [ln for ln in out.splitlines() if "WOULD-PREFLIGHT" in ln]
    assert (
        len(would_block) == 1
        and "docker-not-installed" in would_block[0]
        and "resource=docker" in would_block[0]
    )
    assert len(would_pf) == 1 and "port-collision" in would_pf[0]
    assert "PREFLIGHT BLOCK" not in out and "PREFLIGHT WARN" not in out
    assert "db:${X}" in out  # unresolved ports surfaced, never guessed
    assert "WOULD-SPAWN" in out  # the rest of the plan is still printed
    assert _snapshot(stack_repo) == before
    assert adapter.spawns == [] and _records() == []
    assert not (stack_repo / ".claude" / "worktrees").exists()
    assert _host_probes(argv_log) == []


# covers hub-tooling FR-0011:AC-9
def test_real_module_with_injected_io_through_the_dispatcher_end_to_end(
    stack_repo, adapter, capsys, monkeypatch, argv_log
):
    """The real `run_preflight` runs behind the seam with every I/O injected:
    the repo's own compose file is parsed, the fakes' story (docker present
    and reachable, `node` missing, port 5470 busy, non-Windows) reaches the
    console and the record, and no host probe ran."""
    _write(
        stack_repo, "docker-compose.yml", 'services:\n  db:\n    ports: ["5470:5432"]\n'
    )
    _commit_all(stack_repo, "publish a port")
    probed: list[int] = []
    _inject_real_with_fakes(
        monkeypatch,
        which=lambda t: None if t == "node" else f"/fake/{t}",
        port_busy=lambda p: probed.append(p) or True,
        platform="linux",
    )
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    assert probed == [5470]
    warns = [ln for ln in out.splitlines() if "PREFLIGHT WARN" in ln]
    assert (
        len(warns) == 2 and "tool-missing" in warns[0] and "port-collision" in warns[1]
    )
    assert "resource=5470" in warns[1] and "docker-compose.yml" in warns[1]
    [rec] = _kind("dispatch.spawn")
    assert (
        rec["worktree_status"]
        == f"created,{_FULL_STACK_SEG},preflight=port-collision+tool-missing"
    )
    assert _host_probes(argv_log) == []


# covers hub-tooling FR-0011:AC-9
def test_dispatcher_passes_repo_root_tools_and_its_own_find_uv_into_the_seam(
    stack_repo, adapter, monkeypatch
):
    calls = _inject(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    [call] = calls
    assert call["repo_root"] == stack_repo and call["tools"] == _FULL_STACK
    assert call["find_uv"] is dispatch._find_uv
    assert set(call) == {"repo_root", "tools", "find_uv"}


# ---------------------------------------------------------------------------
# AC-10: no stack -> byte-identical to today
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-10
@pytest.mark.parametrize("cmd", ["tick", "maintain", "wave"])
@pytest.mark.parametrize("apply", [False, True])
def test_no_stack_repo_runs_no_check_and_prints_only_the_no_stack_ok_line(
    cmd, apply, repo, adapter, capsys, monkeypatch, argv_log
):
    """Every check function and host name is trapped; only the seam (real)
    is reachable, and it must return without touching any of them."""
    _trap_checks(monkeypatch)
    assert dispatch.detected_stack_tools() == []
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {_FR: "timeout"}
    )
    if cmd == "tick":
        assert (
            dispatch.cmd_tick(apply=apply, adapter=adapter, role="dev", fr_filter=[_FR])
            == 0
        )
    elif cmd == "maintain":
        assert dispatch.cmd_oneshot(_FR, "mnt", apply=apply, adapter=adapter) == 0
    else:
        dispatch.cmd_wave(
            apply=apply,
            adapter=adapter,
            fr_filter=[_FR],
            timeout=5,
            phase_timeout=1,
            poll_interval=0.01,
        )
    out = capsys.readouterr().out
    assert _preflight_lines(out) == ["  PREFLIGHT OK (no stack declared)"]
    assert _host_probes(argv_log) == []
    for rec in _kind("dispatch.spawn"):
        assert rec["worktree_status"] == "created"


# covers hub-tooling FR-0011:AC-10
def test_no_stack_spawn_record_and_settings_are_byte_identical_to_the_pre_fr_dispatcher(
    repo, adapter, monkeypatch, pre_fr_dispatch, tmp_path
):
    _trap_checks(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    new_wt = _role_wt(repo, "dev")
    new_settings = (new_wt / ".claude" / "settings.local.json").read_bytes()
    [new_rec] = _kind("dispatch.spawn")
    new_lock = json.loads(
        (repo / "_dispatch" / f"{_FR}.dev.lock").read_text(encoding="utf-8")
    )
    old_repo = _make_repo(tmp_path, "old")
    _point(monkeypatch, pre_fr_dispatch, old_repo)
    old_adapter = _FakeAdapter(pre_fr_dispatch.ClaudeCodeAdapter())
    assert (
        pre_fr_dispatch.cmd_tick(
            apply=True, adapter=old_adapter, role="dev", fr_filter=[_FR]
        )
        == 0
    )
    old_settings = (
        _role_wt(old_repo, "dev") / ".claude" / "settings.local.json"
    ).read_bytes()
    [old_rec] = _kind("dispatch.spawn")
    old_lock = json.loads(
        (old_repo / "_dispatch" / f"{_FR}.dev.lock").read_text(encoding="utf-8")
    )
    assert new_settings == old_settings
    assert set(new_rec) == set(old_rec)
    volatile = {"record_id", "ts", "run_id"}
    assert {k: v for k, v in new_rec.items() if k not in volatile} == {
        k: v for k, v in old_rec.items() if k not in volatile
    }
    assert (
        set(new_lock) == set(old_lock)
        and new_lock["worktree_status"] == old_lock["worktree_status"]
    )


# covers hub-tooling FR-0011:AC-10
def test_no_stack_dry_run_mutates_nothing(repo, adapter, capsys, monkeypatch):
    _trap_checks(monkeypatch)
    before = _snapshot(repo)
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    assert dispatch.cmd_oneshot(_FR, "mnt", apply=False, adapter=adapter) == 0
    assert _snapshot(repo) == before and _records() == [] and adapter.spawns == []


# covers hub-tooling FR-0011:AC-10
def test_a_narrower_spawn_role_fake_still_works_when_preflight_has_nothing_to_say(
    stack_repo, adapter, monkeypatch
):
    """Out-of-scope guard: `_spawn_extra_kwargs` passes `preflight_segment`
    only when non-empty, so FR-0002/FR-0006-style fakes with the pre-FR-0011
    signature keep working on a no-stack repo and on a stack repo with no
    findings — and break loudly only when there is a segment to carry."""
    seen: list[tuple] = []

    def narrow(fr_id, role, apply, adapter, extra_prompt=None, round_num=1):
        seen.append((fr_id, role))
        return ("dry-run", None, None)

    monkeypatch.setattr(dispatch, "spawn_role", narrow)
    _inject(monkeypatch)
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert seen == [(_FR, "dev")]
    _inject(monkeypatch, _WARN_PORT)
    with pytest.raises(TypeError):
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR])
