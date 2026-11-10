"""Reviewer tests for FR-0013 — the post-approve half: an approve fast-forwards
the implementation branch onto the Reviewer's tip and pushes it (AC-1); the
maintainer footprint check exempts Reviewer-landed paths by commit provenance
and `specs/_metrics/**` unconditionally (AC-5); a declared `--allow-crossing`
glob is exempted only when its diff is provably content-free (AC-6); a branch
behind `origin/main` is warned about, or merged-and-revalidated behind
`--revalidate` and automatically inside `wave` when a dependency merged this
run (AC-7); `wave --rounds` defaults to 2 (AC-8); dry-run previews every new
step and mutates nothing (AC-9); and no history is rewritten while existing
behaviour and the PR metrics records are preserved (AC-10).

The Reviewer-artifact half (AC-2, AC-3, AC-4) is in
`test_dispatch_review_artifact.py`.

Harness: `dispatch.py` is loaded by path with `REPO_ROOT` / `SPECS_DIR` /
`DISPATCH_DIR` pointed at a **real temporary git repository** that has a real
**bare `origin`** next to it, so `_push_branch` runs for real (fast-forward
only, into the bare) and every test can assert what the remote received.
Only `gh` leaves the machine, so `subprocess.run` is wrapped to intercept
`gh ...` argv with canned answers and pass every git call through unchanged;
`_gh_preflight` and `_repo_nwo` are stubbed. `gh` is never invoked for real.

The "pre-FR dispatcher" the bite checks run against is loaded from
`git show <pre-FR ref>:template/scripts/dispatch.py` (the hub commit FR-0013
branched from); inside a bootstrapped project that object does not exist and
those checks skip.

Coverage annotations are written `# covers hub-tooling FR-0013:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_finalize.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import ast
import contextlib
import functools
import importlib.util
import inspect
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
# The hub commit FR-0013 branched from (`main` after FR-0014 merged).
_PRE_FR_REF = "d1926ee"
_FR = "FR-0001"
_DEP = "FR-0002"
_OTHER = "FR-0003"

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


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0013_pa")


@functools.lru_cache(maxsize=1)
def _pre_fr_source() -> bytes | None:
    hub_root = _TEMPLATE_DIR.parent
    proc = _REAL_RUN(
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
    d = tmp_path_factory.mktemp("pre_fr0013_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0013_pa")


# The round-1 implementation of this FR (`1cad878`): AC-5(a) by ancestry of
# `claude/rev-<FR>` (withdrawn by DEC-0009) and a rev leg that names the
# Developer's branch and record only (before AC-11). The K1 and AC-11 bite
# checks load it so the round-2 pins are proven discriminating.
_ROUND1_REF = "1cad878"


@functools.lru_cache(maxsize=1)
def _round1_source() -> bytes | None:
    proc = _REAL_RUN(
        [
            "git",
            "-C",
            str(_TEMPLATE_DIR.parent),
            "show",
            f"{_ROUND1_REF}:template/scripts/dispatch.py",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


@pytest.fixture(scope="session")
def round1_dispatch(tmp_path_factory):
    src = _round1_source()
    if src is None:
        pytest.skip(f"round-1 dispatch.py ({_ROUND1_REF}) not reachable")
    d = tmp_path_factory.mktemp("round1_fr0013_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_round1_fr0013_pa")


# ---------------------------------------------------------------------------
# Real-git fixture: a primary repo with a bare `origin`
# ---------------------------------------------------------------------------


def _fr_md(
    fr_id: str,
    owns: tuple[str, ...] = ("src/**",),
    depends_on: tuple[str, ...] = (),
    status: str = "ready",
) -> str:
    owns_yaml = "[" + ", ".join(f'"{o}"' for o in owns) + "]"
    deps_yaml = "[" + ", ".join(depends_on) + "]"
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: {deps_yaml}
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


def _make_repo(
    tmp_path: Path, specs: dict[str, str] | None = None
) -> tuple[Path, Path]:
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
    specs = specs or {_FR: _fr_md(_FR)}
    for fr_id, text in specs.items():
        _write(repo / "specs" / f"{fr_id}-synthetic.md", text)
    _write(
        repo / ".gitignore",
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\nPR_BODY.md\n",
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


def _worktree(repo: Path, role: str, base: str = "main", fr_id: str = _FR) -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{fr_id}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{fr_id}", str(wt), base)
    if role in ("dev", "mnt", "bkf"):
        _write(
            wt / "PR_BODY.md", f"# {fr_id} ({role})" + chr(10)
        )  # gitignored; the PR-opening roles need it
    return wt


def _commit(wt: Path, rel: str, content: str | bytes, msg: str) -> str:
    _write(wt / rel, content)
    _git(wt, "add", rel)
    _git(wt, "commit", "-q", "-m", msg)
    return _git(wt, "rev-parse", "HEAD")


def _rev_log(repo: Path, text: str, fr_id: str = _FR) -> None:
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
        {"type": "result", "subtype": "success"},
    ]
    _write(
        repo / "_dispatch" / f"{fr_id}.rev.log",
        "\n".join(json.dumps(ln) for ln in lines) + "\n",
    )


def _parents(repo: Path, ref: str) -> list[str]:
    return _git(repo, "log", "-1", "--format=%P", ref).split()


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


def _records() -> list[dict]:
    d = metrics_log.METRICS_DIR
    if not d.exists():
        return []
    return [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


class _Env:
    """The temp repo, its bare origin, and every `gh` argv the code produced."""

    def __init__(self, repo: Path, bare: Path) -> None:
        self.repo = repo
        self.bare = bare
        self.gh: list[list[str]] = []
        self.pr_list_number: int | None = None

    def refs(self) -> str:
        return _git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)")

    def bare_refs(self) -> str:
        return _git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)")

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

    def snapshot(self, wts: list[Path]) -> str:
        parts = [self.refs(), self.bare_refs()]
        for wt in wts:
            parts.append(_git(wt, "rev-parse", "HEAD"))
            parts.append(_git(wt, "status", "--porcelain"))
            parts.append(_git(wt, "diff", "--cached"))
        dd = self.repo / "_dispatch"
        for p in sorted(dd.rglob("*")):
            if p.is_file():
                parts.append(f"{p.relative_to(dd)}:{p.read_bytes().hex()}")
        md = metrics_log.METRICS_DIR
        parts.append(
            ",".join(sorted(p.name for p in md.iterdir()))
            if md.exists()
            else "<no metrics>"
        )
        return "\n".join(parts)


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


def _route_gh(monkeypatch, env: _Env) -> None:
    """Intercept `gh` argv only; every git call stays real."""

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
                rows = [{"number": env.pr_list_number}] if env.pr_list_number else []
                return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", routed)


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, repo, tmp_path)
    e = _Env(repo, bare)
    _route_gh(monkeypatch, e)
    return e


def _finalize(role: str, apply: bool = True, draft: bool = True, **kw) -> int:
    adapter = dispatch.get_adapter("claude-code") if role == "rev" else None
    return dispatch.cmd_finalize(
        _FR, role, apply=apply, draft=draft, adapter=adapter, **kw
    )


def _impl_pr_record(role: str = "dev", pr_number: int = 7, **extra) -> None:
    """The implementation role's PR record, `_dispatch/<FR>.<role>.pr.json`,
    as that role's own finalize would have written it. AC-11: the rev leg
    resolves the record by the implementation role (`dev`, else `mnt`), so
    a mnt scenario must carry a *mnt* record — a dev-keyed one is exactly
    the accident round 1's E2 named."""
    dispatch._save_pr_record(
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


def _dev_pr_record(pr_number: int = 7, **extra) -> None:
    _impl_pr_record("dev", pr_number, **extra)


def _approve_scenario(env: _Env, impl_role: str = "dev") -> tuple[Path, Path]:
    """Implementation branch with one commit (pushed to origin); a Reviewer
    branch off its tip carrying a test and its own committed REVIEW.md; an
    approve in the rev log; a parent PR record under `impl_role`."""
    impl_wt = _worktree(env.repo, impl_role)
    _commit(impl_wt, "src/thing.py", "print('thing')\n", "feat: impl work")
    _git(env.repo, "push", "-q", "-u", "origin", f"claude/{impl_role}-{_FR}")
    rev_wt = _worktree(env.repo, "rev", base=f"claude/{impl_role}-{_FR}")
    _commit(
        rev_wt,
        "tests/test_ac1.py",
        f"# @{'covers'} {_FR}:AC-1\n",
        "test: reviewer tests",
    )
    _commit(
        rev_wt, "REVIEW.md", "## Approve\n\nreviewer's own\n", "reviewer wrote its own"
    )
    _rev_log(env.repo, "## Approve\n\nAll ACs covered.")
    _impl_pr_record(impl_role)
    return impl_wt, rev_wt


# ---------------------------------------------------------------------------
# AC-1: an approve fast-forwards the implementation branch and pushes it
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0013:AC-1
@pytest.mark.parametrize("impl_role", ["dev", "mnt"])
def test_approve_fast_forwards_the_implementation_branch_onto_the_rev_tip_and_pushes(
    env, capsys, impl_role
):
    impl_wt, _rev_wt = _approve_scenario(env, impl_role)
    impl_branch, rev_branch = f"claude/{impl_role}-{_FR}", f"claude/rev-{_FR}"
    old_impl = _git(env.repo, "rev-parse", impl_branch)
    assert env.bare_sha(impl_branch) == old_impl

    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    new_impl = _git(env.repo, "rev-parse", impl_branch)
    rev_tip = _git(env.repo, "rev-parse", rev_branch)
    assert new_impl == rev_tip != old_impl
    assert len(_parents(env.repo, impl_branch)) == 1  # fast-forward, not a merge commit
    assert _git(impl_wt, "rev-parse", "HEAD") == new_impl  # the worktree moved too
    assert _git(impl_wt, "status", "--porcelain") == ""
    assert env.bare_sha(impl_branch) == new_impl  # pushed for real
    assert env.bare_sha(rev_branch) == rev_tip
    ff = _lines(out, "FF-PUSHED")
    assert len(ff) == 1
    assert impl_branch in ff[0] and rev_branch in ff[0] and new_impl[:7] in ff[0]
    assert dispatch._load_pr_record(_FR, impl_role)["head_sha"] == new_impl
    assert any(c[:3] == ["gh", "pr", "review"] and "--approve" in c for c in env.gh)
    assert not any(c[:3] == ["gh", "pr", "create"] for c in env.gh)
    # The Reviewer's commits are now on the PR head.
    assert "tests/test_ac1.py" in _git(
        env.repo, "ls-tree", "-r", "--name-only", impl_branch
    )


# covers hub-tooling FR-0013:AC-1
def test_dev_branch_is_preferred_over_mnt_when_both_exist(env, capsys):
    """Adversarial: with both branches present the target is `dev`; the mnt
    branch is neither merged nor pushed."""
    _worktree(env.repo, "mnt")
    _commit(env.repo / ".claude" / "worktrees" / f"mnt-{_FR}", "src/m.py", "m\n", "mnt")
    _approve_scenario(env, "dev")
    mnt_before = _git(env.repo, "rev-parse", f"claude/mnt-{_FR}")
    assert dispatch._implementation_branch_for_fr(_FR) == (f"claude/dev-{_FR}", "dev")
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert f"FF-PUSHED    claude/dev-{_FR}" in out
    assert _git(env.repo, "rev-parse", f"claude/mnt-{_FR}") == mnt_before
    assert env.bare_sha(f"claude/mnt-{_FR}") is None


# covers hub-tooling FR-0013:AC-1
def test_already_current_and_ahead_implementation_branches_get_one_note_and_no_push(
    env, capsys
):
    dev_wt, _rev_wt = _approve_scenario(env, "dev")
    dev_branch, rev_branch = f"claude/dev-{_FR}", f"claude/rev-{_FR}"
    # First approve fast-forwards; a re-run finds dev already at the rev tip.
    assert _finalize("rev") == 0, capsys.readouterr().out
    capsys.readouterr()
    bare_before = env.bare_refs()
    assert _finalize("rev") == 0
    out = capsys.readouterr().out
    notes = [
        n for n in _lines(out, "NOTE") if "adds no commits" not in n
    ]  # FR-0006's own NOTE aside
    assert len(notes) == 1 and "already at" in notes[0] and rev_branch in notes[0]
    assert "FF-PUSHED" not in out and "ERROR" not in out
    assert env.bare_refs() == bare_before
    # Ahead: dev gains a commit past the rev tip; rev is an ancestor of dev.
    _commit(dev_wt, "src/more.py", "more\n", "feat: more")
    ahead_sha = _git(env.repo, "rev-parse", dev_branch)
    assert _finalize("rev") == 0
    out = capsys.readouterr().out
    notes = [n for n in _lines(out, "NOTE") if "adds no commits" not in n]
    assert (
        len(notes) == 1
        and "ahead" in notes[0]
        and "nothing to fast-forward" in notes[0]
    )
    assert _git(env.repo, "rev-parse", dev_branch) == ahead_sha
    assert env.bare_sha(dev_branch) != ahead_sha  # the NOTE case pushes nothing


# covers hub-tooling FR-0013:AC-1
def test_diverged_branches_are_refused_never_merged_or_forced(env, capsys):
    """Adversarial: dev moved on after the Reviewer branched. Nothing may
    merge, rebase or force-push; the dev branch, its worktree and the bare
    origin are exactly as before, and the review itself was still posted."""
    dev_wt, _rev_wt = _approve_scenario(env, "dev")
    dev_branch = f"claude/dev-{_FR}"
    diverged = _commit(dev_wt, "src/late.py", "late\n", "feat: late dev commit")
    _git(env.repo, "push", "-q", "origin", dev_branch)
    rc = _finalize("rev")
    out = capsys.readouterr().out
    assert rc == 1, out  # DEC-0009 / E3: the terminal state was not reached
    errors = _lines(out, "ERROR")
    assert (
        len(errors) == 1
        and "diverged" in errors[0]
        and "refusing to fast-forward" in errors[0]
    )
    assert "FF-PUSHED" not in out
    assert _git(env.repo, "rev-parse", dev_branch) == diverged
    assert len(_parents(env.repo, dev_branch)) == 1
    assert (
        _git(dev_wt, "rev-parse", "HEAD") == diverged
        and _git(dev_wt, "status", "--porcelain") == ""
    )
    assert env.bare_sha(dev_branch) == diverged
    assert any(c[:3] == ["gh", "pr", "review"] for c in env.gh)
    assert "head_sha" not in (dispatch._load_pr_record(_FR, "dev") or {})


# covers hub-tooling FR-0013:AC-1
def test_request_changes_verdict_leaves_the_implementation_branch_alone(env, capsys):
    _approve_scenario(env, "dev")
    _rev_log(env.repo, "## Request changes\n\n- AC-1 wrong")
    dev_before = _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    bare_before = env.bare_sha(f"claude/dev-{_FR}")
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "FF-PUSHED" not in out and "WOULD-FF-PUSH" not in out
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == dev_before
    assert env.bare_sha(f"claude/dev-{_FR}") == bare_before
    assert any(
        "--request-changes" in c for c in env.gh if c[:3] == ["gh", "pr", "review"]
    )
    assert "head_sha" not in dispatch._load_pr_record(_FR, "dev")


# covers hub-tooling FR-0013:AC-1
def test_no_implementation_branch_is_one_note_and_not_an_error(env, capsys):
    rev_wt = _worktree(env.repo, "rev")  # off main: no dev, no mnt
    _commit(rev_wt, "tests/test_ac1.py", "# t\n", "test: reviewer tests")
    _rev_log(env.repo, "## Approve\n\nfine")
    _dev_pr_record()
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    notes = [ln for ln in _lines(out, "NOTE") if "no implementation branch" in ln]
    assert (
        len(notes) == 1
        and f"claude/dev-{_FR}" in notes[0]
        and f"claude/mnt-{_FR}" in notes[0]
    )
    assert "ERROR" not in out and "FF-PUSHED" not in out


# covers hub-tooling FR-0013:AC-1
def test_dirty_implementation_worktree_blocks_the_fast_forward_without_touching_it(
    env, capsys
):
    """Adversarial: an uncommitted tracked edit in the dev worktree must not
    be merged over (git would refuse or clobber); the dispatcher refuses first."""
    dev_wt, _rev_wt = _approve_scenario(env, "dev")
    (dev_wt / "src" / "thing.py").write_bytes(b"print('edited, not staged')\n")
    dev_before = _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    rc = _finalize("rev")
    out = capsys.readouterr().out
    assert rc == 1, out  # DEC-0009 / E3
    errors = _lines(out, "ERROR")
    assert (
        len(errors) == 1
        and "uncommitted tracked changes" in errors[0]
        and "src/thing.py" in errors[0]
    )
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == dev_before
    assert env.bare_sha(f"claude/dev-{_FR}") == dev_before
    assert (
        dev_wt / "src" / "thing.py"
    ).read_bytes() == b"print('edited, not staged')\n"


# covers hub-tooling FR-0013:AC-1
def test_approve_pushes_even_when_the_dev_pr_opened_draft_exempt(env, capsys):
    """Open-question default: a draft PR whose gate was red-but-tolerated
    still receives the Reviewer's commits."""
    _approve_scenario(env, "dev")
    _dev_pr_record(
        gate_warning_at_finalize="Deploy gate FAILED (synthetic)", draft=True
    )
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert len(_lines(out, "FF-PUSHED")) == 1
    assert env.bare_sha(f"claude/dev-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/rev-{_FR}"
    )


# covers hub-tooling FR-0013:AC-1
def test_shared_ff_only_helper_keeps_the_fr0006_rev_sync_messages(
    env, pre_fr_dispatch, monkeypatch, tmp_path
):
    """`_fast_forward_rev_worktree` (FR-0006) now goes through `_ff_only_merge`;
    on the same states — a fast-forward git refuses (untracked collision) and
    one it performs — the pre-FR and current dispatchers return the same
    (ok, message)."""
    _point(monkeypatch, pre_fr_dispatch, env.repo, tmp_path)

    def run(mod, fr_id: str):
        dev_wt = _worktree(env.repo, "dev", fr_id=fr_id)
        _commit(dev_wt, "src/a.py", "a\n", "dev a")
        rev_wt = _worktree(env.repo, "rev", base=f"claude/dev-{fr_id}", fr_id=fr_id)
        _commit(dev_wt, "src/b.py", "b\n", "dev b")
        _write(rev_wt / "src" / "b.py", "untracked collision\n")
        failed = mod._fast_forward_rev_worktree(fr_id, rev_wt)
        (rev_wt / "src" / "b.py").unlink()
        ok = mod._fast_forward_rev_worktree(fr_id, rev_wt)

        def norm(s: str) -> str:
            s = s.replace(fr_id, "<FR>").replace(str(rev_wt), "<wt>")
            return re.sub(r"\b[0-9a-f]{7}\b", "<sha>", s)

        return (failed[0], norm(failed[1]), ok[0], norm(ok[1]))

    new = run(dispatch, _FR)
    old = run(pre_fr_dispatch, _DEP)
    assert new == old
    assert (
        new[0] is False
        and "failed:" in new[1]
        and new[2] is True
        and "fast-forwarded" in new[3]
    )


# covers hub-tooling FR-0013:AC-1
# covers hub-tooling FR-0013:AC-10
def test_pre_fr_dispatcher_left_the_dev_branch_behind_on_approve(
    env, pre_fr_dispatch, monkeypatch, tmp_path, capsys
):
    """Bite check: the same approve under the pre-FR dispatcher moves neither
    the dev branch nor the bare origin — so the AC-1 tests above are testing
    the new behaviour, not the fixture."""
    _approve_scenario(env, "dev")
    _point(monkeypatch, pre_fr_dispatch, env.repo, tmp_path)
    monkeypatch.setattr(pre_fr_dispatch.subprocess, "run", dispatch.subprocess.run)
    dev_before = _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    adapter = pre_fr_dispatch.get_adapter("claude-code")
    assert (
        pre_fr_dispatch.cmd_finalize(
            _FR, "rev", apply=True, draft=True, adapter=adapter
        )
        == 0
    ), capsys.readouterr().out
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == dev_before
    assert env.bare_sha(f"claude/dev-{_FR}") == dev_before
    assert "FF-PUSHED" not in capsys.readouterr().out


# covers hub-tooling FR-0013:AC-1
@pytest.mark.parametrize("shape", ["diverged", "dirty-worktree", "worktree-missing"])
def test_refused_fast_forward_exits_one_with_the_review_posted_and_says_so(
    env, capsys, shape
):
    """DEC-0009 / E3: every refusal shape is one ERROR that names the
    already-posted review (so a re-run is understood to re-post it), a
    non-zero exit, the review record written, the implementation branch,
    its worktree and the bare origin untouched, and no `ff_commits`."""
    dev_wt, _rev_wt = _approve_scenario(env, "dev")
    dev_branch = f"claude/dev-{_FR}"
    if shape == "diverged":
        _commit(dev_wt, "src/late.py", "late\n", "feat: late dev commit")
        _git(env.repo, "push", "-q", "origin", dev_branch)
    elif shape == "dirty-worktree":
        (dev_wt / "src" / "thing.py").write_bytes(b"edited, not staged\n")
    else:
        _git(env.repo, "worktree", "remove", "--force", str(dev_wt))
        assert not dev_wt.exists()
    dev_before = _git(env.repo, "rev-parse", dev_branch)
    rc = _finalize("rev")
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1, out
    assert "the review is already posted (#7)" in errors[0]
    assert len(_lines(out, "REVIEW-POSTED")) == 1 and "FF-PUSHED" not in out
    reviews = [c for c in env.gh if c[:3] == ["gh", "pr", "review"]]
    assert len(reviews) == 1 and "7" in reviews[0] and "--approve" in reviews[0]
    assert _git(env.repo, "rev-parse", dev_branch) == dev_before
    assert env.bare_sha(dev_branch) == dev_before
    assert env.bare_sha(f"claude/rev-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/rev-{_FR}"
    )
    dev_record = dispatch._load_pr_record(_FR, "dev")
    assert "ff_commits" not in dev_record and "head_sha" not in dev_record
    assert dispatch._load_pr_record(_FR, "rev")["verdict"] == "approve"
    # A re-run re-posts (FR-0006's idempotency model) and refuses again.
    assert _finalize("rev") == 1
    out = capsys.readouterr().out
    assert len([c for c in env.gh if c[:3] == ["gh", "pr", "review"]]) == 2
    assert "already posted (#7)" in "".join(_lines(out, "ERROR"))


# covers hub-tooling FR-0013:AC-1
# covers hub-tooling FR-0013:AC-9
def test_dry_run_refusal_carries_no_posted_review_suffix(env, capsys):
    """Adversarial for the E3 wording: in dry-run nothing was posted, so the
    refusal line must not claim a review was."""
    dev_wt, _rev_wt = _approve_scenario(env, "dev")
    _commit(dev_wt, "src/late.py", "late\n", "feat: late dev commit")
    before = env.snapshot([dev_wt])
    _finalize("rev", apply=False)
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "diverged" in errors[0]
    assert "already posted" not in out and "WOULD-FF-PUSH" not in out
    assert env.snapshot([dev_wt]) == before and env.gh == []


# covers hub-tooling FR-0013:AC-1
# covers hub-tooling FR-0013:AC-5
@pytest.mark.parametrize("impl_role", ["dev", "mnt"])
def test_ff_commits_is_exactly_the_fast_forwarded_range_and_unions_across_rounds(
    env, capsys, impl_role
):
    """The implementation role's PR record gains `ff_commits` = the full
    SHAs of `<impl-tip>..<rev-tip>` at the moment of the merge; a round-2
    approve unions round 1's in; the nothing-to-do and refused cases leave
    the key exactly as it was."""
    impl_wt, rev_wt = _approve_scenario(env, impl_role)
    impl_branch, rev_branch = f"claude/{impl_role}-{_FR}", f"claude/rev-{_FR}"
    impl_before = _git(env.repo, "rev-parse", impl_branch)
    round1 = _git(env.repo, "rev-list", f"{impl_before}..{rev_branch}").split()
    assert len(round1) == 2 and all(len(s) == 40 for s in round1)
    assert "ff_commits" not in dispatch._load_pr_record(_FR, impl_role)
    assert _finalize("rev") == 0, capsys.readouterr().out
    capsys.readouterr()
    # DEC-0024: round 1 is taken after finalize, so it includes the filing commit.
    round1 = _git(env.repo, "rev-list", f"{impl_before}..{rev_branch}").split()
    assert len(round1) == 3
    record = dispatch._load_pr_record(_FR, impl_role)
    assert record["ff_commits"] == sorted(round1)
    assert record["pr_number"] == 7 and record["branch"] == impl_branch  # rest intact
    assert not (
        env.repo
        / "_dispatch"
        / f"{_FR}.{'mnt' if impl_role == 'dev' else 'dev'}.pr.json"
    ).exists()
    # Nothing to do (already at the tip): the key is untouched.
    assert _finalize("rev") == 0
    capsys.readouterr()
    assert dispatch._load_pr_record(_FR, impl_role)["ff_commits"] == sorted(round1)
    # Round 2: the Reviewer adds a commit; the approve unions it in.
    round2_sha = _commit(rev_wt, "tests/test_ac2.py", "# round 2\n", "test: round 2")
    assert _finalize("rev") == 0, capsys.readouterr().out
    capsys.readouterr()
    assert dispatch._load_pr_record(_FR, impl_role)["ff_commits"] == sorted(
        [*round1, round2_sha]
    )
    assert _git(env.repo, "rev-parse", impl_branch) == round2_sha
    # Refused (diverged — both moved on): the key is left as it was.
    _commit(impl_wt, "src/late.py", "late\n", "feat: late")
    _git(env.repo, "push", "-q", "origin", impl_branch)
    _commit(rev_wt, "tests/test_ac3.py", "# round 3\n", "test: round 3")
    assert _finalize("rev") == 1
    capsys.readouterr()
    assert dispatch._load_pr_record(_FR, impl_role)["ff_commits"] == sorted(
        [*round1, round2_sha]
    )


# ---------------------------------------------------------------------------
# AC-5: footprint exemptions by commit provenance and for specs/_metrics/**
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _push_stubbed():
    """`_push_branch` swapped for a recording no-op for the duration, so a
    helper can run the dispatcher's real AC-1 step without touching the
    bare origin — every "nothing was pushed" assertion in the AC-5 tests
    keeps meaning what it says. Restored on exit, even on failure."""
    real = dispatch._push_branch
    pushed: list[str] = []

    def stub(branch: str) -> tuple[bool, str]:
        pushed.append(branch)
        return (True, "pushed (stub)")

    dispatch._push_branch = stub
    try:
        yield pushed
    finally:
        dispatch._push_branch = real


def _land_rev_through_dispatcher(env: _Env, impl_role: str) -> str:
    """Fast-forward `claude/<impl_role>-<FR>` onto `claude/rev-<FR>` through
    the dispatcher's own AC-1 step, `_ff_push_impl_onto_rev(apply=True)` —
    the only thing that writes the `ff_commits` provenance record AC-5(a)
    checks (DEC-0009). Never a hand `git merge --ff-only`, which lands the
    same tree with no record. The push inside the step is stubbed (see
    `_push_stubbed`). Returns the new implementation tip."""
    impl_branch, rev_branch = f"claude/{impl_role}-{_FR}", f"claude/rev-{_FR}"
    impl_before = _git(env.repo, "rev-parse", impl_branch)
    rev_tip = _git(env.repo, "rev-parse", rev_branch)
    brought_in = _git(env.repo, "rev-list", f"{impl_before}..{rev_tip}").split()
    sink = io.StringIO()
    with _push_stubbed() as pushed, contextlib.redirect_stdout(sink):
        assert dispatch._ff_push_impl_onto_rev(_FR, rev_branch, apply=True) is True
    assert pushed == [impl_branch], sink.getvalue()
    assert len(_lines(sink.getvalue(), "FF-PUSHED")) == 1, sink.getvalue()
    assert _git(env.repo, "rev-parse", impl_branch) == rev_tip
    record = dispatch._load_pr_record(_FR, impl_role)
    assert record["head_sha"] == rev_tip
    assert record["ff_commits"] == sorted(brought_in) and brought_in
    return rev_tip


def _mnt_with_rev_landed_tests(
    env: _Env, extra_mnt_files: dict[str, str] | None = None
) -> Path:
    """A mnt branch (owns src/**) carrying an owned path and a metrics append,
    plus whatever `extra_mnt_files` the maintainer committed; a Reviewer
    branch off the mnt tip adds tests/**; mnt is fast-forwarded onto it
    through the dispatcher's AC-1 step (`_land_rev_through_dispatcher`), so
    the `ff_commits` record names exactly the Reviewer's commit."""
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned work")
    for rel, content in (extra_mnt_files or {}).items():
        _commit(mnt_wt, rel, content, f"chore: {rel}")
    _commit(
        mnt_wt, "specs/_metrics/2026-09.ndjson", '{"kind": "gate.run"}\n', "gate append"
    )
    rev_wt = _worktree(env.repo, "rev", base=f"claude/mnt-{_FR}")
    _commit(
        rev_wt,
        "tests/test_ac1.py",
        f"# @{'covers'} {_FR}:AC-1\n",
        "test: reviewer tests",
    )
    _land_rev_through_dispatcher(env, "mnt")
    return mnt_wt


# covers hub-tooling FR-0013:AC-5
def test_reviewer_landed_tests_and_metrics_append_are_exempt_with_one_note_each(
    env, capsys
):
    _mnt_with_rev_landed_tests(env)
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    notes = _lines(out, "NOTE")
    assert len(notes) == 2
    assert any(
        "tests/test_ac1.py" in n and "AC-5a" in n and f"claude/rev-{_FR}" in n
        for n in notes
    )
    assert any("specs/_metrics/2026-09.ndjson" in n and "AC-5b" in n for n in notes)
    assert "ERROR" not in out and "WOULD-REFUSE" not in out and "WOULD-FINALIZE" in out
    # Apply: pushed and a PR opened.
    assert _finalize("mnt", apply=True) == 0
    out = capsys.readouterr().out
    assert "PUSHED" in out and any(c[:3] == ["gh", "pr", "create"] for c in env.gh)
    assert env.bare_sha(f"claude/mnt-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/mnt-{_FR}"
    )


# covers hub-tooling FR-0013:AC-5
def test_unowned_source_file_still_refuses_after_the_reviewer_fast_forward(env, capsys):
    """The AC's own verification scenario: owned path + Reviewer-landed test +
    metrics append + an unowned source file the *maintainer* committed. Only
    the last one refuses. The unowned commit predates the Reviewer branch
    (the Reviewer worktree is created from the mnt tip, so it inherits it);
    provenance must not mistake inherited history for Reviewer-landed work."""
    _mnt_with_rev_landed_tests(env, {"src_outside/unowned.py": "BAD\n"})
    # `src_outside/` is outside `owns: ["src/**"]`.
    rc = _finalize("mnt", apply=True)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _lines(out, "ERROR")
    assert (
        len(errors) == 1
        and "src_outside/unowned.py" in errors[0]
        and "1 path(s)" in errors[0]
    )
    assert "tests/test_ac1.py" not in errors[0]
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0013:AC-5
def test_maintainer_writing_tests_directly_is_still_refused(env, capsys):
    """Adversarial for "provenance, not path pattern": the same `tests/**`
    path written by the maintainer, with a Reviewer branch present that does
    not carry that commit, is refused exactly as today."""
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    rev_wt = _worktree(env.repo, "rev", base=f"claude/mnt-{_FR}")
    _commit(rev_wt, "tests/test_ac1.py", "# rev\n", "test: reviewer tests")
    _commit(
        mnt_wt,
        "tests/test_sneaky.py",
        "# maintainer wrote this\n",
        "chore: sneaky test",
    )
    _finalize("mnt", apply=True)
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "tests/test_sneaky.py" in errors[0]
    assert "AC-5a" not in out and env.bare_sha(f"claude/mnt-{_FR}") is None


# covers hub-tooling FR-0013:AC-5
def test_mixed_provenance_on_one_path_is_not_exempt(env, capsys):
    """Adversarial: the Reviewer landed tests/test_ac1.py, then the maintainer
    edited the same file after the fast-forward. Every touching commit must
    come from the Reviewer branch; one maintainer commit poisons the path."""
    mnt_wt = _mnt_with_rev_landed_tests(env)
    _commit(mnt_wt, "tests/test_ac1.py", "# maintainer edit\n", "chore: edit the test")
    _finalize("mnt", apply=False)
    out = capsys.readouterr().out
    assert "tests/test_ac1.py exempt" not in out
    assert "specs/_metrics/2026-09.ndjson exempt" in out
    refusal = _lines(out, "outside")
    assert len(refusal) == 1 and "tests/test_ac1.py" in refusal[0]


# covers hub-tooling FR-0013:AC-5
def test_metrics_dir_is_exempt_without_a_reviewer_branch_but_a_lookalike_is_not(
    env, capsys
):
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    _commit(
        mnt_wt,
        "specs/_metrics/reports/2026-09.md",
        "report\n",
        "nested metrics artifact",
    )
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    assert "specs/_metrics/reports/2026-09.md exempt" in out and "AC-5b" in out
    # Prefix look-alike outside the directory is a real violation.
    _commit(mnt_wt, "specs/_metricsX.md", "x\n", "lookalike")
    _finalize("mnt", apply=False)
    out = capsys.readouterr().out
    assert "specs/_metricsX.md exempt" not in out
    assert any("specs/_metricsX.md" in ln for ln in _lines(out, "outside"))


# covers hub-tooling FR-0013:AC-5
# covers hub-tooling FR-0013:AC-10
def test_unowned_path_refusal_text_is_identical_to_the_pre_fr_dispatcher(
    env, pre_fr_dispatch, monkeypatch, tmp_path, capsys
):
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    _commit(mnt_wt, "docs/unowned.md", "x\n", "unowned")
    assert _finalize("mnt", apply=True) == 1
    new_err = _lines(capsys.readouterr().out, "ERROR")
    _point(monkeypatch, pre_fr_dispatch, env.repo, tmp_path)
    assert pre_fr_dispatch.cmd_finalize(_FR, "mnt", apply=True, draft=True) == 1
    old_err = _lines(capsys.readouterr().out, "ERROR")
    assert new_err == old_err and len(new_err) == 1 and "docs/unowned.md" in new_err[0]


# covers hub-tooling FR-0013:AC-5
def test_hand_merged_reviewer_branch_with_no_record_is_not_exempt(env, capsys):
    """DEC-0009: a Reviewer branch the *maintainer* fast-forwarded in by hand
    is not dispatcher-landed — there is no `ff_commits` record — so its
    paths are refused; ancestry of `claude/rev-<FR>` is not provenance. The
    metrics append is still exempt (AC-5b needs no record)."""
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned work")
    _commit(
        mnt_wt, "specs/_metrics/2026-09.ndjson", '{"kind": "gate.run"}\n', "gate append"
    )
    rev_wt = _worktree(env.repo, "rev", base=f"claude/mnt-{_FR}")
    _commit(rev_wt, "tests/test_ac1.py", "# rev\n", "test: reviewer tests")
    _git(mnt_wt, "merge", "-q", "--ff-only", f"claude/rev-{_FR}")
    assert _git(env.repo, "rev-parse", f"claude/mnt-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/rev-{_FR}"
    )  # the exact shape the ancestry test exempted everything in
    assert dispatch._load_pr_record(_FR, "mnt") is None
    assert _finalize("mnt", apply=True) == 1
    out = capsys.readouterr().out
    assert "AC-5a" not in out
    assert "specs/_metrics/2026-09.ndjson exempt" in out and "AC-5b" in out
    refusal = _lines(out, "outside")
    assert len(refusal) == 1 and "tests/test_ac1.py" in refusal[0]
    assert "1 path(s)" in refusal[0]
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []
    # A record with no `ff_commits` key (the mnt PR opened, nothing
    # fast-forwarded yet) is the same refusal.
    _impl_pr_record("mnt", 55)
    assert _finalize("mnt", apply=False) == 1
    out = capsys.readouterr().out
    assert "AC-5a" not in out and "tests/test_ac1.py" in "".join(_lines(out, "outside"))


# covers hub-tooling FR-0013:AC-5
def test_maintainer_commit_after_the_fast_forward_is_not_exempt(env, capsys):
    """Adversarial: a path the maintainer committed *after* AC-1's
    fast-forward is not in `ff_commits`; the Reviewer-landed path next to it
    still is."""
    mnt_wt = _mnt_with_rev_landed_tests(env)
    _commit(mnt_wt, "src_outside/late.py", "late\n", "chore: after the ff")
    assert _finalize("mnt", apply=True) == 1
    out = capsys.readouterr().out
    assert "tests/test_ac1.py exempt" in out and "AC-5a" in out
    refusal = _lines(out, "outside")
    assert (
        len(refusal) == 1
        and "src_outside/late.py" in refusal[0]
        and "1 path(s)" in refusal[0]
    )
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0013:AC-5
def test_provenance_is_read_from_the_implementation_roles_record_only(env, capsys):
    """Adversarial: a stale `<FR>.dev.pr.json` carrying the right SHAs under
    `ff_commits` does not vouch for a mnt branch — the record consulted is
    the implementation role's (`mnt` here), which has none."""
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned work")
    rev_wt = _worktree(env.repo, "rev", base=f"claude/mnt-{_FR}")
    landed = _commit(rev_wt, "tests/test_ac1.py", "# rev\n", "test: reviewer tests")
    _git(mnt_wt, "merge", "-q", "--ff-only", f"claude/rev-{_FR}")
    _impl_pr_record("dev", 7, ff_commits=[landed])
    assert dispatch._implementation_branch_for_fr(_FR) == (f"claude/mnt-{_FR}", "mnt")
    assert _finalize("mnt", apply=False) == 1
    out = capsys.readouterr().out
    assert "AC-5a" not in out and "tests/test_ac1.py" in "".join(_lines(out, "outside"))
    # ... and once the mnt record carries it, the same branch is exempt.
    _impl_pr_record("mnt", 55, ff_commits=[landed])
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    assert "tests/test_ac1.py exempt" in out and "WOULD-FINALIZE" in out


# covers hub-tooling FR-0013:AC-5
def test_round1_ancestry_provenance_exempted_the_inherited_unowned_file(
    env, round1_dispatch, monkeypatch, tmp_path, capsys
):
    """K1 bite check: the AC's own four-item scenario, driven through the
    round-1 implementation (`1cad878`, provenance = ancestry of
    `claude/rev-<FR>`), exempts the maintainer's inherited unowned file and
    would push — the hole DEC-0009 closed. The round-2 dispatcher refuses it
    (`test_unowned_source_file_still_refuses_after_the_reviewer_fast_forward`)."""
    _mnt_with_rev_landed_tests(env, {"src_outside/unowned.py": "BAD\n"})
    _point(monkeypatch, round1_dispatch, env.repo, tmp_path)
    monkeypatch.setattr(round1_dispatch.subprocess, "run", dispatch.subprocess.run)
    assert round1_dispatch.cmd_finalize(_FR, "mnt", apply=False, draft=True) == 0
    old = capsys.readouterr().out
    assert "src_outside/unowned.py exempt" in old and "WOULD-FINALIZE" in old
    assert "ERROR" not in old
    _point(monkeypatch, dispatch, env.repo, tmp_path)
    assert _finalize("mnt", apply=False) == 1
    new = capsys.readouterr().out
    assert "src_outside/unowned.py exempt" not in new
    assert "src_outside/unowned.py" in "".join(_lines(new, "outside"))


# ---------------------------------------------------------------------------
# AC-6: --allow-crossing is verified, not trusted
# ---------------------------------------------------------------------------

_CROSSING = ".claude/commands/**"


def _mnt_with_crossing(
    env: _Env, content: bytes, extra: dict[str, str] | None = None
) -> Path:
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    _commit(mnt_wt, ".claude/commands/synthetic.md", content, "chore: renormalise")
    for rel, text in (extra or {}).items():
        _commit(mnt_wt, rel, text, f"chore: {rel}")
    return mnt_wt


# covers hub-tooling FR-0013:AC-6
@pytest.mark.parametrize(
    "content",
    [
        b"line one\r\nline two\r\n",
        b"line one   \nline two\t\n",
        b"line one\r\nline two   \r\n",
    ],
    ids=["crlf-only", "whitespace-only", "both"],
)
def test_content_free_crossing_is_allowed_with_the_glob_and_file_count(
    env, capsys, content
):
    _mnt_with_crossing(env, content)
    assert _finalize("mnt", apply=False, allow_crossing=[_CROSSING]) == 0
    out = capsys.readouterr().out
    allowed = _lines(out, "WOULD-ALLOW-CROSSING")
    assert (
        len(allowed) == 1
        and repr(_CROSSING) in allowed[0]
        and "(1 file(s))" in allowed[0]
    )
    assert "ERROR" not in out and "WOULD-REFUSE" not in out and "WOULD-FINALIZE" in out
    assert _finalize("mnt", apply=True, allow_crossing=[_CROSSING]) == 0
    out = capsys.readouterr().out
    allowed = _lines(out, "CROSSING-ALLOWED")
    assert (
        len(allowed) == 1
        and repr(_CROSSING) in allowed[0]
        and "(1 file(s))" in allowed[0]
    )
    assert env.bare_sha(f"claude/mnt-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/mnt-{_FR}"
    )


# covers hub-tooling FR-0013:AC-6
def test_crossing_with_one_real_edit_under_the_same_glob_is_refused(env, capsys):
    _mnt_with_crossing(env, b"line one\r\nline two changed\r\n")
    assert _finalize("mnt", apply=True, allow_crossing=[_CROSSING]) == 1
    out = capsys.readouterr().out
    crossing_errors = [e for e in _lines(out, "ERROR") if _CROSSING in e]
    assert len(crossing_errors) == 1 and "carries content" in crossing_errors[0]
    # ... and it refuses as it would without the flag: the standard refusal.
    refusal = _lines(out, "outside")
    assert len(refusal) == 1 and ".claude/commands/synthetic.md" in refusal[0]
    assert "CROSSING-ALLOWED" not in out
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0013:AC-6
def test_crossing_that_adds_a_new_file_under_the_glob_is_refused(env, capsys):
    """Adversarial: a brand-new file is all content — no line-ending trick
    makes an addition diff empty."""
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    _commit(mnt_wt, ".claude/commands/new.md", "\n\n", "chore: blank new file")
    assert _finalize("mnt", apply=True, allow_crossing=[_CROSSING]) == 1
    out = capsys.readouterr().out
    assert "carries content" in out and "CROSSING-ALLOWED" not in out


# covers hub-tooling FR-0013:AC-6
@pytest.mark.parametrize(
    "bad_glob", ["/abs/.claude/commands/**", "../hub/.claude/**", ".claude/../x/**", ""]
)
def test_malformed_crossing_glob_is_refused_by_the_footprint_rule(
    env, capsys, bad_glob
):
    _mnt_with_crossing(env, b"line one\r\nline two\r\n")
    assert _finalize("mnt", apply=True, allow_crossing=[bad_glob]) == 1
    out = capsys.readouterr().out
    invalid = [e for e in _lines(out, "ERROR") if "invalid" in e]
    assert (
        len(invalid) == 1
        and "--allow-crossing" in invalid[0]
        and repr(bad_glob) in invalid[0]
    )
    assert "ALLOW-CROSSING" not in out  # no exemption from a glob that never validated
    assert env.bare_sha(f"claude/mnt-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0013:AC-6
def test_glob_matching_nothing_is_one_warn_and_no_exemption(env, capsys):
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/owned.py", "owned\n", "chore: owned")
    assert _finalize("mnt", apply=False, allow_crossing=["docs/**"]) == 0
    out = capsys.readouterr().out
    warns = [w for w in _lines(out, "WARN") if "docs/**" in w]
    assert len(warns) == 1 and "matches no changed path" in warns[0]
    assert "ALLOW-CROSSING" not in out and "WOULD-FINALIZE" in out


# covers hub-tooling FR-0013:AC-6
def test_flag_is_repeatable_and_an_allowed_crossing_never_covers_an_unrelated_violation(
    env, capsys
):
    """Adversarial: a legitimate content-free crossing beside an unowned
    source edit — the exemption is scoped to the glob's matches only."""
    _mnt_with_crossing(env, b"line one\r\nline two\r\n", {"docs/unowned.md": "x\n"})
    assert _finalize("mnt", apply=False, allow_crossing=[_CROSSING, "nothing/**"]) == 1
    out = capsys.readouterr().out
    assert len(_lines(out, "WOULD-ALLOW-CROSSING")) == 1
    assert len([w for w in _lines(out, "WARN") if "nothing/**" in w]) == 1
    refusal = _lines(out, "outside")
    assert len(refusal) == 1 and "docs/unowned.md" in refusal[0]
    assert ".claude/commands/synthetic.md" not in refusal[0]


# covers hub-tooling FR-0013:AC-6
def test_crossing_refusal_is_verified_from_committed_history_not_the_working_tree(
    env, capsys
):
    """Adversarial: reverting the real edit in the working tree without
    committing does not make the committed crossing content-free."""
    mnt_wt = _mnt_with_crossing(env, b"line one\r\nline two changed\r\n")
    (mnt_wt / ".claude" / "commands" / "synthetic.md").write_bytes(
        b"line one\r\nline two\r\n"
    )
    _finalize("mnt", apply=False, allow_crossing=[_CROSSING])
    out = capsys.readouterr().out
    assert len(_lines(out, "WOULD-REFUSE")) == 1 and "WOULD-ALLOW-CROSSING" not in out


# ---------------------------------------------------------------------------
# AC-7: stale branch — WARN by default, merge + re-gate behind --revalidate
# ---------------------------------------------------------------------------


def _advance_origin_main(
    env: _Env, rel: str = "docs/landed.md", content: str = "landed\n"
) -> str:
    """Land a commit on `main` and push it, so `origin/main` is ahead of any
    role branch cut earlier."""
    _commit(env.repo, rel, content, f"feat: {rel} merged on main")
    _git(env.repo, "push", "-q", "origin", "main")
    return _git(env.repo, "rev-parse", "main")


class _Gate:
    """Scripted `_run_deploy_gate` double: pops outcomes in order and records
    the metrics env each run received. Any further keyword the dispatcher
    passes (e.g. the tree to gate; see
    `test_revalidate_gates_the_merged_worktree_not_the_primary_checkout`) is
    accepted and kept in `extra`."""

    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, dict | None]] = []
        self.extra: list[dict] = []

    def __call__(
        self, stage: str, env_extra: dict | None = None, **kw
    ) -> tuple[bool, str]:
        self.calls.append((stage, dict(env_extra) if env_extra else None))
        self.extra.append(dict(kw))
        ok = self.outcomes.pop(0) if self.outcomes else True
        return (ok, "" if ok else "Deploy gate FAILED (synthetic)")


_FAKE_GATE = (
    "import sys\n"
    "from pathlib import Path\n"
    "# Like the real deploy-gate.py, the repo root is this file's own location.\n"
    "root = Path(__file__).resolve().parent.parent\n"
    "if (root / 'GATE-RED').exists():\n"
    "    print('Deploy gate FAILED (fake): GATE-RED present in', root)\n"
    "    sys.exit(1)\n"
    "print('Deploy gate PASSED (fake):', root)\n"
)


def _install_fake_gate(env: _Env) -> None:
    """Commit a stand-in `scripts/deploy-gate.py` on main (so every worktree
    cut afterwards carries it) that is red iff a `GATE-RED` file exists in
    the tree it runs from, resolving that tree from its own location exactly
    as the real gate does."""
    _commit(env.repo, "scripts/deploy-gate.py", _FAKE_GATE, "chore: fake gate")
    _git(env.repo, "push", "-q", "origin", "main")


def _ready_impl(env: _Env, role: str) -> Path:
    wt = _worktree(env.repo, role)
    _commit(wt, "src/thing.py", "thing\n", f"{role}: work")
    if role == "dev":
        _write(wt / "PR_BODY.md", "# body\n")
    return wt


# covers hub-tooling FR-0013:AC-7
@pytest.mark.parametrize("role", ["dev", "mnt", "bkf"])
def test_stale_branch_without_the_flag_is_one_warn_naming_the_count_and_remedy(
    env, capsys, role
):
    wt = _ready_impl(env, role)
    _advance_origin_main(env)
    _advance_origin_main(env, "docs/second.md")
    branch = f"claude/{role}-{_FR}"
    before = _git(env.repo, "rev-parse", branch)
    assert _finalize(role, apply=True) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    warns = [w for w in _lines(out, "WARN") if "origin/main" in w]
    assert len(warns) == 1 and "2 commit(s)" in warns[0] and "--revalidate" in warns[0]
    assert "REVALIDATE" not in out.replace("--revalidate", "")
    assert _git(env.repo, "rev-parse", branch) == before  # proceeded as today: no merge
    assert env.bare_sha(branch) == before
    assert _git(wt, "status", "--porcelain") in ("", "?? PR_BODY.md")


# covers hub-tooling FR-0013:AC-7
def test_up_to_date_branch_prints_neither_warn_nor_revalidate(env, capsys):
    _ready_impl(env, "dev")
    assert _finalize("dev", apply=True, revalidate=True) == 0
    out = capsys.readouterr().out
    assert "origin/main" not in out and "REVALIDATE" not in out


# covers hub-tooling FR-0013:AC-7
@pytest.mark.parametrize("role", ["dev", "mnt", "bkf"])
def test_revalidate_merges_origin_main_with_a_two_parent_commit_and_regates(
    env, monkeypatch, capsys, role
):
    wt = _ready_impl(env, role)
    own = _git(env.repo, "rev-parse", f"claude/{role}-{_FR}")
    landed = _advance_origin_main(env)
    gate = _Gate([True, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    branch = f"claude/{role}-{_FR}"
    assert _finalize(role, apply=True, revalidate=True) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    tip = _git(env.repo, "rev-parse", branch)
    parents = _parents(env.repo, branch)
    assert parents == [
        own,
        landed,
    ]  # an ordinary merge: own work first, origin/main second
    assert _git(env.repo, "merge-base", "--is-ancestor", own, tip, check=False) == ""
    assert _git(env.repo, "rev-parse", f"{branch}~1") == own  # nothing rebased
    assert (wt / "docs" / "landed.md").read_bytes() == b"landed\n"
    lines = _lines(out, "REVALIDATE")
    assert (
        len(lines) == 1
        and tip[:7] in lines[0]
        and "gate=pass" in lines[0]
        and branch in lines[0]
    )
    assert [c[0] for c in gate.calls] == [
        "dev",
        "dev",
    ]  # before and after the merge, dev stage
    assert env.bare_sha(branch) == tip
    assert "WARN" not in "\n".join(w for w in _lines(out, "origin/main"))


# covers hub-tooling FR-0013:AC-7
def test_revalidate_dry_run_previews_and_runs_no_gate(env, monkeypatch, capsys):
    wt = _ready_impl(env, "dev")
    _advance_origin_main(env)
    gate = _Gate([True, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    before = env.snapshot([wt])
    assert _finalize("dev", apply=False, revalidate=True) == 0
    out = capsys.readouterr().out
    would = _lines(out, "WOULD-REVALIDATE")
    assert len(would) == 1 and "1 commit(s)" in would[0] and str(wt) in would[0]
    assert gate.calls == [] and env.snapshot([wt]) == before
    assert len(_parents(env.repo, f"claude/dev-{_FR}")) == 1


# covers hub-tooling FR-0013:AC-7
def test_merge_conflict_is_one_error_no_push_and_the_conflict_is_left_for_a_human(
    env, monkeypatch, capsys
):
    wt = _ready_impl(env, "dev")
    _commit(wt, "README.md", "dev's version\n", "dev: readme")
    _advance_origin_main(env, "README.md", "main's version\n")
    gate = _Gate([True, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    assert _finalize("dev", apply=True, revalidate=True) == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert (
        len(errors) == 1
        and "origin/main" in errors[0]
        and "left for a human" in errors[0]
    )
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []
    status = _git(wt, "status", "--porcelain")
    assert "UU README.md" in status  # conflict left in place, not aborted
    assert (wt / ".git").exists() and _git(
        wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False
    )
    assert len(gate.calls) == 1  # baseline ran; no post-merge gate on a failed merge


# covers hub-tooling FR-0013:AC-7
def test_newly_red_gate_after_the_merge_is_one_error_and_no_push(
    env, monkeypatch, capsys
):
    """Green before the merge, red after: the merge broke it. `--ready`
    (non-draft) so no exemption is in play."""
    wt = _ready_impl(env, "dev")
    _advance_origin_main(env)
    gate = _Gate([True, False])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    assert _finalize("dev", apply=True, draft=False, revalidate=True) == 1
    out = capsys.readouterr().out
    assert len(_lines(out, "ERROR")) == 1
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []
    assert (
        len(_parents(env.repo, f"claude/dev-{_FR}")) == 2
    )  # merged tree left in place
    assert _git(wt, "status", "--porcelain") in ("", "?? PR_BODY.md")


# covers hub-tooling FR-0013:AC-7
def test_newly_red_gate_is_an_error_even_when_the_pr_is_a_draft(
    env, monkeypatch, capsys
):
    """Watch-out (i), ruled: the draft exemption lets a red gate *open* a
    draft PR (FR-0002); it does not turn a green->red transition caused by
    the merge into "same or better". AC-7: a newly red gate is one ERROR, a
    non-zero exit and no push — draft or not."""
    _ready_impl(env, "dev")
    _advance_origin_main(env)
    gate = _Gate([True, False])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    rc = _finalize("dev", apply=True, draft=True, revalidate=True)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert len(_lines(out, "ERROR")) == 1
    assert "gate=pass" not in out
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0013:AC-7
def test_red_before_and_after_proceeds_and_the_revalidate_line_does_not_claim_pass(
    env, monkeypatch, capsys
):
    """Watch-out (i), ruled: "same" (red -> red) proceeds; the REVALIDATE
    line records the gate outcome, so it must not print `gate=pass` for a
    gate that failed, and on a draft it names the exemption."""
    _ready_impl(env, "dev")
    _advance_origin_main(env)
    gate = _Gate([False, False])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    assert _finalize("dev", apply=True, draft=True, revalidate=True) == 0, (
        capsys.readouterr().out
    )
    out = capsys.readouterr().out
    lines = _lines(out, "REVALIDATE")
    assert len(lines) == 1
    assert "gate=pass" not in lines[0]
    assert "draft-exempt" in lines[0]
    assert env.bare_sha(f"claude/dev-{_FR}") == _git(
        env.repo, "rev-parse", f"claude/dev-{_FR}"
    )


# covers hub-tooling FR-0013:AC-7
def test_red_before_green_after_is_better_and_proceeds(env, monkeypatch, capsys):
    _ready_impl(env, "dev")
    _advance_origin_main(env)
    gate = _Gate([False, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    assert _finalize("dev", apply=True, draft=False, revalidate=True) == 0, (
        capsys.readouterr().out
    )
    out = capsys.readouterr().out
    assert "ERROR" not in out and "gate=pass" in "".join(_lines(out, "REVALIDATE"))


# covers hub-tooling FR-0013:AC-7
# covers hub-tooling FR-0013:AC-10
def test_pr_opened_cites_the_post_merge_gate_run_and_reflects_the_merged_head(
    env, monkeypatch, capsys
):
    """Watch-out (ii), re-pointed at v5 (DEC-0011): the two gate runs — the
    pre-merge baseline and the post-merge re-run — both execute in the dev
    worktree (`cwd == <wt>`) and both `--status-only`, so neither is given a
    metrics environment (no `METRICS_GATE_RECORD_ID`, no `env_extra` at all),
    no preflight record id is registered, and the `pr.opened` record cites
    `gate_record_id: null` — the value every other live finalize path
    carries. The record still validates and its head/commit count are the
    post-merge state, as before."""
    wt = _ready_impl(env, "dev")
    _advance_origin_main(env)
    gate = _Gate([True, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    assert _finalize("dev", apply=True, revalidate=True) == 0, capsys.readouterr().out
    assert [c[0] for c in gate.calls] == ["dev", "dev"]
    for _stage, env_extra in gate.calls:
        assert env_extra is None or "METRICS_GATE_RECORD_ID" not in env_extra
    assert len(gate.extra) == 2
    for extra in gate.extra:
        assert extra["cwd"] == wt and extra["status_only"] is True
    assert dispatch._PREFLIGHT_GATE_RECORD_IDS == {}
    assert [r["kind"] for r in _records() if r["kind"] == "gate.run"] == []
    opened = [r for r in _records() if r["kind"] == "pr.opened"]
    assert len(opened) == 1 and metrics_log.validation_errors(opened[0]) == []
    assert opened[0]["gate_record_id"] is None
    assert opened[0]["head_sha"] == _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    assert opened[0]["commits_ahead"] == 2  # own commit + the merge commit


# covers hub-tooling FR-0013:AC-7
def test_dirty_worktree_blocks_revalidate_before_any_merge(env, monkeypatch, capsys):
    wt = _ready_impl(env, "dev")
    _advance_origin_main(env)
    (wt / "src" / "thing.py").write_bytes(b"edited\n")
    gate = _Gate([True, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    assert _finalize("dev", apply=True, revalidate=True) == 1
    out = capsys.readouterr().out
    assert len(_lines(out, "ERROR")) == 1 and "cannot revalidate" in out
    assert len(_parents(env.repo, f"claude/dev-{_FR}")) == 1 and gate.calls == []


# covers hub-tooling FR-0013:AC-7
def test_revalidate_gates_the_merged_worktree_not_the_primary_checkout(env, capsys):
    """AC-7: the gate is re-run *against the merged tree* and compared with
    the branch tree before the merge. With a real (stand-in) gate on disk:
    the dev branch is cut while main is green; main then lands `GATE-RED`.
    The branch tree is green before the merge and red after it — newly red,
    so one ERROR, a non-zero exit and no push, draft or not. A gate run in
    the primary checkout instead sees `GATE-RED` both times (red -> red,
    "unchanged"), never evaluates the branch, and proceeds to push."""
    _install_fake_gate(env)
    wt = _ready_impl(env, "dev")
    _advance_origin_main(env, "GATE-RED", "landed on main after the branch\n")
    assert (env.repo / "GATE-RED").exists() and not (wt / "GATE-RED").exists()
    rc = _finalize("dev", apply=True, draft=True, revalidate=True)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert len(_lines(out, "ERROR")) == 1 and "REVALIDATE" not in out
    assert "PUSHED" not in out and "OPENED" not in out
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []
    assert (
        len(_parents(env.repo, f"claude/dev-{_FR}")) == 2
    )  # merged tree left in place
    assert (wt / "GATE-RED").exists()


_FAKE_WRITING_GATE = (
    "import sys\n"
    "from pathlib import Path\n"
    "# Like the real deploy-gate.py: the repo root is this file's own location,\n"
    "# and unless --status-only the run rewrites the tracked specs/INDEX.md and\n"
    "# appends its gate.run record to specs/_metrics/<month>.ndjson beside it.\n"
    "root = Path(__file__).resolve().parent.parent\n"
    "if '--status-only' not in sys.argv:\n"
    "    (root / 'specs' / 'INDEX.md').write_text('rewritten by the gate\\n')\n"
    "    m = root / 'specs' / '_metrics'\n"
    "    m.mkdir(parents=True, exist_ok=True)\n"
    "    with (m / '2026-09.ndjson').open('a') as f:\n"
    '        f.write(\'{"kind": "gate.run"}\\n\')\n'
    "if (root / 'GATE-RED').exists():\n"
    "    print('Deploy gate FAILED (fake): GATE-RED present in', root)\n"
    "    sys.exit(1)\n"
    "print('Deploy gate PASSED (fake):', root)\n"
)


# covers hub-tooling FR-0013:AC-7
# covers hub-tooling FR-0013:AC-1
def test_revalidate_writes_nothing_so_the_worktree_stays_clean_for_the_fast_forward(
    env, capsys
):
    """DEC-0011: both revalidate gate runs are `--status-only`, so the
    dispatcher's own observation writes nothing — no `specs/INDEX.md`
    rewrite, no `gate.run` append — in the worktree or the primary checkout.
    The stand-in gate here does exactly what the real one does when the
    flag is missing (rewrites the tracked index, appends a metrics line), so
    a dispatcher that dropped `--status-only`, or one that still gated the
    primary checkout, dirties a tree this test inspects. After a green ->
    green `--revalidate` the worktree is clean apart from the merge commit,
    the tracked index is byte-identical everywhere, no ndjson exists in
    either tree, and `pr.opened.gate_record_id` is null."""
    _commit(env.repo, "specs/INDEX.md", "# index (tracked)\n", "chore: index")
    _commit(env.repo, "scripts/deploy-gate.py", _FAKE_WRITING_GATE, "chore: gate")
    _git(env.repo, "push", "-q", "origin", "main")
    wt = _ready_impl(env, "dev")
    _advance_origin_main(env)
    index_before = (env.repo / "specs" / "INDEX.md").read_bytes()
    assert (wt / "specs" / "INDEX.md").read_bytes() == index_before
    assert not list((wt / "specs").glob("_metrics/*.ndjson"))
    assert not list((env.repo / "specs").glob("_metrics/*.ndjson"))
    rc = _finalize("dev", apply=True, draft=True, revalidate=True)
    out = capsys.readouterr().out
    assert rc == 0, out
    lines = _lines(out, "REVALIDATE")
    assert len(lines) == 1 and "gate=pass" in lines[0]
    branch = f"claude/dev-{_FR}"
    assert len(_parents(env.repo, branch)) == 2
    assert env.bare_sha(branch) == _git(env.repo, "rev-parse", branch)
    # The worktree is as clean after the step as the dirtiness check found it
    # before the merge (plus the merge commit); AC-1's later fast-forward is
    # never refused by the dispatcher's own side effects.
    assert _git(wt, "status", "--porcelain") == ""
    assert dispatch._rev_worktree_dirty_paths(wt) == []
    assert (wt / "specs" / "INDEX.md").read_bytes() == index_before
    assert not list((wt / "specs").glob("_metrics/*.ndjson"))
    # The primary checkout was never gated and never written to.
    assert (env.repo / "specs" / "INDEX.md").read_bytes() == index_before
    assert not list((env.repo / "specs").glob("_metrics/*.ndjson"))
    assert _git(env.repo, "status", "--porcelain", "--untracked-files=no") == ""
    # No preflight record was registered or written; pr.opened cites null.
    assert dispatch._PREFLIGHT_GATE_RECORD_IDS == {}
    kinds = [r["kind"] for r in _records()]
    assert "gate.run" not in kinds
    opened = [r for r in _records() if r["kind"] == "pr.opened"]
    assert len(opened) == 1 and metrics_log.validation_errors(opened[0]) == []
    assert opened[0]["gate_record_id"] is None


# --- wave scoping ----------------------------------------------------------


class _FakeAdapter:
    name = "fake"
    binary_name = "fake"

    def write_worktree_settings(self, wt_path: Path, role: str, fr_id: str) -> None:
        pass

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        return ("spawned", 999_999)

    def parse_log(self, log_path: Path):
        return SimpleNamespace(last_text="", result_subtype="success", tool_calls=0)

    def dry_run_preview(self, fr_id: str, role: str, wt_preview: Path) -> str:
        return f"fake-preview {role} {fr_id}"


class _WaveDrive:
    """Signature-faithful `cmd_finalize` double plus the phase doubles the
    FR-0014 harness established."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.finalize_calls: list[tuple[str, str, dict]] = []
        self.rev_verdicts: dict[str, list[str]] = {}
        self.prepare_ok = True

    def finalize_double(self, real):
        sig = inspect.signature(real)

        def double(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            args_d = dict(bound.arguments)
            self.finalize_calls.append((args_d["fr_id"], args_d["role"], args_d))
            return 0

        return double

    def spawn_role(
        self,
        fr_id,
        role,
        apply,
        adapter,
        extra_prompt=None,
        round_num=1,
        preflight_segment="",
    ):
        if not apply:
            return ("dry-run", None, None)
        wt = self.repo / ".claude" / "worktrees" / f"{role}-{fr_id}"
        if role == "dev" and not wt.exists():
            wt.parent.mkdir(parents=True, exist_ok=True)
            _git(
                self.repo,
                "worktree",
                "add",
                "-q",
                "-b",
                f"claude/dev-{fr_id}",
                str(wt),
                "main",
            )
            _write(wt / "PR_BODY.md", f"# {fr_id}\n")
            _write(
                wt / "specs" / f"{fr_id}-synthetic.md",
                _fr_md(fr_id, status="in-progress"),
            )
            _git(wt, "add", "-A")
            _git(wt, "commit", "-q", "-m", "dev: hand-off")
        return ("spawned", 4242, wt)

    def wait_for_phase(self, targets, poll_interval, phase_timeout):
        return {fr_id: "completed" for fr_id, _role in targets}

    def evaluate(self, fr_id, role, adapter):
        if role == "dev":
            return dispatch.AgentOutcome(status="success", summary="dev success")
        queue = self.rev_verdicts.setdefault(fr_id, ["approve"])
        verdict = queue.pop(0) if len(queue) > 1 else queue[0]
        return dispatch.AgentOutcome(
            status="success", summary="rev success", verdict=verdict
        )

    def prepare_rework(self, fr_id):
        return (
            self.prepare_ok,
            "synced (stub)" if self.prepare_ok else "REVIEW.md missing (stub)",
        )

    def dev_calls(self) -> list[dict]:
        return [a for _f, role, a in self.finalize_calls if role == "dev"]


def _wave_env(
    tmp_path, monkeypatch, specs: dict[str, str], flipped: list[str]
) -> tuple[_Env, _WaveDrive]:
    repo, bare = _make_repo(tmp_path, specs)
    _point(monkeypatch, dispatch, repo, tmp_path)
    e = _Env(repo, bare)
    _route_gh(monkeypatch, e)
    d = _WaveDrive(repo)
    monkeypatch.setattr(
        dispatch, "cmd_finalize", d.finalize_double(dispatch.cmd_finalize)
    )
    monkeypatch.setattr(dispatch, "spawn_role", d.spawn_role)
    monkeypatch.setattr(dispatch, "_wait_for_phase", d.wait_for_phase)
    monkeypatch.setattr(dispatch, "_evaluate_agent_outcome", d.evaluate)
    monkeypatch.setattr(dispatch, "_prepare_dev_worktree_for_rework", d.prepare_rework)
    monkeypatch.setattr(
        dispatch, "_collect_failing_tests", lambda wt, timeout_s=900: []
    )
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (True, "venv:stub"))
    monkeypatch.setattr(dispatch, "prune_dead_locks", lambda verbose=True: 0)
    monkeypatch.setattr(
        dispatch,
        "reconcile_merged_prs",
        lambda apply=False, verbose=False: dispatch.ReconcileSummary(
            flipped=list(flipped), cleaned=[], skipped=[]
        ),
    )
    return e, d


def _wave(**kw) -> int:
    kw.setdefault("apply", True)
    kw.setdefault("fr_filter", [_FR])
    kw.setdefault("timeout", 600)
    kw.setdefault("phase_timeout", 600)
    kw.setdefault("poll_interval", 0.01)
    return dispatch.cmd_wave(adapter=_FakeAdapter(), **kw)


_DEP_SPECS = {
    _FR: _fr_md(_FR, depends_on=(_DEP,)),
    _DEP: _fr_md(_DEP, status="merged"),
    _OTHER: _fr_md(_OTHER, status="merged"),
}


# covers hub-tooling FR-0013:AC-7
def test_wave_phase3_auto_revalidates_only_when_a_dependency_merged_this_run(
    tmp_path, monkeypatch, capsys
):
    _e, d = _wave_env(tmp_path, monkeypatch, _DEP_SPECS, flipped=[_DEP])
    assert _wave() == 0, capsys.readouterr().out
    dev = d.dev_calls()
    assert len(dev) == 1 and dev[0]["revalidate"] is True and dev[0]["apply"] is True


# covers hub-tooling FR-0013:AC-7
@pytest.mark.parametrize(
    "flipped", [[], [_OTHER]], ids=["merged-before-the-run", "unrelated-fr-flipped"]
)
def test_wave_phase3_does_not_revalidate_for_a_dependency_merged_earlier_or_an_unrelated_flip(
    tmp_path, monkeypatch, capsys, flipped
):
    """Adversarial: a dependency that was already `merged` on disk before the
    run, or an FR this one does not depend on flipping, is not "merged during
    the run" for this FR."""
    _e, d = _wave_env(tmp_path, monkeypatch, _DEP_SPECS, flipped=flipped)
    assert _wave() == 0, capsys.readouterr().out
    dev = d.dev_calls()
    assert len(dev) == 1 and dev[0].get("revalidate", False) is False


# covers hub-tooling FR-0013:AC-7
def test_rework_round_dev_finalize_never_auto_revalidates(
    tmp_path, monkeypatch, capsys
):
    """Notes ruling: no reconcile runs between Phase 3 and a rework round, so
    the rework leg's dev finalize passes no `revalidate` even when the
    dependency flipped this run."""
    _e, d = _wave_env(tmp_path, monkeypatch, _DEP_SPECS, flipped=[_DEP])
    d.rev_verdicts[_FR] = ["request-changes", "approve"]
    assert _wave(rounds=2) == 0, capsys.readouterr().out
    dev = d.dev_calls()
    assert len(dev) == 2
    assert dev[0]["revalidate"] is True
    assert dev[1].get("revalidate", False) is False


# covers hub-tooling FR-0013:AC-7
def test_dry_run_wave_records_no_merged_this_run_and_reaches_no_finalize(
    tmp_path, monkeypatch, capsys
):
    _e, d = _wave_env(tmp_path, monkeypatch, _DEP_SPECS, flipped=[_DEP])
    assert _wave(apply=False) == 0
    assert d.finalize_calls == []


# ---------------------------------------------------------------------------
# AC-8: --rounds defaults to 2
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0013:AC-8
def test_cmd_wave_rounds_default_is_two_and_the_pre_fr_default_was_one(pre_fr_dispatch):
    assert inspect.signature(dispatch.cmd_wave).parameters["rounds"].default == 2
    assert inspect.signature(pre_fr_dispatch.cmd_wave).parameters["rounds"].default == 1
    assert dispatch.REVIEW_CYCLE_BUDGET == 3


# covers hub-tooling FR-0013:AC-8
@pytest.mark.parametrize(
    "argv,expected", [([], 2), (["--rounds", "1"], 1), (["--rounds", "3"], 3)]
)
def test_cli_passes_the_default_or_the_explicit_rounds_to_cmd_wave(
    monkeypatch, argv, expected
):
    seen: dict = {}
    monkeypatch.setattr(dispatch, "get_adapter", lambda name: _FakeAdapter())
    monkeypatch.setattr(dispatch, "cmd_wave", lambda **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["dispatch.py", "wave", *argv])
    assert dispatch.main() == 0
    assert seen["rounds"] == expected


# covers hub-tooling FR-0013:AC-8
@pytest.mark.parametrize("rounds", [0, 4, -1])
def test_range_check_is_unchanged_and_exits_two(env, capsys, rounds):
    assert _wave(rounds=rounds, apply=False) == 2
    out = capsys.readouterr().out
    assert "out of range" in out and "Wave started" not in out


# covers hub-tooling FR-0013:AC-8
def test_wave_help_states_the_new_default():
    proc = _REAL_RUN(
        [sys.executable, str(_SCRIPTS_DIR / "dispatch.py"), "wave", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0
    text = " ".join(proc.stdout.split())
    assert "default: 2" in text and "--rounds 1" in text


# covers hub-tooling FR-0013:AC-8
def test_dry_run_plan_shows_round_two_by_default_and_not_with_rounds_one(
    tmp_path, monkeypatch, capsys
):
    _wave_env(tmp_path, monkeypatch, {_FR: _fr_md(_FR)}, flipped=[])
    assert _wave(apply=False) == 0
    out = capsys.readouterr().out
    assert "rounds=2)" in out.splitlines()[0]
    assert "(rounds=2)" in out
    assert len(_lines(out, "WOULD-RUN  Round 2/2")) == 1
    assert _wave(apply=False, rounds=1) == 0
    out = capsys.readouterr().out
    assert (
        "rounds=1)" in out.splitlines()[0]
        and "Round 2/" not in out
        and "(rounds=1)" in out
    )


# covers hub-tooling FR-0013:AC-8
def test_default_budget_drives_one_rework_round_and_the_wave_record_says_so(
    tmp_path, monkeypatch, capsys
):
    _e, d = _wave_env(tmp_path, monkeypatch, {_FR: _fr_md(_FR)}, flipped=[])
    d.rev_verdicts[_FR] = ["request-changes", "approve"]
    assert _wave() == 0, capsys.readouterr().out  # no rounds passed: the default
    out = capsys.readouterr().out
    assert "REWORK round 2/2" in out and "FORCE-ESCALATE" not in out
    recs = [r for r in _records() if r["kind"] == "dispatch.wave"]
    assert len(recs) == 1 and metrics_log.validation_errors(recs[0]) == []
    assert recs[0]["rounds_ran"] == {_FR: 2} and recs[0]["force_escalated"] == []
    assert len([a for _f, role, a in d.finalize_calls if role == "rev"]) == 2


# covers hub-tooling FR-0013:AC-8
def test_rounds_one_still_ends_the_wave_on_request_changes_without_a_rework_round(
    tmp_path, monkeypatch, capsys
):
    _e, d = _wave_env(tmp_path, monkeypatch, {_FR: _fr_md(_FR)}, flipped=[])
    d.rev_verdicts[_FR] = ["request-changes", "approve"]
    assert _wave(rounds=1) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "REWORK" not in out and "FORCE-ESCALATE" not in out
    assert len(d.dev_calls()) == 1
    recs = [r for r in _records() if r["kind"] == "dispatch.wave"]
    assert recs[0]["rounds_ran"] == {_FR: 1}


# covers hub-tooling FR-0013:AC-8
def test_budget_exhaustion_force_escalates_and_rework_round_slugs_are_intact(
    tmp_path, monkeypatch, capsys
):
    _e, d = _wave_env(tmp_path, monkeypatch, {_FR: _fr_md(_FR)}, flipped=[])
    d.rev_verdicts[_FR] = ["request-changes", "request-changes", "request-changes"]
    assert _wave(rounds=3) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "FORCE-ESCALATE" in out and "3 Dev<->Reviewer cycle(s)" in out
    recs = [r for r in _records() if r["kind"] == "dispatch.wave"]
    assert recs[0]["rounds_ran"] == {_FR: 3} and recs[0]["force_escalated"] == [_FR]


# covers hub-tooling FR-0013:AC-8
def test_fr0014_rework_round_slug_is_intact_under_the_default_budget(
    tmp_path, monkeypatch, capsys
):
    """A mechanical failure in the automatic round 2 is still reported at
    `rework-round-2` (FR-0014's slug), now reached without passing --rounds."""
    _e, d = _wave_env(tmp_path, monkeypatch, {_FR: _fr_md(_FR)}, flipped=[])
    d.rev_verdicts[_FR] = ["request-changes", "approve"]
    d.prepare_ok = False
    assert _wave() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "REWORK STOPPED" in out and "REWORK round 2/2" in out
    recs = [r for r in _records() if r["kind"] == "dispatch.wave"]
    assert len(recs) == 1 and recs[0]["drop_reasons"][0]["phase"] == "rework-round-2"


# ---------------------------------------------------------------------------
# AC-9: dry-run previews every new step and mutates nothing
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0013:AC-9
def test_dry_run_rev_approve_previews_keep_and_ff_push_and_changes_nothing(env, capsys):
    dev_wt, rev_wt = _approve_scenario(env, "dev")
    _write(rev_wt / "tests" / "test_more.py", "# staged only\n")
    _git(rev_wt, "add", "tests/test_more.py")
    before = env.snapshot([dev_wt, rev_wt])
    assert _finalize("rev", apply=False) == 0
    out = capsys.readouterr().out
    assert len(_lines(out, "WOULD-KEEP-REVIEW")) == 1
    would_ff = _lines(out, "WOULD-FF-PUSH")
    assert len(would_ff) == 1 and f"claude/dev-{_FR} -> claude/rev-{_FR}" in would_ff[0]
    assert "WOULD-FINALIZE" in out and "--approve" in out and "{verdict}" not in out
    assert env.snapshot([dev_wt, rev_wt]) == before
    assert env.gh == [] and _records() == []
    assert "FF-PUSHED" not in out and "REVIEW-KEPT" not in out


# covers hub-tooling FR-0013:AC-9
def test_dry_run_mnt_previews_crossing_and_revalidate_and_changes_nothing(
    env, monkeypatch, capsys
):
    mnt_wt = _mnt_with_crossing(env, b"line one\r\nline two\r\n")
    _advance_origin_main(env)
    gate = _Gate([True, True])
    monkeypatch.setattr(dispatch, "_run_deploy_gate", gate)
    before = env.snapshot([mnt_wt])
    assert (
        _finalize("mnt", apply=False, allow_crossing=[_CROSSING], revalidate=True) == 0
    )
    out = capsys.readouterr().out
    assert len(_lines(out, "WOULD-REVALIDATE")) == 1
    assert len(_lines(out, "WOULD-ALLOW-CROSSING")) == 1
    assert "WOULD-FINALIZE" in out
    assert env.snapshot([mnt_wt]) == before and gate.calls == [] and env.gh == []
    assert not any(
        "CROSSING-ALLOWED" in ln and "WOULD" not in ln for ln in out.splitlines()
    )


# covers hub-tooling FR-0013:AC-9
def test_dry_run_reports_a_content_carrying_crossing_as_would_refuse_not_error(
    env, capsys
):
    mnt_wt = _mnt_with_crossing(env, b"line one\r\nline two changed\r\n")
    before = env.snapshot([mnt_wt])
    _finalize("mnt", apply=False, allow_crossing=[_CROSSING])
    out = capsys.readouterr().out
    would = _lines(out, "WOULD-REFUSE")
    assert (
        len(would) == 1
        and repr(_CROSSING) in would[0]
        and "carries content" in would[0]
    )
    assert not any(
        _CROSSING in e for e in _lines(out, "ERROR")
    )  # the crossing itself is not an error
    assert "WOULD-FINALIZE" not in out and "WOULD-ALLOW-CROSSING" not in out
    assert env.snapshot([mnt_wt]) == before and env.gh == []


# covers hub-tooling FR-0013:AC-9
def test_dry_run_revalidate_on_a_conflicting_branch_still_mutates_nothing(
    env, monkeypatch, capsys
):
    """Adversarial: the branch *would* conflict; dry-run must not find out
    by trying."""
    wt = _ready_impl(env, "dev")
    _commit(wt, "README.md", "dev's version\n", "dev: readme")
    _advance_origin_main(env, "README.md", "main's version\n")
    monkeypatch.setattr(dispatch, "_run_deploy_gate", _Gate([True, True]))
    before = env.snapshot([wt])
    assert _finalize("dev", apply=False, revalidate=True) == 0
    out = capsys.readouterr().out
    assert "WOULD-REVALIDATE" in out and "ERROR" not in out
    assert env.snapshot([wt]) == before
    assert not _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)


# ---------------------------------------------------------------------------
# AC-10: no history rewritten; existing behaviour and records preserved
# ---------------------------------------------------------------------------


def _git_argv_lists(source: str) -> list[list[str]]:
    """Every list literal in the module whose string elements look like a git
    argv (contains one of the verbs we care about)."""
    tree = ast.parse(source)
    verbs = {"merge", "rebase", "reset", "checkout", "push"}
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            strs = [
                e.value
                for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if any(s in verbs for s in strs):
                found.append(strs)
    return found


# covers hub-tooling FR-0013:AC-10
def test_no_git_argv_rewrites_history_and_every_merge_is_ff_only_or_the_ac7_exception():
    source = (_SCRIPTS_DIR / "dispatch.py").read_text(encoding="utf-8")
    lists = _git_argv_lists(source)
    assert lists, "expected git argv list literals in dispatch.py"
    assert not any("rebase" in ls for ls in lists)
    assert not any("reset" in ls and "--hard" in ls for ls in lists)
    assert not any("checkout" in ls and ("-f" in ls or "--force" in ls) for ls in lists)
    assert not any(
        "push" in ls and any(f in ls for f in ("--force", "-f", "--force-with-lease"))
        for ls in lists
    )
    merges = [ls for ls in lists if "merge" in ls]
    ff_only = [ls for ls in merges if "--ff-only" in ls]
    origin_main = [ls for ls in merges if "origin/main" in ls]
    aborts = [ls for ls in merges if "--abort" in ls]
    others = [ls for ls in merges if ls not in ff_only + origin_main + aborts]
    assert len(ff_only) == 1, ff_only  # the one shared `_ff_only_merge` helper
    assert len(origin_main) == 1, origin_main  # AC-7's explicit exception
    # Pre-existing (FR-0006): the rework sync merges the rev branch into the
    # dev worktree by name, plus its abort. Nothing else.
    assert len(others) == 1 and "--no-edit" in others[0], others


# covers hub-tooling FR-0013:AC-10
def test_pre_fr_git_argv_shapes_are_all_still_present(pre_fr_dispatch):
    """Adversarial for "existing behaviour preserved": every git argv list
    the pre-FR dispatcher had is still there verbatim (only additions)."""
    src = _pre_fr_source()
    assert src is not None
    old = _git_argv_lists(src.decode("utf-8"))
    new = _git_argv_lists((_SCRIPTS_DIR / "dispatch.py").read_text(encoding="utf-8"))
    missing = [ls for ls in old if ls not in new and "--ff-only" not in ls]
    assert missing == [], missing


# covers hub-tooling FR-0013:AC-10
def test_refreshed_pr_record_reflects_the_post_fast_forward_state_and_validates(
    env, capsys
):
    """After the approve fast-forward, a dev re-finalize refreshes the open
    PR: `pr.refreshed` carries the post-ff head and commit count, validates,
    and no new record kind or field appears."""
    _approve_scenario(env, "dev")
    assert _finalize("rev") == 0, capsys.readouterr().out
    capsys.readouterr()
    ff_head = _git(env.repo, "rev-parse", f"claude/dev-{_FR}")
    env.pr_list_number = 7
    assert _finalize("dev", apply=True) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "PR-EXISTS" in out
    recs = _records()
    for r in recs:
        assert metrics_log.validation_errors(r) == [], r
        assert r["kind"] in metrics_log.KINDS
    kinds = [r["kind"] for r in recs]
    assert kinds.count("pr.review") == 1 and kinds.count("pr.refreshed") == 1
    refreshed = next(r for r in recs if r["kind"] == "pr.refreshed")
    assert refreshed["head_sha"] == ff_head
    assert (
        refreshed["commits_ahead"] == 4
    )  # dev work + reviewer tests + reviewer's REVIEW.md + the filing commit (DEC-0024)
    assert dispatch._load_pr_record(_FR, "dev")["head_sha"] == ff_head


# covers hub-tooling FR-0013:AC-10
def test_every_emitted_metrics_kind_is_a_known_kind_and_none_is_new():
    """No new metrics record kind: every literal `_metrics_emit("<kind>"` in
    the dispatcher names a kind `metrics_log.KINDS` already declares."""
    source = (_SCRIPTS_DIR / "dispatch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_metrics_emit"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            kinds.add(node.args[0].value)
    assert kinds and kinds <= set(metrics_log.KINDS)
    assert not any(
        k.startswith(("ff", "revalidate", "crossing", "verdict"))
        for k in metrics_log.KINDS
    )


# covers hub-tooling FR-0013:AC-10
def test_existing_callers_are_unaffected_by_the_keyword_only_additions():
    """`cmd_finalize` / `_finalize_rev` keep their positional shape; the new
    parameters are keyword-only with today's-behaviour defaults."""
    sig = inspect.signature(dispatch.cmd_finalize)
    for name, default in (
        ("verdict_file", None),
        ("allow_crossing", None),
        ("revalidate", False),
    ):
        p = sig.parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default == default
    positional = [
        p.name
        for p in sig.parameters.values()
        if p.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    assert positional == ["fr_id", "role", "apply", "draft", "adapter"]
    rsig = inspect.signature(dispatch._finalize_rev)
    assert [p.name for p in rsig.parameters.values()][:5] == [
        "fr_id",
        "branch",
        "head_sha",
        "nwo",
        "adapter",
    ]
    assert rsig.parameters["verdict_file"].kind is inspect.Parameter.KEYWORD_ONLY


# covers hub-tooling FR-0013:AC-4
# covers hub-tooling FR-0013:AC-6
# covers hub-tooling FR-0013:AC-7
def test_cli_wires_the_three_new_finalize_flags(monkeypatch, tmp_path):
    seen: dict = {}

    def fake_finalize(fr_id, role, **kw):
        seen.update({"fr_id": fr_id, "role": role, **kw})
        return 0

    monkeypatch.setattr(dispatch, "cmd_finalize", fake_finalize)
    vf = tmp_path / "verdict.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "finalize",
            _FR,
            "--role",
            "mnt",
            "--verdict-file",
            str(vf),
            "--allow-crossing",
            ".claude/commands/**",
            "--allow-crossing",
            ".cursor/**",
            "--revalidate",
        ],
    )
    assert dispatch.main() == 0
    assert seen["verdict_file"] == vf and isinstance(seen["verdict_file"], Path)
    assert seen["allow_crossing"] == [".claude/commands/**", ".cursor/**"]
    assert (
        seen["revalidate"] is True and seen["apply"] is False and seen["draft"] is True
    )
    seen.clear()
    monkeypatch.setattr(sys, "argv", ["dispatch.py", "finalize", _FR, "--role", "dev"])
    assert dispatch.main() == 0
    assert (
        seen["verdict_file"] is None
        and seen["allow_crossing"] is None
        and seen["revalidate"] is False
    )


# ---------------------------------------------------------------------------
# AC-11: the rev leg resolves the implementation role (dev, else mnt)
# ---------------------------------------------------------------------------


def _mnt_only_fr(
    env: _Env, pr_number: int = 55, spec_status: str | None = None
) -> Path:
    """A maintainer-mode FR: `claude/mnt-<FR>` only (no dev branch), pushed,
    with `<FR>.mnt.pr.json` and no `<FR>.dev.pr.json`; when `spec_status`
    is given the FR's status is flipped to it on the mnt branch."""
    mnt_wt = _worktree(env.repo, "mnt")
    _commit(mnt_wt, "src/thing.py", "print('thing')\n", "chore: maintainer work")
    if spec_status is not None:
        _commit(
            mnt_wt,
            f"specs/{_FR}-synthetic.md",
            _fr_md(_FR, status=spec_status),
            "chore: status flip",
        )
    _git(env.repo, "push", "-q", "-u", "origin", f"claude/mnt-{_FR}")
    _impl_pr_record("mnt", pr_number)
    assert not dispatch._git_branch_exists(f"claude/dev-{_FR}")
    return mnt_wt


def _review_of(env: _Env, base_role: str) -> Path:
    rev_wt = _worktree(env.repo, "rev", base=f"claude/{base_role}-{_FR}")
    _commit(
        rev_wt,
        "tests/test_ac1.py",
        f"# @{'covers'} {_FR}:AC-1\n",
        "test: reviewer tests",
    )
    _commit(
        rev_wt, "REVIEW.md", "## Approve\n\nreviewer's own\n", "reviewer wrote its own"
    )
    _rev_log(env.repo, "## Approve\n\nAll ACs covered.")
    return rev_wt


# covers hub-tooling FR-0013:AC-11
# covers hub-tooling FR-0013:AC-1
# covers hub-tooling FR-0013:AC-5
def test_mnt_only_fr_is_reviewed_approved_fast_forwarded_and_recorded_through_the_rev_leg(
    env, capsys
):
    """The maintainer-mode case end to end: every rev-leg resolver names the
    mnt branch; dry-run previews the mnt PR number and `WOULD-FF-PUSH
    claude/mnt-<FR> -> claude/rev-<FR>`; apply posts against the mnt PR,
    fast-forwards and pushes `claude/mnt-<FR>` for real, records
    `ff_commits` on `<FR>.mnt.pr.json` and writes no dev record; a
    following `finalize --role mnt` exempts the Reviewer's test by that
    record, refreshes the PR without losing it, and still refuses a
    maintainer commit made after the fast-forward."""
    mnt_wt = _mnt_only_fr(env)
    mnt_branch, rev_branch = f"claude/mnt-{_FR}", f"claude/rev-{_FR}"
    assert dispatch._base_branch_for_role(_FR, "rev") == mnt_branch
    rev_wt = _review_of(env, "mnt")
    assert dispatch._finalize_base_branch(_FR, "rev") == mnt_branch
    mnt_before = _git(env.repo, "rev-parse", mnt_branch)
    # Dry-run.
    before = env.snapshot([mnt_wt, rev_wt])
    assert _finalize("rev", apply=False) == 0
    out = capsys.readouterr().out
    would_ff = _lines(out, "WOULD-FF-PUSH")
    assert len(would_ff) == 1 and f"{mnt_branch} -> {rev_branch}" in would_ff[0]
    would_fin = _lines(out, "WOULD-FINALIZE")
    assert len(would_fin) == 1 and "gh pr review #55 --approve" in would_fin[0]
    assert env.snapshot([mnt_wt, rev_wt]) == before and env.gh == []
    # Apply.
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    reviews = [c for c in env.gh if c[:3] == ["gh", "pr", "review"]]
    assert len(reviews) == 1 and reviews[0][3] == "55" and "--approve" in reviews[0]
    rev_tip = _git(env.repo, "rev-parse", rev_branch)
    assert _git(env.repo, "rev-parse", mnt_branch) == rev_tip != mnt_before
    assert env.bare_sha(mnt_branch) == rev_tip  # pushed for real
    ff = _lines(out, "FF-PUSHED")
    assert len(ff) == 1 and f"{mnt_branch} -> {rev_branch}" in ff[0]
    record = dispatch._load_pr_record(_FR, "mnt")
    assert record["head_sha"] == rev_tip and record["pr_number"] == 55
    assert record["ff_commits"] == sorted(
        _git(env.repo, "rev-list", f"{mnt_before}..{rev_tip}").split()
    )
    assert len(record["ff_commits"]) == 3  # DEC-0024: plus the filing commit
    assert dispatch._load_pr_record(_FR, "dev") is None
    assert dispatch._load_pr_record(_FR, "rev")["parent_pr_number"] == 55
    # The maintainer's own finalize now sees the Reviewer's test as landed.
    env.pr_list_number = 55
    assert _finalize("mnt", apply=True) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "tests/test_ac1.py exempt" in out and "AC-5a" in out
    assert "PR-EXISTS    #55" in out
    refreshed = dispatch._load_pr_record(_FR, "mnt")
    assert refreshed["ff_commits"] == record["ff_commits"]  # survives the refresh
    # ... but not a commit made after the fast-forward.
    _commit(mnt_wt, "src_outside/late.py", "late\n", "chore: after the ff")
    assert _finalize("mnt", apply=True) == 1
    out = capsys.readouterr().out
    refusal = _lines(out, "outside")
    assert len(refusal) == 1 and "src_outside/late.py" in refusal[0]
    assert "tests/test_ac1.py" not in refusal[0]


# covers hub-tooling FR-0013:AC-11
def test_rev_worktree_sync_plan_and_fast_forward_target_the_mnt_branch(env, capsys):
    """A reused Reviewer worktree is fast-forwarded onto the *maintainer's*
    tip when that is the implementation branch."""
    mnt_wt = _mnt_only_fr(env)
    rev_wt = _worktree(env.repo, "rev", base=f"claude/mnt-{_FR}")
    assert dispatch._rev_sync_plan(_FR)[0] == "noop"
    later = _commit(mnt_wt, "src/more.py", "more\n", "chore: more maintainer work")
    plan, detail = dispatch._rev_sync_plan(_FR)
    assert plan == "fast-forward" and f"claude/mnt-{_FR}" in detail
    ok, note = dispatch._fast_forward_rev_worktree(_FR, rev_wt)
    assert ok, note
    assert f"claude/mnt-{_FR}" in note
    assert _git(rev_wt, "rev-parse", "HEAD") == later
    assert _git(env.repo, "rev-parse", f"claude/rev-{_FR}") == later


# covers hub-tooling FR-0013:AC-11
def test_rev_tick_eligibility_reads_status_and_lock_from_the_mnt_branch(env, capsys):
    mnt_wt = _mnt_only_fr(env)  # status still `ready` on the mnt branch
    # Not reviewable yet, and the message names the *mnt* branch.
    why = dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "rev")
    assert why and f"claude/mnt-{_FR}" in why and "'ready'" in why
    _commit(
        mnt_wt, f"specs/{_FR}-synthetic.md", _fr_md(_FR, status="in-review"), "flip"
    )
    assert dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "rev") is None
    # A live mnt lock blocks the rev tick the way a dev lock does.
    dispatch.write_lock(_FR, "mnt", os.getpid())
    why = dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "rev")
    assert why and "Maintainer still running" in why and "mnt lock held" in why


# covers hub-tooling FR-0013:AC-11
def test_both_branches_present_every_rev_leg_resolver_picks_dev(env, capsys):
    """Adversarial: a mnt branch *and* a mnt record with a different PR
    number sit beside the dev ones; the review goes to the dev PR and the
    mnt record is never touched."""
    _mnt_only_fr(env, pr_number=55)
    _approve_scenario(env, "dev")  # dev branch + dev record #7
    dev_branch = f"claude/dev-{_FR}"
    assert dispatch._base_branch_for_role(_FR, "rev") == dev_branch
    assert dispatch._finalize_base_branch(_FR, "rev") == dev_branch
    assert dispatch._rev_sync_plan(_FR)[0] == "noop"
    mnt_record_before = (env.repo / "_dispatch" / f"{_FR}.mnt.pr.json").read_bytes()
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    reviews = [c for c in env.gh if c[:3] == ["gh", "pr", "review"]]
    assert len(reviews) == 1 and reviews[0][3] == "7"
    assert f"FF-PUSHED    {dev_branch}" in out
    assert (
        env.repo / "_dispatch" / f"{_FR}.mnt.pr.json"
    ).read_bytes() == mnt_record_before
    assert "ff_commits" in dispatch._load_pr_record(_FR, "dev")


# covers hub-tooling FR-0013:AC-11
def test_neither_branch_is_the_existing_error_naming_both_candidates(env, capsys):
    rev_wt = _worktree(env.repo, "rev")  # off main
    _commit(rev_wt, "tests/test_ac1.py", "# t\n", "test: reviewer tests")
    _rev_log(env.repo, "## Approve\n\nfine")
    assert dispatch._base_branch_for_role(_FR, "rev") == "main"
    assert dispatch._rev_sync_plan(_FR) == ("noop", "no dev/rev branch pair")
    why = dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "rev")
    assert why and f"claude/dev-{_FR}" in why and f"claude/mnt-{_FR}" in why
    assert _finalize("rev") == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "no parent PR" in errors[0]
    assert f"claude/dev-{_FR}" in errors[0] and f"claude/mnt-{_FR}" in errors[0]
    assert "--role dev --apply" in errors[0] and "--role mnt" in errors[0]
    assert not any(c[:3] == ["gh", "pr", "review"] for c in env.gh)
    # mnt-only with no mnt record: the error names the mnt branch and remedy.
    env.gh.clear()
    _worktree(env.repo, "mnt")
    assert _finalize("rev") == 1
    errors = _lines(capsys.readouterr().out, "ERROR")
    assert len(errors) == 1 and f"no parent PR for claude/mnt-{_FR}" in errors[0]
    assert "--role mnt --apply" in errors[0]
    assert not any(c[:3] == ["gh", "pr", "review"] for c in env.gh)


# covers hub-tooling FR-0013:AC-11
def test_mnt_only_fr_was_unreviewable_through_the_round1_rev_leg(
    env, round1_dispatch, monkeypatch, tmp_path, capsys
):
    """AC-11 bite check: the round-1 dispatcher (`1cad878`) bases the
    Reviewer worktree on `main` and fails `finalize --role rev` with
    "no parent PR for claude/dev-<FR>" for a maintainer-mode FR."""
    _mnt_only_fr(env)
    _review_of(env, "mnt")
    _point(monkeypatch, round1_dispatch, env.repo, tmp_path)
    monkeypatch.setattr(round1_dispatch.subprocess, "run", dispatch.subprocess.run)
    assert round1_dispatch._base_branch_for_role(_FR, "rev") == "main"
    adapter = round1_dispatch.get_adapter("claude-code")
    assert (
        round1_dispatch.cmd_finalize(
            _FR, "rev", apply=True, draft=True, adapter=adapter
        )
        == 1
    )
    old = capsys.readouterr().out
    assert f"no parent PR for claude/dev-{_FR}" in old
    assert not any(c[:3] == ["gh", "pr", "review"] for c in env.gh)


def _norm(out: str, repo: Path) -> str:
    return out.replace(str(repo), "<repo>")


def _stable_records(repo: Path) -> dict[str, dict]:
    recs: dict[str, dict] = {}
    for p in sorted((repo / "_dispatch").glob("*.pr.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d.pop("finalized_at", None)
        recs[p.name] = d
    return recs


# covers hub-tooling FR-0013:AC-11
# covers hub-tooling FR-0013:AC-10
def test_dev_present_rev_leg_is_byte_identical_to_the_round1_dispatcher(
    round1_dispatch, monkeypatch, tmp_path, capsys
):
    """When `claude/dev-<FR>` exists, every line of output and every record
    on the rev leg — dry-run, the approve with its fast-forward, and the
    "no parent PR" error — is byte-identical to the pre-AC-11 dispatcher
    (`1cad878`), the `ff_commits` key DEC-0009 added excepted. Both runs
    use fixed commit dates so the two repositories' SHAs coincide."""
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")

    def run(mod, root: Path) -> tuple[list[str], dict[str, dict]]:
        repo, bare = _make_repo(root)
        _point(monkeypatch, mod, repo, root)
        e = _Env(repo, bare)
        _route_gh(monkeypatch, e)
        monkeypatch.setattr(mod.subprocess, "run", dispatch.subprocess.run)
        adapter = mod.get_adapter("claude-code")
        outs: list[str] = []

        def fin(apply: bool) -> int:
            rc = mod.cmd_finalize(_FR, "rev", apply=apply, draft=True, adapter=adapter)
            outs.append(_norm(capsys.readouterr().out, repo))
            return rc

        dev_wt = _worktree(repo, "dev")
        _commit(dev_wt, "src/thing.py", "print('thing')\n", "feat: impl work")
        _git(repo, "push", "-q", "-u", "origin", f"claude/dev-{_FR}")
        rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
        _commit(rev_wt, "tests/test_ac1.py", "# t\n", "test: reviewer tests")
        _commit(
            rev_wt,
            "REVIEW.md",
            "## Approve\n\nreviewer's own\n",
            "reviewer wrote its own",
        )
        _rev_log(repo, "## Approve\n\nAll ACs covered.")
        resolvers = (
            mod._base_branch_for_role(_FR, "rev"),
            mod._finalize_base_branch(_FR, "rev"),
            mod._rev_sync_plan(_FR),
            mod.explain_not_runnable(_FR, mod.load_frs(), "rev"),
        )
        assert fin(apply=True) == 1  # no record, no open PR: "no parent PR"
        dispatch_mod_record = {
            "pr_number": 7,
            "branch": f"claude/dev-{_FR}",
            "draft": True,
        }
        mod._save_pr_record(_FR, "dev", dispatch_mod_record)
        assert fin(apply=False) == 0
        assert fin(apply=True) == 0
        _commit(rev_wt, "tests/test_ac2.py", "# t2\n", "test: round 2")
        _rev_log(repo, "## Request changes\n\n- AC-2")
        assert fin(apply=True) == 0
        outs.append(repr(resolvers))
        outs.append(e.bare_refs().replace(str(bare), "<bare>"))
        return outs, _stable_records(repo)

    new_out, new_recs = run(dispatch, tmp_path / "new")
    old_out, old_recs = run(round1_dispatch, tmp_path / "old")
    assert new_out == old_out
    assert "FF-PUSHED" in "".join(new_out) and "REVIEW-KEPT" in "".join(new_out)
    assert (
        set(new_recs) == set(old_recs) == {f"{_FR}.dev.pr.json", f"{_FR}.rev.pr.json"}
    )
    new_dev, old_dev = new_recs[f"{_FR}.dev.pr.json"], old_recs[f"{_FR}.dev.pr.json"]
    assert set(new_dev) - set(old_dev) == {"ff_commits"}  # DEC-0009's addition only
    assert {k: v for k, v in new_dev.items() if k != "ff_commits"} == old_dev
    assert new_recs[f"{_FR}.rev.pr.json"] == old_recs[f"{_FR}.rev.pr.json"]
