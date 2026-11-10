"""Hub-level reviewer tests for FR-0019 AC-1: every hub-script text write is LF.

Each write site AC-1 names is driven through a `tmp_path` tree three times:

* **live** -- the checked-out `scripts/{bootstrap,parking,patterns}.py`;
* **fr** -- the same script at FR-0019's implementation commit `7bec5d6`;
* **base** -- the same script at FR-0019's base `82670a5`.

`fr` and `base` are loaded from `git show` as extra modules. The live run must
write no `\\r\\n` anywhere in its tree: that is the standing invariant. The
"apart from line endings, byte-identical to today's output" clause is a
statement about FR-0019's own diff, so it is checked between the two fixed
commits (`fr` == `base` with `\\r\\n` normalised to `\\n`) and never rots when a
later FR legitimately changes a script's output. On Windows the base runs
natively and really writes CRLF. Elsewhere a Windows shim (FR-0007's technique, see
`template/tests/unit/scripts/test_line_endings.py`) wraps `Path.write_text` so
a call *without* `newline=` translates `\\n` to `\\r\\n`, as CPython does on
Windows; a call that passes `newline=` is forwarded untouched. Either way the
base output is asserted to contain CRLF, so each LF assertion has teeth.

Every root-derived module constant is monkeypatched to the temp tree before a
site runs: `HUB_ROOT`/`TEMPLATE_ROOT`/`PROFILES_ROOT` (bootstrap),
`HUB_ROOT`/`PARKING_DIR`/`INDEX_PATH` (parking) and
`HUB_ROOT`/`PATTERNS_DIR`/`INDEX_PATH`/`HUB_INDEX_PATH` (patterns). `today()`
is pinned so head and base runs are comparable. Nothing here touches the live
parking lot, pattern catalog, registry or `projects/`. Fixture text is
synthetic.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

# tests/unit/scripts/ -> parents[3] == hub root
HUB_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = HUB_ROOT / "scripts"
TEMPLATE_DIR = HUB_ROOT / "template"
PROFILE_DIR = HUB_ROOT / "profiles" / "phipa"
BASE_REF = "82670a5354c2561e3bb350945bd09dd154ed0099"
# FR-0019's implementation commit: the other end of AC-1's "identical apart
# from line endings" comparison. Immutable, so the comparison never rots.
FR_REF = "7bec5d6731bbfc7f681cb28ee827a378c687b095"
FIXED_DAY = "2026-01-02"
COMMANDS_REL = "template/.agent-team/commands"


def _load_module(name: str, path: Path) -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # parking/patterns define dataclasses, which look their module up in
    # sys.modules while the class body is processed.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git_show(ref: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(HUB_ROOT), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


HEAD = {
    "bootstrap": _load_module("bootstrap_fr0019_lf_head", SCRIPTS_DIR / "bootstrap.py"),
    "parking": _load_module("parking_fr0019_lf_head", SCRIPTS_DIR / "parking.py"),
    "patterns": _load_module("patterns_fr0019_lf_head", SCRIPTS_DIR / "patterns.py"),
}


def _command_names(ref: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(HUB_ROOT), "ls-tree", "--name-only", f"{ref}:{COMMANDS_REL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"{ref[:7]} not reachable")
    return sorted(n[:-3] for n in proc.stdout.split() if n.endswith(".md"))


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, ModuleType]]:
    """The three scripts at the base and at FR-0019's commit, keyed
    `{"base"|"fr": {script: module}}`. Skips when either is unreachable."""
    out: dict[str, dict[str, ModuleType]] = {}
    for tag, ref in (("base", BASE_REF), ("fr", FR_REF)):
        d = tmp_path_factory.mktemp(f"{tag}_scripts")
        out[tag] = {}
        for name in HEAD:
            src = _git_show(ref, f"scripts/{name}.py")
            if src is None:
                pytest.skip(f"{tag} {ref[:7]} not reachable")
            (d / f"{name}.py").write_bytes(src)
            out[tag][name] = _load_module(f"{name}_fr0019_lf_{tag}", d / f"{name}.py")
    return out


@pytest.fixture(autouse=True)
def crlf_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a non-Windows host, make `Path.write_text` without `newline=`
    behave as it does on Windows. On Windows the native behaviour is used."""
    if os.name == "nt":
        return
    orig = pathlib.Path.write_text

    def _crlf_write_text(self, data, encoding=None, errors=None, newline=None):
        if newline is None:
            return orig(
                self,
                data.replace("\n", "\r\n"),
                encoding=encoding,
                errors=errors,
                newline="",
            )
        return orig(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(pathlib.Path, "write_text", _crlf_write_text)


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _assert_lf_and_equal_to_base(head: bytes, base_out: bytes, what: str) -> None:
    """`head` is the FR-0019-commit output; `base_out` the base output."""
    assert b"\r\n" in base_out, (
        f"{what}: base did not write CRLF -- the check has no teeth"
    )
    assert b"\r\n" not in head, f"{what}: FR-0019 commit wrote CRLF"
    assert head == _lf(base_out), f"{what}: head differs from base beyond line endings"


def _assert_tree_lf(root: Path) -> None:
    """The live run's standing invariant: nothing in its tree is CRLF (every
    input the scenarios seed is LF, or is CRLF and rewritten by the script)."""
    crlf = [
        str(f.relative_to(root))
        for f in root.rglob("*")
        if f.is_file() and b"\r\n" in f.read_bytes()
    ]
    assert crlf == [], crlf


def _patch_bootstrap(mod: ModuleType, root: Path, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(mod, "HUB_ROOT", root)
    mp.setattr(mod, "TEMPLATE_ROOT", root / "template")
    mp.setattr(mod, "PROFILES_ROOT", root / "profiles")


def _patch_parking(mod: ModuleType, root: Path, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(mod, "HUB_ROOT", root)
    mp.setattr(mod, "PARKING_DIR", root / "parking-lot")
    mp.setattr(mod, "INDEX_PATH", root / "parking-lot" / "INDEX.md")
    mp.setattr(mod, "today", lambda: FIXED_DAY)
    (root / "parking-lot").mkdir(parents=True, exist_ok=True)


def _patch_patterns(mod: ModuleType, root: Path, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(mod, "HUB_ROOT", root)
    mp.setattr(mod, "PATTERNS_DIR", root / "patterns")
    mp.setattr(mod, "INDEX_PATH", root / "patterns" / "INDEX.md")
    mp.setattr(mod, "HUB_INDEX_PATH", root / "hub" / "PATTERN-INDEX.md")
    mp.setattr(mod, "today", lambda: FIXED_DAY)
    (root / "patterns").mkdir(parents=True, exist_ok=True)
    (root / "hub").mkdir(parents=True, exist_ok=True)


def _run_both(
    base: dict[str, ModuleType],
    script: str,
    tmp_path: Path,
    mp: pytest.MonkeyPatch,
    scenario: Callable[[ModuleType, Path], None],
) -> tuple[Path, Path]:
    patch = {
        "bootstrap": _patch_bootstrap,
        "parking": _patch_parking,
        "patterns": _patch_patterns,
    }[script]
    """Run `scenario` with the live, FR-0019-commit and base modules, each in
    its own tree. Asserts the live tree is LF, and returns the (FR-0019
    commit, base) roots for the anchored comparison."""
    roots = {}
    for tag, mod in (
        ("live", HEAD[script]),
        ("head", base["fr"][script]),
        ("base", base["base"][script]),
    ):
        root = tmp_path / tag
        root.mkdir()
        patch(mod, root, mp)
        scenario(mod, root)
        roots[tag] = root
    _assert_tree_lf(roots["live"])
    return roots["head"], roots["base"]


# ---------------------------------------------------------------------------
# scripts/bootstrap.py
# ---------------------------------------------------------------------------


# @covers FR-0019:AC-1
def test_substitute_description_writes_lf(base, tmp_path, monkeypatch):
    def scenario(mod, root):
        _write(root / "AGENTS.md", (TEMPLATE_DIR / "AGENTS.md").read_bytes())
        mod.substitute_description(root / "AGENTS.md", "Synthetic project for FR-0019.")

    h, b = _run_both(base, "bootstrap", tmp_path, monkeypatch, scenario)
    _assert_lf_and_equal_to_base(
        (h / "AGENTS.md").read_bytes(), (b / "AGENTS.md").read_bytes(), "AGENTS.md"
    )
    assert b"Synthetic project for FR-0019." in (h / "AGENTS.md").read_bytes()


# @covers FR-0019:AC-1
@pytest.mark.parametrize("stack", ["python", "node"])
def test_inject_stack_writes_lf(base, tmp_path, monkeypatch, stack):
    def scenario(mod, root):
        _write(root / "AGENTS.md", (TEMPLATE_DIR / "AGENTS.md").read_bytes())
        mod.inject_stack(root / "AGENTS.md", stack)

    h, b = _run_both(base, "bootstrap", tmp_path, monkeypatch, scenario)
    _assert_lf_and_equal_to_base(
        (h / "AGENTS.md").read_bytes(), (b / "AGENTS.md").read_bytes(), stack
    )


# @covers FR-0019:AC-1
@pytest.mark.parametrize("stack", ["python", "node"])
def test_enable_cursor_rule_writes_lf(base, tmp_path, monkeypatch, stack):
    rel = Path(".cursor") / "rules" / f"20-{stack}.mdc"

    def scenario(mod, root):
        _write(root / rel, (TEMPLATE_DIR / rel).read_bytes())
        mod.enable_cursor_rule(root / rel)

    h, b = _run_both(base, "bootstrap", tmp_path, monkeypatch, scenario)
    _assert_lf_and_equal_to_base(
        (h / rel).read_bytes(), (b / rel).read_bytes(), str(rel)
    )


# @covers FR-0019:AC-1
@pytest.mark.parametrize("stack", ["python", "node"])
def test_uncomment_ci_job_writes_lf(base, tmp_path, monkeypatch, stack):
    rel = Path(".github") / "workflows" / "agent-gates.yml"

    def scenario(mod, root):
        _write(root / rel, (TEMPLATE_DIR / rel).read_bytes())
        mod.uncomment_ci_job(root / rel, stack)

    h, b = _run_both(base, "bootstrap", tmp_path, monkeypatch, scenario)
    _assert_lf_and_equal_to_base(
        (h / rel).read_bytes(), (b / rel).read_bytes(), str(rel)
    )


# @covers FR-0019:AC-1
def test_generate_commands_writes_both_wrappers_lf(base, tmp_path, monkeypatch):
    """Each generator over its own commit's sources (live: the checked-out
    ones): every live wrapper LF; the FR-0019 commit's 22 wrappers equal the
    base's CRLF output normalised."""
    names = _command_names(FR_REF)
    assert _command_names(BASE_REF) == names

    def scenario(mod, root):
        if mod is HEAD["bootstrap"]:
            live = sorted((HUB_ROOT / COMMANDS_REL).glob("*.md"))
            for src in live:
                _write(root / ".agent-team" / "commands" / src.name, src.read_bytes())
            assert mod.generate_commands(root) == len(live)
            return
        ref = FR_REF if mod is base["fr"]["bootstrap"] else BASE_REF
        for name in names:
            data = _git_show(ref, f"{COMMANDS_REL}/{name}.md")
            assert data is not None
            _write(root / ".agent-team" / "commands" / f"{name}.md", data)
        assert mod.generate_commands(root) == len(names)

    h, b = _run_both(base, "bootstrap", tmp_path, monkeypatch, scenario)
    n = 0
    for harness in (".claude", ".cursor"):
        for name in names:
            rel = Path(harness) / "commands" / f"{name}.md"
            _assert_lf_and_equal_to_base(
                (h / rel).read_bytes(), (b / rel).read_bytes(), str(rel)
            )
            n += 1
    assert n == 22


# @covers FR-0019:AC-1
@pytest.mark.parametrize("with_marker", [True, False])
def test_profile_hygiene_block_append_writes_lf(
    base, tmp_path, monkeypatch, with_marker
):
    """Both branches of the append: before `## Universal rules`, and at the
    end when the marker is absent."""

    def scenario(mod, root):
        shutil.copytree(PROFILE_DIR, root / "profiles" / "phipa")
        agents = (TEMPLATE_DIR / "AGENTS.md").read_text(encoding="utf-8")
        if not with_marker:
            agents = agents.replace("## Universal rules", "## Common rules")
        _write(root / "proj" / "AGENTS.md", agents)
        _write(
            root / "proj" / ".claude" / "settings.json",
            (TEMPLATE_DIR / ".claude" / "settings.json").read_bytes(),
        )
        mod.apply_profiles(root / "proj", ["phipa"])

    h, b = _run_both(base, "bootstrap", tmp_path, monkeypatch, scenario)
    rel = Path("proj") / "AGENTS.md"
    _assert_lf_and_equal_to_base(
        (h / rel).read_bytes(), (b / rel).read_bytes(), "AGENTS.md+phipa"
    )
    settings = Path("proj") / ".claude" / "settings.json"
    assert b"\r" not in (h / settings).read_bytes()


# ---------------------------------------------------------------------------
# scripts/parking.py
# ---------------------------------------------------------------------------

IDEA_LF = (
    "---\n"
    "id: IDEA-0007\n"
    "title: Synthetic parked idea\n"
    "status: parked\n"
    "tags:\n- synthetic\n"
    "size: S\n"
    "created: '2026-01-01'\n"
    "updated: '2026-01-01'\n"
    "last_reviewed: '2026-01-01'\n"
    "promoted_to: null\n"
    "pattern: null\n"
    "archive_reason: null\n"
    "---\n"
    "\n# IDEA-0007: Synthetic parked idea\n\n## Description\n\nLine one.\nLine two.\n"
)


def _add_args(**kw) -> Namespace:
    base_kw = {
        "title": "Synthetic idea — with an em dash",
        "description": "Synthetic description.",
        "tags": "alpha,beta",
        "size": "S",
        "value": "Synthetic value hypothesis.",
        "context": "Synthetic context.",
    }
    base_kw.update(kw)
    return Namespace(**base_kw)


# @covers FR-0019:AC-1
def test_parking_cmd_add_writes_the_idea_and_the_index_lf(
    base, tmp_path, monkeypatch, capsys
):
    def scenario(mod, root):
        _write(root / "parking-lot" / "IDEA-0007-synthetic-parked-idea.md", IDEA_LF)
        assert mod.cmd_add(_add_args()) == 0

    h, b = _run_both(base, "parking", tmp_path, monkeypatch, scenario)
    new = "parking-lot/IDEA-0008-synthetic-idea-with-an-em-dash.md"
    _assert_lf_and_equal_to_base((h / new).read_bytes(), (b / new).read_bytes(), new)
    idx = "parking-lot/INDEX.md"
    _assert_lf_and_equal_to_base((h / idx).read_bytes(), (b / idx).read_bytes(), idx)


# @covers FR-0019:AC-1
def test_parking_write_idea_via_promote_writes_lf(base, tmp_path, monkeypatch, capsys):
    rel = "parking-lot/IDEA-0007-synthetic-parked-idea.md"

    def scenario(mod, root):
        _write(root / rel, IDEA_LF)
        assert (
            mod.cmd_promote(
                Namespace(idea_id="IDEA-0007", to_fr="synth/FR-0001", to_project=None)
            )
            == 0
        )

    h, b = _run_both(base, "parking", tmp_path, monkeypatch, scenario)
    _assert_lf_and_equal_to_base((h / rel).read_bytes(), (b / rel).read_bytes(), rel)
    assert b"promoted_to: synth/FR-0001" in (h / rel).read_bytes()


# @covers FR-0019:AC-1
def test_parking_reindex_writes_lf(base, tmp_path, monkeypatch):
    def scenario(mod, root):
        _write(root / "parking-lot" / "IDEA-0007-synthetic-parked-idea.md", IDEA_LF)
        mod.reindex()

    h, b = _run_both(base, "parking", tmp_path, monkeypatch, scenario)
    idx = "parking-lot/INDEX.md"
    _assert_lf_and_equal_to_base((h / idx).read_bytes(), (b / idx).read_bytes(), idx)


# @covers FR-0019:AC-1
def test_parking_empty_reindex_writes_lf(base, tmp_path, monkeypatch):
    h, b = _run_both(
        base, "parking", tmp_path, monkeypatch, lambda mod, root: mod.reindex()
    )
    idx = "parking-lot/INDEX.md"
    _assert_lf_and_equal_to_base((h / idx).read_bytes(), (b / idx).read_bytes(), idx)
    assert b"_Empty." in (h / idx).read_bytes()


# @covers FR-0019:AC-1
def test_a_pre_existing_crlf_idea_is_rewritten_wholly_lf(
    base, tmp_path, monkeypatch, capsys
):
    """A CRLF IDEA touched by `archive`: `read_text` reads it in universal-
    newline mode, so the body arrives as LF and `write_idea` writes the whole
    file LF -- frontmatter *and* the untouched body. The base wrote the whole
    file CRLF. Content is otherwise identical. (The script does not preserve a
    file's existing line endings; it normalises the file it rewrites.)"""
    rel = "parking-lot/IDEA-0007-synthetic-parked-idea.md"
    crlf = IDEA_LF.replace("\n", "\r\n").encode("utf-8")

    def scenario(mod, root):
        _write(root / rel, crlf)
        assert mod.cmd_archive(Namespace(idea_id="IDEA-0007", reason="synthetic")) == 0

    h, b = _run_both(base, "parking", tmp_path, monkeypatch, scenario)
    head = (h / rel).read_bytes()
    assert b"\r" not in head
    assert b"Line one.\nLine two.\n" in head
    _assert_lf_and_equal_to_base(head, (b / rel).read_bytes(), rel)
    # The index a CRLF IDEA feeds is LF too.
    assert b"\r" not in (h / "parking-lot" / "INDEX.md").read_bytes()


# ---------------------------------------------------------------------------
# scripts/patterns.py
# ---------------------------------------------------------------------------

PATTERN_LF = (
    "---\n"
    "id: PATTERN-0003\n"
    "name: Synthetic pattern\n"
    "status: proposed\n"
    "tags:\n- synthetic\n"
    "created: '2026-01-01'\n"
    "updated: '2026-01-01'\n"
    "instances:\n- synth/FR-0001\n"
    "ideas:\n- IDEA-0007\n"
    "rejection_reason: null\n"
    "---\n"
    "\n# PATTERN-0003: Synthetic pattern\n\n## Description\n\nOne.\nTwo.\n"
)


def _propose_args() -> Namespace:
    return Namespace(
        name="Synthetic proposal — em dash",
        description="Synthetic.",
        value="Synthetic compounding value: 3 x 2h saved.",
        tags="alpha",
        instances="synth/FR-0001,synth/FR-0002",
        ideas="IDEA-0007",
    )


# @covers FR-0019:AC-1
def test_patterns_cmd_propose_writes_the_pattern_and_both_indexes_lf(
    base, tmp_path, monkeypatch, capsys
):
    def scenario(mod, root):
        _write(root / "patterns" / "PATTERN-0003-synthetic-pattern.md", PATTERN_LF)
        assert mod.cmd_propose(_propose_args()) == 0

    h, b = _run_both(base, "patterns", tmp_path, monkeypatch, scenario)
    new = "patterns/PATTERN-0004-synthetic-proposal-em-dash.md"
    for rel in (new, "patterns/INDEX.md", "hub/PATTERN-INDEX.md"):
        _assert_lf_and_equal_to_base(
            (h / rel).read_bytes(), (b / rel).read_bytes(), rel
        )


# @covers FR-0019:AC-1
def test_patterns_write_pattern_via_accept_writes_lf(
    base, tmp_path, monkeypatch, capsys
):
    rel = "patterns/PATTERN-0003-synthetic-pattern.md"

    def scenario(mod, root):
        _write(root / rel, PATTERN_LF.replace("\n", "\r\n"))
        assert mod.cmd_accept(Namespace(pattern_id="PATTERN-0003")) == 0

    h, b = _run_both(base, "patterns", tmp_path, monkeypatch, scenario)
    head = (h / rel).read_bytes()
    assert b"\r" not in head and b"status: accepted" in head
    _assert_lf_and_equal_to_base(head, (b / rel).read_bytes(), rel)


# @covers FR-0019:AC-1
def test_patterns_reindex_writes_both_indexes_lf_and_identical(
    base, tmp_path, monkeypatch
):
    def scenario(mod, root):
        _write(root / "patterns" / "PATTERN-0003-synthetic-pattern.md", PATTERN_LF)
        mod.reindex()

    h, b = _run_both(base, "patterns", tmp_path, monkeypatch, scenario)
    for rel in ("patterns/INDEX.md", "hub/PATTERN-INDEX.md"):
        _assert_lf_and_equal_to_base(
            (h / rel).read_bytes(), (b / rel).read_bytes(), rel
        )
    assert (h / "patterns/INDEX.md").read_bytes() == (
        h / "hub/PATTERN-INDEX.md"
    ).read_bytes()


# ---------------------------------------------------------------------------
# Structural guard
# ---------------------------------------------------------------------------


def _unguarded_write_text_calls(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
        ):
            nl = [k for k in node.keywords if k.arg == "newline"]
            if not nl or not (
                isinstance(nl[0].value, ast.Constant) and nl[0].value.value == "\n"
            ):
                lines.append(node.lineno)
    return lines


# @covers FR-0019:AC-1
@pytest.mark.parametrize("script", ["bootstrap", "parking", "patterns"])
def test_no_write_text_call_in_the_three_scripts_omits_newline_lf(script):
    """Adversarial: a write site added later without `newline="\\n"` (or a
    named site this review missed) is caught statically."""
    src = (SCRIPTS_DIR / f"{script}.py").read_text(encoding="utf-8")
    assert _unguarded_write_text_calls(src) == []


# @covers FR-0019:AC-1
def test_the_structural_guard_bites_on_the_base_scripts():
    counts = {}
    for script in ("bootstrap", "parking", "patterns"):
        src = _git_show(BASE_REF, f"scripts/{script}.py")
        if src is None:
            pytest.skip("base not reachable")
        counts[script] = len(_unguarded_write_text_calls(src.decode("utf-8")))
    # AC-1's list: bootstrap 7 (4 helpers + 2 wrappers + profile append),
    # parking 3, patterns 4.
    assert counts == {"bootstrap": 7, "parking": 3, "patterns": 4}
