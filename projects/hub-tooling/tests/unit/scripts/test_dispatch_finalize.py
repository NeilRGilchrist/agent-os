"""Reviewer tests for FR-0006 — the `finalize` half: the dispatcher commits the
agent's staged index (AC-1), aborts before the push when it cannot (AC-2),
reports leftovers without adding them (AC-3), refuses an empty PR-opening
branch (AC-4) but not an empty Reviewer branch (AC-5), materialises
`REVIEW.md` on the Reviewer branch (AC-6), states the staging contract in the
developer / reviewer commands (AC-7), previews all of it in dry-run without
mutating anything (AC-12, finalize half), and leaves the FR-0002 PR metrics
intact (AC-13).

Harness: `dispatch.py` is loaded by path (as in `test_dispatch_metrics.py`)
with `REPO_ROOT` / `SPECS_DIR` / `DISPATCH_DIR` pointed at a **real temporary
git repository** — the ACs are about commits, indexes and branches, so a
stubbed git would prove nothing. Only the seams that would leave the machine
are replaced: `_gh_preflight`, `_push_branch`, the three `_finalize_*`
posters and `_repo_nwo`. Every push / post is recorded so a test can assert
it did *not* happen.

Coverage annotations are written `# covers hub-tooling FR-0006:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0006 exists and `deploy-gate.py` would fail
with "@covers references unknown FR".

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_COMMANDS_DIR = _TEMPLATE_DIR / ".agent-team" / "commands"
_FR = "FR-0001"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log


def _load_dispatch(name: str = "dispatch_under_test_fr0006_finalize"):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch()

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
- **AC-2:** does the second thing
"""


# ---------------------------------------------------------------------------
# Real-git fixture
# ---------------------------------------------------------------------------


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


def _make_repo(tmp_path: Path) -> Path:
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
    (repo / "specs").mkdir()
    (repo / "specs" / f"{_FR}-synthetic.md").write_text(
        _FR_MD, encoding="utf-8", newline="\n"
    )
    (repo / ".gitignore").write_text(
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\nPR_BODY.md\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "README.md").write_text("synthetic\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _worktree(repo: Path, role: str, base: str = "main") -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{_FR}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{_FR}", str(wt), base)
    return wt


def _stage(wt: Path, rel: str, content: str = "x\n") -> None:
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")
    _git(wt, "add", rel)


def _ahead(repo: Path, branch: str, base: str = "main") -> int:
    return int(_git(repo, "rev-list", "--count", f"{base}..{branch}"))


def _tree_paths(repo: Path, ref: str) -> set[str]:
    return set(_git(repo, "ls-tree", "-r", "--name-only", ref).splitlines())


def _write_rev_log(repo: Path, text: str) -> None:
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
        {"type": "result", "subtype": "success"},
    ]
    (repo / "_dispatch").mkdir(exist_ok=True)
    (repo / "_dispatch" / f"{_FR}.rev.log").write_text(
        "\n".join(json.dumps(ln) for ln in lines) + "\n", encoding="utf-8", newline="\n"
    )


class _Seams:
    """Records every network-facing call `cmd_finalize` would make."""

    def __init__(self) -> None:
        self.pushed: list[str] = []
        self.posted: list[tuple[str, str]] = []

    def push(self, branch: str) -> tuple[bool, str]:
        self.pushed.append(branch)
        return (True, "stub-pushed")

    def dev(self, fr_id, branch, head_sha, nwo, draft) -> int:
        self.posted.append(("dev", branch))
        return 0

    def rev(self, fr_id, branch, head_sha, nwo, adapter) -> int:
        self.posted.append(("rev", branch))
        return 0

    def oneshot(self, fr_id, branch, head_sha, nwo, draft, *, role, pr_title) -> int:
        self.posted.append((role, branch))
        return 0


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    r = _make_repo(tmp_path)
    monkeypatch.setattr(dispatch, "REPO_ROOT", r)
    monkeypatch.setattr(dispatch, "SPECS_DIR", r / "specs")
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", r / "_dispatch")
    monkeypatch.setattr(dispatch, "_RUN_REGISTRY", {})
    monkeypatch.setattr(metrics_log, "METRICS_DIR", r / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    (r / "_dispatch").mkdir()
    return r


@pytest.fixture
def seams(monkeypatch) -> _Seams:
    s = _Seams()
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(dispatch, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(dispatch, "_push_branch", s.push)
    monkeypatch.setattr(dispatch, "_finalize_dev", s.dev)
    monkeypatch.setattr(dispatch, "_finalize_rev", s.rev)
    monkeypatch.setattr(dispatch, "_finalize_oneshot", s.oneshot)
    monkeypatch.setattr(
        dispatch, "mnt_footprint_violations", lambda fr_id, branch: ([], None)
    )
    return s


def _finalize(role: str, apply: bool = True, draft: bool = True) -> int:
    adapter = dispatch.get_adapter("claude-code") if role == "rev" else None
    return dispatch.cmd_finalize(_FR, role, apply=apply, draft=draft, adapter=adapter)


# ---------------------------------------------------------------------------
# AC-1: finalize commits the staged index, verbatim, before pushing
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-1
@pytest.mark.parametrize(
    "role,base", [("dev", "main"), ("bkf", "main"), ("mnt", "main"), ("rev", "main")]
)
def test_finalize_commits_exactly_the_staged_index_for_every_role(
    repo, seams, capsys, role, base
):
    if role == "rev":
        _worktree(repo, "dev")  # rev is measured against the dev branch
        _write_rev_log(repo, "## Approve\n\nAll ACs covered.")
    wt = _worktree(repo, role)
    _stage(wt, "src/staged.py", "print('staged')\n")
    (wt / "README.md").write_text(
        "modified but NOT staged\n", encoding="utf-8"
    )  # tracked, unstaged
    (wt / "src" / "untracked.py").write_text("never added\n", encoding="utf-8")
    assert _ahead(repo, f"claude/{role}-{_FR}", base) == 0

    rc = _finalize(role)
    out = capsys.readouterr().out
    assert rc == 0, out
    branch = f"claude/{role}-{_FR}"
    subjects = _git(repo, "log", "--format=%s", f"{base}..{branch}").splitlines()
    # rev additionally carries the dispatcher's REVIEW.md commit (AC-6); the
    # staged-work commit is the first one either way.
    assert subjects[-1] == dispatch._finalize_commit_subject(_FR, role)
    assert len(subjects) == (2 if role == "rev" else 1)
    tree = _tree_paths(repo, f"{branch}~{1 if role == 'rev' else 0}")
    assert "src/staged.py" in tree
    assert "src/untracked.py" not in tree
    assert (
        _git(repo, "show", f"{branch}:README.md") == "synthetic"
    )  # unstaged edit not committed
    assert "COMMITTED    1 staged path(s)" in out
    assert seams.pushed == [branch]


# covers hub-tooling FR-0006:AC-1
def test_commit_happens_before_push_and_footprint_check(
    repo, seams, monkeypatch, capsys
):
    """Adversarial ordering: the push must see the commit, and the `mnt`
    footprint check (which diffs main..branch) must see the staged work —
    a commit placed after either would pass the happy path and fail this."""
    wt = _worktree(repo, "mnt")
    _stage(wt, "src/thing.py")
    order: list[str] = []
    seen_ahead: dict[str, int] = {}

    def push(branch):
        order.append("push")
        seen_ahead["push"] = _ahead(repo, branch)
        return (True, "ok")

    def footprint(fr_id, branch):
        order.append("footprint")
        seen_ahead["footprint"] = _ahead(repo, branch)
        return ([], None)

    monkeypatch.setattr(dispatch, "_push_branch", push)
    monkeypatch.setattr(dispatch, "mnt_footprint_violations", footprint)
    assert _finalize("mnt") == 0, capsys.readouterr().out
    assert order == ["footprint", "push"]
    assert seen_ahead == {"footprint": 1, "push": 1}


# covers hub-tooling FR-0006:AC-1
def test_agent_that_committed_itself_gets_no_extra_commit(repo, seams, capsys):
    wt = _worktree(repo, "dev")
    _stage(wt, "src/own.py")
    _git(wt, "commit", "-q", "-m", "feat: the agent committed on its own")
    assert _finalize("dev") == 0
    out = capsys.readouterr().out
    assert "COMMITTED" not in out
    assert _ahead(repo, f"claude/dev-{_FR}") == 1
    assert seams.pushed == [f"claude/dev-{_FR}"] and seams.posted == [
        ("dev", f"claude/dev-{_FR}")
    ]


# ---------------------------------------------------------------------------
# AC-2: a commit step that cannot complete aborts finalize before the push
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-2
def test_worktree_on_another_branch_aborts_before_push(repo, seams, capsys):
    wt = _worktree(repo, "dev")
    _stage(wt, "src/thing.py")
    _git(wt, "checkout", "-q", "-b", "somewhere-else")  # staged index carried over
    record = repo / "_dispatch" / f"{_FR}.dev.pr.json"
    assert _finalize("dev") == 1
    out = capsys.readouterr().out
    assert out.count("ERROR") == 1 and str(wt) in out and "somewhere-else" in out
    assert seams.pushed == [] and seams.posted == []
    assert not record.exists()
    assert _ahead(repo, f"claude/dev-{_FR}") == 0  # nothing landed on the role branch


# covers hub-tooling FR-0006:AC-2
def test_detached_head_and_missing_worktree_both_abort(repo, seams, capsys):
    wt = _worktree(repo, "dev")
    _stage(wt, "src/thing.py")
    _git(wt, "checkout", "-q", "--detach")
    assert _finalize("dev") == 1
    assert seams.pushed == []
    # Missing worktree: the branch exists (created above) but the checkout is gone.
    _git(repo, "worktree", "remove", "--force", str(wt))
    assert dispatch._git_branch_exists(f"claude/dev-{_FR}")
    assert _finalize("dev") == 1
    out = capsys.readouterr().out
    assert "worktree missing" in out and str(wt) in out
    assert seams.pushed == [] and seams.posted == []


# covers hub-tooling FR-0006:AC-2
def test_failed_git_commit_aborts_before_push(repo, seams, monkeypatch, capsys):
    """Adversarial: make `git commit` itself fail (a pre-commit hook that
    rejects) rather than the branch check. Still one ERROR, still no push."""
    wt = _worktree(repo, "dev")
    _stage(wt, "src/thing.py")
    hooks = Path(_git(wt, "rev-parse", "--git-path", "hooks"))
    if not hooks.is_absolute():
        hooks = wt / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\necho 'synthetic hook says no' >&2\nexit 1\n",
        encoding="utf-8",
        newline="\n",
    )
    hook.chmod(0o755)
    assert _finalize("dev") == 1
    out = capsys.readouterr().out
    assert out.count("ERROR") == 1 and "commit step failed" in out
    assert seams.pushed == [] and seams.posted == []
    assert _ahead(repo, f"claude/dev-{_FR}") == 0


# ---------------------------------------------------------------------------
# AC-3: leftovers are reported, never dropped silently, never added
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-3
def test_one_warn_per_category_with_counts_and_paths(repo, seams, capsys):
    wt = _worktree(repo, "dev")
    _stage(wt, "src/staged.py")
    (wt / "README.md").write_text("changed\n", encoding="utf-8")  # tracked, unstaged
    (wt / "src" / "loose.py").write_text("x\n", encoding="utf-8")  # untracked
    (wt / "PR_BODY.md").write_text(
        "ignored by .gitignore\n", encoding="utf-8"
    )  # ignored
    (wt / dispatch.VENV_DIRNAME).mkdir()
    (wt / dispatch.VENV_DIRNAME / "pyvenv.cfg").write_text(
        "ignored\n", encoding="utf-8"
    )
    assert _finalize("dev") == 0
    out = capsys.readouterr().out
    warns = [ln for ln in out.splitlines() if "WARN" in ln]
    assert len(warns) == 2
    assert any(
        "1 unstaged tracked modification(s)" in w and "README.md" in w for w in warns
    )
    assert any("1 untracked file(s)" in w and "src/loose.py" in w for w in warns)
    assert "PR_BODY.md" not in out and dispatch.VENV_DIRNAME not in out
    # Never added: the index is empty after finalize and the tree lacks them.
    assert _git(wt, "diff", "--cached", "--name-only") == ""
    tree = _tree_paths(repo, f"claude/dev-{_FR}")
    assert (
        "src/loose.py" not in tree
        and _git(repo, "show", f"claude/dev-{_FR}:README.md") == "synthetic"
    )


# covers hub-tooling FR-0006:AC-3
def test_only_ignored_leftovers_print_no_warn_and_more_than_ten_paths_are_capped(
    repo, seams, capsys
):
    wt = _worktree(repo, "dev")
    _stage(wt, "src/staged.py")
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    assert _finalize("dev") == 0
    assert "WARN" not in capsys.readouterr().out
    # Twelve untracked files: the line carries 10 paths and a "+2 more" tail.
    for i in range(12):
        (wt / "src" / f"u{i:02d}.py").write_text("x\n", encoding="utf-8")
    _stage(wt, "src/again.py")
    assert _finalize("dev") == 0
    out = capsys.readouterr().out
    warn = next(ln for ln in out.splitlines() if "WARN" in ln)
    assert "12 untracked file(s)" in warn and "+2 more" in warn
    assert warn.count("src/u") == 10


# ---------------------------------------------------------------------------
# AC-4 / AC-5: zero commits over base
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-4
@pytest.mark.parametrize("role", ["dev", "bkf", "mnt"])
def test_pr_opening_roles_refuse_an_empty_branch(repo, seams, capsys, role):
    """The FR-0015 shape: agent finished, nothing staged, nothing committed."""
    wt = _worktree(repo, role)
    (wt / "src").mkdir()
    (wt / "src" / "forgot_to_stage.py").write_text("x\n", encoding="utf-8")
    record = repo / "_dispatch" / f"{_FR}.{role}.pr.json"
    assert _finalize(role) == 1
    out = capsys.readouterr().out
    errors = [ln for ln in out.splitlines() if "ERROR" in ln]
    assert len(errors) == 1
    assert (
        "adds no commits over main" in errors[0]
        and str(wt) in errors[0]
        and "re-run finalize" in errors[0]
    )
    assert seams.pushed == [] and seams.posted == [] and not record.exists()


# covers hub-tooling FR-0006:AC-4
def test_uncountable_commits_are_refused_too(repo, seams, monkeypatch, capsys):
    wt = _worktree(repo, "dev")
    _stage(wt, "src/thing.py")
    monkeypatch.setattr(dispatch, "_commits_ahead", lambda branch, base: None)
    assert _finalize("dev") == 1
    out = capsys.readouterr().out
    assert "cannot count commits" in out and seams.pushed == []
    # The staged work was still committed (durable), so a re-run can proceed.
    assert _ahead(repo, f"claude/dev-{_FR}") == 1


# covers hub-tooling FR-0006:AC-5
def test_reviewer_branch_equal_to_dev_tip_is_not_refused(repo, seams, capsys):
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    _worktree(repo, "rev", base=f"claude/dev-{_FR}")  # rev == dev tip, nothing staged
    _write_rev_log(repo, "## Approve\n\nRound-2 approve, no new tests.")
    assert _finalize("rev") == 0
    out = capsys.readouterr().out
    assert (
        "NOTE" in out
        and "adds no commits over claude/dev-" in out
        and "still posted" in out
    )
    assert "ERROR" not in out
    assert seams.posted == [("rev", f"claude/rev-{_FR}")]


# covers hub-tooling FR-0006:AC-5
def test_reviewer_is_measured_against_dev_not_main(repo, seams, capsys):
    """Adversarial: a rev branch that is *ahead of main* (it inherits the dev
    commits) but adds nothing over dev must produce the NOTE, proving the
    base really is the dev branch. Measured against main it would be 1 ahead
    and silent."""
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    assert _ahead(repo, f"claude/rev-{_FR}", "main") == 1
    _write_rev_log(repo, "## Approve\n\nok")
    assert _finalize("rev") == 0
    assert "NOTE" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# AC-6: the dispatcher materialises REVIEW.md on the Reviewer branch
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-6
def test_review_md_is_committed_before_push_with_the_posted_body(
    repo, seams, monkeypatch, capsys
):
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _stage(rev_wt, "tests/test_x.py", "# covers-ish\n")
    body = "## Request changes\n\n- AC-2: provenance line missing\n- AC-7: wrong item number"
    _write_rev_log(repo, body)
    ahead_at_push: dict[str, int] = {}

    def push(branch):
        ahead_at_push["n"] = _ahead(repo, branch, f"claude/dev-{_FR}")
        return (True, "ok")

    monkeypatch.setattr(dispatch, "_push_branch", push)
    assert _finalize("rev") == 0, capsys.readouterr().out
    branch = f"claude/rev-{_FR}"
    assert (
        ahead_at_push["n"] == 2
    )  # tests commit + REVIEW.md commit, both before the push
    assert _git(repo, "show", f"{branch}:REVIEW.md") == body
    assert (rev_wt / "REVIEW.md").read_bytes() == (body + "\n").encode(
        "utf-8"
    )  # LF, no CR
    subject = _git(repo, "log", "-1", "--format=%s", branch)
    assert subject == f"review({_FR}): round 1 verdict=request-changes"
    assert dispatch._read_review_md_on_branch(_FR) == body + "\n"


# covers hub-tooling FR-0006:AC-6
# covers hub-tooling FR-0013:AC-2
def test_review_md_keeps_an_agent_authored_one_and_a_rerun_keeps_it_again(
    repo, seams, capsys
):
    """The Reviewer left its own committed REVIEW.md. Under DEC-0001 (FR-0006
    v2 AC-6, implemented by FR-0013 AC-2) it is the artifact of record: kept
    byte-for-byte, no synthesised commit, one REVIEW-KEPT line — and a re-run
    of finalize keeps it again."""
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    (rev_wt / "REVIEW.md").write_text(
        "stale agent-authored text\n", encoding="utf-8", newline="\n"
    )  # 26 bytes, LF
    _git(rev_wt, "add", "REVIEW.md")
    _git(rev_wt, "commit", "-q", "-m", "reviewer wrote its own")
    _write_rev_log(repo, "## Approve\n\nround two")
    dispatch._RUN_REGISTRY[(_FR, "rev")] = {
        "run_id": "r",
        "started_at": 0.0,
        "round": 2,
    }
    assert _finalize("rev") == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    branch = f"claude/rev-{_FR}"
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "show", f"{branch}:REVIEW.md"],
            capture_output=True,
            check=True,
        ).stdout
        == b"stale agent-authored text\n"
    )
    assert _git(repo, "log", "-1", "--format=%s", branch) == "reviewer wrote its own"
    assert f"review({_FR}):" not in "\n".join(
        _git(repo, "log", "--format=%s", f"claude/dev-{_FR}..{branch}").splitlines()
    )
    kept = [ln for ln in out.splitlines() if "REVIEW-KEPT" in ln]
    assert len(kept) == 1
    assert (
        f"REVIEW.md on {branch}" in kept[0]
        and "26 bytes" in kept[0]
        and "branch" in kept[0]
    )
    # Agent wrote one, finalize re-run: still kept, still no commit.
    before = _git(repo, "rev-parse", branch)
    assert _finalize("rev") == 0
    out = capsys.readouterr().out
    assert _git(repo, "rev-parse", branch) == before
    assert _git(repo, "show", f"{branch}:REVIEW.md") == "stale agent-authored text"
    assert len([ln for ln in out.splitlines() if "REVIEW-KEPT" in ln]) == 1


# covers hub-tooling FR-0006:AC-6
def test_synthesised_review_md_carries_the_run_context_round(repo, seams, capsys):
    """No agent-authored REVIEW.md: the synthesised commit is still made and
    its subject carries the round from the run context, not a hard-coded 1."""
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _stage(rev_wt, "tests/test_x.py", "# covers-ish\n")
    _write_rev_log(repo, "## Approve\n\nround two")
    dispatch._RUN_REGISTRY[(_FR, "rev")] = {
        "run_id": "r",
        "started_at": 0.0,
        "round": 2,
    }
    assert _finalize("rev") == 0, capsys.readouterr().out
    branch = f"claude/rev-{_FR}"
    assert _git(repo, "show", f"{branch}:REVIEW.md") == "## Approve\n\nround two"
    assert (
        _git(repo, "log", "-1", "--format=%s", branch)
        == f"review({_FR}): round 2 verdict=approve"
    )
    # Re-running finalize with an unchanged body is not an error and adds no commit.
    before = _git(repo, "rev-parse", branch)
    assert _finalize("rev") == 0
    assert _git(repo, "rev-parse", branch) == before
    assert "REVIEW-KEPT" in capsys.readouterr().out


# covers hub-tooling FR-0006:AC-6
def test_review_md_satisfies_the_rework_precondition_without_a_human(
    repo, seams, capsys
):
    """End-to-end for the reason AC-6 exists: after finalize, the rework
    prep merges the rev branch into the dev worktree and requires REVIEW.md
    and a covers test there. No agent wrote REVIEW.md."""
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _stage(
        rev_wt,
        "tests/test_ac1.py",
        f"# @{'covers'} {_FR}:AC-1\ndef test_a():\n    assert True\n",
    )
    _write_rev_log(repo, "## Request changes\n\n- AC-1 wrong")
    assert _finalize("rev") == 0, capsys.readouterr().out
    ok, note = dispatch._prepare_dev_worktree_for_rework(_FR)
    assert ok, note
    assert (dev_wt / "REVIEW.md").exists()


# covers hub-tooling FR-0006:AC-6
def test_missing_reviewer_log_aborts_rev_finalize_before_push(repo, seams, capsys):
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _stage(rev_wt, "tests/test_x.py")
    assert _finalize("rev") == 1
    out = capsys.readouterr().out
    assert "no reviewer log" in out and seams.pushed == [] and seams.posted == []


# ---------------------------------------------------------------------------
# AC-7: the commands state the staging contract
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-7
def test_developer_command_states_the_staging_contract():
    text = (_COMMANDS_DIR / "developer.md").read_text(encoding="utf-8")
    dispatcher_line = next(
        ln for ln in text.splitlines() if "If a dispatcher is configured" in ln
    )
    for needle in (
        "git add",
        "Committing is optional",
        "staged index verbatim",
        "Unstaged and untracked",
        "not** part of the handoff",
    ):
        assert needle in dispatcher_line, needle
    assert "Do NOT push" in dispatcher_line and "gh pr create" in dispatcher_line
    # Non-dispatcher branch untouched.
    assert "**If no dispatcher**: Save it to `PR_BODY.md`" in text


# covers hub-tooling FR-0006:AC-7
def test_reviewer_command_makes_the_final_message_the_verdict_and_drops_self_commit_on_dispatcher_path():
    text = (_COMMANDS_DIR / "reviewer.md").read_text(encoding="utf-8")
    assert "verdict of record" in text
    assert "## Approve" in text and "## Request changes" in text
    # DEC-0018 Decision 1: the Reviewer writes and stages its own REVIEW.md;
    # the dispatcher keeps it and synthesises one only when absent.
    assert "to `REVIEW.md` at the worktree root and stage it" in text
    assert "keeps a staged or committed `REVIEW.md` byte-for-byte" in text
    assert "synthesises one from your final message only when you wrote none" in text
    # The dispatcher-path bullets must not instruct `git commit` or setting
    # PR review state; the no-dispatcher bullets still may.
    for ln in text.splitlines():
        if "If a dispatcher is configured" in ln:
            assert "git commit" not in ln, ln
            assert "review state on the PR" not in ln, ln
    assert any(
        "If no dispatcher" in ln and "git commit" in ln for ln in text.splitlines()
    )
    assert any(
        "If no dispatcher" in ln and "`Approve` review state on the PR" in ln
        for ln in text.splitlines()
    )


# covers hub-tooling FR-0006:AC-7
def test_verdict_headings_named_in_the_command_are_what_the_extractor_reads():
    """Adversarial for the doc/code contract: the exact heading the reviewer
    command prescribes must resolve to the intended verdict, and prose
    mentioning the words must not."""
    assert dispatch._extract_review_verdict("## Approve\n\nfine")[0] == "approve"
    assert (
        dispatch._extract_review_verdict("## Request changes\n\n- AC-1")[0]
        == "request-changes"
    )
    assert (
        dispatch._extract_review_verdict("I would approve but request changes first")[0]
        == "comment"
    )


# covers hub-tooling FR-0006:AC-7
def test_template_wrappers_still_point_at_the_edited_sources():
    """The template's own .claude / .cursor command files are @-pointer stubs,
    not rendered copies; they must keep pointing at the canonical sources so
    the new contract reaches agents through them."""
    for harness in (".claude", ".cursor"):
        for name in ("developer.md", "reviewer.md"):
            stub = (_TEMPLATE_DIR / harness / "commands" / name).read_text(
                encoding="utf-8"
            )
            assert f".agent-team/commands/{name}" in stub, (harness, name)


# ---------------------------------------------------------------------------
# AC-12 (finalize half): dry-run previews and mutates nothing
# ---------------------------------------------------------------------------


def _snapshot(repo: Path, wts: list[Path]) -> str:
    parts = [
        _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    ]
    for wt in wts:
        parts.append(_git(wt, "rev-parse", "HEAD"))
        parts.append(_git(wt, "status", "--porcelain"))
        parts.append(_git(wt, "diff", "--cached"))
    parts.append(",".join(sorted(p.name for p in (repo / "_dispatch").iterdir())))
    return "\n".join(parts)


# covers hub-tooling FR-0006:AC-12
def test_dry_run_previews_commit_review_and_finalize_and_changes_nothing(
    repo, seams, capsys
):
    dev_wt = _worktree(repo, "dev")
    _stage(dev_wt, "src/thing.py")
    _git(dev_wt, "commit", "-q", "-m", "feat: dev work")
    _stage(dev_wt, "src/second.py")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _stage(rev_wt, "tests/test_x.py")
    _write_rev_log(repo, "## Request changes\n\n- AC-1")
    before = _snapshot(repo, [dev_wt, rev_wt])
    assert _finalize("dev", apply=False) == 0
    dev_out = capsys.readouterr().out
    assert _finalize("rev", apply=False) == 0
    rev_out = capsys.readouterr().out
    assert "WOULD-COMMIT 1 staged path(s)" in dev_out and "WOULD-FINALIZE" in dev_out
    assert "WOULD-COMMIT 1 staged path(s)" in rev_out
    assert "WOULD-WRITE-REVIEW" in rev_out and "verdict=request-changes" in rev_out
    assert "WOULD-FINALIZE" in rev_out
    assert _snapshot(repo, [dev_wt, rev_wt]) == before
    assert not (rev_wt / "REVIEW.md").exists()
    assert seams.pushed == [] and seams.posted == []


# covers hub-tooling FR-0006:AC-12
def test_dry_run_reports_zero_commit_refusal_as_would_refuse_not_error(
    repo, seams, capsys
):
    wt = _worktree(repo, "mnt")
    before = _snapshot(repo, [wt])
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    assert "WOULD-REFUSE" in out and "ERROR" not in out and "WOULD-FINALIZE" not in out
    assert _snapshot(repo, [wt]) == before
    # And a staged-only branch is *not* refused in dry-run: the preview counts
    # the commit it would make.
    _stage(wt, "src/thing.py")
    assert _finalize("mnt", apply=False) == 0
    out = capsys.readouterr().out
    assert (
        "WOULD-COMMIT" in out and "WOULD-REFUSE" not in out and "WOULD-FINALIZE" in out
    )
    assert _ahead(repo, f"claude/mnt-{_FR}") == 0  # still uncommitted


# ---------------------------------------------------------------------------
# AC-13: existing behaviour and metrics preserved
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-13
def test_pr_opened_commits_ahead_reflects_the_post_commit_count(
    repo, monkeypatch, capsys
):
    """The real `_finalize_dev` runs after the commit step; its `pr.opened`
    record must count the commit finalize just made. Only `gh pr create` and
    the PR lookup are stubbed."""
    wt = _worktree(repo, "dev")
    _stage(wt, "src/thing.py")
    (wt / "PR_BODY.md").write_text("# body\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(dispatch, "_repo_nwo", lambda: "synthetic/repo")
    monkeypatch.setattr(dispatch, "_push_branch", lambda branch: (True, "ok"))
    monkeypatch.setattr(dispatch, "_gh_pr_for_branch", lambda branch: None)
    calls: list[list[str]] = []
    real_run = (
        subprocess.run
    )  # captured before patching: dispatch shares this module object

    def routed(cmd, *a, **k):
        # `gh` is stubbed; every git call the finalize path makes stays real.
        if cmd and cmd[0] == "gh":
            calls.append(list(cmd))
            return SimpleNamespace(
                returncode=0,
                stdout="https://github.com/synthetic/repo/pull/7\n",
                stderr="",
            )
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", routed)
    assert dispatch.cmd_finalize(_FR, "dev", apply=True, draft=True) == 0, (
        capsys.readouterr().out
    )
    assert any(c[:3] == ["gh", "pr", "create"] for c in calls)
    recs = [
        json.loads(ln)
        for f in (repo / "metrics").glob("*.ndjson")
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    opened = [r for r in recs if r["kind"] == "pr.opened"]
    assert len(opened) == 1
    assert metrics_log.validation_errors(opened[0]) == []
    assert opened[0]["commits_ahead"] == 1 and opened[0]["pr_number"] == 7


# covers hub-tooling FR-0006:AC-13
def test_no_new_metrics_kind_and_role_permissions_untouched():
    assert not any(
        k.startswith(("finalize", "commit", "sync")) for k in metrics_log.KINDS
    )
    perms = dispatch._slash_command_body  # sanity: module still importable end to end
    assert callable(perms)
    for role in ("dev", "rev", "bkf", "mnt"):
        assert dispatch._finalize_commit_subject(_FR, role).split("(")[0] in {
            "feat",
            "test",
            "chore",
        }
