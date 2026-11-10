"""Reviewer tests for FR-0006 — the dispatch half: Developer / maintainer
runnability reads the FR status committed on the role branch (AC-8), the
unfiltered selection applies the same rule and says why (AC-9), a reused
Reviewer worktree is fast-forwarded onto the Developer's tip (AC-10), an
impossible fast-forward refuses the spawn and stops a rework round as a
precondition failure without ever force-syncing (AC-11), and dry-run
previews all of it without mutating anything (AC-12, dispatch half).

Harness: `dispatch.py` loaded by path with its path globals pointed at a real
temporary git repository (branches, worktrees and ancestry are the subject),
a fake harness adapter that records spawns instead of launching anything, and
the venv provisioner / gh preflight / reconcile stubbed. No network, no
`claude` binary.

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
_FR = "FR-0001"
_FR2 = "FR-0002"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log


def _load_dispatch(name: str = "dispatch_under_test_fr0006_runnability"):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch()


def _fr_md(fr_id: str, status: str = "ready") -> str:
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
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

# {fr_id}: Synthetic

## Acceptance criteria

- **AC-1:** does the first thing
"""


# ---------------------------------------------------------------------------
# Real-git fixture + fake adapter
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


def _make_repo(tmp_path: Path, frs: dict[str, str] | None = None) -> Path:
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
    for fr_id, status in (frs or {_FR: "ready"}).items():
        (repo / "specs" / f"{fr_id}-synthetic.md").write_text(
            _fr_md(fr_id, status), encoding="utf-8", newline="\n"
        )
    (repo / ".gitignore").write_text(
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _worktree(repo: Path, role: str, fr_id: str = _FR, base: str = "main") -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{fr_id}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{fr_id}", str(wt), base)
    return wt


def _commit_file(wt: Path, rel: str, content: str, msg: str) -> str:
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")
    _git(wt, "add", rel)
    _git(wt, "commit", "-q", "-m", msg)
    return _git(wt, "rev-parse", "HEAD")


def _flip_status(wt: Path, fr_id: str, status: str, *, commit: bool) -> None:
    p = wt / "specs" / f"{fr_id}-synthetic.md"
    p.write_text(_fr_md(fr_id, status), encoding="utf-8", newline="\n")
    _git(wt, "add", str(p.relative_to(wt)))
    if commit:
        _git(wt, "commit", "-q", "-m", f"status -> {status}")


def _sha(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref)


class _FakeAdapter:
    name = "fake"
    binary_name = "fake"

    def __init__(self) -> None:
        self.spawns: list[tuple[str, str, Path, str | None]] = []
        self.settings_written: list[Path] = []

    def write_worktree_settings(self, wt_path: Path, role: str, fr_id: str) -> None:
        self.settings_written.append(wt_path)

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.spawns.append((fr_id, role, wt_path, extra_prompt))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type":"result","subtype":"success"}\n', encoding="utf-8")
        return ("spawned", 999_999)

    def parse_log(self, log_path: Path):
        return SimpleNamespace(last_text="", result_subtype="success", tool_calls=0)

    def dry_run_preview(self, fr_id: str, role: str, wt_preview: Path) -> str:
        return f"fake-preview {role} {fr_id}"


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    r = _make_repo(tmp_path)
    _point(monkeypatch, r)
    return r


def _point(monkeypatch, r: Path) -> None:
    monkeypatch.setattr(dispatch, "REPO_ROOT", r)
    monkeypatch.setattr(dispatch, "SPECS_DIR", r / "specs")
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", r / "_dispatch")
    monkeypatch.setattr(dispatch, "LAST_TICK_FILE", r / "_dispatch" / ".last-tick")
    monkeypatch.setattr(dispatch, "ESCALATIONS_DIR", r / "specs" / "_escalations")
    monkeypatch.setattr(dispatch, "_RUN_REGISTRY", {})
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (True, "venv:stub"))
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(
        dispatch,
        "reconcile_merged_prs",
        lambda apply=False, verbose=False: dispatch.ReconcileSummary(
            flipped=[], cleaned=[], skipped=[]
        ),
    )
    monkeypatch.setattr(dispatch, "prune_dead_locks", lambda verbose=True: 0)
    monkeypatch.setattr(metrics_log, "METRICS_DIR", r / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    (r / "_dispatch").mkdir(exist_ok=True)


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter()


def _handed_off_dev(repo: Path, status: str = "in-progress") -> Path:
    """Dev worktree whose branch carries a committed status flip; main stays `ready`."""
    wt = _worktree(repo, "dev")
    _commit_file(wt, "src/thing.py", "x\n", "feat: work")
    _flip_status(wt, _FR, status, commit=True)
    assert "status: ready" in (repo / "specs" / f"{_FR}-synthetic.md").read_text(
        encoding="utf-8"
    )
    return wt


# ---------------------------------------------------------------------------
# AC-8: targeted dev / mnt runnability honours the role branch's status
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-8
@pytest.mark.parametrize("status", ["in-progress", "in-review"])
def test_committed_flip_on_dev_branch_refuses_fresh_dev_with_actionable_reason(
    repo, adapter, status, capsys
):
    _handed_off_dev(repo, status)
    frs = dispatch.load_frs()
    reason = dispatch.explain_not_runnable(_FR, frs, "dev")
    assert reason is not None
    assert f"claude/dev-{_FR}" in reason and f"'{status}'" in reason
    assert f"tick --role rev --fr {_FR}" in reason and "rework" in reason
    # tick --fr: abort, exit 1, no spawn.
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 1
    )
    assert adapter.spawns == []
    assert reason in capsys.readouterr().out


# covers hub-tooling FR-0006:AC-8
def test_wave_fr_aborts_on_a_handed_off_fr_even_though_main_reads_ready(
    repo, adapter, capsys
):
    _handed_off_dev(repo)
    rc = dispatch.cmd_wave(
        apply=True,
        adapter=adapter,
        fr_filter=[_FR],
        timeout=5,
        phase_timeout=5,
        poll_interval=0.01,
    )
    out = capsys.readouterr().out
    assert rc == 1 and adapter.spawns == []
    assert "Wave aborted" in out and "already handed off" in out


# covers hub-tooling FR-0006:AC-8
def test_maintainer_branch_with_committed_flip_refuses_oneshot(repo, adapter, capsys):
    wt = _worktree(repo, "mnt")
    _flip_status(wt, _FR, "in-progress", commit=True)
    assert dispatch.cmd_oneshot(_FR, "mnt", apply=True, adapter=adapter) == 1
    out = capsys.readouterr().out
    assert "SKIP" in out and f"claude/mnt-{_FR}" in out and adapter.spawns == []


# covers hub-tooling FR-0006:AC-8
def test_role_branch_still_reading_ready_stays_runnable_and_reuses_the_worktree(
    repo, adapter, capsys
):
    """Adversarial: the agent did work but exited before flipping status.
    The FR must still be runnable and the *existing* worktree reused — not a
    fresh checkout that would hide the work."""
    wt = _worktree(repo, "dev")
    marker = _commit_file(wt, "src/partial.py", "x\n", "feat: partial")
    assert dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "dev") is None
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    assert [s[1] for s in adapter.spawns] == ["dev"]
    assert adapter.spawns[0][2] == wt
    assert _sha(repo, f"claude/dev-{_FR}") == marker  # nothing reset
    assert "SPAWNED" in capsys.readouterr().out


# covers hub-tooling FR-0006:AC-8
def test_staged_but_uncommitted_flip_does_not_count(repo, adapter):
    """The rule reads the status *as committed on the branch*: a flip that is
    only staged in the worktree (the pre-finalize state) is invisible to it."""
    wt = _worktree(repo, "dev")
    _flip_status(wt, _FR, "in-progress", commit=False)
    assert dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "dev") is None
    # rev role is untouched by the new rule: it already read the branch.
    assert dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "rev") is not None


# ---------------------------------------------------------------------------
# AC-9: unfiltered selection applies the same rule and says why
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-9
def test_unfiltered_tick_skips_handed_off_fr_with_reason_and_still_runs_the_rest(
    tmp_path, monkeypatch, adapter, capsys
):
    repo = _make_repo(tmp_path, {_FR: "ready", _FR2: "ready"})
    _point(monkeypatch, repo)
    _handed_off_dev(repo)
    frs = dispatch.load_frs()
    assert [fr["id"] for fr in dispatch.runnable_frs(frs)] == [_FR2]
    assert dispatch.cmd_tick(apply=False, adapter=adapter, role="dev") == 0
    out = capsys.readouterr().out
    skip = [ln for ln in out.splitlines() if "SKIP" in ln]
    assert (
        len(skip) == 1
        and _FR in skip[0]
        and f"claude/dev-{_FR}" in skip[0]
        and "already handed off" in skip[0]
    )
    assert f"{_FR2}  WOULD-SPAWN" in out and f"{_FR}  WOULD-SPAWN" not in out


# covers hub-tooling FR-0006:AC-9
def test_unfiltered_wave_skips_handed_off_fr_with_reason(
    tmp_path, monkeypatch, adapter, capsys
):
    repo = _make_repo(tmp_path, {_FR: "ready", _FR2: "ready"})
    _point(monkeypatch, repo)
    _handed_off_dev(repo)
    assert dispatch.cmd_wave(apply=False, adapter=adapter) == 0
    out = capsys.readouterr().out
    assert f"{_FR}  SKIP — status is 'in-progress' on claude/dev-{_FR}" in out
    assert f"Runnable FRs for Developer: ['{_FR2}']" in out


# covers hub-tooling FR-0006:AC-9
def test_frs_without_a_role_branch_are_selected_exactly_as_before(
    tmp_path, monkeypatch
):
    """Adversarial regression guard: with no `claude/dev-*` branch anywhere,
    `runnable_frs` must equal the plain ready-with-terminal-deps filter."""
    repo = _make_repo(
        tmp_path, {_FR: "ready", _FR2: "ready", "FR-0003": "merged", "FR-0004": "draft"}
    )
    _point(monkeypatch, repo)
    frs = dispatch.load_frs()
    expected = [fr for fr in frs if fr["status"] == "ready"]
    assert dispatch.runnable_frs(frs) == expected
    assert dispatch.handed_off_frs(frs, "dev") == []


# ---------------------------------------------------------------------------
# AC-10: a reused Reviewer worktree is fast-forwarded onto the dev tip
# ---------------------------------------------------------------------------


def _round1_then_rework(repo: Path) -> tuple[Path, Path]:
    """Round 1 (rev branched off dev, tests committed), the rework prep merge
    into the dev worktree, then a Developer rework commit: rev is now a strict
    ancestor of dev."""
    dev_wt = _worktree(repo, "dev")
    _commit_file(dev_wt, "src/thing.py", "round 1\n", "feat: round 1")
    _flip_status(dev_wt, _FR, "in-progress", commit=True)
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _commit_file(rev_wt, "tests/test_x.py", "# test\n", "test: AC coverage")
    _git(dev_wt, "merge", "-q", "--no-edit", f"claude/rev-{_FR}")
    _commit_file(dev_wt, "src/thing.py", "round 2\n", "fix: rework")
    assert (
        _git(
            repo,
            "merge-base",
            "--is-ancestor",
            f"claude/rev-{_FR}",
            f"claude/dev-{_FR}",
        )
        == ""
    )
    return dev_wt, rev_wt


# covers hub-tooling FR-0006:AC-10
def test_reused_rev_worktree_is_fast_forwarded_before_spawn(repo, adapter):
    _dev_wt, rev_wt = _round1_then_rework(repo)
    assert _sha(rev_wt, "HEAD") != _sha(repo, f"claude/dev-{_FR}")
    result, _pid, wt = dispatch.spawn_role(
        _FR, "rev", apply=True, adapter=adapter, round_num=2
    )
    assert result == "spawned" and wt == rev_wt
    assert _sha(rev_wt, "HEAD") == _sha(repo, f"claude/dev-{_FR}")
    assert _sha(repo, f"claude/rev-{_FR}") == _sha(repo, f"claude/dev-{_FR}")
    # The adapter was handed the synced worktree, and the lock records it.
    assert adapter.spawns[0][2] == rev_wt
    lock = json.loads(
        (repo / "_dispatch" / f"{_FR}.rev.lock").read_text(encoding="utf-8")
    )
    assert lock["worktree_status"].startswith("reused,fast-forwarded")


# covers hub-tooling FR-0006:AC-10
def test_fast_forward_is_a_true_fast_forward_not_a_merge_commit(repo, adapter):
    """Adversarial: after the sync the rev branch must point at the dev commit
    itself — a merge commit or a rebase would produce a new SHA."""
    _, rev_wt = _round1_then_rework(repo)
    dev_tip = _sha(repo, f"claude/dev-{_FR}")
    ok, note = dispatch._fast_forward_rev_worktree(_FR, rev_wt)
    assert ok, note
    assert _sha(rev_wt, "HEAD") == dev_tip
    assert (
        _git(rev_wt, "log", "-1", "--format=%P").count(" ") == 0
        or _git(rev_wt, "log", "-1", "--format=%s") == "fix: rework"
    )


# covers hub-tooling FR-0006:AC-10
@pytest.mark.parametrize("shape", ["equal", "dev-behind-rev"])
def test_nothing_runs_when_rev_already_contains_dev(repo, adapter, shape):
    dev_wt = _worktree(repo, "dev")
    _commit_file(dev_wt, "src/thing.py", "x\n", "feat: work")
    _flip_status(dev_wt, _FR, "in-progress", commit=True)
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    if shape == "dev-behind-rev":
        _commit_file(rev_wt, "tests/test_x.py", "# t\n", "test: coverage")
    before = _sha(rev_wt, "HEAD")
    plan, _ = dispatch._rev_sync_plan(_FR)
    assert plan == "noop"
    wt, status = dispatch.ensure_role_worktree(_FR, "rev", adapter)
    assert (
        wt == rev_wt and status.startswith("reused,") and "fast-forwarded" not in status
    )
    assert _sha(rev_wt, "HEAD") == before


# covers hub-tooling FR-0006:AC-10
def test_fresh_rev_worktree_is_created_off_dev_without_a_sync_step(repo, adapter):
    """The sync applies to the *reused* path only; creation is unchanged."""
    dev_wt = _worktree(repo, "dev")
    _commit_file(dev_wt, "src/thing.py", "x\n", "feat: work")
    wt, status = dispatch.ensure_role_worktree(_FR, "rev", adapter)
    assert wt is not None and status.startswith("created,")
    assert _sha(wt, "HEAD") == _sha(repo, f"claude/dev-{_FR}")


# ---------------------------------------------------------------------------
# AC-11: impossible fast-forward refuses; never force-syncs
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0006:AC-11
def test_diverged_branches_refuse_the_spawn_and_leave_both_branches_untouched(
    repo, adapter
):
    _, rev_wt = _round1_then_rework(repo)
    _commit_file(
        rev_wt, "tests/test_extra.py", "# extra\n", "test: rev-only"
    )  # now diverged
    rev_before, dev_before = (
        _sha(repo, f"claude/rev-{_FR}"),
        _sha(repo, f"claude/dev-{_FR}"),
    )
    result, pid, _wt = dispatch.spawn_role(
        _FR, "rev", apply=True, adapter=adapter, round_num=2
    )
    assert result.startswith("error:") and pid is None
    assert (
        f"claude/rev-{_FR}" in result
        and f"claude/dev-{_FR}" in result
        and "diverged" in result
    )
    assert adapter.spawns == []
    assert (_sha(repo, f"claude/rev-{_FR}"), _sha(repo, f"claude/dev-{_FR}")) == (
        rev_before,
        dev_before,
    )
    assert not (repo / "_dispatch" / f"{_FR}.rev.lock").exists()


# covers hub-tooling FR-0006:AC-11
def test_dirty_tracked_changes_refuse_but_untracked_scratch_does_not(repo, adapter):
    _, rev_wt = _round1_then_rework(repo)
    (rev_wt / "tests" / "test_x.py").write_text(
        "# edited, not committed\n", encoding="utf-8"
    )
    before = _sha(rev_wt, "HEAD")
    result, _pid, _wt = dispatch.spawn_role(
        _FR, "rev", apply=True, adapter=adapter, round_num=2
    )
    assert (
        result.startswith("error:")
        and "uncommitted tracked changes" in result
        and "tests/test_x.py" in result
    )
    assert adapter.spawns == [] and _sha(rev_wt, "HEAD") == before
    assert (rev_wt / "tests" / "test_x.py").read_text(
        encoding="utf-8"
    ) == "# edited, not committed\n"  # not clobbered
    # Restore the tracked file; leave an untracked scratch file: must NOT block.
    _git(rev_wt, "checkout", "--", "tests/test_x.py")
    (rev_wt / "notes.txt").write_text("reviewer scratch\n", encoding="utf-8")
    result, _pid, _wt = dispatch.spawn_role(
        _FR, "rev", apply=True, adapter=adapter, round_num=2
    )
    assert result == "spawned"
    assert _sha(rev_wt, "HEAD") == _sha(repo, f"claude/dev-{_FR}")
    assert (rev_wt / "notes.txt").exists()


# covers hub-tooling FR-0006:AC-11
def test_rework_round_stops_as_precondition_failure_without_spawning_the_reviewer(
    repo, adapter, monkeypatch
):
    """Drive `_run_one_rework_round` with the Developer leg stubbed to succeed
    and the real branch state diverged: the round returns `(None,
    "precondition: …")` — a mechanical stop, not a verdict — and the Reviewer
    is never spawned."""
    dev_wt, rev_wt = _round1_then_rework(repo)
    _commit_file(rev_wt, "tests/test_extra.py", "# extra\n", "test: rev-only")
    spawned: list[str] = []

    def fake_spawn_role(fr_id, role, apply, adapter, extra_prompt=None, round_num=1):
        spawned.append(role)
        return ("spawned", 1, dev_wt)

    monkeypatch.setattr(
        dispatch, "_prepare_dev_worktree_for_rework", lambda fr_id: (True, "synced")
    )
    monkeypatch.setattr(
        dispatch, "_collect_failing_tests", lambda wt, timeout_s=900: []
    )
    monkeypatch.setattr(
        dispatch, "_write_rework_brief", lambda wt, fr_id, n, text: "_dispatch/brief.md"
    )
    monkeypatch.setattr(dispatch, "spawn_role", fake_spawn_role)
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {_FR: "done"}
    )
    monkeypatch.setattr(
        dispatch,
        "_evaluate_agent_outcome",
        lambda fr_id, role, adapter: SimpleNamespace(
            status="success", summary="", verdict=None
        ),
    )
    monkeypatch.setattr(dispatch, "cmd_finalize", lambda *a, **k: 0)
    verdict, note = dispatch._run_one_rework_round(
        _FR,
        2,
        3,
        "## Request changes",
        True,
        adapter,
        phase_timeout=5,
        poll_interval=0.01,
    )
    assert verdict is None and note.startswith("precondition:") and "diverged" in note
    assert spawned == ["dev"]


# covers hub-tooling FR-0006:AC-11
def test_dispatcher_never_runs_a_non_ff_merge_rebase_or_reset_on_the_reviewer_worktree(
    repo, adapter, monkeypatch
):
    """Adversarial: record every git invocation during a diverged refusal and
    a successful fast-forward; only `merge --ff-only` may mutate."""
    _, rev_wt = _round1_then_rework(repo)
    real_run = subprocess.run
    seen: list[list[str]] = []

    def spy(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            seen.append([str(c) for c in cmd])
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", spy)
    assert dispatch._fast_forward_rev_worktree(_FR, rev_wt)[0]
    _commit_file(rev_wt, "tests/test_extra.py", "# extra\n", "test: rev-only")
    _commit_file(
        repo / ".claude" / "worktrees" / f"dev-{_FR}",
        "src/more.py",
        "y\n",
        "feat: more",
    )
    assert not dispatch._fast_forward_rev_worktree(_FR, rev_wt)[0]
    mutating = [c for c in seen if any(w in c for w in ("rebase", "reset", "checkout"))]
    assert mutating == []
    merges = [c for c in seen if "merge" in c and "merge-base" not in c]
    assert merges and all("--ff-only" in c for c in merges)


# ---------------------------------------------------------------------------
# AC-12 (dispatch half): dry-run previews the sync and mutates nothing
# ---------------------------------------------------------------------------


def _snapshot(repo: Path, wts: list[Path]) -> str:
    parts = [
        _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    ]
    for wt in wts:
        parts += [_git(wt, "rev-parse", "HEAD"), _git(wt, "status", "--porcelain")]
    parts.append(
        ",".join(
            sorted(
                p.name
                for p in (repo / "_dispatch").iterdir()
                if not p.name.startswith("wave-")
            )
        )
    )
    return "\n".join(parts)


# covers hub-tooling FR-0006:AC-12
def test_rev_tick_dry_run_previews_fast_forward_and_changes_nothing(
    repo, adapter, capsys
):
    dev_wt, rev_wt = _round1_then_rework(repo)
    before = _snapshot(repo, [dev_wt, rev_wt])
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="rev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    assert (
        f"{_FR}  WOULD-FAST-FORWARD  claude/rev-{_FR}" in out
        and f"-> claude/dev-{_FR}" in out
    )
    assert f"{_FR}  WOULD-SPAWN" in out
    assert adapter.spawns == [] and _snapshot(repo, [dev_wt, rev_wt]) == before


# covers hub-tooling FR-0006:AC-12
def test_diverged_dry_run_says_would_refuse_and_withholds_would_spawn(
    repo, adapter, capsys
):
    dev_wt, rev_wt = _round1_then_rework(repo)
    _commit_file(rev_wt, "tests/test_extra.py", "# extra\n", "test: rev-only")
    before = _snapshot(repo, [dev_wt, rev_wt])
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="rev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    assert f"{_FR}  WOULD-REFUSE" in out and "diverged" in out
    assert "WOULD-SPAWN" not in out
    assert _snapshot(repo, [dev_wt, rev_wt]) == before


# covers hub-tooling FR-0006:AC-12
def test_wave_dry_run_previews_the_rev_sync_in_its_summary(repo, adapter, capsys):
    """A fresh wave over an FR whose rev worktree is behind its dev branch
    (status not yet flipped on the branch, so the FR is still runnable)."""
    dev_wt = _worktree(repo, "dev")
    _commit_file(dev_wt, "src/thing.py", "r1\n", "feat: round 1")
    rev_wt = _worktree(repo, "rev", base=f"claude/dev-{_FR}")
    _commit_file(dev_wt, "src/thing.py", "r2\n", "feat: moved on")
    before = _snapshot(repo, [dev_wt, rev_wt])
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    out = capsys.readouterr().out
    assert "WOULD-RUN  Phase 4: Rev Tick" in out
    assert f"{_FR}  WOULD-FAST-FORWARD  claude/rev-{_FR}" in out
    assert adapter.spawns == [] and _snapshot(repo, [dev_wt, rev_wt]) == before
