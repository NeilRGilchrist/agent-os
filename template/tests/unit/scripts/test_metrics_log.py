"""Reviewer tests for FR-0002 — pipeline instrumentation, append-only
per-project metrics log (H6).

Covers the shared module `scripts/metrics_log.py` directly (record envelope,
kind-specific and reserved fields, forward compatibility, the privacy rules,
append-only semantics and month files, the never-load-bearing `emit`, the
query surface and named reports, the per-FR INDEX.md section) plus the two
CLI emitters that are simplest to drive end-to-end through `subprocess`:
`escalation-log.py` (AC-6) and the `metrics_log.py` CLI itself (AC-8, AC-10,
AC-11, AC-14). `deploy-gate.py` emission lives in `test_deploy_gate_metrics.py`
and `dispatch.py` emission in `test_dispatch_metrics.py`.

`metrics_log` is imported by name (pytest.ini puts `scripts/` on `sys.path`).
Every test is isolated from the template's live `specs/_metrics/` by the
autouse fixture below, which repoints the module's default directory at a
temp path — nothing here can ever append to a real log.

Coverage annotations are written `# covers hub-tooling FR-0002:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0002 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (see test_index_specs_versioning.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

# Convention: backward-compat baselines pin a commit, never a branch name.
# `main:` only means "the code before this FR" while the FR lives on a feature
# branch; once merged, `main:` IS the code under test and every "identical to
# baseline" assertion turns into a tautology. Pinning a commit keeps the
# comparison meaningful forever. Outside the hub checkout (bootstrapped
# projects, shallow clones) the commit is unreachable and the tests skip.

from __future__ import annotations

import contextlib
import copy
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# once bootstrapped).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_METRICS_README = _TEMPLATE_DIR / "specs" / "_metrics" / "README.md"
_REPORTS_DIR = _TEMPLATE_DIR / "specs" / "_metrics" / "reports"
_FIXTURE = _TEMPLATE_DIR / "tests" / "fixtures" / "metrics" / "2026-08.ndjson"
_GITATTRIBUTES = _TEMPLATE_DIR / ".gitattributes"
_MATRIX = _TEMPLATE_DIR / ".agent-team" / "escalation-matrix.md"

# Hub `main` immediately before FR-0002 (the FR-0005 test-baseline retarget
# merge). `escalation-log.py resolve` was broken there (AC-6 fix anchor).
_PRE_FR0002_REF = "c49a893"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log  # sibling module, importable by name

# The compliance profile's hook, verbatim in shape: three synthetic-pattern
# regexes. Tests that need "a profile is active" write this file into a temp
# `.agent-team/hooks/phi_regex_check.py` and point the module at it.
_PHI_HOOK_SOURCE = '''
PHI_PATTERNS = [
    (r"\\b\\d{3}[-\\s]\\d{3}[-\\s]\\d{3}\\b", "Possible Canadian SIN (XXX-XXX-XXX)"),
    (r"\\b\\d{4}[-\\s]\\d{3}[-\\s]\\d{3}(?:[-\\s][A-Z]{2})?\\b", "Possible Ontario HCN (XXXX-XXX-XXX [VV])"),
    (r"\\b\\d{3}-\\d{2}-\\d{4}\\b", "Possible US SSN (XXX-XX-XXXX)"),
]
'''


def _git_show_baseline(rel: str, ref: str = _PRE_FR0002_REF) -> bytes | None:
    """`<hub>/<ref>:<rel>` as bytes, or None when the pinned commit is not
    reachable (bootstrapped projects and shallow clones have no hub history)."""
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
    """No test may touch the template's live log or read the checkout's
    compliance hook; the project name is fixed so `git rev-parse` is never
    consulted."""
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "isolated_metrics")
    monkeypatch.setattr(metrics_log, "PHI_HOOK_PATH", tmp_path / "no-such-hook.py")
    monkeypatch.setattr(metrics_log, "_PHI_PATTERNS", None)
    monkeypatch.setattr(metrics_log, "_PHI_PATH_LOADED", None)
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)


# ---------------------------------------------------------------------------
# Record factory — one valid record per kind, overridable
# ---------------------------------------------------------------------------

_KIND_DEFAULTS: dict[str, dict] = {
    "dispatch.spawn": {
        "source": "dispatch", "role": "dev",
        "harness": "claude-code", "worktree_status": "created", "base_branch": "main", "model": None, "round": 1,
    },
    "dispatch.run": {
        "source": "dispatch", "role": "dev",
        "status": "success", "tool_calls_total": 3, "tool_calls_by_tool": {"Read": 2, "Bash": 1},
        "tool_errors_total": 1, "tool_errors_by_tool": {"Bash": 1}, "tokens_in": 1000, "tokens_out": 50,
        "duration_s": 12.5, "round": 1, "verdict": None, "findings": [],
    },
    "dispatch.wave": {
        "source": "dispatch", "role": "orchestrator",
        "fr_count": 1, "completed": 1, "dev_only": 0, "dropped": 0, "drop_reasons": [],
        "rounds_ran": {"FR-0100": 1}, "force_escalated": [],
    },
    "gate.run": {
        "source": "gate", "role": None,
        "stage": "full", "outcome": "pass", "failure_classes": [], "warning_classes": [],
        "counts": {"frs": 1, "covers": 2, "implements": 0}, "invoked_by": "manual",
    },
    "pr.opened": {
        "source": "dispatch", "role": "dev",
        "pr_number": 42, "pr_url": "https://github.com/example-org/synthetic-project/pull/42", "draft": True,
        "head_sha": "a" * 40, "commits_ahead": 1, "files_touched": 1, "files_touched_paths": ["src/x.py"],
        "tests_changed": 0, "covers_delta": 0, "gate_record_id": None,
    },
    "pr.refreshed": {
        "source": "dispatch", "role": "dev",
        "pr_number": 42, "pr_url": "https://github.com/example-org/synthetic-project/pull/42", "draft": True,
        "head_sha": "a" * 40, "commits_ahead": 2, "files_touched": 1, "files_touched_paths": ["src/x.py"],
        "tests_changed": 0, "covers_delta": 0, "gate_record_id": None,
    },
    "pr.review": {
        "source": "dispatch", "role": "rev",
        "parent_pr_number": 42, "verdict": "approve", "posted_as": "approve", "round": 1,
    },
    "pr.merged": {"source": "dispatch", "role": "dev", "pr_number": 42, "merge_sha": "b" * 40},
    # FR-0008 AC-11 / DEC-0012 item 2(d): the declared-gate verdict record.
    "gate.decision": {
        "source": "dispatch", "role": "gat",
        "gate": "design-review", "after": "dev", "reviewer": "architect",
        "verdict": "pass", "by": "architect", "round": 1, "head_sha": "a" * 39 + "1",
    },
    "escalation": {"source": "escalation-log", "role": "dev", "trigger_class": "spec-is-ambiguous"},
    "escalation.resolved": {"source": "escalation-log", "role": "dev", "trigger_class": "spec-is-ambiguous"},
}


def _rec(kind: str = "gate.run", **over) -> dict:
    rec = {
        "schema_version": 1,
        "record_id": "f" + "0" * 31,
        "ts": "2026-08-03T09:00:00Z",
        "project": "synthetic-project",
        "kind": kind,
        "source": "gate",
        "role": None,
        "object_ids": ["FR-0100"],
        "run_id": None,
    }
    rec.update(copy.deepcopy(_KIND_DEFAULTS.get(kind, _KIND_DEFAULTS["gate.run"])))
    rec.update(over)
    return rec


def _lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _fixture_dir(tmp_path: Path) -> Path:
    """The shipped fixture plus the shipped report definitions, as one
    metrics dir (README: `report` looks for `reports/` under the metrics dir)."""
    d = tmp_path / "metrics"
    d.mkdir()
    shutil.copy(_FIXTURE, d / _FIXTURE.name)
    shutil.copytree(_REPORTS_DIR, d / "reports")
    return d


def _cli(*args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "METRICS_PROJECT": "synthetic-project"}
    full_env.pop("METRICS_LOG_DISABLED", None)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "metrics_log.py"), *args],
        capture_output=True, check=False, text=True, encoding="utf-8", cwd=str(cwd) if cwd else None, env=full_env,
    )


# ---------------------------------------------------------------------------
# AC-1: record envelope and minimum field set
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-1
def test_every_kind_default_record_validates_and_carries_the_full_envelope():
    assert set(metrics_log.ENVELOPE_FIELDS) == {
        "schema_version", "record_id", "ts", "project", "kind", "source", "role", "object_ids", "run_id",
    }
    assert metrics_log.SCHEMA_VERSION == 1
    for kind in metrics_log.KINDS:
        rec = _rec(kind)
        assert metrics_log.validation_errors(rec) == [], kind
        metrics_log.validate(rec)  # does not raise
        assert all(f in rec for f in metrics_log.ENVELOPE_FIELDS)


# covers hub-tooling FR-0002:AC-1
def test_kinds_and_sources_and_roles_are_exactly_the_spec_enums():
    # "gate.decision" and the "gat" role are FR-0008 AC-11's authorised
    # additions (DEC-0012 item 2(d)); the sets stay literal and exhaustive.
    assert metrics_log.KINDS == {
        "dispatch.spawn", "dispatch.run", "dispatch.wave", "gate.run",
        "pr.opened", "pr.refreshed", "pr.review", "pr.merged", "escalation", "escalation.resolved",
        "gate.decision",
    }
    assert metrics_log.SOURCES == {"dispatch", "gate", "escalation-log", "manual"}
    assert metrics_log.ROLES == {"architect", "dev", "rev", "bkf", "mnt", "docs", "orchestrator", "gat"}


# covers hub-tooling FR-0002:AC-1
@pytest.mark.parametrize("field", metrics_log.ENVELOPE_FIELDS)
def test_missing_envelope_field_is_rejected(field):
    rec = _rec()
    del rec[field]
    errors = metrics_log.validation_errors(rec)
    assert errors and field in errors[0]
    with pytest.raises(metrics_log.MetricsError):
        metrics_log.validate(rec)


# covers hub-tooling FR-0002:AC-1
@pytest.mark.parametrize(
    "over",
    [
        {"kind": "dispatch.unknown"},
        {"source": "cron"},
        {"role": "developer"},           # free-text label, not the enum
        {"schema_version": "1"},
        {"schema_version": True},
        {"record_id": ""},
        {"ts": "yesterday"},
        {"project": ""},
        {"object_ids": "FR-0100"},        # must be a list
        {"object_ids": [1]},
        {"run_id": 7},
    ],
)
def test_bad_envelope_values_are_rejected(over):
    assert metrics_log.validation_errors(_rec(**over)), over


# covers hub-tooling FR-0002:AC-1
def test_role_null_and_run_id_null_are_legal_envelope_values():
    assert metrics_log.validation_errors(_rec(role=None, run_id=None)) == []
    assert metrics_log.validation_errors(_rec("dispatch.run", run_id="ab" * 16)) == []


# covers hub-tooling FR-0002:AC-1
@pytest.mark.parametrize("kind", sorted(metrics_log.KINDS))
def test_each_kind_specific_required_field_is_enforced(kind):
    required = metrics_log.KIND_REQUIRED[kind]
    assert required, f"{kind} declares no kind-specific fields"
    for field in required:
        rec = _rec(kind)
        del rec[field]
        errors = metrics_log.validation_errors(rec)
        assert any(field in e and kind in e for e in errors), (kind, field, errors)


# covers hub-tooling FR-0002:AC-1
def test_kind_specific_enums_are_enforced():
    assert metrics_log.validation_errors(_rec("dispatch.run", status="crashed"))
    assert metrics_log.validation_errors(_rec("gate.run", outcome="green"))
    assert metrics_log.validation_errors(_rec("gate.run", failure_classes=["flaky-test"]))
    assert metrics_log.validation_errors(_rec("gate.run", warning_classes=["lint"]))
    assert metrics_log.validation_errors(_rec("gate.run", invoked_by="cron"))
    assert metrics_log.validation_errors(_rec("gate.run", failure_classes="spec-validation"))
    assert metrics_log.validation_errors(_rec("dispatch.run", findings=[{"tag": "bogus", "refs": [], "chars": 1}]))
    assert metrics_log.validation_errors(_rec("dispatch.run", findings=[{"tag": "spec", "text": "prose"}]))
    assert metrics_log.validation_errors(_rec("dispatch.run", findings="none"))
    for status in ("success", "error", "escalation", "timeout", "no-log"):
        assert metrics_log.validation_errors(_rec("dispatch.run", status=status)) == []


# covers hub-tooling FR-0002:AC-1
def test_unknown_string_free_fields_are_accepted_for_forward_compatibility():
    rec = _rec("dispatch.run", future_counter=12, future_flag=True, future_nested={"a": [1, 2.5, None]})
    assert metrics_log.validation_errors(rec) == []


# covers hub-tooling FR-0002:AC-1
def test_non_object_record_is_rejected():
    assert metrics_log.validation_errors(["not", "a", "record"]) == ["record is not a JSON object"]
    assert metrics_log.validation_errors(None)


# ---------------------------------------------------------------------------
# AC-2: reserved optional fields
# ---------------------------------------------------------------------------

_RESERVED_VALUES = {
    "dec_id": "DEC-0007",
    "tr_id": "TR-0003",
    "tier": "2",
    "ratification_outcome": "ratified",
    "revision_event": "supersession",
    "breaking_declared": True,
    "breaking_observed": False,
    "dec_proposed_at": "2026-08-01T00:00:00Z",
    "dec_ratified_at": "2026-08-02T00:00:00Z",
    "slice_id": "slice-0001",
}


# covers hub-tooling FR-0002:AC-2
def test_reserved_field_list_is_exactly_the_spec_list():
    assert set(metrics_log.RESERVED_FIELDS) == set(_RESERVED_VALUES)


# covers hub-tooling FR-0002:AC-2
def test_record_with_no_reserved_fields_validates():
    rec = _rec("dispatch.run")
    assert not any(f in rec for f in metrics_log.RESERVED_FIELDS)
    assert metrics_log.validation_errors(rec) == []


# covers hub-tooling FR-0002:AC-2
@pytest.mark.parametrize("field", sorted(_RESERVED_VALUES))
def test_each_reserved_field_alone_validates_set_or_null(field):
    assert metrics_log.validation_errors(_rec("dispatch.run", **{field: _RESERVED_VALUES[field]})) == []
    assert metrics_log.validation_errors(_rec("dispatch.run", **{field: None})) == []


# covers hub-tooling FR-0002:AC-2
def test_all_reserved_fields_together_round_trip_byte_for_byte(tmp_path):
    rec = _rec("dispatch.run", **_RESERVED_VALUES)
    path = metrics_log.append(rec, tmp_path / "m")
    raw = path.read_text(encoding="utf-8")
    assert raw == json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    [back] = metrics_log.read_records(tmp_path / "m")
    assert back == rec
    [queried] = metrics_log.filter_records(metrics_log.attach_fr_context([back]), fr="FR-0100")
    queried.pop("fr")
    assert queried == rec


# covers hub-tooling FR-0002:AC-2
def test_reserved_enums_and_booleans_are_type_checked():
    assert metrics_log.validation_errors(_rec(ratification_outcome="maybe"))
    assert metrics_log.validation_errors(_rec(revision_event="rewrite"))
    assert metrics_log.validation_errors(_rec(breaking_declared="yes"))
    assert metrics_log.validation_errors(_rec(breaking_observed=1))


# ---------------------------------------------------------------------------
# AC-7: spec_refs — identifiers and paths out of a finding, never the text
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-7
def test_spec_refs_extracts_ids_and_repo_paths_from_the_ac_example():
    text = "needed specs/FR-0009-extraction-agent.md to satisfy AC-3"
    refs = metrics_log.spec_refs(text)
    assert "FR-0009" in refs and "specs/FR-0009-extraction-agent.md" in refs
    assert not any("needed" in r or "satisfy" in r for r in refs)
    assert refs[0] == "FR-0009"  # IDs first


# covers hub-tooling FR-0002:AC-7
def test_spec_refs_handles_every_id_family_urls_and_punctuation():
    text = (
        "TR-0002 and DEC-0011 revise ADR-0001 (see GOAL-extraction-v2); "
        "read docs/_spec/overview.yaml, `scripts/index-specs.py`. "
        "Not https://example.org/a/b/c or /etc/passwd"
    )
    refs = metrics_log.spec_refs(text)
    for want in ("TR-0002", "DEC-0011", "ADR-0001", "GOAL-extraction-v2", "docs/_spec/overview.yaml", "scripts/index-specs.py"):
        assert want in refs, want
    assert not any(r.startswith("/") or "://" in r or "example.org" in r for r in refs)
    assert metrics_log.spec_refs("plain prose without a single reference") == []


# ---------------------------------------------------------------------------
# AC-8: append-only semantics and location
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-8
def test_append_creates_dir_and_month_file_from_utc_month_of_ts(tmp_path):
    d = tmp_path / "nested" / "_metrics"
    assert not d.exists()
    p = metrics_log.append(_rec(ts="2026-08-31T23:59:59Z"), d)
    assert p == d / "2026-08.ndjson" and p.is_file()
    # A local-offset timestamp lands in its UTC month, not its wall-clock month.
    p2 = metrics_log.append(_rec(ts="2026-09-01T01:30:00+02:00"), d)
    assert p2 == d / "2026-08.ndjson"
    p3 = metrics_log.append(_rec(ts="2026-09-01T00:00:00Z"), d)
    assert p3 == d / "2026-09.ndjson"
    assert sorted(x.name for x in d.glob("*.ndjson")) == ["2026-08.ndjson", "2026-09.ndjson"]


# covers hub-tooling FR-0002:AC-8
def test_append_is_one_line_per_record_and_bytes_before_are_a_prefix_of_bytes_after(tmp_path):
    d = tmp_path / "m"
    metrics_log.append(_rec(record_id="1" * 32), d)
    before = (d / "2026-08.ndjson").read_bytes()
    metrics_log.append(_rec(record_id="2" * 32, object_ids=["FR-0101"]), d)
    after = (d / "2026-08.ndjson").read_bytes()
    assert after.startswith(before) and after != before
    assert after.endswith(b"\n") and b"\r" not in after
    recs = _lines(d / "2026-08.ndjson")
    assert [r["record_id"] for r in recs] == ["1" * 32, "2" * 32]


# covers hub-tooling FR-0002:AC-8
def test_append_rejects_invalid_records_without_creating_the_file(tmp_path):
    d = tmp_path / "m"
    with pytest.raises(metrics_log.MetricsError):
        metrics_log.append(_rec(kind="nope"), d)
    assert not d.exists()


# covers hub-tooling FR-0002:AC-8
def test_two_alternating_writers_in_separate_processes_keep_every_line_whole(tmp_path):
    """Two processes append to the same month file turn by turn (the branch-
    merge shape `merge=union` is for); every line parses and the file only
    ever grows."""
    d = tmp_path / "m"
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]); import metrics_log as m; from pathlib import Path\n"
        "m.append(json.loads(sys.argv[3]), Path(sys.argv[2]))\n"
    )
    snapshots: list[bytes] = []
    for i in range(6):
        rec = _rec(record_id=f"{i:032x}", run_id=f"writer-{i % 2}")
        proc = subprocess.run(
            [sys.executable, "-c", code, str(_SCRIPTS_DIR), str(d), json.dumps(rec)],
            capture_output=True, check=False, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        snapshots.append((d / "2026-08.ndjson").read_bytes())
    for earlier, later in itertools.pairwise(snapshots):
        assert later.startswith(earlier)
    assert [r["record_id"] for r in _lines(d / "2026-08.ndjson")] == [f"{i:032x}" for i in range(6)]


# covers hub-tooling FR-0002:AC-8
def test_two_concurrent_writers_lose_no_record_and_leave_every_line_parseable(tmp_path):
    """The AC's literal scenario: two writers appending concurrently to the
    same file. Every line must still parse as a complete record and no record
    may be lost. Exercises the platform's append semantics for real (Python's
    `open(..., "a")` is atomic per write on POSIX O_APPEND; on Windows the CRT
    seeks then writes, so the emitter needs its own guard)."""
    d = tmp_path / "m"
    n = 150
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]); import metrics_log as m; from pathlib import Path\n"
        "d = Path(sys.argv[2]); tag = sys.argv[3]; n = int(sys.argv[4])\n"
        "for i in range(n):\n"
        "    rec = m.make_record('gate.run', source='gate', object_ids=[], run_id=tag, ts='2026-08-01T00:00:00Z',\n"
        "        project='synthetic-project', record_id=f'{tag}{i:031d}'[:32], stage='dev', outcome='pass',\n"
        "        failure_classes=[], warning_classes=[], counts={'frs': i, 'covers': 0, 'implements': 0}, invoked_by='manual')\n"
        "    m.append(rec, d)\n"
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", code, str(_SCRIPTS_DIR), str(d), tag, str(n)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for tag in ("a", "b")
    ]
    for p in procs:
        _, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
    raw = (d / "2026-08.ndjson").read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.decode("utf-8", errors="replace").splitlines()
    parsed = []
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except json.JSONDecodeError:
            pytest.fail(f"corrupted line after concurrent append: {ln[:80]!r}")
    assert len(parsed) == 2 * n, f"{2 * n - len(parsed)} record(s) lost to concurrent append"
    assert len({r["record_id"] for r in parsed}) == 2 * n


_HOLDER_CODE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import metrics_log as m; from pathlib import Path\n"
    "p = Path(sys.argv[2]); p.parent.mkdir(parents=True, exist_ok=True)\n"
    "with p.open('a', encoding='utf-8', newline='\\n') as fh:\n"
    "    m._lock(fh.fileno()); print('locked', flush=True); sys.stdin.readline(); m._unlock(fh.fileno())\n"
)


@contextlib.contextmanager
def _lock_held_by_another_process(month: Path):
    """A second interpreter takes `append()`'s own lock on `month` and holds
    it until the block exits — the real cross-process shape, not a thread."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER_CODE, str(_SCRIPTS_DIR), str(month)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked", proc.stderr.read()
        yield
    finally:
        try:
            proc.stdin.write("\n")
            proc.stdin.flush()
        except OSError:
            pass
        proc.wait(timeout=30)


def _gate_fields() -> dict:
    """`_rec("gate.run")` minus the envelope `emit()` builds itself (keeps `ts`
    so the record lands in the 2026-08 month file the tests lock)."""
    fields = _rec("gate.run")
    for k in metrics_log.ENVELOPE_FIELDS:
        if k != "ts":
            fields.pop(k, None)
    return fields


# covers hub-tooling FR-0002:AC-8
def test_reader_is_neither_blocked_nor_skipped_while_another_process_holds_the_append_lock(tmp_path):
    """The lock must serialise writers only. `iter_records` swallows OSError
    per file, so a lock covering any readable byte would silently drop the
    whole month from every query instead of failing loudly — check raw bytes,
    the library and the CLI all see the complete file while the lock is held."""
    d = tmp_path / "m"
    metrics_log.append(_rec(record_id="1" * 32), d)
    month = d / "2026-08.ndjson"
    before = month.read_bytes()
    with _lock_held_by_another_process(month):
        assert month.read_bytes() == before
        assert [r["record_id"] for r in metrics_log.iter_records(d)] == ["1" * 32]
        proc = _cli("--metrics-dir", str(d), "query")
        assert proc.returncode == 0 and proc.stderr == "", proc.stderr
        assert [json.loads(ln)["record_id"] for ln in proc.stdout.splitlines()] == ["1" * 32]
        if sys.platform == "win32":
            import msvcrt

            # Windows region locks are mandatory: prove the file's real bytes
            # are free and only the far-off guard byte is held (by the other
            # process), i.e. the 64-bit offset is used as intended.
            with month.open("a") as fh:
                fd = fh.fileno()
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                os.lseek(fd, metrics_log._LOCK_OFFSET, os.SEEK_SET)
                with pytest.raises(OSError):
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


# covers hub-tooling FR-0002:AC-8
# covers hub-tooling FR-0002:AC-9
def test_lock_held_past_the_deadline_is_one_warn_zero_bytes_and_the_caller_is_untouched(tmp_path, monkeypatch, capsys):
    """A writer that cannot take the lock within `LOCK_TIMEOUT_S` is just
    another emitter failure: exactly one WARN, None, nothing written, and the
    instrumented command's exit code and stdout unchanged. Disabled emission
    does not even wait."""
    d = tmp_path / "m"
    metrics_log.append(_rec(record_id="1" * 32), d)
    month = d / "2026-08.ndjson"
    before = month.read_bytes()
    monkeypatch.setattr(metrics_log, "LOCK_TIMEOUT_S", 0.3)
    with _lock_held_by_another_process(month):
        t0 = time.monotonic()
        assert metrics_log.emit("gate.run", source="gate", object_ids=["FR-0100"], metrics_dir=d, **_gate_fields()) is None
        assert 0.25 < time.monotonic() - t0 < 5
        err = capsys.readouterr().err
        assert err.count("WARN: metrics:") == 1 and err.count("\n") == 1 and "lock" in err, err
        assert month.read_bytes() == before and [p.name for p in d.iterdir()] == ["2026-08.ndjson"]

        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import metrics_log as m; from pathlib import Path\n"
            "m.LOCK_TIMEOUT_S = 0.3\n"
            "m.emit('gate.run', source='gate', object_ids=['FR-0100'], metrics_dir=Path(sys.argv[2]), ts='2026-08-03T09:00:00Z',\n"
            "    stage='full', outcome='pass', failure_classes=[], warning_classes=[],\n"
            "    counts={'frs': 1, 'covers': 2, 'implements': 0}, invoked_by='manual')\n"
            "print('gate stdout line')\n"
        )
        proc = subprocess.run([sys.executable, "-c", code, str(_SCRIPTS_DIR), str(d)], capture_output=True, check=False, text=True, timeout=60)
        assert proc.returncode == 0 and proc.stdout == "gate stdout line\n", (proc.returncode, proc.stdout)
        assert proc.stderr.count("WARN: metrics:") == 1 and proc.stderr.count("\n") == 1, proc.stderr
        assert month.read_bytes() == before

        monkeypatch.setenv("METRICS_LOG_DISABLED", "1")
        t0 = time.monotonic()
        assert metrics_log.emit("gate.run", source="gate", object_ids=["FR-0100"], metrics_dir=d, **_gate_fields()) is None
        assert time.monotonic() - t0 < 0.25 and capsys.readouterr().err == ""
        monkeypatch.delenv("METRICS_LOG_DISABLED")
    assert month.read_bytes() == before
    # The moment the holder lets go, the next append is immediate.
    t0 = time.monotonic()
    metrics_log.append(_rec(record_id="2" * 32), d)
    assert time.monotonic() - t0 < 1
    assert [r["record_id"] for r in _lines(month)] == ["1" * 32, "2" * 32]


# covers hub-tooling FR-0002:AC-8
def test_write_failure_under_the_lock_releases_it_and_leaves_no_partial_bytes(tmp_path, monkeypatch):
    """If the write itself fails while the lock is held, the lock is released
    on the way out (not leaked until process exit), nothing partial is left
    behind, and the next writer — in another process — does not wait."""
    d = tmp_path / "m"
    released: list[int] = []
    real_unlock = metrics_log._unlock

    def enospc(fd, data):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as mp:
        mp.setattr(metrics_log, "_unlock", lambda fd: (released.append(fd), real_unlock(fd)))
        mp.setattr(os, "write", enospc)
        with pytest.raises(metrics_log.MetricsError, match="No space left"):
            metrics_log.append(_rec(record_id="1" * 32), d)
    assert len(released) == 1
    month = d / "2026-08.ndjson"
    assert month.read_bytes() == b""
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]); import metrics_log as m; from pathlib import Path\n"
        "m.append(json.loads(sys.argv[3]), Path(sys.argv[2]))\n"
    )
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", code, str(_SCRIPTS_DIR), str(d), json.dumps(_rec(record_id="2" * 32))],
        capture_output=True, check=False, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert time.monotonic() - t0 < 5
    metrics_log.append(_rec(record_id="3" * 32), d)
    assert [r["record_id"] for r in _lines(month)] == ["2" * 32, "3" * 32]


# covers hub-tooling FR-0002:AC-8
def test_module_exposes_append_and_read_only_and_cli_has_no_mutating_subcommand_but_emit():
    public = [n for n in dir(metrics_log) if not n.startswith("_")]
    forbidden = re.compile(r"^(update|delete|remove|rewrite|truncate|compact|rotate|purge|edit|set_|replace)", re.IGNORECASE)
    assert not [n for n in public if forbidden.match(n)], public
    assert callable(metrics_log.append) and callable(metrics_log.iter_records) and callable(metrics_log.read_records)
    help_out = _cli("--help").stdout
    m = re.search(r"\{([a-z,]+)\}", help_out)
    assert m and set(m.group(1).split(",")) == {"query", "report", "validate", "emit"}
    source = (_SCRIPTS_DIR / "metrics_log.py").read_text(encoding="utf-8")
    # The only file-write in the module is the append-mode open in append().
    opens = re.findall(r"\.open\(\s*[\"'](\w+)[\"']", source)
    writes = [mode for mode in opens if any(c in mode for c in "wax+")]
    assert writes == ["a"], writes
    assert "write_text(" not in source and "write_bytes(" not in source and ".unlink(" not in source


# covers hub-tooling FR-0002:AC-8
def test_gitattributes_declares_union_merge_for_month_files_and_git_applies_it():
    text = _GITATTRIBUTES.read_text(encoding="utf-8")
    rules = [ln.split() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert ["specs/_metrics/*.ndjson", "merge=union"] in rules, rules
    # Ask git itself, from the template's own directory, what a month file
    # would get — the template is the root every bootstrapped project copies.
    hub = _TEMPLATE_DIR.parent
    probe = subprocess.run(["git", "-C", str(hub), "rev-parse", "--is-inside-work-tree"], capture_output=True, check=False, text=True)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        pytest.skip("template is not inside a git checkout")
    rel = _TEMPLATE_DIR.relative_to(hub).as_posix() if _TEMPLATE_DIR != hub else ""
    target = f"{rel}/specs/_metrics/2026-01.ndjson" if rel else "specs/_metrics/2026-01.ndjson"
    proc = subprocess.run(["git", "-C", str(hub), "check-attr", "merge", "--", target], capture_output=True, check=False, text=True)
    assert proc.returncode == 0 and proc.stdout.strip().endswith("merge: union"), proc.stdout
    other = f"{rel}/specs/_metrics/README.md" if rel else "specs/_metrics/README.md"
    proc2 = subprocess.run(["git", "-C", str(hub), "check-attr", "merge", "--", other], capture_output=True, check=False, text=True)
    assert proc2.stdout.strip().endswith("merge: unspecified"), proc2.stdout


# ---------------------------------------------------------------------------
# AC-9: emission is never load-bearing
# ---------------------------------------------------------------------------


def _emit_ok(**over) -> dict | None:
    fields = _rec("gate.run", **over)
    for k in metrics_log.ENVELOPE_FIELDS:
        fields.pop(k, None)
    return metrics_log.emit("gate.run", source="gate", object_ids=["FR-0100"], **fields)


# covers hub-tooling FR-0002:AC-9
def test_emit_writes_to_the_module_default_dir_and_returns_the_record(capsys):
    rec = _emit_ok()
    assert rec is not None and rec["kind"] == "gate.run" and rec["project"] == "synthetic-project"
    assert re.fullmatch(r"[0-9a-f]{32}", rec["record_id"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", rec["ts"])
    month = metrics_log.METRICS_DIR / f"{rec['ts'][:7]}.ndjson"
    assert _lines(month) == [rec]
    assert capsys.readouterr().err == ""


# covers hub-tooling FR-0002:AC-9
def test_emit_on_invalid_record_is_exactly_one_warn_line_and_none(capsys):
    result = metrics_log.emit("gate.run", source="gate", object_ids=["FR-0100"], stage="full")  # missing fields
    assert result is None
    err = capsys.readouterr().err
    assert err.count("WARN: metrics:") == 1 and err.strip().startswith("WARN: metrics:")
    assert not metrics_log.METRICS_DIR.exists()


# covers hub-tooling FR-0002:AC-9
def test_emit_on_unwritable_directory_is_exactly_one_warn_line_and_none(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    monkeypatch.setattr(metrics_log, "METRICS_DIR", blocker)
    assert _emit_ok() is None
    err = capsys.readouterr().err
    assert err.count("WARN: metrics:") == 1 and err.count("\n") == 1
    assert blocker.read_text(encoding="utf-8") == "a file where the directory should be"


# covers hub-tooling FR-0002:AC-9
def test_emit_never_raises_even_when_serialisation_or_disk_fail(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise OSError("disk on fire")

    with monkeypatch.context() as mp:
        mp.setattr(metrics_log, "append", boom)
        assert _emit_ok() is None
    assert capsys.readouterr().err.count("WARN: metrics:") == 1

    class Weird:  # not JSON-serialisable; validation passes (no strings), dumps fails
        pass

    assert _emit_ok(extra_obj=Weird()) is None
    assert capsys.readouterr().err.count("WARN: metrics:") == 1


# covers hub-tooling FR-0002:AC-9
@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_metrics_log_disabled_suppresses_all_emission_silently(monkeypatch, capsys, value):
    monkeypatch.setenv("METRICS_LOG_DISABLED", value)
    assert metrics_log.is_disabled()
    assert _emit_ok() is None
    assert not metrics_log.METRICS_DIR.exists()
    assert capsys.readouterr().err == ""


# covers hub-tooling FR-0002:AC-9
def test_metrics_log_disabled_falsy_values_do_not_disable(monkeypatch):
    for value in ("", "0", "false", "no"):
        monkeypatch.setenv("METRICS_LOG_DISABLED", value)
        assert not metrics_log.is_disabled(), value


# covers hub-tooling FR-0002:AC-9
def test_warn_is_the_only_stderr_surface_and_has_the_fixed_prefix(capsys):
    metrics_log.warn("something")
    out = capsys.readouterr()
    assert out.out == "" and out.err == "WARN: metrics: something\n"


# ---------------------------------------------------------------------------
# AC-10: query surface (library + CLI)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-10
def test_query_cli_filters_kind_fr_role_since_until_and_streams_ndjson(tmp_path):
    d = _fixture_dir(tmp_path)
    out = _cli("--metrics-dir", str(d), "query", "--kind", "dispatch.run", "--kind", "gate.run")
    assert out.returncode == 0, out.stderr
    recs = [json.loads(ln) for ln in out.stdout.splitlines()]
    assert len(recs) == 10 and {r["kind"] for r in recs} == {"dispatch.run", "gate.run"}
    assert all("fr" not in r for r in recs)  # the virtual field is never emitted
    out = _cli("--metrics-dir", str(d), "query", "--fr", "FR-0020", "--role", "rev", "--kind", "dispatch.run")
    recs = [json.loads(ln) for ln in out.stdout.splitlines()]
    assert [r["verdict"] for r in recs] == ["request-changes", "approve"]
    out = _cli("--metrics-dir", str(d), "query", "--since", "2026-08-03T11:00:00Z", "--until", "2026-08-03T11:31:00Z")
    recs = [json.loads(ln) for ln in out.stdout.splitlines()]
    assert [r["ts"] for r in recs] == ["2026-08-03T11:00:00Z", "2026-08-03T11:20:00Z", "2026-08-03T11:30:00Z"]
    assert _cli("--metrics-dir", str(d), "query", "--fr", "FR-9999").stdout == ""
    # A gate run that names no FR joins its FR through run_id.
    out = _cli("--metrics-dir", str(d), "query", "--fr", "FR-0020", "--kind", "gate.run")
    assert len(out.stdout.splitlines()) == 5


# covers hub-tooling FR-0002:AC-10
def test_query_cli_table_group_by_and_aggregations(tmp_path):
    d = _fixture_dir(tmp_path)
    out = _cli("--metrics-dir", str(d), "query", "--kind", "dispatch.run", "--table")
    assert out.returncode == 0 and out.stdout.startswith("ts ") and "dispatch.run" in out.stdout
    assert out.stdout.count("\n") == 2 + 5  # header, rule, five runs
    out = _cli(
        "--metrics-dir", str(d), "query", "--kind", "dispatch.run",
        "--group-by", "fr", "--group-by", "role",
        "--agg", "count", "--agg", "sum:tool_calls_total", "--agg", "avg:tool_calls_total", "--agg", "max:tokens_in",
    )
    rows = [json.loads(ln) for ln in out.stdout.splitlines()]
    assert rows == [
        {"fr": "FR-0020", "role": "architect", "count": 1, "sum_tool_calls_total": 25, "avg_tool_calls_total": 25, "max_tokens_in": 180000},
        {"fr": "FR-0020", "role": "dev", "count": 2, "sum_tool_calls_total": 93, "avg_tool_calls_total": 46.5, "max_tokens_in": 900000},
        {"fr": "FR-0020", "role": "rev", "count": 2, "sum_tool_calls_total": 32, "avg_tool_calls_total": 16, "max_tokens_in": 400000},
    ]
    bad = _cli("--metrics-dir", str(d), "query", "--group-by", "fr", "--agg", "median:x")
    assert bad.returncode == 2 and bad.stdout == "" and "aggregation" in bad.stderr


# covers hub-tooling FR-0002:AC-10
def test_query_reads_every_month_file_tolerates_unknown_kinds_extra_fields_and_junk(tmp_path):
    d = _fixture_dir(tmp_path)
    future = {**_rec("gate.run", ts="2026-09-02T00:00:00Z", record_id="9" * 32), "kind": "future.kind", "novel": {"n": 1}}
    (d / "2026-09.ndjson").write_text(
        json.dumps(future) + "\n" + "{not json\n" + "\n" + json.dumps(_rec(ts="2026-09-03T00:00:00Z", record_id="8" * 32)) + "\n",
        encoding="utf-8",
    )
    out = _cli("--metrics-dir", str(d), "query", "--kind", "future.kind")
    assert out.returncode == 0 and [json.loads(ln) for ln in out.stdout.splitlines()] == [future]
    out = _cli("--metrics-dir", str(d), "query", "--since", "2026-09-01T00:00:00Z")
    assert [json.loads(ln)["record_id"] for ln in out.stdout.splitlines()] == ["9" * 32, "8" * 32]
    assert out.stderr == ""


# covers hub-tooling FR-0002:AC-10
def test_query_and_report_with_no_log_exit_zero_with_empty_output(tmp_path):
    missing = tmp_path / "never-created"
    for args in (("query",), ("query", "--table"), ("query", "--group-by", "kind")):
        out = _cli("--metrics-dir", str(missing), *args)
        assert out.returncode == 0 and out.stderr == "", args
        assert out.stdout.strip() in ("", "(no rows)"), args
    assert not missing.exists()
    d = tmp_path / "only-reports"
    (d / "reports").mkdir(parents=True)
    shutil.copy(_REPORTS_DIR / "tool-calls-per-fr.json", d / "reports")
    out = _cli("--metrics-dir", str(d), "report", "tool-calls-per-fr")
    assert out.returncode == 0 and out.stdout == "" and out.stderr == ""
    assert sorted(p.name for p in d.iterdir()) == ["reports"]  # read-only: nothing created


# covers hub-tooling FR-0002:AC-10
def test_report_is_a_data_file_so_a_new_dashboard_is_a_new_file_not_code(tmp_path):
    d = _fixture_dir(tmp_path)
    (d / "reports" / "verdicts.json").write_text(
        json.dumps({"description": "reviewer verdicts", "filters": {"kind": "pr.review"}, "group_by": ["verdict"], "aggs": {"n": "count"}}),
        encoding="utf-8",
    )
    out = _cli("--metrics-dir", str(d), "report", "verdicts")
    assert out.returncode == 0, out.stderr
    assert [json.loads(ln) for ln in out.stdout.splitlines()] == [
        {"section": "verdicts", "verdict": "approve", "n": 1},
        {"section": "verdicts", "verdict": "request-changes", "n": 1},
    ]
    as_json = json.loads(_cli("--metrics-dir", str(d), "report", "verdicts", "--json").stdout)
    assert as_json == {"report": "verdicts", "sections": {"verdicts": [{"verdict": "approve", "n": 1}, {"verdict": "request-changes", "n": 1}]}}
    assert "# verdicts — reviewer verdicts" in _cli("--metrics-dir", str(d), "report", "verdicts", "--table").stdout
    missing = _cli("--metrics-dir", str(d), "report", "no-such-report")
    assert missing.returncode == 2 and "no report named" in missing.stderr
    traversal = _cli("--metrics-dir", str(d), "report", "../reports/verdicts")
    assert traversal.returncode == 2 and "invalid report name" in traversal.stderr


# covers hub-tooling FR-0002:AC-10
def test_where_clauses_and_dotted_fields(tmp_path):
    d = _fixture_dir(tmp_path)
    out = _cli("--metrics-dir", str(d), "query", "--kind", "gate.run", "--where", '["counts.frs","eq",3]', "--where", '["outcome","ne","pass"]')
    assert len(out.stdout.splitlines()) == 3
    out = _cli("--metrics-dir", str(d), "query", "--where", '["round","gt",1]', "--kind", "dispatch.run")
    assert sorted(json.loads(ln)["role"] for ln in out.stdout.splitlines()) == ["dev", "rev"]
    bad = _cli("--metrics-dir", str(d), "query", "--where", '["round","like",1]')
    assert bad.returncode == 2 and "unknown where operator" in bad.stderr


# ---------------------------------------------------------------------------
# AC-11: baseline reports reproduce IDEA-0016's hand measurements
# ---------------------------------------------------------------------------


def _run_named(name: str, d: Path) -> dict:
    return metrics_log.run_report(metrics_log.load_report(name, d), metrics_log.iter_records(d))


# covers hub-tooling FR-0002:AC-11
def test_tool_calls_per_fr_reproduces_the_fixture_lifecycle(tmp_path):
    d = _fixture_dir(tmp_path)
    result = _run_named("tool-calls-per-fr", d)
    assert list(result) == ["by_role", "lifecycle_total"]
    assert result["by_role"] == [
        {"fr": "FR-0020", "role": "architect", "runs": 1, "tool_calls": 25},
        {"fr": "FR-0020", "role": "dev", "runs": 2, "tool_calls": 93},
        {"fr": "FR-0020", "role": "rev", "runs": 2, "tool_calls": 32},
    ]
    assert result["lifecycle_total"] == [{"fr": "FR-0020", "runs": 5, "tool_calls": 150}]


# covers hub-tooling FR-0002:AC-11
def test_retries_per_fr_reproduces_the_fixture_lifecycle(tmp_path):
    d = _fixture_dir(tmp_path)
    result = _run_named("retries-per-fr", d)
    assert list(result) == ["rework_rounds", "tool_errors", "gate_failures"]
    assert result["rework_rounds"] == [{"fr": "FR-0020", "rework_rounds": 1}]
    assert result["tool_errors"] == [{"fr": "FR-0020", "tool_errors": 18}]
    assert result["gate_failures"] == [
        {"fr": "FR-0020", "gate_failures": 3, "failure_classes": ["coverage-missing", "covers-unknown-ac", "spec-validation"]}
    ]


# covers hub-tooling FR-0002:AC-11
def test_both_baseline_reports_run_through_the_cli_against_the_fixture(tmp_path):
    d = _fixture_dir(tmp_path)
    out = _cli("--metrics-dir", str(d), "report", "tool-calls-per-fr", "--json")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["sections"]["lifecycle_total"] == [{"fr": "FR-0020", "runs": 5, "tool_calls": 150}]
    out = _cli("--metrics-dir", str(d), "report", "retries-per-fr")
    rows = [json.loads(ln) for ln in out.stdout.splitlines()]
    assert {"section": "rework_rounds", "fr": "FR-0020", "rework_rounds": 1} in rows
    assert {"section": "tool_errors", "fr": "FR-0020", "tool_errors": 18} in rows


# covers hub-tooling FR-0002:AC-11
def test_retries_report_counts_only_developer_rounds_beyond_the_first_and_non_pass_gates(tmp_path):
    """Adversarial: a Reviewer round 2 and an `error` gate run must land in
    the right buckets; a second FR with no retries must be absent, not zero."""
    d = tmp_path / "m"
    (d / "reports").mkdir(parents=True)
    shutil.copy(_REPORTS_DIR / "retries-per-fr.json", d / "reports")
    recs = [
        _rec("dispatch.run", record_id="1" * 32, role="dev", round=1, tool_errors_total=2),
        _rec("dispatch.run", record_id="2" * 32, role="rev", round=2, tool_errors_total=1),
        _rec("dispatch.run", record_id="3" * 32, role="dev", round=3, tool_errors_total=0),
        _rec("gate.run", record_id="4" * 32, outcome="error", failure_classes=["script-error"]),
        _rec("gate.run", record_id="5" * 32, outcome="pass"),
        _rec("dispatch.run", record_id="6" * 32, role="dev", round=1, object_ids=["FR-0101"], tool_errors_total=0),
    ]
    for r in recs:
        metrics_log.append(r, d)
    result = _run_named("retries-per-fr", d)
    assert result["rework_rounds"] == [{"fr": "FR-0100", "rework_rounds": 1}]
    assert result["tool_errors"] == [{"fr": "FR-0100", "tool_errors": 3}, {"fr": "FR-0101", "tool_errors": 0}]
    assert result["gate_failures"] == [{"fr": "FR-0100", "gate_failures": 1, "failure_classes": ["script-error"]}]


# ---------------------------------------------------------------------------
# AC-12: per-FR summary for INDEX.md (the shared renderer)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-12
def test_render_index_section_summarises_the_fixture_lifecycle_per_fr(tmp_path):
    d = _fixture_dir(tmp_path)
    lines = metrics_log.render_index_section(metrics_log.iter_records(d))
    assert lines[:2] == ["", "## Pipeline metrics"]
    assert lines[5] == "| FR | Latest run status | Tool calls | Retries | Last gate | Last PR |"
    rows = [ln for ln in lines if ln.startswith("| FR-")]
    assert rows == [
        (
            "| FR-0020 | architect: success, dev: success, rev: success | 150 | "
            "1 rework, 18 tool errors, 3 gate fails (coverage-missing, covers-unknown-ac, spec-validation) | pass | #42 |"
        )
    ]
    summary = metrics_log.summarize_by_fr(metrics_log.iter_records(d))
    assert summary["FR-0020"]["last_gate"] == "pass" and summary["FR-0020"]["last_pr"] == 42


# covers hub-tooling FR-0002:AC-12
def test_render_index_section_is_empty_without_fr_attributable_records(tmp_path):
    assert metrics_log.render_index_section([]) == []
    orphan_gate = _rec("gate.run", object_ids=[], run_id=None)
    assert metrics_log.render_index_section([orphan_gate]) == []
    # Unattributed gate run joined to an FR through a dispatch record's run_id.
    spawn = _rec("dispatch.spawn", run_id="r" * 32, record_id="1" * 32)
    gate = _rec("gate.run", object_ids=[], run_id="r" * 32, outcome="fail", failure_classes=["coverage-missing"])
    rows = [ln for ln in metrics_log.render_index_section([spawn, gate]) if ln.startswith("| FR-")]
    assert rows == ["| FR-0100 | — | 0 | 0 rework, 0 tool errors, 1 gate fails (coverage-missing) | fail | — |"]


# covers hub-tooling FR-0002:AC-12
def test_render_index_section_is_deterministic_regardless_of_file_order(tmp_path):
    recs = metrics_log.read_records(_fixture_dir(tmp_path))
    forward = metrics_log.render_index_section(recs)
    assert metrics_log.render_index_section(list(reversed(recs))) == forward


# ---------------------------------------------------------------------------
# AC-13: no transcript text or PHI in records
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-13
def test_strings_longer_than_200_chars_are_rejected_anywhere_in_the_record():
    assert metrics_log.MAX_STRING_LEN == 200
    assert metrics_log.validation_errors(_rec(project="p" * 200)) == []
    long = "x" * 500
    for over in (
        {"project": long},
        {"object_ids": [long]},
        {"run_id": long},
        {"failure_classes": [long]},                       # enum list, still capped
        {"counts": {long: 1}},                             # dict key
        {"future_field": {"nested": [{"deeper": long}]}},  # unknown field
    ):
        errors = metrics_log.validation_errors(_rec(**over))
        assert any("200" in e for e in errors), (over, errors)
    assert metrics_log.validation_errors(_rec(project="x" * 201))


# covers hub-tooling FR-0002:AC-13
def test_string_bearing_fields_off_the_allow_list_are_rejected_string_free_ones_accepted():
    prose = "The agent said: I could not find the patient record, retrying"
    for over in (
        {"summary": prose},
        {"body": [prose]},
        {"details": {"message": prose}},
        {"counts": {"frs": "1"}},              # known field, but not on the allow-list
    ):
        errors = metrics_log.validation_errors(_rec(**over))
        assert any("allow-list" in e for e in errors), (over, errors)
    errors = metrics_log.validation_errors(_rec("dispatch.run", tool_calls_total="3"))
    assert any("allow-list" in e for e in errors), errors
    assert metrics_log.validation_errors(_rec(extra_count=3, extra_flags={"a": True, "b": None})) == []


# covers hub-tooling FR-0002:AC-13
def test_allow_list_names_no_prose_field_and_matches_the_documented_shapes():
    for banned in ("summary", "body", "message", "text", "note", "error", "stderr", "stdout", "diff", "content", "prose"):
        assert banned not in metrics_log.STRING_FIELDS, banned
    # Every string-typed field a default record carries is on the allow-list
    # (otherwise the emitters' own records would fail), and nothing else is.
    string_fields_in_use: set[str] = set()
    for kind in metrics_log.KINDS:
        for name, value in _rec(kind).items():
            if name != "schema_version" and any(True for _ in metrics_log._iter_strings(value, keys=False)):
                string_fields_in_use.add(name)
    assert string_fields_in_use <= metrics_log.STRING_FIELDS
    assert {"tool_calls_total", "tool_errors_total", "tokens_in", "tokens_out", "duration_s", "counts", "round", "draft",
            "commits_ahead", "files_touched", "tests_changed", "covers_delta", "pr_number", "parent_pr_number",
            "fr_count", "completed", "dev_only", "dropped", "breaking_declared", "breaking_observed"}.isdisjoint(metrics_log.STRING_FIELDS)


def _install_hook(tmp_path: Path, monkeypatch) -> Path:
    hook = tmp_path / ".agent-team" / "hooks" / "phi_regex_check.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(_PHI_HOOK_SOURCE, encoding="utf-8")
    monkeypatch.setattr(metrics_log, "PHI_HOOK_PATH", hook)
    monkeypatch.setattr(metrics_log, "_PHI_PATTERNS", None)
    monkeypatch.setattr(metrics_log, "_PHI_PATH_LOADED", None)
    return hook


# covers hub-tooling FR-0002:AC-13
@pytest.mark.parametrize(
    "poison",
    [
        {"base_branch": "feature/123-456-789"},                       # SIN-like in an allow-listed string
        {"base_branch": "hcn-1234-567-890-AB"},                       # OHIP-like
        {"object_ids": ["FR-0100", "987-65-4321"]},                   # SSN-like in a list
        {"tool_calls_by_tool": {"Bash 123 456 789": 1}},               # in a dict key (tool name)
    ],
)
def test_record_matching_a_phi_pattern_under_an_active_profile_is_dropped_not_appended(tmp_path, monkeypatch, capsys, poison):
    _install_hook(tmp_path, monkeypatch)
    kind = "dispatch.run" if "tool_calls_by_tool" in poison else "dispatch.spawn"
    fields = _rec(kind, **poison)
    for k in metrics_log.ENVELOPE_FIELDS:
        if k != "object_ids":
            fields.pop(k, None)
    object_ids = fields.pop("object_ids")
    assert metrics_log.validation_errors(_rec(kind, **poison)) == []  # schema-valid: only the hook stops it
    result = metrics_log.emit(kind, source="dispatch", role="dev", object_ids=object_ids, **fields)
    assert result is None
    err = capsys.readouterr().err
    assert err.count("WARN: metrics:") == 1 and "dropped" in err and "Possible" in err
    assert not metrics_log.METRICS_DIR.exists()
    # The same record without the profile is appended: the hook, not a
    # hard-coded pattern, is what gates it.
    monkeypatch.setattr(metrics_log, "PHI_HOOK_PATH", tmp_path / "absent.py")
    monkeypatch.setattr(metrics_log, "_PHI_PATTERNS", None)
    assert metrics_log.emit(kind, source="dispatch", role="dev", object_ids=object_ids, **fields) is not None


# covers hub-tooling FR-0002:AC-13
def test_hook_patterns_are_loaded_from_the_hook_file_and_a_broken_hook_does_not_block_emission(tmp_path, monkeypatch, capsys):
    hook = _install_hook(tmp_path, monkeypatch)
    labels = [label for _, label in metrics_log.phi_patterns()]
    assert len(labels) == 3 and any("SIN" in lbl for lbl in labels)
    assert metrics_log.phi_hits(_rec(project="clean-project")) == []
    assert metrics_log.phi_hits(_rec(project="sin 123-456-789")) == ["Possible Canadian SIN (XXX-XXX-XXX)"]
    hook.write_text("raise RuntimeError('hook exploded')\n", encoding="utf-8")
    monkeypatch.setattr(metrics_log, "_PHI_PATTERNS", None)
    assert _emit_ok() is not None
    err = capsys.readouterr().err
    assert err.count("WARN: metrics:") == 1 and "phi hook unusable" in err


# covers hub-tooling FR-0002:AC-13
def test_record_ids_cannot_collide_with_the_hook_patterns(tmp_path, monkeypatch):
    _install_hook(tmp_path, monkeypatch)
    for _ in range(200):
        rid = metrics_log.new_id()
        assert re.fullmatch(r"[0-9a-f]{32}", rid)
        assert metrics_log.phi_hits(_rec(record_id=rid, run_id=rid)) == []


# covers hub-tooling FR-0002:AC-13
def test_emit_cli_rejects_a_500_char_string_and_off_list_prose(tmp_path):
    d = tmp_path / "m"
    long = "x" * 500
    out = _cli("--metrics-dir", str(d), "emit", "--kind", "escalation", "--object-id", "FR-0100",
               "--json", json.dumps({"trigger_class": long}))
    assert out.returncode == 1 and "200" in out.stderr and not d.exists()
    out = _cli("--metrics-dir", str(d), "emit", "--kind", "escalation", "--object-id", "FR-0100",
               "--json", json.dumps({"trigger_class": "other", "note": "free text"}))
    assert out.returncode == 1 and "allow-list" in out.stderr and not d.exists()
    out = _cli("--metrics-dir", str(d), "emit", "--kind", "escalation", "--object-id", "FR-0100", "--role", "dev",
               "--json", json.dumps({"trigger_class": "other"}))
    assert out.returncode == 0, out.stderr
    [rec] = _lines(next(d.glob("*.ndjson")))
    assert rec["kind"] == "escalation" and rec["source"] == "manual" and rec["role"] == "dev"


# ---------------------------------------------------------------------------
# AC-14: schema documented, fixture ships
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-14
def test_readme_documents_every_envelope_kind_specific_and_reserved_field_with_source_and_ac():
    text = _METRICS_README.read_text(encoding="utf-8")
    for name in metrics_log.ENVELOPE_FIELDS:
        assert f"`{name}`" in text, name
    for kind, fields in metrics_log.KIND_REQUIRED.items():
        assert f"`{kind}`" in text, kind
        for name in fields:
            assert f"`{name}`" in text, (kind, name)
    for name in metrics_log.RESERVED_FIELDS:
        assert f"`{name}`" in text, name
    assert "back-filled by H1-H5 / WS1-WS4" in text and "no emitter" in text
    for ac in (1, 2, 3, 4, 5, 6, 7, 11, 13):
        assert f"AC-{ac}" in text, f"AC-{ac} not cited"
    for source in ("dispatch", "gate", "escalation-log", "manual"):
        assert f"`{source}`" in text, source
    for header in ("| Field | Type |", "Nullable"):
        assert header in text
    assert "`[slice-miss]`" in text and "## FINDINGS" in text
    assert "`tool-calls-per-fr`" in text and "`retries-per-fr`" in text
    for cls in sorted(metrics_log.GATE_FAILURE_CLASSES | metrics_log.GATE_WARNING_CLASSES | metrics_log.GATE_INVOKED_BY):
        assert f"`{cls}`" in text, cls
    assert "tests/fixtures/metrics/2026-08.ndjson" in text


# covers hub-tooling FR-0002:AC-14
def test_shipped_fixture_validates_line_by_line_and_models_one_synthetic_lifecycle():
    assert _FIXTURE.parent == _TEMPLATE_DIR / "tests" / "fixtures" / "metrics"
    raw = _FIXTURE.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    recs = _lines(_FIXTURE)
    assert len(recs) == 24
    for rec in recs:
        assert metrics_log.validation_errors(rec) == [], rec["record_id"]
    assert len({r["record_id"] for r in recs}) == len(recs)
    kinds = [r["kind"] for r in recs]
    assert set(kinds) == metrics_log.KINDS  # every kind appears at least once
    assert all(r["project"] == "synthetic-project" for r in recs)
    assert {o for r in recs for o in r["object_ids"]} == {"FR-0020"}
    out = _cli("validate", str(_FIXTURE))
    assert out.returncode == 0 and out.stdout.strip() == "24/24 records valid"


# covers hub-tooling FR-0002:AC-14
def test_shipped_fixture_carries_no_real_looking_identifiers(tmp_path, monkeypatch):
    _install_hook(tmp_path, monkeypatch)
    text = _FIXTURE.read_text(encoding="utf-8")
    for rec in _lines(_FIXTURE):
        assert metrics_log.phi_hits(rec) == [], rec["record_id"]
        for s in metrics_log._iter_strings(rec, keys=False):
            assert len(s) <= 200
    for url in re.findall(r"https?://[^\s\"]+", text):
        assert url.startswith("https://github.com/example-org/synthetic-project/"), url
    for sha in re.findall(r"\b[0-9a-f]{40}\b", text):
        assert len(set(sha[:-1])) == 1, sha  # placeholder SHAs (aaaa...1), not real commits
    assert "@" not in text  # no e-mail addresses / handles


# covers hub-tooling FR-0002:AC-14
def test_validate_cli_reports_bad_lines_and_exits_one(tmp_path):
    f = tmp_path / "mixed.ndjson"
    f.write_text(json.dumps(_rec()) + "\n{oops\n" + json.dumps(_rec(kind="nope")) + "\n\n", encoding="utf-8")
    out = _cli("validate", str(f))
    assert out.returncode == 1
    assert "line 2: not JSON" in out.stdout and "line 3: unknown kind 'nope'" in out.stdout
    assert out.stdout.strip().endswith("1/3 records valid")


# ---------------------------------------------------------------------------
# AC-6: escalation-log.py — Markdown row plus structured twin
# ---------------------------------------------------------------------------


def _escalation_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    (repo / "scripts").mkdir(parents=True)
    for name in ("escalation-log.py", "metrics_log.py"):
        shutil.copy(_SCRIPTS_DIR / name, repo / "scripts" / name)
    (repo / ".agent-team").mkdir()
    shutil.copy(_MATRIX, repo / ".agent-team" / "escalation-matrix.md")
    return repo


def _esc(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "METRICS_PROJECT": "synthetic-project"}
    full_env.pop("METRICS_LOG_DISABLED", None)
    full_env.pop("DISPATCH_RUN_ID", None)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "escalation-log.py"), *args],
        capture_output=True, check=False, text=True, encoding="utf-8", env=full_env,
    )


def _esc_records(repo: Path) -> list[dict]:
    files = sorted((repo / "specs" / "_metrics").glob("*.ndjson")) if (repo / "specs" / "_metrics").exists() else []
    return [r for f in files for r in _lines(f)]


# covers hub-tooling FR-0002:AC-6
def test_append_writes_the_markdown_row_and_one_escalation_record_without_the_text(tmp_path):
    repo = _escalation_repo(tmp_path)
    marker = "zqxv-unique-summary-token"
    out = _esc(repo, "append", "--fr", "FR-0007", "--role", "Developer", "--trigger", f"Spec is ambiguous ({marker})")
    assert out.returncode == 0 and out.stdout.startswith("Appended escalation for FR-0007"), out.stderr
    assert out.stderr == ""
    md = (repo / ".agent-team" / "escalation-log.md").read_text(encoding="utf-8")
    assert f"| FR-0007 | Developer | Spec is ambiguous ({marker}) | (pending) |" in md
    [rec] = _esc_records(repo)
    assert rec["kind"] == "escalation" and rec["source"] == "escalation-log"
    assert rec["role"] == "dev" and rec["object_ids"] == ["FR-0007"] and rec["run_id"] is None
    assert rec["trigger_class"] == "spec-is-ambiguous"
    assert marker not in json.dumps(rec) and "(pending)" not in json.dumps(rec)
    assert set(rec) == set(metrics_log.ENVELOPE_FIELDS) | {"trigger_class"}


# covers hub-tooling FR-0002:AC-6
def test_resolve_updates_the_pending_row_and_emits_escalation_resolved_with_the_same_identifiers(tmp_path):
    repo = _escalation_repo(tmp_path)
    _esc(repo, "append", "--fr", "FR-0007", "--role", "Reviewer", "--trigger", "Test reveals spec gap")
    out = _esc(repo, "resolve", "--fr", "FR-0007", "--resolution", "clarified AC-2 (resolution-token)",
               env={"DISPATCH_RUN_ID": "r" * 32})
    assert out.returncode == 0 and out.stdout.strip() == "Resolved escalation for FR-0007", out.stderr
    md = (repo / ".agent-team" / "escalation-log.md").read_text(encoding="utf-8")
    assert "| FR-0007 | Reviewer | Test reveals spec gap | clarified AC-2 (resolution-token) |" in md
    assert "(pending)" not in md
    recs = _esc_records(repo)
    assert [r["kind"] for r in recs] == ["escalation", "escalation.resolved"]
    resolved = recs[1]
    assert resolved["role"] == "rev" and resolved["object_ids"] == ["FR-0007"]
    assert resolved["trigger_class"] == "test-reveals-spec-gap" == recs[0]["trigger_class"]
    assert resolved["run_id"] == "r" * 32
    assert "resolution-token" not in json.dumps(resolved)


# covers hub-tooling FR-0002:AC-6
def test_resolve_with_nothing_pending_exits_one_and_emits_nothing(tmp_path):
    repo = _escalation_repo(tmp_path)
    out = _esc(repo, "resolve", "--fr", "FR-0007", "--resolution", "nothing to do")
    assert out.returncode == 1 and "No pending escalation found for FR-0007" in out.stderr
    assert _esc_records(repo) == []
    # A resolved row is not resolved twice.
    _esc(repo, "append", "--fr", "FR-0008", "--role", "Architect", "--trigger", "Two ACs contradict")
    assert _esc(repo, "resolve", "--fr", "FR-0008", "--resolution", "first").returncode == 0
    assert _esc(repo, "resolve", "--fr", "FR-0008", "--resolution", "second").returncode == 1
    assert [r["kind"] for r in _esc_records(repo)] == ["escalation", "escalation.resolved"]


# covers hub-tooling FR-0002:AC-6
def test_resolve_touches_only_the_matching_row_and_leaves_other_rows_byte_identical(tmp_path):
    repo = _escalation_repo(tmp_path)
    _esc(repo, "append", "--fr", "FR-0001", "--role", "Developer", "--trigger", "Code outside FR scope")
    _esc(repo, "append", "--fr", "FR-0002", "--role", "Architect", "--trigger", "Cross-FR conflict")
    _esc(repo, "append", "--fr", "FR-0001", "--role", "Reviewer", "--trigger", "AC has no test")
    before = (repo / ".agent-team" / "escalation-log.md").read_text(encoding="utf-8").splitlines()
    assert _esc(repo, "resolve", "--fr", "FR-0001", "--resolution", "done").returncode == 0
    after = (repo / ".agent-team" / "escalation-log.md").read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert changed == [len(before) - 1]  # the most recent FR-0001 row, and only it
    assert after[-1].endswith("| Reviewer | AC has no test | done |")
    assert after[-2] == before[-2] and "Cross-FR conflict | (pending)" in after[-2]
    resolved = [r for r in _esc_records(repo) if r["kind"] == "escalation.resolved"]
    assert [(r["role"], r["trigger_class"]) for r in resolved] == [("rev", "ac-has-no-test")]


# covers hub-tooling FR-0002:AC-6
def test_trigger_class_is_a_matrix_row_or_other_and_role_labels_normalise(tmp_path):
    repo = _escalation_repo(tmp_path)
    cases = [
        ("Spec is ambiguous", "spec-is-ambiguous"),
        ("Code doesn't satisfy AC", "code-doesnt-satisfy-ac"),
        ("spec is ambiguous about retention", "spec-is-ambiguous"),   # paraphrase, prefix match
        ("Security / privacy / legal concern", "security-privacy-legal-concern"),
        ("Dev↔Reviewer loop hits 3 cycles", "dev-reviewer-loop-hits-3-cycles"),
        ("Architect is being asked to override an existing ADR", "architect-is-being-asked-to-override-an-existing-adr"),
        ("something the matrix never heard of", "other"),
    ]
    for trigger, want in cases:
        assert metrics_log.trigger_class(trigger, repo / ".agent-team" / "escalation-matrix.md") == want, trigger
    assert metrics_log.trigger_class("", repo / ".agent-team" / "escalation-matrix.md") == "other"
    # Without a matrix file the template's rows still classify.
    assert metrics_log.trigger_class("Two ACs contradict", tmp_path / "absent.md") == "two-acs-contradict"
    for label, want in (("Developer", "dev"), ("architect", "architect"), ("Reviewer", "rev"), ("QA", None), ("", None)):
        assert metrics_log.normalise_role(label) == want, label
    out = _esc(repo, "append", "--fr", "n/a", "--role", "QA", "--trigger", "unknown trigger")
    assert out.returncode == 0
    [rec] = _esc_records(repo)
    assert rec["role"] is None and rec["object_ids"] == [] and rec["trigger_class"] == "other"


# covers hub-tooling FR-0002:AC-6
def test_escalation_log_with_metrics_disabled_still_writes_markdown_and_emits_nothing(tmp_path):
    repo = _escalation_repo(tmp_path)
    out = _esc(repo, "append", "--fr", "FR-0007", "--role", "Developer", "--trigger", "Spec is ambiguous",
               env={"METRICS_LOG_DISABLED": "1"})
    assert out.returncode == 0 and out.stdout.startswith("Appended escalation for FR-0007") and out.stderr == ""
    assert "| FR-0007 | Developer |" in (repo / ".agent-team" / "escalation-log.md").read_text(encoding="utf-8")
    assert not (repo / "specs").exists()


# covers hub-tooling FR-0002:AC-6
def test_resolve_row_fix_the_pre_fr0002_helper_never_matched_a_real_pending_row(tmp_path):
    """Anchor for the `resolve_row` fix: the pinned pre-FR-0002 copy compared
    the Trigger column to `(pending)` and so reported "No pending escalation"
    for a row it had itself just appended."""
    baseline = _git_show_baseline("template/scripts/escalation-log.py")
    if baseline is None:
        pytest.skip(f"baseline commit {_PRE_FR0002_REF} not reachable (not running inside the hub checkout)")
    assert b"m.group(4).strip()" in baseline and b"m.group(5).strip()" not in baseline
    old = tmp_path / "old"
    (old / "scripts").mkdir(parents=True)
    (old / "scripts" / "escalation-log.py").write_bytes(baseline)
    (old / ".agent-team").mkdir()
    _esc(old, "append", "--fr", "FR-0007", "--role", "Developer", "--trigger", "Spec is ambiguous")
    assert _esc(old, "resolve", "--fr", "FR-0007", "--resolution", "x").returncode == 1
    new = _escalation_repo(tmp_path)
    _esc(new, "append", "--fr", "FR-0007", "--role", "Developer", "--trigger", "Spec is ambiguous")
    assert _esc(new, "resolve", "--fr", "FR-0007", "--resolution", "x").returncode == 0
