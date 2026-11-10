"""Reviewer tests for FR-0017: stack detection finds a node manifest one
directory below the primary checkout's root (DEC-0020, revising FR-0010 AC-1).

- AC-1: `package.json` / `pnpm-lock.yaml` / `yarn.lock` in an immediate,
  non-dot, non-symlink, non-`node_modules` subdirectory imply the same tools
  as at the root; sorted, de-duplicated.
- AC-2: every other marker stays root-only; the excluded directories are
  excluded; detection stays presence-only and reads no file content.
- AC-3: the nested manifest reaches every role's permission file, `mnt`'s
  deny-lifting and the spawn record through the *unchanged* dispatcher and
  the real Claude Code adapter, from the primary checkout only (DEC-0014
  Decision 4): a manifest committed only on a role branch grants nothing.
- AC-4: a project with no nested manifest gets byte-identical detection,
  grants, pre-flight output, permission files and spawn record compared with
  the pre-FR `stack_profile.py`.

Harness: `stack_profile` imported from `template/scripts`; the committed trees
under `tests/fixtures/stack-nested/trees/` plus per-test temporary trees for
shapes git cannot carry (symlinks, dot-directories, `node_modules/`, a
directory named `package.json`). AC-3/AC-4 follow `test_dispatch_stack_grants.py`:
`dispatch.py` loaded by path, its path globals pointed at a real temporary git
repository, a fake adapter that records spawns and delegates only
`write_worktree_settings` to the real `ClaudeCodeAdapter`.

The pre-FR detector is loaded from `git show <ref>:template/scripts/stack_profile.py`.
Inside a bootstrapped project that object does not exist and those tests skip.

Coverage annotations are written `# covers hub-tooling FR-0017:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0017 exists (see test_stack_profile.py).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import builtins
import functools
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_TREES = _TEMPLATE_DIR / "tests" / "fixtures" / "stack-nested" / "trees"
_PROFILE_TREES = _TEMPLATE_DIR / "tests" / "fixtures" / "stack-profile" / "trees"

# The hub commit FR-0017 branched from (`main` before FR-0017). Its
# `stack_profile.py` is byte-identical to `a8889df`'s, the ref the FR names
# for the bite check.
_PRE_FR_REF = "82670a5"
_BITE_REF = "a8889df"

_FR = "FR-0001"
_ENV = "DISPATCH_STACK_TOOLS"
_NODE = ["node", "npm", "npx"]
_NODE_GRANTS = ["Bash(node *)", "Bash(npm *)", "Bash(npx *)"]
_ROLES = ["dev", "rev", "bkf", "mnt"]
_OWNS = ["frontend/**", "src/**"]
_PKG = '{"name": "synthetic", "private": true}\n'

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import env_preflight
import metrics_log
import stack_profile


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dispatch = _load_module(_SCRIPTS_DIR / "dispatch.py", "dispatch_under_test_fr0017")


@functools.lru_cache(maxsize=4)
def _git_show(ref: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(_TEMPLATE_DIR.parent), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _old_stack_profile(tmp_path_factory, ref: str, name: str):
    src = _git_show(ref, "template/scripts/stack_profile.py")
    if src is None:
        pytest.skip(f"stack_profile.py at {ref} not reachable")
    d = tmp_path_factory.mktemp(name)
    (d / "stack_profile.py").write_bytes(src)
    return _load_module(d / "stack_profile.py", name)


@pytest.fixture(scope="session")
def pre_fr_profile(tmp_path_factory):
    return _old_stack_profile(tmp_path_factory, _PRE_FR_REF, "stack_profile_pre_fr0017")


@pytest.fixture(scope="session")
def bite_profile(tmp_path_factory):
    return _old_stack_profile(tmp_path_factory, _BITE_REF, "stack_profile_a8889df")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """An operator's `DISPATCH_STACK_TOOLS` must never leak into detection."""
    monkeypatch.delenv(_ENV, raising=False)


def _tree(tmp_path: Path, *files: str, content: dict[str, str] | None = None) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((content or {}).get(rel, ""), encoding="utf-8", newline="\n")
    return root


def _tools(root: Path, mod=stack_profile) -> list[str]:
    return list(mod.detect_stack(root).tools)


def _digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _symlink_or_skip(link: Path, target: Path, *, is_dir: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"platform cannot create a symlink here: {e}")


# ---------------------------------------------------------------------------
# AC-1: node markers one level down
# ---------------------------------------------------------------------------

_TREE_EXPECTATIONS = {
    # AC-1's listed trees.
    "frontend-package-json": _NODE,
    "web-pnpm-lock": ["pnpm"],
    "app-yarn-lock": ["yarn"],
    "project-a-shape": ["node", "npm", "npx", "python", "uv"],
    "project-a-shape-compose": ["docker", "node", "npm", "npx", "python", "uv"],
    "root-and-nested-package-json": _NODE,
    # Open question 1: two nested manifests yield the trio once.
    "two-nested-package-json": _NODE,
    # All three nested markers across three directories, one repeated.
    "every-nested-marker": ["node", "npm", "npx", "pnpm", "yarn"],
    # AC-2: presence-only — unparseable and empty manifests both count.
    "unparseable-nested-package-json": _NODE,
    "empty-nested-package-json": _NODE,
    # AC-2: every non-node marker one level down stays root-only.
    "nested-non-node-markers": [],
    # AC-2: two levels down is out of reach, for all three node markers.
    "two-levels-down": [],
}


# covers hub-tooling FR-0017:AC-1
# covers hub-tooling FR-0017:AC-2
@pytest.mark.parametrize(("tree", "expected"), sorted(_TREE_EXPECTATIONS.items()))
def test_fixture_trees_detect_exactly_the_expected_tools(tree, expected):
    detection = stack_profile.detect_stack(_TREES / tree)
    assert list(detection.tools) == expected
    assert detection.warnings == ()
    assert list(detection.tools) == sorted(set(detection.tools))


# covers hub-tooling FR-0017:AC-1
def test_every_committed_tree_is_pinned():
    """A tree added to the fixture directory without an expectation would be
    silently untested."""
    on_disk = sorted(p.name for p in _TREES.iterdir() if p.is_dir())
    assert on_disk == sorted(_TREE_EXPECTATIONS)


# covers hub-tooling FR-0017:AC-1
def test_project_a_shape_nested_marker_is_additive_to_the_root_rule(tmp_path):
    """The nested rule adds node to what the root markers already imply —
    it never replaces or reorders them; the result is the sorted union."""
    root = _tree(tmp_path, "pyproject.toml", "uv.lock", "alembic.ini")
    before = _tools(root)
    assert before == ["alembic", "python", "uv"]
    (root / "frontend").mkdir()
    (root / "frontend" / "package.json").write_text(_PKG, encoding="utf-8")
    assert _tools(root) == sorted(set(before) | set(_NODE))


# covers hub-tooling FR-0017:AC-1
def test_root_and_nested_everything_yields_each_tool_exactly_once(tmp_path):
    root = _tree(
        tmp_path,
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "web/package.json",
        "web/pnpm-lock.yaml",
        "web/yarn.lock",
        "admin/package.json",
        "admin/yarn.lock",
    )
    tools = _tools(root)
    assert tools == ["node", "npm", "npx", "pnpm", "yarn"]
    assert len(tools) == len(set(tools))


# covers hub-tooling FR-0017:AC-1
@pytest.mark.parametrize("marker", ["package.json", "pnpm-lock.yaml", "yarn.lock"])
def test_nested_marker_implies_exactly_what_the_root_marker_implies(tmp_path, marker):
    """DEC-0020 Decision 1: "the same tools the root rule does"."""
    at_root = _tools(_tree(tmp_path / "a", marker))
    nested = _tools(_tree(tmp_path / "b", f"frontend/{marker}"))
    assert nested == at_root and nested


# covers hub-tooling FR-0017:AC-1
def test_bite_pre_fr_detector_misses_the_project_a_shape(bite_profile):
    """Bite check (FR Notes, Reviewer): `a8889df`'s detector finds no node in
    Project A's shape, so the AC-1 project-a-shape assertion fails against it."""
    expected = _TREE_EXPECTATIONS["project-a-shape"]
    old = _tools(_TREES / "project-a-shape", bite_profile)
    assert old == ["python", "uv"]
    assert not set(_NODE) & set(old)
    assert old != expected
    assert _tools(_TREES / "project-a-shape") == expected
    assert _tools(_TREES / "frontend-package-json", bite_profile) == []


# ---------------------------------------------------------------------------
# AC-2: everything else stays root-only; exclusions are excluded
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0017:AC-2
@pytest.mark.parametrize(
    "files",
    [
        ["sub/pyproject.toml"],
        ["deploy/uv.lock"],
        ["api/requirements.txt"],
        ["db/alembic.ini"],
        ["infra/docker-compose.yml"],
        ["infra/compose.yaml"],
        ["a/b/package.json"],
        ["a/b/pnpm-lock.yaml"],
        ["a/b/yarn.lock"],
        [".hidden/package.json"],
        [".hidden/pnpm-lock.yaml"],
        [".hidden/yarn.lock"],
        ["node_modules/package.json"],
        ["node_modules/pnpm-lock.yaml"],
        ["node_modules/yarn.lock"],
        ["node_modules/left-pad/package.json"],
        [".claude/worktrees/x/package.json"],
        [".claude/package.json"],
        [".git/package.json"],
        [".venv/package.json"],
        # Lookalike names one level down are not markers either.
        ["frontend/package.json5", "frontend/package-lock.json", "web/yarn.lock.bak"],
    ],
    ids=lambda f: "+".join(f),
)
def test_non_qualifying_nested_files_yield_nothing(tmp_path, files):
    assert _tools(_tree(tmp_path, *files)) == []


# covers hub-tooling FR-0017:AC-2
def test_a_directory_named_package_json_is_not_a_marker(tmp_path):
    root = _tree(tmp_path, "frontend/package.json/index.js")
    assert (root / "frontend" / "package.json").is_dir()
    (root / "web" / "pnpm-lock.yaml").mkdir(parents=True)
    (root / "app" / "yarn.lock").mkdir(parents=True)
    assert _tools(root) == []


# covers hub-tooling FR-0017:AC-2
def test_a_root_file_named_like_a_directory_is_not_walked(tmp_path):
    """A root entry that is a file (`frontend` with no extension) is not a
    subdirectory; nothing below it can exist, and nothing is detected."""
    root = _tree(tmp_path, "frontend", "web")
    assert _tools(root) == []


# covers hub-tooling FR-0017:AC-2
def test_symlinked_directory_to_a_tree_with_package_json_is_excluded(tmp_path):
    """The maintainer's order-sensitive check: `is_symlink()` must be asked
    before `is_dir()`, which follows the link. A symlinked `frontend/`
    pointing *outside* the root at a tree with every node marker must
    detect nothing — the link itself is the only candidate."""
    outside = tmp_path / "outside"
    outside.mkdir()
    for m in ("package.json", "pnpm-lock.yaml", "yarn.lock"):
        (outside / m).write_text("", encoding="utf-8")
    root = _tree(tmp_path)
    _symlink_or_skip(root / "frontend", outside, is_dir=True)
    assert (root / "frontend").is_dir()  # the naive check would say yes
    assert (root / "frontend" / "package.json").is_file()
    assert _tools(root) == []


# covers hub-tooling FR-0017:AC-2
def test_symlink_into_a_two_level_tree_does_not_shorten_the_path(tmp_path):
    """Adversarial: a root-level symlink to `a/b/` would make the two-level
    `a/b/package.json` look one level down if the link were followed."""
    root = _tree(tmp_path, "a/b/package.json")
    _symlink_or_skip(root / "web", root / "a" / "b", is_dir=True)
    assert _tools(root) == []


# covers hub-tooling FR-0017:AC-2
def test_dangling_directory_symlink_is_skipped_without_error(tmp_path):
    root = _tree(tmp_path, "pyproject.toml")
    _symlink_or_skip(root / "frontend", tmp_path / "missing", is_dir=True)
    assert _tools(root) == ["python"]


# covers hub-tooling FR-0017:AC-2
def test_symlinked_marker_file_is_treated_exactly_as_at_the_root(tmp_path):
    """AC-2 requires `<d>` to be a real directory and is silent on the marker
    itself. Decision (FINDING in REVIEW.md): a marker that is a symlink to a
    file *counts*, because `is_file()` follows links — the same answer the
    root rule has always given. A dangling marker symlink counts at neither
    level."""
    target = tmp_path / "real-package.json"
    target.write_text(_PKG, encoding="utf-8")
    nested = _tree(tmp_path / "n")
    (nested / "frontend").mkdir()
    _symlink_or_skip(nested / "frontend" / "package.json", target, is_dir=False)
    at_root = _tree(tmp_path / "r")
    _symlink_or_skip(at_root / "package.json", target, is_dir=False)
    assert _tools(nested) == _tools(at_root) == _NODE

    dangling_nested = _tree(tmp_path / "dn")
    (dangling_nested / "frontend").mkdir()
    _symlink_or_skip(
        dangling_nested / "frontend" / "package.json", tmp_path / "nope", is_dir=False
    )
    dangling_root = _tree(tmp_path / "dr")
    _symlink_or_skip(dangling_root / "package.json", tmp_path / "nope", is_dir=False)
    assert _tools(dangling_nested) == _tools(dangling_root) == []


# covers hub-tooling FR-0017:AC-2
def test_nested_detection_reads_no_file_content_and_writes_nothing(
    monkeypatch, tmp_path
):
    """Adversarial: every content-reading and writing route is booby-trapped.
    Detection over trees with unparseable, empty and valid nested markers
    must still succeed — presence is all it may look at."""
    root = _tree(
        tmp_path,
        "frontend/package.json",
        "web/pnpm-lock.yaml",
        "admin/yarn.lock",
        "node_modules/package.json",
        ".hidden/package.json",
        content={"frontend/package.json": "{ not json,,\n"},
    )
    roots = [root, *sorted(p for p in _TREES.iterdir() if p.is_dir())]
    before = {r: _digest(r) for r in roots}

    def _boom(*_a, **_k):
        raise AssertionError("nested detection must not read or write file content")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(io, "open", _boom)
    monkeypatch.setattr(os, "open", _boom)
    for name in (
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "touch",
        "unlink",
    ):
        monkeypatch.setattr(Path, name, _boom)
    results = {r: _tools(r) for r in roots}
    monkeypatch.undo()
    assert results[root] == ["node", "npm", "npx", "pnpm", "yarn"]
    assert {r: _digest(r) for r in roots} == before


# ---------------------------------------------------------------------------
# AC-3 / AC-4 harness: the real dispatcher over a real temporary git repo
# ---------------------------------------------------------------------------


def _fr_md(fr_id: str, owns: list[str]) -> str:
    return f"""---
id: {fr_id}
title: Synthetic {fr_id}
status: ready
owner: architect
depends_on: []
tags: []
owns: {json.dumps(owns)}
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


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr or proc.stdout}"
    return (proc.stdout or "").strip()


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def _commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _make_repo(parent: Path, files: dict[str, str] | None = None) -> Path:
    repo = parent / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (
        ("user.email", "synthetic@example.invalid"),
        ("user.name", "Synthetic"),
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
    ):
        _git(repo, "config", k, v)
    _write(repo, f"specs/{_FR}-synthetic.md", _fr_md(_FR, _OWNS))
    for rel in (
        ".agent-team/roles/developer.md",
        ".agent-team/roles/reviewer.md",
        "scripts/deploy-gate.py",
        "src/thing.py",
    ):
        _write(repo, rel, f"# {rel}\n")
    _write(
        repo,
        ".gitignore",
        f".claude/settings.local.json\n.cursor/cli.json\n{dispatch.VENV_DIRNAME}/\n"
        "__pycache__/\n_dispatch/\nmetrics/\n",
    )
    for rel, text in (files or {}).items():
        _write(repo, rel, text)
    _commit_all(repo, "base")
    return repo


def _point(monkeypatch, r: Path) -> None:
    monkeypatch.setattr(dispatch, "REPO_ROOT", r)
    monkeypatch.setattr(dispatch, "SPECS_DIR", r / "specs")
    monkeypatch.setattr(dispatch, "DISPATCH_DIR", r / "_dispatch")
    monkeypatch.setattr(dispatch, "LAST_TICK_FILE", r / "_dispatch" / ".last-tick")
    monkeypatch.setattr(dispatch, "ESCALATIONS_DIR", r / "specs" / "_escalations")
    monkeypatch.setattr(dispatch, "_RUN_REGISTRY", {})
    monkeypatch.setattr(dispatch, "ensure_dev_venv", lambda wt: (True, "venv-created"))
    monkeypatch.setattr(dispatch, "_gh_preflight", lambda verbose=False: (True, None))
    monkeypatch.setattr(
        dispatch,
        "reconcile_merged_prs",
        lambda apply=False, verbose=False: dispatch.ReconcileSummary(
            flipped=[], cleaned=[], skipped=[]
        ),
    )
    monkeypatch.setattr(dispatch, "prune_dead_locks", lambda verbose=True: 0)
    monkeypatch.setattr(
        env_preflight, "run_preflight", lambda *a, **k: env_preflight.PreflightResult()
    )
    monkeypatch.setattr(metrics_log, "METRICS_DIR", r / "metrics")
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    monkeypatch.delenv("DISPATCH_RUN_ID", raising=False)
    (r / "_dispatch").mkdir(exist_ok=True)


class _FakeAdapter:
    name = "fake"
    binary_name = "fake"

    def __init__(self) -> None:
        self.real = dispatch.ClaudeCodeAdapter()
        self.spawns: list[tuple[str, str]] = []

    def write_worktree_settings(self, wt_path: Path, role: str, fr_id: str) -> None:
        self.real.write_worktree_settings(wt_path, role, fr_id)

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.spawns.append((fr_id, role))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type":"result","subtype":"success"}\n', encoding="utf-8")
        return ("spawned", 999_999)

    def parse_log(self, log_path: Path):
        return SimpleNamespace(last_text="", result_subtype="success", tool_calls=0)

    def dry_run_preview(self, fr_id: str, role: str, wt_preview: Path) -> str:
        return f"fake-preview {role} {fr_id}"


def _settings_bytes(adapter: _FakeAdapter, out: Path, role: str) -> bytes:
    adapter.write_worktree_settings(out, role, _FR)
    return (out / ".claude" / "settings.local.json").read_bytes()


def _perms(raw: bytes) -> dict[str, list[str]]:
    return json.loads(raw.decode("utf-8"))["permissions"]


def _spawn_records() -> list[dict]:
    d = metrics_log.METRICS_DIR
    if not d.exists():
        return []
    recs = [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    return [r for r in recs if r["kind"] == "dispatch.spawn"]


# ---------------------------------------------------------------------------
# AC-3: grants through the unchanged dispatcher, from the primary checkout only
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0017:AC-3
def test_nested_manifest_permission_files_equal_a_root_manifests_for_every_role(
    tmp_path, monkeypatch
):
    adapter = _FakeAdapter()
    root_repo = _make_repo(tmp_path / "rootpkg", {"package.json": _PKG})
    _point(monkeypatch, root_repo)
    assert dispatch.detected_stack_tools() == _NODE
    from_root = {
        role: _settings_bytes(adapter, tmp_path / f"root-{role}", role)
        for role in _ROLES
    }

    nested_repo = _make_repo(tmp_path / "nested", {"frontend/package.json": _PKG})
    _point(monkeypatch, nested_repo)
    assert not (nested_repo / "package.json").exists()
    assert dispatch.detected_stack_tools() == _NODE
    for role in _ROLES:
        raw = _settings_bytes(adapter, tmp_path / f"nested-{role}", role)
        allow = _perms(raw)["allow"]
        for grant in _NODE_GRANTS:
            assert allow.count(grant) == 1, (role, grant)
        assert raw == from_root[role], role


# covers hub-tooling FR-0017:AC-3
def test_nested_manifest_lifts_mnt_node_and_npx_denies_only(tmp_path, monkeypatch):
    adapter = _FakeAdapter()
    bare = _make_repo(tmp_path / "bare")
    _point(monkeypatch, bare)
    bare_deny = _perms(_settings_bytes(adapter, tmp_path / "bare-mnt", "mnt"))["deny"]
    assert "Bash(node *)" in bare_deny and "Bash(npx *)" in bare_deny

    nested = _make_repo(tmp_path / "nested", {"frontend/package.json": _PKG})
    _point(monkeypatch, nested)
    deny = _perms(_settings_bytes(adapter, tmp_path / "nested-mnt", "mnt"))["deny"]
    assert "Bash(node *)" not in deny and "Bash(npx *)" not in deny
    assert "Bash(uv *)" in deny and "Bash(pip *)" in deny
    assert deny == [d for d in bare_deny if d not in ("Bash(node *)", "Bash(npx *)")]
    assert [d for d in deny if d in dispatch.MNT_BASH_DENIES] == (
        dispatch._mnt_bash_denies(_NODE)
    )


# covers hub-tooling FR-0017:AC-3
def test_nested_manifest_reaches_the_stack_line_and_the_spawn_record(
    tmp_path, monkeypatch, capsys
):
    adapter = _FakeAdapter()
    repo = _make_repo(tmp_path, {"frontend/package.json": _PKG})
    _point(monkeypatch, repo)
    assert (
        dispatch.cmd_tick(apply=False, adapter=adapter, role="dev", fr_filter=[_FR])
        == 0
    )
    out = capsys.readouterr().out
    assert "stack=node,npm,npx  stack-grants=3" in out, out
    result, _pid, wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result == "spawned"
    rec = _spawn_records()[-1]
    assert rec["worktree_status"] == "created,stack=node+npm+npx"
    for grant in _NODE_GRANTS:
        assert (
            grant
            in _perms((wt / ".claude" / "settings.local.json").read_bytes())["allow"]
        )


# covers hub-tooling FR-0017:AC-3
def test_nested_only_project_runs_preflight_exactly_as_a_root_manifest_does(
    tmp_path, monkeypatch, capsys
):
    """FR Open question 2: a nested-only project now gets the `ran:` form,
    with the same tools passed to the pre-flight seam as a root manifest."""
    seen: list[list[str]] = []
    real = env_preflight.run_preflight

    def outputs(files: dict[str, str], name: str) -> str:
        repo = _make_repo(tmp_path / name, files)
        _point(monkeypatch, repo)

        def fake(root, tools, **_k):
            seen.append(list(tools))
            return real(
                root,
                tools,
                find_uv=lambda: None,
                which=lambda n: f"/usr/bin/{n}",
                run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                port_busy=lambda *a, **k: False,
                platform="linux",
            )

        monkeypatch.setattr(env_preflight, "run_preflight", fake)
        gate = dispatch._run_env_preflight(apply=True, skip=False)
        assert not gate.blocked
        return capsys.readouterr().out

    at_root = outputs({"package.json": _PKG}, "root")
    nested = outputs({"frontend/package.json": _PKG}, "nested")
    assert seen == [_NODE, _NODE]
    assert nested == at_root
    assert "PREFLIGHT OK        ran:" in nested
    assert "no stack declared" not in nested


# covers hub-tooling FR-0017:AC-3
def test_manifest_committed_only_on_a_role_branch_grants_nothing(tmp_path, monkeypatch):
    """Adversarial (DEC-0014 Decision 4): the dev branch commits
    `frontend/package.json`; the primary checkout never has it. Every role's
    permission file — written directly, and written by `ensure_role_worktree`
    into worktrees that *do* contain the manifest (dev's own, and rev's,
    which is cut from dev's branch) — is byte-identical to the no-stack
    project's."""
    adapter = _FakeAdapter()
    repo = _make_repo(tmp_path)
    _point(monkeypatch, repo)
    assert dispatch.detected_stack_tools() == []
    baseline = {
        role: _settings_bytes(adapter, tmp_path / f"base-{role}", role)
        for role in _ROLES
    }
    for role in _ROLES:
        assert not set(_NODE_GRANTS) & set(_perms(baseline[role])["allow"])

    dev_wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    dev_wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/dev-{_FR}", str(dev_wt), "main")
    _write(dev_wt, "frontend/package.json", _PKG)
    spec = dev_wt / "specs" / f"{_FR}-synthetic.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "status: ready", "status: in-progress"
        ),
        encoding="utf-8",
        newline="\n",
    )
    _commit_all(dev_wt, "role-branch-only manifest")
    assert not (repo / "frontend").exists()
    assert dispatch.detected_stack_tools() == []

    for role in _ROLES:
        after = _settings_bytes(adapter, tmp_path / f"after-{role}", role)
        assert after == baseline[role], role

    for role in ("dev", "rev"):
        wt, status = dispatch.ensure_role_worktree(_FR, role, adapter)
        assert wt is not None, status
        assert (wt / "frontend" / "package.json").is_file(), role
        written = (wt / ".claude" / "settings.local.json").read_bytes()
        assert written == baseline[role], role
    assert dispatch.detected_stack_tools() == []


# ---------------------------------------------------------------------------
# AC-4: nothing else changes for a project without nested manifests
# ---------------------------------------------------------------------------

# A project with root markers and every *non-qualifying* nested decoy.
_DECOY_FILES = {
    "pyproject.toml": '[project]\nname = "synthetic"\n',
    "uv.lock": "",
    "alembic.ini": "[alembic]\n",
    "sub/pyproject.toml": "",
    "deploy/uv.lock": "",
    "api/requirements.txt": "typing-extensions\n",
    "db/alembic.ini": "",
    "infra/docker-compose.yml": "services: {}\n",
    "a/b/package.json": _PKG,
    ".hidden/package.json": _PKG,
    "node_modules/package.json": _PKG,
    "frontend/package.json5": "",
}


# covers hub-tooling FR-0017:AC-4
def test_detection_without_nested_manifests_is_identical_to_pre_fr(
    tmp_path, pre_fr_profile
):
    decoy = _tree(tmp_path, *_DECOY_FILES)
    (decoy / "web" / "package.json").mkdir(parents=True)
    no_stack_decoys = _tree(tmp_path / "ns", *[k for k in _DECOY_FILES if "/" in k])
    roots = [
        decoy,
        no_stack_decoys,
        *sorted(p for p in _PROFILE_TREES.iterdir() if p.is_dir()),
        _TREES / "nested-non-node-markers",
        _TREES / "two-levels-down",
    ]
    for root in roots:
        new = stack_profile.detect_stack(root)
        old = pre_fr_profile.detect_stack(root)
        assert (new.tools, new.warnings) == (old.tools, old.warnings), root
        assert stack_profile.stack_bash_grants(list(new.tools)) == (
            pre_fr_profile.stack_bash_grants(list(old.tools))
        )
    assert _tools(decoy) == ["alembic", "python", "uv"]
    assert _tools(no_stack_decoys) == []


def _with_profile(monkeypatch, mod) -> None:
    monkeypatch.setattr(dispatch, "stack_profile", mod)


# covers hub-tooling FR-0017:AC-4
@pytest.mark.parametrize("decoys", ["root-markers", "no-stack"])
def test_permission_files_preflight_and_spawn_record_identical_to_pre_fr(
    tmp_path, monkeypatch, capsys, pre_fr_profile, decoys
):
    files = (
        dict(_DECOY_FILES)
        if decoys == "root-markers"
        else {k: v for k, v in _DECOY_FILES.items() if "/" in k}
    )
    real = env_preflight.run_preflight

    def observe(mod, name: str) -> dict:
        repo = _make_repo(tmp_path / name, files)
        _point(monkeypatch, repo)
        _with_profile(monkeypatch, mod)
        adapter = _FakeAdapter()
        perms = {
            role: _settings_bytes(adapter, tmp_path / f"{name}-{role}", role)
            for role in _ROLES
        }
        seen: list[list[str]] = []

        def fake(root, tools, **_k):
            seen.append(list(tools))
            return real(
                root,
                tools,
                find_uv=lambda: "uv",
                which=lambda n: f"/usr/bin/{n}",
                run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                port_busy=lambda *a, **k: False,
                platform="linux",
            )

        monkeypatch.setattr(env_preflight, "run_preflight", fake)
        capsys.readouterr()
        dispatch._run_env_preflight(apply=True, skip=False)
        preflight = capsys.readouterr().out
        result, _pid, _wt = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
        assert result == "spawned"
        spawn_out = capsys.readouterr().out.replace(str(repo), "<repo>")
        return {
            "tools": dispatch.detected_stack_tools(),
            "perms": perms,
            "preflight": preflight,
            "preflight_tools": seen,
            "record": _spawn_records()[-1]["worktree_status"],
            "spawn_out": spawn_out,
        }

    new = observe(stack_profile, "new")
    old = observe(pre_fr_profile, "old")
    assert new == old
    if decoys == "root-markers":
        assert new["record"] == "created,stack=alembic+python+uv"
    else:
        assert new["record"] == "created"
        assert "PREFLIGHT OK (no stack declared)" in new["preflight"]
