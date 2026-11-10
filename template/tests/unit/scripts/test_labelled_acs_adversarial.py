"""Reviewer's adversarial tests for hub-tooling FR-0027 (labelled ACs).

They complement `test_labelled_acs.py` where its coverage is thin:
- label edge cases the Terms allow or forbid (`)`, `:`, `**`, backticks, a
  `):**` in the rest, whitespace-only labels, tabs, trailing whitespace, CRLF);
- the label not leaking from a labelled AC into the plain AC that follows it;
- moving a ratified AC between the plain and labelled forms, end to end;
- the gate on an empty label, on an indented labelled AC at check 3, and on
  gate/indexer agreement for column-0 bullets;
- byte-identity with the base ref on a tree of *additional* near-miss shapes
  that sit one character away from the labelled pattern;
- the `solution_space.fixed` lines (no new failure/warning class, untouched
  `metrics_log.py`, unchanged `ac-format` text, single pattern definitions);
- the hub's FR-0001 AC-12 annotation sitting on a test that builds both
  fixture shapes.

Same conventions as `test_labelled_acs.py`: subprocess copies of the team
scripts in `tmp_path`, the base ref loaded with `git show` (skips where hub
history is unreachable), synthetic fixtures only, and ride-along annotations
`# covers hub-tooling FR-0027:AC-N`.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_COPY_SCRIPTS = (
    "deploy-gate.py",
    "index-specs.py",
    "spec_footprint.py",
    "spec_query.py",
    "metrics_log.py",
)
_SIBLING_MODULES = (
    "index_specs",
    "spec_footprint",
    "spec_query",
    "metrics_log",
    "dispatch",
)
_METRICS_ENV = (
    "METRICS_LOG_DISABLED",
    "METRICS_INVOKED_BY",
    "METRICS_GATE_RECORD_ID",
    "METRICS_GATE_OVERRIDE",
    "DISPATCH_RUN_ID",
)
_BASE_REF = "b803216"
# Split so a bootstrapped project's gate never reads these as annotations.
_COVERS = "@" + "covers"
_UNEXPECTED = "contains AC references in unexpected format"
_HUB_FR0001 = "projects/hub-tooling/specs/FR-0001-profile-aware-upgrade.md"
_HUB_PROFILES_TEST = "tests/unit/scripts/test_bootstrap_profiles.py"


# ---------------------------------------------------------------------------
# Harness (self-contained; mirrors test_labelled_acs.py)
# ---------------------------------------------------------------------------


def _fr(fr_id: str, body: str, *, status: str = "ready", ac_state: str = "{}") -> str:
    return (
        "---\n"
        f"id: {fr_id}\n"
        f"title: Synthetic {fr_id}\n"
        f"status: {status}\n"
        "owner: architect\n"
        "depends_on: []\n"
        "tags: []\n"
        "owns: []\n"
        "reads: []\n"
        "derived_from: null\n"
        "pattern: null\n"
        f"ac_state: {ac_state}\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n"
        f"{body}"
    )


def _section(*lines: str) -> str:
    return "\n# Synthetic\n\n## Acceptance criteria\n\n" + "\n".join(lines) + "\n"


def _covers(*refs: str) -> dict[str, str]:
    return {"test_synthetic.py": "".join(f"# {_COVERS} {r}\n" for r in refs)}


def _git_show(ref: str, rel: str) -> bytes | None:
    hub = _TEMPLATE_DIR.parent
    probe = subprocess.run(
        ["git", "-C", str(hub), "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    proc = subprocess.run(
        ["git", "-C", str(hub), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _base_scripts() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name in _COPY_SCRIPTS:
        data = _git_show(_BASE_REF, f"template/scripts/{name}")
        if data is None:
            pytest.skip(f"hub history for {_BASE_REF} is not reachable")
        out[name] = data
    return out


def _build_repo(
    base: Path,
    specs: dict[str, str],
    *,
    tests: dict[str, str] | None = None,
    scripts: dict[str, bytes] | None = None,
) -> Path:
    (base / "scripts").mkdir(parents=True)
    for name in _COPY_SCRIPTS:
        if scripts is not None:
            (base / "scripts" / name).write_bytes(scripts[name])
        else:
            shutil.copy(_SCRIPTS_DIR / name, base / "scripts" / name)
    for folder, files in (("specs", specs), ("tests", tests or {})):
        (base / folder).mkdir(exist_ok=True)
        for rel, content in files.items():
            (base / folder / rel).write_bytes(content.encode("utf-8"))
    return base


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _METRICS_ENV}
    env["METRICS_PROJECT"] = "synthetic-project"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=_env(),
    )


def _records(repo: Path) -> list[dict]:
    d = repo / "specs" / "_metrics"
    if not d.exists():
        return []
    return [
        json.loads(ln)
        for f in sorted(d.glob("*.ndjson"))
        for ln in f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


@contextlib.contextmanager
def _isolated_imports(scripts_dir: Path) -> Iterator[None]:
    saved_modules = dict(sys.modules)
    saved_path = list(sys.path)
    for name in _SIBLING_MODULES:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path


def _load(path: Path, module_name: str):  # type: ignore[no-untyped-def]
    with _isolated_imports(path.parent):
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_CURRENT: dict[str, object] = {}


def _current(script: str):  # type: ignore[no-untyped-def]
    if script not in _CURRENT:
        name = "fr0027_adv_" + script.replace("-", "_").removesuffix(".py")
        _CURRENT[script] = _load(_SCRIPTS_DIR / script, name)
    return _CURRENT[script]


def _gate_acs(gate, path: Path) -> set[int]:  # type: ignore[no-untyped-def]
    fr = SimpleNamespace(id="FR-0000", status="ready", path=path)
    with contextlib.redirect_stderr(io.StringIO()):
        return gate._load_fr_summaries([fr])["FR-0000"].acs


# ---------------------------------------------------------------------------
# AC-1: label edge cases and form transitions
# ---------------------------------------------------------------------------

# (line, expected parse_acs text for AC-1) for shapes Terms calls labelled.
_LABELLED_EDGES = [
    ("- **AC-1 (a)b):** r", "(a)b) r"),  # `)` inside the label
    ("- **AC-1 (a:b):** r", "(a:b) r"),  # `:` inside the label
    ("- **AC-1 (a **b** c):** r", "(a **b** c) r"),  # bold markers inside
    ("- **AC-1 (`x):**`):** r", "(`x) `):** r"),  # L ends at the FIRST `):**`
    ("- **AC-1 (a):** b):** c", "(a) b):** c"),  # `):**` in the rest
    ("- **AC-1 ()):** r", "()) r"),  # label is a single `)`
    ("- **AC-1 ( ):** r", "( ) r"),  # whitespace-only label is non-empty
    ("-\t**AC-1\t(a):**\tr", "(a) r"),  # tabs throughout
    ("- **AC-1  (a):** r", "(a) r"),  # several spaces before `(`
    ("- **AC-1 (a):**   ", "(a)"),  # trailing whitespace, empty rest
    ("- **AC-1 (a):**", "(a)"),  # nothing after `:**`
]


# covers hub-tooling FR-0027:AC-1
@pytest.mark.parametrize(
    "line, expected",
    _LABELLED_EDGES,
    ids=[f"edge{i}" for i in range(len(_LABELLED_EDGES))],
)
def test_labelled_edge_shapes_parse_with_label_ending_at_first_close_colon_bold(
    line, expected
):
    idx = _current("index-specs.py")
    assert idx.parse_acs("## Acceptance criteria\n\n" + line + "\n") == {1: expected}


# Shapes one character away from a labelled bullet: none is an AC to the
# indexer, and none is a labelled bullet to the gate.
_ONE_OFF_SHAPES = [
    "- **AC-1(a):** r",  # no whitespace before `(`
    "- **AC-1 (a) :** r",  # space before the colon
    "- **AC-1 (a):* r",  # single closing star
    "- **AC-1 (a)::** r",  # extra colon
    "* **AC-1 (a):** r",  # `*` bullet, not `-`
    "-**AC-1 (a):** r",  # no whitespace after `-`
    "- ** AC-1 (a):** r",  # space inside the bold
    "- **AC-1 ():** r",  # empty label
    "- **AC- 1 (a):** r",  # space inside the number
    "- **AC-x (a):** r",  # no digits
]


# covers hub-tooling FR-0027:AC-1
@pytest.mark.parametrize("line", _ONE_OFF_SHAPES, ids=[f"oneoff{i}" for i in range(10)])
def test_one_off_shapes_are_not_labelled_bullets(line):
    idx = _current("index-specs.py")
    gate = _current("deploy-gate.py")
    assert idx.parse_acs("## Acceptance criteria\n\n" + line + "\n") == {}
    assert not idx.AC_LABELLED_LINE_PATTERN.match(line)
    assert not gate.AC_LABELLED_PATTERN.search(line)


# covers hub-tooling FR-0027:AC-1
def test_label_does_not_leak_into_the_next_plain_ac():
    idx = _current("index-specs.py")
    body = "## Acceptance criteria\n\n" + "\n".join(
        [
            "- **AC-1 (L):** one",
            "- **AC-2:** two",
            "- **AC-3 (M):**",
            "- **AC-4:**",
            "- **AC-5:** (looks) five",
            "- **AC-6 (N):** six",
        ]
    )
    assert idx.parse_acs(body) == {
        1: "(L) one",
        2: "two",
        3: "(M)",
        4: "",
        5: "(looks) five",
        6: "(N) six",
    }


# covers hub-tooling FR-0027:AC-1
def test_a_labelled_bullet_ends_a_multi_line_plain_ac_and_vice_versa():
    idx = _current("index-specs.py")
    body = "## Acceptance criteria\n\n" + "\n".join(
        [
            "- **AC-1:** one",
            "  cont one",
            "- **AC-2 (L):** two",
            "  cont two",
            "- **AC-3:** three",
        ]
    )
    assert idx.parse_acs(body) == {
        1: "one\n  cont one",
        2: "(L) two\n  cont two",
        3: "three",
    }


# covers hub-tooling FR-0027:AC-1
def test_crlf_text_parses_like_lf_text():
    idx = _current("index-specs.py")
    lf = "## Acceptance criteria\n\n- **AC-1 (L):** R\n  cont\n- **AC-2:** x\n"
    assert idx.parse_acs(lf.replace("\n", "\r\n")) == idx.parse_acs(lf)
    assert idx.parse_acs(lf) == {1: "(L) R\n  cont", 2: "x"}


# covers hub-tooling FR-0027:AC-1
def test_a_later_labelled_duplicate_wins_like_a_later_plain_duplicate():
    idx = _current("index-specs.py")
    head = "## Acceptance criteria\n\n- **AC-1:** first\n"
    assert idx.parse_acs(head + "- **AC-1 (x):** second\n") == {1: "(x) second"}
    assert idx.parse_acs(head + "- **AC-1:** (x) second\n") == {1: "(x) second"}


# covers hub-tooling FR-0027:AC-1
@pytest.mark.parametrize(
    "line",
    [
        "- **AC-1 (" + "x" * 200_000,
        "- **AC-1 (" + "):*" * 70_000,
        "- **AC-" + "1" * 200_000 + "x",
    ],
    ids=["no-close", "almost-close", "long-number"],
)
def test_pathological_lines_are_linear_not_catastrophic(line):
    idx = _current("index-specs.py")
    gate = _current("deploy-gate.py")
    start = time.perf_counter()
    assert idx.AC_LABELLED_LINE_PATTERN.match(line) is None
    assert list(gate.AC_LABELLED_PATTERN.finditer(line)) == []
    # Linear scans take well under a second here; catastrophic backtracking on
    # 200k characters would not finish.
    assert time.perf_counter() - start < 5.0


# ---------------------------------------------------------------------------
# AC-2: the hash is the plain rewrite's hash, end to end
# ---------------------------------------------------------------------------

# (labelled, plain rewrite) pairs whose hashes must be equal.
_HASH_PAIRS = [
    ("- **AC-1 (L):** R\n  cont", "- **AC-1:** (L) R\n  cont"),
    ("- **AC-1 (L):**\n  cont", "- **AC-1:** (L)\n  cont"),
    ("- **AC-1 (L):**", "- **AC-1:** (L)"),
    ("- **AC-1 (L):**   \n\n", "- **AC-1:** (L)   \n\n"),
    ("- **AC-1 ( L ):** R", "- **AC-1:** ( L ) R"),
    ("- **AC-1 (L):**\tR\t", "- **AC-1:** (L)\tR\t"),
    ("- **AC-1 (a):** b):** c", "- **AC-1:** (a) b):** c"),
    ("- **AC-1 (`--yes` is (safe)):** R", "- **AC-1:** (`--yes` is (safe)) R"),
]


# covers hub-tooling FR-0027:AC-2
@pytest.mark.parametrize(
    "labelled, plain", _HASH_PAIRS, ids=[f"pair{i}" for i in range(8)]
)
def test_labelled_and_plain_rewrite_hash_equal(labelled, plain):
    idx = _current("index-specs.py")
    a = idx.parse_acs("## Acceptance criteria\n\n" + labelled + "\n")
    b = idx.parse_acs("## Acceptance criteria\n\n" + plain + "\n")
    assert sorted(a) == sorted(b) == [1]
    assert idx.ac_hash(a[1]) == idx.ac_hash(b[1])
    # The text itself starts with the label and a single space when R is non-empty.
    assert a[1].startswith("(")


# covers hub-tooling FR-0027:AC-2
def test_ac_hash_and_normalize_are_unchanged_from_the_base_ref(tmp_path):
    scripts = _base_scripts()
    d = tmp_path / "base"
    d.mkdir()
    for name, data in scripts.items():
        (d / name).write_bytes(data)
    base = _load(d / "index-specs.py", "fr0027_adv_base_index_specs")
    idx = _current("index-specs.py")
    for sample in ("", "(L) R", "  (L)\n  R \t", "a  b\n\nc"):
        assert idx.normalize_ac_text(sample) == base.normalize_ac_text(sample)
        assert idx.ac_hash(sample) == base.ac_hash(sample)


# covers hub-tooling FR-0027:AC-2
@pytest.mark.parametrize("direction", ["plain-to-labelled", "labelled-to-plain"])
def test_moving_a_ratified_ac_between_forms_raises_no_drift(tmp_path, direction):
    plain = _section(
        "- **AC-1:** (the label) The rest.", "  More text.", "- **AC-2:** Two."
    )
    labelled = _section(
        "- **AC-1 (the label):** The rest.", "  More text.", "- **AC-2:** Two."
    )
    first, second = (
        (plain, labelled) if direction == "plain-to-labelled" else (labelled, plain)
    )
    repo = _build_repo(tmp_path / "r", {"FR-0100-a.md": _fr("FR-0100", first)})
    proc = _run(repo, "index-specs.py", "--ac-hashes", "FR-0100")
    assert proc.returncode == 0, proc.stderr
    hashes = dict(re.findall(r"^FR-0100 AC-(\d+): (\w+)$", proc.stdout, re.M))
    assert sorted(hashes) == ["1", "2"]
    state = (
        "{"
        + ", ".join(f"{n}: {{state: ratified, hash: {h}}}" for n, h in hashes.items())
        + "}"
    )
    (repo / "specs" / "FR-0100-a.md").write_bytes(
        _fr("FR-0100", second, ac_state=state).encode("utf-8")
    )
    proc = _run(repo, "index-specs.py")
    assert proc.returncode == 0, proc.stderr
    assert "ratified text changed" not in proc.stdout + proc.stderr
    assert "no matching" not in proc.stdout + proc.stderr
    assert "## AC ratification warnings" not in (repo / "specs" / "INDEX.md").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# AC-3: the gate on edge shapes
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0027:AC-3
def test_gate_does_not_detect_an_empty_label_and_still_warns_on_it(tmp_path):
    body = _section("- **AC-1:** plain.", "- **AC-2 ():** empty label.")
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", body)},
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2"),
    )
    proc = _run(repo, "deploy-gate.py", "--stage", "dev")
    assert proc.returncode == 1
    assert "  - @covers references FR-0100:AC-2 but that AC is not in the FR" in (
        proc.stderr.splitlines()
    )
    assert f"FR-0100-a.md {_UNEXPECTED}: AC-2 " in proc.stderr
    (rec,) = _records(repo)
    assert rec["failure_classes"] == ["covers-unknown-ac"]
    assert rec["warning_classes"] == ["ac-format"]


# covers hub-tooling FR-0027:AC-3
@pytest.mark.parametrize("indent", ["  ", "\t", "    "])
@pytest.mark.parametrize("stage", ["review", "full"])
def test_indented_labelled_ac_is_required_at_check3(tmp_path, indent, stage):
    body = _section("- **AC-1:** Plain one.", f"{indent}- **AC-2 (indented):** Two.")
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", body, status="merged")},
        tests=_covers("FR-0100:AC-1"),
    )
    proc = _run(repo, "deploy-gate.py", "--stage", stage)
    assert proc.returncode == 1
    assert "  - FR-0100 (merged): no @covers test for AC-2" in proc.stderr.splitlines()
    assert _UNEXPECTED not in proc.stderr
    (rec,) = _records(repo)
    assert rec["failure_classes"] == ["coverage-missing"]


# covers hub-tooling FR-0027:AC-3
def test_gate_and_indexer_agree_on_column_zero_bullets(tmp_path):
    gate = _current("deploy-gate.py")
    idx = _current("index-specs.py")
    lines = [line for line, _ in _LABELLED_EDGES] + _ONE_OFF_SHAPES
    for i, line in enumerate(lines):
        number = i + 1
        line = line.replace("AC-1", f"AC-{number}", 1)
        body = _section("- **AC-100:** anchor.", line)
        path = tmp_path / f"FR-0000-{i}.md"
        path.write_bytes(_fr("FR-0000", body).encode("utf-8"))
        assert _gate_acs(gate, path) == set(idx.parse_acs(body)), line


# covers hub-tooling FR-0027:AC-3
def test_tricky_labels_pass_check2_and_check3(tmp_path):
    body = _section(
        "- **AC-1 (a)b):** one.",
        "- **AC-2 (`x` **y** (z)):** two.",
        "- **AC-3 (c):** three):** more.",
    )
    repo = _build_repo(
        tmp_path / "r",
        {"FR-0100-a.md": _fr("FR-0100", body, status="merged")},
        tests=_covers("FR-0100:AC-1", "FR-0100:AC-2", "FR-0100:AC-3"),
    )
    proc = _run(repo, "deploy-gate.py", "--stage", "full")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _UNEXPECTED not in proc.stderr


# ---------------------------------------------------------------------------
# AC-4: one-off near misses stay byte-identical to the base ref
# ---------------------------------------------------------------------------


def _near_miss_tree() -> tuple[dict[str, str], dict[str, str]]:
    shapes = [
        s.replace("AC-1", f"AC-{n}", 1) for n, s in enumerate(_ONE_OFF_SHAPES, start=2)
    ]
    body = (
        "\n# Synthetic\n\n## Why\n\n- **AC-50 (a) :** outside the section.\n\n"
        "## Acceptance criteria\n\n- **AC-1:** plain one.\n" + "\n".join(shapes) + "\n"
    )
    specs = {"FR-0100-a.md": _fr("FR-0100", body, status="merged")}
    return specs, _covers("FR-0100:AC-1", "FR-0100:AC-3")


# covers hub-tooling FR-0027:AC-4
@pytest.mark.parametrize(
    "script, args",
    [
        ("index-specs.py", ()),
        ("index-specs.py", ("--validate",)),
        ("index-specs.py", ("--ac-hashes", "*")),
        ("index-specs.py", ("--slice", "FR-0100", "--json")),
        ("deploy-gate.py", ("--stage", "dev")),
        ("deploy-gate.py", ("--stage", "full")),
        ("deploy-gate.py", ("--status-only",)),
    ],
    ids=[
        "idx",
        "validate",
        "ac-hashes",
        "slice",
        "gate-dev",
        "gate-full",
        "status-only",
    ],
)
def test_one_off_near_misses_are_byte_identical_to_the_base_ref(tmp_path, script, args):
    specs, tests = _near_miss_tree()
    old = _build_repo(tmp_path / "old", specs, tests=tests, scripts=_base_scripts())
    new = _build_repo(tmp_path / "new", specs, tests=tests)
    p_old = _run(old, script, *args)
    p_new = _run(new, script, *args)

    def norm(text: str, repo: Path) -> str:
        return text.replace(str(repo), "<repo>").replace(repo.as_posix(), "<repo>")

    assert p_new.returncode == p_old.returncode
    assert norm(p_new.stdout, new) == norm(p_old.stdout, old)
    assert norm(p_new.stderr, new) == norm(p_old.stderr, old)
    for rel in ("specs/INDEX.md", "CODEOWNERS"):
        assert (new / rel).exists() == (old / rel).exists()
        if (new / rel).exists():
            assert (new / rel).read_bytes() == (old / rel).read_bytes()
    strip = ("ts", "record_id")
    assert [{k: v for k, v in r.items() if k not in strip} for r in _records(new)] == [
        {k: v for k, v in r.items() if k not in strip} for r in _records(old)
    ]
    if script == "deploy-gate.py":
        # The tree really is all near misses: AC-3 is unknown to the gate.
        assert "FR-0100:AC-3 but that AC is not in the FR" in p_new.stderr


# ---------------------------------------------------------------------------
# AC-5 / solution_space.fixed
# ---------------------------------------------------------------------------


def _gate_class_literals(source: str) -> set[str]:
    return set(re.findall(r"""report\.(?:fail|warn)\(\s*["']([a-z-]+)["']""", source))


# FR-0027's merge commit on hub `main` (PR #24). The class, ac-format text and
# metrics_log pins below check FR-0027's own diff only (the file at this commit
# against its first parent), as FR-0005's `test_spec_query.py` pins do, so a
# later FR that legitimately adds a class or edits metrics_log.py (FR-0026,
# FR-0018) does not turn them red.
_FR0027_MERGE_REF = "f1a17a7"


def _fr0027_diff_sides(rel: str) -> tuple[bytes, bytes]:
    """(file at FR-0027's first parent, file at FR-0027's merge commit).
    Skips where that history is unreachable (outside the hub, shallow clone)."""
    before = _git_show(f"{_FR0027_MERGE_REF}^1", rel)
    after = _git_show(_FR0027_MERGE_REF, rel)
    if before is None or after is None:
        pytest.skip(
            f"hub history for FR-0027's merge {_FR0027_MERGE_REF} is not reachable"
        )
    return before, after


# covers hub-tooling FR-0027:AC-5
def test_no_new_failure_or_warning_class_and_ac_format_text_unchanged():
    before, after = _fr0027_diff_sides("template/scripts/deploy-gate.py")
    old, new = before.decode("utf-8"), after.decode("utf-8")
    assert _gate_class_literals(new)  # the scrape is not vacuous
    assert _gate_class_literals(new) == _gate_class_literals(old)
    warn = re.compile(r"contains AC references in unexpected format.*?format\",", re.S)
    assert warn.search(new) and warn.search(new).group(0) == warn.search(old).group(0)


# covers hub-tooling FR-0027:AC-5
def test_metrics_log_is_untouched():
    before, after = _fr0027_diff_sides("template/scripts/metrics_log.py")
    assert after.replace(b"\r\n", b"\n") == before.replace(b"\r\n", b"\n")


# covers hub-tooling FR-0027:AC-5
def test_existing_patterns_are_assigned_once_and_never_rebound():
    for script, names in (
        ("deploy-gate.py", ("AC_HEADING_PATTERN", "AC_LOOSE_PATTERN")),
        ("index-specs.py", ("AC_LINE_PATTERN",)),
    ):
        tree = ast.parse((_SCRIPTS_DIR / script).read_text(encoding="utf-8"))
        for name in names:
            stores = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and node.id == name
                and isinstance(node.ctx, ast.Store)
            ]
            assert len(stores) == 1, (script, name)


# ---------------------------------------------------------------------------
# AC-6: the AC-12 annotation sits on a test that builds both fixture shapes
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0027:AC-6
def test_fr0001_ac12_annotation_sits_on_a_test_requesting_both_fixtures():
    hub = _TEMPLATE_DIR.parent
    path = hub / _HUB_PROFILES_TEST
    if not path.is_file() or not (hub / _HUB_FR0001).is_file():
        pytest.skip("not running inside the hub")
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = re.compile(r"^#\s*" + re.escape(_COVERS) + r"\s+FR-0001:AC-12\s*$")
    tree = ast.parse("\n".join(lines))
    tests = {
        node.lineno: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    hits = [i for i, ln in enumerate(lines, start=1) if marker.match(ln.strip())]
    assert hits, "no FR-0001:AC-12 annotation in the hub's bootstrap-profiles tests"
    for hit in hits:
        # The annotation block runs straight into a `def test_...` line.
        nxt = hit + 1
        while nxt <= len(lines) and lines[nxt - 1].lstrip().startswith(("#", "@")):
            nxt += 1
        func = tests.get(nxt) or next(
            (
                f
                for f in tests.values()
                if f.decorator_list and f.decorator_list[0].lineno == nxt
            ),
            None,
        )
        assert func is not None, f"annotation at line {hit} is not on a test"
        params = {a.arg for a in func.args.args}
        assert {"profiled", "unprofiled"} <= params, func.name


# covers hub-tooling FR-0027:AC-6
def test_every_fr0001_covers_in_hub_tests_names_ac1_to_ac12_in_any_source_file():
    hub = _TEMPLATE_DIR.parent
    if not (hub / _HUB_FR0001).is_file() or not (hub / "tests").is_dir():
        pytest.skip("not running inside the hub")
    gate = _current("deploy-gate.py")
    seen: set[int] = set()
    for path in (hub / "tests").rglob("*"):
        if not path.is_file() or path.suffix not in gate.SOURCE_EXTENSIONS:
            continue
        for m in gate.COVERS_PATTERN.finditer(
            path.read_text(encoding="utf-8", errors="ignore")
        ):
            if m.group(1) == "FR-0001":
                seen.add(int(m.group(2).removeprefix("AC-")))
    assert seen == set(range(1, 13))


# covers hub-tooling FR-0027:AC-6
@pytest.mark.parametrize(
    "name", ["test_labelled_acs.py", "test_labelled_acs_adversarial.py"]
)
def test_ride_along_test_files_carry_no_live_covers_annotation(name):
    """These files ride into every bootstrapped project, whose gate regex-scans
    tests/ with COVERS_PATTERN. Any literal match there (even inside a string)
    is a live annotation: it fails `covers-unknown-fr` in a project with no
    such FR, and `covers-unknown-ac` or false coverage in one that has it."""
    gate = _current("deploy-gate.py")
    text = (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")
    hits = [m.group(0) for m in gate.COVERS_PATTERN.finditer(text)]
    assert hits == [], f"{name} carries live annotations: {hits}"
