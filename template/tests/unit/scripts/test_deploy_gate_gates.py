"""Reviewer tests for FR-0008 — the deploy gate's declared-gate evidence lint
(AC-9) and the `gate.decision` metrics kind (AC-11).

Harness: the same shape as `test_deploy_gate_metrics.py` — the team scripts are
copied into a self-contained temporary git repo and the gate is driven through
`subprocess`, so exit code, stdout, stderr, the emitted `gate.run` record and
the files on disk are all observable. `dispatch.py` travels too, because the
lint reads gate evidence through its `gate_status` (AC-2's single reader); one
test deliberately omits it to pin the optional-import contract.

Coverage annotations are written `# covers hub-tooling FR-0008:AC-N` rather than
the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0008 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (IDEA-0061).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

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
_GATES_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "gates"

# Spelled in two halves so a bootstrapped project's `deploy-gate.py`, which
# regex-scans every file under tests/, does not read these as real annotations.
_COVERS = "@" + "covers"

# deploy-gate imports index-specs (-> spec_footprint, spec_query, metrics_log);
# FR-0008:AC-9 adds the optional dispatch import (-> env_preflight,
# stack_profile).
_BASE_SCRIPTS = (
    "deploy-gate.py",
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
)
_DISPATCH_SCRIPTS = ("dispatch.py", "env_preflight.py", "stack_profile.py")
_METRICS_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
)

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log

_FR = "FR-0100"
_GATE = "design-review"
_REV_GATE = "release-review"

_DEV_GATE_BLOCK = f"""gates:
  - id: {_GATE}
    after: dev
    reviewer: human
    scope: The human signs off the rendered screens before the Reviewer runs.
"""
_REV_GATE_BLOCK = f"""gates:
  - id: {_REV_GATE}
    after: rev
    reviewer: human
    scope: A pre-merge gate only.
"""
#: Satisfies the pre-existing `coverage-missing` check so a `merged` FR's
#: exit code reflects the FR-0008 gate lint and nothing else.
_COVERING_TEST = {
    "test_x.py": "\n".join(
        [
            f"# {_COVERS} {_FR}:AC-1",
            f"# {_COVERS} {_FR}:AC-2",
            "def test_x():",
            "    pass",
            "",
        ]
    )
}

_BOTH_GATES_BLOCK = f"""gates:
  - id: {_GATE}
    after: dev
    reviewer: human
    scope: The human signs off the rendered screens before the Reviewer runs.
  - id: {_REV_GATE}
    after: rev
    reviewer: human
    scope: A pre-merge gate only.
"""


def _fr_markdown(fr_id: str = _FR, *, status: str = "ready", gates: str = "") -> str:
    extra = f"{gates.rstrip()}\n" if gates.strip() else ""
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
owns: []
reads: []
derived_from: null
pattern: null
ac_state: {{}}
{extra}created: 2026-01-01
updated: 2026-01-01
---

# {fr_id}: Synthetic

## Acceptance criteria

- **AC-1:** does the first thing
- **AC-2:** does the second thing
"""


def _evidence(
    fr_id: str,
    gate: str,
    verdict: str,
    head_sha: str = "a" * 39 + "1",
    body: str = "Synthetic rationale.",
) -> str:
    """`body=""` is the shape AC-3's bare `gate pass` (no `--note`) writes."""
    return (
        "---\n"
        f"fr: {fr_id}\n"
        f"gate: {gate}\n"
        f"verdict: {verdict}\n"
        "by: Neil\n"
        "date: 2026-01-02\n"
        "round: 1\n"
        f"head_sha: {head_sha}\n"
        "---\n"
        f"\n{body}\n"
    )


def _build_repo(
    tmp_path: Path,
    fr_files: dict[str, str],
    *,
    gates_evidence: dict[str, str] | None = None,
    tests: dict[str, str] | None = None,
    with_dispatch: bool = True,
    name: str = "repo",
) -> Path:
    repo = tmp_path / name
    (repo / "scripts").mkdir(parents=True)
    scripts = _BASE_SCRIPTS + (_DISPATCH_SCRIPTS if with_dispatch else ())
    for script in scripts:
        shutil.copy(_SCRIPTS_DIR / script, repo / "scripts" / script)
    (repo / "specs").mkdir()
    for filename, content in fr_files.items():
        (repo / "specs" / filename).write_text(content, encoding="utf-8", newline="\n")
    for filename, content in (gates_evidence or {}).items():
        d = repo / "specs" / "_gates"
        d.mkdir(exist_ok=True)
        (d / filename).write_text(content, encoding="utf-8", newline="\n")
    if tests:
        (repo / "tests").mkdir()
        for filename, content in tests.items():
            (repo / "tests" / filename).write_text(
                content, encoding="utf-8", newline="\n"
            )
    # `gate_status(ref=None)` reads the working tree, but dispatch.py still
    # shells out to git for its branch lookups, so a real repo keeps the lint
    # on its intended path rather than an error path.
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
    ):
        subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    return repo


def _run(repo: Path, *args: str, env: dict[str, str] | None = None):
    full_env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    full_env["METRICS_PROJECT"] = "synthetic-project"
    full_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "deploy-gate.py"), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=full_env,
    )


def _records(repo: Path) -> list[dict]:
    d = repo / "specs" / "_metrics"
    if not d.exists():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.ndjson")):
        out.extend(
            json.loads(ln)
            for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        )
    return out


def _one_gate_record(repo: Path) -> dict:
    recs = [r for r in _records(repo) if r["kind"] == "gate.run"]
    assert len(recs) == 1, recs
    assert metrics_log.validation_errors(recs[0]) == [], recs[0]
    return recs[0]


# ---------------------------------------------------------------------------
# AC-9: merged requires every gate; in-review requires the `after: dev` ones
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-9
@pytest.mark.parametrize("stage", ["review", "full"])
def test_merged_fr_without_gate_evidence_fails_naming_the_fr_and_the_gate(
    tmp_path, stage
):
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        name=f"repo-{stage}",
    )
    proc = _run(repo, "--stage", stage)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    combined = proc.stdout + proc.stderr
    assert _FR in combined and _GATE in combined
    assert "missing" in combined and "expected pass" in combined
    rec = _one_gate_record(repo)
    assert rec["outcome"] == "fail"
    assert "gate-evidence-missing" in rec["failure_classes"]
    assert set(rec["failure_classes"]) <= metrics_log.GATE_FAILURE_CLASSES


# covers hub-tooling FR-0008:AC-9
def test_merged_fr_with_passing_evidence_clears_the_lint(tmp_path):
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_BOTH_GATES_BLOCK)},
        gates_evidence={
            f"{_FR}-{_GATE}.md": _evidence(_FR, _GATE, "pass"),
            f"{_FR}-{_REV_GATE}.md": _evidence(_FR, _REV_GATE, "pass"),
        },
    )
    proc = _run(repo, "--stage", "full")
    combined = proc.stdout + proc.stderr
    assert "gate '" not in combined, combined
    assert "evidence is" not in combined, combined
    rec = _one_gate_record(repo)
    assert "gate-evidence-missing" not in rec["failure_classes"]
    assert "gate-evidence-stale" not in rec["failure_classes"]


# covers hub-tooling FR-0008:AC-9
def test_merged_fr_needs_every_gate_including_the_after_rev_one(tmp_path):
    """Adversarial: `merged` is the strict case — an `after: rev` gate counts
    too, so satisfying only the `after: dev` one is still a failure."""
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_BOTH_GATES_BLOCK)},
        gates_evidence={f"{_FR}-{_GATE}.md": _evidence(_FR, _GATE, "pass")},
    )
    proc = _run(repo, "--stage", "full")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert _REV_GATE in combined
    assert f"gate '{_GATE}'" not in combined  # the satisfied one is not reported


# covers hub-tooling FR-0008:AC-9
def test_in_review_fr_requires_only_its_after_dev_gates(tmp_path):
    """The `in-review` case is the narrow one: an unsatisfied `after: rev` gate
    is fine (it is a pre-merge gate), an unsatisfied `after: dev` gate is not."""
    ok = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="in-review", gates=_REV_GATE_BLOCK)},
        name="rev-only",
    )
    proc = _run(ok, "--stage", "full")
    assert "evidence is" not in (proc.stdout + proc.stderr)

    bad = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="in-review", gates=_BOTH_GATES_BLOCK)},
        gates_evidence={f"{_FR}-{_REV_GATE}.md": _evidence(_FR, _REV_GATE, "pass")},
        name="dev-missing",
    )
    proc = _run(bad, "--stage", "full")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert f"gate '{_GATE}'" in combined
    assert f"gate '{_REV_GATE}'" not in combined


# covers hub-tooling FR-0008:AC-9
@pytest.mark.parametrize("verdict", ["changes-requested"])
def test_a_changes_requested_verdict_is_not_a_pass(tmp_path, verdict):
    """Adversarial: the lint asks for `pass`, not "some evidence exists"."""
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        gates_evidence={f"{_FR}-{_GATE}.md": _evidence(_FR, _GATE, verdict)},
    )
    proc = _run(repo, "--stage", "full")
    assert proc.returncode == 1
    assert verdict in (proc.stdout + proc.stderr)
    assert "gate-evidence-missing" in _one_gate_record(repo)["failure_classes"]


# covers hub-tooling FR-0008:AC-9
def test_dev_stage_demotes_the_same_condition_to_a_warning(tmp_path):
    repo = _build_repo(
        tmp_path, {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)}
    )
    proc = _run(repo, "--stage", "dev")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    combined = proc.stdout + proc.stderr
    assert _GATE in combined and "missing" in combined
    rec = _one_gate_record(repo)
    assert rec["outcome"] == "pass"
    assert rec["failure_classes"] == []
    # The warning classes stay FR-0002's fixed enum: a gate miss is not one.
    assert set(rec["warning_classes"]) <= metrics_log.GATE_WARNING_CLASSES
    assert "gate-evidence-missing" not in rec["warning_classes"]


# covers hub-tooling FR-0008:AC-9
# covers hub-tooling FR-0008:AC-13
@pytest.mark.parametrize(
    "status", ["ready", "draft", "in-progress", "merged", "in-review"]
)
def test_an_fr_with_no_gates_adds_nothing_to_the_report_at_any_status(tmp_path, status):
    """AC-13: identical deploy-gate results for a gate-free FR."""
    with_d = _build_repo(
        tmp_path, {f"{_FR}-x.md": _fr_markdown(status=status)}, name=f"d-{status}"
    )
    without_d = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status=status)},
        with_dispatch=False,
        name=f"n-{status}",
    )
    a = _run(with_d, "--stage", "full", env={"METRICS_LOG_DISABLED": "1"})
    b = _run(without_d, "--stage", "full", env={"METRICS_LOG_DISABLED": "1"})
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)
    assert "gate '" not in (a.stdout + a.stderr)


# covers hub-tooling FR-0008:AC-9
def test_the_lint_is_skipped_not_fatal_when_there_is_no_sibling_dispatch_py(tmp_path):
    """Adversarial, the optional-import contract: a project whose `scripts/`
    predates FR-0008 still gates. The lint is skipped, never a hard failure."""
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        tests=_COVERING_TEST,
        with_dispatch=False,
    )
    proc = _run(repo, "--stage", "full")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    combined = proc.stdout + proc.stderr
    assert "gate-evidence-missing" not in combined
    assert "Traceback" not in combined
    rec = _one_gate_record(repo)
    assert rec["outcome"] == "pass" and rec["failure_classes"] == []


# covers hub-tooling FR-0008:AC-9
def test_both_new_failure_classes_are_in_the_fixed_enum_and_are_reachable(tmp_path):
    """The complement of DEC-0012 item 2(f): `test_deploy_gate_metrics.py`'s
    source scrape cannot see these two (they are emitted through a computed
    local), so their reachable branches are pinned here instead — one by the
    tests above, one by the stale branch below."""
    assert {
        "gate-evidence-missing",
        "gate-evidence-stale",
    } <= metrics_log.GATE_FAILURE_CLASSES
    source = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    assert (
        '"gate-evidence-stale" if gstatus == "stale" else "gate-evidence-missing"'
        in source
    )
    assert "report.fail(cls, msg)" in source


# covers hub-tooling FR-0008:AC-9
def test_a_stale_pass_is_classified_as_gate_evidence_stale(tmp_path):
    """The `gate-evidence-stale` branch: evidence whose `verdict: pass` names a
    `head_sha` that is not an ancestor-or-equal of the implementation branch's
    tip. Built by giving the FR a real `claude/dev-<FR>` branch and a SHA from
    a sibling branch that the dev branch never contained."""
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        name="stale",
    )
    g = ["git", "-C", str(repo)]
    subprocess.run([*g, "branch", "-q", f"claude/dev-{_FR}"], check=True)
    subprocess.run([*g, "commit", "-q", "--allow-empty", "-m", "unrelated"], check=True)
    orphan = subprocess.run(
        [*g, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "specs" / "_gates").mkdir(exist_ok=True)
    (repo / "specs" / "_gates" / f"{_FR}-{_GATE}.md").write_text(
        _evidence(_FR, _GATE, "pass", head_sha=orphan), encoding="utf-8", newline="\n"
    )
    proc = _run(repo, "--stage", "full")
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "stale" in combined and _GATE in combined
    rec = _one_gate_record(repo)
    assert "gate-evidence-stale" in rec["failure_classes"]
    assert "gate-evidence-missing" not in rec["failure_classes"]


# ---------------------------------------------------------------------------
# AC-11: the `gate.decision` record validates against the unmodified validator
# ---------------------------------------------------------------------------


def _decision(**over) -> dict:
    rec = {
        "schema_version": 1,
        "record_id": "f" * 32,
        "ts": "2026-08-03T10:18:00Z",
        "project": "synthetic-project",
        "kind": "gate.decision",
        "source": "dispatch",
        "role": "gat",
        "object_ids": [_FR],
        "run_id": None,
        "gate": _GATE,
        "after": "dev",
        "reviewer": "architect",
        "verdict": "pass",
        "by": "architect",
        "round": 1,
        "head_sha": "a" * 39 + "1",
    }
    rec.update(over)
    return rec


# covers hub-tooling FR-0008:AC-11
def test_a_well_formed_gate_decision_validates():
    assert metrics_log.validation_errors(_decision()) == []
    assert "gate.decision" in metrics_log.KINDS
    assert "gat" in metrics_log.ROLES
    assert metrics_log.normalise_role("gate-review") == "gat"


# covers hub-tooling FR-0008:AC-11
@pytest.mark.parametrize(
    "field", ("gate", "after", "reviewer", "verdict", "by", "round", "head_sha")
)
def test_every_required_field_is_enforced(field):
    """Adversarial: AC-11 names seven required fields. Dropping any one of them
    is a validation error."""
    rec = _decision()
    del rec[field]
    errors = metrics_log.validation_errors(rec)
    assert errors, field
    assert any(field in e for e in errors), (field, errors)


# covers hub-tooling FR-0008:AC-11
@pytest.mark.parametrize(
    "over",
    [
        {"after": "merge"},
        {"after": None},
        {"reviewer": "docs"},
        {"verdict": "approved"},
        {"verdict": "blocked"},
        {"gate": ""},
        {"gate": 7},
        {"by": ""},
        {"round": 0},
        {"round": -1},
        {"round": "1"},
        {"round": True},
        {"head_sha": 42},
        {"role": "gate"},
    ],
)
def test_out_of_vocabulary_and_wrong_typed_values_are_rejected(over):
    assert metrics_log.validation_errors(_decision(**over)), over


# covers hub-tooling FR-0008:AC-11
def test_the_three_verdicts_and_both_vocabularies_are_accepted():
    for verdict in ("pass", "changes-requested", "bypassed"):
        assert metrics_log.validation_errors(_decision(verdict=verdict)) == [], verdict
    for after in ("dev", "rev"):
        assert metrics_log.validation_errors(_decision(after=after)) == [], after
    for reviewer in ("human", "architect"):
        assert metrics_log.validation_errors(_decision(reviewer=reviewer)) == [], (
            reviewer
        )
    # `head_sha` is the one nullable member (a bypass may have no tip to name).
    assert metrics_log.validation_errors(_decision(head_sha=None)) == []


# covers hub-tooling FR-0008:AC-11
# covers hub-tooling FR-0008:AC-13
def test_no_other_kinds_required_fields_or_enums_moved():
    """AC-11's last sentence, asserted literally: the other ten kinds keep the
    exact required-field tuples they had, and every pre-FR-0008 enum member is
    still present."""
    assert metrics_log.KIND_REQUIRED["gate.decision"] == (
        "gate",
        "after",
        "reviewer",
        "verdict",
        "by",
        "round",
        "head_sha",
    )
    assert metrics_log.KIND_REQUIRED["dispatch.spawn"] == (
        "harness",
        "worktree_status",
        "base_branch",
        "model",
        "round",
    )
    assert metrics_log.KIND_REQUIRED["pr.merged"] == ("pr_number", "merge_sha")
    assert metrics_log.KIND_REQUIRED["escalation"] == ("trigger_class",)
    assert set(metrics_log.KINDS) - {"gate.decision"} == {
        "dispatch.spawn",
        "dispatch.run",
        "dispatch.wave",
        "gate.run",
        "pr.opened",
        "pr.refreshed",
        "pr.review",
        "pr.merged",
        "escalation",
        "escalation.resolved",
    }
    assert set(metrics_log.ROLES) - {"gat"} == {
        "architect",
        "dev",
        "rev",
        "bkf",
        "mnt",
        "docs",
        "orchestrator",
    }
    assert metrics_log.SOURCES == {"dispatch", "gate", "escalation-log", "manual"}
    assert set(metrics_log.GATE_FAILURE_CLASSES) - {
        "gate-evidence-missing",
        "gate-evidence-stale",
    } == {
        "spec-validation",
        "covers-unknown-fr",
        "covers-malformed-ac",
        "covers-unknown-ac",
        "coverage-missing",
        "script-error",
    }
    assert metrics_log.GATE_WARNING_CLASSES == {
        "implements-missing",
        "implements-unknown-fr",
        "ac-format",
        "ac-exemption-invalid",  # FR-0026 AC-12
        "ac-all-exempt",  # FR-0026 AC-12
    }


# covers hub-tooling FR-0008:AC-11
def test_the_metrics_readme_documents_the_new_kind_and_the_two_failure_classes():
    """FR-0002:AC-14's home, which FR-0008 owns: every field and kind names the
    AC that introduced it."""
    readme = (_TEMPLATE_DIR / "specs" / "_metrics" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "gate.decision" in readme
    for field in ("gate", "after", "reviewer", "verdict", "by", "round", "head_sha"):
        assert field in readme, field
    assert "gate-evidence-missing" in readme and "gate-evidence-stale" in readme
    assert "FR-0008" in readme


# covers hub-tooling FR-0008:AC-11
def test_the_shipped_fixture_models_the_new_kind():
    """FR-0002:AC-14's shipped fixture must still model every kind, which is
    why DEC-0012 item 2(e) adds exactly one `gate.decision` line to it."""
    fixture = _TEMPLATE_DIR / "tests" / "fixtures" / "metrics" / "2026-08.ndjson"
    raw = fixture.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    recs = [json.loads(ln) for ln in raw.decode("utf-8").splitlines() if ln.strip()]
    decisions = [r for r in recs if r["kind"] == "gate.decision"]
    assert len(decisions) == 1
    (d,) = decisions
    assert metrics_log.validation_errors(d) == []
    assert d["role"] == "gat" and d["verdict"] == "pass"
    assert {r["kind"] for r in recs} == set(metrics_log.KINDS)
    # Inserted in `ts` order, nothing reordered.
    assert [r["ts"] for r in recs] == sorted(r["ts"] for r in recs)
    assert len({r["record_id"] for r in recs}) == len(recs)


# ---------------------------------------------------------------------------
# Round 2: bare-invocation pins — the lint driven with required arguments only,
# over the evidence shape AC-3's bare `gate pass` actually writes (no `--note`,
# so no body). Round 4 found the `ref`-based reader could not parse that shape;
# the deploy gate reads the working tree instead, and these pin that the shape
# is readable there too rather than assuming it.
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-9
def test_body_less_evidence_clears_the_lint_exactly_as_evidence_with_a_note(
    tmp_path,
):
    """Evidence written by `gate pass <FR> <gate-id> --by <who> --apply` has an
    empty body. AC-9's `merged` case must clear on it, and a body-less
    `changes-requested` must still fail — the body is not what carries the
    verdict."""
    ok = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        gates_evidence={f"{_FR}-{_GATE}.md": _evidence(_FR, _GATE, "pass", body="")},
        tests=_COVERING_TEST,
        name="bodyless-pass",
    )
    proc = _run(ok, "--stage", "full")
    combined = proc.stdout + proc.stderr
    assert "evidence is" not in combined, combined
    assert proc.returncode == 0, combined

    bad = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        gates_evidence={
            f"{_FR}-{_GATE}.md": _evidence(_FR, _GATE, "changes-requested", body="")
        },
        tests=_COVERING_TEST,
        name="bodyless-block",
    )
    proc = _run(bad, "--stage", "full")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert _GATE in combined and "expected pass" in combined


# covers hub-tooling FR-0008:AC-9
# covers hub-tooling FR-0008:AC-13
def test_the_bare_deploy_gate_invocation_runs_the_lint_at_stage_full(tmp_path):
    """`deploy-gate.py` has no required arguments; `--stage` defaults to
    `full`. The bare invocation — the one AGENTS.md tells every role to run
    before claiming done — must therefore carry the FR-0008 lint, byte for byte
    as `--stage full` does."""
    repo = _build_repo(
        tmp_path,
        {f"{_FR}-x.md": _fr_markdown(status="merged", gates=_DEV_GATE_BLOCK)},
        tests=_COVERING_TEST,
        name="bare",
    )
    bare = _run(repo, "--status-only")
    staged = _run(repo, "--status-only", "--stage", "full")
    assert bare.returncode == staged.returncode == 1
    assert bare.stdout == staged.stdout
    assert _GATE in bare.stdout + bare.stderr
    assert "expected pass" in bare.stdout + bare.stderr
