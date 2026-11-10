"""Hub-level reviewer tests for `scripts/bootstrap.py` -- FR-0020.

`--upgrade` stops clobbering project-specialised files: `pytest.ini` is
seed-only (AC-1), the two stack-injected files are rendered for the project's
registered stack (AC-2), added files carry a provenance reminder (AC-3), and
`.gitattributes` is a managed block that never touches the project's own lines
(AC-4, AC-5), all idempotently (AC-6) and without disturbing FR-0001/FR-0019
behaviour (AC-7).

Everything runs against a *fake hub* built in `tmp_path` (the
`test_bootstrap_profiles.py` pattern): a minimal `template/` whose
stack-injected files, `pytest.ini`, `.gitattributes` and `settings.json` are
the live template's bytes, a copy of the real `profiles/phipa/`, a temporary
`hub/projects.yaml`, and stub `scripts/*.py` for create's subprocess calls.
`HUB_ROOT`, `TEMPLATE_ROOT` and `PROFILES_ROOT` are monkeypatched on every
module a test drives. Nothing here touches `projects/`, `hub/`, `parking-lot/`
or `patterns/` of the real hub.

Three modules are in play:

* **live** -- the checked-out `scripts/bootstrap.py` (the behaviour under test);
* **fr** -- `git show 12996e8:scripts/bootstrap.py`, FR-0020's implementation;
* **base** -- `git show 6738b1e:scripts/bootstrap.py`, FR-0020's base.

"Unchanged against base" checks (create output, `.claude/settings.json`
output, the test files FR-0020 must leave unedited) diff the two *fixed*
commits `fr` and `base`, never HEAD or the working tree, so they do not rot
when a later FR changes the script. The bite checks run AC-1, AC-2 and AC-5's
scenarios against `base` and require them to fail. Every `git` read skips
when the object is unreachable. Fixture text is synthetic.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

# tests/unit/scripts/ -> parents[3] == hub root
HUB_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = HUB_ROOT / "scripts"
REAL_TEMPLATE = HUB_ROOT / "template"
REAL_PROFILE = HUB_ROOT / "profiles" / "phipa"
FIXTURES = HUB_ROOT / "tests" / "fixtures" / "bootstrap-upgrade"

# FR-0020's base and implementation commits. Immutable, so every comparison
# between them is stable for the life of the repo.
BASE_REF = "6738b1e54cd32ff6f017d843d8112e59b0d4970d"
FR_REF = "12996e89abe3d92dabe6161471f4c6775b375f81"

PYTHON_RULE = ".cursor/rules/20-python.mdc"
NODE_RULE = ".cursor/rules/20-node.mdc"
WORKFLOW = ".github/workflows/agent-gates.yml"
GITATTR = ".gitattributes"
PYTEST_INI = "pytest.ini"
SETTINGS = ".claude/settings.json"
HOOK_REL = ".agent-team/hooks/phi_regex_check.py"
REGISTER_REL = "specs/knowledge/provenance-register.md"

BEGIN_PREFIX = "# BEGIN bootstrap.py --upgrade managed block"
END_PREFIX = "# END bootstrap.py --upgrade managed block"
UP_TO_DATE = "Everything is already up to date."
RENORMALIZE = "git add --renormalize ."


def _load_module(name: str, path: Path) -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(HUB_ROOT), *args], capture_output=True, check=False
    )


def _git_show(ref: str, rel: str) -> bytes | None:
    proc = _git("show", f"{ref}:{rel}")
    return proc.stdout if proc.returncode == 0 else None


def _reachable(*refs: str) -> None:
    for ref in refs:
        if _git("cat-file", "-e", f"{ref}^{{commit}}").returncode != 0:
            pytest.skip(f"{ref[:7]} not reachable")


bs = _load_module("bootstrap_fr0020_live", SCRIPTS_DIR / "bootstrap.py")


@pytest.fixture(scope="module")
def pinned(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ModuleType]:
    """`bootstrap.py` at the base and at FR-0020's commit, as extra modules."""
    out: dict[str, ModuleType] = {}
    for tag, ref in (("base", BASE_REF), ("fr", FR_REF)):
        src = _git_show(ref, "scripts/bootstrap.py")
        if src is None:
            pytest.skip(f"{tag} {ref[:7]} not reachable")
        d = tmp_path_factory.mktemp(f"fr0020_{tag}")
        (d / "bootstrap.py").write_bytes(src)
        out[tag] = _load_module(f"bootstrap_fr0020_{tag}", d / "bootstrap.py")
    return out


# ---------------------------------------------------------------------------
# Fake hub
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

REGISTRY_HEAD = "# Synthetic registry for FR-0020 tests.\nprojects:\n"
STUB_EXIT_0 = "import sys\nsys.exit(0)\n"


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def _build_hub(root: Path) -> SimpleNamespace:
    template = root / "template"
    profiles = root / "profiles"
    _write(template / "AGENTS.md", TEMPLATE_AGENTS_MD)
    _write(template / "README.md", "# template\n")
    _write(template / ".gitignore", "__pycache__/\n")
    for rel in (
        PYTEST_INI,
        GITATTR,
        PYTHON_RULE,
        NODE_RULE,
        WORKFLOW,
        SETTINGS,
        HOOK_REL,
    ):
        _write(template / rel, (REAL_TEMPLATE / rel).read_bytes())
    _write(template / ".agent-team/roles/reviewer.md", "# Role: Reviewer\n")
    _write(template / ".agent-team/commands/gate.md", "Run the gate for $ARGUMENTS.\n")
    _write(template / "scripts/index-specs.py", STUB_EXIT_0)
    _write(template / "scripts/deploy-gate.py", STUB_EXIT_0)
    _write(template / "specs/_template/FR-template.md", "# FR template\n")
    _write(template / "specs/FR-0001-example.md", "# example\n")
    (template / "src").mkdir()
    (template / "tests").mkdir()
    shutil.copytree(REAL_PROFILE, profiles / "phipa")
    _write(root / "hub/projects.yaml", REGISTRY_HEAD)
    _write(root / "scripts/hub-index.py", STUB_EXIT_0)
    (root / "projects").mkdir()
    return SimpleNamespace(
        root=root,
        template=template,
        profiles=profiles,
        registry=root / "hub/projects.yaml",
    )


def _patch(
    mod: ModuleType, hub: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod, "HUB_ROOT", hub.root)
    monkeypatch.setattr(mod, "TEMPLATE_ROOT", hub.template)
    monkeypatch.setattr(mod, "PROFILES_ROOT", hub.profiles)


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    h = _build_hub(tmp_path / "hub")
    _patch(bs, h, monkeypatch)
    return h


def _create(
    mod: ModuleType,
    hub: SimpleNamespace,
    name: str,
    stack: str = "none",
    profile: list[str] | None = None,
    *,
    register_stack: str | None = None,
) -> Path:
    """Create a throwaway with `--no-register --no-git`; optionally
    hand-register it in the temporary registry with `register_stack`."""
    mod.run_create(
        SimpleNamespace(
            name=name,
            description=f"Synthetic FR-0020 fixture {name}.",
            stack=stack,
            profile=list(profile or []),
            keep_example=False,
            no_git=True,
            private=False,
            no_register=True,
        )
    )
    project = hub.root / "projects" / name
    if register_stack is not None:
        _register(hub, name, register_stack)
    return project


def _register(
    hub: SimpleNamespace,
    name: str,
    stack: str,
    *,
    path: str | None = None,
    local: bool = False,
) -> None:
    entry = (
        f"- name: {name}\n  path: {path or 'projects/' + name}\n"
        f"  created: '2026-09-26'\n  stack: {stack}\n  private: false\n"
    )
    target = hub.root / "hub" / ("projects.local.yaml" if local else "projects.yaml")
    prior = target.read_bytes() if target.is_file() else b"projects:\n"
    _write(target, prior + entry.encode("utf-8"))


def _upgrade(
    mod: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    project: Path,
    *,
    yes: bool = True,
    answers: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Run `mod.run_upgrade`; with `answers=None` any prompt fails the test."""
    capsys.readouterr()
    prompts: list[str] = []
    queue = list(answers or [])

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        if answers is None:
            raise AssertionError(f"unexpected prompt: {prompt!r}")
        return queue.pop(0) if queue else "n"

    monkeypatch.setattr("builtins.input", fake_input)
    mod.run_upgrade(project, auto_yes=yes)
    captured = capsys.readouterr()
    return captured.out + captured.err, prompts


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _drift_line(rel: str) -> str:
    return f"  ! {rel} differs from template — NOT changed (drift; reconcile by hand)"


def _reported(out: str, rel: str) -> bool:
    """True when `rel` appears in any summary list (updated/added/drift)."""
    return any(
        line.strip() in (f"~ {rel}", f"+ {rel}")
        or line.strip().startswith(f"! {rel}  (")
        for line in out.splitlines()
    )


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _job_uncommented(text: str, job: str) -> bool:
    return re.search(rf"^  {re.escape(job)}:\s*$", text, re.MULTILINE) is not None


def _rule_enabled(text: str) -> bool:
    return "DISABLED_BY_DEFAULT" not in text and "<!--" not in text


# ---------------------------------------------------------------------------
# Scenarios shared by the live tests and the bite checks against `base`
# ---------------------------------------------------------------------------


def _scenario_ac1_pytest_ini_survives(mod, hub, monkeypatch, capsys) -> None:
    project = _create(mod, hub, "fx-pyini", register_stack="none")
    custom = (hub.template / PYTEST_INI).read_bytes() + _fixture(
        "pytest-project-section.ini"
    )
    _write(project / PYTEST_INI, custom)
    out, _ = _upgrade(mod, monkeypatch, capsys, project)
    assert (project / PYTEST_INI).read_bytes() == custom
    assert _drift_line(PYTEST_INI) in out.splitlines()
    assert (
        f"    ! {PYTEST_INI}  (reconcile by hand — never auto-overwritten)"
        in out.splitlines()
    )
    assert f"    ~ {PYTEST_INI}" not in out.splitlines()


def _scenario_ac2_python_stack_kept(mod, hub, monkeypatch, capsys) -> None:
    project = _create(mod, hub, "fx-py", "python", register_stack="python")
    before = _tree(project)
    out, _ = _upgrade(mod, monkeypatch, capsys, project)
    for rel in (PYTHON_RULE, WORKFLOW):
        assert (project / rel).read_bytes() == before[rel], rel
        assert not _reported(out, rel), rel
    assert _rule_enabled((project / PYTHON_RULE).read_text(encoding="utf-8"))
    assert _job_uncommented(
        (project / WORKFLOW).read_text(encoding="utf-8"), "python-tests"
    )


def _scenario_ac5_project_a_shape_block_inserted(mod, hub, monkeypatch, capsys) -> None:
    project = _create(mod, hub, "fx-project-a", register_stack="none")
    project_a = _fixture("project-a-shape.gitattributes")
    _write(project / GITATTR, project_a)
    out, _ = _upgrade(mod, monkeypatch, capsys, project)
    block = (hub.template / GITATTR).read_bytes()
    assert (project / GITATTR).read_bytes() == block + b"\n" + project_a
    assert f"    ~ {GITATTR}" in out.splitlines()
    assert RENORMALIZE in out


SCENARIOS: dict[str, Callable[..., None]] = {
    "AC-1": _scenario_ac1_pytest_ini_survives,
    "AC-2": _scenario_ac2_python_stack_kept,
    "AC-5": _scenario_ac5_project_a_shape_block_inserted,
}


# ---------------------------------------------------------------------------
# AC-1: pytest.ini is seeded, never overwritten
# ---------------------------------------------------------------------------


# @covers FR-0020:AC-1
def test_project_a_shaped_pytest_ini_survives_yes_and_is_listed_as_drift(
    hub, monkeypatch, capsys
):
    _scenario_ac1_pytest_ini_survives(bs, hub, monkeypatch, capsys)


# @covers FR-0020:AC-1
def test_customised_pytest_ini_interactive_prints_diff_without_prompting(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-pyini-i", register_stack="none")
    custom = (hub.template / PYTEST_INI).read_bytes() + _fixture(
        "pytest-project-section.ini"
    )
    _write(project / PYTEST_INI, custom)
    out, prompts = _upgrade(bs, monkeypatch, capsys, project, yes=False, answers=None)
    assert prompts == []
    assert (project / PYTEST_INI).read_bytes() == custom
    assert _drift_line(PYTEST_INI) in out.splitlines()
    # The diff is shown (either direction), without a prompt.
    assert any(
        ln.strip() in ("-testpaths = tests", "+testpaths = tests")
        for ln in out.splitlines()
    )


# @covers FR-0020:AC-1
def test_absent_pytest_ini_is_seeded_with_the_template_bytes(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-pyini-absent", register_stack="none")
    (project / PYTEST_INI).unlink()
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / PYTEST_INI).read_bytes() == (
        hub.template / PYTEST_INI
    ).read_bytes()
    assert f"  + {PYTEST_INI} (new file)" in out.splitlines()
    assert f"    + {PYTEST_INI}" in out.splitlines()


# @covers FR-0020:AC-1
def test_crlf_only_pytest_ini_difference_is_drift_not_rewritten(
    hub, monkeypatch, capsys
):
    """Adversarial: a line-ending-only difference must not slip through as
    'equal' (decoded compare) nor be rewritten to LF."""
    project = _create(bs, hub, "fx-pyini-crlf", register_stack="none")
    crlf = (hub.template / PYTEST_INI).read_bytes().replace(b"\n", b"\r\n")
    _write(project / PYTEST_INI, crlf)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / PYTEST_INI).read_bytes() == crlf
    assert _drift_line(PYTEST_INI) in out.splitlines()


# @covers FR-0020:AC-1
def test_seed_only_set_names_both_files_and_is_not_mutated_by_a_run(
    hub, monkeypatch, capsys
):
    """Adversarial: the per-run additions (unresolved stack, damaged block)
    must not leak into the module-level set for the next run."""
    assert bs.SEED_ONLY_FILES == {SETTINGS, PYTEST_INI}
    project = _create(bs, hub, "fx-seed-leak", "python")  # unregistered
    _write(
        project / GITATTR, "# BEGIN bootstrap.py --upgrade managed block\n*.x -text\n"
    )
    _upgrade(bs, monkeypatch, capsys, project)
    assert bs.SEED_ONLY_FILES == {SETTINGS, PYTEST_INI}


# @covers FR-0020:AC-1
# @covers FR-0020:AC-7
def test_settings_json_drift_output_and_bytes_identical_between_base_and_fr(
    pinned, tmp_path, monkeypatch, capsys
):
    """`.claude/settings.json`'s behaviour and output are byte-identical to
    today's: base and FR commits over identical fake hubs, --yes and
    interactive."""
    results = {}
    for tag in ("base", "fr"):
        mod = pinned[tag]
        h = _build_hub(tmp_path / tag / "hub")
        _patch(mod, h, monkeypatch)
        project = _create(mod, h, "fx-settings", register_stack="none")
        drifted = (project / SETTINGS).read_bytes() + b"\n"
        _write(project / SETTINGS, drifted)
        lines = []
        for yes in (True, False):
            out, prompts = _upgrade(
                mod, monkeypatch, capsys, project, yes=yes, answers=None
            )
            assert prompts == []
            assert (project / SETTINGS).read_bytes() == drifted
            lines.append([ln for ln in out.splitlines() if "settings.json" in ln])
        results[tag] = lines
    assert results["fr"] == results["base"]
    assert results["fr"][0], "settings drift was not reported at all"


# ---------------------------------------------------------------------------
# AC-2: stack-injected files are compared against the project's stack rendering
# ---------------------------------------------------------------------------


# @covers FR-0020:AC-2
def test_registered_python_project_keeps_rule_and_ci_job_with_unchanged_template(
    hub, monkeypatch, capsys
):
    _scenario_ac2_python_stack_kept(bs, hub, monkeypatch, capsys)


# @covers FR-0020:AC-2
def test_registered_node_project_keeps_rule_and_ci_job_with_unchanged_template(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-node", "node", register_stack="node")
    before = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    for rel in (NODE_RULE, WORKFLOW, PYTHON_RULE):
        assert (project / rel).read_bytes() == before[rel], rel
        assert not _reported(out, rel), rel
    assert _rule_enabled((project / NODE_RULE).read_text(encoding="utf-8"))
    wf = (project / WORKFLOW).read_text(encoding="utf-8")
    assert _job_uncommented(wf, "node-tests")
    assert not _job_uncommented(wf, "python-tests")
    assert "Project stack is unknown" not in out


@pytest.mark.parametrize("stack", ["python", "node"])
# @covers FR-0020:AC-2
def test_template_change_to_both_stack_files_arrives_rendered_for_the_stack(
    hub, monkeypatch, capsys, stack
):
    """A template change to either file still arrives, and what arrives is
    byte-identical to what create would write today for that stack."""
    project = _create(bs, hub, f"fx-{stack}-chg", stack, register_stack=stack)
    rule = PYTHON_RULE if stack == "python" else NODE_RULE
    wf_t = hub.template / WORKFLOW
    wf_text = wf_t.read_text(encoding="utf-8")
    assert '"3.11"' in wf_text and '"20"' in wf_text
    _write(
        wf_t,
        "# synthetic template change (FR-0020 review)\n"
        + wf_text.replace('"3.11"', '"3.12"').replace('"20"', '"22"'),
    )
    rule_t = hub.template / rule
    _write(
        rule_t,
        rule_t.read_text(encoding="utf-8").replace(
            "\n-->", "\n- Synthetic new bullet.\n-->", 1
        ),
    )
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    fresh = _create(bs, hub, f"fx-{stack}-fresh", stack)
    for rel in (rule, WORKFLOW):
        assert (project / rel).read_bytes() == (fresh / rel).read_bytes(), rel
        assert f"    ~ {rel}" in out.splitlines(), rel
    wf = (project / WORKFLOW).read_text(encoding="utf-8")
    assert wf.startswith("# synthetic template change")
    assert _job_uncommented(wf, f"{stack}-tests")
    assert "Synthetic new bullet" in (project / rule).read_text(encoding="utf-8")
    assert _rule_enabled((project / rule).read_text(encoding="utf-8"))


# @covers FR-0020:AC-2
def test_unregistered_python_project_keeps_both_files_with_one_notice(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-unreg-py", "python")
    before = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    for rel in (PYTHON_RULE, WORKFLOW):
        assert (project / rel).read_bytes() == before[rel], rel
        assert _drift_line(rel) in out.splitlines(), rel
    assert not _reported(out, NODE_RULE)
    notices = [ln for ln in out.splitlines() if "stack is unknown" in ln]
    assert len(notices) == 1
    assert ".cursor/rules/20-<stack>.mdc" in notices[0] and WORKFLOW in notices[0]


# @covers FR-0020:AC-2
def test_unregistered_node_project_keeps_its_node_rule_per_decision(
    hub, monkeypatch, capsys
):
    """Decisions ruling: the unresolved seed-only set covers both cursor-rule
    variants, so a node project's enabled rule survives too."""
    project = _create(bs, hub, "fx-unreg-node", "node")
    before = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    for rel in (NODE_RULE, WORKFLOW, PYTHON_RULE):
        assert (project / rel).read_bytes() == before[rel], rel
    assert _drift_line(NODE_RULE) in out.splitlines()
    assert not _reported(out, PYTHON_RULE)


# @covers FR-0020:AC-2
def test_unresolved_stack_does_not_deliver_template_change_it_reports_drift(
    hub, monkeypatch, capsys
):
    """Adversarial: seed-only means *no* write, even when the template moved."""
    project = _create(bs, hub, "fx-unreg-chg", "python")
    before = _tree(project)
    _write(
        hub.template / WORKFLOW, b"# changed\n" + (hub.template / WORKFLOW).read_bytes()
    )
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / WORKFLOW).read_bytes() == before[WORKFLOW]
    assert _drift_line(WORKFLOW) in out.splitlines()


@pytest.mark.parametrize("bad", ["rust", "Python", "''"])
# @covers FR-0020:AC-2
def test_stack_outside_the_allowed_set_is_unresolved(hub, monkeypatch, capsys, bad):
    project = _create(bs, hub, "fx-badstack", "python", register_stack=bad)
    before = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / WORKFLOW).read_bytes() == before[WORKFLOW]
    assert (project / PYTHON_RULE).read_bytes() == before[PYTHON_RULE]
    assert sum("stack is unknown" in ln for ln in out.splitlines()) == 1


# @covers FR-0020:AC-2
def test_malformed_registry_is_unresolved_not_a_crash(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-badreg", "python")
    _write(hub.registry, "projects: [\n  - name: fx-badreg\n")
    before = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / WORKFLOW).read_bytes() == before[WORKFLOW]
    assert sum("stack is unknown" in ln for ln in out.splitlines()) == 1


# @covers FR-0020:AC-2
def test_stack_is_read_from_local_overlay_over_shared_registry(
    hub, monkeypatch, capsys
):
    """Shared registry says `none` (which would revert the files); the
    per-machine overlay says `python` and wins by name."""
    project = _create(bs, hub, "fx-overlay", "python", register_stack="none")
    _register(hub, "fx-overlay", "python", local=True)
    before = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / WORKFLOW).read_bytes() == before[WORKFLOW]
    assert (project / PYTHON_RULE).read_bytes() == before[PYTHON_RULE]
    assert not _reported(out, WORKFLOW)


# @covers FR-0020:AC-2
def test_stack_resolves_by_name_when_registry_path_differs(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-byname", "python")
    _register(hub, "fx-byname", "python", path="projects/somewhere-else")
    assert bs.resolve_stack(project, hub.root) == ("python", [])
    before = _tree(project)
    _upgrade(bs, monkeypatch, capsys, project)
    assert (project / WORKFLOW).read_bytes() == before[WORKFLOW]


# @covers FR-0020:AC-2
def test_registered_none_uses_raw_template_bytes_as_today(hub, monkeypatch, capsys):
    """Adversarial: `none` is resolved, so it must not be seed-only: a
    python-enabled project registered `none` is synced to the template."""
    project = _create(bs, hub, "fx-none", "python", register_stack="none")
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    for rel in (PYTHON_RULE, WORKFLOW):
        assert (project / rel).read_bytes() == (hub.template / rel).read_bytes()
        assert f"    ~ {rel}" in out.splitlines()
    assert "stack is unknown" not in out


# @covers FR-0020:AC-2
def test_agents_md_is_never_in_the_upgrade_plan(hub):
    assert "AGENTS.md" not in bs.build_sync_plan([])
    assert "AGENTS.md" not in bs.build_sync_plan(["phipa"])


# ---------------------------------------------------------------------------
# AC-3: provenance reminder
# ---------------------------------------------------------------------------

PROV_HEAD = (
    f"  Provenance: {{n}} added file(s) need a row in {REGISTER_REL} before commit:"
)


def _add_two_template_scripts(hub: SimpleNamespace) -> list[str]:
    rels = ["scripts/fx_new_alpha.py", "scripts/fx_new_beta.py"]
    for rel in rels:
        _write(hub.template / rel, "# synthetic new template file\n")
    return rels


# @covers FR-0020:AC-3
def test_register_and_two_added_files_print_reminder_after_added_block(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-prov", register_stack="none")
    _write(project / REGISTER_REL, _fixture("provenance-register.md"))
    rels = _add_two_template_scripts(hub)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    lines = out.splitlines()
    head = PROV_HEAD.format(n=2)
    assert lines.count(head) == 1
    i = lines.index(head)
    added_i = lines.index("  Added:    2 file(s)")
    # The reminder follows the Added: block's own lines directly.
    assert lines[added_i + 1 : added_i + 3] == [f"    + {r}" for r in rels]
    assert i == added_i + 3
    assert lines[i + 1 : i + 3] == [f"    + {r}" for r in rels]


# @covers FR-0020:AC-3
def test_register_present_but_nothing_added_prints_nothing_extra(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-prov-zero", register_stack="none")
    _write(project / REGISTER_REL, _fixture("provenance-register.md"))
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert "Provenance:" not in out
    assert UP_TO_DATE in out


# @covers FR-0020:AC-3
def test_added_files_without_register_print_no_reminder(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-prov-none", register_stack="none")
    _write(project / "specs/provenance-register.md", _fixture("provenance-register.md"))
    _add_two_template_scripts(hub)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert "  Added:    2 file(s)" in out.splitlines()
    assert "Provenance:" not in out


# @covers FR-0020:AC-3
def test_profile_sourced_added_file_is_named_in_the_reminder(hub, monkeypatch, capsys):
    project = _create(
        bs, hub, "fx-prov-phipa", profile=["phipa"], register_stack="none"
    )
    _write(project / REGISTER_REL, _fixture("provenance-register.md"))
    (project / HOOK_REL).unlink()
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    lines = out.splitlines()
    i = lines.index(PROV_HEAD.format(n=1))
    assert lines[i + 1].startswith(f"    + {HOOK_REL}")


# @covers FR-0020:AC-3
def test_interactive_declined_addition_is_not_counted(hub, monkeypatch, capsys):
    """Adversarial: the reminder counts what was added, not what was offered."""
    project = _create(bs, hub, "fx-prov-i", register_stack="none")
    _write(project / REGISTER_REL, _fixture("provenance-register.md"))
    rels = _add_two_template_scripts(hub)
    out, prompts = _upgrade(
        bs, monkeypatch, capsys, project, yes=False, answers=["y", "n"]
    )
    assert len(prompts) == 2
    lines = out.splitlines()
    i = lines.index(PROV_HEAD.format(n=1))
    added = [r for r in rels if (project / r).exists()]
    assert len(added) == 1
    assert lines[i + 1] == f"    + {added[0]}"


# ---------------------------------------------------------------------------
# AC-4: the template's .gitattributes is a managed block
# ---------------------------------------------------------------------------

_ATTR_RE = re.compile(r"^[-!]?[A-Za-z0-9_.-]+(=\S+)?$")


# @covers FR-0020:AC-4
def test_template_gitattributes_is_one_marked_block_with_the_minimum_set():
    raw = (REAL_TEMPLATE / GITATTR).read_bytes()
    assert b"\r" not in raw
    lines = raw.decode("utf-8").splitlines()
    assert lines[0].startswith(BEGIN_PREFIX) and "bootstrap.py --upgrade" in lines[0]
    assert lines[-1].startswith(END_PREFIX) and "bootstrap.py --upgrade" in lines[-1]
    assert sum(ln.startswith("# BEGIN ") for ln in lines) == 1
    assert sum(ln.startswith("# END ") for ln in lines) == 1
    assert "* text=auto eol=lf" in lines
    for ext in (
        "png",
        "jpg",
        "jpeg",
        "gif",
        "ico",
        "pdf",
        "zip",
        "pptx",
        "docx",
        "xlsx",
    ):
        assert f"*.{ext} binary" in lines, ext
    i = lines.index("specs/_metrics/*.ndjson merge=union")
    assert lines[i - 1].startswith("#"), "the union rule keeps its comment"
    # The live bytes carry the bootstrap.py marker constants exactly.
    assert raw.startswith(bs.GITATTRIBUTES_BLOCK_BEGIN.encode("utf-8"))
    assert raw.endswith(bs.GITATTRIBUTES_BLOCK_END.encode("utf-8"))


# @covers FR-0020:AC-4
def test_every_line_inside_the_block_is_a_valid_gitattributes_line():
    """Adversarial: a stray prose line inside the block would be parsed by
    git as a pattern with attributes."""
    for ln in (REAL_TEMPLATE / GITATTR).read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        pattern, *attrs = ln.split()
        assert pattern and attrs, ln
        assert all(_ATTR_RE.match(a) for a in attrs), ln


def _check_attr(repo: Path, attr: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "check-attr", attr, "--", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip().rsplit(": ", 1)[-1]


def _git_init(repo: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.longpaths", "true"], check=True
    )


# @covers FR-0020:AC-4
def test_git_check_attr_on_a_fresh_throwaway_matches_the_block(hub, capsys):
    project = _create(bs, hub, "fx-checkattr")
    assert (project / GITATTR).read_bytes() == (REAL_TEMPLATE / GITATTR).read_bytes()
    _git_init(project)
    assert _check_attr(project, "text", "pkg/mod.py") == "auto"
    assert _check_attr(project, "eol", "pkg/mod.py") == "lf"
    assert _check_attr(project, "binary", "img/logo.png") == "set"
    assert _check_attr(project, "text", "img/logo.png") == "unset"
    assert _check_attr(project, "merge", "specs/_metrics/2026-09.ndjson") == "union"
    # Adversarial: the union rule is scoped; a non-month file is not union.
    assert _check_attr(project, "merge", "specs/INDEX.md") == "unspecified"


# @covers FR-0020:AC-4
def test_every_tracked_text_file_under_template_is_lf_at_fr_commit():
    _reachable(FR_REF)
    proc = _git("grep", "-I", "-l", "-e", "\r", FR_REF, "--", "template")
    assert proc.returncode == 1 and proc.stdout == b"", proc.stdout.decode(
        "utf-8", "replace"
    )


# @covers FR-0020:AC-4
# @covers FR-0020:AC-7
def test_metrics_log_union_test_and_template_tests_unedited_between_pinned_commits():
    _reachable(BASE_REF, FR_REF)
    proc = _git(
        "diff", "--name-only", BASE_REF, FR_REF, "--", "template/tests", "tests"
    )
    assert proc.returncode == 0 and proc.stdout == b""


# ---------------------------------------------------------------------------
# AC-5: --upgrade syncs the managed block, never the project's own lines
# ---------------------------------------------------------------------------


def _block(hub: SimpleNamespace) -> bytes:
    return (hub.template / GITATTR).read_bytes()


# @covers FR-0020:AC-5
def test_absent_gitattributes_is_added_and_renormalize_reminder_fires(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-ga-absent", register_stack="none")
    (project / GITATTR).unlink()
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == _block(hub)
    assert f"    + {GITATTR}" in out.splitlines()
    assert sum(RENORMALIZE in ln for ln in out.splitlines()) == 1


# @covers FR-0020:AC-5
def test_project_a_shape_gets_block_on_top_and_its_four_rules_intact(
    hub, monkeypatch, capsys
):
    _scenario_ac5_project_a_shape_block_inserted(bs, hub, monkeypatch, capsys)


# @covers FR-0020:AC-5
def test_project_a_shape_duplicate_note_names_duplicates_only(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-project-a-note", register_stack="none")
    _write(project / GITATTR, _fixture("project-a-shape.gitattributes"))
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    notes = [ln for ln in out.splitlines() if "NOTE" in ln and ".gitattributes" in ln]
    assert len(notes) == 1
    assert "* text=auto eol=lf" in notes[0]
    assert "specs/_metrics/*.ndjson merge=union" in notes[0]
    assert "*.pptx -text" not in notes[0]
    assert "specs/INDEX.md text eol=lf" not in notes[0]


# @covers FR-0020:AC-5
def test_no_duplicate_lines_means_no_note(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-ga-nodup", register_stack="none")
    _write(project / GITATTR, "*.pptx -text\n")
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == _block(hub) + b"\n*.pptx -text\n"
    assert "NOTE" not in out


# @covers FR-0020:AC-5
def test_project_lines_after_the_block_keep_winning_in_git(hub, monkeypatch, capsys):
    """Later line wins: Project A's `*.pptx -text` still overrides the block's
    `*.pptx binary`, and its INDEX.md pin still applies."""
    project = _create(bs, hub, "fx-ga-git", register_stack="none")
    _write(project / GITATTR, _fixture("project-a-shape.gitattributes"))
    _upgrade(bs, monkeypatch, capsys, project)
    _git_init(project)
    assert _check_attr(project, "text", "deck/slides.pptx") == "unset"
    assert _check_attr(project, "eol", "specs/INDEX.md") == "lf"
    assert _check_attr(project, "binary", "img/logo.png") == "set"
    assert _check_attr(project, "merge", "specs/_metrics/2026-09.ndjson") == "union"


# @covers FR-0020:AC-5
def test_current_block_is_not_reported_and_no_reminder(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-ga-current", register_stack="none")
    content = b"# project head\n*.bin -text\n\n" + _block(hub) + b"\n*.pptx -text\n"
    _write(project / GITATTR, content)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == content
    assert not _reported(out, GITATTR)
    assert RENORMALIZE not in out
    assert UP_TO_DATE in out


# @covers FR-0020:AC-5
def test_stale_block_is_replaced_and_outside_bytes_are_identical(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-ga-stale", register_stack="none")
    head = b"# project head line\r\n*.bin -text\r\n"  # CRLF, must survive as-is
    stale = (
        bs.GITATTRIBUTES_BLOCK_BEGIN.encode("utf-8")
        + b"* text=auto\n*.png binary\n"
        + bs.GITATTRIBUTES_BLOCK_END.encode("utf-8")
    )
    tail = b"\n*.pptx -text\nno-trailing-newline merge=union"
    _write(project / GITATTR, head + stale + tail)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == head + _block(hub) + tail
    assert f"    ~ {GITATTR}" in out.splitlines()
    assert sum(RENORMALIZE in ln for ln in out.splitlines()) == 1


# @covers FR-0020:AC-5
def test_crlf_project_file_without_markers_keeps_its_bytes_below_the_block(
    hub, monkeypatch, capsys
):
    """Adversarial: a CRLF working-tree copy (autocrlf) must not be
    normalised; every existing line is kept byte-for-byte."""
    project = _create(bs, hub, "fx-ga-crlf", register_stack="none")
    crlf = _fixture("project-a-shape.gitattributes").replace(b"\n", b"\r\n")
    _write(project / GITATTR, crlf)
    _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == _block(hub) + b"\n" + crlf


@pytest.mark.parametrize(
    "damage",
    [
        "begin-only",
        "end-only",
        "reversed",
    ],
)
# @covers FR-0020:AC-5
def test_damaged_markers_leave_the_file_untouched_with_one_drift_line(
    hub, monkeypatch, capsys, damage
):
    project = _create(bs, hub, f"fx-ga-{damage}", register_stack="none")
    b = bs.GITATTRIBUTES_BLOCK_BEGIN
    e = bs.GITATTRIBUTES_BLOCK_END
    body = {
        "begin-only": b + "*.png binary\n*.pptx -text\n",
        "end-only": "*.pptx -text\n" + e,
        "reversed": e + "*.png binary\n" + b + "*.pptx -text\n",
    }[damage].encode("utf-8")
    _write(project / GITATTR, body)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == body
    assert out.splitlines().count(_drift_line(GITATTR)) == 1
    assert RENORMALIZE not in out
    assert f"    ~ {GITATTR}" not in out.splitlines()


@pytest.mark.parametrize("dup", ["two-blocks", "two-begins", "two-ends"])
# @covers FR-0020:AC-5
def test_duplicated_markers_are_drift_and_never_overwritten(
    hub, monkeypatch, capsys, dup
):
    """Adversarial (dispatch brief): duplicated markers are damage. Replacing
    only the first span would leave a second 'managed' span nobody manages."""
    project = _create(bs, hub, f"fx-ga-{dup}", register_stack="none")
    b = bs.GITATTRIBUTES_BLOCK_BEGIN
    e = bs.GITATTRIBUTES_BLOCK_END
    body = {
        "two-blocks": b
        + "*.png binary\n"
        + e
        + "*.pptx -text\n"
        + b
        + "*.gif binary\n"
        + e,
        "two-begins": b + "*.png binary\n" + b + "*.gif binary\n" + e,
        "two-ends": b + "*.png binary\n" + e + "*.pptx -text\n" + e,
    }[dup].encode("utf-8")
    _write(project / GITATTR, body)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == body
    assert out.splitlines().count(_drift_line(GITATTR)) == 1
    assert RENORMALIZE not in out


# @covers FR-0020:AC-5
def test_crlf_checked_out_managed_block_is_not_treated_as_absent(
    hub, monkeypatch, capsys
):
    """Adversarial: a project whose managed block is present but checked out
    CRLF (core.autocrlf=true) has both markers. It must be replaced in place or
    reported as drift -- never get a second block inserted above the first."""
    project = _create(bs, hub, "fx-ga-crlfblock", register_stack="none")
    body = (_block(hub) + b"\n*.pptx -text\n").replace(b"\n", b"\r\n")
    _write(project / GITATTR, body)
    _upgrade(bs, monkeypatch, capsys, project)
    after = (project / GITATTR).read_bytes()
    assert after.count(b"# BEGIN bootstrap.py --upgrade managed block") == 1
    assert after.count(b"# END bootstrap.py --upgrade managed block") == 1


# @covers FR-0020:AC-5
def test_interactive_gitattributes_shows_diff_and_prompts(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-ga-i", register_stack="none")
    project_a = _fixture("project-a-shape.gitattributes")
    _write(project / GITATTR, project_a)
    out, prompts = _upgrade(bs, monkeypatch, capsys, project, yes=False, answers=["n"])
    assert len(prompts) == 1 and "Apply this change?" in prompts[0]
    assert (project / GITATTR).read_bytes() == project_a
    assert any(
        ln.strip().startswith(("+# BEGIN", "-# BEGIN")) for ln in out.splitlines()
    )
    assert RENORMALIZE not in out
    out, prompts = _upgrade(bs, monkeypatch, capsys, project, yes=False, answers=["y"])
    assert (project / GITATTR).read_bytes() == _block(hub) + b"\n" + project_a
    assert RENORMALIZE in out


# @covers FR-0020:AC-5
def test_upgrade_runs_no_git_command(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-ga-nogit", register_stack="none")
    _write(project / GITATTR, _fixture("project-a-shape.gitattributes"))
    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy(cmd, *a, **k):
        calls.append(
            [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        )
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(bs.subprocess, "run", spy)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert RENORMALIZE in out
    assert not [c for c in calls if Path(c[0]).name.lower().startswith("git")]


# ---------------------------------------------------------------------------
# AC-6: idempotence over every fixture
# ---------------------------------------------------------------------------


def _fx_pytest_custom(hub):
    p = _create(bs, hub, "fx6-pyini", register_stack="none")
    _write(
        p / PYTEST_INI,
        (hub.template / PYTEST_INI).read_bytes()
        + _fixture("pytest-project-section.ini"),
    )
    return p


def _fx_pytest_absent(hub):
    p = _create(bs, hub, "fx6-pyini-absent", register_stack="none")
    (p / PYTEST_INI).unlink()
    return p


def _fx_python(hub):
    return _create(bs, hub, "fx6-py", "python", register_stack="python")


def _fx_node(hub):
    return _create(bs, hub, "fx6-node", "node", register_stack="node")


def _fx_python_template_changed(hub):
    p = _create(bs, hub, "fx6-py-chg", "python", register_stack="python")
    _write(
        hub.template / WORKFLOW, b"# changed\n" + (hub.template / WORKFLOW).read_bytes()
    )
    return p


def _fx_unregistered(hub):
    return _create(bs, hub, "fx6-unreg", "python")


def _fx_ga_absent(hub):
    p = _create(bs, hub, "fx6-ga-absent", register_stack="none")
    (p / GITATTR).unlink()
    return p


def _fx_project_a(hub):
    p = _create(bs, hub, "fx6-project-a", register_stack="none")
    _write(p / GITATTR, _fixture("project-a-shape.gitattributes"))
    return p


def _fx_stale(hub):
    p = _create(bs, hub, "fx6-stale", register_stack="none")
    _write(
        p / GITATTR,
        bs.GITATTRIBUTES_BLOCK_BEGIN
        + "*.png binary\n"
        + bs.GITATTRIBUTES_BLOCK_END
        + "*.pptx -text\n",
    )
    return p


def _fx_one_marker(hub):
    p = _create(bs, hub, "fx6-onemarker", register_stack="none")
    _write(p / GITATTR, bs.GITATTRIBUTES_BLOCK_BEGIN + "*.pptx -text\n")
    return p


def _fx_phipa(hub):
    return _create(bs, hub, "fx6-phipa", profile=["phipa"], register_stack="none")


AC6_FIXTURES = {
    "pytest-custom": _fx_pytest_custom,
    "pytest-absent": _fx_pytest_absent,
    "python": _fx_python,
    "node": _fx_node,
    "python-template-changed": _fx_python_template_changed,
    "unregistered": _fx_unregistered,
    "gitattributes-absent": _fx_ga_absent,
    "project-a-shape": _fx_project_a,
    "stale-block": _fx_stale,
    "one-marker": _fx_one_marker,
    "phipa": _fx_phipa,
}


@pytest.mark.parametrize("fx", sorted(AC6_FIXTURES))
# @covers FR-0020:AC-6
def test_second_yes_upgrade_changes_no_byte_and_reports_up_to_date(
    hub, monkeypatch, capsys, fx
):
    project = AC6_FIXTURES[fx](hub)
    out1, _ = _upgrade(bs, monkeypatch, capsys, project)
    snap = _tree(project)
    out2, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert _tree(project) == snap
    assert (
        UP_TO_DATE in out2.splitlines()[-3:] or f"  {UP_TO_DATE}" in out2.splitlines()
    )
    lines2 = out2.splitlines()
    assert not [ln for ln in lines2 if ln.startswith(("    ~ ", "    + "))]
    assert RENORMALIZE not in out2
    # Only seed-only drift lines remain, and they are the same as run one's.
    drift1 = [ln for ln in out1.splitlines() if "NOT changed (drift" in ln]
    drift2 = [ln for ln in lines2 if "NOT changed (drift" in ln]
    assert drift2 == drift1


# @covers FR-0020:AC-6
def test_third_run_after_template_change_is_still_stable(hub, monkeypatch, capsys):
    """Adversarial: idempotence must hold after a *delivered* change too."""
    project = _fx_project_a(hub)
    _upgrade(bs, monkeypatch, capsys, project)
    _write(
        hub.template / GITATTR,
        _block(hub).replace(b"*.zip binary\n", b"*.zip binary\n*.7z binary\n"),
    )
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert f"    ~ {GITATTR}" in out.splitlines()
    assert (project / GITATTR).read_bytes() == _block(hub) + b"\n" + _fixture(
        "project-a-shape.gitattributes"
    )
    snap = _tree(project)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert _tree(project) == snap and UP_TO_DATE in out


# ---------------------------------------------------------------------------
# AC-7: existing behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stack,profile", [("none", []), ("python", []), ("node", []), ("none", ["phipa"])]
)
# @covers FR-0020:AC-7
def test_create_output_is_byte_identical_between_base_and_fr(
    pinned, tmp_path, monkeypatch, capsys, stack, profile
):
    trees = {}
    for tag in ("base", "fr"):
        mod = pinned[tag]
        h = _build_hub(tmp_path / tag / "hub")
        _patch(mod, h, monkeypatch)
        project = _create(mod, h, "fx-create", stack, profile)
        trees[tag] = _tree(project)
    assert trees["fr"] == trees["base"]
    assert trees["fr"][GITATTR] == (REAL_TEMPLATE / GITATTR).read_bytes()


# @covers FR-0020:AC-7
def test_only_owned_files_changed_between_pinned_commits():
    _reachable(BASE_REF, FR_REF)
    proc = _git("diff", "--name-only", BASE_REF, FR_REF)
    assert proc.returncode == 0
    assert set(proc.stdout.decode("utf-8").split()) == {
        "scripts/bootstrap.py",
        "template/.gitattributes",
    }


# @covers FR-0020:AC-7
def test_upgrade_exclude_is_neither_used_nor_removed(pinned):
    base_src = _git_show(BASE_REF, "scripts/bootstrap.py")
    fr_src = _git_show(FR_REF, "scripts/bootstrap.py")
    assert base_src is not None and fr_src is not None
    assert pinned["fr"].UPGRADE_EXCLUDE == pinned["base"].UPGRADE_EXCLUDE
    # Same mentions (definition + its comments) at both commits: not newly used.
    assert fr_src.count(b"UPGRADE_EXCLUDE") == base_src.count(b"UPGRADE_EXCLUDE")
    assert re.search(rb"^UPGRADE_EXCLUDE = ", fr_src, re.MULTILINE)


# @covers FR-0020:AC-7
def test_profiled_project_hook_and_settings_survive_and_cli_exits_zero(
    hub, monkeypatch, capsys
):
    project = _create(bs, hub, "fx-phipa", profile=["phipa"], register_stack="none")
    hook = (project / HOOK_REL).read_bytes()
    settings = (project / SETTINGS).read_bytes()
    assert hook == (hub.profiles / "phipa/phi_regex_check.py").read_bytes()
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("prompted"))
    monkeypatch.setattr(
        sys, "argv", ["bootstrap.py", "--upgrade", str(project), "--yes"]
    )
    try:
        bs.main()
    except SystemExit as exc:  # pragma: no cover - only a non-zero exit fails
        assert exc.code in (0, None)
    out = capsys.readouterr()
    text = out.out + out.err
    assert "Profiles: phipa" in text
    assert UP_TO_DATE in text
    assert (project / HOOK_REL).read_bytes() == hook
    assert (project / SETTINGS).read_bytes() == settings


# ---------------------------------------------------------------------------
# Bite checks: AC-1, AC-2 and AC-5 scenarios fail against the base
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ac", sorted(SCENARIOS))
# @covers FR-0020:AC-1
# @covers FR-0020:AC-2
# @covers FR-0020:AC-5
def test_bite_scenarios_fail_against_base(pinned, tmp_path, monkeypatch, capsys, ac):
    h = _build_hub(tmp_path / "hub")
    _patch(pinned["base"], h, monkeypatch)
    with pytest.raises(AssertionError):
        SCENARIOS[ac](pinned["base"], h, monkeypatch, capsys)


@pytest.mark.parametrize("ac", sorted(SCENARIOS))
# @covers FR-0020:AC-1
# @covers FR-0020:AC-2
# @covers FR-0020:AC-5
def test_bite_scenarios_pass_against_fr_commit(
    pinned, tmp_path, monkeypatch, capsys, ac
):
    h = _build_hub(tmp_path / "hub")
    _patch(pinned["fr"], h, monkeypatch)
    SCENARIOS[ac](pinned["fr"], h, monkeypatch, capsys)


# ---------------------------------------------------------------------------
# Round 2: K1 probes beyond round 1 (AC-5) and the K2 notice wording (AC-2)
# ---------------------------------------------------------------------------

# The round-2 fix commit. Immutable; the bite checks below diff it against
# `FR_REF`, never HEAD or the working tree.
R2_REF = "408abd7c90b4d40b403322f110ded6ad5d06236a"

_B = bs.GITATTRIBUTES_BLOCK_BEGIN
_E = bs.GITATTRIBUTES_BLOCK_END
_BOM = "﻿"


def _marker_lines(data: bytes, marker: str) -> int:
    """Count lines that *are* the marker (terminator-stripped, exact)."""
    target = marker.rstrip("\r\n").encode("utf-8")
    return sum(1 for ln in data.splitlines() if ln.rstrip(b"\r") == target)


def _exact_block_count(data: bytes) -> tuple[int, int]:
    return _marker_lines(data, _B), _marker_lines(data, _E)


def _assert_damaged_untouched(out: str, project: Path, body: bytes) -> None:
    assert (project / GITATTR).read_bytes() == body
    assert out.splitlines().count(_drift_line(GITATTR)) == 1
    assert RENORMALIZE not in out
    assert f"    ~ {GITATTR}" not in out.splitlines()


@pytest.mark.parametrize(
    "case",
    [
        "begin-trailing-space",
        "end-trailing-space",
        "begin-trailing-tab-crlf",
        "bom-before-begin",
    ],
)
# @covers FR-0020:AC-5
def test_one_mangled_marker_line_is_damaged_drift_no_write(
    hub, monkeypatch, capsys, case
):
    """Ruling: a marker line with trailing whitespace or a leading BOM is *not*
    a marker (detection is exact after stripping only the line terminator).
    With the other marker intact the file has exactly one marker: damaged,
    so one drift line, bytes untouched, never a second block. Twice."""
    project = _create(bs, hub, f"fx-r2-{case}", register_stack="none")
    b, e = _B, _E
    if case == "begin-trailing-space":
        b = _B.rstrip("\n") + "  \n"
    elif case == "end-trailing-space":
        e = _E.rstrip("\n") + " \n"
    elif case == "begin-trailing-tab-crlf":
        b = _B.rstrip("\n") + "\t\r\n"
    else:
        b = _BOM + _B
    body = (b + "*.png binary\n" + e + "*.pptx -text\n").encode("utf-8")
    _write(project / GITATTR, body)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    _assert_damaged_untouched(out, project, body)
    out2, _ = _upgrade(bs, monkeypatch, capsys, project)
    _assert_damaged_untouched(out2, project, body)


# @covers FR-0020:AC-5
def test_both_markers_mangled_never_loses_a_project_byte_and_is_stable(
    hub, monkeypatch, capsys
):
    """Both marker lines carry trailing spaces, so neither is a marker and the
    file reads as marker-free (AC-5 "Present without markers"). Invariants
    that hold whether the upgrader inserts or reports drift: at most one exact
    BEGIN/END pair, every original byte kept in order at the end, and a second
    run changes nothing. (FINDINGS F6: the near-marker pair survives below.)"""
    project = _create(bs, hub, "fx-r2-both-mangled", register_stack="none")
    body = (
        _B.rstrip("\n") + " \n*.png binary\n" + _E.rstrip("\n") + " \n*.pptx -text\n"
    ).encode("utf-8")
    _write(project / GITATTR, body)
    _upgrade(bs, monkeypatch, capsys, project)
    after = (project / GITATTR).read_bytes()
    assert after.endswith(body)
    assert _exact_block_count(after) in ((0, 0), (1, 1))
    snap = _tree(project)
    _upgrade(bs, monkeypatch, capsys, project)
    assert _tree(project) == snap


# @covers FR-0020:AC-5
def test_bom_file_with_well_formed_block_keeps_its_bom_and_outside_bytes(
    hub, monkeypatch, capsys
):
    """A BOM on a *project* first line damages nothing: the block below it is
    well-formed and replaced; the BOM line is outside bytes and survives."""
    project = _create(bs, hub, "fx-r2-bom-head", register_stack="none")
    head = (_BOM + "# project head\n").encode("utf-8")
    stale = (_B + "*.png binary\n" + _E).encode("utf-8")
    tail = b"*.pptx -text\n"
    _write(project / GITATTR, head + stale + tail)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == head + _block(hub) + tail
    assert f"    ~ {GITATTR}" in out.splitlines()


@pytest.mark.parametrize("marker_eol", ["lf", "crlf"])
# @covers FR-0020:AC-5
def test_markers_among_crlf_project_lines_replace_in_place_outside_identical(
    hub, monkeypatch, capsys, marker_eol
):
    """Markers (LF or CRLF) surrounded by CRLF project lines: one block, in
    place, outside bytes byte-identical, block body LF, second run stable."""
    project = _create(bs, hub, f"fx-r2-crlf-{marker_eol}", register_stack="none")
    head = b"# head one\r\n*.bin -text\r\n\r\n"
    tail = b"\r\n*.pptx -text\r\nlast merge=union\r\n"
    stale = (_B + "* text=auto\n*.png binary\n" + _E).encode("utf-8")
    if marker_eol == "crlf":
        stale = stale.replace(b"\n", b"\r\n")
    _write(project / GITATTR, head + stale + tail)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    after = (project / GITATTR).read_bytes()
    assert after == head + _block(hub) + tail
    assert b"\r" not in after[len(head) : len(after) - len(tail)]
    assert _exact_block_count(after) == (1, 1)
    assert f"    ~ {GITATTR}" in out.splitlines()
    assert sum(RENORMALIZE in ln for ln in out.splitlines()) == 1
    snap = _tree(project)
    out2, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert _tree(project) == snap and UP_TO_DATE in out2
    assert RENORMALIZE not in out2


# @covers FR-0020:AC-5
def test_crlf_block_that_is_already_current_is_rewritten_lf_inside_only(
    hub, monkeypatch, capsys
):
    """A current block checked out CRLF (autocrlf): replace-in-place per the
    maintainer's decision. Only the block's bytes change (to LF); a second
    run is up to date."""
    project = _create(bs, hub, "fx-r2-crlf-current", register_stack="none")
    head = b"# head\r\n"
    tail = b"\r\n*.pptx -text\r\n"
    body = head + _block(hub).replace(b"\n", b"\r\n") + tail
    _write(project / GITATTR, body)
    _upgrade(bs, monkeypatch, capsys, project)
    assert (project / GITATTR).read_bytes() == head + _block(hub) + tail
    snap = _tree(project)
    out2, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert _tree(project) == snap and UP_TO_DATE in out2


# @covers FR-0020:AC-5
def test_begin_and_end_text_on_one_line_does_not_crash_or_double(
    hub, monkeypatch, capsys
):
    """BEGIN and END concatenated on one physical line: that line is neither
    marker, so the file is marker-free; no crash, at most one exact pair after,
    and every original byte kept below."""
    project = _create(bs, hub, "fx-r2-sameline", register_stack="none")
    body = (_B.rstrip("\n") + _E + "*.pptx -text\n").encode("utf-8")
    _write(project / GITATTR, body)
    _upgrade(bs, monkeypatch, capsys, project)
    after = (project / GITATTR).read_bytes()
    assert after.endswith(body)
    assert _exact_block_count(after) in ((0, 0), (1, 1))


@pytest.mark.parametrize("lines", [1, 2])
# @covers FR-0020:AC-5
def test_begin_equal_to_end_constant_is_damaged_not_a_crash(monkeypatch, lines):
    """Impossible by construction, but were the two marker constants ever
    equal, every marker line is both BEGIN and END: never 'replaced'."""
    monkeypatch.setattr(bs, "GITATTRIBUTES_BLOCK_END", bs.GITATTRIBUTES_BLOCK_BEGIN)
    text = _B * lines + "*.pptx -text\n"
    assert bs._gitattributes_merge(text, _B + "* text=auto\n" + _B) == (
        None,
        "damaged",
    )


# @covers FR-0020:AC-5
def test_empty_gitattributes_gets_the_block_and_is_stable(hub, monkeypatch, capsys):
    project = _create(bs, hub, "fx-r2-empty", register_stack="none")
    _write(project / GITATTR, b"")
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    after = (project / GITATTR).read_bytes()
    assert after == _block(hub) + b"\n"
    assert _exact_block_count(after) == (1, 1)
    assert f"    ~ {GITATTR}" in out.splitlines()
    snap = _tree(project)
    out2, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert _tree(project) == snap and UP_TO_DATE in out2


@pytest.mark.parametrize(
    "shape",
    ["lf", "crlf", "no-final-newline", "begin-only", "end-only", "end-begin"],
)
# @covers FR-0020:AC-5
def test_file_of_only_markers(hub, monkeypatch, capsys, shape):
    project = _create(bs, hub, f"fx-r2-only-{shape}", register_stack="none")
    body = {
        "lf": _B + _E,
        "crlf": (_B + _E).replace("\n", "\r\n"),
        "no-final-newline": _B + _E.rstrip("\n"),
        "begin-only": _B,
        "end-only": _E,
        "end-begin": _E + _B,
    }[shape].encode("utf-8")
    _write(project / GITATTR, body)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    if shape in ("begin-only", "end-only", "end-begin"):
        _assert_damaged_untouched(out, project, body)
    else:
        assert (project / GITATTR).read_bytes() == _block(hub)
        assert f"    ~ {GITATTR}" in out.splitlines()
    assert _exact_block_count((project / GITATTR).read_bytes())[0] <= 1


@pytest.mark.parametrize("where", ["no-markers", "middle-block", "dup-at-end"])
# @covers FR-0020:AC-5
def test_very_large_gitattributes(hub, monkeypatch, capsys, where):
    """200k project lines: correct result, no second block, bounded time."""
    project = _create(bs, hub, f"fx-r2-large-{where}", register_stack="none")
    half = "".join(f"dir{i}/*.dat -text\n" for i in range(100_000)).encode("utf-8")
    stale = (_B + "*.png binary\n" + _E).encode("utf-8")
    body = {
        "no-markers": half + half,
        "middle-block": half + stale + half,
        "dup-at-end": half + stale + half + stale,
    }[where]
    _write(project / GITATTR, body)
    t0 = time.perf_counter()
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    assert time.perf_counter() - t0 < 60
    after = (project / GITATTR).read_bytes()
    if where == "no-markers":
        assert after == _block(hub) + b"\n" + body
        assert _exact_block_count(after) == (1, 1)
    elif where == "middle-block":
        assert after == half + _block(hub) + half
        assert _exact_block_count(after) == (1, 1)
    else:
        _assert_damaged_untouched(out, project, body)


@pytest.mark.parametrize(
    "shape", ["two-blocks-crlf", "lf-block-then-crlf-block", "crlf-begin-lf-begin"]
)
# @covers FR-0020:AC-5
def test_duplicated_markers_with_mixed_line_endings_are_damaged(
    hub, monkeypatch, capsys, shape
):
    """Duplicate detection must also see CRLF copies of a marker."""
    project = _create(bs, hub, f"fx-r2-{shape}", register_stack="none")
    crlf_b, crlf_e = _B.replace("\n", "\r\n"), _E.replace("\n", "\r\n")
    body = {
        "two-blocks-crlf": crlf_b + "a -text\r\n" + crlf_e + crlf_b + crlf_e,
        "lf-block-then-crlf-block": _B + _E + "x -text\r\n" + crlf_b + crlf_e,
        "crlf-begin-lf-begin": crlf_b + _B + _E,
    }[shape].encode("utf-8")
    _write(project / GITATTR, body)
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    _assert_damaged_untouched(out, project, body)


@pytest.mark.parametrize("cause", ["unregistered", "bad-stack"])
# @covers FR-0020:AC-2
def test_k2_unresolved_stack_notice_says_left_unchanged_or_drift(
    hub, monkeypatch, capsys, cause
):
    """K2: both notice variants name both paths, say the stack is unknown, and
    say the files are left unchanged and reported as drift -- not compared
    'byte-for-byte' (which read as a promise to overwrite)."""
    project = _create(bs, hub, f"fx-r2-k2-{cause}", "python")
    if cause == "bad-stack":
        _register(hub, f"fx-r2-k2-{cause}", "rust")
    out, _ = _upgrade(bs, monkeypatch, capsys, project)
    notices = [ln for ln in out.splitlines() if "stack is unknown" in ln]
    assert len(notices) == 1
    note = notices[0]
    assert ".cursor/rules/20-<stack>.mdc" in note
    assert WORKFLOW in note
    assert "left unchanged" in note
    assert "reported as drift" in note
    assert "byte-for-byte" not in note
    if cause == "bad-stack":
        assert "'rust'" in note


@pytest.fixture(scope="module")
def r2_pinned(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ModuleType]:
    """`bootstrap.py` at FR-0020's round-1 commit and at the round-2 fix."""
    out: dict[str, ModuleType] = {}
    for tag, ref in (("fr", FR_REF), ("r2", R2_REF)):
        src = _git_show(ref, "scripts/bootstrap.py")
        if src is None:
            pytest.skip(f"{tag} {ref[:7]} not reachable")
        d = tmp_path_factory.mktemp(f"fr0020r2_{tag}")
        (d / "bootstrap.py").write_bytes(src)
        out[tag] = _load_module(f"bootstrap_fr0020r2_{tag}", d / "bootstrap.py")
    return out


# input text -> the state `_gitattributes_merge` must return at R2_REF
_K1_BITE_CASES = {
    "crlf-block": ((_B + "a -text\n" + _E).replace("\n", "\r\n"), "replaced"),
    "two-blocks": (_B + _E + "x -text\n" + _B + _E, "damaged"),
    "two-begins": (_B + _B + _E, "damaged"),
    "two-ends": (_B + _E + _E, "damaged"),
}


@pytest.mark.parametrize("case", sorted(_K1_BITE_CASES))
# @covers FR-0020:AC-5
def test_k1_bite_round1_commit_misclassifies_round2_commit_does_not(r2_pinned, case):
    """Pinned-commit bite: each K1 input was misclassified at `12996e8` and is
    classified correctly at `408abd7`. Fixed commits only."""
    text, want = _K1_BITE_CASES[case]
    block = _B + "* text=auto\n" + _E
    _, fr_state = r2_pinned["fr"]._gitattributes_merge(text, block)
    r2_text, r2_state = r2_pinned["r2"]._gitattributes_merge(text, block)
    assert fr_state != want
    assert r2_state == want
    if want == "replaced":
        assert r2_text == block


# @covers FR-0020:AC-7
def test_round2_fix_touches_only_bootstrap_py_between_pinned_commits():
    """`12996e8..408abd7` (fixed commits; reviewer files excluded) changes
    only `scripts/bootstrap.py`."""
    _reachable(FR_REF, R2_REF)
    proc = _git(
        "diff",
        "--name-only",
        FR_REF,
        R2_REF,
        "--",
        ".",
        ":!REVIEW.md",
        ":!tests/unit/scripts/test_bootstrap_upgrade.py",
        ":!tests/fixtures/bootstrap-upgrade",
    )
    assert proc.returncode == 0
    assert set(proc.stdout.decode("utf-8").split()) == {"scripts/bootstrap.py"}
