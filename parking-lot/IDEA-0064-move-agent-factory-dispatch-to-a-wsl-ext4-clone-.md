---
id: IDEA-0064
title: Move agent-factory dispatch to a WSL ext4 clone; keep Windows for CoS and UI
  review; Tailscale remote access
status: parked
tags:
- wsl
- environment
- dispatch
- tooling
- remote-access
- tailscale
- developer-experience
size: M
created: '2026-09-20'
updated: '2026-09-20'
last_reviewed: '2026-09-20'
promoted_to: null
pattern: null
archive_reason: null
---

# IDEA-0064: Move agent-factory dispatch to a WSL ext4 clone; keep Windows for CoS and UI review; Tailscale remote access

## Description

Run dispatched agent work (Project A today, any bootstrapped project later) from a hub clone on WSL2 Ubuntu ext4, keep the Windows checkout for Chief of Staff triage, connectors, and browser-pane UI review, sync the two through GitHub (submodule bumps are the pass-through), and reach the PC from the laptop over Tailscale with SSH into WSL plus RustDesk for the desktop. Full checklist in Notes.

## Originating context

Measured 2026-09-20 during a /cos evaluation: native Windows 105 s vs WSL /mnt/c 56 s vs WSL ext4 28 s for template pytest; git status 0.1 s vs 3.0 s vs 0.007 s. WSL Ubuntu 24.04 already present with systemd, docker, python 3.12, node 18, stale claude 2.1.114; missing gh, uv, ruff, pytest, ssh keys. Desktop-app WSL sessions lack terminal, browser pane, and connectors, hence the split. Windows 11 Home cannot host RDP, hence RustDesk. Related: IDEA-0028, IDEA-0063, IDEA-0061.

## Value hypothesis

Cuts the deploy gate and every dispatched agent's self-verification from 105 s to 28 s on the 637-test template suite (3.7x), unlocks the Bash sandbox for autonomous worktree agents (WSL/Linux only), and removes the native python3 stub, cp1252, and CRLF failure modes from the agent path, for roughly one sitting of setup and no hub code changes.

## Notes

- Imported 2026-10-23 from a separate hub snapshot (was IDEA-0046 there). Personal-project names generalised.

### Target shape

- WSL clone on ext4 (`~/code/cos-agent-hub-main`) is the write side for dispatched projects. Never run from `/mnt/c` (2x slower tests, 30x slower git status).
- Windows checkout stays the write side for hub-level triage (parking lot, patterns, projects.yaml, /promote) and is read-only for UI projects under review.
- GitHub is the sync bus. The hub commit pins the downstream projects, so the pass-through from a WSL merge to the Windows hub index is: bump submodule pointer, push, `git pull --recurse-submodules` on the other side. One write side per project at a time.
- Fix IDEA-0063 before the Windows side commits generated indexes, or commit indexes only from WSL.

### WSL setup (one sitting)

1. `sudo apt install python-is-python3 bubblewrap socat` (template hooks call `python`; sandbox needs the other two).
2. Install Linux gh, uv, ruff, pytest; `gh auth login`; ssh keys or HTTPS token for GitHub.
3. `claude update` (WSL copy is 2.1.114 vs 2.1.278 native). Login opens the browser on the wrong host: paste the code, or set `BROWSER` to Windows Chrome.
4. Copy user settings (model, effort, fullscreen) into WSL `~/.claude/settings.json`; auth, memory, and history are per OS. Optionally copy the project memory dir into the WSL-path-keyed folder.
5. Set `appendWindowsPath=false` in `/etc/wsl.conf` (or ensure Linux binaries win) so `shutil.which("claude")`/`uv` in dispatch.py never picks up a Windows .exe.
6. Run `/sandbox` in a session to verify; Ubuntu 24.04 AppArmor may need the profile from the sandboxing docs.
7. Clone hub with submodules; `hub/projects.local.yaml` overlay re-pointed; confirm Project A phipa hook fires.
8. Keep WSL alive: `vmIdleTimeout=-1` in `.wslconfig` plus a logon scheduled task that starts the distro.

### Remote access (Tailscale)

- Windows 11 Home cannot host RDP. Use RustDesk for the desktop (browser pane, UI review); install as a service for unattended access and lock-screen/UAC visibility; set a permanent password. Over the tailnet, enable direct IP access in RustDesk and skip the relay; a self-hosted hbbs/hbbr is only needed for peers off the tailnet.
- Install Tailscale inside WSL as its own node with `tailscale up --ssh` (systemd already on). SSH into the WSL clone directly; the Windows host does not forward tailnet traffic to WSL by default.
- Windows Tailscale client: enable unattended mode; disable key expiry on the desktop node in the admin console; MFA on the identity provider.
- Power: never sleep while plugged in; Code tab keep-awake for long runs. Wake-on-LAN does not traverse Tailscale.
- Run Claude Code inside tmux/zellij over SSH so dispatch waves survive venue Wi-Fi drops. Remote Control (already on at startup) covers steering from laptop/phone without SSH.
- `tailscale serve <port>` on the host publishes a WSL dev server (visible on Windows localhost) to the tailnet over HTTPS for UI preview on the laptop. Avoid Funnel unless public sharing is intended.
- DERP relay fallback when venues block UDP: terminal fine, screen share degraded; test the venue first.
- SSH sessions into WSL and desktop-app sessions on the Windows login cannot see each other; decide which owns the work before a session.

### Related

IDEA-0028 (cp1252), IDEA-0063 (CRLF indexes), IDEA-0061 (hub-tooling cannot use dispatch waves yet, so the near-term win is Project A and new bootstraps), IDEA-0031/0032 (dispatch harness issues WSL does not fix).
