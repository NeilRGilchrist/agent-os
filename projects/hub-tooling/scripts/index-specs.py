#!/usr/bin/env python3
"""
index-specs.py — Build a flat index of the spec objects in specs/

Reads YAML frontmatter from every specs/FR-*.md file and writes a Markdown
table to specs/INDEX.md showing id, title, status, version, lifecycle, owner,
and dependencies. Also discovers Technical Requirements (specs/TR-*.md) and
Decisions (specs/decisions/DEC-*.md) — FR-0004 — and renders them as
`## Technical requirements` and `## Decisions` tables, and discovers
specs/decisions/ADR-*.md and renders an ADR table (FR-0003).

Also performs basic validation:
- No duplicate FR / TR / DEC IDs
- All depends_on / extends / supersedes / superseded_by references resolve to
  existing objects of the same type; DEC `constrained_by` / `revises` and TR
  `operationalises` resolve to FRs (or TRs); FR and TR `revisions` entries
  resolve to DEC files
- Required frontmatter fields are present
- The optional versioning block and solution-space fields (FR-0003) have the
  right shape; every one of them defaults when absent so pre-existing FRs
  keep validating unchanged

Warn-only (never changes the exit code): AC ratification drift, versioning
arithmetic / supersession symmetry / DEC reciprocity and breaking-marker
checks (`## Versioning warnings`), and ADR structure (`## ADR warnings`).

Coverage exemptions (FR-0026): an `ac_state` entry in `deferred`, `withdrawn`
or `superseded` with a valid `moved_to` exempts its AC from the deploy gate's
coverage check; `coverage_exemptions()` is the gate's one entry point. Every
`deferred` one is listed under `## Open deferrals`, and IDEA pointers are
checked against the hub parking lot on stderr when a hub is found.

Supersession-aware (FR-0005, H2): the FR, TR and DEC tables list only the
default view (live + draft objects, DECs since `last_breaking_revision`);
everything else moves to `## Retired objects`, and live provisional DECs are
listed under `## Provisional decisions`. The liveness rules live in the pure
sibling module `spec_query.py`. Read-only query modes — `--list`, `--slice`,
`--provisional`, each with `--json` — expose the same view to H1 / H7 and
write nothing.

Exits 0 on success, non-zero on validation failure (so it can run in CI).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# spec_footprint is a sibling module providing pure functions for FR footprint
# metadata (owns:/reads: globs), overlap reporting, and CODEOWNERS emission.
# This script orchestrates I/O (file reads, git ls-files, file writes).
from spec_footprint import (
    FRRecord,
    Footprint,
    FootprintInvalid,
    find_overlaps,
    parse_footprint,
    _git_ls_files,
)

# spec_query is the pure sibling module answering "what is live?" (FR-0005):
# visibility classes, the default view, revision windows, the slice query and
# the provisional report. This script only feeds it parsed objects.
from spec_query import (
    dec_window_class,
    in_default_view,
    normalise_include,
    object_type,
    provisional,
    retired_reason,
    select,
    slice as slice_graph,
    visibility,
)

# metrics_log is the append-only pipeline metrics log (FR-0002). The indexer
# only *reads* it, to render `## Pipeline metrics` into INDEX.md; it is
# optional so a project whose scripts/ predates the module still indexes.
try:
    import metrics_log as _metrics_log
except ImportError:  # pragma: no cover — partially-upgraded project
    _metrics_log = None

# project_layout reads the project's optional `.agent-team/layout.yaml`
# (FR-0023). The indexer only validates it, so a malformed layout fails every
# mode that reports graph errors; it is optional so a copy of this script with
# no sibling project_layout.py indexes exactly as before.
try:
    import project_layout as _project_layout
except ImportError:  # pragma: no cover — partially-upgraded project
    _project_layout = None


REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
INDEX_PATH = SPECS_DIR / "INDEX.md"
CODEOWNERS_PATH = REPO_ROOT / "CODEOWNERS"
CODEOWNERS_CONFIG_PATH = REPO_ROOT / ".agent-team" / "codeowners-config.yaml"

REQUIRED_FIELDS = {"id", "title", "status", "owner", "created", "updated"}
VALID_STATUSES = {
    "draft",
    "ready",
    "in-progress",
    "in-review",
    "merged",
    "deprecated",
    "blocked",
}

FR_FILE_PATTERN = re.compile(r"^FR-\d{4}-.+\.md$")
FR_ID_PATTERN = re.compile(r"^FR-\d{4}$")
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
AC_LINE_PATTERN = re.compile(r"^-\s+\*\*AC-(\d+):\*\*\s*(.*)$")
# The labelled form `- **AC-N (L):** R`: a non-empty label `L` that ends at the
# first `):**` on the line. @implements FR-0027:AC-1
AC_LABELLED_LINE_PATTERN = re.compile(
    r"^-\s+\*\*AC-(\d+)[ \t]+\(((?:(?!\):\*\*).)+)\):\*\*\s*(.*)$"
)

# Per-AC ratification lifecycle (Lockstep N-4). A ratified AC whose text later
# changes is drift — reported as needing re-review (warn-only for now).
# `deferred` and `withdrawn` (FR-0026) join `superseded` as exemption states:
# an entry in one of the three, with a `moved_to` pointer naming where the
# work went, exempts its AC from the deploy gate's coverage check.
# @implements FR-0026:AC-1
AC_STATES = {
    "proposed",
    "refined",
    "client-review",
    "ratified",
    "superseded",
    "deferred",
    "withdrawn",
}
AC_EXEMPT_STATES = frozenset({"deferred", "withdrawn", "superseded"})
# A `moved_to` pointer: a local FR, DEC or ADR, or a hub IDEA. ASCII digits
# only, matched in full (no trailing newline). @implements FR-0026:AC-1
MOVED_TO_PATTERN = re.compile(r"(FR|IDEA|ADR|DEC)-[0-9]{4}")
# The section holding the text of withdrawn and superseded ACs. @implements FR-0026:AC-5
WITHDRAWN_ACS_HEADING = "Withdrawn acceptance criteria"

# Declared gates (FR-0008:AC-1): an FR's optional `gates:` frontmatter list.
# Closed vocabularies the dispatcher and deploy-gate.py share via this module.
GATE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
GATE_AFTER_VALUES = {"dev", "rev"}
GATE_REVIEWER_VALUES = {"human", "architect"}
GATE_ALLOWED_KEYS = {"id", "after", "reviewer", "scope"}

# Shared versioning block (FR-0003; FR-0004 applies the identical block to TRs).
# `lifecycle` is the identity axis (is this object current?) and is orthogonal
# to the workflow `status` above. See specs/decisions/README.md ->
# "Revision vs supersession" for the rule that drives these fields.
LIFECYCLES = {"draft", "live", "superseded"}
VARIABILITIES = {"core", "configurable", "tenant_specific"}
DEC_ID_PATTERN = re.compile(r"^DEC-\d{4}$")
GOAL_ID_PATTERN = re.compile(r"^GOAL-[A-Za-z0-9-]+$")
SOLUTION_SPACE_KEYS = ("open", "fixed")

# Technical requirements (FR-0004): specs/TR-NNNN-<slug>.md. The versioning
# block above applies verbatim; TRs have no workflow `status` or `owner`.
TR_FILE_PATTERN = re.compile(r"^TR-\d{4}-.+\.md$")
TR_ID_PATTERN = re.compile(r"^TR-\d{4}$")
TR_REQUIRED_FIELDS = {"id", "title", "operationalises", "created", "updated"}

# Decisions (FR-0004): specs/decisions/DEC-NNNN-<slug>.md, beside the ADRs.
# `tier` is a free string here — the vocabulary is a project-profile overlay.
DEC_FILE_PATTERN = re.compile(r"^DEC-\d{4}-.+\.md$")
DEC_REQUIRED_FIELDS = {"id", "title", "tier", "status", "rationale", "created", "updated"}
DEC_STATUSES = {"proposed", "ratified", "rejected", "superseded"}
# A live DEC is one the design proceeds on (FR-0004 liveness table).
LIVE_DEC_STATUSES = {"proposed", "ratified"}
REVERSIBILITIES = {"high", "medium", "low"}

# Architecture decision records (FR-0003). Discovery and lint are warn-only:
# projects have ADRs written before the template carried the deviation sections.
DECISIONS_DIR = SPECS_DIR / "decisions"
ADR_FILE_PATTERN = re.compile(r"^ADR-\d{4}-.+\.md$")
ADR_ID_PATTERN = re.compile(r"^ADR-\d{4}$")
# Vocabulary shared with render-docs.py (BROKEN_ADR_STATUSES + "accepted").
ADR_STATUSES = {"proposed", "accepted", "superseded", "rejected", "deprecated"}
ADR_DEVIATION_SECTIONS = (
    "When you may deviate",
    "What you must record when you deviate",
)


@dataclass
class FR:
    path: Path
    id: str
    title: str
    status: str
    owner: str
    depends_on: list[str]
    tags: list[str]
    derived_from: str | None
    pattern: str | None
    created: str
    updated: str
    owns: tuple[str, ...]
    reads: tuple[str, ...]
    acs: dict[int, str] = field(default_factory=dict)
    ac_state: dict = field(default_factory=dict)
    # Shared versioning block (@implements FR-0003:AC-10). Attribute names are
    # exactly the frontmatter keys; defaults are the "absent" values (AC-2).
    version: int = 1
    lifecycle: str = "live"
    revisions: list[str] = field(default_factory=list)
    last_breaking_revision: int | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    # FR-only solution-space fields (plan WS1c).
    extends: list[str] = field(default_factory=list)
    serves_roles: list[str] = field(default_factory=list)
    solution_space: dict[str, list[str]] = field(
        default_factory=lambda: {"open": [], "fixed": []}
    )
    goal: str | None = None
    success_criteria: list[str] = field(default_factory=list)
    asserted_by: list[str] = field(default_factory=list)
    variability: str | None = None
    # @implements FR-0008:AC-1 — declared pre-review/pre-merge gates, each
    # {id, after, reviewer, scope}. Default () — "no gates" is the default,
    # appended last so existing positional FR(...) construction is unaffected.
    gates: tuple[dict, ...] = field(default_factory=tuple)
    # @implements FR-0026:AC-5 — {AC number: raw text} from the body's
    # `## Withdrawn acceptance criteria` section, kept apart from `acs` (whose
    # hashes and `--ac-hashes` output it never touches). Body text, so
    # `--slice --json` does not serialise it; defaulted so `FR(...)` built
    # without it still works.
    withdrawn_acs: dict[int, str] = field(default_factory=dict)


@dataclass
class ADR:
    """A discovered specs/decisions/ADR-*.md. Every problem with an ADR is a
    warning carried on the record (never an error), so a malformed ADR still
    renders a row in INDEX.md and `--validate` still exits 0."""

    path: Path
    id: str
    title: str
    status: str | None
    updated: str
    has_deviation_sections: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class TR:
    """A parsed specs/TR-NNNN-<slug>.md. Attribute names equal the frontmatter
    keys (@implements FR-0004:AC-10); the versioning block is FR-0003's, with
    the same defaults."""

    path: Path
    id: str
    title: str
    operationalises: list[str]
    created: str
    updated: str
    version: int = 1
    lifecycle: str = "live"
    revisions: list[str] = field(default_factory=list)
    last_breaking_revision: int | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    implemented_by: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)


@dataclass
class DEC:
    """A parsed specs/decisions/DEC-NNNN-<slug>.md. Attribute names equal the
    frontmatter keys (@implements FR-0004:AC-10); defaults are the "absent"
    values from the FR-0004 field table."""

    path: Path
    id: str
    title: str
    tier: str
    status: str
    rationale: str
    created: str
    updated: str
    satisfies: list[str] = field(default_factory=list)
    constrained_by: list[str] = field(default_factory=list)
    revises: str | None = None
    breaking: bool = False
    authorised_by: list[str] = field(default_factory=list)
    invokes_exception: str | None = None
    alternatives: list[str] = field(default_factory=list)
    reversibility: str | None = None
    provisional_until: str | None = None
    client_visible: bool = False
    supersedes: str | None = None
    superseded_by: str | None = None


@dataclass
class SpecGraph:
    """Everything `collect_graph()` discovers under specs/, plus the merged
    parse + resolution error list (empty when the tree is valid)."""

    frs: list[FR] = field(default_factory=list)
    trs: list[TR] = field(default_factory=list)
    decs: list[DEC] = field(default_factory=list)
    adrs: list[ADR] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_live(obj) -> bool:  # type: ignore[no-untyped-def]
    """Liveness predicate for any versioned object (FR, TR): live iff its
    identity lifecycle is `live`. @implements FR-0003:AC-10"""
    return obj.lifecycle == "live"


def is_live_dec(dec) -> bool:  # type: ignore[no-untyped-def]
    """Liveness predicate for a Decision: the design proceeds on `proposed`
    and `ratified` DECs; `rejected` and `superseded` ones are history.
    @implements FR-0004:AC-10"""
    return dec.status in LIVE_DEC_STATUSES


def _section_body(text: str, heading: str) -> str:
    """Return the body of a `## <heading>` section, up to the next `## `."""
    out: list[str] = []
    in_section = False
    want = heading.strip().lower()
    for line in text.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            in_section = line[3:].strip().lower() == want
            continue
        if in_section:
            out.append(line)
    return "\n".join(out)


def parse_acs(text: str) -> dict[int, str]:
    """Return {AC number: raw text} from the Acceptance criteria section. An AC
    spans its bullet line through any continuation lines up to the next AC
    bullet, so multi-line ACs hash on their full text. A labelled bullet
    `- **AC-N (L):** R` reads as `(L) R`, the text of `- **AC-N:** (L) R`.
    @implements FR-0027:AC-1, FR-0027:AC-2"""
    return _parse_ac_bullets(_section_body(text, "Acceptance criteria"))


def parse_withdrawn_acs(text: str) -> dict[int, str]:
    """Return {AC number: raw text} from the `## Withdrawn acceptance criteria`
    section (heading matched case-insensitively), with exactly `parse_acs`'s
    bullet rules: `AC_LINE_PATTERN` or `AC_LABELLED_LINE_PATTERN` at column 0,
    a labelled bullet reading as `(L) R`. Any other line in the section — the
    legacy `- **[DEPRECATED] AC-N**` form included — is continuation text of
    the bullet above it, or ignored before the first bullet.
    @implements FR-0026:AC-5"""
    return _parse_ac_bullets(_section_body(text, WITHDRAWN_ACS_HEADING))


def _parse_ac_bullets(section: str) -> dict[int, str]:
    acs: dict[int, str] = {}
    current: int | None = None
    label = ""
    buf: list[str] = []
    for line in section.splitlines():
        m = AC_LINE_PATTERN.match(line)
        lm = None if m else AC_LABELLED_LINE_PATTERN.match(line)
        if m or lm:
            if current is not None:
                acs[current] = _ac_text(label, buf)
            if m:
                current, label, buf = int(m.group(1)), "", [m.group(2)]
            else:
                current, label = int(lm.group(1)), f"({lm.group(2)})"
                buf = [lm.group(3)]
        elif current is not None:
            buf.append(line)
    if current is not None:
        acs[current] = _ac_text(label, buf)
    return acs


def _ac_text(label: str, buf: list[str]) -> str:
    text = "\n".join(buf).strip()
    if not label:
        return text
    return f"{label} {text}" if text else label


def normalize_ac_text(text: str) -> str:
    """Whitespace-insensitive normalization, so reflowing an AC does not read as
    a change. This is the contract a recorded `hash` is computed against."""
    return " ".join(text.split())


def ac_hash(text: str) -> str:
    return hashlib.sha256(normalize_ac_text(text).encode("utf-8")).hexdigest()


def _is_positive_int(value: object) -> bool:
    # bool is an int subclass; `version: true` is not a version.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _str_list(raw: object, name: str, key: str, errors: list[str]) -> list[str]:
    """Lift an optional list-of-non-empty-strings value. Absent (or explicit
    null) -> []. Anything else that is not a list of non-empty strings is a
    shape error naming the file and the field (`key` is the label used in the
    message, e.g. `solution_space.open`)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(
            f"{name}: {key} must be a list of non-empty strings (got {raw!r})"
        )
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            errors.append(
                f"{name}: {key} entry {item!r} must be a non-empty string"
            )
            continue
        out.append(item)
    return out


def _parse_versioning_block(
    meta: dict, name: str, errors: list[str], id_kind: str = "FR"
) -> dict:
    """Shape-validate the shared versioning block (FR-0003) for an FR or — with
    `id_kind="TR"` — a TR (@implements FR-0004:AC-3). An absent key, or an
    explicit `null`, yields the default silently; a present value with the
    wrong shape is an error naming the file and the field. `supersedes` /
    `superseded_by` are resolved later (`validate_graph` for FRs,
    `validate_references` for TRs); `revisions` entries are pattern-checked
    here and resolved to DEC files in `validate_references`."""
    out: dict = {}

    raw = meta.get("version")
    if raw is None:
        out["version"] = 1
    elif _is_positive_int(raw):
        out["version"] = raw
    else:
        errors.append(f"{name}: version must be an integer >= 1 (got {raw!r})")
        out["version"] = 1

    raw = meta.get("lifecycle")
    if raw is None:
        out["lifecycle"] = "live"
    elif isinstance(raw, str) and raw in LIFECYCLES:
        out["lifecycle"] = raw
    else:
        errors.append(f"{name}: lifecycle '{raw}' not in {sorted(LIFECYCLES)}")
        out["lifecycle"] = "live"

    raw = meta.get("revisions")
    revisions: list[str] = []
    if raw is None:
        pass
    elif not isinstance(raw, list):
        errors.append(
            f"{name}: revisions must be a list of DEC IDs (DEC-XXXX), got {raw!r}"
        )
    else:
        for item in raw:
            if not isinstance(item, str) or not DEC_ID_PATTERN.match(item):
                errors.append(f"{name}: revisions entry {item!r} must match DEC-XXXX")
                continue
            revisions.append(item)
    out["revisions"] = revisions

    raw = meta.get("last_breaking_revision")
    if raw is None:
        out["last_breaking_revision"] = None
    elif _is_positive_int(raw):
        out["last_breaking_revision"] = raw
    else:
        errors.append(
            f"{name}: last_breaking_revision must be an integer >= 1 or null "
            f"(got {raw!r})"
        )
        out["last_breaking_revision"] = None

    for key in ("supersedes", "superseded_by"):
        raw = meta.get(key)
        if raw is None:
            out[key] = None
        elif isinstance(raw, str) and raw.strip():
            out[key] = raw
        else:
            errors.append(
                f"{name}: {key} must be a{'n' if id_kind == 'FR' else ''} {id_kind} ID "
                f"({id_kind}-XXXX) or null (got {raw!r})"
            )
            out[key] = None

    return out


def _parse_versioning_fields(meta: dict, name: str, errors: list[str]) -> dict:
    """Shape-validate the shared versioning block and the FR-only solution-space
    fields (FR-0003). Returns a kwargs dict for `FR`. An absent key — or an
    explicit `null`, which this parser treats the same way — yields the default
    silently (@implements FR-0003:AC-2); a present value with the wrong shape is
    an error naming the file and the field (@implements FR-0003:AC-3).
    References (`extends`, `supersedes`, `superseded_by`) are resolved later in
    `validate_graph`."""
    out = _parse_versioning_block(meta, name, errors, "FR")

    raw = meta.get("extends")
    if raw is None:
        out["extends"] = []
    elif not isinstance(raw, list):
        errors.append(f"{name}: extends must be a list of FR IDs (got {raw!r})")
        out["extends"] = []
    else:
        out["extends"] = [str(x) for x in raw]

    for key in ("serves_roles", "success_criteria", "asserted_by"):
        out[key] = _str_list(meta.get(key), name, key, errors)

    raw = meta.get("solution_space")
    solution_space: dict[str, list[str]] = {"open": [], "fixed": []}
    if raw is None:
        pass
    elif not isinstance(raw, dict):
        errors.append(
            f"{name}: solution_space must be a mapping with keys "
            f"{list(SOLUTION_SPACE_KEYS)} (got {raw!r})"
        )
    else:
        missing = [k for k in SOLUTION_SPACE_KEYS if k not in raw]
        unknown = sorted(str(k) for k in raw if k not in SOLUTION_SPACE_KEYS)
        if missing:
            errors.append(f"{name}: solution_space is missing key(s) {missing}")
        if unknown:
            errors.append(f"{name}: solution_space has unknown key(s) {unknown}")
        for k in SOLUTION_SPACE_KEYS:
            if k in raw:
                solution_space[k] = _str_list(
                    raw.get(k), name, f"solution_space.{k}", errors
                )
    out["solution_space"] = solution_space

    raw = meta.get("goal")
    if raw is None:
        out["goal"] = None
    elif isinstance(raw, str) and GOAL_ID_PATTERN.match(raw):
        out["goal"] = raw
    else:
        errors.append(f"{name}: goal must match GOAL-<slug> or be null (got {raw!r})")
        out["goal"] = None

    raw = meta.get("variability")
    if raw is None:
        out["variability"] = None
    elif isinstance(raw, str) and raw in VARIABILITIES:
        out["variability"] = raw
    else:
        errors.append(
            f"{name}: variability '{raw}' not in {sorted(VARIABILITIES)} (or null)"
        )
        out["variability"] = None

    return out


def _parse_gates_field(meta: dict, name: str, errors: list[str]) -> tuple[dict, ...]:
    """Lift the optional `gates:` frontmatter list (FR-0008:AC-1).

    Absent or explicit `null` -> `()` — "no gates" is the default, and
    FRs written before this key existed need no edits. Every shape problem
    (missing/unknown key, duplicate id, out-of-vocabulary `after`/`reviewer`,
    empty `scope`, a non-list value) is an error naming the FR (`name`) and
    the offending gate (its position, and its `id` once that much parses).
    """
    raw = meta.get("gates")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        errors.append(f"{name}: gates must be a list (got {raw!r})")
        return ()
    seen_ids: set[str] = set()
    out: list[dict] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"{name}: gates[{i}] must be a mapping (got {entry!r})")
            continue
        keys = set(entry.keys())
        missing_keys = GATE_ALLOWED_KEYS - keys
        extra_keys = keys - GATE_ALLOWED_KEYS
        if missing_keys or extra_keys:
            errors.append(
                f"{name}: gates[{i}] must have exactly the keys "
                f"{sorted(GATE_ALLOWED_KEYS)} (missing {sorted(missing_keys)}, "
                f"unknown {sorted(extra_keys)})"
            )
            continue
        gate_id = str(entry.get("id", ""))
        if not GATE_ID_PATTERN.match(gate_id):
            errors.append(
                f"{name}: gates[{i}].id '{gate_id}' must match "
                f"'{GATE_ID_PATTERN.pattern}'"
            )
            continue
        if gate_id in seen_ids:
            errors.append(f"{name}: duplicate gate id '{gate_id}'")
            continue
        after = str(entry.get("after", ""))
        if after not in GATE_AFTER_VALUES:
            errors.append(
                f"{name}: gate '{gate_id}'.after '{after}' not in "
                f"{sorted(GATE_AFTER_VALUES)}"
            )
            continue
        reviewer = str(entry.get("reviewer", ""))
        if reviewer not in GATE_REVIEWER_VALUES:
            errors.append(
                f"{name}: gate '{gate_id}'.reviewer '{reviewer}' not in "
                f"{sorted(GATE_REVIEWER_VALUES)}"
            )
            continue
        scope = entry.get("scope")
        if not isinstance(scope, str) or not scope.strip() or "\n" in scope:
            errors.append(
                f"{name}: gate '{gate_id}'.scope must be a non-empty, "
                f"one-line string"
            )
            continue
        seen_ids.add(gate_id)
        out.append(
            {"id": gate_id, "after": after, "reviewer": reviewer, "scope": scope.strip()}
        )
    return tuple(out)


def parse_fr(path: Path) -> tuple[FR | None, list[str]]:
    """Parse a single FR file. Returns (fr, errors)."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return None, [f"{path.name}: missing YAML frontmatter"]

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        return None, [f"{path.name}: invalid YAML frontmatter: {e}"]

    missing = REQUIRED_FIELDS - set(meta.keys())
    if missing:
        errors.append(f"{path.name}: missing required fields: {sorted(missing)}")

    fr_id = str(meta.get("id", ""))
    if not FR_ID_PATTERN.match(fr_id):
        errors.append(f"{path.name}: id '{fr_id}' must match FR-XXXX")

    status = str(meta.get("status", ""))
    if status not in VALID_STATUSES:
        errors.append(f"{path.name}: status '{status}' not in {sorted(VALID_STATUSES)}")

    depends_on = meta.get("depends_on") or []
    if not isinstance(depends_on, list):
        errors.append(f"{path.name}: depends_on must be a list")
        depends_on = []

    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        errors.append(f"{path.name}: tags must be a list (or omitted)")
        tags = []

    derived_from = meta.get("derived_from")
    if derived_from is not None and not str(derived_from).startswith("IDEA-"):
        errors.append(
            f"{path.name}: derived_from must be 'IDEA-NNNN' or null (got '{derived_from}')"
        )

    pattern = meta.get("pattern")
    if pattern is not None and not str(pattern).startswith("PATTERN-"):
        errors.append(
            f"{path.name}: pattern must be 'PATTERN-NNNN' or null (got '{pattern}')"
        )

    versioning = _parse_versioning_fields(meta, path.name, errors)
    gates = _parse_gates_field(meta, path.name, errors)

    try:
        footprint = parse_footprint(meta)
    except FootprintInvalid as e:
        errors.append(f"{path.name}: {e}")
        return None, errors

    if errors:
        return None, errors

    # AC bodies + optional per-AC ratification state (Lockstep N-4). Neither is
    # required and neither can fail the build — ac_state issues are warn-only.
    acs = parse_acs(text[match.end():])
    withdrawn_acs = parse_withdrawn_acs(text[match.end() :])
    raw_ac_state = meta.get("ac_state")
    ac_state = raw_ac_state if isinstance(raw_ac_state, dict) else {}

    return (
        FR(
            path=path,
            id=fr_id,
            title=str(meta["title"]),
            status=status,
            owner=str(meta["owner"]),
            depends_on=[str(d) for d in depends_on],
            tags=[str(t) for t in tags],
            derived_from=str(derived_from) if derived_from else None,
            pattern=str(pattern) if pattern else None,
            created=str(meta["created"]),
            updated=str(meta["updated"]),
            owns=footprint.owns,
            reads=footprint.reads,
            gates=gates,
            acs=acs,
            ac_state=ac_state,
            withdrawn_acs=withdrawn_acs,
            **versioning,
        ),
        [],
    )


def collect_frs() -> tuple[list[FR], list[str]]:
    if not SPECS_DIR.exists():
        return [], [f"specs/ directory not found at {SPECS_DIR}"]

    frs: list[FR] = []
    errors: list[str] = []

    for path in sorted(SPECS_DIR.glob("FR-*.md")):
        if not FR_FILE_PATTERN.match(path.name):
            errors.append(f"{path.name}: filename does not match FR-XXXX-<slug>.md")
            continue
        fr, file_errors = parse_fr(path)
        if file_errors:
            errors.extend(file_errors)
        if fr:
            frs.append(fr)

    return frs, errors


def _load_frontmatter(path: Path) -> tuple[dict | None, list[str]]:
    """Read a spec file's YAML frontmatter as a dict. Returns (None, [error])
    when the frontmatter is missing or unparseable."""
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return None, [f"{path.name}: missing YAML frontmatter"]
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        return None, [f"{path.name}: invalid YAML frontmatter: {e}"]
    return (loaded if isinstance(loaded, dict) else {}), []


def _required_string(meta: dict, name: str, key: str, errors: list[str]) -> str:
    """Lift a required non-empty string field; absent/empty is an error naming
    the file and the field. Returns "" on error so parsing can continue."""
    raw = meta.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip() if key == "rationale" else raw
    if key in meta:
        errors.append(f"{name}: {key} must be a non-empty string (got {raw!r})")
    return ""


def _optional_string(meta: dict, name: str, key: str, errors: list[str]) -> str | None:
    """Lift an optional string-or-null field (dates are accepted and
    stringified, since YAML parses `2026-10-01` as a date)."""
    raw = meta.get(key)
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip():
        return raw
    if isinstance(raw, date):
        return raw.isoformat()
    errors.append(f"{name}: {key} must be a non-empty string or null (got {raw!r})")
    return None


def _bool_field(meta: dict, name: str, key: str, errors: list[str], default: bool) -> bool:
    raw = meta.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    errors.append(f"{name}: {key} must be a boolean (got {raw!r})")
    return default


def _id_list(
    raw: object, name: str, key: str, pattern: re.Pattern, kind: str, errors: list[str]
) -> list[str]:
    """Lift an optional list of IDs matching `pattern` (e.g. FR-XXXX). Absent
    or null -> []. A non-list or a non-matching entry is a shape error."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{name}: {key} must be a list of {kind} IDs ({kind}-XXXX), got {raw!r}")
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not pattern.match(item):
            errors.append(f"{name}: {key} entry {item!r} must match {kind}-XXXX")
            continue
        out.append(item)
    return out


def _reject_version_citations(entries: list[str], name: str, key: str, errors: list[str]) -> None:
    """Code and tests cite the stable ID only — `TR-0014@v2` is never valid.
    @implements FR-0004:AC-3"""
    for entry in entries:
        if "@" in entry:
            errors.append(
                f"{name}: {key} entry {entry!r} must not contain '@' "
                "(cite the stable ID, never a version)"
            )


def _check_id_and_filename(
    meta: dict, path: Path, prefix_len: int, id_pattern: re.Pattern, kind: str, errors: list[str]
) -> str:
    """The `id` must match `<kind>-XXXX` and equal the filename prefix.
    @implements FR-0004:AC-2"""
    obj_id = str(meta.get("id", ""))
    if not id_pattern.match(obj_id):
        errors.append(f"{path.name}: id '{obj_id}' must match {kind}-XXXX")
    elif obj_id != path.name[:prefix_len]:
        errors.append(
            f"{path.name}: id '{obj_id}' does not match filename prefix "
            f"'{path.name[:prefix_len]}'"
        )
    return obj_id


def parse_tr(path: Path) -> tuple[TR | None, list[str]]:
    """Parse one specs/TR-NNNN-<slug>.md. Returns (tr, errors); any error
    yields (None, errors) naming the file and the field.
    @implements FR-0004:AC-2, FR-0004:AC-3"""
    meta, errors = _load_frontmatter(path)
    if meta is None:
        return None, errors
    name = path.name

    missing = TR_REQUIRED_FIELDS - set(meta.keys())
    if missing:
        errors.append(f"{name}: missing required fields: {sorted(missing)}")

    tr_id = _check_id_and_filename(meta, path, 7, TR_ID_PATTERN, "TR", errors)
    title = _required_string(meta, name, "title", errors)

    raw = meta.get("operationalises")
    operationalises: list[str] = []
    if "operationalises" in meta:
        if not isinstance(raw, list) or not raw:
            errors.append(
                f"{name}: operationalises must be a non-empty list of FR IDs "
                f"(FR-XXXX), got {raw!r}"
            )
        else:
            operationalises = _id_list(raw, name, "operationalises", FR_ID_PATTERN, "FR", errors)

    versioning = _parse_versioning_block(meta, name, errors, "TR")

    tr_fields: dict[str, list[str]] = {}
    for key in ("implemented_by", "success_criteria", "tests"):
        tr_fields[key] = _str_list(meta.get(key), name, key, errors)
    for key in ("implemented_by", "tests"):
        _reject_version_citations(tr_fields[key], name, key, errors)

    for key in ("created", "updated"):
        if key in meta and meta.get(key) is None:
            errors.append(f"{name}: {key} must be a date")

    if errors:
        return None, errors
    return (
        TR(
            path=path,
            id=tr_id,
            title=title,
            operationalises=operationalises,
            created=str(meta["created"]),
            updated=str(meta["updated"]),
            **versioning,
            **tr_fields,
        ),
        [],
    )


def parse_dec(path: Path) -> tuple[DEC | None, list[str]]:
    """Parse one specs/decisions/DEC-NNNN-<slug>.md. Returns (dec, errors);
    any error yields (None, errors) naming the file and the field.
    @implements FR-0004:AC-2, FR-0004:AC-3"""
    meta, errors = _load_frontmatter(path)
    if meta is None:
        return None, errors
    name = path.name

    missing = DEC_REQUIRED_FIELDS - set(meta.keys())
    if missing:
        errors.append(f"{name}: missing required fields: {sorted(missing)}")

    dec_id = _check_id_and_filename(meta, path, 8, DEC_ID_PATTERN, "DEC", errors)
    title = _required_string(meta, name, "title", errors)
    tier = _required_string(meta, name, "tier", errors)
    rationale = _required_string(meta, name, "rationale", errors)

    status = str(meta.get("status", ""))
    if "status" in meta and status not in DEC_STATUSES:
        errors.append(f"{name}: status '{status}' not in {sorted(DEC_STATUSES)}")

    satisfies = _id_list(meta.get("satisfies"), name, "satisfies", GOAL_ID_PATTERN, "GOAL", errors)
    constrained_by = _id_list(
        meta.get("constrained_by"), name, "constrained_by", FR_ID_PATTERN, "FR", errors
    )
    authorised_by = _id_list(
        meta.get("authorised_by"), name, "authorised_by", ADR_ID_PATTERN, "ADR", errors
    )

    raw = meta.get("revises")
    revises: str | None = None
    if raw is not None:
        if isinstance(raw, str) and "@" in raw:
            errors.append(
                f"{name}: revises {raw!r} must not contain '@' "
                "(cite the stable ID, never a version)"
            )
        elif isinstance(raw, str) and (FR_ID_PATTERN.match(raw) or TR_ID_PATTERN.match(raw)):
            revises = raw
        else:
            errors.append(
                f"{name}: revises must be an FR ID (FR-XXXX), a TR ID (TR-XXXX) or null "
                f"(got {raw!r})"
            )

    # `breaking` is required exactly when there is something to break.
    # An explicit `breaking: null` counts as absent (FR-0003 convention).
    if raw is not None and meta.get("breaking") is None:
        errors.append(f"{name}: breaking is required when revises is set (got absent)")
    breaking = _bool_field(meta, name, "breaking", errors, False)
    client_visible = _bool_field(meta, name, "client_visible", errors, False)

    invokes_exception = _optional_string(meta, name, "invokes_exception", errors)
    provisional_until = _optional_string(meta, name, "provisional_until", errors)
    alternatives = _str_list(meta.get("alternatives"), name, "alternatives", errors)

    raw = meta.get("reversibility")
    reversibility: str | None = None
    if raw is not None:
        if isinstance(raw, str) and raw in REVERSIBILITIES:
            reversibility = raw
        else:
            errors.append(
                f"{name}: reversibility '{raw}' not in {sorted(REVERSIBILITIES)} (or null)"
            )

    links: dict[str, str | None] = {}
    for key in ("supersedes", "superseded_by"):
        raw = meta.get(key)
        if raw is None:
            links[key] = None
        elif isinstance(raw, str) and DEC_ID_PATTERN.match(raw):
            links[key] = raw
        else:
            errors.append(f"{name}: {key} must be a DEC ID (DEC-XXXX) or null (got {raw!r})")
            links[key] = None

    for key in ("created", "updated"):
        if key in meta and meta.get(key) is None:
            errors.append(f"{name}: {key} must be a date")

    if errors:
        return None, errors
    return (
        DEC(
            path=path,
            id=dec_id,
            title=title,
            tier=tier,
            status=status,
            rationale=rationale,
            created=str(meta["created"]),
            updated=str(meta["updated"]),
            satisfies=satisfies,
            constrained_by=constrained_by,
            revises=revises,
            breaking=breaking,
            authorised_by=authorised_by,
            invokes_exception=invokes_exception,
            alternatives=alternatives,
            reversibility=reversibility,
            provisional_until=provisional_until,
            client_visible=client_visible,
            **links,
        ),
        [],
    )


def collect_trs() -> tuple[list[TR], list[str]]:
    """Discover specs/TR-*.md (never specs/FR-*.md), mirroring `collect_frs`.
    @implements FR-0004:AC-2"""
    if not SPECS_DIR.exists():
        return [], []
    trs: list[TR] = []
    errors: list[str] = []
    for path in sorted(SPECS_DIR.glob("TR-*.md")):
        if not path.is_file():
            continue
        if not TR_FILE_PATTERN.match(path.name):
            errors.append(f"{path.name}: filename does not match TR-XXXX-<slug>.md")
            continue
        tr, file_errors = parse_tr(path)
        errors.extend(file_errors)
        if tr:
            trs.append(tr)
    return trs, errors


def collect_decs() -> tuple[list[DEC], list[str]]:
    """Discover specs/decisions/DEC-*.md (never ADR-*.md), mirroring
    `collect_frs`. @implements FR-0004:AC-2"""
    if not DECISIONS_DIR.exists():
        return [], []
    decs: list[DEC] = []
    errors: list[str] = []
    for path in sorted(DECISIONS_DIR.glob("DEC-*.md")):
        if not path.is_file():
            continue
        if not DEC_FILE_PATTERN.match(path.name):
            errors.append(f"{path.name}: filename does not match DEC-XXXX-<slug>.md")
            continue
        dec, file_errors = parse_dec(path)
        errors.extend(file_errors)
        if dec:
            decs.append(dec)
    return decs, errors


def _has_heading(text: str, heading: str) -> bool:
    want = heading.strip().lower()
    return any(
        line.startswith("## ") and line[3:].strip().lower() == want
        for line in text.splitlines()
    )


def parse_adr(path: Path) -> ADR:
    """Parse one ADR file. Never raises on content; every problem becomes a
    warning on the returned record. @implements FR-0003:AC-7"""
    warnings: list[str] = []
    name = path.name
    prefix = name[:8] if ADR_FILE_PATTERN.match(name) else None
    if prefix is None:
        warnings.append(f"{name}: filename does not match ADR-XXXX-<slug>.md")

    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(text)
    meta: dict | None = None
    if not match:
        warnings.append(f"{name}: missing YAML frontmatter")
    else:
        try:
            loaded = yaml.safe_load(match.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError as e:
            warnings.append(f"{name}: invalid YAML frontmatter: {e}")

    adr_id = prefix or path.stem
    title = "—"
    status: str | None = None
    updated = "—"
    if meta is not None:
        raw_id = str(meta.get("id") or "")
        if prefix is not None and raw_id != prefix:
            warnings.append(
                f"{name}: id '{raw_id}' does not match filename prefix '{prefix}'"
            )
        elif prefix is None and not ADR_ID_PATTERN.match(raw_id):
            warnings.append(f"{name}: id '{raw_id}' must match ADR-XXXX")
        if raw_id:
            adr_id = raw_id
        raw_status = meta.get("status")
        status = str(raw_status) if raw_status is not None else None
        if status not in ADR_STATUSES:
            warnings.append(
                f"{name}: status '{status or ''}' not in {sorted(ADR_STATUSES)}"
            )
        if meta.get("title"):
            title = str(meta["title"])
        if meta.get("updated"):
            updated = str(meta["updated"])

    # A missing/unparseable frontmatter is that file's one warning; do not
    # cascade into id/status/section findings the reader cannot act on yet.
    missing_sections: list[str] = []
    if meta is not None:
        body = text[match.end():]
        missing_sections = [h for h in ADR_DEVIATION_SECTIONS if not _has_heading(body, h)]
    if missing_sections:
        listed = ", ".join(f"`## {h}`" for h in missing_sections)
        warnings.append(f"{name}: missing mandatory section(s) {listed}")

    return ADR(
        path=path,
        id=adr_id,
        title=title,
        status=status,
        updated=updated,
        has_deviation_sections=meta is not None and not missing_sections,
        warnings=warnings,
    )


def collect_adrs() -> list[ADR]:
    """Discover specs/decisions/ADR-*.md, sorted by filename. Empty when the
    directory is absent. @implements FR-0003:AC-7"""
    if not DECISIONS_DIR.exists():
        return []
    return [parse_adr(p) for p in sorted(DECISIONS_DIR.glob("ADR-*.md")) if p.is_file()]


def validate_graph(frs: list[FR]) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, Path] = {}
    for fr in frs:
        if fr.id in seen_ids:
            errors.append(
                f"duplicate FR id {fr.id} in {fr.path.name} and {seen_ids[fr.id].name}"
            )
        seen_ids[fr.id] = fr.path

    valid_ids = set(seen_ids.keys())
    for fr in frs:
        for dep in fr.depends_on:
            if dep not in valid_ids:
                errors.append(
                    f"{fr.path.name}: depends_on references unknown FR '{dep}'"
                )
        # FR-typed references from the versioning block / solution-space fields
        # resolve against this project's specs/ only. @implements FR-0003:AC-4
        for ext in fr.extends:
            if ext not in valid_ids:
                errors.append(
                    f"{fr.path.name}: extends references unknown FR '{ext}'"
                )
        for key in ("supersedes", "superseded_by"):
            ref = getattr(fr, key)
            if ref is not None and ref not in valid_ids:
                errors.append(
                    f"{fr.path.name}: {key} references unknown FR '{ref}'"
                )

    return errors


def _duplicate_id_errors(objs: list, kind: str) -> list[str]:  # type: ignore[type-arg]
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for obj in objs:
        if obj.id in seen:
            errors.append(
                f"duplicate {kind} id {obj.id} in {obj.path.name} and {seen[obj.id].name}"
            )
        seen[obj.id] = obj.path
    return errors


def validate_references(frs: list[FR], trs: list[TR], decs: list[DEC]) -> list[str]:
    """Hard cross-object resolution (FR-0004), within this project's specs/
    only: duplicate TR / DEC IDs; TR `operationalises` -> FR, TR `supersedes`
    / `superseded_by` -> TR; DEC `constrained_by` -> FR, DEC `revises` -> FR
    or TR by prefix, DEC `supersedes` / `superseded_by` -> DEC; and FR / TR
    `revisions` -> DEC file (the resolution FR-0003 deferred).
    `authorised_by` -> ADR is warn-only and lives in `_cross_object_warnings`.
    @implements FR-0004:AC-2, FR-0004:AC-4"""
    errors: list[str] = []
    errors.extend(_duplicate_id_errors(trs, "TR"))
    errors.extend(_duplicate_id_errors(decs, "DEC"))
    fr_ids = {fr.id for fr in frs}
    tr_ids = {tr.id for tr in trs}
    dec_ids = {dec.id for dec in decs}

    def unknown(name: str, key: str, kind: str, ref: str) -> None:
        errors.append(f"{name}: {key} references unknown {kind} '{ref}'")

    for tr in trs:
        for ref in tr.operationalises:
            if ref not in fr_ids:
                unknown(tr.path.name, "operationalises", "FR", ref)
        for key in ("supersedes", "superseded_by"):
            ref = getattr(tr, key)
            if ref is not None and ref not in tr_ids:
                unknown(tr.path.name, key, "TR", ref)

    for dec in decs:
        for ref in dec.constrained_by:
            if ref not in fr_ids:
                unknown(dec.path.name, "constrained_by", "FR", ref)
        if dec.revises is not None:
            if dec.revises.startswith("FR-") and dec.revises not in fr_ids:
                unknown(dec.path.name, "revises", "FR", dec.revises)
            elif dec.revises.startswith("TR-") and dec.revises not in tr_ids:
                unknown(dec.path.name, "revises", "TR", dec.revises)
        for key in ("supersedes", "superseded_by"):
            ref = getattr(dec, key)
            if ref is not None and ref not in dec_ids:
                unknown(dec.path.name, key, "DEC", ref)

    for obj in [*frs, *trs]:
        for ref in obj.revisions:
            if ref not in dec_ids:
                unknown(obj.path.name, "revisions", "DEC", ref)

    return errors


def _layout_errors() -> list[str]:
    """The project layout's validation error, if any, as a one-entry list.
    Empty when the layout is absent or valid, or when project_layout.py is
    not beside this script. @implements FR-0023:AC-1"""
    if _project_layout is None:
        return []
    try:
        _project_layout.load(REPO_ROOT)
    except _project_layout.LayoutInvalid as e:
        return [str(e)]
    return []


def collect_graph() -> SpecGraph:
    """Discover and validate every object type under specs/ in one call: FRs,
    TRs, DECs (hard-validated) and ADRs (warn-only). `errors` merges parse
    errors with `validate_graph` and `validate_references`; when it is empty
    every reference in the graph resolves. A malformed project layout is the
    first error, ahead of the FR, TR and DEC errors.
    @implements FR-0004:AC-10, FR-0023:AC-1"""
    frs, errors = collect_frs()
    trs, tr_errors = collect_trs()
    decs, dec_errors = collect_decs()
    errors = [*_layout_errors(), *errors, *tr_errors, *dec_errors]
    errors.extend(validate_graph(frs))
    errors.extend(validate_references(frs, trs, decs))
    return SpecGraph(frs=frs, trs=trs, decs=decs, adrs=collect_adrs(), errors=errors)


def validate_spec_graph() -> list[str]:
    """The one entry point a consumer outside this module should call to learn
    whether the spec graph validates: exactly the error list `--validate`
    reports (every error `collect_graph()` collects), and nothing else.
    Exported so a caller such as `deploy-gate.py` can delegate the full
    FR/TR/DEC/cross-object validation to the indexer without importing (or
    re-implementing) any DEC/TR-specific vocabulary of its own.
    @implements FR-0021:AC-1, FR-0021:AC-2"""
    return collect_graph().errors


def _fmt_globs(globs: tuple[str, ...]) -> str:
    if not globs:
        return "—"
    # Backtick each glob; comma-separate. Markdown table cells have no native
    # list rendering, so this stays one line per FR.
    return ", ".join(f"`{g}`" for g in globs)


def _fmt_gates(gates: tuple[dict, ...]) -> str:
    """`<id>:<after>:<reviewer>` joined by `, `, or `—`. @implements FR-0008:AC-1"""
    if not gates:
        return "—"
    return ", ".join(f"`{g['id']}:{g['after']}:{g['reviewer']}`" for g in gates)


def _render_overlap_warnings(frs: list[FR], repo_files: list[str]) -> list[str]:
    records = [
        FRRecord(
            id=fr.id,
            status=fr.status,
            footprint=Footprint(owns=fr.owns, reads=fr.reads),
        )
        for fr in frs
    ]
    overlaps = find_overlaps(records, repo_files=repo_files)
    if not overlaps:
        return []
    lines = ["", "## Footprint warnings", ""]
    for o in overlaps:
        shared = sorted(o.shared_files)
        truncated = shared[:5]
        suffix = ""
        if len(shared) > 5:
            suffix = f", … (+{len(shared) - 5} more)"
        files_md = ", ".join(f"`{f}`" for f in truncated)
        lines.append(f"- **{o.fr_a} ↔ {o.fr_b}**: shared files: {files_md}{suffix}")
    return lines


@dataclass(frozen=True)
class CoverageExemptions:
    """One FR's answer to the deploy gate (FR-0026): `exempt` is every AC
    number with a honoured exemption entry, and `invalid` is the warning text
    for each exemption entry that is not honoured (its AC stays live).
    @implements FR-0026:AC-6"""

    exempt: frozenset[int] = frozenset()
    invalid: tuple[str, ...] = ()


@dataclass
class _ACStateReport:
    """Everything one FR's `ac_state` and AC sections say. `warnings` pairs
    each line with whether FR-0026 introduced it (reported by `--validate`
    too); `honoured` maps each honoured exemption entry's AC number to its
    entry. @implements FR-0026:AC-1"""

    warnings: list[tuple[str, bool]] = field(default_factory=list)
    honoured: dict[int, dict] = field(default_factory=dict)
    invalid: list[str] = field(default_factory=list)


class _PointerResolver:
    """Resolves a well-formed `moved_to` inside this project only: an FR among
    the parsed FRs, a DEC among the DEC files that parsed, an ADR by its
    `specs/decisions/ADR-NNNN-*.md` file. An IDEA resolves on shape alone —
    nothing here looks outside the project tree. DECs and ADRs are discovered
    lazily, only when a pointer names one. @implements FR-0026:AC-2"""

    def __init__(
        self,
        frs: list[FR],
        decs: list[DEC] | None = None,
        adrs: list[ADR] | None = None,
    ) -> None:
        self._fr_ids = {fr.id for fr in frs}
        self._decs = decs
        self._adrs = adrs

    def resolves(self, ref: str) -> bool:
        kind = ref.split("-", 1)[0]
        if kind == "IDEA":
            return True
        if kind == "FR":
            return ref in self._fr_ids
        if kind == "DEC":
            if self._decs is None:
                self._decs, _ = collect_decs()
            return any(dec.id == ref for dec in self._decs)
        if self._adrs is None:
            self._adrs = collect_adrs()
        return any(
            ADR_FILE_PATTERN.match(adr.path.name)
            and adr.path.name.startswith(f"{ref}-")
            for adr in self._adrs
        )


def _exemption_problem(
    fr_id: str, n: int, state: str, entry: dict, resolver: _PointerResolver
) -> str | None:
    """None when an exemption entry is honoured (AC-1's shape and AC-2's local
    resolution both hold); otherwise its not-honoured warning.
    @implements FR-0026:AC-1, FR-0026:AC-2"""
    head = f"{fr_id} AC-{n}: "
    tail = f"; not honoured, AC-{n} still requires coverage"
    if "moved_to" not in entry:
        return (
            head + f"{state} needs moved_to (FR-NNNN, IDEA-NNNN, ADR-NNNN, DEC-NNNN, "
            "or null with a reason)" + tail
        )
    moved_to = entry["moved_to"]
    if moved_to is None:
        if state == "superseded":
            return (
                head
                + "superseded needs a non-null moved_to naming its successor"
                + tail
            )
        reason = entry.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            return head + "moved_to is null but no reason is given" + tail
        return None
    if not isinstance(moved_to, str) or not MOVED_TO_PATTERN.fullmatch(moved_to):
        return (
            head + f"moved_to '{moved_to}' is not FR-NNNN, IDEA-NNNN, ADR-NNNN, "
            "DEC-NNNN or null" + tail
        )
    if not resolver.resolves(moved_to):
        return head + f"moved_to {moved_to} does not resolve in this project" + tail
    return None


def _stray_moved_to_warning(fr_id: str, n: int) -> str:
    """AC-1's warning for a `moved_to` on a non-exemption state.
    @implements FR-0026:AC-1"""
    return (
        f"{fr_id} AC-{n}: moved_to applies only to deferred, withdrawn or "
        "superseded; ignored"
    )


def _ac_state_report(fr: FR, resolver: _PointerResolver) -> _ACStateReport:
    """Warn-only checks on one FR's per-AC state (Lockstep N-4, FR-0026).

    An FR with no `ac_state` and no `## Withdrawn acceptance criteria` bullet
    is unmanaged and yields nothing. `no ac_state entry for …` is reported only
    once the FR has an entry whose state is not an exemption state, so recording
    a deferral does not opt an FR into ratification tracking.
    @implements FR-0026:AC-1, FR-0026:AC-4, FR-0026:AC-5"""
    report = _ACStateReport()
    if not fr.ac_state and not fr.withdrawn_acs:
        return report  # unmanaged — no opt-in, no noise

    def old(msg: str) -> None:
        report.warnings.append((msg, False))

    def new(msg: str) -> None:
        report.warnings.append((msg, True))

    state_by_n: dict[int, dict] = {}
    for k, v in fr.ac_state.items():
        try:
            state_by_n[int(k)] = v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            old(f"{fr.id}: ac_state has a non-numeric key '{k}'")
    for n, entry in sorted(state_by_n.items()):
        state = str(entry.get("state", ""))
        # AC-1: a `moved_to` outside the exemption states is ignored, with a
        # warning, whether or not the AC has text in this FR.
        stray_moved_to = state not in AC_EXEMPT_STATES and "moved_to" in entry
        problem = None
        if state in AC_EXEMPT_STATES:
            problem = _exemption_problem(fr.id, n, state, entry, resolver)
            if problem is None:
                report.honoured[n] = entry
            else:
                report.invalid.append(problem)
        if n not in fr.acs and n not in fr.withdrawn_acs:
            if n in report.honoured:
                new(
                    f"{fr.id} AC-{n}: {state} but has no text in this FR; keep its "
                    f"original text under ## {WITHDRAWN_ACS_HEADING}"
                )
            else:
                old(
                    f"{fr.id}: ac_state references AC-{n}, which has no matching "
                    "acceptance criterion"
                )
            if problem is not None:
                new(problem)
            if stray_moved_to:
                new(_stray_moved_to_warning(fr.id, n))
            continue
        if state not in AC_STATES:
            old(f"{fr.id} AC-{n}: state '{state}' not in {sorted(AC_STATES)}")
        if problem is not None:
            new(problem)
        if stray_moved_to:
            new(_stray_moved_to_warning(fr.id, n))
        if state == "ratified":
            stored = entry.get("hash")
            current = ac_hash(fr.acs[n] if n in fr.acs else fr.withdrawn_acs[n])
            if not stored:
                old(
                    f"{fr.id} AC-{n}: ratified but has no recorded hash — "
                    f"record hash: {current}"
                )
            elif str(stored) != current:
                old(
                    f"{fr.id} AC-{n}: ratified text changed since sign-off - needs "
                    f"client-review (recorded {str(stored)[:12]}.., current {current[:12]}..)"
                )
    # The Withdrawn section and `ac_state` disagreeing: `ac_state` always wins
    # (the gate reads only it); each disagreement is a warning. @implements FR-0026:AC-5
    for n in sorted(set(fr.acs) | set(fr.withdrawn_acs)):
        in_acs, in_withdrawn = n in fr.acs, n in fr.withdrawn_acs
        entry = state_by_n.get(n)
        state = str(entry.get("state", "")) if entry is not None else ""
        honoured = n in report.honoured
        if in_withdrawn and not honoured:
            new(
                f"{fr.id} AC-{n}: listed under {WITHDRAWN_ACS_HEADING} but ac_state is "
                f"{state or 'absent'}; it is live for coverage"
            )
        if in_acs and honoured and state in {"withdrawn", "superseded"}:
            new(
                f"{fr.id} AC-{n}: {state} but still under Acceptance criteria; move it "
                f"under ## {WITHDRAWN_ACS_HEADING}"
            )
        if in_withdrawn and honoured and state == "deferred":
            new(f"{fr.id} AC-{n}: deferred ACs stay under Acceptance criteria")
        if in_acs and in_withdrawn:
            new(
                f"{fr.id} AC-{n}: appears under both Acceptance criteria and "
                f"{WITHDRAWN_ACS_HEADING}"
            )
    opted_in = any(
        not (isinstance(v, dict) and str(v.get("state", "")) in AC_EXEMPT_STATES)
        for v in fr.ac_state.values()
    )
    unmanaged = sorted(n for n in fr.acs if n not in state_by_n)
    if opted_in and unmanaged:
        listed = ", ".join(f"AC-{n}" for n in unmanaged)
        old(f"{fr.id}: no ac_state entry for {listed}")
    return report


def _ac_state_reports(
    frs: list[FR], decs: list[DEC] | None = None, adrs: list[ADR] | None = None
) -> list[tuple[FR, _ACStateReport]]:
    resolver = _PointerResolver(frs, decs, adrs)
    return [
        (fr, _ac_state_report(fr, resolver)) for fr in sorted(frs, key=lambda f: f.id)
    ]


def _ac_state_warnings(
    frs: list[FR], decs: list[DEC] | None = None, adrs: list[ADR] | None = None
) -> list[str]:
    """Warn-only checks on per-AC ratification state (Lockstep N-4).

    Measurement before enforcement (CLAUDE.md rule 1): these never fail the
    build. An FR with no `ac_state` at all is 'unmanaged' and skipped silently —
    that is the migration default for FRs written before ratification tracking.
    Once an FR opts in (any entry not in an exemption state), gaps in its
    coverage are reported. Exemption entries and the Withdrawn section are
    checked too (FR-0026). `decs` / `adrs` default to discovery, and are only
    read when a `moved_to` names a DEC or an ADR."""
    return [w for _, rep in _ac_state_reports(frs, decs, adrs) for w, _ in rep.warnings]


def _ac_exemption_warnings(
    frs: list[FR], decs: list[DEC] | None = None, adrs: list[ADR] | None = None
) -> list[str]:
    """The subset of `_ac_state_warnings` that FR-0026 introduced (exemption
    entries and the Withdrawn section), in the same order. `--validate` prints
    only these, so its output on every tree without them is unchanged.
    @implements FR-0026:AC-1"""
    return [
        w
        for _, rep in _ac_state_reports(frs, decs, adrs)
        for w, is_new in rep.warnings
        if is_new
    ]


def coverage_exemptions(
    frs: list[FR], decs: list[DEC] | None = None, adrs: list[ADR] | None = None
) -> dict[str, CoverageExemptions]:
    """The one function the deploy gate calls to learn, per FR id, which ACs
    are exempt from its coverage check: the honoured exemption entries
    (AC-1's shape, AC-2's local resolution), and the warning text of every
    exemption entry that is not honoured. Only `ac_state` decides; no section
    heading or AC-text tag exempts anything. Pointers are resolved here, so the
    caller needs no vocabulary of its own beyond the FR.
    @implements FR-0026:AC-6"""
    return {
        fr.id: CoverageExemptions(
            exempt=frozenset(rep.honoured), invalid=tuple(rep.invalid)
        )
        for fr, rep in _ac_state_reports(frs, decs, adrs)
    }


def _render_ac_state_warnings(
    frs: list[FR], decs: list[DEC] | None = None, adrs: list[ADR] | None = None
) -> list[str]:
    warnings = _ac_state_warnings(frs, decs, adrs)
    if not warnings:
        return []
    return ["", "## AC ratification warnings", "", *[f"- {w}" for w in warnings]]


def _md_cell(text: str) -> str:
    return " ".join(text.splitlines()).strip().replace("|", "\\|")


def _render_open_deferrals(
    frs: list[FR], decs: list[DEC] | None = None, adrs: list[ADR] | None = None
) -> list[str]:
    """`## Open deferrals`: one row per honoured `deferred` entry on any FR
    (any lifecycle, any status), sorted by FR ID then AC number; omitted when
    there is none. A deterministic function of the tree: never the hub, the
    clock or the network. @implements FR-0026:AC-13"""
    rows: list[str] = []
    for fr, rep in _ac_state_reports(frs, decs, adrs):
        for n, entry in sorted(rep.honoured.items()):
            if str(entry.get("state", "")) != "deferred":
                continue
            moved_to = entry["moved_to"] if entry["moved_to"] is not None else "none"
            raw_reason = entry.get("reason")
            reason = _md_cell(str(raw_reason)) if raw_reason is not None else ""
            rows.append(
                f"| [{fr.id}]({fr.path.name}) | AC-{n} | `{fr.status}` | {moved_to} "
                f"| {reason or '—'} |"
            )
    if not rows:
        return []
    return [
        "",
        "## Open deferrals",
        "",
        "_ACs deliberately not delivered yet, from `ac_state`. Each names where the work went._",
        "",
        "| FR | AC | FR status | Moved to | Reason |",
        "|----|----|-----------|----------|--------|",
        *rows,
    ]


def _find_hub_root(start: Path) -> Path | None:
    """The workspace hub, by `dispatch.py`'s `_find_hub_root` rule (re-
    implemented, not imported): `DISPATCH_HUB_ROOT` when it names a directory
    holding `scripts/parking.py`, else the first of `start` and its ancestors
    holding both `scripts/parking.py` and `parking-lot/`. @implements FR-0026:AC-3"""
    env = os.environ.get("DISPATCH_HUB_ROOT")
    if env:
        p = Path(env).expanduser()
        if (p / "scripts" / "parking.py").exists():
            return p
    for parent in [start, *start.parents]:
        if (parent / "scripts" / "parking.py").exists() and (
            parent / "parking-lot"
        ).is_dir():
            return parent
    return None


def _deferral_pointer_warnings(
    frs: list[FR],
    decs: list[DEC] | None = None,
    adrs: list[ADR] | None = None,
    hub: Path | None = None,
) -> list[str]:
    """Stderr-only check of each honoured `moved_to: IDEA-NNNN` on a
    default-view FR against the hub parking lot, when a hub is found. Never
    makes an entry not honoured, never reaches INDEX.md or the exit code.
    @implements FR-0026:AC-3"""
    if hub is None:
        return []
    parking = hub / "parking-lot"
    warnings: list[str] = []
    for fr, rep in _ac_state_reports(frs, decs, adrs):
        if not in_default_view(fr):
            continue
        for n, entry in sorted(rep.honoured.items()):
            idea = entry.get("moved_to")
            if not (isinstance(idea, str) and idea.startswith("IDEA-")):
                continue
            matches = sorted(p for p in parking.glob(f"{idea}-*.md") if p.is_file())
            if not matches:
                warnings.append(
                    f"{fr.id} AC-{n}: moved_to {idea} not found in the hub parking lot"
                )
                continue
            try:
                meta, _ = _load_frontmatter(matches[0])
            except (OSError, UnicodeDecodeError):
                meta = None
            if meta is not None and str(meta.get("status", "")) == "archived":
                warnings.append(
                    f"{fr.id} AC-{n}: moved_to {idea} is archived; the work has no live home"
                )
    return warnings


def _versioning_warnings(frs: list) -> list[str]:  # type: ignore[type-arg]
    """Warn-only lint on the versioning block (FR-0003; ADR-0001 arithmetic).
    Never fails the build — enforcement is IDEA-0056. @implements FR-0003:AC-5

    Duck-typed on the shared block, so the same checks run over a list of FRs
    or a list of TRs (FR-0004; supersession links are same-type, so each type
    is checked against its own list).

    Checks, one line each: version == len(revisions) + 1;
    last_breaking_revision <= version; `lifecycle: superseded` <-> `superseded_by`
    set; and supersession symmetry, checked from the `supersedes` side (the new
    object) and — for an object that is fully marked superseded — from the
    `superseded_by` side too."""
    by_id = {fr.id: fr for fr in frs}
    warnings: list[str] = []
    for fr in sorted(frs, key=lambda f: f.id):
        expected = len(fr.revisions) + 1
        if fr.version != expected:
            warnings.append(
                f"{fr.id}: version {fr.version} does not equal len(revisions) + 1 "
                f"= {expected}"
            )
        if fr.last_breaking_revision is not None and fr.last_breaking_revision > fr.version:
            warnings.append(
                f"{fr.id}: last_breaking_revision {fr.last_breaking_revision} is "
                f"greater than version {fr.version}"
            )
        if fr.lifecycle == "superseded" and fr.superseded_by is None:
            warnings.append(f"{fr.id}: lifecycle is 'superseded' but superseded_by is null")
        if fr.lifecycle != "superseded" and fr.superseded_by is not None:
            warnings.append(
                f"{fr.id}: superseded_by is '{fr.superseded_by}' but lifecycle is "
                f"'{fr.lifecycle}' (expected 'superseded')"
            )
        if fr.supersedes is not None and fr.supersedes in by_id:
            old = by_id[fr.supersedes]
            if old.superseded_by != fr.id:
                warnings.append(
                    f"{fr.id}: supersedes {old.id} but {old.id}.superseded_by is "
                    f"{old.superseded_by!r} (expected '{fr.id}')"
                )
        if (
            fr.lifecycle == "superseded"
            and fr.superseded_by is not None
            and fr.superseded_by in by_id
        ):
            new = by_id[fr.superseded_by]
            if new.supersedes != fr.id:
                warnings.append(
                    f"{fr.id}: superseded_by {new.id} but {new.id}.supersedes is "
                    f"{new.supersedes!r} (expected '{fr.id}')"
                )
    return warnings


def _cross_object_warnings(frs: list[FR], trs: list[TR], decs: list[DEC], adrs: list[ADR]) -> list[str]:
    """Warn-only cross-object checks (FR-0004). Never fails the build.
    @implements FR-0004:AC-5, FR-0004:AC-4

    One line per finding, naming both objects:
    (a) reciprocity — every DEC in an object's `revisions` should `revise`
        that object (regardless of the DEC's status: being listed asserts it
        was applied); every *live* DEC (`is_live_dec`) whose `revises` names an
        object should appear in that object's `revisions` — `rejected` and
        `superseded` DECs are exempt from this direction, `proposed` is not;
    (b) breaking marker — `last_breaking_revision` should equal 1 + the
        1-based position of the newest `breaking: true` DEC in `revisions`, or
        be null when none is breaking;
    (c) a TR with `lifecycle: superseded` and non-empty `implemented_by` (the
        migration-window case, ADR-0001 rule 9);
    (d) DEC supersession symmetry, as FR-0003 checks it for FRs, with DEC
        `status: superseded` in the role of `lifecycle: superseded`;
    plus `authorised_by` entries with no matching ADR file (warn-only, since
    ADRs are warn-only per FR-0003)."""
    warnings: list[str] = []
    objs_by_id = {obj.id: obj for obj in [*frs, *trs]}
    decs_by_id = {dec.id: dec for dec in decs}
    adr_ids = {adr.id for adr in adrs}

    for obj in sorted([*frs, *trs], key=lambda o: o.id):
        newest_breaking: int | None = None
        for pos, dec_id in enumerate(obj.revisions, start=1):
            dec = decs_by_id.get(dec_id)
            if dec is None:
                continue  # unresolved: a hard error elsewhere, nothing to lint
            if dec.revises != obj.id:
                warnings.append(
                    f"{obj.id}: revisions lists {dec.id} but {dec.id}.revises is "
                    f"{dec.revises!r} (expected '{obj.id}')"
                )
            if dec.breaking:
                newest_breaking = pos
        if obj.revisions and all(d in decs_by_id for d in obj.revisions):
            if newest_breaking is None:
                if obj.last_breaking_revision is not None:
                    warnings.append(
                        f"{obj.id}: last_breaking_revision is {obj.last_breaking_revision} "
                        "but no DEC in revisions has breaking: true (expected null)"
                    )
            else:
                expected = newest_breaking + 1
                if obj.last_breaking_revision != expected:
                    warnings.append(
                        f"{obj.id}: last_breaking_revision is "
                        f"{obj.last_breaking_revision!r} but the newest breaking DEC "
                        f"({obj.revisions[newest_breaking - 1]}, position {newest_breaking}) "
                        f"produced version {expected} (expected {expected})"
                    )
        # An object with empty `revisions` is left to FR-0003's lint alone, so
        # a tree with no DEC files keeps FR-0003's exact stderr (AC-7).

    for tr in sorted(trs, key=lambda t: t.id):
        if tr.lifecycle == "superseded" and tr.implemented_by:
            listed = ", ".join(tr.implemented_by)
            warnings.append(
                f"{tr.id}: lifecycle is 'superseded' but implemented_by is non-empty "
                f"({listed}) — migration window; a DEC must justify it"
            )

    for dec in sorted(decs, key=lambda d: d.id):
        if is_live_dec(dec) and dec.revises is not None:
            target = objs_by_id.get(dec.revises)
            if target is not None and dec.id not in target.revisions:
                warnings.append(
                    f"{dec.id}: revises {target.id} (status '{dec.status}') but "
                    f"{target.id}.revisions does not list {dec.id}"
                )
        if dec.status == "superseded" and dec.superseded_by is None:
            warnings.append(f"{dec.id}: status is 'superseded' but superseded_by is null")
        if dec.status != "superseded" and dec.superseded_by is not None:
            warnings.append(
                f"{dec.id}: superseded_by is '{dec.superseded_by}' but status is "
                f"'{dec.status}' (expected 'superseded')"
            )
        if dec.supersedes is not None and dec.supersedes in decs_by_id:
            old = decs_by_id[dec.supersedes]
            if old.superseded_by != dec.id:
                warnings.append(
                    f"{dec.id}: supersedes {old.id} but {old.id}.superseded_by is "
                    f"{old.superseded_by!r} (expected '{dec.id}')"
                )
        if (
            dec.status == "superseded"
            and dec.superseded_by is not None
            and dec.superseded_by in decs_by_id
        ):
            new = decs_by_id[dec.superseded_by]
            if new.supersedes != dec.id:
                warnings.append(
                    f"{dec.id}: superseded_by {new.id} but {new.id}.supersedes is "
                    f"{new.supersedes!r} (expected '{dec.id}')"
                )
        for ref in dec.authorised_by:
            if ref not in adr_ids:
                warnings.append(f"{dec.id}: authorised_by references unknown ADR '{ref}'")
    return warnings


def _all_versioning_warnings(
    frs: list[FR], trs: list[TR], decs: list[DEC], adrs: list[ADR]
) -> list[str]:
    """Everything rendered under `## Versioning warnings`: the FR-0003 block
    lint over FRs, the same over TRs, then the FR-0004 cross-object checks.
    Empty lists contribute nothing, so a tree with no TR/DEC files yields
    exactly FR-0003's lines (@implements FR-0004:AC-7)."""
    return [
        *_versioning_warnings(frs),
        *_versioning_warnings(trs),
        *_cross_object_warnings(frs, trs, decs, adrs),
    ]


def _render_versioning_warnings(
    frs: list[FR], trs: list[TR], decs: list[DEC], adrs: list[ADR]
) -> list[str]:
    warnings = _all_versioning_warnings(frs, trs, decs, adrs)
    if not warnings:
        return []
    return ["", "## Versioning warnings", "", *[f"- {w}" for w in warnings]]


def _fmt_list(items: list[str]) -> str:
    return ", ".join(items) if items else "—"


def _render_tr_table(trs: list[TR]) -> list[str]:
    """`## Technical requirements`; omitted when the project has no TRs.
    @implements FR-0004:AC-6"""
    if not trs:
        return []
    lines = [
        "",
        "## Technical requirements",
        "",
        "| ID | Title | Operationalises | Ver | Lifecycle | Last breaking | Implemented by | Updated |",
        "|----|-------|-----------------|-----|-----------|---------------|----------------|---------|",
    ]
    for tr in sorted(trs, key=lambda t: t.id):
        link = f"[{tr.id}]({tr.path.name})"
        last_breaking = tr.last_breaking_revision if tr.last_breaking_revision is not None else "—"
        implemented = _fmt_globs(tuple(tr.implemented_by))
        lines.append(
            f"| {link} | {tr.title} | {_fmt_list(tr.operationalises)} | {tr.version} | "
            f"`{tr.lifecycle}` | {last_breaking} | {implemented} | {tr.updated} |"
        )
    return lines


def _render_dec_table(decs: list[DEC]) -> list[str]:
    """`## Decisions`; omitted when the project has no DECs.
    @implements FR-0004:AC-6"""
    if not decs:
        return []
    lines = [
        "",
        "## Decisions",
        "",
        "| ID | Title | Tier | Status | Revises | Breaking | Authorised by | Updated |",
        "|----|-------|------|--------|---------|----------|---------------|---------|",
    ]
    for dec in sorted(decs, key=lambda d: d.id):
        link = f"[{dec.id}]({dec.path.parent.name}/{dec.path.name})"
        revises = dec.revises if dec.revises else "—"
        breaking = "yes" if dec.breaking else "no"
        lines.append(
            f"| {link} | {dec.title} | {dec.tier} | `{dec.status}` | {revises} | "
            f"{breaking} | {_fmt_list(dec.authorised_by)} | {dec.updated} |"
        )
    return lines


def _adr_warnings(adrs: list[ADR]) -> list[str]:
    return [w for adr in sorted(adrs, key=lambda a: a.path.name) for w in adr.warnings]


def _render_adr_sections(adrs: list[ADR]) -> list[str]:
    """`## Architecture decision records` table plus `## ADR warnings`; both
    omitted when the project has no ADR files. @implements FR-0003:AC-7"""
    if not adrs:
        return []
    lines = [
        "",
        "## Architecture decision records",
        "",
        "| ID | Title | Status | Deviation sections | Updated |",
        "|----|-------|--------|--------------------|---------|",
    ]
    for adr in sorted(adrs, key=lambda a: a.path.name):
        link = f"[{adr.id}]({adr.path.parent.name}/{adr.path.name})"
        status_md = f"`{adr.status}`" if adr.status else "—"
        deviation = "yes" if adr.has_deviation_sections else "no"
        lines.append(
            f"| {link} | {adr.title} | {status_md} | {deviation} | {adr.updated} |"
        )
    warnings = _adr_warnings(adrs)
    if warnings:
        lines.extend(["", "## ADR warnings", "", *[f"- {w}" for w in warnings]])
    return lines


def _object_link(obj) -> str:  # type: ignore[no-untyped-def]
    """Markdown link to a spec object, relative to specs/ (FR / TR files sit
    at the top level, DEC / ADR files under decisions/)."""
    if object_type(obj) in ("DEC", "ADR"):
        return f"[{obj.id}]({obj.path.parent.name}/{obj.path.name})"
    return f"[{obj.id}]({obj.path.name})"


def _render_provisional_table(decs: list[DEC], objs_by_id: dict) -> list[str]:
    """`## Provisional decisions`: every default-view DEC with a non-null
    `provisional_until`, sorted by ID. Never evaluates dates — the file must
    be byte-stable across days and across the two writers — so `past` /
    `pending` appear only in the CLI report and on stderr. Omitted when empty.
    @implements FR-0005:AC-9"""
    rows = [
        dec
        for dec in sorted(decs, key=lambda d: d.id)
        if dec.provisional_until is not None and in_default_view(dec, objs_by_id)
    ]
    if not rows:
        return []
    lines = [
        "",
        "## Provisional decisions",
        "",
        "| ID | Title | Trigger | Revises | Updated |",
        "|----|-------|---------|---------|---------|",
    ]
    for dec in rows:
        revises = dec.revises if dec.revises else "—"
        lines.append(
            f"| {_object_link(dec)} | {dec.title} | {dec.provisional_until} | {revises} | "
            f"{dec.updated} |"
        )
    return lines


def _render_retired_table(
    frs: list[FR], trs: list[TR], decs: list[DEC], objs_by_id: dict
) -> list[str]:
    """`## Retired objects`: every superseded FR / TR / DEC, rejected DEC and
    pre-breaking DEC, sorted by ID, with `Why` in FR-0005's wording. Omitted
    when empty. @implements FR-0005:AC-9"""
    rows: list[tuple] = []  # type: ignore[type-arg]
    for obj in [*frs, *trs, *decs]:
        why = retired_reason(obj, objs_by_id)
        if why is not None:
            rows.append((obj, why))
    if not rows:
        return []
    lines = [
        "",
        "## Retired objects",
        "",
        "| ID | Type | Title | Why | Updated |",
        "|----|------|-------|-----|---------|",
    ]
    for obj, why in sorted(rows, key=lambda r: r[0].id):
        lines.append(
            f"| {_object_link(obj)} | {object_type(obj)} | {obj.title} | {why} | {obj.updated} |"
        )
    return lines


def _render_undeclared_section(frs: list[FR]) -> list[str]:
    # Only flag active-status FRs as missing footprint; merged/deprecated/draft
    # don't need to declare. AC-4 treats "footprint not declared" as a soft
    # nudge, not an error.
    active = {"ready", "in-progress", "in-review"}
    undeclared = sorted(
        [fr.id for fr in frs if fr.status in active and not fr.owns],
    )
    if not undeclared:
        return []
    return [
        "",
        "## FRs with undeclared footprint",
        "",
        "_These FRs have empty `owns:` and will not appear in `CODEOWNERS`._",
        "",
        *[f"- {fid}" for fid in undeclared],
    ]


def _render_metrics_section() -> list[str]:
    """`## Pipeline metrics` lines from `specs/_metrics/*.ndjson`, or [] when
    there is no log, no module, or no record attributable to an FR — so a
    project without the log renders byte-identical output. Reading the log is
    never load-bearing for the index. @implements FR-0002:AC-12"""
    if _metrics_log is None:
        return []
    metrics_dir = SPECS_DIR / "_metrics"
    if not metrics_dir.is_dir():
        return []
    try:
        return _metrics_log.render_index_section(_metrics_log.iter_records(metrics_dir))
    except Exception as e:  # noqa: BLE001 — a bad log line must not break indexing
        _metrics_log.warn(f"INDEX.md metrics section skipped: {type(e).__name__}: {e}")
        return []


def render_index(
    frs: list[FR],
    repo_files: list[str],
    adrs: list[ADR] | None = None,
    trs: list[TR] | None = None,
    decs: list[DEC] | None = None,
) -> str:
    """Render specs/INDEX.md. `adrs`, `trs` and `decs` default to their
    `collect_*()` discovery so that deploy-gate.py, which calls
    `render_index(frs, repo_files)` with two positional arguments, writes
    byte-identical output to this script (@implements FR-0003:AC-8,
    FR-0004:AC-9). On the default path TR/DEC parse errors are not raised
    here — the objects that parsed are rendered; hard validation is
    `collect_graph()`'s job."""
    if adrs is None:
        adrs = collect_adrs()
    if trs is None:
        trs, _ = collect_trs()
    if decs is None:
        decs, _ = collect_decs()
    # Default view (FR-0005): the FR, TR and DEC tables show live + draft
    # objects and only DECs in their target's current revision window; the
    # rest is listed under `## Retired objects`. Warning sections still run
    # over every object — this FR filters, it does not lint. Because the
    # filter sits here, deploy-gate.py's `render_index(frs, repo_files)` call
    # writes byte-identical output. @implements FR-0005:AC-9, FR-0005:AC-10
    objs_by_id = {obj.id: obj for obj in [*frs, *trs]}
    view_frs = [fr for fr in frs if in_default_view(fr)]
    view_trs = [tr for tr in trs if in_default_view(tr)]
    view_decs = [dec for dec in decs if in_default_view(dec, objs_by_id)]
    # `Ver` and `Lifecycle` sit immediately after `Status`; every pre-existing
    # column keeps its name, order and formatting. @implements FR-0003:AC-6
    lines = [
        "# Spec Index",
        "",
        "_Auto-generated by `scripts/index-specs.py`. Do not edit by hand._",
        "",
        "| ID | Title | Status | Ver | Lifecycle | Owner | Tags | Owns | Reads | Depends on | Derived from | Updated | Gates |",
        "|----|-------|--------|-----|-----------|-------|------|------|-------|------------|--------------|---------|-------|",
    ]
    for fr in sorted(view_frs, key=lambda f: f.id):
        deps = ", ".join(fr.depends_on) if fr.depends_on else "—"
        tags = ", ".join(fr.tags) if fr.tags else "—"
        derived = fr.derived_from if fr.derived_from else "—"
        link = f"[{fr.id}]({fr.path.name})"
        owns_md = _fmt_globs(fr.owns)
        reads_md = _fmt_globs(fr.reads)
        gates_md = _fmt_gates(fr.gates)
        lines.append(
            f"| {link} | {fr.title} | `{fr.status}` | {fr.version} | `{fr.lifecycle}` | {fr.owner} | {tags} | {owns_md} | {reads_md} | {deps} | {derived} | {fr.updated} | {gates_md} |"
        )
    lines.extend(_render_overlap_warnings(frs, repo_files))
    lines.extend(_render_undeclared_section(frs))
    lines.extend(_render_ac_state_warnings(frs, decs, adrs))
    # Open deferrals sit right after the AC ratification warnings (or where
    # they would be) and before the versioning warnings. @implements FR-0026:AC-13
    lines.extend(_render_open_deferrals(frs, decs, adrs))
    lines.extend(_render_versioning_warnings(frs, trs, decs, adrs))
    # TR and DEC tables sit after the FR table and its warning sections and
    # before the ADR table; both are omitted when empty. @implements FR-0004:AC-6
    lines.extend(_render_tr_table(view_trs))
    lines.extend(_render_dec_table(view_decs))
    lines.extend(_render_adr_sections(adrs))
    # Provisional decisions immediately before Retired objects, both last and
    # both omitted when empty. @implements FR-0005:AC-9
    lines.extend(_render_provisional_table(decs, objs_by_id))
    lines.extend(_render_retired_table(frs, trs, decs, objs_by_id))
    # Pipeline metrics (FR-0002) render last and only when the log has
    # FR-attributable records. Inside render_index, like the FR-0005 default
    # view, so deploy-gate.py's two-argument call writes the same bytes.
    # @implements FR-0002:AC-12
    lines.extend(_render_metrics_section())
    lines.append("")
    return "\n".join(lines)


def _load_codeowners_handle() -> str | None:
    """Read the configured GitHub handle, or return None to skip CODEOWNERS emission."""
    if not CODEOWNERS_CONFIG_PATH.exists():
        print(
            f"INFO: {CODEOWNERS_CONFIG_PATH.relative_to(REPO_ROOT).as_posix()} absent; "
            "skipping CODEOWNERS emission.",
            file=sys.stderr,
        )
        return None
    try:
        cfg = yaml.safe_load(CODEOWNERS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        print(
            f"ERROR: malformed YAML in {CODEOWNERS_CONFIG_PATH.relative_to(REPO_ROOT).as_posix()}: {e}",
            file=sys.stderr,
        )
        return None
    handle = cfg.get("owner_handle")
    if not isinstance(handle, str) or not handle.startswith("@"):
        print(
            f"ERROR: {CODEOWNERS_CONFIG_PATH.relative_to(REPO_ROOT).as_posix()} "
            'must define `owner_handle: "@<github-handle>"`; skipping CODEOWNERS emission.',
            file=sys.stderr,
        )
        return None
    return handle


def render_codeowners(frs: list[FR], handle: str) -> str:
    lines = [
        "# Auto-generated by scripts/index-specs.py — do not edit by hand.",
        "# Source: owns: globs declared in specs/FR-*.md frontmatter.",
        "# Owner handle: read from .agent-team/codeowners-config.yaml (key: owner_handle).",
        "",
    ]
    # Per AC-5: per-FR, sorted by FR ID; within an FR, in declared order.
    # Docs-only FRs (empty `owns:`) are excluded silently per Open Q default.
    for fr in sorted(frs, key=lambda f: f.id):
        if not fr.owns:
            continue
        for glob in fr.owns:
            lines.append(f"{glob} {handle}")
    # Trailing newline so the file is POSIX-friendly and idempotent under
    # editors that auto-append.
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Read-only query modes (FR-0005). JSON keys are the contract H1 (dispatch.py)
# and H7 consume: add, never rename.
# ---------------------------------------------------------------------------


def _rel_posix(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_print(text: str) -> None:
    """Human-readable query output may carry non-ASCII titles; a cp1252
    console must not crash the query (JSON output is ensure_ascii already)."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(text.encode(enc, "replace").decode(enc, "replace"))


def _jsonable(value):  # type: ignore[no-untyped-def]
    if isinstance(value, Path):
        return _rel_posix(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _object_summary(obj, objs_by_id: dict) -> dict:  # type: ignore[no-untyped-def]
    """The per-object JSON record: `id`, `type`, `title`, `visibility`,
    `path` (repo-relative POSIX), plus `version` / `lifecycle` for FR and TR
    or `status` for DEC and ADR; DECs also carry their revision `window`.
    @implements FR-0005:AC-8"""
    kind = object_type(obj)
    out = {
        "id": obj.id,
        "type": kind,
        "title": obj.title,
        "visibility": visibility(obj),
        "path": _rel_posix(obj.path),
    }
    if kind in ("FR", "TR"):
        out["version"] = obj.version
        out["lifecycle"] = obj.lifecycle
    else:
        out["status"] = obj.status
    if kind == "DEC":
        out["window"] = dec_window_class(obj, objs_by_id)[0]
    return out


def _object_fields(obj) -> dict:  # type: ignore[no-untyped-def]
    """Every non-null frontmatter field of a parsed object (no path, no body
    text: `acs` and `withdrawn_acs` are body-derived and Markdown bodies are
    H1's to serialise). @implements FR-0026:AC-5"""
    fields = dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else dict(vars(obj))
    return {
        k: _jsonable(v)
        for k, v in fields.items()
        if k not in ("path", "acs", "withdrawn_acs") and v is not None
    }


def _query_list(graph: SpecGraph, kind: str, include: frozenset[str], as_json: bool) -> int:
    """`--list {fr,tr,dec,adr,all} [--include ...] [--json]`: IDs one per line
    or a JSON array of object summaries, default view unless opted in.
    @implements FR-0005:AC-8"""
    pools = {"fr": graph.frs, "tr": graph.trs, "dec": graph.decs, "adr": graph.adrs}
    objs = [*graph.frs, *graph.trs, *graph.decs, *graph.adrs] if kind == "all" else pools[kind]
    objs_by_id = {obj.id: obj for obj in [*graph.frs, *graph.trs]}
    chosen = select(objs, include, objs_by_id)
    if as_json:
        print(json.dumps([_object_summary(o, objs_by_id) for o in chosen], indent=2))
    else:
        for obj in chosen:
            print(obj.id)
    return 0


def _query_slice(graph: SpecGraph, root_id: str, mode: str, as_json: bool) -> int:
    """`--slice <FR-nnnn|TR-nnnn> [--mode current|migration] [--json]`. An
    unknown root, or a DEC / ADR root, is a stderr message naming the ID and
    exit 1. @implements FR-0005:AC-6, FR-0005:AC-8"""
    try:
        result = slice_graph(graph, root_id, mode)
    except (KeyError, ValueError) as e:
        msg = e.args[0] if e.args else str(e)
        print(f"--slice: {msg}", file=sys.stderr)
        return 1
    objs_by_id = {obj.id: obj for obj in [*graph.frs, *graph.trs]}
    if as_json:
        payload = {
            "root": result.root,
            "mode": result.mode,
            "objects": [
                {**_object_summary(o.obj, objs_by_id), "via": o.via, **_object_fields(o.obj)}
                for o in result.objects
            ],
            "excluded": [
                {"id": e.id, "class": e.visibility, "visibility": e.visibility, "via": e.via}
                for e in result.excluded
            ],
            "notes": list(result.notes),
        }
        print(json.dumps(payload, indent=2))
        return 0
    _safe_print(f"Slice of {result.root} (mode: {result.mode}): {len(result.objects)} object(s)")
    for o in result.objects:
        _safe_print(f"  {o.type:<3} {o.id}  {o.visibility:<10} via {o.via}  - {o.obj.title}")
    if result.excluded:
        print(f"Excluded ({len(result.excluded)}):")
        for e in result.excluded:
            print(f"  - {e.id} ({e.visibility}) via {e.via}")
    if result.notes:
        print(f"Notes ({len(result.notes)}):")
        for n in result.notes:
            print(f"  - {n}")
    return 0


def _query_provisional(graph: SpecGraph, as_of: date, as_json: bool) -> int:
    """`--provisional [--as-of YYYY-MM-DD] [--json]`: default-view DECs with a
    `provisional_until`, grouped `past` / `pending` / `event`, `past` first.
    @implements FR-0005:AC-7, FR-0005:AC-8"""
    objs_by_id = {obj.id: obj for obj in [*graph.frs, *graph.trs]}
    report = provisional(graph.decs, as_of, objs_by_id)

    def entry(dec: DEC) -> dict:
        return {
            "id": dec.id,
            "title": dec.title,
            "trigger": dec.provisional_until,
            "revises": dec.revises,
            "updated": dec.updated,
            "path": _rel_posix(dec.path),
        }

    if as_json:
        payload = {
            "as_of": as_of.isoformat(),
            "past": [entry(d) for d in report.past],
            "pending": [entry(d) for d in report.pending],
            "event": [entry(d) for d in report.event],
        }
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Provisional decisions as of {as_of.isoformat()}")
    for group in ("past", "pending", "event"):
        decs = getattr(report, group)
        print(f"{group} ({len(decs)}):")
        for dec in decs:
            revises = f" - revises {dec.revises}" if dec.revises else ""
            _safe_print(f"  - {dec.id}: {dec.provisional_until}{revises}")
    return 0


def _print_warnings(label: str, warnings: list[str]) -> None:
    if not warnings:
        return
    print(f"{label} ({len(warnings)}):", file=sys.stderr)
    for w in warnings:
        print(f"  - {w}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Index specs/ and validate the FR graph.")
    ap.add_argument(
        "--ac-hashes",
        nargs="?",
        const="*",
        metavar="FR-XXXX",
        help=(
            "Print the normalized hash of every acceptance criterion (the value to "
            "record under ac_state.<n>.hash when ratifying) and exit. Optionally "
            "limit to one FR."
        ),
    )
    ap.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Validate the FR graph and exit non-zero on error. Writes nothing — "
            "for the spec_validate_if_changed hook, which must observe without "
            "rewriting the tracked specs/INDEX.md on every edit."
        ),
    )
    # Read-only query modes (FR-0005). Like --validate they write nothing and
    # fail the same way on a broken graph. @implements FR-0005:AC-8
    ap.add_argument(
        "--list",
        choices=["fr", "tr", "dec", "adr", "all"],
        metavar="{fr,tr,dec,adr,all}",
        help="List default-view objects of a type (IDs one per line, or --json). Writes nothing.",
    )
    ap.add_argument(
        "--include",
        default="",
        metavar="superseded,rejected,history,all",
        help="Comma-separated opt-ins for --list: superseded, rejected, history (pre-breaking DECs), all.",
    )
    ap.add_argument(
        "--slice",
        metavar="FR-XXXX|TR-XXXX",
        help="Print the reachable subgraph rooted at an FR or TR (the H1 seam). Writes nothing.",
    )
    ap.add_argument(
        "--mode",
        choices=["current", "migration"],
        default="current",
        help="Slice mode: current (default) or migration (adds the root's supersedes/superseded_by neighbour).",
    )
    ap.add_argument(
        "--provisional",
        action="store_true",
        help="Report default-view DECs with a provisional_until, grouped past / pending / event. Writes nothing.",
    )
    ap.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        help="Date the --provisional report is evaluated against (default: today).",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit the query result as JSON (with --list, --slice, --provisional).",
    )
    args = ap.parse_args()

    if args.ac_hashes is not None:
        frs, _ = collect_frs()
        target = None if args.ac_hashes == "*" else args.ac_hashes
        for fr in sorted(frs, key=lambda f: f.id):
            if target and fr.id != target:
                continue
            for n in sorted(fr.acs):
                print(f"{fr.id} AC-{n}: {ac_hash(fr.acs[n])}")
        return 0

    # FR, TR and DEC parse errors plus graph / cross-object resolution errors
    # all fail the run, under --validate too. @implements FR-0004:AC-8
    graph = collect_graph()
    frs, trs, decs, adrs = graph.frs, graph.trs, graph.decs, graph.adrs

    if graph.errors:
        print("Spec validation FAILED:", file=sys.stderr)
        for err in graph.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Query modes: read-only, same failure contract as --validate above (a
    # slice over a broken graph is exactly the stale-context risk H2 exists to
    # prevent). @implements FR-0005:AC-8
    if args.list is not None:
        try:
            include = normalise_include(v for v in args.include.split(",") if v.strip())
        except ValueError as e:
            print(f"--include: {e}", file=sys.stderr)
            return 1
        return _query_list(graph, args.list, include, args.json)
    if args.slice is not None:
        return _query_slice(graph, args.slice, args.mode, args.json)
    if args.provisional:
        if args.as_of is None:
            as_of = date.today()
        else:
            try:
                as_of = date.fromisoformat(args.as_of)
            except ValueError:
                print(f"--as-of: {args.as_of!r} is not a YYYY-MM-DD date", file=sys.stderr)
                return 1
        return _query_provisional(graph, as_of, args.json)

    # --validate is a check-only mode: the graph is valid, so report and exit 0
    # without writing INDEX.md or CODEOWNERS. The spec_validate_if_changed hook
    # runs this after every spec edit; writing a tracked file from a validation
    # hook would dirty the tree on each edit — the thing it only means to observe.
    # Warn-only versioning / ADR lint is reported on stderr in both modes
    # (FR-0003 AC-5, AC-7) and never changes the exit code.
    versioning_warnings = _all_versioning_warnings(frs, trs, decs, adrs)
    adr_warnings = _adr_warnings(adrs)
    counts = f"{len(frs)} FRs"
    if trs or decs:
        counts += f", {len(trs)} TRs, {len(decs)} DECs"

    # FR-0026: the exemption and Withdrawn-section warnings print in both
    # modes (only these under --validate, so a tree without them prints what it
    # always did), then the hub IDEA-pointer check, on stderr only and only
    # when a hub is found. @implements FR-0026:AC-1, FR-0026:AC-3
    hub = _find_hub_root(REPO_ROOT)
    pointer_warnings = _deferral_pointer_warnings(frs, decs, adrs, hub)

    if args.validate:
        _print_warnings(
            "AC ratification warnings", _ac_exemption_warnings(frs, decs, adrs)
        )
        _print_warnings("Deferral pointer warnings", pointer_warnings)
        _print_warnings("Versioning warnings", versioning_warnings)
        _print_warnings("ADR warnings", adr_warnings)
        print(f"Spec graph OK ({counts}). Wrote nothing (--validate).")
        return 0

    repo_files = _git_ls_files()

    # Always LF: platform newline translation made a Windows regeneration differ
    # byte-for-byte from CI's. @implements FR-0007:AC-1
    INDEX_PATH.write_text(
        render_index(frs, repo_files, adrs, trs, decs), encoding="utf-8", newline="\n"
    )
    print(f"Wrote {INDEX_PATH.relative_to(REPO_ROOT)} ({counts})")

    # Warn-only: surface AC ratification drift on the console too (it is also
    # rendered into INDEX.md). Never changes the exit code — enforcement is a
    # later phase.
    _print_warnings("AC ratification warnings", _ac_state_warnings(frs, decs, adrs))
    _print_warnings("Deferral pointer warnings", pointer_warnings)
    _print_warnings("Versioning warnings", versioning_warnings)
    _print_warnings("ADR warnings", adr_warnings)
    # Provisional DECs past their date trigger: stderr only, at index time, so
    # INDEX.md never depends on the system date. Never changes the exit code.
    # @implements FR-0005:AC-9
    objs_by_id = {obj.id: obj for obj in [*frs, *trs]}
    for dec in provisional(decs, date.today(), objs_by_id).past:
        print(f"Provisional past trigger: {dec.id} ({dec.provisional_until})", file=sys.stderr)

    handle = _load_codeowners_handle()
    if handle is not None:
        # @implements FR-0007:AC-1
        CODEOWNERS_PATH.write_text(
            render_codeowners(frs, handle), encoding="utf-8", newline="\n"
        )
        print(f"Wrote {CODEOWNERS_PATH.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
