"""Reviewer tests for FR-0014 — both rev-leg `cmd_finalize` call sites forward
the wave's `draft` (AC-1 Phase 6, AC-2 the rework rev leg) under a
signature-faithful double; an uncaught exception in Phases 1-6, a rework
round or synthesis prints `CRASHED — <phase>: <Type>: <msg>` plus the
traceback to stdout (flushed) and stderr and exits `3`, propagated by
`main()` (AC-3); in apply mode the synthesis file and the single
`dispatch.wave` record are still written with the in-flight FRs marked
`<phase>-crash` while dry-run writes neither (AC-4); and `wave` flushes
stdout at every phase boundary, per-FR outcome line, rework banner and the
`CRASHED` line, even when stdout is block-buffered (AC-5).

Harness: `dispatch.py` loaded by path with its path globals pointed at a real
temporary git repository, a fake harness adapter, `spawn_role` /
`_wait_for_phase` / `_evaluate_agent_outcome` monkeypatched as the existing
wave tests do, and `cmd_finalize` replaced by a double that binds the real
function's signature (`inspect.signature(...).bind`) before returning — the
FR's fixed rule; a `lambda *a, **k: 0` double is what let the regression ship.
No network, no `claude` binary; every wave drive is in-process.

The "pre-FR dispatcher" the bite checks run against is loaded from
`git show <pre-FR ref>:template/scripts/dispatch.py` (the hub commit FR-0014
branched from); inside a bootstrapped project that object does not exist and
those checks skip.

Coverage annotations are written `# covers hub-tooling FR-0014:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_permissions.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import contextlib
import functools
import importlib.util
import inspect
import io
import itertools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
# The hub commit FR-0014 branched from (`main` after FR-0011 merged).
_PRE_FR_REF = "aa6f5ee"
_FR = "FR-0001"
_FR2 = "FR-0002"
_FR3 = "FR-0003"
_CRASH_RC = 3
# `inspect.Signature.bind` words the miss "missing a required argument"; the
# runtime call the FR quotes words it "missing 1 required positional argument".
# Both name `'draft'`; the double surfaces the former by construction.
_MISSING_DRAFT = r"missing (1|a) required (positional )?argument: 'draft'"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_REAL_SUBPROCESS_RUN = subprocess.run


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0014")
assert dispatch._metrics is metrics_log


@functools.lru_cache(maxsize=1)
def _pre_fr_source() -> bytes | None:
    hub_root = _TEMPLATE_DIR.parent
    proc = _REAL_SUBPROCESS_RUN(
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
    d = tmp_path_factory.mktemp("pre_fr0014_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0014")


# ---------------------------------------------------------------------------
# Synthetic FR + real-git repo fixture (FR-0006 harness shape)
# ---------------------------------------------------------------------------


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


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = _REAL_SUBPROCESS_RUN(
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


def _make_repo(tmp_path: Path, fr_ids: tuple[str, ...] = (_FR,)) -> Path:
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
    (repo / "specs").mkdir()
    for fr_id in fr_ids:
        (repo / "specs" / f"{fr_id}-synthetic.md").write_text(
            _fr_md(fr_id), encoding="utf-8", newline="\n"
        )
    (repo / ".gitignore").write_text(
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _point(monkeypatch, mod, r: Path) -> None:
    monkeypatch.setattr(mod, "REPO_ROOT", r)
    monkeypatch.setattr(mod, "SPECS_DIR", r / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", r / "_dispatch")
    monkeypatch.setattr(mod, "LAST_TICK_FILE", r / "_dispatch" / ".last-tick")
    monkeypatch.setattr(mod, "ESCALATIONS_DIR", r / "specs" / "_escalations")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "ensure_dev_venv", lambda wt: (True, "venv:stub"))
    monkeypatch.setattr(mod, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(
        mod,
        "reconcile_merged_prs",
        lambda apply=False, verbose=False: mod.ReconcileSummary(
            flipped=[], cleaned=[], skipped=[]
        ),
    )
    monkeypatch.setattr(mod, "prune_dead_locks", lambda verbose=True: 0)
    monkeypatch.setattr(metrics_log, "METRICS_DIR", r / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (r / "_dispatch").mkdir(exist_ok=True)


class _FakeAdapter:
    name = "fake"
    binary_name = "fake"

    def __init__(self) -> None:
        self.spawns: list[tuple[str, str, Path, str | None]] = []

    def write_worktree_settings(self, wt_path: Path, role: str, fr_id: str) -> None:
        pass

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.spawns.append((fr_id, role, wt_path, extra_prompt))
        return ("spawned", 999_999)

    def parse_log(self, log_path: Path):
        return SimpleNamespace(last_text="", result_subtype="success", tool_calls=0)

    def dry_run_preview(self, fr_id: str, role: str, wt_preview: Path) -> str:
        return f"fake-preview {role} {fr_id}"


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    r = _make_repo(tmp_path)
    _point(monkeypatch, dispatch, r)
    return r


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter()


# ---------------------------------------------------------------------------
# Wave doubles: signature-faithful `cmd_finalize`, worktree-creating
# `spawn_role`, instant `_wait_for_phase`, scripted `_evaluate_agent_outcome`
# ---------------------------------------------------------------------------


class _Drive:
    """Everything a driven wave records, plus the knobs that make it raise."""

    def __init__(self, mod, repo: Path) -> None:
        self.mod = mod
        self.repo = repo
        self.finalize_calls: list[tuple[str, str, dict]] = []
        self.spawned: list[tuple[str, str, int]] = []
        self.wait_calls = 0
        self.rev_verdicts: dict[str, list[str]] = {}
        self.dev_status: dict[str, str] = {}
        self.rev_status: dict[str, str] = {}
        # raise_at: one of the `current_phase` slugs, or "rework"/"synthesis".
        self.raise_at: str | None = None
        self.raise_exc: BaseException = RuntimeError("boom")
        self.raise_for_fr: str | None = None
        self.synthesis_calls = 0

    def _maybe_raise(self, site: str, fr_id: str | None = None) -> None:
        if self.raise_at != site:
            return
        if self.raise_for_fr is not None and fr_id != self.raise_for_fr:
            return
        raise self.raise_exc

    # -- cmd_finalize: binds the REAL signature, records, returns 0 --------
    def finalize_double(self, real):
        sig = inspect.signature(real)

        def double(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)  # TypeError propagates by design
            args_d = dict(bound.arguments)
            fr_id, role = args_d["fr_id"], args_d["role"]
            self.finalize_calls.append((fr_id, role, args_d))
            self._maybe_raise(f"{role}-finalize", fr_id)
            return 0

        return double

    # -- spawn_role: creates a real dev worktree/branch with PR_BODY.md -----
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
        self._maybe_raise(f"{role}-tick", fr_id)
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
            (wt / "PR_BODY.md").write_text(
                f"# {fr_id}\n", encoding="utf-8", newline="\n"
            )
            (wt / "specs" / f"{fr_id}-synthetic.md").write_text(
                _fr_md(fr_id, "in-progress"), encoding="utf-8", newline="\n"
            )
            _git(wt, "add", "-A")
            _git(wt, "commit", "-q", "-m", "dev: hand-off")
        self.spawned.append((fr_id, role, round_num))
        return ("spawned", 4242, wt)

    def wait_for_phase(self, targets, poll_interval, phase_timeout):
        self.wait_calls += 1
        for fr_id, role in targets:
            self._maybe_raise(f"{role}-monitor", fr_id)
        return {fr_id: "completed" for fr_id, _role in targets}

    def evaluate(self, fr_id, role, adapter):
        self._maybe_raise(f"{role}-evaluate", fr_id)
        if role == "dev":
            status = self.dev_status.get(fr_id, "success")
            return self.mod.AgentOutcome(status=status, summary=f"dev {status}")
        status = self.rev_status.get(fr_id, "success")
        queue = self.rev_verdicts.setdefault(fr_id, ["approve"])
        verdict = queue.pop(0) if len(queue) > 1 else queue[0]
        return self.mod.AgentOutcome(
            status=status, summary=f"rev {status}", verdict=verdict
        )

    def prepare_rework(self, fr_id):
        self._maybe_raise("rework", fr_id)
        return (True, "synced (stub)")

    def rev_calls(self) -> list[dict]:
        return [a for _f, role, a in self.finalize_calls if role == "rev"]

    def dev_calls(self) -> list[dict]:
        return [a for _f, role, a in self.finalize_calls if role == "dev"]


def _install(monkeypatch, mod, repo: Path) -> _Drive:
    d = _Drive(mod, repo)
    real_finalize = mod.cmd_finalize
    monkeypatch.setattr(mod, "cmd_finalize", d.finalize_double(real_finalize))
    monkeypatch.setattr(mod, "spawn_role", d.spawn_role)
    monkeypatch.setattr(mod, "_wait_for_phase", d.wait_for_phase)
    monkeypatch.setattr(mod, "_evaluate_agent_outcome", d.evaluate)
    monkeypatch.setattr(mod, "_prepare_dev_worktree_for_rework", d.prepare_rework)
    monkeypatch.setattr(mod, "_collect_failing_tests", lambda wt, timeout_s=900: [])
    real_synth = mod._write_wave_synthesis

    def synth(*a, **k):
        d.synthesis_calls += 1
        if d.raise_at == "synthesis" and d.synthesis_calls == 1:
            raise d.raise_exc
        return real_synth(*a, **k)

    monkeypatch.setattr(mod, "_write_wave_synthesis", synth)
    return d


@pytest.fixture
def drive(repo, monkeypatch) -> _Drive:
    return _install(monkeypatch, dispatch, repo)


def _wave(mod, adapter, **kw) -> int:
    kw.setdefault("apply", True)
    kw.setdefault("fr_filter", [_FR])
    kw.setdefault("timeout", 600)
    kw.setdefault("phase_timeout", 600)
    kw.setdefault("poll_interval", 0.01)
    return mod.cmd_wave(adapter=adapter, **kw)


def _records() -> list[dict]:
    d = metrics_log.METRICS_DIR
    if not d.exists():
        return []
    recs = [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    for r in recs:
        assert metrics_log.validation_errors(r) == [], r
    return recs


def _wave_records() -> list[dict]:
    return [r for r in _records() if r["kind"] == "dispatch.wave"]


def _synthesis_files(repo: Path) -> list[Path]:
    return sorted((repo / "_dispatch").glob("wave-*.md"))


def _crashed_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("CRASHED — ")]


_TRACEBACK_HEADER = "Traceback (most recent call last):"


# ---------------------------------------------------------------------------
# AC-1: Phase 6 rev finalize passes `draft`, under a signature-faithful double
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0014:AC-1
@pytest.mark.parametrize("draft", [True, False])
def test_phase6_rev_finalize_forwards_the_waves_draft_under_the_real_signature(
    repo, adapter, drive, draft
):
    rc = _wave(dispatch, adapter, draft=draft)
    assert rc == 0
    rev = drive.rev_calls()
    assert len(rev) == 1
    assert rev[0]["fr_id"] == _FR and rev[0]["apply"] is True
    assert rev[0]["draft"] is draft and rev[0]["adapter"] is adapter
    # The dev leg (already correct pre-FR) carries the same value.
    assert [c["draft"] for c in drive.dev_calls()] == [draft]
    [rec] = _wave_records()
    assert rec["completed"] == 1 and rec["dropped"] == 0 and rec["drop_reasons"] == []
    assert rec["rounds_ran"] == {_FR: 1}


# covers hub-tooling FR-0014:AC-1
def test_the_double_itself_rejects_a_call_without_draft(repo):
    """The fixed rule: a double that accepts any call shape is not this test's
    double. Prove the one used here raises exactly the pre-FR TypeError."""
    d = _Drive(dispatch, repo)
    double = d.finalize_double(dispatch.cmd_finalize)
    with pytest.raises(TypeError, match=_MISSING_DRAFT):
        double(_FR, "rev", apply=True, adapter=None)
    assert d.finalize_calls == []
    assert double(_FR, "rev", apply=True, draft=True, adapter=None) == 0
    assert d.finalize_calls[0][2]["draft"] is True


# covers hub-tooling FR-0014:AC-1
@pytest.mark.parametrize("draft", [True, False])
def test_bite_pre_fr_phase6_raises_missing_draft_under_the_same_drive(
    tmp_path, monkeypatch, pre_fr_dispatch, draft
):
    """Same fixtures, same doubles, the dispatcher at the pre-FR ref: the wave
    reaches Phase 6 and dies with the TypeError Project A L57 reported."""
    r = _make_repo(tmp_path)
    _point(monkeypatch, pre_fr_dispatch, r)
    d = _install(monkeypatch, pre_fr_dispatch, r)
    with pytest.raises(TypeError, match=_MISSING_DRAFT):
        _wave(pre_fr_dispatch, _FakeAdapter(), draft=draft)
    # It got exactly as far as the dev leg — the rev finalize never bound.
    assert [role for _f, role, _a in d.finalize_calls] == ["dev"]
    assert _wave_records() == []


# ---------------------------------------------------------------------------
# AC-2: rework rev leg passes `draft`
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0014:AC-2
@pytest.mark.parametrize("draft", [True, False])
def test_rework_rev_leg_forwards_draft_in_round_two(repo, adapter, drive, draft):
    drive.rev_verdicts[_FR] = ["request-changes", "approve"]
    rc = _wave(dispatch, adapter, draft=draft, rounds=2)
    assert rc == 0
    rev, dev = drive.rev_calls(), drive.dev_calls()
    assert len(rev) == 2 and len(dev) == 2
    assert all(c["draft"] is draft and c["apply"] is True for c in rev + dev)
    assert all(c["adapter"] is adapter for c in rev + dev)
    # Round order: dev1, rev1, dev2, rev2.
    assert [role for _f, role, _a in drive.finalize_calls] == [
        "dev",
        "rev",
        "dev",
        "rev",
    ]
    assert [rn for _f, role, rn in drive.spawned] == [1, 1, 2, 2]
    [rec] = _wave_records()
    assert rec["rounds_ran"] == {_FR: 2} and rec["completed"] == 1
    assert rec["force_escalated"] == [] and rec["dropped"] == 0


# covers hub-tooling FR-0014:AC-2
@pytest.mark.parametrize("draft", [True, False])
def test_every_rev_leg_over_a_full_budget_carries_draft_including_force_escalation(
    repo, adapter, drive, draft
):
    """Adversarial: three rounds, never approved. Each rework rev call still
    binds `draft`; the budget exhausts into a force-escalation, not a crash."""
    drive.rev_verdicts[_FR] = ["request-changes", "request-changes", "request-changes"]
    rc = _wave(dispatch, adapter, draft=draft, rounds=3)
    assert rc == 0
    rev = drive.rev_calls()
    assert len(rev) == 3 and all(c["draft"] is draft for c in rev)
    assert len(drive.dev_calls()) == 3
    [rec] = _wave_records()
    assert rec["rounds_ran"] == {_FR: 3} and rec["force_escalated"] == [_FR]


# covers hub-tooling FR-0014:AC-2
def test_bite_pre_fr_rework_rev_leg_raises_missing_draft(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    """Drive `_run_one_rework_round` directly at the pre-FR ref (Phase 6 would
    already have died there) so the rework call site is proven on its own."""
    r = _make_repo(tmp_path)
    _point(monkeypatch, pre_fr_dispatch, r)
    d = _install(monkeypatch, pre_fr_dispatch, r)
    d.spawn_role(_FR, "dev", True, None)  # dev worktree exists for the brief
    with pytest.raises(TypeError, match=_MISSING_DRAFT):
        pre_fr_dispatch._run_one_rework_round(
            _FR,
            2,
            3,
            "## Request changes",
            True,
            _FakeAdapter(),
            phase_timeout=5,
            poll_interval=0.01,
        )
    assert [role for _f, role, _a in d.finalize_calls] == ["dev"]


# covers hub-tooling FR-0014:AC-2
def test_post_fr_rework_round_direct_drive_binds_draft_on_both_legs(
    repo, adapter, drive
):
    drive.rev_verdicts[_FR] = ["approve"]
    drive.spawn_role(_FR, "dev", True, adapter)
    verdict, note = dispatch._run_one_rework_round(
        _FR,
        2,
        3,
        "## Request changes",
        False,
        adapter,
        phase_timeout=5,
        poll_interval=0.01,
    )
    assert (verdict, note) == ("approve", "round completed")
    assert [(role, a["draft"]) for _f, role, a in drive.finalize_calls] == [
        ("dev", False),
        ("rev", False),
    ]


# ---------------------------------------------------------------------------
# AC-3: a crash is visible — CRASHED line + traceback on stdout and stderr,
# exit code 3, propagated by main()
# ---------------------------------------------------------------------------

_RAISE_SITES: list[tuple[str, str, dict]] = [
    # (raise_at, expected phase name in the CRASHED line, extra wave kwargs)
    ("dev-tick", "Phase 1: Dev Tick", {}),
    ("dev-monitor", "Phase 2: Dev Monitor", {}),
    ("dev-evaluate", "Phase 3: Dev Evaluate + Finalize", {}),
    ("dev-finalize", "Phase 3: Dev Evaluate + Finalize", {}),
    ("rev-tick", "Phase 4: Rev Tick", {}),
    ("rev-monitor", "Phase 5: Rev Monitor", {}),
    ("rev-evaluate", "Phase 6: Rev Evaluate + Finalize", {}),
    ("rev-finalize", "Phase 6: Rev Evaluate + Finalize", {}),
    ("rework", "rework", {"rounds": 2}),
    ("synthesis", "Synthesis", {}),
]


# covers hub-tooling FR-0014:AC-3
@pytest.mark.parametrize(
    "site,phase_name,extra", _RAISE_SITES, ids=[s[0] for s in _RAISE_SITES]
)
def test_a_raise_in_any_phase_prints_crashed_with_traceback_and_returns_3(
    repo, adapter, drive, capsys, site, phase_name, extra
):
    drive.raise_at = site
    if site == "rework":
        drive.rev_verdicts[_FR] = ["request-changes", "approve"]
    rc = _wave(dispatch, adapter, **extra)
    out, err = capsys.readouterr()
    assert rc == _CRASH_RC
    assert _crashed_lines(out) == [f"CRASHED — {phase_name}: RuntimeError: boom"]
    assert _TRACEBACK_HEADER in out and "RuntimeError: boom" in out
    assert _TRACEBACK_HEADER in err and "RuntimeError: boom" in err
    # The traceback on stdout comes right after the CRASHED line, before any
    # synthesis output.
    tb_idx = out.index(_TRACEBACK_HEADER, out.index("CRASHED — "))
    if "Synthesis written" in out:
        assert out.index("Synthesis written") > tb_idx


# covers hub-tooling FR-0014:AC-3
def test_phase6_rev_evaluate_crash_names_phase_6_and_phase3_names_phase_3(
    repo, adapter, drive, capsys
):
    """The FR's two worked parametrisations, asserted with the exact strings."""
    drive.raise_at = "rev-evaluate"
    assert _wave(dispatch, adapter) == _CRASH_RC
    out = capsys.readouterr().out
    assert "CRASHED — Phase 6: Rev Evaluate + Finalize: RuntimeError: boom" in out
    # Fresh repo state for the second site (the dev worktree already exists).
    drive.raise_at = "dev-evaluate"
    _git(
        repo,
        "worktree",
        "remove",
        "--force",
        str(repo / ".claude" / "worktrees" / f"dev-{_FR}"),
    )
    _git(repo, "branch", "-D", f"claude/dev-{_FR}")
    assert _wave(dispatch, adapter) == _CRASH_RC
    out = capsys.readouterr().out
    assert "CRASHED — Phase 3: Dev Evaluate + Finalize: RuntimeError: boom" in out


# covers hub-tooling FR-0014:AC-3
def test_exception_type_and_message_are_reported_verbatim(repo, adapter, drive, capsys):
    drive.raise_at = "rev-evaluate"
    drive.raise_exc = KeyError("no such key")
    assert _wave(dispatch, adapter) == _CRASH_RC
    out = capsys.readouterr().out
    assert _crashed_lines(out) == [
        "CRASHED — Phase 6: Rev Evaluate + Finalize: KeyError: 'no such key'"
    ]


# covers hub-tooling FR-0014:AC-3
def test_main_propagates_the_crash_code_unchanged(
    repo, adapter, drive, monkeypatch, capsys
):
    drive.raise_at = "rev-evaluate"
    monkeypatch.setattr(dispatch, "get_adapter", lambda name: adapter)
    monkeypatch.setattr(
        sys,
        "argv",
        ["dispatch.py", "wave", "--apply", "--fr", _FR, "--poll-interval", "0.01"],
    )
    assert dispatch.main() == _CRASH_RC
    out = capsys.readouterr().out
    assert "CRASHED — Phase 6: Rev Evaluate + Finalize: RuntimeError: boom" in out
    # `--ready` flips draft=False all the way to the rev leg through main().
    drive.raise_at = None
    _git(
        repo,
        "worktree",
        "remove",
        "--force",
        str(repo / ".claude" / "worktrees" / f"dev-{_FR}"),
    )
    _git(repo, "branch", "-D", f"claude/dev-{_FR}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "wave",
            "--apply",
            "--ready",
            "--fr",
            _FR,
            "--poll-interval",
            "0.01",
        ],
    )
    assert dispatch.main() == 0
    assert [c["draft"] for c in drive.rev_calls()] == [False]


# covers hub-tooling FR-0014:AC-3
def test_phase0_raises_are_not_caught_and_leave_no_crashed_line(
    repo, adapter, drive, monkeypatch, capsys
):
    """Adversarial: pre-flight (Phase 0) keeps today's behaviour — an exception
    in `_gh_preflight` or `_run_env_preflight` propagates untouched."""

    def boom(*a, **k):
        raise RuntimeError("preflight boom")

    monkeypatch.setattr(dispatch, "_gh_preflight", boom)
    with pytest.raises(RuntimeError, match="preflight boom"):
        _wave(dispatch, adapter)
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(dispatch, "_run_env_preflight", boom)
    with pytest.raises(RuntimeError, match="preflight boom"):
        _wave(dispatch, adapter)
    out = capsys.readouterr().out
    assert _crashed_lines(out) == []
    assert _wave_records() == [] and _synthesis_files(repo) == []


# covers hub-tooling FR-0014:AC-3
def test_keyboard_interrupt_is_not_swallowed(repo, adapter, drive, capsys):
    drive.raise_at = "rev-evaluate"
    drive.raise_exc = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _wave(dispatch, adapter)
    out = capsys.readouterr().out
    assert _crashed_lines(out) == []
    assert _wave_records() == [] and _synthesis_files(repo) == []


# covers hub-tooling FR-0014:AC-3
def test_exit_codes_1_and_2_are_unchanged_for_their_cases(repo, adapter, drive, capsys):
    # 2: --rounds out of range, before any phase.
    assert _wave(dispatch, adapter, rounds=0) == 2
    assert _wave(dispatch, adapter, rounds=dispatch.REVIEW_CYCLE_BUDGET + 1) == 2
    # 1: something dropped (rev leg errored), nothing completed — no crash.
    drive.rev_status[_FR] = "error"
    assert _wave(dispatch, adapter) == 1
    out = capsys.readouterr().out
    assert _crashed_lines(out) == [] and f"{_FR}  DROPPED — rev error" in out
    [rec] = _wave_records()
    assert rec["drop_reasons"] == [{"fr_id": _FR, "phase": "rev-evaluate"}]


# covers hub-tooling FR-0014:AC-3
def test_unknown_phase_slug_falls_back_to_the_raw_slug():
    """`_WAVE_PHASE_NAMES` is a lookup with a fallback, never a KeyError."""
    assert dispatch._WAVE_PHASE_NAMES.get("rework", "rework") == "rework"
    assert dispatch._WAVE_PHASE_NAMES.get("not-a-phase", "not-a-phase") == "not-a-phase"
    for slug in (
        "dev-tick",
        "dev-monitor",
        "dev-evaluate",
        "dev-finalize",
        "rev-tick",
        "rev-monitor",
        "rev-evaluate",
        "rev-finalize",
        "synthesis",
    ):
        assert slug in dispatch._WAVE_PHASE_NAMES


# ---------------------------------------------------------------------------
# AC-4: synthesis + dispatch.wave record still written on crash
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0014:AC-4
def test_phase6_crash_writes_synthesis_and_one_record_marked_rev_evaluate_crash(
    repo, adapter, drive, capsys
):
    drive.raise_at = "rev-evaluate"
    assert _wave(dispatch, adapter) == _CRASH_RC
    [synth] = _synthesis_files(repo)
    text = synth.read_text(encoding="utf-8")
    assert _FR in text and "rev-evaluate-crash" in text
    assert f"- {_FR}: DROPPED at rev-evaluate-crash (RuntimeError: boom)" in text
    [rec] = _wave_records()
    assert rec["dropped"] == 1 and rec["completed"] == 0
    assert rec["drop_reasons"] == [{"fr_id": _FR, "phase": "rev-evaluate-crash"}]
    assert rec["object_ids"] == [_FR] and rec["fr_count"] == 1
    assert "boom" not in json.dumps(rec)  # no prose in the record


# covers hub-tooling FR-0014:AC-4
@pytest.mark.parametrize(
    "site,_name,extra", _RAISE_SITES[:-2], ids=[s[0] for s in _RAISE_SITES[:-2]]
)
def test_every_phase_crash_marks_the_in_flight_fr_with_that_phases_slug(
    repo, adapter, drive, site, _name, extra
):
    drive.raise_at = site
    assert _wave(dispatch, adapter, **extra) == _CRASH_RC
    [rec] = _wave_records()
    assert rec["drop_reasons"] == [{"fr_id": _FR, "phase": f"{site}-crash"}]
    [synth] = _synthesis_files(repo)
    assert f"{site}-crash" in synth.read_text(encoding="utf-8")


# covers hub-tooling FR-0014:AC-4
def test_terminal_frs_keep_their_state_while_only_the_in_flight_one_is_crash_marked(
    tmp_path, monkeypatch, capsys
):
    """Adversarial, three FRs: one dropped at dev-evaluate before the crash,
    one completed end-to-end in Phase 6 before the crash, one crashing in
    Phase 6. Only the third gets `rev-evaluate-crash`."""
    r = _make_repo(tmp_path, (_FR, _FR2, _FR3))
    _point(monkeypatch, dispatch, r)
    d = _install(monkeypatch, dispatch, r)
    adapter = _FakeAdapter()
    d.dev_status[_FR] = "error"
    d.raise_at, d.raise_for_fr = "rev-evaluate", _FR3
    assert _wave(dispatch, adapter, fr_filter=[_FR, _FR2, _FR3]) == _CRASH_RC
    out = capsys.readouterr().out
    assert _crashed_lines(out) == [
        "CRASHED — Phase 6: Rev Evaluate + Finalize: RuntimeError: boom"
    ]
    assert f"{_FR2}  REVIEW-POSTED  verdict=approve" in out
    [rec] = _wave_records()
    assert rec["fr_count"] == 3 and rec["completed"] == 1 and rec["dropped"] == 2
    assert rec["drop_reasons"] == [
        {"fr_id": _FR, "phase": "dev-evaluate"},
        {"fr_id": _FR3, "phase": "rev-evaluate-crash"},
    ]
    text = _synthesis_files(r)[0].read_text(encoding="utf-8")
    assert f"- {_FR}: DROPPED at dev-evaluate (dev error)" in text
    assert f"- {_FR2}: PR opened (draft), reviewer: approve" in text
    assert f"- {_FR3}: DROPPED at rev-evaluate-crash (RuntimeError: boom)" in text
    # The rev finalize double bound `draft` for the FR that got that far.
    assert [c["fr_id"] for c in d.rev_calls()] == [_FR2]


# covers hub-tooling FR-0014:AC-4
def test_crash_drop_reasons_compose_with_fr0011_preflight_skip_note(
    repo, adapter, drive
):
    drive.raise_at = "rev-evaluate"
    assert _wave(dispatch, adapter, skip_env_preflight=True) == _CRASH_RC
    [rec] = _wave_records()
    assert rec["drop_reasons"] == [
        {"fr_id": _FR, "phase": "rev-evaluate-crash"},
        {"fr_id": None, "phase": "preflight-env", "class": "skipped"},
    ]


# covers hub-tooling FR-0014:AC-4
@pytest.mark.parametrize("site", ["dev-tick", "synthesis"])
def test_dry_run_crash_prints_traceback_returns_3_and_writes_nothing(
    repo, adapter, drive, capsys, site
):
    if site == "dev-tick":
        # Dry-run never calls spawn_role; the preview is Phase 1's raise site.
        def preview(fr_id, role, wt_preview):
            raise RuntimeError("boom")

        adapter.dry_run_preview = preview
    else:
        drive.raise_at = "synthesis"
    rc = _wave(dispatch, adapter, apply=False)
    out, err = capsys.readouterr()
    assert rc == _CRASH_RC
    assert len(_crashed_lines(out)) == 1 and "RuntimeError: boom" in out
    assert _TRACEBACK_HEADER in out and _TRACEBACK_HEADER in err
    assert _synthesis_files(repo) == []
    assert _records() == [] and not metrics_log.METRICS_DIR.exists()
    # Dry-run still spawned nothing and created no worktree.
    assert drive.spawned == [] and not (repo / ".claude" / "worktrees").exists()


# covers hub-tooling FR-0014:AC-4
def test_wave_record_key_set_is_unchanged_from_the_pre_fr_dispatcher(
    tmp_path, monkeypatch, pre_fr_dispatch
):
    """A crashed wave's record has exactly the keys a pre-FR wave record had —
    `drop_reasons` carries the new phase value, nothing else changes shape."""
    r_new = _make_repo(tmp_path / "new")
    _point(monkeypatch, dispatch, r_new)
    d = _install(monkeypatch, dispatch, r_new)
    d.raise_at = "rev-evaluate"
    assert _wave(dispatch, _FakeAdapter()) == _CRASH_RC
    [rec_new] = _wave_records()
    r_old = _make_repo(tmp_path / "old")
    _point(monkeypatch, pre_fr_dispatch, r_old)
    d_old = _install(monkeypatch, pre_fr_dispatch, r_old)
    d_old.rev_status[_FR] = "error"  # pre-FR cannot pass Phase 6; drop at rev-evaluate
    assert _wave(pre_fr_dispatch, _FakeAdapter()) == 1
    [rec_old] = _wave_records()
    assert set(rec_new) == set(rec_old)
    assert (
        set(rec_new["drop_reasons"][0])
        == set(rec_old["drop_reasons"][0])
        == {"fr_id", "phase"}
    )


# covers hub-tooling FR-0014:AC-4
def test_a_deterministic_synthesis_failure_still_prints_crashed_but_reraises(
    repo, adapter, drive, capsys, monkeypatch
):
    """Adversarial (the Developer's FINDINGS edge): when `_write_wave_synthesis`
    itself fails every time, the handler prints CRASHED + traceback and then
    its own synthesis call raises again. Documented behaviour: the second
    exception propagates out of `cmd_wave` (no `3`, no file, no record); the
    CRASHED line is not lost."""

    def always_boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(dispatch, "_write_wave_synthesis", always_boom)
    with pytest.raises(OSError, match="disk full"):
        _wave(dispatch, adapter)
    out = capsys.readouterr().out
    assert _crashed_lines(out) == ["CRASHED — Synthesis: OSError: disk full"]
    assert _TRACEBACK_HEADER in out
    assert _synthesis_files(repo) == [] and _wave_records() == []


# covers hub-tooling FR-0014:AC-4
def test_a_crash_after_synthesis_in_park_findings_emits_a_second_wave_record(
    repo, adapter, drive, monkeypatch, capsys
):
    """Adversarial: `--park-findings` runs after the normal synthesis; a raise
    there is caught as a "Synthesis" crash and the handler synthesises again.
    Documented behaviour: exit 3 and the CRASHED line as required, but the
    wave is recorded twice (same file path, two `dispatch.wave` records) —
    pinned so the duplicate is visible (FINDINGS), not a silent count drift."""

    def boom(rows, started_at):
        raise RuntimeError("park boom")

    monkeypatch.setattr(dispatch, "_park_findings", boom)
    assert _wave(dispatch, adapter, park_findings=True) == _CRASH_RC
    out = capsys.readouterr().out
    assert _crashed_lines(out) == ["CRASHED — Synthesis: RuntimeError: park boom"]
    assert drive.synthesis_calls == 2 and len(_synthesis_files(repo)) == 1
    recs = _wave_records()
    assert len(recs) == 2 and all(
        r["completed"] == 1 and r["dropped"] == 0 for r in recs
    )


# covers hub-tooling FR-0014:AC-4
def test_a_rework_round_crash_leaves_the_round1_completed_fr_unmarked(
    repo, adapter, drive, capsys
):
    """Per AC-4's terminal-state rule an FR that finalized both legs in round 1
    is `completed_e2e`, so a crash inside its rework round is NOT re-marked:
    the record shows completed=1, dropped=0, and only the CRASHED line and
    exit code carry the crash. Pinned here so the gap is visible (FINDINGS)."""
    drive.raise_at = "rework"
    drive.rev_verdicts[_FR] = ["request-changes", "approve"]
    assert _wave(dispatch, adapter, rounds=2) == _CRASH_RC
    out = capsys.readouterr().out
    assert _crashed_lines(out) == ["CRASHED — rework: RuntimeError: boom"]
    [rec] = _wave_records()
    assert rec["completed"] == 1 and rec["dropped"] == 0 and rec["drop_reasons"] == []
    assert rec["rounds_ran"] == {_FR: 1}
    assert "-crash" not in _synthesis_files(repo)[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-5: stdout flushed at every phase boundary
# ---------------------------------------------------------------------------


class _CountingStdout(io.TextIOWrapper):
    """Block-buffered text stream that records what had reached the underlying
    bytes at each flush — so "flushed before the wave proceeded" is provable."""

    def __init__(self) -> None:
        self._raw = io.BytesIO()
        super().__init__(
            io.BufferedWriter(self._raw, buffer_size=1 << 20),
            encoding="utf-8",
            write_through=False,
        )
        self.flush_count = 0
        self.snapshots: list[str] = []

    def flush(self) -> None:
        super().flush()
        self.flush_count += 1
        self.snapshots.append(self._raw.getvalue().decode("utf-8"))

    def reached(self, needle: str) -> str | None:
        """The first flush snapshot containing `needle`, or None."""
        for snap in self.snapshots:
            if needle in snap:
                return snap
        return None

    def written(self) -> str:
        super().flush()
        return self._raw.getvalue().decode("utf-8")


def _wave_into(w: _CountingStdout, mod, adapter, **kw) -> int:
    """Run the wave with `sys.stdout` swapped for the counting wrapper for the
    duration of the call only (pytest re-installs its capture stream between
    fixture setup and the test body, so a fixture-time swap does not hold)."""
    with contextlib.redirect_stdout(w):
        return _wave(mod, adapter, **kw)


def _phase_banners(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("--- Phase ")]


# covers hub-tooling FR-0014:AC-5
def test_dry_run_flushes_at_least_once_per_phase_banner(repo, adapter, drive):
    w = _CountingStdout()
    assert _wave_into(w, dispatch, adapter, apply=False) == 0
    text = w.written()
    banners = _phase_banners(text)
    assert banners[:2] == ["--- Phase 0: Pre-flight ---", "--- Phase 1: Dev Tick ---"]
    assert w.flush_count >= len(banners) >= 2
    # Phase 0's banner reached the bytes before Phase 1's was even written.
    snap = w.reached("--- Phase 0: Pre-flight ---")
    assert snap is not None and "--- Phase 1" not in snap
    assert w.reached("--- Phase 1: Dev Tick ---") is not None
    assert w.reached(f"{_FR}  WOULD-SPAWN") is not None


# covers hub-tooling FR-0014:AC-5
def test_a_stream_that_is_never_flushed_holds_everything_back(
    repo, adapter, drive, monkeypatch
):
    """Sanity check on the harness: with `flush=True` prints neutralised the
    same wrapper sees zero flushes and zero bytes until the end — so the
    counter above is measuring the dispatcher, not the wrapper."""
    w = _CountingStdout()
    real_print = print

    def no_flush_print(*a, **k):
        k.pop("flush", None)
        real_print(*a, **k)

    # A module-global `print` shadows the builtin for dispatch.py's own calls.
    monkeypatch.setattr(dispatch, "print", no_flush_print, raising=False)
    with contextlib.redirect_stdout(w):
        assert _wave(dispatch, adapter, apply=False) == 0
    assert w.flush_count == 0 and w._raw.getvalue() == b""
    assert "--- Phase 1: Dev Tick ---" in w.written()


# covers hub-tooling FR-0014:AC-5
def test_apply_mode_flushes_every_banner_outcome_line_and_the_rework_banner(
    repo, adapter, drive
):
    drive.rev_verdicts[_FR] = ["request-changes", "approve"]
    w = _CountingStdout()
    assert _wave_into(w, dispatch, adapter, rounds=2) == 0
    text = w.written()
    banners = _phase_banners(text)
    assert [b.split(" (")[0] for b in banners] == [
        "--- Phase 0: Pre-flight ---",
        "--- Phase 1: Dev Tick ---",
        "--- Phase 2: Dev Monitor",
        "--- Phase 3: Dev Evaluate + Finalize ---",
        "--- Phase 4: Rev Tick ---",
        "--- Phase 5: Rev Monitor",
        "--- Phase 6: Rev Evaluate + Finalize ---",
    ]
    assert w.flush_count >= len(banners)
    # Each banner was flushed before the next one was written.
    for this, nxt in itertools.pairwise(banners):
        snap = w.reached(this)
        assert snap is not None, this
        assert nxt not in snap, f"{this!r} not flushed before {nxt!r}"
    for line in (
        f"{_FR}  SPAWNED",
        f"{_FR}  FINALIZED",
        f"{_FR}  REVIEW-POSTED  verdict=request-changes",
        "--- Rework rounds (budget=2) ---",
        f"{_FR}  REWORK round 2/2",
        f"{_FR}  REWORK round 2 verdict=approve",
    ):
        assert w.reached(line) is not None, line
    # The rework banner reached the stream before round 2's first line.
    snap = w.reached("--- Rework rounds (budget=2) ---")
    assert f"{_FR}  REWORK round 2 verdict=" not in snap


# covers hub-tooling FR-0014:AC-5
def test_dropped_lines_and_the_crashed_line_are_flushed_before_return(
    repo, adapter, drive
):
    drive.rev_status[_FR] = "error"
    w = _CountingStdout()
    assert _wave_into(w, dispatch, adapter) == 1
    assert w.reached(f"{_FR}  DROPPED — rev error") is not None
    _git(
        repo,
        "worktree",
        "remove",
        "--force",
        str(repo / ".claude" / "worktrees" / f"dev-{_FR}"),
    )
    _git(repo, "branch", "-D", f"claude/dev-{_FR}")
    drive.rev_status.clear()
    drive.raise_at = "rev-evaluate"
    w2 = _CountingStdout()
    assert _wave_into(w2, dispatch, adapter) == _CRASH_RC
    crashed = "CRASHED — Phase 6: Rev Evaluate + Finalize: RuntimeError: boom"
    snap = w2.reached(crashed)
    assert snap is not None and w2.flush_count >= 2
    # The traceback is flushed too, in its own flush after the CRASHED line.
    tb_snap = w2.reached(f"{_TRACEBACK_HEADER}")
    assert tb_snap is not None and "RuntimeError: boom" in tb_snap
    # The CRASHED line was pushed before the synthesis ran.
    assert "Synthesis written" not in snap


# covers hub-tooling FR-0014:AC-5
def test_dry_run_output_is_byte_identical_to_the_pre_fr_dispatcher(
    tmp_path, monkeypatch, pre_fr_dispatch, capsys
):
    """Out-of-scope guard: flushing changes *when* bytes land, never *what*.

    Both sides run at an explicit `rounds=1` (DEC-0007): the `--rounds`
    default is FR-0013 AC-8's to set and is not part of what this guard pins.
    """

    def run(mod, root):
        r = _make_repo(root)
        _point(monkeypatch, mod, r)
        _install(monkeypatch, mod, r)
        assert _wave(mod, _FakeAdapter(), apply=False, rounds=1) == 0
        out = capsys.readouterr().out
        out = re.sub(r"Wave started at \S+", "Wave started at <ts>", out)
        out = re.sub(r"Elapsed: [^.]+\.", "Elapsed: <t>.", out)
        out = re.sub(r"Wave Synthesis — \S+", "Wave Synthesis — <ts>", out)
        out = re.sub(r"wave-\S+\.md", "wave-<ts>.md", out)
        return out.replace(str(r), "<repo>")

    assert run(dispatch, tmp_path / "new") == run(pre_fr_dispatch, tmp_path / "old")


_CHILD_SOURCE = """\
import importlib.util, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[4])  # dispatch.py's sibling modules
spec = importlib.util.spec_from_file_location('d', sys.argv[1])
d = importlib.util.module_from_spec(spec); sys.modules['d'] = d
spec.loader.exec_module(d)
r = Path(sys.argv[2])
d.REPO_ROOT, d.SPECS_DIR, d.DISPATCH_DIR = r, r / 'specs', r / '_dispatch'
def blocking(verbose=False):
    time.sleep(120)
    return (True, None)
d._gh_preflight = blocking
d.prune_dead_locks = lambda verbose=False: 0
A = SimpleNamespace(name='fake', binary_name='fake', dry_run_preview=lambda *a: 'p')
raise SystemExit(d.cmd_wave(apply=False, adapter=A, fr_filter=[sys.argv[3]]))
"""


def _child_script(tmp_path: Path) -> Path:
    """A subprocess that points a dispatch.py at a repo, makes `_gh_preflight`
    block, and runs a dry-run wave — so the only way the Phase 0 banner reaches
    the redirected file while the child is alive is a flush."""
    script = tmp_path / "child.py"
    script.write_text(_CHILD_SOURCE, encoding="utf-8", newline="\n")
    return script


def _run_child_and_kill(
    tmp_path: Path, dispatch_path: Path, repo: Path, wait_s: float
) -> str:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.pop("PYTHONIOENCODING", None)
    log = tmp_path / f"wave-{dispatch_path.parent.name}.log"
    with log.open("wb") as fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(_child_script(tmp_path)),
                str(dispatch_path),
                str(repo),
                _FR,
                str(_SCRIPTS_DIR),
            ],
            stdout=fh,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=str(repo),
        )
        try:
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                if "--- Phase 0: Pre-flight ---" in log.read_text(
                    encoding="utf-8", errors="replace"
                ):
                    break
                time.sleep(0.1)
            assert proc.poll() is None, (
                "child exited before it was killed — the block never held"
            )
        finally:
            proc.kill()
            proc.wait(timeout=30)
    return log.read_text(encoding="utf-8", errors="replace")


# covers hub-tooling FR-0014:AC-5
def test_subprocess_with_redirected_stdout_shows_phase0_banner_while_still_running(
    tmp_path, repo
):
    text = _run_child_and_kill(tmp_path, _SCRIPTS_DIR / "dispatch.py", repo, wait_s=30)
    assert "--- Phase 0: Pre-flight ---" in text
    assert "Wave started at" in text


# covers hub-tooling FR-0014:AC-5
def test_bite_pre_fr_subprocess_shows_nothing_until_exit(
    tmp_path, repo, pre_fr_dispatch
):
    """Same child, the pre-FR dispatcher: the block-buffered banner never lands
    while the process is alive — the failure mode Project A L57 described."""
    text = _run_child_and_kill(tmp_path, Path(pre_fr_dispatch.__file__), repo, wait_s=3)
    assert "--- Phase 0: Pre-flight ---" not in text


# covers hub-tooling FR-0014:AC-5
def test_a_stdout_whose_flush_raises_surfaces_the_error_rather_than_hanging(
    repo, adapter, drive
):
    """Adversarial: a consumer that dies (flush -> BrokenPipeError) is not
    hidden. Documented behaviour: failing from the first flush, the error
    propagates from Phase 0's banner — outside the crash handler — so no
    CRASHED line, no record; the wave neither hangs nor spawns."""

    class _Broken(io.StringIO):
        def __init__(self, fail_from: int) -> None:
            super().__init__()
            self.calls = 0
            self.fail_from = fail_from

        def flush(self):
            self.calls += 1
            if self.calls >= self.fail_from:
                raise BrokenPipeError("consumer gone")

    w = _Broken(fail_from=1)
    with contextlib.redirect_stdout(w), pytest.raises(BrokenPipeError):
        _wave(dispatch, adapter)
    assert drive.spawned == [] and _wave_records() == []
    # Failing from the second flush (Phase 1's banner, inside the handler's
    # reach): the handler catches it, prints CRASHED — whose own flush raises
    # again — so the BrokenPipeError still propagates, with no record and no
    # synthesis file. Not hidden, not hung; documented under FINDINGS.
    w2 = _Broken(fail_from=2)
    with contextlib.redirect_stdout(w2), pytest.raises(BrokenPipeError):
        _wave(dispatch, adapter)
    assert (
        "CRASHED — Phase 1: Dev Tick: BrokenPipeError: consumer gone" in w2.getvalue()
    )
    assert (
        drive.spawned == [] and _wave_records() == [] and _synthesis_files(repo) == []
    )
