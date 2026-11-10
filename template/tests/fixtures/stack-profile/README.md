# stack-profile fixtures (FR-0010)

Synthetic marker-file trees for `detect_stack` (AC-1/AC-2) and two tiny
uv-managed projects for `ensure_dev_venv` (AC-8/AC-9/AC-10). Nothing here is
copied from a real project; every file is hand-written and minimal — only the
fields/markers the detector or the venv provisioner actually reads.

## `trees/` — `detect_stack(repo_root)` fixtures (AC-1/AC-2)

Each subdirectory is a `repo_root` candidate. No subdirectory contains more
than the markers its name promises.

- `empty/` — no markers at all; `detect_stack` returns `[]`.
- `no-stack/` — AC-12's "a project that declares no stack" fixture. Same
  shape as `empty/`, kept as a separate, intention-revealing name for tests
  that assert byte-identical-to-today behaviour rather than empty detection.
- `python-only/` — `pyproject.toml` only -> `["python"]`.
- `uv-python/` — `pyproject.toml` + `uv.lock` -> `["python", "uv"]`.
- `node-only/` — `package.json` only -> `["node", "npm", "npx"]`.
- `python-node-compose/` — `pyproject.toml` + `package.json` +
  `docker-compose.yml` -> `["docker", "node", "npm", "npx", "python"]`.
- `unparseable-pyproject/` — a `pyproject.toml` that is not valid TOML.
  `detect_stack` never parses it (presence-only check), so this must still
  yield `["python"]` with no error.
- `adr-accepted-stack-tools/` — `specs/decisions/ADR-0001-stack.md`,
  `status: accepted`, `stack_tools: [uv, docker, kubectl]`. `kubectl` is
  outside the closed vocabulary, so this exercises the one-WARN-per-entry
  path alongside the two recognised ids.
- `adr-proposed-stack-tools/` — the same declaration but `status: proposed`;
  contributes nothing (AC-2: only `accepted` ADRs count).
- `adr-malformed-stack-tools/` — `stack_tools: "docker"` (a string, not a
  list); ignored with one WARN naming the ADR, per AC-2.

## `venv-provision/` — `ensure_dev_venv` fixtures (AC-8/AC-9/AC-10)

- `lock-project/` — a minimal `pyproject.toml` + `uv.lock` declaring one
  tiny pure-Python dependency, for the lock-sync branch. The Reviewer's
  dogfood step is expected to regenerate `uv.lock` in a throwaway copy
  (`uv lock`) rather than trust this committed one to stay resolvable
  forever; it is checked in only so the *shape* (a real two-file uv
  project) is version-controlled.
- `requirements-project/` — a minimal `requirements.txt` (no `uv.lock`),
  for the requirements-install branch.
