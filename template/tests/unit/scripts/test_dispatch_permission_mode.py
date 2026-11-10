"""Tests for hub-tooling FR-0028 — the Claude Code adapter starts every role
with an explicit `--permission-mode default`.

AC-1 pins the whole argv `ClaudeCodeAdapter.spawn` hands `subprocess.Popen`
across the FR's matrix (every role, `gat` with a gate id, an extra prompt, a
model override, prefix "" and a subdirectory project). AC-2 sets every
override a naive implementation might read — environment variables, a CLI
flag, host settings keys, an FR field — and shows the argv does not move, then
scans the source. AC-3 loads the base ref's `dispatch.py` as a second module
and shows everything else is byte-identical: the argv minus the pair, Cursor,
both previews, every permission file, and the dry-run `tick` output. The bite
checks show the pin fails against the base ref and against three in-memory
mutations of this FR's copy.

Harness: `dispatch.py` loaded by path; `REPO_ROOT` re-pointed at a synthetic
git repository under `tmp_path`; `shutil.which` and `subprocess.Popen` are
signature-faithful doubles on the module under test (and on the base-ref
module for AC-3). No real `claude` or `cursor-agent` runs.

Coverage annotations are written `# covers hub-tooling FR-0028:AC-N` rather
than the gate's own form on purpose: this file rides along into every
bootstrapped project, where no FR-0028 exists and `deploy-gate.py` would fail
with "references unknown FR".

Every fixture is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_DISPATCH_PY = _SCRIPTS_DIR / "dispatch.py"
_BASELINE_REF = "8f785fd"  # main when FR-0028 was dispatched
_FR = "FR-0001"
_GATE = "arch"
_PREFIX = "projects/demo/"
_PAIR = ["--permission-mode", "default"]

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log  # noqa: E402  (sibling module, importable by name)

_REAL_RUN = subprocess.run
_REAL_POPEN = subprocess.Popen
_REAL_WHICH = shutil.which
_POPEN_SIG = inspect.signature(_REAL_POPEN)
_WHICH_SIG = inspect.signature(_REAL_WHICH)

# The slash command each role's prompt opens with. A template-owned
# vocabulary, so pinned as a literal (craft rule: "Derive stated vocabularies").
_SLASH = {
    "dev": "developer",
    "rev": "reviewer",
    "bkf": "reviewer-backfill",
    "mnt": "maintainer",
    "gat": "gate-review",
}


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_DISPATCH_PY, "dispatch_under_test_fr0028")


@functools.lru_cache(maxsize=1)
def _baseline_source() -> bytes | None:
    proc = _REAL_RUN(
        [
            "git",
            "-C",
            str(_TEMPLATE_DIR.parent),
            "show",
            f"{_BASELINE_REF}:template/scripts/dispatch.py",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


@pytest.fixture(scope="session")
def base_dispatch(tmp_path_factory):
    """The base ref's dispatcher. Its siblings are the working tree's: FR-0028
    changes `dispatch.py` only, so they are the base ref's too."""
    src = _baseline_source()
    if src is None:
        pytest.skip(f"base-ref dispatch.py ({_BASELINE_REF}) not reachable")
    d = tmp_path_factory.mktemp("base_fr0028_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_base_fr0028")


@pytest.fixture(autouse=True)
def _no_inherited_overrides(monkeypatch):
    for key in (
        "DISPATCH_METRICS_DIR",
        "DISPATCH_WORKTREE",
        "DISPATCH_RUN_ID",
        "DISPATCH_HARNESS",
        "DISPATCH_PERMISSION_MODE",
        *(f"DISPATCH_MODEL_{r.upper()}" for r in _SLASH),
        *(f"DISPATCH_PERMISSION_MODE_{r.upper()}" for r in _SLASH),
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Fixture repository and doubles
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    proc = _REAL_RUN(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr or proc.stdout}"
    return (proc.stdout or "").strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def _fr_md(extra_frontmatter: str = "") -> str:
    return f"""---
id: {_FR}
title: Synthetic {_FR}
status: ready
owner: architect
depends_on: []
tags: []
owns: ["src/**"]
reads: []
derived_from: null
pattern: null
ac_state: {{}}
{extra_frontmatter}created: 2026-01-01
updated: 2026-01-01
---

# {_FR}: Synthetic

## Acceptance criteria

- **AC-1:** does the first thing
"""


def _command_md(slash: str) -> str:
    return f"---\ndescription: synthetic {slash}\n---\n\nSynthetic {slash} for $ARGUMENTS.\n"


def _make_env(
    tmp_path: Path, *, subdir: bool = False, fr_extra: str = ""
) -> SimpleNamespace:
    """A synthetic repository whose project is its top (prefix "") or
    `projects/demo/` (FR-0024's subdirectory shape)."""
    top = tmp_path / "top"
    top.mkdir(parents=True)
    _git(top, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(top, "config", k, v)
    proj = top / "projects" / "demo" if subdir else top
    _write(proj / "specs" / f"{_FR}-synthetic.md", _fr_md(fr_extra))
    _write(proj / "specs" / "INDEX.md", "# Spec index\n")
    _write(proj / "src" / "a.py", "a = 1\n")
    for slash in _SLASH.values():
        _write(proj / ".claude" / "commands" / f"{slash}.md", _command_md(slash))
    _write(top / ".gitignore", "**/.claude/worktrees/\n_dispatch/\n")
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "base")
    wt = proj / ".claude" / "worktrees" / f"dev-{_FR}"
    wt.mkdir(parents=True)
    return SimpleNamespace(top=top, proj=proj, wt=wt, tmp=tmp_path)


def _point(monkeypatch, mod, env: SimpleNamespace) -> None:
    proj = env.proj
    monkeypatch.setattr(mod, "REPO_ROOT", proj)
    monkeypatch.setattr(mod, "SPECS_DIR", proj / "specs")
    monkeypatch.setattr(mod, "COMMANDS_DIR", proj / ".claude" / "commands")
    monkeypatch.setattr(mod, "DISPATCH_DIR", proj / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", proj / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", proj / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_PROJECT_PREFIX_CACHE", {}, raising=False)
    monkeypatch.setattr(mod, "_find_uv", lambda: None)
    if getattr(mod, "_metrics", None) is not None:
        monkeypatch.setattr(mod._metrics, "METRICS_DIR", env.tmp / "metrics")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", env.tmp / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    (proj / "_dispatch").mkdir(exist_ok=True)
    # Warm the prefix cache before Popen is faked (FR-0024's test does too).
    mod._project_prefix()


class _Proc:
    pid = 4343


class _Recorder:
    """Signature-faithful `shutil.which` and `subprocess.Popen` doubles: a
    call that no longer binds to the real signature fails the test."""

    def __init__(self, binary: str, raise_oserror: bool = False):
        self.binary = binary
        self.raise_oserror = raise_oserror
        self.calls: list[SimpleNamespace] = []
        self.which_names: list[str] = []

    def which(self, *args, **kwargs):
        bound = _WHICH_SIG.bind(*args, **kwargs)
        self.which_names.append(bound.arguments["cmd"])
        return self.binary

    def popen(self, *args, **kwargs):
        bound = _POPEN_SIG.bind(*args, **kwargs)
        argv = list(bound.arguments["args"])
        kw = dict(bound.arguments.get("kwargs", {}))
        kw.update(
            {k: v for k, v in bound.arguments.items() if k not in ("args", "kwargs")}
        )
        stdout = kw.get("stdout")
        stdout_name = getattr(stdout, "name", None)
        if stdout is not None and hasattr(stdout, "close"):
            stdout.close()
        self.calls.append(SimpleNamespace(argv=argv, kw=kw, stdout_name=stdout_name))
        if self.raise_oserror:
            raise OSError("synthetic spawn failure")
        return _Proc()


def _spawn(monkeypatch, mod, env, role, *, adapter_cls="ClaudeCodeAdapter", **kw):
    rec = _Recorder(str(env.tmp / "bin" / "claude-synthetic"))
    monkeypatch.setattr(mod.shutil, "which", rec.which)
    monkeypatch.setattr(mod.subprocess, "Popen", rec.popen)
    log = env.tmp / f"{role}-agent.log"
    try:
        result = getattr(mod, adapter_cls)().spawn(_FR, role, env.wt, log, **kw)
    finally:
        monkeypatch.setattr(mod.shutil, "which", _REAL_WHICH)
        monkeypatch.setattr(mod.subprocess, "Popen", _REAL_POPEN)
    assert len(rec.calls) == 1, rec.calls
    call = rec.calls[0]
    call.result = result
    call.binary = rec.binary
    call.log = log
    return call


def _expected_argv(
    mod, binary: str, role: str, *, gate_id=None, extra_prompt=None
) -> list[str]:
    """AC-1's argv, built from the AC's text rather than from `spawn`."""
    args = f"{_FR} {gate_id}" if gate_id else _FR
    prompt = f"/{_SLASH[role]} {args}"
    if extra_prompt:
        prompt = f"{prompt}\n\n{extra_prompt}"
    argv = [binary, "-p", prompt, "--output-format", "stream-json", "--verbose", *_PAIR]
    model = mod._resolve_model(role)
    if model is not None:
        argv += ["--model", model]
    return argv


def _assert_pinned(argv: list[str]) -> None:
    """The pin: exactly one `--permission-mode`, followed by `default`,
    immediately after `--verbose` and before `--model`."""
    assert argv.count("--permission-mode") == 1, argv
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "default", argv
    assert argv[i - 1] == "--verbose", argv
    if "--model" in argv:
        assert i < argv.index("--model"), argv


def _without_pair(argv: list[str]) -> list[str]:
    for i in range(len(argv) - 1):
        if argv[i : i + 2] == _PAIR:
            return argv[:i] + argv[i + 2 :]
    raise AssertionError(f"adjacent pair {_PAIR} not in {argv}")


# AC-1's matrix: (id, role, spawn kwargs, env overrides).
_MATRIX = [
    ("dev", "dev", {}, {}),
    ("rev", "rev", {}, {}),
    ("bkf", "bkf", {}, {}),
    ("mnt", "mnt", {}, {}),
    ("gat-gate", "gat", {"gate_id": _GATE}, {}),
    ("rev-extra", "rev", {"extra_prompt": "Round 2 brief.\nSecond line."}, {}),
    ("dev-model-env", "dev", {}, {"DISPATCH_MODEL_DEV": "opus"}),
]
_MATRIX_IDS = [m[0] for m in _MATRIX]


# ---------------------------------------------------------------------------
# AC-1: every Claude Code spawn carries `--permission-mode default`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subdir", [False, True], ids=["prefix-empty", "subdirectory"])
@pytest.mark.parametrize(("case", "role", "kw", "envs"), _MATRIX, ids=_MATRIX_IDS)
# covers hub-tooling FR-0028:AC-1
def test_every_claude_spawn_hands_popen_the_pinned_argv(
    tmp_path, monkeypatch, case, role, kw, envs, subdir
):
    env = _make_env(tmp_path, subdir=subdir)
    _point(monkeypatch, dispatch, env)
    for k, v in envs.items():
        monkeypatch.setenv(k, v)
    call = _spawn(monkeypatch, dispatch, env, role, **kw)
    assert call.argv == _expected_argv(dispatch, call.binary, role, **kw)
    _assert_pinned(call.argv)
    assert call.result == ("spawned", 4343)
    # The other Popen arguments are today's, exactly.
    assert set(call.kw) == {"cwd", "stdout", "stderr", "stdin", "close_fds"}
    assert Path(call.kw["cwd"]) == (env.wt / "projects" / "demo" if subdir else env.wt)
    assert call.stdout_name == str(call.log)
    assert call.kw["stderr"] == subprocess.STDOUT
    assert call.kw["stdin"] == subprocess.DEVNULL
    assert call.kw["close_fds"] is True


# covers hub-tooling FR-0028:AC-1
def test_gat_has_no_model_and_the_pair_is_the_argv_tail(tmp_path, monkeypatch):
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    assert dispatch._resolve_model("gat") is None
    call = _spawn(monkeypatch, dispatch, env, "gat", gate_id=_GATE)
    assert "--model" not in call.argv
    assert len(call.argv) == 8
    assert call.argv[-2:] == _PAIR
    assert call.argv[2] == f"/gate-review {_FR} {_GATE}"


# covers hub-tooling FR-0028:AC-1
def test_the_model_override_changes_only_the_model_value(tmp_path, monkeypatch):
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    plain = _spawn(monkeypatch, dispatch, env, "dev").argv
    monkeypatch.setenv("DISPATCH_MODEL_DEV", "  opus  ")
    overridden = _spawn(monkeypatch, dispatch, env, "dev").argv
    assert plain[-2:] == ["--model", "sonnet"]
    assert overridden[-2:] == ["--model", "opus"]
    assert overridden[:-1] == plain[:-1]
    _assert_pinned(overridden)


# covers hub-tooling FR-0028:AC-1
def test_the_subdirectory_project_changes_only_cwd(tmp_path, monkeypatch):
    top_env = _make_env(tmp_path / "a")
    sub_env = _make_env(tmp_path / "b", subdir=True)
    _point(monkeypatch, dispatch, top_env)
    assert dispatch._project_prefix() == ""
    top = _spawn(monkeypatch, dispatch, top_env, "dev")
    _point(monkeypatch, dispatch, sub_env)
    assert dispatch._project_prefix() == _PREFIX
    sub = _spawn(monkeypatch, dispatch, sub_env, "dev")
    assert top.argv[1:] == sub.argv[1:]
    assert Path(top.kw["cwd"]) == top_env.wt
    assert Path(sub.kw["cwd"]) == sub_env.wt / "projects" / "demo"


# covers hub-tooling FR-0028:AC-1
def test_a_role_added_later_is_pinned_too(tmp_path, monkeypatch):
    """Adversarial: a role absent from every role table (and from
    `ROLE_MODEL`) still gets the pair — the pin is not per-role."""
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    call = _spawn(monkeypatch, dispatch, env, "zzz")
    assert call.argv[2] == f"/zzz {_FR}"
    assert call.argv[-2:] == _PAIR
    _assert_pinned(call.argv)


# covers hub-tooling FR-0028:AC-1
def test_a_prompt_naming_another_mode_does_not_add_a_flag(tmp_path, monkeypatch):
    """Adversarial: an extra prompt that spells out a competing flag stays one
    prompt element; the argv still carries exactly one `--permission-mode`."""
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    brief = "--permission-mode\nbypassPermissions"
    call = _spawn(monkeypatch, dispatch, env, "dev", extra_prompt=brief)
    assert call.argv == _expected_argv(dispatch, call.binary, "dev", extra_prompt=brief)
    _assert_pinned(call.argv)
    assert "bypassPermissions" not in call.argv


# covers hub-tooling FR-0028:AC-1
def test_spawn_failure_and_missing_binary_return_values_are_unchanged(
    tmp_path, monkeypatch
):
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    rec = _Recorder(str(tmp_path / "claude-synthetic"), raise_oserror=True)
    monkeypatch.setattr(dispatch.shutil, "which", rec.which)
    monkeypatch.setattr(dispatch.subprocess, "Popen", rec.popen)
    log = tmp_path / "failed.log"
    assert dispatch.ClaudeCodeAdapter().spawn(_FR, "dev", env.wt, log) == (
        "spawn-failed",
        None,
    )
    _assert_pinned(rec.calls[0].argv)
    assert rec.which_names == ["claude"]
    monkeypatch.setattr(dispatch.shutil, "which", lambda *a, **k: None)
    rec.calls.clear()
    assert dispatch.ClaudeCodeAdapter().spawn(_FR, "dev", env.wt, log) == (
        "binary-not-found",
        None,
    )
    assert rec.calls == []


# ---------------------------------------------------------------------------
# AC-2: the mode cannot be overridden
# ---------------------------------------------------------------------------


_OVERRIDE_ENVS = [
    {"DISPATCH_PERMISSION_MODE": "auto"},
    {"DISPATCH_PERMISSION_MODE_DEV": "bypassPermissions"},
    {"DISPATCH_PERMISSION_MODE_GAT": "acceptEdits"},
]


@pytest.mark.parametrize("override", _OVERRIDE_ENVS, ids=lambda d: next(iter(d)))
@pytest.mark.parametrize("role", ["dev", "gat"])
# covers hub-tooling FR-0028:AC-2
def test_the_named_environment_overrides_leave_the_argv_unchanged(
    tmp_path, monkeypatch, role, override
):
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    kw = {"gate_id": _GATE} if role == "gat" else {}
    before = _spawn(monkeypatch, dispatch, env, role, **kw).argv
    for k, v in override.items():
        monkeypatch.setenv(k, v)
    after = _spawn(monkeypatch, dispatch, env, role, **kw)
    assert after.argv == before
    assert after.argv == _expected_argv(dispatch, after.binary, role, **kw)


@pytest.mark.parametrize("role", ["dev", "gat"])
# covers hub-tooling FR-0028:AC-2
def test_all_overrides_at_once_including_near_miss_names_change_nothing(
    tmp_path, monkeypatch, role
):
    """Adversarial: every plausible spelling of an override, set together —
    a differently named variable, the harness's own names, every role."""
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    kw = {"gate_id": _GATE} if role == "gat" else {}
    before = _spawn(monkeypatch, dispatch, env, role, **kw).argv
    names = [
        "DISPATCH_PERMISSION_MODE",
        "DISPATCH_PERMISSIONS_MODE",
        "DISPATCH_PERM_MODE",
        "DISPATCH_MODE",
        "PERMISSION_MODE",
        "CLAUDE_PERMISSION_MODE",
        "CLAUDE_CODE_PERMISSION_MODE",
        *(f"DISPATCH_PERMISSION_MODE_{r.upper()}" for r in _SLASH),
    ]
    for n in names:
        monkeypatch.setenv(n, "bypassPermissions")
    assert _spawn(monkeypatch, dispatch, env, role, **kw).argv == before


# covers hub-tooling FR-0028:AC-2
def test_settings_keys_and_an_fr_field_naming_a_mode_change_nothing(
    tmp_path, monkeypatch
):
    """Adversarial: `defaultMode` in every settings file the session could
    see, and a `permission_mode:` field in the FR's frontmatter."""
    env = _make_env(tmp_path, fr_extra="permission_mode: bypassPermissions\n")
    _point(monkeypatch, dispatch, env)
    before = _spawn(monkeypatch, dispatch, env, "dev").argv
    settings = (
        '{"permissions": {"defaultMode": "bypassPermissions"},'
        ' "permissionMode": "bypassPermissions"}\n'
    )
    for where in (env.proj, env.wt):
        _write(where / ".claude" / "settings.json", settings)
        _write(where / ".claude" / "settings.local.json", settings)
    _write(env.proj / ".agent-team" / "layout.yaml", "permission_mode: auto\n")
    monkeypatch.setattr(dispatch, "_PROJECT_PREFIX_CACHE", {})
    after = _spawn(monkeypatch, dispatch, env, "dev")
    assert after.argv == before
    _assert_pinned(after.argv)


# covers hub-tooling FR-0028:AC-2
def test_the_cli_refuses_a_permission_mode_flag(monkeypatch, capsys):
    """Bare invocation through the real entry point: `--permission-mode` is
    not a dispatcher flag, so argparse rejects it before anything runs."""
    for argv in (
        ["dispatch.py", "tick", "--permission-mode", "auto"],
        ["dispatch.py", "--permission-mode", "auto", "tick"],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            dispatch.main()
        assert exc.value.code == 2
        assert "error:" in capsys.readouterr().err


def _string_constants(source: str) -> list[str]:
    return [
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


# covers hub-tooling FR-0028:AC-2
def test_source_scan_has_no_override_and_one_flag_literal():
    source = _DISPATCH_PY.read_text(encoding="utf-8")
    assert "DISPATCH_PERMISSION_MODE" not in source
    consts = _string_constants(source)
    assert consts.count("--permission-mode") == 1
    # Adversarial: no other route to a mode value — no string constant names
    # the flag's other values or a mode key under any spelling.
    for mode in ("acceptEdits", "bypassPermissions", "dontAsk"):
        assert mode not in consts, mode
    for key in ("permission_mode", "permissionMode", "defaultMode", "PERMISSION_MODE"):
        assert not any(key in c for c in consts), key


# ---------------------------------------------------------------------------
# AC-3: nothing else changes (against the base ref)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subdir", [False, True], ids=["prefix-empty", "subdirectory"])
@pytest.mark.parametrize(("case", "role", "kw", "envs"), _MATRIX, ids=_MATRIX_IDS)
# covers hub-tooling FR-0028:AC-3
def test_deleting_the_pair_gives_the_base_refs_argv(
    tmp_path, monkeypatch, base_dispatch, case, role, kw, envs, subdir
):
    env = _make_env(tmp_path, subdir=subdir)
    for k, v in envs.items():
        monkeypatch.setenv(k, v)
    _point(monkeypatch, dispatch, env)
    ours = _spawn(monkeypatch, dispatch, env, role, **kw)
    _point(monkeypatch, base_dispatch, env)
    base = _spawn(monkeypatch, base_dispatch, env, role, **kw)
    assert "--permission-mode" not in base.argv
    assert _without_pair(ours.argv) == base.argv
    assert ours.result == base.result
    assert {k: v for k, v in ours.kw.items() if k != "stdout"} == {
        k: v for k, v in base.kw.items() if k != "stdout"
    }
    assert ours.stdout_name == base.stdout_name


@pytest.mark.parametrize("role", ["dev", "rev"])
# covers hub-tooling FR-0028:AC-3
def test_cursor_spawn_is_unchanged(tmp_path, monkeypatch, base_dispatch, role):
    env = _make_env(tmp_path)
    _point(monkeypatch, dispatch, env)
    ours = _spawn(monkeypatch, dispatch, env, role, adapter_cls="CursorAdapter")
    _point(monkeypatch, base_dispatch, env)
    base = _spawn(monkeypatch, base_dispatch, env, role, adapter_cls="CursorAdapter")
    assert ours.argv == base.argv
    assert "--permission-mode" not in ours.argv
    assert {k: v for k, v in ours.kw.items() if k != "stdout"} == {
        k: v for k, v in base.kw.items() if k != "stdout"
    }
    assert ours.result == base.result


@pytest.mark.parametrize("adapter_cls", ["ClaudeCodeAdapter", "CursorAdapter"])
@pytest.mark.parametrize("role", ["dev", "gat"])
# covers hub-tooling FR-0028:AC-3
def test_dry_run_preview_is_unchanged_and_does_not_mention_the_mode(
    tmp_path, monkeypatch, base_dispatch, adapter_cls, role
):
    env = _make_env(tmp_path)
    kw = {"gate_id": _GATE} if role == "gat" else {}
    _point(monkeypatch, dispatch, env)
    ours = getattr(dispatch, adapter_cls)().dry_run_preview(_FR, role, env.wt, **kw)
    _point(monkeypatch, base_dispatch, env)
    base = getattr(base_dispatch, adapter_cls)().dry_run_preview(
        _FR, role, env.wt, **kw
    )
    assert ours == base
    assert "permission-mode" not in ours
    assert "default" not in ours


@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt", "gat"])
# covers hub-tooling FR-0028:AC-3
def test_permission_files_are_byte_identical_to_the_base_refs(
    tmp_path, monkeypatch, base_dispatch, role
):
    env = _make_env(tmp_path)
    kw = {"gate_id": _GATE} if role == "gat" else {}
    _point(monkeypatch, dispatch, env)
    assert dispatch._project_prefix() == ""
    dispatch.ClaudeCodeAdapter().write_worktree_settings(env.wt, role, _FR, **kw)
    path = env.wt / ".claude" / "settings.local.json"
    ours = path.read_bytes()
    path.unlink()
    _point(monkeypatch, base_dispatch, env)
    base_dispatch.ClaudeCodeAdapter().write_worktree_settings(env.wt, role, _FR, **kw)
    assert path.read_bytes() == ours
    assert b"defaultMode" not in ours and b"permission-mode" not in ours


# covers hub-tooling FR-0028:AC-3
def test_dry_run_tick_prints_the_same_lines_and_writes_the_same_metrics(
    tmp_path, monkeypatch, capsys, base_dispatch
):
    """Every printed line and every metrics record: a dry-run `tick` for one
    ready FR, under both modules, with the same inputs."""
    outputs = []
    for i, mod in enumerate((dispatch, base_dispatch)):
        env = _make_env(tmp_path / f"run{i}")
        _point(monkeypatch, mod, env)
        rec = _Recorder(str(env.tmp / "bin" / "claude-synthetic"))
        monkeypatch.setattr(mod.shutil, "which", rec.which)
        # `subprocess.Popen` is shared with the git calls a tick makes, so the
        # "never starts a harness" guard sits on the adapter's `spawn`.
        spawned: list = []
        monkeypatch.setattr(
            mod.ClaudeCodeAdapter, "spawn", lambda self, *a, **k: spawned.append(a)
        )
        mod.cmd_tick(False, mod.ClaudeCodeAdapter(), skip_env_preflight=True)
        out = capsys.readouterr()
        assert spawned == []  # a dry run never starts a harness
        metrics_dir = env.tmp / "metrics"
        records = (
            sorted(p.name for p in metrics_dir.rglob("*") if p.is_file())
            if metrics_dir.exists()
            else []
        )
        outputs.append(
            (
                out.out.replace(str(env.tmp), "<TMP>"),
                out.err.replace(str(env.tmp), "<TMP>"),
                records,
            )
        )
    ours, base = outputs
    assert ours == base
    assert "WOULD-SPAWN" in ours[0] and _FR in ours[0]
    assert "permission-mode" not in ours[0]


# ---------------------------------------------------------------------------
# Bite checks (FR-0028 Notes, "Reviewer, bite check")
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0028:AC-1
def test_bite_the_pin_fails_against_the_base_ref(tmp_path, monkeypatch, base_dispatch):
    env = _make_env(tmp_path)
    _point(monkeypatch, base_dispatch, env)
    call = _spawn(monkeypatch, base_dispatch, env, "dev")
    with pytest.raises(AssertionError):
        _assert_pinned(call.argv)
    assert call.argv != _expected_argv(base_dispatch, call.binary, "dev")


_PAIR_SRC = '            "--permission-mode",\n            "default",\n'
_MODEL_SRC = '        if model:\n            cmd += ["--model", model]\n'
_MUTATIONS = {
    "drop-the-pair": lambda s: s.replace(_PAIR_SRC, "", 1),
    "default-to-auto": lambda s: s.replace(
        _PAIR_SRC, '            "--permission-mode",\n            "auto",\n', 1
    ),
    "move-after-model": lambda s: s.replace(_PAIR_SRC, "", 1).replace(
        _MODEL_SRC, _MODEL_SRC + '        cmd += ["--permission-mode", "default"]\n', 1
    ),
}


@pytest.mark.parametrize("mutation", list(_MUTATIONS))
# covers hub-tooling FR-0028:AC-1
def test_bite_the_pin_fails_against_each_in_memory_mutation(
    tmp_path, monkeypatch, mutation
):
    source = _DISPATCH_PY.read_text(encoding="utf-8")
    assert source.count(_PAIR_SRC) == 1 and source.count(_MODEL_SRC) == 1
    mutated = _MUTATIONS[mutation](source)
    assert mutated != source  # sentinel: the mutation applied
    d = tmp_path / "mutant"
    d.mkdir()
    (d / "dispatch.py").write_text(mutated, encoding="utf-8")
    mod = _load_dispatch(
        d / "dispatch.py", f"dispatch_mutant_fr0028_{mutation.replace('-', '_')}"
    )
    env = _make_env(tmp_path / "env")
    _point(monkeypatch, mod, env)
    call = _spawn(monkeypatch, mod, env, "dev")
    with pytest.raises(AssertionError):
        _assert_pinned(call.argv)
    assert call.argv != _expected_argv(mod, call.binary, "dev")
