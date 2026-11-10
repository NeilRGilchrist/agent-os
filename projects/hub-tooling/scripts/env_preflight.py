"""
env_preflight.py — Stack-aware, read-only environment pre-flight (FR-0011).

Four checks, each gated on the stack `stack_profile.detect_stack` reports for
the project, none of which installs, starts, stops, configures, or repairs
anything — they read host state and report:

  * AC-2 `check_docker`         — Docker daemon reachability, only when
                                   `docker` is in the detected stack.
  * AC-3 `check_tool_presence`  — every other declared tool (`uv`, `node`,
                                   `npm`, `npx`, `pnpm`, `yarn`, `alembic`)
                                   resolved on PATH. `docker`'s absence is
                                   reported by `check_docker`'s more specific
                                   `docker-not-installed` class instead of a
                                   generic `tool-missing`, so the two checks
                                   never double-report the same resource.
  * AC-4 `check_app_control`    — Windows Smart App Control / WDAC policy
                                   enforcement state, read-only and bounded.
  * AC-5 `check_ports`          — host ports every `docker-compose*.y[a]ml` /
                                   `compose.y[a]ml` in the repo root publishes,
                                   tested for a bind collision.

`run_preflight` is the orchestrator `dispatch.py` calls: it runs every check
whose stack marker is present, bounded by an overall wall-clock budget, and
never raises — an unexpected failure in any one check degrades to one
`preflight-check-error` finding rather than aborting the rest.

Every finding is a `Finding`: a closed-vocabulary `cls`, a `resource`, a
`severity` of `block` or `warn`, and a one-line `remedy`. There is no
free-text finding and no finding without a class (AC-1).

Dependency-free of `dispatch.py` itself (only `stack_profile`-shaped inputs —
a list of detected tool ids — are needed), so every function here is
importable and unit-testable without a dispatcher, a repo, or an agent.

@implements FR-0011:AC-1, FR-0011:AC-2, FR-0011:AC-3, FR-0011:AC-4,
            FR-0011:AC-5, FR-0011:AC-6, FR-0011:AC-9, FR-0011:AC-10
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# AC-1: the closed finding vocabulary
# ---------------------------------------------------------------------------

FINDING_CLASSES = frozenset(
    {
        "docker-daemon-unreachable",
        "docker-not-installed",
        "tool-missing",
        "app-control-enforced",
        "port-collision",
        "preflight-check-error",
    }
)

SEVERITIES = frozenset({"block", "warn"})


@dataclass(frozen=True)
class Finding:
    """One pre-flight finding. `cls` must be in `FINDING_CLASSES` and
    `severity` must be `block` or `warn` — constructing one with either
    outside its closed set raises `ValueError`.

    @implements FR-0011:AC-1
    """

    cls: str
    resource: str
    severity: str
    remedy: str

    def __post_init__(self) -> None:
        if self.cls not in FINDING_CLASSES:
            raise ValueError(
                f"unknown finding class {self.cls!r}; must be one of {sorted(FINDING_CLASSES)}"
            )
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"unknown severity {self.severity!r}; must be one of {sorted(SEVERITIES)}"
            )


# Bounds every subprocess/registry/socket probe carries, and the overall
# wall-clock budget `run_preflight` enforces across every check it runs.
# Overridable for a slow host or a fast test suite.
DEFAULT_CHECK_TIMEOUT_S = float(os.environ.get("DISPATCH_PREFLIGHT_TIMEOUT", "5"))
DEFAULT_BUDGET_S = float(os.environ.get("DISPATCH_PREFLIGHT_BUDGET", "20"))


# ---------------------------------------------------------------------------
# AC-2: Docker — presence and daemon reachability, two distinct classes
# ---------------------------------------------------------------------------


# @implements FR-0016:AC-1
def check_docker(
    tools: list[str] | tuple[str, ...],
    *,
    run=subprocess.run,
    which=shutil.which,
    timeout: float = DEFAULT_CHECK_TIMEOUT_S,
) -> list[Finding]:
    """A single bounded, read-only Docker daemon probe, only when `docker` is
    in the detected stack — when it is not, this returns `[]` without
    spawning a subprocess. Docker absent from PATH yields one
    `docker-not-installed` finding; present but with an unreachable daemon
    yields one `docker-daemon-unreachable`; a reachable daemon yields none.
    Both failure classes are `severity: block`.

    @implements FR-0011:AC-2
    """
    if "docker" not in tools:
        return []
    docker_path = which("docker")
    if not docker_path:
        return [
            Finding(
                cls="docker-not-installed",
                resource="docker",
                severity="block",
                remedy=(
                    "install Docker Desktop (docker is declared by a "
                    "docker-compose*.yml/compose.yml in this repo) — or, if it is "
                    "no longer needed, undeclare it (see FR-0010 AC-2 for where a "
                    "tool is declared)"
                ),
            )
        ]
    try:
        proc = run(
            [docker_path, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is None or proc.returncode != 0:
        return [
            Finding(
                cls="docker-daemon-unreachable",
                resource="docker",
                severity="block",
                remedy=(
                    "start Docker Desktop — the daemon is not responding; "
                    "pre-flight never starts it for you"
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# AC-3: every other declared tool, resolved on PATH
# ---------------------------------------------------------------------------

# `docker` is deliberately absent: AC-2 already reports its absence with a
# more specific class (`docker-not-installed`), so including it here would
# double-report the same resource under two classes for the same condition.
CHECKED_TOOLS = ("uv", "node", "npm", "npx", "pnpm", "yarn", "alembic")

_BLOCK_ON_MISSING = frozenset({"uv"})

# What to name in a `tool-missing` remedy as "how the project declares it"
# (FR-0011:AC-3) — the marker file `stack_profile.detect_stack` reads for
# that tool id. A tool declared instead through an accepted ADR's
# `stack_tools:` or `DISPATCH_STACK_TOOLS` is still named by its usual
# marker; the remedy also names the other two channels generically.
_TOOL_DECLARED_BY = {
    "uv": "uv.lock",
    "node": "package.json",
    "npm": "package.json",
    "npx": "package.json",
    "pnpm": "pnpm-lock.yaml",
    "yarn": "yarn.lock",
    "alembic": "alembic.ini",
}


def _default_find_uv() -> str | None:
    """Standalone fallback mirroring `dispatch.py`'s own `_find_uv`: PATH
    first, then the two common `~/.local/bin` install locations `uv`'s own
    installer uses. `dispatch.py` passes its real `_find_uv` in via
    `find_uv=` so the two never drift; this default only matters when the
    module is used or tested on its own."""
    found = shutil.which("uv")
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / ".local" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def check_tool_presence(
    tools: list[str] | tuple[str, ...],
    *,
    find_uv=None,
    which=shutil.which,
) -> list[Finding]:
    """One `tool-missing` finding per declared tool (from `CHECKED_TOOLS`)
    unresolved on PATH. `uv` resolution reuses the caller's `find_uv`
    fallback (`dispatch.py`'s `_find_uv`) rather than a bare `which("uv")`,
    so a `~/.local/bin` install is never reported missing. `tool-missing` is
    `severity: block` for `uv`, `warn` for the rest.

    @implements FR-0011:AC-3
    """
    finder = find_uv or _default_find_uv
    findings: list[Finding] = []
    for tool in CHECKED_TOOLS:
        if tool not in tools:
            continue
        resolved = finder() if tool == "uv" else which(tool)
        if resolved:
            continue
        severity = "block" if tool in _BLOCK_ON_MISSING else "warn"
        hint = _TOOL_DECLARED_BY[tool]
        findings.append(
            Finding(
                cls="tool-missing",
                resource=tool,
                severity=severity,
                remedy=(
                    f"install {tool} and put it on PATH (this project declares it "
                    f"via {hint} — see FR-0010 AC-2 for the other declaration channels)"
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# AC-4: Windows application-control policy state
# ---------------------------------------------------------------------------

# A bounded, read-only, single PowerShell query for both signals: Smart App
# Control's registry-exposed policy state, and WDAC/Device Guard's
# CIM-exposed enforcement status. `-ErrorAction SilentlyContinue` throughout
# so a signal this SKU/build doesn't expose comes back null rather than
# raising inside the script (which would otherwise turn into a non-zero exit
# this function has to distinguish from "enforced").
_APP_CONTROL_PS_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$sac=(Get-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\CI\\Policy' "
    "-Name VerifiedAndReputablePolicyState -ErrorAction SilentlyContinue)."
    "VerifiedAndReputablePolicyState;"
    "$dg=Get-CimInstance -Namespace root\\Microsoft\\Windows\\DeviceGuard "
    "-ClassName Win32_DeviceGuard -ErrorAction SilentlyContinue;"
    "$wdac=$dg.CodeIntegrityPolicyEnforcementStatus;"
    "[PSCustomObject]@{sac=$sac; wdac=$wdac} | ConvertTo-Json -Compress"
)


# @implements FR-0016:AC-1
def _query_windows_app_control(*, run=subprocess.run, timeout: float) -> dict | None:
    try:
        proc = run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _APP_CONTROL_PS_SCRIPT,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def check_app_control(
    *,
    platform: str = sys.platform,
    run=subprocess.run,
    timeout: float = DEFAULT_CHECK_TIMEOUT_S,
) -> list[Finding]:
    """A bounded, read-only read of Windows Smart App Control / WDAC-Device-
    Guard enforcement state. Never runs off Windows. A query that fails,
    times out, or is unavailable degrades to one `preflight-check-error`
    finding rather than raising or being silently treated as "not enforced".

    @implements FR-0011:AC-4
    """
    if platform != "win32":
        return []
    data = _query_windows_app_control(run=run, timeout=timeout)
    if data is None:
        return [
            Finding(
                cls="preflight-check-error",
                resource="app-control",
                severity="warn",
                remedy=(
                    "could not read Smart App Control / WDAC policy state within "
                    f"{timeout:g}s; check manually with `Get-MpComputerStatus` if "
                    "native-extension import failures show up later"
                ),
            )
        ]
    sac = data.get("sac")
    wdac = data.get("wdac")
    enforcing: list[str] = []
    if isinstance(sac, int) and sac >= 2:
        enforcing.append(f"Smart App Control (state={sac})")
    if isinstance(wdac, int) and wdac >= 2:
        enforcing.append(f"WDAC/Device Guard (status={wdac})")
    if not enforcing:
        return []
    return [
        Finding(
            cls="app-control-enforced",
            resource="windows-app-control",
            severity="warn",
            remedy=(
                f"{' and '.join(enforcing)} is enforcing on this host; unsigned "
                "compiled extension modules (e.g. .pyd wheels) may fail to load, "
                "which an agent will experience as a plain import error — do not "
                "let it silently swap the dependency (see FR-0012's ## FINDINGS rule)"
            ),
        )
    ]


# ---------------------------------------------------------------------------
# AC-5: host port collisions against compose's published ports
# ---------------------------------------------------------------------------

_COMPOSE_FILE_RE = re.compile(
    r"^(docker-compose.*\.ya?ml|compose\.ya?ml)$", re.IGNORECASE
)

# `${VAR}` or `${VAR:-default}` as a whole token.
_ENV_VAR_RE = re.compile(
    r"^\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}$"
)

# The short compose port syntax: `HOST[:CONTAINER][/PROTO]`, `HOST` may be a
# literal port or an `${VAR}`/`${VAR:-default}` token. A bare value with no
# `:CONTAINER` part is Compose's *container*-port shorthand — it publishes to
# an ephemeral host port, so there is no host port to check; only an entry
# with a `:CONTAINER` part names a host port.
_SHORT_PORT_RE = re.compile(
    r"^(?P<host>\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}|\d+)"
    r"(?::(?P<container>\d+))?"
    r"(?:/(?P<proto>[A-Za-z]+))?$"
)


def _compose_files(repo_root: Path) -> list[Path]:
    try:
        entries = list(repo_root.glob("*"))
    except OSError:
        return []
    return sorted(p for p in entries if p.is_file() and _COMPOSE_FILE_RE.match(p.name))


def _resolve_port_token(token: str) -> tuple[int | None, bool]:
    """`(port, resolvable)`. `resolvable=False` means "skip this port, don't
    guess" — an `${VAR}` with no default whose variable is unset (Open
    question default), or a token that isn't a port at all."""
    m = _ENV_VAR_RE.match(token)
    if m:
        name = m.group("name")
        default = m.group("default")
        value = os.environ.get(name)
        if value is None:
            if default is None:
                return (None, False)
            token = default
        else:
            token = value
    try:
        return (int(token), True)
    except (TypeError, ValueError):
        return (None, False)


def _extract_host_token(entry: object) -> str | None:
    """The host-port token of one `ports:` list entry, or `None` when the
    entry publishes no host port at all (container-only, or a shape this
    function doesn't recognise — skipped rather than guessed)."""
    if isinstance(entry, dict):
        published = entry.get("published")
        return None if published is None else str(published)
    if isinstance(entry, (int, str)):
        m = _SHORT_PORT_RE.match(str(entry))
        if not m or m.group("container") is None:
            # No `:CONTAINER` part: this is the bare container-port shorthand
            # (`"3000"`), published to an ephemeral host port, not a known
            # host port to probe.
            return None
        return m.group("host")
    return None


def _parse_published_ports(path: Path) -> tuple[list[tuple[int, str]], list[str], bool]:
    """`(ports, unresolved_tokens, parse_error)` for one compose file.
    `parse_error=True` means the file itself is unparseable (AC-5); a
    per-entry token this module doesn't recognise is silently skipped
    rather than treated as a file-level error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ([], [], True)
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return ([], [], True)
    if doc is None:
        return ([], [], False)
    if not isinstance(doc, dict):
        return ([], [], True)
    services = doc.get("services")
    if services is None:
        return ([], [], False)
    if not isinstance(services, dict):
        return ([], [], True)

    ports: list[tuple[int, str]] = []
    unresolved: list[str] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        raw_ports = svc.get("ports")
        if not isinstance(raw_ports, list):
            continue
        for entry in raw_ports:
            host_token = _extract_host_token(entry)
            if host_token is None:
                continue
            port, resolvable = _resolve_port_token(host_token)
            if resolvable and port is not None:
                ports.append((port, str(svc_name)))
            elif not resolvable:
                unresolved.append(f"{svc_name}:{host_token}")
    return (ports, unresolved, False)


def _port_busy(port: int, *, host: str = "0.0.0.0", timeout: float = 2.0) -> bool:
    """Attempts a transient bind to `(host, port)`; True when the OS refuses
    it (something else already holds it). On Windows a plain wildcard bind
    can succeed beside an existing `127.0.0.1`-only listener (e.g. a
    natively installed Postgres) — a false "free" — so the probe socket sets
    `SO_EXCLUSIVEADDRUSE` before binding, which Windows honours against any
    existing listener on the same port regardless of the address it bound.
    The socket is always closed immediately after — no state survives the
    call."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        exclusive_flag = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_flag is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive_flag, 1)
        sock.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def check_ports(
    repo_root: Path,
    tools: list[str] | tuple[str, ...],
    *,
    port_busy=_port_busy,
) -> tuple[list[Finding], list[str]]:
    """`(findings, unresolved_ports)` — host ports published by every
    `docker-compose*.y[a]ml` / `compose.y[a]ml` in `repo_root`, each tried
    for a bind collision, only when `docker` is in the detected stack. A
    port already bound by something else yields one `port-collision`
    finding (`severity: warn` — Open question default). An unparseable
    compose file yields one `preflight-check-error` and no port findings
    from that file.

    @implements FR-0011:AC-5
    """
    if "docker" not in tools:
        return ([], [])
    findings: list[Finding] = []
    unresolved: list[str] = []
    for path in _compose_files(repo_root):
        ports, file_unresolved, parse_error = _parse_published_ports(path)
        if parse_error:
            findings.append(
                Finding(
                    cls="preflight-check-error",
                    resource=path.name,
                    severity="warn",
                    remedy=(
                        f"fix or remove the unparseable compose file {path.name}; "
                        "no ports were checked from it"
                    ),
                )
            )
            continue
        unresolved.extend(file_unresolved)
        seen: set[int] = set()
        for port, service in ports:
            if port in seen:
                continue
            seen.add(port)
            if port_busy(port):
                findings.append(
                    Finding(
                        cls="port-collision",
                        resource=str(port),
                        severity="warn",
                        remedy=(
                            f"port {port} is already bound on this host; stop the "
                            f"other process or change the published port in "
                            f"{path.name} (service {service!r})"
                        ),
                    )
                )
    return (findings, unresolved)


# ---------------------------------------------------------------------------
# AC-6 / AC-9 / AC-10: orchestrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreflightResult:
    """`run_preflight`'s return: every finding across every check that ran,
    the names of the checks that ran (for the `PREFLIGHT OK` line), and any
    port tokens that could not be resolved (Open question default —
    surfaced, never guessed into a false collision)."""

    findings: tuple[Finding, ...] = ()
    checks_ran: tuple[str, ...] = ()
    unresolved_ports: tuple[str, ...] = ()


def run_preflight(
    repo_root: Path,
    tools: list[str] | tuple[str, ...],
    *,
    find_uv=None,
    timeout: float = DEFAULT_CHECK_TIMEOUT_S,
    budget: float = DEFAULT_BUDGET_S,
    run=subprocess.run,
    which=shutil.which,
    port_busy=_port_busy,
    platform: str = sys.platform,
) -> PreflightResult:
    """Run every check whose stack marker is present, bounded overall by
    `budget` wall-clock seconds. For a repo with no detected stack (`tools`
    empty), no check runs at all and `PreflightResult()` (nothing, no
    checks_ran) is returned unconditionally — the AC-10 no-stack guarantee,
    which is stricter than AC-4's own "runs on Windows" so a no-stack
    project's environment pre-flight output is unaffected by the host OS.

    Never raises: an unexpected exception inside any one check degrades to
    one `preflight-check-error` finding naming that check, and the remaining
    checks still run if the time budget allows.

    @implements FR-0011:AC-6
    @implements FR-0011:AC-9
    @implements FR-0011:AC-10
    """
    tools = list(tools)
    if not tools:
        return PreflightResult()

    findings: list[Finding] = []
    checks_ran: list[str] = []
    unresolved: list[str] = []
    deadline = time.monotonic() + budget

    def _guarded(name: str, fn) -> None:
        if time.monotonic() >= deadline:
            findings.append(
                Finding(
                    cls="preflight-check-error",
                    resource=name,
                    severity="warn",
                    remedy=(
                        "pre-flight's overall time budget was exhausted before "
                        "this check ran; re-run"
                    ),
                )
            )
            return
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a check must never abort the run
            findings.append(
                Finding(
                    cls="preflight-check-error",
                    resource=name,
                    severity="warn",
                    remedy=f"{type(e).__name__} while running the {name} check; re-run or investigate",
                )
            )
        else:
            checks_ran.append(name)

    if "docker" in tools:
        _guarded(
            "docker",
            lambda: findings.extend(
                check_docker(tools, run=run, which=which, timeout=timeout)
            ),
        )

    if any(t in tools for t in CHECKED_TOOLS):
        _guarded(
            "tool-presence",
            lambda: findings.extend(
                check_tool_presence(tools, find_uv=find_uv, which=which)
            ),
        )

    if platform == "win32":
        _guarded(
            "app-control",
            lambda: findings.extend(
                check_app_control(platform=platform, run=run, timeout=timeout)
            ),
        )

    if "docker" in tools:

        def _do_ports() -> None:
            port_findings, port_unresolved = check_ports(
                repo_root, tools, port_busy=port_busy
            )
            findings.extend(port_findings)
            unresolved.extend(port_unresolved)

        _guarded("ports", _do_ports)

    return PreflightResult(
        findings=tuple(findings),
        checks_ran=tuple(checks_ran),
        unresolved_ports=tuple(unresolved),
    )
