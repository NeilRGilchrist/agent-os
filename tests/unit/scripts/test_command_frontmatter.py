"""Hub-level reviewer tests for `scripts/bootstrap.py` -- FR-0019 AC-2..AC-6:
each canonical command source carries its own wrapper frontmatter, and
`generate_commands` reads it instead of the retired `COMMAND_META`.

Three copies of the generator are exercised:

* **live** -- `scripts/bootstrap.py` as checked out. Used only for standing
  invariants (the block never reaches a wrapper body, Claude-only keys, AC-5's
  refusals, `COMMAND_META` stays gone) that every later FR must keep.
* **fr** -- `git show 7bec5d6:scripts/bootstrap.py`, FR-0019's implementation
  commit, with the sources at that commit. Every "exactly as at the base"
  comparison (AC-2's values, AC-3's fallback, AC-4's bytes, AC-6's output) is a
  statement about FR-0019's own diff, so it is made between this fixed commit
  and the base and never rots when a later FR edits a source or the script.
* **base** -- `git show 82670a5:scripts/bootstrap.py` (FR-0019's base). It is
  the oracle for "exactly as today" and the target of the bite checks: against
  the frontmatter-bearing sources it emits the source block inside the wrapper
  body.

AC-6's "what changed" pins diff fixed commits too: `82670a5..7bec5d6` for the
implementation and `7bec5d6..55d7805` for the Reviewer's DEC-0016 cascade.
All `git` reads skip when the object is unreachable.

Everything runs in `tmp_path` trees. Every root-derived module constant
(`HUB_ROOT`, `TEMPLATE_ROOT`, `PROFILES_ROOT`) is monkeypatched before any
flow that reads them runs; `generate_commands` itself takes its target
explicitly. Nothing here writes to the live hub. Fixtures under
`tests/fixtures/command-frontmatter/` are synthetic. Comparisons are on bytes,
with the base generator's host line endings normalised (`\\r\\n` -> `\\n`)
where the AC says "apart from line endings".
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

# tests/unit/scripts/ -> parents[3] == hub root
HUB_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = HUB_ROOT / "scripts"
TEMPLATE_DIR = HUB_ROOT / "template"
COMMANDS_REL = ".agent-team/commands"
FIXTURES = HUB_ROOT / "tests" / "fixtures" / "command-frontmatter"
BASE_REF = "82670a5354c2561e3bb350945bd09dd154ed0099"
# FR-0019's implementation commit (sources + generator) and the Reviewer's
# DEC-0016 cascade commit. Immutable anchors for FR-0019's own diff.
FR_REF = "7bec5d6731bbfc7f681cb28ee827a378c687b095"
CASCADE_REF = "55d780564e4979c0b449348c92667371539b7ef0"

NAMES = (
    "architect",
    "developer",
    "docs",
    "escalate",
    "gate",
    "gate-review",
    "maintainer",
    "orchestrator",
    "reviewer",
    "reviewer-backfill",
    "status",
)
QUOTED = ("description", "argument-hint")
CLAUDE_ONLY = ("model", "effort", "allowed-tools")
HARNESSES = (".claude", ".cursor")


def _load_module(name: str, path: Path) -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_show(ref: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(HUB_ROOT), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _base_or_skip(rel: str) -> bytes:
    data = _git_show(BASE_REF, rel)
    if data is None:
        pytest.skip(f"base {BASE_REF[:7]}:{rel} not reachable")
    return data


def _fr_or_skip(rel: str) -> bytes:
    data = _git_show(FR_REF, rel)
    if data is None:
        pytest.skip(f"FR-0019 commit {FR_REF[:7]}:{rel} not reachable")
    return data


bs = _load_module("bootstrap_fr0019_head", SCRIPTS_DIR / "bootstrap.py")


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    """`scripts/bootstrap.py` at FR-0019's base, as a second module."""
    src = _git_show(BASE_REF, "scripts/bootstrap.py")
    if src is None:
        pytest.skip(f"base {BASE_REF[:7]} not reachable")
    d = tmp_path_factory.mktemp("base_scripts")
    (d / "bootstrap.py").write_bytes(src)
    return _load_module("bootstrap_fr0019_base", d / "bootstrap.py")


@pytest.fixture(scope="module")
def fr(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    """`scripts/bootstrap.py` at FR-0019's implementation commit."""
    src = _git_show(FR_REF, "scripts/bootstrap.py")
    if src is None:
        pytest.skip(f"FR-0019 commit {FR_REF[:7]} not reachable")
    d = tmp_path_factory.mktemp("fr_scripts")
    (d / "bootstrap.py").write_bytes(src)
    return _load_module("bootstrap_fr0019_fr", d / "bootstrap.py")


@pytest.fixture(autouse=True)
def _isolate_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file may resolve a live-hub path through the module."""
    fake = tmp_path / "_fake_hub"
    monkeypatch.setattr(bs, "HUB_ROOT", fake)
    monkeypatch.setattr(bs, "TEMPLATE_ROOT", fake / "template")
    monkeypatch.setattr(bs, "PROFILES_ROOT", fake / "profiles")


def _patch_roots(mod: ModuleType, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "HUB_ROOT", root)
    monkeypatch.setattr(mod, "TEMPLATE_ROOT", root / "template")
    monkeypatch.setattr(mod, "PROFILES_ROOT", root / "profiles")


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _render_block(meta: dict[str, str]) -> bytes:
    """AC-2's block for `meta`, in COMMAND_META's order and today's quoting,
    plus exactly one blank line."""
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f'{key}: "{value}"' if key in QUOTED else f"{key}: {value}")
    lines += ["---", ""]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _gen(mod: ModuleType, root: Path, sources: dict[str, bytes]) -> int:
    for name, data in sources.items():
        _write(root / COMMANDS_REL / f"{name}.md", data)
    return mod.generate_commands(root)


def _wrapper(root: Path, harness: str, name: str) -> bytes:
    return (root / harness / "commands" / f"{name}.md").read_bytes()


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _split_wrapper(data: bytes) -> tuple[list[bytes], bytes]:
    """(frontmatter lines, everything after the closing fence)."""
    assert data.startswith(b"---\n"), data[:40]
    close = data.index(b"\n---\n", 4)
    return data[4:close].split(b"\n"), data[close + 5 :]


def _banner(name: str) -> bytes:
    return (
        f"<!-- Generated from .agent-team/commands/{name}.md — do not edit by hand. -->"
    ).encode()


def _head_sources() -> dict[str, bytes]:
    """The checked-out sources: input for the standing-invariant tests only."""
    return {
        p.stem: p.read_bytes()
        for p in sorted((TEMPLATE_DIR / COMMANDS_REL).glob("*.md"))
    }


def _fr_sources() -> dict[str, bytes]:
    """The 11 sources as FR-0019 committed them."""
    return {n: _fr_or_skip(f"template/{COMMANDS_REL}/{n}.md") for n in NAMES}


def _warn_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("WARN:")]


# ---------------------------------------------------------------------------
# AC-2: each canonical source declares its own metadata
# ---------------------------------------------------------------------------


def _ac2_failures(
    name: str, data: bytes, meta: dict[str, str], base_src: bytes
) -> list[str]:
    expected = _render_block(meta) + base_src
    if data == expected:
        return []
    fails: list[str] = []
    if not data.startswith(_render_block(meta)):
        fails.append(
            f"{name}: block differs from COMMAND_META (keys/values/order/quoting/blank line)"
        )
    if not data.endswith(base_src):
        fails.append(f"{name}: body differs from base")
    return fails or [f"{name}: differs"]


# @covers FR-0019:AC-2
def test_exactly_the_eleven_base_commands_exist_and_each_has_a_base_meta_entry(base):
    _fr_or_skip("scripts/bootstrap.py")
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(HUB_ROOT),
            "ls-tree",
            "--name-only",
            f"{FR_REF}:template/{COMMANDS_REL}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert sorted(n[:-3] for n in proc.stdout.split()) == sorted(NAMES)
    assert sorted(base.COMMAND_META) == sorted(NAMES)


# @covers FR-0019:AC-2
@pytest.mark.parametrize("name", NAMES)
def test_source_is_base_meta_block_then_one_blank_line_then_base_file(base, name):
    rel = f"template/{COMMANDS_REL}/{name}.md"
    base_src = _base_or_skip(rel)
    data = _fr_or_skip(rel)
    meta = base.COMMAND_META[name]
    assert _ac2_failures(name, data, meta, base_src) == []
    # Spelled out, so a failure names the exact clause.
    assert data.startswith(b"---\n")
    block_lines = data.split(b"\n---\n", 1)[0].split(b"\n")[1:]
    assert [ln.split(b":", 1)[0].decode() for ln in block_lines] == list(meta)
    assert data[len(_render_block(meta)) - 1 : len(_render_block(meta)) + 1] != b"\n\n"
    assert b"\r" not in data


# @covers FR-0019:AC-2
@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda d: d.replace(b"---\n\n", b"---\n\n\n", 1), "two blank lines"),
        (lambda d: d.replace(b"---\n\n", b"---\n", 1), "no blank line"),
        (lambda d: d.replace(b'description: "', b"description: '", 1), "single quotes"),
        (
            lambda d: d.replace(b"model: sonnet", b'model: "sonnet"', 1),
            "quoted bare key",
        ),
        (
            lambda d: d.replace(
                b'argument-hint: "FR-XXXX"\nmodel: sonnet',
                b'model: sonnet\nargument-hint: "FR-XXXX"',
                1,
            ),
            "reordered keys",
        ),
        (lambda d: d.replace(b"effort: medium\n", b"", 1), "dropped key"),
        (lambda d: d + b"\n", "body changed"),
    ],
)
def test_ac2_checker_catches_each_shape_violation(base, mutate, why):
    """Adversarial: the AC-2 comparison is not satisfied by "close enough"."""
    base_src = _base_or_skip(f"template/{COMMANDS_REL}/developer.md")
    data = _fr_or_skip(f"template/{COMMANDS_REL}/developer.md")
    bad = mutate(data)
    assert bad != data, why
    assert _ac2_failures("developer", bad, base.COMMAND_META["developer"], base_src), (
        why
    )


# ---------------------------------------------------------------------------
# AC-3: generate_commands reads each source's frontmatter; COMMAND_META gone
# ---------------------------------------------------------------------------


# @covers FR-0019:AC-3
def test_command_meta_is_gone_and_no_hub_code_reads_per_command_metadata():
    assert not hasattr(bs, "COMMAND_META")
    offenders = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\bCOMMAND_META\b(?!_)", text):
            line = text[: m.start()].count("\n") + 1
            stripped = text.splitlines()[line - 1].lstrip()
            # Prose in comments/docstrings naming the retired dict is fine; any
            # code use (assignment, subscript, .get) is not.
            if re.search(r"\bCOMMAND_META\s*(=|\[|\.get|\.items|\.keys)", stripped):
                offenders.append(f"{path.name}:{line}")
    assert offenders == []
    # No other hub script carries the wrapper metadata strings.
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name == "bootstrap.py":
            continue
        assert "Write tests adversarially against every AC" not in path.read_text(
            encoding="utf-8"
        ), path.name


# @covers FR-0019:AC-3
def test_signature_and_return_value_are_unchanged(base, fr, tmp_path):
    assert inspect.signature(fr.generate_commands) == inspect.signature(
        base.generate_commands
    )
    assert _gen(fr, tmp_path / "t", _fr_sources()) == len(NAMES)
    assert _gen(fr, tmp_path / "empty", {}) == 0
    live = _head_sources()
    assert _gen(bs, tmp_path / "live", live) == len(live)


# @covers FR-0019:AC-3
def test_source_without_a_block_gets_the_unknown_name_fallback(
    base, fr, tmp_path, capsys
):
    src = (FIXTURES / "wellformed" / "no-block.md").read_bytes()
    assert _gen(fr, tmp_path / "head", {"no-block": src}) == 1
    assert _gen(base, tmp_path / "base", {"no-block": src}) == 1
    assert _warn_lines(capsys.readouterr().err) == []
    for harness in HARNESSES:
        head = _wrapper(tmp_path / "head", harness, "no-block")
        assert head == _lf(_wrapper(tmp_path / "base", harness, "no-block")), harness
        fm, _ = _split_wrapper(head)
        assert fm == [b'description: "Run the no-block command."'], harness
    assert _wrapper(tmp_path / "head", ".claude", "no-block").endswith(
        _banner("no-block") + b"\n\n" + src
    )


# @covers FR-0019:AC-3
@pytest.mark.parametrize("name", NAMES)
def test_the_source_block_never_appears_in_either_wrapper_body(tmp_path, name):
    """Standing invariant: the live generator over the live sources."""
    live = _head_sources()
    if name not in live:
        pytest.skip(f"{name}.md no longer a canonical command")
    _gen(bs, tmp_path, live)
    src = live[name]
    block = src.split(b"\n---\n", 1)[0] + b"\n---\n"
    for harness in HARNESSES:
        _, rest = _split_wrapper(_wrapper(tmp_path, harness, name))
        assert rest.startswith(_banner(name) + b"\n\n"), harness
        body = rest[len(_banner(name)) + 2 :]
        assert block not in body, harness
        assert not body.startswith(b"---"), harness
        assert b"description: " not in body, harness


# @covers FR-0019:AC-3
@pytest.mark.parametrize("name", NAMES)
def test_claude_only_keys_only_in_claude_and_args_substituted_in_cursor(tmp_path, name):
    live = _head_sources()
    if name not in live:
        pytest.skip(f"{name}.md no longer a canonical command")
    _gen(bs, tmp_path, live)
    claude_fm, claude_rest = _split_wrapper(_wrapper(tmp_path, ".claude", name))
    cursor_fm, cursor_rest = _split_wrapper(_wrapper(tmp_path, ".cursor", name))
    for key in CLAUDE_ONLY:
        assert not any(ln.startswith(key.encode() + b":") for ln in cursor_fm), key
    assert [ln for ln in claude_fm if ln in cursor_fm] == cursor_fm
    assert b"$ARGUMENTS" not in cursor_rest
    assert cursor_rest == claude_rest.replace(b"$ARGUMENTS", b"{{args}}")


# @covers FR-0019:AC-3
def test_docs_claude_wrapper_carries_all_three_claude_only_keys(tmp_path):
    _gen(bs, tmp_path, _fr_sources())
    fm, _ = _split_wrapper(_wrapper(tmp_path, ".claude", "docs"))
    assert [ln.split(b":", 1)[0].decode() for ln in fm] == [
        "description",
        "argument-hint",
        "model",
        "effort",
        "allowed-tools",
    ]


# ---------------------------------------------------------------------------
# AC-4: lossless migration -- the 22 wrappers regenerate byte-identical
# ---------------------------------------------------------------------------


# @covers FR-0019:AC-4
def test_all_22_wrappers_regenerate_byte_identical_to_base(fr, tmp_path):
    """FR-0019's generator over FR-0019's sources reproduces the base's
    committed wrappers, all 22, byte for byte."""
    root = tmp_path / "template_copy"
    assert _gen(fr, root, _fr_sources()) == len(NAMES)
    checked = 0
    for harness in HARNESSES:
        for name in NAMES:
            rel = f"template/{harness}/commands/{name}.md"
            expected = _base_or_skip(rel)
            got = _wrapper(root, harness, name)
            assert b"\r" not in got, rel
            assert got == expected, rel
            checked += 1
    assert checked == 22


# @covers FR-0019:AC-4
def test_branch_diff_to_the_committed_wrappers_is_empty():
    _base_or_skip("scripts/bootstrap.py")
    _fr_or_skip("scripts/bootstrap.py")
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(HUB_ROOT),
            "diff",
            "--stat",
            BASE_REF,
            CASCADE_REF,
            "--",
            "template/.claude/commands",
            "template/.cursor/commands",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout == ""


SHAPES = {
    "architect": {
        "description": "Synthetic architect-shaped command.",
        "argument-hint": "FR-XXXX or text",
    },
    "developer": {
        "description": "Synthetic developer-shaped command — nothing more.",
        "argument-hint": "FR-XXXX",
        "model": "sonnet",
        "effort": "medium",
    },
    "docs": {
        "description": "Synthetic docs-shaped command; ## FINDINGS.",
        "argument-hint": "<doc-id> (optional)",
        "model": "sonnet",
        "effort": "medium",
        "allowed-tools": "Read, Glob, Edit(docs/client/**), Bash(python *)",
    },
    "gate-review": {
        "description": "Synthetic gate-review-shaped command.",
        "argument-hint": "FR-XXXX gate-id",
    },
}


# @covers FR-0019:AC-4
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_each_metadata_shape_round_trips_to_what_command_meta_rendered(
    base, fr, tmp_path, monkeypatch, shape
):
    """A synthetic source with the block renders exactly what the base
    generator rendered for the same body with the same dict in COMMAND_META."""
    meta = SHAPES[shape]
    body = b"Synthetic body for $ARGUMENTS.\n\n---\n\nTrailing section.\n"
    monkeypatch.setitem(base.COMMAND_META, "synth", dict(meta))
    assert _gen(base, tmp_path / "base", {"synth": body}) == 1
    assert _gen(fr, tmp_path / "head", {"synth": _render_block(meta) + body}) == 1
    for harness in HARNESSES:
        assert _wrapper(tmp_path / "head", harness, "synth") == _lf(
            _wrapper(tmp_path / "base", harness, "synth")
        ), harness


# @covers FR-0019:AC-4
@pytest.mark.parametrize(
    "name", ("architect", "developer", "reviewer", "docs", "gate-review")
)
def test_the_real_shape_exemplars_round_trip(base, fr, tmp_path, name):
    """The four shapes as FR-0019 committed them."""
    base_src = _base_or_skip(f"template/{COMMANDS_REL}/{name}.md")
    _gen(base, tmp_path / "base", {name: base_src})
    _gen(
        fr, tmp_path / "head", {name: _fr_or_skip(f"template/{COMMANDS_REL}/{name}.md")}
    )
    for harness in HARNESSES:
        assert _wrapper(tmp_path / "head", harness, name) == _lf(
            _wrapper(tmp_path / "base", harness, name)
        )


# @covers FR-0019:AC-3
# @covers FR-0019:AC-4
def test_bite_base_generator_emits_the_source_block_inside_the_body(base, tmp_path):
    """Bite check: the base generator has no frontmatter parse. Over the
    frontmatter-bearing sources every wrapper body carries the block, so the
    AC-3 "never in the body" check and the AC-4 byte comparison both fail."""
    root = tmp_path / "base_over_fr"
    _gen(base, root, _fr_sources())
    mismatched = 0
    for harness in HARNESSES:
        for name in NAMES:
            got = _lf(_wrapper(root, harness, name))
            _, rest = _split_wrapper(got)
            body = rest[len(_banner(name)) + 2 :]
            assert body.startswith(b"---\ndescription: "), (harness, name)
            expected = _base_or_skip(f"template/{harness}/commands/{name}.md")
            if got != expected:
                mismatched += 1
    assert mismatched == 22


# ---------------------------------------------------------------------------
# AC-5: malformed block refused per command; unknown key warned and ignored
# ---------------------------------------------------------------------------

GOOD = b'---\ndescription: "A good neighbour."\n---\n\nGood body for $ARGUMENTS.\n'
SENTINEL = b"PRE-EXISTING WRAPPER, MUST SURVIVE BYTE-FOR-BYTE\r\n"

MALFORMED = {
    "no-closing": "closing",
    "not-a-mapping": "not a mapping",
    "multi-line-value": "single-line",
    "quote-in-description": "'description'",
    "quote-in-argument-hint": "'argument-hint'",
}


def _malformed_run(tmp_path: Path, capsys, name: str, data: bytes):
    root = tmp_path / "t"
    for harness in HARNESSES:
        _write(root / harness / "commands" / f"{name}.md", SENTINEL)
    count = _gen(bs, root, {"good": GOOD, name: data})
    err = capsys.readouterr().err
    return root, count, err


# @covers FR-0019:AC-5
@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_malformed_block_is_refused_for_that_command_only(tmp_path, capsys, name):
    data = (FIXTURES / "malformed" / f"{name}.md").read_bytes()
    root, count, err = _malformed_run(tmp_path, capsys, name, data)
    warns = _warn_lines(err)
    assert len(warns) == 1, warns
    assert f"{name}.md" in warns[0] and MALFORMED[name] in warns[0], warns[0]
    for harness in HARNESSES:
        assert _wrapper(root, harness, name) == SENTINEL, harness  # untouched
        assert _wrapper(root, harness, "good").startswith(
            b'---\ndescription: "A good neighbour."\n'
        )
    assert count == 1


# @covers FR-0019:AC-5
@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_malformed_block_writes_nothing_when_no_wrapper_existed(tmp_path, capsys, name):
    data = (FIXTURES / "malformed" / f"{name}.md").read_bytes()
    root = tmp_path / "t"
    assert _gen(bs, root, {"good": GOOD, name: data}) == 1
    for harness in HARNESSES:
        assert not (root / harness / "commands" / f"{name}.md").exists()


# @covers FR-0019:AC-5
@pytest.mark.parametrize(
    "value",
    ['"has \\" escaped"', "'single \"quoted\"'", 'plain "inner" quote'],
)
def test_every_yaml_spelling_of_a_quote_in_description_is_refused(
    tmp_path, capsys, value
):
    data = f"---\ndescription: {value}\n---\n\nBody.\n".encode()
    _, count, err = _malformed_run(tmp_path, capsys, "q", data)
    assert count == 1 and len(_warn_lines(err)) == 1


# @covers FR-0019:AC-5
@pytest.mark.parametrize(
    "line",
    ["model: 3", "effort: yes", "model:", "model: [a, b]", 'description: "a\\nb"'],
)
def test_non_string_or_embedded_newline_values_are_refused(tmp_path, capsys, line):
    data = f"---\n{line}\n---\n\nBody.\n".encode()
    root, count, err = _malformed_run(tmp_path, capsys, "v", data)
    assert count == 1 and len(_warn_lines(err)) == 1, err
    assert _wrapper(root, ".claude", "v") == SENTINEL


# @covers FR-0019:AC-5
def test_unknown_key_warns_once_is_ignored_and_wrappers_are_generated(tmp_path, capsys):
    data = (FIXTURES / "wellformed" / "unknown-key.md").read_bytes()
    root = tmp_path / "t"
    assert _gen(bs, root, {"good": GOOD, "unknown-key": data}) == 2
    warns = _warn_lines(capsys.readouterr().err)
    assert len(warns) == 1 and "unknown-key.md" in warns[0] and "colour" in warns[0]
    for harness in HARNESSES:
        w = _wrapper(root, harness, "unknown-key")
        assert b"colour" not in w and b"blue" not in w
        fm, _ = _split_wrapper(w)
        assert fm == [
            b'description: "Synthetic command with a stray key."',
            b'argument-hint: "FR-XXXX"',
        ]


# @covers FR-0019:AC-5
def test_exit_code_is_unchanged_with_a_malformed_and_an_unknown_key_source(
    tmp_path, monkeypatch, capsys
):
    """End to end through `main()`: `--upgrade --yes` over a fake hub whose
    template carries one malformed and one unknown-key source finishes
    normally (no SystemExit), exactly as a clean upgrade does."""
    root = tmp_path / "hub"
    _patch_roots(bs, root, monkeypatch)
    tpl = root / "template"
    _write(tpl / "AGENTS.md", "# AGENTS.md\n\n## Universal rules\n")
    _write(tpl / COMMANDS_REL / "good.md", GOOD)
    _write(
        tpl / COMMANDS_REL / "bad.md",
        (FIXTURES / "malformed" / "no-closing.md").read_bytes(),
    )
    _write(
        tpl / COMMANDS_REL / "odd.md",
        (FIXTURES / "wellformed" / "unknown-key.md").read_bytes(),
    )
    (root / "profiles").mkdir(parents=True)
    _write(root / "hub" / "projects.yaml", "projects: []\n")
    project = tmp_path / "proj-f19"
    shutil.copytree(tpl, project)
    _write(project / ".agent-team" / "profiles.yaml", "profiles: []\n")
    monkeypatch.setattr(
        sys, "argv", ["bootstrap.py", "--upgrade", str(project), "--yes"]
    )
    try:
        bs.main()
        code = 0
    except SystemExit as e:  # pragma: no cover - the failure path
        code = e.code
    assert code in (0, None)
    out = capsys.readouterr()
    warns = _warn_lines(out.err)
    assert sum("bad.md" in w for w in warns) == 1
    assert sum("odd.md" in w for w in warns) == 1
    assert "Commands: 2 regenerated" in out.out
    assert not (project / ".claude" / "commands" / "bad.md").exists()


# ---- adversarial shapes the ACs do not name ---------------------------------


# @covers FR-0019:AC-5
def test_empty_block_is_refused_not_silently_leaked(tmp_path, capsys):
    """`---\\n---\\n` is not a mapping. The implementation refuses it (it
    reports "no closing '---'" because the closing-fence search starts after
    the opening fence's newline -- the cause wording is off, the outcome is
    sane). Nothing written, nothing counted."""
    data = (FIXTURES / "adversarial" / "empty-block.md").read_bytes()
    root, count, err = _malformed_run(tmp_path, capsys, "empty-block", data)
    assert count == 1 and len(_warn_lines(err)) == 1
    assert _wrapper(root, ".claude", "empty-block") == SENTINEL


# @covers FR-0019:AC-5
def test_empty_block_followed_by_a_body_rule_is_still_refused(tmp_path, capsys):
    data = b"---\n---\n\nIntro.\n\n---\n\nAfter the rule.\n"
    root, count, err = _malformed_run(tmp_path, capsys, "empty2", data)
    assert count == 1 and len(_warn_lines(err)) == 1
    assert _wrapper(root, ".claude", "empty2") == SENTINEL


# @covers FR-0019:AC-3
def test_a_later_rule_in_the_body_is_body_not_a_fence(tmp_path, capsys):
    data = (FIXTURES / "wellformed" / "later-fence.md").read_bytes()
    assert _gen(bs, tmp_path, {"later-fence": data}) == 1
    assert _warn_lines(capsys.readouterr().err) == []
    _, rest = _split_wrapper(_wrapper(tmp_path, ".claude", "later-fence"))
    assert rest.endswith(b"Intro for $ARGUMENTS.\n\n---\n\nAfter the rule.\n")


# @covers FR-0019:AC-3
def test_crlf_source_renders_exactly_as_its_lf_twin(tmp_path, capsys):
    lf = _fr_sources()["developer"]
    crlf = lf.replace(b"\n", b"\r\n")
    _gen(bs, tmp_path / "lf", {"developer": lf})
    _gen(bs, tmp_path / "crlf", {"developer": crlf})
    assert _warn_lines(capsys.readouterr().err) == []
    for harness in HARNESSES:
        got = _wrapper(tmp_path / "crlf", harness, "developer")
        assert b"\r" not in got
        assert got == _wrapper(tmp_path / "lf", harness, "developer")


# @covers FR-0019:AC-3
def test_bom_before_the_fence_falls_back_and_leaks_the_block(tmp_path, capsys):
    """A UTF-8 BOM means the source does not start with `---`, so AC-3's
    no-block fallback applies literally: generic description, whole file
    (block included) as the body, no warning. Pinned as observed; reported as
    a FINDING (silent, AC-conformant, but not what an author intends)."""
    data = b"\xef\xbb\xbf" + _fr_sources()["architect"]
    assert _gen(bs, tmp_path, {"architect": data}) == 1
    assert _warn_lines(capsys.readouterr().err) == []
    fm, rest = _split_wrapper(_wrapper(tmp_path, ".claude", "architect"))
    assert fm == [b'description: "Run the architect command."']
    assert b'---\ndescription: "Operate as the Architect.' in rest


# @covers FR-0019:AC-5
def test_folded_continuation_line_is_accepted_as_one_line(tmp_path, capsys):
    """A plain scalar continued on an indented second line parses to a
    single-line string, so AC-5's "not a single-line string" does not fire.
    Pinned as observed; reported as a FINDING against AC-2's one-line shape."""
    data = b"---\ndescription: first half\n  second half\n---\n\nBody.\n"
    assert _gen(bs, tmp_path, {"folded": data}) == 1
    assert _warn_lines(capsys.readouterr().err) == []
    fm, _ = _split_wrapper(_wrapper(tmp_path, ".claude", "folded"))
    assert fm == [b'description: "first half second half"']


# @covers FR-0019:AC-5
def test_block_closed_at_end_of_file_without_newline_is_refused(tmp_path, capsys):
    data = b'---\ndescription: "Only a block."\n---'
    _, count, err = _malformed_run(tmp_path, capsys, "eof", data)
    assert count == 1 and len(_warn_lines(err)) == 1
    assert "closing" in _warn_lines(err)[0]


# ---------------------------------------------------------------------------
# AC-6: existing behaviour preserved
# ---------------------------------------------------------------------------


def _changed(old: str, new: str, *paths: str) -> list[str]:
    """Paths FR-0019 changed between two fixed commits. Never the working
    tree or HEAD: a later FR's legitimate edit must not turn this red."""
    for ref in (old, new):
        if _git_show(ref, "scripts/bootstrap.py") is None:
            pytest.skip(f"{ref[:7]} not reachable")
    proc = subprocess.run(
        ["git", "-C", str(HUB_ROOT), "diff", "--name-only", old, new, "--", *paths],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(proc.stdout.split())


# @covers FR-0019:AC-6
def test_hub_index_and_fr0001_tests_are_unedited():
    """Across all of FR-0019 (implementation and cascade)."""
    assert (
        _changed(
            BASE_REF,
            CASCADE_REF,
            "scripts/hub-index.py",
            "tests/unit/scripts/test_bootstrap_profiles.py",
        )
        == []
    )


# @covers FR-0019:AC-6
def test_only_the_two_dec0016_cascade_template_test_files_changed():
    # The implementation touched no template test ...
    assert _changed(BASE_REF, FR_REF, "template/tests") == []
    # ... and the cascade touched exactly DEC-0016's two files.
    assert _changed(FR_REF, CASCADE_REF, "template/tests") == [
        "template/tests/unit/scripts/test_dispatch_gates.py",
        "template/tests/unit/scripts/test_headless_conduct.py",
    ]


def _upgrade_output(
    mod, root: Path, sources: dict[str, bytes], monkeypatch, capsys
) -> str:
    _patch_roots(mod, root, monkeypatch)
    tpl = root / "template"
    _write(tpl / "AGENTS.md", "# AGENTS.md\n\n## Universal rules\n")
    _write(tpl / ".agent-team" / "roles" / "reviewer.md", "# Role\n")
    for name, data in sources.items():
        _write(tpl / COMMANDS_REL / f"{name}.md", data)
    (root / "profiles").mkdir(parents=True)
    _write(root / "hub" / "projects.yaml", "projects: []\n")
    project = root / "proj-f19"
    shutil.copytree(tpl, project)
    _write(project / ".agent-team" / "profiles.yaml", "profiles: []\n")
    # One template file the project lacks, and one it has stale.
    _write(tpl / ".agent-team" / "roles" / "architect.md", "# Architect\n")
    _write(tpl / ".agent-team" / "roles" / "reviewer.md", "# Role v2\n")
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("prompted"))
    capsys.readouterr()
    mod.run_upgrade(project, auto_yes=True)
    cap = capsys.readouterr()
    return (cap.out + cap.err).replace(str(root), "<ROOT>").replace("\\", "/")


# @covers FR-0019:AC-6
def test_upgrade_output_is_identical_to_base_for_equivalent_sources(
    base, fr, tmp_path, monkeypatch, capsys
):
    names = ("architect", "developer", "docs", "gate-review")
    base_src = {n: _base_or_skip(f"template/{COMMANDS_REL}/{n}.md") for n in names}
    head_src = {n: _fr_or_skip(f"template/{COMMANDS_REL}/{n}.md") for n in names}
    head_out = _upgrade_output(fr, tmp_path / "h", head_src, monkeypatch, capsys)
    base_out = _upgrade_output(base, tmp_path / "b", base_src, monkeypatch, capsys)
    # The synced command sources differ (the block), nothing else.
    assert head_out == base_out
    assert "Updated:  1 file(s)" in head_out and "Added:    1 file(s)" in head_out
    assert "Commands: 4 regenerated" in head_out
