"""Reviewer tests for FR-0016: Windows text I/O hardening in the dispatcher
scripts.

- AC-1: every text-mode subprocess read in `dispatch.py`, `metrics_log.py`,
  `spec_footprint.py` and `env_preflight.py` passes `encoding="utf-8"` and
  `errors="replace"`, and an AST guard keeps it so.
- AC-2: `_git_capture` never reports a capture with no output object as a
  success, so FR-0013 AC-6's `--allow-crossing` check refuses.
- AC-3: the deploy gate, the indexer and pytest run with
  `PYTHONIOENCODING=utf-8` in a copy of `os.environ`.
- AC-4: the branch-read paths survive `”`, `←` and an invalid byte.
- AC-5: the two committed files the dispatcher writes are LF.
- AC-6: nothing else changes.

How the guard treats kwargs it cannot see (AC-1). A subprocess-shaped call
(`run`, `Popen`, `check_output`, `check_call`, `call`, including an injected
`run` seam) that spreads `**kwargs` or `*args` is a violation outright: the
guard cannot prove the spread carries the two keywords, so a later FR must
pass them explicitly. A dict literal that sets `"text"` or
`"universal_newlines"` (kwargs built in a dict) must carry `"encoding":
"utf-8"` and `"errors": "replace"` itself. `dict(text=True, ...)` is a call
and falls under the main rule. A non-constant `text=` value counts as text
mode. `encoding=` or `errors=` on a subprocess-shaped call implies text mode,
which is how the two pre-existing `encoding="utf-8"` calls are caught.

Windows emulation. On Windows a text-mode `subprocess.run` with no
`encoding=` decodes with the locale codec (cp1252) in a reader thread; a
decode failure there leaves `stdout`/`stderr` as `None` with return code 0.
On POSIX the same failure raises in the caller instead. `_windows_run`
reproduces the Windows behaviour on every host: it runs the real command in
bytes mode, then decodes with the caller's `encoding=`/`errors=` if given,
else cp1252 strict, yielding `None` on failure. A call that passes
`encoding="utf-8", errors="replace"` is therefore decoded exactly as the
real `subprocess` would. That makes every bite check deterministic on
Linux CI; the native bite checks additionally run unshimmed when the host
locale codec cannot decode `”`.

The "before" side of every bite check is `d3d780c` (this FR's base) and, for
the AC-1 guard, also `a8889df` (the FR's grounding commit). Every
"unchanged against base" check compares two fixed commits, `d3d780c` and
`0782744` (the maintainer's tip), never the live checkout. Inside a
bootstrapped project those objects do not exist and those checks skip.
Behaviour tests drive the live `dispatch`.

Coverage annotations are written `# covers hub-tooling FR-0016:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_finalize.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import ast
import codecs
import functools
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "windows-text-io"
_GROUNDING_REF = "a8889df"  # the FR's grounding read (41 unencoded calls)
_PRE_REF = "d3d780c"  # this FR's base
_POST_REF = "0782744"  # the maintainer's tip: the "after" side of every pin
_FR = "FR-0001"
_GUARDED = ("dispatch.py", "metrics_log.py", "spec_footprint.py", "env_preflight.py")
_NON_CP1252 = "” ←"  # right double quote, leftwards arrow

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_REAL_RUN = subprocess.run  # captured before any test patches `subprocess.run`
_REAL_WRITE_TEXT = pathlib.Path.write_text


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0016")


@functools.lru_cache(maxsize=32)
def _git_show(ref: str, rel: str) -> bytes | None:
    proc = _REAL_RUN(
        ["git", "-C", str(_TEMPLATE_DIR.parent), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _source_at(ref: str, name: str) -> str:
    src = _git_show(ref, f"template/scripts/{name}")
    if src is None:
        pytest.skip(f"{name} at {ref} not reachable")
    return src.decode("utf-8")


_SNAPSHOT_SIBLINGS = ("env_preflight", "spec_footprint", "stack_profile")


def _load_snapshot(ref: str, tmp_path_factory, name: str):
    """`dispatch.py` and its siblings exactly as at `ref`, loaded as an
    isolated module; skips when `ref` is not reachable."""
    files = {}
    for mod in ("dispatch", *_SNAPSHOT_SIBLINGS):
        src = _git_show(ref, f"template/scripts/{mod}.py")
        if src is None:
            pytest.skip(f"{mod}.py at {ref} not reachable")
        files[mod] = src
    d = tmp_path_factory.mktemp(f"fr0016_{ref}_scripts")
    for mod, src in files.items():
        (d / f"{mod}.py").write_bytes(src)
    saved = {n: sys.modules.pop(n) for n in _SNAPSHOT_SIBLINGS if n in sys.modules}
    sys.path.insert(0, str(d))
    try:
        return _load_dispatch(d / "dispatch.py", name)
    finally:
        sys.path.remove(str(d))
        for n in _SNAPSHOT_SIBLINGS:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


@pytest.fixture(scope="session")
def pre(tmp_path_factory):
    """The pre-FR dispatcher (`d3d780c`)."""
    return _load_snapshot(_PRE_REF, tmp_path_factory, "dispatch_pre_fr0016")


@pytest.fixture(scope="session")
def post(tmp_path_factory):
    """The maintainer's tip (`0782744`), for fixed-commit identity checks."""
    return _load_snapshot(_POST_REF, tmp_path_factory, "dispatch_post_fr0016")


def _host_locale_breaks_on_non_cp1252() -> bool:
    enc = __import__("locale").getpreferredencoding(False)
    try:
        "”".encode().decode(enc)
        "←".encode(enc)
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
        return True
    return False


_skip_unless_cp1252 = pytest.mark.skipif(
    not _host_locale_breaks_on_non_cp1252() or sys.flags.utf8_mode,
    reason="host locale codec decodes and encodes UTF-8; the native bite is moot",
)
# The pre-FR code's decode failure happens in subprocess's reader thread; that
# thread's traceback is the very bug being demonstrated, not test noise.
_quiet_reader_thread = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)


def _native_bite(fn):
    return _quiet_reader_thread(_skip_unless_cp1252(fn))


# ---------------------------------------------------------------------------
# Windows emulation: decode a real child's bytes the way Windows would
# ---------------------------------------------------------------------------


def _decode_like_windows(data: bytes | None, kw: dict) -> str | bytes | None:
    if data is None:
        return None
    text_mode = bool(
        kw.get("text")
        or kw.get("universal_newlines")
        or kw.get("encoding")
        or kw.get("errors")
    )
    if not text_mode:
        return data
    enc = kw.get("encoding") or "cp1252"
    try:
        text = data.decode(enc, kw.get("errors") or "strict")
    except UnicodeDecodeError:
        return None  # the reader thread died; the attribute stays None
    return text.replace("\r\n", "\n").replace("\r", "\n")


_TEXT_KW = ("text", "universal_newlines", "encoding", "errors")


def _windows_run(cmd, *args, **kw):
    """`subprocess.run` as a cp1252 Windows host behaves, on every host."""
    decode_kw = {k: kw.pop(k) for k in _TEXT_KW if k in kw}
    check = kw.pop("check", False)
    if isinstance(kw.get("input"), str):
        kw["input"] = kw["input"].encode(decode_kw.get("encoding") or "cp1252")
    proc = _REAL_RUN(cmd, *args, **kw)
    out = subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        _decode_like_windows(proc.stdout, decode_kw),
        _decode_like_windows(proc.stderr, decode_kw),
    )
    if check and out.returncode != 0:
        raise subprocess.CalledProcessError(
            out.returncode, out.args, out.stdout, out.stderr
        )
    return out


def _canned_run(rows):
    """A `subprocess.run` double: the first row whose predicate matches the
    argv answers with canned *bytes*, decoded per the call's own kwargs the
    way Windows would (so the double exercises the encoding keywords rather
    than bypassing them). Unmatched calls run for real."""
    calls: list[tuple[list[str], dict]] = []

    def run(cmd, *args, **kw):
        calls.append((list(cmd), dict(kw)))
        for pred, rc, out, err in rows:
            if pred(list(cmd)):
                return subprocess.CompletedProcess(
                    list(cmd),
                    rc,
                    _decode_like_windows(out, kw),
                    _decode_like_windows(err, kw),
                )
        return _REAL_RUN(cmd, *args, **kw)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _crlf_write_text(self, data, encoding=None, errors=None, newline=None):
    """`Path.write_text` as Windows translates it when `newline=` is omitted."""
    if newline is None:
        return _REAL_WRITE_TEXT(
            self,
            data.replace("\n", "\r\n"),
            encoding=encoding,
            errors=errors,
            newline="",
        )
    return _REAL_WRITE_TEXT(
        self, data, encoding=encoding, errors=errors, newline=newline
    )


# ---------------------------------------------------------------------------
# Real-git fixture
# ---------------------------------------------------------------------------


def _spec_md(
    fr_id: str = _FR,
    title: str = "Synthetic",
    status: str = "ready",
    owns: tuple[str, ...] = ("src/**",),
) -> str:
    owns_yaml = "[" + ", ".join(f'"{o}"' for o in owns) + "]"
    return f"""---
id: {fr_id}
title: {title}
status: {status}
owner: architect
depends_on: []
tags: []
owns: {owns_yaml}
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

## Changelog

- 2026-01-01: created.
"""


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = _REAL_RUN(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check:
        assert proc.returncode == 0, (
            f"git {' '.join(args)}: {proc.stderr or proc.stdout}"
        )
    return (proc.stdout or "").strip()


def _git_bytes(cwd: Path, *args: str) -> bytes:
    proc = _REAL_RUN(["git", "-C", str(cwd), *args], capture_output=True, check=True)
    return proc.stdout


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)
    _write(repo / "specs" / f"{_FR}-synthetic.md", _spec_md())
    _write(
        repo / ".gitignore",
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\n",
    )
    _write(repo / "README.md", "synthetic\n")
    _write(repo / ".claude" / "commands" / "synthetic.md", "line one\nline two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, bare


def _worktree(repo: Path, role: str, base: str = "main") -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{_FR}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{_FR}", str(wt), base)
    return wt


def _commit(wt: Path, rel: str, content: str | bytes, msg: str) -> str:
    _write(wt / rel, content)
    _git(wt, "add", "--", rel)
    _git(wt, "commit", "-q", "-m", msg)
    return _git(wt, "rev-parse", "HEAD")


def _branch_commit(repo: Path, branch: str, rel: str, content: bytes) -> None:
    """Commit `rel` onto a new `branch` off main without a worktree."""
    blob = (
        _REAL_RUN(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=content,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    idx = repo / ".git" / "fr0016-index"
    env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
    for argv in (
        ["read-tree", "main"],
        ["update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}"],
    ):
        _REAL_RUN(["git", "-C", str(repo), *argv], env=env, check=True)
    tree = (
        _REAL_RUN(
            ["git", "-C", str(repo), "write-tree"],
            env=env,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    idx.unlink()
    sha = (
        _REAL_RUN(
            ["git", "-C", str(repo), "commit-tree", tree, "-p", "main", "-m", "branch"],
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    _git(repo, "branch", branch, sha)


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


class _Env:
    def __init__(self, repo: Path, bare: Path) -> None:
        self.repo = repo
        self.bare = bare
        self.gh: list[list[str]] = []

    def bare_sha(self, branch: str) -> str | None:
        return (
            _git(
                self.bare,
                "rev-parse",
                "--verify",
                "-q",
                f"refs/heads/{branch}",
                check=False,
            )
            or None
        )


def _point(monkeypatch, mod, repo: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    monkeypatch.setattr(mod, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", repo / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", repo / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", repo / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(mod, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (repo / "_dispatch").mkdir(exist_ok=True)


def _route(monkeypatch, env: _Env, windows: bool = False, content_diff_none=False):
    """Intercept `gh` by intent; git runs for real (optionally through the
    Windows emulation). `content_diff_none` answers FR-0013 AC-6's content
    diff (the `--ignore-all-space` diff) with return code 0 and no output
    object, as a failed decode on Windows does."""

    def routed(cmd, *a, **k):
        cmd = list(cmd)
        if cmd and cmd[0] == "gh":
            env.gh.append(cmd)
            if cmd[1:3] == ["pr", "create"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="https://github.com/synthetic/repo/pull/7\n",
                    stderr="",
                )
            if cmd[1:3] == ["pr", "list"]:
                return SimpleNamespace(returncode=0, stdout="[]", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if content_diff_none and "diff" in cmd and "--ignore-all-space" in cmd:
            return subprocess.CompletedProcess(cmd, 0, None, "")
        return (_windows_run if windows else _REAL_RUN)(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", routed)


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, repo, tmp_path)
    return _Env(repo, bare)


def _finalize(mod, role: str, apply: bool = True, **kw) -> int:
    return mod.cmd_finalize(_FR, role, apply=apply, draft=True, adapter=None, **kw)


# ---------------------------------------------------------------------------
# AC-1: the AST guard
# ---------------------------------------------------------------------------

_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _func_tail(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _const(node: ast.AST | None):
    return node.value if isinstance(node, ast.Constant) else _MISSING


_MISSING = object()


def _text_flag_on(value: ast.AST | None) -> bool:
    if value is None:
        return False
    v = _const(value)
    return True if v is _MISSING else bool(v)


def encoding_violations(source: str, filename: str) -> tuple[list[str], int]:
    """(violations as `file:line: reason`, number of text-mode calls checked)."""
    tree = ast.parse(source)
    violations: list[str] = []
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {
                k.value: v
                for k, v in zip(node.keys, node.values)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if any(_text_flag_on(keys.get(f)) for f in ("text", "universal_newlines")):
                checked += 1
                if (
                    _const(keys.get("encoding")) != "utf-8"
                    or _const(keys.get("errors")) != "replace"
                ):
                    violations.append(
                        f"{filename}:{node.lineno}: kwargs dict sets text mode without "
                        'encoding="utf-8", errors="replace"'
                    )
            continue
        if not isinstance(node, ast.Call):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg is not None}
        spread = any(k.arg is None for k in node.keywords) or any(
            isinstance(a, ast.Starred) for a in node.args
        )
        subprocess_shaped = _func_tail(node) in _SUBPROCESS_FUNCS
        text_mode = any(
            _text_flag_on(kws.get(f)) for f in ("text", "universal_newlines")
        )
        if subprocess_shaped and ("encoding" in kws or "errors" in kws):
            text_mode = True
        if subprocess_shaped and spread:
            violations.append(
                f"{filename}:{node.lineno}: {_func_tail(node)}(...) spreads *args/**kwargs; "
                "pass encoding= and errors= explicitly"
            )
            continue
        if not text_mode:
            continue
        checked += 1
        missing = []
        if _const(kws.get("encoding")) != "utf-8":
            missing.append('encoding="utf-8"')
        if _const(kws.get("errors")) != "replace":
            missing.append('errors="replace"')
        if missing:
            violations.append(
                f"{filename}:{node.lineno}: text-mode call lacks {', '.join(missing)}"
            )
    return violations, checked


def _live_source(name: str) -> str:
    return (_SCRIPTS_DIR / name).read_text(encoding="utf-8")


# covers hub-tooling FR-0016:AC-1
@pytest.mark.parametrize("name", _GUARDED)
def test_guard_every_text_mode_call_in_the_four_files_decodes_utf8_with_replace(name):
    violations, checked = encoding_violations(_live_source(name), name)
    assert violations == [], "\n".join(violations)
    assert checked >= 1  # the guard is not vacuous for any of the four files


# covers hub-tooling FR-0016:AC-1
def test_guard_counts_the_43_sites_the_maintainer_claims_at_the_fixed_tip():
    per_file = {}
    for name in _GUARDED:
        v, n = encoding_violations(_source_at(_POST_REF, name), name)
        assert v == [], v
        per_file[name] = n
    assert per_file == {
        "dispatch.py": 39,
        "metrics_log.py": 1,
        "spec_footprint.py": 1,
        "env_preflight.py": 2,
    }


# covers hub-tooling FR-0016:AC-1
@pytest.mark.parametrize("ref", [_GROUNDING_REF, _PRE_REF])
@pytest.mark.parametrize("name", _GUARDED)
def test_guard_bites_on_the_pre_fr_files(ref, name):
    """Bite: every one of the four files fails the guard before this FR."""
    violations, _ = encoding_violations(_source_at(ref, name), name)
    assert violations, f"{name}@{ref} unexpectedly passes the guard"
    assert all(
        v.startswith(f"{name}:") and v.split(":")[1].isdigit() for v in violations
    )


# covers hub-tooling FR-0016:AC-1
@pytest.mark.parametrize("name", _GUARDED)
@pytest.mark.parametrize("kwarg", ['encoding="utf-8",', 'errors="replace",'])
def test_guard_catches_one_removed_keyword_and_names_its_line(name, kwarg):
    """Adversarial mutation of a copy of the live file: drop one keyword
    from one call; the guard fails and names that call's file and line."""
    lines = _live_source(name).splitlines(keepends=True)
    idx = next(i for i, ln in enumerate(lines) if ln.strip() == kwarg)
    mutated = "".join(lines[:idx] + lines[idx + 1 :])
    violations, _ = encoding_violations(mutated, name)
    assert len(violations) == 1, violations
    call_line = int(violations[0].split(":")[1])
    assert call_line <= idx + 1 and name in violations[0]
    assert kwarg.rstrip(",") in violations[0]


# covers hub-tooling FR-0016:AC-1
@pytest.mark.parametrize(
    "snippet, expect",
    [
        ('subprocess.run(a, text=True, encoding="utf-8", errors="replace")', 0),
        ('subprocess.run(a, text=True, encoding="utf-8", errors="strict")', 1),
        ('subprocess.run(a, text=True, encoding="cp1252", errors="replace")', 1),
        ('subprocess.run(a, universal_newlines=True, encoding="utf-8")', 1),
        ("subprocess.run(a, text=flag)", 1),
        ('run(a, encoding="utf-8")', 1),  # the pre-FR REVIEW.md shape
        ("subprocess.run(a, text=False)", 0),
        ("subprocess.run(a, capture_output=True)", 0),
        ("subprocess.run(a, **kw)", 1),
        ("subprocess.Popen(*argv)", 1),
        ('kw = {"text": True, "encoding": "utf-8"}', 1),
        ('kw = {"text": True, "encoding": "utf-8", "errors": "replace"}', 0),
        ("kw = dict(text=True)", 1),
        ('p.read_text(encoding="utf-8")', 0),
    ],
)
def test_guard_rules_on_synthetic_shapes(snippet, expect):
    violations, _ = encoding_violations(snippet + "\n", "synthetic.py")
    assert len(violations) == expect, violations


# covers hub-tooling FR-0016:AC-1
def test_ascii_output_decodes_identically_with_and_without_the_keywords(tmp_path):
    """Behaviour on ASCII output is byte-identical: a real child's ASCII
    stdout (with CRLF) reads the same under locale and utf-8/replace."""
    child = tmp_path / "child.py"
    child.write_bytes(
        b"import sys\nsys.stdout.buffer.write(b'ok line\\r\\nsecond\\n')\n"
    )
    a = _REAL_RUN([sys.executable, str(child)], capture_output=True, text=True)
    b = _REAL_RUN(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert a.stdout == b.stdout == "ok line\nsecond\n"


# ---------------------------------------------------------------------------
# AC-2: _git_capture never reports an undecoded capture as success
# ---------------------------------------------------------------------------


def _none_stdout(rc=0, stderr=""):
    def run(cmd, *a, **k):
        return subprocess.CompletedProcess(list(cmd), rc, None, stderr)

    return run


# covers hub-tooling FR-0016:AC-2
@pytest.mark.parametrize("stderr", ["", "warning: something"])
def test_git_capture_refuses_exit_zero_with_no_stdout(monkeypatch, tmp_path, stderr):
    monkeypatch.setattr(subprocess, "run", _none_stdout(0, stderr))
    ok, msg = dispatch._git_capture(["diff", "a...b"], tmp_path)
    assert ok is False
    assert "could not be" in msg and ("read" in msg or "decod" in msg)


# covers hub-tooling FR-0016:AC-2
def test_pre_fr_git_capture_reported_the_same_capture_as_success(
    monkeypatch, tmp_path, pre
):
    """Bite: the base reports `(True, "")`, the fail-open the FR closes."""
    monkeypatch.setattr(subprocess, "run", _none_stdout(0))
    assert pre._git_capture(["diff", "a...b"], tmp_path) == (True, "")


# covers hub-tooling FR-0016:AC-2
def test_git_capture_success_and_failure_paths_are_unchanged(env, pre):
    """Happy: decodable captures behave exactly as at the base, including an
    empty successful capture (still a success, not a refusal)."""
    for args in (
        ["rev-parse", "--abbrev-ref", "HEAD"],
        ["diff", "main...main"],  # exit 0, empty stdout
        ["rev-parse", "--verify", "no-such-ref"],  # exit != 0
        ["log", "-1", "--format=%s"],
    ):
        assert dispatch._git_capture(args, env.repo) == pre._git_capture(args, env.repo)
    assert dispatch._git_capture(["diff", "main...main"], env.repo) == (True, "")


# covers hub-tooling FR-0016:AC-2
def test_nonzero_exit_with_no_output_objects_is_still_a_plain_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 128, None, None),
    )
    assert dispatch._git_capture(["status"], tmp_path) == (False, "")


_CROSSING = ".claude/commands/**"


def _mnt_crossing(env: _Env, content: bytes) -> None:
    mnt_wt = _worktree(env.repo, "mnt")
    _write(mnt_wt / "PR_BODY.md", "# FR-0001 (mnt)\n")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    _commit(mnt_wt, ".claude/commands/synthetic.md", content, "chore: crossing")


# covers hub-tooling FR-0016:AC-2
def test_finalize_mnt_allow_crossing_refuses_when_the_content_diff_has_no_stdout(
    env, monkeypatch, capsys
):
    """Double: the crossing is really CRLF-only (content-free), so the only
    reason to refuse is the undecoded content diff."""
    _mnt_crossing(env, b"line one\r\nline two\r\n")
    _route(monkeypatch, env, content_diff_none=True)
    assert _finalize(dispatch, "mnt", apply=True, allow_crossing=[_CROSSING]) == 1
    out = capsys.readouterr().out
    errors = [e for e in _lines(out, "ERROR") if _CROSSING in e]
    assert len(errors) == 1 and "carries content" in errors[0]
    assert "CROSSING-ALLOWED" not in out
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0016:AC-2
def test_control_same_crlf_only_crossing_is_allowed_without_the_double(
    env, monkeypatch, capsys
):
    _mnt_crossing(env, b"line one\r\nline two\r\n")
    _route(monkeypatch, env)
    assert _finalize(dispatch, "mnt", apply=False, allow_crossing=[_CROSSING]) == 0
    assert len(_lines(capsys.readouterr().out, "WOULD-ALLOW-CROSSING")) == 1


# covers hub-tooling FR-0016:AC-2
def test_pre_fr_finalize_allowed_the_crossing_under_the_same_double(
    tmp_path, monkeypatch, capsys, pre
):
    """Bite: the base prints CROSSING-ALLOWED for the undecoded diff."""
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, pre, repo, tmp_path)
    e = _Env(repo, bare)
    _mnt_crossing(e, b"line one\r\nline two\r\n")
    _route(monkeypatch, e, content_diff_none=True)
    assert _finalize(pre, "mnt", apply=False, allow_crossing=[_CROSSING]) == 0
    assert len(_lines(capsys.readouterr().out, "WOULD-ALLOW-CROSSING")) == 1


_REAL_CONTENT = ("line one\nline two " + _NON_CP1252 + "\n").encode("utf-8")


# covers hub-tooling FR-0016:AC-2
@pytest.mark.parametrize("windows", [False, True], ids=["native", "windows-emulated"])
def test_real_repo_crossing_with_non_cp1252_content_is_refused_on_every_host(
    env, monkeypatch, capsys, windows
):
    """Real repository, no double on git: the control-plane diff contains
    `”` and `←`. Refused as content-carrying natively and under the cp1252
    Windows emulation."""
    _mnt_crossing(env, _REAL_CONTENT)
    _route(monkeypatch, env, windows=windows)
    assert _finalize(dispatch, "mnt", apply=True, allow_crossing=[_CROSSING]) == 1
    out = capsys.readouterr().out
    errors = [e for e in _lines(out, "ERROR") if _CROSSING in e]
    assert len(errors) == 1 and "carries content" in errors[0]
    assert "CROSSING-ALLOWED" not in out
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []


def _pre_real_crossing(tmp_path, monkeypatch, capsys, pre, windows: bool) -> str:
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, pre, repo, tmp_path)
    e = _Env(repo, bare)
    _mnt_crossing(e, _REAL_CONTENT)
    _route(monkeypatch, e, windows=windows)
    _finalize(pre, "mnt", apply=False, allow_crossing=[_CROSSING])
    return capsys.readouterr().out


# covers hub-tooling FR-0016:AC-2
def test_pre_fr_real_repo_crossing_was_allowed_on_a_cp1252_host_emulated(
    tmp_path, monkeypatch, capsys, pre
):
    """Bite (deterministic on every host): the base lets the real `”`/`←`
    control-plane edit through under the cp1252 emulation."""
    out = _pre_real_crossing(tmp_path, monkeypatch, capsys, pre, windows=True)
    assert (
        len(_lines(out, "WOULD-ALLOW-CROSSING")) == 1 and "carries content" not in out
    )


# covers hub-tooling FR-0016:AC-2
@_native_bite
def test_pre_fr_real_repo_crossing_was_allowed_natively_on_this_host(
    tmp_path, monkeypatch, capsys, pre
):
    """Bite, unshimmed, on a host whose locale codec is cp1252."""
    out = _pre_real_crossing(tmp_path, monkeypatch, capsys, pre, windows=False)
    assert len(_lines(out, "WOULD-ALLOW-CROSSING")) == 1


# ---------------------------------------------------------------------------
# AC-3: the dispatcher's Python children write UTF-8 to the pipes it reads
# ---------------------------------------------------------------------------


def _spy():
    calls: list[dict] = []

    def run(cmd, *a, **k):
        calls.append({"cmd": list(cmd), **k})
        return subprocess.CompletedProcess(list(cmd), 0, "", "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _drive_three(tmp_path: Path, monkeypatch, mod=None) -> dict[str, dict]:
    mod = mod or dispatch
    root = tmp_path / "root"
    _write(root / "scripts" / "index-specs.py", "print('x')\n")
    _write(root / "scripts" / "deploy-gate.py", "print('x')\n")
    monkeypatch.setattr(mod, "REPO_ROOT", root)
    out = {}
    for name, call in (
        (
            "_run_deploy_gate",
            lambda: mod._run_deploy_gate(
                "dev", {"METRICS_INVOKED_BY": "t", "DISPATCH_RUN_ID": "r1"}
            ),
        ),
        ("_refresh_spec_index", mod._refresh_spec_index),
        ("_collect_failing_tests", lambda: mod._collect_failing_tests(root)),
    ):
        spy = _spy()
        monkeypatch.setattr(subprocess, "run", spy)
        call()
        assert len(spy.calls) == 1, (name, spy.calls)
        out[name] = spy.calls[0]
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    return out


# covers hub-tooling FR-0016:AC-3
def test_the_three_children_get_pythonioencoding_in_a_copy_of_os_environ(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setenv("FR0016_SENTINEL", "kept")
    before = dict(os.environ)
    calls = _drive_three(tmp_path, monkeypatch)
    assert dict(os.environ) == before and "PYTHONIOENCODING" not in os.environ
    for name, kw in calls.items():
        env = kw["env"]
        assert env is not None and env is not os.environ, name
        assert env["PYTHONIOENCODING"] == "utf-8", name
        assert env["FR0016_SENTINEL"] == "kept", name
        assert kw["encoding"] == "utf-8" and kw["errors"] == "replace", name
    gate_env = calls["_run_deploy_gate"]["env"]
    assert gate_env["METRICS_INVOKED_BY"] == "t" and gate_env["DISPATCH_RUN_ID"] == "r1"


# covers hub-tooling FR-0016:AC-3
def test_a_host_pythonioencoding_is_overridden_for_the_child_and_left_alone_on_the_host(
    tmp_path, monkeypatch
):
    """Adversarial: the host already exports a cp1252 PYTHONIOENCODING; the
    children still get utf-8 and the host variable is not mutated."""
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    calls = _drive_three(tmp_path, monkeypatch)
    assert os.environ["PYTHONIOENCODING"] == "cp1252"
    for name, kw in calls.items():
        assert kw["env"]["PYTHONIOENCODING"] == "utf-8", name


# covers hub-tooling FR-0016:AC-3
def test_run_deploy_gate_without_env_extra_still_gets_the_encoding(
    tmp_path, monkeypatch
):
    """Adversarial: the base passed `env=None` when there was no
    `env_extra`; the new env must not depend on `env_extra` being set."""
    root = tmp_path / "root"
    _write(root / "scripts" / "deploy-gate.py", "print('x')\n")
    monkeypatch.setattr(dispatch, "REPO_ROOT", root)
    spy = _spy()
    monkeypatch.setattr(subprocess, "run", spy)
    dispatch._run_deploy_gate("dev")
    assert spy.calls[0]["env"]["PYTHONIOENCODING"] == "utf-8"


def _env_kw_by_function(source: str) -> list[tuple[str, str, str]]:
    """(function, call func, unparsed env= or '<none>') per call, in order."""
    out: list[tuple[str, str, str]] = []

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            name = fn
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if isinstance(child, ast.Call) and _func_tail(child) in _SUBPROCESS_FUNCS:
                env = next((k.value for k in child.keywords if k.arg == "env"), None)
                out.append(
                    (fn, _func_tail(child), ast.unparse(env) if env else "<none>")
                )
            visit(child, name)

    visit(ast.parse(source), "<module>")
    return out


# covers hub-tooling FR-0016:AC-3
def test_no_other_child_environment_changes_between_the_fixed_commits():
    """Adversarial: `env=` differs between `d3d780c` and `0782744` on exactly
    the three named calls; every agent spawn and every other child is as
    before (IDEA-0086 stays out of scope)."""
    for name in _GUARDED:
        a = _env_kw_by_function(_source_at(_PRE_REF, name))
        b = _env_kw_by_function(_source_at(_POST_REF, name))
        assert len(a) == len(b), name
        changed = {x[0] for x, y in zip(a, b) if x != y}
        expected = (
            {"_run_deploy_gate", "_refresh_spec_index", "_collect_failing_tests"}
            if name == "dispatch.py"
            else set()
        )
        assert changed == expected, (name, changed)


_CHILD_PRINTS = (
    "import sys\n"
    f"print('out {_NON_CP1252}')\n"
    f"print('err {_NON_CP1252}', file=sys.stderr)\n"
)


def _real_child_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    _write(root / "scripts" / "deploy-gate.py", _CHILD_PRINTS)
    _write(root / "scripts" / "index-specs.py", _CHILD_PRINTS)
    _write(
        root / "pytest.py",  # shadows pytest for `python -m pytest` run from root
        "import sys\n"
        f"print('FAILED tests/test_x.py::test_y[{_NON_CP1252.replace(' ', '')}] - boom')\n"
        f"print('err {_NON_CP1252}', file=sys.stderr)\n"
        "sys.exit(1)\n",
    )
    return root


def _clean_encoding_env(monkeypatch) -> None:
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)


# covers hub-tooling FR-0016:AC-3
def test_real_children_non_cp1252_output_reaches_the_dispatcher(tmp_path, monkeypatch):
    _clean_encoding_env(monkeypatch)
    root = _real_child_root(tmp_path)
    monkeypatch.setattr(dispatch, "REPO_ROOT", root)
    ok, out = dispatch._run_deploy_gate("dev")
    assert ok and f"out {_NON_CP1252}" in out and f"err {_NON_CP1252}" in out
    assert dispatch._refresh_spec_index() is True
    assert dispatch._collect_failing_tests(root) == ["tests/test_x.py::test_y[”←]"]


# covers hub-tooling FR-0016:AC-3
@_native_bite
def test_pre_fr_real_children_lost_the_output_on_this_host(tmp_path, monkeypatch, pre):
    """Bite, unshimmed: at the base the children crash writing `←` to a
    cp1252 pipe."""
    _clean_encoding_env(monkeypatch)
    root = _real_child_root(tmp_path)
    monkeypatch.setattr(pre, "REPO_ROOT", root)
    ok, out = pre._run_deploy_gate("dev")
    assert not (ok and f"out {_NON_CP1252}" in out)
    assert pre._refresh_spec_index() is False
    assert pre._collect_failing_tests(root) == []


# ---------------------------------------------------------------------------
# AC-4: branch-read paths survive non-cp1252 content
# ---------------------------------------------------------------------------

_TITLE_BYTES = (
    (_FIXTURES / "FR-0001-non-cp1252-title.md").read_bytes()
    if (_FIXTURES / "FR-0001-non-cp1252-title.md").exists()
    else None
)


def _review_scenario(env: _Env, spec: bytes) -> None:
    _branch_commit(env.repo, f"claude/dev-{_FR}", f"specs/{_FR}-synthetic.md", spec)


def _frs():
    return [{"id": _FR, "status": "ready", "gates": ()}]


# covers hub-tooling FR-0016:AC-4
@pytest.mark.parametrize("windows", [False, True], ids=["native", "windows-emulated"])
def test_tick_rev_path_reads_the_branch_status_through_a_non_cp1252_title(
    env, monkeypatch, windows
):
    assert _TITLE_BYTES is not None and "”".encode() in _TITLE_BYTES
    _review_scenario(env, _TITLE_BYTES)
    monkeypatch.setattr(subprocess, "run", _windows_run if windows else _REAL_RUN)
    assert dispatch._fr_status_on_branch(_FR, f"claude/dev-{_FR}") == "in-review"
    assert [f["id"] for f in dispatch.runnable_review_frs(_frs())] == [_FR]


# covers hub-tooling FR-0016:AC-4
@pytest.mark.parametrize("windows", [False, True], ids=["native", "windows-emulated"])
def test_invalid_byte_in_the_branch_spec_is_replaced_not_fatal(
    env, monkeypatch, windows
):
    """Adversarial: a lone 0x9D (invalid UTF-8, undefined in cp1252) in the
    title still yields the branch's status."""
    spec = _spec_md(title="Synthetic @@", status="in-review").encode("utf-8")
    spec = spec.replace(b"@@", b"\x9d \xe2\x80\x9d")
    _review_scenario(env, spec)
    monkeypatch.setattr(subprocess, "run", _windows_run if windows else _REAL_RUN)
    assert dispatch._fr_status_on_branch(_FR, f"claude/dev-{_FR}") == "in-review"
    assert [f["id"] for f in dispatch.runnable_review_frs(_frs())] == [_FR]


# covers hub-tooling FR-0016:AC-4
def test_pre_fr_tick_rev_path_crashed_under_the_cp1252_emulation(
    tmp_path, monkeypatch, pre
):
    """Bite: the Project A L61 `TypeError` at the base."""
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, pre, repo, tmp_path)
    _review_scenario(_Env(repo, bare), _TITLE_BYTES)
    monkeypatch.setattr(subprocess, "run", _windows_run)
    with pytest.raises(TypeError):
        pre.runnable_review_frs(_frs())


# covers hub-tooling FR-0016:AC-4
@_native_bite
def test_pre_fr_tick_rev_path_crashed_natively_on_this_host(tmp_path, monkeypatch, pre):
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, pre, repo, tmp_path)
    _review_scenario(_Env(repo, bare), _TITLE_BYTES)
    with pytest.raises(TypeError):
        pre.runnable_review_frs(_frs())


_PR_BODY = (
    ("# PR " + _NON_CP1252 + "\n\nbad byte: @@\n")
    .encode("utf-8")
    .replace(b"@@", b"\x9d")
)
_PR_BODY_TEXT = "# PR " + _NON_CP1252 + "\n\nbad byte: �\n"


def _pr_body_scenario(env: _Env, role: str) -> None:
    _branch_commit(env.repo, f"claude/{role}-{_FR}", "PR_BODY.md", _PR_BODY)


def _call_finalize_body(mod, role: str) -> int:
    branch = f"claude/{role}-{_FR}"
    if role == "dev":
        return mod._finalize_dev(_FR, branch, None, "synthetic/repo", True)
    return mod._finalize_oneshot(
        _FR, branch, None, "synthetic/repo", True, role, f"chore({_FR}): x"
    )


# covers hub-tooling FR-0016:AC-4
@pytest.mark.parametrize("role", ["dev", "mnt"])
@pytest.mark.parametrize("windows", [False, True], ids=["native", "windows-emulated"])
def test_pr_body_read_from_the_branch_survives_non_cp1252_content(
    env, monkeypatch, role, windows
):
    _pr_body_scenario(env, role)
    _route(monkeypatch, env, windows=windows)
    assert _call_finalize_body(dispatch, role) == 0
    body = env.repo / "_dispatch" / f"{_FR}.{role}.pr_body.md"
    assert body.read_text(encoding="utf-8") == _PR_BODY_TEXT
    create = [c for c in env.gh if c[1:3] == ["pr", "create"]]
    assert len(create) == 1 and str(body) in create[0]


# covers hub-tooling FR-0016:AC-4
@pytest.mark.parametrize("role", ["dev", "mnt"])
def test_pre_fr_pr_body_read_crashed_under_the_cp1252_emulation(
    tmp_path, monkeypatch, pre, role
):
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, pre, repo, tmp_path)
    e = _Env(repo, bare)
    _pr_body_scenario(e, role)
    _route(monkeypatch, e, windows=True)
    with pytest.raises(TypeError):
        _call_finalize_body(pre, role)


_MERGED_JSON = (
    json.dumps(
        [
            {
                "number": 7,
                "headRefName": f"claude/dev-{_FR}",
                "mergedAt": "2026-01-01T00:00:00Z",
                "mergeCommit": {"oid": "a" * 40},
                "title": "feat: " + _NON_CP1252 + " @@",
            }
        ],
        ensure_ascii=False,
    )
    .encode("utf-8")
    .replace(b"@@", b"\x9d")
)


def _gh_list(cmd):
    return cmd[:3] == ["gh", "pr", "list"] and "merged" in cmd


# covers hub-tooling FR-0016:AC-4
def test_gh_merged_prs_parses_non_cp1252_titles(monkeypatch):
    monkeypatch.setattr(dispatch, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(
        subprocess, "run", _canned_run([(_gh_list, 0, _MERGED_JSON, b"")])
    )
    rows = dispatch._gh_merged_prs()
    assert rows is not None and len(rows) == 1
    assert rows[0]["title"] == "feat: " + _NON_CP1252 + " �"
    assert rows[0]["number"] == 7


# covers hub-tooling FR-0016:AC-4
def test_pre_fr_gh_merged_prs_silently_lost_the_rows(monkeypatch, pre):
    """Bite: at the base the undecoded JSON became `[]` (no merged PRs)."""
    monkeypatch.setattr(pre, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(
        subprocess, "run", _canned_run([(_gh_list, 0, _MERGED_JSON, b"")])
    )
    assert pre._gh_merged_prs() == []


def _uv_sync(cmd):
    return len(cmd) > 1 and cmd[1] == "sync"


_UV_ERR = ("error: " + _NON_CP1252 + " @@\n").encode("utf-8").replace(b"@@", b"\x9d")


# covers hub-tooling FR-0016:AC-4
def test_uv_sync_stderr_with_non_cp1252_content_is_classified(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _canned_run([(_uv_sync, 2, b"", _UV_ERR)]))
    ok, note = dispatch._sync_dependencies(
        "uv", tmp_path / "py", tmp_path / "venv", tmp_path, tmp_path / "uv.lock", None
    )
    assert ok is False
    assert note == "lock-sync-failed:error: " + _NON_CP1252 + " �"


# covers hub-tooling FR-0016:AC-4
def test_pre_fr_uv_sync_stderr_read_crashed(tmp_path, monkeypatch, pre):
    monkeypatch.setattr(subprocess, "run", _canned_run([(_uv_sync, 2, b"", _UV_ERR)]))
    with pytest.raises(AttributeError):
        pre._sync_dependencies(
            "uv",
            tmp_path / "py",
            tmp_path / "venv",
            tmp_path,
            tmp_path / "uv.lock",
            None,
        )


# ---------------------------------------------------------------------------
# AC-5: committed files the dispatcher writes are LF
# ---------------------------------------------------------------------------


def _flip(mod, spec: Path) -> bytes:
    assert mod._flip_frontmatter_to_merged(spec, "in-review", 7, "b" * 40) is True
    return spec.read_bytes()


# covers hub-tooling FR-0016:AC-5
@pytest.mark.parametrize("windows", [False, True], ids=["native", "windows-emulated"])
@pytest.mark.parametrize("input_eol", [b"\n", b"\r\n"], ids=["lf-input", "crlf-input"])
def test_flip_frontmatter_writes_lf(tmp_path, monkeypatch, windows, input_eol):
    monkeypatch.setattr(dispatch, "_repo_nwo", lambda: "synthetic/repo")
    if windows:
        monkeypatch.setattr(pathlib.Path, "write_text", _crlf_write_text)
    spec = tmp_path / f"{_FR}-synthetic.md"
    spec.write_bytes(_spec_md(status="in-review").encode().replace(b"\n", input_eol))
    data = _flip(dispatch, spec)
    assert b"\r" not in data
    assert b"status: merged" in data and "→".encode() in data


# covers hub-tooling FR-0016:AC-5
@pytest.mark.parametrize("windows", [False, True], ids=["native", "windows-emulated"])
def test_forced_gate_banner_writes_lf(tmp_path, monkeypatch, windows):
    if windows:
        monkeypatch.setattr(pathlib.Path, "write_text", _crlf_write_text)
    evidence = tmp_path / "GATE-0001.md"
    evidence.write_bytes(b"# Gate\r\n\r\nevidence line\r\n")
    dispatch._prepend_forced_gate_banner(evidence, "operator " + _NON_CP1252)
    data = evidence.read_bytes()
    assert b"\r" not in data
    assert data.startswith("> ⚠️ Forced past red gate by operator".encode())
    assert data.endswith(b"evidence line\n")


# covers hub-tooling FR-0016:AC-5
def test_pre_fr_writers_produced_crlf_under_the_windows_translation(
    tmp_path, monkeypatch, pre
):
    """Bite: the base's two writers relied on the platform newline."""
    monkeypatch.setattr(pre, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(pathlib.Path, "write_text", _crlf_write_text)
    spec = tmp_path / f"{_FR}-synthetic.md"
    spec.write_bytes(_spec_md(status="in-review").encode())
    assert b"\r\n" in _flip(pre, spec)
    evidence = tmp_path / "GATE-0001.md"
    evidence.write_bytes(b"# Gate\n")
    pre._prepend_forced_gate_banner(evidence, "operator")
    assert b"\r\n" in evidence.read_bytes()


def _flip_and_commit(mod, env_repo: Path) -> bytes:
    spec = env_repo / "specs" / f"{_FR}-synthetic.md"
    _write(spec, _spec_md(status="in-review"))
    _write(env_repo / "specs" / "INDEX.md", "# Index\n")
    _git(env_repo, "add", "-A")
    _git(env_repo, "commit", "-q", "-m", "in-review")
    _flip(mod, spec)
    ok, note = mod._commit_spec_flip(_FR, 7, "b" * 40)
    assert ok and note == "committed", note
    return _git_bytes(env_repo, "show", f"HEAD:specs/{_FR}-synthetic.md")


# covers hub-tooling FR-0016:AC-5
def test_the_spec_the_dispatcher_commits_has_no_cr(env, monkeypatch):
    """Real repository, `core.autocrlf=false`, under the Windows write
    translation: the committed blob is LF."""
    monkeypatch.setattr(pathlib.Path, "write_text", _crlf_write_text)
    blob = _flip_and_commit(dispatch, env.repo)
    assert b"\r" not in blob and b"status: merged" in blob


# covers hub-tooling FR-0016:AC-5
def test_pre_fr_committed_a_crlf_spec(tmp_path, monkeypatch, pre):
    repo, _bare = _make_repo(tmp_path)
    _point(monkeypatch, pre, repo, tmp_path)
    monkeypatch.setattr(pathlib.Path, "write_text", _crlf_write_text)
    assert b"\r\n" in _flip_and_commit(pre, repo)


def _write_text_calls(source: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef) else fn
            if isinstance(child, ast.Call) and _func_tail(child) == "write_text":
                out.append((fn, ast.unparse(child)))
            visit(child, name)

    visit(ast.parse(source), "<module>")
    return out


# covers hub-tooling FR-0016:AC-5
def test_no_other_write_text_changes_between_the_fixed_commits():
    a = _write_text_calls(_source_at(_PRE_REF, "dispatch.py"))
    b = _write_text_calls(_source_at(_POST_REF, "dispatch.py"))
    assert len(a) == len(b)
    changed = [(x, y) for x, y in zip(a, b) if x != y]
    assert {x[0] for x, _ in changed} == {
        "_flip_frontmatter_to_merged",
        "_prepend_forced_gate_banner",
    }
    assert all(y[1] == x[1][:-1] + ", newline='\\n')" for x, y in changed)


# ---------------------------------------------------------------------------
# AC-6: nothing else changes
# ---------------------------------------------------------------------------

_AC3_FUNCS = {"_run_deploy_gate", "_refresh_spec_index", "_collect_failing_tests"}
_AC5_FUNCS = {"_flip_frontmatter_to_merged", "_prepend_forced_gate_banner"}


class _Normalise(ast.NodeTransformer):
    """Strip exactly what FR-0016 is allowed to change: docstrings, the
    encoding keywords on subprocess-shaped calls, `env=` in the three AC-3
    functions, `newline=` on the two AC-5 writers, and `_git_capture`'s body
    (AC-2)."""

    def __init__(self) -> None:
        self.fn: list[str] = ["<module>"]

    def _strip_doc(self, node):
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
        ):
            node.body = body[1:] or [ast.Pass()]

    def visit_FunctionDef(self, node):
        self._strip_doc(node)
        if node.name == "_git_capture":
            node.body = [ast.Pass()]
            return node
        self.fn.append(node.name)
        self.generic_visit(node)
        self.fn.pop()
        return node

    def visit_Module(self, node):
        self._strip_doc(node)
        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        tail = _func_tail(node)
        drop: set[str] = set()
        if tail in _SUBPROCESS_FUNCS:
            drop |= {"encoding", "errors"}
            if self.fn[-1] in _AC3_FUNCS:
                drop.add("env")
        if tail == "write_text" and self.fn[-1] in _AC5_FUNCS:
            drop.add("newline")
        node.keywords = [k for k in node.keywords if k.arg not in drop]
        return node


def _normalised(source: str) -> str:
    return ast.dump(_Normalise().visit(ast.parse(source)))


# covers hub-tooling FR-0016:AC-6
@pytest.mark.parametrize("name", _GUARDED)
def test_the_diff_is_exactly_the_permitted_surface_between_the_fixed_commits(name):
    assert _normalised(_source_at(_PRE_REF, name)) == _normalised(
        _source_at(_POST_REF, name)
    )


# covers hub-tooling FR-0016:AC-6
def test_normaliser_is_not_vacuous():
    """Adversarial: a change outside the permitted surface is detected."""
    src = _source_at(_POST_REF, "dispatch.py")
    mutated = src.replace("timeout=10,", "timeout=11,", 1)
    assert mutated != src and _normalised(mutated) != _normalised(src)
    mutated = src.replace(
        "stdin=subprocess.DEVNULL", "stdin=subprocess.DEVNULL, text=True", 1
    )
    assert _normalised(mutated) != _normalised(src)


# covers hub-tooling FR-0016:AC-6
def test_no_test_file_changed_between_the_fixed_commits():
    proc = _REAL_RUN(
        [
            "git",
            "-C",
            str(_TEMPLATE_DIR.parent),
            "diff",
            "--name-only",
            _PRE_REF,
            _POST_REF,
            "--",
            "template/tests",
            "tests",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        pytest.skip("fixed commits not reachable")
    assert proc.stdout.strip() == ""


# covers hub-tooling FR-0016:AC-6
def test_ascii_reads_are_identical_between_the_fixed_commits(
    tmp_path, monkeypatch, pre, post
):
    repo, _bare = _make_repo(tmp_path)
    _branch_commit(
        repo,
        f"claude/dev-{_FR}",
        f"specs/{_FR}-synthetic.md",
        _spec_md(status="in-review").encode(),
    )
    results = []
    for mod in (pre, post):
        _point(monkeypatch, mod, repo, tmp_path)
        results.append(
            (
                mod._fr_status_on_branch(_FR, f"claude/dev-{_FR}"),
                mod._fr_spec_committed_on_branch(_FR, f"claude/dev-{_FR}"),
                mod._on_default_branch(),
                mod._branch_head_sha("main"),
                mod._remote_url(),
                mod._git_capture(["log", "-1", "--format=%s"], repo),
                mod._git_capture(["rev-parse", "--verify", "nope"], repo),
                [f["id"] for f in mod.runnable_review_frs(_frs())],
            )
        )
    assert results[0] == results[1]
    assert results[0][0] == "in-review" and results[0][7] == [_FR]


# covers hub-tooling FR-0016:AC-6
def test_ascii_gate_output_and_exit_are_identical_between_the_fixed_commits(
    tmp_path, monkeypatch, pre, post
):
    root = tmp_path / "root"
    _write(
        root / "scripts" / "deploy-gate.py",
        "import sys\nprint('Deploy gate FAILED (stage=dev)')\n"
        "print('detail', file=sys.stderr)\nsys.exit(1)\n",
    )
    got = []
    for mod in (pre, post):
        monkeypatch.setattr(mod, "REPO_ROOT", root)
        got.append(mod._run_deploy_gate("dev", {"METRICS_INVOKED_BY": "t"}))
    assert got[0] == got[1] == (False, "Deploy gate FAILED (stage=dev)\ndetail")


# covers hub-tooling FR-0016:AC-6
def test_metrics_log_project_name_is_unchanged_for_an_ascii_repo(tmp_path, monkeypatch):
    repo, _bare = _make_repo(tmp_path)
    monkeypatch.delenv("METRICS_PROJECT", raising=False)
    names = []
    for ref in (_PRE_REF, _POST_REF):
        src = _git_show(ref, "template/scripts/metrics_log.py")
        if src is None:
            pytest.skip("fixed commits not reachable")
        d = tmp_path / f"ml_{ref}"
        d.mkdir()
        (d / "metrics_log.py").write_bytes(src)
        mod = _load_dispatch(d / "metrics_log.py", f"metrics_log_fr0016_{ref}")
        mod._PROJECT_CACHE.clear()
        names.append(mod.project_name(repo))
    assert names[0] == names[1] == "repo"


# covers hub-tooling FR-0016:AC-4
def test_fixture_is_synthetic_and_carries_the_characters():
    """The fixture spec's title is the dogfood's shape: `”` and `←`."""
    assert _TITLE_BYTES is not None
    text = _TITLE_BYTES.decode("utf-8")
    assert "”" in text and "←" in text and "status: in-review" in text
    with pytest.raises(UnicodeDecodeError):
        codecs.decode(_TITLE_BYTES, "cp1252")
