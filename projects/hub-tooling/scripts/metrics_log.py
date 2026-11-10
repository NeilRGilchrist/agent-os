#!/usr/bin/env python3
"""
metrics_log.py — append-only per-project pipeline metrics log (FR-0002 / H6).

One shared emitter + reader for the structured records that `dispatch.py`,
`deploy-gate.py` and `escalation-log.py` produce at the source, so that agent
effectiveness is measured from events rather than mined from transcripts.

Records are single-line JSON objects appended to
`specs/_metrics/<YYYY-MM>.ndjson` (UTC month of `ts`). The module exposes
append and read only — no update, delete or rewrite. Emission is never
load-bearing: `emit()` swallows every failure into exactly one
`WARN: metrics:` stderr line and returns None, and `METRICS_LOG_DISABLED=1`
suppresses all emission.

The normative schema lives in `specs/_metrics/README.md`; this module is the
executable form of it.

Usage:
  python scripts/metrics_log.py query [--kind K]... [--fr FR-XXXX] [--role R]
                                       [--since ISO] [--until ISO] [--table]
                                       [--group-by FIELD]... [--agg AGG]...
  python scripts/metrics_log.py report <name> [--table|--json]
  python scripts/metrics_log.py validate [FILE]
  python scripts/metrics_log.py emit --kind KIND [--source manual] [--role R]
                                      [--object-id ID]... [--json '{...}']

@implements FR-0002:AC-1, FR-0002:AC-2, FR-0002:AC-8, FR-0002:AC-9,
            FR-0002:AC-10, FR-0002:AC-11, FR-0002:AC-13
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

if sys.platform == "win32":  # pragma: no cover - platform-specific
    import msvcrt
else:  # pragma: no cover - platform-specific
    import fcntl

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# Set by `dispatch.py spawn_role` around an agent's spawn (FR-0018 AC-1): the
# primary checkout's log directory, and the project root inside the agent's
# role worktree.
METRICS_DIR_ENV = "DISPATCH_METRICS_DIR"
WORKTREE_ENV = "DISPATCH_WORKTREE"


def _same_directory(a: Path, b: Path) -> bool:
    """True when `a` and `b` name one directory: the same file on disk, or,
    when either cannot be stat'ed, equal resolved paths (case-insensitive on
    Windows)."""
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        pass
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except (OSError, RuntimeError, ValueError):
        return False


def _default_metrics_dir(repo_root: Path) -> Path:
    """The log directory this copy of the module writes to by default.

    `DISPATCH_METRICS_DIR` is followed only when `DISPATCH_WORKTREE` is also
    set and names this module's own `repo_root`: a dispatched agent running
    its role worktree's scripts appends to the primary checkout's log, so its
    branch never carries metrics rows. Any other copy of the scripts (a test
    suite's temporary repository, another checkout) keeps its own
    `specs/_metrics`, as before. The comparison is against whatever project
    root the dispatcher names; only the dispatcher decides that value.
    @implements FR-0018:AC-2
    """
    redirect = os.environ.get(METRICS_DIR_ENV)
    worktree = os.environ.get(WORKTREE_ENV)
    if redirect and worktree and _same_directory(repo_root, Path(worktree)):
        return Path(redirect)
    return repo_root / "specs" / "_metrics"


METRICS_DIR = _default_metrics_dir(REPO_ROOT)
REPORTS_SUBDIR = "reports"
PHI_HOOK_PATH = REPO_ROOT / ".agent-team" / "hooks" / "phi_regex_check.py"
ESCALATION_MATRIX_PATH = REPO_ROOT / ".agent-team" / "escalation-matrix.md"

DISABLED_ENV = "METRICS_LOG_DISABLED"
PROJECT_ENV = "METRICS_PROJECT"
RUN_ID_ENV = "DISPATCH_RUN_ID"

# ---------------------------------------------------------------------------
# Schema (@implements FR-0002:AC-1, FR-0002:AC-2)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
MAX_STRING_LEN = 200

ENVELOPE_FIELDS = (
    "schema_version",
    "record_id",
    "ts",
    "project",
    "kind",
    "source",
    "role",
    "object_ids",
    "run_id",
)

SOURCES = frozenset({"dispatch", "gate", "escalation-log", "manual"})
ROLES = frozenset({"architect", "dev", "rev", "bkf", "mnt", "docs", "orchestrator", "gat"})

RUN_STATUSES = frozenset({"success", "error", "escalation", "timeout", "no-log"})
GATE_OUTCOMES = frozenset({"pass", "fail", "error"})
GATE_FAILURE_CLASSES = frozenset(
    {
        "spec-validation",
        "covers-unknown-fr",
        "covers-malformed-ac",
        "covers-unknown-ac",
        "coverage-missing",
        "script-error",
        # @implements FR-0008:AC-9 — a declared gate's evidence is missing
        # (or, respectively, `verdict: pass` but the recorded `head_sha` is
        # not an ancestor-or-equal of the current dev tip).
        "gate-evidence-missing",
        "gate-evidence-stale",
    }
)
# @implements FR-0026:AC-12 — `ac-exemption-invalid` (an exemption entry the
# indexer does not honour) and `ac-all-exempt` (an FR with no live AC).
GATE_WARNING_CLASSES = frozenset(
    {
        "implements-missing",
        "implements-unknown-fr",
        "ac-format",
        "ac-exemption-invalid",
        "ac-all-exempt",
    }
)
GATE_INVOKED_BY = frozenset({"dispatch-finalize", "hook", "ci", "manual"})
# @implements FR-0008:AC-11 — declared-gate decision enums (distinct from the
# deploy gate's own GATE_* enums above, which describe `gate.run`).
GATE_DECISION_AFTER = frozenset({"dev", "rev"})
GATE_DECISION_REVIEWER = frozenset({"human", "architect"})
GATE_DECISION_VERDICTS = frozenset({"pass", "changes-requested", "bypassed"})
FINDING_TAGS = frozenset({"scope", "spec", "doc", "slice-miss", ""})
RATIFICATION_OUTCOMES = frozenset({"ratified", "rejected"})
REVISION_EVENTS = frozenset({"revision", "supersession"})

# kind -> required kind-specific fields (presence is required; nullability is
# documented per field in specs/_metrics/README.md).
KIND_REQUIRED: dict[str, tuple[str, ...]] = {
    "dispatch.spawn": ("harness", "worktree_status", "base_branch", "model", "round"),
    "dispatch.run": (
        "status",
        "tool_calls_total",
        "tool_calls_by_tool",
        "tool_errors_total",
        "tool_errors_by_tool",
        "tokens_in",
        "tokens_out",
        "duration_s",
        "round",
        "verdict",
        "findings",
    ),
    "dispatch.wave": (
        "fr_count",
        "completed",
        "dev_only",
        "dropped",
        "drop_reasons",
        "rounds_ran",
        "force_escalated",
    ),
    "gate.run": (
        "stage",
        "outcome",
        "failure_classes",
        "warning_classes",
        "counts",
        "invoked_by",
    ),
    "pr.opened": (
        "pr_number",
        "pr_url",
        "draft",
        "head_sha",
        "commits_ahead",
        "files_touched",
        "files_touched_paths",
        "tests_changed",
        "covers_delta",
        "gate_record_id",
    ),
    "pr.refreshed": (
        "pr_number",
        "pr_url",
        "draft",
        "head_sha",
        "commits_ahead",
        "files_touched",
        "files_touched_paths",
        "tests_changed",
        "covers_delta",
        "gate_record_id",
    ),
    "pr.review": ("parent_pr_number", "verdict", "posted_as", "round"),
    "pr.merged": ("pr_number", "merge_sha"),
    "escalation": ("trigger_class",),
    "escalation.resolved": ("trigger_class",),
    # @implements FR-0008:AC-11 — one record per gate verdict, emitted by
    # `gate pass|block`, by `finalize --role gat`, and by a merge past an
    # unsatisfied gate (`reconcile-merged`, verdict "bypassed").
    "gate.decision": ("gate", "after", "reviewer", "verdict", "by", "round", "head_sha"),
}
KINDS = frozenset(KIND_REQUIRED)

# Reserved, nullable, optional: back-filled by H1-H5 / WS1-WS4; no emitter in
# this FR populates them. @implements FR-0002:AC-2
RESERVED_FIELDS = (
    "dec_id",
    "tr_id",
    "tier",
    "ratification_outcome",
    "revision_event",
    "breaking_declared",
    "breaking_observed",
    "dec_proposed_at",
    "dec_ratified_at",
    "slice_id",
)

# Allow-list of top-level fields whose values may carry strings (directly, in
# lists, as dict keys/values, or inside the documented nested shapes). A string
# anywhere under any other field fails validation. @implements FR-0002:AC-13
STRING_FIELDS = frozenset(
    {
        # envelope
        "record_id",
        "ts",
        "project",
        "kind",
        "source",
        "role",
        "object_ids",
        "run_id",
        # dispatch.spawn
        "harness",
        "worktree_status",
        "base_branch",
        "model",
        # dispatch.run
        "status",
        "verdict",
        "findings",
        "tool_calls_by_tool",
        "tool_errors_by_tool",
        # dispatch.wave
        "drop_reasons",
        "rounds_ran",
        "force_escalated",
        # gate.run
        "stage",
        "outcome",
        "failure_classes",
        "warning_classes",
        "invoked_by",
        # pr.*
        "pr_url",
        "head_sha",
        "files_touched_paths",
        "gate_record_id",
        "posted_as",
        "merge_sha",
        # gate.decision
        "gate",
        "after",
        "reviewer",
        "by",
        # escalation
        "trigger_class",
        # reserved
        "dec_id",
        "tr_id",
        "tier",
        "ratification_outcome",
        "revision_event",
        "dec_proposed_at",
        "dec_ratified_at",
        "slice_id",
    }
)

FR_ID_RE = re.compile(r"^FR-\d{4}$")
SPEC_ID_RE = re.compile(r"\b(?:FR|TR|DEC|ADR)-\d{4}\b|\bGOAL-[A-Za-z0-9-]+")
_URL_RE = re.compile(r"\w+://\S+")
_PATH_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)+[\w.-]+")


class MetricsError(ValueError):
    """Raised by `validate()` and `append()` on an invalid record or write."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def warn(message: str) -> None:
    """The one and only stderr surface of this module. @implements FR-0002:AC-9"""
    print(f"WARN: metrics: {message}", file=sys.stderr)


def is_disabled() -> bool:
    return os.environ.get(DISABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def new_id() -> str:
    """32 hex chars, no separators — cannot collide with the PHI hook's
    hyphen/space-grouped digit patterns."""
    return uuid.uuid4().hex


def now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: str) -> dt.datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


_PROJECT_CACHE: dict[str, str] = {}


# @implements FR-0016:AC-1
def project_name(repo_root: Path | None = None) -> str:
    """`METRICS_PROJECT` if set, else the name of the primary checkout's root
    directory — resolved through `git rev-parse --git-common-dir` so records
    written from an agent worktree still carry the project's name, not the
    worktree's (open question Q3 default)."""
    env = os.environ.get(PROJECT_ENV)
    if env:
        return env
    root = repo_root or REPO_ROOT
    key = str(root)
    if key in _PROJECT_CACHE:
        return _PROJECT_CACHE[key]
    name = root.name
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            common = Path(proc.stdout.strip())
            if not common.is_absolute():
                common = (root / common).resolve()
            if common.name == ".git":
                name = common.parent.name or name
    except (OSError, subprocess.SubprocessError):
        pass
    _PROJECT_CACHE[key] = name
    return name


def normalise_role(text: str | None) -> str | None:
    """Map free-text role labels (`Developer`, `dev`, `Reviewer`, ...) onto the
    record enum, or None."""
    if not text:
        return None
    t = text.strip().lower()
    aliases = {
        "architect": "architect",
        "arch": "architect",
        "developer": "dev",
        "dev": "dev",
        "reviewer": "rev",
        "rev": "rev",
        "reviewer-backfill": "bkf",
        "backfill": "bkf",
        "bkf": "bkf",
        "maintainer": "mnt",
        "mnt": "mnt",
        "gate-review": "gat",
        "gat": "gat",
        "docs": "docs",
        "documentation": "docs",
        "orchestrator": "orchestrator",
        "dispatcher": "orchestrator",
    }
    return aliases.get(t)


def kebab(text: str) -> str:
    text = re.sub(r"['’]", "", text.strip().lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


_DEFAULT_TRIGGER_ROWS = (
    "Spec is ambiguous",
    "Code doesn't satisfy AC",
    "AC has no test",
    "Test reveals spec gap",
    "Code outside FR scope",
    "Two ACs contradict",
    "FR contradicts user intent",
    "Cross-FR conflict",
    "Security / privacy / legal concern",
    "Dev-Reviewer loop hits 3 cycles",
    "Architect is being asked to override an existing ADR",
)


def matrix_trigger_classes(matrix_path: Path | None = None) -> list[str]:
    """Kebab-case first-column cells of the escalation matrix's decision
    table, falling back to the template's rows when the file is absent."""
    path = matrix_path or ESCALATION_MATRIX_PATH
    rows: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if in_table:
                break  # only the first table is the decision tree
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if set(first) <= set("-: ") and first:
            in_table = True
            continue
        if not in_table:
            continue  # header row
        if first.lower() in {"situation", "loop"}:
            continue
        k = kebab(first)
        if k and k not in rows:
            rows.append(k)
    if not rows:
        rows = [kebab(r) for r in _DEFAULT_TRIGGER_ROWS]
    return rows


def trigger_class(trigger: str | None, matrix_path: Path | None = None) -> str:
    """Normalise an escalation trigger to a matrix row (kebab-case) or `other`.
    Only the class is stored, never the trigger text. @implements FR-0002:AC-6"""
    if not trigger:
        return "other"
    k = kebab(trigger)
    if not k:
        return "other"
    classes = matrix_trigger_classes(matrix_path)
    if k in classes:
        return k
    # Tolerate the common paraphrases without storing them.
    for cls in classes:
        if k.startswith(cls) or cls.startswith(k):
            return cls
    return "other"


def spec_refs(text: str) -> list[str]:
    """Spec-object IDs (FR-/TR-/DEC-/ADR-/GOAL-) and repo-relative paths found
    in a finding's text, deduplicated, IDs first. The text itself is never
    stored. @implements FR-0002:AC-7"""
    refs: list[str] = []
    for m in SPEC_ID_RE.finditer(text):
        if m.group(0) not in refs:
            refs.append(m.group(0))
    stripped = _URL_RE.sub(" ", text)
    for m in _PATH_RE.finditer(stripped):
        tok = m.group(0).rstrip(".,;:)]}`'\"")
        if "/" in tok and tok not in refs and not tok.startswith("/"):
            refs.append(tok)
    return refs


# ---------------------------------------------------------------------------
# Record construction and validation
# ---------------------------------------------------------------------------


def make_record(
    kind: str,
    *,
    source: str,
    role: str | None = None,
    object_ids: Sequence[str] = (),
    run_id: str | None = None,
    record_id: str | None = None,
    ts: str | None = None,
    project: str | None = None,
    **fields: Any,
) -> dict:
    """Build a record envelope plus kind-specific fields. Does not validate."""
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id or new_id(),
        "ts": ts or now_ts(),
        "project": project or project_name(),
        "kind": kind,
        "source": source,
        "role": role,
        "object_ids": list(object_ids),
        "run_id": run_id,
    }
    record.update(fields)
    return record


def _iter_strings(value: Any, *, keys: bool) -> Iterator[str]:
    """Yield every string in a JSON-like value. `keys` selects dict keys
    (identifier position) versus values."""
    if isinstance(value, str):
        if not keys:
            yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if keys and isinstance(k, str):
                yield k
            yield from _iter_strings(v, keys=keys)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item, keys=keys)


def validation_errors(record: Any) -> list[str]:
    """Every reason `record` is invalid; empty when valid.
    @implements FR-0002:AC-1, FR-0002:AC-2, FR-0002:AC-13"""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record is not a JSON object"]

    for name in ENVELOPE_FIELDS:
        if name not in record:
            errors.append(f"missing envelope field {name!r}")
    if errors:
        return errors

    if not isinstance(record["schema_version"], int) or isinstance(record["schema_version"], bool):
        errors.append("schema_version must be an integer")
    if not isinstance(record["record_id"], str) or not record["record_id"]:
        errors.append("record_id must be a non-empty string")
    ts = record["ts"]
    if not isinstance(ts, str):
        errors.append("ts must be an ISO-8601 string")
    else:
        try:
            parse_ts(ts)
        except ValueError:
            errors.append(f"ts {ts!r} is not ISO-8601")
    if not isinstance(record["project"], str) or not record["project"]:
        errors.append("project must be a non-empty string")
    kind = record["kind"]
    if kind not in KINDS:
        errors.append(f"unknown kind {kind!r}")
    if record["source"] not in SOURCES:
        errors.append(f"unknown source {record['source']!r}")
    role = record["role"]
    if role is not None and role not in ROLES:
        errors.append(f"unknown role {role!r}")
    oids = record["object_ids"]
    if not isinstance(oids, list) or not all(isinstance(o, str) for o in oids):
        errors.append("object_ids must be a list of strings")
    if record["run_id"] is not None and not isinstance(record["run_id"], str):
        errors.append("run_id must be a string or null")

    for name in KIND_REQUIRED.get(kind, ()):
        if name not in record:
            errors.append(f"{kind}: missing required field {name!r}")

    # Kind-specific enums (only when the field is present and non-null).
    def _enum(name: str, allowed: frozenset[str], nullable: bool = False) -> None:
        if name not in record:
            return
        v = record[name]
        if v is None and nullable:
            return
        if v not in allowed:
            errors.append(f"{name} {v!r} not in {sorted(allowed)}")

    def _enum_list(name: str, allowed: frozenset[str]) -> None:
        if name not in record:
            return
        v = record[name]
        if not isinstance(v, list):
            errors.append(f"{name} must be a list")
            return
        bad = [x for x in v if x not in allowed]
        if bad:
            errors.append(f"{name} has values outside the enum: {bad!r}")

    if kind == "dispatch.run":
        _enum("status", RUN_STATUSES)
        if isinstance(record.get("findings"), list):
            for f in record["findings"]:
                if not isinstance(f, dict) or set(f) - {"tag", "refs", "chars"}:
                    errors.append("findings entries must be {tag, refs, chars}")
                    break
                if f.get("tag") not in FINDING_TAGS:
                    errors.append(f"finding tag {f.get('tag')!r} unknown")
        elif "findings" in record:
            errors.append("findings must be a list")
    elif kind == "gate.run":
        _enum("outcome", GATE_OUTCOMES)
        _enum_list("failure_classes", GATE_FAILURE_CLASSES)
        _enum_list("warning_classes", GATE_WARNING_CLASSES)
        _enum("invoked_by", GATE_INVOKED_BY)
    elif kind == "gate.decision":
        # @implements FR-0008:AC-11
        _enum("after", GATE_DECISION_AFTER)
        _enum("reviewer", GATE_DECISION_REVIEWER)
        _enum("verdict", GATE_DECISION_VERDICTS)
        if not isinstance(record.get("gate"), str) or not record.get("gate"):
            errors.append("gate.decision: 'gate' must be a non-empty string")
        if not isinstance(record.get("by"), str) or not record.get("by"):
            errors.append("gate.decision: 'by' must be a non-empty string")
        rnd = record.get("round")
        if not isinstance(rnd, int) or isinstance(rnd, bool) or rnd < 1:
            errors.append("gate.decision: 'round' must be an integer >= 1")
        head_sha = record.get("head_sha")
        if head_sha is not None and not isinstance(head_sha, str):
            errors.append("gate.decision: 'head_sha' must be a string or null")
    _enum("ratification_outcome", RATIFICATION_OUTCOMES, nullable=True)
    _enum("revision_event", REVISION_EVENTS, nullable=True)
    for name in ("breaking_declared", "breaking_observed"):
        if name in record and record[name] is not None and not isinstance(record[name], bool):
            errors.append(f"{name} must be a boolean or null")

    # Privacy rules: string cap everywhere; strings only under allow-listed
    # fields (dict keys are identifiers and are only length-checked).
    for name, value in record.items():
        if name == "schema_version":
            continue
        for s in _iter_strings(value, keys=True):
            if len(s) > MAX_STRING_LEN:
                errors.append(f"{name}: key longer than {MAX_STRING_LEN} chars")
                break
        has_string = False
        for s in _iter_strings(value, keys=False):
            has_string = True
            if len(s) > MAX_STRING_LEN:
                errors.append(f"{name}: string value longer than {MAX_STRING_LEN} chars")
                break
        if has_string and name not in STRING_FIELDS:
            errors.append(f"{name}: string-bearing field is not on the schema allow-list")
    return errors


def validate(record: Any) -> None:
    """Raise MetricsError unless `record` is valid. @implements FR-0002:AC-1"""
    errors = validation_errors(record)
    if errors:
        raise MetricsError("; ".join(errors))


# ---------------------------------------------------------------------------
# PHI guard (@implements FR-0002:AC-13)
# ---------------------------------------------------------------------------

_PHI_PATTERNS: list[tuple[re.Pattern[str], str]] | None = None
_PHI_PATH_LOADED: Path | None = None


def phi_patterns(hook_path: Path | None = None) -> list[tuple[re.Pattern[str], str]]:
    """The compliance hook's `PHI_PATTERNS`, when the hook exists; else []."""
    global _PHI_PATTERNS, _PHI_PATH_LOADED
    path = hook_path or PHI_HOOK_PATH
    if _PHI_PATTERNS is not None and _PHI_PATH_LOADED == path:
        return _PHI_PATTERNS
    patterns: list[tuple[re.Pattern[str], str]] = []
    if path.exists():
        try:
            spec = importlib.util.spec_from_file_location("_metrics_phi_hook", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for entry in getattr(mod, "PHI_PATTERNS", []) or []:
                    pat, label = entry[0], (entry[1] if len(entry) > 1 else "PHI pattern")
                    patterns.append((re.compile(pat), str(label)))
        except Exception as e:  # noqa: BLE001 — a broken hook must not break emission
            warn(f"phi hook unusable ({type(e).__name__}); continuing without it")
    _PHI_PATTERNS = patterns
    _PHI_PATH_LOADED = path
    return patterns


def phi_hits(record: dict, hook_path: Path | None = None) -> list[str]:
    """Labels of every PHI pattern matched by any string in the record."""
    patterns = phi_patterns(hook_path)
    if not patterns:
        return []
    hits: list[str] = []
    strings = list(_iter_strings(record, keys=False)) + list(_iter_strings(record, keys=True))
    for pat, label in patterns:
        if any(pat.search(s) for s in strings) and label not in hits:
            hits.append(label)
    return hits


# ---------------------------------------------------------------------------
# Append (the only write) and read
# ---------------------------------------------------------------------------


def month_file(ts: str, metrics_dir: Path | None = None) -> Path:
    """`<metrics_dir>/<YYYY-MM>.ndjson` for the UTC month of `ts`."""
    when = parse_ts(ts)
    return (metrics_dir or METRICS_DIR) / f"{when.year:04d}-{when.month:02d}.ndjson"


# Concurrent appends are serialised with an OS-level lock on the month file
# itself (no sidecar file, nothing to clean up, released by the kernel if the
# holder dies). POSIX `open(..., "a")` is already atomic per write (O_APPEND),
# but the Windows CRT implements append as seek-to-end + write, so two writers
# interleave and lose or split lines without the lock. On Windows the lock is
# one byte at a fixed offset far beyond any plausible file size, so it is the
# same byte for every writer whatever the file's length (including an empty,
# just-created file) and never covers a byte a concurrent reader would touch
# (a Windows region lock blocks other processes' reads of that region).
LOCK_TIMEOUT_S = 10.0
_LOCK_RETRY_S = 0.005
_LOCK_OFFSET = 0x7FFF_FFFF_FFFF_0000


def _lock(fd: int) -> None:
    """Take an exclusive lock on `fd`, polling non-blocking until acquired or
    `LOCK_TIMEOUT_S` elapses. Raises MetricsError on timeout so `emit()` can
    degrade to its single WARN line instead of hanging the caller."""
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            if sys.platform == "win32":
                os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as e:
            if time.monotonic() >= deadline:
                raise MetricsError(f"lock not acquired within {LOCK_TIMEOUT_S:g}s: {e}") from e
            time.sleep(_LOCK_RETRY_S)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def append(record: dict, metrics_dir: Path | None = None) -> Path:
    """Validate and append one record as one line; create dir/file on first
    write; flush per record. The complete line is written as a single `bytes`
    write under an exclusive OS lock (see `_lock`), so concurrent writers
    never interleave and a reader never sees a partial line. Raises
    MetricsError. @implements FR-0002:AC-8"""
    validate(record)
    path = month_file(record["ts"], metrics_dir)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if "\n" in line or "\r" in line:
        raise MetricsError("record serialises across more than one line")
    data = (line + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fd = fh.fileno()
            _lock(fd)
            try:
                os.lseek(fd, 0, os.SEEK_END)
                view = memoryview(data)
                while view:  # os.write may, in theory, write fewer bytes than asked
                    view = view[os.write(fd, view):]
                fh.flush()
            finally:
                _unlock(fd)
    except OSError as e:
        raise MetricsError(f"cannot append to {path}: {e}") from e
    return path


def emit(
    kind: str,
    *,
    source: str,
    role: str | None = None,
    object_ids: Sequence[str] = (),
    run_id: str | None = None,
    record_id: str | None = None,
    metrics_dir: Path | None = None,
    **fields: Any,
) -> dict | None:
    """Build, validate, PHI-check and append a record. Never raises; every
    failure is exactly one `WARN: metrics:` line and a None return.
    @implements FR-0002:AC-9, FR-0002:AC-13"""
    if is_disabled():
        return None
    try:
        record = make_record(
            kind,
            source=source,
            role=role,
            object_ids=object_ids,
            run_id=run_id,
            record_id=record_id,
            **fields,
        )
        validate(record)
        hits = phi_hits(record)
        if hits:
            warn(f"{kind} record dropped: matched {', '.join(hits)}")
            return None
        append(record, metrics_dir)
        return record
    except Exception as e:  # noqa: BLE001 — emission must never be load-bearing
        warn(f"{kind}: {type(e).__name__}: {e}")
        return None


def month_files(metrics_dir: Path | None = None) -> list[Path]:
    d = metrics_dir or METRICS_DIR
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.ndjson") if p.is_file())


def iter_records(metrics_dir: Path | None = None) -> Iterator[dict]:
    """Every parseable record across every month file, oldest file first,
    file order within a file. Unknown kinds and extra fields are tolerated;
    unparseable lines are skipped. @implements FR-0002:AC-10"""
    for path in month_files(metrics_dir):
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        yield obj
        except OSError:
            continue


def read_records(metrics_dir: Path | None = None) -> list[dict]:
    return list(iter_records(metrics_dir))


# ---------------------------------------------------------------------------
# Query surface (@implements FR-0002:AC-10)
# ---------------------------------------------------------------------------


def _record_frs(record: dict) -> list[str]:
    return [o for o in record.get("object_ids") or [] if isinstance(o, str) and FR_ID_RE.match(o)]


def attach_fr_context(records: Iterable[dict]) -> list[dict]:
    """Return copies of `records` carrying a virtual `fr` list: the FR IDs in
    `object_ids`, or — when there are none — the FRs of the dispatch records
    sharing the same `run_id` (so a Developer's gate run in a worktree joins
    its FR). The virtual field is never persisted."""
    recs = [dict(r) for r in records]
    by_run: dict[str, list[str]] = {}
    for r in recs:
        rid = r.get("run_id")
        if isinstance(rid, str) and str(r.get("kind", "")).startswith("dispatch."):
            for fr in _record_frs(r):
                by_run.setdefault(rid, [])
                if fr not in by_run[rid]:
                    by_run[rid].append(fr)
    for r in recs:
        frs = _record_frs(r)
        if not frs:
            rid = r.get("run_id")
            if isinstance(rid, str):
                frs = list(by_run.get(rid, []))
        r["fr"] = frs
    return recs


def get_field(record: dict, dotted: str) -> Any:
    cur: Any = record
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in (b or []),
    "not-in": lambda a, b: a not in (b or []),
    "contains": lambda a, b: isinstance(a, (list, str)) and b in a,
}


def _where_ok(record: dict, where: Sequence[Sequence[Any]]) -> bool:
    for clause in where or []:
        if len(clause) != 3:
            raise MetricsError(f"where clause must be [field, op, value]: {clause!r}")
        field, op, value = clause
        fn = _OPS.get(str(op))
        if fn is None:
            raise MetricsError(f"unknown where operator {op!r}")
        actual = get_field(record, str(field))
        if field == "fr" and isinstance(actual, list):
            if not any(fn(a, value) for a in actual):
                return False
            continue
        if not fn(actual, value):
            return False
    return True


def filter_records(
    records: Iterable[dict],
    *,
    kinds: Sequence[str] | None = None,
    fr: str | None = None,
    role: str | None = None,
    since: str | None = None,
    until: str | None = None,
    where: Sequence[Sequence[Any]] | None = None,
) -> list[dict]:
    """Filter records (which should carry the virtual `fr` field from
    `attach_fr_context`). `since` is inclusive, `until` exclusive."""
    since_dt = parse_ts(since) if since else None
    until_dt = parse_ts(until) if until else None
    out: list[dict] = []
    for r in records:
        if kinds and r.get("kind") not in kinds:
            continue
        if fr and fr not in (r.get("fr") if "fr" in r else _record_frs(r)):
            continue
        if role and r.get("role") != role:
            continue
        if since_dt or until_dt:
            try:
                ts = parse_ts(str(r.get("ts", "")))
            except ValueError:
                continue
            if since_dt and ts < since_dt:
                continue
            if until_dt and ts >= until_dt:
                continue
        if where and not _where_ok(r, where):
            continue
        out.append(r)
    return out


def _explode_groups(record: dict, group_by: Sequence[str]) -> list[tuple]:
    """Group keys for a record; the virtual `fr` field fans out one key per
    FR so a record about two FRs counts once for each."""
    keys: list[tuple] = [()]
    for field in group_by:
        value = get_field(record, field)
        values = value if (field == "fr" and isinstance(value, list)) else [value]
        if field == "fr" and not values:
            values = [None]
        keys = [k + (_hashable(v),) for k in keys for v in values]
    return keys


def _hashable(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def parse_agg(spec: str) -> tuple[str, str | None]:
    op, _, field = spec.partition(":")
    op = op.strip()
    field = field.strip() or None
    if op == "count":
        return ("count", None)
    if op in {"sum", "avg", "max", "min", "distinct"} and field:
        return (op, field)
    raise MetricsError(f"unknown aggregation {spec!r} (count|sum:<f>|avg:<f>|max:<f>|min:<f>|distinct:<f>)")


def aggregate(
    records: Iterable[dict],
    group_by: Sequence[str],
    aggs: dict[str, str],
) -> list[dict]:
    """Group `records` by `group_by` fields and compute `aggs`
    ({output_name: 'count'|'sum:<f>'|'avg:<f>'|'max:<f>'|'min:<f>'|'distinct:<f>'}).
    Rows are sorted by group key for deterministic output."""
    parsed = {name: parse_agg(spec) for name, spec in aggs.items()}
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        for key in _explode_groups(r, group_by):
            groups.setdefault(key, []).append(r)
    rows: list[dict] = []
    for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
        members = groups[key]
        row: dict[str, Any] = {field: key[i] for i, field in enumerate(group_by)}
        for name, (op, field) in parsed.items():
            if op == "count":
                row[name] = len(members)
                continue
            values = [get_field(m, field) for m in members]  # type: ignore[arg-type]
            if op == "distinct":
                seen: list[Any] = []
                for v in values:
                    for item in v if isinstance(v, list) else [v]:
                        if item is not None and item not in seen:
                            seen.append(item)
                row[name] = sorted(seen, key=str)
                continue
            nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if not nums:
                row[name] = None
            elif op == "sum":
                row[name] = sum(nums)
            elif op == "avg":
                row[name] = round(sum(nums) / len(nums), 3)
            elif op == "max":
                row[name] = max(nums)
            elif op == "min":
                row[name] = min(nums)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Named reports (@implements FR-0002:AC-10, FR-0002:AC-11)
# ---------------------------------------------------------------------------


def reports_dir(metrics_dir: Path | None = None) -> Path:
    return (metrics_dir or METRICS_DIR) / REPORTS_SUBDIR


def load_report(name: str, metrics_dir: Path | None = None) -> dict:
    """Read `specs/_metrics/reports/<name>.json`."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise MetricsError(f"invalid report name {name!r}")
    path = reports_dir(metrics_dir) / f"{name}.json"
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MetricsError(f"no report named {name!r} under {path.parent}") from None
    except (OSError, json.JSONDecodeError) as e:
        raise MetricsError(f"cannot read report {name!r}: {e}") from e
    if not isinstance(spec, dict):
        raise MetricsError(f"report {name!r} must be a JSON object")
    spec.setdefault("name", name)
    return spec


def _section_rows(section: dict, records: list[dict]) -> list[dict]:
    filters = section.get("filters") or {}
    kinds = filters.get("kind")
    if isinstance(kinds, str):
        kinds = [kinds]
    subset = filter_records(
        records,
        kinds=kinds,
        fr=filters.get("fr"),
        role=filters.get("role"),
        since=filters.get("since"),
        until=filters.get("until"),
        where=section.get("where") or filters.get("where"),
    )
    group_by = section.get("group_by") or []
    if isinstance(group_by, str):
        group_by = [group_by]
    aggs = section.get("aggs") or {"count": "count"}
    return aggregate(subset, group_by, aggs)


def run_report(spec: dict, records: Iterable[dict]) -> dict[str, list[dict]]:
    """Execute a report definition (a dict of filters + aggregations, or a
    list of such `sections`) and return {section_name: rows}."""
    recs = attach_fr_context(records)
    sections = spec.get("sections")
    if not sections:
        sections = [dict(spec, name=spec.get("name", "report"))]
    out: dict[str, list[dict]] = {}
    for i, section in enumerate(sections):
        if not isinstance(section, dict):
            raise MetricsError("report sections must be objects")
        name = str(section.get("name") or f"section_{i + 1}")
        out[name] = _section_rows(section, recs)
    return out


# ---------------------------------------------------------------------------
# Per-FR summary for INDEX.md (@implements FR-0002:AC-12)
# ---------------------------------------------------------------------------


def _sort_key(record: dict) -> tuple:
    try:
        return (parse_ts(str(record.get("ts", ""))).isoformat(), 0)
    except ValueError:
        return ("", 0)


def summarize_by_fr(records: Iterable[dict]) -> dict[str, dict]:
    """Per FR: latest `dispatch.run` status per role, total tool calls, the
    three retry measures of AC-11 (Developer runs beyond round 1, tool errors,
    failed gate runs with their classes), last gate outcome, last PR number.
    Deterministic: driven by `ts` then file order."""
    recs = attach_fr_context(records)
    indexed = sorted(enumerate(recs), key=lambda pair: (_sort_key(pair[1]), pair[0]))
    out: dict[str, dict] = {}

    def slot(fr: str) -> dict:
        return out.setdefault(
            fr,
            {
                "latest_status_by_role": {},
                "tool_calls": 0,
                "rework_rounds": 0,
                "tool_errors": 0,
                "gate_failures": 0,
                "gate_failure_classes": [],
                "last_gate": None,
                "last_pr": None,
            },
        )

    for _, r in indexed:
        kind = r.get("kind")
        for fr in r.get("fr") or []:
            s = slot(fr)
            if kind == "dispatch.run":
                role = r.get("role") or "null"
                s["latest_status_by_role"][role] = r.get("status")
                tc = r.get("tool_calls_total")
                if isinstance(tc, (int, float)) and not isinstance(tc, bool):
                    s["tool_calls"] += int(tc)
                te = r.get("tool_errors_total")
                if isinstance(te, (int, float)) and not isinstance(te, bool):
                    s["tool_errors"] += int(te)
                rnd = r.get("round")
                if r.get("role") == "dev" and isinstance(rnd, int) and rnd > 1:
                    s["rework_rounds"] += 1
            elif kind == "gate.run":
                s["last_gate"] = r.get("outcome")
                if r.get("outcome") != "pass":
                    s["gate_failures"] += 1
                    for cls in r.get("failure_classes") or []:
                        if cls not in s["gate_failure_classes"]:
                            s["gate_failure_classes"].append(cls)
            elif kind in {"pr.opened", "pr.refreshed", "pr.merged"}:
                if r.get("pr_number") is not None:
                    s["last_pr"] = r.get("pr_number")
            elif kind == "pr.review":
                if r.get("parent_pr_number") is not None:
                    s["last_pr"] = r.get("parent_pr_number")
    return out


def render_index_section(records: Iterable[dict]) -> list[str]:
    """Markdown lines for `## Pipeline metrics`, or [] when there are no
    records with an FR to attribute to. Shared by index-specs.py (and, through
    it, deploy-gate.py) so both writers stay byte-identical."""
    summary = summarize_by_fr(records)
    if not summary:
        return []
    lines = [
        "",
        "## Pipeline metrics",
        "",
        (
            "_From `specs/_metrics/*.ndjson` (schema: `specs/_metrics/README.md`). "
            "Query with `python scripts/metrics_log.py query --fr FR-XXXX`._"
        ),
        "",
        "| FR | Latest run status | Tool calls | Retries | Last gate | Last PR |",
        "|----|-------------------|------------|---------|-----------|---------|",
    ]
    for fr in sorted(summary):
        s = summary[fr]
        statuses = ", ".join(f"{role}: {status}" for role, status in sorted(s["latest_status_by_role"].items()))
        retries = (
            f"{s['rework_rounds']} rework, {s['tool_errors']} tool errors, "
            f"{s['gate_failures']} gate fails"
        )
        if s["gate_failure_classes"]:
            retries += f" ({', '.join(sorted(s['gate_failure_classes']))})"
        last_gate = s["last_gate"] or "—"
        last_pr = f"#{s['last_pr']}" if s["last_pr"] is not None else "—"
        lines.append(
            f"| {fr} | {statuses or '—'} | {s['tool_calls']} | {retries} | {last_gate} | {last_pr} |"
        )
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_table(rows: list[dict], columns: Sequence[str] | None = None) -> str:
    if not rows:
        return "(no rows)"
    cols = list(columns) if columns else []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    cells = [[_fmt_cell(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    out = [
        " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)),
        "-+-".join("-" * w for w in widths),
    ]
    out.extend(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in cells)
    return "\n".join(out)


_QUERY_COLUMNS = ("ts", "kind", "source", "role", "object_ids", "run_id", "status", "outcome")


def _cmd_query(args: argparse.Namespace, metrics_dir: Path) -> int:
    recs = attach_fr_context(iter_records(metrics_dir))
    try:
        where = [json.loads(w) for w in (args.where or [])]
        subset = filter_records(
            recs,
            kinds=args.kind or None,
            fr=args.fr,
            role=args.role,
            since=args.since,
            until=args.until,
            where=where or None,
        )
    except (MetricsError, ValueError, json.JSONDecodeError) as e:
        print(f"query: {e}", file=sys.stderr)
        return 2
    if args.group_by or args.agg:
        aggs: dict[str, str] = {}
        for spec in args.agg or ["count"]:
            try:
                parse_agg(spec)
            except MetricsError as e:
                print(f"query: {e}", file=sys.stderr)
                return 2
            aggs[spec.replace(":", "_")] = spec
        try:
            rows = aggregate(subset, args.group_by or [], aggs)
        except MetricsError as e:
            print(f"query: {e}", file=sys.stderr)
            return 2
        if args.table:
            print(render_table(rows))
        else:
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.table:
        for r in subset:
            r.pop("fr", None)
        print(render_table(subset, _QUERY_COLUMNS))
        return 0
    for r in subset:
        r.pop("fr", None)
        print(json.dumps(r, ensure_ascii=False))
    return 0


def _cmd_report(args: argparse.Namespace, metrics_dir: Path) -> int:
    try:
        spec = load_report(args.name, metrics_dir)
        result = run_report(spec, iter_records(metrics_dir))
    except MetricsError as e:
        print(f"report: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"report": spec.get("name", args.name), "sections": result}, ensure_ascii=False, indent=2))
        return 0
    if args.table:
        if spec.get("description"):
            print(f"# {spec.get('name', args.name)} — {spec['description']}")
        for name, rows in result.items():
            print(f"\n## {name}")
            print(render_table(rows))
        return 0
    for name, rows in result.items():
        for row in rows:
            print(json.dumps({"section": name, **row}, ensure_ascii=False))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    source = sys.stdin if args.file in (None, "-") else open(args.file, encoding="utf-8")  # noqa: SIM115
    bad = 0
    total = 0
    with source:
        for lineno, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"line {lineno}: not JSON ({e.msg})")
                bad += 1
                continue
            errors = validation_errors(obj)
            if errors:
                bad += 1
                print(f"line {lineno}: " + "; ".join(errors))
    print(f"{total - bad}/{total} records valid")
    return 1 if bad else 0


def _cmd_emit(args: argparse.Namespace, metrics_dir: Path) -> int:
    fields: dict[str, Any] = {}
    if args.json:
        try:
            fields = json.loads(args.json)
        except json.JSONDecodeError as e:
            print(f"emit: --json is not valid JSON: {e.msg}", file=sys.stderr)
            return 2
        if not isinstance(fields, dict):
            print("emit: --json must be an object", file=sys.stderr)
            return 2
    record = make_record(
        args.kind,
        source=args.source,
        role=args.role,
        object_ids=args.object_id or [],
        run_id=args.run_id or os.environ.get(RUN_ID_ENV),
        **fields,
    )
    if is_disabled():
        print(f"emit: {DISABLED_ENV} is set; nothing written", file=sys.stderr)
        return 0
    try:
        validate(record)
        hits = phi_hits(record)
        if hits:
            print(f"emit: record dropped, matched {', '.join(hits)}", file=sys.stderr)
            return 1
        path = append(record, metrics_dir)
    except MetricsError as e:
        print(f"emit: {e}", file=sys.stderr)
        return 1
    print(f"{record['record_id']} -> {path}")
    return 0


def _metrics_dir_help() -> str:
    """`METRICS_DIR` for `--metrics-dir`'s help: repo-relative when it lies
    under `REPO_ROOT`, else absolute (the FR-0018 redirect), with `%` escaped
    for argparse. @implements FR-0018:AC-2"""
    try:
        shown = METRICS_DIR.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = str(METRICS_DIR)
    return shown.replace("%", "%%")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Append-only pipeline metrics log: query, report, validate, emit.")
    ap.add_argument(
        "--metrics-dir",
        type=Path,
        default=None,
        help=f"Override the log directory (default: {_metrics_dir_help()}).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_q = sub.add_parser("query", help="Filter records; stream NDJSON (default) or a table; optionally aggregate.")
    p_q.add_argument("--kind", action="append", help="Record kind (repeatable).")
    p_q.add_argument("--fr", help="FR id the record is about (object_ids, or joined through run_id).")
    p_q.add_argument("--role", help="Role enum value.")
    p_q.add_argument("--since", help="Inclusive lower bound on ts (ISO-8601).")
    p_q.add_argument("--until", help="Exclusive upper bound on ts (ISO-8601).")
    p_q.add_argument("--where", action="append", help='Extra clause as JSON: \'["round","gt",1]\' (repeatable).')
    p_q.add_argument("--group-by", action="append", help="Field to group by (repeatable; `fr` is the virtual FR field).")
    p_q.add_argument("--agg", action="append", help="count | sum:<f> | avg:<f> | max:<f> | min:<f> | distinct:<f> (repeatable).")
    p_q.add_argument("--table", action="store_true", help="Render a table instead of NDJSON.")

    p_r = sub.add_parser("report", help="Run a named report from specs/_metrics/reports/<name>.json.")
    p_r.add_argument("name")
    p_r.add_argument("--table", action="store_true", help="Render tables per section.")
    p_r.add_argument("--json", action="store_true", help="Emit one JSON document with every section.")

    p_v = sub.add_parser("validate", help="Validate NDJSON records from a file or stdin (read-only).")
    p_v.add_argument("file", nargs="?", help="Path to an .ndjson file (default: stdin).")

    p_e = sub.add_parser("emit", help="Append one record by hand (the only mutating subcommand).")
    p_e.add_argument("--kind", required=True, choices=sorted(KINDS))
    p_e.add_argument("--source", default="manual", choices=sorted(SOURCES))
    p_e.add_argument("--role", default=None, choices=sorted(ROLES))
    p_e.add_argument("--object-id", action="append", help="Spec-object id the record is about (repeatable).")
    p_e.add_argument("--run-id", default=None, help=f"Run id (default: ${RUN_ID_ENV} if set).")
    p_e.add_argument("--json", default=None, help="Kind-specific fields as a JSON object.")

    args = ap.parse_args(argv)
    # Records carry em-dashes and arbitrary tool names; never crash a Windows
    # console on encoding (same guard as dispatch.py).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass
    metrics_dir = args.metrics_dir or METRICS_DIR
    if args.cmd == "query":
        return _cmd_query(args, metrics_dir)
    if args.cmd == "report":
        return _cmd_report(args, metrics_dir)
    if args.cmd == "validate":
        return _cmd_validate(args)
    if args.cmd == "emit":
        return _cmd_emit(args, metrics_dir)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
