"""Reviewer tests for FR-0002 — `deploy-gate.py` emission (AC-4), the
never-load-bearing contract as seen from the gate (AC-9), the INDEX.md
metrics section written identically by indexer and gate (AC-12) and the
PHI guard under an active profile as seen from the gate (AC-13).

Same harness as `test_deploy_gate.py`: the team scripts are copied into a
self-contained temporary repo and the gate is driven through `subprocess`, so
exit code, stdout, stderr and the files on disk are all observable. Every
failure branch is driven from a synthetic specs/tests fixture and the emitted
`gate.run` record's class list is asserted. Byte-identity is proven by running
the same tree twice — once with `METRICS_LOG_DISABLED=1`, once without — and
comparing stdout, stderr and the exit code.

Coverage annotations are written `# covers hub-tooling FR-0002:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0002 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (see test_index_specs_versioning.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_FIXTURE = _TEMPLATE_DIR / "tests" / "fixtures" / "metrics" / "2026-08.ndjson"
# Spelled in two halves so a bootstrapped project's `deploy-gate.py`, which
# regex-scans every file under tests/, does not read these fixture strings as
# real annotations against FRs that project never had.
_COVERS = "@" + "covers"
# deploy-gate imports index-specs (which imports spec_footprint, spec_query and
# metrics_log), so all five travel.
_COPY_SCRIPTS = ("deploy-gate.py", "index-specs.py", "spec_footprint.py", "spec_query.py", "metrics_log.py")
_METRICS_ENV = ("METRICS_LOG_DISABLED", "METRICS_INVOKED_BY", "METRICS_GATE_RECORD_ID", "METRICS_GATE_OVERRIDE", "DISPATCH_RUN_ID")

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_PHI_HOOK_SOURCE = '''
PHI_PATTERNS = [
    (r"\\b\\d{3}[-\\s]\\d{3}[-\\s]\\d{3}\\b", "Possible Canadian SIN (XXX-XXX-XXX)"),
    (r"\\b\\d{3}-\\d{2}-\\d{4}\\b", "Possible US SSN (XXX-XX-XXXX)"),
]
'''


def _fr_markdown(fr_id: str, *, status: str = "ready", depends_on: str = "[]", extra_body: str = "") -> str:
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: {depends_on}
tags: []
owns: []
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
- **AC-2:** does the second thing
{extra_body}"""


def _build_repo(
    tmp_path: Path,
    fr_files: dict[str, str],
    *,
    tests: dict[str, str] | None = None,
    src: dict[str, str] | None = None,
    name: str = "repo",
) -> Path:
    repo = tmp_path / name
    (repo / "scripts").mkdir(parents=True)
    for script in _COPY_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / script, repo / "scripts" / script)
    (repo / "specs").mkdir()
    for filename, content in fr_files.items():
        (repo / "specs" / filename).write_text(content, encoding="utf-8")
    for folder, files in (("tests", tests), ("src", src)):
        if files:
            (repo / folder).mkdir()
            for filename, content in files.items():
                (repo / folder / filename).write_text(content, encoding="utf-8")
    return repo


def _run(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    full_env["METRICS_PROJECT"] = "synthetic-project"
    full_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "deploy-gate.py"), *args],
        capture_output=True, check=False, text=True, encoding="utf-8", env=full_env,
    )


def _records(repo: Path) -> list[dict]:
    d = repo / "specs" / "_metrics"
    if not d.exists():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.ndjson")):
        out.extend(json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip())
    return out


def _one_gate_record(repo: Path) -> dict:
    recs = _records(repo)
    assert len(recs) == 1, recs
    rec = recs[0]
    assert metrics_log.validation_errors(rec) == [], rec
    assert rec["kind"] == "gate.run" and rec["source"] == "gate" and rec["role"] is None
    return rec


_TWICE_COUNTER = [0]


def _run_twice(builder, *args: str, env: dict[str, str] | None = None):
    """Run the same tree with emission disabled and enabled; return
    (disabled_proc, enabled_proc, enabled_repo)."""
    _TWICE_COUNTER[0] += 1
    off_repo = builder(f"off-{_TWICE_COUNTER[0]}")
    on_repo = builder(f"on-{_TWICE_COUNTER[0]}")
    off = _run(off_repo, *args, env={**(env or {}), "METRICS_LOG_DISABLED": "1"})
    on = _run(on_repo, *args, env=env)
    assert _records(off_repo) == []
    return off, on, on_repo


# ---------------------------------------------------------------------------
# Scenarios: one builder per gate branch
# ---------------------------------------------------------------------------


def _scenario(tmp_path: Path, which: str):
    def build(name: str) -> Path:
        ready = {"FR-0100-example.md": _fr_markdown("FR-0100")}
        if which == "pass":
            return _build_repo(tmp_path, ready, name=name)
        if which == "spec-validation":
            return _build_repo(tmp_path, {"FR-0100-example.md": _fr_markdown("FR-0100", depends_on="[FR-9999]")}, name=name)
        if which == "covers-unknown-fr":
            return _build_repo(tmp_path, ready, tests={"test_x.py": f"# {_COVERS} FR-0999:AC-1\ndef test_x():\n    pass\n"}, name=name)
        if which == "covers-unknown-ac":
            return _build_repo(tmp_path, ready, tests={"test_x.py": f"# {_COVERS} FR-0100:AC-9\ndef test_x():\n    pass\n"}, name=name)
        if which == "coverage-missing":
            return _build_repo(
                tmp_path,
                {"FR-0100-example.md": _fr_markdown("FR-0100", status="in-review")},
                tests={"test_x.py": f"# {_COVERS} FR-0100:AC-1\ndef test_x():\n    pass\n"},
                name=name,
            )
        if which == "two-failures":
            return _build_repo(
                tmp_path,
                {"FR-0100-example.md": _fr_markdown("FR-0100", status="in-review")},
                tests={"test_x.py": f"# {_COVERS} FR-0999:AC-1\n# {_COVERS} FR-0100:AC-1\ndef test_x():\n    pass\n"},
                name=name,
            )
        if which == "implements-missing":
            return _build_repo(
                tmp_path,
                {"FR-0100-example.md": _fr_markdown("FR-0100", status="in-review")},
                tests={"test_x.py": f"# {_COVERS} FR-0100:AC-1\n# {_COVERS} FR-0100:AC-2\ndef test_x():\n    pass\n"},
                name=name,
            )
        if which == "implements-unknown-fr":
            return _build_repo(tmp_path, ready, src={"x.py": "# @implements FR-0999\n"}, name=name)
        if which == "ac-format":
            return _build_repo(
                tmp_path,
                {"FR-0100-example.md": _fr_markdown("FR-0100", extra_body="\nSee also AC-7 in the notes above.\n")},
                name=name,
            )
        raise AssertionError(which)

    return build


# ---------------------------------------------------------------------------
# AC-4: every gate run emits a classified outcome
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-4
def test_passing_run_emits_exactly_one_pass_record_with_counts(tmp_path):
    repo = _scenario(tmp_path, "pass")("r")
    proc = _run(repo)
    assert proc.returncode == 0, proc.stderr
    rec = _one_gate_record(repo)
    assert rec["stage"] == "full" and rec["outcome"] == "pass"
    assert rec["failure_classes"] == [] and rec["warning_classes"] == []
    assert rec["counts"] == {"frs": 1, "covers": 0, "implements": 0}
    assert rec["invoked_by"] == "manual" and rec["object_ids"] == [] and rec["run_id"] is None
    assert "forced" not in rec and "draft_exempt" not in rec
    assert rec["project"] == "synthetic-project"
    assert (repo / "specs" / "_metrics" / f"{rec['ts'][:7]}.ndjson").is_file()


# covers hub-tooling FR-0002:AC-4
@pytest.mark.parametrize(
    "which, classes, object_ids",
    [
        ("spec-validation", ["spec-validation"], ["FR-0100", "FR-9999"]),
        ("covers-unknown-fr", ["covers-unknown-fr"], ["FR-0999"]),
        ("covers-unknown-ac", ["covers-unknown-ac"], ["FR-0100"]),
        ("coverage-missing", ["coverage-missing"], ["FR-0100"]),
        ("two-failures", ["covers-unknown-fr", "coverage-missing"], ["FR-0100", "FR-0999"]),
    ],
)
def test_each_failure_branch_emits_fail_with_its_class_and_the_frs_named(tmp_path, which, classes, object_ids):
    repo = _scenario(tmp_path, which)("r")
    proc = _run(repo)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    rec = _one_gate_record(repo)
    assert rec["outcome"] == "fail"
    assert rec["failure_classes"] == classes
    assert set(rec["failure_classes"]) <= metrics_log.GATE_FAILURE_CLASSES
    assert rec["object_ids"] == object_ids  # sorted, deduplicated


# covers hub-tooling FR-0002:AC-4
def test_failure_classes_are_the_fixed_enum_and_the_gate_only_uses_those(tmp_path):
    assert metrics_log.GATE_FAILURE_CLASSES == {
        "spec-validation", "covers-unknown-fr", "covers-malformed-ac", "covers-unknown-ac", "coverage-missing", "script-error",
        "gate-evidence-missing", "gate-evidence-stale",  # FR-0008 AC-9 (DEC-0012 item 2(f))
    }
    assert metrics_log.GATE_WARNING_CLASSES == {"implements-missing", "implements-unknown-fr", "ac-format"}
    assert metrics_log.GATE_INVOKED_BY == {"dispatch-finalize", "hook", "ci", "manual"}
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    import re

    used_fail = set(re.findall(r'report\.fail\("([a-z-]+)"', source))
    used_warn = set(re.findall(r'report\.warn\("([a-z-]+)"', source))
    assert used_fail <= metrics_log.GATE_FAILURE_CLASSES and used_warn == metrics_log.GATE_WARNING_CLASSES
    # Every class except covers-malformed-ac has a reachable branch (that one is
    # guarded by COVERS_PATTERN, which only ever captures well-formed AC ids).
    # FR-0008 AC-9's two classes are emitted through a computed local, invisible
    # to the scrape above; their branches are pinned by test_deploy_gate_gates.py.
    FR0008_COMPUTED = {"gate-evidence-missing", "gate-evidence-stale"}
    assert used_fail | FR0008_COMPUTED == metrics_log.GATE_FAILURE_CLASSES


# covers hub-tooling FR-0002:AC-4
@pytest.mark.parametrize(
    "which, warnings",
    [
        ("implements-missing", ["implements-missing"]),
        ("implements-unknown-fr", ["implements-unknown-fr"]),
        ("ac-format", ["ac-format"]),
    ],
)
def test_each_warning_branch_is_classified_on_a_passing_run(tmp_path, which, warnings):
    repo = _scenario(tmp_path, which)("r")
    proc = _run(repo)
    assert proc.returncode == 0, proc.stderr
    rec = _one_gate_record(repo)
    assert rec["outcome"] == "pass" and rec["warning_classes"] == warnings
    assert set(rec["warning_classes"]) <= metrics_log.GATE_WARNING_CLASSES


# covers hub-tooling FR-0002:AC-4
def test_stage_is_recorded_and_dev_stage_skips_the_coverage_check(tmp_path):
    repo = _scenario(tmp_path, "coverage-missing")("r")
    proc = _run(repo, "--stage", "dev")
    assert proc.returncode == 0, proc.stderr
    rec = _one_gate_record(repo)
    assert rec["stage"] == "dev" and rec["outcome"] == "pass" and rec["failure_classes"] == []
    assert rec["counts"]["covers"] == 1
    repo2 = _scenario(tmp_path, "coverage-missing")("r2")
    _run(repo2, "--stage", "review")
    assert _one_gate_record(repo2)["stage"] == "review"
    assert _one_gate_record(repo2)["failure_classes"] == ["coverage-missing"]


# covers hub-tooling FR-0002:AC-4
def test_invoked_by_run_id_and_record_id_come_from_the_dispatcher_environment(tmp_path):
    repo = _scenario(tmp_path, "pass")("r")
    _run(repo, env={"METRICS_INVOKED_BY": "dispatch-finalize", "DISPATCH_RUN_ID": "r" * 32, "METRICS_GATE_RECORD_ID": "g" * 32})
    rec = _one_gate_record(repo)
    assert rec["invoked_by"] == "dispatch-finalize" and rec["run_id"] == "r" * 32 and rec["record_id"] == "g" * 32
    for value, want in (("ci", "ci"), ("hook", "hook"), ("cron-job", "manual"), ("", "manual")):
        repo = _scenario(tmp_path, "pass")(f"r-{want}-{len(value)}")
        _run(repo, env={"METRICS_INVOKED_BY": value})
        assert _one_gate_record(repo)["invoked_by"] == want, value


# covers hub-tooling FR-0002:AC-4
def test_forced_and_draft_exempt_overrides_are_recorded_only_when_they_apply(tmp_path):
    repo = _scenario(tmp_path, "coverage-missing")("forced")
    _run(repo, env={"METRICS_GATE_OVERRIDE": "forced"})
    rec = _one_gate_record(repo)
    assert rec["forced"] is True and "draft_exempt" not in rec and rec["outcome"] == "fail"
    repo = _scenario(tmp_path, "coverage-missing")("exempt-red")
    _run(repo, env={"METRICS_GATE_OVERRIDE": "draft-exempt"})
    rec = _one_gate_record(repo)
    assert rec["draft_exempt"] is True and "forced" not in rec
    repo = _scenario(tmp_path, "pass")("exempt-green")
    _run(repo, env={"METRICS_GATE_OVERRIDE": "draft-exempt"})
    rec = _one_gate_record(repo)
    assert "draft_exempt" not in rec and "forced" not in rec  # nothing was overridden
    repo = _scenario(tmp_path, "pass")("bogus")
    _run(repo, env={"METRICS_GATE_OVERRIDE": "yolo"})
    assert "forced" not in _one_gate_record(repo)


# covers hub-tooling FR-0002:AC-4
def test_status_only_emits_nothing_and_leaves_a_committed_tree_clean(tmp_path):
    repo = _scenario(tmp_path, "pass")("r")
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    git = ["git", "-C", str(repo), "-c", "user.email=t@example.org", "-c", "user.name=t"]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True, capture_output=True)

    def files() -> list[str]:
        return sorted(
            p.relative_to(repo).as_posix() for p in repo.rglob("*")
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts
        )

    before = files()
    proc = _run(repo, "--status-only")
    assert proc.returncode == 0 and "Deploy gate PASSED" in proc.stdout, proc.stderr
    after = files()
    assert after == before  # no INDEX.md, no specs/_metrics/, nothing
    status = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    assert status.strip() == "", status
    # The plain run, by contrast, is what creates the (committed-by-design)
    # month file — the only thing it adds beyond specs/INDEX.md.
    proc = _run(repo)
    assert proc.returncode == 0
    status = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    assert sorted(ln.split()[-1] for ln in status.splitlines()) == ["specs/INDEX.md", "specs/_metrics/"]


# covers hub-tooling FR-0002:AC-4
def test_status_only_on_a_failing_tree_still_emits_nothing(tmp_path):
    repo = _scenario(tmp_path, "spec-validation")("r")
    proc = _run(repo, "--status-only")
    assert proc.returncode == 1
    assert _records(repo) == [] and not (repo / "specs" / "_metrics").exists()


# covers hub-tooling FR-0002:AC-4
def test_script_error_is_classified_and_the_exception_still_propagates(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("deploy_gate_under_test_fr0002", _SCRIPTS_DIR / "deploy-gate.py")
    gate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gate
    spec.loader.exec_module(gate)
    assert gate._metrics is metrics_log
    monkeypatch.setattr(metrics_log, "METRICS_DIR", tmp_path / "m")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)

    def explode(args, report):
        report.counts["frs"] = 3
        raise RuntimeError("indexer blew up")

    monkeypatch.setattr(gate, "_run_checks", explode)
    monkeypatch.setattr(sys, "argv", ["deploy-gate.py", "--stage", "dev"])
    with pytest.raises(RuntimeError, match="indexer blew up"):
        gate.main()
    [rec] = [json.loads(ln) for f in (tmp_path / "m").glob("*.ndjson") for ln in f.read_text(encoding="utf-8").splitlines()]
    assert rec["kind"] == "gate.run" and rec["outcome"] == "error" and rec["failure_classes"] == ["script-error"]
    assert rec["stage"] == "dev" and rec["counts"]["frs"] == 3
    # --status-only: still re-raised, still nothing written.
    shutil.rmtree(tmp_path / "m")
    monkeypatch.setattr(sys, "argv", ["deploy-gate.py", "--status-only"])
    with pytest.raises(RuntimeError):
        gate.main()
    assert not (tmp_path / "m").exists()


# ---------------------------------------------------------------------------
# AC-9: emission is never load-bearing (as seen from the gate)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-9
@pytest.mark.parametrize(
    "which", ["pass", "spec-validation", "covers-unknown-fr", "covers-unknown-ac", "coverage-missing", "two-failures",
              "implements-missing", "implements-unknown-fr", "ac-format"],
)
def test_every_branch_is_byte_identical_with_emission_on_and_off(tmp_path, which):
    off, on, on_repo = _run_twice(_scenario(tmp_path, which))
    assert (on.returncode, on.stdout, on.stderr) == (off.returncode, off.stdout, off.stderr)
    assert len(_records(on_repo)) == 1
    off2, on2, _ = _run_twice(_scenario(tmp_path, which), "--status-only")
    assert (on2.returncode, on2.stdout, on2.stderr) == (off2.returncode, off2.stdout, off2.stderr)


# covers hub-tooling FR-0002:AC-9
def test_unwritable_metrics_dir_yields_one_warn_line_and_nothing_else_changes(tmp_path):
    def build(name: str) -> Path:
        repo = _scenario(tmp_path, "pass")(name)
        (repo / "specs" / "_metrics").write_text("a file squatting on the directory name", encoding="utf-8")
        return repo

    off, on, on_repo = _run_twice(build)
    assert on.returncode == off.returncode == 0
    assert on.stdout == off.stdout
    extra = [ln for ln in on.stderr.splitlines() if ln not in off.stderr.splitlines()]
    assert len(extra) == 1 and extra[0].startswith("WARN: metrics:"), on.stderr
    assert on.stderr.count("WARN: metrics:") == 1
    assert (on_repo / "specs" / "_metrics").read_text(encoding="utf-8") == "a file squatting on the directory name"
    # A failing tree behaves the same way: same exit code, one WARN.
    def build_fail(name: str) -> Path:
        repo = _scenario(tmp_path, "coverage-missing")(name)
        (repo / "specs" / "_metrics").write_text("squatter", encoding="utf-8")
        return repo

    off, on, _ = _run_twice(build_fail)
    assert on.returncode == off.returncode == 1 and on.stdout == off.stdout
    assert on.stderr.count("WARN: metrics:") == 1


# covers hub-tooling FR-0002:AC-9
def test_gate_without_metrics_log_module_still_gates_identically(tmp_path):
    """A partially-upgraded project (scripts/ predates metrics_log.py) must
    gate exactly as before: the import is optional."""
    off, _on, _on_repo = _run_twice(_scenario(tmp_path, "pass"))
    stripped = _scenario(tmp_path, "pass")("stripped")
    (stripped / "scripts" / "metrics_log.py").unlink()
    proc = _run(stripped)
    assert (proc.returncode, proc.stdout, proc.stderr) == (off.returncode, off.stdout, off.stderr)
    assert _records(stripped) == []


# ---------------------------------------------------------------------------
# AC-12: INDEX.md metrics section — identical from indexer and gate
# ---------------------------------------------------------------------------


def _indexer(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "index-specs.py"), *args], capture_output=True, check=False, text=True, encoding="utf-8", env=env,
    )


def _with_log(repo: Path, *, poison: bool = False) -> None:
    d = repo / "specs" / "_metrics"
    d.mkdir(exist_ok=True)
    text = _FIXTURE.read_text(encoding="utf-8").replace("FR-0020", "FR-0100")
    if poison:
        bad = json.loads(text.splitlines()[0])
        bad["object_ids"] = 5  # not iterable -> the renderer's guarded exception path
        text += json.dumps(bad) + "\n"
    (d / "2026-08.ndjson").write_text(text, encoding="utf-8")


# covers hub-tooling FR-0002:AC-12
def test_index_with_records_is_byte_identical_from_indexer_and_gate_and_appends_one_row_per_fr(tmp_path):
    frs = {"FR-0100-a.md": _fr_markdown("FR-0100"), "FR-0101-b.md": _fr_markdown("FR-0101")}
    repo = _build_repo(tmp_path, frs)
    _with_log(repo)
    proc = _indexer(repo)
    assert proc.returncode == 0, proc.stderr
    from_indexer = (repo / "specs" / "INDEX.md").read_bytes()
    (repo / "specs" / "INDEX.md").unlink()
    proc = _run(repo)
    assert proc.returncode == 0, proc.stderr
    from_gate = (repo / "specs" / "INDEX.md").read_bytes()
    assert from_gate == from_indexer
    text = from_gate.decode("utf-8").replace("\r\n", "\n")
    assert text.count("## Pipeline metrics") == 1
    section = text.split("## Pipeline metrics", 1)[1]
    rows = [ln for ln in section.splitlines() if ln.startswith("| FR-")]
    assert rows == [
        (
            "| FR-0100 | architect: success, dev: success, rev: success | 150 | "
            "1 rework, 18 tool errors, 3 gate fails (coverage-missing, covers-unknown-ac, spec-validation) | pass | #42 |"
        )
    ]  # FR-0101 has no records -> no row
    assert text.rstrip("\n").endswith(rows[-1])  # the section is the last thing in the file


# covers hub-tooling FR-0002:AC-12
def test_index_without_records_is_byte_identical_to_a_project_without_the_log(tmp_path):
    frs = {"FR-0100-a.md": _fr_markdown("FR-0100")}
    no_dir = _build_repo(tmp_path, frs, name="no-dir")
    empty_dir = _build_repo(tmp_path, frs, name="empty-dir")
    (empty_dir / "specs" / "_metrics").mkdir()
    (empty_dir / "specs" / "_metrics" / "2026-08.ndjson").write_text("", encoding="utf-8")
    orphan = _build_repo(tmp_path, frs, name="orphan")
    (orphan / "specs" / "_metrics").mkdir()
    (orphan / "specs" / "_metrics" / "2026-08.ndjson").write_text(
        json.dumps({"schema_version": 1, "record_id": "x" * 32, "ts": "2026-08-01T00:00:00Z", "project": "p", "kind": "gate.run",
                    "source": "gate", "role": None, "object_ids": [], "run_id": None, "stage": "full", "outcome": "pass",
                    "failure_classes": [], "warning_classes": [], "counts": {"frs": 0, "covers": 0, "implements": 0},
                    "invoked_by": "manual"}) + "\n",
        encoding="utf-8",
    )
    outputs = {}
    for repo in (no_dir, empty_dir, orphan):
        assert _indexer(repo).returncode == 0
        outputs[(repo.name, "indexer")] = (repo / "specs" / "INDEX.md").read_bytes()
        (repo / "specs" / "INDEX.md").unlink()
        assert _run(repo).returncode == 0
        outputs[(repo.name, "gate")] = (repo / "specs" / "INDEX.md").read_bytes()
    assert len(set(outputs.values())) == 1, "INDEX.md differs across no-log / empty-log / orphan-only-log or indexer / gate"
    assert b"Pipeline metrics" not in next(iter(outputs.values()))
    # And the with-records index is the no-records index plus the section.
    with_log = _build_repo(tmp_path, frs, name="with-log")
    _with_log(with_log)
    _indexer(with_log)
    # read_text() normalises the indexer's platform newlines; do the same to the raw baseline bytes.
    text = (with_log / "specs" / "INDEX.md").read_text(encoding="utf-8")
    base = next(iter(outputs.values())).decode("utf-8").replace("\r\n", "\n")
    assert text.startswith(base.rstrip("\n")) and "\n## Pipeline metrics\n" in text[len(base.rstrip("\n")):]


# covers hub-tooling FR-0002:AC-12
def test_validate_ac_hashes_and_query_modes_never_read_the_log(tmp_path):
    repo = _build_repo(tmp_path, {"FR-0100-a.md": _fr_markdown("FR-0100")})
    _with_log(repo, poison=True)
    plain = _indexer(repo)
    assert plain.returncode == 0
    assert plain.stderr.count("WARN: metrics:") == 1 and "metrics section skipped" in plain.stderr
    assert b"Pipeline metrics" not in (repo / "specs" / "INDEX.md").read_bytes()  # skipped as a whole, index still written
    for args in (("--validate",), ("--ac-hashes",), ("--ac-hashes", "FR-0100"), ("--list", "fr"), ("--slice", "FR-0100"), ("--provisional",)):
        proc = _indexer(repo, *args)
        assert proc.returncode == 0, (args, proc.stderr)
        assert "metrics" not in proc.stderr.lower(), (args, proc.stderr)
    assert _run(repo, "--status-only").stderr.count("WARN: metrics:") == 0


# ---------------------------------------------------------------------------
# AC-13: PHI guard as seen from the gate under an active profile
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0002:AC-13
def test_gate_record_matching_the_profile_hook_is_dropped_with_one_warn_and_nothing_else_changes(tmp_path):
    def build(name: str) -> Path:
        repo = _scenario(tmp_path, "pass")(name)
        hook = repo / ".agent-team" / "hooks" / "phi_regex_check.py"
        hook.parent.mkdir(parents=True)
        hook.write_text(_PHI_HOOK_SOURCE, encoding="utf-8")
        return repo

    off, on, on_repo = _run_twice(build, env={"METRICS_PROJECT": "clinic 123-456-789"})
    assert (on.returncode, on.stdout) == (off.returncode, off.stdout)
    extra = [ln for ln in on.stderr.splitlines() if ln not in off.stderr.splitlines()]
    assert len(extra) == 1 and extra[0].startswith("WARN: metrics: gate.run record dropped: matched Possible Canadian SIN"), on.stderr
    assert _records(on_repo) == [] and not (on_repo / "specs" / "_metrics").exists()
    # A clean project name under the same hook is appended normally.
    clean = build("clean")
    proc = _run(clean, env={"METRICS_PROJECT": "clinic-tooling"})
    assert proc.returncode == 0 and proc.stderr.count("WARN: metrics:") == 0
    assert _one_gate_record(clean)["project"] == "clinic-tooling"
