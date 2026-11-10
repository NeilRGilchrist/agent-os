"""FR-0018 AC-3, automated: the metrics redirect never leaks into a test
suite or the real log.

AC-3 was first met by the Reviewer's real run (the whole suite from a linked
worktree of a bootstrapped project, FR-0018 r1). This file checks the same
promise mechanically, on a slice small enough to run every time:

1. A primary checkout is built from this project's own files (the scripts,
   the metrics-writing tests and what they read), with a tracked month file
   in `specs/_metrics/`, and given a linked role worktree (`git worktree
   add`), as `dispatch.py` does.
2. `DISPATCH_METRICS_DIR` and `DISPATCH_WORKTREE` are set the way
   `spawn_role` sets them: the primary's `specs/_metrics` and the worktree,
   both absolute. A probe first shows the redirect is live for the
   worktree's own `metrics_log`, so a leak would land in the primary log.
3. The metrics-writing tests (`test_metrics_log.py`, `test_dispatch_metrics.py`
   and three gate-emission tests from `test_deploy_gate_metrics.py`) run as a
   subprocess from inside the worktree.
4. The slice passes; every file under the primary's `specs/_metrics/` is
   byte-identical (sha256) before and after, with nothing added; and the
   worktree is clean.

The bite check plants a test that emits without isolating the log, runs it
the same way, and shows the harness catches it: the primary log changes.

Annotations are `# covers hub-tooling FR-0018:AC-N`, not the gate's form:
this file rides along into every bootstrapped project, where FR-0018 does
not exist. Every fixture here is synthetic.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from . import test_merge_friction as _mf

_TEMPLATE_DIR = _mf._TEMPLATE_DIR
_git = _mf._git
_write = _mf._write
_METRICS_DIR_ENV = _mf._METRICS_DIR_ENV
_WORKTREE_ENV = _mf._WORKTREE_ENV
_HERE = Path(__file__).resolve().parent

# The metrics-writing slice: every record kind the template emits in-process
# or from a script (gate, escalation, dispatch), run from the worktree.
_SLICE_FILES = ("test_metrics_log.py", "test_dispatch_metrics.py")
_GATE_TESTS = (
    "test_passing_run_emits_exactly_one_pass_record_with_counts",
    "test_invoked_by_run_id_and_record_id_come_from_the_dispatcher_environment",
    "test_status_only_emits_nothing_and_leaves_a_committed_tree_clean",
)
# What those tests read from the project, besides `scripts/` and themselves.
_PROJECT_FILES = (
    "pytest.ini",
    ".gitattributes",
    ".gitignore",
    "tests/__init__.py",
    "tests/unit/__init__.py",
    "tests/unit/scripts/__init__.py",
    "tests/fixtures/README.md",
    "tests/fixtures/metrics/2026-08.ndjson",
)
_PROJECT_DIRS = (".agent-team", "specs/_metrics", "scripts")
_PLANTED = """\
import metrics_log


def test_planted_leak():
    rec = metrics_log.emit(
        "gate.run",
        source="manual",
        stage="dev",
        outcome="pass",
        failure_classes=[],
        warning_classes=[],
        counts={},
        invoked_by="manual",
    )
    assert rec is not None
"""


@pytest.fixture(autouse=True)
def _no_inherited_redirect(monkeypatch):
    for key in (_METRICS_DIR_ENV, _WORKTREE_ENV):
        monkeypatch.delenv(key, raising=False)


def _copy_project(dest: Path) -> None:
    """The slice's project: this project's own files, byte for byte."""
    for rel in _PROJECT_DIRS:
        shutil.copytree(
            _TEMPLATE_DIR / rel,
            dest / rel,
            ignore=shutil.ignore_patterns("__pycache__", "*.ndjson"),
            dirs_exist_ok=True,
        )
    for rel in _PROJECT_FILES:
        _write(dest / rel, (_TEMPLATE_DIR / rel).read_bytes())
    for name in (*_SLICE_FILES, "test_deploy_gate_metrics.py"):
        _write(dest / "tests" / "unit" / "scripts" / name, (_HERE / name).read_bytes())
    # A tracked month file, so "byte-identical" has bytes to compare.
    _write(
        dest / "specs" / "_metrics" / "2026-08.ndjson",
        (
            _TEMPLATE_DIR / "tests" / "fixtures" / "metrics" / "2026-08.ndjson"
        ).read_bytes(),
    )


@pytest.fixture
def armed(tmp_path):
    """A primary checkout with a linked role worktree, and the environment
    `spawn_role` would give an agent in it."""
    primary = tmp_path / "primary"
    _mf._init_repo(primary)
    _copy_project(primary)
    _git(primary, "add", "-A")
    _git(primary, "commit", "-q", "-m", "synthetic project")
    wt = primary / ".claude" / "worktrees" / "dev-FR-0001"
    _git(primary, "worktree", "add", "-q", "-b", "claude/dev-FR-0001", str(wt), "main")
    env = _mf._clean_env(
        PYTHONDONTWRITEBYTECODE="1",
        **{
            _METRICS_DIR_ENV: os.path.abspath(primary / "specs" / "_metrics"),
            _WORKTREE_ENV: os.path.abspath(wt),
        },
    )
    env.pop("PYTEST_ADDOPTS", None)
    # The redirect is live for the worktree's own metrics_log: a leak from
    # the slice would land in the primary's log, which is what is watched.
    probe = subprocess.run(
        [sys.executable, "-c", "import metrics_log; print(metrics_log.METRICS_DIR)"],
        cwd=str(wt / "scripts"),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert os.path.samefile(probe.stdout.strip(), primary / "specs" / "_metrics")
    return primary, wt, env


def _log_state(primary: Path) -> tuple[dict[str, str], str]:
    d = primary / "specs" / "_metrics"
    hashes = {
        p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob("*"))
        if p.is_file()
    }
    status = _git(
        primary,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "specs/_metrics",
    )
    return hashes, status


def _pytest(
    wt: Path, env: dict[str, str], *targets: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
        cwd=str(wt),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# covers hub-tooling FR-0018:AC-3
def test_metrics_slice_from_a_linked_worktree_leaves_the_primary_log_byte_identical(
    armed,
):
    primary, wt, env = armed
    before = _log_state(primary)
    assert before[0], "the primary log has a tracked month file to compare"
    targets = [f"tests/unit/scripts/{name}" for name in _SLICE_FILES]
    targets += [
        f"tests/unit/scripts/test_deploy_gate_metrics.py::{name}"
        for name in _GATE_TESTS
    ]
    proc = _pytest(wt, env, *targets)
    tail = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-2000:]
    assert proc.returncode == 0, tail
    passed = re.search(r"(\d+) passed", proc.stdout)
    # The whole slice ran: 106 + 25 + 3 tests, less the history-guard skips.
    assert passed and int(passed.group(1)) >= 120, tail
    assert " failed" not in proc.stdout and " error" not in proc.stdout, tail
    assert _log_state(primary) == before, tail
    assert _git(wt, "status", "--porcelain", "--untracked-files=all") == ""


# covers hub-tooling FR-0018:AC-3
def test_the_harness_catches_a_planted_leak(armed):
    """Bite check for the test above: a test that emits without isolating
    the log, run the same way, changes the primary log."""
    primary, wt, env = armed
    before = _log_state(primary)
    planted = wt / "tests" / "unit" / "scripts" / "test_zz_planted_leak.py"
    _write(planted, _PLANTED)
    proc = _pytest(wt, env, "tests/unit/scripts/test_zz_planted_leak.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = _log_state(primary)
    changed = sorted(name for name in after[0] if after[0][name] != before[0].get(name))
    assert len(changed) == 1 and changed[0].endswith(".ndjson"), after
    assert after[1] != before[1]  # git sees the primary log change
    # ... and the worktree carries no metrics row: the redirect took it.
    assert _git(wt, "status", "--porcelain", "--", "specs/_metrics") == ""
