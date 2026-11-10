"""Reviewer tests for FR-0010, the dispatcher half — every role's allow-list
unions the detected stack's Bash grants with deny still winning (AC-4),
`rev`/`bkf` derive `Edit`/`Write` grants from `owns:` exactly as FR-0009 does
for `dev` (AC-5), `uv`/`node`/`npx` leave the maintainer deny list iff the
stack declares them (AC-6), the spawn report and the `dispatch.spawn` metrics
record name the stack per DEC-0003 (AC-7), the dispatch venv is provisioned
from the project's own lock / requirements file (AC-8), provisioning failure
is a classified soft failure that reaches the metrics record as
`venv=<classification>` (AC-9), provisioning is idempotent and bounded
(AC-10), the Cursor adapter mirrors all of it (AC-11), and a project that
declares no stack is byte-identical to the pre-FR-0010 dispatcher while
dry-run mutates nothing (AC-12).

Harness: the FR-0009 pattern — `dispatch.py` loaded by path with its path
globals pointed at a real temporary git repository, a fake harness adapter
that records spawns and delegates only `write_worktree_settings` to the real
`ClaudeCodeAdapter` / `CursorAdapter`, gh preflight / reconcile stubbed, and
the venv provisioner stubbed *except* in the AC-8/AC-9/AC-10 tests, which run
the real `ensure_dev_venv` against a real `uv` and the tiny synthetic
projects under `tests/fixtures/stack-profile/venv-provision/` (they skip when
`uv` is not on PATH; `uv` is never uninstalled — absence is simulated by
monkeypatching `_find_uv`). FR-0011's environment pre-flight is stubbed at
its one seam, `env_preflight.run_preflight`, so nothing here touches the
host's Docker, PATH or Windows policy (DEC-0005).

The "pre-FR dispatcher" that AC-4/AC-6/AC-12 compare against is loaded from
`git show <pre-FR ref>:template/scripts/dispatch.py` — the hub commit FR-0010
branched from. Inside a bootstrapped project that object does not exist and
those comparisons skip; the static-payload comparisons next to them always
run.

Coverage annotations are written `# covers hub-tooling FR-0010:AC-N` rather
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
_VENV_FIXTURES = (
    _TEMPLATE_DIR / "tests" / "fixtures" / "stack-profile" / "venv-provision"
)
_LOCK_PROJECT = _VENV_FIXTURES / "lock-project"
_REQ_PROJECT = _VENV_FIXTURES / "requirements-project"
# The hub commit FR-0010 branched from (`main` after FR-0009 merged). Used
# only to load the pre-FR dispatcher for the byte-identity comparisons.
_PRE_FR_REF = "2e029c4"

_FR = "FR-0001"
_ENV = "DISPATCH_STACK_TOOLS"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import env_preflight
import metrics_log
import stack_profile


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0010")
# Kept before any monkeypatching so the AC-8/AC-9/AC-10 tests can restore it.
_REAL_ENSURE_DEV_VENV = dispatch.ensure_dev_venv

# python + uv + node + docker — the AC-4 / AC-11 fixture stack.
_FULL_STACK = ["docker", "node", "npm", "npx", "python", "uv"]
_FULL_STACK_GRANTS = [
    "Bash(docker *)",
    "Bash(node *)",
    "Bash(npm *)",
    "Bash(npx *)",
    "Bash(uv *)",
]
_LIFTED = ["Bash(uv *)", "Bash(node *)", "Bash(npx *)"]
_CURSOR_LIFTED = ["Shell(uv)", "Shell(node)", "Shell(npx)"]

_OWNS = [".python-version", "migrations/**", "frontend/*", ".github/workflows/ci.yml"]
_PROTECTED_OWNS = [
    "scripts/deploy-gate.py",
    ".agent-team/roles/developer.md",
    "tests/test_foo.py",
    "CLAUDE.md",
]


@functools.lru_cache(maxsize=1)
def _pre_fr_source() -> bytes | None:
    hub_root = _TEMPLATE_DIR.parent
    proc = subprocess.run(
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
    d = tmp_path_factory.mktemp("pre_fr0010_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0010")


# ---------------------------------------------------------------------------
# Synthetic FR + repo fixtures
# ---------------------------------------------------------------------------


def _fr_md(
    fr_id: str,
    owns: list[str] | None = None,
    *,
    owns_raw: str | None = None,
    status: str = "ready",
) -> str:
    if owns_raw is not None:
        owns_line = owns_raw
    elif owns is None:
        owns_line = ""
    else:
        owns_line = "owns: " + json.dumps(owns) + "\n"
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
{owns_line}reads: []
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
    proc = subprocess.run(
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


def _write_spec(repo: Path, fr_id: str, text: str) -> Path:
    return _write(repo, f"specs/{fr_id}-synthetic.md", text)


def _commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _commit_spec(repo: Path, fr_id: str, text: str, msg: str = "spec update") -> None:
    p = _write_spec(repo, fr_id, text)
    _git(repo, "add", str(p.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", msg)


def _make_repo(tmp_path: Path, spec_text: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)
    _write_spec(repo, _FR, spec_text)
    for rel in (
        ".agent-team/roles/developer.md",
        ".agent-team/roles/reviewer.md",
        "scripts/deploy-gate.py",
        "scripts/setup.py",
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


def _declare_full_stack(repo: Path) -> None:
    """python + uv + node + docker markers, committed (a real, tiny uv lock)."""
    shutil.copy(_LOCK_PROJECT / "pyproject.toml", repo / "pyproject.toml")
    shutil.copy(_LOCK_PROJECT / "uv.lock", repo / "uv.lock")
    _write(repo, "package.json", '{"name": "synthetic", "private": true}\n')
    _write(repo, "docker-compose.yml", "services: {}\n")
    _commit_all(repo, "declare stack")


def _dev_branch_in_progress(repo: Path) -> Path:
    """A `claude/dev-FR-0001` branch (with worktree) whose spec reads
    `in-progress` — what makes the FR runnable for the Reviewer."""
    wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    if not wt.exists():  # else: a real dev spawn already created it
        wt.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", "-b", f"claude/dev-{_FR}", str(wt), "main")
    spec = wt / "specs" / f"{_FR}-synthetic.md"
    text = spec.read_text(encoding="utf-8").replace(
        "status: ready", "status: in-progress"
    )
    spec.write_text(text, encoding="utf-8", newline="\n")
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
    monkeypatch.setattr(
        env_preflight, "run_preflight", lambda *a, **k: env_preflight.PreflightResult()
    )
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


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """AC-2's environment channel must never leak an operator's declaration
    into these tests (or FR-0002's byte-identity ones)."""
    monkeypatch.delenv(_ENV, raising=False)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    r = _make_repo(tmp_path, _fr_md(_FR, _OWNS))
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


@pytest.fixture
def uv() -> str:
    found = dispatch._find_uv()
    if found is None:
        pytest.skip("uv not on PATH; AC-8/AC-9/AC-10 need the real provisioner")
    return found


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


def _spawn_records() -> list[dict]:
    return [r for r in _records() if r["kind"] == "dispatch.spawn"]


def _lock(repo: Path, role: str) -> dict:
    return json.loads(
        (repo / "_dispatch" / f"{_FR}.{role}.lock").read_text(encoding="utf-8")
    )


def _settings(wt: Path) -> dict[str, list[str]]:
    return json.loads(
        (wt / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )["permissions"]


def _cursor_settings(wt: Path) -> dict[str, list[str]]:
    return json.loads((wt / ".cursor" / "cli.json").read_text(encoding="utf-8"))[
        "permissions"
    ]


def _static(mod=dispatch, adapter_cls: str = "ClaudeCodeAdapter", role: str = "dev"):
    perms = getattr(mod, adapter_cls).ROLE_PERMISSIONS[role]
    return {"allow": list(perms["allow"]), "deny": list(perms["deny"])}


def _grants(perms: dict[str, list[str]], tool: str) -> list[str]:
    return [a[len(tool) + 1 : -1] for a in perms["allow"] if a.startswith(f"{tool}(")]


def _bash_grants(perms: dict[str, list[str]]) -> list[str]:
    return [a for a in perms["allow"] if a.startswith("Bash(")]


def _lines(out: str, needle: str) -> list[int]:
    return [i for i, ln in enumerate(out.splitlines()) if needle in ln]


def _warn_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if "WARN" in ln]


def _tree_digest(root: Path) -> str:
    if not root.exists():
        return "absent"
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _role_wt(repo: Path, role: str) -> Path:
    return repo / ".claude" / "worktrees" / f"{role}-{_FR}"


def _venv_python(project: Path) -> Path:
    return dispatch._venv_python_exe(project / dispatch.VENV_DIRNAME)


def _imports(py: Path, *modules: str) -> bool:
    proc = subprocess.run(
        [str(py), "-c", "import " + ", ".join(modules)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode == 0


def _spy_subprocess(monkeypatch, mod) -> list[tuple[list[str], dict]]:
    """Record every `subprocess.run` `mod` makes, still running it."""
    seen: list[tuple[list[str], dict]] = []
    real_run = subprocess.run

    def spy(cmd, *a, **k):
        seen.append(([str(c) for c in cmd], dict(k)))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(mod.subprocess, "run", spy)
    return seen


# ---------------------------------------------------------------------------
# AC-4: every role unions the stack grants; deny still wins
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-4
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_static_roles_allow_is_static_plus_owns_plus_stack_grants_deny_unchanged(
    stack_repo, adapter, tmp_path, role
):
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, role, _FR)
    perms = _settings(wt)
    static = _static(role=role)
    owns_grants = [f"Edit({g})" for g in _OWNS] + [f"Write({g})" for g in _OWNS]
    assert perms["allow"] == static["allow"] + owns_grants + _FULL_STACK_GRANTS
    assert perms["deny"] == static["deny"]
    for entry in static["allow"]:
        assert entry in perms["allow"]


# covers hub-tooling FR-0010:AC-4
def test_mnt_allow_is_pre_fr_allow_plus_stack_grants(
    stack_repo, monkeypatch, pre_fr_dispatch
):
    _point(monkeypatch, pre_fr_dispatch, stack_repo)
    new = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    old = pre_fr_dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    assert new["allow"] == old["allow"] + _FULL_STACK_GRANTS
    # deny: only AC-6's three lifted; everything else in the pre-FR order.
    assert new["deny"] == [d for d in old["deny"] if d not in _LIFTED]


# covers hub-tooling FR-0010:AC-4
@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
def test_every_role_gets_every_stack_grant_and_no_deny_entry_moves(
    stack_repo, adapter, tmp_path, role
):
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, role, _FR)
    perms = _settings(wt)
    for g in _FULL_STACK_GRANTS:
        assert g in perms["allow"], (role, g)
    if role == "mnt":
        expected_deny = dispatch._mnt_bash_denies(_FULL_STACK)
        assert [
            d for d in perms["deny"] if d in dispatch.MNT_BASH_DENIES
        ] == expected_deny
    else:
        assert perms["deny"] == _static(role=role)["deny"]


# covers hub-tooling FR-0010:AC-4
def test_a_stack_grant_present_in_a_role_deny_list_is_written_to_both_never_hidden(
    stack_repo, adapter, tmp_path, monkeypatch
):
    """Adversarial: give `rev` a static `Bash(docker *)` deny and `mnt` an
    unconditional `Bash(docker *)` deny; the grant must still land in
    `allow` and the deny must still be there — the settings file must not be
    edited to hide the conflict (the harness resolves deny-over-allow)."""
    rev_perms = dispatch.ClaudeCodeAdapter.ROLE_PERMISSIONS["rev"]
    monkeypatch.setitem(rev_perms, "deny", [*rev_perms["deny"], "Bash(docker *)"])
    monkeypatch.setattr(
        dispatch, "MNT_BASH_DENIES", (*dispatch.MNT_BASH_DENIES, "Bash(docker *)")
    )
    for role in ("rev", "mnt"):
        wt = tmp_path / role
        adapter.write_worktree_settings(wt, role, _FR)
        perms = _settings(wt)
        assert "Bash(docker *)" in perms["allow"], role
        assert "Bash(docker *)" in perms["deny"], role
        assert perms["deny"].count("Bash(docker *)") == 1


# covers hub-tooling FR-0010:AC-4
def test_stack_grants_are_appended_once_in_sorted_order_after_the_static_list(
    stack_repo, adapter, tmp_path, monkeypatch
):
    """Adversarial: the same id declared by markers, an accepted ADR and the
    env var, plus a grant already present in the static allow-list, must
    produce exactly one occurrence of each grant, after the static entries,
    in the table's sorted order."""
    _write(
        stack_repo,
        "specs/decisions/ADR-0001-x.md",
        "---\nid: ADR-0001\nstatus: accepted\nstack_tools: [uv, docker, alembic]\n---\n# x\n",
    )
    monkeypatch.setenv(_ENV, "uv,docker,node")
    dev_perms = dispatch.ClaudeCodeAdapter.ROLE_PERMISSIONS["dev"]
    monkeypatch.setitem(dev_perms, "allow", [*dev_perms["allow"], "Bash(uv *)"])
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    allow = _settings(wt)["allow"]
    assert allow.count("Bash(uv *)") == 1
    assert allow.count("Bash(docker *)") == 1
    tail = allow[len(dev_perms["allow"]) + 2 * len(_OWNS) :]
    assert tail == [
        "Bash(alembic *)",
        "Bash(docker *)",
        "Bash(node *)",
        "Bash(npm *)",
        "Bash(npx *)",
    ]


# covers hub-tooling FR-0010:AC-4
def test_union_helper_never_touches_deny_and_returns_the_same_object_for_no_grants():
    perms = {"allow": ["Read", "Bash(uv *)"], "deny": ["Bash(uv *)", "Edit(src/**)"]}
    out = dispatch._union_grants(perms, ["Bash(uv *)", "Bash(node *)"])
    assert out == {
        "allow": ["Read", "Bash(uv *)", "Bash(node *)"],
        "deny": ["Bash(uv *)", "Edit(src/**)"],
    }
    assert dispatch._union_grants(perms, []) == perms


# ---------------------------------------------------------------------------
# AC-5: rev / bkf derive Edit/Write grants from `owns:` exactly as dev
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-5
@pytest.mark.parametrize("role", ["rev", "bkf"])
def test_rev_and_bkf_get_edit_and_write_for_every_owned_glob_like_dev(
    repo, adapter, tmp_path, role
):
    wt, dev_wt = tmp_path / role, tmp_path / "dev"
    adapter.write_worktree_settings(wt, role, _FR)
    adapter.write_worktree_settings(dev_wt, "dev", _FR)
    perms, static = _settings(wt), _static(role=role)
    assert perms["allow"][: len(static["allow"])] == static["allow"]
    assert perms["deny"] == static["deny"]
    extra = perms["allow"][len(static["allow"]) :]
    assert extra == [f"Edit({g})" for g in _OWNS] + [f"Write({g})" for g in _OWNS]
    # Same derived set as dev's, from the same helper.
    dev_static = _static()
    assert extra == _settings(dev_wt)["allow"][len(dev_static["allow"]) :]


# covers hub-tooling FR-0010:AC-5
def test_role_path_denies_still_win_and_are_written_unchanged(repo, adapter, tmp_path):
    """`src/**` in `owns:` produces the grant for `rev` and leaves
    `Edit(src/**)`/`Write(src/**)` in its deny; `specs/**` does the same for
    `bkf`'s `specs/**` deny."""
    _write_spec(repo, _FR, _fr_md(_FR, ["src/**", "specs/**", "docs/x.md"]))
    for role, denied in (("rev", "src/**"), ("bkf", "specs/**")):
        wt = tmp_path / role
        adapter.write_worktree_settings(wt, role, _FR)
        perms = _settings(wt)
        assert (
            f"Edit({denied})" in perms["allow"] and f"Write({denied})" in perms["allow"]
        )
        assert (
            f"Edit({denied})" in perms["deny"] and f"Write({denied})" in perms["deny"]
        )
        assert perms["deny"] == _static(role=role)["deny"]


# covers hub-tooling FR-0010:AC-5
@pytest.mark.parametrize("role", ["rev", "bkf"])
def test_protected_globs_are_withheld_with_one_warn_each_before_the_spawn_line(
    repo, adapter, tmp_path, capsys, role
):
    _commit_spec(repo, _FR, _fr_md(_FR, _PROTECTED_OWNS + ["docs/ok.md"]))
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, role, _FR)
    perms = _settings(wt)
    assert _grants(perms, "Edit") == _grants(_static(role=role), "Edit") + [
        "docs/ok.md"
    ]
    assert perms["deny"] == _static(role=role)["deny"]
    if role == "rev":
        _dev_branch_in_progress(repo)
        rc = dispatch.cmd_tick(
            apply=False, adapter=adapter, role="rev", fr_filter=[_FR]
        )
    else:
        rc = dispatch.cmd_oneshot(_FR, "bkf", apply=False, adapter=adapter)
    assert rc == 0
    out = capsys.readouterr().out
    warns = [ln for ln in _warn_lines(out) if "owns:" in ln]
    assert len(warns) == 4
    for glob, line in zip(_PROTECTED_OWNS, warns):
        assert glob in line and f".{role}" in line, line
    assert max(_lines(out, "WARN")) < _lines(out, "WOULD-SPAWN")[0]
    assert adapter.spawns == []


# covers hub-tooling FR-0010:AC-5
@pytest.mark.parametrize("role", ["rev", "bkf"])
def test_empty_owns_is_byte_identical_to_the_pre_fr_file(
    repo, adapter, tmp_path, monkeypatch, pre_fr_dispatch, role
):
    _point(monkeypatch, pre_fr_dispatch, repo)
    for shape in ("[]", None):
        text = (
            _fr_md(_FR, None) if shape is None else _fr_md(_FR, owns_raw="owns: []\n")
        )
        _write_spec(repo, _FR, text)
        for cls, rel in (
            ("ClaudeCodeAdapter", ".claude/settings.local.json"),
            ("CursorAdapter", ".cursor/cli.json"),
        ):
            old_wt, new_wt = (
                tmp_path / f"old{shape}{cls}",
                tmp_path / f"new{shape}{cls}",
            )
            getattr(pre_fr_dispatch, cls)().write_worktree_settings(old_wt, role, _FR)
            getattr(dispatch, cls)().write_worktree_settings(new_wt, role, _FR)
            assert (new_wt / rel).read_bytes() == (old_wt / rel).read_bytes(), (
                cls,
                shape,
            )


# covers hub-tooling FR-0010:AC-5
@pytest.mark.parametrize("role", ["rev", "bkf"])
def test_empty_owns_writes_exactly_the_static_payload(repo, adapter, tmp_path, role):
    _write_spec(repo, _FR, _fr_md(_FR, []))
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, role, _FR)
    body = (wt / ".claude" / "settings.local.json").read_bytes().replace(b"\r\n", b"\n")
    assert (
        body
        == (json.dumps({"permissions": _static(role=role)}, indent=2) + "\n").encode()
    )


# covers hub-tooling FR-0010:AC-5
def test_malformed_owns_refuses_rev_tick_and_bkf_oneshot_in_dry_run_and_apply(
    repo, adapter, capsys
):
    """Adversarial: the FR-0009 AC-5 refusal, at the rev/bkf call sites —
    ERROR lines, no spawn line, no worktree, no lock, no spawn record."""
    _commit_spec(repo, _FR, _fr_md(_FR, owns_raw='owns: ["/abs", "src/../x", 7]\n'))
    _dev_branch_in_progress(repo)
    for apply in (False, True):
        assert (
            dispatch.cmd_tick(apply=apply, adapter=adapter, role="rev", fr_filter=[_FR])
            == 0
        )
        out = capsys.readouterr().out
        assert len([ln for ln in out.splitlines() if "ERROR" in ln]) == 3
        assert "WOULD-SPAWN" not in out and "SPAWNED" not in out and "STACK" not in out
        assert dispatch.cmd_oneshot(_FR, "bkf", apply=apply, adapter=adapter) == 1
        out = capsys.readouterr().out
        assert len([ln for ln in out.splitlines() if "ERROR" in ln]) == 3
        assert "WOULD-SPAWN" not in out and "SPAWNED" not in out and "STACK" not in out
    assert adapter.spawns == []
    assert not _role_wt(repo, "rev").exists() and not _role_wt(repo, "bkf").exists()
    assert not (repo / "_dispatch" / f"{_FR}.rev.lock").exists()
    assert _spawn_records() == []


# covers hub-tooling FR-0010:AC-5
@pytest.mark.parametrize("role", ["rev", "bkf"])
def test_direct_spawn_with_malformed_owns_never_widens_beyond_the_static_surface(
    repo, adapter, role
):
    """Adversarial (the asymmetry the PR body flags): bypassing the call-site
    preflight and driving `ensure_role_worktree` directly for rev/bkf with a
    malformed `owns:`. Whatever the refusal behaviour, the safety property
    AC-5 needs is that no path grant beyond the static surface is written."""
    _commit_spec(repo, _FR, _fr_md(_FR, owns_raw='owns: ["../escape", "src/ok.py"]\n'))
    wt, status = dispatch.ensure_role_worktree(_FR, role, adapter)
    if wt is None:
        assert status.startswith("error:")
        return
    perms = _settings(wt)
    assert _grants(perms, "Edit") == _grants(_static(role=role), "Edit")
    assert _grants(perms, "Write") == _grants(_static(role=role), "Write")
    assert perms["deny"] == _static(role=role)["deny"]


# covers hub-tooling FR-0010:AC-5
def test_reused_rev_worktree_re_derives_from_the_current_owns(repo, adapter):
    """Adversarial: like FR-0009 AC-6 for dev — a glob added after the rev
    worktree was created appears on reuse, a removed one disappears."""
    _dev_branch_in_progress(repo)
    result, _pid, wt = dispatch.spawn_role(_FR, "rev", apply=True, adapter=adapter)
    assert result == "spawned" and wt == _role_wt(repo, "rev")
    assert "Edit(alembic.ini)" not in _settings(wt)["allow"]
    _commit_spec(repo, _FR, _fr_md(_FR, ["alembic.ini"]), "owns: swap")
    dispatch.lock_path(_FR, "rev").unlink()
    wt2, status = dispatch.ensure_role_worktree(_FR, "rev", adapter)
    assert wt2 == wt and status.startswith("reused")
    assert _grants(_settings(wt), "Edit") == _grants(_static(role="rev"), "Edit") + [
        "alembic.ini"
    ]


# ---------------------------------------------------------------------------
# AC-6: uv / node / npx leave MNT_BASH_DENIES iff the stack declares them
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-6
def test_uv_node_fixture_lifts_exactly_three_denies_and_preserves_the_rest_in_order(
    repo, monkeypatch, pre_fr_dispatch
):
    _write(repo, "uv.lock", "")
    _write(repo, "package.json", "{}\n")
    assert dispatch.detected_stack_tools() == ["node", "npm", "npx", "uv"]
    _point(monkeypatch, pre_fr_dispatch, repo)
    new = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)["deny"]
    old = pre_fr_dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)["deny"]
    for lifted in _LIFTED:
        assert lifted in old and lifted not in new
    assert new == [d for d in old if d not in _LIFTED]
    for kept in (
        "Bash(pip *)",
        "Bash(bash *)",
        "Bash(sh *)",
        "Bash(powershell *)",
        "Bash(python -c*)",
        "Bash(tee *)",
        "Bash(sed -i*)",
        "Bash(cp *)",
        "Bash(mv *)",
    ):
        assert kept in new


# covers hub-tooling FR-0010:AC-6
def test_marker_less_project_deny_list_is_byte_identical_to_today(
    repo, monkeypatch, pre_fr_dispatch
):
    _point(monkeypatch, pre_fr_dispatch, repo)
    new = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    old = pre_fr_dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    assert new == old
    assert dispatch._mnt_bash_denies([]) == list(dispatch.MNT_BASH_DENIES)


# covers hub-tooling FR-0010:AC-6
@pytest.mark.parametrize(
    ("declared", "lifted"),
    [
        ("node", ["Bash(node *)"]),
        ("npx", ["Bash(npx *)"]),
        ("uv", ["Bash(uv *)"]),
        ("npm", []),
        ("docker", []),
        ("alembic", []),
        ("pip", []),
        ("python", []),
        ("node,npx", ["Bash(node *)", "Bash(npx *)"]),
    ],
)
def test_each_toggled_deny_lifts_only_for_its_own_tool(
    repo, monkeypatch, declared, lifted
):
    """Adversarial: `node` alone must not un-deny `uv`; `pip` in the stack
    (a requirements-only project, or declared outright) never un-denies
    `Bash(pip *)`; nothing else in the list moves."""
    monkeypatch.setenv(_ENV, declared)
    deny = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)["deny"]
    bash_denies = [d for d in deny if d in dispatch.MNT_BASH_DENIES]
    assert bash_denies == [d for d in dispatch.MNT_BASH_DENIES if d not in lifted]
    assert "Bash(pip *)" in deny
    for still in set(_LIFTED) - set(lifted):
        assert still in deny


# covers hub-tooling FR-0010:AC-6
def test_pip_stays_denied_for_a_requirements_only_project(repo):
    _write(repo, "requirements.txt", "typing-extensions\n")
    assert dispatch.detected_stack_tools() == ["pip"]
    deny = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)["deny"]
    assert "Bash(pip *)" in deny and all(d in deny for d in _LIFTED)


# ---------------------------------------------------------------------------
# AC-7: the spawn report names the stack; the metrics record per DEC-0003
# ---------------------------------------------------------------------------


def _assert_stack_line_immediately_before(
    out: str, spawn_marker: str, expected: str
) -> None:
    stack = _lines(out, "STACK")
    spawn = _lines(out, spawn_marker)
    assert len(stack) == 1 and len(spawn) == 1, out
    assert spawn[0] - stack[0] == 1, out
    line = out.splitlines()[stack[0]]
    assert expected in line, line


# covers hub-tooling FR-0010:AC-7
def test_dev_tick_reports_stack_and_grant_count_in_dry_run_and_apply(
    stack_repo, adapter, capsys
):
    expected = "stack=docker,node,npm,npx,python,uv  stack-grants=5"
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    _assert_stack_line_immediately_before(
        capsys.readouterr().out, "WOULD-SPAWN", expected
    )
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    _assert_stack_line_immediately_before(capsys.readouterr().out, "SPAWNED", expected)
    assert [s[1] for s in adapter.spawns] == ["dev"]


# covers hub-tooling FR-0010:AC-7
def test_rev_tick_bkf_and_mnt_oneshot_report_stack_before_their_spawn_line(
    stack_repo, adapter, capsys
):
    expected = "stack=docker,node,npm,npx,python,uv  stack-grants=5"
    _dev_branch_in_progress(stack_repo)
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="rev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    _assert_stack_line_immediately_before(out, "WOULD-SPAWN", expected)
    assert f"{_FR}.rev  STACK" in out
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="rev", fr_filter=[_FR]) == 0
    )
    _assert_stack_line_immediately_before(capsys.readouterr().out, "SPAWNED", expected)
    for role in ("bkf", "mnt"):
        assert dispatch.cmd_oneshot(_FR, role, apply=False, adapter=adapter) == 0
        out = capsys.readouterr().out
        _assert_stack_line_immediately_before(out, "WOULD-SPAWN", expected)
        assert f"{_FR}.{role}  STACK" in out
    assert dispatch.cmd_oneshot(_FR, "bkf", apply=True, adapter=adapter) == 0
    _assert_stack_line_immediately_before(capsys.readouterr().out, "SPAWNED", expected)
    assert [s[1] for s in adapter.spawns] == ["rev", "bkf"]


# covers hub-tooling FR-0010:AC-7
def test_wave_reports_stack_before_the_dev_spawn_line(
    stack_repo, adapter, capsys, monkeypatch
):
    expected = "stack=docker,node,npm,npx,python,uv  stack-grants=5"
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    _assert_stack_line_immediately_before(
        capsys.readouterr().out, "WOULD-SPAWN", expected
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
    )
    _assert_stack_line_immediately_before(capsys.readouterr().out, "SPAWNED", expected)


# covers hub-tooling FR-0010:AC-7
def test_no_stack_reports_stack_none_and_zero_grants(repo, adapter, capsys):
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    _assert_stack_line_immediately_before(
        capsys.readouterr().out, "WOULD-SPAWN", "stack=none  stack-grants=0"
    )


# covers hub-tooling FR-0010:AC-7
def test_spawn_record_carries_stack_segment_only_when_non_empty(stack_repo, adapter):
    result, _pid, _wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    dispatch.lock_path(_FR, "dev").unlink()
    result, _pid, _wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    recs = _spawn_records()
    assert [r["worktree_status"] for r in recs] == [
        "created,stack=docker+node+npm+npx+python+uv",
        "reused,stack=docker+node+npm+npx+python+uv",
    ]
    # The lock keeps the full status string, as today.
    assert _lock(stack_repo, "dev")["worktree_status"] == "reused,venv-created"


# covers hub-tooling FR-0010:AC-7
def test_no_stack_spawn_record_is_exactly_the_base_status(repo, adapter):
    for expected in ("created", "reused"):
        result, _pid, _wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
        assert result == "spawned"
        dispatch.lock_path(_FR, "dev").unlink()
        assert _spawn_records()[-1]["worktree_status"] == expected


# covers hub-tooling FR-0010:AC-7
def test_env_declared_stack_reaches_console_and_record_with_plus_joined_ids(
    repo, adapter, capsys, monkeypatch
):
    """Adversarial: a stack with no markers at all (env only), an id with no
    grant (`pnpm`) alongside one with — the console lists both, counts one
    grant, and the record joins with `+` so the field's own comma delimiter
    is never ambiguous."""
    monkeypatch.setenv(_ENV, "pnpm,alembic")
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    _assert_stack_line_immediately_before(
        capsys.readouterr().out, "SPAWNED", "stack=alembic,pnpm  stack-grants=1"
    )
    [rec] = _spawn_records()
    assert rec["worktree_status"] == "created,stack=alembic+pnpm"
    assert "," not in rec["worktree_status"].split("stack=", 1)[1]


# covers hub-tooling FR-0010:AC-7
def test_rev_fast_forward_reuse_record_is_base_plus_stack_only(stack_repo, adapter):
    """`reused,fast-forwarded,venv-created` in the lock -> `reused,stack=...`
    in the record: `fast-forwarded` and a success venv string never surface."""
    dev_wt = _dev_branch_in_progress(stack_repo)
    result, _pid, _rev_wt = dispatch.spawn_role(_FR, "rev", apply=True, adapter=adapter)
    assert result == "spawned"
    dispatch.lock_path(_FR, "rev").unlink()
    _write(dev_wt, "src/more.py", "x\n")
    _git(dev_wt, "add", "-A")
    _git(dev_wt, "commit", "-q", "-m", "more")
    result, _pid, _wt = dispatch.spawn_role(_FR, "rev", apply=True, adapter=adapter)
    assert result == "spawned"
    assert (
        _lock(stack_repo, "rev")["worktree_status"]
        == "reused,fast-forwarded,venv-created"
    )
    assert (
        _spawn_records()[-1]["worktree_status"]
        == "reused,stack=docker+node+npm+npx+python+uv"
    )


# covers hub-tooling FR-0010:AC-7
@pytest.mark.parametrize(
    "wt_status",
    [
        "created,venv-created",
        "reused,venv-reused",
        "reused,venv-resynced",
        "reused,fast-forwarded,venv-reused",
        "reused,venv reused",
        "created,venv:stub",
        "created",
    ],
)
def test_success_spellings_and_fast_forwarded_never_produce_a_venv_segment(wt_status):
    assert dispatch._venv_metrics_segment(wt_status) == ""
    assert dispatch._stack_metrics_segment(["python", "uv"]) == "stack=python+uv"


# ---------------------------------------------------------------------------
# AC-8: the venv is provisioned from the project's lock / requirements file
# ---------------------------------------------------------------------------


def _project(tmp_path: Path, source: Path | None) -> Path:
    p = tmp_path / "project"
    if source is None:
        p.mkdir(parents=True)
    else:
        shutil.copytree(source, p)
    return p


# covers hub-tooling FR-0010:AC-8
def test_lock_driven_provisioning_installs_the_locked_dependency_and_the_gate_tooling(
    uv, tmp_path
):
    project = _project(tmp_path, _LOCK_PROJECT)
    lock_before = (project / "uv.lock").read_bytes()
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    py = _venv_python(project)
    assert _imports(py, "typing_extensions")  # named only in the lock
    assert _imports(py, "pytest", "yaml", "ruff")  # VENV_PACKAGES topped up
    assert (project / "uv.lock").read_bytes() == lock_before  # never re-resolved
    assert not (
        project / ".venv"
    ).exists()  # synced into VENV_DIRNAME, not uv's default


# covers hub-tooling FR-0010:AC-8
def test_requirements_driven_provisioning_installs_from_the_file(uv, tmp_path):
    project = _project(tmp_path, _REQ_PROJECT)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    py = _venv_python(project)
    assert _imports(py, "typing_extensions", "pytest", "yaml", "ruff")


# covers hub-tooling FR-0010:AC-8
def test_requirements_lock_file_is_honoured_when_requirements_txt_is_absent(
    uv, tmp_path
):
    project = _project(tmp_path, None)
    _write(project, "requirements-dev.lock", "typing-extensions>=4.0\n")
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    assert _imports(_venv_python(project), "typing_extensions", "pytest")


# covers hub-tooling FR-0010:AC-8
def test_no_lock_no_requirements_installs_only_the_gate_tooling(uv, tmp_path):
    """Adversarial: proves the lock/requirements branch is what installed
    `typing_extensions` above — a bare project gets VENV_PACKAGES only."""
    project = _project(tmp_path, None)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    py = _venv_python(project)
    assert _imports(py, "pytest", "yaml", "ruff")
    assert not _imports(py, "typing_extensions")


# covers hub-tooling FR-0010:AC-8
def test_uv_lock_beats_requirements_txt_and_installs_target_the_worktree_venv_only(
    uv, tmp_path, monkeypatch
):
    """Adversarial: with both files present the (valid) lock drives the
    install and the (unresolvable) requirements file is never read; every
    install is pinned to the worktree venv interpreter — no global install."""
    project = _project(tmp_path, _LOCK_PROJECT)
    _write(project, "requirements.txt", "no-such-package-fr0010-zzz==99\n")
    seen = _spy_subprocess(monkeypatch, dispatch)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    venv_path = project / dispatch.VENV_DIRNAME
    for cmd, kwargs in seen:
        assert "timeout" in kwargs, cmd
        if cmd[1:3] == ["pip", "install"]:
            assert cmd[3] == "-p" and Path(cmd[4]) == _venv_python(project), cmd
            assert "-r" not in cmd, cmd
        elif cmd[1] == "sync":
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(venv_path), cmd
            assert "--frozen" in cmd
    assert any(cmd[1] == "sync" for cmd, _ in seen)


# ---------------------------------------------------------------------------
# AC-9: provisioning failure is a classified soft failure, never a spawn abort
# ---------------------------------------------------------------------------


_CLOSED = {
    "uv-not-found",
    "venv-create-failed",
    "lock-sync-failed",
    "requirements-install-failed",
    "packages-install-failed",
}


# covers hub-tooling FR-0010:AC-9
def test_closed_set_matches_the_ac_text_and_the_pre_fr_spelling_is_gone():
    assert dispatch._VENV_FAILURE_CLASSIFICATIONS == frozenset(_CLOSED)
    assert "venv-install-failed" not in dispatch._VENV_FAILURE_CLASSIFICATIONS


# covers hub-tooling FR-0010:AC-9
@pytest.mark.parametrize(
    ("scenario", "classification"),
    [
        ("uv-absent", "uv-not-found"),
        ("garbage-lock", "lock-sync-failed"),
        ("bad-requirements", "requirements-install-failed"),
        ("bad-base-packages", "packages-install-failed"),
        ("bad-python", "venv-create-failed"),
    ],
)
def test_every_failure_mode_returns_its_closed_set_classification(
    uv, tmp_path, monkeypatch, scenario, classification
):
    if scenario == "uv-absent":
        project = _project(tmp_path, _LOCK_PROJECT)
        monkeypatch.setattr(dispatch, "_find_uv", lambda: None)
    elif scenario == "garbage-lock":
        project = _project(tmp_path, _LOCK_PROJECT)
        (project / "uv.lock").write_bytes(b"garbage = [\n")
    elif scenario == "bad-requirements":
        project = _project(tmp_path, None)
        _write(project, "requirements.txt", "no-such-package-fr0010-zzz==99\n")
    elif scenario == "bad-base-packages":
        project = _project(tmp_path, None)
        monkeypatch.setattr(dispatch, "VENV_PACKAGES", ["no-such-package-fr0010-zzz"])
    else:
        project = _project(tmp_path, None)
        monkeypatch.setattr(dispatch, "VENV_PYTHON_VERSION", "9.99")
    ok, msg = _REAL_ENSURE_DEV_VENV(project)
    assert ok is False
    assert msg.split(":", 1)[0] == classification
    assert dispatch._venv_metrics_segment(f"created,{msg}") == f"venv={classification}"
    # A failed lock/requirements provision is never recorded as provisioned:
    # the next call retries rather than reporting `venv-reused` over a
    # half-built venv. (A no-lock project keeps the pre-FR unconditional
    # reuse fast-path by AC-12 — see FINDINGS in REVIEW.md.)
    if scenario in ("garbage-lock", "bad-requirements", "bad-python"):
        ok2, msg2 = _REAL_ENSURE_DEV_VENV(project)
        assert ok2 is False and msg2.split(":", 1)[0] == classification


# covers hub-tooling FR-0010:AC-9
def test_uv_absent_spawn_proceeds_with_one_warn_naming_classification_and_lock(
    stack_repo, adapter, capsys, monkeypatch
):
    # DEC-0005: the pre-flight gate (stubbed here), not this test, decides whether a declared-but-missing `uv` reaches the provisioner.
    monkeypatch.setattr(dispatch, "ensure_dev_venv", _REAL_ENSURE_DEV_VENV)
    monkeypatch.setattr(dispatch, "_find_uv", lambda: None)
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    warns = _warn_lines(out)
    assert len(warns) == 1
    assert (
        "uv-not-found" in warns[0]
        and "uv.lock" in warns[0]
        and f"{_FR}.dev" in warns[0]
    )
    assert _lines(out, "WARN")[0] < _lines(out, "SPAWNED")[0]
    assert [s[1] for s in adapter.spawns] == ["dev"]
    wt = _role_wt(stack_repo, "dev")
    assert wt.exists() and not (wt / dispatch.VENV_DIRNAME).exists()
    assert _lock(stack_repo, "dev")["worktree_status"] == "created,uv-not-found"
    [rec] = _spawn_records()
    assert (
        rec["worktree_status"]
        == "created,stack=docker+node+npm+npx+python+uv,venv=uv-not-found"
    )


# covers hub-tooling FR-0010:AC-9
def test_lock_sync_failure_record_carries_bare_classification_after_stack(
    uv, stack_repo, adapter, capsys, monkeypatch
):
    """Adversarial: a real `uv sync` failure whose message carries a
    `:`-suffixed detail; the record must carry the bare classification, in
    order after `stack=`, and the WARN must name `uv.lock`."""
    (stack_repo / "uv.lock").write_bytes(b"garbage = [\n")
    _commit_all(stack_repo, "break the lock")
    monkeypatch.setattr(dispatch, "ensure_dev_venv", _REAL_ENSURE_DEV_VENV)
    result, _pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned" and wt is not None
    warns = _warn_lines(capsys.readouterr().out)
    assert len(warns) == 1 and "lock-sync-failed" in warns[0] and "uv.lock" in warns[0]
    lock_status = _lock(stack_repo, "dev")["worktree_status"]
    assert lock_status.startswith("created,lock-sync-failed:") and len(
        lock_status
    ) > len("created,lock-sync-failed:")
    [rec] = _spawn_records()
    assert (
        rec["worktree_status"]
        == "created,stack=docker+node+npm+npx+python+uv,venv=lock-sync-failed"
    )


# covers hub-tooling FR-0010:AC-9
def test_no_stack_failure_record_is_base_plus_venv_segment_only(
    repo, adapter, capsys, monkeypatch
):
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (False, "uv-not-found"))
    for expected in ("created,venv=uv-not-found", "reused,venv=uv-not-found"):
        result, _pid, _wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
        assert result == "spawned"
        dispatch.lock_path(_FR, "dev").unlink()
        assert _spawn_records()[-1]["worktree_status"] == expected
        warns = _warn_lines(capsys.readouterr().out)
        assert len(warns) == 1 and "uv-not-found" in warns[0]
        assert "static VENV_PACKAGES" in warns[0]


# covers hub-tooling FR-0010:AC-9
def test_requirements_only_failure_record_carries_pip_stack_then_venv_and_names_the_file(
    repo, adapter, capsys, monkeypatch
):
    """`pip` is in the stack but maps to no grant; the record still carries
    it, ordered before `venv=`, and the WARN names the requirements file the
    provisioner was reading (the worktree's copy)."""
    _write(repo, "requirements.txt", "no-such-package-fr0010-zzz==99\n")
    _commit_all(repo, "requirements")
    monkeypatch.setattr(
        dispatch,
        "ensure_dev_venv",
        lambda wt: (False, "requirements-install-failed:boom"),
    )
    result, _pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    [rec] = _spawn_records()
    assert (
        rec["worktree_status"] == "created,stack=pip,venv=requirements-install-failed"
    )
    warns = _warn_lines(capsys.readouterr().out)
    assert len(warns) == 1 and str(wt / "requirements.txt") in warns[0]
    assert (
        _lock(repo, "dev")["worktree_status"]
        == "created,requirements-install-failed:boom"
    )


# covers hub-tooling FR-0010:AC-9
def test_a_classification_lookalike_never_becomes_a_segment():
    """Adversarial: only the closed set, matched whole, produces `venv=`."""
    for status in (
        "created,uv-not-found-really",
        "created,xlock-sync-failed",
        "created,LOCK-SYNC-FAILED",
        "created,venv-install-failed:old spelling",
        "created,detail:lock-sync-failed",
    ):
        assert dispatch._venv_metrics_segment(status) == "", status
    assert (
        dispatch._venv_metrics_segment("reused,fast-forwarded,uv-not-found")
        == "venv=uv-not-found"
    )
    assert (
        dispatch._venv_metrics_segment("created,lock-sync-failed:x:y")
        == "venv=lock-sync-failed"
    )


# ---------------------------------------------------------------------------
# AC-10: idempotent and bounded
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-10
def test_unchanged_lock_reuses_without_any_subprocess_and_changed_lock_resyncs(
    uv, tmp_path, monkeypatch
):
    project = _project(tmp_path, _LOCK_PROJECT)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    lock = project / "uv.lock"
    content = lock.read_bytes()
    lock.write_bytes(content)  # touched: new mtime, identical content
    seen = _spy_subprocess(monkeypatch, dispatch)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-reused")
    assert seen == []
    lock.write_bytes(content + b"\n# a comment changes the hash\n")
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-resynced")
    assert any(cmd[1] == "sync" for cmd, _ in seen)
    assert all("timeout" in kwargs for _, kwargs in seen)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-reused")


# covers hub-tooling FR-0010:AC-10
def test_resync_installs_a_dependency_added_to_the_lock(uv, tmp_path):
    project = _project(tmp_path, _LOCK_PROJECT)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    assert not _imports(_venv_python(project), "six")
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            '"typing-extensions>=4.0"', '"typing-extensions>=4.0", "six>=1.16"'
        ),
        encoding="utf-8",
        newline="\n",
    )
    relock = subprocess.run(
        [uv, "lock"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if relock.returncode != 0:
        pytest.skip(f"uv lock could not resolve here: {relock.stderr[:200]}")
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-resynced")
    assert _imports(_venv_python(project), "six", "typing_extensions", "pytest")


# covers hub-tooling FR-0010:AC-10
def test_every_provisioning_subprocess_carries_an_explicit_timeout(
    uv, tmp_path, monkeypatch
):
    seen = _spy_subprocess(monkeypatch, dispatch)
    for source in (_LOCK_PROJECT, _REQ_PROJECT, None):
        project = _project(tmp_path / (source.name if source else "bare"), source)
        assert _REAL_ENSURE_DEV_VENV(project)[0] is True
    assert seen
    for cmd, kwargs in seen:
        assert (
            isinstance(kwargs.get("timeout"), (int, float)) and kwargs["timeout"] > 0
        ), cmd


# covers hub-tooling FR-0010:AC-10
def test_kind_switch_corrupt_state_and_pre_fr_venv_all_resync_rather_than_reuse(
    uv, tmp_path, monkeypatch
):
    """Adversarial: (a) a venv provisioned from requirements.txt that then
    gains a uv.lock re-syncs (kind-prefixed fingerprint); (b) a corrupt state
    file re-syncs instead of crashing; (c) a venv with no state file (built by
    the pre-FR dispatcher) re-syncs on the first call that sees a lock."""
    project = _project(tmp_path, _REQ_PROJECT)
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-created")
    shutil.copy(_LOCK_PROJECT / "pyproject.toml", project / "pyproject.toml")
    shutil.copy(_LOCK_PROJECT / "uv.lock", project / "uv.lock")
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-resynced")
    state = project / dispatch.VENV_DIRNAME / dispatch._VENV_PROVISION_STATE_FILENAME
    state.write_text("{not json", encoding="utf-8")
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-resynced")
    state.unlink()
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-resynced")
    assert _REAL_ENSURE_DEV_VENV(project) == (True, "venv-reused")


# ---------------------------------------------------------------------------
# AC-11: the Cursor adapter applies the same derivation
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-11
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_cursor_static_roles_union_shell_grants_and_owns_writes_deny_unchanged(
    stack_repo, tmp_path, role
):
    wt = tmp_path / "wt"
    dispatch.CursorAdapter().write_worktree_settings(wt, role, _FR)
    perms = _cursor_settings(wt)
    static = _static(adapter_cls="CursorAdapter", role=role)
    expected_stack = [
        g for g in dispatch.cursor_stack_grants(_FULL_STACK) if g not in static["allow"]
    ]
    assert (
        perms["allow"]
        == static["allow"] + [f"Write({g})" for g in _OWNS] + expected_stack
    )
    assert perms["deny"] == static["deny"]
    assert not any(a.startswith("Edit(") for a in perms["allow"])
    for tool in ("docker", "node", "npm", "npx", "uv"):
        assert f"Shell({tool})" in perms["allow"], tool


# covers hub-tooling FR-0010:AC-11
def test_cursor_mnt_lifts_the_three_shell_denies_and_unions_shell_grants(
    stack_repo, monkeypatch, pre_fr_dispatch
):
    _point(monkeypatch, pre_fr_dispatch, stack_repo)
    new = dispatch.CursorAdapter().mnt_permissions(_FR)
    old = pre_fr_dispatch.CursorAdapter().mnt_permissions(_FR)
    assert new["deny"] == [d for d in old["deny"] if d not in _CURSOR_LIFTED]
    assert new["allow"] == old["allow"] + [
        g for g in dispatch.cursor_stack_grants(_FULL_STACK) if g not in old["allow"]
    ]
    assert "Shell(pip)" in new["deny"]
    # node alone lifts node alone, exactly as the Claude adapter.
    monkeypatch.setenv(_ENV, "node")
    _write(stack_repo, "uv.lock", "")  # keep the marker; env adds nothing new
    for m in (
        stack_repo / "package.json",
        stack_repo / "uv.lock",
        stack_repo / "docker-compose.yml",
    ):
        m.unlink()
    (stack_repo / "pyproject.toml").unlink()
    assert dispatch.detected_stack_tools() == ["node"]
    deny = dispatch.CursorAdapter().mnt_permissions(_FR)["deny"]
    assert "Shell(node)" not in deny and "Shell(uv)" in deny and "Shell(npx)" in deny


# covers hub-tooling FR-0010:AC-11
@pytest.mark.parametrize("role", ["rev", "bkf"])
def test_cursor_rev_and_bkf_withhold_identically_to_claude_and_keep_path_denies(
    repo, tmp_path, role
):
    owns = _PROTECTED_OWNS + ["src/**", "specs/**", "docs/ok.md"]
    _write_spec(repo, _FR, _fr_md(_FR, owns))
    c_wt, k_wt = tmp_path / "cursor", tmp_path / "claude"
    dispatch.CursorAdapter().write_worktree_settings(c_wt, role, _FR)
    dispatch.ClaudeCodeAdapter().write_worktree_settings(k_wt, role, _FR)
    c_static = _static(adapter_cls="CursorAdapter", role=role)
    k_static = _static(role=role)
    c_new = _cursor_settings(c_wt)["allow"][len(c_static["allow"]) :]
    k_new = _settings(k_wt)["allow"][len(k_static["allow"]) :]
    assert c_new == [f"Write({g})" for g in ["src/**", "specs/**", "docs/ok.md"]]
    assert c_new == [a for a in k_new if a.startswith("Write(")]
    assert _cursor_settings(c_wt)["deny"] == c_static["deny"]
    assert (
        "Write(src/**)" in _cursor_settings(c_wt)["deny"]
    )  # rev's and bkf's path deny


# covers hub-tooling FR-0010:AC-11
def test_cursor_stack_grant_table_is_closed_and_shell_shaped():
    assert set(dispatch.CURSOR_STACK_SHELL_GRANTS) == set(
        stack_profile.STACK_BASH_GRANTS
    )
    assert dispatch.cursor_stack_grants([]) == []
    assert (
        dispatch.cursor_stack_grants(["kubectl", "pnpm", "yarn", "python", "pip"]) == []
    )
    for tool, grants in dispatch.CURSOR_STACK_SHELL_GRANTS.items():
        assert grants == (f"Shell({tool})",)


# ---------------------------------------------------------------------------
# AC-12: a no-stack project is byte-identical to today; dry-run mutates nothing
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0010:AC-12
@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "docs", "mnt"])
def test_no_stack_permission_files_are_byte_identical_to_the_pre_fr_dispatcher(
    repo, tmp_path, monkeypatch, pre_fr_dispatch, role
):
    """rev/bkf against an ownerless FR (DEC-0002); dev/mnt/docs against a
    rich `owns:` (their derivation predates this FR)."""
    _point(monkeypatch, pre_fr_dispatch, repo)
    owns = [] if role in ("rev", "bkf") else _OWNS + [".agent-team/roles/developer.md"]
    _write_spec(repo, _FR, _fr_md(_FR, owns))
    for cls, rel in (
        ("ClaudeCodeAdapter", ".claude/settings.local.json"),
        ("CursorAdapter", ".cursor/cli.json"),
    ):
        old_wt, new_wt = tmp_path / f"old-{cls}-{role}", tmp_path / f"new-{cls}-{role}"
        getattr(pre_fr_dispatch, cls)().write_worktree_settings(old_wt, role, _FR)
        getattr(dispatch, cls)().write_worktree_settings(new_wt, role, _FR)
        assert (new_wt / rel).exists() == (old_wt / rel).exists(), (cls, role)
        if (old_wt / rel).exists():
            assert (new_wt / rel).read_bytes() == (old_wt / rel).read_bytes(), (
                cls,
                role,
            )
    for cls in ("ClaudeCodeAdapter", "CursorAdapter"):
        assert (
            getattr(dispatch, cls).ROLE_PERMISSIONS
            == getattr(pre_fr_dispatch, cls).ROLE_PERMISSIONS
        )
    assert dispatch.MNT_BASH_DENIES == pre_fr_dispatch.MNT_BASH_DENIES


# covers hub-tooling FR-0010:AC-12
def test_no_stack_ensure_dev_venv_runs_exactly_the_pre_fr_commands(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    """Both dispatchers driven over a fake `subprocess.run` on a project with
    no lock and no requirements: identical argv sequence, identical
    timeouts, identical results, and the reuse fast-path writes no state."""
    for mod in (dispatch, pre_fr_dispatch):
        monkeypatch.setattr(mod, "_find_uv", lambda: "uv")
        monkeypatch.setattr(mod, "VENV_PACKAGES", ["pyyaml", "ruff", "pytest"])
        monkeypatch.setattr(mod, "VENV_PYTHON_VERSION", "3.11")

    def run_with(mod, project: Path):
        seen: list[tuple[list[str], float | None]] = []

        def fake_run(cmd, *a, **k):
            seen.append(([str(c) for c in cmd], k.get("timeout")))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        result = mod.ensure_dev_venv(project)
        return result, [(cmd[1:3] + cmd[3:], t) for cmd, t in seen]

    new_p, old_p = tmp_path / "new", tmp_path / "old"
    new_p.mkdir()
    old_p.mkdir()
    new_result, new_cmds = run_with(dispatch, new_p)
    old_result, old_cmds = run_with(pre_fr_dispatch, old_p)
    assert new_result == old_result == (True, "venv-created")
    norm = lambda cmds, root: [
        ([c.replace(str(root), "<root>") for c in cmd], t) for cmd, t in cmds
    ]
    assert norm(new_cmds, new_p) == norm(old_cmds, old_p)
    assert len(new_cmds) == 2  # uv venv, uv pip install <VENV_PACKAGES>
    assert not (
        new_p / dispatch.VENV_DIRNAME / dispatch._VENV_PROVISION_STATE_FILENAME
    ).exists()
    # Existing venv, nothing declared: the pre-FR unconditional fast-path.
    py = _venv_python(new_p)
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr(dispatch, "_find_uv", lambda: None)
    assert dispatch.ensure_dev_venv(new_p) == (True, "venv-reused")


# covers hub-tooling FR-0010:AC-12
def test_no_stack_spawn_record_and_lock_are_byte_identical_to_today(repo, adapter):
    """Adversarial: the healthy no-stack spawn record is exactly `created`
    then `reused` (FR-0002's pinned values), and the lock's full status
    string is unchanged, for dev and rev alike."""
    for role in ("dev", "rev"):
        if role == "rev":
            _dev_branch_in_progress(repo)  # reuses the spawned dev worktree
        for expected in ("created", "reused"):
            result, _pid, _wt = dispatch.spawn_role(
                _FR, role, apply=True, adapter=adapter
            )
            assert result == "spawned", role
            dispatch.lock_path(_FR, role).unlink()
            assert _spawn_records()[-1]["worktree_status"] == expected, role
    statuses = [r["worktree_status"] for r in _spawn_records()]
    assert statuses == ["created", "reused", "created", "reused"]
    for r in _spawn_records():
        assert (
            "stack=" not in r["worktree_status"] and "venv=" not in r["worktree_status"]
        )


# covers hub-tooling FR-0010:AC-12
def test_dry_run_tick_wave_and_oneshot_create_no_venv_and_write_no_settings(
    stack_repo, adapter, capsys, monkeypatch
):
    def _no_venv(wt):
        raise AssertionError("dry-run must never provision a venv")

    monkeypatch.setattr(dispatch, "ensure_dev_venv", _no_venv)
    written: list[Path] = []
    real_write = adapter.write_worktree_settings
    adapter.write_worktree_settings = lambda wt, role, fr: (
        written.append(wt),
        real_write(wt, role, fr),
    )
    before = _git(stack_repo, "status", "--porcelain")
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    assert dispatch.cmd_oneshot(_FR, "bkf", apply=False, adapter=adapter) == 0
    assert dispatch.cmd_oneshot(_FR, "mnt", apply=False, adapter=adapter) == 0
    assert not (stack_repo / ".claude" / "worktrees").exists()
    _dev_branch_in_progress(stack_repo)  # a dev branch for the Reviewer to review
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="rev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    assert out.count("STACK") == 5 and out.count("stack-grants=5") == 5
    assert written == [] and adapter.spawns == []
    for role in ("rev", "bkf", "mnt"):
        assert not _role_wt(stack_repo, role).exists()
    assert not (stack_repo / dispatch.VENV_DIRNAME).exists()
    # Nothing new appeared: the only untracked path is the dev worktree the
    # test itself created for the Reviewer to review.
    assert before == "" and _git(stack_repo, "status", "--porcelain") == "?? .claude/"
    assert _spawn_records() == []


# covers hub-tooling FR-0010:AC-12
def test_dry_run_leaves_an_existing_worktree_byte_identical_even_when_grants_changed(
    stack_repo, adapter, capsys, monkeypatch
):
    """Adversarial: spawn for real, then change both the stack (add alembic)
    and `owns:` so a forbidden dry-run rewrite would be visible; the tree —
    settings and venv marker included — must not change."""
    # dev: real spawn, then widen the stack and owns:, then dry-run tick + wave.
    result, _pid, dev_wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    dispatch.lock_path(_FR, "dev").unlink()
    _write(stack_repo, "alembic.ini", "[alembic]\n")
    _commit_spec(stack_repo, _FR, _fr_md(_FR, _OWNS + ["alembic.ini"]), "owns: add")
    dev_digest = _tree_digest(dev_wt)
    monkeypatch.setattr(
        dispatch, "ensure_dev_venv", lambda wt: pytest.fail("dry-run provisioned")
    )
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    out = capsys.readouterr().out
    assert out.count("stack=alembic,docker,node,npm,npx,python,uv  stack-grants=6") == 2
    assert _tree_digest(dev_wt) == dev_digest
    assert "Bash(alembic *)" not in _settings(dev_wt)["allow"]
    # rev: real spawn, then a new dev commit (apply would fast-forward), then
    # a dry-run tick: the preview is printed, the worktree is untouched.
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (True, "venv-created"))
    _dev_branch_in_progress(stack_repo)
    result, _pid, rev_wt = dispatch.spawn_role(_FR, "rev", apply=True, adapter=adapter)
    assert result == "spawned"
    dispatch.lock_path(_FR, "rev").unlink()
    _write(dev_wt, "src/more.py", "x\n")
    _git(dev_wt, "add", "-A")
    _git(dev_wt, "commit", "-q", "-m", "more")
    rev_digest, rev_head = _tree_digest(rev_wt), _git(rev_wt, "rev-parse", "HEAD")
    monkeypatch.setattr(
        dispatch, "ensure_dev_venv", lambda wt: pytest.fail("dry-run provisioned")
    )
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="rev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    assert "WOULD-FAST-FORWARD" in out and "WOULD-SPAWN" in out
    assert out.count("stack=alembic,docker,node,npm,npx,python,uv  stack-grants=6") == 1
    assert _tree_digest(rev_wt) == rev_digest
    assert _git(rev_wt, "rev-parse", "HEAD") == rev_head
    assert len(adapter.spawns) == 2


# covers hub-tooling FR-0010:AC-12
def test_detected_but_ungranted_tools_are_reported_and_grant_nothing(
    repo, adapter, tmp_path, capsys
):
    """Out of scope: pnpm / yarn are detected (they name the stack) but map
    to no grant; the settings file gains nothing for them."""
    _write(repo, "pnpm-lock.yaml", "")
    _write(repo, "yarn.lock", "")
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    assert _bash_grants(_settings(wt)) == _bash_grants(_static())
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert "stack=pnpm,yarn  stack-grants=0" in capsys.readouterr().out
