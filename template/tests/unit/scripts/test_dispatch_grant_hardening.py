"""Reviewer tests for FR-0015: control-plane paths are refused at finalize
whoever wrote them.

- AC-1: Reviewer provenance never exempts a control-plane path.
- AC-2: a `dev`/`rev`/`bkf` branch carrying a control-plane path never
  reaches a push, a review post or a PR.
- AC-3: uncommitted changes to an off-limits path refuse finalize.
- AC-4: a permission file the agent rewrote refuses finalize.
- AC-5: a malformed `owns:` is refused for `rev`, `bkf` and `mnt`.
- AC-6: nothing widens, and clean runs are byte-identical.

Harness: `dispatch.py` is loaded by path with `REPO_ROOT` / `SPECS_DIR` /
`DISPATCH_DIR` pointed at a real temporary git repository with a real bare
`origin`. `_push_branch` runs for real into the bare. Only `gh` leaves the
machine, so `subprocess.run` is wrapped to intercept `gh ...` argv, and every
git call passes through. `gh` is never invoked for real. `_gh_preflight`,
`_repo_nwo` and `ensure_dev_venv` are stubbed.

The pre-FR dispatcher the bite checks and byte-identity checks run against is
loaded from `git show 82670a5:template/scripts/*.py` (FR-0015's base). The
"after" side of every byte-identity / edit-surface pin is FR-0015's own tip,
`a7be8eb`, loaded the same way, never the live checkout, so a later FR's
legitimate edit cannot rot the pin. Inside a bootstrapped project those
objects do not exist and those checks skip.

Coverage annotations are written `# covers hub-tooling FR-0015:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_finalize.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import ast
import functools
import hashlib
import importlib.util
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_PRE_FR_REF = "82670a5"
_FR_TIP_REF = "a7be8eb"  # FR-0015's own tip: the "after" side of identity pins
_FR = "FR-0001"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_REAL_RUN = subprocess.run  # captured before any test patches `subprocess.run`


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0015")


@functools.lru_cache(maxsize=4)
def _git_show(ref: str, rel: str) -> bytes | None:
    proc = _REAL_RUN(
        ["git", "-C", str(_TEMPLATE_DIR.parent), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


# Sibling modules `dispatch.py` imports at module level. A snapshot loads its
# own copies from the same commit, so a later FR's change to one of them
# (e.g. FR-0017's `stack_profile.py`) cannot move either side of a
# comparison. `metrics_log` is deliberately shared with the live module: the
# harness monkeypatches its `METRICS_DIR`, and it is an output sink only.
_SNAPSHOT_SIBLINGS = ("env_preflight", "spec_footprint", "stack_profile")


def _load_snapshot(ref: str, tmp_path_factory, name: str):
    """`template/scripts/dispatch.py` and its siblings exactly as at `ref`,
    loaded as an isolated module; skips when `ref` is not reachable (e.g.
    inside a bootstrapped project)."""
    files = {}
    for mod in ("dispatch", *_SNAPSHOT_SIBLINGS):
        src = _git_show(ref, f"template/scripts/{mod}.py")
        if src is None:
            pytest.skip(f"{mod}.py at {ref} not reachable")
        files[mod] = src
    d = tmp_path_factory.mktemp(f"fr0015_{ref}_scripts")
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
    """The pre-FR dispatcher (FR-0015's base), loaded as a second module."""
    return _load_snapshot(_PRE_FR_REF, tmp_path_factory, "dispatch_pre_fr0015")


@pytest.fixture(scope="session")
def post(tmp_path_factory):
    """FR-0015's own tip, loaded as a third module. Every "identical to the
    base" comparison is `post` vs `pre`, both fixed commits, so a later FR's
    legitimate edit to the live dispatcher cannot turn it red. Refusal and
    behaviour tests keep driving the live `dispatch`."""
    return _load_snapshot(_FR_TIP_REF, tmp_path_factory, "dispatch_post_fr0015")


# ---------------------------------------------------------------------------
# Real-git fixture: a primary repo with a bare `origin`
# ---------------------------------------------------------------------------


def _fr_md(owns: tuple[str, ...] | None = ("src/**",), fr_id: str = _FR) -> str:
    if owns is None:
        owns_line = ""
    else:
        owns_line = "owns: [" + ", ".join(json.dumps(o) for o in owns) + "]\n"
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: ready
owner: architect
depends_on: []
tags: []
{owns_line}reads: []
gates: []
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


# Control-plane files every synthetic repo tracks on `main`, so a test can
# modify, delete or add next to them.
_TRACKED = {
    "README.md": "synthetic\n",
    "src/app.py": "print('app')\n",
    "docs/notes.md": "a\nb\n",
    "scripts/deploy-gate.py": "# synthetic gate: exits 0\n",
    "scripts/index-specs.py": "# synthetic indexer\n",
    ".agent-team/roles/developer.md": "developer role\n",
    ".agent-team/roles/reviewer.md": "reviewer role\n",
    "CLAUDE.md": "working agreement\n",
}


def _make_repo(
    root: Path, owns: tuple[str, ...] | None = ("src/**",), extra: dict | None = None
) -> tuple[Path, Path]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)
    _write(repo / "specs" / f"{_FR}-synthetic.md", _fr_md(owns))
    # Mirrors template/.gitignore: the dispatcher-written settings file is NOT
    # ignored, exactly as in a bootstrapped project.
    _write(
        repo / ".gitignore",
        f"_dispatch/\n.claude/worktrees/\nPR_BODY.md\n{dispatch.VENV_DIRNAME}/\n"
        "__pycache__/\n",
    )
    for rel, content in {**_TRACKED, **(extra or {})}.items():
        _write(repo / rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = root / "origin.git"
    _git(root, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, bare


class _Env:
    def __init__(self, repo: Path, bare: Path) -> None:
        self.repo = repo
        self.bare = bare
        self.gh: list[list[str]] = []

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

    def refs(self) -> str:
        return _git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)")

    def bare_refs(self) -> str:
        return _git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)")


def _point(monkeypatch, mod, repo: Path, root: Path) -> None:
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    monkeypatch.setattr(mod, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", repo / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", repo / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", repo / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(mod, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(mod, "ensure_dev_venv", lambda wt: (True, "venv:stub"))
    monkeypatch.setattr(metrics_log, "METRICS_DIR", root / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    monkeypatch.delenv("DISPATCH_STACK_TOOLS", raising=False)
    (repo / "_dispatch").mkdir(exist_ok=True)


def _route_gh(monkeypatch, env: _Env) -> None:
    """Intercept `gh` argv only; every git (and python) call stays real."""

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

    monkeypatch.setattr(subprocess, "run", routed)


def _build_env(root: Path, monkeypatch, mod=None, **kw) -> _Env:
    repo, bare = _make_repo(root, **kw)
    _point(monkeypatch, mod or dispatch, repo, root)
    e = _Env(repo, bare)
    _route_gh(monkeypatch, e)
    return e


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    return _build_env(tmp_path, monkeypatch)


def _set_owns(env: _Env, owns: tuple[str, ...] | None) -> None:
    """Rewrite the FR's `owns:` in the primary checkout (where the dispatcher
    reads it) and commit it on `main`, before any role branch is cut."""
    _write(env.repo / "specs" / f"{_FR}-synthetic.md", _fr_md(owns))
    _git(env.repo, "add", "-A")
    _git(env.repo, "commit", "-q", "-m", "owns")
    _git(env.repo, "push", "-q", "origin", "main")


def _worktree(repo: Path, role: str, base: str = "main") -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{_FR}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{_FR}", str(wt), base)
    if role in ("dev", "mnt", "bkf"):
        _write(wt / "PR_BODY.md", f"# {_FR} ({role})\n")
    return wt


def _commit(wt: Path, rel: str, content: str | bytes, msg: str) -> str:
    _write(wt / rel, content)
    _git(wt, "add", rel)
    _git(wt, "commit", "-q", "-m", msg)
    return _git(wt, "rev-parse", "HEAD")


def _rev_log(repo: Path, text: str) -> None:
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
        {"type": "result", "subtype": "success"},
    ]
    _write(
        repo / "_dispatch" / f"{_FR}.rev.log",
        "\n".join(json.dumps(ln) for ln in lines) + "\n",
    )


def _impl_pr_record(mod, role: str = "dev", pr_number: int = 7, **extra) -> None:
    mod._save_pr_record(
        _FR,
        role,
        {
            "pr_number": pr_number,
            "pr_url": f"https://github.com/synthetic/repo/pull/{pr_number}",
            "branch": f"claude/{role}-{_FR}",
            "draft": True,
            **extra,
        },
    )


def _role_branch(env: _Env, role: str, mod=None) -> Path:
    """A clean branch for `role` carrying one legitimate commit. For `rev`:
    a dev implementation branch (pushed, with a PR record) and a Reviewer
    branch off its tip with a test and an approve verdict in the log."""
    mod = mod or dispatch
    if role == "rev":
        dev_wt = _worktree(env.repo, "dev")
        _commit(dev_wt, "src/thing.py", "print('thing')\n", "feat: impl work")
        _git(env.repo, "push", "-q", "-u", "origin", f"claude/dev-{_FR}")
        wt = _worktree(env.repo, "rev", base=f"claude/dev-{_FR}")
        _commit(wt, "tests/test_ac1.py", "# t\n", "test: reviewer tests")
        _rev_log(env.repo, "## Approve\n\nAll ACs covered.")
        _impl_pr_record(mod, "dev")
        return wt
    wt = _worktree(env.repo, role)
    rel = "tests/test_backfill.py" if role == "bkf" else "src/work.py"
    _commit(wt, rel, "print('work')\n", f"work for {role}")
    return wt


def _finalize(role: str, apply: bool = True, mod=None, **kw) -> int:
    mod = mod or dispatch
    adapter = mod.get_adapter("claude-code") if role == "rev" else None
    return mod.cmd_finalize(_FR, role, apply=apply, draft=True, adapter=adapter, **kw)


def _cli(monkeypatch, *argv: str, mod=None) -> int:
    """Drive `finalize` through the real CLI parser (`main()` reads argv)."""
    mod = mod or dispatch
    monkeypatch.setattr(sys, "argv", ["dispatch.py", *argv])
    return mod.main()


def _n(text: str, repo: Path) -> str:
    """Strip a run's temp repo path (plain and repr-escaped) from text."""
    return text.replace(repr(str(repo))[1:-1], "<r>").replace(str(repo), "<r>")


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


def _py_write(path: Path, content: str) -> None:
    """A write by a separate interpreter process — the stand-in for
    `uv run python -c`, `docker run -v`, `alembic`, a pytest fixture."""
    code = (
        "import pathlib, sys; p = pathlib.Path(sys.argv[1]); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_bytes(sys.argv[2].encode())"
    )
    proc = _REAL_RUN(
        [sys.executable, "-c", code, str(path), content],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def _wt_state(wt: Path) -> str:
    """Everything a refusal must leave as found: every file's bytes, the
    index, HEAD and status."""
    parts = [
        _git(wt, "rev-parse", "HEAD"),
        _git(wt, "status", "--porcelain", "--untracked-files=all"),
        _git(wt, "diff"),
        _git(wt, "diff", "--cached"),
    ]
    for p in sorted(wt.rglob("*")):
        if ".git" in p.relative_to(wt).parts or not p.is_file():
            continue
        parts.append(
            f"{p.relative_to(wt).as_posix()}:{hashlib.sha256(p.read_bytes()).hexdigest()}"
        )
    return "\n".join(parts)


def _no_egress(env: _Env, *branches: str) -> None:
    assert env.gh == [], env.gh
    for b in branches:
        assert env.bare_sha(b) is None, b


# ---------------------------------------------------------------------------
# AC-1: Reviewer provenance never exempts a control-plane path
# ---------------------------------------------------------------------------


def _mnt_with_reviewer_landed(env: _Env, rel: str, content: str, mod=None) -> Path:
    """A mnt branch (owns src/**) with an owned commit; a Reviewer branch
    off its tip committing `rel`; mnt fast-forwarded onto it through the
    dispatcher's own FR-0013 AC-1 step, so `ff_commits` names exactly the
    Reviewer's commit. The push inside that step is stubbed."""
    mod = mod or dispatch
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned work")
    _git(env.repo, "push", "-q", "-u", "origin", f"claude/mnt-{_FR}")
    _impl_pr_record(mod, "mnt", 9)
    rev_wt = _worktree(env.repo, "rev", base=f"claude/mnt-{_FR}")
    _commit(rev_wt, rel, content, "test: reviewer commit")
    real_push = mod._push_branch
    mod._push_branch = lambda branch: (True, "pushed (stub)")
    try:
        assert mod._ff_push_impl_onto_rev(_FR, f"claude/rev-{_FR}", apply=True) is True
    finally:
        mod._push_branch = real_push
    rec = mod._load_pr_record(_FR, "mnt")
    assert rec["ff_commits"] == [_git(env.repo, "rev-parse", f"claude/rev-{_FR}")]
    # The fixture's own ff push went to the bare only via the stub.
    _git(env.bare, "update-ref", "-d", f"refs/heads/claude/mnt-{_FR}")
    return mnt_wt


# covers hub-tooling FR-0015:AC-1
@pytest.mark.parametrize(
    "rel", ["scripts/deploy-gate.py", ".agent-team/roles/reviewer.md"]
)
def test_reviewer_landed_control_plane_path_refuses_mnt_finalize(
    env, capsys, monkeypatch, rel
):
    _mnt_with_reviewer_landed(env, rel, "reviewer rewrote this\n")
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", "mnt", "--apply")
    out = capsys.readouterr().out
    assert rc == 1, out
    lines = out.splitlines()
    errors = _lines(out, "ERROR")
    assert len(errors) == 1
    assert f"outside {_FR} `owns:`" in errors[0] and rel in errors[0]
    notes = [ln for ln in _lines(out, "NOTE") if rel in ln]
    assert len(notes) == 1
    assert "Reviewer provenance" in notes[0] and "control-plane" in notes[0]
    assert "exempt (fast-forwarded" not in out and "AC-5a" not in out
    # The one line precedes the existing footprint ERROR.
    assert lines.index(notes[0]) < lines.index(errors[0])
    _no_egress(env, f"claude/mnt-{_FR}")
    assert "pr_url" in dispatch._load_pr_record(_FR, "mnt")  # record unchanged
    assert dispatch._load_pr_record(_FR, "mnt")["pr_number"] == 9


# covers hub-tooling FR-0015:AC-1
def test_reviewer_landed_control_plane_path_bite_pre_fr_exempted_it(
    env, pre, capsys, monkeypatch, tmp_path
):
    """Bite check: the pre-FR dispatcher exempts the Reviewer-landed gate
    edit with AC-5(a)'s NOTE and would finalize."""
    _point(monkeypatch, pre, env.repo, tmp_path)
    _mnt_with_reviewer_landed(env, "scripts/deploy-gate.py", "rewritten\n", mod=pre)
    capsys.readouterr()
    assert _finalize("mnt", apply=False, mod=pre) == 0
    out = capsys.readouterr().out
    assert "scripts/deploy-gate.py exempt (fast-forwarded" in out
    assert "WOULD-FINALIZE" in out and "ERROR" not in out


# covers hub-tooling FR-0015:AC-1
def test_reviewer_landed_test_is_still_exempt_with_todays_note(
    env, capsys, monkeypatch
):
    _mnt_with_reviewer_landed(env, "tests/test_ac1.py", "# covers\n")
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", "mnt", "--apply")
    out = capsys.readouterr().out
    assert rc == 0, out
    today = (
        f"  {_FR}.mnt  NOTE         tests/test_ac1.py exempt (fast-forwarded "
        f"from claude/rev-{_FR} — AC-5a)"
    )
    assert _lines(out, "NOTE") == [today]
    assert "ERROR" not in out and "control-plane" not in out
    assert any(c[:3] == ["gh", "pr", "create"] for c in env.gh)
    assert env.bare_sha(f"claude/mnt-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/mnt-{_FR}"
    )


def _metrics_and_crossing_run(mod, root: Path, monkeypatch, capsys) -> list[str]:
    e = _build_env(root, monkeypatch, mod=mod)
    wt = _worktree(e.repo, "mnt")
    _commit(wt, "src/owned.py", "owned\n", "owned")
    _commit(wt, "specs/_metrics/2026-09.ndjson", '{"kind": "gate.run"}\n', "metrics")
    _commit(wt, "docs/notes.md", "a\r\nb\r\n", "crlf only")  # content-free crossing
    outs: list[str] = []
    for kw in (
        {"apply": False},
        {"apply": False, "allow_crossing": ["docs/**"]},
        {"apply": True, "allow_crossing": ["docs/**"]},
    ):
        rc = _finalize("mnt", mod=mod, **kw)
        outs.append(f"rc={rc}\n" + capsys.readouterr().out.replace(str(e.repo), "<r>"))
    _commit(wt, "docs/notes.md", "a\r\nb\r\nc\r\n", "real content")
    rc = _finalize("mnt", mod=mod, apply=True, allow_crossing=["docs/**"])
    outs.append(f"rc={rc}\n" + capsys.readouterr().out.replace(str(e.repo), "<r>"))
    outs.append(_n(repr(e.gh), e.repo))
    return outs


# covers hub-tooling FR-0015:AC-1
def test_metrics_exemption_and_allow_crossing_are_unchanged(
    pre, post, tmp_path, monkeypatch, capsys
):
    """AC-5(b) and FR-0013 AC-6 behave exactly as at FR-0015's base (anchored:
    FR-0015's tip vs its base)."""
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")
    new = _metrics_and_crossing_run(post, tmp_path / "new", monkeypatch, capsys)
    old = _metrics_and_crossing_run(pre, tmp_path / "old", monkeypatch, capsys)
    assert new == old
    joined = "".join(new)
    assert "AC-5b" in joined and "CROSSING-ALLOWED" in joined
    assert "carries content" in joined


# ---------------------------------------------------------------------------
# AC-2: a dev / rev / bkf branch carrying a control-plane path
# ---------------------------------------------------------------------------


def _upstream_moves(
    env: _Env, rel: str = "README.md", content: str = "upstream change\n"
) -> None:
    """origin/main gains a commit no role branch has, and local `main` stays
    behind it — so a finalize that reached AC-7 would print its WARN."""
    before = _git(env.repo, "rev-parse", "main")
    _commit(env.repo, rel, content, "upstream")
    _git(env.repo, "push", "-q", "origin", "main")
    _git(env.repo, "reset", "-q", "--hard", before)


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize(
    "role,rel",
    [
        ("dev", ".agent-team/roles/developer.md"),
        ("bkf", "CLAUDE.md"),
        ("dev", "scripts/index-specs.py"),
        ("bkf", ".agent-team/new-hook.py"),
    ],
)
def test_protected_path_on_a_dev_or_bkf_branch_is_refused_before_anything_leaves(
    env, capsys, monkeypatch, role, rel
):
    wt = _role_branch(env, role)
    _commit(wt, rel, "agent wrote this\n", "sneaky")
    _upstream_moves(env)
    refs_before = env.refs()
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", role, "--apply")
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1, out
    assert f"{_FR}.{role}" in errors[0] and rel in errors[0]
    assert "control-plane" in errors[0]
    assert "origin/main has" not in out and "REVALIDATE" not in out  # AC-7 not reached
    assert "PUSHED" not in out
    _no_egress(env, f"claude/{role}-{_FR}")
    assert dispatch._load_pr_record(_FR, role) is None
    assert env.refs() == refs_before
    assert not (metrics_log.METRICS_DIR).exists() or not any(
        "pr." in p.read_text(encoding="utf-8")
        for p in metrics_log.METRICS_DIR.glob("*.ndjson")
    )


# covers hub-tooling FR-0015:AC-2
def test_protected_path_on_a_dev_branch_bite_pre_fr_would_finalize(
    env, pre, capsys, monkeypatch, tmp_path
):
    _point(monkeypatch, pre, env.repo, tmp_path)
    wt = _role_branch(env, "dev", mod=pre)
    _commit(wt, ".agent-team/roles/developer.md", "x\n", "sneaky")
    capsys.readouterr()
    assert _finalize("dev", apply=False, mod=pre) == 0
    out = capsys.readouterr().out
    assert "WOULD-FINALIZE" in out and "ERROR" not in out and "WOULD-REFUSE" not in out


# covers hub-tooling FR-0015:AC-2
def test_reviewer_committing_the_gate_never_posts_a_review_or_fast_forwards(
    env, capsys, monkeypatch
):
    rev_wt = _role_branch(env, "rev")
    _commit(rev_wt, "scripts/deploy-gate.py", "# neutered gate\n", "test: helper")
    dev_before = _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    bare_dev_before = env.bare_sha(f"claude/dev-{_FR}")
    rev_before = _git(env.repo, "rev-parse", f"claude/rev-{_FR}")
    dev_record_before = (env.repo / "_dispatch" / f"{_FR}.dev.pr.json").read_bytes()
    state_before = _wt_state(rev_wt)
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", "rev", "--apply")
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "scripts/deploy-gate.py" in errors[0]
    assert f"{_FR}.rev" in errors[0]
    assert not any(c[:3] == ["gh", "pr", "review"] for c in env.gh)
    assert env.gh == []
    # Not fast-forwarded, locally or on origin.
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == dev_before
    assert env.bare_sha(f"claude/dev-{_FR}") == bare_dev_before
    # No REVIEW.md materialised: no dispatcher commit, nothing in the tree.
    assert _git(env.repo, "rev-parse", f"claude/rev-{_FR}") == rev_before
    assert "REVIEW.md" not in _git(
        env.repo, "ls-tree", "-r", "--name-only", f"claude/rev-{_FR}"
    )
    assert not (rev_wt / "REVIEW.md").exists()
    assert _wt_state(rev_wt) == state_before
    # No push, no PR record written or refreshed.
    assert env.bare_sha(f"claude/rev-{_FR}") is None
    assert (
        env.repo / "_dispatch" / f"{_FR}.dev.pr.json"
    ).read_bytes() == dev_record_before
    assert dispatch._load_pr_record(_FR, "rev") is None
    for tag in ("FF-PUSHED", "REVIEW-KEPT", "PUSHED", "REVIEWED"):
        assert tag not in out


# covers hub-tooling FR-0015:AC-2
def test_reviewer_committing_the_gate_bite_pre_fr_posts_and_fast_forwards(
    env, pre, capsys, monkeypatch, tmp_path
):
    _point(monkeypatch, pre, env.repo, tmp_path)
    rev_wt = _role_branch(env, "rev", mod=pre)
    _commit(rev_wt, "scripts/deploy-gate.py", "# neutered gate\n", "test: helper")
    capsys.readouterr()
    assert _finalize("rev", apply=True, mod=pre) == 0, capsys.readouterr().out
    assert any(c[:3] == ["gh", "pr", "review"] for c in env.gh)
    assert "scripts/deploy-gate.py" in _git(
        env.repo, "diff", "--name-only", "main", f"claude/dev-{_FR}"
    )


# covers hub-tooling FR-0015:AC-2
def test_reviewer_with_no_implementation_branch_diffs_against_main(
    env, capsys, monkeypatch
):
    """DEC-0017 Decision 1: no claude/dev-<FR> and no claude/mnt-<FR>, so the
    diff base is `main` — the check runs (no 'check failed' refusal) and
    still refuses the Reviewer's own protected commit."""
    rev_wt = _worktree(env.repo, "rev")  # off main
    _commit(rev_wt, "tests/test_ac1.py", "# t\n", "test: reviewer tests")
    _commit(rev_wt, ".agent-team/roles/reviewer.md", "widened\n", "test: sneaky")
    _rev_log(env.repo, "## Approve\n\nfine")
    _impl_pr_record(dispatch, "dev")
    capsys.readouterr()
    assert _finalize("rev") == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and ".agent-team/roles/reviewer.md" in errors[0]
    assert "check failed" not in out
    assert "tests/test_ac1.py" not in errors[0]
    assert env.gh == []


# covers hub-tooling FR-0015:AC-2
def test_dry_run_counts_the_staged_index_and_mutates_nothing(env, capsys, monkeypatch):
    wt = _role_branch(env, "dev")
    _write(wt / "scripts/index-specs.py", "# staged rewrite\n")
    _git(wt, "add", "scripts/index-specs.py")
    state_before, refs_before = _wt_state(wt), env.refs()
    dispatch_dir_before = sorted(p.name for p in (env.repo / "_dispatch").iterdir())
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", "dev")  # required args only
    out = capsys.readouterr().out
    assert rc == 0, out  # the exit `_finalize_commit_step`'s WOULD-REFUSE uses
    refusals = _lines(out, "WOULD-REFUSE")
    assert len(refusals) == 1 and "scripts/index-specs.py" in refusals[0]
    assert f"{_FR}.dev" in refusals[0]
    assert "ERROR" not in out and "WOULD-FINALIZE" not in out
    assert _wt_state(wt) == state_before and env.refs() == refs_before
    assert (
        sorted(p.name for p in (env.repo / "_dispatch").iterdir())
        == dispatch_dir_before
    )
    assert env.gh == []


# covers hub-tooling FR-0015:AC-2
def test_commit_step_dry_run_refusal_exit_matches_the_new_refusal(env, capsys):
    """The dry-run exit AC-2 must mirror: an empty dev branch's WOULD-REFUSE."""
    _worktree(env.repo, "dev")
    assert _finalize("dev", apply=False) == 0
    assert "WOULD-REFUSE" in capsys.readouterr().out


_GIT_USAGE = (
    "fatal: bad revision 'claude/nope...claude/dev-FR-0001'\n"
    "usage: git diff [<options>] [<commit>] [--] [<path>...]\n"
    "   or: git diff [<options>] --cached [--merge-base] [<commit>] [--] [<path>...]\n"
)


def _fail_git(monkeypatch, pred) -> list[list[str]]:
    real = dispatch._git_capture
    seen: list[list[str]] = []

    def fake(args, cwd):
        if pred(args):
            seen.append(list(args))
            return (False, _GIT_USAGE.strip())
        return real(args, cwd)

    monkeypatch.setattr(dispatch, "_git_capture", fake)
    return seen


def _is_range_diff(args: list[str]) -> bool:
    """Any `git diff` over AC-2's `<base>...<branch>` range, whatever flags it
    carries. Round 2 loosened this from the exact three-element argv: the
    test pins the behaviour (a range read that cannot run is a refusal), not
    how many reads the implementation makes or which flags it passes."""
    return bool(args) and args[0] == "diff" and any("..." in a for a in args[1:])


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_a_diff_that_cannot_run_is_a_refusal_quoting_the_first_line(
    env, capsys, monkeypatch, role
):
    _role_branch(env, role)
    seen = _fail_git(monkeypatch, _is_range_diff)
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    out = capsys.readouterr().out
    assert seen
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and f"{_FR}.{role}" in errors[0]
    assert "fatal: bad revision" in errors[0] and "usage:" not in errors[0]
    _no_egress(env, f"claude/{role}-{_FR}")
    assert _finalize(role, apply=False) == 0
    out = capsys.readouterr().out
    refusals = _lines(out, "WOULD-REFUSE")
    assert len(refusals) == 1 and "fatal: bad revision" in refusals[0]
    assert "WOULD-FINALIZE" not in out


# covers hub-tooling FR-0015:AC-2
def test_upstream_protected_change_merged_by_revalidate_does_not_refuse(
    env, capsys, monkeypatch
):
    """Placement: the check runs before AC-7's merge of origin/main, so an
    upstream (template --upgrade) change to a protected path does not refuse."""
    wt = _role_branch(env, "dev")
    _upstream_moves(env, "scripts/deploy-gate.py", "# upstream change\n")
    capsys.readouterr()
    rc = _finalize("dev", apply=True, revalidate=True)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REVALIDATE   merged origin/main" in out
    assert "control-plane" not in out and "ERROR" not in out
    assert "upstream change" in (wt / "scripts" / "deploy-gate.py").read_text()
    assert any(c[:3] == ["gh", "pr", "create"] for c in env.gh)
    # Discriminates placement: run *after* the merge, the same helper sees
    # the upstream gate change on main...branch (local main is stale).
    paths, err = dispatch._control_plane_branch_paths(
        _FR, "dev", f"claude/dev-{_FR}", True
    )
    assert err is None and paths == ["scripts/deploy-gate.py"]


# ---------------------------------------------------------------------------
# AC-3: uncommitted changes to an off-limits path refuse finalize
# ---------------------------------------------------------------------------


def _warn_lines_of(
    mod, env: _Env, role: str, monkeypatch, tmp_path, capsys
) -> list[str]:
    """FR-0006's WARN lines from `mod`'s dry-run finalize on `env`, as-is."""
    _point(monkeypatch, mod, env.repo, tmp_path)
    capsys.readouterr()
    mod.cmd_finalize(_FR, role, apply=False, draft=True, adapter=None)
    out = capsys.readouterr().out
    _point(monkeypatch, dispatch, env.repo, tmp_path)
    return _lines(out, "WARN         ")


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
def test_unstaged_subprocess_write_to_the_gate_is_refused_and_left_in_place(
    env, pre, post, capsys, monkeypatch, tmp_path, role
):
    wt = _role_branch(env, role)
    _py_write(
        wt / "scripts" / "deploy-gate.py", "import sys; sys.exit(0)  # neutered\n"
    )
    state_before = _wt_state(wt)
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", role, "--apply")
    out = capsys.readouterr().out
    assert rc == 1, out
    lines = out.splitlines()
    errors = _lines(out, "ERROR")
    assert len(errors) == 1, out
    assert f"{_FR}.{role}" in errors[0] and "scripts/deploy-gate.py" in errors[0]
    assert "uncommitted" in errors[0]
    warns = _lines(out, "WARN         ")
    assert warns and all(lines.index(w) < lines.index(errors[0]) for w in warns)
    assert "footprint" not in out  # mnt: stops before the footprint check
    # Refuse, never repair.
    assert _wt_state(wt) == state_before
    assert "neutered" in (wt / "scripts" / "deploy-gate.py").read_text()
    _no_egress(env, f"claude/{role}-{_FR}")
    # FR-0006's WARN lines are unchanged by FR-0015 (anchored: tip vs base).
    assert _warn_lines_of(
        post, env, role, monkeypatch, tmp_path, capsys
    ) == _warn_lines_of(pre, env, role, monkeypatch, tmp_path, capsys)
    # Dry-run through the CLI, required arguments only.
    rc = _cli(monkeypatch, "finalize", _FR, "--role", role)
    out = capsys.readouterr().out
    assert rc == 0 and len(_lines(out, "WOULD-REFUSE")) == 1, out
    assert "scripts/deploy-gate.py" in _lines(out, "WOULD-REFUSE")[0]
    assert _wt_state(wt) == state_before


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
def test_untracked_file_under_agent_team_is_refused(env, capsys, monkeypatch, role):
    wt = _role_branch(env, role)
    _py_write(wt / ".agent-team" / "x", "planted\n")
    state_before = _wt_state(wt)
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and ".agent-team/x" in errors[0]
    assert f"{_FR}.{role}" in errors[0]
    assert (wt / ".agent-team" / "x").read_text() == "planted\n"
    assert _wt_state(wt) == state_before
    _no_egress(env, f"claude/{role}-{_FR}")


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize("role", ["dev", "mnt"])
def test_unstaged_deletion_of_a_protected_file_is_refused(env, capsys, role):
    wt = _role_branch(env, role)
    (wt / "CLAUDE.md").unlink()
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and "CLAUDE.md" in errors[0]
    assert not (wt / "CLAUDE.md").exists()


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize("role", ["dev", "mnt"])
def test_unstaged_protected_write_bite_pre_fr_would_finalize(
    env, pre, capsys, monkeypatch, tmp_path, role
):
    _point(monkeypatch, pre, env.repo, tmp_path)
    wt = _role_branch(env, role, mod=pre)
    _py_write(wt / "scripts" / "deploy-gate.py", "# neutered\n")
    _py_write(wt / ".agent-team" / "x", "planted\n")
    capsys.readouterr()
    assert _finalize(role, apply=False, mod=pre) == 0
    out = capsys.readouterr().out
    assert "WOULD-FINALIZE" in out and "WOULD-REFUSE" not in out


# covers hub-tooling FR-0015:AC-3
def test_mnt_unstaged_change_to_an_owned_protected_path_is_only_warned(
    env, pre, post, capsys, monkeypatch, tmp_path
):
    _set_owns(env, ("src/**", "scripts/deploy-gate.py"))
    wt = _role_branch(env, "mnt")
    _py_write(wt / "scripts" / "deploy-gate.py", "# unfinished maintainer work\n")
    capsys.readouterr()
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    assert "WOULD-REFUSE" not in out and "ERROR" not in out
    assert "WOULD-FINALIZE" in out
    warns = _lines(out, "WARN         ")
    assert len(warns) == 1 and "scripts/deploy-gate.py" in warns[0]
    assert _warn_lines_of(
        post, env, "mnt", monkeypatch, tmp_path, capsys
    ) == _warn_lines_of(pre, env, "mnt", monkeypatch, tmp_path, capsys)
    assert _finalize("mnt", apply=True) == 0
    assert any(c[:3] == ["gh", "pr", "create"] for c in env.gh)


# covers hub-tooling FR-0015:AC-3
def test_mnt_owning_claude_md_exactly_still_refuses_it(env, capsys):
    """MNT_NEVER_WRITABLE is off-limits for mnt even when `owns:` lists it."""
    _set_owns(env, ("src/**", "CLAUDE.md"))
    wt = _role_branch(env, "mnt")
    _py_write(wt / "CLAUDE.md", "rewritten agreement\n")
    capsys.readouterr()
    assert _finalize("mnt", apply=True) == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and "CLAUDE.md" in errors[0] and "uncommitted" in errors[0]


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize(
    "owns,rel",
    [
        (("src/**", "*.md"), "CLAUDE.md"),
        (("src/**", "scripts/*"), "scripts/deploy-gate.py"),
        (("**",), ".agent-team/roles/reviewer.md"),
    ],
)
def test_mnt_broad_owns_glob_does_not_make_a_denied_protected_path_writable(
    env, capsys, owns, rel
):
    """FR-0015's Term: for mnt a protected path is off-limits unless the
    permission derivation grants it, so MNT_NEVER_WRITABLE is *always*
    off-limits. A broad `owns:` glob that happens to match a protected path
    does not grant it: `mnt_permission_rules` still denies it (deny wins),
    so the harness forbids the write — and an interpreter write to it is
    exactly the crossing AC-3 exists to catch."""
    _set_owns(env, owns)
    perms = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    assert f"Edit({rel})" in perms["deny"] or any(
        d.startswith("Edit(") and dispatch._owned(rel, [d[5:-1]]) for d in perms["deny"]
    ), perms["deny"]
    wt = _role_branch(env, "mnt")
    _py_write(wt / rel, "interpreter write\n")
    capsys.readouterr()
    assert _finalize("mnt", apply=True) == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and rel in errors[0] and "uncommitted" in errors[0], out
    assert env.gh == []


def _is_wt_read(args: list[str]) -> bool:
    return args in (
        ["diff", "--name-only"],
        ["ls-files", "--others", "--exclude-standard"],
    )


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize(
    "which", [["diff", "--name-only"], ["ls-files", "--others", "--exclude-standard"]]
)
@pytest.mark.parametrize("role", ["dev", "mnt"])
def test_a_failing_worktree_read_is_a_refusal(env, capsys, monkeypatch, role, which):
    _role_branch(env, role)
    seen = _fail_git(monkeypatch, lambda args: list(args) == which)
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    out = capsys.readouterr().out
    assert seen
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and f"{_FR}.{role}" in errors[0]
    assert "fatal: bad revision" in errors[0] and "usage:" not in errors[0]
    _no_egress(env, f"claude/{role}-{_FR}")
    assert _finalize(role, apply=False) == 0
    assert len(_lines(capsys.readouterr().out, "WOULD-REFUSE")) == 1


# covers hub-tooling FR-0015:AC-3
def test_fr0006_leftover_helpers_stay_fail_open(env, capsys, monkeypatch):
    wt = _role_branch(env, "dev")
    _py_write(wt / "README.md", "edited\n")
    _py_write(wt / "src" / "new.py", "new\n")
    _fail_git(monkeypatch, _is_wt_read)
    assert dispatch._unstaged_paths(wt) == []
    assert dispatch._untracked_paths(wt) == []
    capsys.readouterr()
    dispatch._report_leftover_work(_FR, "dev", wt)
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# AC-4: a permission file the agent rewrote refuses finalize
# ---------------------------------------------------------------------------


_ADAPTERS = {
    "claude-code": (".claude", "settings.local.json"),
    "cursor": (".cursor", "cli.json"),
}


def _stub_spawn(monkeypatch, adapter) -> list:
    calls: list = []

    def spawn(fr_id, role, wt_path, log_path, extra_prompt=None, gate_id=None):
        calls.append((fr_id, role))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type":"result","subtype":"success"}\n', encoding="utf-8")
        return ("spawned", 999_999)

    monkeypatch.setattr(adapter, "spawn", spawn)
    return calls


def _spawn(env: _Env, monkeypatch, role: str, harness: str, dd: Path) -> Path:
    """A real `spawn_role(apply=True)` with only the harness process
    stubbed; `DISPATCH_DIR` is re-pointed *after* import, to `dd`."""
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", dd)
    adapter = dispatch.get_adapter(harness)
    calls = _stub_spawn(monkeypatch, adapter)
    status, _pid, wt = dispatch.spawn_role(_FR, role, True, adapter)
    assert wt is not None, status
    assert calls == [(_FR, role)]
    return wt


def _record(dd: Path, role: str) -> dict:
    files = sorted(
        p
        for p in dd.iterdir()
        if p.is_file() and role in p.name and "settings" in p.name
    )
    assert len(files) == 1, [p.name for p in dd.iterdir()]
    return json.loads(files[0].read_text(encoding="utf-8"))


# covers hub-tooling FR-0015:AC-4
@pytest.mark.parametrize("harness", ["claude-code", "cursor"])
@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
def test_spawn_records_the_sha256_of_the_bytes_on_disk_under_call_time_dispatch_dir(
    env, monkeypatch, tmp_path, harness, role
):
    if role == "rev":
        dev_wt = _worktree(env.repo, "dev")
        _commit(dev_wt, "src/thing.py", "x\n", "impl")
    dd = tmp_path / "dispatch-elsewhere"
    wt = _spawn(env, monkeypatch, role, harness, dd)
    sub, name = _ADAPTERS[harness]
    settings = wt / sub / name
    rec = _record(dd, role)
    assert Path(rec["path"]) == settings
    assert rec["sha256"] == hashlib.sha256(settings.read_bytes()).hexdigest()
    # Never inside the worktree, never in the import-time or repo _dispatch.
    assert not any("sha256" in p.name for p in wt.rglob("*") if ".git" not in p.parts)
    assert not any("settings" in p.name for p in (env.repo / "_dispatch").iterdir()), (
        list((env.repo / "_dispatch").iterdir())
    )
    real_dd = _SCRIPTS_DIR.parent / "_dispatch"
    assert not real_dd.exists() or not any(
        _FR in p.name and "settings" in p.name for p in real_dd.iterdir()
    )


# covers hub-tooling FR-0015:AC-4
def test_digest_is_in_neither_the_lock_nor_any_metrics_record(
    env, monkeypatch, tmp_path
):
    dd = env.repo / "_dispatch"
    _spawn(env, monkeypatch, "dev", "claude-code", dd)
    digest = _record(dd, "dev")["sha256"]
    lock_text = dispatch.lock_path(_FR, "dev").read_text(encoding="utf-8")
    lock = json.loads(lock_text)
    assert digest not in lock_text and digest[:12] not in lock_text
    assert not any("sha" in k or "digest" in k for k in lock)
    assert "sha" not in str(lock["worktree_status"])
    texts = [
        p.read_text(encoding="utf-8") for p in metrics_log.METRICS_DIR.glob("*.ndjson")
    ]
    assert texts, "the spawn emits a dispatch record"
    for t in texts:
        assert digest not in t and digest[:12] not in t and "sha256" not in t
    for t in texts:
        for ln in t.splitlines():
            rec = json.loads(ln)
            ws = rec.get("worktree_status")
            if ws is not None:
                assert "sha" not in str(ws) and "digest" not in str(ws)


def _tamper_add_allow(settings: Path) -> None:
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["permissions"]["allow"].append("Bash(*)")
    _py_write(settings, json.dumps(data, indent=2) + "\n")


# covers hub-tooling FR-0015:AC-4
@pytest.mark.parametrize("harness", ["claude-code", "cursor"])
@pytest.mark.parametrize("role", ["dev", "bkf", "mnt"])
def test_one_added_allow_entry_refuses_with_both_digests_truncated(
    env, capsys, monkeypatch, harness, role
):
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, role, harness, dd)
    _commit(wt, "tests/test_b.py" if role == "bkf" else "src/w.py", "w\n", "work")
    sub, name = _ADAPTERS[harness]
    settings = wt / sub / name
    recorded = _record(dd, role)["sha256"]
    _tamper_add_allow(settings)
    current = hashlib.sha256(settings.read_bytes()).hexdigest()
    assert current != recorded
    capsys.readouterr()
    rc = _cli(monkeypatch, "finalize", _FR, "--role", role, "--apply")
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and f"{_FR}.{role}" in errors[0]
    assert str(settings) in errors[0]
    assert current[:12] in errors[0] and recorded[:12] in errors[0]
    assert current[:13] not in errors[0] and recorded[:13] not in errors[0]
    assert "Bash(*)" in settings.read_text(encoding="utf-8")  # left as found
    _no_egress(env, f"claude/{role}-{_FR}")
    rc = _cli(monkeypatch, "finalize", _FR, "--role", role)
    out = capsys.readouterr().out
    assert rc == 0 and len(_lines(out, "WOULD-REFUSE")) == 1, out


# covers hub-tooling FR-0015:AC-4
def test_deleted_permission_file_is_refused_as_missing(env, capsys, monkeypatch):
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", "claude-code", dd)
    _commit(wt, "src/w.py", "w\n", "work")
    recorded = _record(dd, "dev")["sha256"]
    settings = wt / ".claude" / "settings.local.json"
    settings.unlink()
    capsys.readouterr()
    assert _finalize("dev", apply=True) == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and "missing" in errors[0] and recorded[:12] in errors[0]
    assert str(settings) in errors[0]
    assert not settings.exists()
    assert env.gh == []


# covers hub-tooling FR-0015:AC-4
def test_permission_file_rewrite_bite_pre_fr_would_finalize(
    env, pre, capsys, monkeypatch, tmp_path
):
    _point(monkeypatch, pre, env.repo, tmp_path)
    adapter = pre.get_adapter("claude-code")
    _stub_spawn(monkeypatch, adapter)
    _status, _pid, wt = pre.spawn_role(_FR, "dev", True, adapter)
    _commit(wt, "src/w.py", "w\n", "work")
    _tamper_add_allow(wt / ".claude" / "settings.local.json")
    capsys.readouterr()
    assert _finalize("dev", apply=False, mod=pre) == 0
    assert "WOULD-FINALIZE" in capsys.readouterr().out


# covers hub-tooling FR-0015:AC-4
@pytest.mark.parametrize("harness", ["claude-code", "cursor"])
def test_reuse_path_refreshes_the_record_and_finalize_proceeds(
    env, capsys, monkeypatch, harness
):
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", harness, dd)
    _commit(wt, "src/w.py", "w\n", "work")
    sub, name = _ADAPTERS[harness]
    settings = wt / sub / name
    original = settings.read_bytes()
    _tamper_add_allow(settings)
    adapter = dispatch.get_adapter(harness)
    wt2, status = dispatch.ensure_role_worktree(_FR, "dev", adapter)
    assert wt2 == wt and status.startswith("reused"), status
    assert settings.read_bytes() == original  # rewritten by the dispatcher
    assert _record(dd, "dev")["sha256"] == hashlib.sha256(original).hexdigest()
    capsys.readouterr()
    assert _finalize("dev", apply=False) == 0
    out = capsys.readouterr().out
    assert "WOULD-FINALIZE" in out and "permission file" not in out


# covers hub-tooling FR-0015:AC-4
def test_a_worktree_with_no_record_gets_no_extra_line(
    env, pre, post, capsys, monkeypatch, tmp_path
):
    wt = _role_branch(env, "dev")
    _write(
        wt / ".claude" / "settings.local.json",
        '{"permissions": {"allow": ["Bash(*)"]}}\n',
    )
    capsys.readouterr()
    assert _finalize("dev", apply=False) == 0  # live: no record, no refusal
    live = capsys.readouterr().out
    assert "permission file" not in live and "WOULD-REFUSE" not in live
    # Byte identity is anchored: FR-0015's tip vs its base.
    _point(monkeypatch, post, env.repo, tmp_path)
    assert _finalize("dev", apply=False, mod=post) == 0
    new = capsys.readouterr().out
    _point(monkeypatch, pre, env.repo, tmp_path)
    assert _finalize("dev", apply=False, mod=pre) == 0
    assert capsys.readouterr().out == new


class _PoisonAdapter:
    """Any attribute access fails the test: finalize must find the
    permission file from the record, never from `adapter`."""

    def __getattr__(self, name):
        pytest.fail(f"finalize read adapter.{name}")


# covers hub-tooling FR-0015:AC-4
def test_finalize_finds_the_file_from_the_record_never_from_adapter(
    env, capsys, monkeypatch
):
    dd = env.repo / "_dispatch"
    dev_wt = _worktree(env.repo, "dev")
    _commit(dev_wt, "src/thing.py", "x\n", "impl")
    _impl_pr_record(dispatch, "dev")
    # Spawned under Cursor; finalized with no adapter / a poison adapter.
    wt = _spawn(env, monkeypatch, "rev", "cursor", dd)
    _commit(wt, "tests/test_ac1.py", "# t\n", "test")
    _rev_log(env.repo, "## Approve\n\nok")
    _tamper_add_allow(wt / ".cursor" / "cli.json")
    capsys.readouterr()
    rc = dispatch.cmd_finalize(
        _FR, "rev", apply=True, draft=True, adapter=_PoisonAdapter()
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "cli.json" in errors[0]
    assert env.gh == []
    src = inspect.getsource(dispatch._finalize_settings_digest_violation)
    assert "adapter" not in src


# covers hub-tooling FR-0015:AC-4
def test_clean_spawned_finalize_with_untracked_settings_file_does_not_refuse(
    env, capsys, monkeypatch
):
    """The dispatcher-written settings file is untracked and not ignored in a
    bootstrapped project: FR-0006's WARN names it, nothing refuses."""
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", "claude-code", dd)
    _commit(wt, "src/w.py", "w\n", "work")
    _write(wt / "PR_BODY.md", f"# {_FR}\n")
    capsys.readouterr()
    rc = _finalize("dev", apply=True)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ERROR" not in out and "PUSHED" in out
    assert ".claude/settings.local.json" in "".join(_lines(out, "WARN"))
    tree = _git(env.repo, "ls-tree", "-r", "--name-only", f"claude/dev-{_FR}")
    assert "sha256" not in tree and "settings.local.json" not in tree


# ---------------------------------------------------------------------------
# AC-5: a malformed `owns:` is refused for rev, bkf and mnt
# ---------------------------------------------------------------------------


class _SpyAdapter:
    def __init__(self, real) -> None:
        self.real = real
        self.writes: list = []
        self.spawns: list = []
        self.name = real.name

    def write_worktree_settings(self, *a, **k):
        self.writes.append(a)
        return self.real.write_worktree_settings(*a, **k)

    def spawn(self, *a, **k):
        self.spawns.append(a)
        return ("spawned", 999_999)

    def __getattr__(self, name):
        return getattr(self.real, name)


_BAD_OWNS = [("/abs/escape.py", "src/**"), ("src/../escape/**", "src/**")]


def _dev_error(owns: tuple[str, ...]) -> str:
    return "error:" + "; ".join(dispatch._invalid_owns_entries(_FR))


# covers hub-tooling FR-0015:AC-5
@pytest.mark.parametrize("owns", _BAD_OWNS)
@pytest.mark.parametrize("role", ["rev", "bkf", "mnt"])
def test_malformed_owns_is_refused_with_devs_exact_error_and_nothing_written(
    env, monkeypatch, capsys, role, owns
):
    _set_owns(env, owns)
    if role == "rev":
        dev_wt = _worktree(env.repo, "dev")
        _commit(dev_wt, "src/thing.py", "x\n", "impl")
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: pytest.fail("venv"))
    dd = env.repo / "_dispatch"
    dd_before = sorted(p.name for p in dd.iterdir())
    refs_before = env.refs()
    dev_wt_path = env.repo / ".claude" / "worktrees" / f"dev-{_FR}"
    dev_path, dev_status = None, None
    spy = _SpyAdapter(dispatch.get_adapter("claude-code"))
    path, status = dispatch.ensure_role_worktree(_FR, role, spy)
    assert path is None
    expected = _dev_error(owns)
    assert status == expected
    assert ("absolute" in status) or (".." in status)
    # dev gets the very same text.
    if role != "rev":
        dev_path, dev_status = dispatch.ensure_role_worktree(_FR, "dev", spy)
        assert dev_path is None and dev_status == status
        assert not dev_wt_path.exists()
    # Through spawn_role: no lock, no spawn, no spawn record.
    st, pid, wt = dispatch.spawn_role(_FR, role, True, spy)
    assert (st, pid, wt) == (status, None, None)
    assert spy.writes == [] and spy.spawns == []
    assert not (env.repo / ".claude" / "worktrees" / f"{role}-{_FR}").exists()
    assert sorted(p.name for p in dd.iterdir()) == dd_before
    assert not dispatch.lock_path(_FR, role).exists()
    assert env.refs() == refs_before  # no branch created
    assert not metrics_log.METRICS_DIR.exists() or not list(
        metrics_log.METRICS_DIR.glob("*.ndjson")
    )


# covers hub-tooling FR-0015:AC-5
@pytest.mark.parametrize("owns", _BAD_OWNS)
def test_malformed_owns_blocks_revs_reuse_fast_forward(env, monkeypatch, owns):
    dev_wt = _worktree(env.repo, "dev")
    _commit(dev_wt, "src/thing.py", "x\n", "impl")
    rev_wt = _worktree(env.repo, "rev", base=f"claude/dev-{_FR}")
    rev_head = _git(rev_wt, "rev-parse", "HEAD")
    _commit(dev_wt, "src/more.py", "more\n", "dev moved on")  # a ff is due
    assert dispatch._rev_sync_plan(_FR)[0] == "fast-forward"
    _write(env.repo / "specs" / f"{_FR}-synthetic.md", _fr_md(owns))
    settings = rev_wt / ".claude" / "settings.local.json"
    assert not settings.exists()
    spy = _SpyAdapter(dispatch.get_adapter("claude-code"))
    path, status = dispatch.ensure_role_worktree(_FR, "rev", spy)
    assert path is None and status == _dev_error(owns)
    assert _git(rev_wt, "rev-parse", "HEAD") == rev_head  # not fast-forwarded
    assert _git(env.repo, "rev-parse", f"claude/rev-{_FR}") == rev_head
    assert not settings.exists() and spy.writes == []


# covers hub-tooling FR-0015:AC-5
def test_malformed_owns_bite_pre_fr_created_the_reviewer_worktree(
    env, pre, monkeypatch, tmp_path
):
    _point(monkeypatch, pre, env.repo, tmp_path)
    _set_owns(env, ("/abs/escape.py",))
    path, status = pre.ensure_role_worktree(_FR, "bkf", pre.get_adapter("claude-code"))
    assert path is not None and status.startswith("created"), status


# covers hub-tooling FR-0015:AC-5
def test_mnt_empty_owns_refusal_still_runs_first(env):
    _set_owns(env, ("",))  # empty after stripping; also an invalid entry
    assert dispatch._invalid_owns_entries(_FR)  # would fire if it ran first
    spy = _SpyAdapter(dispatch.get_adapter("claude-code"))
    path, status = dispatch.ensure_role_worktree(_FR, "mnt", spy)
    assert path is None
    assert (
        "declares no `owns:` frontmatter" in status
        and "must not be empty" not in status
    )
    path, status = dispatch.ensure_role_worktree(_FR, "dev", spy)
    assert path is None and "must not be empty" in status
    assert spy.writes == []


# covers hub-tooling FR-0015:AC-5
@pytest.mark.parametrize("role", ["rev", "bkf", "mnt"])
@pytest.mark.parametrize("owns", [("src/**",), None])
def test_valid_or_absent_owns_is_unchanged(
    pre, post, tmp_path, monkeypatch, role, owns
):
    if role == "mnt" and owns is None:
        pytest.skip("mnt refuses an absent owns: (unchanged, covered above)")
    results = {}
    for name, mod in (("new", post), ("old", pre)):
        e = _build_env(tmp_path / name, monkeypatch, mod=mod, owns=owns)
        if role == "rev":
            dev_wt = _worktree(e.repo, "dev")
            _commit(dev_wt, "src/thing.py", "x\n", "impl")
        path, status = mod.ensure_role_worktree(
            _FR, role, mod.get_adapter("claude-code")
        )
        assert path is not None, status
        results[name] = (
            status,
            (path / ".claude" / "settings.local.json").read_bytes(),
            _git(path, "rev-parse", "--abbrev-ref", "HEAD"),
        )
    assert results["new"] == results["old"]


# ---------------------------------------------------------------------------
# AC-6: nothing widens, clean runs byte-identical
# ---------------------------------------------------------------------------


_STACKS = {
    "none": {},
    "python-uv": {
        "pyproject.toml": "[project]\nname='x'\n",
        "uv.lock": "version = 1\n",
    },
    "node": {"package.json": "{}\n"},
    "docker": {"docker-compose.yml": "services: {}\n"},
}


# covers hub-tooling FR-0015:AC-6
@pytest.mark.parametrize("stack", sorted(_STACKS))
@pytest.mark.parametrize(
    "owns",
    [("src/**",), ("src/**", "scripts/deploy-gate.py", ".agent-team/roles/x.md")],
)
def test_every_permission_file_is_byte_identical_to_the_base(
    pre, post, tmp_path, monkeypatch, stack, owns
):
    """Anchored: FR-0015's tip vs its base, each with its own siblings."""
    repo, _bare = _make_repo(tmp_path, owns=owns, extra=_STACKS[stack])
    compared = 0
    for mod in (post, pre):
        _point(monkeypatch, mod, repo, tmp_path)
    tools = post.detected_stack_tools()
    assert tools == pre.detected_stack_tools()
    if stack != "none":
        assert tools
    for role in ("dev", "rev", "bkf", "mnt", "gat"):
        for cls, (sub, name) in (
            ("ClaudeCodeAdapter", _ADAPTERS["claude-code"]),
            ("CursorAdapter", _ADAPTERS["cursor"]),
        ):
            kw = {"gate_id": "g1"} if role == "gat" else {}
            new_wt, old_wt = tmp_path / f"n-{role}-{cls}", tmp_path / f"o-{role}-{cls}"
            getattr(post, cls)().write_worktree_settings(new_wt, role, _FR, **kw)
            getattr(pre, cls)().write_worktree_settings(old_wt, role, _FR, **kw)
            assert (new_wt / sub / name).read_bytes() == (
                old_wt / sub / name
            ).read_bytes(), (
                role,
                cls,
            )
            compared += 1
    assert compared == 10


_FROZEN = (
    "STACK_BASH_GRANTS",  # lives in stack_profile.py
    "CURSOR_STACK_SHELL_GRANTS",
    "_union_grants",
    "_mnt_bash_denies",
    "MNT_BASH_NOT_INHERITED",
    "MNT_BASH_DENIES",
    "MNT_PROTECTED_GLOBS",
    "MNT_NEVER_WRITABLE",
    "mnt_footprint_violations",
    "_unstaged_paths",
    "_untracked_paths",
    "_report_leftover_work",
    "_finalize_base_branch",
)


def _top_level(src: str) -> dict[str, str]:
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        for n in names:
            out[n] = ast.get_source_segment(src, node) or ""
    return out


def _strip_docstring(fn_src: str) -> str:
    node = ast.parse(fn_src).body[0]
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    ):
        node.body = node.body[1:]
    return ast.dump(node)


# covers hub-tooling FR-0015:AC-6
def test_frozen_constants_and_helpers_are_unedited_and_the_edit_surface_is_the_acs():
    """Anchored: FR-0015's own change is `82670a5` -> `a7be8eb`. Later FRs
    may legitimately edit these files; that is not FR-0015's edit surface."""
    old_src = _git_show(_PRE_FR_REF, "template/scripts/dispatch.py")
    old_sp = _git_show(_PRE_FR_REF, "template/scripts/stack_profile.py")
    new_src = _git_show(_FR_TIP_REF, "template/scripts/dispatch.py")
    new_sp = _git_show(_FR_TIP_REF, "template/scripts/stack_profile.py")
    if None in (old_src, old_sp, new_src, new_sp):
        pytest.skip("FR-0015 base or tip sources not reachable")
    assert new_sp == old_sp
    old = _top_level(old_src.decode("utf-8"))
    new = _top_level(new_src.decode("utf-8"))
    for name in _FROZEN:
        if name == "STACK_BASH_GRANTS":
            continue
        assert new[name] == old[name], name
    changed = {n for n in old if n in new and new[n] != old[n]}
    added = set(new) - set(old)
    assert set(old) - set(new) == set()
    assert changed == {
        "ClaudeCodeAdapter",
        "CursorAdapter",
        "ensure_role_worktree",
        "_mnt_provenance_exemptions",
        "cmd_finalize",
        "detected_stack_tools",
    }, changed
    assert added == {
        "_settings_digest_record_path",
        "_record_settings_digest",
        "_finalize_settings_digest_violation",
        "_first_nonempty_line",
        "_control_plane_branch_paths",
        "_off_limits_worktree_paths",
        "_uncommitted_control_plane_paths",
    }, added
    # detected_stack_tools: the docstring sentence only.
    assert _strip_docstring(new["detected_stack_tools"]) == _strip_docstring(
        old["detected_stack_tools"]
    )
    assert "DEC-0014" in new["detected_stack_tools"]
    assert "re-pointed later" not in new["detected_stack_tools"]
    # Inside the adapters, only write_worktree_settings moved.
    for cls in ("ClaudeCodeAdapter", "CursorAdapter"):
        o = {
            n.name: ast.get_source_segment(old[cls], n)
            for n in ast.parse(old[cls]).body[0].body
            if isinstance(n, ast.FunctionDef)
        }
        n_ = {
            n.name: ast.get_source_segment(new[cls], n)
            for n in ast.parse(new[cls]).body[0].body
            if isinstance(n, ast.FunctionDef)
        }
        assert set(o) == set(n_)
        assert {k for k in o if o[k] != n_[k]} == {"write_worktree_settings"}, cls
        # How the file is written is unchanged: same write_text call.
        assert (
            'json.dumps(payload, indent=2) + "\\n", encoding="utf-8"'
            in n_["write_worktree_settings"]
        )
        assert "write_bytes" not in n_["write_worktree_settings"]
        assert "newline=" not in n_["write_worktree_settings"]


# covers hub-tooling FR-0015:AC-6
def test_mnt_footprint_violations_keeps_its_signature_and_single_call_site(pre, post):
    """Anchored: FR-0015's tip vs its base (DEC-0017 Decision 4)."""
    assert inspect.signature(post.mnt_footprint_violations) == inspect.signature(
        pre.mnt_footprint_violations
    )
    src = inspect.getsource(post.cmd_finalize)
    assert src.count("mnt_footprint_violations(") == 1
    assert "mnt_footprint_violations(fr_id, branch)" in src
    for helper in (
        post._control_plane_branch_paths,
        post._uncommitted_control_plane_paths,
        post._off_limits_worktree_paths,
    ):
        assert "mnt_footprint_violations" not in inspect.getsource(helper)


def _norm_metrics(root: Path, repo: Path) -> list[dict]:
    volatile = re.compile(r"(^ts$|_at$|^at$|time|duration|_id$|^id$|^run$)")
    out = []
    for f in (
        sorted((root / "metrics").glob("*.ndjson"))
        if (root / "metrics").exists()
        else []
    ):
        for ln in f.read_text(encoding="utf-8").splitlines():
            rec = json.loads(ln)
            out.append(
                json.loads(
                    json.dumps(
                        {k: v for k, v in rec.items() if not volatile.search(k)}
                    ).replace(json.dumps(str(repo))[1:-1], "<r>")
                )
            )
    return out


def _pr_records(repo: Path) -> dict[str, dict]:
    recs = {}
    for p in sorted((repo / "_dispatch").glob("*.pr.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d.pop("finalized_at", None)
        recs[p.name] = d
    return recs


def _clean_run(mod, root: Path, role: str, spawned: bool, monkeypatch, capsys):
    e = _build_env(root, monkeypatch, mod=mod)
    if spawned:
        if role == "rev":
            dev_wt = _worktree(e.repo, "dev")
            _commit(dev_wt, "src/thing.py", "print('thing')\n", "feat: impl work")
            _git(e.repo, "push", "-q", "-u", "origin", f"claude/dev-{_FR}")
            _impl_pr_record(mod, "dev")
            _rev_log(e.repo, "## Approve\n\nAll ACs covered.")
        adapter = mod.get_adapter("claude-code")
        _stub_spawn(monkeypatch, adapter)
        _st, _pid, wt = mod.spawn_role(_FR, role, True, adapter)
        _stage_rel = "tests/test_x.py" if role in ("rev", "bkf") else "src/w.py"
        _write(wt / _stage_rel, "w\n")
        _git(wt, "add", _stage_rel)  # staged: the dispatcher commits it
        if role in ("dev", "mnt", "bkf"):
            _write(wt / "PR_BODY.md", f"# {_FR} ({role})\n")
    else:
        wt = _role_branch(e, role, mod=mod)
        _py_write(wt / "README.md", "unstaged, non-protected\n")
        _py_write(wt / "src" / "untracked.py", "x\n")
    capsys.readouterr()
    outs = []
    for apply in (False, True):
        rc = _finalize(role, apply=apply, mod=mod)
        outs.append(f"rc={rc}\n" + capsys.readouterr().out.replace(str(e.repo), "<r>"))
    outs.append(_n(repr(e.gh), e.repo))
    outs.append(e.bare_refs())
    return outs, _pr_records(e.repo), _norm_metrics(root, e.repo)


# covers hub-tooling FR-0015:AC-6
# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("spawned", [False, True])
@pytest.mark.parametrize("role", ["dev", "rev", "bkf", "mnt"])
def test_clean_finalize_is_byte_identical_to_the_base(
    pre, post, tmp_path, monkeypatch, capsys, role, spawned
):
    """Every line, exit code, `gh` argv, pushed ref, PR record and metrics
    record of a clean dry-run + apply finalize matches FR-0015's base.
    Anchored: FR-0015's tip (`a7be8eb`) vs its base (`82670a5`).
    `spawned=True` goes through the real `spawn_role` so the dispatcher-
    written permission file and its AC-4 record are present."""
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")
    new = _clean_run(post, tmp_path / "new", role, spawned, monkeypatch, capsys)
    old = _clean_run(pre, tmp_path / "old", role, spawned, monkeypatch, capsys)
    assert new[0] == old[0]
    assert new[1] == old[1]
    assert new[2] == old[2]
    assert "ERROR" not in "".join(new[0])
    assert "PUSHED" in new[0][1]


# ---------------------------------------------------------------------------
# Kick-back pins (request-changes round 1)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_renaming_a_protected_file_away_is_a_control_plane_change(env, capsys, role):
    """`git diff --name-only` detects renames by default and then prints only
    the *new* name, so `git mv scripts/deploy-gate.py src/gate.py` hides the
    gate's removal from `<base>...<branch>`. The protected path changed on
    the branch (it is gone), so AC-2 must refuse."""
    wt = _role_branch(env, role)
    _git(wt, "mv", "scripts/deploy-gate.py", "src/gate.py")
    _git(wt, "commit", "-q", "-m", "move the gate out of the way")
    assert "scripts/deploy-gate.py" not in _git(
        env.repo,
        "diff",
        "--name-only",
        f"{dispatch._finalize_base_branch(_FR, role)}...claude/{role}-{_FR}",
    )
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1, capsys.readouterr().out
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and "scripts/deploy-gate.py" in errors[0]
    _no_egress(env, f"claude/{role}-{_FR}")


# covers hub-tooling FR-0015:AC-2
def test_dry_run_staged_rename_of_a_protected_file_is_counted(env, capsys):
    wt = _role_branch(env, "dev")
    _git(wt, "mv", ".agent-team/roles/developer.md", "docs/developer.md")
    capsys.readouterr()
    assert _finalize("dev", apply=False) == 0
    out = capsys.readouterr().out
    refusals = _lines(out, "WOULD-REFUSE")
    assert len(refusals) == 1 and ".agent-team/roles/developer.md" in refusals[0], out


# covers hub-tooling FR-0015:AC-4
@pytest.mark.parametrize(
    "record_text",
    ["not json at all\n", '{"path": null}\n', "[]\n", ""],
)
def test_a_record_that_exists_but_cannot_be_read_is_a_refusal(
    env, capsys, monkeypatch, record_text
):
    """A record exists, so the check must run; one that cannot be parsed is
    "a check that cannot run", which FR-0015's fixed rule makes a refusal,
    not the silent skip AC-4 reserves for "no record exists"."""
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", "claude-code", dd)
    _commit(wt, "src/w.py", "w\n", "work")
    rec_path = dispatch._settings_digest_record_path(_FR, "dev")
    assert rec_path.exists()
    rec_path.write_text(record_text, encoding="utf-8")
    capsys.readouterr()
    rc = _finalize("dev", apply=True)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and f"{_FR}.dev" in errors[0]
    _no_egress(env, f"claude/dev-{_FR}")


# ---------------------------------------------------------------------------
# Round 2: K1 / K2 / K3 beyond the round-1 red tests
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize(
    "owns,rel",
    [
        (("src/**", "**/*.md"), ".agent-team/roles/reviewer.md"),
        (("src/**", "**/*.md"), "CLAUDE.md"),
        (("src/**", "scripts/**"), "scripts/deploy-gate.py"),
        (("src/**", "scripts/**"), "scripts/index-specs.py"),
        (("src/**", ".agent-team/roles/developer.md"), ".agent-team/roles/reviewer.md"),
        (("src/**", ".agent-team/roles/developer.md"), ".agent-team/hooks/new.py"),
    ],
)
def test_k1_other_broad_or_sibling_globs_leave_a_denied_path_off_limits(
    env, capsys, owns, rel
):
    """K1 beyond round 1's three globs: a glob that matches a protected path
    without the derivation granting it, and an unowned sibling (tracked or
    new) under a partly-owned protected tree, both refuse."""
    _set_owns(env, owns)
    wt = _role_branch(env, "mnt")
    _py_write(wt / rel, "interpreter write\n")
    capsys.readouterr()
    assert _finalize("mnt", apply=True) == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and rel in errors[0] and "uncommitted" in errors[0], out
    assert env.gh == []


# covers hub-tooling FR-0015:AC-3
@pytest.mark.parametrize(
    "rel", [".agent-team/roles/reviewer.md", "scripts/index-specs.py"]
)
def test_k1_owning_a_protected_path_exactly_is_still_only_warned(env, capsys, rel):
    """The legitimate grant K1's fix must not break: `owns:` naming a
    protected path exactly leaves an unstaged change to it as today's WARN."""
    _set_owns(env, ("src/**", rel))
    perms = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    assert f"Edit({rel})" not in perms["deny"]
    wt = _role_branch(env, "mnt")
    _py_write(wt / rel, "# unfinished maintainer work\n")
    capsys.readouterr()
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    assert "WOULD-REFUSE" not in out and "ERROR" not in out, out
    warns = _lines(out, "WARN         ")
    assert len(warns) == 1 and rel in warns[0]


def _commit_all(wt: Path, msg: str) -> None:
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", msg)


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_k2_rename_into_a_protected_path_is_refused(env, capsys, role):
    wt = _role_branch(env, role)
    _git(wt, "mv", "src/app.py", ".agent-team/roles/app.py")
    _commit_all(wt, "move into the control plane")
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and ".agent-team/roles/app.py" in errors[0]
    _no_egress(env, f"claude/{role}-{_FR}")


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_k2_rename_plus_modify_away_from_a_protected_path_is_refused(env, capsys, role):
    wt = _role_branch(env, role)
    _git(wt, "mv", "scripts/deploy-gate.py", "src/gate.py")
    (wt / "src" / "gate.py").write_bytes(
        b"# synthetic gate: exits 0\n# and one more line\n"
    )
    _commit_all(wt, "move and tweak the gate")
    rng = f"{dispatch._finalize_base_branch(_FR, role)}...claude/{role}-{_FR}"
    assert "scripts/deploy-gate.py" not in _git(env.repo, "diff", "--name-only", rng)
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and "scripts/deploy-gate.py" in errors[0]
    _no_egress(env, f"claude/{role}-{_FR}")


# covers hub-tooling FR-0015:AC-2
def test_k2_copy_detection_config_does_not_hide_a_rename_away(env, capsys):
    """`diff.renames=copies` in the repo config turns on copy detection for
    the default call; `--no-renames` must still name the old path."""
    _git(env.repo, "config", "diff.renames", "copies")
    wt = _role_branch(env, "dev")
    _git(wt, "mv", "scripts/index-specs.py", "src/indexer.py")
    _commit_all(wt, "move the indexer")
    capsys.readouterr()
    assert _finalize("dev", apply=True) == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and "scripts/index-specs.py" in errors[0]


# covers hub-tooling FR-0015:AC-2
def test_k2_copying_a_protected_file_out_without_changing_it_is_not_refused(
    env, capsys
):
    """A copy leaves the protected path unchanged, so it is not a
    control-plane change, with or without copy detection."""
    _git(env.repo, "config", "diff.renames", "copies")
    wt = _role_branch(env, "dev")
    _write(wt / "src" / "gate_copy.py", "# synthetic gate: exits 0\n")
    _commit_all(wt, "copy the gate")
    capsys.readouterr()
    assert _finalize("dev", apply=False) == 0
    out = capsys.readouterr().out
    assert "WOULD-REFUSE" not in out and "WOULD-FINALIZE" in out, out


def _is_no_renames_range_diff(args: list[str]) -> bool:
    return _is_range_diff(args) and "--no-renames" in args


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("role", ["dev", "rev", "bkf"])
def test_k2_a_failing_no_renames_read_alone_is_a_refusal_quoting_the_first_line(
    env, capsys, monkeypatch, role
):
    """The union fails closed on either call: only the `--no-renames` range
    read fails here, and the renames-default read succeeds."""
    _role_branch(env, role)
    seen = _fail_git(monkeypatch, _is_no_renames_range_diff)
    capsys.readouterr()
    assert _finalize(role, apply=True) == 1
    out = capsys.readouterr().out
    assert seen
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "control-plane check failed" in errors[0]
    assert "fatal: bad revision" in errors[0] and "usage:" not in errors[0]
    _no_egress(env, f"claude/{role}-{_FR}")
    assert _finalize(role, apply=False) == 0
    refusals = _lines(capsys.readouterr().out, "WOULD-REFUSE")
    assert len(refusals) == 1 and "fatal: bad revision" in refusals[0]


# covers hub-tooling FR-0015:AC-2
@pytest.mark.parametrize("no_renames", [False, True])
def test_k2_a_failing_dry_run_staged_read_is_a_refusal(
    env, capsys, monkeypatch, no_renames
):
    """The AC-2-private staged reads fail closed (round 1 routed them
    through fail-open `_staged_paths`)."""
    wt = _role_branch(env, "dev")
    _write(wt / "src" / "staged.py", "x\n")
    _git(wt, "add", "src/staged.py")

    def pred(args: list[str]) -> bool:
        return (
            args[:3] == ["diff", "--cached", "--name-only"]
            and ("--no-renames" in args) == no_renames
        )

    seen = _fail_git(monkeypatch, pred)
    capsys.readouterr()
    assert _finalize("dev", apply=False) == 0
    out = capsys.readouterr().out
    assert seen
    refusals = _lines(out, "WOULD-REFUSE")
    assert len(refusals) == 1 and "control-plane check failed" in refusals[0], out
    assert "fatal: bad revision" in refusals[0] and "usage:" not in refusals[0]
    assert "WOULD-FINALIZE" not in out


# covers hub-tooling FR-0015:AC-2
def test_k2_clean_run_makes_both_range_reads_and_prints_nothing_extra(
    env, capsys, monkeypatch
):
    """The union's cost on a clean branch: exactly one extra `git diff`, no
    extra line (byte identity itself is pinned by the AC-6 test)."""
    _role_branch(env, "dev")
    real = dispatch._git_capture
    calls: list[list[str]] = []

    def spy(args, cwd):
        calls.append(list(args))
        return real(args, cwd)

    monkeypatch.setattr(dispatch, "_git_capture", spy)
    capsys.readouterr()
    assert _finalize("dev", apply=False) == 0
    out = capsys.readouterr().out
    assert "WOULD-REFUSE" not in out and "control-plane" not in out
    ranged = [c for c in calls if _is_range_diff(c)]
    assert len(ranged) == 2 and sum("--no-renames" in c for c in ranged) == 1


# covers hub-tooling FR-0015:AC-4
@pytest.mark.parametrize(
    "record_bytes",
    [
        pytest.param(b"\xff\xfe\x00not utf-8", id="not-utf8"),
        pytest.param(b'{"path": 5, "sha256": "ab"}\n', id="path-int"),
        pytest.param(b'{"path": ["x"], "sha256": "ab"}\n', id="path-list"),
        pytest.param(b'{"path": true, "sha256": "ab"}\n', id="path-bool"),
        pytest.param(b'{"path": "PATH", "sha256": 12345}\n', id="sha-int"),
        pytest.param(b'{"path": "PATH", "sha256": {"a": 1}}\n', id="sha-object"),
        pytest.param(b'{"path": "PATH", "sha256": ["ab"]}\n', id="sha-list"),
    ],
)
def test_k3_every_malformed_record_shape_refuses_and_never_raises(
    env, capsys, monkeypatch, record_bytes
):
    """K3 beyond round 1's four shapes: a record that is not UTF-8, or whose
    `path`/`sha256` is present but not a string, is still "a record that
    exists but cannot be read": one ERROR line, exit 1, never a traceback."""
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", "claude-code", dd)
    _commit(wt, "src/w.py", "w\n", "work")
    rec_path = dispatch._settings_digest_record_path(_FR, "dev")
    settings = json.loads(rec_path.read_text(encoding="utf-8"))["path"]
    rec_path.write_bytes(
        record_bytes.replace(b'"PATH"', json.dumps(settings).encode("utf-8"))
    )
    capsys.readouterr()
    rc = _finalize("dev", apply=True)  # a raise fails the test here
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and f"{_FR}.dev" in errors[0], out
    _no_egress(env, f"claude/dev-{_FR}")
    assert _finalize("dev", apply=False) == 0
    assert len(_lines(capsys.readouterr().out, "WOULD-REFUSE")) == 1


# ---------------------------------------------------------------------------
# Round 3: K3' probes beyond round 2's seven shapes
# ---------------------------------------------------------------------------


def _k3_record_bytes(shape: str, real: dict) -> bytes:
    path = json.dumps(real["path"])
    sha = json.dumps(real["sha256"])
    if shape == "deeply-nested":
        depth = 100_000  # far past the interpreter's recursion limit
        return ("[" * depth + "]" * depth).encode("ascii")
    if shape == "path-empty-sha-valid":
        return f'{{"path": "", "sha256": {sha}}}\n'.encode()
    if shape == "sha-empty-string":
        return f'{{"path": {path}, "sha256": ""}}\n'.encode()
    if shape == "json-string":
        return b'"abc"\n'
    if shape == "raw-nul-byte":
        return f'{{"path": {path}, "sha256": {sha}}}'.encode().replace(
            b'"sha256"', b'"sha\x00256"'
        )
    if shape == "escaped-nul-in-path":
        return f'{{"path": "a\u0000b", "sha256": {sha}}}\n'.encode()
    if shape == "trailing-nul-byte":
        return f'{{"path": {path}, "sha256": {sha}}}\n\x00'.encode()
    raise AssertionError(shape)


# covers hub-tooling FR-0015:AC-4
@pytest.mark.parametrize(
    "shape",
    [
        "deeply-nested",
        "path-empty-sha-valid",
        "sha-empty-string",
        "json-string",
        "raw-nul-byte",
        "escaped-nul-in-path",
        "trailing-nul-byte",
    ],
)
def test_k3prime_more_malformed_record_shapes_refuse_and_never_raise(
    env, capsys, monkeypatch, shape
):
    """K3': a pathologically nested record (RecursionError), an empty `path`
    beside a valid digest, an empty `sha256`, a bare JSON string, and NUL
    bytes (raw, escaped inside `path`, trailing) each refuse with exactly one
    ERROR line, exit 1, no egress, and never a traceback."""
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", "claude-code", dd)
    _commit(wt, "src/w.py", "w\n", "work")
    rec_path = dispatch._settings_digest_record_path(_FR, "dev")
    real = json.loads(rec_path.read_text(encoding="utf-8"))
    rec_path.write_bytes(_k3_record_bytes(shape, real))
    capsys.readouterr()
    rc = _finalize("dev", apply=True)  # a raise fails the test here
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and f"{_FR}.dev" in errors[0], out
    assert "Traceback" not in out
    _no_egress(env, f"claude/dev-{_FR}")
    assert _finalize("dev", apply=False) == 0
    assert len(_lines(capsys.readouterr().out, "WOULD-REFUSE")) == 1


# covers hub-tooling FR-0015:AC-4
def test_k3prime_violation_helper_returns_a_string_for_every_shape_and_none_when_absent(
    env, monkeypatch
):
    """Direct call: every K3/K3' shape yields a one-line cause (a str with no
    newline), never an exception; deleting the record yields None."""
    dd = env.repo / "_dispatch"
    wt = _spawn(env, monkeypatch, "dev", "claude-code", dd)
    _commit(wt, "src/w.py", "w\n", "work")
    rec_path = dispatch._settings_digest_record_path(_FR, "dev")
    original = rec_path.read_bytes()
    real = json.loads(original.decode("utf-8"))
    assert dispatch._finalize_settings_digest_violation(_FR, "dev") is None
    for shape in (
        "deeply-nested",
        "path-empty-sha-valid",
        "sha-empty-string",
        "json-string",
        "raw-nul-byte",
        "escaped-nul-in-path",
        "trailing-nul-byte",
    ):
        rec_path.write_bytes(_k3_record_bytes(shape, real))
        cause = dispatch._finalize_settings_digest_violation(_FR, "dev")
        assert isinstance(cause, str) and cause, shape
        assert "\n" not in cause, (shape, cause)
    rec_path.unlink()
    assert dispatch._finalize_settings_digest_violation(_FR, "dev") is None
