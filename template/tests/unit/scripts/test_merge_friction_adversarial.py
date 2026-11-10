"""Reviewer's adversarial tests for FR-0018 (merge friction removed at the
source).

These complement the Developer's `test_merge_friction.py`, whose harness
(the fake adapter, the linked-worktree fixture, the real bare-origin
revalidate scenarios) they reuse. Each one is built to fail a plausible
naive implementation:

- AC-1: the exported project root is whatever `_worktree_project_root`
  returns (the one seam FR-0024 changes); restoration survives an adapter
  that rewrites the variables itself, a non-`spawned` result and a worktree
  error.
- AC-2: the redirect matches the same directory however it is spelled
  (`\\\\?\\` prefix, junction, 8.3 short name, case, separators) and never a
  directory that merely contains, is contained by, or shares a prefix with
  the copy's project root. A target that cannot be written is one WARN, never
  a raise.
- AC-4: an indexer that writes and then fails has the conflicted bytes put
  back; an `INDEX.md` anywhere but `specs/` is not special; nothing applies
  without `MERGE_HEAD`; the git argv actually run (not just the source's
  list literals) holds one merge and one `commit --no-edit` and nothing that
  rewrites history, with `core.autocrlf` off and on.
- AC-6 / AC-7: FR-0018's own commits change only the README's Committed
  bullet, no file the FR fixes as unedited, and no record schema constant.
  Scoped to those commits rather than diffed against the base, so FR-0026
  (which edits the same files) or any later FR landing does not break them.
- Annotation hygiene: neither FR-0018 test file carries a live gate
  annotation.

Round 2 (DEC-0030 item 6): the r1 strict xfail on `CODEOWNERS` is now a
plain test; the argv-recording test also drives the side-write restore and
checks it runs before `add` and `commit`; a side-write the resolution
cannot put back stops before staging; and a refused `commit --no-edit` is
reported as a staged index with the merge still in progress.

Bite checks load the base commit's scripts (`_mf._BASE_REF`) and skip where
it is unreachable (inside a bootstrapped project).

Annotations are `# covers hub-tooling FR-0018:AC-N`, not the gate's form:
this file rides along into every bootstrapped project, where FR-0018 does
not exist. Every fixture here is synthetic.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from . import test_merge_friction as _mf

dispatch = _mf.dispatch
metrics_log = _mf.metrics_log
_git = _mf._git
_write = _mf._write
_FR = _mf._FR
_METRICS_DIR_ENV = _mf._METRICS_DIR_ENV
_WORKTREE_ENV = _mf._WORKTREE_ENV
_SCRIPTS_DIR = _mf._SCRIPTS_DIR
_TEMPLATE_DIR = _mf._TEMPLATE_DIR
_COVERS = "@" + "covers"

# The Developer's fixtures, reused by name.
spawn_env = _mf.spawn_env
linked = _mf.linked


@pytest.fixture(autouse=True)
def _no_inherited_redirect(monkeypatch):
    for key in (_METRICS_DIR_ENV, _WORKTREE_ENV):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# AC-1
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0018:AC-1
def test_exported_project_root_is_whatever_the_one_seam_returns(spawn_env, monkeypatch):
    """FR-0024 changes `_worktree_project_root` and nothing else (DEC-0030):
    a spawn exports exactly what it returns, absolutised."""
    prefixed = spawn_env.wt / "projects" / "demo"
    monkeypatch.setattr(dispatch, "_worktree_project_root", lambda wt: prefixed)
    adapter = _mf._SamplingAdapter()
    assert dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)[0] == "spawned"
    assert adapter.seen[_WORKTREE_ENV] == os.path.abspath(prefixed)
    assert adapter.seen[_METRICS_DIR_ENV] == os.path.abspath(
        spawn_env.repo / "specs" / "_metrics"
    )


# covers hub-tooling FR-0018:AC-1
def test_the_worktree_variable_has_one_producer_in_the_dispatcher():
    """Static: the variable name is spelled once and stored once, and the
    stored value is `_worktree_project_root`'s, absolutised. (Other callers
    of the seam are fine: FR-0024 may reuse it for AC-4's paths.)"""
    src = (_SCRIPTS_DIR / "dispatch.py").read_text(encoding="utf-8")
    assert src.count('"DISPATCH_WORKTREE"') == 1
    assert src.count('"DISPATCH_METRICS_DIR"') == 1
    uses = [ln.strip() for ln in src.splitlines() if "_WORKTREE_ENV" in ln]
    assert len(uses) == 2, uses  # the constant and the one child_env entry
    stores = [
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Subscript)
            and isinstance(t.slice, ast.Name)
            and t.slice.id == "_WORKTREE_ENV"
            for t in n.targets
        )
    ]
    assert len(stores) == 1
    value = ast.unparse(stores[0].value)
    assert value.startswith("os.path.abspath(_worktree_project_root("), value


class _RewritingAdapter(_mf._SamplingAdapter):
    """Rewrites and deletes the variables inside `spawn`, then returns a
    non-`spawned` result."""

    def spawn(self, fr_id, role, wt_path, log_path, extra_prompt=None):
        self.seen = dict(os.environ)
        os.environ[_WORKTREE_ENV] = "rewritten-by-the-harness"
        os.environ.pop(_METRICS_DIR_ENV, None)
        os.environ["DISPATCH_RUN_ID"] = "rewritten"
        return ("error:synthetic harness refused", None)


# covers hub-tooling FR-0018:AC-1
@pytest.mark.parametrize("preset", [False, True])
def test_restored_after_an_adapter_that_rewrites_them_and_does_not_spawn(
    spawn_env, monkeypatch, preset
):
    if preset:
        monkeypatch.setenv(_METRICS_DIR_ENV, "synthetic-before-dir")
        monkeypatch.setenv(_WORKTREE_ENV, "synthetic-before-wt")
        monkeypatch.setenv("DISPATCH_RUN_ID", "synthetic-before-run")
    before = dict(os.environ)
    adapter = _RewritingAdapter()
    result = dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter)
    assert result[0] == "error:synthetic harness refused"
    assert adapter.seen[_WORKTREE_ENV] == os.path.abspath(spawn_env.wt)
    assert dict(os.environ) == before


# covers hub-tooling FR-0018:AC-1
def test_a_worktree_error_sets_nothing_and_spawns_nothing(spawn_env, monkeypatch):
    monkeypatch.setattr(
        dispatch,
        "ensure_role_worktree",
        lambda fr, role, adapter: (None, "error:synthetic"),
    )
    before = dict(os.environ)
    adapter = _mf._SamplingAdapter()
    assert dispatch.spawn_role(_FR, "dev", apply=True, adapter=adapter) == (
        "error:synthetic",
        None,
        None,
    )
    assert adapter.seen is None and dict(os.environ) == before


# ---------------------------------------------------------------------------
# AC-2: same directory however spelled; never a neighbour
# ---------------------------------------------------------------------------


def _load_copy(root: Path, redirect: Path, worktree: str, monkeypatch):
    path = _mf._copy_metrics_log(root)
    monkeypatch.setenv(_METRICS_DIR_ENV, str(redirect))
    monkeypatch.setenv(_WORKTREE_ENV, worktree)
    return _mf._import_copy(path)


# covers hub-tooling FR-0018:AC-2
@pytest.mark.parametrize(
    "case",
    [
        "parent-of-root",
        "grandparent-of-root",
        "child-of-root",
        "scripts-dir",
        "the-module-file",
        "shared-name-prefix",
        "shared-name-suffix",
        "missing-sibling",
    ],
)
def test_a_neighbour_of_the_project_root_never_matches(tmp_path, monkeypatch, case):
    """A copy whose project root contains, is contained by, or shares a
    prefix with `DISPATCH_WORKTREE` keeps its own log. `wt/projects/demo`
    with `DISPATCH_WORKTREE=wt` is also today's hub-tooling shape before
    FR-0024 (DEC-0030): inert, as predicted."""
    root = tmp_path / "wt" / "projects" / "demo"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    (root / "specs").mkdir(parents=True)
    (tmp_path / "wt" / "projects" / "demo-other").mkdir()
    (tmp_path / "wt" / "projects" / "xdemo").mkdir()
    worktree = {
        "parent-of-root": root.parent,
        "grandparent-of-root": tmp_path / "wt",
        "child-of-root": root / "specs",
        "scripts-dir": root / "scripts",
        "the-module-file": root / "scripts" / "metrics_log.py",
        "shared-name-prefix": root.parent / "demo-other",
        "shared-name-suffix": root.parent / "xdemo",
        "missing-sibling": root.parent / "demo2",
    }[case]
    mod = _load_copy(root, redirect, str(worktree), monkeypatch)
    assert mod.METRICS_DIR == root.resolve() / "specs" / "_metrics"


# covers hub-tooling FR-0018:AC-2
def test_a_contained_copy_follows_once_the_seam_names_its_prefix(tmp_path, monkeypatch):
    """The other half of the FR-0024 shape: name the prefix and it follows."""
    root = tmp_path / "wt" / "projects" / "demo"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    assert _load_copy(root, redirect, str(root), monkeypatch).METRICS_DIR == redirect


_WIN = pytest.mark.skipif(sys.platform != "win32", reason="a Windows path spelling")


# covers hub-tooling FR-0018:AC-2
@_WIN
def test_long_path_prefix_case_and_mixed_separators_still_match(tmp_path, monkeypatch):
    root = tmp_path / "Project-Root"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    _mf._copy_metrics_log(root)
    spellings = [
        "\\\\?\\" + str(root.resolve()),
        str(root).swapcase() + "\\",
        str(root).replace("\\", "/") + "/",
        "\\\\?\\" + str(root.resolve()).upper(),
    ]
    for spelling in spellings:
        mod = _load_copy(root, redirect, spelling, monkeypatch)
        assert mod.METRICS_DIR == redirect, spelling
    # ... and the prefix does not make a sibling match.
    other = tmp_path / "Project-Root-2"
    other.mkdir()
    mod = _load_copy(root, redirect, "\\\\?\\" + str(other.resolve()), monkeypatch)
    assert mod.METRICS_DIR == root.resolve() / "specs" / "_metrics"


def _junction(target: Path, link: Path) -> None:
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, OSError) as e:  # pragma: no cover - host-specific
        pytest.skip(f"cannot create a junction here: {e}")


# covers hub-tooling FR-0018:AC-2
@_WIN
def test_a_junction_to_the_root_matches_and_a_junction_elsewhere_does_not(
    tmp_path, monkeypatch
):
    root = tmp_path / "real-root"
    other = tmp_path / "other-root"
    other.mkdir()
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    _mf._copy_metrics_log(root)
    to_root = tmp_path / "via-junction"
    to_other = tmp_path / "via-junction-elsewhere"
    _junction(root, to_root)
    _junction(other, to_other)
    assert _load_copy(root, redirect, str(to_root), monkeypatch).METRICS_DIR == redirect
    mod = _load_copy(root, redirect, str(to_other), monkeypatch)
    assert mod.METRICS_DIR != redirect
    # The module itself loaded through the junction, compared with the real path.
    path = to_root / "scripts" / "metrics_log.py"
    monkeypatch.setenv(_WORKTREE_ENV, str(root))
    assert _mf._import_copy(path).METRICS_DIR == redirect


def _short_path(p: Path) -> str | None:
    import ctypes

    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf))
    return buf.value if n else None


# covers hub-tooling FR-0018:AC-2
@_WIN
def test_an_8dot3_short_name_for_the_root_matches(tmp_path, monkeypatch):
    root = tmp_path / "a-project-root-with-a-long-name"
    redirect = tmp_path / "primary" / "specs" / "_metrics"
    _mf._copy_metrics_log(root)
    short = _short_path(root)
    if not short or Path(short).name.lower() == root.name.lower():
        pytest.skip("8.3 names are disabled on this volume")
    assert _load_copy(root, redirect, short, monkeypatch).METRICS_DIR == redirect


# covers hub-tooling FR-0018:AC-2
def test_without_samefile_the_fallback_still_matches_only_the_same_directory(
    tmp_path, monkeypatch
):
    """`_same_directory`'s resolved-path fallback, forced: same directory by
    another spelling matches; a sibling does not."""
    root = tmp_path / "root"
    other = tmp_path / "root-2"
    other.mkdir()
    redirect = tmp_path / "primary" / "specs" / "_metrics"

    def no_samefile(a, b):
        raise OSError("synthetic: no stat")

    monkeypatch.setattr(os.path, "samefile", no_samefile)
    spelled = str(root / "scripts" / "..") + os.sep
    assert _load_copy(root, redirect, spelled, monkeypatch).METRICS_DIR == redirect
    mod = _load_copy(root, redirect, str(other), monkeypatch)
    assert mod.METRICS_DIR == root.resolve() / "specs" / "_metrics"


# covers hub-tooling FR-0018:AC-2
def test_an_unwritable_redirect_target_is_one_warn_and_never_raises(
    tmp_path, monkeypatch, capsys
):
    """FR-0002 AC-9 under the redirect (FR-0018 Open question default): the
    record is lost with one WARN; the copy's own log is not a fallback."""
    root = tmp_path / "wt"
    blocker = tmp_path / "primary-is-a-file"
    blocker.write_text("not a directory\n", encoding="utf-8")
    redirect = blocker / "specs" / "_metrics"
    monkeypatch.setenv("METRICS_PROJECT", "synthetic-project")
    monkeypatch.delenv("METRICS_LOG_DISABLED", raising=False)
    mod = _load_copy(root, redirect, str(root), monkeypatch)
    assert mod.METRICS_DIR == redirect
    monkeypatch.setattr(mod, "PHI_HOOK_PATH", tmp_path / "no-such-hook.py")
    assert mod.emit("gate.run", source="manual", **_mf._gate_fields()) is None
    err = capsys.readouterr().err
    assert len([ln for ln in err.splitlines() if ln.startswith("WARN: metrics:")]) == 1
    assert not (root / "specs" / "_metrics").exists()


# ---------------------------------------------------------------------------
# AC-4
# ---------------------------------------------------------------------------

_FAKE_INDEXER = """\
import sys
from pathlib import Path

index = Path(__file__).resolve().parent.parent / "specs" / "INDEX.md"
{action}
sys.exit(3)
"""


def _custom_scenario(
    tmp_path: Path,
    *,
    base: dict[str, str] | None = None,
    dev: dict[str, str],
    main: dict[str, str],
    autocrlf: str = "false",
):
    """`_mf._scenario` with arbitrary extra files on each side."""
    repo = tmp_path / "repo"
    _mf._init_repo(repo)
    _git(repo, "config", "core.autocrlf", autocrlf)
    _mf._install_project(repo, _mf._INDEXER_SCRIPTS)
    files = {
        f"specs/{_FR}-synthetic.md": _mf._fr_md(_FR),
        "specs/INDEX.md": "# Spec index\n\nbase\n",
        "README.md": "synthetic\n",
        ".gitignore": (
            f".claude/\n{dispatch.VENV_DIRNAME}/\n__pycache__/\n_dispatch/\nPR_BODY.md\n"
        ),
        **(base or {}),
    }
    for rel, content in files.items():
        _write(repo / rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    wt = repo / ".claude" / "worktrees" / f"dev-{_FR}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", f"claude/dev-{_FR}", str(wt), "main")
    own = _mf._commit(wt, {"src/thing.py": "thing\n", **dev}, "dev: work")
    _write(wt / "PR_BODY.md", "# body\n")
    landed = _mf._commit(repo, main, "feat: landed on main")
    _git(repo, "push", "-q", "origin", "main")
    return _mf._Env(repo, bare), wt, own, landed


_INDEX_SIDES = (
    {"specs/INDEX.md": "# Spec index\n\ndev's index\n"},
    {"specs/INDEX.md": "# Spec index\n\nmain's index\n"},
)


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize(
    "action",
    [
        'index.write_text("synthetic garbage\\n", encoding="utf-8")',
        "index.unlink()",
    ],
    ids=["writes-then-fails", "deletes-then-fails"],
)
def test_an_indexer_that_touches_the_index_and_fails_has_the_conflict_put_back(
    tmp_path, monkeypatch, capsys, action
):
    """The merged tree's indexer (landed on `main`, so the branch never
    touches a control-plane path) rewrites or deletes `INDEX.md` and exits
    3. A naive implementation leaves its output in place of the conflict."""
    dev, main = _INDEX_SIDES
    main = {**main, "scripts/index-specs.py": _FAKE_INDEXER.format(action=action)}
    env, wt, own, _landed = _custom_scenario(tmp_path, dev=dev, main=main)
    _mf._point(monkeypatch, dispatch, env, tmp_path)
    rc = _mf._finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _mf._lines(out, "ERROR")
    assert len(errors) == 1 and "exited 3" in errors[0], out
    assert "left for a human" in errors[0] and "MERGE-RESOLVED" not in out
    text = (wt / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "synthetic garbage" not in text
    assert "<<<<<<<" in text and "dev's index" in text and "main's index" in text
    assert _git(wt, "status", "--porcelain", "--", "specs/INDEX.md") == (
        "UU specs/INDEX.md"
    )
    assert _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize("elsewhere", ["docs/INDEX.md", "specs/sub/INDEX.md"])
def test_an_index_md_outside_specs_is_not_special(
    tmp_path, monkeypatch, capsys, elsewhere
):
    """Only `specs/INDEX.md` itself: a suffix or basename match is wrong."""
    env, wt, own, _landed = _custom_scenario(
        tmp_path,
        base={elsewhere: "base\n"},
        dev={elsewhere: "dev side\n"},
        main={elsewhere: "main side\n"},
    )
    _mf._point(monkeypatch, dispatch, env, tmp_path)
    rc = _mf._finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "MERGE-RESOLVED" not in out and len(_mf._lines(out, "ERROR")) == 1
    assert f"UU {elsewhere}" in _git(wt, "status", "--porcelain")
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None


# covers hub-tooling FR-0018:AC-4
def test_an_unmerged_index_without_merge_head_is_not_resolved(tmp_path):
    """Called directly on a cherry-pick conflict confined to
    `specs/INDEX.md` (`CHERRY_PICK_HEAD`, no `MERGE_HEAD`): returns None and
    changes nothing, so no `commit --no-edit` concludes the wrong operation."""
    env, wt, own, landed = _custom_scenario(
        tmp_path, dev=_INDEX_SIDES[0], main=_INDEX_SIDES[1]
    )
    proc = subprocess.run(
        ["git", "-C", str(wt), "cherry-pick", landed],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert _git(wt, "status", "--porcelain", "--untracked-files=no") == (
        "UU specs/INDEX.md"
    )
    assert not _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    before = (wt / "specs" / "INDEX.md").read_bytes()
    got = dispatch._resolve_index_only_merge_conflict(
        _FR, "dev", f"claude/dev-{_FR}", wt
    )
    assert got is None
    assert (wt / "specs" / "INDEX.md").read_bytes() == before
    assert _git(wt, "rev-parse", "HEAD") == own
    assert _git(wt, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", check=False)
    # ... and with nothing unmerged at all, also None.
    _git(wt, "cherry-pick", "--abort")
    assert (
        dispatch._resolve_index_only_merge_conflict(_FR, "dev", f"claude/dev-{_FR}", wt)
        is None
    )


_HISTORY_REWRITERS = {
    "reset",
    "checkout",
    "restore",
    "rebase",
    "stash",
    "switch",
    "--abort",
    "--continue",
    "--amend",
    "--force",
    "-f",
}


_CODEOWNERS_BASE = {
    ".agent-team/codeowners-config.yaml": 'owner_handle: "@synthetic-owner"\n',
    "CODEOWNERS": "# stale, never regenerated\n",
}


# covers hub-tooling FR-0018:AC-4
@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_the_git_argv_actually_run_hold_one_merge_and_one_commit_no_edit(
    tmp_path, monkeypatch, capsys, autocrlf
):
    """Dynamic, not static: every git argv the dispatcher runs during an
    `INDEX.md`-only resolution, with a codeowners config so the indexer also
    rewrites `CODEOWNERS` and the side-write restore runs (DEC-0030 item 6).
    The restore adds no git argv, and has already put `CODEOWNERS` back when
    `add` and `commit` run. With `core.autocrlf=true` (Git for Windows'
    default) the restored bytes are the checkout's, so the tree is clean."""
    env, wt, own, landed = _custom_scenario(
        tmp_path,
        base=_CODEOWNERS_BASE,
        dev=_INDEX_SIDES[0],
        main=_INDEX_SIDES[1],
        autocrlf=autocrlf,
    )
    _mf._point(monkeypatch, dispatch, env, tmp_path)
    owners = wt / "CODEOWNERS"
    checked_out = owners.read_bytes()
    routed = dispatch.subprocess.run
    seen: list[list[str]] = []
    owners_at: dict[str, bytes | None] = {}

    def recording(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            args = list(cmd[1:])
            if args[:1] == ["-C"]:
                args = args[2:]
            seen.append(args)
            if args[:1] in (["add"], ["commit"]):
                owners_at[args[0]] = owners.read_bytes() if owners.is_file() else None
        return routed(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", recording)
    rc = _mf._finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert len(_mf._lines(out, "MERGE-RESOLVED")) == 1
    merges = [a for a in seen if a[:1] == ["merge"]]
    assert len(merges) == 1 and merges[0][1] == "origin/main", merges
    assert [a for a in seen if a[:1] == ["commit"]] == [["commit", "--no-edit"]]
    assert [a for a in seen if a[:1] == ["add"]] == [["add", "--", "specs/INDEX.md"]]
    bad = [a for a in seen if a and (a[0] in _HISTORY_REWRITERS)]
    bad += [
        a
        for a in seen
        if a[:1] in (["merge"], ["commit"], ["push"])
        and _HISTORY_REWRITERS.intersection(a[1:])
    ]
    assert bad == [], bad
    # Restore order: CODEOWNERS was already back when git staged and committed.
    assert owners_at == {"add": checked_out, "commit": checked_out}
    branch = f"claude/dev-{_FR}"
    assert _git(env.repo, "log", "-1", "--format=%P", branch).split() == [own, landed]
    assert _git(wt, "status", "--porcelain", "--untracked-files=no") == ""
    assert owners.read_bytes() == checked_out
    tip_owners = _git(wt, "show", f"{branch}:CODEOWNERS")
    assert tip_owners == "# stale, never regenerated"
    # The case is real: a regenerate rewrites CODEOWNERS, and only CODEOWNERS.
    _mf._regenerate(wt)
    status = _git(wt, "status", "--porcelain", "--untracked-files=no")
    assert status == "M CODEOWNERS", status


# covers hub-tooling FR-0018:AC-4
def test_a_codeowners_rewrite_by_the_indexer_does_not_leave_the_worktree_dirty(
    tmp_path, monkeypatch, capsys
):
    """r1's E-1 reproduction, now a plain test (DEC-0030 item 6)."""
    env, wt, _own, _landed = _custom_scenario(
        tmp_path, base=_CODEOWNERS_BASE, dev=_INDEX_SIDES[0], main=_INDEX_SIDES[1]
    )
    _mf._point(monkeypatch, dispatch, env, tmp_path)
    rc = _mf._finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 0 and len(_mf._lines(out, "MERGE-RESOLVED")) == 1, out
    assert dispatch._rev_worktree_dirty_paths(wt) == []


_DIRECTORY_INDEXER = """\
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
(root / "specs" / "INDEX.md").write_text("# regenerated\\n", encoding="utf-8")
(root / "CODEOWNERS").mkdir()
(root / "CODEOWNERS" / "stray").write_text("synthetic\\n", encoding="utf-8")
sys.exit(0)
"""


# covers hub-tooling FR-0018:AC-4
def test_a_side_write_that_cannot_be_put_back_stops_before_staging(
    tmp_path, monkeypatch, capsys
):
    """The Developer's round-2 addition: the indexer exits 0, but leaves a
    directory where `CODEOWNERS` was absent, which a file unlink cannot
    remove. One ERROR naming it, `INDEX.md`'s conflict back, no `add`, no
    `commit`, no push."""
    dev, main = _INDEX_SIDES
    main = {**main, "scripts/index-specs.py": _DIRECTORY_INDEXER}
    env, wt, own, _landed = _custom_scenario(tmp_path, dev=dev, main=main)
    _mf._point(monkeypatch, dispatch, env, tmp_path)
    routed = dispatch.subprocess.run
    seen: list[list[str]] = []

    def recording(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            seen.append([x for x in cmd[1:] if x != "-C"])
        return routed(cmd, *a, **k)

    monkeypatch.setattr(dispatch.subprocess, "run", recording)
    rc = _mf._finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _mf._lines(out, "ERROR")
    assert len(errors) == 1 and "could not put back" in errors[0], out
    assert "CODEOWNERS" in errors[0] and "left for a human" in errors[0]
    assert "MERGE-RESOLVED" not in out and "REVALIDATE  " not in out
    assert not any("add" in a or "commit" in a for a in seen), seen
    text = (wt / "specs" / "INDEX.md").read_text(encoding="utf-8")
    assert "# regenerated" not in text
    assert "<<<<<<<" in text and "dev's index" in text and "main's index" in text
    assert "UU specs/INDEX.md" in _git(wt, "status", "--porcelain")
    assert _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []


# covers hub-tooling FR-0018:AC-4
def test_a_refused_commit_says_the_index_is_staged_and_the_merge_in_progress(
    tmp_path, monkeypatch, capsys
):
    """The Developer's round-2 rewording (r1 N-3), driven for real: a
    `pre-commit` hook refuses `git commit --no-edit`. One ERROR that says
    `specs/INDEX.md` is staged and the merge is still in progress, which is
    what git then shows; the side-write is already back; nothing is pushed."""
    env, wt, own, _landed = _custom_scenario(
        tmp_path, base=_CODEOWNERS_BASE, dev=_INDEX_SIDES[0], main=_INDEX_SIDES[1]
    )
    hooks = Path(_git(env.repo, "rev-parse", "--git-common-dir"))
    if not hooks.is_absolute():
        hooks = env.repo / hooks
    hook = hooks / "hooks" / "pre-commit"
    _write(hook, "#!/bin/sh\necho synthetic hook refusal >&2\nexit 1\n")
    hook.chmod(0o755)
    _mf._point(monkeypatch, dispatch, env, tmp_path)
    owners_before = (wt / "CODEOWNERS").read_bytes()
    rc = _mf._finalize(dispatch)
    out = capsys.readouterr().out
    assert rc == 1, out
    errors = _mf._lines(out, "ERROR")
    assert len(errors) == 1, out
    assert "concluding the merge failed" in errors[0]
    assert "specs/INDEX.md is staged and the merge is still in progress" in errors[0]
    assert "MERGE-RESOLVED" not in out and "REVALIDATE  " not in out
    assert _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    assert _git(wt, "diff", "--name-only", "--diff-filter=U") == ""
    assert "specs/INDEX.md" in _git(wt, "diff", "--cached", "--name-only").split()
    assert (wt / "CODEOWNERS").read_bytes() == owners_before
    assert _git(env.repo, "rev-parse", f"claude/dev-{_FR}") == own
    assert env.bare_sha(f"claude/dev-{_FR}") is None and env.gh == []


# ---------------------------------------------------------------------------
# AC-6 / AC-7: what FR-0018's own commits change
#
# Scoped to the commits whose Conventional-Commit scope names FR-0018, not
# diffed against the base, so they stay true after FR-0026 (which edits the
# same README, `metrics_log.py`, gate and indexer) or any later FR lands.
# They skip where the base is unreachable (inside a bootstrapped project).
# ---------------------------------------------------------------------------

_SCOPE_RE = re.compile(r"^\w+\((?:[^)]*[ ,])?FR-0018(?:[ ,][^)]*)?\)!?:")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def _hub_show(ref: str, rel: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(_TEMPLATE_DIR.parent), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=True,
    )
    return proc.stdout


def _fr0018_commits(rel: str) -> list[str]:
    """Non-merge commits touching `rel` (hub-root-relative, so this also
    works from a project inside the hub) whose scope names FR-0018."""
    _mf._require_base(rel)
    out = _git(
        _TEMPLATE_DIR.parent,
        "log",
        "--no-merges",
        "--format=%H %s",
        "--",
        f":(top){rel}",
    )
    shas = []
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if _SCOPE_RE.match(subject):
            shas.append(sha)
    return shas


def _bullet_lines(text: str, head: str) -> range:
    """1-based line numbers of the top-level bullet that starts with `head`."""
    lines = text.splitlines()
    start = next(n for n, ln in enumerate(lines) if ln.startswith(head))
    end = start + 1
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    return range(start + 1, end + 1)


# covers hub-tooling FR-0018:AC-6
def test_fr0018_changes_only_the_committed_bullet_of_the_metrics_readme():
    """Every hunk FR-0018's commits make to the README lies inside the
    `- **Committed**` bullet, before and after it: the `warning_classes` row
    FR-0026 owns and the `gate.decision` rows tests pin are untouched."""
    rel = "template/specs/_metrics/README.md"
    commits = _fr0018_commits(rel)
    assert commits, "AC-6: FR-0018 states where rows go"
    for sha in commits:
        old = _hub_show(f"{sha}^", rel).decode("utf-8")
        new = _hub_show(sha, rel).decode("utf-8")
        old_bullet = _bullet_lines(old, "- **Committed**")
        new_bullet = _bullet_lines(new, "- **Committed**")
        diff = _git(
            _TEMPLATE_DIR.parent, "show", "-U0", "--format=", sha, "--", f":(top){rel}"
        )
        hunks = _HUNK_RE.findall(diff)
        assert hunks, sha
        for o_start, o_len, n_start, n_len in hunks:
            o = range(int(o_start), int(o_start) + int(o_len or 1))
            n = range(int(n_start), int(n_start) + int(n_len or 1))
            assert all(x in old_bullet for x in o), (sha, o)
            assert all(x in new_bullet for x in n), (sha, n)


# covers hub-tooling FR-0018:AC-7
@pytest.mark.parametrize(
    "rel",
    [
        "template/scripts/index-specs.py",
        "template/scripts/deploy-gate.py",
        "template/scripts/escalation-log.py",
        "template/.gitattributes",
    ],
)
def test_no_fr0018_commit_touches_a_file_the_fr_fixes_as_unedited(rel):
    assert _fr0018_commits(rel) == []
    if rel.endswith(".gitattributes"):
        assert b"specs/_metrics/*.ndjson merge=union" in _hub_show("HEAD", rel)


_SCHEMA_NAMES = (
    "SCHEMA_VERSION",
    "ENVELOPE_FIELDS",
    "SOURCES",
    "ROLES",
    "KIND_REQUIRED",
    "KINDS",
    "RESERVED_FIELDS",
    "STRING_FIELDS",
    "GATE_FAILURE_CLASSES",
    "GATE_WARNING_CLASSES",
    "GATE_INVOKED_BY",
)


# covers hub-tooling FR-0018:AC-7
def test_no_fr0018_commit_adds_a_metrics_record_kind_or_field(tmp_path):
    """Each FR-0018 commit's `metrics_log.py` against its parent's: every
    record-schema constant is equal."""
    rel = "template/scripts/metrics_log.py"
    commits = _fr0018_commits(rel)
    assert commits, "AC-2: FR-0018 changes METRICS_DIR's resolution"
    for i, sha in enumerate(commits):
        before, after = (
            _mf._import_copy(
                _mf._copy_metrics_log(tmp_path / f"{i}-{side}", _hub_show(ref, rel))
            )
            for side, ref in (("parent", f"{sha}^"), ("commit", sha))
        )
        for name in _SCHEMA_NAMES:
            assert getattr(after, name) == getattr(before, name), (sha, name)


# ---------------------------------------------------------------------------
# Annotation hygiene (the ride-along rule)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0018:AC-7
def test_neither_fr0018_test_file_carries_a_live_gate_annotation():
    """A literal gate annotation in a template test fails every bootstrapped
    project's gate with `covers-unknown-fr`. Checked with the gate's own
    pattern, so a form the gate would count is caught whatever its spelling."""
    gate = _mf._load_module(_SCRIPTS_DIR / "deploy-gate.py", "deploy_gate_fr0018_adv")
    here = Path(__file__).resolve().parent
    for name in ("test_merge_friction.py", "test_merge_friction_adversarial.py"):
        text = (here / name).read_text(encoding="utf-8")
        assert gate.COVERS_PATTERN.findall(text) == [], name
        assert _COVERS not in text, name
        assert re.findall(r"# covers hub-tooling FR-0018:AC-\d+", text), name


# covers hub-tooling FR-0018:AC-7
def test_fr0018_implements_tags_stay_outside_a_projects_default_scan(tmp_path):
    """The new `@implements FR-0018` tags live in `scripts/`, which a
    bootstrapped project's gate does not scan by default (`src/`), so they
    can at most warn (FR-0023 r2). Pinned at the source level: they are in
    `scripts/` only."""
    tags = [
        p.name
        for p in sorted(_SCRIPTS_DIR.glob("*.py"))
        if "@implements FR-0018" in p.read_text(encoding="utf-8")
    ]
    assert tags == ["dispatch.py", "metrics_log.py"]
    gate_src = (_SCRIPTS_DIR / "deploy-gate.py").read_text(encoding="utf-8")
    assert "implements-unknown-fr" in gate_src  # a warning class, never a failure
