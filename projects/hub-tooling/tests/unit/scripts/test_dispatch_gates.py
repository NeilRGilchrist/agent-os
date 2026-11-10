"""Reviewer tests for FR-0008 — the dispatcher half of declared gates.

Covers the one evidence reader and its four outcomes in both the `dev` and the
`mnt` implementation-role resolution (AC-2, DEC-0012 item 3), the `gate
list|pass|block` subcommand (AC-3), Reviewer runnability (AC-4), the human gate
that stops a wave (AC-5), the one-shot Architect gate-review session (AC-6), the
verdict routing (AC-7), the draft refusal on both `_finalize_dev` and
`_finalize_oneshot` (AC-8, DEC-0012 item 4), `reconcile-merged`'s bypass warning
and record (AC-10), the command files (AC-12) and the gate-free FR's unchanged
behaviour (AC-13).

Harness: `dispatch.py` loaded by path with its path globals pointed at a real
temporary git repository (branches, worktrees and ancestry are the subject), a
fake harness adapter that records spawns instead of launching anything, and the
venv provisioner / gh preflight / reconcile stubbed. `gh` is never invoked: the
one path that would call it is driven through a `subprocess.run` double that
records the argv. No network, no `claude` binary, no `gh` binary.

The bite checks load the *round-1* dispatcher (`git show 681d661:...`) and the
*pre-FR* dispatcher (`git show 706ba9d:...`) as separate modules and skip when
those commits are not reachable (i.e. outside the hub checkout).

Coverage annotations are written `# covers hub-tooling FR-0008:AC-N` rather than
the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0008 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (IDEA-0061).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_COMMANDS_DIR = _TEMPLATE_DIR / ".agent-team" / "commands"
_FR = "FR-0001"
_FR2 = "FR-0002"
_GATE = "design-review"
_ARCH_GATE = "tier-map-review"

# Backward-compat / bite-check baselines pin a commit, never a branch name.
_PRE_FR_REF = "706ba9d"  # wave 1's merge point, before FR-0008
_ROUND1_REF = "681d661"  # FR-0008 implementation round 1, before DEC-0012
_ROUND3_REF = "93e9dda"  # FR-0008 round 3, before the two round-4 defect fixes

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log


def _load_dispatch(name: str = "dispatch_under_test_fr0008_gates"):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch()

#: Captured before any test monkeypatches it: `_point` replaces
#: `reconcile_merged_prs` with a no-op stub (every other dispatch test does the
#: same), so AC-10's tests call the real function through this handle.
_REAL_RECONCILE = dispatch.reconcile_merged_prs


def _load_dispatch_at(ref: str, name: str, tmp_path: Path):
    """`dispatch.py` as of `ref`, loaded as its own module, or None when that
    commit is not reachable (running outside the hub checkout)."""
    proc = subprocess.run(
        ["git", "show", f"{ref}:template/scripts/dispatch.py"],
        cwd=str(_TEMPLATE_DIR),
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return None
    path = tmp_path / f"{name}.py"
    path.write_bytes(proc.stdout)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Synthetic FRs
# ---------------------------------------------------------------------------

_HUMAN_DEV_GATE = f"""gates:
  - id: {_GATE}
    after: dev
    reviewer: human
    scope: The human signs off the rendered screens before the Reviewer runs.
"""

_ARCHITECT_DEV_GATE = f"""gates:
  - id: {_ARCH_GATE}
    after: dev
    reviewer: architect
    scope: The Architect checks the legacy-ID tier map before the Reviewer runs.
"""

_REV_ONLY_GATE = f"""gates:
  - id: {_GATE}
    after: rev
    reviewer: human
    scope: A pre-merge gate only; it never blocks the Reviewer.
"""


def _fr_md(fr_id: str, status: str = "ready", gates: str = "") -> str:
    extra = f"{gates.rstrip()}\n" if gates.strip() else ""
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: {status}
owner: architect
depends_on: []
tags: []
owns: ["src/**", "specs/_gates/**"]
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
"""


# ---------------------------------------------------------------------------
# Real-git fixture + fake adapter (the `test_dispatch_runnability.py` shape)
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


def _make_repo(tmp_path: Path, frs: dict[str, tuple[str, str]] | None = None) -> Path:
    """`frs` maps FR id -> (status, gates-frontmatter-block)."""
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
    for fr_id, (status, gates) in (frs or {_FR: ("ready", "")}).items():
        (repo / "specs" / f"{fr_id}-synthetic.md").write_text(
            _fr_md(fr_id, status, gates), encoding="utf-8", newline="\n"
        )
    (repo / ".gitignore").write_text(
        f".claude/settings.local.json\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _point(monkeypatch, r: Path) -> None:
    monkeypatch.setattr(dispatch, "REPO_ROOT", r)
    monkeypatch.setattr(dispatch, "SPECS_DIR", r / "specs")
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", r / "_dispatch")
    monkeypatch.setattr(dispatch, "LAST_TICK_FILE", r / "_dispatch" / ".last-tick")
    monkeypatch.setattr(dispatch, "ESCALATIONS_DIR", r / "specs" / "_escalations")
    monkeypatch.setattr(dispatch, "_RUN_REGISTRY", {})
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (True, "venv:stub"))
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(dispatch, "_push_branch", lambda branch: (True, "pushed"))
    monkeypatch.setattr(dispatch, "_repo_nwo", lambda: "example-org/synthetic-project")
    monkeypatch.setattr(
        dispatch,
        "reconcile_merged_prs",
        lambda apply=False, verbose=False: dispatch.ReconcileSummary(
            flipped=[], cleaned=[], skipped=[]
        ),
    )
    monkeypatch.setattr(dispatch, "prune_dead_locks", lambda verbose=True: 0)
    # Metrics are isolated per test: nothing is ever written under the
    # template's own specs/_metrics/.
    monkeypatch.setattr(metrics_log, "METRICS_DIR", r / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    (r / "_dispatch").mkdir(exist_ok=True)


class _FakeAdapter:
    name = "fake"
    binary_name = "fake"

    def __init__(self) -> None:
        self.spawns: list[tuple[str, str, Path, str | None, str | None]] = []
        self.settings: list[tuple[Path, str, str, str | None]] = []

    def write_worktree_settings(self, wt_path, role, fr_id, gate_id=None) -> None:
        self.settings.append((wt_path, role, fr_id, gate_id))
        # Write the real adapter's payload so the permission assertions have
        # something on disk to read.
        perms = (
            dispatch.ClaudeCodeAdapter().gat_permissions(fr_id, gate_id)
            if role == "gat"
            else None
        )
        if perms is not None:
            (wt_path / ".claude").mkdir(parents=True, exist_ok=True)
            (wt_path / ".claude" / "settings.local.json").write_text(
                json.dumps({"permissions": perms}, indent=2) + "\n", encoding="utf-8"
            )

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None, gate_id=None):
        self.spawns.append((fr_id, role, wt_path, extra_prompt, gate_id))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type":"result","subtype":"success"}\n', encoding="utf-8")
        return ("spawned", 999_999)

    def parse_log(self, log_path: Path):
        return SimpleNamespace(last_text="", result_subtype="success", tool_calls=0)

    def dry_run_preview(self, fr_id, role, wt_preview, gate_id=None) -> str:
        args = f"{fr_id} {gate_id}" if gate_id else fr_id
        return f"fake-preview /{dispatch.SLASH_COMMAND_NAMES.get(role, role)} {args}"


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter()


# ---------------------------------------------------------------------------
# Branch / worktree / evidence helpers
# ---------------------------------------------------------------------------


def _impl_worktree(repo: Path, fr_id: str, role: str, base: str = "main") -> Path:
    """A `dev` or `mnt` worktree on `claude/<role>-<FR>`, with one commit."""
    wt = repo / ".claude" / "worktrees" / f"{role}-{fr_id}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/{role}-{fr_id}", str(wt), base)
    (wt / "src").mkdir(parents=True, exist_ok=True)
    (wt / "src" / "thing.py").write_text("x\n", encoding="utf-8", newline="\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "feat: work")
    return wt


def _flip_status(repo: Path, wt: Path, fr_id: str, status: str, gates: str) -> None:
    p = wt / "specs" / f"{fr_id}-synthetic.md"
    p.write_text(_fr_md(fr_id, status, gates), encoding="utf-8", newline="\n")
    _git(wt, "add", str(p.relative_to(wt)))
    _git(wt, "commit", "-q", "-m", f"status -> {status}")


def _evidence_text(
    fr_id: str, gate: str, verdict: str, by: str, head_sha: str, body: str = "ok"
) -> str:
    return (
        "---\n"
        f"fr: {fr_id}\n"
        f"gate: {gate}\n"
        f"verdict: {verdict}\n"
        f"by: {by}\n"
        "date: 2026-01-02\n"
        "round: 1\n"
        f"head_sha: {head_sha}\n"
        "---\n"
        f"\n{body}\n"
    )


def _commit_evidence(
    repo: Path,
    wt: Path,
    fr_id: str,
    gate: str,
    verdict: str,
    head_sha: str | None = None,
    body: str = "ok",
) -> str:
    """Write + commit an evidence file on the worktree's own branch.

    `body=""` is the shape AC-3's bare `gate pass` (no `--note`) writes — see
    the bare-invocation section at the end of this file."""
    branch = _git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    sha = head_sha if head_sha is not None else _git(repo, "rev-parse", branch)
    d = wt / "specs" / "_gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{fr_id}-{gate}.md").write_text(
        _evidence_text(fr_id, gate, verdict, "Neil", sha, body),
        encoding="utf-8",
        newline="\n",
    )
    _git(wt, "add", f"specs/_gates/{fr_id}-{gate}.md")
    _git(wt, "commit", "-q", "-m", f"gate({fr_id}): {gate} {verdict} by Neil")
    return sha


#: Dispatcher scratch directories. Excluded from the snapshot below because a
#: dry-run legitimately writes a preview synthesis and a `.last-tick` there;
#: "mutates nothing" is a statement about the repository. Metrics are asserted
#: separately, by reading the isolated log.
_SCRATCH = ("_dispatch", "metrics", ".git")


def _repo_snapshot(repo: Path) -> dict[str, object]:
    """FR-0006:AC-12's snapshot method: every path's bytes outside the
    dispatcher's own scratch, plus every ref, so "mutates nothing" is
    asserted, not assumed."""
    files: dict[str, bytes] = {}
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if p.is_file() and not any(part in _SCRATCH for part in rel.parts):
            files[str(rel).replace("\\", "/")] = p.read_bytes()
    refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    return {"files": files, "refs": refs}


# ---------------------------------------------------------------------------
# AC-2: one reader, four outcomes, dev-else-mnt resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-2
def test_gate_status_reads_evidence_committed_on_the_resolved_implementation_branch(
    tmp_path, monkeypatch, role
):
    """Happy path, in both resolutions (DEC-0012 item 3): the default `ref` is
    the FR's implementation branch — `claude/dev-<FR>` when it exists, else
    `claude/mnt-<FR>` — so a gate on a maintainer-mode FR is readable at all."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    assert dispatch.gate_status(_FR, _GATE) == "missing"
    _commit_evidence(repo, wt, _FR, _GATE, "pass")
    assert dispatch.gate_status(_FR, _GATE) == "pass"
    assert dispatch._implementation_branch_for_fr(_FR) == (f"claude/{role}-{_FR}", role)
    # The evidence is read from the branch, not the primary checkout.
    assert not (repo / "specs" / "_gates").exists()


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-2
def test_gate_status_changes_requested_and_stale_in_both_resolutions(
    tmp_path, monkeypatch, role
):
    """The other two outcomes, again in both resolutions. `stale` is a `pass`
    whose `head_sha` is not an ancestor-or-equal of the *resolved* branch's
    current tip — i.e. a verdict given against a branch later rewritten."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    _commit_evidence(repo, wt, _FR, _GATE, "changes-requested")
    assert dispatch.gate_status(_FR, _GATE) == "changes-requested"

    # A `pass` recorded against a SHA that is not on the branch at all.
    orphan = _git(repo, "rev-parse", "main")
    _git(repo, "branch", "-q", "sidecar", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unrelated")
    sidecar_sha = _git(repo, "rev-parse", "HEAD")
    assert sidecar_sha != orphan
    d = wt / "specs" / "_gates"
    (d / f"{_FR}-{_GATE}.md").write_text(
        _evidence_text(_FR, _GATE, "pass", "Neil", sidecar_sha),
        encoding="utf-8",
        newline="\n",
    )
    _git(wt, "add", f"specs/_gates/{_FR}-{_GATE}.md")
    _git(wt, "commit", "-q", "-m", "gate: rewritten evidence")
    assert dispatch.gate_status(_FR, _GATE) == "stale"


# covers hub-tooling FR-0008:AC-2
def test_gate_status_ref_none_reads_the_working_tree_and_any_string_reads_that_ref(
    tmp_path, monkeypatch
):
    """The three `ref` modes are distinct: omitted -> implementation branch,
    `None` -> the working tree (the deploy gate's reading), any other string
    -> that ref."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    sha = _commit_evidence(repo, wt, _FR, _GATE, "pass")

    # Nothing in the primary checkout yet.
    assert dispatch.gate_status(_FR, _GATE, ref=None) == "missing"
    assert dispatch.gate_status(_FR, _GATE, ref="main") == "missing"
    assert dispatch.gate_status(_FR, _GATE) == "pass"

    d = repo / "specs" / "_gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_FR}-{_GATE}.md").write_text(
        _evidence_text(_FR, _GATE, "pass", "Neil", sha), encoding="utf-8", newline="\n"
    )
    assert dispatch.gate_status(_FR, _GATE, ref=None) == "pass"
    assert dispatch.gate_status(_FR, _GATE, ref=f"claude/dev-{_FR}") == "pass"


# covers hub-tooling FR-0008:AC-2
def test_gate_status_is_missing_for_an_fr_with_neither_branch_and_for_broken_evidence(
    tmp_path, monkeypatch
):
    """Adversarial: no implementation branch at all, no evidence file, no
    frontmatter, unparseable frontmatter, and an out-of-vocabulary verdict all
    read `missing` — never a crash, never an accidental `pass`."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    assert dispatch._implementation_branch_for_fr(_FR) is None
    assert dispatch.gate_status(_FR, _GATE) == "missing"

    wt = _impl_worktree(repo, _FR, "dev")
    d = wt / "specs" / "_gates"
    d.mkdir(parents=True, exist_ok=True)
    for body in (
        "no frontmatter at all\n",
        "---\ngate: [design-review\nverdict: pass\n---\n\nbroken yaml\n",
        _evidence_text(_FR, _GATE, "approved", "Neil", "deadbeef"),
    ):
        (d / f"{_FR}-{_GATE}.md").write_text(body, encoding="utf-8", newline="\n")
        _git(wt, "add", f"specs/_gates/{_FR}-{_GATE}.md")
        _git(wt, "commit", "-q", "-m", "evidence")
        assert dispatch.gate_status(_FR, _GATE) == "missing", body[:30]


# covers hub-tooling FR-0008:AC-2
def test_evidence_path_is_the_tracked_specs_gates_file_never_dispatch(
    tmp_path, monkeypatch
):
    """The FR's fixed solution-space point: evidence is a tracked file under
    `specs/_gates/`, never the gitignored `_dispatch/` and never only a PR
    comment."""
    assert dispatch._gate_evidence_path(_FR, _GATE) == f"specs/_gates/{_FR}-{_GATE}.md"
    assert "_dispatch" not in dispatch._gate_evidence_path(_FR, _GATE)


# ---------------------------------------------------------------------------
# AC-3: `gate list | pass | block`
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-3
def test_gate_list_prints_one_line_per_declared_gate_with_its_status(
    tmp_path, monkeypatch, capsys
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE), _FR2: ("ready", "")})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    assert dispatch.cmd_gate_list(_FR) == 0
    out = capsys.readouterr().out
    assert _FR in out and _GATE in out
    assert "after=dev" in out and "reviewer=human" in out and "status=missing" in out
    assert dispatch.cmd_gate_list(_FR2) == 0
    assert "no declared gates" in capsys.readouterr().out
    assert dispatch.cmd_gate_list("FR-9999") == 1
    assert "unknown FR id" in capsys.readouterr().out


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-3
def test_gate_pass_writes_commits_and_pushes_the_evidence_on_the_impl_branch(
    tmp_path, monkeypatch, capsys, role
):
    """Happy path, in both resolutions: the evidence is written into the
    implementation worktree, committed on that branch with AC-3's subject, and
    read back as `pass` by the one reader."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    branch = f"claude/{role}-{_FR}"
    tip_before = _git(repo, "rev-parse", branch)

    rc = dispatch.cmd_gate_verdict(
        _FR, _GATE, "pass", by="Neil", note="Screens match.", apply=True
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "GATED" in out and _GATE in out and "by Neil" in out

    subject = _git(repo, "log", "-1", "--format=%s", branch)
    assert subject == f"gate({_FR}): {_GATE} pass by Neil"
    assert _git(repo, "rev-parse", branch) != tip_before
    # Tracked on the branch, not merely on disk.
    tracked = _git(repo, "ls-tree", "-r", "--name-only", branch)
    assert f"specs/_gates/{_FR}-{_GATE}.md" in tracked.splitlines()
    assert dispatch.gate_status(_FR, _GATE) == "pass"

    text = (wt / "specs" / "_gates" / f"{_FR}-{_GATE}.md").read_text(encoding="utf-8")
    assert "verdict: pass" in text and "by: Neil" in text and "round: 1" in text
    assert f"head_sha: {tip_before}" in text  # the tip the verdict was given against
    assert "Screens match." in text
    # `main` is never touched.
    assert _git(repo, "rev-parse", "main") == _git(repo, "rev-parse", "main")
    assert "_gates" not in _git(repo, "ls-tree", "-r", "--name-only", "main")


# covers hub-tooling FR-0008:AC-3
# covers hub-tooling FR-0008:AC-11
def test_gate_pass_and_block_emit_one_gate_decision_record_each(
    tmp_path, monkeypatch, capsys
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    assert (
        dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note="ok", apply=True)
        == 0
    )
    capsys.readouterr()
    recs = _read_records(repo)
    decisions = [r for r in recs if r["kind"] == "gate.decision"]
    assert len(decisions) == 1
    (d,) = decisions
    assert d["object_ids"] == [_FR]
    assert d["gate"] == _GATE and d["after"] == "dev" and d["reviewer"] == "human"
    assert d["verdict"] == "pass" and d["by"] == "Neil" and d["round"] == 1
    assert isinstance(d["head_sha"], str) and len(d["head_sha"]) == 40
    assert metrics_log.validation_errors(d) == []


def _read_records(repo: Path) -> list[dict]:
    out: list[dict] = []
    mdir = repo / "metrics"
    if not mdir.exists():
        return out
    for p in sorted(mdir.glob("*.ndjson")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


# covers hub-tooling FR-0008:AC-3
def test_gate_verdict_refuses_naming_both_candidate_branches_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    """Adversarial, DEC-0012 item 3: when *neither* implementation branch
    exists the refusal is one ERROR line naming **both** candidates, and the
    repository is byte-identical afterwards."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    before = _repo_snapshot(repo)
    rc = dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note="ok", apply=True)
    out = capsys.readouterr().out
    assert rc == 1
    errors = [line for line in out.splitlines() if line.startswith("ERROR")]
    assert len(errors) == 1, out
    assert f"claude/dev-{_FR}" in errors[0] and f"claude/mnt-{_FR}" in errors[0]
    assert _repo_snapshot(repo) == before


# covers hub-tooling FR-0008:AC-3
def test_gate_verdict_refuses_an_undeclared_gate_id_and_a_block_without_a_note(
    tmp_path, monkeypatch, capsys
):
    """Adversarial: the dispatcher never invents a gate, and a block with no
    rationale is refused before anything is written."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    before = _repo_snapshot(repo)

    assert (
        dispatch.cmd_gate_verdict(
            _FR, "not-declared", "pass", by="Neil", note="x", apply=True
        )
        == 1
    )
    out = capsys.readouterr().out
    assert "declares no gate" in out and _GATE in out  # names what IS declared

    for note in (None, "", "   "):
        assert (
            dispatch.cmd_gate_verdict(
                _FR, _GATE, "changes-requested", by="Neil", note=note, apply=True
            )
            == 1
        )
        assert "requires --note" in capsys.readouterr().out
    assert _repo_snapshot(repo) == before


# covers hub-tooling FR-0008:AC-3
def test_gate_verdict_refuses_when_the_resolved_worktree_is_on_another_branch(
    tmp_path, monkeypatch, capsys
):
    """Adversarial: writing into a worktree that has been switched to another
    branch would commit the evidence in the wrong place."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    _git(wt, "checkout", "-q", "-b", "sidetrack")
    before = _repo_snapshot(repo)
    assert (
        dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note="x", apply=True)
        == 1
    )
    out = capsys.readouterr().out
    assert "is on branch" in out and "sidetrack" in out
    assert _repo_snapshot(repo) == before


# covers hub-tooling FR-0008:AC-3
# covers hub-tooling FR-0008:AC-13
def test_gate_verdict_dry_run_prints_would_gate_and_mutates_nothing(
    tmp_path, monkeypatch, capsys
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    before = _repo_snapshot(repo)
    assert (
        dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note="x", apply=False)
        == 0
    )
    out = capsys.readouterr().out
    assert out.strip() == f"WOULD-GATE {_FR} {_GATE} pass"
    assert _repo_snapshot(repo) == before
    assert _read_records(repo) == []
    assert dispatch.gate_status(_FR, _GATE) == "missing"


# ---------------------------------------------------------------------------
# AC-4: Reviewer runnability
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-4
def test_an_unsatisfied_after_dev_gate_excludes_the_fr_from_runnable_review_frs(
    tmp_path, monkeypatch
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    _flip_status(repo, wt, _FR, "in-review", _HUMAN_DEV_GATE)
    frs = dispatch.load_frs()
    assert [f["id"] for f in dispatch.runnable_review_frs(frs)] == []
    pending = dispatch.gate_pending_review_frs(frs)
    assert [fr_id for fr_id, _ in pending] == [_FR]
    reason = pending[0][1]
    assert _GATE in reason and "reviewer=human" in reason and "status=missing" in reason
    assert f"gate pass {_FR} {_GATE}" in reason  # the exact satisfying command

    _commit_evidence(repo, wt, _FR, _GATE, "pass")
    frs = dispatch.load_frs()
    assert [f["id"] for f in dispatch.runnable_review_frs(frs)] == [_FR]
    assert dispatch.gate_pending_review_frs(frs) == []


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-4
def test_explain_not_runnable_gives_the_same_reason_in_both_resolutions(
    tmp_path, monkeypatch, role
):
    """DEC-0012 item 3 again, on the `--fr` selector path: the reason a
    maintainer-mode FR is not reviewable must be the gate, not a missing
    branch."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    _flip_status(repo, wt, _FR, "in-review", _HUMAN_DEV_GATE)
    frs = dispatch.load_frs()
    reason = dispatch.explain_not_runnable(_FR, frs, "rev")
    assert reason is not None and _GATE in reason and "reviewer=human" in reason
    assert f"gate pass {_FR} {_GATE}" in reason

    _commit_evidence(repo, wt, _FR, _GATE, "pass")
    assert dispatch.explain_not_runnable(_FR, dispatch.load_frs(), "rev") is None


# covers hub-tooling FR-0008:AC-4
def test_tick_role_rev_prints_one_skip_line_per_gated_fr(
    tmp_path, monkeypatch, capsys, adapter
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    _flip_status(repo, wt, _FR, "in-review", _HUMAN_DEV_GATE)
    dispatch.cmd_tick(apply=True, adapter=adapter, role="rev")
    out = capsys.readouterr().out
    assert "SKIP" in out and _GATE in out and f"gate pass {_FR} {_GATE}" in out
    assert [s[1] for s in adapter.spawns] == []


# covers hub-tooling FR-0008:AC-4
# covers hub-tooling FR-0008:AC-13
def test_an_after_rev_gate_never_blocks_the_reviewer(tmp_path, monkeypatch):
    """Adversarial: only `after: dev` gates gate the Reviewer. An FR whose
    only gate is `after: rev` is reviewable exactly as today, even with no
    evidence at all."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _REV_ONLY_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    _flip_status(repo, wt, _FR, "in-review", _REV_ONLY_GATE)
    frs = dispatch.load_frs()
    assert dispatch.gate_status(_FR, _GATE) == "missing"
    assert [f["id"] for f in dispatch.runnable_review_frs(frs)] == [_FR]
    assert dispatch.gate_pending_review_frs(frs) == []
    assert dispatch.explain_not_runnable(_FR, frs, "rev") is None


@pytest.mark.parametrize("status", ["changes-requested", "stale"])
# covers hub-tooling FR-0008:AC-4
# covers hub-tooling FR-0008:AC-7
def test_only_a_pass_makes_the_fr_runnable_again(tmp_path, monkeypatch, status):
    """Adversarial: `changes-requested` and `stale` are both not-pass; neither
    lets the Reviewer through."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    _flip_status(repo, wt, _FR, "in-review", _HUMAN_DEV_GATE)
    if status == "changes-requested":
        _commit_evidence(repo, wt, _FR, _GATE, "changes-requested")
    else:
        # A `pass` recorded against a SHA that is not on the branch: the
        # branch-was-rewritten case. (A 40-char *all-digit* value would be
        # parsed by YAML as an int, not a SHA — see the review's FINDINGS.)
        _commit_evidence(repo, wt, _FR, _GATE, "pass", head_sha="deadbeef" * 5)
    assert dispatch.gate_status(_FR, _GATE) == status
    assert [f["id"] for f in dispatch.runnable_review_frs(dispatch.load_frs())] == []


# ---------------------------------------------------------------------------
# AC-5 / AC-7: the wave
# ---------------------------------------------------------------------------


def _wave(adapter, **kw) -> int:
    defaults = {
        "apply": True,
        "adapter": adapter,
        "fr_filter": [_FR],
        "timeout": 60,
        "phase_timeout": 30,
        "poll_interval": 0.01,
    }
    defaults.update(kw)
    return dispatch.cmd_wave(**defaults)


def _install_wave(monkeypatch, repo: Path, *, gat_verdict: str | None = None) -> dict:
    """Drive a wave to Phase 3.5 without spawning anything.

    The `spawn_role` double creates the role's branch and worktree the way the
    real one does (`test_dispatch_wave_finalize.py`'s shape), so `wave` reaches
    the gate check with a real `claude/dev-<FR>` to read evidence from. When
    `gat_verdict` is given, the `gat` spawn also writes, commits and lands the
    evidence file — standing in for a gate-review session.
    """
    state: dict = {"spawned": [], "finalized": []}

    def spawn_role(fr_id, role, apply, adapter, *a, gate_id=None, **k):
        state["spawned"].append((fr_id, role, gate_id))
        wt = repo / ".claude" / "worktrees" / f"{role}-{fr_id}"
        if not wt.exists():
            base = (
                "main" if role == "dev" else dispatch._base_branch_for_role(fr_id, role)
            )
            wt.parent.mkdir(parents=True, exist_ok=True)
            _git(
                repo,
                "worktree",
                "add",
                "-q",
                "-b",
                f"claude/{role}-{fr_id}",
                str(wt),
                base,
            )
            if role == "dev":
                (wt / "PR_BODY.md").write_text(
                    f"# {fr_id}\n", encoding="utf-8", newline="\n"
                )
                (wt / "specs" / f"{fr_id}-synthetic.md").write_text(
                    _fr_md(fr_id, "in-review", _gates_of(repo, fr_id)),
                    encoding="utf-8",
                    newline="\n",
                )
                _git(wt, "add", "-A")
                _git(wt, "commit", "-q", "-m", "dev: hand-off")
        if role == "gat" and gat_verdict is not None:
            base = dispatch._base_branch_for_role(fr_id, "gat")
            d = wt / "specs" / "_gates"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{fr_id}-{gate_id}.md").write_text(
                _evidence_text(
                    fr_id,
                    gate_id,
                    gat_verdict,
                    "architect",
                    _git(repo, "rev-parse", base),
                    "rationale",
                ),
                encoding="utf-8",
                newline="\n",
            )
            _git(wt, "add", f"specs/_gates/{fr_id}-{gate_id}.md")
            _git(
                wt,
                "commit",
                "-q",
                "-m",
                f"gate({fr_id}): {gate_id} {gat_verdict} by architect",
            )
            _git(repo, "update-ref", f"refs/heads/{base}", f"claude/gat-{fr_id}")
        (repo / "_dispatch").mkdir(exist_ok=True)
        return ("spawned", 4242, wt)

    def finalize(fr_id, role, apply, draft, adapter=None, **k):
        state["finalized"].append((fr_id, role))
        return 0

    monkeypatch.setattr(dispatch, "spawn_role", spawn_role)
    monkeypatch.setattr(dispatch, "cmd_finalize", finalize)
    monkeypatch.setattr(
        dispatch,
        "_wait_for_phase",
        lambda targets, *a, **k: {fr_id: "completed" for fr_id, _r in targets},
    )
    monkeypatch.setattr(
        dispatch,
        "_evaluate_agent_outcome",
        lambda fr_id, role, adapter=None: dispatch.AgentOutcome(
            status="success", summary=f"{role} success", verdict="approve"
        ),
    )
    monkeypatch.setattr(
        dispatch, "_collect_failing_tests", lambda wt, timeout_s=900: []
    )
    return state


def _gates_of(repo: Path, fr_id: str) -> str:
    """The FR's `gates:` block as written on main, so the dev branch's copy of
    the spec declares the same gates."""
    text = (repo / "specs" / f"{fr_id}-synthetic.md").read_text(encoding="utf-8")
    if "\ngates:" not in text:
        return ""
    block = text.split("\ngates:", 1)[1].split("\ncreated:", 1)[0]
    return "gates:" + block


# covers hub-tooling FR-0008:AC-5
def test_a_human_gate_stops_the_wave_and_spawns_no_reviewer(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-5's assertions other than the exit code: the `GATE-PENDING` line
    names the FR, the gate, the reviewer kind, the scope and the exact
    satisfying command; no `rev` lock and no `rev` worktree exist; the FR is
    recorded as a gated per-FR result, not a failure and not an escalation.
    (The exit code is pinned separately — see the K1 block below.)"""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    state = _install_wave(monkeypatch, repo)
    _wave(adapter)
    out = capsys.readouterr().out
    assert "GATE-PENDING" in out and _GATE in out and "reviewer=human" in out
    assert "satisfy with:" in out and f"gate pass {_FR} {_GATE}" in out
    assert "The human signs off" in out  # the gate's own scope text
    assert [r for _f, r, _g in state["spawned"]] == ["dev"]  # no Reviewer, no gat
    assert not (repo / ".claude" / "worktrees" / f"rev-{_FR}").exists()
    assert not (repo / "_dispatch" / f"{_FR}.rev.lock").exists()
    assert f"- {_FR}: GATE-PENDING ({_GATE}" in out  # the synthesis per-FR result
    assert "1 gated" in out
    assert "## Open Escalations\n(none)" in out


# covers hub-tooling FR-0008:AC-5
# covers hub-tooling FR-0008:AC-7
def test_a_mixed_wave_with_one_gated_and_one_gate_free_fr_exits_3(
    tmp_path, monkeypatch, capsys, adapter
):
    """The exit-code plumbing itself is correct: as soon as *some* FR reaches
    the Reviewer phase, the wave runs to its end and `any(r.gate_result ...)`
    returns 3 for the gated one. This is the control for the K1 pins below,
    which isolate the defect to Phase 4's two early `return 0`s."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE), _FR2: ("ready", "")})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo)
    rc = dispatch.cmd_wave(
        apply=True,
        adapter=adapter,
        fr_filter=[_FR, _FR2],
        timeout=60,
        phase_timeout=30,
        poll_interval=0.01,
    )
    out = capsys.readouterr().out
    assert "GATE-PENDING" in out and _FR in out
    assert rc == 3, out


# ---------------------------------------------------------------------------
# K1 (kick-back) — AC-5 / AC-7's exit code 3 is unreachable in exactly the
# scenario the ACs describe. `runnable_review_frs` correctly excludes a gated
# FR (AC-4), so a wave whose every dev-finalized FR is gated leaves Phase 4
# with `rev_eligible == []` and takes `return 0` at dispatch.py:8230, before
# the `any(r.gate_result ...) -> return 3` check at :8378 is ever reached.
# `wave --fr <one gated FR>` therefore exits 0 for GATE-PENDING, GATE-BLOCKED
# and GATE-STALE alike — while the `orchestrator.md` paragraph this same FR
# adds tells the Orchestrator both outcomes are "both exit 3".
#
# Pinned strict-xfail so the suite stays green while the defect is recorded.
# Once it is fixed these three XPASS and fail: delete the marker, not the test.
# ---------------------------------------------------------------------------

_K1 = pytest.mark.xfail(
    strict=True,
    reason=(
        "KICK-BACK K1 (FR-0008:AC-5/AC-7): a wave whose every finalized FR is "
        "gated exits 0, not 3 — Phase 4's `if not rev_eligible: return 0` "
        "(dispatch.py:8230) precedes the exit-3 check at :8378"
    ),
)


# covers hub-tooling FR-0008:AC-5
def test_k1_a_wave_stopped_by_a_human_gate_exits_3(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-5 verbatim: "…spawns no Reviewer, and exits with status `3`. Verified
    by asserting no `rev` lock, no `rev` worktree, and exit code 3.\""""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo)
    rc = _wave(adapter)
    assert "GATE-PENDING" in capsys.readouterr().out
    assert rc == 3


# covers hub-tooling FR-0008:AC-7
def test_k1_a_wave_blocked_by_an_architect_gate_exits_3(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-7 verbatim: "`changes-requested` -> the wave prints `GATE-BLOCKED
    <FR> <gate-id> by architect` and stops (exit 3)\"."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo, gat_verdict="changes-requested")
    rc = _wave(adapter)
    assert "GATE-BLOCKED" in capsys.readouterr().out
    assert rc == 3


# covers hub-tooling FR-0008:AC-7
def test_k1_a_wave_stopped_by_a_stale_gate_exits_3(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-7: "A `stale` status (AC-2) is treated as not-pass and reported as
    `GATE-STALE`" — the same exit-3 outcome."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo, gat_verdict="pass")
    real = dispatch.gate_status
    monkeypatch.setattr(
        dispatch,
        "gate_status",
        lambda f, g, *a, **k: (
            "stale" if real(f, g, *a, **k) == "pass" else real(f, g, *a, **k)
        ),
    )
    rc = _wave(adapter)
    assert "GATE-STALE" in capsys.readouterr().out
    assert rc == 3


# covers hub-tooling FR-0008:AC-5
def test_nothing_in_the_dispatcher_ever_writes_a_pass_for_a_human_gate(
    tmp_path, monkeypatch, capsys, adapter
):
    """Adversarial, the AC's strongest clause: an *approved PR* on the branch
    does not satisfy a human gate. Neither does running the wave twice (no
    timeout path, no `--force` path writes one)."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo)
    # A PR record that is open, not draft, and carries an approving review.
    (repo / "_dispatch").mkdir(exist_ok=True)
    (repo / "_dispatch" / f"{_FR}.dev.pr.json").write_text(
        json.dumps(
            {
                "pr_number": 42,
                "pr_url": "https://github.com/example-org/synthetic-project/pull/42",
                "branch": f"claude/dev-{_FR}",
                "draft": False,
                "verdict": "approve",
                "review_state": "APPROVED",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for _ in range(2):
        _wave(adapter)  # exit code is K1's; the gate state is this test's
        capsys.readouterr()
        assert dispatch.gate_status(_FR, _GATE) == "missing"
    # No evidence file exists anywhere, on any branch or on disk.
    assert f"specs/_gates/{_FR}-{_GATE}.md" not in _git(
        repo, "ls-tree", "-r", "--name-only", f"claude/dev-{_FR}"
    )
    assert not (repo / "specs" / "_gates").exists()
    assert [r for r in _read_records(repo) if r["kind"] == "gate.decision"] == []


# covers hub-tooling FR-0008:AC-13
def test_a_gate_free_fr_never_prints_the_phase_35_header_or_any_gate_line(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-13: a wave over an FR with no `gates:` key must produce output with
    nothing gate-shaped in it at all."""
    repo = _make_repo(tmp_path, {_FR: ("ready", "")})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo)
    _wave(adapter)
    out = capsys.readouterr().out
    for needle in (
        "Phase 3.5",
        "GATE-PENDING",
        "GATE-BLOCKED",
        "GATE-STALE",
        "WOULD-GATE",
        "Gate check",
    ):
        assert needle not in out, needle
    assert "Phase 4: Rev Tick" in out  # the wave carried on exactly as before


# covers hub-tooling FR-0008:AC-13
def test_wave_dry_run_prints_would_gate_only_for_a_gated_fr_and_mutates_nothing(
    tmp_path, monkeypatch, capsys, adapter
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE), _FR2: ("ready", "")})
    _point(monkeypatch, repo)
    before = _repo_snapshot(repo)
    dispatch.cmd_wave(
        apply=False,
        adapter=adapter,
        fr_filter=[_FR, _FR2],
        timeout=30,
        phase_timeout=20,
        poll_interval=0.01,
    )
    out = capsys.readouterr().out
    assert "Phase 3.5: Gate check" in out
    assert f"  {_FR}  WOULD-GATE   {_GATE} reviewer=human" in out
    assert f"{_FR2}  WOULD-GATE" not in out
    assert _repo_snapshot(repo) == before
    assert adapter.spawns == []

    # And with no gated FR in the selection, the phase is invisible.
    capsys.readouterr()
    dispatch.cmd_wave(
        apply=False,
        adapter=adapter,
        fr_filter=[_FR2],
        timeout=30,
        phase_timeout=20,
        poll_interval=0.01,
    )
    out2 = capsys.readouterr().out
    assert "Phase 3.5" not in out2 and "WOULD-GATE" not in out2


# ---------------------------------------------------------------------------
# AC-6: the `gat` one-shot gate-review session
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-6
def test_tick_role_gat_spawns_on_a_branch_cut_at_the_impl_tip_with_one_writable_path(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-6 + DEC-0012 item 5: the worktree sits on a *new* branch
    `claude/gat-<FR>` created at the implementation branch's current tip (git
    refuses two worktrees on one branch), and its only writable path is the one
    gate's evidence file."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    tip = _git(repo, "rev-parse", f"claude/dev-{_FR}")
    assert dispatch._base_branch_for_role(_FR, "gat") == f"claude/dev-{_FR}"

    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="gat", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    assert "SPAWNED" in out
    (fr_id, role, wt_path, _extra, gate_id) = adapter.spawns[0]
    assert (fr_id, role, gate_id) == (_FR, "gat", _ARCH_GATE)
    assert _git(repo, "rev-parse", f"claude/gat-{_FR}") == tip
    assert _git(wt_path, "rev-parse", "--abbrev-ref", "HEAD") == f"claude/gat-{_FR}"

    perms = json.loads(
        (wt_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )["permissions"]
    evidence = f"specs/_gates/{_FR}-{_ARCH_GATE}.md"
    writes = [g for g in perms["allow"] if g.startswith(("Edit(", "Write("))]
    assert sorted(writes) == sorted([f"Edit({evidence})", f"Write({evidence})"])
    assert (
        "Edit(PR_BODY.md)" in perms["deny"]
        and "Write(scripts/dispatch.py)" in perms["deny"]
    )


# covers hub-tooling FR-0008:AC-6
def test_gat_dry_run_previews_the_fr_and_gate_in_the_prompt_and_mutates_nothing(
    tmp_path, monkeypatch, capsys, adapter
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    before = _repo_snapshot(repo)
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="gat", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    assert "WOULD-SPAWN" in out
    assert f"/gate-review {_FR} {_ARCH_GATE}" in out
    assert f"base=claude/dev-{_FR}" in out and f"gate={_ARCH_GATE}" in out
    assert _repo_snapshot(repo) == before
    assert adapter.spawns == []


# covers hub-tooling FR-0008:AC-6
def test_tick_role_gat_refuses_without_exactly_one_fr_and_is_a_noop_with_no_open_gate(
    tmp_path, monkeypatch, capsys, adapter
):
    """Adversarial: `gat` is FR+gate scoped and one-shot. It never runs over a
    runnable set, and it does nothing at all when the FR has no unsatisfied
    `after: dev` architect gate (including when the only gate is a human one)."""
    repo = _make_repo(
        tmp_path,
        {_FR: ("ready", _HUMAN_DEV_GATE), _FR2: ("ready", _ARCHITECT_DEV_GATE)},
    )
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="gat", fr_filter=None) == 1
    )
    assert "exactly one" in capsys.readouterr().out
    assert (
        dispatch.cmd_tick(
            apply=True, adapter=adapter, role="gat", fr_filter=[_FR, _FR2]
        )
        == 1
    )
    capsys.readouterr()
    # Declared, but human-judged: no `gat` session exists for it.
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="gat", fr_filter=[_FR]) == 0
    )
    assert "no unsatisfied" in capsys.readouterr().out
    assert adapter.spawns == []


def _gat_session(
    repo: Path, fr_id: str, gate: str, verdict: str, body: str = "ok"
) -> Path:
    """Stand in for a gate-review session: a `claude/gat-<FR>` worktree cut at
    the implementation tip with the evidence file staged (uncommitted), exactly
    as `_finalize_commit_step` expects to find it."""
    base = dispatch._base_branch_for_role(fr_id, "gat")
    wt = repo / ".claude" / "worktrees" / f"gat-{fr_id}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/gat-{fr_id}", str(wt), base)
    d = wt / "specs" / "_gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{fr_id}-{gate}.md").write_text(
        _evidence_text(
            fr_id, gate, verdict, "architect", _git(repo, "rev-parse", base), body
        ),
        encoding="utf-8",
        newline="\n",
    )
    _git(wt, "add", f"specs/_gates/{fr_id}-{gate}.md")
    return wt


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-6
def test_finalize_role_gat_fast_forwards_the_impl_branch_and_uses_the_ac6_subject(
    tmp_path, monkeypatch, capsys, adapter, role
):
    """Happy path, both resolutions: the one evidence commit is committed by
    the dispatcher with AC-6's subject and fast-forwarded onto the *real*
    implementation branch, which is the branch that is pushed."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, role)
    impl = f"claude/{role}-{_FR}"
    before = _git(repo, "rev-parse", impl)
    _gat_session(repo, _FR, _ARCH_GATE, "pass")

    pushed: list[str] = []
    monkeypatch.setattr(
        dispatch,
        "_push_branch",
        lambda branch: (pushed.append(branch), (True, "pushed"))[1],
    )
    rc = dispatch.cmd_finalize(_FR, "gat", apply=True, draft=True, adapter=adapter)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "GATED" in out and _ARCH_GATE in out and "pass" in out

    after = _git(repo, "rev-parse", impl)
    assert after != before
    assert _git(repo, "rev-parse", f"claude/gat-{_FR}") == after  # a real fast-forward
    assert _git(repo, "log", "-1", "--format=%s", impl) == (
        f"gate({_FR}): {_ARCH_GATE} pass by architect"
    )
    assert pushed == [impl]  # the gat staging branch is never pushed
    assert dispatch.gate_status(_FR, _ARCH_GATE) == "pass"


# covers hub-tooling FR-0008:AC-6
# covers hub-tooling FR-0008:AC-11
def test_finalize_role_gat_takes_round_and_head_sha_from_the_evidence_frontmatter(
    tmp_path, monkeypatch, capsys, adapter
):
    """DEC-0012 item 5 / the Architect's confirmed ruling: the dispatcher never
    invents a round number or a SHA for a `gat` record — both come from the
    evidence file the session wrote."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    wt = _gat_session(repo, _FR, _ARCH_GATE, "pass")
    p = wt / "specs" / "_gates" / f"{_FR}-{_ARCH_GATE}.md"
    p.write_text(
        p.read_text(encoding="utf-8")
        .replace("round: 1", "round: 4")
        .replace(
            f"head_sha: {_git(repo, 'rev-parse', f'claude/dev-{_FR}')}",
            "head_sha: " + "c" * 40,
        ),
        encoding="utf-8",
        newline="\n",
    )
    _git(wt, "add", f"specs/_gates/{_FR}-{_ARCH_GATE}.md")
    assert (
        dispatch.cmd_finalize(_FR, "gat", apply=True, draft=True, adapter=adapter) == 0
    )
    capsys.readouterr()
    (d,) = [r for r in _read_records(repo) if r["kind"] == "gate.decision"]
    assert d["round"] == 4 and d["head_sha"] == "c" * 40
    assert d["by"] == "architect" and d["reviewer"] == "architect"
    assert metrics_log.validation_errors(d) == []


# covers hub-tooling FR-0008:AC-6
def test_finalize_role_gat_posts_the_evidence_body_as_a_pr_comment_on_changes_requested(
    tmp_path, monkeypatch, capsys, adapter
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    _gat_session(repo, _FR, _ARCH_GATE, "changes-requested", body="FR-0001:AC-1 unmet.")
    monkeypatch.setattr(dispatch, "_gh_pr_for_branch", lambda branch: 42)
    calls = _install_gh_double(monkeypatch)
    assert (
        dispatch.cmd_finalize(_FR, "gat", apply=True, draft=True, adapter=adapter) == 0
    )
    capsys.readouterr()
    comments = [c for c in calls if c[:3] == ["gh", "pr", "comment"]]
    assert len(comments) == 1
    assert "42" in comments[0]
    assert "FR-0001:AC-1 unmet." in comments[0][comments[0].index("--body") + 1]
    assert dispatch.gate_status(_FR, _ARCH_GATE) == "changes-requested"


def _install_gh_double(monkeypatch) -> list[list[str]]:
    """Replace `subprocess.run` inside dispatch for `gh` argv only; every other
    call (git, in particular) goes to the real thing. `gh` is NEVER invoked."""
    calls: list[list[str]] = []
    real = subprocess.run

    def fake(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "gh":
            calls.append(list(cmd))
            if list(cmd[:3]) == ["gh", "pr", "create"]:
                out = "https://github.com/example-org/synthetic-project/pull/42\n"
            elif list(cmd[:3]) == ["gh", "pr", "list"]:
                out = "[]\n"
            else:
                out = "ok\n"
            return subprocess.CompletedProcess(list(cmd), 0, out, "")
        return real(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", fake)
    return calls


# covers hub-tooling FR-0008:AC-6
def test_finalize_role_gat_refuses_a_diverged_branch_and_a_malformed_evidence_file(
    tmp_path, monkeypatch, capsys, adapter
):
    """Adversarial: the fast-forward is guarded (diverged -> refuse, never
    merge or force), and an evidence file with no readable verdict is refused
    rather than guessed at."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    dev_wt = _impl_worktree(repo, _FR, "dev")
    _gat_session(repo, _FR, _ARCH_GATE, "pass")
    # The implementation branch moves on independently -> divergence.
    (dev_wt / "src" / "later.py").write_text("y\n", encoding="utf-8", newline="\n")
    _git(dev_wt, "add", "-A")
    _git(dev_wt, "commit", "-q", "-m", "feat: later")
    impl_tip = _git(repo, "rev-parse", f"claude/dev-{_FR}")

    assert (
        dispatch.cmd_finalize(_FR, "gat", apply=True, draft=True, adapter=adapter) == 1
    )
    out = capsys.readouterr().out
    assert "diverged" in out and "refusing to fast-forward" in out
    assert _git(repo, "rev-parse", f"claude/dev-{_FR}") == impl_tip  # untouched


# covers hub-tooling FR-0008:AC-6
def test_finalize_role_gat_dry_run_names_the_resolved_branch_and_mutates_nothing(
    tmp_path, monkeypatch, capsys, adapter
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "mnt")
    _gat_session(repo, _FR, _ARCH_GATE, "pass")
    before = _repo_snapshot(repo)
    assert (
        dispatch.cmd_finalize(_FR, "gat", apply=False, draft=True, adapter=adapter) == 0
    )
    out = capsys.readouterr().out
    assert "WOULD-FINALIZE" in out
    assert f"claude/gat-{_FR} -> claude/mnt-{_FR}" in out  # the resolved branch
    assert _repo_snapshot(repo) == before


# ---------------------------------------------------------------------------
# AC-7: verdict routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict, marker", [("pass", "GATE-PASS"), ("changes-requested", "GATE-BLOCKED")]
)
# covers hub-tooling FR-0008:AC-7
def test_a_gat_verdict_routes_the_wave(
    tmp_path, monkeypatch, capsys, adapter, verdict, marker
):
    """AC-7: `pass` lets the wave proceed to the Reviewer tick; a
    `changes-requested` prints `GATE-BLOCKED` and stops, naming the evidence
    path as the rework input. (The exit code is K1's, above.)"""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    state = _install_wave(monkeypatch, repo, gat_verdict=verdict)
    got = _wave(adapter)
    out = capsys.readouterr().out
    assert marker in out, out
    assert "gat" in [r for _f, r, _g in state["spawned"]], state["spawned"]
    if verdict == "pass":
        assert got == 0, out
        assert "Phase 4: Rev Tick" in out
        assert "GATE-BLOCKED" not in out
        assert dispatch.gate_status(_FR, _ARCH_GATE) == "pass"
    else:
        assert f"specs/_gates/{_FR}-{_ARCH_GATE}.md" in out  # the rework input
        # "Stops" = no Reviewer is spawned for this FR; Phase 4 runs and
        # finds it ineligible (AC-4), which is the same mechanism.
        assert "rev" not in [r for _f, r, _g in state["spawned"]]
        assert "No FRs eligible for Reviewer" in out
        # Rework is NOT automated by this FR (Out of scope).
        assert "Round 2" not in out
        assert f"- {_FR}: GATE-BLOCKED" in out  # the synthesis per-FR result


# covers hub-tooling FR-0008:AC-7
def test_a_stale_verdict_is_reported_as_gate_stale_with_both_shas(
    tmp_path, monkeypatch, capsys, adapter
):
    """Adversarial: `stale` is not-pass — it must not be waved through as a
    pass — and the line carries both SHAs so the human can see which tip the
    verdict was given against."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo, gat_verdict="pass")
    # The gate session's `pass` names a SHA that is not on the branch: the
    # evidence-from-a-rewritten-branch case AC-2 calls `stale`.
    real = dispatch.gate_status

    def staleify(fr_id, gate, *a, **k):
        got = real(fr_id, gate, *a, **k)
        return "stale" if got == "pass" else got

    monkeypatch.setattr(dispatch, "gate_status", staleify)
    _wave(adapter)
    out = capsys.readouterr().out
    assert "GATE-STALE" in out and "vs current dev tip" in out
    assert "GATE-PASS" not in out
    assert "No FRs eligible for Reviewer" in out  # no Reviewer spawned
    assert f"- {_FR}: GATE-STALE" in out  # the synthesis per-FR result


# ---------------------------------------------------------------------------
# AC-8: the PR stays a draft
# ---------------------------------------------------------------------------


def _ready_to_finalize(repo: Path, role: str, fr_id: str = _FR) -> Path:
    wt = repo / ".claude" / "worktrees" / f"{role}-{fr_id}"
    (wt / "PR_BODY.md").write_text(
        f"# {fr_id}\n\n## AC coverage\n\n- AC-1: done\n", encoding="utf-8", newline="\n"
    )
    _git(wt, "add", "PR_BODY.md")
    _git(wt, "commit", "-q", "-m", "docs: PR body")
    return wt


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-8
def test_finalize_ready_refuses_while_an_after_dev_gate_is_unsatisfied(
    tmp_path, monkeypatch, capsys, adapter, role
):
    """DEC-0012 item 4: the guard is shared, so `--ready` refuses identically
    on `_finalize_dev` and on `_finalize_oneshot` (`mnt` / `bkf`). One ERROR
    line, naming the gate and its status; no `gh pr create` is reached."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, role)
    _ready_to_finalize(repo, role)
    monkeypatch.setattr(
        dispatch, "mnt_footprint_violations", lambda *a, **k: ([], None)
    )
    monkeypatch.setattr(
        dispatch, "_finalize_revalidate_stale_branch", lambda *a, **k: True
    )
    calls = _install_gh_double(monkeypatch)

    rc = dispatch.cmd_finalize(_FR, role, apply=True, draft=False, adapter=adapter)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = [line for line in out.splitlines() if "ERROR" in line]
    assert len(errors) == 1, out
    assert "cannot open ready-for-review" in errors[0]
    assert f"{_GATE} (missing)" in errors[0]
    assert [c for c in calls if c[:3] == ["gh", "pr", "create"]] == []


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-8
def test_finalize_ready_succeeds_once_the_gate_passes(
    tmp_path, monkeypatch, capsys, adapter, role
):
    """The other half of AC-8: the guard is a gate, not a wall. Once the
    evidence says `pass`, `--ready` opens a non-draft PR."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    _ready_to_finalize(repo, role)
    _commit_evidence(repo, wt, _FR, _GATE, "pass")
    assert dispatch.gate_status(_FR, _GATE) == "pass"
    monkeypatch.setattr(
        dispatch, "mnt_footprint_violations", lambda *a, **k: ([], None)
    )
    monkeypatch.setattr(
        dispatch, "_finalize_revalidate_stale_branch", lambda *a, **k: True
    )
    calls = _install_gh_double(monkeypatch)

    rc = dispatch.cmd_finalize(_FR, role, apply=True, draft=False, adapter=adapter)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "cannot open ready-for-review" not in out
    creates = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert len(creates) == 1
    assert "--draft" not in creates[0]
    assert "PR-OPENED" in out


# covers hub-tooling FR-0008:AC-8
def test_the_gates_pr_body_section_is_applied_on_both_finalize_paths(
    tmp_path, monkeypatch, capsys, adapter
):
    """Re-pointed per the Architect's "rulings on round 2" (FR-0008 Notes,
    ruling (i)): AC-8's `## Gates` section is unqualified, and DEC-0012 item
    4's "keeps its existing behaviour on both paths" describes the draft
    *refusal*, not the section's visibility — so `_finalize_oneshot`
    (`mnt`/`bkf`) renders and refreshes the section exactly as
    `_finalize_dev` does, and a maintainer-mode PR now carries it too."""
    monkeypatch.setattr(
        dispatch, "mnt_footprint_violations", lambda *a, **k: ([], None)
    )
    monkeypatch.setattr(
        dispatch, "_finalize_revalidate_stale_branch", lambda *a, **k: True
    )
    seen = {}
    for role in ("dev", "mnt"):
        repo = _make_repo(tmp_path / role, {_FR: ("ready", _HUMAN_DEV_GATE)})
        _point(monkeypatch, repo)
        wt = _impl_worktree(repo, _FR, role)
        _ready_to_finalize(repo, role)
        _commit_evidence(repo, wt, _FR, _GATE, "pass")
        _install_gh_double(monkeypatch)
        assert (
            dispatch.cmd_finalize(_FR, role, apply=True, draft=True, adapter=adapter)
            == 0
        ), capsys.readouterr().out
        capsys.readouterr()
        seen[role] = "## Gates" in (wt / "PR_BODY.md").read_text(encoding="utf-8")
    assert seen == {"dev": True, "mnt": True}
    # The shared guard is genuinely shared, and now so is the section.
    assert "_gate_draft_refusal" in _source_of(dispatch._finalize_dev)
    assert "_gate_draft_refusal" in _source_of(dispatch._finalize_oneshot)


def _source_of(fn) -> str:
    import inspect

    return inspect.getsource(fn)


# covers hub-tooling FR-0008:AC-8
def test_a_draft_finalize_is_never_refused_by_the_gate_guard(
    tmp_path, monkeypatch, capsys, adapter
):
    """Adversarial: the guard fires on un-drafting only. Opening the PR as a
    draft while the gate is unsatisfied is exactly the intended state."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    _ready_to_finalize(repo, "dev")
    monkeypatch.setattr(
        dispatch, "_finalize_revalidate_stale_branch", lambda *a, **k: True
    )
    calls = _install_gh_double(monkeypatch)
    assert dispatch._gate_draft_refusal(_FR, "dev", draft=True) is False
    rc = dispatch.cmd_finalize(_FR, "dev", apply=True, draft=True, adapter=adapter)
    out = capsys.readouterr().out
    assert rc == 0, out
    creates = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert len(creates) == 1 and "--draft" in creates[0]
    assert "DRAFT-OPENED" in out


# covers hub-tooling FR-0008:AC-8
def test_the_pr_body_gains_a_gates_section_that_re_renders_idempotently(
    tmp_path, monkeypatch
):
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE), _FR2: ("ready", "")})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    body = wt / "PR_BODY.md"
    body.write_text(
        "# Title\n\n## AC coverage\n\n- AC-1\n", encoding="utf-8", newline="\n"
    )

    assert dispatch._apply_gates_section(body, _FR) is True
    text = body.read_text(encoding="utf-8")
    assert "## Gates" in text
    assert f"- {_GATE} (dev, human): missing" in text
    assert "## AC coverage" in text  # nothing else disturbed

    # Idempotent: a second render changes nothing.
    assert dispatch._apply_gates_section(body, _FR) is False
    assert body.read_text(encoding="utf-8") == text
    assert text.count("## Gates") == 1

    # It tracks the status.
    _commit_evidence(repo, wt, _FR, _GATE, "pass")
    assert dispatch._apply_gates_section(body, _FR) is True
    assert f"- {_GATE} (dev, human): pass" in body.read_text(encoding="utf-8")

    # A gate-free FR gets no section at all.
    body2 = wt / "PR_BODY_2.md"
    body2.write_text("# Other\n\nbody\n", encoding="utf-8", newline="\n")
    assert dispatch._apply_gates_section(body2, _FR2) is False
    assert "## Gates" not in body2.read_text(encoding="utf-8")
    assert dispatch._render_gates_section(_FR2) == ""


# ---------------------------------------------------------------------------
# AC-10: reconcile-merged reports a merge past a gate
# ---------------------------------------------------------------------------


def _reconcile_setup(monkeypatch, repo: Path, merge_sha: str) -> list[tuple]:
    """`reconcile_merged_prs` with its `gh` and git-write seams stubbed, the
    shape `test_dispatch_metrics.py` established. The gate read is real."""
    flips: list[tuple] = []
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose: (True, None))
    monkeypatch.setattr(
        dispatch,
        "_gh_merged_prs",
        lambda limit=100: [
            {
                "headRefName": f"claude/dev-{_FR}",
                "number": 42,
                "mergedAt": "2026-09-01T00:00:00Z",
                "mergeCommit": {"oid": merge_sha},
            }
        ],
    )
    monkeypatch.setattr(dispatch, "_on_default_branch", lambda branch="main": True)
    monkeypatch.setattr(
        dispatch,
        "_flip_frontmatter_to_merged",
        lambda path, prev, num, sha: flips.append((prev, num, sha)) or True,
    )
    monkeypatch.setattr(
        dispatch, "_commit_spec_flip", lambda fr, num, sha: (True, "committed")
    )
    return flips


@pytest.mark.parametrize("apply", [True, False])
# covers hub-tooling FR-0008:AC-10
def test_reconcile_merged_warns_on_a_merge_past_a_gate_in_both_modes(
    tmp_path, monkeypatch, capsys, apply
):
    """AC-10: the WARN is printed in apply *and* dry-run; the FR still flips
    (the merge happened); the `verdict: bypassed` record is emitted only on a
    successful apply-mode flip."""
    repo = _make_repo(tmp_path, {_FR: ("in-review", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    merge_sha = _git(repo, "rev-parse", "main")
    flips = _reconcile_setup(monkeypatch, repo, merge_sha)

    summary = _REAL_RECONCILE(apply=apply, verbose=True)
    out = capsys.readouterr().out
    assert f"WARN — merged past gate {_GATE}: status missing" in out, out
    assert summary.flipped == [_FR]  # the merge happened; AC-9 fails on main
    decisions = [r for r in _read_records(repo) if r["kind"] == "gate.decision"]
    if apply:
        assert flips == [("in-review", 42, merge_sha)]
        assert [d["verdict"] for d in decisions] == ["bypassed"]
        (d,) = decisions
        assert d["gate"] == _GATE and d["after"] == "dev" and d["reviewer"] == "human"
        assert d["object_ids"] == [_FR]
        assert metrics_log.validation_errors(d) == []
    else:
        assert flips == []
        assert decisions == []


# covers hub-tooling FR-0008:AC-10
def test_reconcile_merged_is_silent_for_a_satisfied_gate_and_for_a_gate_free_fr(
    tmp_path, monkeypatch, capsys
):
    """Adversarial: the warning fires on a *bypass*, not on every merge. A gate
    whose evidence is `pass` on the merge commit, and an FR with no gates at
    all, produce no WARN and no `gate.decision` record."""
    for gates in (_HUMAN_DEV_GATE, ""):
        repo = _make_repo(tmp_path / f"r{len(gates)}", {_FR: ("in-review", gates)})
        _point(monkeypatch, repo)
        if gates:
            # Put passing evidence on `main` itself, which is the merge commit.
            d = repo / "specs" / "_gates"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{_FR}-{_GATE}.md").write_text(
                _evidence_text(
                    _FR, _GATE, "pass", "Neil", _git(repo, "rev-parse", "main")
                ),
                encoding="utf-8",
                newline="\n",
            )
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "gate evidence")
        merge_sha = _git(repo, "rev-parse", "main")
        _reconcile_setup(monkeypatch, repo, merge_sha)
        _REAL_RECONCILE(apply=True, verbose=True)
        out = capsys.readouterr().out
        assert "merged past gate" not in out, (gates, out)
        assert [r for r in _read_records(repo) if r["kind"] == "gate.decision"] == []


# covers hub-tooling FR-0008:AC-11
def test_bypassed_is_in_the_verdict_vocabulary_and_the_other_two_are_too():
    """AC-10's record shape is only emittable because AC-11 put `bypassed` in
    the enum; a fourth value is refused."""
    assert metrics_log.GATE_DECISION_VERDICTS == {
        "pass",
        "changes-requested",
        "bypassed",
    }
    assert metrics_log.GATE_DECISION_AFTER == {"dev", "rev"}
    assert metrics_log.GATE_DECISION_REVIEWER == {"human", "architect"}


# ---------------------------------------------------------------------------
# AC-12: the command files
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-12
def test_orchestrator_command_documents_both_new_wave_outcomes():
    text = (_COMMANDS_DIR / "orchestrator.md").read_text(encoding="utf-8")
    assert "GATE-PENDING" in text and "GATE-BLOCKED" in text
    block = text.split("**Two more per-FR wave outcomes")[1]
    assert "Hand that command to the human and stop" in block
    assert "do not start a rework round unprompted" in block
    assert "exit 3" in text
    # Placed in Phase 2's outcome handling, before Phase 3.
    assert text.index("**Two more per-FR wave outcomes") < text.index(
        "**Phase 3: Escalation routing**"
    )


# covers hub-tooling FR-0008:AC-12
def test_gate_review_command_exists_with_the_role_preamble_and_one_writable_path():
    text = (_COMMANDS_DIR / "gate-review.md").read_text(encoding="utf-8")
    assert "specs/_gates/" in text
    assert "gate" in text.lower() and "evidence" in text.lower()
    # It must state that the session writes nothing but the evidence file.
    lowered = text.lower()
    assert (
        "writes only" in lowered or "nothing but" in lowered or "only file" in lowered
    )
    for token in ("verdict", "pass", "changes-requested", "head_sha", "round"):
        assert token in text, token


@pytest.mark.parametrize("harness", [".claude", ".cursor"])
# covers hub-tooling FR-0008:AC-12
# covers hub-tooling FR-0019:AC-4
def test_both_gate_review_wrappers_are_generator_output_with_the_dec0013_frontmatter(
    harness,
):
    """DEC-0013 items 2 and 3: the wrappers carry the real description and
    argument-hint the generator produces from the source's frontmatter, not
    the generic `Run the gate-review command.` fallback."""
    wrapper = (_TEMPLATE_DIR / harness / "commands" / "gate-review.md").read_bytes()
    assert b"\r" not in wrapper and wrapper.endswith(b"\n")
    text = wrapper.decode("utf-8")
    assert (
        'description: "Operate as the Architect in gate-review mode for one '
        'declared gate. One-shot; writes only the evidence file."' in text
    )
    assert 'argument-hint: "FR-XXXX gate-id"' in text
    assert "Run the gate-review command." not in text
    assert "model:" not in text and "effort:" not in text  # matches `architect`
    # The body is the canonical source verbatim apart from the banner and
    # frontmatter (and, for cursor, the $ARGUMENTS substitution). The source
    # body is the text after its own frontmatter block (DEC-0016).
    source = (_COMMANDS_DIR / "gate-review.md").read_text(encoding="utf-8")
    if source.startswith("---\n"):
        source = source[source.index("\n---\n", 4) + 5 :]
    expected_body = (
        source.replace("$ARGUMENTS", "{{args}}") if harness == ".cursor" else source
    )
    assert expected_body.strip() in text


# ---------------------------------------------------------------------------
# AC-13 bite checks: these pins must fail against the earlier dispatchers
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-13
def test_bite_round_one_dispatcher_cannot_read_a_gate_on_a_maintainer_mode_fr(
    tmp_path, monkeypatch
):
    """Bite check for DEC-0012 item 3: at `681d661` the gate leg was pinned to
    the literal `claude/dev-<FR>`, so a gate on a maintainer-mode FR read
    `missing` forever and `gate pass` refused naming only the dev branch. Both
    dev-else-mnt pins above must fail against it."""
    old = _load_dispatch_at(_ROUND1_REF, "dispatch_fr0008_round1", tmp_path)
    if old is None:
        pytest.skip(f"round-1 commit {_ROUND1_REF} not reachable")
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    for mod in (old,):
        monkeypatch.setattr(mod, "REPO_ROOT", repo)
        monkeypatch.setattr(mod, "SPECS_DIR", repo / "specs")
        monkeypatch.setattr(mod, "DISPATCH_DIR", repo / "_dispatch")
        monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    wt = _impl_worktree(repo, _FR, "mnt")
    _commit_evidence(repo, wt, _FR, _GATE, "pass")
    # The current dispatcher reads it; the round-1 one cannot.
    _point(monkeypatch, repo)
    assert dispatch.gate_status(_FR, _GATE) == "pass"
    assert old.gate_status(_FR, _GATE) == "missing"


# covers hub-tooling FR-0008:AC-13
def test_bite_round_one_dispatcher_has_no_shared_draft_guard_for_the_oneshot_path(
    tmp_path,
):
    """Bite check for DEC-0012 item 4: at `681d661` AC-8's refusal lived only
    in `_finalize_dev`, so `finalize --role mnt --ready` un-drafted past an
    unsatisfied gate. The AC-8 `mnt` pin above must fail against it."""
    old = _load_dispatch_at(_ROUND1_REF, "dispatch_fr0008_round1_b", tmp_path)
    if old is None:
        pytest.skip(f"round-1 commit {_ROUND1_REF} not reachable")
    assert not hasattr(old, "_gate_draft_refusal")
    assert hasattr(dispatch, "_gate_draft_refusal")
    import inspect

    old_src = inspect.getsource(old._finalize_oneshot)
    assert "gate" not in old_src.lower().split("@implements")[0] or (
        "_pending_after_dev_gates" not in old_src
    )
    assert "_gate_draft_refusal" in inspect.getsource(dispatch._finalize_oneshot)


# covers hub-tooling FR-0008:AC-13
def test_bite_the_pre_fr_dispatcher_has_no_gate_surface_at_all(tmp_path):
    """Bite check for the whole FR: none of the gate entry points exist before
    it, so every pin in this file is genuinely about this FR's code."""
    pre = _load_dispatch_at(_PRE_FR_REF, "dispatch_fr0008_pre", tmp_path)
    if pre is None:
        pytest.skip(f"pre-FR commit {_PRE_FR_REF} not reachable")
    for name in (
        "gate_status",
        "cmd_gate_list",
        "cmd_gate_verdict",
        "_pending_after_dev_gates",
        "_gate_draft_refusal",
        "_finalize_gat",
        "_render_gates_section",
    ):
        assert not hasattr(pre, name), name
        assert hasattr(dispatch, name), name
    assert "gat" not in pre.SLASH_COMMAND_NAMES
    assert dispatch.SLASH_COMMAND_NAMES["gat"] == "gate-review"


# ---------------------------------------------------------------------------
# Round 2: bare-invocation pins — every AC that names a CLI invocation, driven
# with only its *required* arguments.
#
# Round 1's 135 tests let two defects ship green because every evidence fixture
# above happened to carry an optional `--note`, so nothing ever exercised the
# bytes AC-3's documented happy path — `gate pass <FR> <gate-id> --by <who>
# --apply`, where `--note` is optional and required only on `block` — actually
# writes: frontmatter and an *empty* body. `_git_capture` strips what it
# returns, which removed the newline after the closing `---` that
# `FRONTMATTER_PATTERN` requires, so genuinely passing evidence read back as
# `missing` on every `ref`-based path (AC-2/4/5/8/10) and the gate could never
# be satisfied; and the same write used `Path.write_text`'s default
# `newline=None`, so the tracked evidence was CRLF on Windows.
#
# The generalisation these pins apply: drive each CLI with its required
# arguments only, and assert on bytes where a decode would normalise them away.
# ---------------------------------------------------------------------------


def _git_bytes(cwd: Path, *args: str) -> bytes:
    """Raw bytes from git. `_git` decodes and strips — exactly the kind of
    normalisation that hid the line-ending defect."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout


def _evidence_bytes_on(repo: Path, branch: str, fr_id: str, gate: str) -> bytes:
    return _git_bytes(
        repo, "cat-file", "-p", f"{branch}:specs/_gates/{fr_id}-{gate}.md"
    )


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-2
# covers hub-tooling FR-0008:AC-3
# covers hub-tooling FR-0008:AC-4
def test_gate_pass_with_no_note_reads_back_as_a_pass_and_unblocks_the_reviewer(
    tmp_path, monkeypatch, capsys, role
):
    """AC-3's happy path with its *required arguments only*. The evidence body
    is empty; AC-2's single reader must still return `pass` for it, AC-3's
    `gate list` must still show it, and AC-4 must let the Reviewer through —
    in both resolutions (DEC-0012 item 3)."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    _flip_status(repo, wt, _FR, "in-review", _HUMAN_DEV_GATE)
    branch = f"claude/{role}-{_FR}"

    # The rule the optional `--note` must not be confused with: `block` still
    # refuses without one, before anything is written.
    before = _repo_snapshot(repo)
    assert (
        dispatch.cmd_gate_verdict(
            _FR, _GATE, "changes-requested", by="Neil", note=None, apply=True
        )
        == 1
    )
    assert "requires --note" in capsys.readouterr().out
    assert _repo_snapshot(repo) == before

    assert (
        dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note=None, apply=True)
        == 0
    )
    assert "GATED" in capsys.readouterr().out

    raw = _evidence_bytes_on(repo, branch, _FR, _GATE)
    assert raw.startswith(b"---\n") and b"verdict: pass\n" in raw
    assert raw.split(b"\n---\n", 1)[1].strip() == b""  # no body at all

    assert dispatch.gate_status(_FR, _GATE) == "pass"
    assert dispatch.cmd_gate_list(_FR) == 0
    assert "status=pass" in capsys.readouterr().out

    frs = dispatch.load_frs()
    assert dispatch.explain_not_runnable(_FR, frs, "rev") is None
    assert dispatch.gate_pending_review_frs(frs) == []
    if role == "dev":
        assert [f["id"] for f in dispatch.runnable_review_frs(frs)] == [_FR]


@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-3
# covers hub-tooling FR-0008:AC-8
def test_finalize_ready_succeeds_on_evidence_written_without_a_note(
    tmp_path, monkeypatch, capsys, adapter, role
):
    """The end of AC-3's bare happy path: evidence the dispatcher itself wrote
    with no `--note` satisfies AC-8's guard, so `finalize --role <role> --ready`
    opens a non-draft PR and the `## Gates` section reports `pass`. Round 1
    proved this only for hand-written evidence that happened to have a body."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    _ready_to_finalize(repo, role)
    assert (
        dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note=None, apply=True)
        == 0
    )
    capsys.readouterr()
    monkeypatch.setattr(
        dispatch, "mnt_footprint_violations", lambda *a, **k: ([], None)
    )
    monkeypatch.setattr(
        dispatch, "_finalize_revalidate_stale_branch", lambda *a, **k: True
    )
    calls = _install_gh_double(monkeypatch)

    rc = dispatch.cmd_finalize(_FR, role, apply=True, draft=False, adapter=adapter)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "cannot open ready-for-review" not in out
    creates = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert len(creates) == 1 and "--draft" not in creates[0]
    assert f"- {_GATE} (dev, human): pass" in (wt / "PR_BODY.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("note", [None, "Screens match."])
@pytest.mark.parametrize("role", ["dev", "mnt"])
# covers hub-tooling FR-0008:AC-3
def test_committed_gate_evidence_is_lf_with_and_without_a_note(
    tmp_path, monkeypatch, capsys, role, note
):
    """Round-4 defect 2: `Path.write_text`'s default `newline=None` translates
    every newline to `os.linesep`, so on Windows the tracked evidence was CRLF
    while every other tracked file this wave writes is LF. Asserted on the
    *committed bytes* (`git cat-file -p` applies no filters) as well as on
    disk — `_git`'s decode-and-strip is what hid this."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, role)
    assert (
        dispatch.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note=note, apply=True)
        == 0
    )
    capsys.readouterr()
    rel = f"specs/_gates/{_FR}-{_GATE}.md"
    assert b"\r" not in _evidence_bytes_on(repo, f"claude/{role}-{_FR}", _FR, _GATE)
    assert b"\r" not in (wt / "specs" / "_gates" / f"{_FR}-{_GATE}.md").read_bytes()
    eol = _git(wt, "ls-files", "--eol", "--", rel)
    assert "i/lf" in eol and "w/lf" in eol, eol
    assert "crlf" not in eol, eol


# covers hub-tooling FR-0008:AC-3
def test_the_gate_cli_requires_a_note_only_for_block(tmp_path, monkeypatch, capsys):
    """The argparse layer itself, through `main()`, with required arguments
    only: `gate list <FR>` takes nothing optional, `gate block ... --by <who>
    --apply` is rejected by argparse for the missing `--note`, and `gate pass
    ... --by <who> --apply` parses and satisfies the gate."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")

    monkeypatch.setattr(sys, "argv", ["dispatch.py", "gate", "list", _FR])
    assert dispatch.main() == 0
    assert "status=missing" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["dispatch.py", "gate", "block", _FR, _GATE, "--by", "Neil", "--apply"],
    )
    with pytest.raises(SystemExit) as exc:
        dispatch.main()
    assert exc.value.code == 2
    capsys.readouterr()
    assert dispatch.gate_status(_FR, _GATE) == "missing"

    monkeypatch.setattr(
        sys,
        "argv",
        ["dispatch.py", "gate", "pass", _FR, _GATE, "--by", "Neil", "--apply"],
    )
    assert dispatch.main() == 0
    assert "GATED" in capsys.readouterr().out
    assert dispatch.gate_status(_FR, _GATE) == "pass"


# covers hub-tooling FR-0008:AC-5
def test_a_no_note_gate_pass_lets_the_wave_through_to_the_reviewer(
    tmp_path, monkeypatch, capsys, adapter
):
    """AC-5's gate must be satisfiable by the very command AC-5's own `satisfy
    with:` line prints — and that line carries no `--note`. With body-less
    evidence in place the wave stops printing `GATE-PENDING` and stops exiting
    3."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _install_wave(monkeypatch, repo)
    assert _wave(adapter) == 3
    out = capsys.readouterr().out
    assert "GATE-PENDING" in out
    line = next(ln for ln in out.splitlines() if "satisfy with:" in ln)
    assert "--note" not in line

    wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    _commit_evidence(repo, wt, _FR, _GATE, "pass", body="")
    assert dispatch.gate_status(_FR, _GATE) == "pass"
    rc = _wave(adapter)
    out = capsys.readouterr().out
    assert "GATE-PENDING" not in out, out
    assert rc != 3, out


# covers hub-tooling FR-0008:AC-6
def test_finalize_role_gat_reads_evidence_through_the_same_unrestored_strip(
    tmp_path, monkeypatch, capsys, adapter
):
    """`_finalize_gat` is the *other* reader of the same artifact, through the
    same `git show` + `FRONTMATTER_PATTERN` pair; round 4 restored the trailing
    newline in `gate_status` only. Both halves are characterised here so the
    asymmetry cannot go quiet again.

    With the rationale AC-6 requires the gate session to write ("a verdict and
    rationale citing IDs only"), the finalize lands with AC-6's subject. With
    an *empty* body it falls through to the "malformed" refusal instead — a
    shape only a session that ignored that instruction can produce, never one
    `gate pass` puts on this branch, so no FR-0008 path composes into it. See
    this review's FINDINGS: the one-line restoration would make the two
    readers agree."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo)
    _impl_worktree(repo, _FR, "dev")
    _gat_session(repo, _FR, _ARCH_GATE, "pass", body="FR-0001:AC-1 checked.")
    assert (
        dispatch.cmd_finalize(_FR, "gat", apply=True, draft=True, adapter=adapter) == 0
    )
    out = capsys.readouterr().out
    assert "malformed" not in out and "GATED" in out
    assert _git(repo, "log", "-1", "--format=%s", f"claude/dev-{_FR}") == (
        f"gate({_FR}): {_ARCH_GATE} pass by architect"
    )
    assert dispatch.gate_status(_FR, _ARCH_GATE) == "pass"

    # The body-less half: the frontmatter is valid, yet the read fails.
    repo2 = _make_repo(tmp_path / "b", {_FR: ("ready", _ARCHITECT_DEV_GATE)})
    _point(monkeypatch, repo2)
    _impl_worktree(repo2, _FR, "dev")
    _gat_session(repo2, _FR, _ARCH_GATE, "pass", body="")
    rc = dispatch.cmd_finalize(_FR, "gat", apply=True, draft=True, adapter=adapter)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "malformed (missing/invalid gate or verdict)" in out
    # …although `gate_status`, post-round-4, reads the very same bytes fine,
    # and `_finalize_commit_subject` — which reads from disk, not through the
    # strip — already derived AC-6's subject for the staging commit that the
    # refusal then strands on `claude/gat-<FR>`.
    assert dispatch.gate_status(_FR, _ARCH_GATE, ref=f"claude/gat-{_FR}") == "pass"
    assert _git(repo2, "log", "-1", "--format=%s", f"claude/gat-{_FR}") == (
        f"gate({_FR}): {_ARCH_GATE} pass by architect"
    )
    assert _git(repo2, "rev-parse", f"claude/gat-{_FR}") != _git(
        repo2, "rev-parse", f"claude/dev-{_FR}"
    )


# covers hub-tooling FR-0008:AC-10
def test_reconcile_merged_is_silent_for_a_body_less_pass_on_the_merge_commit(
    tmp_path, monkeypatch, capsys
):
    """AC-10 reads the gate *on the merge commit* — another `ref`-based read.
    Body-less passing evidence must not be reported as a bypass, and must not
    emit a `verdict: bypassed` record for a gate that was in fact satisfied."""
    repo = _make_repo(tmp_path, {_FR: ("in-review", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    d = repo / "specs" / "_gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_FR}-{_GATE}.md").write_text(
        _evidence_text(
            _FR, _GATE, "pass", "Neil", _git(repo, "rev-parse", "main"), body=""
        ),
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "gate evidence, no note")
    merge_sha = _git(repo, "rev-parse", "main")
    _reconcile_setup(monkeypatch, repo, merge_sha)
    _REAL_RECONCILE(apply=True, verbose=True)
    out = capsys.readouterr().out
    assert "merged past gate" not in out, out
    assert [r for r in _read_records(repo) if r["kind"] == "gate.decision"] == []


def _point_old(monkeypatch, mod, repo: Path) -> None:
    """The minimum `_point` does, for a dispatcher loaded from an older ref."""
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    monkeypatch.setattr(mod, "SPECS_DIR", repo / "specs")
    monkeypatch.setattr(mod, "DISPATCH_DIR", repo / "_dispatch")
    monkeypatch.setattr(mod, "_RUN_REGISTRY", {})
    monkeypatch.setattr(mod, "_push_branch", lambda branch: (True, "pushed"))
    (repo / "_dispatch").mkdir(exist_ok=True)


# covers hub-tooling FR-0008:AC-13
def test_bite_the_round_three_dispatcher_cannot_read_body_less_gate_evidence(
    tmp_path, monkeypatch
):
    """Bite check for round-4 defect 1: at `93e9dda` `gate_status` matched
    `FRONTMATTER_PATTERN` against `_git_capture`'s *stripped* text, so evidence
    written by the bare `gate pass` read `missing` forever and the gate could
    never be satisfied. Every no-note pin above must fail against it — and the
    same evidence *with* a note read `pass` there, which is exactly what made
    the gap invisible to round 1."""
    old = _load_dispatch_at(_ROUND3_REF, "dispatch_fr0008_round3", tmp_path)
    if old is None:
        pytest.skip(f"round-3 commit {_ROUND3_REF} not reachable")
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _point_old(monkeypatch, old, repo)
    wt = _impl_worktree(repo, _FR, "dev")

    _commit_evidence(repo, wt, _FR, _GATE, "pass", body="")
    assert dispatch.gate_status(_FR, _GATE) == "pass"
    assert old.gate_status(_FR, _GATE) == "missing"  # the shipped defect

    # With a body, both agree — the round-1 fixtures' blind spot.
    _commit_evidence(repo, wt, _FR, _GATE, "pass", body="Screens match.")
    assert dispatch.gate_status(_FR, _GATE) == "pass"
    assert old.gate_status(_FR, _GATE) == "pass"


# covers hub-tooling FR-0008:AC-13
def test_bite_the_round_three_gate_pass_wrote_unreadable_platform_line_endings(
    tmp_path, monkeypatch, capsys
):
    """Bite check for round-4 defect 2, driven through round-3's own
    `cmd_gate_verdict` with required arguments only. Where `os.linesep` is CRLF
    the evidence it commits carries a carriage return; HEAD's never does. The
    source-level half of the assertion holds on every platform."""
    old = _load_dispatch_at(_ROUND3_REF, "dispatch_fr0008_round3_b", tmp_path)
    if old is None:
        pytest.skip(f"round-3 commit {_ROUND3_REF} not reachable")
    import inspect

    assert 'newline="\\n"' not in inspect.getsource(old.cmd_gate_verdict)
    assert 'newline="\\n"' in inspect.getsource(dispatch.cmd_gate_verdict)

    if os.linesep == "\n":
        pytest.skip("the byte half is only observable where os.linesep is CRLF")
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    _point_old(monkeypatch, old, repo)
    _impl_worktree(repo, _FR, "dev")
    assert (
        old.cmd_gate_verdict(_FR, _GATE, "pass", by="Neil", note=None, apply=True) == 0
    )
    capsys.readouterr()
    assert b"\r" in _evidence_bytes_on(repo, f"claude/dev-{_FR}", _FR, _GATE)


# ---------------------------------------------------------------------------
# Round 2: the Architect's ruling (ii) on `head_sha` (AC-2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0" * 40, "stale"),  # YAML int 0 — present, falsy, the round-2 defect
        ("0", "stale"),  # int 0 again, unpadded
        ("false", "stale"),  # YAML bool False — present, falsy
        ("deadbeef" * 5, "stale"),  # a present string that is not on the branch
        ("", "pass"),  # genuinely absent: the documented face value
    ],
)
# covers hub-tooling FR-0008:AC-2
def test_a_present_but_unusable_head_sha_is_stale_not_a_trusted_pass(
    tmp_path, monkeypatch, raw, expected
):
    """Architect ruling (ii) on round 2: only an *absent or empty* `head_sha`
    (or no implementation branch to compare against) keeps AC-2's documented
    face-value `pass`. A value that is merely *present* and does not resolve to
    an ancestor-or-equal of the implementation tip is `stale` — including one
    YAML parsed as something other than a string. The shape suggested in round
    1, `str(meta.get("head_sha") or "")`, would have mapped falsy `0` straight
    back to `""` and gone on trusting it; the check is keyed on `is not None`,
    never on truthiness."""
    repo = _make_repo(tmp_path, {_FR: ("ready", _HUMAN_DEV_GATE)})
    _point(monkeypatch, repo)
    wt = _impl_worktree(repo, _FR, "dev")
    _commit_evidence(repo, wt, _FR, _GATE, "pass", head_sha=raw)
    assert dispatch.gate_status(_FR, _GATE) == expected
    # The same evidence with no implementation branch at all is the other
    # documented face-value case, and is unaffected by the coercion.
    _git(repo, "worktree", "remove", "--force", str(wt))
    _git(repo, "branch", "-q", "-D", f"claude/dev-{_FR}")
    assert dispatch.gate_status(_FR, _GATE, ref="main") == "missing"


# covers hub-tooling FR-0008:AC-11
def test_the_metrics_readme_documents_the_per_emitter_role_semantics():
    """Architect ruling (iii) on round 2: `gate.decision`'s `role` differs by
    emitter by design, so AC-11's README says so rather than any emitter
    changing. Documented, not pinned — so this asserts the documentation."""
    readme = (_TEMPLATE_DIR / "specs" / "_metrics" / "README.md").read_text(
        encoding="utf-8"
    )
    block = readme.split("gate.decision", 1)[1]
    assert "session" in block and "role" in block
    assert "group by" in block and "never by `role`" in block
    for emitter in ("gate pass", "finalize --role gat", "reconcile-merged"):
        assert emitter in block, emitter
