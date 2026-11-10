"""Hub-level tests for `scripts/bootstrap.py` -- FR-0001, profile-aware
`--upgrade` and append-only project registration.

Everything runs against a *fake hub* built in `tmp_path`: a minimal `template/`,
a copy of the real `profiles/phipa/` (copied in, so the tests do not depend on
the live tree beyond "the profile exists"), a hand-written `hub/projects.yaml`
with comments, and stub `scripts/index-specs.py` / `scripts/hub-index.py` for
the subprocess calls create mode makes. `bootstrap.py`'s `HUB_ROOT`,
`TEMPLATE_ROOT` and `PROFILES_ROOT` globals are monkeypatched at the fake hub.

Two synthetic fixture projects (FR-0001:AC-12): one profiled (`phipa` record +
profile-sourced hook + AGENTS.md block) and one unprofiled (empty record,
template hook). Nothing here touches `projects/`, `hub/projects.yaml`, or any
real project. File comparisons are on bytes so line endings are asserted, not
assumed (no reliance on core.autocrlf).

The module under test is loaded via importlib with `<hub>/scripts/` on
`sys.path` because it imports its sibling `_console`.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

# tests/unit/scripts/ -> parents[3] == hub root
HUB_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = HUB_ROOT / "scripts"
REAL_PROFILE_DIR = HUB_ROOT / "profiles" / "phipa"
REAL_TEMPLATE_DIR = HUB_ROOT / "template"

HOOK_REL = ".agent-team/hooks/phi_regex_check.py"
RECORD_REL = ".agent-team/profiles.yaml"
SETTINGS_REL = ".claude/settings.json"


def _load_module(name: str, path: Path):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bs = _load_module("bootstrap_under_test", SCRIPTS_DIR / "bootstrap.py")


# ---------------------------------------------------------------------------
# Fake hub + fixture projects
# ---------------------------------------------------------------------------

TEMPLATE_AGENTS_MD = """# AGENTS.md -- Project Working Agreement

## What you are working on

<<REPLACE: ONE_PARAGRAPH_PROJECT_DESCRIPTION>>

## Data hygiene

Baseline rules apply to every role.

## Universal rules (all roles)

1. Spec graph is the source of truth.

## Project conventions

<<REPLACE: PROJECT_CONVENTIONS>>
"""

# Registry with a header comment, a comment nested inside an entry, and one
# entry whose last key is followed by a comment line. LF only.
REGISTRY_TEXT = (
    "# Project registry -- maintained by scripts/bootstrap.py\n"
    "#\n"
    "# Schema:\n"
    "#   - name: <slug>\n"
    "#     private: false  # if true, excluded from pattern detection\n"
    "\n"
    "projects:\n"
    "- name: alpha\n"
    "  path: projects/alpha\n"
    "  # Git submodule -> own history (comment nested inside the entry).\n"
    "  created: '2026-05-29'\n"
    "  stack: none\n"
    "  private: false\n"
    "- name: beta\n"
    "  path: projects/beta\n"
    "  created: '2026-06-04'\n"
    "  stack: node\n"
    "  # Gitignored, out-of-tree: excluded from the shared index.\n"
    "  private: true\n"
)

STUB_EXIT_0 = "import sys\nsys.exit(0)\n"


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Build a fake hub and point bootstrap.py's roots at it."""
    root = tmp_path / "hub"
    template = root / "template"
    profiles = root / "profiles"

    # --- template/ (minimal but shaped like the real one) ---
    _write(template / "AGENTS.md", TEMPLATE_AGENTS_MD)
    _write(template / "README.md", "# template\n")
    _write(template / ".gitignore", "__pycache__/\n")
    _write(template / "pytest.ini", "[pytest]\npythonpath = scripts\n")
    _write(template / HOOK_REL, (REAL_TEMPLATE_DIR / HOOK_REL).read_bytes())
    _write(template / ".agent-team/hooks/spec_validate_if_changed.py", "# template hook v1\n")
    _write(template / ".agent-team/roles/reviewer.md", "# Role: Reviewer\n")
    _write(template / ".agent-team/commands/gate.md", "Run the gate for $ARGUMENTS.\n")
    _write(template / SETTINGS_REL, (REAL_TEMPLATE_DIR / SETTINGS_REL).read_bytes())
    _write(template / "scripts/index-specs.py", STUB_EXIT_0)
    _write(template / "scripts/deploy-gate.py", STUB_EXIT_0)
    _write(template / "specs/_template/FR-template.md", "# FR template\n")
    _write(template / "specs/FR-0001-example.md", "# example\n")
    (template / "src").mkdir()
    (template / "tests").mkdir()

    # --- profiles/ : real phipa copied in, plus a second, apply-less profile ---
    shutil.copytree(REAL_PROFILE_DIR, profiles / "phipa")
    _write(profiles / "zeta" / "README.md", "# zeta profile (no install steps)\n")

    # --- hub/ registry and stub hub scripts used by create mode ---
    _write(root / "hub/projects.yaml", REGISTRY_TEXT)
    _write(root / "scripts/hub-index.py", STUB_EXIT_0)
    (root / "projects").mkdir()

    monkeypatch.setattr(bs, "HUB_ROOT", root)
    monkeypatch.setattr(bs, "TEMPLATE_ROOT", template)
    monkeypatch.setattr(bs, "PROFILES_ROOT", profiles)

    return SimpleNamespace(
        root=root,
        template=template,
        profiles=profiles,
        registry=root / "hub/projects.yaml",
        template_hook=(template / HOOK_REL).read_bytes(),
        profile_hook=(profiles / "phipa/phi_regex_check.py").read_bytes(),
        template_settings=(template / SETTINGS_REL).read_bytes(),
        block=(profiles / "phipa/phi_hygiene_block.md").read_text(encoding="utf-8"),
    )


def _write_record(project: Path, profiles: list[str]) -> None:
    body = "profiles: [" + ", ".join(profiles) + "]\n"
    _write(project / RECORD_REL, "# hand-written fixture record\n" + body)


def _make_project(hub: SimpleNamespace, name: str, *, profiled: bool, record: bool = True) -> Path:
    """A bootstrapped-looking project under the fake hub's projects/.

    Built by hand (not via run_create) so the fixture shape does not depend on
    the code under test. Profiled: profile-sourced hook, AGENTS.md hygiene
    block, `profiles: [phipa]` record. Unprofiled: template hook, `profiles: []`.
    """
    project = hub.root / "projects" / name
    shutil.copytree(
        hub.template, project, ignore=shutil.ignore_patterns("FR-0001-example.md"),
    )
    agents = project / "AGENTS.md"
    text = agents.read_text(encoding="utf-8").replace(
        "<<REPLACE: ONE_PARAGRAPH_PROJECT_DESCRIPTION>>", f"Synthetic fixture {name}.",
    )
    if profiled:
        _write(project / HOOK_REL, hub.profile_hook)
        text = text.replace(
            "## Universal rules", hub.block.strip() + "\n\n## Universal rules",
        )
    _write(agents, text)
    if record:
        _write_record(project, ["phipa"] if profiled else [])
    return project


@pytest.fixture
def profiled(hub: SimpleNamespace) -> Path:
    return _make_project(hub, "prof-fixture", profiled=True)


@pytest.fixture
def unprofiled(hub: SimpleNamespace) -> Path:
    return _make_project(hub, "plain-fixture", profiled=False)


def _append_registry(hub: SimpleNamespace, name: str, path: str, profiles: list[str] | None) -> None:
    """Hand-append a registry entry (bypassing the code under test)."""
    entry = (
        f"- name: {name}\n  path: {path}\n  created: '2026-09-01'\n"
        f"  stack: none\n  private: false\n"
    )
    if profiles is not None:
        entry += "  profiles: [" + ", ".join(profiles) + "]\n"
    _write(hub.registry, hub.registry.read_bytes() + entry.encode("utf-8"))


def _run_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    project: Path,
    *,
    yes: bool = True,
    answers: list[str] | None = None,
    backfill: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Run bootstrap.run_upgrade; return (stdout+stderr, prompts issued).

    With `answers=None` any prompt is a test failure (unattended runs must
    never call input()).
    """
    prompts: list[str] = []
    queue = list(answers or [])

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        if answers is None:
            raise AssertionError(f"unexpected prompt: {prompt!r}")
        return queue.pop(0) if queue else "n"

    monkeypatch.setattr("builtins.input", fake_input)
    bs.run_upgrade(project, auto_yes=yes, backfill_profiles=backfill)
    captured = capsys.readouterr()
    return captured.out + captured.err, prompts


def _read_record(project: Path) -> list[str]:
    raw = (project / RECORD_REL).read_bytes()
    assert b"\r\n" not in raw, "profile record must be LF"
    data = yaml.safe_load(raw.decode("utf-8"))
    return list(data["profiles"])


def _phi_hook_count(settings_bytes: bytes) -> int:
    settings = json.loads(settings_bytes.decode("utf-8"))
    return sum(
        1
        for entry in settings["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
        if "phi_regex_check.py" in h.get("command", "")
    )


def _create_args(name: str, **overrides) -> SimpleNamespace:
    base = dict(
        name=name,
        description=f"Synthetic project {name} for FR-0001 tests.",
        stack="none",
        profile=[],
        keep_example=False,
        no_git=True,
        private=False,
        no_register=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _registry_entry(hub: SimpleNamespace, name: str) -> dict:
    data = yaml.safe_load(hub.registry.read_bytes().decode("utf-8"))
    matches = [e for e in data["projects"] if e.get("name") == name]
    assert len(matches) == 1, matches
    return matches[0]


# ---------------------------------------------------------------------------
# AC-1: profile set is recorded at creation
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-1
# @covers FR-0001:AC-11
def test_create_with_profile_records_phipa_locally_and_in_registry(hub, capsys):
    bs.run_create(_create_args("newprof", profile=["phipa"]))
    project = hub.root / "projects" / "newprof"

    assert _read_record(project) == ["phipa"]
    entry = _registry_entry(hub, "newprof")
    assert entry["profiles"] == ["phipa"]
    assert b"  profiles: [phipa]\n" in hub.registry.read_bytes()
    # The profiled project carries the profile-sourced hook, not the template's.
    assert (project / HOOK_REL).read_bytes() == hub.profile_hook
    # AC-11: overlay applied on top of a template that already wires the hook
    # yields exactly one PHI hook entry.
    assert _phi_hook_count((project / SETTINGS_REL).read_bytes()) == 1


# @covers FR-0001:AC-1
def test_create_without_profile_records_empty_set(hub, capsys):
    bs.run_create(_create_args("newplain"))
    project = hub.root / "projects" / "newplain"

    assert (project / RECORD_REL).is_file()
    assert _read_record(project) == []
    assert _registry_entry(hub, "newplain")["profiles"] == []
    assert b"  profiles: []\n" in hub.registry.read_bytes()
    assert (project / HOOK_REL).read_bytes() == hub.template_hook


# @covers FR-0001:AC-1
def test_create_multiple_profiles_ordered_and_deduplicated(hub, capsys):
    bs.run_create(_create_args("multi", profile=["zeta", "phipa", "zeta", "phipa"]))
    project = hub.root / "projects" / "multi"

    assert _read_record(project) == ["zeta", "phipa"]
    assert _registry_entry(hub, "multi")["profiles"] == ["zeta", "phipa"]


# @covers FR-0001:AC-1
def test_create_rejects_unknown_profile_before_writing_anything(hub, capsys):
    with pytest.raises(SystemExit) as exc:
        bs.run_create(_create_args("bad", profile=["phipa", "nope"]))
    assert exc.value.code == 1
    assert "Unknown profile: 'nope'" in capsys.readouterr().err
    assert not (hub.root / "projects" / "bad").exists()
    assert hub.registry.read_bytes() == REGISTRY_TEXT.encode("utf-8")


# ---------------------------------------------------------------------------
# AC-2: profile set resolution on upgrade
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-2
def test_local_record_is_canonical_when_present(hub, profiled):
    resolved, notices = bs.resolve_profiles(profiled, hub.root)
    assert resolved == ["phipa"]
    assert notices == []


# @covers FR-0001:AC-2
def test_missing_record_falls_back_to_registry_entry(hub, profiled, monkeypatch, capsys):
    (profiled / RECORD_REL).unlink()
    _append_registry(hub, "prof-fixture", "projects/prof-fixture", ["phipa"])

    resolved, notices = bs.resolve_profiles(profiled, hub.root)
    assert resolved == ["phipa"]
    assert len(notices) == 1 and "registry" in notices[0]

    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "Profiles: phipa" in out
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook


# @covers FR-0001:AC-2
def test_registry_fallback_honours_local_overlay(hub, profiled):
    (profiled / RECORD_REL).unlink()
    # Shared registry knows the name but has no profiles; the per-machine
    # overlay re-points it and carries the profile set. Overlay wins by name.
    _append_registry(hub, "prof-fixture", "projects/elsewhere", None)
    _write(
        hub.root / "hub/projects.local.yaml",
        "projects:\n- name: prof-fixture\n  path: projects/prof-fixture\n"
        "  created: '2026-09-01'\n  stack: none\n  private: true\n  profiles: [phipa]\n",
    )
    resolved, _ = bs.resolve_profiles(profiled, hub.root)
    assert resolved == ["phipa"]


# @covers FR-0001:AC-2
# @covers FR-0001:AC-9
def test_unrecorded_project_is_unprofiled_with_exactly_one_notice(hub, unprofiled, monkeypatch, capsys):
    (unprofiled / RECORD_REL).unlink()

    resolved, notices = bs.resolve_profiles(unprofiled, hub.root)
    assert resolved == []
    assert len(notices) == 1 and "unrecorded" in notices[0] and "--profile" in notices[0]

    out, _ = _run_upgrade(monkeypatch, capsys, unprofiled)
    # (count the notice text, not the bare word: tmp_path echoes the test name)
    assert out.count("Profile state is unrecorded") == 1
    assert "Profiles: (none)" in out
    assert "Profile overlay" not in out and "Profile block" not in out
    assert "(from profile" not in out


# @covers FR-0001:AC-2
def test_disagreement_uses_local_record_and_reports_it(hub, profiled, monkeypatch, capsys):
    # Registry says unprofiled; the project-local record says phipa.
    _append_registry(hub, "prof-fixture", "projects/prof-fixture", [])

    resolved, notices = bs.resolve_profiles(profiled, hub.root)
    assert resolved == ["phipa"]
    assert len(notices) == 1
    assert "[phipa]" in notices[0] and "[]" in notices[0]

    (profiled / HOOK_REL).write_bytes(hub.profile_hook + b"# drift\n")
    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "using the project-local record" in out
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook


# @covers FR-0001:AC-2
def test_disagreement_reverse_direction_still_prefers_local(hub, unprofiled):
    # Adversarial: registry claims phipa, local record is explicitly empty.
    # Local wins (per spec) and the conflict is surfaced, not silently picked.
    _append_registry(hub, "plain-fixture", "projects/plain-fixture", ["phipa"])
    resolved, notices = bs.resolve_profiles(unprofiled, hub.root)
    assert resolved == []
    assert len(notices) == 1 and "[phipa]" in notices[0]


# @covers FR-0001:AC-2
def test_unknown_profile_in_record_is_rejected_like_create(hub, profiled, monkeypatch, capsys):
    _write_record(profiled, ["nope"])
    before = (profiled / HOOK_REL).read_bytes()
    with pytest.raises(SystemExit) as exc:
        _run_upgrade(monkeypatch, capsys, profiled)
    assert exc.value.code == 1
    assert "Unknown profile: 'nope'" in capsys.readouterr().err
    assert (profiled / HOOK_REL).read_bytes() == before


# @covers FR-0001:AC-2
def test_malformed_record_is_fatal_not_silently_unprofiled(hub, profiled, monkeypatch, capsys):
    _write(profiled / RECORD_REL, "profiles: [unterminated\n")
    with pytest.raises(SystemExit):
        _run_upgrade(monkeypatch, capsys, profiled)
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook


# ---------------------------------------------------------------------------
# AC-3: profile-owned files are never overwritten with the template base copy
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-3
def test_sync_plan_maps_owned_file_to_profile_source_and_never_offers_record(hub):
    # Adversarial: even if a future template shipped a profiles.yaml, it must
    # never enter the plan.
    _write(hub.template / RECORD_REL, "profiles: [phipa]\n")

    plan = bs.build_sync_plan(["phipa"])
    src, owner = plan[HOOK_REL]
    assert src == hub.profiles / "phipa" / "phi_regex_check.py"
    assert owner == "phipa"
    assert RECORD_REL not in plan

    plan_plain = bs.build_sync_plan([])
    src, owner = plan_plain[HOOK_REL]
    assert src == hub.template / HOOK_REL
    assert owner is None
    assert RECORD_REL not in plan_plain


# @covers FR-0001:AC-3
def test_profile_owned_set_for_phipa_is_exactly_the_hook(hub):
    owned = bs.profile_owned_files(["phipa"], hub.profiles)
    assert list(owned) == [HOOK_REL]
    assert owned[HOOK_REL][0] == "phipa"


# @covers FR-0001:AC-3
def test_up_to_date_profiled_hook_is_not_offered_even_interactively(hub, profiled, monkeypatch, capsys):
    # The fixture hook equals the profile source and differs from the template.
    assert hub.profile_hook != hub.template_hook
    # answers=None -> any prompt fails the test: the hook must not be offered.
    out, prompts = _run_upgrade(monkeypatch, capsys, profiled, yes=False)
    assert prompts == []
    assert "CHANGED: " + HOOK_REL not in out
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook


# @covers FR-0001:AC-3
# @covers FR-0001:AC-4
def test_differing_profiled_hook_diff_is_against_profile_source(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).write_bytes(hub.profile_hook + b"# local tweak\n")

    out, prompts = _run_upgrade(monkeypatch, capsys, profiled, yes=False, answers=["n"])
    assert len(prompts) == 1 and "Apply this change?" in prompts[0]
    assert f"CHANGED: {HOOK_REL} (from profile: phipa)" in out
    assert f"+++ profile:phipa/{HOOK_REL}" in out
    assert f"--- project/{HOOK_REL}" in out
    # Project == profile + one line, so a diff against the *profile* is a single
    # removal and no additions. A diff against the template would add lines.
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if f"CHANGED: {HOOK_REL}" in ln)
    seps = [i for i, ln in enumerate(lines[start:], start) if ln.strip() == "-" * 60]
    body = [ln.strip() for ln in lines[seps[0] + 1 : seps[1]]]
    removals = [ln for ln in body if ln.startswith("-") and not ln.startswith("---")]
    additions = [ln for ln in body if ln.startswith("+") and not ln.startswith("+++")]
    assert removals == ["-# local tweak"]
    assert additions == []
    # Declined -> untouched, listed under Skipped with the profile annotation.
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook + b"# local tweak\n"
    assert "Skipped:" in out and f"- {HOOK_REL} (from profile: phipa)" in out


# @covers FR-0001:AC-3
def test_missing_profile_source_never_falls_back_to_template_copy(hub, profiled, monkeypatch, capsys):
    # Adversarial: profile dir exists (name validates) but its hook file is
    # gone. The only safe outcome is to leave the project's hook alone -- the
    # template base copy must not be written into a profiled project.
    (hub.profiles / "phipa" / "phi_regex_check.py").unlink()
    _run_upgrade(monkeypatch, capsys, profiled)
    after = (profiled / HOOK_REL).read_bytes()
    assert after == hub.profile_hook
    assert after != hub.template_hook


# ---------------------------------------------------------------------------
# AC-4: profile-owned files sync from the profile source, standard semantics
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-4
# @covers FR-0001:AC-8
def test_yes_applies_profile_source_and_lists_under_updated(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).write_bytes(b"# stale local hook\n")

    out, prompts = _run_upgrade(monkeypatch, capsys, profiled)
    assert prompts == []
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook
    assert "Updated:" in out
    assert f"~ {HOOK_REL} (from profile: phipa)" in out


# @covers FR-0001:AC-4
def test_interactive_applies_profile_source_only_on_y(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).write_bytes(b"# stale local hook\n")

    out, prompts = _run_upgrade(monkeypatch, capsys, profiled, yes=False, answers=["y"])
    assert len(prompts) == 1
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook
    assert f"~ {HOOK_REL} (from profile: phipa)" in out


# @covers FR-0001:AC-4
def test_interactive_default_answer_does_not_apply(hub, profiled, monkeypatch, capsys):
    # Adversarial: empty / non-"y" answers must not apply (default is N).
    (profiled / HOOK_REL).write_bytes(b"# stale local hook\n")
    _run_upgrade(monkeypatch, capsys, profiled, yes=False, answers=[""])
    assert (profiled / HOOK_REL).read_bytes() == b"# stale local hook\n"


# @covers FR-0001:AC-4
def test_missing_owned_file_is_added_from_profile_source(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).unlink()

    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook
    assert "Added:" in out and f"+ {HOOK_REL} (from profile: phipa)" in out


# @covers FR-0001:AC-4
def test_missing_owned_file_interactive_offer_names_profile(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).unlink()
    out, prompts = _run_upgrade(monkeypatch, capsys, profiled, yes=False, answers=["y"])
    assert len(prompts) == 1 and "Add it?" in prompts[0]
    assert f"NEW: {HOOK_REL} (from profile: phipa)" in out
    assert "exists in the profile:phipa but not in your project" in out
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook


# @covers FR-0001:AC-4
def test_summary_distinguishes_profile_from_template_sources(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).write_bytes(b"# stale\n")
    (profiled / ".agent-team/hooks/spec_validate_if_changed.py").write_bytes(b"# stale\n")

    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert f"~ {HOOK_REL} (from profile: phipa)" in out
    assert "~ .agent-team/hooks/spec_validate_if_changed.py\n" in out
    assert "spec_validate_if_changed.py (from profile" not in out


# ---------------------------------------------------------------------------
# AC-5: settings overlay verified, never edited
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-5
def test_overlay_present_reports_nothing(hub, profiled, monkeypatch, capsys):
    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "Profile overlay missing" not in out


# @covers FR-0001:AC-5
def test_overlay_missing_is_reported_and_settings_never_written(hub, profiled, monkeypatch, capsys):
    stripped = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    stripped_bytes = (json.dumps(stripped, indent=2) + "\n").encode("utf-8")
    _write(profiled / SETTINGS_REL, stripped_bytes)

    for yes in (True, False):
        out, _ = _run_upgrade(monkeypatch, capsys, profiled, yes=yes, answers=[])
        assert "Profile overlay missing" in out
        assert "phipa" in out and "phi_regex_check.py" in out
        assert "Drift:" in out  # existing drift-warn path still fires
        assert (profiled / SETTINGS_REL).read_bytes() == stripped_bytes


# @covers FR-0001:AC-5
def test_overlay_check_is_structural_containment_not_byte_equality(hub, profiled, monkeypatch, capsys):
    settings = json.loads(hub.template_settings)
    for entry in settings["hooks"]["PreToolUse"]:
        for h in entry["hooks"]:
            h["timeout"] = 30  # project-local addition
    settings["permissions"] = {"allow": ["Bash(python *)"]}
    _write(profiled / SETTINGS_REL, json.dumps(settings, indent=2) + "\n")

    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "Profile overlay missing" not in out
    assert "Drift:" in out


# ---------------------------------------------------------------------------
# AC-6: AGENTS.md profile block verified, never edited
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-6
def test_agents_block_present_is_silent(hub, profiled, monkeypatch, capsys):
    before = (profiled / "AGENTS.md").read_bytes()
    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "Profile block" not in out
    assert (profiled / "AGENTS.md").read_bytes() == before


# @covers FR-0001:AC-6
def test_agents_block_missing_is_reported_and_file_untouched(hub, profiled, monkeypatch, capsys):
    text = (profiled / "AGENTS.md").read_text(encoding="utf-8")
    text = text.replace(hub.block.strip() + "\n\n", "")
    assert "PHI hygiene" not in text
    _write(profiled / "AGENTS.md", text)
    before = (profiled / "AGENTS.md").read_bytes()

    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "Profile block missing" in out and "phipa" in out
    assert (profiled / "AGENTS.md").read_bytes() == before


# @covers FR-0001:AC-6
def test_agents_block_differs_is_reported_with_diff_and_file_untouched(hub, profiled, monkeypatch, capsys):
    text = (profiled / "AGENTS.md").read_text(encoding="utf-8")
    text = text.replace("Test fixtures use synthetic data only.", "Test fixtures use whatever.")
    _write(profiled / "AGENTS.md", text)
    before = (profiled / "AGENTS.md").read_bytes()

    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert "Profile block differs" in out
    assert (profiled / "AGENTS.md").read_bytes() == before

    out, _ = _run_upgrade(monkeypatch, capsys, profiled, yes=False, answers=[])
    assert "PROFILE BLOCK DIFFERS" in out and "+++ profile:phipa/AGENTS.md" in out
    assert (profiled / "AGENTS.md").read_bytes() == before


# @covers FR-0001:AC-6
def test_agents_block_state_classifier():
    block = "## PHI hygiene\n\n- rule one\n- rule two\n"
    assert bs.agents_block_state("# X\n\n## PHI hygiene\n\n- rule one\n- rule two\n\n## Next\n", block)[0] == "present"
    # CRLF project text still counts as present (normalised, not byte-compared).
    assert bs.agents_block_state("## PHI hygiene\r\n\r\n- rule one\r\n- rule two\r\n", block)[0] == "present"
    state, section = bs.agents_block_state("## PHI hygiene\n\n- rule one\n\n## Next\n", block)
    assert state == "differs" and section.startswith("## PHI hygiene")
    assert bs.agents_block_state("# nothing here\n", block)[0] == "missing"


# ---------------------------------------------------------------------------
# AC-7: backfill for pre-existing profiled projects
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-7
def test_backfill_writes_record_and_inserts_single_registry_line(hub, monkeypatch, capsys):
    # Pre-FR shape: profile-sourced hook + block, no record, registry entry
    # with a comment nested inside it and no profiles key (Project A's shape).
    project = _make_project(hub, "legacy", profiled=True, record=False)
    _append_registry(hub, "legacy", "projects/legacy", None)
    hub.registry.write_bytes(
        hub.registry.read_bytes().replace(
            b"  path: projects/legacy\n",
            b"  path: projects/legacy\n  # Submodule -> own history.\n",
        )
    )
    before = hub.registry.read_bytes()

    out, prompts = _run_upgrade(monkeypatch, capsys, project, backfill=["phipa"])
    assert prompts == []
    assert _read_record(project) == ["phipa"]

    after = hub.registry.read_bytes()
    assert b"\r\n" not in after
    old_lines = before.split(b"\n")
    new_lines = after.split(b"\n")
    assert len(new_lines) == len(old_lines) + 1
    inserted = [ln for ln in new_lines if ln not in old_lines]
    assert inserted == [b"  profiles: [phipa]"]
    idx = new_lines.index(b"  profiles: [phipa]")
    assert new_lines[idx - 1] == b"  private: false"
    assert [ln for ln in new_lines if ln != b"  profiles: [phipa]"] == old_lines
    assert _registry_entry(hub, "legacy")["profiles"] == ["phipa"]
    assert "profiles" not in _registry_entry(hub, "alpha")  # neighbours untouched

    # The Project A scenario: nothing to change on the hook, nothing missing.
    assert (project / HOOK_REL).read_bytes() == hub.profile_hook
    assert "Profiles: phipa" in out
    assert "Profile overlay missing" not in out and "Profile block missing" not in out
    assert "unrecorded" not in out
    assert HOOK_REL not in out.split("Upgrade summary:")[1]


# @covers FR-0001:AC-7
def test_backfill_replaces_prior_record_and_existing_profiles_line(hub, profiled, monkeypatch, capsys):
    _write_record(profiled, [])
    _append_registry(hub, "prof-fixture", "projects/prof-fixture", [])
    before = hub.registry.read_bytes()

    _run_upgrade(monkeypatch, capsys, profiled, backfill=["phipa"])
    assert _read_record(profiled) == ["phipa"]
    after = hub.registry.read_bytes()
    assert after.count(b"\n") == before.count(b"\n")
    assert after == before.replace(b"  profiles: []\n", b"  profiles: [phipa]\n")

    # Running it again is a no-op on the registry.
    _run_upgrade(monkeypatch, capsys, profiled, backfill=["phipa"])
    assert hub.registry.read_bytes() == after


# @covers FR-0001:AC-7
def test_backfill_unregistered_project_prints_line_and_continues(hub, monkeypatch, capsys):
    project = _make_project(hub, "orphan", profiled=True, record=False)
    before = hub.registry.read_bytes()

    out, _ = _run_upgrade(monkeypatch, capsys, project, backfill=["phipa"])
    assert _read_record(project) == ["phipa"]
    assert hub.registry.read_bytes() == before
    assert "No hub registry entry" in out and "profiles: [phipa]" in out
    assert "Profiles: phipa" in out  # upgrade still ran with the set


# @covers FR-0001:AC-7
def test_backfill_ambiguous_registry_entry_is_left_alone(hub, monkeypatch, capsys):
    project = _make_project(hub, "dup", profiled=True, record=False)
    _append_registry(hub, "dup", "projects/dup", None)
    _append_registry(hub, "dup", "projects/dup", None)
    before = hub.registry.read_bytes()

    out, _ = _run_upgrade(monkeypatch, capsys, project, backfill=["phipa"])
    assert hub.registry.read_bytes() == before
    assert "Could not locate a unique" in out and "profiles: [phipa]" in out
    assert _read_record(project) == ["phipa"]


# @covers FR-0001:AC-7
def test_backfill_rejects_unknown_profile_and_writes_nothing(hub, monkeypatch, capsys):
    project = _make_project(hub, "legacy2", profiled=True, record=False)
    before = hub.registry.read_bytes()
    with pytest.raises(SystemExit):
        _run_upgrade(monkeypatch, capsys, project, backfill=["nope"])
    assert not (project / RECORD_REL).exists()
    assert hub.registry.read_bytes() == before


# @covers FR-0001:AC-7
def test_set_registry_profiles_preserves_other_bytes_incl_crlf_file(hub):
    crlf = REGISTRY_TEXT.replace("\n", "\r\n").encode("utf-8")
    path = hub.root / "hub" / "crlf.yaml"
    path.write_bytes(crlf)
    assert bs.set_registry_profiles(path, "beta", ["phipa"]) is True
    after = path.read_bytes()
    # Only one line was added; every pre-existing line (with its CR) survives.
    assert [ln for ln in after.split(b"\n") if ln != b"  profiles: [phipa]"] == crlf.split(b"\n")
    assert bs.set_registry_profiles(path, "nobody", ["phipa"]) is False


# ---------------------------------------------------------------------------
# AC-8: --yes is unattended and safe
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-8
def test_yes_on_profiled_fixture_is_unattended_and_leaves_profile_sources(hub, profiled, monkeypatch, capsys):
    (profiled / HOOK_REL).write_bytes(hub.template_hook)  # worst case: template copy crept in

    out, prompts = _run_upgrade(monkeypatch, capsys, profiled)  # any prompt -> AssertionError
    assert prompts == []
    assert "Profiles: phipa" in out
    hook = (profiled / HOOK_REL).read_bytes()
    assert hook == hub.profile_hook
    assert hook != hub.template_hook
    for rel, (src, owner) in bs.build_sync_plan(["phipa"]).items():
        if owner is not None:
            assert (profiled / rel).read_bytes() == src.read_bytes()
            assert (profiled / rel).read_bytes() != (hub.template / rel).read_bytes()


# @covers FR-0001:AC-8
def test_yes_output_names_empty_profile_set(hub, unprofiled, monkeypatch, capsys):
    out, prompts = _run_upgrade(monkeypatch, capsys, unprofiled)
    assert prompts == []
    assert "Profiles: (none)" in out


# @covers FR-0001:AC-8
def test_yes_run_via_cli_exits_zero(hub, profiled, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--upgrade", str(profiled), "--yes"])
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("prompted")))
    bs.main()  # no SystemExit -> exit 0
    assert "Profiles: phipa" in capsys.readouterr().out
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook


# ---------------------------------------------------------------------------
# AC-9: unprofiled projects are unchanged
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-9
def test_unprofiled_hook_syncs_from_template_settings_drift_agents_untouched(hub, unprofiled, monkeypatch, capsys):
    (unprofiled / HOOK_REL).write_bytes(hub.profile_hook)  # adversarial: looks profiled, isn't
    settings = json.loads(hub.template_settings)
    settings["permissions"] = {"allow": ["Bash(python *)"]}
    settings_bytes = (json.dumps(settings, indent=2) + "\n").encode("utf-8")
    _write(unprofiled / SETTINGS_REL, settings_bytes)
    agents_before = (unprofiled / "AGENTS.md").read_bytes()

    out, prompts = _run_upgrade(monkeypatch, capsys, unprofiled)
    assert prompts == []
    assert (unprofiled / HOOK_REL).read_bytes() == hub.template_hook
    assert f"~ {HOOK_REL}\n" in out and "(from profile" not in out
    assert (unprofiled / SETTINGS_REL).read_bytes() == settings_bytes
    assert "Drift:" in out and f"! {SETTINGS_REL}" in out
    assert (unprofiled / "AGENTS.md").read_bytes() == agents_before
    assert "Profile overlay" not in out and "Profile block" not in out
    assert "unrecorded" not in out  # record exists (empty) -> no notice
    assert _read_record(unprofiled) == []


# @covers FR-0001:AC-9
def test_unprofiled_interactive_diff_is_against_template(hub, unprofiled, monkeypatch, capsys):
    (unprofiled / HOOK_REL).write_bytes(hub.template_hook + b"# local tweak\n")
    out, prompts = _run_upgrade(monkeypatch, capsys, unprofiled, yes=False, answers=["n"])
    assert len(prompts) == 1
    assert f"+++ template/{HOOK_REL}" in out
    assert f"CHANGED: {HOOK_REL}\n" in out
    assert (unprofiled / HOOK_REL).read_bytes() == hub.template_hook + b"# local tweak\n"


# ---------------------------------------------------------------------------
# AC-10: registration is append-only and preserves the file
# ---------------------------------------------------------------------------

hub_index = _load_module("hub_index_under_test", SCRIPTS_DIR / "hub-index.py")


# @covers FR-0001:AC-10
def test_register_appends_entry_preserving_every_existing_byte(hub):
    original = hub.registry.read_bytes()
    target = hub.root / "projects" / "gamma"
    target.mkdir()

    bs.register_project(hub.root, "gamma", target, "python", False, sys.executable, profiles=["phipa"])

    after = hub.registry.read_bytes()
    assert after.startswith(original)
    assert b"\r\n" not in after
    appended = after[len(original):].decode("utf-8")
    assert appended.splitlines() == [
        "- name: gamma",
        "  path: projects/gamma",
        f"  created: '{bs.datetime.date.today().isoformat()}'",
        "  stack: python",
        "  private: false",
        "  profiles: [phipa]",
    ]
    data = yaml.safe_load(after.decode("utf-8"))
    original_entries = yaml.safe_load(original.decode("utf-8"))["projects"]
    assert data["projects"][: len(original_entries)] == original_entries
    assert data["projects"][-1]["name"] == "gamma"
    assert data["projects"][-1]["profiles"] == ["phipa"]
    # scripts/hub-index.py's registry loader still accepts the result.
    entries, errors = hub_index._load_registry(hub.registry, "hub/projects.yaml")
    assert errors == []
    assert [e["name"] for e in entries] == ["alpha", "beta", "gamma"]


# @covers FR-0001:AC-10
def test_register_duplicate_name_is_byte_identical_and_warns(hub, capsys):
    original = hub.registry.read_bytes()
    target = hub.root / "projects" / "alpha"
    target.mkdir()

    bs.register_project(hub.root, "alpha", target, "none", False, sys.executable, profiles=[])

    assert hub.registry.read_bytes() == original
    assert "already registered" in capsys.readouterr().err


# @covers FR-0001:AC-10
def test_register_handles_no_trailing_newline_and_empty_flow_list(hub):
    hub.registry.write_bytes(b"# header\nprojects: []  # none yet")
    target = hub.root / "projects" / "delta"
    target.mkdir()

    bs.register_project(hub.root, "delta", target, "none", True, sys.executable, profiles=[])

    after = hub.registry.read_bytes()
    assert after.startswith(b"# header\nprojects:  # none yet\n- name: delta\n")
    assert b"\r\n" not in after
    data = yaml.safe_load(after.decode("utf-8"))
    assert data["projects"] == [
        {
            "name": "delta", "path": "projects/delta",
            "created": bs.datetime.date.today().isoformat(),
            "stack": "none", "private": True, "profiles": [],
        }
    ]


# @covers FR-0001:AC-10
def test_register_leaves_existing_crlf_bytes_alone_and_appends_lf(hub):
    crlf = REGISTRY_TEXT.replace("\n", "\r\n").encode("utf-8")
    hub.registry.write_bytes(crlf)
    target = hub.root / "projects" / "epsilon"
    target.mkdir()

    bs.register_project(hub.root, "epsilon", target, "node", False, sys.executable, profiles=["zeta", "zeta"])

    after = hub.registry.read_bytes()
    assert after.startswith(crlf)
    assert b"\r" not in after[len(crlf):]
    assert after.endswith(b"  profiles: [zeta]\n")
    # Adversarial: the existing entries must still be visible after the append.
    # A second `projects:` key would shadow every pre-existing project for
    # yaml.safe_load (and therefore for scripts/hub-index.py).
    assert after.count(b"projects:") == 1
    names = [e["name"] for e in yaml.safe_load(after.decode("utf-8"))["projects"]]
    assert names == ["alpha", "beta", "epsilon"]
    assert yaml.safe_load(after.decode("utf-8"))["projects"][-1]["profiles"] == ["zeta"]


# @covers FR-0001:AC-10
def test_register_creates_registry_when_absent(hub):
    hub.registry.unlink()
    target = hub.root / "projects" / "first"
    target.mkdir()
    bs.register_project(hub.root, "first", target, "none", False, sys.executable)
    after = hub.registry.read_bytes()
    assert after.startswith(b"# Project registry")
    assert b"\r\n" not in after
    assert yaml.safe_load(after.decode("utf-8"))["projects"][0]["name"] == "first"


# @covers FR-0001:AC-10
def test_register_out_of_tree_path_is_posix_absolute(hub, tmp_path):
    target = tmp_path / "elsewhere" / "zed"
    target.mkdir(parents=True)
    bs.register_project(hub.root, "zed", target, "none", False, sys.executable)
    entry = _registry_entry(hub, "zed")
    assert entry["path"] == target.resolve().as_posix()
    assert "\\" not in entry["path"]


# ---------------------------------------------------------------------------
# AC-11: profile application is idempotent on settings.json
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-11
def test_merge_json_does_not_duplicate_identical_hook_entry(hub):
    base = json.loads(hub.template_settings)
    overlay = json.loads((hub.profiles / "phipa/settings_overlay.json").read_text(encoding="utf-8"))
    assert _phi_hook_count(hub.template_settings) == 1

    merged = bs._merge_json(base, overlay)
    assert _phi_hook_count(json.dumps(merged).encode("utf-8")) == 1
    merged = bs._merge_json(merged, json.loads(json.dumps(overlay)))
    assert _phi_hook_count(json.dumps(merged).encode("utf-8")) == 1


# @covers FR-0001:AC-11
def test_merge_json_still_appends_distinct_entries():
    base = {"hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "a"}]}]}}
    overlay = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Write", "hooks": [{"type": "command", "command": "a"}]},
                {"matcher": "Write", "hooks": [{"type": "command", "command": "b"}]},
            ],
            "Stop": [{"hooks": [{"type": "command", "command": "c"}]}],
        },
        "permissions": {"allow": ["x"]},
    }
    merged = bs._merge_json(base, overlay)
    assert [h["hooks"][0]["command"] for h in merged["hooks"]["PreToolUse"]] == ["a", "b"]
    assert merged["hooks"]["Stop"][0]["hooks"][0]["command"] == "c"
    assert merged["permissions"] == {"allow": ["x"]}


# @covers FR-0001:AC-11
def test_apply_profiles_yields_one_hook_and_template_identical_settings(hub, capsys):
    project = hub.root / "projects" / "applied"
    shutil.copytree(hub.template, project)

    bs.apply_profiles(project, ["phipa"])
    settings = (project / SETTINGS_REL).read_bytes()
    assert _phi_hook_count(settings) == 1
    # Merge was a no-op and the write is LF, so a fresh profiled project's
    # settings.json still byte-equals the template's (no spurious drift).
    assert settings == hub.template_settings
    assert (project / HOOK_REL).read_bytes() == hub.profile_hook

    bs.apply_profiles(project, ["phipa"])
    assert _phi_hook_count((project / SETTINGS_REL).read_bytes()) == 1


# ---------------------------------------------------------------------------
# Round 2 (Reviewer): adversarial coverage of the eb22e50 fixes
#   - AC-3: a profile-owned path whose profile source is absent is dropped from
#     the plan in every mode, including when the project file is also missing
#   - AC-10: CRLF registries with nested comments and `projects: []` variants
#     survive append + set; the post-write re-parse really restores bytes
#   - AC-9 / AC-5: byte comparison re-syncs CRLF-only drift without touching
#     .claude/settings.json
# ---------------------------------------------------------------------------

CRLF_REGISTRY = REGISTRY_TEXT.replace("\n", "\r\n").encode("utf-8")


def _registry_names(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_bytes().decode("utf-8"))
    return [e["name"] for e in data["projects"]]


def _yaml_failing_when(monkeypatch: pytest.MonkeyPatch, marker: str, *, mode: str) -> None:
    """Swap bootstrap's yaml for one that parses normally until it sees text
    containing `marker` (i.e. the post-write re-parse of the edited registry),
    then either raises YAMLError or reports zero projects."""
    real = bs._require_yaml()

    class Fake:
        YAMLError = real.YAMLError

        @staticmethod
        def safe_load(s):
            if marker in s:
                if mode == "raise":
                    raise real.YAMLError("forced parse failure")
                return {"projects": []}
            return real.safe_load(s)

    monkeypatch.setattr(bs, "_require_yaml", lambda: Fake)


# @covers FR-0001:AC-3
def test_sync_plan_drops_owned_path_outright_when_profile_source_missing(hub):
    (hub.profiles / "phipa" / "phi_regex_check.py").unlink()
    assert HOOK_REL not in bs.build_sync_plan(["phipa"])
    # The unprofiled plan is unaffected: the template copy is still its source.
    src, origin = bs.build_sync_plan([])[HOOK_REL]
    assert src == hub.template / HOOK_REL and origin is None
    assert [(p, n) for p, n, _ in bs.missing_profile_sources(["phipa"])] == [(HOOK_REL, "phipa")]
    assert bs.missing_profile_sources([]) == []


# @covers FR-0001:AC-3
def test_missing_profile_source_interactive_never_prompts_for_hook_and_reports_skip(
    hub, profiled, monkeypatch, capsys,
):
    (hub.profiles / "phipa" / "phi_regex_check.py").unlink()
    # answers=None: any input() call fails the test.
    out, prompts = _run_upgrade(monkeypatch, capsys, profiled, yes=False)
    assert prompts == []
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook
    assert f"! {HOOK_REL}: profile source missing -- skipped" in out
    assert "NOT compared against the template copy" in out
    assert "Profile source missing: 1 path(s) skipped" in out
    assert f"CHANGED: {HOOK_REL}" not in out and f"NEW: {HOOK_REL}" not in out


# @covers FR-0001:AC-3
# @covers FR-0001:AC-4
@pytest.mark.parametrize("yes", [True, False])
def test_missing_profile_source_and_missing_project_file_writes_nothing(
    hub, profiled, monkeypatch, capsys, yes,
):
    # Adversarial: neither the profile source nor the project file exists. The
    # only remaining candidate is the template copy, and it must not be added.
    (hub.profiles / "phipa" / "phi_regex_check.py").unlink()
    (profiled / HOOK_REL).unlink()
    out, prompts = _run_upgrade(monkeypatch, capsys, profiled, yes=yes)
    assert prompts == []
    assert not (profiled / HOOK_REL).exists()
    assert f"+ {HOOK_REL}" not in out and f"NEW: {HOOK_REL}" not in out
    assert "Added:" not in out
    assert f"! {HOOK_REL}: profile source missing -- skipped" in out


# @covers FR-0001:AC-3
# @covers FR-0001:AC-4
def test_profiled_crlf_hook_resyncs_from_profile_bytes(hub, profiled, monkeypatch, capsys):
    # Line-ending-only drift used to be invisible to read_text(); it must now
    # re-sync, and from the profile source.
    _write(profiled / HOOK_REL, hub.profile_hook.replace(b"\n", b"\r\n"))
    out, _ = _run_upgrade(monkeypatch, capsys, profiled)
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook
    assert f"~ {HOOK_REL} (updated (from profile: phipa))" in out


# @covers FR-0001:AC-9
def test_unprofiled_crlf_hook_resyncs_from_template_bytes(hub, unprofiled, monkeypatch, capsys):
    _write(unprofiled / HOOK_REL, hub.template_hook.replace(b"\n", b"\r\n"))
    out, _ = _run_upgrade(monkeypatch, capsys, unprofiled)
    assert (unprofiled / HOOK_REL).read_bytes() == hub.template_hook
    assert f"~ {HOOK_REL} (updated)" in out
    assert "from profile" not in out


# @covers FR-0001:AC-9
# @covers FR-0001:AC-5
@pytest.mark.parametrize("yes", [True, False])
def test_settings_crlf_only_difference_is_drift_warned_never_written(
    hub, unprofiled, monkeypatch, capsys, yes,
):
    crlf = hub.template_settings.replace(b"\n", b"\r\n")
    _write(unprofiled / SETTINGS_REL, crlf)
    out, prompts = _run_upgrade(monkeypatch, capsys, unprofiled, yes=yes)
    assert prompts == []
    assert (unprofiled / SETTINGS_REL).read_bytes() == crlf
    assert f"! {SETTINGS_REL} differs from template" in out
    assert "Drift:    1 file(s)" in out
    # No profile-related headings for an unprofiled project (AC-9).
    assert "Profile" not in out.split("Upgrade summary:")[1]


# @covers FR-0001:AC-10
# @covers FR-0001:AC-7
def test_crlf_registry_with_nested_comments_survives_append_then_set(hub):
    hub.registry.write_bytes(CRLF_REGISTRY)
    target = hub.root / "projects" / "gamma"
    target.mkdir()
    bs.register_project(hub.root, "gamma", target, "python", False, sys.executable, profiles=[])
    after_append = hub.registry.read_bytes()
    assert after_append.startswith(CRLF_REGISTRY)
    assert b"\r" not in after_append[len(CRLF_REGISTRY):]
    assert _registry_names(hub.registry) == ["alpha", "beta", "gamma"]

    # Insert into a CRLF entry whose last key is preceded by a nested comment,
    # then replace the `profiles:` line of the LF entry just appended.
    assert bs.set_registry_profiles(hub.registry, "beta", ["phipa"]) is True
    assert bs.set_registry_profiles(hub.registry, "gamma", ["zeta"]) is True

    after = hub.registry.read_bytes()
    lines = after.split(b"\n")
    # Every original CRLF line survives, in order, with its CR.
    assert [ln for ln in lines if ln.endswith(b"\r")] == CRLF_REGISTRY.split(b"\n")[:-1]
    # The inserted line is LF-only and sits right after beta's `private:`.
    assert lines[lines.index(b"  private: true\r") + 1] == b"  profiles: [phipa]"
    assert after.count(b"projects:") == 1
    data = yaml.safe_load(after.decode("utf-8"))
    by_name = {e["name"]: e for e in data["projects"]}
    assert list(by_name) == ["alpha", "beta", "gamma"]
    assert "profiles" not in by_name["alpha"]
    assert by_name["beta"]["profiles"] == ["phipa"]
    assert by_name["gamma"]["profiles"] == ["zeta"]
    entries, errors = hub_index._load_registry(hub.registry, "hub/projects.yaml")
    assert errors == [] and len(entries) == 3


# @covers FR-0001:AC-10
@pytest.mark.parametrize(
    "raw, expect_prefix",
    [
        (b"# h\r\nprojects: []\r\n", b"# h\r\nprojects:\r\n- name: delta\n"),
        (b"# h\r\nprojects: []  # none yet\r\n", b"# h\r\nprojects:  # none yet\r\n- name: delta\n"),
        (b"# h\r\nprojects: [ ]", b"# h\r\nprojects:\n- name: delta\n"),
        (
            b"# h\r\nprojects:\r\n# nothing registered yet\r\n",
            b"# h\r\nprojects:\r\n# nothing registered yet\r\n- name: delta\n",
        ),
        (b"# h\r\n", b"# h\r\nprojects:\n- name: delta\n"),
    ],
    ids=["crlf-empty-list", "crlf-empty-list-comment", "no-trailing-newline", "crlf-key-then-comment", "no-key"],
)
def test_register_crlf_empty_registry_variants_parse_to_one_project(hub, raw, expect_prefix):
    hub.registry.write_bytes(raw)
    target = hub.root / "projects" / "delta"
    target.mkdir()
    bs.register_project(hub.root, "delta", target, "none", False, sys.executable, profiles=["phipa"])
    after = hub.registry.read_bytes()
    assert after.startswith(expect_prefix), after
    assert after.count(b"projects:") == 1
    data = yaml.safe_load(after.decode("utf-8"))
    assert [e["name"] for e in data["projects"]] == ["delta"]
    assert data["projects"][0]["profiles"] == ["phipa"]


# @covers FR-0001:AC-10
# @covers FR-0001:AC-7
def test_set_registry_profiles_with_column_zero_comment_inside_entry(hub):
    # A column-0 comment inside an entry is legal YAML; the block scanner must
    # not lose the entry or corrupt neighbours.
    text = REGISTRY_TEXT.replace(
        "  stack: node\n", "  stack: node\n# column-0 comment inside beta (YAML ignores it)\n",
    )
    hub.registry.write_bytes(text.encode("utf-8"))
    assert bs.set_registry_profiles(hub.registry, "beta", ["phipa"]) is True
    after = hub.registry.read_bytes()
    assert [ln for ln in after.split(b"\n") if ln != b"  profiles: [phipa]"] == text.encode("utf-8").split(b"\n")
    data = yaml.safe_load(after.decode("utf-8"))
    assert [e["name"] for e in data["projects"]] == ["alpha", "beta"]
    assert data["projects"][1]["profiles"] == ["phipa"]
    assert data["projects"][1]["private"] is True


# @covers FR-0001:AC-10
@pytest.mark.parametrize("mode", ["raise", "count"])
def test_append_restores_original_bytes_when_recheck_fails(hub, monkeypatch, capsys, mode):
    original = hub.registry.read_bytes()
    _yaml_failing_when(monkeypatch, "ghost", mode=mode)
    with pytest.raises(SystemExit) as e:
        bs.append_registry_entry(hub.registry, "- name: ghost\n  path: projects/ghost\n")
    assert e.value.code == 1
    assert hub.registry.read_bytes() == original
    assert "original bytes restored" in capsys.readouterr().err


# @covers FR-0001:AC-10
def test_append_to_absent_registry_leaves_no_file_when_recheck_fails(hub, monkeypatch, capsys):
    hub.registry.unlink()
    _yaml_failing_when(monkeypatch, "ghost", mode="raise")
    with pytest.raises(SystemExit):
        bs.append_registry_entry(hub.registry, "- name: ghost\n  path: projects/ghost\n")
    assert not hub.registry.exists()


# @covers FR-0001:AC-10
# @covers FR-0001:AC-7
def test_set_registry_profiles_restores_original_bytes_when_recheck_fails(hub, monkeypatch, capsys):
    hub.registry.write_bytes(CRLF_REGISTRY)
    _yaml_failing_when(monkeypatch, "profiles: [phipa]", mode="count")
    with pytest.raises(SystemExit):
        bs.set_registry_profiles(hub.registry, "alpha", ["phipa"])
    assert hub.registry.read_bytes() == CRLF_REGISTRY
    assert "original bytes restored" in capsys.readouterr().err


# @covers FR-0001:AC-10
def test_append_after_trailing_top_level_key_is_refused_and_restored(hub, capsys):
    # Real (un-faked) failure: a top-level key after the list means an EOF
    # append is not under `projects:`; PyYAML rejects it and the original
    # bytes must come back.
    raw = REGISTRY_TEXT.encode("utf-8") + b"patterns_root: patterns/\n"
    hub.registry.write_bytes(raw)
    target = hub.root / "projects" / "delta"
    target.mkdir()
    with pytest.raises(SystemExit):
        bs.register_project(hub.root, "delta", target, "none", False, sys.executable)
    assert hub.registry.read_bytes() == raw
    assert "original bytes restored" in capsys.readouterr().err


# @covers FR-0001:AC-10
def test_append_dies_before_writing_when_projects_is_a_mapping(hub, capsys):
    raw = b"# h\nprojects:\n  alpha:\n    path: projects/alpha\n"
    hub.registry.write_bytes(raw)
    target = hub.root / "projects" / "delta"
    target.mkdir()
    with pytest.raises(SystemExit):
        bs.register_project(hub.root, "delta", target, "none", False, sys.executable)
    assert hub.registry.read_bytes() == raw
    assert "not a list" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# AC-12: hub-level tests exist for both fixture shapes
# ---------------------------------------------------------------------------

# @covers FR-0001:AC-12
def test_both_fixture_shapes_are_built_under_tmp_path_and_are_distinct(hub, profiled, unprofiled, tmp_path):
    # Both synthetic projects live in the temp fake hub, never the real one.
    for project in (profiled, unprofiled):
        assert project.is_relative_to(tmp_path)
        assert not project.resolve().is_relative_to(HUB_ROOT / "projects")
    # Profiled: `phipa` record + profile-sourced hook + AGENTS.md block.
    assert _read_record(profiled) == ["phipa"]
    assert (profiled / HOOK_REL).read_bytes() == hub.profile_hook
    assert hub.block.strip() in (profiled / "AGENTS.md").read_text(encoding="utf-8")
    # Unprofiled: empty record + template hook, no block.
    assert _read_record(unprofiled) == []
    assert (unprofiled / HOOK_REL).read_bytes() == hub.template_hook
    assert hub.block.strip() not in (unprofiled / "AGENTS.md").read_text(encoding="utf-8")
    # The two shapes really differ, and building them left the fake registry alone.
    assert hub.profile_hook != hub.template_hook
    assert hub.registry.read_bytes() == REGISTRY_TEXT.encode("utf-8")
