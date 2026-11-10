"""Reviewer tests for FR-0002 — `dispatch.py` emission: spawn / run / wave
records (AC-3), PR events (AC-5), the `[slice-miss]` FINDINGS tag stored as
refs + length (AC-7), the "no separate escalation record from the dispatcher"
half of AC-6, and the control-plane invariants this FR must not disturb
(`ROLE_PERMISSIONS`, `_FINDING_LINE` handling of `scope|spec|doc`).

There were no unit tests for `dispatch.py` before this FR, so the harness is
new: the hyphen-free module is loaded by path, its `REPO_ROOT` / `SPECS_DIR` /
`DISPATCH_DIR` globals are pointed at a temp tree, the git-touching helpers
that a real dispatcher would call (`ensure_role_worktree`, `_gh_*`,
`_commit_spec_flip`, ...) are replaced with in-process stubs, and the harness
log is a synthetic Claude Code NDJSON file written by the test (AC-3: "a fake
harness adapter over a synthetic NDJSON log fixture"). No network, no `gh`,
no worktrees are created. `metrics_log` is the same module object the
dispatcher imported, so repointing its `METRICS_DIR` captures every record.

Coverage annotations are written `# covers hub-tooling FR-0002:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0002 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (see test_index_specs_versioning.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

# Convention: backward-compat baselines pin a commit, never a branch name (see
# test_spec_query.py). Outside the hub checkout the commit is unreachable and
# the baseline-comparison tests skip.

from __future__ import annotations

import importlib.util
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
_PRE_FR0002_REF = "c49a893"
# Spelled in two halves so a bootstrapped project's `deploy-gate.py`, which
# regex-scans every file under tests/, does not read these fixture strings as
# real annotations against FRs that project never had.
_COVERS = "@" + "covers"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log


def _load_dispatch(name: str = "dispatch_under_test_fr0002", path: Path | None = None):
    spec = importlib.util.spec_from_file_location(name, path or _SCRIPTS_DIR / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch()
assert dispatch._metrics is metrics_log, "dispatch must import the same metrics_log the tests observe"


def _git_show_baseline(rel: str, ref: str = _PRE_FR0002_REF) -> bytes | None:
    hub = _TEMPLATE_DIR.parent
    probe = subprocess.run(["git", "-C", str(hub), "cat-file", "-e", f"{ref}^{{commit}}"], capture_output=True, check=False)
    if probe.returncode != 0:
        return None
    proc = subprocess.run(["git", "-C", str(hub), "show", f"{ref}:{rel}"], capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dispatch, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", tmp_path / "_dispatch")
    monkeypatch.setattr(dispatch, "_RUN_REGISTRY", {})
    monkeypatch.setattr(dispatch, "_PREFLIGHT_GATE_RECORD_IDS", {})
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setattr(metrics_log, "PHI_HOOK_PATH", tmp_path / "no-such-hook.py")
    monkeypatch.setattr(metrics_log, "_PHI_PATTERNS", None)
    monkeypatch.setattr(metrics_log, "_PHI_PATH_LOADED", None)
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (tmp_path / "specs").mkdir()
    (tmp_path / "_dispatch").mkdir()


def _records() -> list[dict]:
    d = metrics_log.METRICS_DIR
    if not d.exists():
        return []
    recs = [json.loads(ln) for f in sorted(d.glob("*.ndjson")) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for r in recs:
        assert metrics_log.validation_errors(r) == [], r
    return recs


# ---------------------------------------------------------------------------
# Synthetic Claude Code NDJSON harness log
# ---------------------------------------------------------------------------


def _tool_use(tool_id: str, name: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}]}}


def _tool_result(tool_id: str, *, error: bool) -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "is_error": error, "content": "…"}]}}


def _text(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _result(*, error: bool = False, usage: dict | None = None, subtype: str = "success") -> dict:
    obj: dict = {"type": "result", "subtype": subtype, "is_error": error}
    if usage is not None:
        obj["usage"] = usage
    return obj


_FINAL_TEXT = (
    "Done. Implemented the mapper.\n\n"
    "## FINDINGS\n"
    "- [slice-miss] needed specs/FR-0009-extraction-agent.md to satisfy AC-3\n"
    "- [spec] FR-0100 AC-2 says 'retain' but the matrix says 'archive' — this is prose the log must never carry\n"
    "- unlabelled observation about docs/architecture/overview.md\n"
    "- (none)\n"
)

_USAGE = {"input_tokens": 1000, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 50000, "output_tokens": 777}


def _standard_log(*, final_text: str = _FINAL_TEXT, usage: dict | None = _USAGE, error: bool = False) -> list[dict]:
    return [
        _tool_use("t1", "Read"), _tool_result("t1", error=False),
        _tool_use("t2", "Bash"), _tool_result("t2", error=True),
        _tool_use("t3", "Bash"), _tool_result("t3", error=True),
        _tool_use("t4", "Edit"), _tool_result("t4", error=True),
        _tool_use("t5", "Bash"), _tool_result("t5", error=False),
        {"type": "system", "subtype": "init"},
        _text(final_text),
        _result(error=error, usage=usage, subtype="error_during_execution" if error else "success"),
    ]


def _write_log(fr_id: str, role: str, entries: list[dict]) -> Path:
    p = dispatch.DISPATCH_DIR / f"{fr_id}.{role}.log"
    p.write_text("".join(json.dumps(e) + "\n" for e in entries) + "not json at all\n", encoding="utf-8")
    return p


def _lock(fr_id: str, role: str, *, run_id: str = "r" * 32, round_num: int = 2) -> None:
    dispatch.write_lock(fr_id, role, os.getpid(), run_id=run_id, round=round_num, harness="claude-code")


# ---------------------------------------------------------------------------
# AC-3 (b): dispatch.run from a faked harness log
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-3
def test_evaluate_emits_one_run_record_with_counts_tokens_round_and_duration_from_the_fake_log():
    _write_log("FR-0100", "dev", _standard_log())
    _lock("FR-0100", "dev", run_id="d" * 32, round_num=2)
    outcome = dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    assert outcome.status == "success" and outcome.verdict is None
    [rec] = _records()
    assert rec["kind"] == "dispatch.run" and rec["source"] == "dispatch" and rec["role"] == "dev"
    assert rec["object_ids"] == ["FR-0100"] and rec["run_id"] == "d" * 32
    assert rec["status"] == "success"
    assert rec["tool_calls_total"] == 5 and rec["tool_calls_by_tool"] == {"Read": 1, "Bash": 3, "Edit": 1}
    assert rec["tool_errors_total"] == 3 and rec["tool_errors_by_tool"] == {"Bash": 2, "Edit": 1}
    assert rec["tokens_in"] == 1000 + 200 + 50000 and rec["tokens_out"] == 777
    assert isinstance(rec["duration_s"], (int, float)) and 0 <= rec["duration_s"] < 60
    assert rec["round"] == 2 and rec["verdict"] is None
    assert len(rec["findings"]) == 3
    assert set(rec) == set(metrics_log.ENVELOPE_FIELDS) | set(metrics_log.KIND_REQUIRED["dispatch.run"])


# covers hub-tooling FR-0002:AC-3
def test_tokens_are_null_never_estimated_when_the_harness_log_carries_no_usage():
    _write_log("FR-0100", "dev", _standard_log(usage=None))
    _lock("FR-0100", "dev")
    dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    [rec] = _records()
    assert rec["tokens_in"] is None and rec["tokens_out"] is None
    assert rec["tool_calls_total"] == 5  # counts still come from the log
    # Partial usage: only output_tokens present -> tokens_in stays null.
    _write_log("FR-0101", "dev", _standard_log(usage={"output_tokens": 5}))
    _lock("FR-0101", "dev")
    dispatch._evaluate_agent_outcome("FR-0101", "dev", dispatch.ClaudeCodeAdapter())
    rec = _records()[-1]
    assert rec["tokens_in"] is None and rec["tokens_out"] == 5


# covers hub-tooling FR-0002:AC-3
def test_error_escalation_and_reviewer_verdict_paths_emit_the_matching_status():
    _write_log("FR-0100", "dev", _standard_log(error=True))
    _lock("FR-0100", "dev")
    assert dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter()).status == "error"
    _write_log("FR-0101", "dev", _standard_log(final_text="## ESCALATION\n- FR(s): FR-0101\n- Trigger: Spec is ambiguous\n- Summary: prose"))
    _lock("FR-0101", "dev")
    assert dispatch._evaluate_agent_outcome("FR-0101", "dev", dispatch.ClaudeCodeAdapter()).status == "escalation"
    _write_log("FR-0102", "rev", _standard_log(final_text="## Review\n\n**Request changes** — AC-2 uncovered.\n"))
    _lock("FR-0102", "rev", round_num=1)
    out = dispatch._evaluate_agent_outcome("FR-0102", "rev", dispatch.ClaudeCodeAdapter())
    assert out.status == "success" and out.verdict == "request-changes"
    recs = _records()
    assert [(r["role"], r["status"], r["verdict"], r["round"]) for r in recs] == [
        ("dev", "error", None, 2), ("dev", "escalation", None, 2), ("rev", "success", "request-changes", 1),
    ]
    # AC-6: an agent's ## ESCALATION block produces no separate `escalation`
    # record from the dispatcher — the dispatch.run status carries it.
    assert all(r["kind"] == "dispatch.run" for r in recs)
    assert not any("Summary" in json.dumps(r) or "prose" in json.dumps(r) for r in recs)


# covers hub-tooling FR-0002:AC-3
def test_no_log_and_timeout_paths_emit_zeroed_records_with_null_tokens():
    _lock("FR-0100", "dev", run_id="n" * 32, round_num=1)
    outcome = dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    assert outcome.status == "no-log"
    dispatch._emit_dispatch_run("FR-0100", "dev", "timeout", None)
    no_log, timeout = _records()
    for rec in (no_log, timeout):
        assert rec["tool_calls_total"] == 0 and rec["tool_calls_by_tool"] == {} and rec["tool_errors_total"] == 0
        assert rec["tokens_in"] is None and rec["tokens_out"] is None and rec["findings"] == []
        assert rec["run_id"] == "n" * 32 and rec["round"] == 1
    assert no_log["status"] == "no-log" and timeout["status"] == "timeout"
    # Without any lock or registry entry: still a record, duration/run_id null.
    dispatch._emit_dispatch_run("FR-0199", "rev", "timeout", None)
    rec = _records()[-1]
    assert rec["run_id"] is None and rec["duration_s"] is None and rec["round"] == 1


# covers hub-tooling FR-0002:AC-3
def test_rework_round_timeout_path_emits_a_dev_timeout_record(monkeypatch):
    """Drive `_run_one_rework_round` to its Developer-timeout exit with the
    worktree, brief and spawn replaced by stubs."""
    monkeypatch.setattr(dispatch, "_prepare_dev_worktree_for_rework", lambda fr: (True, "ok"))
    monkeypatch.setattr(dispatch, "_dev_worktree", lambda fr: dispatch.REPO_ROOT / "wt")
    monkeypatch.setattr(dispatch, "_collect_failing_tests", lambda wt: [])
    monkeypatch.setattr(dispatch, "_generate_rework_brief", lambda **kw: "brief")
    monkeypatch.setattr(dispatch, "_write_rework_brief", lambda wt, fr, rn, brief: "REWORK.md")
    monkeypatch.setattr(dispatch, "_fr_title", lambda fr: "Synthetic")
    monkeypatch.setattr(dispatch, "fr_owns_globs", lambda fr: [])
    seen: dict = {}

    def fake_spawn(fr_id, role, apply, adapter, extra_prompt=None, round_num=1):
        seen["round_num"] = round_num
        _lock(fr_id, role, run_id="w" * 32, round_num=round_num)
        return ("spawned", 4242, dispatch.REPO_ROOT / "wt")

    monkeypatch.setattr(dispatch, "spawn_role", fake_spawn)
    monkeypatch.setattr(dispatch, "_wait_for_phase", lambda targets, poll, timeout: {fr: "timeout" for fr, _ in targets})
    verdict, note = dispatch._run_one_rework_round("FR-0100", 3, 3, "verdict text", True, SimpleNamespace(name="claude-code"), 1.0, 0.1)
    assert verdict is None and note == "dev rework timed out" and seen["round_num"] == 3
    [rec] = _records()
    assert rec["kind"] == "dispatch.run" and rec["status"] == "timeout" and rec["role"] == "dev"
    assert rec["round"] == 3 and rec["run_id"] == "w" * 32


# covers hub-tooling FR-0002:AC-3
def test_dispatch_run_never_carries_the_transcript_or_error_messages():
    marker = "xq-permission-denied-marker-text"
    entries = [
        _tool_use("t1", "Bash"),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": marker}]}},
        _text(f"I saw {marker} and gave up.\n\n## FINDINGS\n- [scope] the file {marker}.py is outside my footprint\n"),
        _result(usage=_USAGE),
    ]
    _write_log("FR-0100", "dev", entries)
    _lock("FR-0100", "dev")
    dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    [rec] = _records()
    assert marker not in json.dumps(rec)
    assert rec["findings"] == [{"tag": "scope", "refs": [], "chars": len(f"the file {marker}.py is outside my footprint")}]


# ---------------------------------------------------------------------------
# AC-3 (a): dispatch.spawn
# ---------------------------------------------------------------------------


class _FakeAdapter:
    name = "claude-code"
    binary_name = "claude"

    def __init__(self, result: str = "spawned"):
        self.result = result
        self.env_seen: dict[str, str | None] = {}
        self.calls: list[tuple] = []

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.env_seen = {k: os.environ.get(k) for k in ("DISPATCH_RUN_ID", "METRICS_PROJECT")}
        self.calls.append((fr_id, role, extra_prompt))
        return (self.result, 4242 if self.result == "spawned" else None)

    def parse_log(self, log_path):
        return dispatch.AgentLogSummary()

    def write_worktree_settings(self, wt_path, role, fr_id):
        pass

    def dry_run_preview(self, fr_id, role, wt_preview):
        return f"preview {fr_id} {role}"


def _stub_worktree(monkeypatch, tmp_path, status: str = "created,venv skipped"):
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    monkeypatch.setattr(dispatch, "ensure_role_worktree", lambda fr, role, adapter: (wt, status))
    monkeypatch.setattr(dispatch, "_base_branch_for_role", lambda fr, role: "main" if role == "dev" else f"claude/dev-{fr}")
    return wt


# covers hub-tooling FR-0002:AC-3
def test_spawn_emits_one_spawn_record_exports_run_id_to_the_agent_and_restores_the_environment(monkeypatch, tmp_path):
    _stub_worktree(monkeypatch, tmp_path)
    monkeypatch.delenv("DISPATCH_MODEL_DEV", raising=False)
    adapter = _FakeAdapter()
    assert "DISPATCH_RUN_ID" not in os.environ
    result, pid, wt = dispatch.spawn_role("FR-0100", "dev", apply=True, adapter=adapter, round_num=2)
    assert (result, pid) == ("spawned", 4242) and wt == tmp_path / "wt"
    assert "DISPATCH_RUN_ID" not in os.environ  # restored after the spawn
    assert os.environ["METRICS_PROJECT"] == "synthetic-project"
    run_id = adapter.env_seen["DISPATCH_RUN_ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", run_id or "") and adapter.env_seen["METRICS_PROJECT"] == "synthetic-project"
    [rec] = _records()
    assert rec["kind"] == "dispatch.spawn" and rec["role"] == "dev" and rec["object_ids"] == ["FR-0100"]
    assert rec["run_id"] == run_id
    assert rec["harness"] == "claude-code" and rec["worktree_status"] == "created" and rec["base_branch"] == "main"
    assert rec["model"] == dispatch._resolve_model("dev") == "sonnet" and rec["round"] == 2
    lock = json.loads(dispatch.lock_path("FR-0100", "dev").read_text(encoding="utf-8"))
    assert lock["run_id"] == run_id and lock["round"] == 2 and lock["base_branch"] == "main"
    assert dispatch._RUN_REGISTRY[("FR-0100", "dev")]["run_id"] == run_id
    assert adapter.calls == [("FR-0100", "dev", None)]


# covers hub-tooling FR-0002:AC-3
def test_spawn_round_defaults_to_one_and_reused_worktree_and_model_override_are_recorded(monkeypatch, tmp_path):
    _stub_worktree(monkeypatch, tmp_path, status="reused,venv reused")
    monkeypatch.setenv("DISPATCH_MODEL_REV", "opus-custom")
    dispatch.spawn_role("FR-0100", "rev", apply=True, adapter=_FakeAdapter(), extra_prompt="rework brief")
    [rec] = _records()
    assert rec["round"] == 1 and rec["worktree_status"] == "reused" and rec["model"] == "opus-custom"
    assert rec["base_branch"] == "claude/dev-FR-0100" and rec["role"] == "rev"


# covers hub-tooling FR-0002:AC-3
def test_spawn_and_run_records_join_on_run_id(monkeypatch, tmp_path):
    _stub_worktree(monkeypatch, tmp_path)
    dispatch.spawn_role("FR-0100", "dev", apply=True, adapter=_FakeAdapter())
    _write_log("FR-0100", "dev", _standard_log())
    dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    spawn, run = _records()
    assert spawn["kind"] == "dispatch.spawn" and run["kind"] == "dispatch.run"
    assert spawn["run_id"] == run["run_id"] and run["round"] == spawn["round"] == 1
    # Across processes the lock is the join: wipe the registry and re-evaluate.
    dispatch._RUN_REGISTRY.clear()
    dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    assert _records()[-1]["run_id"] == spawn["run_id"]


# covers hub-tooling FR-0002:AC-3
def test_dry_run_and_failed_spawns_emit_nothing(monkeypatch, tmp_path):
    assert dispatch.spawn_role("FR-0100", "dev", apply=False, adapter=_FakeAdapter()) == ("dry-run", None, None)
    assert _records() == [] and not dispatch.lock_path("FR-0100", "dev").exists()
    _stub_worktree(monkeypatch, tmp_path)
    result, pid, _ = dispatch.spawn_role("FR-0100", "dev", apply=True, adapter=_FakeAdapter("binary-not-found"))
    assert result == "binary-not-found" and pid is None
    assert _records() == [] and "DISPATCH_RUN_ID" not in os.environ
    monkeypatch.setattr(dispatch, "ensure_role_worktree", lambda fr, role, adapter: (None, "error:git failed"))
    result, _, _ = dispatch.spawn_role("FR-0100", "dev", apply=True, adapter=_FakeAdapter())
    assert result == "error:git failed" and _records() == []


# covers hub-tooling FR-0002:AC-3
def test_spawn_with_emission_disabled_still_exports_a_run_id_but_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("METRICS_LOG_DISABLED", "1")
    _stub_worktree(monkeypatch, tmp_path)
    adapter = _FakeAdapter()
    assert dispatch.spawn_role("FR-0100", "dev", apply=True, adapter=adapter)[0] == "spawned"
    assert adapter.env_seen["DISPATCH_RUN_ID"] and not metrics_log.METRICS_DIR.exists()


# ---------------------------------------------------------------------------
# AC-3 (c): dispatch.wave
# ---------------------------------------------------------------------------


def _wave_results() -> list:
    ok = dispatch.WaveFRResult(fr_id="FR-0100", dev_finalize_ok=True, rev_finalize_ok=True, rev_verdict="approve", rounds_ran=2,
                               round_verdicts=["request-changes", "approve"])
    dev_only = dispatch.WaveFRResult(fr_id="FR-0101", dev_finalize_ok=True, rounds_ran=1)
    dropped = dispatch.WaveFRResult(fr_id="FR-0102", dropped_at="dev-monitor", drop_reason="phase timeout (agent killed) — prose", rounds_ran=1)
    forced = dispatch.WaveFRResult(fr_id="FR-0103", dev_finalize_ok=True, rev_finalize_ok=True, rev_verdict="request-changes",
                                   rounds_ran=3, round_verdicts=["request-changes"] * 3, force_escalated=True)
    return [ok, dev_only, dropped, forced]


# covers hub-tooling FR-0002:AC-3
def test_wave_synthesis_emits_one_wave_record_with_counts_phases_rounds_and_force_escalations(capsys):
    path = dispatch._write_wave_synthesis(_wave_results(), "2026-09-07T00:00:00+00:00", 42.0, emit_record=True)
    assert path.exists()
    report = capsys.readouterr().out
    [rec] = _records()
    assert rec["kind"] == "dispatch.wave" and rec["role"] == "orchestrator" and rec["run_id"] is None
    assert rec["object_ids"] == ["FR-0100", "FR-0101", "FR-0102", "FR-0103"]
    assert rec["fr_count"] == 4 and rec["completed"] == 2 and rec["dev_only"] == 1 and rec["dropped"] == 1
    assert rec["drop_reasons"] == [{"fr_id": "FR-0102", "phase": "dev-monitor"}]
    assert rec["rounds_ran"] == {"FR-0100": 2, "FR-0101": 1, "FR-0102": 1, "FR-0103": 3}
    assert rec["force_escalated"] == ["FR-0103"]
    assert "prose" not in json.dumps(rec) and "phase timeout" not in json.dumps(rec)
    # The synthesis report itself is unchanged by the record.
    assert "Processed 4 FR(s). 2 completed end-to-end. 1 dev-only" in report


# covers hub-tooling FR-0002:AC-3
def test_wave_synthesis_without_emit_record_and_the_dry_run_wave_write_nothing(monkeypatch, capsys):
    dispatch._write_wave_synthesis(_wave_results(), "2026-09-07T00:00:00+00:00", 1.0)
    assert _records() == []
    # A full dry-run wave: pre-flight, one runnable FR, WOULD-SPAWN, synthesis.
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose: (True, None))
    monkeypatch.setattr(dispatch, "prune_dead_locks", lambda verbose: 0)
    monkeypatch.setattr(dispatch, "reconcile_merged_prs", lambda apply, verbose: dispatch.ReconcileSummary(flipped=[], cleaned=[], skipped=[]))
    frs = [{"id": "FR-0100", "status": "ready", "depends_on": []}]
    monkeypatch.setattr(dispatch, "load_frs", lambda: frs)
    monkeypatch.setattr(dispatch, "runnable_frs", lambda all_frs: frs)
    monkeypatch.setattr(dispatch, "lock_state", lambda fr, role: ("free", None))
    monkeypatch.setattr(dispatch, "_base_branch_for_role", lambda fr, role: "main")
    rc = dispatch.cmd_wave(apply=False, adapter=_FakeAdapter(), poll_interval=0.01)
    out = capsys.readouterr().out
    assert rc == 0 and "WOULD-SPAWN" in out and "Synthesis written" in out
    assert _records() == [] and not metrics_log.METRICS_DIR.exists()
    monkeypatch.setattr(dispatch, "runnable_frs", lambda all_frs: [])
    assert dispatch.cmd_wave(apply=False, adapter=_FakeAdapter()) == 0
    assert _records() == []


# ---------------------------------------------------------------------------
# AC-7: [slice-miss] FINDINGS tag — parsed, stored as refs + length
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-7
def test_finding_line_accepts_slice_miss_and_keeps_scope_spec_doc_and_untagged_handling():
    text = (
        "## FINDINGS\n"
        "- [slice-miss] needed specs/FR-0009-extraction-agent.md to satisfy AC-3\n"
        "- [scope] touched src/x.py outside owns\n"
        "- [spec] FR-0100 AC-2 ambiguous\n"
        "- [doc] docs/README.md stale\n"
        "- [bogus] unknown tags stay in the text\n"
        "- plain untagged line\n"
        "- (none)\n"
        "## NEXT\n- [spec] not a finding, block closed\n"
    )
    findings = dispatch._parse_findings(text)
    assert findings == [
        ("slice-miss", "needed specs/FR-0009-extraction-agent.md to satisfy AC-3"),
        ("scope", "touched src/x.py outside owns"),
        ("spec", "FR-0100 AC-2 ambiguous"),
        ("doc", "docs/README.md stale"),
        ("", "[bogus] unknown tags stay in the text"),
        ("", "plain untagged line"),
    ]
    assert dispatch._parse_findings(None) == [] and dispatch._parse_findings("no block here") == []
    assert dispatch._FINDING_LINE.pattern == r"^-\s+(?:\[(scope|spec|doc|slice-miss)\]\s*)?(.+)$"


# covers hub-tooling FR-0002:AC-7
def test_slice_miss_record_carries_tag_refs_and_length_and_no_other_text():
    body = "needed specs/FR-0009-extraction-agent.md to satisfy AC-3"
    _write_log("FR-0100", "dev", _standard_log(final_text=f"## FINDINGS\n- [slice-miss] {body}\n"))
    _lock("FR-0100", "dev")
    outcome = dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    assert outcome.findings == [("slice-miss", body)]  # the text still reaches the outcome / synthesis
    [rec] = _records()
    [finding] = rec["findings"]
    assert set(finding) == {"tag", "refs", "chars"}
    assert finding["tag"] == "slice-miss" and finding["chars"] == len(body)
    assert "FR-0009" in finding["refs"] and "specs/FR-0009-extraction-agent.md" in finding["refs"]
    assert set(finding["refs"]) == {"FR-0009", "specs/FR-0009-extraction-agent.md"}
    for word in ("needed", "satisfy", "to", "AC-3"):
        assert word not in json.dumps(finding["refs"])
    assert body not in json.dumps(rec)


# covers hub-tooling FR-0002:AC-7
def test_every_finding_is_recorded_structurally_whatever_its_tag():
    _write_log("FR-0100", "dev", _standard_log())
    _lock("FR-0100", "dev")
    dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    [rec] = _records()
    tags = [f["tag"] for f in rec["findings"]]
    assert tags == ["slice-miss", "spec", ""]
    spec_finding = rec["findings"][1]
    assert spec_finding["refs"] == ["FR-0100"] and spec_finding["chars"] > 40
    assert rec["findings"][2]["refs"] == ["docs/architecture/overview.md"]
    assert "retain" not in json.dumps(rec) and "archive" not in json.dumps(rec)


# ---------------------------------------------------------------------------
# AC-5: PR events
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.org", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _pr_repo(tmp_path: Path) -> Path:
    """main: one test with one @covers. claude/dev-FR-0100: adds src/x.py,
    rewrites the test to +2/-1 @covers lines, adds a second test file."""
    repo = tmp_path / "gitrepo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text(f"# {_COVERS} FR-0100:AC-1\ndef test_a():\n    pass\n", encoding="utf-8")
    (repo / "README.md").write_text("synthetic\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "claude/dev-FR-0100")
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("# @implements FR-0100\n", encoding="utf-8")
    (repo / "tests" / "test_a.py").write_text(
        f"# {_COVERS} FR-0100:AC-2\ndef test_a():\n    pass\n\n# {_COVERS} FR-0100:AC-3\ndef test_b():\n    pass\n", encoding="utf-8"
    )
    (repo / "tests" / "test_c.py").write_text(f"# {_COVERS} FR-0100:AC-4\ndef test_c():\n    pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat(FR-0100): work")
    _git(repo, "checkout", "-q", "main")
    return repo


# covers hub-tooling FR-0002:AC-5
def test_pr_opened_carries_change_size_fields_from_the_branch_diff(monkeypatch, tmp_path):
    repo = _pr_repo(tmp_path)
    monkeypatch.setattr(dispatch, "REPO_ROOT", repo)
    dispatch._RUN_REGISTRY[("FR-0100", "dev")] = {"run_id": "d" * 32, "started_at": 1.0, "round": 1}
    record = {"pr_number": 42, "pr_url": "https://github.com/example-org/synthetic-project/pull/42", "draft": True, "head_sha": "a" * 40}
    dispatch._emit_pr_event("pr.opened", "FR-0100", "dev", record, "claude/dev-FR-0100")
    [rec] = _records()
    assert rec["kind"] == "pr.opened" and rec["role"] == "dev" and rec["object_ids"] == ["FR-0100"] and rec["run_id"] == "d" * 32
    assert rec["pr_number"] == 42 and rec["pr_url"].endswith("/pull/42") and rec["draft"] is True and rec["head_sha"] == "a" * 40
    assert rec["commits_ahead"] == 1
    assert rec["files_touched"] == 3 and rec["files_touched_paths"] == ["src/x.py", "tests/test_a.py", "tests/test_c.py"]
    assert rec["tests_changed"] == 2
    assert rec["covers_delta"] == 3 - 1  # +AC-2 +AC-3 +AC-4, -AC-1
    assert rec["gate_record_id"] is None  # no preflight gate ran in this process
    assert "feat(FR-0100)" not in json.dumps(rec)  # no commit message


# covers hub-tooling FR-0002:AC-5
def test_pr_refreshed_cites_the_preflight_gate_record_and_a_missing_branch_degrades_to_zeroes(monkeypatch, tmp_path):
    repo = _pr_repo(tmp_path)
    monkeypatch.setattr(dispatch, "REPO_ROOT", repo)
    env = dispatch._gate_metrics_env("FR-0100", "dev")
    assert env["METRICS_INVOKED_BY"] == "dispatch-finalize" and re.fullmatch(r"[0-9a-f]{32}", env["METRICS_GATE_RECORD_ID"])
    assert "DISPATCH_RUN_ID" not in env  # no run context for this (fr, role) yet
    record = {"pr_number": 42, "pr_url": "https://github.com/example-org/synthetic-project/pull/42", "draft": False, "head_sha": None}
    dispatch._emit_pr_event("pr.refreshed", "FR-0100", "dev", record, "claude/dev-FR-0100")
    dispatch._emit_pr_event("pr.opened", "FR-0100", "bkf", record, "claude/bkf-FR-0100")  # branch does not exist
    refreshed, missing = _records()
    assert refreshed["kind"] == "pr.refreshed" and refreshed["gate_record_id"] == env["METRICS_GATE_RECORD_ID"]
    assert refreshed["draft"] is False and refreshed["head_sha"] is None and refreshed["run_id"] is None
    assert missing["role"] == "bkf" and missing["commits_ahead"] is None and missing["files_touched"] == 0
    assert missing["files_touched_paths"] == [] and missing["tests_changed"] == 0 and missing["covers_delta"] == 0


# covers hub-tooling FR-0002:AC-5
def test_gate_metrics_env_joins_the_agents_run_id_when_known(monkeypatch, tmp_path):
    _lock("FR-0100", "dev", run_id="j" * 32)
    env = dispatch._gate_metrics_env("FR-0100", "dev")
    assert env["DISPATCH_RUN_ID"] == "j" * 32
    assert dispatch._PREFLIGHT_GATE_RECORD_IDS[("FR-0100", "dev")] == env["METRICS_GATE_RECORD_ID"]


# covers hub-tooling FR-0002:AC-5
@pytest.mark.parametrize(
    "final_text, gh_rc, gh_stderr, verdict, posted_as",
    [
        ("## Review\n\n## APPROVE\n\nall good", 0, "", "approve", "approve"),
        ("**Request changes**\n\nAC-2 uncovered", 0, "", "request-changes", "request-changes"),
        ("## APPROVE", 1, "Can not approve your own pull request", "approve", "comment (intended approve)"),
    ],
)
def test_reviewer_finalize_emits_pr_review_with_verdict_posted_as_and_round(monkeypatch, tmp_path, capsys, final_text, gh_rc, gh_stderr, verdict, posted_as):
    dispatch._save_pr_record("FR-0100", "dev", {"pr_number": 42, "pr_url": "https://github.com/example-org/synthetic-project/pull/42"})
    _write_log("FR-0100", "rev", _standard_log(final_text=final_text))
    _lock("FR-0100", "rev", run_id="e" * 32, round_num=2)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        # DEC-0010 / FR-0013 AC-11: `git show-ref` precedes `gh pr review`; non-`gh` argv gets a neutral success.
        if not cmd or cmd[0] != "gh":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        # First gh call fails with the own-PR message when asked; every later gh call (the --comment retry) succeeds.
        rc = gh_rc if sum(1 for c in calls if c and c[0] == "gh") == 1 else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr=gh_stderr if rc else "")

    monkeypatch.setattr(dispatch, "subprocess", SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired,
                                                              CalledProcessError=subprocess.CalledProcessError, PIPE=subprocess.PIPE))
    rc = dispatch._finalize_rev("FR-0100", "claude/rev-FR-0100", "b" * 40, "example-org/synthetic-project", dispatch.ClaudeCodeAdapter())
    assert rc == 0, capsys.readouterr()
    # DEC-0010 / FR-0013 AC-11: a `gh pr review` was issued, located by argv rather than assumed to be calls[0].
    assert any(c[:3] == ["gh", "pr", "review"] for c in calls)
    [rec] = _records()
    assert rec["kind"] == "pr.review" and rec["role"] == "rev" and rec["object_ids"] == ["FR-0100"] and rec["run_id"] == "e" * 32
    assert rec["parent_pr_number"] == 42 and rec["verdict"] == verdict and rec["posted_as"] == posted_as and rec["round"] == 2
    assert final_text.splitlines()[-1] not in json.dumps(rec) or final_text.splitlines()[-1] in ("## APPROVE",)
    assert "REVIEW-POSTED" in capsys.readouterr().out


# covers hub-tooling FR-0002:AC-5
def test_reviewer_finalize_that_fails_at_gh_emits_nothing(monkeypatch, tmp_path, capsys):
    dispatch._save_pr_record("FR-0100", "dev", {"pr_number": 42})
    _write_log("FR-0100", "rev", _standard_log(final_text="## APPROVE"))
    fake = SimpleNamespace(run=lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="gh: network down"),
                           TimeoutExpired=subprocess.TimeoutExpired)
    monkeypatch.setattr(dispatch, "subprocess", fake)
    assert dispatch._finalize_rev("FR-0100", "claude/rev-FR-0100", None, "example-org/synthetic-project", dispatch.ClaudeCodeAdapter()) == 1
    assert _records() == []


# covers hub-tooling FR-0002:AC-5
def test_reconcile_emits_pr_merged_only_when_the_flip_is_applied_and_committed(monkeypatch, tmp_path):
    (tmp_path / "specs" / "FR-0100-synthetic.md").write_text(
        "---\nid: FR-0100\ntitle: Synthetic\nstatus: in-review\nowner: architect\ndepends_on: []\n---\n\n# FR-0100\n", encoding="utf-8"
    )
    rows = [{"headRefName": "claude/dev-FR-0100", "number": 42, "mergedAt": "2026-09-01T00:00:00Z", "mergeCommit": {"oid": "c" * 40}}]
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose: (True, None))
    monkeypatch.setattr(dispatch, "_gh_merged_prs", lambda limit=100: rows)
    monkeypatch.setattr(dispatch, "_on_default_branch", lambda branch="main": True)
    monkeypatch.setattr(dispatch, "_git_branch_exists", lambda branch: False)
    flips: list[tuple] = []
    monkeypatch.setattr(dispatch, "_flip_frontmatter_to_merged", lambda path, prev, num, sha: flips.append((prev, num, sha)) or True)
    monkeypatch.setattr(dispatch, "_commit_spec_flip", lambda fr, num, sha: (True, "committed"))
    # Dry run: WOULD flip, nothing emitted.
    summary = dispatch.reconcile_merged_prs(apply=False, verbose=False)
    assert summary.flipped == ["FR-0100"] and _records() == [] and flips == []
    # Apply: flip + commit -> one pr.merged.
    summary = dispatch.reconcile_merged_prs(apply=True, verbose=False)
    assert summary.flipped == ["FR-0100"] and flips == [("in-review", 42, "c" * 40)]
    [rec] = _records()
    assert rec["kind"] == "pr.merged" and rec["role"] == "dev" and rec["object_ids"] == ["FR-0100"] and rec["run_id"] is None
    assert rec["pr_number"] == 42 and rec["merge_sha"] == "c" * 40
    # Commit failure: flipped on disk but not committed -> no record.
    monkeypatch.setattr(dispatch, "_commit_spec_flip", lambda fr, num, sha: (False, "git commit failed"))
    dispatch.reconcile_merged_prs(apply=True, verbose=False)
    assert len(_records()) == 1


# ---------------------------------------------------------------------------
# Control-plane invariants this FR must not disturb
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-3
def test_role_permissions_and_finding_line_are_unchanged_against_the_pinned_baseline(tmp_path):
    baseline = _git_show_baseline("template/scripts/dispatch.py")
    if baseline is None:
        pytest.skip(f"baseline commit {_PRE_FR0002_REF} not reachable (not running inside the hub checkout)")
    path = tmp_path / "dispatch_baseline.py"
    path.write_bytes(baseline)
    old = _load_dispatch("dispatch_baseline_fr0002", path)
    for adapter in ("ClaudeCodeAdapter", "CursorAdapter"):
        assert getattr(dispatch, adapter).ROLE_PERMISSIONS == getattr(old, adapter).ROLE_PERMISSIONS, adapter
    assert dispatch.ROLE_MODEL == old.ROLE_MODEL
    assert dispatch._FINDING_LINE.pattern == old._FINDING_LINE.pattern.replace("scope|spec|doc", "scope|spec|doc|slice-miss")
    assert dispatch._FINDINGS_MARKER.pattern == old._FINDINGS_MARKER.pattern
    assert dispatch._ESCALATION_MARKER.pattern == old._ESCALATION_MARKER.pattern
    sample = "## FINDINGS\n- [scope] a\n- [spec] b\n- [doc] c\n- [zzz] d\n- e\n- (none)\n"
    assert dispatch._parse_findings(sample) == old._parse_findings(sample)


# covers hub-tooling FR-0002:AC-9
def test_metrics_failure_inside_dispatch_never_changes_the_outcome(monkeypatch, tmp_path, capsys):
    _write_log("FR-0100", "dev", _standard_log())
    _lock("FR-0100", "dev")

    def boom(*a, **k):
        raise RuntimeError("metrics exploded")

    with monkeypatch.context() as mp:
        mp.setattr(metrics_log, "emit", boom)
        outcome = dispatch._evaluate_agent_outcome("FR-0100", "dev", dispatch.ClaudeCodeAdapter())
    assert outcome.status == "success" and len(outcome.findings) == 3
    err = capsys.readouterr().err
    assert err.count("WARN: metrics:") == 1 and "metrics exploded" in err
    # The wave and spawn paths call metrics_log.emit directly (contract: never
    # raises); exercise them against an unwritable log instead.
    blocked = tmp_path / "blocked-by-file"
    blocked.write_text("squatter", encoding="utf-8")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", blocked)
    path = dispatch._write_wave_synthesis(_wave_results(), "2026-09-07T00:00:00+00:00", 1.0, emit_record=True)
    assert path.exists()
    assert capsys.readouterr().err.count("WARN: metrics:") == 1
    _stub_worktree(monkeypatch, tmp_path)
    assert dispatch.spawn_role("FR-0101", "dev", apply=True, adapter=_FakeAdapter())[0] == "spawned"
    assert capsys.readouterr().err.count("WARN: metrics:") == 1
    assert blocked.read_text(encoding="utf-8") == "squatter"
