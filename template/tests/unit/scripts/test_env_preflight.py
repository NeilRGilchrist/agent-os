"""Reviewer tests for FR-0011, the module half — `env_preflight.py` in
isolation: the closed finding vocabulary (AC-1), the Docker probe and its two
failure classes (AC-2), per-tool PATH presence with `uv` through the
dispatcher's `_find_uv` fallback and `docker` reported once (AC-3), the
read-only, bounded, degrade-to-`unknown` Windows app-control read (AC-4),
compose port parsing across every fixture spelling plus a real in-process
bind collision (AC-5), the injectable-I/O and wall-clock-budget properties
AC-9 (v2) states, and the no-stack short-circuit that AC-10 rests on.

Harness: every check takes its host I/O as keyword parameters (`run=`,
`which=`, `port_busy=`, `platform=`, `find_uv=`), so these tests never
execute `docker`, `powershell` or `uv`, and bind a socket only in the two
AC-5 tests that prove the real `_port_busy` against a listener the test
opens and closes itself. Module-level names that would reach the host
(`subprocess`, `shutil`, `socket`) are booby-trapped where a test claims no
host contact happens.

Coverage annotations are written `# covers hub-tooling FR-0011:AC-N` rather
than the gate's `@covers` form on purpose (see test_dispatch_permissions.py):
this file rides along into every bootstrapped project, where no FR-0011
exists.

Every fixture here is synthetic (see tests/fixtures/README.md).
"""

from __future__ import annotations

import dataclasses
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _TEMPLATE_DIR / "scripts"
_COMPOSE_FIXTURES = _TEMPLATE_DIR / "tests" / "fixtures" / "env-preflight" / "compose"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import env_preflight as ep

_VOCAB = {
    "docker-daemon-unreachable",
    "docker-not-installed",
    "tool-missing",
    "app-control-enforced",
    "port-collision",
    "preflight-check-error",
}
_PATH_TOOLS = ("uv", "node", "npm", "npx", "pnpm", "yarn", "alembic")


# ---------------------------------------------------------------------------
# Fakes and booby traps
# ---------------------------------------------------------------------------


def _proc(returncode: int = 0, stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def _trap(name: str):
    def _boom(*a, **k):
        raise AssertionError(f"{name} must not be called: args={a!r} kwargs={k!r}")

    return _boom


def _recording_run(returncode: int = 0, stdout: str = ""):
    """A `run=` fake that records every call (argv + kwargs)."""
    calls: list[tuple[list[str], dict]] = []

    def _run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        return _proc(returncode, stdout)

    _run.calls = calls  # type: ignore[attr-defined]
    return _run


def _which_all(tool: str) -> str:
    return f"/fake/bin/{tool}"


def _which_none(tool: str) -> None:
    return None


def _write_compose(root: Path, text: str, name: str = "docker-compose.yml") -> Path:
    p = root / name
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def _classes(findings) -> list[str]:
    return [f.cls for f in findings]


@pytest.fixture(autouse=True)
def _no_host_names(monkeypatch):
    """Nothing in this file may reach the host through the module's global
    names. `subprocess.TimeoutExpired` stays real so the fakes can raise it;
    everything else on those modules explodes on touch."""
    monkeypatch.delenv("DISPATCH_STACK_TOOLS", raising=False)
    monkeypatch.setattr(
        ep,
        "subprocess",
        SimpleNamespace(
            run=_trap("subprocess.run"), TimeoutExpired=subprocess.TimeoutExpired
        ),
    )
    monkeypatch.setattr(ep, "shutil", SimpleNamespace(which=_trap("shutil.which")))


@pytest.fixture
def real_socket(monkeypatch):
    """The two real-bind tests opt back in to the socket module."""
    monkeypatch.setattr(ep, "socket", socket)


@pytest.fixture(autouse=True)
def _trap_socket(monkeypatch, request):
    if "real_socket" not in request.fixturenames:
        monkeypatch.setattr(
            ep, "socket", SimpleNamespace(socket=_trap("socket.socket"))
        )


# ---------------------------------------------------------------------------
# AC-1: typed findings, closed vocabulary
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-1
def test_vocabulary_is_exactly_the_six_classes_and_two_severities_and_shared():
    assert set(ep.FINDING_CLASSES) == _VOCAB
    assert isinstance(ep.FINDING_CLASSES, frozenset)
    assert set(ep.SEVERITIES) == {"block", "warn"}
    # Every class in the set is constructible with either severity...
    for cls in _VOCAB:
        for sev in ("block", "warn"):
            f = ep.Finding(cls=cls, resource="r", severity=sev, remedy="do x")
            assert (f.cls, f.resource, f.severity, f.remedy) == (cls, "r", sev, "do x")
    # ...and the structure has exactly the four AC-1 fields, no free-text slot.
    assert [fld.name for fld in dataclasses.fields(ep.Finding)] == [
        "cls",
        "resource",
        "severity",
        "remedy",
    ]


# covers hub-tooling FR-0011:AC-1
@pytest.mark.parametrize(
    "cls",
    [
        "docker-down",
        "Docker-Not-Installed",
        "tool-missing ",
        "",
        None,
        "port-collision; rm -rf",
        "preflight-check-error\n",
        123,
    ],
)
def test_unknown_class_cannot_be_constructed(cls):
    """Adversarial: near-misses (case, whitespace, punctuation, empty, None,
    wrong type) are all outside the closed set and must raise, not coerce."""
    with pytest.raises(ValueError):
        ep.Finding(cls=cls, resource="r", severity="warn", remedy="x")


# covers hub-tooling FR-0011:AC-1
def test_no_finding_without_a_class_and_no_severity_outside_block_warn():
    with pytest.raises(TypeError):
        ep.Finding(resource="r", severity="warn", remedy="x")  # type: ignore[call-arg]
    for sev in ("error", "BLOCK", "info", "", None):
        with pytest.raises(ValueError):
            ep.Finding(cls="tool-missing", resource="r", severity=sev, remedy="x")
    # Frozen: a constructed finding cannot be re-classed after the fact, and a
    # `dataclasses.replace` re-runs the vocabulary check.
    f = ep.Finding(cls="tool-missing", resource="node", severity="warn", remedy="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.cls = "free text"  # type: ignore[misc]
    with pytest.raises(ValueError):
        dataclasses.replace(f, cls="free text")


# covers hub-tooling FR-0011:AC-1
def test_every_finding_any_check_emits_is_in_the_vocabulary(tmp_path):
    """Run every check through every failure branch with fakes and assert the
    union of emitted classes is a subset of the constant — the dispatcher and
    these tests share one definition."""
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5555:5432"]\n')
    _write_compose(tmp_path, "services: [\n", name="compose.yaml")
    emitted: set[str] = set()
    emitted.update(
        _classes(ep.check_docker(["docker"], which=_which_none, run=_trap("run")))
    )
    emitted.update(
        _classes(ep.check_docker(["docker"], which=_which_all, run=_recording_run(1)))
    )
    emitted.update(
        _classes(
            ep.check_tool_presence(
                list(_PATH_TOOLS), which=_which_none, find_uv=lambda: None
            )
        )
    )
    emitted.update(
        _classes(
            ep.check_app_control(
                platform="win32", run=_recording_run(0, '{"sac":3,"wdac":0}')
            )
        )
    )
    emitted.update(
        _classes(ep.check_app_control(platform="win32", run=_recording_run(1)))
    )
    port_findings, _ = ep.check_ports(tmp_path, ["docker"], port_busy=lambda p: True)
    emitted.update(_classes(port_findings))

    def _raise(*a, **k):
        raise RuntimeError("synthetic")

    emitted.update(
        _classes(
            ep.run_preflight(
                tmp_path,
                ["docker"],
                run=_raise,
                which=_which_all,
                port_busy=_raise,
                platform="linux",
            ).findings
        )
    )
    assert emitted == _VOCAB
    assert emitted <= ep.FINDING_CLASSES


# ---------------------------------------------------------------------------
# AC-2: Docker — only when declared; two failure modes distinguished
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-2
def test_docker_absent_from_path_is_one_not_installed_block_and_no_subprocess():
    findings = ep.check_docker(
        ["docker", "python"], which=_which_none, run=_trap("run")
    )
    assert len(findings) == 1
    f = findings[0]
    assert (f.cls, f.resource, f.severity) == (
        "docker-not-installed",
        "docker",
        "block",
    )
    assert f.remedy.strip()


# covers hub-tooling FR-0011:AC-2
@pytest.mark.parametrize(
    "failure",
    ["rc1", "rc125", "oserror", "timeout"],
)
def test_docker_present_but_daemon_unreachable_is_one_block_of_that_class(failure):
    """Present on PATH but the probe fails — any way it can — is exactly one
    `docker-daemon-unreachable`, never `docker-not-installed`, never two."""
    if failure == "rc1":
        run = _recording_run(1)
    elif failure == "rc125":
        run = _recording_run(125)
    elif failure == "oserror":

        def run(argv, **kw):
            raise PermissionError("synthetic")

    else:

        def run(argv, **kw):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 0))

    findings = ep.check_docker(["docker"], which=_which_all, run=run)
    assert [(f.cls, f.resource, f.severity) for f in findings] == [
        ("docker-daemon-unreachable", "docker", "block")
    ]


# covers hub-tooling FR-0011:AC-2
def test_docker_reachable_yields_nothing_and_the_probe_is_single_read_only_and_bounded():
    run = _recording_run(0, "27.0.1\n")
    assert ep.check_docker(["docker"], which=_which_all, run=run, timeout=1.5) == []
    assert len(run.calls) == 1
    argv, kwargs = run.calls[0]
    assert argv[0] == "/fake/bin/docker" and argv[1] == "info"
    # Read-only: an informational subcommand, no `start`/`compose up`/`pull`.
    assert not {"start", "up", "pull", "run", "restart"} & set(argv)
    assert kwargs.get("timeout") == 1.5 and kwargs.get("check") is False


# covers hub-tooling FR-0011:AC-2
@pytest.mark.parametrize(
    "tools", [[], ["python", "uv"], ["node", "npm", "npx"], ["Docker"], ["dockerd"]]
)
def test_docker_not_declared_means_no_probe_at_all(tools):
    """Adversarial: near-miss ids (`Docker`, `dockerd`) are not `docker`;
    neither `which` nor `run` may be consulted and there is no finding."""
    assert ep.check_docker(tools, which=_trap("which"), run=_trap("run")) == []


# ---------------------------------------------------------------------------
# AC-3: every other declared tool resolved on PATH
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-3
def test_each_declared_path_tool_missing_yields_one_tool_missing_naming_it_and_its_marker():
    tools = list(_PATH_TOOLS) + ["python", "pip"]
    findings = ep.check_tool_presence(tools, which=_which_none, find_uv=lambda: None)
    assert [f.cls for f in findings] == ["tool-missing"] * len(_PATH_TOOLS)
    assert [f.resource for f in findings] == list(_PATH_TOOLS)
    expected_marker = {
        "uv": "uv.lock",
        "node": "package.json",
        "npm": "package.json",
        "npx": "package.json",
        "pnpm": "pnpm-lock.yaml",
        "yarn": "yarn.lock",
        "alembic": "alembic.ini",
    }
    for f in findings:
        # The remedy names how the project declares the tool (its marker) and
        # points at FR-0010 AC-2 for the ADR / env channels.
        assert expected_marker[f.resource] in f.remedy and "FR-0010 AC-2" in f.remedy
        assert f.severity == ("block" if f.resource == "uv" else "warn")
    # `python` / `pip` are not executables this AC checks: no finding for them.
    assert "python" not in [f.resource for f in findings]


# covers hub-tooling FR-0011:AC-3
def test_only_declared_tools_are_checked_and_present_ones_are_silent():
    seen: list[str] = []

    def which(tool):
        seen.append(tool)
        return None if tool == "yarn" else f"/bin/{tool}"

    findings = ep.check_tool_presence(
        ["node", "yarn", "docker"], which=which, find_uv=_trap("find_uv")
    )
    assert sorted(seen) == ["node", "yarn"]  # never `docker`, never undeclared tools
    assert [(f.cls, f.resource, f.severity) for f in findings] == [
        ("tool-missing", "yarn", "warn")
    ]


# covers hub-tooling FR-0011:AC-3
def test_uv_resolves_through_the_find_uv_fallback_not_bare_which():
    """A `~/.local/bin` install: `which` says missing, the dispatcher's
    fallback finds it — not reported. And the reverse: the fallback is what
    decides, so `which` finding `uv` is irrelevant when `find_uv` says no."""
    assert (
        ep.check_tool_presence(
            ["uv"], which=_which_none, find_uv=lambda: "/home/x/.local/bin/uv"
        )
        == []
    )
    calls: list[str] = []

    def which(tool):
        calls.append(tool)
        return _which_all(tool)

    findings = ep.check_tool_presence(["uv", "node"], which=which, find_uv=lambda: None)
    assert calls == ["node"]  # `uv` never went through `which`
    assert [(f.cls, f.resource, f.severity) for f in findings] == [
        ("tool-missing", "uv", "block")
    ]
    # The standalone default mirrors `dispatch._find_uv` (PATH, then ~/.local/bin).
    assert {"which", "home"} <= set(ep._default_find_uv.__code__.co_names)


# covers hub-tooling FR-0011:AC-3
def test_docker_absent_is_reported_exactly_once_under_ac2_class_never_tool_missing(
    tmp_path,
):
    """DEC-0006: `docker` is not in the generic PATH loop; an absent binary is
    one `docker-not-installed` from the whole pre-flight, not two findings."""
    assert "docker" not in ep.CHECKED_TOOLS
    assert set(ep.CHECKED_TOOLS) == set(_PATH_TOOLS)
    assert (
        ep.check_tool_presence(["docker"], which=_which_none, find_uv=lambda: None)
        == []
    )
    _write_compose(tmp_path, "services: {}\n")
    result = ep.run_preflight(
        tmp_path,
        ["docker", "node"],
        which=_which_none,
        run=_trap("run"),
        port_busy=_trap("port_busy"),
        platform="linux",
        find_uv=lambda: None,
    )
    docker_findings = [f for f in result.findings if f.resource == "docker"]
    assert [(f.cls, f.severity) for f in docker_findings] == [
        ("docker-not-installed", "block")
    ]
    assert [f.cls for f in result.findings].count("tool-missing") == 1  # node only


# ---------------------------------------------------------------------------
# AC-4: Windows application-control state — read, never assumed
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-4
@pytest.mark.parametrize(
    ("payload", "expect_enforced", "names"),
    [
        ('{"sac":2,"wdac":0}', True, ["Smart App Control"]),
        ('{"sac":0,"wdac":2}', True, ["WDAC/Device Guard"]),
        ('{"sac":3,"wdac":2}', True, ["Smart App Control", "WDAC/Device Guard"]),
        ('{"sac":0,"wdac":1}', False, []),  # audit mode is not enforcing
        ('{"sac":1,"wdac":0}', False, []),  # SAC evaluation mode is not enforcing
        ('{"sac":null,"wdac":null}', False, []),
        ('{"sac":"2","wdac":"2"}', False, []),  # strings are not policy states
        ('{"sac":true,"wdac":true}', False, []),  # bools are not >= 2
    ],
)
def test_app_control_reads_both_signals_and_names_the_observed_policy(
    payload, expect_enforced, names
):
    run = _recording_run(0, payload)
    findings = ep.check_app_control(platform="win32", run=run, timeout=3.0)
    if not expect_enforced:
        assert findings == []
        return
    [f] = findings
    assert (f.cls, f.severity) == ("app-control-enforced", "warn")
    assert f.resource
    for n in names:
        assert n in f.remedy
    # The consequence and the FR-0012 FINDINGS rule are named in the remedy.
    assert "import" in f.remedy and "FR-0012" in f.remedy


# covers hub-tooling FR-0011:AC-4
def test_app_control_query_is_read_only_bounded_and_single():
    run = _recording_run(0, '{"sac":0,"wdac":0}')
    ep.check_app_control(platform="win32", run=run, timeout=2.5)
    assert len(run.calls) == 1
    argv, kwargs = run.calls[0]
    assert kwargs.get("timeout") == 2.5 and kwargs.get("check") is False
    assert argv[0].lower().startswith("powershell") and "-NonInteractive" in argv
    script = argv[-1]
    # Read-only: a Get-* / registry read, no Set-*, no policy mutation.
    assert "Get-ItemProperty" in script and "Get-CimInstance" in script
    assert "Set-" not in script and "Remove-" not in script and "New-" not in script
    assert "ConvertTo-Json" in script


# covers hub-tooling FR-0011:AC-4
@pytest.mark.parametrize(
    "failure", ["timeout", "oserror", "rc1", "empty", "garbage", "not-an-object"]
)
def test_app_control_query_failure_degrades_to_one_check_error_never_raises(failure):
    """Adversarial: a hanging/raising/non-zero/empty/non-JSON reader yields
    exactly one `preflight-check-error` (warn) — never an exception and never
    a silent "not enforced"."""
    if failure == "timeout":

        def run(argv, **kw):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 0))

    elif failure == "oserror":

        def run(argv, **kw):
            raise FileNotFoundError("powershell")

    elif failure == "rc1":
        run = _recording_run(1, '{"sac":2,"wdac":2}')
    elif failure == "empty":
        run = _recording_run(0, "   \n")
    elif failure == "garbage":
        run = _recording_run(0, "not json {")
    else:
        run = _recording_run(0, "[2, 2]")
    findings = ep.check_app_control(platform="win32", run=run)
    assert [(f.cls, f.severity) for f in findings] == [
        ("preflight-check-error", "warn")
    ]
    assert findings[0].resource


# covers hub-tooling FR-0011:AC-4
def test_app_control_reader_raising_anything_else_degrades_through_run_preflight(
    tmp_path,
):
    def run(argv, **kw):
        raise RuntimeError("synthetic reader crash")

    result = ep.run_preflight(
        tmp_path, ["python"], run=run, which=_trap("which"), platform="win32"
    )
    assert [(f.cls, f.severity, f.resource) for f in result.findings] == [
        ("preflight-check-error", "warn", "app-control")
    ]


# covers hub-tooling FR-0011:AC-4
@pytest.mark.parametrize(
    "platform", ["linux", "darwin", "cygwin", "win32 ", "Windows", ""]
)
def test_app_control_never_runs_off_windows(platform):
    assert ep.check_app_control(platform=platform, run=_trap("run")) == []


# covers hub-tooling FR-0011:AC-4
def test_app_control_is_gated_on_a_declared_stack_and_runs_for_any_stack(tmp_path):
    """DEC-0006: an empty stack never queries (AC-10 wins); any non-empty
    stack — even one with no PATH tool of its own — does, on Windows only."""
    assert ep.run_preflight(
        tmp_path, [], run=_trap("run"), which=_trap("which"), platform="win32"
    ) == (ep.PreflightResult())
    run = _recording_run(0, '{"sac":0,"wdac":2}')
    result = ep.run_preflight(
        tmp_path, ["pip"], run=run, which=_trap("which"), platform="win32"
    )
    assert len(run.calls) == 1 and result.checks_ran == ("app-control",)
    assert [f.cls for f in result.findings] == ["app-control-enforced"]
    assert (
        ep.run_preflight(
            tmp_path, ["pip"], run=_trap("run"), which=_trap("which"), platform="linux"
        )
        == ep.PreflightResult()
    )


# ---------------------------------------------------------------------------
# AC-5: host port collisions against the ports compose publishes
# ---------------------------------------------------------------------------


def _ports_from_fixture(name: str, tmp_path: Path, port_busy, env: dict | None = None):
    src = _COMPOSE_FIXTURES / name
    assert src.is_file(), src
    (tmp_path / "docker-compose.yml").write_bytes(src.read_bytes())
    return ep.check_ports(tmp_path, ["docker"], port_busy=port_busy)


# covers hub-tooling FR-0011:AC-5
@pytest.mark.parametrize(
    ("fixture", "expected_port"),
    [
        ("long-form.yml", 5433),
        ("short-form.yml", 5434),
        ("short-form-env-default.yml", 5435),
    ],
)
def test_three_port_spellings_are_parsed_and_a_busy_port_is_one_warn_collision(
    fixture, expected_port, tmp_path, monkeypatch
):
    monkeypatch.delenv("DB_PORT", raising=False)
    probed: list[int] = []

    def busy(port):
        probed.append(port)
        return True

    findings, unresolved = _ports_from_fixture(fixture, tmp_path, busy)
    assert probed == [expected_port] and unresolved == []
    [f] = findings
    assert (f.cls, f.resource, f.severity) == (
        "port-collision",
        str(expected_port),
        "warn",
    )
    assert "docker-compose.yml" in f.remedy and "'db'" in f.remedy
    # A free port is no finding at all.
    assert _ports_from_fixture(fixture, tmp_path, lambda p: False) == ([], [])


# covers hub-tooling FR-0011:AC-5
def test_env_default_is_overridden_by_a_set_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PORT", "6543")
    probed: list[int] = []
    _ports_from_fixture(
        "short-form-env-default.yml", tmp_path, lambda p: probed.append(p) or False
    )
    assert probed == [6543]
    # A set-but-not-a-port value is skipped and surfaced, never guessed.
    monkeypatch.setenv("DB_PORT", "not-a-port")
    findings, unresolved = _ports_from_fixture(
        "short-form-env-default.yml", tmp_path, _trap("busy")
    )
    assert findings == [] and unresolved == ["db:${DB_PORT:-5435}"]


# covers hub-tooling FR-0011:AC-5
def test_no_published_ports_probes_nothing(tmp_path):
    assert _ports_from_fixture("no-published-ports.yml", tmp_path, _trap("busy")) == (
        [],
        [],
    )


# covers hub-tooling FR-0011:AC-5
def test_unresolved_env_var_without_default_is_skipped_and_listed_not_guessed(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DB_PORT_NO_DEFAULT", raising=False)
    findings, unresolved = _ports_from_fixture(
        "unresolved-env-var.yml", tmp_path, _trap("busy")
    )
    assert findings == [] and unresolved == ["db:${DB_PORT_NO_DEFAULT}"]


# covers hub-tooling FR-0011:AC-5
@pytest.mark.parametrize(
    "text",
    [
        None,  # the malformed.yml fixture
        "- a\n- b\n",  # top-level list
        "services: [a, b]\n",  # services not a mapping
        "services:\n  db:\n    ports: !!python/object:os.system {}\n",  # unsafe tag
        "\x00\x01binary",
    ],
)
def test_malformed_compose_is_one_check_error_and_no_port_findings_not_a_crash(
    text, tmp_path
):
    if text is None:
        (tmp_path / "docker-compose.yml").write_bytes(
            (_COMPOSE_FIXTURES / "malformed.yml").read_bytes()
        )
    else:
        _write_compose(tmp_path, text)
    findings, unresolved = ep.check_ports(tmp_path, ["docker"], port_busy=_trap("busy"))
    assert [(f.cls, f.resource, f.severity) for f in findings] == [
        ("preflight-check-error", "docker-compose.yml", "warn")
    ]
    assert unresolved == []


# covers hub-tooling FR-0011:AC-5
def test_a_malformed_file_does_not_stop_the_other_compose_files(tmp_path):
    """Adversarial: every compose spelling in the root is read; one bad file
    costs one error finding and the good ones are still probed."""
    _write_compose(tmp_path, "services: [\n", name="docker-compose.yml")
    _write_compose(
        tmp_path,
        'services:\n  a:\n    ports: ["7001:80"]\n',
        name="docker-compose.override.yaml",
    )
    _write_compose(
        tmp_path,
        "services:\n  b:\n    ports:\n      - published: 7002\n        target: 80\n",
        name="compose.yml",
    )
    _write_compose(
        tmp_path, 'services:\n  c:\n    ports: ["7003:80"]\n', name="not-compose.yml"
    )
    (tmp_path / "compose.yaml").mkdir()  # a directory with a compose name is not a file
    probed: list[int] = []
    findings, _ = ep.check_ports(
        tmp_path, ["docker"], port_busy=lambda p: probed.append(p) or (p == 7002)
    )
    assert sorted(probed) == [7001, 7002]
    assert sorted((f.cls, f.resource) for f in findings) == [
        ("port-collision", "7002"),
        ("preflight-check-error", "docker-compose.yml"),
    ]
    assert (
        "compose.yml" in next(f for f in findings if f.cls == "port-collision").remedy
    )


# covers hub-tooling FR-0011:AC-5
def test_mixed_entries_dedupe_per_port_and_skip_container_only_shapes(tmp_path):
    _write_compose(
        tmp_path,
        "services:\n"
        "  db:\n"
        "    ports:\n"
        '      - "5440:5432"\n'
        '      - "5440:5433"\n'  # same host port twice -> one probe
        "      - target: 5432\n"  # long form, no `published` -> container-only
        '      - "5441:5432/udp"\n'
        "  cache:\n"
        "    ports:\n"
        '      - "${CACHE_PORT:-5442}:6379"\n'
        "  plain: not-a-mapping\n",
    )
    probed: list[int] = []
    findings, unresolved = ep.check_ports(
        tmp_path, ["docker"], port_busy=lambda p: probed.append(p) or (p == 5442)
    )
    assert probed == [5440, 5441, 5442] and unresolved == []
    assert [(f.cls, f.resource) for f in findings] == [("port-collision", "5442")]
    assert "'cache'" in findings[0].remedy


# covers hub-tooling FR-0011:AC-5
def test_bare_container_port_publishes_no_known_host_port_and_is_not_probed(tmp_path):
    """Adversarial: the compose short syntax `[HOST:]CONTAINER` — a bare
    `"3000"` is a *container* port published to an ephemeral host port, so
    there is no host port to check. Probing 3000 would be a guessed port,
    which the FR's Open-question default forbids ("guessing a port produces
    false collisions")."""
    probed: list[int] = []
    findings, _unresolved = _ports_from_fixture(
        "bare-container-port.yml", tmp_path, lambda p: probed.append(p) or True
    )
    assert probed == [] and findings == []


# covers hub-tooling FR-0011:AC-5
def test_ports_are_not_checked_when_docker_is_not_declared(tmp_path):
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5450:5432"]\n')
    assert ep.check_ports(tmp_path, ["python", "node"], port_busy=_trap("busy")) == (
        [],
        [],
    )
    assert ep.check_ports(tmp_path, [], port_busy=_trap("busy")) == ([], [])


# covers hub-tooling FR-0011:AC-5
def test_real_bind_probe_detects_a_wildcard_listener_and_releases_after(
    real_socket, tmp_path
):
    """The real `_port_busy` against a listener this test opens on all
    interfaces and closes again; no state survives the probe."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("0.0.0.0", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        _write_compose(tmp_path, f'services:\n  db:\n    ports: ["{port}:5432"]\n')
        findings, _ = ep.check_ports(tmp_path, ["docker"])
        assert [(f.cls, f.resource, f.severity) for f in findings] == [
            ("port-collision", str(port), "warn")
        ]
    finally:
        listener.close()
    assert ep._port_busy(port) is False
    assert ep.check_ports(tmp_path, ["docker"]) == ([], [])
    # The probe socket itself is closed: we can bind the port ourselves now.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
    finally:
        s.close()


# covers hub-tooling FR-0011:AC-5
def test_real_bind_probe_detects_a_loopback_only_listener(real_socket, tmp_path):
    """Adversarial: "anything already listening on the host ports the compose
    file publishes" (FR What) includes a service bound to 127.0.0.1 only —
    the default `listen_addresses = 'localhost'` of a natively installed
    Postgres, the ambient collision FR-0011's L21 evidence describes. A
    wildcard `bind` that succeeds beside a loopback listener (Windows allows
    it without SO_EXCLUSIVEADDRUSE) is a false "free"."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert ep._port_busy(port) is True
        _write_compose(tmp_path, f'services:\n  db:\n    ports: ["{port}:5432"]\n')
        findings, _ = ep.check_ports(tmp_path, ["docker"])
        assert [(f.cls, f.resource) for f in findings] == [
            ("port-collision", str(port))
        ]
    finally:
        listener.close()
    assert ep._port_busy(port) is False


# covers hub-tooling FR-0011:AC-5
@pytest.mark.parametrize(
    "entry",
    [
        '"3000"',
        "3000",
        '"3000/udp"',
        '"3000/tcp"',
        '"${PF_R2_UNSET}"',
        '"${PF_R2_UNSET:-3000}"',
        '"${PF_R2_SET}"',
    ],
)
def test_short_form_entries_without_a_container_part_are_neither_probed_nor_listed(
    entry, tmp_path, monkeypatch
):
    """Round 2: every short-form spelling that lacks a `:CONTAINER` part is
    Compose's container-port shorthand — with or without a `/PROTO` suffix,
    as a YAML integer, or as an env token (which then names the *container*
    port, set or not). None publishes a known host port: nothing is probed,
    no finding, and nothing to list as unresolved either (there is no host
    port to resolve). The `"3001:3000/udp"` sibling is the control: an entry
    with a `:CONTAINER` part is still probed."""
    monkeypatch.delenv("PF_R2_UNSET", raising=False)
    monkeypatch.setenv("PF_R2_SET", "3000")
    _write_compose(
        tmp_path,
        f'services:\n  web:\n    ports:\n      - {entry}\n      - "3001:3000/udp"\n',
    )
    probed: list[int] = []
    findings, unresolved = ep.check_ports(
        tmp_path, ["docker"], port_busy=lambda p: probed.append(p) or True
    )
    assert probed == [3001] and unresolved == []
    assert [(f.cls, f.resource) for f in findings] == [("port-collision", "3001")]


class _FakeProbeSocket:
    """Stands in for `socket.socket` inside `_port_busy`; records the exact
    call sequence and refuses the bind on demand."""

    log: ClassVar[list] = []
    refuse: ClassVar[bool] = False

    def __init__(self, family, kind) -> None:
        self.log.append(("socket", family, kind))

    def settimeout(self, t) -> None:
        self.log.append(("settimeout", t))

    def setsockopt(self, level, opt, value) -> None:
        self.log.append(("setsockopt", level, opt, value))

    def bind(self, addr) -> None:
        self.log.append(("bind", addr))
        if self.refuse:
            raise OSError(98, "address already in use")

    def close(self) -> None:
        self.log.append(("close",))


# covers hub-tooling FR-0011:AC-5
@pytest.mark.parametrize("exposed", [True, False])
@pytest.mark.parametrize("refused", [True, False])
def test_probe_sets_the_exclusive_flag_before_bind_only_where_the_platform_exposes_it(
    exposed, refused, monkeypatch
):
    """Round 2, deterministic on any host: with `SO_EXCLUSIVEADDRUSE` on the
    socket module the probe sets it (SOL_SOCKET, flag, 1) *before* the
    wildcard bind; without it (POSIX) no option is set and a `None` flag is
    never passed through. Either way the bind is attempted exactly once, a
    refusal is "busy", success is "free", and the socket is closed last."""
    log: list = []

    class Sock(_FakeProbeSocket):
        pass

    Sock.log = log
    Sock.refuse = refused
    ns = SimpleNamespace(
        socket=Sock, AF_INET="af-inet", SOCK_STREAM="stream", SOL_SOCKET="sol"
    )
    if exposed:
        ns.SO_EXCLUSIVEADDRUSE = 0x4242
    monkeypatch.setattr(ep, "socket", ns)

    assert ep._port_busy(5470, timeout=1.5) is refused

    expected: list = [("socket", "af-inet", "stream"), ("settimeout", 1.5)]
    if exposed:
        expected.append(("setsockopt", "sol", 0x4242, 1))
    expected += [("bind", ("0.0.0.0", 5470)), ("close",)]
    assert log == expected


# covers hub-tooling FR-0011:AC-5
def test_probe_without_the_exclusive_flag_still_detects_a_wildcard_listener(
    real_socket, monkeypatch
):
    """Round 2: on a platform whose socket module lacks `SO_EXCLUSIVEADDRUSE`
    (POSIX) the probe falls back to the plain bind, which the OS refuses
    against a wildcard listener — the round-1 behaviour must survive the
    fix. The attribute is removed from the real module for this test only."""
    monkeypatch.delattr(socket, "SO_EXCLUSIVEADDRUSE", raising=False)
    assert not hasattr(ep.socket, "SO_EXCLUSIVEADDRUSE")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("0.0.0.0", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert ep._port_busy(port) is True
    finally:
        listener.close()
    assert ep._port_busy(port) is False


# ---------------------------------------------------------------------------
# AC-9 (v2): read-only, bounded, every check's I/O injectable
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-9
def test_run_preflight_uses_only_the_injected_io_and_forwards_find_uv(tmp_path):
    """With every I/O parameter injected, `run_preflight` consults nothing
    else (the module's `subprocess`/`shutil`/`socket` names are trapped by
    the autouse fixture) and its findings tell the fakes' story, not the
    host's."""
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5460:5432"]\n')
    run = _recording_run(0, '{"sac":0,"wdac":0}')
    which_calls: list[str] = []

    def which(tool):
        which_calls.append(tool)
        return f"/fake/{tool}" if tool == "docker" else None

    uv_calls: list[int] = []

    def find_uv():
        uv_calls.append(1)
        return "/home/x/.local/bin/uv"

    busy: list[int] = []
    result = ep.run_preflight(
        tmp_path,
        ["docker", "uv", "node", "python"],
        find_uv=find_uv,
        run=run,
        which=which,
        port_busy=lambda p: busy.append(p) or True,
        platform="win32",
        timeout=0.75,
    )
    assert result.checks_ran == ("docker", "tool-presence", "app-control", "ports")
    assert [(f.cls, f.resource) for f in result.findings] == [
        ("tool-missing", "node"),
        ("port-collision", "5460"),
    ]
    assert uv_calls == [1] and which_calls == ["docker", "node"] and busy == [5460]
    # Both subprocess probes carried the injected timeout.
    assert [c[1]["timeout"] for c in run.calls] == [0.75, 0.75]


# covers hub-tooling FR-0011:AC-9
def test_a_check_that_raises_becomes_one_check_error_and_the_rest_still_run(tmp_path):
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5470:5432"]\n')

    def exploding_which(tool):
        raise RuntimeError("synthetic which crash")

    result = ep.run_preflight(
        tmp_path,
        ["docker", "node"],
        run=_trap("run"),
        which=exploding_which,
        port_busy=lambda p: False,
        platform="linux",
    )
    # docker and tool-presence both crashed (each is one error, named), ports still ran.
    assert result.checks_ran == ("ports",)
    assert [(f.cls, f.resource, f.severity) for f in result.findings] == [
        ("preflight-check-error", "docker", "warn"),
        ("preflight-check-error", "tool-presence", "warn"),
    ]


# covers hub-tooling FR-0011:AC-9
def test_wall_clock_budget_bounds_the_whole_preflight_even_when_every_check_hangs(
    tmp_path, monkeypatch
):
    """Adversarial: a `run` that eats 60 "seconds" of a deterministic fake
    clock per call against a 50-second budget — the docker check runs, every
    later check is skipped with a named `preflight-check-error`, and the
    real call returns well inside a second (nothing actually waits)."""
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5480:5432"]\n')
    clock = [0.0]
    monkeypatch.setattr(ep, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def slow_run(argv, **kw):
        clock[0] += 60.0
        return _proc(1)

    started = time.monotonic()
    result = ep.run_preflight(
        tmp_path,
        ["docker", "node"],
        run=slow_run,
        which=_which_all,
        port_busy=_trap("busy"),
        platform="win32",
        budget=50.0,
    )
    assert time.monotonic() - started < 1.0
    assert result.checks_ran == ("docker",)
    assert [(f.cls, f.resource) for f in result.findings] == [
        ("docker-daemon-unreachable", "docker"),
        ("preflight-check-error", "tool-presence"),
        ("preflight-check-error", "app-control"),
        ("preflight-check-error", "ports"),
    ]
    assert all("budget" in f.remedy for f in result.findings[1:])


# covers hub-tooling FR-0011:AC-9
def test_default_bounds_are_finite_and_every_probe_carries_a_timeout():
    assert 0 < ep.DEFAULT_CHECK_TIMEOUT_S <= 60
    assert 0 < ep.DEFAULT_BUDGET_S <= 300
    run = _recording_run(0, "x")
    ep.check_docker(["docker"], which=_which_all, run=run)
    ep.check_app_control(platform="win32", run=run)
    assert all(c[1].get("timeout") == ep.DEFAULT_CHECK_TIMEOUT_S for c in run.calls)
    assert run.calls  # both probes went through the injected `run`


# covers hub-tooling FR-0011:AC-9
def test_read_only_no_check_writes_into_the_repo(tmp_path):
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5490:5432"]\n')
    (tmp_path / "compose.yaml").write_text("services: [\n", encoding="utf-8")
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    ep.run_preflight(
        tmp_path,
        ["docker", "uv", "node"],
        run=_recording_run(1),
        which=_which_none,
        port_busy=lambda p: True,
        platform="win32",
        find_uv=lambda: None,
    )
    after = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert after == before


# ---------------------------------------------------------------------------
# AC-10: no stack -> no check executes
# ---------------------------------------------------------------------------


# covers hub-tooling FR-0011:AC-10
@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("tools", [[], ()])
def test_empty_stack_runs_no_check_even_with_a_compose_file_present(
    tmp_path, platform, tools
):
    """Adversarial: a compose file that *would* publish a busy port sits in
    the root, but the detected stack is empty — nothing is read, nothing is
    probed, nothing is found."""
    _write_compose(tmp_path, 'services:\n  db:\n    ports: ["5500:5432"]\n')
    result = ep.run_preflight(
        tmp_path,
        tools,
        run=_trap("run"),
        which=_trap("which"),
        port_busy=_trap("busy"),
        find_uv=_trap("find_uv"),
        platform=platform,
    )
    assert result == ep.PreflightResult()
    assert (
        result.findings == ()
        and result.checks_ran == ()
        and result.unresolved_ports == ()
    )


# covers hub-tooling FR-0011:AC-10
def test_preflight_result_default_is_the_empty_no_checks_value():
    r = ep.PreflightResult()
    assert (r.findings, r.checks_ran, r.unresolved_ports) == ((), (), ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.findings = (
            ep.Finding(cls="tool-missing", resource="x", severity="warn", remedy="y"),
        )  # type: ignore[misc]
