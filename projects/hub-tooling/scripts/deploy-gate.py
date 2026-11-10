#!/usr/bin/env python3
"""
deploy-gate.py — Pre-merge gate for agent-driven PRs

Verifies the spec graph and traceability invariants that the agent workflow
depends on. Designed to run in CI (and locally before declaring work done).

Checks performed:

1. Spec graph validates (delegates to index-specs.py parsing)
2. Every FR with status in-review or merged has at least one test annotated
   with @covers FR-XXXX:AC-Y for every AC in the FR, except the ACs the
   indexer reports exempt (a deferred, withdrawn or superseded `ac_state`
   entry with a valid `moved_to`)
3. Every @covers annotation in tests/ references a real FR and AC (an exempt
   AC counts as real)
4. No orphan @covers (referencing deleted FRs)
5. @implements FR-XXXX tags in src/ are cross-referenced against the spec
   graph; FRs in dev or later status without any @implements tag produce
   warnings (not failures)

Exits 0 on pass, 1 on gate failure or script error (a script error re-raises
the exception after emitting its metrics record, so the interpreter's normal
traceback-then-exit-1 behavior applies).

Usage:
  python3 scripts/deploy-gate.py              # Full check
  python3 scripts/deploy-gate.py --stage dev  # Lighter check for Developer stage
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Import shared parsing from the sibling index-specs module to avoid
# duplicating frontmatter/YAML parsing logic (DRY).
import importlib.util as _ilu

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

def _import_from(filename: str, module_name: str):  # type: ignore[no-untyped-def]
    spec = _ilu.spec_from_file_location(module_name, _SCRIPTS_DIR / filename)
    mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

_index_specs = _import_from("index-specs.py", "index_specs")
collect_frs = _index_specs.collect_frs
validate_graph = _index_specs.validate_graph
render_index = _index_specs.render_index
FR = _index_specs.FR
INDEX_PATH = _index_specs.INDEX_PATH
# The one function the indexer exports for a caller to learn whether the full
# spec graph validates (FR/TR/DEC parse errors, graph errors, cross-object
# reference errors — everything `--validate` reports), so this gate gains no
# parsing or vocabulary of its own for any object type beyond the FR. See its
# docstring in index-specs.py. @implements FR-0021:AC-2
validate_spec_graph = _index_specs.validate_spec_graph
# The one function the indexer exports for this gate to learn each FR's exempt
# ACs and the warnings for its exemption entries that are not honoured. The
# gate parses no `ac_state` and no section of its own. @implements FR-0026:AC-6
coverage_exemptions = _index_specs.coverage_exemptions

from spec_footprint import _git_ls_files  # noqa: E402

# The project's declared layout (FR-0023): footprint root, gate source and test
# directories, and the project name that qualified `# covers` annotations
# carry. Optional, like dispatch.py and metrics_log below: a copy of this file
# with no sibling project_layout.py scans src/ and tests/ exactly as before.
try:
    import project_layout as _project_layout  # noqa: E402
except ImportError:  # pragma: no cover
    _project_layout = None

# @implements FR-0008:AC-9 — `gate_status` is dispatch.py's single evidence
# reader (FR-0008:AC-2); reused here rather than re-implemented so the two
# scripts never disagree about a gate's status. Optional: a project whose
# scripts/ predates FR-0008 (or a test copy of this file alone, with no
# sibling dispatch.py) still gates — the lint below is skipped, not a hard
# failure, mirroring the metrics_log optional-import convention above.
try:
    _dispatch = _import_from("dispatch.py", "dispatch")
except Exception:  # noqa: BLE001 — never load-bearing; see comment above
    _dispatch = None

# Pipeline metrics log (FR-0002 AC-4): every run except --status-only appends
# one classified `gate.run` record. Optional import so a project whose
# scripts/ predates metrics_log.py (or a test copy of this file alone) still
# gates; emission is never load-bearing either way.
try:
    import metrics_log as _metrics  # noqa: E402
except ImportError:  # pragma: no cover
    _metrics = None


REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
TESTS_DIR = REPO_ROOT / "tests"
SRC_DIR = REPO_ROOT / "src"

# AC detection: matches **AC-1:**, AC-1:, **AC-1**:, and list-prefixed variants
AC_HEADING_PATTERN = re.compile(
    r"(?:^[\s*-]*)"           # optional leading whitespace, bullet, or bold marker
    r"(?:\*\*\s*)?"           # optional opening bold
    r"AC-(\d+)"              # the AC number (captured)
    r"(?:\s*\*\*)?"           # optional closing bold
    r"\s*:",                  # colon (possibly with space before)
    re.MULTILINE,
)
# The labelled bullet `- **AC-N (L):**`, optionally indented: a non-empty label
# `L` ending at the first `):**` on the line. @implements FR-0027:AC-3
AC_LABELLED_PATTERN = re.compile(
    r"^[ \t]*-[ \t]+\*\*AC-(\d+)[ \t]+\((?:(?!\):\*\*).)+\):\*\*",
    re.MULTILINE,
)
# Loose detector for "AC-" mentions that don't match the structured pattern
AC_LOOSE_PATTERN = re.compile(r"\bAC-\d+\b")

COVERS_PATTERN = re.compile(r"@covers\s+(FR-\d{4}):(AC-\d+)")
IMPLEMENTS_PATTERN = re.compile(r"@implements\s+(FR-\d{4})")

AC_NUM_PATTERN = re.compile(r"AC-(\d+)")

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Statuses where @implements is expected (dev-stage and beyond)
IMPLEMENTS_EXPECTED_STATUSES = {
    "in-progress", "in-review", "merged",
}

SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt"}


@dataclass
class FRSummary:
    id: str
    status: str
    acs: set[int]
    path: Path


@dataclass
class _GateReport:
    """What one gate run is about, for the `gate.run` metrics record. Filled in
    alongside the human output without changing it. @implements FR-0002:AC-4"""

    stage: str = "full"
    outcome: str = "error"
    failure_classes: list[str] = field(default_factory=list)
    warning_classes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"frs": 0, "covers": 0, "implements": 0})
    object_ids: list[str] = field(default_factory=list)

    def fail(self, cls: str, *lines: str) -> None:
        if cls not in self.failure_classes:
            self.failure_classes.append(cls)
        for line in lines:
            for fr_id in FR_IN_TEXT_PATTERN.findall(line):
                if fr_id not in self.object_ids:
                    self.object_ids.append(fr_id)

    def warn(self, cls: str) -> None:
        if cls not in self.warning_classes:
            self.warning_classes.append(cls)


FR_IN_TEXT_PATTERN = re.compile(r"\bFR-\d{4}\b")

_INVOKED_BY_ENV = "METRICS_INVOKED_BY"
_GATE_RECORD_ID_ENV = "METRICS_GATE_RECORD_ID"
_GATE_OVERRIDE_ENV = "METRICS_GATE_OVERRIDE"


def _emit_gate_record(status_only: bool, report: _GateReport) -> None:
    """Append the run's `gate.run` record — never under --status-only (a
    read-only surface must not dirty the tree), never load-bearing.
    @implements FR-0002:AC-4, FR-0002:AC-9"""
    if _metrics is None or status_only:
        return
    invoked_by = os.environ.get(_INVOKED_BY_ENV, "manual")
    if invoked_by not in _metrics.GATE_INVOKED_BY:
        invoked_by = "manual"
    extra: dict[str, bool] = {}
    override = os.environ.get(_GATE_OVERRIDE_ENV, "")
    if override == "forced":
        extra["forced"] = True
    elif override == "draft-exempt" and report.outcome != "pass":
        extra["draft_exempt"] = True
    _metrics.emit(
        "gate.run",
        source="gate",
        role=None,
        object_ids=sorted(report.object_ids),
        run_id=os.environ.get(_metrics.RUN_ID_ENV) or None,
        record_id=os.environ.get(_GATE_RECORD_ID_ENV) or None,
        stage=report.stage,
        outcome=report.outcome,
        failure_classes=list(report.failure_classes),
        warning_classes=list(report.warning_classes),
        counts=dict(report.counts),
        invoked_by=invoked_by,
        **extra,
    )


def _load_fr_summaries(
    frs: list[FR], report: _GateReport | None = None
) -> dict[str, FRSummary]:
    """Convert imported FR objects to FRSummary with AC extraction from body."""
    summaries: dict[str, FRSummary] = {}
    for fr in frs:
        text = fr.path.read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(text)
        body = text[match.end():] if match else text
        ac_nums = {int(m.group(1)) for m in AC_HEADING_PATTERN.finditer(body)}
        ac_nums |= {int(m.group(1)) for m in AC_LABELLED_PATTERN.finditer(body)}

        # Warn if body contains AC- references not matched by the structured pattern
        all_ac_mentions = {m.group(0) for m in AC_LOOSE_PATTERN.finditer(body)}
        detected_strs = {f"AC-{n}" for n in ac_nums}
        undetected = all_ac_mentions - detected_strs
        if undetected:
            print(
                f"WARN: {fr.path.name} contains AC references in unexpected format: "
                f"{', '.join(sorted(undetected))} — consider using '**AC-N:**' format",
                file=sys.stderr,
            )
            if report is not None:
                report.warn("ac-format")

        summaries[fr.id] = FRSummary(id=fr.id, status=fr.status, acs=ac_nums, path=fr.path)
    return summaries


def _qualified_covers_pattern(project_name: str) -> re.Pattern[str]:
    """`# covers <project_name> FR-NNNN:AC-N`: the ride-along annotation form,
    counted exactly like `@covers` but only for the project it names. The name
    is matched literally and bounded by whitespace. @implements FR-0023:AC-4"""
    return re.compile(
        r"#\s*covers\s+" + re.escape(project_name) + r"\s+(FR-\d{4}):(AC-\d+)"
    )


def collect_covers(
    layout: _project_layout.ProjectLayout | None = None,
) -> dict[str, set[str]]:
    """Return mapping of FR-id -> set of AC-N strings covered by tests.

    Scans each of the layout's test directories (default: `tests/`); a
    missing directory is skipped. With a `project_name`, the qualified
    `# covers <project_name>` form counts too. @implements FR-0023:AC-3"""
    covers: dict[str, set[str]] = defaultdict(set)
    test_dirs = layout.test_paths if layout is not None else (TESTS_DIR,)
    patterns = [COVERS_PATTERN]
    if layout is not None and layout.project_name:
        patterns.append(_qualified_covers_pattern(layout.project_name))
    for tests_dir in test_dirs:
        if not tests_dir.exists():
            continue
        for path in tests_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SOURCE_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in patterns:
                for m in pattern.finditer(text):
                    covers[m.group(1)].add(m.group(2))
    return covers


def collect_implements(
    layout: _project_layout.ProjectLayout | None = None,
) -> dict[str, list[str]]:
    """Return mapping of FR-id -> list of source file paths with @implements.

    Scans each of the layout's source directories (default: `src/`); a
    missing directory is skipped. Paths are reported relative to the
    footprint root, so a directory outside the project root is reportable.
    @implements FR-0023:AC-3"""
    implements: dict[str, list[str]] = defaultdict(list)
    source_dirs = layout.source_paths if layout is not None else (SRC_DIR,)
    root = layout.root if layout is not None else REPO_ROOT
    for src_dir in source_dirs:
        if not src_dir.exists():
            continue
        for path in src_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SOURCE_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in IMPLEMENTS_PATTERN.finditer(text):
                rel = str(path.relative_to(root))
                implements[m.group(1)].append(rel)
    return implements


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent deploy gate")
    parser.add_argument(
        "--stage",
        choices=["dev", "review", "full"],
        default="full",
        help="Which stage's checks to run. dev = lightest; full = all.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help=(
            "Run all checks and print the summary but write nothing. Intended for "
            "the Stop hook: a reporting surface must not dirty the working tree by "
            "rewriting the tracked specs/INDEX.md on every turn."
        ),
    )
    args = parser.parse_args()

    # The checks run unchanged; the report is filled in beside them and emitted
    # afterwards so exit code, stdout and stderr stay byte-identical. An
    # exception escaping the checks is recorded as `script-error` and then
    # re-raised untouched. @implements FR-0002:AC-4
    report = _GateReport(stage=args.stage)
    try:
        rc = _run_checks(args, report)
    except Exception:
        report.outcome = "error"
        report.fail("script-error")
        _emit_gate_record(args.status_only, report)
        raise
    _emit_gate_record(args.status_only, report)
    return rc


def _run_checks(args: argparse.Namespace, report: _GateReport) -> int:
    failures: list[str] = []
    warnings: list[str] = []

    # 1. Spec graph validates: delegate to the indexer's exported validator for
    # every error `index-specs.py --validate` would report — FR, TR and DEC
    # parse errors, graph errors, and cross-object reference errors included,
    # not just the FR-only errors `validate_graph` alone would see. Nothing is
    # written when this set is non-empty. @implements FR-0021:AC-1
    # A malformed `.agent-team/layout.yaml` fails the same way and under the
    # same class, ahead of the graph's own errors. @implements FR-0023:AC-1
    layout = None
    layout_errors: list[str] = []
    if _project_layout is not None:
        try:
            layout = _project_layout.load(REPO_ROOT)
        except _project_layout.LayoutInvalid as e:
            layout_errors.append(str(e))
    all_errors = list(dict.fromkeys([*layout_errors, *validate_spec_graph()]))
    if all_errors:
        failures.append("Spec index validation failed:")
        for err in all_errors:
            failures.append(f"  {err}")
        print("\n".join(failures), file=sys.stderr)
        report.outcome = "fail"
        report.fail("spec-validation", *all_errors)
        return 1

    parsed_frs, _ = collect_frs()
    report.counts["frs"] = len(parsed_frs)

    # Write INDEX.md as the old subprocess call did — unless --status-only, which
    # is a read-only reporting surface. The Stop hook runs this; it must not dirty
    # the working tree by rewriting a tracked file as a side effect of observing.
    if not args.status_only:
        repo_files = _git_ls_files(layout)
        # Always LF, matching index-specs.py byte-for-byte. @implements FR-0007:AC-2
        INDEX_PATH.write_text(
            render_index(parsed_frs, repo_files), encoding="utf-8", newline="\n"
        )

    frs = _load_fr_summaries(parsed_frs, report)
    covers = collect_covers(layout)

    # Exemptions come from the indexer alone (`ac_state` decides). An entry it
    # does not honour leaves its AC live and is reported at every stage.
    # @implements FR-0026:AC-6, FR-0026:AC-10
    exemptions = coverage_exemptions(parsed_frs)
    invalid_exemptions = [
        w for fr_id in sorted(exemptions) for w in exemptions[fr_id].invalid
    ]
    if invalid_exemptions:
        warnings.extend(invalid_exemptions)
        report.warn("ac-exemption-invalid")

    def exempt_acs(fr_id: str) -> frozenset[int]:
        entry = exemptions.get(fr_id)
        return entry.exempt if entry is not None else frozenset()

    # 2. @covers must reference real FRs and ACs (any stage)
    for fr_id, ac_set in covers.items():
        if fr_id not in frs:
            failures.append(
                f"@covers references unknown FR {fr_id} (FR may have been deleted)"
            )
            report.fail("covers-unknown-fr", failures[-1])
            continue
        for ac in ac_set:
            num_match = AC_NUM_PATTERN.match(ac)
            if not num_match:
                failures.append(f"@covers has malformed AC '{ac}' for {fr_id}")
                report.fail("covers-malformed-ac", failures[-1])
                continue
            ac_num = int(num_match.group(1))
            # A detected AC or a honoured exempt one is a real target.
            # @implements FR-0026:AC-7
            if ac_num not in frs[fr_id].acs and ac_num not in exempt_acs(fr_id):
                failures.append(
                    f"@covers references {fr_id}:{ac} but that AC is not in the FR"
                )
                report.fail("covers-unknown-ac", failures[-1])

    # 3. Coverage check (only for review/full stages)
    if args.stage in {"review", "full"}:
        for fr in frs.values():
            if fr.status not in {"in-review", "merged"}:
                continue
            covered = covers.get(fr.id, set())
            covered_nums = {int(AC_NUM_PATTERN.match(a).group(1)) for a in covered if AC_NUM_PATTERN.match(a)}
            # Exempt ACs never need coverage. @implements FR-0026:AC-8
            exempt = exempt_acs(fr.id)
            missing = sorted(fr.acs - covered_nums - exempt)
            if missing:
                failures.append(
                    f"{fr.id} ({fr.status}): no @covers test for AC-{', AC-'.join(str(n) for n in missing)}"
                )
                report.fail("coverage-missing", failures[-1])
            # An FR whose every detected AC is exempt delivers nothing: a
            # warning, never a failure. @implements FR-0026:AC-11
            if fr.acs and fr.acs <= exempt:
                warnings.append(
                    f"{fr.id} ({fr.status}): every AC is deferred, withdrawn or "
                    "superseded; nothing in this FR is delivered"
                )
                report.warn("ac-all-exempt")

    # 5. Declared-gate evidence lint (FR-0008:AC-9). `status: merged` requires
    # every declared gate to be `pass`; `status: in-review` requires it for
    # every `after: dev` gate. In `dev` stage the same condition is a warning
    # only. FRs with no gates add nothing. `_dispatch` is None when this copy
    # of deploy-gate.py predates FR-0008 or has no sibling dispatch.py.
    if _dispatch is not None:
        for fr in parsed_frs:
            if not fr.gates:
                continue
            if fr.status == "merged":
                required = fr.gates
            elif fr.status == "in-review":
                required = tuple(g for g in fr.gates if g["after"] == "dev")
            else:
                continue
            for g in required:
                gstatus = _dispatch.gate_status(fr.id, g["id"], ref=None)
                if gstatus == "pass":
                    continue
                cls = "gate-evidence-stale" if gstatus == "stale" else "gate-evidence-missing"
                msg = (
                    f"{fr.id} ({fr.status}): gate '{g['id']}' evidence is "
                    f"{gstatus} (expected pass)"
                )
                if args.stage in {"review", "full"}:
                    failures.append(msg)
                    report.fail(cls, msg)
                else:
                    warnings.append(msg)

    # 4. @implements cross-reference (warnings only)
    implements = collect_implements(layout)
    for fr in frs.values():
        if fr.status not in IMPLEMENTS_EXPECTED_STATUSES:
            continue
        if fr.id not in implements:
            warnings.append(
                f"{fr.id} ({fr.status}): no @implements tag found in src/"
            )
            report.warn("implements-missing")
    for fr_id in implements:
        if fr_id not in frs:
            warnings.append(
                f"@implements references unknown FR {fr_id} in: "
                + ", ".join(implements[fr_id])
            )
            report.warn("implements-unknown-fr")

    report.counts["covers"] = sum(len(v) for v in covers.values())
    report.counts["implements"] = sum(len(v) for v in implements.values())

    if warnings:
        print("Deploy gate WARNINGS:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)

    if failures:
        print("Deploy gate FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        report.outcome = "fail"
        return 1

    report.outcome = "pass"
    # The scope clause states what this run checked and that it ran no test
    # suite (Out of scope), so "gate green" is never read as "tests passed".
    # ASCII-only and a deterministic function of `--stage` alone, so two runs
    # over the same tree still print identical stdout. @implements FR-0021:AC-4
    if args.stage == "dev":
        scope_clause = "; scope: spec graph, annotations; tests not run"
    else:
        scope_clause = (
            "; scope: spec graph, annotations, AC coverage, gate evidence; "
            "tests not run"
        )
    print(
        f"Deploy gate PASSED (stage={args.stage}): {len(frs)} FRs, "
        f"{sum(len(v) for v in covers.values())} @covers annotations, "
        f"{sum(len(v) for v in implements.values())} @implements annotations"
        f"{scope_clause}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
