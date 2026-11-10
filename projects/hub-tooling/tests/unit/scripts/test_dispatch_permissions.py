"""Reviewer tests for FR-0009 — a dispatched Developer's worktree permission
file unions the FR's `owns:` footprint into the static `dev` grants (AC-1,
AC-8), withholds and reports protected control-plane paths without narrowing
the static deny list (AC-2), reports harness-guarded globs before the spawn
line (AC-3), degrades to byte-identical pre-FR output for an ownerless FR
(AC-4), refuses malformed footprints with the indexer's own rule (AC-5),
re-derives on worktree reuse (AC-6), states `owns-grants=<n>` on the spawn
report in `tick` and `wave` without mutating anything in dry-run (AC-7),
leaves `mnt` / `rev` / `bkf` byte-for-byte alone (AC-9; for `rev` / `bkf`, for
an ownerless FR — DEC-0002), and is sufficient for the Project A FR-0001 footprint
that motivated the FR (AC-10).

Harness: `dispatch.py` loaded by path with its path globals pointed at a real
temporary git repository (worktrees are the subject of AC-6/AC-7), a fake
harness adapter that records spawns and delegates only
`write_worktree_settings` to the real `ClaudeCodeAdapter` / `CursorAdapter`,
and the venv provisioner / gh preflight / reconcile stubbed. No network, no
`claude` binary.

The "pre-FR dispatcher" that AC-4 and AC-9 compare against is loaded from
`git show <pre-FR ref>:template/scripts/dispatch.py` — the hub commit FR-0009
branched from — rather than from a hand-written expectation. Inside a
bootstrapped project (where this file rides along) that object does not
exist, and those comparisons skip; the static-payload comparisons next to
them do not depend on it and always run.

Coverage annotations are written `# covers hub-tooling FR-0009:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0009 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (same convention as
test_dispatch_runnability.py / test_dispatch_finalize.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_FIXTURE_SPECS = _TEMPLATE_DIR / "tests" / "fixtures" / "dispatch-permissions" / "specs"
_PROJECT_A_FIXTURE = _FIXTURE_SPECS / "FR-9010-project-a-footprint.md"
# The hub commit FR-0009 branched from (`main` at the time of the Developer
# pass). Used only to load the pre-FR dispatcher for AC-4 / AC-9 comparisons.
_PRE_FR_REF = "647f353"

_FR = "FR-0001"
_FR2 = "FR-0002"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import metrics_log
import spec_footprint


def _load_dispatch(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_dispatch(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0009")


@functools.lru_cache(maxsize=1)
def _pre_fr_source() -> bytes | None:
    """`template/scripts/dispatch.py` as of the pre-FR hub commit, or None when
    that object is unreachable (bootstrapped project, shallow clone)."""
    hub_root = _TEMPLATE_DIR.parent
    proc = subprocess.run(
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
    """The pre-FR dispatcher as a module, or a skip when unavailable."""
    src = _pre_fr_source()
    if src is None:
        pytest.skip(
            f"pre-FR dispatch.py ({_PRE_FR_REF}) not reachable from {_TEMPLATE_DIR.parent}"
        )
    d = tmp_path_factory.mktemp("pre_fr_scripts")
    (d / "dispatch.py").write_bytes(src)
    return _load_dispatch(d / "dispatch.py", "dispatch_pre_fr0009")


# ---------------------------------------------------------------------------
# Synthetic FR fixtures
# ---------------------------------------------------------------------------

_AC1_OWNS = [
    ".python-version",
    "migrations/**",
    "frontend/*",
    ".github/workflows/stack-ci.yml",
]
_AC2_OWNS = [
    "scripts/deploy-gate.py",
    ".agent-team/roles/developer.md",
    "tests/test_foo.py",
    "CLAUDE.md",
]
_AC10_OWNS = [
    "src/project_a/*.py",
    "alembic.ini",
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/README.md",
    "docker-compose.yml",
    ".env.example",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "requirements.txt",
    "pytest.ini",
    "tests/conftest.py",
    "tests/smoke/**",
    "frontend/*",
    "frontend/public/**",
    "frontend/src/main.tsx",
    "frontend/src/App.tsx",
    "frontend/src/vite-env.d.ts",
    "frontend/src/api/**",
    ".github/workflows/stack-ci.yml",
    "README.md",
]


def _owns_yaml(owns: list[str] | None) -> str:
    """Render an `owns:` line. None omits the key entirely."""
    if owns is None:
        return ""
    return "owns: " + json.dumps(owns) + "\n"


def _fr_md(
    fr_id: str, owns: list[str] | None = None, *, owns_raw: str | None = None
) -> str:
    """Synthetic FR markdown. `owns_raw` is verbatim YAML for the field (used
    for malformed shapes a JSON list cannot express)."""
    owns_line = owns_raw if owns_raw is not None else _owns_yaml(owns)
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: ready
owner: architect
depends_on: []
tags: []
{owns_line}reads: []
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


def _write_spec(repo: Path, fr_id: str, text: str) -> Path:
    p = repo / "specs" / f"{fr_id}-synthetic.md"
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def _make_repo(tmp_path: Path, specs: dict[str, str]) -> Path:
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
    for fr_id, text in specs.items():
        _write_spec(repo, fr_id, text)
    # A tracked control-plane tree so `mnt_permission_rules` has siblings to
    # enumerate (AC-9 compares that derivation against the pre-FR module).
    for rel in (
        ".agent-team/roles/developer.md",
        ".agent-team/roles/reviewer.md",
        "scripts/deploy-gate.py",
        "scripts/setup.py",
        "src/thing.py",
    ):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}\n", encoding="utf-8", newline="\n")
    (repo / ".gitignore").write_text(
        f".claude/settings.local.json\n.cursor/cli.json\n{dispatch.VENV_DIRNAME}/\n"
        "__pycache__/\n_dispatch/\nmetrics/\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit_spec(repo: Path, fr_id: str, text: str, msg: str = "spec update") -> None:
    p = _write_spec(repo, fr_id, text)
    _git(repo, "add", str(p.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", msg)


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
    (r / "_dispatch").mkdir(exist_ok=True)


class _FakeAdapter:
    """Records spawns; delegates settings writing to a real adapter so the
    permission file under test is the one the real code writes."""

    name = "fake"
    binary_name = "fake"

    def __init__(self, real) -> None:
        self.real = real
        self.spawns: list[tuple[str, str, Path, str | None]] = []

    def write_worktree_settings(self, wt_path: Path, role: str, fr_id: str) -> None:
        self.real.write_worktree_settings(wt_path, role, fr_id)

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
    r = _make_repo(tmp_path, {_FR: _fr_md(_FR, _AC1_OWNS)})
    _point(monkeypatch, dispatch, r)
    return r


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter(dispatch.ClaudeCodeAdapter())


def _records() -> list[dict]:
    d = metrics_log.METRICS_DIR
    if not d.exists():
        return []
    return [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def _lf(data: bytes) -> bytes:
    """Normalise the platform newline translation `Path.write_text` applies
    (CRLF on Windows — pre-existing, identical for every role) so byte
    comparisons against a JSON expectation are about content."""
    return data.replace(b"\r\n", b"\n")


def _settings(wt: Path) -> dict[str, list[str]]:
    return json.loads(
        (wt / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )["permissions"]


def _cursor_settings(wt: Path) -> dict[str, list[str]]:
    return json.loads((wt / ".cursor" / "cli.json").read_text(encoding="utf-8"))[
        "permissions"
    ]


def _static(
    mod=dispatch, adapter_cls: str = "ClaudeCodeAdapter", role: str = "dev"
) -> dict[str, list[str]]:
    perms = getattr(mod, adapter_cls).ROLE_PERMISSIONS[role]
    return {"allow": list(perms["allow"]), "deny": list(perms["deny"])}


def _grants(perms: dict[str, list[str]], tool: str) -> list[str]:
    return [a[len(tool) + 1 : -1] for a in perms["allow"] if a.startswith(f"{tool}(")]


def _warn_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if "WARN" in ln]


def _error_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if "ERROR" in ln]


def _tree_digest(root: Path) -> str:
    """Content digest of every file under `root` (or "absent")."""
    if not root.exists():
        return "absent"
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _dev_wt(repo: Path, fr_id: str = _FR) -> Path:
    return repo / ".claude" / "worktrees" / f"dev-{fr_id}"


# ---------------------------------------------------------------------------
# AC-1: the Developer's permission file unions `owns:` into the static grants
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-1
def test_claude_dev_settings_are_static_allow_plus_edit_and_write_for_every_owned_glob(
    repo, adapter, tmp_path
):
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    perms = _settings(wt)
    static = _static()
    # Static allow list preserved verbatim and in order; deny untouched.
    assert perms["allow"][: len(static["allow"])] == static["allow"]
    assert perms["deny"] == static["deny"]
    for glob in _AC1_OWNS:
        assert f"Edit({glob})" in perms["allow"], glob
        assert f"Write({glob})" in perms["allow"], glob
    # ...and nothing else was added beyond those two grants per glob.
    extra = perms["allow"][len(static["allow"]) :]
    assert sorted(extra) == sorted(
        [f"Edit({g})" for g in _AC1_OWNS] + [f"Write({g})" for g in _AC1_OWNS]
    )


# covers hub-tooling FR-0009:AC-1
def test_owned_globs_are_granted_verbatim_never_expanded_against_tracked_files(
    repo, adapter, tmp_path
):
    """Adversarial: none of the four globs matches a tracked file (this is the
    create case that failed in Project A). The grant must still be written, and
    written as declared — no `./` stripping, no expansion, no reordering."""
    tracked = _git(repo, "ls-files").splitlines()
    assert not any(
        t.startswith((".python-version", "migrations/", "frontend/", ".github/"))
        for t in tracked
    )
    _write_spec(repo, _FR, _fr_md(_FR, ["./docs/notes.md", "frontend/*", "**/*.sql"]))
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    assert _grants(_settings(wt), "Edit")[-3:] == [
        "./docs/notes.md",
        "frontend/*",
        "**/*.sql",
    ]
    assert _grants(_settings(wt), "Write")[-3:] == [
        "./docs/notes.md",
        "frontend/*",
        "**/*.sql",
    ]


# ---------------------------------------------------------------------------
# AC-2: protected paths are withheld, reported, and never narrow the deny list
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-2
def test_protected_owns_get_zero_grants_static_deny_and_one_warn_each(
    repo, adapter, tmp_path, capsys
):
    _commit_spec(repo, _FR, _fr_md(_FR, _AC2_OWNS))
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    perms = _settings(wt)
    assert perms == _static()  # zero grants; deny byte-identical to static
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    warns = _warn_lines(out)
    assert len(warns) == 4
    for glob, line in zip(_AC2_OWNS, warns):
        assert glob in line and "mnt" in line and _FR in line, line
    assert f"{_FR}  WOULD-SPAWN" in out  # the spawn proceeds


# covers hub-tooling FR-0009:AC-2
def test_owns_touching_protected_paths_only_via_double_star_is_still_withheld(
    repo, adapter, tmp_path, capsys
):
    """Adversarial: `scripts/**`, `.agent-team/**` and a bare `**` each cover
    a protected path only through a wildcard; granting them would hand `dev`
    an `Edit(scripts/**)` escape around the per-file denies."""
    owns = ["scripts/**", ".agent-team/**", "**", "scripts/setup.py"]
    _commit_spec(repo, _FR, _fr_md(_FR, owns))
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    perms = _settings(wt)
    granted = _grants(perms, "Edit")
    assert (
        "scripts/**" not in granted
        and ".agent-team/**" not in granted
        and "**" not in granted
    )
    assert "scripts/setup.py" in granted  # unprotected sibling is not over-withheld
    assert perms["deny"] == _static()["deny"]
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    warns = _warn_lines(capsys.readouterr().out)
    assert [w for w in warns if "'scripts/**'" in w] and [
        w for w in warns if "'**'" in w
    ]
    assert len(warns) == 3


# covers hub-tooling FR-0009:AC-2
def test_dev_deny_list_is_never_narrowed_unlike_mnt(repo, adapter, tmp_path):
    """Adversarial: for the same `owns:`, `mnt` rewrites `.agent-team/**` into
    per-sibling denies; `dev` must keep the broad static deny verbatim."""
    _write_spec(repo, _FR, _fr_md(_FR, [".agent-team/roles/developer.md", "src/**"]))
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    assert _settings(wt)["deny"] == _static()["deny"]
    assert "Edit(.agent-team/**)" in _settings(wt)["deny"]
    mnt = dispatch.ClaudeCodeAdapter().mnt_permissions(_FR)
    assert "Edit(.agent-team/**)" not in mnt["deny"]  # the narrowing is mnt's alone
    assert "Edit(.agent-team/roles/reviewer.md)" in mnt["deny"]


# ---------------------------------------------------------------------------
# AC-3: harness-guarded globs are reported before the spawn line
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-3
def test_harness_guarded_glob_warns_once_with_route_before_would_spawn(
    repo, adapter, tmp_path, capsys
):
    _commit_spec(repo, _FR, _fr_md(_FR, [".claude/commands/developer.md"]))
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    warns = [i for i, ln in enumerate(lines) if "WARN" in ln]
    spawn = [i for i, ln in enumerate(lines) if "WOULD-SPAWN" in ln]
    assert len(warns) == 1 and len(spawn) == 1 and warns[0] < spawn[0]
    warn = lines[warns[0]]
    assert ".claude/commands/developer.md" in warn and "harness" in warn
    assert dispatch.mnt_unwritable_hint(".claude/commands/developer.md") in warn
    assert "owns-grants=1" in lines[spawn[0]]
    # The FR's default: the grant is still written (the WARN is the mitigation).
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    assert "Edit(.claude/commands/developer.md)" in _settings(wt)["allow"]


# covers hub-tooling FR-0009:AC-3
def test_harness_guarded_glob_without_a_known_route_warns_once_before_spawned(
    repo, adapter, capsys
):
    """Adversarial: a `.claude/**` path with no `mnt_unwritable_hint` entry
    still gets exactly one WARN (no dangling '; ' suffix), and in apply mode
    the WARN precedes the SPAWNED line."""
    glob = ".claude/settings.local.json"
    assert dispatch.mnt_unwritable_hint(glob) is None
    _commit_spec(repo, _FR, _fr_md(_FR, [glob, "src/**"]))
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    lines = capsys.readouterr().out.splitlines()
    warns = [i for i, ln in enumerate(lines) if "WARN" in ln]
    spawned = [i for i, ln in enumerate(lines) if "SPAWNED" in ln]
    assert len(warns) == 1 and len(spawned) == 1 and warns[0] < spawned[0]
    assert glob in lines[warns[0]] and not lines[warns[0]].rstrip().endswith(";")
    assert "owns-grants=2" in lines[spawned[0]]
    assert [s[1] for s in adapter.spawns] == ["dev"]


# ---------------------------------------------------------------------------
# AC-4: an FR with no `owns:` behaves exactly as today
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-4
def test_ownerless_fr_permission_file_is_byte_identical_to_pre_fr_dispatcher(
    repo, adapter, tmp_path, monkeypatch, pre_fr_dispatch
):
    _point(monkeypatch, pre_fr_dispatch, repo)
    _write_spec(repo, _FR, _fr_md(_FR, []))
    old_wt, new_wt = tmp_path / "old", tmp_path / "new"
    pre_fr_dispatch.ClaudeCodeAdapter().write_worktree_settings(old_wt, "dev", _FR)
    adapter.write_worktree_settings(new_wt, "dev", _FR)
    assert (new_wt / ".claude" / "settings.local.json").read_bytes() == (
        old_wt / ".claude" / "settings.local.json"
    ).read_bytes()


# covers hub-tooling FR-0009:AC-4
@pytest.mark.parametrize("shape", ["absent", "empty-list", "null"])
def test_missing_empty_or_null_owns_gives_static_grants_no_warn_and_spawns(
    repo, adapter, tmp_path, capsys, shape
):
    """Adversarial: three spellings of "no footprint" — key absent, `[]`,
    `null` — all degrade to the static file, print no footprint WARN, report
    `owns-grants=0`, and (unlike `mnt`) are not refused."""
    raw = {"absent": None, "empty-list": "owns: []\n", "null": "owns: null\n"}[shape]
    text = _fr_md(_FR, None) if raw is None else _fr_md(_FR, owns_raw=raw)
    _commit_spec(repo, _FR, text)
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    assert (
        _lf((wt / ".claude" / "settings.local.json").read_bytes())
        == (json.dumps({"permissions": _static()}, indent=2) + "\n").encode()
    )
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    assert _warn_lines(out) == [] and _error_lines(out) == []
    assert "SPAWNED" in out and "owns-grants=0" in out
    assert [s[1] for s in adapter.spawns] == ["dev"]
    # ...whereas `mnt` refuses the same FR (the asymmetry AC-4 calls out).
    wt_mnt, status = dispatch.ensure_role_worktree(_FR, "mnt", adapter)
    assert wt_mnt is None and status.startswith("error:")


# ---------------------------------------------------------------------------
# AC-5: malformed globs refuse the spawn with the indexer's rule
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-5
def test_malformed_owns_prints_error_and_spawns_nothing(repo, adapter, capsys):
    raw = 'owns: ["/abs/path", "src/../etc/passwd", 7, "src/ok.py"]\n'
    _commit_spec(repo, _FR, _fr_md(_FR, owns_raw=raw))
    wt = _dev_wt(repo)
    for apply in (False, True):
        assert (
            dispatch.cmd_tick(apply=apply, adapter=adapter, role="dev", fr_filter=[_FR])
            == 0
        )
        out = capsys.readouterr().out
        errors = _error_lines(out)
        assert len(errors) == 3, errors
        for entry, line in zip(("/abs/path", "src/../etc/passwd", "7"), errors):
            assert _FR in line and entry in line, line
        assert (
            "WOULD-SPAWN" not in out
            and "SPAWNED" not in out
            and "owns-grants" not in out
        )
    assert adapter.spawns == []
    assert not wt.exists()  # no worktree, hence no settings file
    assert not (repo / "_dispatch" / f"{_FR}.dev.lock").exists()
    assert [r for r in _records() if r["kind"] == "dispatch.spawn"] == []
    # The refusal is also enforced at spawn level (defense in depth): direct
    # `spawn_role` with apply=True returns an error and writes nothing.
    result, pid, path = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result.startswith("error:") and pid is None and path is None
    assert "/abs/path" in result and not wt.exists() and adapter.spawns == []
    assert _records() == []


# covers hub-tooling FR-0009:AC-5
@pytest.mark.parametrize(
    "entry_yaml",
    [
        '"./x"',  # suspicious-looking but legal for the indexer
        '"a/b/..c"',  # `..` inside a segment, not a segment
        '"..foo"',
        '"foo.."',
        '"C:/x"',  # not POSIX-absolute per the indexer's rule
        '"  "',
        '""',
        "'a\\b'",  # single-quoted YAML: a literal backslash
        "true",
        "null",
        "3.5",
        '"src/**"',
        '"/"',
        '".."',
        '"x/.."',
    ],
)
def test_dispatcher_classifies_each_entry_exactly_as_the_indexer(repo, entry_yaml):
    """Adversarial: for every entry shape, `_invalid_owns_entries` must flag it
    iff `spec_footprint.parse_footprint` raises on the same frontmatter — the
    dispatcher and the indexer never disagree about legality."""
    _write_spec(repo, _FR, _fr_md(_FR, owns_raw=f"owns: [{entry_yaml}]\n"))
    meta = dispatch._first_spec_frontmatter(_FR)
    try:
        spec_footprint.parse_footprint(meta)
        indexer_rejects = False
    except spec_footprint.FootprintInvalid:
        indexer_rejects = True
    dispatcher_rejects = bool(dispatch._invalid_owns_entries(_FR))
    assert dispatcher_rejects == indexer_rejects, (
        entry_yaml,
        dispatch._invalid_owns_entries(_FR),
    )
    if not indexer_rejects:
        # Legal entries flow through to grants exactly as the indexer sees them.
        expected = [g for g in spec_footprint.parse_footprint(meta).owns if g.strip()]
        d = dispatch.dev_owns_derivation(_FR)
        assert sorted(d["granted"] + d["withheld"]) == sorted(expected)


# covers hub-tooling FR-0009:AC-5
@pytest.mark.parametrize("raw", ['owns: "src/**"\n', "owns: 42\n", "owns: {a: b}\n"])
def test_non_list_owns_is_refused_like_the_indexer_and_never_crashes_the_tick(
    repo, adapter, capsys, raw
):
    """Adversarial: the indexer rejects a scalar / mapping `owns:` outright
    ("must be a YAML list of glob strings"). The dispatcher must reach the
    same verdict — one ERROR, no spawn — rather than iterating the scalar
    into per-character grants or raising out of the tick loop."""
    _commit_spec(repo, _FR, _fr_md(_FR, owns_raw=raw))
    with pytest.raises(spec_footprint.FootprintInvalid):
        spec_footprint.parse_footprint(dispatch._first_spec_frontmatter(_FR))
    assert dispatch._invalid_owns_entries(_FR), raw
    assert dispatch.dev_owns_derivation(_FR)["granted"] == []
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    assert len(_error_lines(out)) == 1 and _FR in _error_lines(out)[0]
    assert "SPAWNED" not in out and adapter.spawns == [] and not _dev_wt(repo).exists()


# ---------------------------------------------------------------------------
# AC-5 (round 2): the non-list fix, probed beyond the round-1 trio
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-5
@pytest.mark.parametrize(
    "raw",
    [
        'owns: ""\n',  # empty string: present, falsy, not a list
        "owns: false\n",
        "owns: true\n",
        "owns: 0\n",  # falsy int: `or []` in fr_owns_globs would hide it
        "owns: {}\n",  # empty mapping: falsy, still not a list
        "owns: 2026-01-01\n",  # YAML date: a non-str scalar
        "owns: !!set {a: null}\n",  # a set: iterable, not a list
        "owns: [[]]\n",  # a list nested in a list
        'owns: [["src/**"]]\n',
        'owns: ["src/ok.py", ["src/**"], null]\n',  # valid beside nested
    ],
)
def test_round2_odd_non_list_and_nested_owns_are_refused_with_the_indexer_message(
    repo, adapter, capsys, raw
):
    """Round-2 adversarial: shapes beyond `"src/**"` / `42` / `{a: b}`. The
    falsy ones (`""`, `false`, `0`, `{}`) are the sharp edge — the
    `or []` in `fr_owns_globs` reads them as "no footprint", but the indexer
    rejects them, so the dispatcher must refuse, not degrade to AC-4. A
    nested list is a list at the top level and must fall through to the
    per-entry check. In every case the first ERROR is the indexer's own
    message, verbatim."""
    _commit_spec(repo, _FR, _fr_md(_FR, owns_raw=raw))
    meta = dispatch._first_spec_frontmatter(_FR)
    with pytest.raises(spec_footprint.FootprintInvalid) as exc:
        spec_footprint.parse_footprint(meta)
    invalid = dispatch._invalid_owns_entries(_FR)
    assert invalid and invalid[0] == str(exc.value), (raw, invalid)
    d = dispatch.dev_owns_derivation(_FR)
    assert d["invalid"] == invalid and d["granted"] == [] and d["withheld"] == []
    for apply in (False, True):
        assert (
            dispatch.cmd_tick(apply=apply, adapter=adapter, role="dev", fr_filter=[_FR])
            == 0
        )
        out = capsys.readouterr().out
        errors = _error_lines(out)
        assert errors and _FR in errors[0] and str(exc.value) in "\n".join(errors)
        assert _warn_lines(out) == []
        assert "WOULD-SPAWN" not in out and "SPAWNED" not in out
        assert "owns-grants" not in out
    assert adapter.spawns == [] and not _dev_wt(repo).exists()
    assert [r for r in _records() if r["kind"] == "dispatch.spawn"] == []
    # `ensure_role_worktree` (the apply-side guard) refuses with the same text.
    wt, status = dispatch.ensure_role_worktree(_FR, "dev", adapter)
    assert wt is None and status.startswith("error:") and str(exc.value) in status


# covers hub-tooling FR-0009:AC-4
@pytest.mark.parametrize("raw", ["owns:\n", "owns: ~\n", "owns: null\n"])
def test_round2_every_yaml_spelling_of_null_owns_is_still_no_footprint(
    repo, adapter, tmp_path, capsys, raw
):
    """The fix keys on `raw is None`; YAML has three ways to say that (bare
    key, `~`, `null`). All three must stay on the AC-4 path — static file,
    no WARN, no ERROR, spawn proceeds — and agree with the indexer, which
    lifts `None` to `()`."""
    _commit_spec(repo, _FR, _fr_md(_FR, owns_raw=raw))
    meta = dispatch._first_spec_frontmatter(_FR)
    assert meta.get("owns") is None
    assert spec_footprint.parse_footprint(meta).owns == ()
    assert dispatch._invalid_owns_entries(_FR) == []
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", _FR)
    assert _settings(wt) == _static()
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    assert _warn_lines(out) == [] and _error_lines(out) == []
    assert "SPAWNED" in out and "owns-grants=0" in out
    assert [s[1] for s in adapter.spawns] == ["dev"]


# covers hub-tooling FR-0009:AC-5
def test_round2_malformed_fr_beside_a_valid_one_is_skipped_not_fatal(
    repo, adapter, capsys, monkeypatch
):
    """The round-1 defect took the whole tick down with a TypeError. Now a
    scalar `owns:` on one FR must cost exactly one ERROR while the valid FR
    in the same tick / wave is still planned (dry-run) and spawned (apply).
    Order-adversarial: the bad FR sorts first, so it is the first one the
    loop meets."""
    bad, good = "FR-0001", "FR-0002"
    _commit_spec(repo, bad, _fr_md(bad, owns_raw="owns: 42\n"))
    _commit_spec(repo, good, _fr_md(good, _AC1_OWNS))
    # tick, dry-run
    assert dispatch.cmd_tick(apply=False, adapter=adapter, role="dev") == 0
    out = capsys.readouterr().out
    errors = _error_lines(out)
    assert len(errors) == 1 and bad in errors[0] and "42" in errors[0]
    [would] = [ln for ln in out.splitlines() if "WOULD-SPAWN" in ln]
    assert good in would and would.rstrip().endswith("owns-grants=4")
    assert not (repo / ".claude" / "worktrees").exists()
    # wave, dry-run (Phase 1 uses the same preflight)
    assert dispatch.cmd_wave(apply=False, adapter=adapter) == 0
    out = capsys.readouterr().out
    assert len(_error_lines(out)) == 1 and bad in _error_lines(out)[0]
    [would] = [ln for ln in out.splitlines() if "WOULD-SPAWN" in ln]
    assert good in would and "owns-grants=4" in would
    assert adapter.spawns == []
    # tick, apply: only the valid FR spawns; the bad one has no worktree.
    assert dispatch.cmd_tick(apply=True, adapter=adapter, role="dev") == 0
    out = capsys.readouterr().out
    assert len(_error_lines(out)) == 1 and bad in _error_lines(out)[0]
    [spawned] = [ln for ln in out.splitlines() if "SPAWNED" in ln]
    assert good in spawned and "owns-grants=4" in spawned
    assert [(s[0], s[1]) for s in adapter.spawns] == [(good, "dev")]
    assert _dev_wt(repo, good).exists() and not _dev_wt(repo, bad).exists()
    spawn_records = [r for r in _records() if r["kind"] == "dispatch.spawn"]
    assert len(spawn_records) == 1 and bad not in json.dumps(spawn_records)
    # wave, apply: Phase 1 still spawns only the valid FR (the tick's lock is
    # released first, as a finished run would, so the FR is runnable again;
    # its worktree is reused — AC-6).
    dispatch.lock_path(good, "dev").unlink()
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {good: "timeout"}
    )
    dispatch.cmd_wave(
        apply=True, adapter=adapter, timeout=5, phase_timeout=1, poll_interval=0.01
    )
    out = capsys.readouterr().out
    assert len(_error_lines(out)) == 1 and bad in _error_lines(out)[0]
    assert [(s[0], s[1]) for s in adapter.spawns] == [(good, "dev"), (good, "dev")]
    assert not _dev_wt(repo, bad).exists()


# ---------------------------------------------------------------------------
# AC-6: the derivation runs on every spawn, including worktree reuse
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-6
def test_reused_worktree_picks_up_a_glob_added_after_creation(repo, adapter):
    result, _pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned" and wt == _dev_wt(repo)
    assert "Edit(alembic.ini)" not in _settings(wt)["allow"]
    _commit_spec(
        repo, _FR, _fr_md(_FR, _AC1_OWNS + ["alembic.ini"]), "owns: add alembic.ini"
    )
    dispatch.lock_path(_FR, "dev").unlink()  # the first run finished
    wt2, status = dispatch.ensure_role_worktree(_FR, "dev", adapter)
    assert wt2 == wt and status.startswith("reused")
    assert (
        "Edit(alembic.ini)" in _settings(wt)["allow"]
        and "Write(alembic.ini)" in _settings(wt)["allow"]
    )


# covers hub-tooling FR-0009:AC-6
def test_reused_worktree_drops_a_removed_glob_and_refuses_a_now_malformed_owns(
    repo, adapter
):
    """Adversarial: the rewrite is from the *current* spec — a glob removed
    after creation disappears (grants are not sticky), and an `owns:` that
    became malformed after creation refuses the reuse without touching the
    existing settings file."""
    result, _pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    dispatch.lock_path(_FR, "dev").unlink()
    _commit_spec(repo, _FR, _fr_md(_FR, ["frontend/*"]), "owns: shrink")
    wt2, status = dispatch.ensure_role_worktree(_FR, "dev", adapter)
    assert wt2 == wt and status.startswith("reused")
    assert _grants(_settings(wt), "Edit") == _grants(_static(), "Edit") + ["frontend/*"]
    before = (wt / ".claude" / "settings.local.json").read_bytes()
    _commit_spec(
        repo, _FR, _fr_md(_FR, owns_raw='owns: ["../escape"]\n'), "owns: malformed"
    )
    wt3, status = dispatch.ensure_role_worktree(_FR, "dev", adapter)
    assert wt3 is None and status.startswith("error:") and "../escape" in status
    assert (wt / ".claude" / "settings.local.json").read_bytes() == before


# ---------------------------------------------------------------------------
# AC-7: the spawn report states the derived grant count; dry-run writes nothing
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-7
def test_tick_and_wave_report_owns_grants_in_dry_run_and_apply(repo, adapter, capsys):
    _commit_spec(
        repo, _FR, _fr_md(_FR, _AC1_OWNS + ["CLAUDE.md", ".claude/x.md"])
    )  # 4 granted + 1 guarded
    # tick, dry-run
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    [line] = [ln for ln in out.splitlines() if "WOULD-SPAWN" in ln]
    assert line.rstrip().endswith("owns-grants=5") and _FR in line
    # wave, dry-run
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    out = capsys.readouterr().out
    [line] = [ln for ln in out.splitlines() if "WOULD-SPAWN" in ln]
    assert line.rstrip().endswith("owns-grants=5") and _FR in line
    assert adapter.spawns == []
    # tick, apply
    assert (
        dispatch.cmd_tick(apply=True, adapter=adapter, role="dev", fr_filter=[_FR]) == 0
    )
    out = capsys.readouterr().out
    [line] = [ln for ln in out.splitlines() if "SPAWNED" in ln]
    assert "owns-grants=5" in line and [s[1] for s in adapter.spawns] == ["dev"]


# covers hub-tooling FR-0009:AC-7
def test_wave_apply_spawned_line_carries_owns_grants(
    repo, adapter, capsys, monkeypatch
):
    """Phase 1 of a real (fake-adapter) wave: the SPAWNED line carries the
    count. Later phases are cut short by the phase timeout / stubbed
    finalize; only the Dev Tick line is under test."""
    monkeypatch.setattr(
        dispatch, "_wait_for_phase", lambda agents, poll, timeout: {_FR: "timeout"}
    )
    dispatch.cmd_wave(
        apply=True,
        adapter=adapter,
        fr_filter=[_FR],
        timeout=5,
        phase_timeout=1,
        poll_interval=0.01,
    )
    out = capsys.readouterr().out
    spawned = [ln for ln in out.splitlines() if "SPAWNED" in ln and _FR in ln]
    assert spawned and "owns-grants=4" in spawned[0]


# covers hub-tooling FR-0009:AC-7
def test_dry_run_tick_and_wave_leave_worktree_and_settings_byte_identical(
    repo, adapter, capsys
):
    """Adversarial: spawn for real, then change the spec's `owns:` on main so a
    (forbidden) dry-run rewrite would be *visible*; tick and wave dry-runs
    must leave the worktree tree — settings included — byte-identical."""
    result, _pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    dispatch.lock_path(_FR, "dev").unlink()
    _commit_spec(repo, _FR, _fr_md(_FR, _AC1_OWNS + ["alembic.ini"]), "owns: add")
    before_tree = _tree_digest(wt)
    before_settings = (wt / ".claude" / "settings.local.json").read_bytes()
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    out = capsys.readouterr().out
    assert out.count("owns-grants=5") == 2  # the new count is previewed...
    assert (
        wt / ".claude" / "settings.local.json"
    ).read_bytes() == before_settings  # ...but not written
    assert _tree_digest(wt) == before_tree
    assert len(adapter.spawns) == 1  # only the initial real spawn


# covers hub-tooling FR-0009:AC-7
def test_dry_run_creates_no_worktree_for_a_never_spawned_fr(repo, adapter, capsys):
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    assert dispatch.cmd_wave(apply=False, adapter=adapter, fr_filter=[_FR]) == 0
    assert "owns-grants=4" in capsys.readouterr().out
    assert not (repo / ".claude" / "worktrees").exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert [r for r in _records() if r["kind"] == "dispatch.spawn"] == []


# ---------------------------------------------------------------------------
# AC-8: the Cursor adapter applies the same derivation
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-8
def test_cursor_dev_settings_are_static_allow_plus_write_for_every_owned_glob(
    repo, tmp_path
):
    wt = tmp_path / "wt"
    dispatch.CursorAdapter().write_worktree_settings(wt, "dev", _FR)
    perms = _cursor_settings(wt)
    static = _static(adapter_cls="CursorAdapter")
    assert perms["allow"][: len(static["allow"])] == static["allow"]
    assert perms["deny"] == static["deny"]
    assert perms["allow"][len(static["allow"]) :] == [f"Write({g})" for g in _AC1_OWNS]
    assert not any(
        a.startswith("Edit(") for a in perms["allow"]
    )  # Cursor has no Edit token


# covers hub-tooling FR-0009:AC-8
def test_cursor_withholds_and_reports_identically_to_claude(repo, tmp_path, capsys):
    """Adversarial: protected + harness-guarded + plain globs mixed; the
    Cursor file must withhold exactly what the Claude file withholds, keep
    its static deny verbatim, and an ownerless FR must match the static file
    byte for byte."""
    owns = _AC2_OWNS + [".claude/commands/developer.md", "frontend/*", "scripts/**"]
    _write_spec(repo, _FR, _fr_md(_FR, owns))
    c_wt, k_wt = tmp_path / "cursor", tmp_path / "claude"
    dispatch.CursorAdapter().write_worktree_settings(c_wt, "dev", _FR)
    dispatch.ClaudeCodeAdapter().write_worktree_settings(k_wt, "dev", _FR)
    c_static, k_static = _static(adapter_cls="CursorAdapter"), _static()
    c_new = _cursor_settings(c_wt)["allow"][len(c_static["allow"]) :]
    k_new = _settings(k_wt)["allow"][len(k_static["allow"]) :]
    assert c_new == [
        f"Write({g})" for g in [".claude/commands/developer.md", "frontend/*"]
    ]
    assert sorted(c_new) == sorted(a for a in k_new if a.startswith("Write("))
    assert _cursor_settings(c_wt)["deny"] == c_static["deny"]
    _write_spec(repo, _FR, _fr_md(_FR, []))
    e_wt = tmp_path / "empty"
    dispatch.CursorAdapter().write_worktree_settings(e_wt, "dev", _FR)
    assert (
        _lf((e_wt / ".cursor" / "cli.json").read_bytes())
        == (json.dumps({"permissions": c_static}, indent=2) + "\n").encode()
    )


# ---------------------------------------------------------------------------
# AC-9: mnt, rev, bkf (and docs) are unchanged
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-9
@pytest.mark.parametrize(
    "owns",
    [
        _AC10_OWNS,
        [
            ".agent-team/roles/developer.md",
            "scripts/deploy-gate.py",
            "CLAUDE.md",
            ".claude/x.md",
        ],
    ],
)
def test_mnt_permissions_equal_the_pre_fr_derivation(
    repo, monkeypatch, pre_fr_dispatch, owns
):
    _point(monkeypatch, pre_fr_dispatch, repo)
    _write_spec(repo, _FR, _fr_md(_FR, owns))
    for cls in ("ClaudeCodeAdapter", "CursorAdapter"):
        new = getattr(dispatch, cls)().mnt_permissions(_FR)
        old = getattr(pre_fr_dispatch, cls)().mnt_permissions(_FR)
        assert new == old, cls
    assert dispatch.mnt_permission_rules(owns) == pre_fr_dispatch.mnt_permission_rules(
        owns
    )
    assert dispatch.mnt_unwritable_grants(
        owns
    ) == pre_fr_dispatch.mnt_unwritable_grants(owns)


# covers hub-tooling FR-0009:AC-9
@pytest.mark.parametrize("role", ["rev", "bkf", "docs", "mnt"])
def test_non_dev_role_settings_files_are_byte_identical_to_pre_fr(
    repo, tmp_path, monkeypatch, pre_fr_dispatch, role
):
    _point(monkeypatch, pre_fr_dispatch, repo)
    # DEC-0002: for `rev` / `bkf` the byte-identity claim holds for an FR with
    # no `owns:`; the rich-`owns:` case is FR-0010 AC-5's (test_dispatch_stack_grants.py).
    owns = (
        []
        if role in ("rev", "bkf")
        else _AC10_OWNS + [".agent-team/roles/developer.md"]
    )
    _write_spec(repo, _FR, _fr_md(_FR, owns))
    for cls, rel in (
        ("ClaudeCodeAdapter", ".claude/settings.local.json"),
        ("CursorAdapter", ".cursor/cli.json"),
    ):
        old_wt, new_wt = tmp_path / f"old-{cls}-{role}", tmp_path / f"new-{cls}-{role}"
        getattr(pre_fr_dispatch, cls)().write_worktree_settings(old_wt, role, _FR)
        getattr(dispatch, cls)().write_worktree_settings(new_wt, role, _FR)
        # A role the adapter does not know (Cursor has no `docs`) writes
        # nothing, before and after alike.
        assert (new_wt / rel).exists() == (old_wt / rel).exists(), (cls, role)
        if (old_wt / rel).exists():
            assert (new_wt / rel).read_bytes() == (old_wt / rel).read_bytes(), (
                cls,
                role,
            )


# covers hub-tooling FR-0009:AC-9
@pytest.mark.parametrize("role", ["rev", "bkf", "docs"])
def test_static_roles_still_write_exactly_their_static_payload(repo, tmp_path, role):
    """Runs everywhere (no pre-FR module needed): a non-derived role's file is
    exactly its `ROLE_PERMISSIONS` entry even for an FR with a rich `owns:`."""
    # DEC-0002: `rev` / `bkf` derive from `owns:` since FR-0010 AC-5, so their
    # static-payload guarantee is for an ownerless FR; `docs` keeps the rich one.
    _write_spec(repo, _FR, _fr_md(_FR, [] if role in ("rev", "bkf") else _AC10_OWNS))
    wt = tmp_path / "wt"
    dispatch.ClaudeCodeAdapter().write_worktree_settings(wt, role, _FR)
    assert (
        _lf((wt / ".claude" / "settings.local.json").read_bytes())
        == (json.dumps({"permissions": _static(role=role)}, indent=2) + "\n").encode()
    )


# covers hub-tooling FR-0009:AC-9
@pytest.mark.parametrize(
    "shape",
    [
        "list",
        "absent",
        "empty",
        "whitespace-entries",
        "non-string-entries",
        "unparseable-yaml",
        "no-frontmatter",
        "no-spec",
    ],
)
def test_fr_owns_globs_is_unchanged_by_the_frontmatter_refactor(
    repo, monkeypatch, pre_fr_dispatch, shape
):
    """Adversarial regression guard for `_first_spec_frontmatter`: the
    `fr_owns_globs` results the `mnt` derivation depends on must be identical
    to the pre-FR function for every input shape it used to handle."""
    _point(monkeypatch, pre_fr_dispatch, repo)
    text = {
        "list": _fr_md(_FR, _AC1_OWNS),
        "absent": _fr_md(_FR, None),
        "empty": _fr_md(_FR, []),
        "whitespace-entries": _fr_md(_FR, owns_raw='owns: ["  ", "src/**", ""]\n'),
        "non-string-entries": _fr_md(_FR, owns_raw="owns: [1, null, true, src/x.py]\n"),
        "unparseable-yaml": "---\nid: FR-0001\nowns: [unclosed\n---\n# x\n",
        "no-frontmatter": "# FR-0001 has no frontmatter\n",
        "no-spec": None,
    }[shape]
    p = repo / "specs" / f"{_FR}-synthetic.md"
    if text is None:
        p.unlink()
    else:
        p.write_text(text, encoding="utf-8", newline="\n")
    assert dispatch.fr_owns_globs(_FR) == pre_fr_dispatch.fr_owns_globs(_FR)


# ---------------------------------------------------------------------------
# AC-10: the derived grants are enough for the motivating case
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0009:AC-10
def test_project_a_footprint_fixture_gets_edit_and_write_for_all_22_globs_with_zero_warn(
    repo, adapter, tmp_path, capsys
):
    text = _PROJECT_A_FIXTURE.read_text(encoding="utf-8")
    _commit_spec(repo, "FR-9010", text, "add Project A fixture")
    wt = tmp_path / "wt"
    adapter.write_worktree_settings(wt, "dev", "FR-9010")
    perms = _settings(wt)
    missing = [
        g
        for g in _AC10_OWNS
        if f"Edit({g})" not in perms["allow"] or f"Write({g})" not in perms["allow"]
    ]
    assert missing == []
    assert perms["deny"] == _static()["deny"]
    assert (
        dispatch.cmd_tick(
            apply=False, adapter=adapter, role="dev", fr_filter=["FR-9010"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert _warn_lines(out) == [] and _error_lines(out) == []
    assert "FR-9010  WOULD-SPAWN" in out and "owns-grants=22" in out
    # Same footprint, Cursor adapter.
    c_wt = tmp_path / "cursor"
    dispatch.CursorAdapter().write_worktree_settings(c_wt, "dev", "FR-9010")
    assert all(f"Write({g})" in _cursor_settings(c_wt)["allow"] for g in _AC10_OWNS)


# covers hub-tooling FR-0009:AC-10
def test_project_a_fixture_matches_the_ac_text_verbatim_and_nothing_is_withheld_or_guarded(
    repo,
):
    """Adversarial: the committed fixture must carry exactly the 22 globs the
    AC lists (guards against fixture drift), and the derivation must classify
    none of them as withheld or harness-guarded — including the `tests/`
    entries that sit next to the Reviewer-owned `tests/test_*.py` pattern."""
    shutil.copy(_PROJECT_A_FIXTURE, repo / "specs" / _PROJECT_A_FIXTURE.name)
    assert dispatch.fr_owns_globs("FR-9010") == _AC10_OWNS
    assert len(set(_AC10_OWNS)) == 22
    d = dispatch.dev_owns_derivation("FR-9010")
    assert d == {
        "invalid": [],
        "granted": _AC10_OWNS,
        "withheld": [],
        "harness_guarded": [],
    }
    assert dispatch.dev_owns_grants(
        ["tests/conftest.py", "tests/smoke/**", "tests/test_x.py"]
    ) == (
        ["tests/conftest.py", "tests/smoke/**"],
        ["tests/test_x.py"],
    )
