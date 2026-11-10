"""Tests for FR-0025 — reviews are filed per FR and per round under
`specs/_reviews/<FR>-r<N>.md`.

`finalize --role rev --apply` files the Reviewer's pending root `REVIEW.md`
(or the synthesised review) at the round's library path and takes the root
file off the branch in the same commit (AC-1); every reader uses the newest
round and nothing else (AC-2); the rework precondition, brief and prompt use
the library (AC-3); `--review-round N` names the round when the dispatcher
cannot know it (AC-4); two FRs' reviews merge into `main` without conflict
(AC-5); the library's README explains itself (AC-6); and nothing else changes
(AC-7).

Harness: as in `test_dispatch_review_artifact.py` — `dispatch.py` loaded by
path against a real temporary git repository with a real bare `origin`; only
`gh` argv is intercepted (never invoked for real); `_gh_preflight` /
`_repo_nwo` stubbed. The pre-FR dispatcher for the bite checks is `git show
<pre-FR ref>:template/scripts/dispatch.py` and skips inside a bootstrapped
project.

Coverage annotations are written `# covers hub-tooling FR-0025:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0025 exists and `deploy-gate.py` would fail
with "@covers references unknown FR".

Every fixture here is synthetic (see tests/fixtures/README.md and
tests/fixtures/review-library/README.md).
"""

from __future__ import annotations

import functools
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "review-library"
_PRE_FR_REF = "b803216"  # main before FR-0025
_FR = "FR-0001"
_FR2 = "FR-0002"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log  # noqa: E402  (sibling module, importable by name)

_REAL_RUN = subprocess.run


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0025")


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
    d = tmp_path_factory.mktemp("pre_fr0025_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0025")


# ---------------------------------------------------------------------------
# Real-git fixture
# ---------------------------------------------------------------------------


def _fr_md(fr: str) -> str:
    return f"""---
id: {fr}
title: Synthetic {fr}
status: ready
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

# {fr}: Synthetic

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
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _make_repo(
    tmp_path: Path, legacy_review: bytes | None = None, autocrlf: str = "false"
) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", autocrlf),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)
    for fr in (_FR, _FR2):
        _write(repo / "specs" / f"{fr}-synthetic.md", _fr_md(fr))
    _write(
        repo / ".gitignore",
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\nPR_BODY.md\n",
    )
    _write(repo / "README.md", "synthetic\n")
    if legacy_review is not None:
        _write(repo / "REVIEW.md", legacy_review)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, bare


def _worktree(repo: Path, role: str, fr: str = _FR, base: str = "main") -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{fr}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{fr}", str(wt), base)
    return wt


def _commit(wt: Path, rel: str, content: str | bytes, msg: str) -> str:
    _write(wt / rel, content)
    _git(wt, "add", rel)
    _git(wt, "commit", "-q", "-m", msg)
    return _git(wt, "rev-parse", "HEAD")


def _stage(wt: Path, rel: str, content: str | bytes) -> None:
    _write(wt / rel, content)
    _git(wt, "add", rel)


def _rev_log(repo: Path, text: str, fr: str = _FR) -> None:
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
        {"type": "result", "subtype": "success"},
    ]
    _write(
        repo / "_dispatch" / f"{fr}.rev.log",
        "\n".join(json.dumps(ln) for ln in lines) + "\n",
    )


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


def _show_bytes(repo: Path, ref: str, path: str) -> bytes | None:
    proc = _REAL_RUN(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def _blob(repo: Path, ref: str, path: str) -> str | None:
    out = _git(repo, "rev-parse", "--verify", "-q", f"{ref}:{path}", check=False)
    return out or None


def _subjects(repo: Path, branch: str, base: str) -> list[str]:
    return _git(repo, "log", "--format=%s", f"{base}..{branch}").splitlines()


def _lib(n: int, fr: str = _FR) -> str:
    return f"specs/_reviews/{fr}-r{n}.md"


def _rev_branch(fr: str = _FR) -> str:
    return f"claude/rev-{fr}"


def _dev_branch(fr: str = _FR) -> str:
    return f"claude/dev-{fr}"


class _Env:
    def __init__(self, repo: Path, bare: Path) -> None:
        self.repo = repo
        self.bare = bare
        self.gh: list[list[str]] = []

    def bare_refs(self) -> str:
        return _git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)")

    def snapshot(self, wts: list[Path]) -> str:
        parts = [
            _git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
            self.bare_refs(),
        ]
        for wt in wts:
            parts.append(_git(wt, "rev-parse", "HEAD"))
            parts.append(_git(wt, "status", "--porcelain", "--untracked-files=all"))
            parts.append(_git(wt, "diff", "--cached"))
            for p in sorted(wt.rglob("*")):
                if p.is_file() and ".git" not in p.parts:
                    parts.append(f"{p.relative_to(wt)}:{p.read_bytes().hex()}")
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
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(mod, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (repo / "_dispatch").mkdir(exist_ok=True)


def _route_gh(monkeypatch, e: _Env) -> None:
    def routed(cmd, *a, **k):
        if cmd and cmd[0] == "gh":
            e.gh.append(list(cmd))
            if cmd[1:3] == ["pr", "list"]:
                return SimpleNamespace(returncode=0, stdout="[]", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", routed)


def _new_env(
    tmp_path: Path,
    monkeypatch,
    legacy: bytes | None = None,
    mod=None,
    autocrlf: str = "false",
) -> _Env:
    repo, bare = _make_repo(tmp_path, legacy, autocrlf)
    _point(monkeypatch, mod or dispatch, repo, tmp_path)
    e = _Env(repo, bare)
    _route_gh(monkeypatch, e)
    return e


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    return _new_env(tmp_path, monkeypatch)


_LEGACY = b"Verdict: approve\n\nlegacy root review of an earlier FR\n"


@pytest.fixture
def legacy_env(tmp_path, monkeypatch) -> _Env:
    """`main` carries a legacy root `REVIEW.md` (another FR's, pre-library)."""
    return _new_env(tmp_path, monkeypatch, legacy=_LEGACY)


def _finalize(apply: bool = True, fr: str = _FR, mod=None, **kw) -> int:
    m = mod or dispatch
    adapter = m.get_adapter("claude-code")
    return m.cmd_finalize(fr, "rev", apply=apply, draft=True, adapter=adapter, **kw)


def _dev_and_rev(
    env: _Env, fr: str = _FR, pr_number: int = 7, mod=None
) -> tuple[Path, Path]:
    """A dev branch with one commit (pushed) and a parent PR record; a
    Reviewer worktree off its tip with one committed `@covers` test."""
    m = mod or dispatch
    dev_wt = _worktree(env.repo, "dev", fr)
    _commit(dev_wt, f"src/{fr.lower()}.py", "print('thing')\n", f"feat: {fr} dev work")
    _git(env.repo, "push", "-q", "-u", "origin", _dev_branch(fr))
    m._save_pr_record(
        fr, "dev", {"pr_number": pr_number, "branch": _dev_branch(fr), "draft": True}
    )
    rev_wt = _worktree(env.repo, "rev", fr, base=_dev_branch(fr))
    _commit(
        rev_wt,
        f"tests/test_{fr.lower().replace('-', '_')}.py",
        f"# @{'covers'} {fr}:AC-1\ndef test_a():\n    assert True\n",
        "test: reviewer tests",
    )
    return dev_wt, rev_wt


def _set_round(n: int, fr: str = _FR) -> None:
    dispatch._RUN_REGISTRY[(fr, "rev")] = {"run_id": "r", "started_at": 0.0, "round": n}


_FIXTURE_REVIEW = (_FIXTURES / "reviewer-authored-REVIEW.md").read_bytes()
_CRLF_EM = b"## Request changes\r\n\r\n- AC-1 \xe2\x80\x94 boundary case missing\r\n"
_RC_BODY = "## Request changes\n\n- AC-1: provenance line missing"


# ---------------------------------------------------------------------------
# AC-1: the review is filed at specs/_reviews/<FR>-r<N>.md
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-1
def test_committed_own_review_is_moved_to_the_library_byte_for_byte_and_rerun_adds_nothing(
    env, capsys
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    assert len(_FIXTURE_REVIEW) != len(_FIXTURE_REVIEW.decode("utf-8"))  # multi-byte
    _commit(rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own")
    agent_blob = _blob(env.repo, _rev_branch(), "REVIEW.md")
    _rev_log(env.repo, "## Request changes\n\nposted body differs from the file")
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out

    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == _FIXTURE_REVIEW
    assert _blob(env.repo, _rev_branch(), _lib(1)) == agent_blob  # moved, not re-added
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    assert _subjects(env.repo, _rev_branch(), _dev_branch()) == [
        f"review({_FR}): round 1 verdict=request-changes",
        "reviewer wrote its own",
        "test: reviewer tests",
    ]
    # One commit: adds the library file, removes the root file, nothing else.
    changed = _git(
        env.repo, "show", "--no-renames", "--name-status", "--format=", _rev_branch()
    )
    assert sorted(changed.splitlines()) == sorted([f"A\t{_lib(1)}", "D\tREVIEW.md"])
    # The worktree matches the branch.
    assert (rev_wt / _lib(1)).read_bytes() == _FIXTURE_REVIEW
    assert not (rev_wt / "REVIEW.md").exists()
    assert _git(rev_wt, "status", "--porcelain") == ""
    kept = _lines(out, "REVIEW-KEPT")
    assert len(kept) == 1
    assert _lib(1) in kept[0] and f"{len(_FIXTURE_REVIEW)} bytes" in kept[0]
    assert "branch" in kept[0]
    assert "REVIEW-WRITTEN" not in out
    assert (
        env.bare_refs().count(_git(env.repo, "rev-parse", _rev_branch())) == 1
    )  # pushed

    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip
    kept = _lines(out, "REVIEW-KEPT")
    assert len(kept) == 1 and _lib(1) in kept[0] and "already filed" in kept[0]
    assert "REVIEW-WRITTEN" not in out


# covers hub-tooling FR-0025:AC-1
def test_staged_own_review_with_crlf_and_an_em_dash_is_filed_byte_for_byte(env, capsys):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _stage(rev_wt, "REVIEW.md", _CRLF_EM)
    _rev_log(env.repo, "## Request changes\n\nposted body differs from the file")
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == _CRLF_EM
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    assert _subjects(env.repo, _rev_branch(), _dev_branch()) == [
        f"review({_FR}): round 1 verdict=request-changes",
        dispatch._finalize_commit_subject(_FR, "rev"),
        "test: reviewer tests",
    ]
    assert "COMMITTED    1 staged path(s)" in out
    kept = _lines(out, "REVIEW-KEPT")
    assert len(kept) == 1 and _lib(1) in kept[0] and f"{len(_CRLF_EM)} bytes" in kept[0]
    assert (rev_wt / _lib(1)).read_bytes() == _CRLF_EM
    assert not (rev_wt / "REVIEW.md").exists()
    assert _git(rev_wt, "status", "--porcelain") == ""
    # Re-run: nothing to file.
    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip
    assert len(_lines(capsys.readouterr().out, "REVIEW-KEPT")) == 1


# covers hub-tooling FR-0025:AC-1
def test_no_own_review_files_the_synthesised_body_and_rerun_adds_nothing(env, capsys):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    expected = (_RC_BODY + "\n").encode("utf-8")
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == expected
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _rev_branch())
        == f"review({_FR}): round 1 verdict=request-changes"
    )
    written = _lines(out, "REVIEW-WRITTEN")
    assert len(written) == 1 and _lib(1) in written[0]
    assert f"{len(expected)} bytes" in written[0] and "synthesised" in written[0]
    assert "REVIEW-KEPT" not in out
    assert (rev_wt / _lib(1)).read_bytes() == expected
    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip
    assert len(_lines(out, "REVIEW-KEPT")) == 1 and "REVIEW-WRITTEN" not in out
    assert "WARN" not in out  # same body: the assumed round is not in doubt


# covers hub-tooling FR-0025:AC-1
def test_untracked_root_review_is_left_untouched_and_the_synthesised_body_is_filed(
    env, capsys
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    untracked = b"## Approve\n\nnever staged\n"
    _write(rev_wt / "REVIEW.md", untracked)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert len(_lines(out, "REVIEW-WRITTEN")) == 1 and "REVIEW-KEPT" not in out
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == (_RC_BODY + "\n").encode()
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    assert (rev_wt / "REVIEW.md").read_bytes() == untracked
    assert _git(rev_wt, "status", "--porcelain") == "?? REVIEW.md"
    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip
    assert (rev_wt / "REVIEW.md").read_bytes() == untracked


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("content", [b"", b"  \r\n\t\n"], ids=["zero-bytes", "blanks"])
def test_committed_empty_root_review_gets_one_warn_is_removed_and_synthesised_is_filed(
    env, capsys, content
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, "REVIEW.md", content, "reviewer committed an empty file")
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    warns = _lines(out, "WARN")
    assert len(warns) == 1 and "empty" in warns[0]
    assert len(_lines(out, "REVIEW-WRITTEN")) == 1
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == (_RC_BODY + "\n").encode()
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    changed = _git(
        env.repo, "show", "--no-renames", "--name-status", "--format=", _rev_branch()
    )
    assert sorted(changed.splitlines()) == sorted([f"A\t{_lib(1)}", "D\tREVIEW.md"])
    assert not (rev_wt / "REVIEW.md").exists()
    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip
    assert "WARN" not in out and len(_lines(out, "REVIEW-KEPT")) == 1


# covers hub-tooling FR-0025:AC-1
def test_inherited_root_review_is_never_filed_or_removed(legacy_env, capsys):
    env = legacy_env
    _dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    warns = _lines(out, "WARN")
    assert len(warns) == 1 and "inherited" in warns[0] and "main" in warns[0]
    assert len(_lines(out, "REVIEW-WRITTEN")) == 1 and "REVIEW-KEPT" not in out
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == (_RC_BODY + "\n").encode()
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") == _LEGACY
    assert (
        "REVIEW.md"
        not in _git(
            env.repo, "diff", "--name-only", f"main...{_rev_branch()}"
        ).splitlines()
    )
    assert (rev_wt / "REVIEW.md").read_bytes() == _LEGACY
    assert _git(rev_wt, "status", "--porcelain") == ""
    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip


# covers hub-tooling FR-0025:AC-1
def test_own_review_over_a_legacy_root_file_is_filed_and_the_legacy_file_is_left_as_found(
    legacy_env, capsys
):
    env = legacy_env
    _dev_wt, rev_wt = _dev_and_rev(env)
    _stage(rev_wt, "REVIEW.md", _FIXTURE_REVIEW)  # overwrites the legacy file
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert len(_lines(out, "REVIEW-KEPT")) == 1 and "inherited" not in out
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == _FIXTURE_REVIEW
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") == _LEGACY
    assert (
        "REVIEW.md"
        not in _git(
            env.repo, "diff", "--name-only", f"main...{_rev_branch()}"
        ).splitlines()
    )
    assert (rev_wt / "REVIEW.md").read_bytes() == _LEGACY
    assert _git(rev_wt, "status", "--porcelain") == ""


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize(
    "filed,expected_round",
    [
        ({1: b"old round one\n"}, 2),
        ({1: b"old round one\n", 3: b"old round three\n"}, 4),
    ],
    ids=["r1-filed", "r1-and-r3-filed"],
)
def test_round_collision_files_at_the_lowest_free_round_above_the_highest_with_one_warn(
    env, capsys, filed, expected_round
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    for n, content in filed.items():
        _commit(rev_wt, _lib(n), content, f"review({_FR}): round {n} verdict=approve")
    before = {n: _blob(env.repo, _rev_branch(), _lib(n)) for n in filed}
    _stage(rev_wt, "REVIEW.md", _FIXTURE_REVIEW)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    warns = _lines(out, "WARN")
    assert len(warns) == 1
    assert "round 1" in warns[0] and f"round {expected_round}" in warns[0]
    assert _show_bytes(env.repo, _rev_branch(), _lib(expected_round)) == _FIXTURE_REVIEW
    for n in filed:
        assert _blob(env.repo, _rev_branch(), _lib(n)) == before[n]
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _rev_branch())
        == f"review({_FR}): round {expected_round} verdict=request-changes"
    )


# covers hub-tooling FR-0025:AC-1
def test_round_collision_with_equal_bytes_only_removes_the_root_file(env, capsys):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, _lib(1), _FIXTURE_REVIEW, f"review({_FR}): round 1 verdict=approve")
    r1 = _blob(env.repo, _rev_branch(), _lib(1))
    _stage(rev_wt, "REVIEW.md", _FIXTURE_REVIEW)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "WARN" not in out and len(_lines(out, "REVIEW-KEPT")) == 1
    changed = _git(
        env.repo, "show", "--no-renames", "--name-status", "--format=", _rev_branch()
    )
    assert changed.splitlines() == ["D\tREVIEW.md"]
    assert _blob(env.repo, _rev_branch(), _lib(1)) == r1
    assert _blob(env.repo, _rev_branch(), _lib(2)) is None
    assert not (rev_wt / "REVIEW.md").exists()


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("round_num", [1, 2, 10])
def test_run_context_round_names_the_library_file_and_the_subject(
    env, capsys, round_num
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _stage(rev_wt, "REVIEW.md", _FIXTURE_REVIEW)
    _rev_log(env.repo, "## Approve\n\nall covered")
    _set_round(round_num)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _show_bytes(env.repo, _rev_branch(), _lib(round_num)) == _FIXTURE_REVIEW
    assert _git(
        env.repo, "ls-tree", "--name-only", _rev_branch(), "--", "specs/_reviews/"
    ) == (_lib(round_num))
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _rev_branch())
        == f"review({_FR}): round {round_num} verdict=approve"
    )
    assert _lib(round_num) in _lines(out, "REVIEW-KEPT")[0]


# covers hub-tooling FR-0025:AC-1
def test_guessed_round_keeps_the_filed_file_and_warns_only_when_the_body_differs(
    env, capsys
):
    _dev_wt, _rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    capsys.readouterr()
    tip = _git(env.repo, "rev-parse", _rev_branch())
    r1 = _show_bytes(env.repo, _rev_branch(), _lib(1))
    # A later, unnumbered round: a different body, no run-context round.
    _rev_log(env.repo, "## Approve\n\nround two, but nobody said so")
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == r1
    warns = _lines(out, "WARN")
    assert len(warns) == 1 and "assumed" in warns[0] and "--review-round" in warns[0]
    assert len(_lines(out, "REVIEW-KEPT")) == 1
    # The same, but the round is known: no warning.
    _set_round(1)
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert "WARN" not in out and _git(env.repo, "rev-parse", _rev_branch()) == tip


_DRY_SCENARIOS = ["committed", "staged", "none", "untracked", "empty", "inherited"]


def _dry_setup(env: _Env, rev_wt: Path, scenario: str) -> None:
    if scenario == "committed":
        _commit(rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own")
    elif scenario == "staged":
        _stage(rev_wt, "REVIEW.md", _CRLF_EM)
    elif scenario == "untracked":
        _write(rev_wt / "REVIEW.md", b"## Approve\n\nnever staged\n")
    elif scenario == "empty":
        _commit(rev_wt, "REVIEW.md", b"", "reviewer committed an empty file")
    _rev_log(env.repo, _RC_BODY)


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("scenario", _DRY_SCENARIOS)
def test_dry_run_previews_the_library_path_and_mutates_nothing(
    tmp_path, monkeypatch, capsys, scenario
):
    env = _new_env(
        tmp_path, monkeypatch, legacy=_LEGACY if scenario == "inherited" else None
    )
    dev_wt, rev_wt = _dev_and_rev(env)
    _dry_setup(env, rev_wt, scenario)
    before = env.snapshot([dev_wt, rev_wt])
    assert _finalize(apply=False) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert env.snapshot([dev_wt, rev_wt]) == before and env.gh == []
    assert "REVIEW-KEPT" not in out and "REVIEW-WRITTEN" not in out
    if scenario in ("committed", "staged"):
        would = _lines(out, "WOULD-KEEP-REVIEW")
        source = "branch" if scenario == "committed" else "staged"
        assert len(would) == 1 and _lib(1) in would[0] and source in would[0]
        assert "WOULD-WRITE-REVIEW" not in out
    else:
        would = _lines(out, "WOULD-WRITE-REVIEW")
        assert len(would) == 1 and _lib(1) in would[0] and "synthesised" in would[0]
        assert "WOULD-KEEP-REVIEW" not in out
    # And the dry-run of a re-run after the real thing: already filed, no change.
    assert _finalize() == 0, capsys.readouterr().out
    capsys.readouterr()
    before = env.snapshot([dev_wt, rev_wt])
    assert _finalize(apply=False) == 0
    out = capsys.readouterr().out
    assert env.snapshot([dev_wt, rev_wt]) == before
    would = _lines(out, "WOULD-KEEP-REVIEW")
    assert len(would) == 1 and _lib(1) in would[0] and "already filed" in would[0]


# --- Round 2: core.autocrlf=true (Git for Windows' default) and DEC-0028 ----

# Two ways a filed blob and its working copy differ in bytes or in hash under
# autocrlf=true: a CRLF blob (staged with autocrlf off) checks out byte for
# byte but hash-object normalises it; a CRLF working file staged with
# autocrlf on is stored as an LF blob, so only hash-object matches.
_AUTOCRLF_CASES = ["crlf-blob", "lf-blob-crlf-file"]


def _stage_under_autocrlf(rev_wt: Path, case: str) -> bytes:
    """Stage the Reviewer's root REVIEW.md for `case`; return the blob bytes."""
    _write(rev_wt / "REVIEW.md", _CRLF_EM)
    if case == "crlf-blob":
        _git(rev_wt, "-c", "core.autocrlf=false", "add", "REVIEW.md")
        return _CRLF_EM
    _git(rev_wt, "add", "REVIEW.md")
    return _CRLF_EM.replace(b"\r\n", b"\n")


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("case", _AUTOCRLF_CASES)
def test_filing_under_autocrlf_true_leaves_no_root_file_in_the_rev_worktree(
    tmp_path, monkeypatch, capsys, case
):
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    _dev_wt, rev_wt = _dev_and_rev(env)
    blob = _stage_under_autocrlf(rev_wt, case)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert len(_lines(out, "REVIEW-KEPT")) == 1
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == blob
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None
    assert not (rev_wt / "REVIEW.md").exists()
    assert _git(rev_wt, "status", "--porcelain") == ""
    tip = _git(env.repo, "rev-parse", _rev_branch())
    assert _finalize() == 0
    assert _git(env.repo, "rev-parse", _rev_branch()) == tip


# covers hub-tooling FR-0025:AC-3
@pytest.mark.parametrize("case", _AUTOCRLF_CASES)
def test_rework_precondition_holds_under_autocrlf_true(
    tmp_path, monkeypatch, capsys, case
):
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    dev_wt, rev_wt = _dev_and_rev(env)
    blob = _stage_under_autocrlf(rev_wt, case)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert _lib(1) in note
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == blob
    assert _git(dev_wt, "status", "--porcelain", "--", _lib(1)) == ""
    held = (dev_wt / _lib(1)).read_bytes()
    assert held.replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n")


# covers hub-tooling FR-0025:AC-3
def test_rework_precondition_under_autocrlf_true_still_refuses_an_edited_library_file(
    tmp_path, monkeypatch, capsys
):
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    dev_wt, rev_wt = _dev_and_rev(env)
    _stage_under_autocrlf(rev_wt, "crlf-blob")
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    _write(dev_wt / _lib(1), b"## Approve\r\n\r\nedited after the sync\r\n")
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert not ok and _lib(1) in note


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("content", [b"", b"  \r\n\t\n"], ids=["zero-bytes", "blanks"])
@pytest.mark.parametrize("apply", [True, False], ids=["apply", "dry-run"])
def test_empty_filed_round_counts_as_filed_with_one_keep_and_one_warn(
    tmp_path, monkeypatch, capsys, content, apply
):
    """DEC-0028 Decision 1: no pending root file and an empty round-N file
    already on the branch is "already filed": no commit, one keep line, one
    WARN naming the empty file, and not the guessed-round WARN."""
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, _lib(1), content, "a hand-made empty round 1")
    _rev_log(env.repo, _RC_BODY)
    before = env.snapshot([dev_wt, rev_wt])
    tip = _git(env.repo, "rev-parse", _rev_branch())
    filed = _show_bytes(env.repo, _rev_branch(), _lib(1))  # as autocrlf stored it
    assert filed is not None and not filed.strip()
    for _ in range(2):  # the first run and a re-run alike
        assert _finalize(apply=apply) == 0, capsys.readouterr().out
        out = capsys.readouterr().out
        assert _git(env.repo, "rev-parse", _rev_branch()) == tip
        assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == filed
        assert _show_bytes(env.repo, _rev_branch(), _lib(2)) is None
        tag = "REVIEW-KEPT" if apply else "WOULD-KEEP-REVIEW"
        kept = _lines(out, tag)
        assert len(kept) == 1 and _lib(1) in kept[0] and "already filed" in kept[0]
        warns = _lines(out, "WARN")
        assert len(warns) == 1 and _lib(1) in warns[0] and "empty" in warns[0]
        assert "assumed" not in out
        assert "REVIEW-WRITTEN" not in out and "WOULD-WRITE-REVIEW" not in out
    if not apply:
        assert env.snapshot([dev_wt, rev_wt]) == before


# covers hub-tooling FR-0025:AC-1
def test_pending_root_file_over_an_empty_filed_round_is_still_a_collision(
    tmp_path, monkeypatch, capsys
):
    """DEC-0028 Decision 1 is reached only with no pending root file."""
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, _lib(1), b"", "a hand-made empty round 1")
    _stage(rev_wt, "REVIEW.md", _FIXTURE_REVIEW)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    warns = _lines(out, "WARN")
    assert len(warns) == 1 and "round 1" in warns[0] and "round 2" in warns[0]
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == b""
    assert _show_bytes(env.repo, _rev_branch(), _lib(2)) == _FIXTURE_REVIEW
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") is None


# covers hub-tooling FR-0025:AC-1
def test_legacy_restore_holds_under_autocrlf_true(tmp_path, monkeypatch, capsys):
    """DEC-0028 Decision 2, unchanged code: the merge-base blob goes back at
    the root, so the branch's net change to the legacy file is nil."""
    env = _new_env(tmp_path, monkeypatch, legacy=_LEGACY, autocrlf="true")
    _dev_wt, rev_wt = _dev_and_rev(env)
    _stage_under_autocrlf(rev_wt, "crlf-blob")
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == _CRLF_EM
    assert _show_bytes(env.repo, _rev_branch(), "REVIEW.md") == _LEGACY
    assert (
        "REVIEW.md"
        not in _git(
            env.repo, "diff", "--name-only", f"main...{_rev_branch()}"
        ).splitlines()
    )
    assert _git(rev_wt, "status", "--porcelain") == ""


# ---------------------------------------------------------------------------
# AC-2: readers find the newest round and nothing else
# ---------------------------------------------------------------------------

_R10 = "Verdict: approve\n\nround ten — the newest\n"


def _library_with_decoys(env: _Env, rev_wt: Path, with_rounds: bool = True) -> None:
    files = {
        "REVIEW.md": "Verdict: request-changes\n\ndecoy root file\n",
        f"specs/_reviews/{_FR2}-r3.md": "Verdict: request-changes\n\nanother FR\n",
        f"specs/_reviews/{_FR}-r01.md": "Verdict: request-changes\n\npadded\n",
        f"specs/_reviews/{_FR}-final.md": "Verdict: request-changes\n\nfinal\n",
        f"specs/_reviews/{_FR}-r11.txt": "Verdict: request-changes\n\nnot md\n",
        f"specs/_reviews/nested/{_FR}-r99.md": "Verdict: request-changes\n\nnested\n",
    }
    if with_rounds:
        files.update(
            {
                _lib(1): "Verdict: request-changes\n\nround one\n",
                _lib(2): "Verdict: request-changes\n\nround two\n",
                _lib(9): "Verdict: request-changes\n\nround nine\n",
                _lib(10): _R10,
            }
        )
    for rel, text in files.items():
        _stage(rev_wt, rel, text)
    _git(rev_wt, "commit", "-q", "-m", "library and decoys")


# covers hub-tooling FR-0025:AC-2
def test_reader_returns_the_highest_round_numerically_and_ignores_every_decoy(env):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _library_with_decoys(env, rev_wt)
    assert dispatch._read_review_md_on_branch(_FR) == _R10
    assert dispatch._resolve_rework_verdict(_FR, "comment") == "approve"
    adapter = dispatch.get_adapter("claude-code")
    assert not (env.repo / "_dispatch" / f"{_FR}.rev.log").exists()
    assert dispatch._reviewer_final_text(_FR, adapter) == _R10


# covers hub-tooling FR-0025:AC-2
def test_reader_returns_none_when_only_decoys_exist(env):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _library_with_decoys(env, rev_wt, with_rounds=False)
    assert dispatch._read_review_md_on_branch(_FR) is None
    assert dispatch._resolve_rework_verdict(_FR, "comment") == "comment"
    assert dispatch._reviewer_final_text(_FR, dispatch.get_adapter("claude-code")) == ""


# covers hub-tooling FR-0025:AC-2
def test_reader_returns_none_without_a_reviewer_branch(env):
    assert dispatch._read_review_md_on_branch(_FR) is None


# ---------------------------------------------------------------------------
# AC-3: the rework precondition and brief use the library
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-3
def test_finalize_then_prepare_puts_the_library_file_in_the_dev_worktree_byte_for_byte(
    env, capsys
):
    dev_wt, rev_wt = _dev_and_rev(env)
    _stage(rev_wt, "REVIEW.md", _CRLF_EM)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert _lib(1) in note
    assert (dev_wt / _lib(1)).read_bytes() == _CRLF_EM
    assert _show_bytes(env.repo, _rev_branch(), _lib(1)) == _CRLF_EM
    assert not (dev_wt / "REVIEW.md").exists()


# covers hub-tooling FR-0025:AC-3
def test_a_root_review_alone_in_the_dev_worktree_does_not_satisfy_the_precondition(env):
    dev_wt, rev_wt = _dev_and_rev(env)
    _commit(
        rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own"
    )  # never filed
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert (dev_wt / "REVIEW.md").exists()  # the sync brought it
    assert not ok
    assert f"specs/_reviews/{_FR}-r<N>.md" in note


# covers hub-tooling FR-0025:AC-3
def test_rework_brief_and_prompt_name_the_library_path_not_the_root_file(
    env, monkeypatch, capsys
):
    dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    _set_round(2)
    assert _finalize() == 0, capsys.readouterr().out
    prompts: list[str | None] = []

    def fake_spawn(fr_id, role, apply, adapter, extra_prompt=None, round_num=1, **kw):
        prompts.append(extra_prompt)
        return ("error", None, None)

    monkeypatch.setattr(dispatch, "spawn_role", fake_spawn)
    monkeypatch.setattr(dispatch, "_collect_failing_tests", lambda wt: [])
    verdict, note = dispatch._run_one_rework_round(
        _FR,
        2,
        3,
        "the verdict text",
        True,
        dispatch.get_adapter("claude-code"),
        1.0,
        0.1,
    )
    assert verdict is None and "dev re-dispatch failed" in note
    brief = (dev_wt / "_dispatch" / f"round2-{_FR}-dev.md").read_text(encoding="utf-8")
    fallback = [ln for ln in brief.splitlines() if "none captured mechanically" in ln]
    assert len(fallback) == 1 and _lib(2) in fallback[0]
    assert "REVIEW.md" not in brief
    assert len(prompts) == 1 and _lib(2) in prompts[0] and "REVIEW.md" not in prompts[0]


# covers hub-tooling FR-0025:AC-3
def test_brief_fallback_line_names_the_given_path():
    brief = dispatch._generate_rework_brief(
        fr_id=_FR,
        fr_title="Synthetic",
        round_num=2,
        budget=3,
        verdict_text="v",
        failing_tests=[],
        owns=["src/**"],
        review_path=_lib(4),
    )
    assert f"`{_lib(4)}` in your worktree" in brief and "REVIEW.md" not in brief


# ---------------------------------------------------------------------------
# AC-4: --review-round N
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-4
@pytest.mark.parametrize("staged", [True, False], ids=["staged-own", "synthesised"])
def test_hand_run_round_two_files_r2_and_leaves_r1_unchanged(
    env, tmp_path, capsys, staged
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    capsys.readouterr()
    r1 = _blob(env.repo, _rev_branch(), _lib(1))
    # A hand-run round-2 Reviewer (subagent): no log, no lock, a verdict file.
    (env.repo / "_dispatch" / f"{_FR}.rev.log").unlink()
    verdict_file = tmp_path / "verdict.md"
    verdict_file.write_bytes(_FIXTURE_REVIEW)
    if staged:
        _stage(rev_wt, "REVIEW.md", _CRLF_EM)
    assert _finalize(review_round="2", verdict_file=verdict_file) == 0, (
        capsys.readouterr().out
    )
    out = capsys.readouterr().out
    expected = _CRLF_EM if staged else _FIXTURE_REVIEW
    assert _show_bytes(env.repo, _rev_branch(), _lib(2)) == expected
    assert _blob(env.repo, _rev_branch(), _lib(1)) == r1
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _rev_branch())
        == f"review({_FR}): round 2 verdict=request-changes"
    )
    assert "WARN" not in out
    # The text reader decodes with universal newlines (unchanged by this FR).
    text = expected.decode("utf-8")
    assert dispatch._read_review_md_on_branch(_FR) == text.replace(
        chr(13) + chr(10), chr(10)
    )


# covers hub-tooling FR-0025:AC-4
def test_review_round_overrides_the_run_context_round(env, capsys):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    _set_round(2)
    assert _finalize(review_round=5) == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _rev_branch(), _lib(5)) is not None
    assert _show_bytes(env.repo, _rev_branch(), _lib(2)) is None


# covers hub-tooling FR-0025:AC-4
@pytest.mark.parametrize(
    "role,value",
    [
        ("dev", "2"),
        ("mnt", "1"),
        ("bkf", 1),
        ("rev", "0"),
        ("rev", "-3"),
        ("rev", 0),
        ("rev", "abc"),
        ("rev", "2.5"),
        ("rev", ""),
    ],
)
def test_bad_review_round_is_one_error_nonzero_and_nothing_done(
    env, capsys, role, value
):
    dev_wt, rev_wt = _dev_and_rev(env)
    _stage(rev_wt, "REVIEW.md", _CRLF_EM)
    _stage(dev_wt, "src/more.py", "more\n")
    _rev_log(env.repo, _RC_BODY)
    before = env.snapshot([dev_wt, rev_wt])
    adapter = dispatch.get_adapter("claude-code")
    rc = dispatch.cmd_finalize(
        _FR, role, apply=True, draft=True, adapter=adapter, review_round=value
    )
    out = capsys.readouterr().out
    assert rc != 0
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and "--review-round" in errors[0]
    assert len([ln for ln in out.splitlines() if ln.strip()]) == 1
    assert env.snapshot([dev_wt, rev_wt]) == before and env.gh == []


# covers hub-tooling FR-0025:AC-4
def test_cli_passes_review_round_through_and_a_non_integer_is_the_dispatchers_error(
    env, monkeypatch, capsys
):
    dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    before = env.snapshot([dev_wt, rev_wt])
    monkeypatch.setattr(
        sys,
        "argv",
        ["dispatch.py", "finalize", _FR, "--role", "rev", "--review-round", "x2"],
    )
    assert dispatch.main() == 1  # not argparse's SystemExit(2)
    out = capsys.readouterr().out
    assert len(_lines(out, "ERROR")) == 1 and "--review-round" in out
    assert env.snapshot([dev_wt, rev_wt]) == before
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "finalize",
            _FR,
            "--role",
            "rev",
            "--review-round",
            "3",
            "--apply",
        ],
    )
    assert dispatch.main() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _rev_branch(), _lib(3)) == (_RC_BODY + "\n").encode()


# ---------------------------------------------------------------------------
# AC-5: two FRs' reviews merge without conflict
# ---------------------------------------------------------------------------


def _review_and_approve(env: _Env, fr: str, pr_number: int, mod=None) -> None:
    _dev_wt, rev_wt = _dev_and_rev(env, fr, pr_number, mod=mod)
    _stage(rev_wt, "REVIEW.md", f"Verdict: approve\n\n{fr} review — own\n")
    _rev_log(env.repo, "## Approve\n\nAll ACs covered.", fr)


def _merge_into_main(env: _Env, branch: str) -> subprocess.CompletedProcess:
    return _REAL_RUN(
        [
            "git",
            "-C",
            str(env.repo),
            "merge",
            "--no-edit",
            "-m",
            f"merge {branch}",
            branch,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _two_fr_scenario(env: _Env, capsys, mod=None) -> None:
    # Both Reviewer branches are cut from the same main before either merges.
    _review_and_approve(env, _FR, 7, mod)
    _review_and_approve(env, _FR2, 8, mod)
    for fr in (_FR, _FR2):
        assert _finalize(fr=fr, mod=mod) == 0, capsys.readouterr().out
        out = capsys.readouterr().out
        assert "FF-PUSHED" in out, out  # the approve fast-forwarded the dev branch
        assert _git(env.repo, "rev-parse", _dev_branch(fr)) == _git(
            env.repo, "rev-parse", _rev_branch(fr)
        )


# covers hub-tooling FR-0025:AC-5
def test_two_frs_reviews_merge_into_main_without_conflict(env, capsys):
    _two_fr_scenario(env, capsys)
    for fr in (_FR, _FR2):
        assert _show_bytes(env.repo, _dev_branch(fr), "REVIEW.md") is None
        assert _show_bytes(env.repo, _rev_branch(fr), "REVIEW.md") is None
    first = _merge_into_main(env, _dev_branch(_FR))
    assert first.returncode == 0, first.stdout + first.stderr
    second = _merge_into_main(env, _dev_branch(_FR2))
    assert second.returncode == 0 and "CONFLICT" not in second.stdout, (
        second.stdout + second.stderr
    )
    for fr in (_FR, _FR2):
        assert _show_bytes(env.repo, "main", _lib(1, fr)) == (
            f"Verdict: approve\n\n{fr} review — own\n".encode()
        )
    assert _show_bytes(env.repo, "main", "REVIEW.md") is None


# covers hub-tooling FR-0025:AC-5
def test_two_frs_merge_cleanly_over_a_legacy_root_review_and_leave_it_unchanged(
    legacy_env, capsys
):
    env = legacy_env
    _two_fr_scenario(env, capsys)
    for fr in (_FR, _FR2):
        assert _show_bytes(env.repo, _dev_branch(fr), "REVIEW.md") == _LEGACY
    for branch in (_dev_branch(_FR), _dev_branch(_FR2)):
        res = _merge_into_main(env, branch)
        assert res.returncode == 0 and "CONFLICT" not in res.stdout, (
            res.stdout + res.stderr
        )
    assert _show_bytes(env.repo, "main", "REVIEW.md") == _LEGACY
    assert _show_bytes(env.repo, "main", _lib(1, _FR)) is not None
    assert _show_bytes(env.repo, "main", _lib(1, _FR2)) is not None


# covers hub-tooling FR-0025:AC-5
def test_pre_fr_dispatcher_conflicts_on_the_second_merge_so_the_merge_test_bites(
    tmp_path, monkeypatch, capsys, pre_fr_dispatch
):
    env = _new_env(tmp_path, monkeypatch, mod=pre_fr_dispatch)
    _two_fr_scenario(env, capsys, mod=pre_fr_dispatch)
    first = _merge_into_main(env, _dev_branch(_FR))
    assert first.returncode == 0, first.stdout + first.stderr
    second = _merge_into_main(env, _dev_branch(_FR2))
    assert second.returncode != 0 and "REVIEW.md" in second.stdout


# ---------------------------------------------------------------------------
# AC-6: the library explains itself
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-6
def test_library_readme_states_the_scheme_the_writer_the_reader_and_the_migration():
    text = (_TEMPLATE_DIR / "specs" / "_reviews" / "README.md").read_text(
        encoding="utf-8"
    )
    # 1. the path scheme and how N is chosen
    assert "specs/_reviews/<FR>-r<N>.md" in text and "--review-round" in text
    # 2. written only by finalize --role rev, one commit per round, never edited
    assert "finalize <FR> --role rev" in text
    assert "One commit per round" in text and "never edited" in text
    # 3. the newest round is the one the dispatcher reads
    assert "newest round" in text
    # 4. the one-time migration of a legacy root REVIEW.md
    assert "git mv REVIEW.md specs/_reviews/<FR>-r<N>.md" in text


# ---------------------------------------------------------------------------
# AC-7: nothing else changes
# ---------------------------------------------------------------------------


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


# covers hub-tooling FR-0025:AC-7
def test_approve_posts_once_fast_forwards_through_the_filing_commit_and_adds_no_metrics(
    env, capsys
):
    dev_wt, _rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, "## Approve\n\nAll ACs covered.")
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    posted = _lines(out, "REVIEW-POSTED")
    assert len(posted) == 1 and "verdict=approve" in posted[0]
    reviews = [c for c in env.gh if c[1:3] == ["pr", "review"]]
    assert len(reviews) == 1 and "--approve" in reviews[0]
    # The fast-forwarded range includes the filing commit.
    assert _git(env.repo, "rev-parse", _dev_branch()) == _git(
        env.repo, "rev-parse", _rev_branch()
    )
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _dev_branch())
        == f"review({_FR}): round 1 verdict=approve"
    )
    assert (dev_wt / _lib(1)).exists()
    recs = _records()
    assert recs
    for r in recs:
        assert metrics_log.validation_errors(r) == [], r
        assert r["kind"] in metrics_log.KINDS


# covers hub-tooling FR-0025:AC-7
def test_role_permissions_metrics_shape_and_protected_paths_match_the_pre_fr_dispatcher(
    tmp_path, monkeypatch, capsys, pre_fr_dispatch
):
    for adapter in ("ClaudeCodeAdapter", "CursorAdapter"):
        assert (
            getattr(dispatch, adapter).ROLE_PERMISSIONS
            == getattr(pre_fr_dispatch, adapter).ROLE_PERMISSIONS
        ), adapter
    assert dispatch.MNT_PROTECTED_GLOBS == pre_fr_dispatch.MNT_PROTECTED_GLOBS
    shapes = {}
    for label, mod in (("post", dispatch), ("pre", pre_fr_dispatch)):
        env = _new_env(tmp_path / label, monkeypatch, mod=mod)
        _dev_and_rev(env, mod=mod)
        _rev_log(env.repo, "## Approve\n\nAll ACs covered.")
        assert _finalize(mod=mod) == 0, capsys.readouterr().out
        capsys.readouterr()
        shapes[label] = sorted((r["kind"], tuple(sorted(r))) for r in _records())
    assert shapes["post"] == shapes["pre"] and shapes["post"]
