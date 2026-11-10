"""Reviewer tests for FR-0013 — the Reviewer-artifact half: the Reviewer's own
`REVIEW.md` (committed or staged) is kept byte-for-byte and one is
synthesised only when absent, with the FR-0006 rework precondition still met
either way (AC-2, implementing DEC-0001); a declared `Verdict:` first line
beats a marker in the first heading, which beats today's sniffed patterns
(AC-3); and `--verdict-file` finalizes a subagent-run Reviewer with no
dispatch log, announced exactly once, precedence over the log, and a hard
stop on a missing or empty file (AC-4). The dry-run half of AC-2 (`WOULD-KEEP-
REVIEW`) and the pre-FR bite check for AC-2 (AC-10) are here too.

The post-approve half (AC-1, AC-5..AC-10) is in `test_dispatch_postapprove.py`.

Harness: as in `test_dispatch_postapprove.py` — `dispatch.py` loaded by path
against a real temporary git repository with a real bare `origin`; only `gh`
argv is intercepted (never invoked for real); `_gh_preflight` / `_repo_nwo`
stubbed. The pre-FR dispatcher for the bite check is `git show
<pre-FR ref>:template/scripts/dispatch.py` and skips inside a bootstrapped
project.

Coverage annotations are written `# covers hub-tooling FR-0013:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_finalize.py).

Every fixture here is synthetic (see tests/fixtures/README.md and
tests/fixtures/postapprove/README.md).
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
_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "postapprove"
_PRE_FR_REF = "d1926ee"
_FR = "FR-0001"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_REAL_RUN = subprocess.run


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0013_ra")


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
    d = tmp_path_factory.mktemp("pre_fr0013_ra_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0013_ra")


# ---------------------------------------------------------------------------
# Real-git fixture
# ---------------------------------------------------------------------------

_FR_MD = f"""---
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
created: 2026-01-01
updated: 2026-01-01
---

# {_FR}: Synthetic

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
    _write(repo / "specs" / f"{_FR}-synthetic.md", _FR_MD)
    _write(
        repo / ".gitignore",
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\nPR_BODY.md\n",
    )
    _write(repo / "README.md", "synthetic\n")
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


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if tag in ln]


def _show_bytes(repo: Path, ref: str, path: str = "REVIEW.md") -> bytes | None:
    proc = _REAL_RUN(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def _subjects(repo: Path, branch: str, base: str) -> list[str]:
    return _git(repo, "log", "--format=%s", f"{base}..{branch}").splitlines()


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
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(mod, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (repo / "_dispatch").mkdir(exist_ok=True)


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    repo, bare = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, repo, tmp_path)
    e = _Env(repo, bare)

    def routed(cmd, *a, **k):
        if cmd and cmd[0] == "gh":
            e.gh.append(list(cmd))
            if cmd[1:3] == ["pr", "list"]:
                return SimpleNamespace(returncode=0, stdout="[]", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", routed)
    return e


def _finalize(apply: bool = True, **kw) -> int:
    adapter = dispatch.get_adapter("claude-code")
    return dispatch.cmd_finalize(
        _FR, "rev", apply=apply, draft=True, adapter=adapter, **kw
    )


def _dev_and_rev(env: _Env) -> tuple[Path, Path]:
    """A dev branch with one commit and a parent PR record; a Reviewer
    worktree off its tip with one committed test."""
    dev_wt = _worktree(env.repo, "dev")
    _commit(dev_wt, "src/thing.py", "print('thing')\n", "feat: dev work")
    _git(env.repo, "push", "-q", "-u", "origin", f"claude/dev-{_FR}")
    dispatch._save_pr_record(
        _FR, "dev", {"pr_number": 7, "branch": f"claude/dev-{_FR}", "draft": True}
    )
    rev_wt = _worktree(env.repo, "rev", base=f"claude/dev-{_FR}")
    _commit(
        rev_wt,
        "tests/test_ac1.py",
        f"# @{'covers'} {_FR}:AC-1\ndef test_a():\n    assert True\n",
        "test: reviewer tests",
    )
    return dev_wt, rev_wt


_FIXTURE_REVIEW = (_FIXTURES / "reviewer-authored-REVIEW.md").read_bytes()
_REV_BRANCH = f"claude/rev-{_FR}"


# ---------------------------------------------------------------------------
# AC-2: the Reviewer's own REVIEW.md is kept; synthesised only when absent
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0013:AC-2
def test_agent_committed_review_md_is_kept_byte_for_byte_and_not_recommitted(
    env, capsys
):
    dev_wt, rev_wt = _dev_and_rev(env)
    assert len(_FIXTURE_REVIEW) != len(
        _FIXTURE_REVIEW.decode("utf-8")
    )  # multi-byte: bytes != chars
    _commit(rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own")
    _rev_log(env.repo, "## Approve\n\nshort final message")
    tip_before = _git(env.repo, "rev-parse", _REV_BRANCH)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _show_bytes(env.repo, _REV_BRANCH) == _FIXTURE_REVIEW
    assert (rev_wt / "REVIEW.md").read_bytes() == _FIXTURE_REVIEW
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _REV_BRANCH)
        == "reviewer wrote its own"
    )
    assert not any(
        s.startswith(f"review({_FR}):")
        for s in _subjects(env.repo, _REV_BRANCH, f"claude/dev-{_FR}")
    )
    kept = _lines(out, "REVIEW-KEPT")
    assert len(kept) == 1
    assert (
        f"REVIEW.md on {_REV_BRANCH}" in kept[0]
        and f"{len(_FIXTURE_REVIEW)} bytes" in kept[0]
    )
    assert "REVIEW-WRITTEN" not in out and "WOULD-WRITE-REVIEW" not in out
    # The guarantee FR-0006 AC-6 made is preserved by the other route.
    on_branch = dispatch._read_review_md_on_branch(_FR)
    assert on_branch and on_branch.startswith("Verdict: approve")
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert (dev_wt / "REVIEW.md").read_bytes() == _FIXTURE_REVIEW
    # The rev branch gained nothing but the approve fast-forward is a separate step.
    assert _git(env.repo, "rev-parse", _REV_BRANCH) == tip_before


# covers hub-tooling FR-0013:AC-2
def test_agent_staged_uncommitted_review_md_is_folded_in_by_the_commit_step_and_kept(
    env, capsys
):
    """Staged, not committed: the existing commit step lands it verbatim
    (`test(FR): AC coverage`), nothing synthesises over it, and the byte
    count is the agent's file."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    agent = b"## Request changes\r\n\r\n- AC-1 \xe2\x80\x94 boundary case missing\r\n"  # CRLF + em dash
    _write(rev_wt / "REVIEW.md", agent)
    _git(rev_wt, "add", "REVIEW.md")
    _rev_log(env.repo, "## Request changes\n\nposted body differs from the file")
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _show_bytes(env.repo, _REV_BRANCH) == agent  # CRLF survived: byte-for-byte
    subjects = _subjects(env.repo, _REV_BRANCH, f"claude/dev-{_FR}")
    assert subjects == [
        dispatch._finalize_commit_subject(_FR, "rev"),
        "test: reviewer tests",
    ]
    kept = _lines(out, "REVIEW-KEPT")
    assert (
        len(kept) == 1
        and f"{len(agent)} bytes" in kept[0]
        and f"REVIEW.md on {_REV_BRANCH}" in kept[0]
    )
    assert "COMMITTED    1 staged path(s)" in out and "REVIEW-WRITTEN" not in out
    assert _git(rev_wt, "diff", "--cached", "--name-only") == ""
    assert dispatch._read_review_md_on_branch(_FR)


# covers hub-tooling FR-0013:AC-2
def test_agent_staged_review_md_previews_as_kept_from_the_index_in_dry_run(env, capsys):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", "## Approve\n\nstaged only\n")
    _git(rev_wt, "add", "REVIEW.md")
    _rev_log(env.repo, "## Approve\n\nposted")
    before = env.snapshot([rev_wt])
    assert _finalize(apply=False) == 0
    out = capsys.readouterr().out
    would = _lines(out, "WOULD-KEEP-REVIEW")
    assert len(would) == 1 and "staged" in would[0] and "24 bytes" in would[0]
    assert "WOULD-WRITE-REVIEW" not in out and "WOULD-COMMIT 1 staged path(s)" in out
    assert env.snapshot([rev_wt]) == before and env.gh == []


# covers hub-tooling FR-0013:AC-2
def test_no_agent_review_md_is_synthesised_committed_and_kept_on_rerun(env, capsys):
    dev_wt, _rev_wt = _dev_and_rev(env)
    body = "## Request changes\n\n- AC-1: provenance line missing"
    _rev_log(env.repo, body)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _show_bytes(env.repo, _REV_BRANCH) == (body + "\n").encode("utf-8")
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _REV_BRANCH)
        == f"review({_FR}): round 1 verdict=request-changes"
    )
    assert len(_lines(out, "REVIEW-WRITTEN")) == 1 and "REVIEW-KEPT" not in out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note and (dev_wt / "REVIEW.md").exists()
    # Re-run: the synthesised file is now the branch's own; kept, no new commit.
    tip = _git(env.repo, "rev-parse", _REV_BRANCH)
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert _git(env.repo, "rev-parse", _REV_BRANCH) == tip
    kept = _lines(out, "REVIEW-KEPT")
    assert (
        len(kept) == 1
        and f"{len(body) + 1} bytes" in kept[0]
        and "REVIEW-WRITTEN" not in out
    )


# covers hub-tooling FR-0013:AC-2
def test_rerun_over_an_agent_committed_file_is_idempotent(env, capsys):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(
        rev_wt, "REVIEW.md", "stale agent-authored text\n", "reviewer wrote its own"
    )
    _rev_log(env.repo, "## Approve\n\nround two")
    dispatch._RUN_REGISTRY[(_FR, "rev")] = {
        "run_id": "r",
        "started_at": 0.0,
        "round": 2,
    }
    for _ in range(2):
        assert _finalize() == 0, capsys.readouterr().out
        out = capsys.readouterr().out
        assert _show_bytes(env.repo, _REV_BRANCH) == b"stale agent-authored text\n"
        assert (
            _git(env.repo, "log", "-1", "--format=%s", _REV_BRANCH)
            == "reviewer wrote its own"
        )
        assert (
            len(_lines(out, "REVIEW-KEPT")) == 1
            and "26 bytes" in out
            and "branch" in out
        )


# covers hub-tooling FR-0013:AC-2
def test_untracked_review_md_is_not_the_agents_handoff_and_a_synthesised_one_is_committed(
    env, capsys
):
    """Adversarial for "committed or staged": an untracked REVIEW.md is not
    part of the handoff (FR-0006 AC-3), so the dispatcher synthesises and
    commits its own; the file on the branch is the posted body."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", "## Approve\n\nnever staged\n")
    body = "## Request changes\n\n- AC-1 wrong"
    _rev_log(env.repo, body)
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "REVIEW-KEPT" not in out and len(_lines(out, "REVIEW-WRITTEN")) == 1
    assert _show_bytes(env.repo, _REV_BRANCH) == (body + "\n").encode("utf-8")


# covers hub-tooling FR-0013:AC-2
def test_keep_rule_does_not_swallow_a_missing_log(env, capsys):
    """Adversarial ordering: an agent-committed REVIEW.md must not let
    finalize proceed without a verdict source — the log check still fires
    first and nothing is pushed."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, "REVIEW.md", "## Approve\n\nown\n", "reviewer wrote its own")
    bare_before = env.bare_refs()
    assert _finalize() == 1
    out = capsys.readouterr().out
    assert "no reviewer log" in out and "REVIEW-KEPT" not in out
    assert env.bare_refs() == bare_before and env.gh == []


# covers hub-tooling FR-0013:AC-2
# covers hub-tooling FR-0013:AC-10
def test_pre_fr_dispatcher_overwrote_the_agents_file_so_the_keep_tests_bite(
    env, pre_fr_dispatch, monkeypatch, tmp_path, capsys
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own")
    _rev_log(env.repo, "## Approve\n\nshort final message")
    _point(monkeypatch, pre_fr_dispatch, env.repo, tmp_path)
    adapter = pre_fr_dispatch.get_adapter("claude-code")
    assert (
        pre_fr_dispatch.cmd_finalize(
            _FR, "rev", apply=True, draft=True, adapter=adapter
        )
        == 0
    ), capsys.readouterr().out
    assert _show_bytes(env.repo, _REV_BRANCH) == b"## Approve\n\nshort final message\n"
    assert _git(env.repo, "log", "-1", "--format=%s", _REV_BRANCH).startswith(
        f"review({_FR}):"
    )


# covers hub-tooling FR-0013:AC-2
@pytest.mark.parametrize(
    "content", [b"", b"\n\n", b"  \r\n\t\n"], ids=["zero-bytes", "newlines", "blanks"]
)
def test_empty_committed_review_md_counts_as_absent_and_is_replaced_with_one_warn(
    env, capsys, content
):
    """DEC-0009 / E4: an empty or whitespace-only committed REVIEW.md is not
    a review — one WARN, the synthesised one replaces it (`REVIEW-WRITTEN`),
    and the non-empty-body guarantee holds; dry-run previews the same with
    `WOULD-WRITE-REVIEW` and mutates nothing."""
    dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, "REVIEW.md", content, "reviewer committed an empty file")
    body = "## Request changes\n\n- AC-1: boundary case"
    _rev_log(env.repo, body)
    empty_tip = _git(env.repo, "rev-parse", _REV_BRANCH)
    # Dry-run first.
    before = env.snapshot([rev_wt])
    assert _finalize(apply=False) == 0
    out = capsys.readouterr().out
    warns = [w for w in _lines(out, "WARN") if "empty" in w]
    assert len(warns) == 1 and "REVIEW.md on" in warns[0] and _REV_BRANCH in warns[0]
    assert len(_lines(out, "WOULD-WRITE-REVIEW")) == 1
    assert "KEEP-REVIEW" not in out and "REVIEW-KEPT" not in out
    assert env.snapshot([rev_wt]) == before and env.gh == []
    # Apply.
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    warns = [w for w in _lines(out, "WARN") if "empty" in w]
    assert len(warns) == 1 and "replac" in warns[0]
    assert len(_lines(out, "REVIEW-WRITTEN")) == 1 and "REVIEW-KEPT" not in out
    assert _show_bytes(env.repo, _REV_BRANCH) == (body + "\n").encode("utf-8")
    assert _git(env.repo, "rev-parse", _REV_BRANCH) != empty_tip
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _REV_BRANCH)
        == f"review({_FR}): round 1 verdict=request-changes"
    )
    on_branch = dispatch._read_review_md_on_branch(_FR)
    assert on_branch and on_branch.strip()
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert (dev_wt / "REVIEW.md").read_bytes() == (body + "\n").encode("utf-8")
    # Re-run: the synthesised file is now the branch's own; kept.
    tip = _git(env.repo, "rev-parse", _REV_BRANCH)
    assert _finalize() == 0
    out = capsys.readouterr().out
    assert len(_lines(out, "REVIEW-KEPT")) == 1 and "WARN" not in out
    assert _git(env.repo, "rev-parse", _REV_BRANCH) == tip


# covers hub-tooling FR-0013:AC-2
@pytest.mark.parametrize("content", [b"", b" \n\r\n"], ids=["zero-bytes", "blanks"])
def test_empty_staged_review_md_counts_as_absent_in_dry_run_and_on_apply(
    env, capsys, content
):
    """Staged, uncommitted and empty: dry-run previews from the index (one
    WARN naming the staged file, `WOULD-WRITE-REVIEW`, nothing mutated);
    apply folds the staged file in by the existing commit step and then
    replaces it, so the branch ends with the synthesised body."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    _write(rev_wt / "REVIEW.md", content)
    _git(rev_wt, "add", "REVIEW.md")
    body = "## Approve\n\nposted body"
    _rev_log(env.repo, body)
    before = env.snapshot([rev_wt])
    assert _finalize(apply=False) == 0
    out = capsys.readouterr().out
    warns = [w for w in _lines(out, "WARN") if "empty" in w]
    assert len(warns) == 1 and "staged" in warns[0]
    assert len(_lines(out, "WOULD-WRITE-REVIEW")) == 1 and "KEEP-REVIEW" not in out
    assert env.snapshot([rev_wt]) == before and env.gh == []
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert len([w for w in _lines(out, "WARN") if "empty" in w]) == 1
    assert len(_lines(out, "REVIEW-WRITTEN")) == 1 and "REVIEW-KEPT" not in out
    assert _show_bytes(env.repo, _REV_BRANCH) == (body + "\n").encode("utf-8")
    assert _git(rev_wt, "diff", "--cached", "--name-only") == ""
    assert dispatch._read_review_md_on_branch(_FR).strip()


# covers hub-tooling FR-0013:AC-2
def test_utf8_body_with_em_dashes_survives_into_the_rework_brief_and_verdict(
    env, capsys
):
    """DEC-0009 folded finding: the committed file is decoded as UTF-8, never
    the host locale — the body `_reviewer_final_text` (the rework brief) and
    `_resolve_rework_verdict` see is the file's text, em dashes intact, and
    the byte count is the object's size."""
    dev_wt, rev_wt = _dev_and_rev(env)
    assert b"\xe2\x80\x94" in _FIXTURE_REVIEW  # an em dash, in UTF-8
    text = _FIXTURE_REVIEW.decode("utf-8")
    assert "\u2014" in text
    _commit(rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own")
    _rev_log(env.repo, "## Approve\n\nshort final message")
    assert _finalize() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    kept = _lines(out, "REVIEW-KEPT")
    assert len(kept) == 1 and f"{len(_FIXTURE_REVIEW)} bytes" in kept[0]
    on_branch = dispatch._read_review_md_on_branch(_FR)
    assert on_branch == text.replace("\r\n", "\n")
    assert "\u2014" in on_branch and "\u00e2\u20ac" not in on_branch  # no mojibake
    # The rework brief quotes the file when no log is left behind.
    (env.repo / "_dispatch" / f"{_FR}.rev.log").unlink()
    adapter = dispatch.get_adapter("claude-code")
    assert dispatch._reviewer_final_text(_FR, adapter) == on_branch
    assert dispatch._resolve_rework_verdict(_FR, "comment") == "approve"
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert (dev_wt / "REVIEW.md").read_bytes() == _FIXTURE_REVIEW


# ---------------------------------------------------------------------------
# AC-3: declared > first-heading marker > sniffed > comment; body verbatim
# ---------------------------------------------------------------------------

_PROJECT_A_L16 = (
    "## FR-0001 review — **Request changes** (round 1 of 3)\n\n- AC-2 missing\n"
)

_VERDICT_CASES = [
    # (id, text, expected)
    ("project-a-L16-heading-marker", _PROJECT_A_L16, "request-changes"),
    (
        "declared-beats-heading",
        "Verdict: approve\n\n## Request changes\n\n- x\n",
        "approve",
    ),
    (
        "declared-beats-heading-rc",
        "Verdict: request-changes\n\n## Approve\n",
        "request-changes",
    ),
    (
        "declared-case-and-spacing",
        "\n\n   VERDICT :  Request Changes\n\n## Approve\n",
        "request-changes",
    ),
    (
        "declared-space-separated",
        "verdict: request changes\n## Approve\n",
        "request-changes",
    ),
    (
        "declared-only-on-first-line",
        "Intro sentence.\nVerdict: approve\n\n## Request changes\n",
        "request-changes",
    ),
    (
        "declared-unknown-token-falls-through",
        "Verdict: comment\n\n## Approve\n",
        "approve",
    ),
    ("heading-marker-emphasis", "## Review — _approve_ with nits\n", "approve"),
    (
        "heading-marker-deep-in-text",
        "Preamble line.\n\nMore prose.\n\n### Result: Request-Changes\n",
        "request-changes",
    ),
    (
        "heading-marker-not-first-heading",
        "## Summary\n\n## Approve\n",
        "comment_or_approve",
    ),
    (
        "marker-not-on-a-heading",
        "## FR-0001 review\n\nI **approve** of the style but not the code.\n",
        "comment",
    ),
    ("hashtag-is-not-a-heading", "#approve\n\nprose\n", "comment"),
    (
        "today-seven-hashes-still-match-the-old-h2-pattern",
        "####### approve\n",
        "approve",
    ),
    (
        "today-suggested-review-approve",
        "### Suggested GitHub review (Approve)\n\nbody\n",
        "approve",
    ),
    (
        "today-suggested-body-request",
        "### Suggested review body (Request changes):\n\nbody\n",
        "request-changes",
    ),
    ("today-h2-approve", "## Approve\n\nfine\n", "approve"),
    ("today-h2-request", "## Request changes\n\n- AC-1\n", "request-changes"),
    ("today-bold-approve-line-start", "Summary\n\n**Approve**\n", "approve"),
    (
        "today-bold-request-line-start",
        "Summary\n\n**Request changes**\n",
        "request-changes",
    ),
    (
        "today-cannot-honestly-approve",
        "I cannot honestly approve this yet.\n",
        "request-changes",
    ),
    (
        "today-earliest-wins",
        "## Summary\n\n**Request changes**\n\n## Approve\n",
        "request-changes",
    ),
    ("neither", "Some prose with no verdict at all.\n", "comment"),
    ("prose-mentioning-both", "I would approve but request changes first\n", "comment"),
]


# covers hub-tooling FR-0013:AC-3
@pytest.mark.parametrize(
    "case_id,text,expected", _VERDICT_CASES, ids=[c[0] for c in _VERDICT_CASES]
)
def test_verdict_resolution_order_and_verbatim_body(case_id, text, expected):
    verdict, body = dispatch._extract_review_verdict(text)
    if expected == "comment_or_approve":
        # `## Summary` is the first heading and carries no marker; tier 3's
        # `##+ approve` pattern then matches the second heading — today's
        # behaviour, unchanged.
        expected = "approve"
    assert verdict == expected, case_id
    assert body == text  # the full text verbatim, in every case


# covers hub-tooling FR-0013:AC-3
def test_empty_or_none_text_is_still_comment_with_the_placeholder_body():
    for text in (None, ""):
        verdict, body = dispatch._extract_review_verdict(text)
        assert verdict == "comment" and "reviewer log empty" in body


# covers hub-tooling FR-0013:AC-3
def test_todays_shapes_resolve_identically_to_the_pre_fr_dispatcher(pre_fr_dispatch):
    """Every case tier 3 owns must give the same answer as before this FR;
    the two new tiers only add resolutions where the old one said `comment`."""
    for case_id, text, _expected in _VERDICT_CASES:
        old_v, old_b = pre_fr_dispatch._extract_review_verdict(text)
        new_v, new_b = dispatch._extract_review_verdict(text)
        assert old_b == new_b == text
        if case_id.startswith(("today-", "neither", "prose", "marker-not", "hashtag")):
            assert old_v == new_v, case_id
        elif case_id.startswith("declared-"):
            continue  # tier 1 overrides by design (AC-3: declared beats sniffed)
        elif new_v != old_v:
            assert old_v == "comment", (
                case_id,
                old_v,
                new_v,
            )  # tier 2 only upgrades from comment


# covers hub-tooling FR-0013:AC-3
def test_project_a_l16_heading_returned_comment_before_this_fr(pre_fr_dispatch):
    assert pre_fr_dispatch._extract_review_verdict(_PROJECT_A_L16)[0] == "comment"
    assert dispatch._extract_review_verdict(_PROJECT_A_L16)[0] == "request-changes"


# covers hub-tooling FR-0013:AC-3
def test_declared_verdict_drives_the_posted_flag_and_the_rework_resolution(env, capsys):
    """End-to-end: a `Verdict:` first line contradicting the heading is what
    reaches `gh pr review` and what `_resolve_rework_verdict` reads back."""
    _dev_wt, _rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, "Verdict: request-changes\n\n## Approve\n\nheading lies\n")
    assert _finalize() == 0, capsys.readouterr().out
    review = [c for c in env.gh if c[:3] == ["gh", "pr", "review"]]
    assert len(review) == 1 and "--request-changes" in review[0]
    assert dispatch._resolve_rework_verdict(_FR, "comment") == "request-changes"
    assert dispatch._load_pr_record(_FR, "rev")["verdict"] == "request-changes"


# ---------------------------------------------------------------------------
# AC-4: --verdict-file
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0013:AC-4
def test_verdict_file_finalizes_without_a_rev_log_and_is_announced_exactly_once(
    env, capsys, tmp_path
):
    _dev_wt, _rev_wt = _dev_and_rev(env)
    vf = tmp_path / "subagent-final.md"
    vf.write_bytes(_FIXTURE_REVIEW)  # `Verdict: approve` first line
    assert not (env.repo / "_dispatch" / f"{_FR}.rev.log").exists()
    assert _finalize(verdict_file=vf) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    announced = _lines(out, "VERDICT-FROM-FILE")
    assert len(announced) == 1 and str(vf) in announced[0]
    assert "no reviewer log" not in out
    assert "REVIEW-POSTED" in out and "verdict=approve" in out
    review = [c for c in env.gh if c[:3] == ["gh", "pr", "review"]]
    assert len(review) == 1 and "--approve" in review[0]
    # The synthesised REVIEW.md is the file's text, and the approve fast-forwarded dev.
    assert _show_bytes(env.repo, _REV_BRANCH) == _FIXTURE_REVIEW
    assert len(_lines(out, "FF-PUSHED")) == 1
    assert dispatch._load_pr_record(_FR, "rev")["body_chars"] == len(
        _FIXTURE_REVIEW.decode("utf-8")
    )


# covers hub-tooling FR-0013:AC-4
def test_verdict_file_is_announced_once_in_dry_run_too(env, capsys, tmp_path):
    _dev_wt, rev_wt = _dev_and_rev(env)
    vf = tmp_path / "v.md"
    vf.write_bytes(_FIXTURE_REVIEW)
    before = env.snapshot([rev_wt])
    assert _finalize(apply=False, verdict_file=vf) == 0
    out = capsys.readouterr().out
    assert len(_lines(out, "VERDICT-FROM-FILE")) == 1
    assert "WOULD-WRITE-REVIEW" in out and "--approve" in out
    assert env.snapshot([rev_wt]) == before and env.gh == []


# covers hub-tooling FR-0013:AC-4
def test_verdict_file_takes_precedence_over_a_conflicting_log(env, capsys):
    _dev_wt, _rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, "## Approve\n\nthe log says approve")
    vf = _FIXTURES / "verdict-request-changes.md"
    assert _finalize(verdict_file=vf) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "verdict=request-changes" in out and "FF-PUSHED" not in out
    review = [c for c in env.gh if c[:3] == ["gh", "pr", "review"]]
    assert len(review) == 1 and "--request-changes" in review[0]
    assert _show_bytes(env.repo, _REV_BRANCH) == vf.read_bytes()
    assert (
        _git(env.repo, "log", "-1", "--format=%s", _REV_BRANCH)
        == f"review({_FR}): round 1 verdict=request-changes"
    )


# covers hub-tooling FR-0013:AC-4
@pytest.mark.parametrize("shape", ["missing", "empty", "whitespace-only"])
def test_missing_or_empty_verdict_file_is_one_error_with_no_push_no_gh_and_no_record(
    env, capsys, tmp_path, shape
):
    _dev_wt, rev_wt = _dev_and_rev(env)
    _rev_log(env.repo, "## Approve\n\nthe log must not be used as a fallback")
    vf = tmp_path / "v.md"
    if shape == "empty":
        vf.write_bytes(b"")
    elif shape == "whitespace-only":
        vf.write_bytes(b"  \n\r\n\t\n")
    bare_before = env.bare_refs()
    tip_before = _git(env.repo, "rev-parse", _REV_BRANCH)
    assert _finalize(verdict_file=vf) == 1
    out = capsys.readouterr().out
    errors = _lines(out, "ERROR")
    assert len(errors) == 1 and str(vf) in errors[0] and "missing or empty" in errors[0]
    assert env.bare_refs() == bare_before and env.gh == []
    assert dispatch._load_pr_record(_FR, "rev") is None
    assert (
        _git(env.repo, "rev-parse", _REV_BRANCH) == tip_before
    )  # no synthesised commit either
    assert not (rev_wt / "REVIEW.md").exists()
    assert "PUSHED" not in out and "REVIEW-POSTED" not in out


# covers hub-tooling FR-0013:AC-4
def test_without_the_flag_and_without_a_log_the_existing_error_is_unchanged(
    env, pre_fr_dispatch, monkeypatch, tmp_path, capsys
):
    _dev_and_rev(env)
    assert _finalize() == 1
    new_err = _lines(capsys.readouterr().out, "ERROR")
    _point(monkeypatch, pre_fr_dispatch, env.repo, tmp_path)
    adapter = pre_fr_dispatch.get_adapter("claude-code")
    assert (
        pre_fr_dispatch.cmd_finalize(
            _FR, "rev", apply=True, draft=True, adapter=adapter
        )
        == 1
    )
    old_err = _lines(capsys.readouterr().out, "ERROR")
    assert (
        new_err == old_err and len(new_err) == 1 and "no reviewer log at" in new_err[0]
    )
    assert env.gh == []


# covers hub-tooling FR-0013:AC-4
def test_verdict_file_with_an_agent_committed_review_md_keeps_the_file_and_posts_the_verdict(
    env, capsys, tmp_path
):
    """AC-2 and AC-4 together: the branch's REVIEW.md is the artifact of
    record; the verdict file is only the verdict source."""
    _dev_wt, rev_wt = _dev_and_rev(env)
    _commit(rev_wt, "REVIEW.md", _FIXTURE_REVIEW, "reviewer wrote its own")
    vf = tmp_path / "v.md"
    vf.write_bytes(b"Verdict: request-changes\n\nfinal message from the subagent\n")
    assert _finalize(verdict_file=vf) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert (
        len(_lines(out, "VERDICT-FROM-FILE")) == 1
        and len(_lines(out, "REVIEW-KEPT")) == 1
    )
    assert _show_bytes(env.repo, _REV_BRANCH) == _FIXTURE_REVIEW
    assert "verdict=request-changes" in out
    assert "--request-changes" in next(
        c for c in env.gh if c[:3] == ["gh", "pr", "review"]
    )


# covers hub-tooling FR-0013:AC-4
def test_direct_finalize_rev_call_shape_is_unchanged_and_accepts_verdict_file_by_keyword(
    env, capsys, tmp_path
):
    """`test_dispatch_metrics.py` pins `_finalize_rev` with five positionals;
    the new parameter is keyword-only and reads the file with `announce=False`."""
    _dev_and_rev(env)
    vf = tmp_path / "v.md"
    vf.write_bytes(b"Verdict: approve\n")
    adapter = dispatch.get_adapter("claude-code")
    rc = dispatch._finalize_rev(
        _FR, _REV_BRANCH, "a" * 40, "synthetic/repo", adapter, verdict_file=vf
    )
    out = capsys.readouterr().out
    assert rc == 0 and "VERDICT-FROM-FILE" not in out and "verdict=approve" in out
    assert (
        dispatch._finalize_rev(_FR, _REV_BRANCH, "a" * 40, "synthetic/repo", adapter)
        == 1
    )
    assert "no reviewer log" in capsys.readouterr().out
