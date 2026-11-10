"""Reviewer's adversarial tests for FR-0025 (review library under
`specs/_reviews/<FR>-r<N>.md`).

These complement the Developer's `test_review_library.py`. Each one is built
to fail a plausible naive implementation, or to pin a host condition the
Developer's harness hides (its repositories set `core.autocrlf=false`, while
Git for Windows defaults to `true`).

Harness: `dispatch.py` loaded by path against a real temporary repository
with a real bare `origin`; only `gh` argv is intercepted. The pre-FR
dispatcher for the bite checks is `git show <pre-FR ref>:template/scripts/
dispatch.py` and the bite tests skip where that ref is unreachable (inside a
bootstrapped project).

Annotations are `# covers hub-tooling FR-0025:AC-N` (not the gate's form):
this file rides along into every bootstrapped project, where FR-0025 does
not exist. Every fixture here is synthetic.
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
_PRE_FR_REF = "b803216"  # main before FR-0025
_FR = "FR-0001"
_FR2 = "FR-0002"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log  # noqa: E402

_REAL_RUN = subprocess.run


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_fr0025_adversarial")


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
    d = tmp_path_factory.mktemp("pre_fr0025_adv")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0025_adv")


# ---------------------------------------------------------------------------
# Real-git fixture
# ---------------------------------------------------------------------------


def _fr_md(fr: str) -> str:
    return (
        f"---\nid: {fr}\ntitle: Synthetic {fr}\nstatus: ready\nowner: architect\n"
        'depends_on: []\ntags: []\nowns: ["src/**"]\nreads: []\n'
        "derived_from: null\npattern: null\nac_state: {}\ncreated: 2026-01-01\n"
        f"updated: 2026-01-01\n---\n\n# {fr}: Synthetic\n\n## Acceptance criteria\n\n"
        "- **AC-1:** does the first thing\n"
    )


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


def _show_bytes(repo: Path, ref: str, path: str) -> bytes | None:
    proc = _REAL_RUN(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def _blob(repo: Path, ref: str, path: str) -> str | None:
    return (
        _git(repo, "rev-parse", "--verify", "-q", f"{ref}:{path}", check=False) or None
    )


def _lib(n: int, fr: str = _FR) -> str:
    return f"specs/_reviews/{fr}-r{n}.md"


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


_REV = f"claude/rev-{_FR}"
_DEV = f"claude/dev-{_FR}"


class _Env:
    def __init__(self, repo: Path, bare: Path) -> None:
        self.repo = repo
        self.bare = bare
        self.gh: list[list[str]] = []
        self.git_argv: list[list[str]] = []

    def snapshot(self, wts: list[Path]) -> str:
        parts = [
            _git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
            _git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)"),
        ]
        for wt in wts:
            parts.append(_git(wt, "rev-parse", "HEAD"))
            parts.append(_git(wt, "status", "--porcelain", "--untracked-files=all"))
            parts.append(_git(wt, "ls-files", "--stage"))
            for p in sorted(wt.rglob("*")):
                if p.is_file() and ".git" not in p.parts:
                    parts.append(f"{p.relative_to(wt)}:{p.read_bytes().hex()}")
        return "\n".join(parts)


def _make_repo(
    tmp_path: Path, autocrlf: str = "false", attributes: str | None = None
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
    if attributes is not None:
        _write(repo / ".gitattributes", attributes)
    _write(repo / "README.md", "synthetic\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, bare


def _new_env(tmp_path: Path, monkeypatch, mod=None, **repo_kw) -> _Env:
    m = mod or dispatch
    repo, bare = _make_repo(tmp_path, **repo_kw)
    monkeypatch.setattr(m, "REPO_ROOT", repo)
    monkeypatch.setattr(m, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(m, "DISPATCH_DIR", repo / "_dispatch")
    monkeypatch.setattr(m, "_RUN_REGISTRY", {})
    monkeypatch.setattr(m, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(m, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(m, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (repo / "_dispatch").mkdir(exist_ok=True)
    e = _Env(repo, bare)

    def routed(cmd, *a, **k):
        if cmd and cmd[0] == "gh":
            e.gh.append(list(cmd))
            if cmd[1:3] == ["pr", "list"]:
                return SimpleNamespace(returncode=0, stdout="[]", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd and cmd[0] == "git":
            e.git_argv.append([str(c) for c in cmd])
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(m.subprocess, "run", routed)
    return e


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    return _new_env(tmp_path, monkeypatch)


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


def _rev_log(repo: Path, text: str, fr: str = _FR) -> None:
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
        {"type": "result", "subtype": "success"},
    ]
    _write(
        repo / "_dispatch" / f"{fr}.rev.log",
        "\n".join(json.dumps(ln) for ln in lines) + "\n",
    )


def _dev_and_rev(env: _Env, fr: str = _FR, mod=None) -> tuple[Path, Path]:
    m = mod or dispatch
    dev_wt = _worktree(env.repo, "dev", fr)
    _commit(dev_wt, f"src/{fr.lower()}.py", "print('thing')\n", f"feat: {fr} dev work")
    _git(env.repo, "push", "-q", "-u", "origin", f"claude/dev-{fr}")
    m._save_pr_record(
        fr, "dev", {"pr_number": 7, "branch": f"claude/dev-{fr}", "draft": True}
    )
    rev_wt = _worktree(env.repo, "rev", fr, base=f"claude/dev-{fr}")
    _commit(
        rev_wt,
        f"tests/test_{fr.lower().replace('-', '_')}.py",
        f"# @{'covers'} {fr}:AC-1\ndef test_a():\n    assert True\n",
        "test: reviewer tests",
    )
    return dev_wt, rev_wt


def _finalize(apply: bool = True, fr: str = _FR, mod=None, **kw) -> int:
    m = mod or dispatch
    return m.cmd_finalize(
        fr, "rev", apply=apply, draft=True, adapter=m.get_adapter("claude-code"), **kw
    )


_RC_BODY = "## Request changes\n\n- AC-1: boundary case missing"
_CRLF_EM = b"## Request changes\r\n\r\n- AC-1 \xe2\x80\x94 boundary case missing\r\n"


# ---------------------------------------------------------------------------
# AC-1
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-1
def test_filing_moves_the_staged_blob_not_the_edited_working_tree_file(env, capsys):
    """The Reviewer staged A, then edited the file to B without staging. The
    handoff is the index (FR-0006 AC-1), so A is filed. An implementation
    that re-reads the working tree and re-adds it files B."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    staged = b"## Request changes\n\n- staged bytes, the handoff\n"
    edited = b"## Approve\n\n- unstaged edit, never the handoff\n"
    _write(rev_wt / "REVIEW.md", staged)
    _git(rev_wt, "add", "REVIEW.md")
    staged_blob = _git(rev_wt, "rev-parse", ":REVIEW.md")
    _write(rev_wt / "REVIEW.md", edited)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _show_bytes(env.repo, _REV, _lib(1)) == staged
    assert _blob(env.repo, _REV, _lib(1)) == staged_blob
    assert _show_bytes(env.repo, _REV, "REVIEW.md") is None
    assert len(_lines(out, "REVIEW-KEPT")) == 1
    # The unstaged edit is not the filed blob, so it is left for the human.
    assert (rev_wt / "REVIEW.md").read_bytes() == edited


# covers hub-tooling FR-0025:AC-1
# covers hub-tooling FR-0025:AC-7
def test_the_filing_step_runs_no_history_rewriting_git_argv(env, capsys):
    """solution_space.fixed: one ordinary commit; never reset, rebase,
    commit --amend, checkout -f or a force push. Spied on the real argv the
    finalize issues, for a kept, a synthesised and a collision filing."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(
        rev_wt, _lib(1), b"old round one\n", f"review({_FR}): round 1 verdict=approve"
    )
    _write(rev_wt / "REVIEW.md", _CRLF_EM)
    _git(rev_wt, "add", "REVIEW.md")
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out  # collision -> r2
    dispatch._RUN_REGISTRY[(_FR, "rev")] = {
        "run_id": "r",
        "started_at": 0.0,
        "round": 3,
    }
    assert _finalize() == 0, capsys.readouterr().out  # synthesised -> r3
    assert _show_bytes(env.repo, _REV, _lib(2)) == _CRLF_EM
    assert _show_bytes(env.repo, _REV, _lib(3)) == (_RC_BODY + "\n").encode()
    forbidden = []
    for argv in env.git_argv:
        sub = argv[3:] if argv[1:2] == ["-C"] else argv[1:]
        joined = " ".join(sub)
        if (
            sub[:1] in (["reset"], ["rebase"])
            or (sub[:1] == ["commit"] and "--amend" in sub)
            or (
                sub[:1] == ["checkout"]
                and ("-f" in sub or "--force" in sub or "--" in sub)
            )
            or (
                sub[:1] == ["push"]
                and any(
                    a.startswith(("-f", "--force")) or a.startswith("+") for a in sub
                )
            )
            or (sub[:1] == ["mv"] and "-f" in sub)
        ):
            forbidden.append(joined)
    assert forbidden == []
    # The Reviewer's own file was moved in the index, not re-added from disk.
    assert any(
        a[3:5] == ["update-index", "--add"] and _lib(2) in a[-1] for a in env.git_argv
    )
    assert not any(a[3:4] == ["add"] and _lib(2) in a for a in env.git_argv)


# covers hub-tooling FR-0025:AC-1
def test_crlf_blob_on_an_autocrlf_true_host_is_filed_byte_for_byte_and_rerun_adds_nothing(
    tmp_path, monkeypatch, capsys
):
    """Git for Windows defaults `core.autocrlf=true`. A CRLF blob the
    Reviewer staged (here under `-c core.autocrlf=false`) is still moved
    byte for byte, the branch carries no root file, and a re-run is a no-op."""
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    _dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", _CRLF_EM)
    _git(rev_wt, "-c", "core.autocrlf=false", "add", "REVIEW.md")
    assert _show_bytes(rev_wt, "", "REVIEW.md") == _CRLF_EM  # a CRLF blob in the index
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _REV, _lib(1)) == _CRLF_EM
    assert _show_bytes(env.repo, _REV, "REVIEW.md") is None
    tip = _git(env.repo, "rev-parse", _REV)
    assert _finalize() == 0
    assert _git(env.repo, "rev-parse", _REV) == tip


# covers hub-tooling FR-0025:AC-1
def test_crlf_filing_on_an_autocrlf_true_host_leaves_no_root_file_in_the_rev_worktree(
    tmp_path, monkeypatch, capsys
):
    """DEC-0023's cascade: "The rev worktree has no root REVIEW.md
    afterwards." Same host condition as the test above."""
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    _dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", _CRLF_EM)
    _git(rev_wt, "-c", "core.autocrlf=false", "add", "REVIEW.md")
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _REV, _lib(1)) == _CRLF_EM
    assert not (rev_wt / "REVIEW.md").exists()
    assert _git(rev_wt, "status", "--porcelain") == ""


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("scenario", ["collision", "legacy-overwritten", "inherited"])
def test_dry_run_of_the_edge_cases_mutates_nothing(
    tmp_path, monkeypatch, capsys, scenario
):
    """The Developer's dry-run matrix covers the six AC-1 sources; these are
    the three edge cases that take their own branches in the filing step."""
    legacy = b"Verdict: approve\n\nlegacy root review of an earlier FR\n"
    env = _new_env(tmp_path, monkeypatch)
    if scenario != "collision":
        _commit(env.repo, "REVIEW.md", legacy, "legacy root review on main")
    dev_wt, rev_wt = _dev_and_rev(env)
    if scenario == "collision":
        _commit(rev_wt, _lib(1), b"old\n", f"review({_FR}): round 1 verdict=approve")
    if scenario != "inherited":
        _write(rev_wt / "REVIEW.md", b"## Request changes\n\nmine\n")
        _git(rev_wt, "add", "REVIEW.md")
    _rev_log(env.repo, _RC_BODY)
    before = env.snapshot([dev_wt, rev_wt])
    assert _finalize(apply=False) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert env.snapshot([dev_wt, rev_wt]) == before and env.gh == []
    assert "REVIEW-KEPT" not in out and "REVIEW-WRITTEN" not in out
    expected_path = _lib(2) if scenario == "collision" else _lib(1)
    would = _lines(out, "WOULD-")
    assert any(expected_path in w and "REVIEW" in w for w in would), out


# covers hub-tooling FR-0025:AC-1
def test_rerun_over_an_empty_filed_round_adds_no_commit(env, capsys):
    """AC-1 / DEC-0028 Decision 1: no pending root file and an empty round-N
    library file already on the branch (committed by hand) is "already
    filed". The first run and every re-run add no commit, print one
    REVIEW-KEPT and one WARN naming the empty file, and never refile the
    synthesised body at another round."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, _lib(1), b"", "an empty round-1 file, committed by hand")
    _rev_log(env.repo, _RC_BODY)
    tip = _git(env.repo, "rev-parse", _REV)
    for _ in range(3):
        assert _finalize() == 0, capsys.readouterr().out
        out = capsys.readouterr().out
        assert _git(env.repo, "rev-parse", _REV) == tip
        kept = _lines(out, "REVIEW-KEPT")
        assert len(kept) == 1 and _lib(1) in kept[0]
        warns = _lines(out, "WARN")
        assert len(warns) == 1 and _lib(1) in warns[0] and "empty" in warns[0]
        assert "REVIEW-WRITTEN" not in out
        assert _show_bytes(env.repo, _REV, _lib(1)) == b""
        assert _show_bytes(env.repo, _REV, _lib(2)) is None


# ---------------------------------------------------------------------------
# AC-2
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-2
def test_reader_ignores_lookalike_names_trees_and_other_refs(env):
    _dev_wt, rev_wt = _dev_and_rev(env)
    decoys = {
        f"specs/_reviews/{_FR}-r2.md": "Verdict: request-changes\n\nthe real newest\n",
        f"specs/_reviews/{_FR}-r1.md": "Verdict: approve\n\nolder\n",
        f"specs/_reviews/{_FR}0-r9.md": "Verdict: approve\n\nFR-00010 lookalike\n",
        f"specs/_reviews/X{_FR}-r9.md": "Verdict: approve\n\nprefixed\n",
        f"specs/_reviews/{_FR}-r9.MD": "Verdict: approve\n\nupper-case extension\n",
        f"specs/_reviews/{_FR}-r9.md.bak": "Verdict: approve\n\nbackup\n",
        f"specs/_reviews/{_FR}-r 9.md": "Verdict: approve\n\nspace\n",
        f"specs/_reviews/{_FR}-r8.md/inner.md": "Verdict: approve\n\na tree, not a blob\n",
        f"specs/{_FR}-r9.md": "Verdict: approve\n\nwrong directory\n",
        "REVIEW.md": "Verdict: approve\n\nroot decoy\n",
    }
    for rel, text in decoys.items():
        _write(rev_wt / rel, text)
    _git(rev_wt, "add", "-A")
    _git(rev_wt, "commit", "-q", "-m", "library and decoys")
    # A newer round on main only is not on the Reviewer's branch.
    _commit(env.repo, _lib(50), "Verdict: approve\n\non main only\n", "main-only round")
    assert dispatch._read_review_md_on_branch(_FR) == (
        "Verdict: request-changes\n\nthe real newest\n"
    )
    assert dispatch._resolve_rework_verdict(_FR, "comment") == "request-changes"


# covers hub-tooling FR-0025:AC-2
def test_pre_fr_reader_returned_the_root_decoy_so_the_reader_test_bites(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    env = _new_env(tmp_path, monkeypatch, mod=pre_fr_dispatch)
    _dev_wt, rev_wt = _dev_and_rev(env, mod=pre_fr_dispatch)
    _commit(rev_wt, _lib(1), "Verdict: request-changes\n\nfiled\n", "filed")
    _commit(rev_wt, "REVIEW.md", "Verdict: approve\n\nroot decoy\n", "decoy")
    assert pre_fr_dispatch._read_review_md_on_branch(_FR) == (
        "Verdict: approve\n\nroot decoy\n"
    )


# ---------------------------------------------------------------------------
# AC-3
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-3
def test_rework_precondition_holds_for_a_crlf_blob_on_an_autocrlf_true_host(
    tmp_path, monkeypatch, capsys
):
    """AC-3: the dev worktree carries the filed library file byte for byte.
    With `core.autocrlf=true` (Git for Windows' default) a CRLF blob checks
    out unchanged, byte for byte, yet `git hash-object` on it hashes the
    LF-normalised text. A precondition that compares `hash-object` of the
    working file to the blob refuses a correct sync."""
    env = _new_env(tmp_path, monkeypatch, autocrlf="true")
    dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", _CRLF_EM)
    _git(rev_wt, "-c", "core.autocrlf=false", "add", "REVIEW.md")
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _REV, _lib(1)) == _CRLF_EM
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert (dev_wt / _lib(1)).read_bytes() == _CRLF_EM  # the sync is correct ...
    assert _git(dev_wt, "status", "--porcelain", "--", _lib(1)) == ""
    assert ok, note  # ... so the precondition must pass


# covers hub-tooling FR-0025:AC-3
def test_rework_precondition_refuses_a_locally_modified_library_file(env, capsys):
    """Adversarial: the library file is present after the sync but the dev
    worktree carries a local edit of it, so it is not the filed bytes."""
    dev_wt, _rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    _write(dev_wt / _lib(1), b"## Approve\n\ntampered in the dev worktree\n")
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert not ok and _lib(1) in note


# covers hub-tooling FR-0025:AC-3
def test_pre_fr_precondition_passed_on_a_root_file_alone_so_the_ac3_test_bites(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    env = _new_env(tmp_path, monkeypatch, mod=pre_fr_dispatch)
    dev_wt, rev_wt = _dev_and_rev(env, mod=pre_fr_dispatch)
    _commit(rev_wt, "REVIEW.md", "Verdict: approve\n\nroot only\n", "root only")
    ok, _note = pre_fr_dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok and (dev_wt / "REVIEW.md").exists()
    assert not (dev_wt / "specs" / "_reviews").exists()


# ---------------------------------------------------------------------------
# AC-4
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-4
@pytest.mark.parametrize("value", ["0", "-1", "1.0", "one", " ", "2 3"])
def test_bad_review_round_in_dry_run_is_still_one_error_and_nothing_printed_else(
    env, capsys, value
):
    dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    before = env.snapshot([dev_wt, rev_wt])
    assert _finalize(apply=False, review_round=value) != 0
    out = capsys.readouterr().out
    assert [ln for ln in out.splitlines() if ln.strip()] == _lines(out, "ERROR")
    assert len(_lines(out, "ERROR")) == 1 and "--review-round" in out
    assert env.snapshot([dev_wt, rev_wt]) == before and env.gh == []


# ---------------------------------------------------------------------------
# AC-5
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0025:AC-5
def test_two_rounds_of_one_fr_and_a_second_fr_merge_cleanly_into_main(env, capsys):
    """The dogfood shape as a test: FR-0001 gets a request-changes round 1
    and an approve round 2 (the dev branch synced and reworked between);
    FR-0002 an approve round 1. No pushed branch carries a root REVIEW.md,
    both implementation branches merge into main with real merges, and
    main ends with all three library files."""
    dev1, rev1 = _dev_and_rev(env, _FR)
    _write(rev1 / "REVIEW.md", "## Request changes\n\n- FR-0001 round one\n")
    _git(rev1, "add", "REVIEW.md")
    _rev_log(env.repo, "## Request changes\n\n- AC-1 missing")
    dispatch._RUN_REGISTRY[(_FR, "rev")] = {
        "run_id": "a",
        "started_at": 0.0,
        "round": 1,
    }
    assert _finalize() == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    _commit(dev1, "src/fix.py", "fixed\n", "fix: round 2 rework")
    _git(env.repo, "push", "-q", "origin", _DEV)
    _git(rev1, "merge", "--ff-only", "-q", _DEV)
    _write(rev1 / "REVIEW.md", "## Approve\n\nFR-0001 round two\n")
    _git(rev1, "add", "REVIEW.md")
    _rev_log(env.repo, "## Approve\n\nAll ACs covered.")
    dispatch._RUN_REGISTRY[(_FR, "rev")] = {
        "run_id": "b",
        "started_at": 0.0,
        "round": 2,
    }
    assert _finalize() == 0, capsys.readouterr().out
    capsys.readouterr()
    assert _git(env.repo, "rev-parse", _DEV) == _git(
        env.repo, "rev-parse", _REV
    )  # approve ff
    _dev2, rev2 = _dev_and_rev(env, _FR2)
    _write(rev2 / "REVIEW.md", "## Approve\n\nFR-0002 round one\n")
    _git(rev2, "add", "REVIEW.md")
    _rev_log(env.repo, "## Approve\n\nAll ACs covered.", _FR2)
    assert _finalize(fr=_FR2) == 0, capsys.readouterr().out
    for ref in (
        "refs/heads/" + _DEV,
        "refs/heads/" + _REV,
        f"refs/heads/claude/dev-{_FR2}",
        f"refs/heads/claude/rev-{_FR2}",
    ):
        assert _show_bytes(env.bare, ref, "REVIEW.md") is None, ref
    for branch in (_DEV, f"claude/dev-{_FR2}"):
        res = _REAL_RUN(
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
        assert res.returncode == 0 and "CONFLICT" not in res.stdout, (
            res.stdout + res.stderr
        )
    assert (
        _show_bytes(env.repo, "main", _lib(1))
        == b"## Request changes\n\n- FR-0001 round one\n"
    )
    assert (
        _show_bytes(env.repo, "main", _lib(2)) == b"## Approve\n\nFR-0001 round two\n"
    )
    assert (
        _show_bytes(env.repo, "main", _lib(1, _FR2))
        == b"## Approve\n\nFR-0002 round one\n"
    )
    assert _show_bytes(env.repo, "main", "REVIEW.md") is None


# ---------------------------------------------------------------------------
# Round 2: probes of `_working_file_holds_blob` (the B1 / N2 fix)
# ---------------------------------------------------------------------------

_LF_REVIEW = b"## Request changes\n\n- AC-1 \xe2\x80\x94 boundary case missing\n"


# covers hub-tooling FR-0025:AC-1
# covers hub-tooling FR-0025:AC-3
def test_bootstrapped_attributes_on_an_autocrlf_true_host_file_tidy_and_sync(
    tmp_path, monkeypatch, capsys
):
    """Every bootstrapped project carries `* text=auto eol=lf`. On a Git for
    Windows host (`core.autocrlf=true`) the Reviewer's CRLF file is stored as
    an LF blob; it is filed byte for byte as that blob, the root file leaves
    the rev worktree, and the rework sync is accepted."""
    env = _new_env(
        tmp_path, monkeypatch, autocrlf="true", attributes="* text=auto eol=lf\n"
    )
    dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", _CRLF_EM)
    _git(rev_wt, "add", "REVIEW.md")
    assert _show_bytes(rev_wt, "", "REVIEW.md") == _LF_REVIEW
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _REV, _lib(1)) == _LF_REVIEW
    assert not (rev_wt / "REVIEW.md").exists()
    assert _git(rev_wt, "status", "--porcelain") == ""
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note


# covers hub-tooling FR-0025:AC-1
@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_tidy_up_removes_the_root_file_only_when_git_itself_sees_it_unmodified(
    tmp_path, monkeypatch, capsys, autocrlf
):
    """The helper's "holds the blob" must never be looser than git's own
    "unmodified". The Reviewer stages an LF file, then rewrites the working
    copy with CRLF endings only. Under autocrlf=false git reports it
    modified, so the tidy-up must leave it; under autocrlf=true git reports
    it clean, so removing it loses nothing."""
    env = _new_env(tmp_path, monkeypatch, autocrlf=autocrlf)
    _dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", _LF_REVIEW)
    _git(rev_wt, "-c", "core.autocrlf=false", "add", "REVIEW.md")
    _write(rev_wt / "REVIEW.md", _LF_REVIEW.replace(b"\n", b"\r\n"))
    git_sees_modified = _git(rev_wt, "diff", "--name-only", "--", "REVIEW.md") != ""
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    assert _show_bytes(env.repo, _REV, _lib(1)) == _LF_REVIEW
    assert (rev_wt / "REVIEW.md").exists() == git_sees_modified
    if git_sees_modified:
        assert (rev_wt / "REVIEW.md").read_bytes() == _LF_REVIEW.replace(b"\n", b"\r\n")


# covers hub-tooling FR-0025:AC-3
@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_rework_precondition_accepts_an_eol_only_variant_only_when_git_does(
    tmp_path, monkeypatch, capsys, autocrlf
):
    """The same agreement on the dev side: after a correct sync, rewrite the
    library file with CRLF endings only. The precondition passes exactly
    when git reports the file unmodified."""
    env = _new_env(tmp_path, monkeypatch, autocrlf=autocrlf)
    dev_wt, _rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, _RC_BODY)
    assert _finalize() == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    body = (_RC_BODY + "\n").encode()
    _write(dev_wt / _lib(1), body.replace(b"\n", b"\r\n"))
    git_sees_modified = _git(dev_wt, "diff", "--name-only", "--", _lib(1)) != ""
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok == (not git_sees_modified), (ok, note, git_sees_modified)
