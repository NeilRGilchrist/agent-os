"""Reviewer tests for hub-tooling FR-0022 — the wave-1 craft rules become
default behaviour in the role commands; the Reviewer is asked for its own
`REVIEW.md`; the DEC template names the pinned-literal cascade cost.

Shape of the suite:

- **Content rules (AC-1..AC-5)** are standing rules over the live command
  sources. Each bullet is anchored on one operative phrase from the AC text
  (not on the maintainer's prose), that anchor must sit on exactly one line,
  and every other operative phrase the AC lists for the bullet must sit on
  that same line. Placement is checked against the `## Headless conduct`
  block and the neighbouring landmarks the AC names.
- **Bite:** the same detectors are run against the command sources at the
  base commit `9c12284` (loaded with `git show`) and must report gaps there.
- **"Unchanged" / "only these changed" checks** diff two fixed commits,
  `9c12284` (base) and `c2dc4f1` (the implementation), never HEAD or the
  working tree, so they cannot rot when later FRs edit the same files.

Coverage annotations are written `# covers hub-tooling FR-0022:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0022 exists. Inside such a project the two
fixed commits and the hub generator are absent and those tests skip; the
standing content rules still run.

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import difflib
import functools
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# template/tests/unit/scripts/ -> parents[3] == template/ (or the project root
# once this file rides along into a bootstrapped project).
_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_COMMANDS_DIR = _TEMPLATE_DIR / ".agent-team" / "commands"
_DEC_TEMPLATE = _TEMPLATE_DIR / "specs" / "_template" / "DEC-XXXX-template.md"
_HUB_ROOT = _TEMPLATE_DIR.parent
_BOOTSTRAP = _HUB_ROOT / "scripts" / "bootstrap.py"

# Immutable commits: the base FR-0022 branched from, and the commit that
# carries AC-1..AC-5 and AC-7 (AC-6 landed in b1a4864, its parent).
_BASE_REF = "9c1228405f4caaac9c48d5d9d4fc6dc3607289e2"
_IMPL_REF = "c2dc4f17a73af643713eed005d4a94a9c3dedafa"

_OWNED_COMMANDS = ("reviewer", "architect", "orchestrator", "developer")
_CONDUCT = ("developer", "reviewer", "maintainer", "reviewer-backfill", "orchestrator")
_HEADING = "## Headless conduct"

# Per AC: bullet -> (anchor, other operative phrases). The anchor is itself an
# AC phrase; all phrases of one bullet must share the anchor's line.
_RULES: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "AC-1": {
        "a": ("only its required arguments", ("real entry point",)),
        "b": (
            "built to fail",
            ("run it once for real", "`## FINDINGS`", "never a silent stub"),
        ),
        "c": ("second module", ("fail against",)),
        "d": ("`inspect.signature`", ("compiled `.exe`", "`.bat`")),
        "e": ("`core.longpaths`", ("short path", "bare repo", "`git remote add`")),
        "f": ("explicit parameter value", ("prefix", "default")),
        "g": (
            "floor subset",
            (
                "stated exactly once",
                "near-miss",
                "member shape",
                "clause found",
                "pinned as literals",
            ),
        ),
        "h": ("even when unit coverage is complete", ()),
    },
    "AC-3": {
        "a": ("test specification", ("double", "drive")),
        "b": ("exact-equality pins", ("pre-write the DEC", "test ids")),
        "c": ("isolation seam", ()),
        "d": ("blast radius", ("`owns:`",)),
        "e": ("live for the first time", ()),
        "f": ("same commit", ()),
        "g": ("branch literal", ()),
        "h": ("`index-specs.py --validate`", ()),
        "i": ("one `revises` target", ("two DECs",)),
    },
    "AC-4": {
        "a": ("range of free DEC numbers", ("non-overlapping",)),
        "b": ("at cycle 2", ()),
        "c": ("no discretion", ()),
        "d": ("3-4x", ()),
        "e": ("explicit test-id", ()),
        "f": ("ratified by the merge", ("same commit", "explicit act")),
    },
    "AC-5": {
        "a": ("your own verification", ()),
        "b": ("stated default", ()),
        "c": ("earlier FR's test", ("escalate",)),
    },
}
_FILE_FOR = {
    "AC-1": "reviewer",
    "AC-3": "architect",
    "AC-4": "orchestrator",
    "AC-5": "developer",
}
# Landmarks: (after, before). The section must lie strictly between them.
_PLACEMENT = {
    "AC-1": (None, "When all tests pass:"),
    "AC-3": (None, "Reminder: when in doubt"),
    "AC-4": ("**Phase 4: Synthesis**", "**Hard limits:**"),
    "AC-5": (None, None),
}

# FR-0012's phrases confined to the conduct sources.
_LIVE_DATA_PHRASES = (
    "asserts existence and well-formedness",
    "never a mutable field",
    "status, class, count, or SHA",
    "within the hour",
)
_NEVER_END = "never end your turn with a question"

# AC-2.
_DISPATCHER_ANCHOR = "If a dispatcher is configured**: your final assistant message"
_KEPT_PREFIX = (
    "   - **If a dispatcher is configured**: your final assistant message **is** "
    "the verdict of record. Open it with a `## Approve` heading (or "
    "`## Request changes`) — that heading is what the dispatcher reads as the "
    "verdict — and confirm in it: every AC has `@covers`, adversarial tests are "
    "present, deploy gate is green. The dispatcher posts that message to the PR "
    "as the review"
)
_KEPT_AC8 = (
    "do not set a GitHub approval state",
    "authored by the same account",
    "GitHub does not permit `--approve` or `--request-changes`",
    "falls back to posting your verdict as a comment",
)
_NEW_CLAUSES = (
    "per-AC findings",
    "`file:line`",
    "`## FINDINGS`",
    "`## ESCALATION`",
    "`REVIEW.md` at the worktree root",
    "stage it",
    "on either verdict",
    "keeps a staged or committed `REVIEW.md` byte-for-byte",
    "synthesises one from your final message only when you wrote none",
    "not post the review yourself",
)
_RETIRED = (
    "records it on your branch as `REVIEW.md`",
    "do not write `REVIEW.md`",
)
_DISPATCHER_FORBIDDEN = ("git commit", "review state on the PR")

# AC-6: the two sentences, as the AC words them.
_AC6_SENTENCES = (
    (
        "If this decision changes a vocabulary, a schema or a grammar that a test "
        "pins as a literal, name each such test by id here and the command that "
        "backfills it."
    ),
    (
        "A spec commit that widens a pinned set turns the verification suite red on "
        "the base branch from the moment it lands; the round that clears it is part "
        "of this decision's cost."
    ),
)
_CASCADE_LEAD = "Mandatory when `breaking: true`"
_DEC_TEMPLATE_REL = "template/specs/_template/DEC-XXXX-template.md"

# AC-7: the 13 files the implementation may touch between the two refs.
_FR_FILES = {
    *(
        f"template/{h}/commands/{n}.md"
        for h in (".agent-team", ".claude", ".cursor")
        for n in _OWNED_COMMANDS
    ),
    _DEC_TEMPLATE_REL,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source(name: str) -> str:
    return (_COMMANDS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _line_containing(text: str, needle: str) -> str:
    matches = [ln for ln in text.splitlines() if needle in ln]
    assert len(matches) == 1, (needle, matches)
    return matches[0]


@functools.cache
def _git_show(ref: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(_HUB_ROOT), "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _at(ref: str, rel: str) -> bytes:
    data = _git_show(ref, rel)
    if data is None:
        pytest.skip(f"{rel} at {ref[:7]} not reachable from {_HUB_ROOT}")
    return data


def _src_rel(name: str, harness: str = ".agent-team") -> str:
    return f"template/{harness}/commands/{name}.md"


def _block_span(lines: list[str]) -> tuple[int, int] | None:
    """[start, end) line indexes of the `## Headless conduct` block: the
    heading through the end of its first bullet run."""
    if _HEADING not in lines:
        return None
    start = lines.index(_HEADING)
    i = start + 1
    while i < len(lines) and not lines[i].startswith("- **"):
        i += 1
    while i < len(lines) and lines[i].startswith("- "):
        i += 1
    return start, i


def _block_text(text: str) -> str | None:
    lines = text.split("\n")
    span = _block_span(lines)
    return None if span is None else "\n".join(lines[span[0] : span[1]])


def _rule_gaps(text: str, ac: str) -> list[str]:
    """Everything wrong with `ac`'s section in `text`; [] when satisfied.
    Covers: each anchor on exactly one line, the bullet's other phrases on
    that line, one distinct bullet per rule, a contiguous run of `- ` bullets,
    outside the conduct block, between the AC's landmarks."""
    lines = text.split("\n")
    gaps: list[str] = []
    idx: dict[str, int] = {}
    for key, (anchor, phrases) in _RULES[ac].items():
        hits = [i for i, ln in enumerate(lines) if anchor in ln]
        if len(hits) != 1:
            gaps.append(f"({key}) anchor {anchor!r} on {len(hits)} lines")
            continue
        i = hits[0]
        idx[key] = i
        gaps += [f"({key}) missing {p!r}" for p in phrases if p not in lines[i]]
        if not lines[i].startswith("- "):
            gaps.append(f"({key}) not a bullet")
    if gaps:
        return gaps
    rows = sorted(idx.values())
    if len(set(rows)) != len(rows):
        gaps.append("two rules share one bullet")
    if rows != list(range(rows[0], rows[0] + len(rows))):
        gaps.append("bullets are not one contiguous section")
    span = _block_span(lines)
    if span is not None and any(span[0] <= r < span[1] for r in rows):
        gaps.append("inside ## Headless conduct")
    after, before = _PLACEMENT[ac]
    if after is not None:
        a = [i for i, ln in enumerate(lines) if ln.startswith(after)]
        if len(a) != 1 or not a[0] < rows[0]:
            gaps.append(f"not after {after!r}")
    if before is not None:
        b = [i for i, ln in enumerate(lines) if ln.startswith(before)]
        if len(b) != 1 or not rows[-1] < b[0]:
            gaps.append(f"not before {before!r}")
    return gaps


def _ac2_gaps(text: str) -> list[str]:
    """AC-2 over the dispatcher-configured verdict bullet of `text`."""
    matches = [ln for ln in text.splitlines() if _DISPATCHER_ANCHOR in ln]
    if len(matches) != 1:
        return [f"dispatcher bullet on {len(matches)} lines"]
    line = matches[0]
    gaps = []
    if not line.startswith(_KEPT_PREFIX):
        gaps.append("kept prefix changed")
    gaps += [f"missing: {p}" for p in _KEPT_AC8 + _NEW_CLAUSES if p not in line]
    gaps += [f"present: {p}" for p in _RETIRED + _DISPATCHER_FORBIDDEN if p in line]
    return gaps


def _opcodes(old: bytes, new: bytes) -> list[tuple[str, list[str], list[str]]]:
    a = old.decode("utf-8").split("\n")
    b = new.decode("utf-8").split("\n")
    return [
        (tag, a[i1:i2], b[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]


def _frontmatter(data: bytes) -> bytes:
    assert data.startswith(b"---\n"), data[:40]
    return data[: data.index(b"\n---\n", 4) + 5]


@functools.lru_cache(maxsize=1)
def _generator():
    if not _BOOTSTRAP.is_file():
        return None
    scripts = str(_BOOTSTRAP.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)  # bootstrap imports its sibling _console
    spec = importlib.util.spec_from_file_location(
        "bootstrap_under_test_fr0022", _BOOTSTRAP
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_commands


def _tree_names(ref: str) -> list[str]:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(_HUB_ROOT),
            "ls-tree",
            "--name-only",
            f"{ref}:template/.agent-team/commands",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"{ref[:7]} not reachable from {_HUB_ROOT}")
    return sorted(n[:-3] for n in proc.stdout.split() if n.endswith(".md"))


def _wrapper_mismatches(copy: Path, committed: dict[str, bytes]) -> list[str]:
    """Compare generator output under `copy` (CRLF -> LF) with committed
    wrapper bytes keyed `<harness>/<name>`."""
    bad = []
    for key, data in committed.items():
        harness, name = key.split("/")
        gen = (copy / harness / "commands" / f"{name}.md").read_bytes()
        if gen.replace(b"\r\n", b"\n") != data:
            bad.append(key)
    return bad


# ---------------------------------------------------------------------------
# AC-1, AC-3, AC-4, AC-5: the craft sections (standing rules + bite)
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-3
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
@pytest.mark.parametrize("ac", sorted(_FILE_FOR))
def test_each_command_carries_its_craft_section_with_every_operative_phrase(ac):
    assert _rule_gaps(_source(_FILE_FOR[ac]), ac) == []


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-3
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
@pytest.mark.parametrize("ac", sorted(_FILE_FOR))
def test_bite_the_base_commit_sources_fail_every_craft_detector(ac):
    """Adversarial / bite: at 9c12284 no command carried its section, so the
    detector reports every bullet's anchor missing there."""
    base = _at(_BASE_REF, _src_rel(_FILE_FOR[ac])).decode("utf-8")
    gaps = _rule_gaps(base, ac)
    assert gaps, ac
    # Every rule is reported, not just one: none of the sections existed.
    assert len(gaps) == len(_RULES[ac]), gaps


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-3
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
@pytest.mark.parametrize(
    "ac,key",
    [(ac, key) for ac in sorted(_FILE_FOR) for key in _RULES[ac]],
)
def test_dropping_one_phrase_from_one_bullet_is_detected_as_that_bullet(ac, key):
    """Adversarial: each bullet's detector is sensitive on its own — removing
    the last operative phrase (or the anchor when it is the only one) from
    exactly that line is reported against exactly that bullet."""
    text = _source(_FILE_FOR[ac])
    anchor, phrases = _RULES[ac][key]
    line = _line_containing(text, anchor)
    victim = phrases[-1] if phrases else anchor
    broken = line.replace(victim, "<removed>")
    assert broken != line
    gaps = _rule_gaps(text.replace(line, broken, 1), ac)
    assert gaps and all(g.startswith(f"({key})") for g in gaps), gaps


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-3
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
@pytest.mark.parametrize("ac", sorted(_FILE_FOR))
def test_a_duplicated_anchor_fails_the_one_line_rule(ac):
    """Adversarial for the FR-0012 `_line_containing` trap: echoing a bullet
    elsewhere in the file makes its anchor ambiguous and is reported."""
    text = _source(_FILE_FOR[ac])
    anchor = next(iter(_RULES[ac].values()))[0]
    doubled = text + f"\nSee also: {anchor}.\n"
    assert any("on 2 lines" in g for g in _rule_gaps(doubled, ac))


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
@pytest.mark.parametrize("ac", ("AC-1", "AC-4", "AC-5"))
def test_moving_the_section_into_the_headless_conduct_block_is_detected(ac):
    """Adversarial for placement: the same bullets appended to the conduct
    block's bullet run (and removed from their section) fail."""
    text = _source(_FILE_FOR[ac])
    lines = text.split("\n")
    bullets = [_line_containing(text, a) for a, _ in _RULES[ac].values()]
    rest = [ln for ln in lines if ln not in bullets]
    _, end = _block_span(rest)
    moved = rest[:end] + bullets + rest[end:]
    assert "inside ## Headless conduct" in _rule_gaps("\n".join(moved), ac)


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-4
@pytest.mark.parametrize("ac", ("AC-1", "AC-4"))
def test_moving_the_section_past_its_landmark_is_detected(ac):
    """Adversarial: the section placed at the end of the file sits after
    "When all tests pass:" / "**Hard limits:**" and fails."""
    text = _source(_FILE_FOR[ac])
    bullets = [_line_containing(text, a) for a, _ in _RULES[ac].values()]
    rest = [ln for ln in text.split("\n") if ln not in bullets]
    moved = "\n".join(rest + bullets)
    assert any(g.startswith("not before") for g in _rule_gaps(moved, ac))


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
@pytest.mark.parametrize("name", ("reviewer", "orchestrator", "developer"))
def test_conduct_blocks_are_byte_identical_at_base_and_implementation(name):
    """Nothing is added inside any `## Headless conduct` block (two fixed
    commits; the live hash pins stay in test_headless_conduct.py)."""
    base = _at(_BASE_REF, _src_rel(name)).decode("utf-8")
    impl = _at(_IMPL_REF, _src_rel(name)).decode("utf-8")
    assert _block_text(base) is not None
    assert _block_text(impl) == _block_text(base)


# covers hub-tooling FR-0022:AC-1
def test_no_new_reviewer_line_sets_or_invites_an_approval_state():
    """AC-1's constraints over the lines FR-0022 added to reviewer.md (fixed
    diff 9c12284..c2dc4f1): no `gh pr review`; `--approve` only as what GitHub
    refuses; "review state" only as a prohibition."""
    added = [
        ln
        for tag, _, new in _opcodes(
            _at(_BASE_REF, _src_rel("reviewer")), _at(_IMPL_REF, _src_rel("reviewer"))
        )
        if tag in ("insert", "replace")
        for ln in new
    ]
    assert len(added) >= 9  # 8 bullets + lead (+ the AC-2 line)
    for ln in added:
        assert "gh pr review" not in ln, ln
        if "--approve" in ln:
            assert "does not permit `--approve`" in ln, ln
        if "review state" in ln:
            assert "do not set" in ln or "never sets" in ln, ln


# covers hub-tooling FR-0022:AC-1
# covers hub-tooling FR-0022:AC-3
def test_fr0012_exclusive_phrases_stay_confined():
    """The live-data-anchor phrases stay in the two reviewer commands only, and
    architect.md never tells anyone not to end a turn with a question. The
    set checked is FR-0012's ten named sources (`gate-review.md`, a later
    reviewer-like role, is outside that rule and carries it by design)."""
    fr0012_sources = _CONDUCT + ("architect", "docs", "escalate", "gate", "status")
    holders = {
        n for n in fr0012_sources if any(ph in _source(n) for ph in _LIVE_DATA_PHRASES)
    }
    assert holders == {"reviewer", "reviewer-backfill"}
    architect = _source("architect")
    assert _NEVER_END not in architect
    assert _block_text(architect) is None


# covers hub-tooling FR-0022:AC-3
def test_architect_section_is_introduced_as_covering_drafting_and_escalation():
    """AC-3: the bullets apply to both branches — the section follows every
    branch of the command and its lead names both activities."""
    text = _source("architect")
    lines = text.split("\n")
    first = min(
        lines.index(_line_containing(text, a)) for a, _ in _RULES["AC-3"].values()
    )
    lead = lines[first - 1]
    assert "drafting an FR" in lead and "escalation" in lead, lead
    branch_heads = [i for i, ln in enumerate(lines) if ln.startswith("**If ")]
    assert branch_heads and max(branch_heads) < first


# ---------------------------------------------------------------------------
# AC-2: the verdict bullet asks for the Reviewer's own REVIEW.md
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0022:AC-2
def test_dispatcher_verdict_bullet_keeps_the_prefix_and_ac8_and_asks_for_review_md():
    assert _ac2_gaps(_source("reviewer")) == []


# covers hub-tooling FR-0022:AC-2
def test_bite_the_base_verdict_bullet_fails_ac2_on_exactly_the_new_and_retired_clauses():
    """Adversarial / bite: at 9c12284 the bullet kept its prefix and AC-8
    clauses but carried both retired needles and none of the new clauses."""
    gaps = _ac2_gaps(_at(_BASE_REF, _src_rel("reviewer")).decode("utf-8"))
    expected = [f"missing: {p}" for p in _NEW_CLAUSES]
    expected += [f"present: {p}" for p in _RETIRED]
    assert gaps == expected


# covers hub-tooling FR-0022:AC-2
@pytest.mark.parametrize(
    "mutation,expected",
    [
        (
            ("The dispatcher posts that message", "The dispatcher sends that message"),
            "kept prefix changed",
        ),
        (("on either verdict", "on approve"), "missing: on either verdict"),
        (
            ("Do not post the review", "Post the review"),
            "missing: not post the review yourself",
        ),
        (
            (
                "stage it with `git add REVIEW.md`",
                "stage it with `git add REVIEW.md` and `git commit`",
            ),
            "present: git commit",
        ),
        (
            ("worktree root", "worktree root (do not write `REVIEW.md` elsewhere)"),
            "present: do not write `REVIEW.md`",
        ),
        (
            (
                "do not set a GitHub approval state",
                "do not set a GitHub review state on the PR",
            ),
            "present: review state on the PR",
        ),
    ],
)
def test_ac2_detector_rejects_each_naive_rewrite(mutation, expected):
    """Adversarial: one targeted rewrite of the live bullet per clause class."""
    text = _source("reviewer")
    line = _line_containing(text, _DISPATCHER_ANCHOR)
    old, new = mutation
    assert old in line
    assert expected in _ac2_gaps(text.replace(line, line.replace(old, new, 1), 1))


# covers hub-tooling FR-0022:AC-2
# covers hub-tooling FR-0022:AC-7
def test_reviewer_diff_is_one_inserted_section_and_one_replaced_verdict_line():
    """Fixed diff 9c12284..c2dc4f1 of reviewer.md: the craft section is
    inserted before "When all tests pass:", the dispatcher verdict line is the
    only replaced line, and the no-dispatcher and staging bullets are
    untouched."""
    ops = _opcodes(
        _at(_BASE_REF, _src_rel("reviewer")), _at(_IMPL_REF, _src_rel("reviewer"))
    )
    assert [t for t, _, _ in ops] == ["insert", "replace"], ops
    inserted = ops[0][2]
    # lead + 8 bullets + one blank separator (difflib may seat it either end)
    assert len(inserted) == 10 and inserted.count("") == 1, inserted
    (old,), (new,) = ops[1][1], ops[1][2]
    assert _DISPATCHER_ANCHOR in old and _DISPATCHER_ANCHOR in new
    assert new.startswith(_KEPT_PREFIX) and old.startswith(_KEPT_PREFIX)


# ---------------------------------------------------------------------------
# AC-5 / AC-3 / AC-4: only insertions in the other three commands
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0022:AC-3
# covers hub-tooling FR-0022:AC-4
# covers hub-tooling FR-0022:AC-5
# covers hub-tooling FR-0022:AC-7
@pytest.mark.parametrize(
    "name,count",
    (("architect", 11), ("orchestrator", 8), ("developer", 5)),
)
def test_other_commands_only_gain_one_inserted_section(name, count):
    """Fixed diff: one insert, no line removed or rewritten — so every
    `_SURVIVING_LINES` entry, the staging line and the ordering pins hold by
    construction at c2dc4f1."""
    ops = _opcodes(_at(_BASE_REF, _src_rel(name)), _at(_IMPL_REF, _src_rel(name)))
    assert len(ops) == 1 and ops[0][0] == "insert", ops
    assert len(ops[0][2]) == count and ops[0][2].count("") == 1, ops[0][2]


# ---------------------------------------------------------------------------
# AC-6: the DEC template's cascade paragraph
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0022:AC-6
def test_dec_template_cascade_paragraph_states_both_sentences():
    text = _DEC_TEMPLATE.read_text(encoding="utf-8")
    body = text.split("\n## Cascade\n", 1)[1].split("\n## ", 1)[0]
    para = _line_containing(body, _CASCADE_LEAD)
    for sentence in _AC6_SENTENCES:
        assert sentence in para, sentence


# covers hub-tooling FR-0022:AC-6
def test_dec_template_diff_is_exactly_the_two_sentences_appended():
    """Fixed diff 9c12284..c2dc4f1: one line changed, the cascade paragraph,
    and the change is the old paragraph plus exactly the AC-6 text."""
    ops = _opcodes(_at(_BASE_REF, _DEC_TEMPLATE_REL), _at(_IMPL_REF, _DEC_TEMPLATE_REL))
    assert len(ops) == 1 and ops[0][0] == "replace", ops
    (old,), (new,) = ops[0][1], ops[0][2]
    assert old.startswith(_CASCADE_LEAD)
    assert new == old + " " + " ".join(_AC6_SENTENCES)


# covers hub-tooling FR-0022:AC-6
def test_bite_the_base_dec_template_lacks_the_cost_sentences():
    base = _at(_BASE_REF, _DEC_TEMPLATE_REL).decode("utf-8")
    assert all(s not in base for s in _AC6_SENTENCES)


# covers hub-tooling FR-0022:AC-6
def test_a_dec_filled_from_the_template_validates(tmp_path):
    """The template stays fillable: placeholders replaced, a breaking DEC
    that revises an FR, `index-specs.py --validate` exits 0."""
    scripts = _TEMPLATE_DIR / "scripts"
    if not (scripts / "index-specs.py").is_file():
        pytest.skip("index-specs.py not present")
    (tmp_path / "scripts").mkdir()
    for n in ("index-specs.py", "deploy-gate.py", "spec_footprint.py", "spec_query.py"):
        if (scripts / n).is_file():
            shutil.copy(scripts / n, tmp_path / "scripts" / n)
    fr = (
        (_TEMPLATE_DIR / "specs" / "_template" / "FR-XXXX-template.md")
        .read_text(encoding="utf-8")
        .replace("FR-XXXX", "FR-0100")
        .replace("YYYY-MM-DD", "2026-01-01")
    )
    dec = (
        _DEC_TEMPLATE.read_text(encoding="utf-8")
        .replace("DEC-XXXX", "DEC-0001")
        .replace("YYYY-MM-DD", "2026-01-01")
        .replace(
            "<one-line title — the choice made, not the topic>", "Widen the status set"
        )
        .replace("tier: <tier>", "tier: agent")
        .replace("revises: null", "revises: FR-0100")
        .replace("breaking: false", "breaking: true")
        .replace(
            "  <why this choice, in prose that stands on its own>",
            "  Synthetic: a widened set needs its pinning test named.",
        )
        .replace(
            "- <artifact> — <what changes>",
            "- tests/unit/test_x.py::test_status_set — backfilled by /reviewer-backfill FR-0100",
        )
    )
    specs = tmp_path / "specs"
    (specs / "decisions").mkdir(parents=True)
    (specs / "FR-0100-filled.md").write_bytes(fr.encode("utf-8"))
    (specs / "decisions" / "DEC-0001-filled.md").write_bytes(dec.encode("utf-8"))
    proc = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "index-specs.py"), "--validate"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "1 DECs" in proc.stdout


# ---------------------------------------------------------------------------
# AC-7: wrappers regenerated; nothing else moves
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0022:AC-7
def test_only_the_thirteen_fr_files_differ_between_base_and_implementation():
    proc = subprocess.run(
        ["git", "-C", str(_HUB_ROOT), "diff", "--name-only", _BASE_REF, _IMPL_REF],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip("fixed refs not reachable")
    assert set(proc.stdout.split()) == _FR_FILES


# covers hub-tooling FR-0022:AC-7
def test_generator_over_implementation_sources_reproduces_all_22_wrappers(tmp_path):
    """Regenerate from c2dc4f1's sources in a temp copy; every wrapper
    committed at c2dc4f1 equals the output byte for byte after CRLF -> LF."""
    generate = _generator()
    if generate is None:
        pytest.skip(f"hub generator not present at {_BOOTSTRAP}")
    names = _tree_names(_IMPL_REF)
    assert len(names) == 11
    copy = tmp_path / "t"
    (copy / ".agent-team" / "commands").mkdir(parents=True)
    for n in names:
        (copy / ".agent-team" / "commands" / f"{n}.md").write_bytes(
            _at(_IMPL_REF, _src_rel(n))
        )
    assert generate(copy) == 11
    committed = {
        f"{h}/{n}": _at(_IMPL_REF, _src_rel(n, h))
        for h in (".claude", ".cursor")
        for n in names
    }
    assert len(committed) == 22
    assert _wrapper_mismatches(copy, committed) == []
    # Adversarial: a hand edit or a CRLF copy of an owned wrapper is caught.
    for tampered in (
        committed[".claude/reviewer"] + b"hand edit\n",
        committed[".cursor/developer"].replace(b"\n", b"\r\n"),
    ):
        key = (
            ".claude/reviewer" if tampered.endswith(b"edit\n") else ".cursor/developer"
        )
        assert _wrapper_mismatches(copy, {key: tampered}) == [key]


# covers hub-tooling FR-0022:AC-7
@pytest.mark.parametrize("harness", (".claude", ".cursor"))
@pytest.mark.parametrize("name", _OWNED_COMMANDS)
def test_owned_wrappers_are_lf_and_start_with_generated_frontmatter(harness, name):
    data = _at(_IMPL_REF, _src_rel(name, harness))
    assert b"\r" not in data and data.endswith(b"\n")
    assert data.startswith(b"---\ndescription: ")
    live = (_TEMPLATE_DIR / harness / "commands" / f"{name}.md").read_bytes()
    assert b"\r" not in live


# covers hub-tooling FR-0022:AC-7
def test_the_14_non_owned_wrappers_are_byte_identical_at_base_and_implementation():
    others = [n for n in _tree_names(_IMPL_REF) if n not in _OWNED_COMMANDS]
    assert len(others) == 7
    for h in (".claude", ".cursor"):
        for n in others:
            assert _at(_BASE_REF, _src_rel(n, h)) == _at(_IMPL_REF, _src_rel(n, h)), (
                h,
                n,
            )


# covers hub-tooling FR-0022:AC-7
@pytest.mark.parametrize("name", _OWNED_COMMANDS)
def test_fr0019_frontmatter_blocks_are_byte_identical_at_base_and_implementation(name):
    base = _frontmatter(_at(_BASE_REF, _src_rel(name)))
    impl = _frontmatter(_at(_IMPL_REF, _src_rel(name)))
    assert base == impl
    assert b"description: " in impl
