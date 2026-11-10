"""Reviewer tests for FR-0012 — the headless conduct contract in the generated
role commands.

Five canonical command sources (`developer`, `reviewer`, `maintainer`,
`reviewer-backfill`, `orchestrator`) carry one `## Headless conduct` block that
is byte-identical across all five apart from a single reviewer-only sentence
(AC-1, AC-7); the block states the five rules AC-2..AC-6 name; `reviewer.md`
and `orchestrator.md` restate the review contract (AC-8); every canonical
command has both harness wrappers, equal to `generate_commands` output (AC-9);
and nothing else in the five sources changed (AC-10).

Anchoring: the block is located by its heading and read as *bytes* so a CRLF
or trailing-whitespace variant is a different block, not the same one. The
AC-9 equality test imports the hub's `scripts/bootstrap.py` and runs
`generate_commands` over a temporary copy of the template; the wrapper
structure tests need no generator and run everywhere. The AC-10 "nothing else
changed" test reads the pre-FR sources from the hub commit this FR branched
from (`bd46dd3`); inside a bootstrapped project that object does not exist and
those tests skip, as `test_dispatch_permissions.py` does for its pre-FR ref.

Coverage annotations are written `# covers hub-tooling FR-0012:AC-N` rather
than the gate's `@covers` form on purpose: this file rides along into every
bootstrapped project, where no FR-0012 exists and `deploy-gate.py` would fail
with "@covers references unknown FR".

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import difflib
import functools
import hashlib
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
_HUB_ROOT = _TEMPLATE_DIR.parent
_BOOTSTRAP = _HUB_ROOT / "scripts" / "bootstrap.py"
# The hub commit FR-0012 branched from: the last state of the five sources
# before the block was added. Immutable, so pinning it is not a live-data
# anchor on a mutable field.
_PRE_FR_REF = "bd46dd35b7b58c80cc5401f9fe34277eec0284be"
# FR-0012's merge commit (PR #5). DEC-0016 anchors AC-10's residual check here:
# at this commit the five sources are exactly FR-0012's result, so the check
# states what FR-0012 changed rather than freezing HEAD. Immutable.
_FR0012_MERGE_REF = "f03797884f882574a45d77bb7efa747f224a8c0f"

_CONDUCT = ("developer", "reviewer", "maintainer", "reviewer-backfill", "orchestrator")
_REVIEWER_ONLY = ("reviewer", "reviewer-backfill")
_NOT_REVIEWER = ("developer", "maintainer", "orchestrator")
_NO_BLOCK = ("architect", "docs", "escalate", "gate", "status")

_HEADING = b"## Headless conduct"
_AC7_LEAD = b"- **Live-data anchors assert structure, not a mutable field.**"
# sha256 of the shared core (heading through the last shared bullet, LF-joined,
# no trailing newline) and of the reviewer variant (core + the AC-7 sentence),
# as recorded in the PR body and recomputed here at review.
_CORE_SHA256 = "d48c55cce0be71f4addfa893e82eb8a381c4c949033fac9e8f1677dead0484f0"
_REVIEWER_SHA256 = "45f0f0da51bd73ae68ae4f546343fe02a24eab834b9b4f2eec48dd49d9ad6b07"

# Operative phrases per AC. Substance, not the whole prose: a rewording that
# keeps every phrase still passes; dropping a rule fails.
_RULES: dict[str, tuple[bytes, ...]] = {
    "AC-2": (
        b"headless under `claude -p`",
        b"none can answer",
        b"never end your turn with a question",
        b"hard stop for that path",
        b"`## ESCALATION`",
        b"`.agent-team/escalation-matrix.md`",
        b"`PR_BODY.md` for the Developer, Maintainer, and Reviewer-backfill",
        b"`REVIEW.md` for the Reviewer",
        b"continue with everything else that does not depend on it",
    ),
    "AC-3": (
        b"Never bare `git stash`",
        b"shared across every worktree and session on the host",
        b"WIP commit",
        b"`git stash push -m <tag>`",
        b"by SHA",
    ),
    "AC-4": (
        b"host-forced substitution is at least a finding",
        b"`## FINDINGS` item",
        b"what was declared",
        b"what you used instead",
        b"host behaviour that forced it",
        b"architectural reach",
        b"is a `## ESCALATION`, not a finding",
    ),
    "AC-5": (
        b"`specs/_metrics/*.ndjson`",
        b"never part of a role branch's handoff",
        b"`git checkout -- specs/_metrics`",
        b"before you stage",
        b"Orchestrator commits metrics from `main`",
    ),
    "AC-6": (
        b"across more than one file",
        b"`@covers`",
        b"`@implements`",
        b"file by file",
        b"read back the diff",
    ),
}
_AC7_PHRASES = (
    b"asserts existence and well-formedness",
    b"never a mutable field",
    b"status, class, count, or SHA",
    b"within the hour",
)
# Bullets that carry each rule, keyed by their bold lead — used by the
# adversarial "drop one bullet" test to prove each detector is sensitive.
_BULLET_LEAD = {
    "AC-2": b"- **Denied is a hard stop, not a question.**",
    "AC-3": b"- **Never bare `git stash`.**",
    "AC-4": b"- **A host-forced substitution is at least a finding.**",
    "AC-5": b"- **Restore the metrics record before staging.**",
    "AC-6": b"- **No blanket substitutions over annotated files.**",
}

# The pre-FR dispatcher-path verdict bullet of reviewer.md (FR-0006 AC-7's
# wording), embedded as a fixture so the AC-8 detector can be shown to reject
# it without needing git.
_PRE_FR_DISPATCHER_VERDICT_LINE = (
    "   - **If a dispatcher is configured**: your final assistant message **is** "
    "the verdict of record. Open it with a `## Approve` heading (or "
    "`## Request changes`) — that heading is what the dispatcher reads as the "
    "verdict — and confirm in it: every AC has `@covers`, adversarial tests are "
    "present, deploy gate is green. The dispatcher posts that message to the PR "
    "as the review and records it on your branch as `REVIEW.md` — do not write "
    "`REVIEW.md` or post the review yourself."
)
# The pre-full-body wrapper stub format the template carried for four
# commands until this FR (see FR-0012 Notes); the generator cannot produce it.
_STALE_STUB = (
    b"Follow the instructions in @.agent-team/commands/architect.md.\n\n"
    b"User input: $ARGUMENTS\n"
)

_BANNER = (
    b"<!-- Generated from .agent-team/commands/%s \xe2\x80\x94 do not edit by hand. -->"
)
_CLAUDE_ONLY_KEYS = {"model", "effort", "allowed-tools"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source(name: str, root: Path = _COMMANDS_DIR) -> bytes:
    return (root / f"{name}.md").read_bytes()


def _extract_block(data: bytes) -> bytes | None:
    """The conduct block: its heading line through the last line of the
    bullet list that follows it. Bytes in, bytes out — a `\\r` anywhere in the
    block stays in the block."""
    lines = data.split(b"\n")
    try:
        start = lines.index(_HEADING)
    except ValueError:
        return None
    out = [lines[start]]
    in_bullets = False
    for ln in lines[start + 1 :]:
        if ln.startswith(b"- "):
            in_bullets = True
            out.append(ln)
            continue
        if in_bullets:
            break
        out.append(ln)
    return b"\n".join(out)


def _core(block: bytes) -> bytes:
    return b"\n".join(ln for ln in block.split(b"\n") if not ln.startswith(_AC7_LEAD))


def _blocks(root: Path) -> dict[str, bytes | None]:
    return {name: _extract_block(_source(name, root)) for name in _CONDUCT}


def _identity_failures(root: Path) -> list[str]:
    """AC-1 as a function of a commands directory: every conduct source has
    the block and every core is byte-identical to `developer.md`'s."""
    blocks = _blocks(root)
    failures = [f"{n}: block missing" for n, b in blocks.items() if b is None]
    if failures:
        return failures
    reference = _core(blocks["developer"])  # type: ignore[arg-type]
    for name, block in blocks.items():
        if _core(block) != reference:  # type: ignore[arg-type]
            failures.append(f"{name}: core differs from developer.md")
    return failures


def _missing_rules(block: bytes, ac: str) -> list[bytes]:
    return [p for p in _RULES[ac] if p not in block]


def _ac7_holders(root: Path) -> set[str]:
    return {
        name for name in _CONDUCT if any(p in _source(name, root) for p in _AC7_PHRASES)
    }


def _line_containing(text: str, needle: str) -> str:
    matches = [ln for ln in text.splitlines() if needle in ln]
    assert len(matches) == 1, (needle, matches)
    return matches[0]


# FR-0006 AC-7's `REVIEW.md` phrases as the bullet carried them at FR-0012's
# merge. DEC-0019 Decision 2 retires them for the live bullet; they remain the
# default only because AC-10's residual check (anchored at `f037978` by
# DEC-0016, untouched per DEC-0019 Decision 4) still runs the detector over
# the bullet in its FR-0012 form.
_FR0006_REVIEW_MD = (
    "records it on your branch as `REVIEW.md`",
    "do not write `REVIEW.md`",
)
# DEC-0018 Decision 1's three clauses: the Reviewer writes and stages
# `REVIEW.md`; the dispatcher keeps it; it synthesises one only when absent.
_DEC0018_REVIEW_MD = (
    "to `REVIEW.md` at the worktree root and stage it",
    "keeps a staged or committed `REVIEW.md` byte-for-byte",
    "synthesises one from your final message only when you wrote none",
)


def _ac8_gaps(
    dispatcher_line: str, review_md: tuple[str, ...] = _FR0006_REVIEW_MD
) -> list[str]:
    """What AC-8 adds to the dispatcher-path verdict bullet on top of the
    FR-0006 AC-7 phrases it must keep. Pass `_DEC0018_REVIEW_MD` for the
    live bullet (DEC-0019 Decision 2)."""
    gaps = []
    for needle in (
        # FR-0006 AC-7, preserved (AC-10):
        "verdict of record",
        "`## Approve`",
        "`## Request changes`",
        *review_md,
        # AC-8, added:
        "do not set a GitHub approval state",
        "authored by the same account",
        "as a comment",
    ):
        if needle not in dispatcher_line:
            gaps.append(f"missing: {needle}")
    for forbidden in ("git commit", "review state on the PR"):
        if forbidden in dispatcher_line:
            gaps.append(f"present: {forbidden}")
    return gaps


def _split_frontmatter(wrapper: bytes) -> tuple[list[bytes], bytes]:
    """(frontmatter lines between the fences, everything after the closing
    fence)."""
    assert wrapper.startswith(b"---\n"), wrapper[:40]
    close = wrapper.index(b"\n---\n", 4)
    return wrapper[4:close].split(b"\n"), wrapper[close + 5 :]


def _source_body(data: bytes) -> bytes:
    """The source text after its leading frontmatter block and the one blank
    line that follows it, or the whole source when it has none (DEC-0016
    Decision 1; hub-tooling FR-0019 AC-2/AC-3)."""
    if not data.startswith(b"---\n"):
        return data
    close = data.index(b"\n---\n", 4)
    rest = data[close + 5 :]
    return rest[1:] if rest.startswith(b"\n") else rest


def _wrapper_failures(root: Path) -> list[str]:
    """AC-9 without the generator: for every canonical source under `root`,
    both wrappers exist, are LF, open with the frontmatter block, carry the
    generated banner, and then the source body verbatim (Cursor: with
    `$ARGUMENTS` -> `{{args}}`). The source body is the text after the
    source's own frontmatter block (DEC-0016)."""
    failures: list[str] = []
    for src in sorted((root / ".agent-team" / "commands").glob("*.md")):
        body = _source_body(src.read_bytes()).strip() + b"\n"
        for harness, expected_body in (
            (".claude", body),
            (".cursor", body.replace(b"$ARGUMENTS", b"{{args}}")),
        ):
            path = root / harness / "commands" / src.name
            tag = f"{harness}/commands/{src.name}"
            if not path.is_file():
                failures.append(f"{tag}: missing")
                continue
            data = path.read_bytes()
            if b"\r" in data:
                failures.append(f"{tag}: CRLF")
            if not data.startswith(b"---\ndescription: "):
                failures.append(f"{tag}: no frontmatter")
                continue
            _, rest = _split_frontmatter(data)
            banner = _BANNER % src.name.encode()
            if not rest.startswith(banner + b"\n\n"):
                failures.append(f"{tag}: banner missing or misplaced")
                continue
            if rest[len(banner) + 2 :] != expected_body:
                failures.append(f"{tag}: body differs from source")
    return failures


@functools.lru_cache(maxsize=1)
def _generator():
    """`generate_commands` from the hub's `scripts/bootstrap.py`, or None when
    this file is running inside a bootstrapped project."""
    if not _BOOTSTRAP.is_file():
        return None
    scripts = str(_BOOTSTRAP.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)  # bootstrap imports its sibling _console
    spec = importlib.util.spec_from_file_location(
        "bootstrap_under_test_fr0012", _BOOTSTRAP
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_commands


def _regenerate(root: Path, tmp_path: Path) -> tuple[int, Path]:
    """Run the generator over a temp copy of `root`'s canonical sources only;
    returns (count, copy root). Generated bytes are compared after
    `\\r\\n` -> `\\n` normalisation (AC-9: the generator emits CRLF on Windows)."""
    generate = _generator()
    if generate is None:
        pytest.skip(f"hub generator not present at {_BOOTSTRAP}")
    copy = tmp_path / "template_copy"
    shutil.copytree(
        root / ".agent-team" / "commands", copy / ".agent-team" / "commands"
    )
    return generate(copy), copy


def _generated(copy: Path, harness: str, name: str) -> bytes:
    return (copy / harness / "commands" / name).read_bytes().replace(b"\r\n", b"\n")


def _copy_template(tmp_path: Path) -> Path:
    root = tmp_path / "template"
    for rel in (".agent-team/commands", ".claude/commands", ".cursor/commands"):
        shutil.copytree(_TEMPLATE_DIR / rel, root / rel)
    return root


@functools.cache
def _pre_fr_source(name: str) -> bytes | None:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(_HUB_ROOT),
            "show",
            f"{_PRE_FR_REF}:template/.agent-team/commands/{name}.md",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _pre_fr(name: str) -> bytes:
    src = _pre_fr_source(name)
    if src is None:
        pytest.skip(
            f"pre-FR {name}.md ({_PRE_FR_REF[:7]}) not reachable from {_HUB_ROOT}"
        )
    return src


@functools.cache
def _merge_source(name: str) -> bytes | None:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(_HUB_ROOT),
            "show",
            f"{_FR0012_MERGE_REF}:template/.agent-team/commands/{name}.md",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _at_fr0012_merge(name: str) -> bytes:
    """The source as FR-0012 left it (DEC-0016 Decision 2)."""
    src = _merge_source(name)
    if src is None:
        pytest.skip(
            f"FR-0012 merge {name}.md ({_FR0012_MERGE_REF[:7]}) not reachable"
            f" from {_HUB_ROOT}"
        )
    return src


def _without_block(data: bytes) -> bytes:
    block = _extract_block(data)
    assert block is not None
    marker = b"\n\n" + block + b"\n\n"
    assert data.count(marker) == 1
    return data.replace(marker, b"\n\n", 1)


def _residual_opcodes(
    head: bytes, pre: bytes
) -> list[tuple[str, list[str], list[str]]]:
    """Line-level diff of (HEAD minus the block) against the pre-FR text, as
    (tag, old lines, new lines) for every non-equal opcode."""
    old = pre.decode("utf-8").split("\n")
    new = _without_block(head).decode("utf-8").split("\n")
    return [
        (tag, old[i1:i2], new[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, old, new, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]


def _is_opening_sentence_split(old: list[str], new: list[str]) -> bool:
    """`S1. Before ...` -> [`S1.`, ``, `Before ...`] — placement, not a
    changed instruction (FR-0012 Notes, Architect ruling i)."""
    return (
        len(old) == 1
        and len(new) == 3
        and new[1] == ""
        and old[0] == f"{new[0]} {new[2]}"
        and new[2].startswith("Before ")
    )


# ---------------------------------------------------------------------------
# AC-1: one canonical block, byte-identical in all five sources
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0012:AC-1
def test_block_core_is_byte_identical_across_the_five_sources():
    assert _identity_failures(_COMMANDS_DIR) == []
    core = _core(_extract_block(_source("developer")))  # type: ignore[arg-type]
    assert hashlib.sha256(core).hexdigest() == _CORE_SHA256
    assert core.startswith(_HEADING + b"\n\n")
    assert b"\r" not in core


# covers hub-tooling FR-0012:AC-1
@pytest.mark.parametrize("name", _CONDUCT)
def test_each_source_carries_the_block_exactly_once_before_its_first_instruction(name):
    data = _source(name)
    assert data.count(_HEADING) == 1, name
    block = _extract_block(data)
    assert block is not None and block.count(b"\n- **") >= 5, name
    # solution_space.open: placement is free, but the block precedes the first
    # numbered instruction — nothing that could be denied runs before it.
    first_step = data.index(b"\n1. ")
    assert data.index(_HEADING) < first_step, name


# covers hub-tooling FR-0012:AC-1
def test_reviewer_blocks_are_the_core_plus_one_ac7_line_and_the_others_are_the_core():
    blocks = _blocks(_COMMANDS_DIR)
    for name in _REVIEWER_ONLY:
        block = blocks[name]
        assert block is not None
        lines = block.split(b"\n")
        assert sum(ln.startswith(_AC7_LEAD) for ln in lines) == 1, name
        assert lines[-1].startswith(_AC7_LEAD), name  # the one permitted extra
        assert hashlib.sha256(block).hexdigest() == _REVIEWER_SHA256, name
    for name in _NOT_REVIEWER:
        block = blocks[name]
        assert block is not None
        assert _core(block) == block, name
    assert blocks["reviewer"] == blocks["reviewer-backfill"]


# covers hub-tooling FR-0012:AC-1
def test_one_character_mutation_in_one_source_breaks_identity(tmp_path):
    """Adversarial: the comparison is not a fuzzy one."""
    root = _copy_template(tmp_path)
    cmds = root / ".agent-team" / "commands"
    data = (cmds / "maintainer.md").read_bytes()
    mutated = data.replace(
        b"Make a WIP commit instead", b"Make a WIP commit instead.", 1
    )
    assert mutated != data
    (cmds / "maintainer.md").write_bytes(mutated)
    assert _identity_failures(cmds) == ["maintainer: core differs from developer.md"]


# covers hub-tooling FR-0012:AC-1
@pytest.mark.parametrize(
    "variant",
    ["crlf", "trailing-space", "tab-indent"],
)
def test_whitespace_and_line_ending_variants_of_the_block_are_not_identical(
    tmp_path, variant
):
    """Adversarial: a block that reads the same is not the same block."""
    root = _copy_template(tmp_path)
    cmds = root / ".agent-team" / "commands"
    data = (cmds / "orchestrator.md").read_bytes()
    block = _extract_block(data)
    assert block is not None
    if variant == "crlf":
        changed = data.replace(block, block.replace(b"\n", b"\r\n"))
    elif variant == "trailing-space":
        changed = data.replace(block, block.replace(b"by SHA.", b"by SHA. "))
    else:
        changed = data.replace(block, block.replace(b"\n- **Never", b"\n\t- **Never"))
    assert changed != data
    (cmds / "orchestrator.md").write_bytes(changed)
    assert _identity_failures(cmds) != []


# ---------------------------------------------------------------------------
# AC-2..AC-6: each named rule is present in substance, in all five sources
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0012:AC-2
# covers hub-tooling FR-0012:AC-3
# covers hub-tooling FR-0012:AC-4
# covers hub-tooling FR-0012:AC-5
# covers hub-tooling FR-0012:AC-6
@pytest.mark.parametrize("ac", sorted(_RULES))
@pytest.mark.parametrize("name", _CONDUCT)
def test_rule_is_stated_in_the_block_of_every_conduct_source(name, ac):
    block = _extract_block(_source(name))
    assert block is not None, name
    assert _missing_rules(block, ac) == [], (name, ac)
    # The rule lives inside the block, not somewhere else in the file.
    assert _BULLET_LEAD[ac] in block, (name, ac)


# covers hub-tooling FR-0012:AC-2
def test_denied_call_rule_names_both_handoff_artifacts_and_the_matrix():
    block = _extract_block(_source("developer"))
    assert block is not None
    bullet = next(
        ln for ln in block.split(b"\n") if ln.startswith(_BULLET_LEAD["AC-2"])
    )
    # Hard stop or escalation — the two sanctioned outcomes, in one bullet.
    assert b"work around it inside your writable footprint" in bullet
    assert b"emit a structured `## ESCALATION` block" in bullet
    assert b"`PR_BODY.md`" in bullet and b"`REVIEW.md`" in bullet
    # And the escalation goes into the artifact, not the final message.
    assert b"into your handoff artifact" in bullet


# covers hub-tooling FR-0012:AC-3
def test_git_stash_rule_names_both_alternatives_in_the_same_bullet():
    block = _extract_block(_source("reviewer"))
    assert block is not None
    bullet = next(
        ln for ln in block.split(b"\n") if ln.startswith(_BULLET_LEAD["AC-3"])
    )
    assert b"WIP commit" in bullet
    assert b"`git stash push -m <tag>`" in bullet and b"by SHA" in bullet


# covers hub-tooling FR-0012:AC-4
def test_substitution_rule_distinguishes_finding_from_escalation():
    block = _extract_block(_source("maintainer"))
    assert block is not None
    bullet = next(
        ln for ln in block.split(b"\n") if ln.startswith(_BULLET_LEAD["AC-4"])
    )
    assert bullet.index(b"`## FINDINGS` item") < bullet.index(b"architectural reach")
    assert bullet.endswith(b"is a `## ESCALATION`, not a finding.")


# covers hub-tooling FR-0012:AC-5
def test_metrics_rule_restores_before_staging_and_commits_from_main():
    block = _extract_block(_source("orchestrator"))
    assert block is not None
    bullet = next(
        ln for ln in block.split(b"\n") if ln.startswith(_BULLET_LEAD["AC-5"])
    )
    assert bullet.index(b"`git checkout -- specs/_metrics`") < bullet.index(
        b"before you stage"
    )
    assert bullet.endswith(b"The Orchestrator commits metrics from `main`.")


# covers hub-tooling FR-0012:AC-6
def test_annotation_rule_covers_both_annotation_kinds_and_multi_file_scope():
    block = _extract_block(_source("reviewer-backfill"))
    assert block is not None
    bullet = next(
        ln for ln in block.split(b"\n") if ln.startswith(_BULLET_LEAD["AC-6"])
    )
    assert b"scripted or regex substitution" in bullet
    assert b"`@covers` or `@implements`" in bullet
    assert b"forbidden" in bullet


# covers hub-tooling FR-0012:AC-2
# covers hub-tooling FR-0012:AC-3
# covers hub-tooling FR-0012:AC-4
# covers hub-tooling FR-0012:AC-5
# covers hub-tooling FR-0012:AC-6
@pytest.mark.parametrize("ac", sorted(_RULES))
def test_dropping_one_bullet_is_detected_as_exactly_that_rule_missing(ac):
    """Adversarial: each rule's detector is sensitive to its own bullet and
    to nothing else — so a block with one rule silently removed fails on that
    AC and only that AC."""
    block = _extract_block(_source("developer"))
    assert block is not None
    kept = b"\n".join(
        ln for ln in block.split(b"\n") if not ln.startswith(_BULLET_LEAD[ac])
    )
    assert kept != block
    assert _missing_rules(kept, ac) != []
    for other in _RULES:
        if other != ac:
            assert _missing_rules(kept, other) == [], (ac, other)


# covers hub-tooling FR-0012:AC-2
@pytest.mark.parametrize("name", _NO_BLOCK)
def test_the_block_is_not_sprayed_into_the_other_five_sources(name):
    """Adversarial for AC-1's "five sources" and Out-of-scope bullet 3: the
    non-dispatched commands do not carry the block."""
    data = _source(name)
    assert _extract_block(data) is None, name
    assert b"never end your turn with a question" not in data, name


# ---------------------------------------------------------------------------
# AC-7: live-data anchor rule — reviewer commands only
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0012:AC-7
@pytest.mark.parametrize("name", _REVIEWER_ONLY)
def test_reviewer_commands_state_the_live_data_anchor_rule_inside_the_block(name):
    block = _extract_block(_source(name))
    assert block is not None
    for phrase in _AC7_PHRASES:
        assert phrase in block, (name, phrase)
    line = next(ln for ln in block.split(b"\n") if ln.startswith(_AC7_LEAD))
    assert b"a register row, a spec's frontmatter, a committed artifact" in line


# covers hub-tooling FR-0012:AC-7
def test_live_data_anchor_rule_appears_in_no_other_source():
    assert _ac7_holders(_COMMANDS_DIR) == set(_REVIEWER_ONLY)
    for name in _NOT_REVIEWER + _NO_BLOCK:
        data = _source(name)
        assert _AC7_LEAD not in data, name
        for phrase in _AC7_PHRASES:
            assert phrase not in data, (name, phrase)


# covers hub-tooling FR-0012:AC-7
def test_copying_the_rule_into_a_developer_command_is_detected(tmp_path):
    """Adversarial: the rule is reviewer-scoped, and the detector says so."""
    root = _copy_template(tmp_path)
    cmds = root / ".agent-team" / "commands"
    reviewer_block = _extract_block((cmds / "reviewer.md").read_bytes())
    dev = (cmds / "developer.md").read_bytes()
    dev_block = _extract_block(dev)
    assert reviewer_block is not None and dev_block is not None
    (cmds / "developer.md").write_bytes(dev.replace(dev_block, reviewer_block))
    assert _ac7_holders(cmds) == {"developer", "reviewer", "reviewer-backfill"}
    # And AC-1 still holds for the cores: the sentence is the one permitted extra.
    assert _identity_failures(cmds) == []


# ---------------------------------------------------------------------------
# AC-8: the review contract as the factory actually works
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0012:AC-8
def test_reviewer_dispatcher_path_keeps_fr0006_phrases_and_adds_the_no_self_approval_rule():
    text = _source("reviewer").decode("utf-8")
    line = _line_containing(
        text, "If a dispatcher is configured**: your final assistant message"
    )
    assert _ac8_gaps(line, _DEC0018_REVIEW_MD) == []
    # The verdict of record is the final message, posted by the dispatcher.
    assert "The dispatcher posts that message to the PR as the review" in line
    assert "GitHub does not permit `--approve` or `--request-changes`" in line
    assert "falls back to posting your verdict as a comment" in line


# covers hub-tooling FR-0012:AC-8
def test_reviewer_no_dispatcher_branch_keeps_the_approve_review_state_for_a_human_reviewer():
    text = _source("reviewer").decode("utf-8")
    line = _line_containing(
        text, "**If no dispatcher**: use `Approve` review state on the PR"
    )
    assert "confirm the same three things" in line
    assert "human reviewer who is not the PR's author" in line
    assert "self-review restriction above does not apply" in line
    # The human merges (AC-8): unchanged hand-off line.
    assert (
        "5. Hand off: tell the user the PR is approved and ready for human merge."
        in text
    )


# covers hub-tooling FR-0012:AC-8
def test_orchestrator_states_the_verdict_is_posted_not_approved_and_the_human_merges():
    text = _source("orchestrator").decode("utf-8")
    line = _line_containing(
        text, "The Reviewer's verdict is its final assistant message"
    )
    assert (
        "no agent, including you, ever sets a GitHub approval state on the project owner's own PR"
        in line
    )
    assert "falls back to posting the verdict as a comment" in line
    assert "still a posted verdict, not a stalled phase" in line
    assert "for the human to merge" in text
    # The restatement sits with the cycle's terminal-state definition.
    assert (
        text.index("**Terminal state of a complete cycle**")
        < text.index(line)
        < text.index("**Phase 3: Escalation routing**")
    )


# covers hub-tooling FR-0012:AC-8
@pytest.mark.parametrize("name", ("reviewer", "orchestrator"))
def test_neither_file_instructs_an_agent_to_set_an_approval_state_on_the_owners_pr(
    name,
):
    text = _source(name).decode("utf-8")
    for ln in text.splitlines():
        assert "gh pr review" not in ln, ln
        if "--approve" in ln:
            # Only ever mentioned as what GitHub refuses.
            assert "does not permit `--approve`" in ln, ln
        if "review state" in ln and "If no dispatcher" not in ln:
            assert "do not set" in ln or "never sets" in ln, ln


# covers hub-tooling FR-0012:AC-8
def test_pre_fr_verdict_bullet_fails_the_ac8_detector_and_the_new_one_extends_it():
    """Adversarial: FR-0006 AC-7's wording alone is not AC-8 — the detector
    rejects it — and the new bullet is that wording extended, not replaced, up
    to "The dispatcher posts that message to the PR as the review" (DEC-0019
    Decision 3; the retired `REVIEW.md` clause after it is replaced)."""
    gaps = _ac8_gaps(_PRE_FR_DISPATCHER_VERDICT_LINE, _DEC0018_REVIEW_MD)
    assert gaps == [
        *(f"missing: {c}" for c in _DEC0018_REVIEW_MD),
        "missing: do not set a GitHub approval state",
        "missing: authored by the same account",
        "missing: as a comment",
    ]
    text = _source("reviewer").decode("utf-8")
    line = _line_containing(
        text, "If a dispatcher is configured**: your final assistant message"
    )
    kept = "The dispatcher posts that message to the PR as the review"
    prefix = _PRE_FR_DISPATCHER_VERDICT_LINE[
        : _PRE_FR_DISPATCHER_VERDICT_LINE.index(kept) + len(kept)
    ]
    assert line.startswith(prefix)


# ---------------------------------------------------------------------------
# AC-9: every canonical command has both wrappers, regenerated from source
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0012:AC-9
def test_every_canonical_command_has_both_wrappers_in_generated_form():
    sources = sorted(p.name for p in _COMMANDS_DIR.glob("*.md"))
    assert len(sources) >= 10
    assert {f"{n}.md" for n in _CONDUCT + _NO_BLOCK} <= set(sources)
    for harness in (".claude", ".cursor"):
        assert (
            sorted(p.name for p in (_TEMPLATE_DIR / harness / "commands").glob("*.md"))
            == sources
        ), harness
    assert _wrapper_failures(_TEMPLATE_DIR) == []


# covers hub-tooling FR-0012:AC-9
@pytest.mark.parametrize("name", [p.stem for p in sorted(_COMMANDS_DIR.glob("*.md"))])
def test_cursor_wrapper_differs_from_claude_only_by_claude_only_keys_and_args(name):
    claude = (_TEMPLATE_DIR / ".claude" / "commands" / f"{name}.md").read_bytes()
    cursor = (_TEMPLATE_DIR / ".cursor" / "commands" / f"{name}.md").read_bytes()
    claude_fm, claude_rest = _split_frontmatter(claude)
    cursor_fm, cursor_rest = _split_frontmatter(cursor)
    cursor_keys = [ln.split(b":", 1)[0].decode() for ln in cursor_fm]
    assert cursor_keys[0] == "description"
    assert set(cursor_keys) <= {"description", "argument-hint"}
    extra = [ln for ln in claude_fm if ln not in cursor_fm]
    assert [
        ln for ln in claude_fm if ln in cursor_fm
    ] == cursor_fm  # shared keys, same order
    assert {ln.split(b":", 1)[0].decode() for ln in extra} <= _CLAUDE_ONLY_KEYS
    assert cursor_rest == claude_rest.replace(b"$ARGUMENTS", b"{{args}}")
    assert b"$ARGUMENTS" not in cursor_rest


# covers hub-tooling FR-0012:AC-9
def test_docs_wrapper_carries_the_claude_only_keys_from_command_meta():
    """DEC-0004 Cascade: `docs.md` was missing under both harnesses; its
    `.claude` variant carries `model`, `effort` and `allowed-tools`, the
    `.cursor` variant none of them."""
    claude_fm, _ = _split_frontmatter(
        (_TEMPLATE_DIR / ".claude" / "commands" / "docs.md").read_bytes()
    )
    cursor_fm, _ = _split_frontmatter(
        (_TEMPLATE_DIR / ".cursor" / "commands" / "docs.md").read_bytes()
    )
    keys = [ln.split(b":", 1)[0].decode() for ln in claude_fm]
    assert keys == ["description", "argument-hint", "model", "effort", "allowed-tools"]
    assert [ln.split(b":", 1)[0].decode() for ln in cursor_fm] == [
        "description",
        "argument-hint",
    ]


# covers hub-tooling FR-0012:AC-9
def test_committed_wrappers_equal_generate_commands_output_after_lf_normalisation(
    tmp_path,
):
    count, copy = _regenerate(_TEMPLATE_DIR, tmp_path)
    sources = sorted(p.name for p in _COMMANDS_DIR.glob("*.md"))
    assert count == len(sources)
    for harness in (".claude", ".cursor"):
        for name in sources:
            committed = (_TEMPLATE_DIR / harness / "commands" / name).read_bytes()
            assert b"\r" not in committed, (harness, name)
            assert committed == _generated(copy, harness, name), (harness, name)


# covers hub-tooling FR-0012:AC-9
def test_generator_is_deterministic_over_the_template_sources(tmp_path):
    """Two runs, two copies, identical bytes — so equality with the committed
    wrappers is a property of the sources, not of the run."""
    _, a = _regenerate(_TEMPLATE_DIR, tmp_path / "a")
    _, b = _regenerate(_TEMPLATE_DIR, tmp_path / "b")
    for harness in (".claude", ".cursor"):
        for name in sorted(p.name for p in _COMMANDS_DIR.glob("*.md")):
            assert (a / harness / "commands" / name).read_bytes() == (
                b / harness / "commands" / name
            ).read_bytes()


# covers hub-tooling FR-0012:AC-9
def test_a_hand_edited_wrapper_fails_both_checks(tmp_path):
    root = _copy_template(tmp_path)
    target = root / ".cursor" / "commands" / "developer.md"
    data = target.read_bytes()
    target.write_bytes(
        data.replace(
            b"never end your turn with a question",
            b"never end your turn with a question!",
            1,
        )
    )
    assert _wrapper_failures(root) == [
        ".cursor/commands/developer.md: body differs from source"
    ]
    if _generator() is not None:
        _, copy = _regenerate(root, tmp_path / "gen")
        assert target.read_bytes() != _generated(copy, ".cursor", "developer.md")


# covers hub-tooling FR-0012:AC-9
def test_a_missing_wrapper_and_a_stale_stub_wrapper_fail(tmp_path):
    root = _copy_template(tmp_path)
    (root / ".claude" / "commands" / "docs.md").unlink()
    (root / ".cursor" / "commands" / "architect.md").write_bytes(_STALE_STUB)
    assert _wrapper_failures(root) == [
        ".cursor/commands/architect.md: no frontmatter",
        ".claude/commands/docs.md: missing",
    ]


# covers hub-tooling FR-0012:AC-9
def test_a_crlf_wrapper_is_reported_even_when_its_content_matches(tmp_path):
    """The committed form is LF; a CRLF file with the right content is the
    generator's raw Windows output, not the committed artifact."""
    root = _copy_template(tmp_path)
    target = root / ".claude" / "commands" / "gate.md"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    failures = _wrapper_failures(root)
    assert failures and failures[0] == ".claude/commands/gate.md: CRLF"


# ---------------------------------------------------------------------------
# AC-10: nothing else in the five sources changed
# ---------------------------------------------------------------------------


# The instructions AC-10 names as surviving verbatim, as the pre-FR sources
# carried them. These run everywhere, including inside bootstrapped projects.
_SURVIVING_LINES = {
    "developer": (
        "1. Read `AGENTS.md`. If it still contains `<<REPLACE: ...>>` markers, **stop and tell the user the project hasn't been bootstrapped**.",
        "1. Set the FR's `status` to `in-progress` and bump `updated` (this is the one frontmatter edit Developers may make).",
        "   - **If no dispatcher**: Save it to `PR_BODY.md` if the user wants you to draft it without opening a PR; otherwise create the PR via `gh pr create`.",
        "Hard limit: if you've pushed three rounds of changes for the same FR after Reviewer feedback, **stop and escalate to the human**. Three rounds means the spec is wrong.",
    ),
    "reviewer": (
        "   - **If a dispatcher is configured** (check: does `scripts/dispatch.py` exist?): stage every path you want in the handoff with `git add tests/`. Committing is optional — the dispatcher's `finalize --role rev` commits the staged index verbatim before it pushes. Unstaged and untracked changes are **not** part of the handoff; the dispatcher warns about them and never adds them for you.",
        '   - **If no dispatcher**: `git add tests/` then `git commit -m "test($ARGUMENTS): reviewer tests and fixtures"`. If no remote is configured, that is fine — leave the commit local; the human handles push / PR / merge.',
        "5. Hand off: tell the user the PR is approved and ready for human merge.",
        "When something needs to go back:",
    ),
    "maintainer": (
        "## Your footprint is the FR, and only the FR",
        "- **Never widen a permission set as a side effect.** If your change touches `ROLE_PERMISSIONS`, state in the PR body exactly which role's grants changed and why an AC required it.",
        "## Deliverables",
    ),
    "reviewer-backfill": (
        "- **Do not modify `src/**` or `config/**`.** The implementation is already merged. If a test cannot be made to pass against the merged code, that is a defect in the merged code; record it in the PR description and request a follow-up FR. Do not silently fix.",
        "- **Do not flip frontmatter status.** It's already `merged`.",
        "## What you must NOT do",
    ),
    "orchestrator": (
        "**Phase 2: Dispatch the wave (default)**",
        "python scripts/dispatch.py wave --fr <FR-IDs> --apply",
        "- **Always pass `--fr <FR-IDs>`.** A bare `wave` spawns a Developer for *every* runnable FR. Omit `--fr` only when a human explicitly names fleet-wide intent.",
        "**Hard limits:**",
        "- 1 retry per phase maximum. After that, escalate to human.",
        "- Never resolve escalations yourself — route them.",
        "- Never implement your own liveness or completion polling — use `wave`'s monitor or `dispatch.py status`.",
    ),
}


# covers hub-tooling FR-0012:AC-10
@pytest.mark.parametrize("name", _CONDUCT)
def test_named_existing_instructions_survive_verbatim(name):
    lines = _source(name).decode("utf-8").split("\n")
    for expected in _SURVIVING_LINES[name]:
        assert expected in lines, (name, expected)


# covers hub-tooling FR-0012:AC-10
# covers hub-tooling FR-0019:AC-6
@pytest.mark.parametrize("name", _CONDUCT)
def test_source_minus_the_block_equals_the_pre_fr_source_apart_from_ac8(name):
    """Build the expected residual: the pre-FR text, plus only the edits the
    AC permits — the opening-sentence split that seats the block (placement),
    and AC-8's restatement in `reviewer.md` / `orchestrator.md`. Any other
    changed line is a failure. The head side is FR-0012's merge commit, not
    HEAD (DEC-0016 Decision 2): AC-10 is a statement about FR-0012's diff."""
    pre = _pre_fr(name)
    assert _extract_block(pre) is None, name  # the block is this FR's
    ops = _residual_opcodes(_at_fr0012_merge(name), pre)
    if name in ("maintainer", "reviewer-backfill"):
        assert ops == [], ops
        return
    assert ops and ops[0][0] == "replace" and _is_opening_sentence_split(*ops[0][1:]), (
        ops[0]
    )
    rest = ops[1:]
    if name == "developer":
        assert rest == [], rest
    elif name == "reviewer":
        # AC-8: the two verdict bullets, each extended — the old line is a
        # prefix of the new one (modulo the old full stop), nothing removed.
        assert len(rest) == 1 and rest[0][0] == "replace", rest
        old, new = rest[0][1], rest[0][2]
        assert len(old) == 2 and len(new) == 2
        for o, n in zip(old, new):
            assert n.startswith(o.rstrip(".")), (o, n)
        assert (
            "If a dispatcher is configured" in old[0] and "If no dispatcher" in old[1]
        )
        assert _ac8_gaps(new[0]) == []
    else:  # orchestrator
        assert len(rest) == 1 and rest[0][0] == "insert", rest
        inserted = rest[0][2]
        assert inserted[1] == ""
        assert inserted[0].startswith(
            "The Reviewer's verdict is its final assistant message"
        )
        assert "GitHub approval state" in inserted[0]
        # At FR-0012's merge the insert is AC-8's two lines only; FR-0008's
        # later block is not FR-0012's diff (DEC-0016 Decision 2).
        assert len(inserted) == 2, inserted


# covers hub-tooling FR-0012:AC-10
def test_any_other_changed_line_is_reported(tmp_path):
    """Adversarial: the residual check is not satisfied by "mostly the same".
    The untampered head is FR-0012's merge (DEC-0016 Decision 2)."""
    pre = _pre_fr("maintainer")
    head = _at_fr0012_merge("maintainer")
    assert _residual_opcodes(head, pre) == []
    tampered = head.replace(b"## Deliverables", b"## Deliverables (draft)", 1)
    assert tampered != head
    ops = _residual_opcodes(tampered, pre)
    assert ops == [("replace", ["## Deliverables"], ["## Deliverables (draft)"])]


# covers hub-tooling FR-0012:AC-10
def test_pre_fr_wrappers_for_the_five_conduct_commands_lacked_the_block():
    """The block reaches agents through regenerated wrappers, not through
    edits to files the generator would overwrite: the pre-FR wrappers had no
    block and the committed ones carry the source's, verbatim."""
    for name in _CONDUCT:
        pre = _pre_fr(name)
        assert _HEADING not in pre
        source_block = _extract_block(_source(name))
        assert source_block is not None
        for harness, expected in (
            (".claude", source_block),
            (".cursor", source_block.replace(b"$ARGUMENTS", b"{{args}}")),
        ):
            wrapper = (_TEMPLATE_DIR / harness / "commands" / f"{name}.md").read_bytes()
            assert _extract_block(wrapper) == expected, (harness, name)


# covers hub-tooling FR-0012:AC-10
@pytest.mark.parametrize("name", _CONDUCT + _NO_BLOCK)
def test_every_source_and_wrapper_this_fr_touches_is_lf_and_newline_terminated(name):
    for path in (
        _COMMANDS_DIR / f"{name}.md",
        _TEMPLATE_DIR / ".claude" / "commands" / f"{name}.md",
        _TEMPLATE_DIR / ".cursor" / "commands" / f"{name}.md",
    ):
        data = path.read_bytes()
        assert b"\r" not in data, path
        assert data.endswith(b"\n") and not data.endswith(b"\n\n"), path
