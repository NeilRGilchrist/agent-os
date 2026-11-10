"""Reviewer tests for FR-0008 — the indexer half: an FR declares `gates:` in
frontmatter, `index-specs.py` validates the shape and renders a `Gates`
column, the FR template documents the key (AC-1), and an FR with no `gates:`
key is byte-identical to the pre-FR indexer's output apart from that column
(AC-13).

Harness: the same shape as `test_index_specs_versioning.py` / `test_spec_query.py`
— the hyphenated module is loaded by path for the pure parse checks, and the CLI
is driven through `subprocess` against a self-contained temporary repo (scripts
copied in, synthetic FRs written under `specs/`). The AC-13 bite check loads the
*pre-FR* indexer from `git show 706ba9d:template/scripts/index-specs.py` and skips
when that commit is not reachable (i.e. outside the hub checkout).

Coverage annotations are written `# covers hub-tooling FR-0008:AC-N` rather than
the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0008 exists and `deploy-gate.py` would fail
with "@covers references unknown FR" (IDEA-0061).

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_SPECS_DIR = _TEMPLATE_DIR / "specs"
_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "gates" / "frontmatter"
_FR_TEMPLATE = _SPECS_DIR / "_template" / "FR-XXXX-template.md"
_COPY_SCRIPTS = (
    "index-specs.py",
    "deploy-gate.py",
    "spec_footprint.py",
    "spec_query.py",
)

# The last commit before FR-0008 (wave 1's merge point). Backward-compat
# baselines pin a commit, never a branch name.
_PRE_FR_REF = "706ba9d"

FR_HEADER = "| ID | Title | Status | Ver | Lifecycle | Owner | Tags | Owns | Reads | Depends on | Derived from | Updated | Gates |"
FR_SEPARATOR = "|----|-------|--------|-----|-----------|-------|------|------|-------|------------|--------------|---------|-------|"


def _load_index_specs(name: str = "index_specs_under_test_fr0008_gates"):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / "index-specs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


index_specs = _load_index_specs()


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _build_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    for name in _COPY_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / name, tmp_path / "scripts" / name)
    specs = tmp_path / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = specs / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return tmp_path


def _run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _index_text(repo: Path) -> str:
    return (repo / "specs" / "INDEX.md").read_text(encoding="utf-8")


def _parse_fixture(tmp_path: Path, name: str):
    """(fr, errors) for one fixture file parsed in a throwaway repo."""
    repo = _build_repo(tmp_path, {name: _fixture(name)})
    return index_specs.parse_fr(repo / "specs" / name)


# ---------------------------------------------------------------------------
# AC-1: the closed key set and vocabularies parse
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-1
def test_valid_two_gate_fr_parses_to_a_tuple_of_records_in_declaration_order(tmp_path):
    """Happy path: the AC's exact shape — two gates, both vocabularies, both
    `after` values — becomes `FR.gates` as a tuple of four-key mappings."""
    fr, errors = _parse_fixture(tmp_path, "FR-0200-valid-two-gates.md")
    assert errors == []
    assert isinstance(fr.gates, tuple)
    assert [g["id"] for g in fr.gates] == ["design-review", "tier-map-review"]
    assert fr.gates[0] == {
        "id": "design-review",
        "after": "dev",
        "reviewer": "human",
        "scope": "The human signs off the rendered screens before the Reviewer runs.",
    }
    assert fr.gates[1]["after"] == "rev" and fr.gates[1]["reviewer"] == "architect"
    assert set(fr.gates[0]) == index_specs.GATE_ALLOWED_KEYS


# covers hub-tooling FR-0008:AC-1
# covers hub-tooling FR-0008:AC-13
@pytest.mark.parametrize(
    "name",
    ["FR-0201-no-gates-key.md", "FR-0202-explicit-null.md", "FR-0203-empty-list.md"],
)
def test_absent_null_and_empty_all_mean_no_gates_with_no_error(tmp_path, name):
    """`gates` defaults to `()`: an FR written before the key existed, one that
    spells it `null` the way the template pre-fills scalars, and one that spells
    it `[]` are indistinguishable and none of them is an error."""
    fr, errors = _parse_fixture(tmp_path, name)
    assert errors == []
    assert fr.gates == ()


# ---------------------------------------------------------------------------
# AC-1: every error class, named and refused
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-1
@pytest.mark.parametrize(
    "name, needle",
    [
        ("FR-0210-not-a-list.md", "gates must be a list"),
        ("FR-0211-entry-not-a-mapping.md", "must be a mapping"),
        ("FR-0212-missing-key.md", "exactly the keys"),
        ("FR-0213-unknown-key.md", "exactly the keys"),
        ("FR-0214-bad-id.md", ".id "),
        ("FR-0215-duplicate-id.md", "duplicate gate id"),
        ("FR-0216-bad-after.md", ".after "),
        ("FR-0217-bad-reviewer.md", ".reviewer "),
        ("FR-0218-empty-scope.md", ".scope must be a non-empty"),
        ("FR-0219-multiline-scope.md", ".scope must be a non-empty"),
    ],
)
def test_every_malformed_gates_shape_is_one_error_naming_the_fr_and_the_gate(
    tmp_path, name, needle
):
    """Adversarial: one fixture per error class AC-1 enumerates. Each is an
    error (not a warning, not a crash), each names the FR file, and each names
    the offending gate — by id where the id parsed, by position where it did
    not."""
    fr, errors = _parse_fixture(tmp_path, name)
    assert len(errors) == 1, errors
    (err,) = errors
    assert err.startswith(name), err
    assert needle in err, err
    # Identified either by gate id or by its position in the list.
    assert (
        ("design-review" in err) or ("gates[0]" in err) or ("Design_Review" in err)
    ), err
    # A malformed gate never becomes a parsed record.
    assert fr is None or fr.gates == ()


# covers hub-tooling FR-0008:AC-1
@pytest.mark.parametrize(
    "name",
    [
        "FR-0210-not-a-list.md",
        "FR-0211-entry-not-a-mapping.md",
        "FR-0212-missing-key.md",
        "FR-0213-unknown-key.md",
        "FR-0214-bad-id.md",
        "FR-0215-duplicate-id.md",
        "FR-0216-bad-after.md",
        "FR-0217-bad-reviewer.md",
        "FR-0218-empty-scope.md",
        "FR-0219-multiline-scope.md",
    ],
)
def test_validate_mode_refuses_a_malformed_gates_the_way_it_refuses_other_frontmatter(
    tmp_path, name
):
    """Adversarial, at the CLI: `--validate` must exit 1 and print the error on
    stderr, exactly as it does for any other malformed frontmatter — not warn,
    not pass silently."""
    repo = _build_repo(tmp_path, {name: _fixture(name)})
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert name in proc.stderr


# covers hub-tooling FR-0008:AC-1
def test_a_valid_two_gate_fr_validates_clean_at_the_cli(tmp_path):
    repo = _build_repo(
        tmp_path, {"FR-0200-valid-two-gates.md": _fixture("FR-0200-valid-two-gates.md")}
    )
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "FR-0200-valid-two-gates.md" not in proc.stderr


# covers hub-tooling FR-0008:AC-1
def test_gate_id_pattern_boundaries(tmp_path):
    """Adversarial on the slug itself: the pattern is anchored, lower-case,
    must start with a letter, and is 2..40 characters."""
    pat = index_specs.GATE_ID_PATTERN
    assert pat.match("ab") and pat.match("a" + "b" * 39)
    assert not pat.match("a")  # one character is too short
    assert not pat.match("a" + "b" * 40)  # 41 is too long
    assert not pat.match("1st-gate")  # must start with a letter
    assert not pat.match("Design-Review")  # no upper case
    assert not pat.match("design_review")  # no underscore
    assert not pat.match("design review")  # no space


# ---------------------------------------------------------------------------
# AC-1: INDEX.md renders the Gates column
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-1
def test_index_renders_the_gates_column_for_gated_and_gate_free_frs(tmp_path):
    repo = _build_repo(
        tmp_path,
        {
            "FR-0200-valid-two-gates.md": _fixture("FR-0200-valid-two-gates.md"),
            "FR-0201-no-gates-key.md": _fixture("FR-0201-no-gates-key.md"),
        },
    )
    assert _run(repo, "index-specs.py").returncode == 0
    lines = _index_text(repo).splitlines()
    assert lines[4] == FR_HEADER
    assert lines[5] == FR_SEPARATOR
    rows = {
        line.split("|")[1].strip(): line for line in lines if line.startswith("| [FR-")
    }
    gated = rows["[FR-0200](FR-0200-valid-two-gates.md)"]
    assert gated.rstrip().endswith(
        "| `design-review:dev:human`, `tier-map-review:rev:architect` |"
    )
    assert rows["[FR-0201](FR-0201-no-gates-key.md)"].rstrip().endswith("| — |")


# covers hub-tooling FR-0008:AC-1
def test_fmt_gates_is_the_documented_join_and_the_em_dash_default():
    assert index_specs._fmt_gates(()) == "—"
    one = ({"id": "g", "after": "dev", "reviewer": "human", "scope": "s"},)
    assert index_specs._fmt_gates(one) == "`g:dev:human`"
    two = one + ({"id": "h", "after": "rev", "reviewer": "architect", "scope": "s"},)
    assert index_specs._fmt_gates(two) == "`g:dev:human`, `h:rev:architect`"


# covers hub-tooling FR-0008:AC-1
def test_the_gates_column_is_the_last_column_and_only_the_fr_table_gains_it(tmp_path):
    """Adversarial: the column belongs to the FR table alone. Every FR row must
    carry exactly one more cell than the pre-FR-0008 row, and no other table's
    header may grow."""
    repo = _build_repo(
        tmp_path,
        {
            "FR-0200-valid-two-gates.md": _fixture("FR-0200-valid-two-gates.md"),
            "FR-0201-no-gates-key.md": _fixture("FR-0201-no-gates-key.md"),
        },
    )
    assert _run(repo, "index-specs.py").returncode == 0
    lines = _index_text(repo).splitlines()
    widths = {len(line.split("|")) for line in lines if line.startswith("| [FR-")} | {
        len(FR_HEADER.split("|")),
        len(FR_SEPARATOR.split("|")),
    }
    assert len(widths) == 1, widths
    for line in lines:
        if line.startswith("| ID |") and line != FR_HEADER:
            assert "Gates" not in line, line


# ---------------------------------------------------------------------------
# AC-1: the FR template documents the key
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0008:AC-1
def test_fr_template_documents_gates_with_a_comment_and_an_example():
    text = _FR_TEMPLATE.read_text(encoding="utf-8")
    assert "gates:" in text
    line = next(line for line in text.splitlines() if line.startswith("gates:"))
    assert "#" in line, "the `gates:` key carries a one-line comment"
    assert "FR-0008" in line or "gate" in line.lower()
    # The example sits in the comment; the template's own `gates:` value must
    # stay the empty default, so a copied template declares no live gate. The
    # template's id is the literal placeholder, so substitute a real one first.
    assert line.split("#")[0].strip() == "gates: []"
    for token in (
        "id",
        "after",
        "reviewer",
        "scope",
        "dev",
        "rev",
        "human",
        "architect",
    ):
        assert token in line, token
    assert "specs/_gates/" in line
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "FR-0300-template-copy.md"
        copy.write_text(
            text.replace("id: FR-XXXX", "id: FR-0300"), encoding="utf-8", newline="\n"
        )
        fr, errors = index_specs.parse_fr(copy)
    assert errors == [], errors
    assert fr is not None and fr.gates == ()


# covers hub-tooling FR-0008:AC-1
def test_specs_readme_documents_the_gates_directory():
    """AC-2's `_gates/` home is documented where an agent will look for it."""
    readme = (_SPECS_DIR / "README.md").read_text(encoding="utf-8")
    assert "_gates/" in readme
    assert "specs/_gates/" in readme


# ---------------------------------------------------------------------------
# AC-13: a gate-free tree is the pre-FR rendering plus one `—` column
# ---------------------------------------------------------------------------


def _pre_fr_indexer(tmp_path: Path) -> Path | None:
    """`index-specs.py` as of `_PRE_FR_REF`, or None outside the hub checkout."""
    proc = subprocess.run(
        ["git", "show", f"{_PRE_FR_REF}:template/scripts/index-specs.py"],
        cwd=str(_TEMPLATE_DIR),
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return None
    out = tmp_path / "pre-fr-index-specs.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(proc.stdout)
    return out


def _strip_gates_column(data: bytes) -> bytes:
    """INDEX.md bytes with the FR table's trailing `Gates` cell removed.

    The same normalisation DEC-0012 item 2(b)/(c) added to the FR-0004 /
    FR-0005 baselines, so AC-13's "identical apart from the new column" is
    asserted as literally as those ACs' own backward-compat tests.
    """
    lines = data.split(b"\n")
    header = FR_HEADER.encode("utf-8")
    if header not in lines:
        return data
    i = lines.index(header)
    while i < len(lines) and lines[i].startswith(b"|"):
        cells = lines[i].split(b"|")
        assert len(cells) >= 3 and cells[-1] == b"", lines[i]
        before = len(cells)
        del cells[-2]
        assert len(cells) == before - 1, lines[i]
        lines[i] = b"|".join(cells)
        i += 1
    return b"\n".join(lines)


def _run_pre_and_post(tmp_path: Path, files: dict[str, str], *args: str):
    pre_script = _pre_fr_indexer(tmp_path)
    if pre_script is None:
        pytest.skip(
            f"pre-FR commit {_PRE_FR_REF} not reachable (not running inside the hub checkout)"
        )
    new = _build_repo(tmp_path / "new", files)
    old = _build_repo(tmp_path / "old", files)
    shutil.copy(pre_script, old / "scripts" / "index-specs.py")
    return (
        _run(old, "index-specs.py", *args),
        _run(new, "index-specs.py", *args),
        old,
        new,
    )


# covers hub-tooling FR-0008:AC-13
def test_gate_free_tree_is_identical_to_the_pre_fr_indexer_apart_from_the_column(
    tmp_path,
):
    """AC-13's own words, against the pre-FR-0008 indexer loaded from
    `_PRE_FR_REF`: exit code, stdout, stderr identical, and INDEX.md identical
    once the one new column is subtracted."""
    files = {
        "FR-0201-no-gates-key.md": _fixture("FR-0201-no-gates-key.md"),
        "FR-0202-explicit-null.md": _fixture("FR-0202-explicit-null.md"),
    }
    old_proc, new_proc, old, new = _run_pre_and_post(tmp_path, files)
    assert old_proc.returncode == 0, old_proc.stderr
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode,
        new_proc.stdout,
        new_proc.stderr,
    )
    old_bytes = (old / "specs" / "INDEX.md").read_bytes().replace(b"\r\n", b"\n")
    assert old_bytes == _strip_gates_column((new / "specs" / "INDEX.md").read_bytes())


# covers hub-tooling FR-0008:AC-13
def test_gate_free_tree_validate_mode_is_identical_to_the_pre_fr_indexer(tmp_path):
    files = {"FR-0201-no-gates-key.md": _fixture("FR-0201-no-gates-key.md")}
    old_proc, new_proc, _, _ = _run_pre_and_post(tmp_path, files, "--validate")
    assert (old_proc.returncode, old_proc.stdout, old_proc.stderr) == (
        new_proc.returncode,
        new_proc.stdout,
        new_proc.stderr,
    )


# covers hub-tooling FR-0008:AC-13
def test_bite_the_pre_fr_indexer_does_not_know_the_gates_key_at_all(tmp_path):
    """Bite check: these pins must fail against the pre-FR indexer. It renders
    no `Gates` column and silently ignores a malformed `gates:` — so both AC-1
    assertions above are genuinely about this FR's code, not about something
    that was already true."""
    pre_script = _pre_fr_indexer(tmp_path)
    if pre_script is None:
        pytest.skip(f"pre-FR commit {_PRE_FR_REF} not reachable")
    repo = _build_repo(
        tmp_path / "old",
        {
            "FR-0200-valid-two-gates.md": _fixture("FR-0200-valid-two-gates.md"),
            "FR-0216-bad-after.md": _fixture("FR-0216-bad-after.md"),
        },
    )
    shutil.copy(pre_script, repo / "scripts" / "index-specs.py")
    proc = _run(repo, "index-specs.py", "--validate")
    assert proc.returncode == 0, "pre-FR indexer accepted the malformed gate"
    assert "FR-0216-bad-after.md" not in proc.stderr
    assert _run(repo, "index-specs.py").returncode == 0
    text = _index_text(repo)
    assert "Gates" not in text
    assert "design-review:dev:human" not in text
